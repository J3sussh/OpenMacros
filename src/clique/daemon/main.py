"""Ponto de entrada do serviço: cliqued."""

from __future__ import annotations

import logging
import os
import signal
import sys

from gi.repository import GLib

from .actions import ActionExecutor
from .config import Config, default_path
from .dbus_service import DBusService
from .timers import GLibScheduler
from .manager import Manager

log = logging.getLogger("cliqued")
RESCAN_FALLBACK_SECONDS = 5
EXIT_NAME_TAKEN = 73  # outra instância já tem o nome D-Bus (o systemd não deve reiniciar)


def _safe_rescan(manager: Manager) -> None:
    try:
        manager.rescan()
    except Exception:
        log.exception("rescan falhou")


def _setup_hotplug(manager: Manager) -> None:
    """pyudev se existir (eventos hidraw); caso contrário, rescan periódico."""
    pending = {"id": 0}

    def schedule():
        if not pending["id"]:
            def run():
                pending["id"] = 0
                _safe_rescan(manager)
                return False
            pending["id"] = GLib.timeout_add(500, run)  # debounce

    try:
        import pyudev
        ctx = pyudev.Context()
        mon = pyudev.Monitor.from_netlink(ctx)
        mon.filter_by(subsystem="hidraw")
        mon.start()

        def on_udev(fd, cond):
            try:
                while mon.poll(0) is not None:
                    pass
                schedule()
            except Exception:
                log.exception("erro no monitor udev")
            return True

        GLib.io_add_watch(mon.fileno(), GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN, on_udev)
        log.info("hotplug via pyudev")
    except Exception as e:
        log.info("hotplug por rescan a cada %ss (%s)", RESCAN_FALLBACK_SECONDS, e)
        GLib.timeout_add_seconds(RESCAN_FALLBACK_SECONDS, lambda: (_safe_rescan(manager), True)[1])


def main() -> int:
    logging.basicConfig(level=os.environ.get("CLIQUE_LOG", "INFO"),
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    fake = os.environ.get("CLIQUE_FAKE", "") not in ("", "0")
    cfg_path = os.environ.get("CLIQUE_CONFIG")
    config = Config(cfg_path if cfg_path else (None if fake else default_path()))
    scheduler = GLibScheduler()
    if fake:
        from .actions import RecordingExecutor
        from .fake import FakeBackend
        from .focus import FakeFocusWatcher
        manager = Manager(config, RecordingExecutor(scheduler=scheduler), scheduler, FakeFocusWatcher())
        manager.debug = True  # habilita DebugSetActiveApp
        manager.backends.append(FakeBackend())
        log.info("modo simulado (CLIQUE_FAKE=1): dispositivos falsos, config em memória")
    else:
        from .hidpp_backend import HidppBackend
        manager = Manager(config, ActionExecutor(scheduler=scheduler), scheduler)
        manager.backends.append(HidppBackend(manager))

    loop = GLib.MainLoop()
    status = {"code": 0}
    service = DBusService(manager)

    def lost():
        status["code"] = EXIT_NAME_TAKEN
        loop.quit()

    service.on_name_lost = lost
    service.start()
    manager.start_focus()
    GLib.idle_add(lambda: (_safe_rescan(manager), False)[1])  # após o loop subir (nome D-Bus primeiro)
    if not fake:
        _setup_hotplug(manager)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            from gi.repository import GLibUnix
            GLibUnix.signal_add(GLib.PRIORITY_HIGH, sig, loop.quit)
        except (ImportError, AttributeError):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, loop.quit)
    try:
        loop.run()
    finally:
        service.stop()
        manager.close()
    return status["code"]


if __name__ == "__main__":
    sys.exit(main())
