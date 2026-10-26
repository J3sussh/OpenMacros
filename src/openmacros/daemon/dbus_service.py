"""Serviço D-Bus (io.github.openmacros.Manager1) usando Gio.DBusConnection."""

from __future__ import annotations

import logging
import os

from gi.repository import Gio, GLib

from .manager import Manager, ManagerError

log = logging.getLogger(__name__)

BUS_NAME = "io.github.openmacros"
OBJECT_PATH = "/io/github/openmacros"
INTERFACE = "io.github.openmacros.Manager1"

_EXTRA_METHODS = """
    <method name="GetActiveApp"><arg type="s" name="app" direction="out"/></method>
    <method name="GetRecentApps"><arg type="s" name="apps" direction="out"/></method>
    <method name="SetProfileAssignment">
      <arg type="s" name="id" direction="in"/><arg type="s" name="app_id" direction="in"/>
      <arg type="q" name="cid" direction="in"/><arg type="s" name="action" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="SetProfileSetting">
      <arg type="s" name="id" direction="in"/><arg type="s" name="app_id" direction="in"/>
      <arg type="s" name="key" direction="in"/><arg type="s" name="value_json" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="RemoveProfile">
      <arg type="s" name="id" direction="in"/><arg type="s" name="app_id" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="GetSmartActions"><arg type="s" name="smart_actions" direction="out"/></method>
    <method name="SaveSmartAction">
      <arg type="s" name="json" direction="in"/><arg type="s" name="result" direction="out"/>
    </method>
    <method name="SetSmartActionEnabled">
      <arg type="s" name="id" direction="in"/><arg type="b" name="enabled" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="ExportSmartAction">
      <arg type="s" name="id" direction="in"/><arg type="s" name="json" direction="out"/>
    </method>
    <method name="ImportSmartAction">
      <arg type="s" name="json" direction="in"/><arg type="s" name="id" direction="out"/>
    </method>
    <method name="GetRunningApps"><arg type="s" name="apps" direction="out"/></method>
    <method name="DeleteSmartAction">
      <arg type="s" name="id" direction="in"/><arg type="b" name="ok" direction="out"/>
    </method>
    <method name="RunAction">
      <arg type="s" name="action" direction="in"/><arg type="b" name="ok" direction="out"/>
    </method>
    <method name="GetPreferences"><arg type="s" name="prefs" direction="out"/></method>
    <method name="SetPreference">
      <arg type="s" name="key" direction="in"/><arg type="s" name="value_json" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="ExportConfig"><arg type="s" name="json" direction="out"/></method>
    <method name="ImportConfig">
      <arg type="s" name="json" direction="in"/><arg type="b" name="merge" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <signal name="PreferencesChanged"><arg type="s" name="prefs_json"/></signal>
    <signal name="ActionTriggered">
      <arg type="s" name="id"/><arg type="q" name="cid"/><arg type="s" name="label"/>
    </signal>
    <signal name="ActiveAppChanged"><arg type="s" name="app_json"/></signal>
    <signal name="SmartActionsChanged"/>
    <signal name="SmartActionTriggered">
      <arg type="s" name="id"/><arg type="s" name="trigger_json"/>
    </signal>
"""
_DEBUG_METHODS = """
    <method name="DebugSetActiveApp"><arg type="s" name="app_id" direction="in"/></method>
"""


def introspection_xml(debug: bool) -> str:
    return INTROSPECTION_XML.replace("</interface>", _EXTRA_METHODS + (_DEBUG_METHODS if debug else "")
                                     + "  </interface>")


INTROSPECTION_XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetDevices"><arg type="s" name="devices" direction="out"/></method>
    <method name="GetDevice">
      <arg type="s" name="id" direction="in"/><arg type="s" name="device" direction="out"/>
    </method>
    <method name="SetAssignment">
      <arg type="s" name="id" direction="in"/><arg type="q" name="cid" direction="in"/>
      <arg type="s" name="action" direction="in"/><arg type="b" name="ok" direction="out"/>
    </method>
    <method name="SetSetting">
      <arg type="s" name="id" direction="in"/><arg type="s" name="key" direction="in"/>
      <arg type="s" name="value_json" direction="in"/><arg type="b" name="ok" direction="out"/>
    </method>
    <method name="ChangeHost">
      <arg type="s" name="id" direction="in"/><arg type="y" name="host" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="ResetDevice">
      <arg type="s" name="id" direction="in"/><arg type="b" name="ok" direction="out"/>
    </method>
    <method name="Rescan"/>
    <signal name="DevicesChanged"/>
    <signal name="DeviceUpdated">
      <arg type="s" name="id"/><arg type="s" name="device_json"/>
    </signal>
    <signal name="Error"><arg type="s" name="id"/><arg type="s" name="message"/></signal>
  </interface>
