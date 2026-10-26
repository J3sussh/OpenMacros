"""X11 dos gatilhos: atalhos globais (XGrabKey) e janelas abertas (_NET_CLIENT_LIST). python-xlib."""

from __future__ import annotations

import logging

from . import smart
from .focus import read_window_app
from .triggers import AppTracker

log = logging.getLogger(__name__)

APP_DEBOUNCE_MS = 150
# tipos de janela que contam como "aplicativo aberto" (sem docks, desktop, menus, notificações…)
_APP_WINDOW_TYPES = ("_NET_WM_WINDOW_TYPE_NORMAL", "_NET_WM_WINDOW_TYPE_DIALOG")


def _watch(display, callback):
    from gi.repository import GLib
    return GLib.io_add_watch(display.fileno(), GLib.PRIORITY_DEFAULT,
                             GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR, callback)


class X11ShortcutBackend:
    """XGrabKey na janela raiz. Cada combinação é registrada com as variantes de CapsLock/NumLock; falha em
    qualquer variante (BadAccess: outro programa já tem a combinação) desfaz a combinação inteira."""
    available = True
    reason = ""

    def __init__(self):
        self.display = None
        self.callback = None
        self._watch_id = 0
        self._grabbed: dict[smart.Combo, list[int]] = {}   # combo -> máscaras X registradas
        self._by_event: dict[tuple[int, int], smart.Combo] = {}
        self._lock_masks: list[int] = []
        self._relevant = 0

    def start(self, callback) -> None:
        from Xlib import X, display
        self.callback = callback
        self.display = display.Display()
        num = self._numlock_mask()
        self._lock_masks = sorted({0, X.LockMask, num, X.LockMask | num})
        self._relevant = X.ShiftMask | X.ControlMask | X.Mod1Mask | X.Mod4Mask
        self._watch_id = _watch(self.display, self._on_x)

    def _numlock_mask(self) -> int:
        from Xlib import X, XK
        try:
            kc = self.display.keysym_to_keycode(XK.XK_Num_Lock)
            if kc:
                for i, keycodes in enumerate(self.display.get_modifier_mapping()):
                    if kc in keycodes and i >= 3:  # só Mod1..Mod5
                        return 1 << i
        except Exception:
            pass
        return X.Mod2Mask

    @staticmethod
    def _xmods(mods: int) -> int:
        from Xlib import X
        return ((X.ControlMask if mods & smart.CTRL else 0) | (X.ShiftMask if mods & smart.SHIFT else 0)
                | (X.Mod1Mask if mods & smart.ALT else 0) | (X.Mod4Mask if mods & smart.SUPER else 0))

    def sync(self, combos) -> dict[smart.Combo, str]:
        """Passa a registrar exatamente `combos`; devolve {combo: motivo} para as que o X recusou."""
        self._ungrab_all()
        errors: dict[smart.Combo, str] = {}
        if self.display is None:
            return {c: "sem conexão com o X11" for c in combos}
        for combo in sorted(combos):
            msg = self._grab(combo)
            if msg:
                errors[combo] = msg
        return errors

    def _grab(self, combo: smart.Combo) -> str | None:
        from Xlib import X, error
        root = self.display.screen().root
        base = self._xmods(combo.mods)
        done: list[int] = []
        failure = None
        for lock in self._lock_masks:
            catcher = error.CatchError()
            root.grab_key(combo.keycode, base | lock, False, X.GrabModeAsync, X.GrabModeAsync, onerror=catcher)
            self.display.sync()
            err = catcher.get_error()
            if err is not None:
                failure = ("já está em uso por outro programa" if isinstance(err, error.BadAccess)
                           else f"o X11 recusou o registro ({type(err).__name__})")
                break
            done.append(base | lock)
        if failure:
            for m in done:
                root.ungrab_key(combo.keycode, m)
            self.display.sync()
            return failure
        self._grabbed[combo] = done
        self._by_event[(combo.keycode, base)] = combo
        return None

    def _ungrab_all(self) -> None:
        if self.display is None:
            return
        root = self.display.screen().root
        for combo, masks in self._grabbed.items():
            for m in masks:
                root.ungrab_key(combo.keycode, m)
        self._grabbed.clear()
        self._by_event.clear()
        try:
            self.display.sync()
        except Exception:
            pass

    def _on_x(self, fd, cond) -> bool:
        from Xlib import X
        from gi.repository import GLib
        try:
            if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
                raise OSError("conexão X fechada")
            while self.display.pending_events():
                ev = self.display.next_event()
                if ev.type == X.KeyPress:
                    combo = self._by_event.get((ev.detail, ev.state & self._relevant))
                    if combo is not None and self.callback:
                        self.callback(combo)
        except Exception as e:
            log.error("conexão X11 dos atalhos perdida (%s); atalhos desativados", e)
            self._watch_id = 0
            return False
        return True

    def stop(self) -> None:
        from gi.repository import GLib
        self._ungrab_all()
        if self._watch_id:
            GLib.source_remove(self._watch_id)
            self._watch_id = 0
        if self.display is not None:
            try:
                self.display.close()
            except Exception:
                pass
            self.display = None


