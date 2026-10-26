"""Notificações/OSD via org.freedesktop.Notifications e lógica de alerta de bateria.

`Notifier` fala D-Bus de forma assíncrona (Gio); se o serviço não existir só loga. Os testes injetam
`RecordingNotifier`. `BatteryAlerts` é uma máquina de estados pura (limiar com rearme).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

APP_NAME = "OpenMacros+"
APP_ICON = "io.github.openmacros.App"
BUS = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"

URGENCY_LOW, URGENCY_NORMAL, URGENCY_CRITICAL = 0, 1, 2
CRITICAL_LEVEL = 5
REARM_MARGIN = 5


class NullNotifier:
    """Descarta tudo (padrão em testes/ações sem notificador)."""

    def notify(self, category: str, summary: str, body: str = "", *, timeout_ms: int = -1,
               urgency: int = URGENCY_NORMAL) -> None:
        pass


class RecordingNotifier(NullNotifier):
    """Guarda as notificações (testes e modo OPENMACROS_FAKE)."""

    def __init__(self, log_calls: bool = False):
        self.sent: list[dict] = []
        self._log = log_calls

    def notify(self, category, summary, body="", *, timeout_ms=-1, urgency=URGENCY_NORMAL):
        self.sent.append({"category": category, "summary": summary, "body": body,
                          "timeout_ms": timeout_ms, "urgency": urgency})
        if self._log:
            log.info("[fake] notificação %s: %s %s", category, summary, body)

    def summaries(self) -> list[str]:
        return [n["summary"] for n in self.sent]


class Notifier(NullNotifier):
    """Notify() assíncrono; `replaces_id` por categoria evita empilhar."""

    def __init__(self, bus_type=None):
        self._bus_type = bus_type
        self._ids: dict[str, int] = {}
        self._bus = None
        self._warned = False

    def _get_bus(self):
        if self._bus is None:
            from gi.repository import Gio
            self._bus = Gio.bus_get_sync(self._bus_type or Gio.BusType.SESSION, None)
        return self._bus

    def notify(self, category, summary, body="", *, timeout_ms=-1, urgency=URGENCY_NORMAL) -> None:
        try:
            from gi.repository import Gio, GLib
            hints = {"urgency": GLib.Variant("y", urgency), "desktop-entry": GLib.Variant("s", APP_ICON),
                     "category": GLib.Variant("s", category.split(":")[0])}
            params = GLib.Variant("(susssasa{sv}i)", (
                APP_NAME, self._ids.get(category, 0), APP_ICON, summary, body, [], hints, int(timeout_ms)))
            self._get_bus().call(BUS, PATH, BUS, "Notify", params, GLib.VariantType("(u)"),
                                 Gio.DBusCallFlags.NONE, 2000, None, self._done, category)
        except Exception as e:
            self._warn(e)

    def _done(self, bus, result, category) -> None:
        try:
            self._ids[category] = int(bus.call_finish(result).unpack()[0])
        except Exception as e:
            self._warn(e)

    def _warn(self, e) -> None:
        if not self._warned:  # uma vez só: sem serviço de notificações é normal
            self._warned = True
            log.info("notificações indisponíveis (%s)", e)
        else:
            log.debug("notificação falhou: %s", e)


class BatteryAlerts:
    """Alerta de bateria baixa uma vez por ciclo de descarga.

    Rearma ao carregar ou ao subir REARM_MARGIN pontos acima do limiar (crítico: acima de 5 + margem).
    `update` devolve [] ou ["low"] ou ["critical"].
    """

    def __init__(self):
        self._low_armed: dict[str, bool] = {}
        self._crit_armed: dict[str, bool] = {}

    def forget(self, dev_id: str) -> None:
        self._low_armed.pop(dev_id, None)
        self._crit_armed.pop(dev_id, None)

    def update(self, dev_id: str, battery: dict | None, threshold: int) -> list[str]:
        if not battery or not isinstance(battery.get("level"), int):
            return []
        level, status = battery["level"], battery.get("status", "")
        low = self._low_armed.get(dev_id, True)
        crit = self._crit_armed.get(dev_id, True)
        if status in ("charging", "full"):
            low = crit = True
        else:
            if level >= threshold + REARM_MARGIN:
                low = True
            if level >= CRITICAL_LEVEL + REARM_MARGIN:
                crit = True
        out: list[str] = []
        if status not in ("charging", "full"):
            if level <= CRITICAL_LEVEL and crit:
                out.append("critical")
                crit = low = False  # o crítico cobre o aviso comum
            elif level <= threshold and low:
                out.append("low")
                low = False
        self._low_armed[dev_id], self._crit_armed[dev_id] = low, crit
        return out
