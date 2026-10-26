"""Diálogo de Preferências (V2/F2): notificações, IA e backup. Fala com o serviço via OpenMacrosClient."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..dbus_client import is_unsupported  # noqa: E402
from ..toasts import new_toast  # noqa: E402
from .fileio import MAX_IMPORT_BYTES, read_text_limited  # noqa: E402,F401
from .risk_dialog import confirm_risks  # noqa: E402


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, ctx):
        super().__init__(title="Preferências", search_enabled=False)
        self.ctx = ctx
        self._syncing = False
        self._prefs = logic.normalize_preferences(ctx.preferences)
        self.set_content_width(560)

        page = Adw.PreferencesPage(icon_name="emblem-system-symbolic", title="Geral")
        self.add(page)

        notif = Adw.PreferencesGroup(
            title="Notificações", description="Avisos do sistema mostrados pelo serviço do OpenMacros+.")
        self.row_battery = Adw.SwitchRow(title="Avisar quando a bateria estiver baixa")
        self.row_threshold = Adw.SpinRow.new_with_range(*logic.BATTERY_THRESHOLD_RANGE, 1)
        self.row_threshold.set_title("Avisar abaixo de")
        self.row_threshold.set_subtitle("Porcentagem de bateria. Abaixo de 5% o aviso é sempre crítico.")
        self.row_profile = Adw.SwitchRow(title="Mostrar o perfil ao trocar de aplicativo",
                                         subtitle="Uma mensagem rápida na tela, como “Perfil: Firefox”.")
        self.row_gestures = Adw.SwitchRow(title="Mostrar a ação dos gestos",
                                          subtitle="Uma mensagem rápida, como “Gesto ↑ — Nova aba”.")
        self.row_connect = Adw.SwitchRow(title="Avisar quando um dispositivo conectar ou desconectar")
        for r in (self.row_battery, self.row_threshold, self.row_profile, self.row_gestures, self.row_connect):
            notif.add(r)
        page.add(notif)

        ai = Adw.PreferencesGroup(
            title="Inteligência artificial",
            description="Como o prompt chega ao serviço escolhido. Vale para novas ações “Perguntar à IA”.")
        self.row_delivery = Adw.ComboRow(title="Entrega padrão")
        self._delivery_keys = list(logic.AI_DELIVERIES)
        self.row_delivery.set_model(Gtk.StringList.new(list(logic.AI_DELIVERIES.values())))
        self.row_delivery.set_subtitle("Pela URL, o texto fica no histórico do navegador.")
        ai.add(self.row_delivery)
        page.add(ai)

        backup = Adw.PreferencesGroup(
            title="Backup", description="Salve todas as configurações em um arquivo ou restaure a partir dele.")
        exp = Adw.ActionRow(title="Exportar configurações…", subtitle="Perfis, botões, Smart Actions e preferências. O arquivo pode conter "
                                    "textos e comandos das suas ações; guarde-o com cuidado.",
                            activatable=True)
        exp.add_suffix(Gtk.Image.new_from_icon_name("document-save-symbolic"))
        exp.connect("activated", lambda *_: self._export())
        imp = Adw.ActionRow(title="Importar configurações…", subtitle="Restaura um arquivo de backup do OpenMacros+.",
                            activatable=True)
        imp.add_suffix(Gtk.Image.new_from_icon_name("document-open-symbolic"))
        imp.connect("activated", lambda *_: self._import())
        backup.add(exp)
        backup.add(imp)
        page.add(backup)

        self.row_battery.connect("notify::active", self._on_switch, "notify_battery")
        self.row_profile.connect("notify::active", self._on_switch, "osd_profile")
        self.row_gestures.connect("notify::active", self._on_switch, "osd_gestures")
        self.row_connect.connect("notify::active", self._on_switch, "notify_connection")
        self.row_threshold.connect("notify::value", self._on_threshold)
        self.row_delivery.connect("notify::selected", self._on_delivery)
        self._apply(self._prefs)
        ctx.client.get_preferences(self._loaded)
        self._sig = ctx.client.connect("preferences-changed", lambda _c, p: self._apply(logic.normalize_preferences(p)))
        self.connect("closed", self._on_closed)

    def _on_closed(self, *_a) -> None:
        self.ctx.client.disconnect(self._sig)
        if getattr(self, "_thr_timer", 0):  # limiar pendente: não dispara depois do diálogo fechado
            GLib.source_remove(self._thr_timer)
            self._thr_timer = 0

    # ---- estado
    def _loaded(self, prefs, error) -> None:
        if error:
            self.add_toast(new_toast(error))
            return
        self.ctx.preferences = logic.normalize_preferences(prefs)
        self._apply(self.ctx.preferences)

    def _apply(self, prefs: dict) -> None:
        self._prefs = prefs
        self._syncing = True
        try:
            self.row_battery.set_active(prefs["notify_battery"])
            if not getattr(self, "_thr_timer", 0):  # edição do limiar ainda pendente: não sobrescrever
                self.row_threshold.set_value(prefs["battery_threshold"])
            self.row_threshold.set_sensitive(prefs["notify_battery"])
            self.row_profile.set_active(prefs["osd_profile"])
            self.row_gestures.set_active(prefs["osd_gestures"])
            self.row_connect.set_active(prefs["notify_connection"])
            self.row_delivery.set_selected(self._delivery_keys.index(prefs["ai_delivery_default"]))
        finally:
            self._syncing = False

    def _save(self, key: str, value) -> None:
        old = self._prefs[key]

        def done(ok, error) -> None:
            if error or ok is False:
                self.add_toast(new_toast(error or "O serviço recusou a preferência"))
                self._apply({**self._prefs, key: old})
                return
            self._prefs = {**self._prefs, key: value}
            self.ctx.preferences = self._prefs
        self._prefs = {**self._prefs, key: value}
        self.row_threshold.set_sensitive(self._prefs["notify_battery"])
        self.ctx.client.set_preference(key, value, done)

    def _on_switch(self, row, _p, key: str) -> None:
        if not self._syncing:
            self._save(key, row.get_active())

    def _on_threshold(self, row, _p) -> None:
        if self._syncing:
            return
        if getattr(self, "_thr_timer", 0):
            GLib.source_remove(self._thr_timer)

        def fire():
            self._thr_timer = 0
            self._save("battery_threshold", int(row.get_value()))
            return False
        self._thr_timer = GLib.timeout_add(400, fire)

    def _on_delivery(self, row, _p) -> None:
        if not self._syncing:
            self._save("ai_delivery_default", self._delivery_keys[row.get_selected()])

    # ---- backup
    def _toast(self, text: str) -> None:
        self.add_toast(new_toast(text))

    def _export(self) -> None:
        def got(text, error) -> None:
            if error:
                self._toast(f"Não foi possível exportar: {error}")
                return
            fd = Gtk.FileDialog(title="Exportar configurações", initial_name=logic.backup_filename())
            fd.set_filters(self._filters())

            def chosen(dlg, res) -> None:
                try:
                    f = dlg.save_finish(res)
                except GLib.Error:
                    return  # cancelado
                try:
                    f.replace_contents(text.encode(), None, False, Gio.FileCreateFlags.PRIVATE, None)
                except GLib.Error as e:
                    self._toast(f"Não foi possível gravar o arquivo: {e.message}")
                    return
                self._toast("Configurações exportadas. O arquivo pode conter textos e comandos das ações.")
            fd.save(self.get_root() if isinstance(self.get_root(), Gtk.Window) else None, None, chosen)
        self.ctx.client.export_config(got)

    @staticmethod
    def _filters() -> Gio.ListStore:
        flt = Gtk.FileFilter(name="Backup do OpenMacros+ (JSON)")
        flt.add_suffix("json")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(flt)
        return store

    def _parent_window(self):
        return self.get_root() if isinstance(self.get_root(), Gtk.Window) else None

    def _import(self) -> None:
        fd = Gtk.FileDialog(title="Importar configurações")
        fd.set_filters(self._filters())

        def chosen(dlg, res) -> None:
            try:
                f = dlg.open_finish(res)
            except GLib.Error:
                return
            loaded(f)

        def chosen_file(text, error) -> None:
            if error:
                self._toast(error)
                return
            try:
                data = logic.validate_import(text)
            except ValueError as e:
                self._toast(str(e))
                return
            confirm_risks(self, logic.collect_risks(data), "Este backup", "Continuar",
                          lambda: self._confirm_import(text))

        def loaded(f) -> None:
            read_text_limited(f, chosen_file)
        fd.open(self._parent_window(), None, chosen)

    def _confirm_import(self, text: str) -> None:
        dlg = Adw.AlertDialog.new(
            "Como importar?",
            "Mesclar mantém o que você já tem e acrescenta ou atualiza o conteúdo do arquivo. "
            "Substituir apaga as configurações atuais e usa só o arquivo.")
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("replace", "Substituir tudo")
        dlg.add_response("merge", "Mesclar")
        dlg.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("merge", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("merge")
        dlg.set_close_response("cancel")

        def response(_d, r: str) -> None:
            if r not in ("merge", "replace"):
                return

            def done(ok, error) -> None:
                if error:
                    self._toast(f"Importação falhou: {error}")
                elif ok is False:
                    self._toast("O serviço recusou o arquivo")
                else:
                    self._toast("Configurações importadas")
                    self.ctx.client.get_preferences(self._loaded)
            self.ctx.client.import_config(text, r == "merge", done)
        dlg.connect("response", response)
        dlg.present(self)


__all__ = ["PreferencesDialog", "is_unsupported"]
