"""Executado dentro de `dbus-run-session`: sobe cliqued em modo fake e fala com ele por D-Bus."""
import json
import os
import subprocess
import sys
import time

from gi.repository import Gio, GLib

env = dict(os.environ, CLIQUE_FAKE="1", PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "src"))
proc = subprocess.Popen([sys.executable, "-m", "clique.daemon.main"], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = None
    for _ in range(100):
        try:
            proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None, "io.github.clique",
                                           "/io/github/clique", "io.github.clique.Manager1", None)
            if proxy.get_name_owner():
                break
        except GLib.Error:
            pass
        time.sleep(0.1)
    assert proxy and proxy.get_name_owner(), "serviço não subiu"

    signals = []
    proxy.connect("g-signal", lambda p, sender, name, params: signals.append((name, params.unpack())))

    def call(method, args=None):
        return proxy.call_sync(method, args, Gio.DBusCallFlags.NONE, 5000, None).unpack()

    devs = json.loads(call("GetDevices")[0])
    assert len(devs) == 2, devs
    m720 = next(d for d in devs if d["name"] == "M720 Triathlon")
    did = m720["id"]

    act = json.dumps({"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]})
    assert call("SetAssignment", GLib.Variant("(sqs)", (did, 82, act))) == (True,)
    assert call("SetSetting", GLib.Variant("(sss)", (did, "pointer_speed", "300"))) == (True,)
    assert call("ChangeHost", GLib.Variant("(sy)", (did, 2))) == (True,)
    d = json.loads(call("GetDevice", GLib.Variant("(s)", (did,)))[0])
    assert d["assignments"]["82"]["keys"] == ["KEY_LEFTCTRL", "KEY_C"]
    assert d["settings"]["pointer_speed"]["value"] == 300 and d["hosts"]["current"] == 2

    ctx = GLib.MainContext.default()
    for _ in range(20):
        while ctx.iteration(False):
            pass
        time.sleep(0.02)
    names = [n for n, _ in signals]
    assert names.count("DeviceUpdated") >= 3, names

    try:
        call("SetSetting", GLib.Variant("(sss)", (did, "dpi", "800")))
        raise SystemExit("deveria falhar")
    except GLib.Error as e:
        assert "io.github.clique.Error.Unsupported" in e.message, e.message
    try:
        call("GetDevice", GLib.Variant("(s)", ("nope",)))
        raise SystemExit("deveria falhar")
    except GLib.Error as e:
        assert "io.github.clique.Error.NotFound" in e.message, e.message
    call("Rescan")

    # --- integrações ---
    assert json.loads(call("GetActiveApp")[0])["app_id"] == ""
    ga = GLib.Variant("(sqs)", (did, 83, json.dumps({"type": "keys", "keys": ["KEY_A"]})))
    pa = GLib.Variant("(ssqs)", (did, "firefox", 83, json.dumps({"type": "keys", "keys": ["KEY_B"]})))
    assert call("SetProfileAssignment", pa) == (True,)
    assert call("SetProfileSetting", GLib.Variant("(ssss)", (did, "firefox", "scroll_invert", "true"))) == (True,)
    d = json.loads(call("GetDevice", GLib.Variant("(s)", (did,)))[0])
    assert d["profiles"]["firefox"]["assignments"]["83"]["keys"] == ["KEY_B"] and d["active_profile"] == ""
    call("DebugSetActiveApp", GLib.Variant("(s)", ("firefox",)))
    d = json.loads(call("GetDevice", GLib.Variant("(s)", (did,)))[0])
    assert d["active_profile"] == "firefox"
    assert json.loads(call("GetActiveApp")[0])["app_id"] == "firefox"
    assert json.loads(call("GetRecentApps")[0])[0]["app_id"] == "firefox"
    sid = call("SaveSmartAction", GLib.Variant("(s)", (json.dumps(
        {"name": "t", "steps": [{"type": "volume", "op": "mute"}]}),)))[0]
    assert sid in json.loads(call("GetSmartActions")[0])
    assert call("RunAction", GLib.Variant("(s)", (json.dumps({"type": "smart_action", "id": sid}),))) == (True,)
    assert call("DeleteSmartAction", GLib.Variant("(s)", (sid,))) == (True,)
    assert call("RemoveProfile", GLib.Variant("(ss)", (did, "firefox"))) == (True,)
    try:
        call("RunAction", GLib.Variant("(s)", (json.dumps({"type": "gestures"}),)))
        raise SystemExit("deveria falhar")
    except GLib.Error as e:
        assert "InvalidArgument" in e.message, e.message
    for _ in range(20):
        while ctx.iteration(False):
            pass
        time.sleep(0.02)
    names = [n for n, _ in signals]
    assert "ActiveAppChanged" in names and names.count("SmartActionsChanged") >= 2, names
    print("OK")
finally:
    proc.terminate()
    proc.wait(5)
