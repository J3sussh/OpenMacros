"""Botão que captura uma combinação de teclas e a converte em nomes evdev."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

from ..logic import keys_from_hardware, pretty_keys  # noqa: E402


class KeyCapture(Gtk.Button):
    __gsignals__ = {"keys-changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self.keys: list[str] = []
        self._capturing = False
        self.set_valign(Gtk.Align.CENTER)
        self.set_focusable(True)
        ctl = Gtk.EventControllerKey()
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctl.connect("key-pressed", self._on_key)
        self.add_controller(ctl)
        self.connect("clicked", self._on_clicked)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_: self._stop())
        self.add_controller(focus)
        self._refresh()

    def set_keys(self, keys: list[str]) -> None:
        self.keys = list(keys)
        self._refresh()

    def _refresh(self) -> None:
        if self._capturing:
            self.set_label("Pressione o atalho… (Esc cancela)")
        elif self.keys:
            self.set_label(pretty_keys(self.keys))
        else:
            self.set_label("Clique para gravar")
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Atalho de teclado: " + self.get_label()])

    def _stop(self) -> None:
        if self._capturing:
            self._capturing = False
            self._refresh()

    def _on_clicked(self, _btn) -> None:
        self._capturing = True
        self.grab_focus()
        self._refresh()

    def _on_key(self, _ctl, keyval, keycode, state) -> bool:
        if not self._capturing:
            return False
        if keyval == Gdk.KEY_Escape:
            self._stop()
            return True
        keys = keys_from_hardware(
            keycode,
            bool(state & Gdk.ModifierType.CONTROL_MASK),
            bool(state & Gdk.ModifierType.SHIFT_MASK),
            bool(state & Gdk.ModifierType.ALT_MASK),
            bool(state & (Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.META_MASK)),
        )
        if keys is None:  # só modificador pressionado: aguarda a tecla principal
            return True
        self.keys = keys
        self._capturing = False
        self._refresh()
        self.emit("keys-changed")
        return True
