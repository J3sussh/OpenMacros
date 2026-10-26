"""Aba SOBRE: foto à esquerda; nome, estado e identificação do dispositivo à direita."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..widgets.imaging import new_picture, set_image  # noqa: E402

# campos opcionais do Device JSON (só aparecem se o serviço os informar)
OPTIONAL_FIELDS = (
    ("firmware", "Firmware"), ("firmware_version", "Firmware"), ("fw_version", "Firmware"),
    ("protocol", "Protocolo HID++"), ("hidpp_version", "Protocolo HID++"),
    ("serial", "Número de série"), ("unit_id", "ID da unidade"),
)


def kv_row(title: str, value: str, selectable: bool = False) -> Gtk.Box:
    row = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8)
    t = Gtk.Label(label=title, xalign=0, hexpand=True)
    t.add_css_class("dim-label")
    v = Gtk.Label(label=value, xalign=1, selectable=selectable, wrap=True, max_width_chars=34)
    v.add_css_class("value-label")
    row.append(t)
    row.append(v)
    row.value = v  # type: ignore[attr-defined]
    row.update_property([Gtk.AccessibleProperty.LABEL], [title])
    return row


class AboutPage(Gtk.ScrolledWindow):
    def __init__(self, device: dict, ctx):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.ctx = ctx
        self.dev_id = device["id"]
        outer = Gtk.Box(spacing=40, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.picture = new_picture(logic.art_path(device), (200, 300), (340, 520))
        outer.append(self.picture)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        right.set_size_request(380, -1)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("page-title")
        right.append(self.title)
        chips = Gtk.Box(spacing=8)
        self.state_chip = Gtk.Label()
        self.state_chip.add_css_class("chip")
        self.conn_chip = Gtk.Label()
        self.conn_chip.add_css_class("chip")
        chips.append(self.state_chip)
        chips.append(self.conn_chip)
        right.append(chips)

        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.card.add_css_class("openmacros-card")
        right.append(self.card)
        self._rows: dict[str, Gtk.Box] = {}
        self._optional: list[Gtk.Widget] = []

        self.feat_row = Adw.ExpanderRow(title="Recursos HID++")
        self.feat_row.add_css_class("card")
        self._feat_rows: list[Adw.ActionRow] = []
        right.append(self.feat_row)

        reset = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8)
        rt = Gtk.Label(label="RESTAURAR", xalign=0)
        rt.add_css_class("section-title")
        rd = Gtk.Label(label="Remove a configuração salva, inclusive os perfis por aplicativo, e devolve os botões ao comportamento de fábrica.",
                       xalign=0, wrap=True)
        rd.add_css_class("dim-label")
        btn = Gtk.Button(label="Restaurar padrões", halign=Gtk.Align.START)
        btn.add_css_class("destructive-action")
        btn.add_css_class("pill-small")
        btn.connect("clicked", self._confirm)
        for w in (rt, rd, btn):
            reset.append(w)
        right.append(reset)
        outer.append(right)
        self.set_child(Adw.Clamp(maximum_size=980, child=outer))
        self.update(device)

    def _set_row(self, key: str, title: str, value: str) -> None:
        row = self._rows.get(key)
        if row is None:
            row = kv_row(title, value, selectable=key == "id" or key.startswith("opt:"))
            self._rows[key] = row
            self.card.append(row)
        else:
            row.value.set_label(value)

    def update(self, device: dict) -> None:
        online = bool(device.get("online", True))
        self.title.set_label(device.get("name", "Dispositivo"))
        self.state_chip.set_label("Online" if online else "Offline")
        (self.state_chip.remove_css_class if online else self.state_chip.add_css_class)("over")
        self.conn_chip.set_label(logic.connection_label(device.get("connection")))
        set_image(self.picture, logic.art_path(device))
        self._set_row("model", "Modelo (PID)", str(device.get("model_id", "")) or "—")
        self._set_row("battery", "Bateria", logic.battery_text(device.get("battery")))
        self._set_row("id", "Identificador", device.get("id", ""))
        seen: set[str] = set()
        for key, title in OPTIONAL_FIELDS:
            val = device.get(key)
            if val in (None, "", 0) or title in seen:
                continue
            seen.add(title)
            self._set_row("opt:" + title, title, str(val))
        feats = device.get("features") or []
        self.feat_row.set_visible(bool(feats))
        self.feat_row.set_subtitle(f"{len(feats)} recursos")
        if feats != getattr(self, "_feats", None):
            self._feats = list(feats)
            for r in self._feat_rows:
                self.feat_row.remove(r)
            self._feat_rows = []
            for f in feats:
                r = Adw.ActionRow(title=str(f))
                r.add_css_class("monospace")
                self.feat_row.add_row(r)
                self._feat_rows.append(r)

    def _confirm(self, btn) -> None:
        dlg = Adw.AlertDialog.new("Restaurar padrões?", "Todas as atribuições de botões e ajustes salvos deste dispositivo serão removidos, incluindo os perfis por aplicativo do dispositivo. Esta ação não pode ser desfeita.")
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("reset", "Restaurar")
        dlg.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.connect("response", self._on_response)
        dlg.present(self.get_root())

    def _on_response(self, _dlg, response: str) -> None:
        if response == "reset":
            self.ctx.client.reset_device(self.dev_id, self.ctx.reporter(
                lambda: self.ctx.toast("Padrões restaurados")))
