"""Executado dentro do dbus-run-session: sobe o serviço falso e exercita o CliqueClient."""

import json
import sys

from gi.repository import GLib

from clique.gui.dbus_client import CliqueClient
from fake_service import FakeService

loop = GLib.MainLoop()
client = CliqueClient()
log = {"signals": []}
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


def finish():
    loop.quit()
    return False


def step_devices(devs, err):
    check(err is None and len(devs) == 2, f"get_devices: {devs} {err}")
    client.set_assignment(devs[0]["id"], 82, {"type": "disabled"}, step_assign)


def step_assign(ok, err):
    check(ok is True and err is None, f"set_assignment {ok} {err}")
    client.set_setting("046d:b35b:KB1", "dpi", 400, step_offline)


def step_offline(ok, err):
    check(ok is None and err and "offline" in err, f"offline esperado: {ok} {err}")
    client.get_device("nope", step_notfound)


def step_notfound(dev, err):
    check(dev is None and err and "não encontrado" in err, f"notfound: {err}")
    client.change_host("046d:405e:ABCD1234", 2, step_host)


M = "046d:405e:ABCD1234"


def step_host(ok, err):
    check(ok is True, f"change_host {err}")
    client.set_profile_assignment(M, "code", 83, {"type": "disabled"}, step_prof1)


def step_prof1(ok, err):
    check(ok is True, f"set_profile_assignment {err}")
    client.set_profile_setting(M, "code", "scroll_invert", True, step_prof2)


def step_prof2(ok, err):
    check(ok is True, f"set_profile_setting {err}")
    client.set_profile_assignment(M, "code", 83, None, step_prof3)


def step_prof3(ok, err):
    check(ok is True, f"remover sobreposição (null) {err}")
    client.get_device(M, step_prof4)


def step_prof4(dev, err):
    check(dev and "83" not in dev["profiles"]["code"]["assignments"], f"perfil: {dev}")
    check(dev["profiles"]["code"]["settings"]["scroll_invert"] == {"value": True}, "setting do perfil")
    client.remove_profile(M, "code", step_rm)


def step_rm(ok, err):
    check(ok is True, f"remove_profile {err}")
    client.remove_profile(M, "code", step_rm2)


def step_rm2(ok, err):
    check(ok is None and err and "não encontrado" in err, f"remove 2x: {ok} {err}")
    client.save_smart_action({"name": "T", "icon": "x", "steps": [{"type": "delay", "ms": 100}]}, step_sa1)


def step_sa1(sid, err):
    check(sid and err is None, f"save_smart_action {sid} {err}")
    log["sid"] = sid
    client.get_smart_actions(step_sa2)


def step_sa2(sas, err):
    check(sas and log["sid"] in sas and "sa_demo01" in sas, f"get_smart_actions {sas}")
    client.run_action({"type": "smart_action", "id": log["sid"]}, step_run)


def step_run(ok, err):
    check(ok is True, f"run_action {err}")
    client.delete_smart_action(log["sid"], step_del)


def step_del(ok, err):
    check(ok is True, f"delete_smart_action {err}")
    client.get_recent_apps(step_recent)


def step_recent(apps, err):
    check(apps and apps[0]["app_id"] == "firefox", f"recent {apps}")
    client.get_active_app(step_active)


def step_active(app, err):
    check(app is not None and "app_id" in app, f"active {app}")
    from gi.repository import Gio
    Gio.bus_get_sync(Gio.BusType.SESSION).call(
        "io.github.clique", "/io/github/clique", "io.github.clique.Manager1", "DebugSetActiveApp",
        GLib.Variant("(s)", ("firefox",)), None, Gio.DBusCallFlags.NONE, 3000, None, None)
    GLib.timeout_add(500, finish)


def on_avail(_c, available):
    if available:
        client.get_devices(step_devices)


client.connect("availability-changed", on_avail)
client.connect("active-app-changed", lambda _c, a: log.setdefault("apps", []).append(a))
client.connect("smart-actions-changed", lambda _c: log.setdefault("sa_signals", []).append(1))
client.connect("device-updated", lambda _c, i, d: log["signals"].append((i, d)))
service = FakeService()
GLib.timeout_add(500, lambda: client.start() or False)
GLib.timeout_add(15000, lambda: (fail.append("timeout"), loop.quit()))
loop.run()
check(any(d["assignments"].get("82") == {"type": "disabled"} for _, d in log["signals"]), "sinal DeviceUpdated")
check(log.get("apps") and log["apps"][-1]["app_id"] == "firefox", "sinal ActiveAppChanged")
check(len(log.get("sa_signals", [])) >= 2, "sinal SmartActionsChanged")
check(any(d["active_profile"] == "firefox" for _, d in log["signals"]), "active_profile no DeviceUpdated")
check(any(d["hosts"]["current"] == 2 for _, d in log["signals"]), "sinal host")
if fail:
    print("FAIL", fail)
    sys.exit(1)
print("SCENARIO OK")
