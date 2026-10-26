"""Executado dentro de `dbus-run-session`: sobe openmacrosd em modo fake e fala com ele por D-Bus."""
import json
import os
import subprocess
import sys
import time

from gi.repository import Gio, GLib

env = dict(os.environ, OPENMACROS_FAKE="1", PYTHONPATH=os.path.join(os.path.dirname(__file__), "..", "src"))
proc = subprocess.Popen([sys.executable, "-m", "openmacros.daemon.main"], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    proxy = None
    for _ in range(100):
        try:
            proxy = Gio.DBusProxy.new_sync(bus, Gio.DBusProxyFlags.NONE, None, "io.github.openmacros",
                                           "/io/github/openmacros", "io.github.openmacros.Manager1", None)
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
        assert "io.github.openmacros.Error.Unsupported" in e.message, e.message
    try:
        call("GetDevice", GLib.Variant("(s)", ("nope",)))
        raise SystemExit("deveria falhar")
    except GLib.Error as e:
        assert "io.github.openmacros.Error.NotFound" in e.message, e.message
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
    saved = json.loads(call("SaveSmartAction", GLib.Variant("(s)", (json.dumps(
        {"name": "t", "steps": [{"type": "volume", "op": "mute"}]}),)))[0])
    sid = saved["id"]
    assert saved["warnings"] == []
    sas = json.loads(call("GetSmartActions")[0])
    assert sid in sas and sas[sid]["enabled"] is True and sas[sid]["trigger_errors"] == []
    assert sas[sid]["stats"]["runs"] == 0 and sas[sid]["triggers"] == []
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
    # --- v2 / B ---
    prefs = json.loads(call("GetPreferences")[0])
    assert prefs["battery_threshold"] == 15 and prefs["ai_delivery_default"] == "clipboard", prefs
    assert call("SetPreference", GLib.Variant("(ss)", ("battery_threshold", "30"))) == (True,)
    try:
        call("SetPreference", GLib.Variant("(ss)", ("battery_threshold", "3")))
        raise SystemExit("deveria falhar")
    except GLib.Error as e:
        assert "InvalidArgument" in e.message, e.message
    pa = GLib.Variant("(ssqs)", (did, "code", 83, json.dumps({"type": "keys", "keys": ["KEY_B"]})))
    assert call("SetProfileAssignment", pa) == (True,)
    exported = call("ExportConfig")[0]
    ex = json.loads(exported)
    assert ex["openmacros_export"] == 1 and ex["preferences"]["battery_threshold"] == 30
    assert "code" in ex["devices"][did]["profiles"]
    # perfil vazio some (B4)
    null_pa = GLib.Variant("(ssqs)", (did, "code", 83, "null"))
    assert call("SetProfileAssignment", null_pa) == (True,)
    d = json.loads(call("GetDevice", GLib.Variant("(s)", (did,)))[0])
    assert "code" not in d["profiles"], d["profiles"]
    # importar de volta (merge) traz o perfil de volta
    assert call("ImportConfig", GLib.Variant("(sb)", (exported, True))) == (True,)
    d = json.loads(call("GetDevice", GLib.Variant("(s)", (did,)))[0])
    assert "code" in d["profiles"]
    try:
        call("ImportConfig", GLib.Variant("(sb)", ('{"openmacros_export": 9}', False)))
        raise SystemExit("deveria falhar")
    except GLib.Error as e:
        assert "InvalidArgument" in e.message, e.message
    for _ in range(20):
        while ctx.iteration(False):
            pass
        time.sleep(0.02)
    names = [n for n, _ in signals]
    assert "PreferencesChanged" in names, names
    # --- Smart Actions v2: gatilhos, ativar/desativar, exportar/importar ---
    trig_sa = {"name": "Ao abrir o Burp", "description": "teste", "triggers": [
        {"type": "app", "event": "open", "app_id": "burp"},
        {"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_P"]}],
        "steps": [{"type": "volume", "op": "mute"}]}
    r = json.loads(call("SaveSmartAction", GLib.Variant("(s)", (json.dumps(trig_sa),)))[0])
    tid = r["id"]
    signals.clear()
    call("DebugSetActiveApp", GLib.Variant("(s)", ("burp",)))
    for _ in range(20):
        while ctx.iteration(False):
            pass
        time.sleep(0.02)
    trig = [a for n, a in signals if n == "SmartActionTriggered"]
    assert trig and trig[0][0] == tid and json.loads(trig[0][1])["event"] == "open", signals
    assert [a for a in json.loads(call("GetRunningApps")[0]) if a["app_id"] == "burp"]
    assert json.loads(call("GetSmartActions")[0])[tid]["stats"]["runs"] == 1
    assert call("SetSmartActionEnabled", GLib.Variant("(sb)", (tid, False))) == (True,)
    assert json.loads(call("GetSmartActions")[0])[tid]["enabled"] is False
    exp = json.loads(call("ExportSmartAction", GLib.Variant("(s)", (tid,)))[0])
    assert exp["openmacros_smart_action"] == 1 and "id" not in exp and "stats" not in exp
    nid = call("ImportSmartAction", GLib.Variant("(s)", (json.dumps(exp),)))[0]
    assert nid != tid and nid in json.loads(call("GetSmartActions")[0])
    for bad in ("{}", '{"openmacros_smart_action": 1, "name": "x", "steps": []}'):
        try:
            call("ImportSmartAction", GLib.Variant("(s)", (bad,)))
            raise SystemExit("deveria falhar")
        except GLib.Error as e:
            assert "InvalidArgument" in e.message, e.message
    try:
        call("SetSmartActionEnabled", GLib.Variant("(sb)", ("sa_nope", True)))
        raise SystemExit("deveria falhar")
    except GLib.Error as e:
        assert "NotFound" in e.message, e.message
    print("OK")
finally:
    proc.terminate()
    proc.wait(5)
