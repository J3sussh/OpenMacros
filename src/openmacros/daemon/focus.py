"""Aplicativo em foco: X11 (python-xlib) com eventos; Null em Wayland/sem DISPLAY."""

from __future__ import annotations

import logging
import os
from typing import Callable

log = logging.getLogger(__name__)

DEBOUNCE_MS = 120
EMPTY_APP = {"app_id": "", "wm_class": [], "title": "", "pid": 0, "exe": ""}


def app_from_props(wm_class, title: str = "", pid: int = 0, exe: str = "") -> dict:
    """app_id = classe do WM_CLASS em minúsculas; sem WM_CLASS usa o exe; sem nada, ''."""
    wm = [c for c in (wm_class or ()) if c]
    app_id = (wm[-1].lower() if wm else "") or (exe or "").lower()
    return {"app_id": app_id, "wm_class": list(wm), "title": title or "", "pid": int(pid or 0),
            "exe": exe or ""}


def exe_name(pid: int) -> str:
    if not pid:
        return ""
    try:
        return os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    except OSError:
        return ""


class FocusWatcher:
    def start(self, callback: Callable[[dict], None]) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        pass


class NullFocusWatcher(FocusWatcher):
    def __init__(self, reason: str = "", retry: bool = False):
        self.reason = reason
        self.retry = retry  # True: faltava só o DISPLAY; vale tentar de novo quando aparecer

    def start(self, callback) -> None:
        log.warning("detecção de aplicativo em foco indisponível (%s): só o perfil global vale",
                    self.reason or "sem suporte")


class FakeFocusWatcher(FocusWatcher):
    """Modo OPENMACROS_FAKE: o foco é definido por DebugSetActiveApp."""

    def __init__(self):
        self.callback = None

    def start(self, callback) -> None:
        self.callback = callback

    def set_active(self, app_id: str) -> None:
        app = EMPTY_APP if not app_id else app_from_props((app_id, app_id), app_id, 0, app_id)
        if self.callback:
            self.callback(dict(app))


class X11FocusWatcher(FocusWatcher):
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.callback = None
        self.display = None
        self._watch = 0
        self._timer = None
        self._last: str | None = None

    def start(self, callback) -> None:
        from gi.repository import GLib
        from Xlib import X, display
        self.callback = callback
        self.display = display.Display()
        self._net_active = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        root = self.display.screen().root
        root.change_attributes(event_mask=X.PropertyChangeMask)
        self.display.flush()
        self._watch = GLib.io_add_watch(self.display.fileno(), GLib.PRIORITY_DEFAULT,
                                        GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                                        self._on_x)
        self._schedule()  # estado inicial

    def stop(self) -> None:
        from gi.repository import GLib
        if self._timer is not None:
            self.scheduler.cancel(self._timer)
            self._timer = None
        if self._watch:
            GLib.source_remove(self._watch)
            self._watch = 0
        if self.display:
            try:
                self.display.close()
            except Exception:
                pass
            self.display = None

    def _on_x(self, fd, cond) -> bool:
        from Xlib import X
        from gi.repository import GLib
        try:
            if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
                raise OSError("conexão X fechada")
            while self.display.pending_events():
                ev = self.display.next_event()
                if ev.type == X.PropertyNotify and ev.atom == self._net_active:
                    self._schedule()
        except Exception as e:
            log.error("conexão X11 perdida (%s); foco desativado", e)
            self._watch = 0
            return False
        return True

    def _schedule(self) -> None:
        if self._timer is not None:
            self.scheduler.cancel(self._timer)
        self._timer = self.scheduler.call_later(DEBOUNCE_MS, self._check)

    def _check(self) -> None:
        self._timer = None
        app = self.read_active()
        if app["app_id"] != self._last:
            self._last = app["app_id"]
            if self.callback:
                self.callback(app)

    def read_active(self) -> dict:
        """Lê a janela ativa; qualquer falha (janela sumiu, propriedade ausente) vira app vazio."""
        from Xlib import X, error
        try:
            root = self.display.screen().root
            prop = root.get_full_property(self._net_active, X.AnyPropertyType)
            wid = int(prop.value[0]) if prop is not None and len(prop.value) else 0
            if not wid:
                return dict(EMPTY_APP)
            return read_window_app(self.display, wid)
        except (error.XError, error.ConnectionClosedError, OSError, IndexError, AttributeError) as e:
            log.debug("falha lendo janela ativa: %s", e)
            return dict(EMPTY_APP)


def read_window_app(display, wid: int) -> dict:
    """ActiveApp de uma janela (mesma regra de app_id para foco, gatilhos de app e ações `app`).
    Propriedades ausentes viram vazias; janela inexistente levanta XError."""
    from Xlib import X, error
    win = display.create_resource_object("window", wid)
    wm_class = None
    try:
        wm_class = win.get_wm_class()
    except (error.XError, UnicodeDecodeError):
        pass
    pid = 0
    try:
        p = win.get_full_property(display.intern_atom("_NET_WM_PID"), X.AnyPropertyType)
        pid = int(p.value[0]) if p is not None and len(p.value) else 0
    except error.XError:
        pass
    title = ""
    try:
        t = win.get_full_property(display.intern_atom("_NET_WM_NAME"), X.AnyPropertyType)
        if t is not None:
            v = t.value
            title = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
        else:
            title = win.get_wm_name() or ""
            if isinstance(title, bytes):
                title = title.decode("latin-1", "replace")
    except (error.XError, UnicodeDecodeError):
        pass
    return app_from_props(wm_class, title[:200], pid, exe_name(pid))


def display_kind() -> str:
    """'wayland' | 'no-display' | 'x11' conforme o ambiente atual do processo."""
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return "wayland"
    return "x11" if os.environ.get("DISPLAY") else "no-display"


def make_focus_watcher(scheduler) -> FocusWatcher:
    kind = display_kind()
    if kind != "x11":
        # sem DISPLAY ainda (serviço subiu antes do login gráfico): o Manager tenta de novo depois
        return NullFocusWatcher("Wayland" if kind == "wayland" else "sem DISPLAY", retry=kind == "no-display")
    try:
        import Xlib  # noqa: F401
    except ImportError:
        return NullFocusWatcher("python-xlib ausente")
    return X11FocusWatcher(scheduler)
