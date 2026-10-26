"""Cliente D-Bus mínimo da bandeja (só Gio). Reconecta quando o serviço volta (bus_watch_name)."""

from __future__ import annotations

import json
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "io.github.openmacros"
OBJECT_PATH = "/io/github/openmacros"
INTERFACE = "io.github.openmacros.Manager1"


class TrayClient:
    """`on_change()` é chamado quando devices/serviço/app ativo mudam. `devices` é None sem serviço."""

    def __init__(self, on_change: Callable[[], None], bus_type: Gio.BusType = Gio.BusType.SESSION):
        self.on_change = on_change
        self._bus_type = bus_type
        self._proxy: Gio.DBusProxy | None = None
        self._watch = 0
        self._gen = 0
        self.devices: list[dict] | None = None
        self.active_app: dict = {}
        self._conn = None
        self._retry_id = 0

    def start(self) -> None:
        self._watch = Gio.bus_watch_name(self._bus_type, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
                                         self._appeared, self._vanished)

    def stop(self) -> None:
        self._cancel_retry()
        if self._watch:
            Gio.bus_unwatch_name(self._watch)
            self._watch = 0
        self._proxy = None

    # ---- ciclo de vida
    RETRY_SECONDS = 3

    def _appeared(self, conn, name, owner) -> None:
        self._gen += 1
        self._conn = conn
        self._cancel_retry()
        self._new_proxy(self._gen)

    def _new_proxy(self, gen: int) -> None:
        Gio.DBusProxy.new(self._conn, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None, BUS_NAME, OBJECT_PATH,
                          INTERFACE, None, self._proxy_ready, gen)

    def _cancel_retry(self) -> None:
        if self._retry_id:
            GLib.source_remove(self._retry_id)
            self._retry_id = 0

    def _schedule_retry(self, fn, *args) -> None:
        """Nova tentativa depois de uma falha (o serviço pode estar subindo); cancelada se o serviço sumir."""
        self._cancel_retry()

        def fire() -> bool:
            self._retry_id = 0
            fn(*args)
            return False
        self._retry_id = GLib.timeout_add_seconds(self.RETRY_SECONDS, fire)

    def _proxy_ready(self, _src, result, gen) -> None:
        try:
            proxy = Gio.DBusProxy.new_finish(result)
        except GLib.Error:
            if gen == self._gen and self._proxy is None and self._conn is not None:
                self._schedule_retry(self._new_proxy, gen)
            return
        if gen != self._gen:
            return
        self._proxy = proxy
        proxy.connect("g-signal", self._on_signal)
        self.refresh()

    def _vanished(self, conn, name) -> None:
        self._gen += 1
        self._cancel_retry()
        self._proxy = None
        self.devices = None
        self.active_app = {}
        self.on_change()

    # ---- dados
    def refresh(self) -> None:
        self._call("GetDevices", None, self._got_devices)
        self._call("GetActiveApp", None, self._got_app)

    def _call(self, method: str, args, cb) -> None:
        if self._proxy is None:
            return

        def done(proxy, result) -> None:
            try:
                (text,) = proxy.call_finish(result).unpack()
            except GLib.Error:
                cb(None)
                return
            cb(text)
        self._proxy.call(method, args, Gio.DBusCallFlags.NONE, 8000, None, done)

    def _got_devices(self, text) -> None:
        if text is None:  # GetDevices falhou (timeout/serviço ocupado): tenta de novo
            if self._proxy is not None and self.devices is None:
                self._schedule_retry(self.refresh)
            return
        try:
            data = json.loads(text)
        except ValueError:
            return
        self.devices = [d for d in data if isinstance(d, dict) and "id" in d] if isinstance(data, list) else []
        self.on_change()

    def _got_app(self, text) -> None:
        try:
            app = json.loads(text) if text else {}
        except ValueError:
            return
        self.active_app = app if isinstance(app, dict) else {}
        self.on_change()

    def _on_signal(self, _proxy, _sender, signal, params) -> None:
        try:
            if signal == "DevicesChanged":
                self._call("GetDevices", None, self._got_devices)
            elif signal == "DeviceUpdated":
                dev_id, text = params.unpack()
                dev = json.loads(text)
                if self.devices is None:
                    return
                for i, d in enumerate(self.devices):
                    if d.get("id") == dev_id:
                        self.devices[i] = dev
                        break
                else:
                    self.devices.append(dev)
                self.on_change()
            elif signal == "ActiveAppChanged":
                (text,) = params.unpack()
                self._got_app(text)
        except (ValueError, TypeError):
            pass

    def change_host(self, dev_id: str, host: int, done: Callable[[bool], None] | None = None) -> None:
        if self._proxy is None:
            return

        def cb(proxy, result) -> None:
            try:
                ok = bool(proxy.call_finish(result).unpack()[0])
            except GLib.Error:
                ok = False
            if done:
                done(ok)
        self._proxy.call("ChangeHost", GLib.Variant("(sy)", (dev_id, host)), Gio.DBusCallFlags.NONE, 8000, None, cb)
