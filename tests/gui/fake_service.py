"""Serviço D-Bus falso que implementa o contrato io.github.openmacros.Manager1 (para testes da GUI)."""

import json
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

XML = """
<node><interface name="io.github.openmacros.Manager1">
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
  <method name="SetSmartActionEnabled"><arg type="s" direction="in"/><arg type="b" direction="in"/><arg type="b" direction="out"/></method>
  <method name="ExportSmartAction"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
  <method name="ImportSmartAction"><arg type="s" direction="in"/><arg type="s" direction="out"/></method>
  <method name="GetRunningApps"><arg type="s" direction="out"/></method>
  <method name="GetPreferences"><arg type="s" direction="out"/></method>
  <method name="SetPreference"><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="b" direction="out"/></method>
  <method name="ExportConfig"><arg type="s" direction="out"/></method>
  <method name="ImportConfig"><arg type="s" direction="in"/><arg type="b" direction="in"/><arg type="b" direction="out"/></method>
  <method name="DebugSetActiveApp"><arg type="s" direction="in"/></method>
  <signal name="ActiveAppChanged"><arg type="s"/></signal>
  <signal name="SmartActionsChanged"/>
  <signal name="SmartActionTriggered"><arg type="s"/><arg type="s"/></signal>
  <signal name="PreferencesChanged"><arg type="s"/></signal>
  <signal name="ActionTriggered"><arg type="s"/><arg type="q"/><arg type="s"/></signal>
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
    "hosts": {"count": 3, "current": 0, "names": ["Desktop", "Laptop", "Tablet"]},
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
    def __init__(self, bus_type=Gio.BusType.SESSION, v2=True, sa2=True):
        self.v2 = v2  # False simula um daemon antigo (UnknownMethod nos membros novos)
        # sa2=False: daemon sem Smart Actions v2 (SaveSmartAction devolve id puro; membros novos => UnknownMethod)
        self.sa2 = sa2
        self.taken_shortcut = ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_L"]  # "já usada" => trigger_errors
        self.ran: list[dict] = []
        self.prefs = {"notify_battery": True, "battery_threshold": 15, "osd_profile": True, "osd_gestures": True,
                      "notify_connection": False, "ai_delivery_default": "clipboard"}
        self.imported: list[tuple] = []
        self.devices = {d["id"]: json.loads(json.dumps(d)) for d in (M720, KEYBOARD)}
        self.calls: list[tuple] = []
        self.active_app = {"app_id": "", "wm_class": [], "title": "", "pid": 0, "exe": ""}
        self.recent = [{"app_id": "firefox", "wm_class": ["Navigator", "firefox"], "title": "Mozilla Firefox", "pid": 1, "exe": "firefox-esr"},
                       {"app_id": "xfce4-terminal", "wm_class": ["xfce4-terminal", "Xfce4-terminal"], "title": "Terminal", "pid": 2, "exe": "xfce4-terminal"}]
        self.smart = {"sa_demo01": {"name": "Começar o dia", "icon": "weather-clear-symbolic",
                                    "steps": [{"type": "open", "target": "https://example.org"}, {"type": "delay", "ms": 500},
                                              {"type": "media", "op": "play_pause"}]}}
        self.running = [{"app_id": "firefox", "wm_class": ["Navigator", "firefox"], "title": "Mozilla Firefox", "pid": 1, "exe": "firefox-esr"}]
        self.conn = None
        self.owner = Gio.bus_own_name(bus_type, "io.github.openmacros", Gio.BusNameOwnerFlags.NONE,
                                      self._bus_acquired, None, None)

    def _bus_acquired(self, conn, name):
        self.conn = conn
        info = Gio.DBusNodeInfo.new_for_xml(XML)
        conn.register_object("/io/github/openmacros", info.interfaces[0], self._call, None, None)

    def stop(self):
        Gio.bus_unown_name(self.owner)

    def emit(self, signal, params):
        self.conn.emit_signal(None, "/io/github/openmacros", "io.github.openmacros.Manager1", signal, params)

    def _dev(self, inv, dev_id):
        if dev_id not in self.devices:
            inv.return_dbus_error("io.github.openmacros.Error.NotFound", dev_id)
            return None
        return self.devices[dev_id]

    def _call(self, conn, sender, path, iface, method, params, inv):
        args = params.unpack()
        self.calls.append((method, args))
        if method == "GetDevices":
            inv.return_value(GLib.Variant("(s)", (json.dumps(list(self.devices.values())),)))
        elif method == "Rescan":
            inv.return_value(None)
        elif method in ("GetPreferences", "SetPreference", "ExportConfig", "ImportConfig"):
            if not self.v2:
                inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "sem " + method)
            elif method == "GetPreferences":
                inv.return_value(GLib.Variant("(s)", (json.dumps(self.prefs),)))
            elif method == "SetPreference":
                key, val = args[0], json.loads(args[1])
                if key not in self.prefs or type(val) is not type(self.prefs[key]):
                    inv.return_dbus_error("io.github.openmacros.Error.InvalidArgument", key)
                    return
                self.prefs[key] = val
                inv.return_value(GLib.Variant("(b)", (True,)))
                self.emit("PreferencesChanged", GLib.Variant("(s)", (json.dumps(self.prefs),)))
            elif method == "ExportConfig":
                inv.return_value(GLib.Variant("(s)", (json.dumps({"openmacros_export": 1, "devices": {},
                                                                  "smart_actions": self.smart,
                                                                  "preferences": self.prefs}),)))
            else:
                self.imported.append(tuple(args))
                inv.return_value(GLib.Variant("(b)", (True,)))
        elif method in ("SetSmartActionEnabled", "ExportSmartAction", "ImportSmartAction", "GetRunningApps"):
            if not self.sa2:
                inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "sem " + method)
            else:
                self._extra(inv, method, args)
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
                inv.return_dbus_error("io.github.openmacros.Error.DeviceOffline", "offline")
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
        out = {}
        for sid, sa in self.smart.items():
            e = dict(sa, id=sid)
            if self.sa2:
                e["trigger_errors"] = [{"index": i, "message": "Combinação já usada por outro programa"}
                                       for i, t in enumerate(sa.get("triggers") or [])
                                       if t.get("type") == "shortcut" and t.get("keys") == self.taken_shortcut]
            out[sid] = e
        inv.return_value(GLib.Variant("(s)", (json.dumps(out),)))
    elif method == "SaveSmartAction":
        sa = json.loads(args[0])
        sid = sa.pop("id", None) or "sa_%06x" % (len(self.smart) + 0xab12cd)
        if self.sa2:
            old = self.smart.get(sid, {})
            sa.setdefault("enabled", old.get("enabled", True))
            sa.setdefault("triggers", [])
            sa["stats"] = old.get("stats") or {"runs": 0, "last_run": None, "created": "2026-01-01T00:00:00",
                                               "modified": "2026-01-01T00:00:00"}
            warnings = [f"o texto do passo {i + 1} parece conter uma senha" for i, st in enumerate(sa.get("steps") or [])
                        if st.get("type") == "type_text" and "senha" in st.get("text", "").lower()]
        self.smart[sid] = sa
        if self.sa2:
            inv.return_value(GLib.Variant("(s)", (json.dumps({"id": sid, "warnings": warnings}),)))
        else:
            inv.return_value(GLib.Variant("(s)", (sid,)))
        self.emit("SmartActionsChanged", None)
    elif method == "SetSmartActionEnabled":
        sa = self.smart.get(args[0])
        if sa is None:
            inv.return_dbus_error("io.github.openmacros.Error.NotFound", args[0])
            return
        sa["enabled"] = bool(args[1])
        inv.return_value(GLib.Variant("(b)", (True,)))
        self.emit("SmartActionsChanged", None)
    elif method == "ExportSmartAction":
        sa = self.smart.get(args[0])
        if sa is None:
            inv.return_dbus_error("io.github.openmacros.Error.NotFound", args[0])
            return
        out = {"openmacros_smart_action": 1, **{k: v for k, v in sa.items() if k != "stats"}}
        inv.return_value(GLib.Variant("(s)", (json.dumps(out),)))
    elif method == "ImportSmartAction":
        data = json.loads(args[0])
        data.pop("openmacros_smart_action", None)
        sid = "sa_%06x" % (len(self.smart) + 0xcd34ef)
        self.smart[sid] = data
        inv.return_value(GLib.Variant("(s)", (sid,)))
        self.emit("SmartActionsChanged", None)
    elif method == "GetRunningApps":
        inv.return_value(GLib.Variant("(s)", (json.dumps(self.running),)))
    elif method == "DeleteSmartAction":
        ok = self.smart.pop(args[0], None) is not None
        inv.return_value(GLib.Variant("(b)", (ok,)))
        self.emit("SmartActionsChanged", None)
    elif method == "RunAction":
        self.ran.append(json.loads(args[0]))
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
            inv.return_dbus_error("io.github.openmacros.Error.NotFound", app)
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