</node>
"""


WRITE_METHODS = {"SetAssignment", "SetSetting", "ChangeHost", "ResetDevice", "SetProfileAssignment",
                 "SetProfileSetting", "RemoveProfile", "SaveSmartAction", "DeleteSmartAction", "RunAction",
                 "SetPreference", "ImportConfig", "SetSmartActionEnabled", "ImportSmartAction",
                 "DebugSetActiveApp"}
ACCESS_DENIED = "org.freedesktop.DBus.Error.AccessDenied"


def is_sandboxed(pid: int) -> bool:
    """Flatpak: /proc/<pid>/root/.flatpak-info existe dentro do sandbox."""
    return os.path.exists(f"/proc/{pid}/root/.flatpak-info")


class DBusService:
    def __init__(self, manager: Manager, bus_type=Gio.BusType.SESSION):
        self.manager = manager
        self.bus_type = bus_type
        self.connection: Gio.DBusConnection | None = None
        self.owner_id = 0
        self.on_name_lost = None
        self.on_name_acquired = None
        self._callers: dict[str, tuple[bool, bool]] = {}  # sender -> (uid ok, sandbox)
        self._node = Gio.DBusNodeInfo.new_for_xml(introspection_xml(manager.debug))
        manager.listeners.append(self._on_manager_signal)

    def start(self) -> None:
        self.owner_id = Gio.bus_own_name(
            self.bus_type, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
            self._bus_acquired, self._name_acquired, self._name_lost)

    def stop(self) -> None:
        if self.owner_id:
            Gio.bus_unown_name(self.owner_id)
            self.owner_id = 0

    def _bus_acquired(self, connection, name) -> None:
        self.connection = connection
        connection.register_object(OBJECT_PATH, self._node.interfaces[0], self._on_call, None, None)

    def _name_acquired(self, connection, name) -> None:
        log.info("nome D-Bus adquirido: %s", name)
        if self.on_name_acquired:
            self.on_name_acquired()

    def _name_lost(self, connection, name) -> None:
        log.error("não foi possível obter o nome D-Bus %s (outra instância rodando?)", name)
        if self.on_name_lost:
            self.on_name_lost()

    # --- autorização ---
    def _credentials(self, sender: str) -> tuple[int, int]:
        """(uid, pid) do remetente via o daemon de barramento."""
        reply = self.connection.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "GetConnectionCredentials", GLib.Variant("(s)", (sender,)), None,
            Gio.DBusCallFlags.NONE, 1000, None)
        creds = reply.unpack()[0]
        return int(creds["UnixUserID"]), int(creds["ProcessID"])

    def authorize(self, sender: str, method: str) -> str | None:
        """None se permitido; senão a mensagem de erro. Falha fechada. Cache por sender."""
        info = self._callers.get(sender)
        if info is None:
            try:
                uid, pid = self._credentials(sender)
                info = (uid == os.getuid(), is_sandboxed(pid))
            except Exception as e:
                log.warning("não foi possível obter credenciais de %s: %s", sender, e)
                return "credenciais do chamador indisponíveis"
            if len(self._callers) > 256:
                self._callers.clear()
            self._callers[sender] = info
        uid_ok, sandboxed = info
        if not uid_ok:
            return "chamador de outro usuário"
        if sandboxed and method in WRITE_METHODS:
            return "aplicativos em sandbox não podem alterar dispositivos"
        return None

    # --- chamadas ---
    def _on_call(self, connection, sender, path, interface, method, params, invocation) -> None:
        mgr = self.manager
        denied = self.authorize(sender, method)
        if denied:
            invocation.return_dbus_error(ACCESS_DENIED, denied)
            return
        try:
            args = params.unpack()
            if method == "GetDevices":
                reply = GLib.Variant("(s)", (mgr.get_devices(),))
            elif method == "GetDevice":
                reply = GLib.Variant("(s)", (mgr.get_device(*args),))
            elif method == "SetAssignment":
                reply = GLib.Variant("(b)", (mgr.set_assignment(*args),))
            elif method == "SetSetting":
                reply = GLib.Variant("(b)", (mgr.set_setting(*args),))
            elif method == "ChangeHost":
                reply = GLib.Variant("(b)", (mgr.change_host(*args),))
            elif method == "ResetDevice":
                reply = GLib.Variant("(b)", (mgr.reset_device(*args),))
            elif method == "GetActiveApp":
                reply = GLib.Variant("(s)", (mgr.get_active_app(),))
            elif method == "GetRecentApps":
                reply = GLib.Variant("(s)", (mgr.get_recent_apps(),))
            elif method == "SetProfileAssignment":
                reply = GLib.Variant("(b)", (mgr.set_profile_assignment(*args),))
            elif method == "SetProfileSetting":
                reply = GLib.Variant("(b)", (mgr.set_profile_setting(*args),))
            elif method == "RemoveProfile":
                reply = GLib.Variant("(b)", (mgr.remove_profile(*args),))
            elif method == "GetSmartActions":
                reply = GLib.Variant("(s)", (mgr.get_smart_actions(),))
            elif method == "SaveSmartAction":
                reply = GLib.Variant("(s)", (mgr.save_smart_action(*args),))
            elif method == "SetSmartActionEnabled":
                reply = GLib.Variant("(b)", (mgr.set_smart_action_enabled(*args),))
            elif method == "ExportSmartAction":
                reply = GLib.Variant("(s)", (mgr.export_smart_action(*args),))
            elif method == "ImportSmartAction":
                reply = GLib.Variant("(s)", (mgr.import_smart_action(*args),))
            elif method == "GetRunningApps":
                reply = GLib.Variant("(s)", (mgr.get_running_apps(),))
            elif method == "DeleteSmartAction":
                reply = GLib.Variant("(b)", (mgr.delete_smart_action(*args),))
            elif method == "RunAction":
                reply = GLib.Variant("(b)", (mgr.run_action(*args),))
            elif method == "GetPreferences":
                reply = GLib.Variant("(s)", (mgr.get_preferences(),))
            elif method == "SetPreference":
                reply = GLib.Variant("(b)", (mgr.set_preference(*args),))
            elif method == "ExportConfig":
                reply = GLib.Variant("(s)", (mgr.export_config(),))
            elif method == "ImportConfig":
                reply = GLib.Variant("(b)", (mgr.import_config(*args),))
            elif method == "DebugSetActiveApp":
                mgr.debug_set_active_app(*args)
                reply = None
            elif method == "Rescan":
                mgr.rescan()
                reply = None
            else:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
                return
            invocation.return_value(reply)
        except ManagerError as e:
            invocation.return_dbus_error(e.dbus_name, str(e))
        except Exception:
            log.exception("erro interno em %s", method)
            invocation.return_dbus_error("org.freedesktop.DBus.Error.Failed", "erro interno do serviço")

    # --- sinais ---
    def _on_manager_signal(self, name: str, *args) -> None:
        if not self.connection:
            return
        if name == "devices_changed":
            sig, var = "DevicesChanged", None
        elif name == "device_updated":
            sig, var = "DeviceUpdated", GLib.Variant("(ss)", tuple(args))
        elif name == "active_app_changed":
            sig, var = "ActiveAppChanged", GLib.Variant("(s)", tuple(args))
        elif name == "smart_actions_changed":
            sig, var = "SmartActionsChanged", None
        elif name == "smart_action_triggered":
            sig, var = "SmartActionTriggered", GLib.Variant("(ss)", tuple(args))
        elif name == "preferences_changed":
            sig, var = "PreferencesChanged", GLib.Variant("(s)", tuple(args))
        elif name == "action_triggered":
            sig, var = "ActionTriggered", GLib.Variant("(sqs)", tuple(args))
        elif name == "error":
            sig, var = "Error", GLib.Variant("(ss)", tuple(args))
        else:
            return
        self.connection.emit_signal(None, OBJECT_PATH, INTERFACE, sig, var)
