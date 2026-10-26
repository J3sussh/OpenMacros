"""Aba Sobre."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import logic  # noqa: E402


class AboutPage(Adw.PreferencesPage):
    def __init__(self, device: dict, ctx):
        super().__init__()
        self.ctx = ctx
        self.dev_id = device["id"]
        info = Adw.PreferencesGroup(title="Dispositivo")
        self.rows: dict[str, Adw.ActionRow] = {}
        for key, title in (("name", "Nome"), ("model_id", "Modelo (PID)"), ("id", "Identificador"), ("connection", "Conexão")):
            row = Adw.ActionRow(title=title, subtitle_selectable=True)
            row.add_css_class("property")
            info.add(row)
            self.rows[key] = row
        self.add(info)

        feats = Adw.PreferencesGroup()
        self.feat_row = Adw.ExpanderRow(title="Recursos HID++")
        feats.add(self.feat_row)
        self.add(feats)
        self._feat_rows: list[Adw.ActionRow] = []

        reset = Adw.PreferencesGroup(title="Restaurar", description="Remove a configuração salva e devolve os botões ao comportamento de fábrica.")
        btn = Gtk.Button(label="Restaurar padrões", halign=Gtk.Align.START)
        btn.add_css_class("destructive-action")
        btn.connect("clicked", self._confirm)
        reset.add(btn)
        self.add(reset)
        self.update(device)

    def update(self, device: dict) -> None:
        self.rows["name"].set_subtitle(device.get("name", ""))
        self.rows["model_id"].set_subtitle(str(device.get("model_id", "")))
        self.rows["id"].set_subtitle(device.get("id", ""))
        self.rows["connection"].set_subtitle(logic.connection_label(device.get("connection")))
        feats = device.get("features") or []
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
        dlg = Adw.AlertDialog.new("Restaurar padrões?", "Todas as atribuições de botões e ajustes salvos deste dispositivo serão removidos.")
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