class X11AppWatcher:
    """Observa _NET_CLIENT_LIST na raiz; chama `callback(opened, closed)` (listas de ActiveApp).
    O estado inicial (janelas que já existem ao subir) não gera eventos."""

    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.display = None
        self.callback = None
        self.tracker = AppTracker(self._read)
        self._watch_id = 0
        self._timer = None
        self._atom = 0

    def start(self, callback) -> None:
        from Xlib import X, display
        self.callback = callback
        self.display = display.Display()
        self._atom = self.display.intern_atom("_NET_CLIENT_LIST")
        self.display.screen().root.change_attributes(event_mask=X.PropertyChangeMask)
        self.display.flush()
        self._watch_id = _watch(self.display, self._on_x)
        self.refresh()  # estado inicial

    def _read(self, wid: int) -> dict | None:
        from Xlib import X, error
        try:
            win = self.display.create_resource_object("window", wid)
            t = win.get_full_property(self.display.intern_atom("_NET_WM_WINDOW_TYPE"), X.AnyPropertyType)
            if t is not None and len(t.value):
                allowed = {self.display.intern_atom(n) for n in _APP_WINDOW_TYPES}
                if not allowed & set(t.value):
                    return None
            return read_window_app(self.display, wid)
        except (error.XError, OSError):
            return None

    def refresh(self) -> None:
        from Xlib import X, error
        try:
            p = self.display.screen().root.get_full_property(self._atom, X.AnyPropertyType)
            wids = [int(v) for v in p.value] if p is not None else []
            opened, closed = self.tracker.update(wids)
        except (error.XError, OSError) as e:
            log.debug("falha lendo _NET_CLIENT_LIST: %s", e)
            return
        if (opened or closed) and self.callback:
            self.callback(opened, closed)

    def _on_x(self, fd, cond) -> bool:
        from Xlib import X
        from gi.repository import GLib
        try:
            if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
                raise OSError("conexão X fechada")
            changed = False
            while self.display.pending_events():
                ev = self.display.next_event()
                if ev.type == X.PropertyNotify and ev.atom == self._atom:
                    changed = True
            if changed:
                if self._timer is not None:
                    self.scheduler.cancel(self._timer)
                self._timer = self.scheduler.call_later(APP_DEBOUNCE_MS, self._debounced)
        except Exception as e:
            log.error("conexão X11 dos aplicativos perdida (%s); gatilhos de aplicativo desativados", e)
            self._watch_id = 0
            return False
        return True

    def _debounced(self) -> None:
        self._timer = None
        if self.display is not None:
            self.refresh()

    def running_apps(self) -> list[dict]:
        return self.tracker.running_apps()

    def stop(self) -> None:
        from gi.repository import GLib
        if self._timer is not None:
            self.scheduler.cancel(self._timer)
            self._timer = None
        if self._watch_id:
            GLib.source_remove(self._watch_id)
            self._watch_id = 0
        if self.display is not None:
            try:
                self.display.close()
            except Exception:
                pass
            self.display = None
