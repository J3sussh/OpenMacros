"""Gravador de sequência de teclas (tempos reais ou atraso fixo). Captura SÓ os eventos de teclado que chegam
a este widget (janela do próprio OpenMacros+, com o foco nele): não há captura global do teclado."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, GObject, Gtk  # noqa: E402

from .. import logic  # noqa: E402


class KeyRecorder(Gtk.Box):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, events: list | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.rec = logic.KeySequenceRecorder(False, events)
        self.recording = False

        modes = Gtk.Box(spacing=0)
        modes.add_css_class("linked")
        self.real_btn = Gtk.ToggleButton(label="Tempos reais", active=True)
        self.fixed_btn = Gtk.ToggleButton(label=f"Atraso fixo ({logic.KEY_SEQ_FIXED_DELAY} ms)", group=self.real_btn)
        self.real_btn.connect("toggled", self._on_mode)
        modes.append(self.real_btn)
        modes.append(self.fixed_btn)
        self.append(modes)

        row = Gtk.Box(spacing=8)
        self.toggle = Gtk.Button()
        self.toggle.connect("clicked", lambda *_: self.stop() if self.recording else self.start())
        self.clear_btn = Gtk.Button(label="Limpar")
        self.clear_btn.connect("clicked", lambda *_: self.clear())
        row.append(self.toggle)
        row.append(self.clear_btn)
        self.append(row)

        self.status = Gtk.Label(xalign=0, wrap=True)
        self.status.add_css_class("card-title")
        self.preview = Gtk.Label(xalign=0, wrap=True, ellipsize=0, max_width_chars=44)
        self.preview.add_css_class("dim-label")
        self.hint = Gtk.Label(xalign=0, wrap=True)
        self.hint.add_css_class("dim-label")
        self.hint.add_css_class("caption")
        for w in (self.status, self.preview, self.hint):
            self.append(w)

        ctl = Gtk.EventControllerKey()
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctl.connect("key-pressed", lambda _c, _kv, code, _st: self._on_key(code, True))
        ctl.connect("key-released", lambda _c, _kv, code, _st: self._on_key(code, False))
        self.add_controller(ctl)
        self.connect("notify::contains-focus", self._on_focus)
        self.connect("unmap", lambda *_: self.stop())
        self._refresh()

    # ---- estado
    @property
    def events(self) -> list[dict]:
        return [dict(e) for e in self.rec.events]

    def set_events(self, events: list | None) -> None:
        self.stop()
        mode_fixed = self.rec.fixed
        self.rec = logic.KeySequenceRecorder(mode_fixed, events)
        self._refresh()

    def start(self) -> None:
        if self.rec.full:
            self._refresh("Limite de eventos atingido. Limpe para gravar de novo.")
            return
        self.recording = True
        self.rec.resume()
        self.toggle.grab_focus()
        self._refresh()

    def stop(self) -> None:
        if not self.recording:
            return
        self.recording = False
        self.rec.release_all()
        self._refresh()
        self.emit("changed")

    def clear(self) -> None:
        self.recording = False
        self.rec.clear()
        self._refresh()
        self.emit("changed")

    def _on_mode(self, _btn) -> None:
        self.rec.fixed = not self.real_btn.get_active()

    def _on_focus(self, *_a) -> None:
        if not self.get_property("contains-focus"):
            self.stop()

    # ---- captura
    def handle_key(self, keycode: int, down: bool, now_ms: int | None = None) -> bool:
        """keycode de hardware GTK (evdev + 8). True se o evento foi consumido."""
        if not self.recording:
            return False
        name = logic.EVDEV_CODE_NAMES.get(keycode - 8)
        if keycode - 8 == 1:  # Esc encerra a gravação
            if down:
                self.stop()
            return True
        if name is None:
            if down:
                self._refresh("Essa tecla não é suportada e foi ignorada.")
            return True
        now = GLib.get_monotonic_time() // 1000 if now_ms is None else now_ms
        if self.rec.feed(name, down, now):
            self._refresh()
            self.emit("changed")
            if self.rec.full:
                self.stop()
        return True

    def _on_key(self, keycode: int, down: bool) -> bool:
        return self.handle_key(keycode, down)

    # ---- visual
    def _refresh(self, note: str = "") -> None:
        ev = self.rec.events
        if self.recording:
            self.toggle.set_label("Parar")
            self.toggle.remove_css_class("suggested-action")
            self.toggle.add_css_class("destructive-action")
            self.hint.set_label(note or "Gravando: digite as teclas aqui. Esc ou Parar encerra.")
        else:
            self.toggle.set_label("Continuar a gravar" if ev else "Começar a gravar")
            self.toggle.remove_css_class("destructive-action")
            self.toggle.add_css_class("suggested-action")
            self.hint.set_label(note or "Só as teclas pressionadas com este painel em foco são gravadas.")
        self.status.set_label(logic.events_summary(ev) if ev else "Nada gravado ainda")
        self.preview.set_label(logic.events_preview(ev))
        self.preview.set_visible(bool(ev))
        self.clear_btn.set_sensitive(bool(ev))
        self.update_property([Gtk.AccessibleProperty.LABEL], ["Gravador de sequência de teclas"])
