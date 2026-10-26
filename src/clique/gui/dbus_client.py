"""Cliente D-Bus assíncrono para io.github.clique.Manager1."""

from __future__ import annotations

import json
from typing import Any, Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib, GObject  # noqa: E402

from .logic import friendly_error  # noqa: E402

BUS_NAME = "io.github.clique"
OBJECT_PATH = "/io/github/clique"
INTERFACE = "io.github.clique.Manager1"
CALL_TIMEOUT_MS = 10000

Callback = Callable[[Any, "str | None"], None]


def parse_devices(text: str) -> list[dict]:
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("lista de dispositivos esperada")
    return [d for d in data if isinstance(d, dict) and "id" in d]


def parse_device(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict) or "id" not in data:
        raise ValueError("dispositivo inválido")
    return data


class CliqueClient(GObject.Object):
    """Sinais: availability-changed(bool), devices-changed(), device-updated(id, dict), error(id, msg)."""

    __gsignals__ = {
        "availability-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "devices-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "device-updated": (GObject.SignalFlags.RUN_FIRST, None, (str, object)),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "active-app-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "smart-actions-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, bus_type: Gio.BusType = Gio.BusType.SESSION):
        super().__init__()
        self._bus_type = bus_type
        self._proxy: Gio.DBusProxy | None = None
        self._watch_id = 0
        self._generation = 0
        self.available = False

    # ------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        if self._watch_id:
            return
        self._watch_id = Gio.bus_watch_name(
            self._bus_type, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            self._on_appeared, self._on_vanished)

    def stop(self) -> None:
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        self._proxy = None

    def _on_appeared(self, connection, name, owner) -> None:
        self._generation += 1
        gen = self._generation
        Gio.DBusProxy.new(
            connection, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
            BUS_NAME, OBJECT_PATH, INTERFACE, None, self._on_proxy_ready, gen)

    def _on_proxy_ready(self, source, result, gen) -> None:
        try:
            proxy = Gio.DBusProxy.new_finish(result)
        except GLib.Error as e:
            self.emit("error", "", friendly_error(e.message))
            return
        if gen != self._generation:
            return
        self._proxy = proxy
        proxy.connect("g-signal", self._on_signal)
        self.available = True
        self.emit("availability-changed", True)

    def _on_vanished(self, connection, name) -> None:
        self._generation += 1
        self._proxy = None
        self.available = False
        self.emit("availability-changed", False)

    def _on_signal(self, proxy, sender, signal, params) -> None:
        try:
            if signal == "DevicesChanged":
                self.emit("devices-changed")
            elif signal == "DeviceUpdated":
                dev_id, text = params.unpack()
                self.emit("device-updated", dev_id, parse_device(text))
            elif signal == "ActiveAppChanged":
                (text,) = params.unpack()
                self.emit("active-app-changed", json.loads(text))
            elif signal == "SmartActionsChanged":
                self.emit("smart-actions-changed")
            elif signal == "Error":
                dev_id, msg = params.unpack()
                self.emit("error", dev_id, msg)
        except (ValueError, TypeError) as e:
            self.emit("error", "", f"Resposta inválida do serviço: {e}")

    # ------------------------------------------------------------ chamadas
    def _call(self, method: str, args: GLib.Variant | None, callback: Callback | None,
              convert: Callable[[tuple], Any]) -> None:
        def done(proxy, result):
            try:
                value = convert(proxy.call_finish(result).unpack())
            except GLib.Error as e:
                if callback:
                    callback(None, friendly_error(e.message))
                return
            except (ValueError, TypeError) as e:
                if callback:
                    callback(None, f"Resposta inválida do serviço: {e}")
                return
            if callback:
                callback(value, None)

        if self._proxy is None:
            if callback:
                GLib.idle_add(lambda: callback(None, "Serviço Clique não está em execução") and False)
            return
        self._proxy.call(method, args, Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None, done)

    def get_devices(self, callback: Callback) -> None:
        self._call("GetDevices", None, callback, lambda r: parse_devices(r[0]))

    def get_device(self, dev_id: str, callback: Callback) -> None:
        self._call("GetDevice", GLib.Variant("(s)", (dev_id,)), callback, lambda r: parse_device(r[0]))

    def set_assignment(self, dev_id: str, cid: int, action: dict, callback: Callback | None = None) -> None:
        self._call("SetAssignment", GLib.Variant("(sqs)", (dev_id, cid, json.dumps(action))),
                   callback, lambda r: bool(r[0]))

    def set_setting(self, dev_id: str, key: str, value: Any, callback: Callback | None = None) -> None:
        self._call("SetSetting", GLib.Variant("(sss)", (dev_id, key, json.dumps(value))),
                   callback, lambda r: bool(r[0]))

    def change_host(self, dev_id: str, host: int, callback: Callback | None = None) -> None:
        self._call("ChangeHost", GLib.Variant("(sy)", (dev_id, host)), callback, lambda r: bool(r[0]))

    def reset_device(self, dev_id: str, callback: Callback | None = None) -> None:
        self._call("ResetDevice", GLib.Variant("(s)", (dev_id,)), callback, lambda r: bool(r[0]))

    def rescan(self, callback: Callback | None = None) -> None:
        self._call("Rescan", None, callback, lambda r: True)

    # ---- extensão: integrações com aplicativos (INTEGRATIONS.md, seção 5)
    def get_active_app(self, callback: Callback) -> None:
        self._call("GetActiveApp", None, callback, lambda r: _json_obj(r[0]))

    def get_recent_apps(self, callback: Callback) -> None:
        self._call("GetRecentApps", None, callback, lambda r: [a for a in json.loads(r[0]) if isinstance(a, dict)])

    def set_profile_assignment(self, dev_id: str, app_id: str, cid: int, action: dict | None,
                               callback: Callback | None = None) -> None:
        """app_id '' = global. action None envia 'null' (remove a sobreposição do perfil)."""
        self._call("SetProfileAssignment", GLib.Variant("(ssqs)", (dev_id, app_id, cid, json.dumps(action))),
                   callback, lambda r: bool(r[0]))

    def set_profile_setting(self, dev_id: str, app_id: str, key: str, value: Any,
                            callback: Callback | None = None) -> None:
        """value None envia 'null' (remove a sobreposição)."""
        self._call("SetProfileSetting", GLib.Variant("(ssss)", (dev_id, app_id, key, json.dumps(value))),
                   callback, lambda r: bool(r[0]))

    def remove_profile(self, dev_id: str, app_id: str, callback: Callback | None = None) -> None:
        self._call("RemoveProfile", GLib.Variant("(ss)", (dev_id, app_id)), callback, lambda r: bool(r[0]))

    def get_smart_actions(self, callback: Callback) -> None:
        self._call("GetSmartActions", None, callback, lambda r: _json_obj(r[0]))

    def save_smart_action(self, sa: dict, callback: Callback | None = None) -> None:
        self._call("SaveSmartAction", GLib.Variant("(s)", (json.dumps(sa),)), callback, lambda r: str(r[0]))

    def delete_smart_action(self, sa_id: str, callback: Callback | None = None) -> None:
        self._call("DeleteSmartAction", GLib.Variant("(s)", (sa_id,)), callback, lambda r: bool(r[0]))

    def run_action(self, action: dict, callback: Callback | None = None) -> None:
        self._call("RunAction", GLib.Variant("(s)", (json.dumps(action),)), callback, lambda r: bool(r[0]))


def _json_obj(text: str) -> dict:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("objeto JSON esperado")
    return data
