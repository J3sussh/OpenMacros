"""Serviço D-Bus falso que implementa o contrato io.github.clique.Manager1 (para testes da GUI)."""

import json
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

XML = """
<node><interface name="io.github.clique.Manager1">
  <method name="GetDevices"><arg type="s" direction="out"/></method>
  <method name="GetDevice"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
  <method name="SetAssignment"><arg type="s" direction="in"/><arg type="q" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="SetSetting"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="ChangeHost"><arg type="s" direction="in"/><arg type="y" direction="in"/><arg type="b" direction="out"/></method>
  <method name="ResetDevice"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="Rescan"/>
  <method name="GetActiveApp"><arg type="s" direction="out"/></method>
  <method name="GetRecentApps"><arg type="s" direction="out"/></method>
  <method name="SetProfileAssignment"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="q" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="SetProfileSetting"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="RemoveProfile"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="GetSmartActions"><arg type="s" direction="out"/></method>
  <method name="SaveSmartAction"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
  <method name="DeleteSmartAction"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="RunAction"><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="DebugSetActiveApp"><arg type="s" direction="in"/></method>
  <signal name="ActiveAppChanged"><arg type="s"/></signal>
  <signal name="SmartActionsChanged"/>
  <signal name="DevicesChanged"/>
  <signal name="DeviceUpdated"><arg type="s"/><arg type="s"/></signal>
  <signal name="Error"><arg type="s"/><arg type="s"/></signal>
</interface></node>"""

