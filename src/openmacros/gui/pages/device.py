"""Página de um dispositivo: cabeçalho, abas de texto e conteúdo."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from .about import AboutPage  # noqa: E402
from .buttons import ButtonsPage  # noqa: E402
from .easyswitch import EasySwitchPage  # noqa: E402
from .pointer import PointerPage  # noqa: E402
from ..widgets.app_picker import AppPickerDialog  # noqa: E402
from ..widgets.profile_bar import ProfileBar  # noqa: E402

TABS = {
    "buttons": ("BOTÕES", ButtonsPage),
    "pointer": ("APONTAR E ROLAR", PointerPage),
    "easyswitch": ("EASY-SWITCH", EasySwitchPage),
    "about": ("SOBRE", AboutPage),
}


class TabBar(Gtk.ScrolledWindow):
    """Abas de texto com a seção ativa sublinhada (botões de rádio, acessíveis por teclado)."""

    def __init__(self, stack: Adw.ViewStack):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.EXTERNAL, vscrollbar_policy=Gtk.PolicyType.NEVER)
        self.stack = stack
        self.box = Gtk.Box(spacing=28, halign=Gtk.Align.CENTER, hexpand=True)
        self.box.add_css_class("tab-bar")
        self.set_child(self.box)
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._group: Gtk.ToggleButton | None = None
        self._syncing = False
        stack.connect("notify::visible-child-name", self._sync)

    def rebuild(self, keys: list[str]) -> None:
        for b in self._buttons.values():
            self.box.remove(b)
        self._buttons.clear()
        self._group = None
        for key in keys:
            b = Gtk.ToggleButton(label=TABS[key][0])
            b.add_css_class("tab")
            b.add_css_class("flat")
            if self._group is not None:
                b.set_group(self._group)
            else:
                self._group = b
            b.connect("toggled", self._on_toggled, key)
            self.box.append(b)
            self._buttons[key] = b
        self._sync()

    def _on_toggled(self, btn, key: str) -> None:
        if btn.get_active() and not self._syncing:
            self.stack.set_visible_child_name(key)

    def _sync(self, *_a) -> None:
        self._syncing = True
        try:
            name = self.stack.get_visible_child_name()
            for key, b in self._buttons.items():
                b.set_active(key == name)
        finally:
            self._syncing = False


class DevicePage(Adw.NavigationPage):
    def __init__(self, device: dict, ctx):
        super().__init__(title=device.get("name", "Dispositivo"))
        self.ctx = ctx
        self.device = device
        self.dev_id = device["id"]
        self._signature: tuple | None = None
        self._pages: dict[str, Gtk.Widget] = {}
        self.add_css_class("device-page")

        self.view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        self.title_label = Gtk.Label(label=device.get("name", ""))
        self.title_label.add_css_class("device-title")
        self.indicator = Gtk.Label()
        self.indicator.add_css_class("profile-indicator")
        self.indicator.set_visible(False)
        tbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        tbox.append(self.title_label)
        tbox.append(self.indicator)
        header.set_title_widget(tbox)
        self.selected_app = ""
        self.pending: list[str] = []
        self._seen: set[str] = set()  # apps que já tiveram perfil de verdade neste dispositivo
        self.battery_icon = Gtk.Image()
        self.battery_label = Gtk.Label()
        self.battery_label.add_css_class("caption")
        bat = Gtk.Box(spacing=6)
        bat.add_css_class("battery-pill")
        bat.append(self.battery_icon)
        bat.append(self.battery_label)
        header.pack_end(bat)
        self.view.add_top_bar(header)

        self.stack = Adw.ViewStack()
        self.tabs = TabBar(self.stack)
        self.view.add_top_bar(self.tabs)
        self.profile_bar = ProfileBar()
        self.profile_bar.set_visible(False)
        self.profile_bar.connect("app-selected", lambda _b, a: self.select_app(a))
        self.profile_bar.connect("add-requested", lambda *_: self._add_app())
        self.profile_bar.connect("remove-requested", lambda _b, a: self._remove_app(a))
        self.profile_bar.connect("suggest-requested", lambda *_: self._suggest_all())
        self.view.add_top_bar(self.profile_bar)
        self.stack.connect("notify::visible-child-name", lambda *_: self._refresh_bar())
        self.banner = Adw.Banner(title="Dispositivo offline — as alterações só serão aplicadas quando ele voltar")
        self.view.add_top_bar(self.banner)
        self.view.set_content(self.stack)
        self.set_child(self.view)
        self.update(device)

    def _build(self, device: dict) -> None:
        for child in list(self._pages.values()):
            self.stack.remove(child)
        self._pages.clear()
        keys = logic.supported_tabs(device)
        for key in keys:
            page = TABS[key][1](device, self.ctx)
            self._pages[key] = page
            self.stack.add_named(page, key)
        self.tabs.rebuild(keys)
        self._apply_profile_to_pages()
        self._refresh_bar()

    # ---- perfis por aplicativo
    def _apply_profile_to_pages(self) -> None:
        for key in ("buttons", "pointer"):
            if key in self._pages:
                self._pages[key].set_profile(self.selected_app)

    def _refresh_bar(self) -> None:
        dev = self.device
        show = logic.supports_profiles(dev) and self.stack.get_visible_child_name() in ("buttons", "pointer")
        self.profile_bar.set_visible(show)
        if not show:
            return
        have = logic.profile_app_ids(dev)
        apps = have + [a for a in self.pending if a not in have]
        sug = bool(self.selected_app) and self.stack.get_visible_child_name() == "buttons" and bool(
            logic.suggestions_for(self.selected_app, dev.get("controls") or []))
        self.profile_bar.set_state(apps, self.selected_app, self.ctx.apps.entry, sug)

    def select_app(self, app_id: str) -> None:
        # F7: perfil que ficou vazio (o serviço o removeu — B4) some assim que o usuário sai dele
        have = logic.profile_app_ids(self.device)
        self.pending = [a for a in self.pending if a == app_id or a in have or a not in self._seen]
        self.selected_app = app_id
        self._apply_profile_to_pages()
        self._refresh_bar()

    def _add_app(self) -> None:
        exclude = set(logic.profile_app_ids(self.device)) | set(self.pending)

        def picked(entry) -> None:
            if entry.app_id not in self.pending and entry.app_id not in logic.profile_app_ids(self.device):
                self.pending.append(entry.app_id)
            self.select_app(entry.app_id)
        AppPickerDialog(self.ctx, picked, exclude=exclude).present(self.get_root())

    def _remove_app(self, app_id: str) -> None:
        def forget() -> None:
            self.pending = [a for a in self.pending if a != app_id]
            self.device.get("profiles", {}).pop(app_id, None)
            if self.selected_app == app_id:
                self.selected_app = ""
            self._apply_profile_to_pages()
            for page in self._pages.values():
                page.update(self.device)
            self._refresh_bar()
        if app_id in logic.profile_app_ids(self.device):
            self.ctx.client.remove_profile(self.dev_id, app_id, self.ctx.reporter(forget))
        else:
            forget()

    def _suggest_all(self) -> None:
        app = self.selected_app
        sugs = logic.suggestions_for(app, self.device.get("controls") or [])
        if not sugs:
            return
        name = self.ctx.apps.name_of(app)
        dlg = Adw.AlertDialog.new(f"Aplicar sugestões para {name}?",
                                  f"Isto define a ação de {len(sugs)} botão(ões) neste perfil, substituindo as atuais.")
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("apply", "Aplicar")
        dlg.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_close_response("cancel")

        def response(_d, r):
            if r != "apply":
                return
            for cid, action in sugs.items():
                def ok(c=int(cid), a=action):
                    logic.with_profile_assignment(self.device, app, c, a)
                    for page in self._pages.values():
                        page.update(self.device)
                    self._refresh_bar()
                self.ctx.client.set_profile_assignment(self.dev_id, app, int(cid), action, self.ctx.reporter(ok))
            self.ctx.toast("Sugestões aplicadas")
        dlg.connect("response", response)
        dlg.present(self.get_root())

    def set_active_app(self, app: dict | None) -> None:
        self.ctx.active_app = app or {}
        self._update_indicator()

    def _update_indicator(self) -> None:
        text = logic.profile_indicator(self.device, self.ctx.active_app, self.ctx.apps.name_of)
        self.indicator.set_label(text)
        self.indicator.set_visible(bool(text))
        (self.indicator.add_css_class if self.device.get("active_profile") else self.indicator.remove_css_class)("active")

    def update(self, device: dict) -> None:
        self.device = device
        self.set_title(device.get("name", "Dispositivo"))
        self.title_label.set_label(device.get("name", "Dispositivo").upper())
        bat = device.get("battery")
        self.battery_icon.set_from_icon_name(logic.battery_icon(bat))
        self.battery_label.set_label(logic.battery_text(bat))
        self.battery_icon.get_parent().set_visible(bool(bat))
        sig = (tuple(logic.supported_tabs(device)),
               tuple(int(c["cid"]) for c in device.get("controls") or []),
               (device.get("hosts") or {}).get("count"),
               tuple(sorted((device.get("settings") or {}).keys())),
               device.get("layout"), str(logic.art_path(device)))
        if sig != self._signature:
            self._signature = sig
            self._build(device)
        else:
            for page in self._pages.values():
                page.update(device)
        self.banner.set_revealed(not bool(device.get("online", True)))
        have = logic.profile_app_ids(device)
        self._seen.update(have)
        for gone in self._seen - set(have):
            if gone != self.selected_app:
                self.pending = [a for a in self.pending if a != gone]
        if self.selected_app and self.selected_app not in have and self.selected_app in self._seen \
                and self.selected_app not in self.pending:
            self.pending.append(self.selected_app)  # fica visível até o usuário sair dele
        if self.selected_app and self.selected_app not in have and self.selected_app not in self.pending:
            self.selected_app = ""
            self._apply_profile_to_pages()
        self._refresh_bar()
        self._update_indicator()
