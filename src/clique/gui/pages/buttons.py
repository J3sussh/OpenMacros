"""Aba BOTÕES: foto grande com hotspots + painel lateral de ações (com perfis por aplicativo)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..widgets.action_panel import ActionPanel  # noqa: E402
from ..widgets.device_art import DeviceArt  # noqa: E402


class ButtonsPage(Gtk.Box):
    def __init__(self, device: dict, ctx):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.ctx = ctx
        self.device = device
        self.app_id = ""  # perfil selecionado ("" = Todos os aplicativos)
        self.selected: int | None = None
        self.controls = {int(c["cid"]): c for c in device.get("controls") or [] if logic.is_configurable(c)}
        layout, _generic = logic.resolve_layout(device)
        self.art = DeviceArt(str(logic.layout_art_file(layout)), layout.aspect)
        for m in layout.markers:
            self.art.add_marker(m, self.controls[m.cid].get("name", f"Controle {m.cid}"))
        self.art.connect("marker-clicked", self._on_marker)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.hint = Gtk.Label(label="Clique em um ponto da imagem para personalizar o botão.", wrap=True, margin_top=8)
        self.hint.add_css_class("dim-label")
        left.append(self.hint)
        left.append(self.art)
        self.append(left)

        self.panel = ActionPanel(ctx)
        self.panel.connect("close", lambda *_: self._close_panel())
        self.panel.connect("inherit", lambda *_: self._inherit())
        self.panel.connect("suggest", lambda *_: self._suggest())
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT,
                                     transition_duration=220, child=self.panel, reveal_child=False,
                                     hexpand=False)
        self.append(self.revealer)
        self.update(device)

    # ---- perfil
    def set_profile(self, app_id: str) -> None:
        self.app_id = app_id
        self.update(self.device)
        if self.selected is not None:
            self._configure_panel(self.selected)

    def _effective(self, cid: int) -> tuple[dict | None, str]:
        return logic.effective_action(self.device, self.app_id, cid)

    def update(self, device: dict) -> None:
        self.device = device
        for cid in self.controls:
            action, src = self._effective(cid)
            inherited = bool(self.app_id) and src == "global"
            self.art.set_action_text(cid, logic.describe_action(action, self.ctx.smart_actions), inherited)
        if self.selected is not None and self.revealer.get_reveal_child():
            action, _ = self._effective(self.selected)
            if action != self.panel.action:
                self.panel.refresh(action)
            self._update_panel_context(self.selected)

    def _suggestion(self, cid: int) -> dict | None:
        if not self.app_id:
            return None
        return logic.suggestions_for(self.app_id, list(self.controls.values())).get(str(cid))

    def _update_panel_context(self, cid: int) -> None:
        if not self.app_id:
            self.panel.set_profile_context(None, False, None)
            return
        _, src = self._effective(cid)
        sug = self._suggestion(cid)
        action, _ = self._effective(cid)
        if sug is not None and sug == action and src == "app":
            sug = None
        self.panel.set_profile_context(self.ctx.apps.name_of(self.app_id), src == "app", sug)

    # ---- painel
    def _close_panel(self) -> None:
        self.revealer.set_reveal_child(False)
        self.selected = None
        self.art.set_selected(None)

    def _on_marker(self, _art, cid: int) -> None:
        if cid not in self.controls:
            return
        if self.selected == cid and self.revealer.get_reveal_child():
            self._close_panel()
            return
        self.selected = cid
        self.art.set_selected(cid)
        self._configure_panel(cid)
        self.revealer.set_reveal_child(True)

    def _configure_panel(self, cid: int) -> None:
        ctrl = self.controls[cid]
        action, _ = self._effective(cid)
        hosts = int((self.device.get("hosts") or {}).get("count", 3))
        self.panel.show_control(ctrl.get("name", f"Controle {cid}"), action, bool(ctrl.get("raw_xy")), hosts,
                                lambda a, c=cid: self._apply(c, a))
        self._update_panel_context(cid)

    def _apply(self, cid: int, action: dict) -> None:
        app = self.app_id

        def ok():
            logic.with_profile_assignment(self.device, app, cid, action)
            self.update(self.device)
        if app:
            self.ctx.client.set_profile_assignment(self.device["id"], app, cid, action, self.ctx.reporter(ok))
        else:
            self.ctx.client.set_assignment(self.device["id"], cid, action, self.ctx.reporter(ok))

    def _inherit(self) -> None:
        """'Usar o padrão de Todos os aplicativos': remove a sobreposição do perfil neste botão."""
        cid, app = self.selected, self.app_id
        if cid is None or not app:
            return

        def done(value, error):
            if error or value is False:
                # o daemon pode não aceitar 'null': grava o valor global explicitamente
                glob = (self.device.get("assignments") or {}).get(str(cid)) or {"type": "default"}
                self.ctx.client.set_profile_assignment(self.device["id"], app, cid, glob, self.ctx.reporter(
                    lambda: (logic.with_profile_assignment(self.device, app, cid, glob), self.update(self.device))))
                return
            logic.with_profile_assignment(self.device, app, cid, None)
            self.update(self.device)
            if self.selected == cid:
                self._configure_panel(cid)
        self.ctx.client.set_profile_assignment(self.device["id"], app, cid, None, done)

    def _suggest(self) -> None:
        cid = self.selected
        sug = self._suggestion(cid) if cid is not None else None
        if sug is not None:
            self._apply(cid, sug)
            self.panel.refresh(sug)
