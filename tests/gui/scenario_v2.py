"""dbus-run-session: membros v2 (preferências, backup, sinais) no cliente da GUI e no cliente da bandeja.
Modo `new` (padrão) ou `old` (daemon sem os membros: UnknownMethod => UNSUPPORTED)."""

import json
import sys

from gi.repository import GLib

from openmacros.gui.dbus_client import OpenMacrosClient, is_unsupported
from openmacros.tray.client import TrayClient
from fake_service import FakeService

mode = sys.argv[1] if len(sys.argv) > 1 else "new"
loop = GLib.MainLoop()
client = OpenMacrosClient()
fail, log = [], {"prefs": [], "actions": [], "tray": 0}


def check(cond, msg):
    if not cond:
        fail.append(msg)


def s1(prefs, err):
    if mode == "old":
        check(prefs is None and is_unsupported(err), f"old: {prefs} {err}")
        client.export_config(lambda t, e: (check(is_unsupported(e), f"old export {e}"), loop.quit()))
        return
    check(err is None and prefs["battery_threshold"] == 15, f"get_preferences {prefs} {err}")
    client.set_preference("battery_threshold", 30, s2)


def s2(ok, err):
    check(ok is True, f"set_preference {err}")
    client.set_preference("battery_threshold", "x", s3)


def s3(ok, err):
    check(ok is None and err and "Valor inválido" in err, f"valor inválido: {ok} {err}")
    client.export_config(s4)


def s4(text, err):
    data = json.loads(text)
    check(data.get("openmacros_export") == 1, f"export {text}")
    client.import_config(text, True, s5)


def s5(ok, err):
    check(ok is True, f"import {err}")
    service.emit("ActionTriggered", GLib.Variant("(sqs)", ("gesture", 208, "Gesto ↑ — Nova aba")))
    GLib.timeout_add(500, lambda: (loop.quit(), False)[1])


def on_avail(_c, available):
    if available:
        client.get_preferences(s1)


service = FakeService(v2=(mode == "new"))
client.connect("availability-changed", on_avail)
client.connect("preferences-changed", lambda _c, p: log["prefs"].append(p))
client.connect("action-triggered", lambda _c, i, cid, label: log["actions"].append((i, cid, label)))
tray = TrayClient(lambda: log.__setitem__("tray", log["tray"] + 1))
GLib.timeout_add(300, lambda: (client.start(), tray.start(), False)[2])
GLib.timeout_add(15000, lambda: (fail.append("timeout"), loop.quit()))
loop.run()
if mode == "new":
    check(log["prefs"] and log["prefs"][-1]["battery_threshold"] == 30, "sinal PreferencesChanged")
    check(log["actions"] == [("gesture", 208, "Gesto ↑ — Nova aba")], f"ActionTriggered {log['actions']}")
check(tray.devices is not None and len(tray.devices) == 2, f"tray devices {tray.devices}")
check(tray.active_app is not None, "tray active_app")
if fail:
    print("FAIL", fail)
    sys.exit(1)
print("SCENARIO OK")
