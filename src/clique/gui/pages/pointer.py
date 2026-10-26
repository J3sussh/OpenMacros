"""Aba APONTAR E ROLAR: foto à esquerda, cartões com sliders grandes à direita (respeita o perfil)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..widgets.imaging import new_picture  # noqa: E402


def _card(title: str) -> tuple[Gtk.Box, Gtk.Box]:
    """(cartão, caixa do cabeçalho onde entra o selo 'herdado/sobreposto')."""
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    card.add_css_class("clique-card")
    head = Gtk.Box(spacing=8)
    t = Gtk.Label(label=title, xalign=0, hexpand=True)
    t.add_css_class("card-title")
    head.append(t)
    card.append(head)
    return card, head


class _Badge(Gtk.Box):
    """Selo por configuração: 'Herdado de Todos os apps' ou 'Sobreposto' + 'Usar o padrão'."""

    def __init__(self, on_reset):
        super().__init__(spacing=6, valign=Gtk.Align.CENTER)
        self.label = Gtk.Label()
        self.label.add_css_class("chip")
        self.btn = Gtk.Button(label="Usar o padrão")
        self.btn.add_css_class("flat")
        self.btn.add_css_class("caption")
        self.btn.connect("clicked", lambda *_: on_reset())
        self.append(self.label)
        self.append(self.btn)
        self.set_visible(False)

    def show_state(self, in_profile: bool, overridden: bool) -> None:
        self.set_visible(in_profile)
        if not in_profile:
            return
        self.label.set_label("Sobreposto neste app" if overridden else "Herdado de Todos os apps")
        (self.label.add_css_class if overridden else self.label.remove_css_class)("over")
        self.btn.set_visible(overridden)


class PointerPage(Gtk.ScrolledWindow):
    def __init__(self, device: dict, ctx):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.ctx = ctx
        self.device = device
        self.dev_id = device["id"]
        self.app_id = ""
        self._updating = False
        self._timers: dict[str, int] = {}
        s = device.get("settings") or {}
        self.rows: dict[str, Adw.SwitchRow] = {}
        self.badges: dict[str, _Badge] = {}

        outer = Gtk.Box(spacing=40, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        pic = new_picture(logic.art_path(device), (200, 300), (340, 520))
        outer.append(pic)

        cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, valign=Gtk.Align.CENTER)
        cards.set_size_request(400, -1)
        self.profile_note = Gtk.Label(xalign=0, wrap=True)
        self.profile_note.add_css_class("dim-label")
        self.profile_note.set_visible(False)
        cards.append(self.profile_note)
        if "pointer_speed" in s:
            sp = s["pointer_speed"]
            self._lo, self._hi = int(sp.get("min", 1)), int(sp.get("max", 512))
            card, head = _card("Velocidade do ponteiro")
            self.badges["pointer_speed"] = _Badge(lambda: self._reset("pointer_speed"))
            head.append(self.badges["pointer_speed"])
            self.speed = self._scale(self._lo, self._hi, "Velocidade do ponteiro")
            self.speed.connect("value-changed", self._on_speed)
            ends = Gtk.Box()
            for txt, xa in (("Lento", 0.0), ("Rápido", 1.0)):
                lb = Gtk.Label(label=txt, hexpand=True, xalign=xa)
                lb.add_css_class("dim-label")
                ends.append(lb)
            card.append(self.speed)
            card.append(ends)
            cards.append(card)
        if "dpi" in s:
            card, head = _card("Sensibilidade (DPI)")
            self.badges["dpi"] = _Badge(lambda: self._reset("dpi"))
            head.append(self.badges["dpi"])
            self.dpi_choices = [int(c) for c in s["dpi"].get("choices", [])]
            self.dpi_dd = Gtk.DropDown.new_from_strings([f"{c} DPI" for c in self.dpi_choices])
            self.dpi_dd.connect("notify::selected", self._on_dpi)
            card.append(self.dpi_dd)
            cards.append(card)
        sw_keys = [k for k in ("hires_scroll", "scroll_invert") if k in s]
        if sw_keys or "smartshift" in s:
            card, _head = _card("Rolagem")
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lb.add_css_class("plain-list")
            texts = {"hires_scroll": ("Rolagem de alta resolução", "Movimento mais suave em aplicativos compatíveis"),
                     "scroll_invert": ("Inverter rolagem", "Girar a roda para cima desce a página")}
            for key in sw_keys:
                row = Adw.SwitchRow(title=texts[key][0], subtitle=texts[key][1])
                self.badges[key] = _Badge(lambda k=key: self._reset(k))
                row.add_suffix(self.badges[key])
                row.connect("notify::active", self._on_switch, key)
                lb.append(row)
                self.rows[key] = row
            if "smartshift" in s:
                self.ss_switch = Adw.SwitchRow(title="SmartShift", subtitle="Alterna a roda entre livre e com cliques conforme a velocidade")
                self.badges["smartshift"] = _Badge(lambda: self._reset("smartshift"))
                self.ss_switch.add_suffix(self.badges["smartshift"])
                self.ss_switch.connect("notify::active", self._on_smartshift)
                lb.append(self.ss_switch)
            card.append(lb)
            if "smartshift" in s:
                self.ss_scale = self._scale(1, 255, "Limiar do SmartShift")
                self.ss_scale.connect("value-changed", self._on_smartshift)
                self.ss_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=8)
                cap = Gtk.Label(label="Limiar do SmartShift", xalign=0)
                cap.add_css_class("dim-label")
                self.ss_box.append(cap)
                self.ss_box.append(self.ss_scale)
                card.append(self.ss_box)
            cards.append(card)
        outer.append(cards)
        self.set_child(Adw.Clamp(maximum_size=1000, child=outer))
        self.update(device)

    @staticmethod
    def _scale(lo, hi, label: str) -> Gtk.Scale:
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
        sc.set_hexpand(True)
        sc.set_draw_value(False)
        sc.add_css_class("big-scale")
        sc.update_property([Gtk.AccessibleProperty.LABEL], [label])
        return sc

    # ---- perfil
    def set_profile(self, app_id: str) -> None:
        self.app_id = app_id
        self.update(self.device)

    def _write(self, key: str, value) -> None:
        """Grava no perfil selecionado (ou global); value None remove a sobreposição."""
        app = self.app_id

        def ok():
            if app:
                cur = (self.device.get("settings") or {}).get(key, {})
                wrapped = None if value is None else (value if isinstance(value, dict) else {**cur, "value": value})
                logic.with_profile_setting(self.device, app, key, wrapped)
                self.update(self.device)
        if app:
            self.ctx.client.set_profile_setting(self.dev_id, app, key, value, self.ctx.reporter(ok))
        else:
            self.ctx.client.set_setting(self.dev_id, key, value, self.ctx.reporter())

    def _reset(self, key: str) -> None:
        if self.app_id:
            self._write(key, None)

    def _debounce(self, key: str, getter) -> None:
        if self._updating:
            return
        if key in self._timers:
            GLib.source_remove(self._timers[key])

        def fire():
            self._timers.pop(key, None)
            self._write(key, getter())
            return False
        self._timers[key] = GLib.timeout_add(250, fire)

    def _on_speed(self, sc) -> None:
        self._debounce("pointer_speed", lambda: int(sc.get_value()))

    def _on_dpi(self, dd, _p) -> None:
        if not self._updating and self.dpi_choices:
            self._write("dpi", self.dpi_choices[dd.get_selected()])

    def _on_switch(self, row, _p, key) -> None:
        if not self._updating:
            self._write(key, bool(row.get_active()))

    def _on_smartshift(self, *_a) -> None:
        if self._updating:
            return
        self.ss_box.set_sensitive(self.ss_switch.get_active())
        self._debounce("smartshift", lambda: {
            "enabled": bool(self.ss_switch.get_active()), "threshold": int(self.ss_scale.get_value())})

    def update(self, device: dict) -> None:
        self.device = device
        app = self.app_id
        self._updating = True
        try:
            def eff(key):
                return logic.effective_setting(device, app, key)
            if app:
                self.profile_note.set_visible(True)
                self.profile_note.set_label(f"Ajustes do perfil: {self.ctx.apps.name_of(app)}. "
                                            "O que não for alterado continua herdando de Todos os aplicativos.")
            else:
                self.profile_note.set_visible(False)
            if hasattr(self, "speed"):
                v, over = eff("pointer_speed")
                self.speed.set_value((v or {}).get("value", self._lo))
                self.badges["pointer_speed"].show_state(bool(app), over)
            if hasattr(self, "dpi_dd"):
                v, over = eff("dpi")
                if (v or {}).get("value") in self.dpi_choices:
                    self.dpi_dd.set_selected(self.dpi_choices.index(v["value"]))
                self.badges["dpi"].show_state(bool(app), over)
            for key, row in self.rows.items():
                v, over = eff(key)
                row.set_active(bool((v or {}).get("value")))
                self.badges[key].show_state(bool(app), over)
            if hasattr(self, "ss_switch"):
                v, over = eff("smartshift")
                v = v or {}
                self.ss_switch.set_active(bool(v.get("enabled")))
                self.ss_scale.set_value(v.get("threshold", 30))
                self.ss_box.set_sensitive(bool(v.get("enabled")))
                self.badges["smartshift"].show_state(bool(app), over)
        finally:
            self._updating = False