M720 = {
    "id": "046d:405e:ABCD1234", "name": "M720 Triathlon", "model_id": "405e", "kind": "mouse",
    "connection": "receiver", "online": True,
    "battery": {"level": 80, "status": "discharging", "approximate": True},
    "features": ["0x0000", "0x0001", "0x1b04", "0x2121", "0x2205", "0x1814"],
    "controls": [
        {"cid": 80, "name": "Botão esquerdo", "remappable": False, "divertable": False, "raw_xy": False},
        {"cid": 82, "name": "Roda (clique)", "remappable": True, "divertable": True, "raw_xy": False},
        {"cid": 83, "name": "Voltar", "remappable": True, "divertable": True, "raw_xy": False},
        {"cid": 86, "name": "Avançar", "remappable": True, "divertable": True, "raw_xy": False},
        {"cid": 91, "name": "Roda para a esquerda", "remappable": True, "divertable": True, "raw_xy": False},
        {"cid": 93, "name": "Roda para a direita", "remappable": True, "divertable": True, "raw_xy": False},
        {"cid": 208, "name": "Botão de gestos", "remappable": True, "divertable": True, "raw_xy": True},
    ],
    "settings": {
        "pointer_speed": {"value": 256, "min": 1, "max": 512},
        "hires_scroll": {"value": True}, "scroll_invert": {"value": False},
    },
    "hosts": {"count": 3, "current": 0, "names": ["BSIT-0661", "Hackbook", "HY300"]},
    "assignments": {"83": {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]},
                    "208": {"type": "gestures", "click": {"type": "default"}, "up": {"type": "disabled"},
                            "down": {"type": "default"}, "left": {"type": "default"},
                            "right": {"type": "default"}, "threshold": 50}},
    "layout": "m720",
    "profiles": {"firefox": {"assignments": {"91": {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_PAGEUP"]}},
                             "settings": {"scroll_invert": {"value": True}}}},
    "active_profile": "",
}
KEYBOARD = {
    "id": "046d:b35b:KB1", "name": "MX Keys (offline)", "model_id": "b35b", "kind": "keyboard",
    "connection": "bluetooth", "online": False, "battery": {"level": 20, "status": "charging", "approximate": False},
    "features": ["0x0000"], "controls": [
        {"cid": 200, "name": "Tecla F1", "remappable": True, "divertable": True, "raw_xy": False},
        {"cid": 201, "name": "Tecla F2", "remappable": True, "divertable": True, "raw_xy": False},
        {"cid": 202, "name": "Tecla F3", "remappable": True, "divertable": True, "raw_xy": False}],
    "settings": {"dpi": {"value": 800, "choices": [400, 800]}, "smartshift": {"enabled": True, "threshold": 30}},
    "hosts": {"count": 3, "current": 1}, "assignments": {}, "layout": "generic-keyboard",
    "profiles": {}, "active_profile": "",
}


class FakeService:
    def __init__(self, bus_type=Gio.BusType.SESSION):
        self.devices = {d["id"]: json.loads(json.dumps(d)) for d in (M720, KEYBOARD)}
        self.calls: list[tuple] = []
        self.active_app = {"app_id": "", "wm_class": [], "title": "", "pid": 0, "exe": ""}
        self.recent = [{"app_id": "firefox", "wm_class": ["Navigator", "firefox"], "title": "Mozilla Firefox", "pid": 1, "exe": "firefox-esr"},
                       {"app_id": "xfce4-terminal", "wm_class": ["xfce4-terminal", "Xfce4-terminal"], "title": "Terminal", "pid": 2, "exe": "xfce4-terminal"}]
        self.smart = {"sa_demo01": {"name": "Começar o dia", "icon": "weather-clear-symbolic",
                                    "steps": [{"type": "open", "target": "https://example.org"}, {"type": "delay", "ms": 500},
                                              {"type": "media", "op": "play_pause"}]}}
        self.conn = None
        self.owner = Gio.bus_own_name(bus_type, "io.github.clique", Gio.BusNameOwnerFlags.NONE,
                                      self._bus_acquired, None, None)

    def _bus_acquired(self, conn, name):
        self.conn = conn
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        conn.register_object("/io/github/clique", info.interfaces[0], self._call, None, None)

    def stop(self):
        Gio.bus_unown_name(self.owner)

    def emit(self, signal, params):
        self.conn.emit_signal(None, "/io/github/clique", "io.github.clique.Manager1", signal, params)

    def _dev(self, inv, dev_id):
        if dev_id not in self.devices:
            inv.return_dbus_error("io.github.clique.Error.NotFound", dev_id)
            return None
        return self.devices[dev_id]

    def _call(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        self.calls.append((method, args))
        if method == "GetDevices":
            inv.return_value(GLib.Variant("(s)", (json.dumps(list(self.devices.values())),)))
        elif method == "Rescan":
            inv.return_value(None)
        elif method in ("GetActiveApp", "GetRecentApps", "GetSmartActions", "SaveSmartAction",
                        "DeleteSmartAction", "RunAction", "DebugSetActiveApp"):
            self._extra(inv, method, args)
        elif method in ("SetProfileAssignment", "SetProfileSetting", "RemoveProfile"):
            self._profile(inv, method, args)
        else:
            dev = self._dev(inv, args[0])
            if dev is None:
                return
            if method == "GetDevice":
                inv.return_value(GLib.Variant("(s)", (json.dumps(dev),)))
                return
            if not dev["online"]:
                inv.return_dbus_error("io.github.clique.Error.DeviceOffline", "offline")
                return
            if method == "SetAssignment":
                dev["assignments"][str(args[1])] = json.loads(args[2])
            elif method == "SetSetting":
                key, val = args[1], json.loads(args[2])
                if key == "smartshift":
                    dev["settings"][key] = val
                elif key in dev["settings"]:
                    dev["settings"][key]["value"] = val
            elif method == "ChangeHost":
                dev["hosts"]["current"] = args[1]
            elif method == "ResetDevice":
                dev["assignments"] = {}
            inv.return_value(GLib.Variant("(b)", (True,)))
            self.emit("DeviceUpdated", GLib.Variant("(ss)", (dev["id"], json.dumps(dev))))


def _profile_active(dev, app):
    return app if app in dev.get("profiles", {}) else ""


FakeService._extra = None


def _extra(self, inv, method, args):
    if method == "GetActiveApp":
        inv.return_value(GLib.Variant("(s)", (json.dumps(self.active_app),)))
    elif method == "GetRecentApps":
        inv.return_value(GLib.Variant("(s)", (json.dumps(self.recent),)))
    elif method == "GetSmartActions":
        inv.return_value(GLib.Variant("(s)", (json.dumps(self.smart),)))
    elif method == "SaveSmartAction":
        sa = json.loads(args[0])
        sid = sa.pop("id", None) or "sa_%06x" % (len(self.smart) + 0xab12cd)
        self.smart[sid] = sa
        inv.return_value(GLib.Variant("(s)", (sid,)))
        self.emit("SmartActionsChanged", None)
    elif method == "DeleteSmartAction":
        ok = self.smart.pop(args[0], None) is not None
        inv.return_value(GLib.Variant("(b)", (ok,)))
        self.emit("SmartActionsChanged", None)
    elif method == "RunAction":
        json.loads(args[0])
        inv.return_value(GLib.Variant("(b)", (True,)))
    elif method == "DebugSetActiveApp":
        app = {"app_id": args[0], "wm_class": [args[0]], "title": args[0], "pid": 99, "exe": args[0]}
        self.active_app = app
        for dev in self.devices.values():
            dev["active_profile"] = _profile_active(dev, args[0])
        inv.return_value(None)
        self.emit("ActiveAppChanged", GLib.Variant("(s)", (json.dumps(app),)))
        for dev in self.devices.values():
            self.emit("DeviceUpdated", GLib.Variant("(ss)", (dev["id"], json.dumps(dev))))


def _profile(self, inv, method, args):
    dev = self._dev(inv, args[0])
    if dev is None:
        return
    app = args[1]
    profiles = dev.setdefault("profiles", {})
    if method == "SetProfileAssignment":
        action = json.loads(args[3])
        if not app:
            dev["assignments"][str(args[2])] = action
        else:
            prof = profiles.setdefault(app, {"assignments": {}, "settings": {}})
            if action is None:
                prof["assignments"].pop(str(args[2]), None)
            else:
                prof["assignments"][str(args[2])] = action
    elif method == "SetProfileSetting":
        value = json.loads(args[3])
        if not app:
            dev["settings"].setdefault(args[2], {}).update(value if isinstance(value, dict) else {"value": value})
        else:
            prof = profiles.setdefault(app, {"assignments": {}, "settings": {}})
            if value is None:
                prof["settings"].pop(args[2], None)
            else:
                prof["settings"][args[2]] = value if isinstance(value, dict) else {"value": value}
    elif method == "RemoveProfile":
        if profiles.pop(app, None) is None:
            inv.return_dbus_error("io.github.clique.Error.NotFound", app)
            return
    dev["active_profile"] = _profile_active(dev, self.active_app["app_id"])
    inv.return_value(GLib.Variant("(b)", (True,)))
    self.emit("DeviceUpdated", GLib.Variant("(ss)", (dev["id"], json.dumps(dev))))


FakeService._extra = _extra
FakeService._profile = _profile


def main():
    FakeService()
    print("fake service ready", file=sys.stderr, flush=True)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
