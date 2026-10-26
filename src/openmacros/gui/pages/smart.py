"""Smart Actions v2 ("Se… Então…"): abas Minhas/Modelos, cartões e editor com gatilhos, ações e gravador."""

from __future__ import annotations

import json
import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..widgets.fileio import read_text_limited  # noqa: E402
from ..widgets.risk_dialog import confirm_risks  # noqa: E402
from ..widgets.smart_dialogs import NameDialog, StepDialog, TriggerDialog  # noqa: E402


def _icon_label(icon: str, title: str, subtitle: str) -> Gtk.Box:
    box = Gtk.Box(spacing=14)
    img = Gtk.Image.new_from_icon_name(icon)
    img.set_pixel_size(24)
    img.add_css_class("sa-icon")
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
    t = Gtk.Label(label=title, xalign=0, ellipsize=3)
    t.add_css_class("card-title")
    texts.append(t)
    if subtitle:
        s = Gtk.Label(label=subtitle, xalign=0, ellipsize=3)
        s.add_css_class("dim-label")
        texts.append(s)
    box.append(img)
    box.append(texts)
    return box


def _flat_btn(icon: str, tip: str, cb) -> Gtk.Button:
    b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER)
    b.add_css_class("flat")
    b.add_css_class("circular")
    b.update_property([Gtk.AccessibleProperty.LABEL], [tip])
    b.connect("clicked", lambda *_: cb())
    return b


def _caption(text: str, wrap: bool = True) -> Gtk.Label:
    lab = Gtk.Label(label=text, xalign=0, wrap=wrap, max_width_chars=48 if wrap else -1)
    lab.add_css_class("caption")
    lab.add_css_class("dim-label")
    return lab


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "smart-action"


def _json_filters() -> Gio.ListStore:
    flt = Gtk.FileFilter(name="Smart Action do OpenMacros+ (JSON)")
    flt.add_suffix("json")
    store = Gio.ListStore.new(Gtk.FileFilter)
    store.append(flt)
    return store


def _cards_flow() -> Gtk.FlowBox:
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=1, max_children_per_line=2,
                       column_spacing=12, row_spacing=12, homogeneous=True, valign=Gtk.Align.START)


def _add_card(flow: Gtk.FlowBox, card: Gtk.Widget) -> None:
    flow.append(card)
    card.get_parent().set_focusable(False)


def _clear(box: Gtk.Widget) -> None:
    while (c := box.get_first_child()) is not None:
        box.remove(c)


class SmartActionsPage(Adw.NavigationPage):
    """Abas "Minhas Smart Actions" e "Modelos"."""

    def __init__(self, ctx):
        super().__init__(title="Smart Actions", tag="smart")
        self.ctx = ctx
        self.sort = "recent"
        self._syncing = False
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        title = Gtk.Label(label="SMART ACTIONS")
        title.add_css_class("device-title")
        header.set_title_widget(title)
        new = Gtk.Button(label="Criar", tooltip_text="Criar uma Smart Action em branco")
        new.add_css_class("suggested-action")
        new.connect("clicked", lambda *_: self.ctx.open_smart_editor(None, None))
        imp = Gtk.Button(label="Importar…", tooltip_text="Importar uma Smart Action exportada")
        imp.connect("clicked", lambda *_: self._import())
        self.import_btn = imp
        header.pack_end(new)
        header.pack_end(imp)
        view.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=12, margin_bottom=28,
                      margin_start=20, margin_end=20)
        bar = Gtk.Box(spacing=8)
        self.tab_mine = Gtk.ToggleButton(label="Minhas Smart Actions", active=True)
        self.tab_tpl = Gtk.ToggleButton(label="Modelos", group=self.tab_mine)
        for b in (self.tab_mine, self.tab_tpl):
            b.add_css_class("profile-chip")
            bar.append(b)
        spacer = Gtk.Box(hexpand=True)
        bar.append(spacer)
        self.sort_dd = Gtk.DropDown.new_from_strings([label for _, label in logic.SA_SORTS])
        self.sort_dd.set_tooltip_text("Ordenar")
        self.sort_dd.update_property([Gtk.AccessibleProperty.LABEL], ["Ordenar Smart Actions"])
        self.sort_dd.connect("notify::selected", self._on_sort)
        bar.append(self.sort_dd)
        box.append(bar)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        self.mine_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.tpl_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.stack.add_named(self.mine_box, "mine")
        self.stack.add_named(self.tpl_box, "templates")
        box.append(self.stack)
        self.tab_mine.connect("toggled", self._on_tab)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=Adw.Clamp(maximum_size=900, child=box))
        view.set_content(sw)
        self.set_child(view)
        self._build_templates()
        self.refresh()

    # ---- abas
    def _on_tab(self, *_a) -> None:
        mine = self.tab_mine.get_active()
        self.stack.set_visible_child_name("mine" if mine else "templates")
        self.sort_dd.set_visible(mine)

    def _on_sort(self, *_a) -> None:
        self.sort = logic.SA_SORTS[self.sort_dd.get_selected()][0]
        self.refresh()

    # ---- helpers de nome
    def _name_of(self, app_id: str) -> str:
        return self.ctx.apps.name_of(app_id)

    def _dev_name(self, dev_id: str) -> str:
        return self.ctx.devices.get(dev_id, {}).get("name", dev_id)

    # ---- minhas
    def refresh(self) -> None:
        _clear(self.mine_box)
        self.import_btn.set_visible(self.ctx.sa_supported("import"))
        sas = self.ctx.smart_actions
        if not sas:
            st = Adw.StatusPage(icon_name="system-run-symbolic", title="Nenhuma Smart Action",
                                description="Clique em Criar para adicionar sua primeira Smart Action")
            st.add_css_class("compact")
            row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
            create = Gtk.Button(label="Criar")
            create.add_css_class("suggested-action")
            create.add_css_class("pill")
            create.connect("clicked", lambda *_: self.ctx.open_smart_editor(None, None))
            tpl = Gtk.Button(label="Ver modelos")
            tpl.add_css_class("pill")
            tpl.connect("clicked", lambda *_: self.tab_tpl.set_active(True))
            row.append(create)
            row.append(tpl)
            st.set_child(row)
            self.mine_box.append(st)
            return
        flow = _cards_flow()
        for sid, sa in logic.sort_smart_actions(sas, self.sort):
            _add_card(flow, self._card(sid, sa))
        self.mine_box.append(flow)

    def _card(self, sid: str, sa: dict) -> Gtk.Widget:
        enabled = bool(sa.get("enabled", True))
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("openmacros-card")
        card.add_css_class("sa-card")
        if not enabled:
            card.add_css_class("sa-off")
        name = sa.get("name", sid)
        head = Gtk.Box(spacing=6)
        titles = _icon_label(sa.get("icon") or logic.SA_DEFAULT_ICON, name, sa.get("description") or "")
        titles.set_hexpand(True)
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self.ctx.open_smart_editor(sa, sid))
        titles.add_controller(click)
        head.append(titles)
        head.append(self._menu(sid, sa))
        card.append(head)
        summary = logic.smart_summary(sa, self._name_of, self._dev_name, logic.button_triggers(self.ctx.devices, sid))
        s = _caption(summary)
        s.set_selectable(False)
        card.append(s)
        errs = logic.trigger_error_map(sa)
        if errs:
            e = Gtk.Label(label="⚠ " + " ".join(sorted(set(errs.values()))), xalign=0, wrap=True)
            e.add_css_class("caption")
            e.add_css_class("error")
            card.append(e)
        foot = Gtk.Box(spacing=8)
        if self.ctx.sa_supported("enabled"):
            sw = Gtk.Switch(active=enabled, valign=Gtk.Align.CENTER)
            sw.update_property([Gtk.AccessibleProperty.LABEL], [f"Ativar {name}"])
            lab = Gtk.Label(label="Ativa" if enabled else "Inativa", xalign=0)
            lab.add_css_class("dim-label")
            sw.connect("notify::active", self._on_enabled, sid, lab)
            foot.append(sw)
            foot.append(lab)
        foot.append(Gtk.Box(hexpand=True))
        foot.append(_flat_btn("media-playback-start-symbolic", "Experimentar",
                              lambda s=sid: self.ctx.test_action({"type": "smart_action", "id": s})))
        card.append(foot)
        return card

    def _menu(self, sid: str, sa: dict) -> Gtk.MenuButton:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        entries = [("Editar", lambda: self.ctx.open_smart_editor(sa, sid)),
                   ("Duplicar", lambda: self._duplicate(sa))]
        if self.ctx.sa_supported("export"):
            entries.append(("Exportar…", lambda: self._export(sid, sa)))
        entries.append(("Excluir", lambda: self._delete(sid)))
        for label, cb in entries:
            b = Gtk.Button(label=label)
            b.add_css_class("flat")
            (lambda lb: lb.set_xalign(0))(b.get_child())
            b.connect("clicked", lambda _b, c=cb: (pop.popdown(), c()))
            if label == "Excluir":
                b.add_css_class("destructive-action")
            box.append(b)
        pop.set_child(box)
        mb = Gtk.MenuButton(icon_name="view-more-symbolic", popover=pop, valign=Gtk.Align.CENTER,
                            tooltip_text="Mais opções")
        mb.add_css_class("flat")
        mb.add_css_class("circular")
        mb.update_property([Gtk.AccessibleProperty.LABEL], [f"Mais opções de {sa.get('name', sid)}"])
        return mb

    def _on_enabled(self, sw, _p, sid: str, lab: Gtk.Label) -> None:
        if self._syncing:
            return
        on = sw.get_active()
        lab.set_label("Ativa" if on else "Inativa")

        def done(ok, error) -> None:
            if error or ok is False:
                if error and self.ctx.sa_failed("enabled", error):
                    self.ctx.toast("O serviço em execução não permite ativar/desativar Smart Actions")
                    self.refresh()
                    return
                self.ctx.toast(error or "O serviço recusou a operação")
                self._syncing = True
                sw.set_active(not on)
                lab.set_label("Ativa" if not on else "Inativa")
                self._syncing = False
        self.ctx.client.set_smart_action_enabled(sid, on, done)

    def _duplicate(self, sa: dict) -> None:
        copy = {k: json.loads(json.dumps(v)) for k, v in sa.items()
                if k in ("name", "description", "icon", "triggers", "steps")}
        copy["name"] = (str(sa.get("name", "Smart Action"))[:logic.SA_NAME_MAX - 8] + " (cópia)")
        inactive = self.ctx.sa_supported("enabled")
        if inactive:
            copy["enabled"] = False  # a cópia não duplica gatilhos até você ativá-la
        try:
            copy = logic.validate_smart_action(copy)
        except ValueError as e:
            self.ctx.toast(str(e))
            return

        def saved(res, error) -> None:
            if error:
                self.ctx.toast(error)
                return
            self.ctx.toast("Cópia criada" + (" (inativa até você ativá-la)" if inactive else ""))
        self.ctx.client.save_smart_action(copy, saved)

    def _delete(self, sid: str) -> None:
        name = self.ctx.smart_actions.get(sid, {}).get("name", sid)
        dlg = Adw.AlertDialog.new(f"Excluir “{name}”?", "Botões que usam esta Smart Action voltam ao padrão.")
        dlg.set_body_use_markup(False)
        dlg.set_heading_use_markup(False)
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("delete", "Excluir")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_default_response("cancel")
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, r: r == "delete" and self.ctx.client.delete_smart_action(
            sid, self.ctx.reporter()))
        dlg.present(self.get_root())

    # ---- exportar / importar
    def _export(self, sid: str, sa: dict) -> None:
        def got(text, error) -> None:
            if error:
                if self.ctx.sa_failed("export", error):
                    self.ctx.toast("O serviço em execução não exporta Smart Actions")
                    self.refresh()
                else:
                    self.ctx.toast(f"Não foi possível exportar: {error}")
                return
            fd = Gtk.FileDialog(title="Exportar Smart Action", initial_name=f"smart-action-{_slug(sa.get('name', ''))}.json")
            fd.set_filters(_json_filters())

            def chosen(dlg, res) -> None:
                try:
                    f = dlg.save_finish(res)
                except GLib.Error:
                    return
                try:
                    f.replace_contents(text.encode(), None, False, Gio.FileCreateFlags.PRIVATE, None)
                except GLib.Error as e:
                    self.ctx.toast(f"Não foi possível gravar o arquivo: {e.message}")
                    return
                self.ctx.toast("Smart Action exportada. O arquivo pode conter textos e comandos das ações.")
            fd.save(self.get_root(), None, chosen)
        self.ctx.client.export_smart_action(sid, got)

    def _import(self) -> None:
        fd = Gtk.FileDialog(title="Importar Smart Action")
        fd.set_filters(_json_filters())

        def chosen(dlg, res) -> None:
            try:
                f = dlg.open_finish(res)
            except GLib.Error:
                return
            read_text_limited(f, loaded)

        def loaded(text, error) -> None:
            if error:
                self.ctx.toast(error)
                return
            try:
                data = logic.validate_smart_import(text)
            except ValueError as e:
                self.ctx.toast(str(e))
                return
            confirm_risks(self.get_root(), logic.collect_risks(data), "Esta Smart Action", "Importar mesmo assim",
                          lambda: self._do_import(text))
        fd.open(self.get_root(), None, chosen)

    def _do_import(self, text: str) -> None:
        def done(sid, error) -> None:
            if error:
                if self.ctx.sa_failed("import", error):
                    self.ctx.toast("O serviço em execução não importa Smart Actions")
                    self.refresh()
                else:
                    self.ctx.toast(f"Importação falhou: {error}")
                return
            self.ctx.toast("Smart Action importada")
        self.ctx.client.import_smart_action(text, done)

    # ---- modelos
    def _build_templates(self) -> None:
        intro = _caption("Modelos prontos: ao usar, você recebe uma cópia que pode editar antes de salvar.")
        self.tpl_box.append(intro)
        flow = _cards_flow()
        for t in logic.SMART_TEMPLATES:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.add_css_class("openmacros-card")
            card.add_css_class("sa-card")
            card.append(_icon_label(t["icon"], t["name"], ""))
            d = Gtk.Label(label=t["description"], xalign=0, wrap=True, max_width_chars=40)
            d.add_css_class("dim-label")
            card.append(d)
            card.append(_caption(logic.smart_summary(t, self._name_of)))
            foot = Gtk.Box(spacing=8)
            foot.append(Gtk.Box(hexpand=True))
            use = Gtk.Button(label="Usar modelo", valign=Gtk.Align.END)
            use.add_css_class("pill-small")
            use.update_property([Gtk.AccessibleProperty.LABEL], [f"Usar o modelo {t['name']}"])
            use.connect("clicked", lambda *_a, tid=t["id"]: self._use_template(tid))
            foot.append(use)
            card.append(foot)
            _add_card(flow, card)
        self.tpl_box.append(flow)

    def _use_template(self, tid: str) -> None:
        draft = logic.smart_from_template(tid)
        confirm_risks(self.get_root(), logic.collect_risks(draft), "Este modelo", "Usar mesmo assim",
                      lambda: self.ctx.open_smart_editor(draft, None))


class StepRow(Gtk.ListBoxRow):
    pass


class SmartEditorPage(Adw.NavigationPage):
    """Editor "Se… / Então…". `draft` = Smart Action existente ou modelo; `sid` = id se já salva."""

    def __init__(self, ctx, draft: dict | None, sid: str | None, on_close):
        super().__init__(title="Editar Smart Action" if sid else "Nova Smart Action")
        self.ctx = ctx
        self.sid = sid
        self._on_close = on_close
        d = draft or {}
        self.name = str(d.get("name", ""))
        self.description = str(d.get("description", ""))
        self.icon = d.get("icon") if d.get("icon") in logic.SA_ICONS else logic.SA_DEFAULT_ICON
        self.enabled = d.get("enabled") if "enabled" in d else None
        self.steps: list[dict] = [dict(s) for s in d.get("steps") or []]
        self.triggers: list[dict] = [dict(t) for t in d.get("triggers") or [] if isinstance(t, dict)]
        self.buttons: list[dict] = logic.button_triggers(ctx.devices, sid)
        self._orig_buttons = [dict(b) for b in self.buttons]
        self._orig_triggers = [dict(t) for t in self.triggers] if sid else []
        self._errors = logic.trigger_error_map(ctx.smart_actions.get(sid or "", d))
        self._saved = self._snapshot()
        self._run_source = 0
        self._running = False

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        t = Gtk.Label(label=("EDITAR SMART ACTION" if sid else "NOVA SMART ACTION"))
        t.add_css_class("device-title")
        header.set_title_widget(t)
        save = Gtk.Button(label="Salvar")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._ask_name())
        header.pack_end(save)
        view.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=16, margin_bottom=28,
                      margin_start=20, margin_end=20)
        # identificação
        self.id_card = Gtk.Box(spacing=12)
        self.id_card.add_css_class("openmacros-card")
        self.id_icon = Gtk.Image(pixel_size=28)
        self.id_icon.add_css_class("sa-icon")
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        self.id_name = Gtk.Label(xalign=0, ellipsize=3)
        self.id_name.add_css_class("card-title")
        self.id_desc = Gtk.Label(xalign=0, ellipsize=3)
        self.id_desc.add_css_class("dim-label")
        texts.append(self.id_name)
        texts.append(self.id_desc)
        rename = Gtk.Button(label="Nome e ícone…", valign=Gtk.Align.CENTER)
        rename.add_css_class("pill-small")
        rename.connect("clicked", lambda *_: self._ask_name(save=False))
        self.id_card.append(self.id_icon)
        self.id_card.append(texts)
        self.id_card.append(rename)
        box.append(self.id_card)

        # Se…
        self.if_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.if_card.add_css_class("openmacros-card")
        box.append(self.if_card)

        # Então…
        steps_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        steps_card.add_css_class("openmacros-card")
        st = Gtk.Label(label="Então…", xalign=0)
        st.add_css_class("card-title")
        self.steps_count = _caption("")
        steps_card.append(st)
        steps_card.append(self.steps_count)
        self.steps_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.steps_list.add_css_class("steps-list")
        steps_card.append(self.steps_list)
        buttons = Gtk.Box(spacing=8, margin_top=6)
        add_a = Gtk.Button(label="Adicionar ação")
        add_a.add_css_class("pill-small")
        add_a.connect("clicked", lambda *_: self._edit_step(None))
        add_d = Gtk.Button(label="Adicionar atraso")
        add_d.add_css_class("pill-small")
        add_d.connect("clicked", lambda *_: self._add_delay())
        buttons.append(add_a)
        buttons.append(add_d)
        steps_card.append(buttons)
        box.append(steps_card)

        # rodapé
        box.append(_caption(logic.SA_SECRETS_NOTE))
        foot = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        self.test_all = Gtk.Button(label="Experimentar")
        self.test_all.set_tooltip_text("Executa todas as ações agora, na ordem")
        self.test_all.connect("clicked", lambda *_: self._try())
        foot.append(self.test_all)
        box.append(foot)
        view.set_content(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                            child=Adw.Clamp(maximum_size=760, child=box)))
        self.set_child(view)
        self.connect("hidden", lambda *_: self._cancel_run())
        self._render_id()
        self._render_triggers()
        self._render()

    # ---- estado
    def _snapshot(self) -> str:
        return json.dumps([self.name, self.description, self.icon, self.triggers, self.steps,
                           sorted((b["device_id"], b["app_id"], b["cid"]) for b in self.buttons)], sort_keys=True)

    def is_dirty(self) -> bool:
        return self._snapshot() != self._saved

    def _render_id(self) -> None:
        self.id_icon.set_from_icon_name(self.icon)
        self.id_name.set_label(self.name or "Sem nome")
        self.id_desc.set_label(self.description or "Sem descrição")

    # ---- Se…
    def _render_triggers(self) -> None:
        _clear(self.if_card)
        head = Gtk.Label(label="Se…", xalign=0)
        head.add_css_class("card-title")
        self.if_card.append(head)
        self.if_card.append(_caption("Gatilhos que iniciam esta Smart Action. Qualquer um deles basta (“Ou”)."))
        rows: list[tuple[str, dict, int]] = ([("button", b, i) for i, b in enumerate(self.buttons)]
                                             + [("trigger", t, i) for i, t in enumerate(self.triggers)])
        if not rows:
            self.if_card.append(_caption("Sem gatilho: ela só roda por um botão ou pelo botão Experimentar."))
        for n, (kind, trig, idx) in enumerate(rows):
            if n:
                ou = Gtk.Label(label="OU", xalign=0, margin_top=2, margin_bottom=2)
                ou.add_css_class("section-title")
                self.if_card.append(ou)
            self.if_card.append(self._trigger_row(kind, trig, idx))
        add = Gtk.Button(label="Adicionar gatilho", halign=Gtk.Align.START, margin_top=6)
        add.add_css_class("pill-small")
        add.connect("clicked", lambda *_: self._edit_trigger(None, None))
        add.set_sensitive(len(self.triggers) < logic.SA_MAX_TRIGGERS)
        self.if_card.append(add)

    def _trigger_row(self, kind: str, trig: dict, idx: int) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        row = Gtk.Box(spacing=8)
        if kind == "button":
            where = "" if not trig["app_id"] else f" em {self.ctx.apps.name_of(trig['app_id'])}"
            text = f"Botão {trig['label']} · {trig['device_name']}{where}"
            icon = "input-mouse-symbolic"
        else:
            names = lambda a: self.ctx.apps.name_of(a)  # noqa: E731
            text = logic.describe_trigger(trig, names, lambda d: self.ctx.devices.get(d, {}).get("name", d))
            icon = {"shortcut": "input-keyboard-symbolic", "app": "application-x-executable-symbolic",
                    "device": "computer-symbolic"}.get(trig.get("type"), "system-run-symbolic")
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class("sa-icon")
        lab = Gtk.Label(label=text, xalign=0, hexpand=True, ellipsize=3)
        row.append(img)
        row.append(lab)
        row.append(_flat_btn("document-edit-symbolic", "Editar gatilho", lambda k=kind, t=trig: self._edit_trigger(k, t)))
        row.append(_flat_btn("edit-delete-symbolic", "Remover gatilho", lambda k=kind, i=idx: self._remove_trigger(k, i)))
        outer.append(row)
        if kind == "trigger" and idx < len(self._orig_triggers) and self._orig_triggers[idx] == trig \
                and idx in self._errors:
            err = Gtk.Label(label="⚠ " + self._errors[idx], xalign=0, wrap=True, margin_start=26)
            err.add_css_class("caption")
            err.add_css_class("error")
            outer.append(err)
        return outer

    def _edit_trigger(self, kind: str | None, trig: dict | None) -> None:
        if kind is None and len(self.triggers) >= logic.SA_MAX_TRIGGERS:
            self.ctx.toast(f"No máximo {logic.SA_MAX_TRIGGERS} gatilhos")
            return

        def done(new: dict) -> None:
            if new.get("type") == "button":
                key = (new["device_id"], new["app_id"], new["cid"])
                if kind == "button" and trig is not None and trig in self.buttons:
                    self.buttons.remove(trig)
                if all((b["device_id"], b["app_id"], b["cid"]) != key for b in self.buttons):
                    self.buttons.append(new)
            else:
                if kind == "trigger" and trig is not None and trig in self.triggers:
                    self.triggers[self.triggers.index(trig)] = new
                else:
                    self.triggers.append(new)
            self._render_triggers()
        TriggerDialog(self.ctx, trig, done).present(self.get_root())

    def _remove_trigger(self, kind: str, idx: int) -> None:
        del (self.buttons if kind == "button" else self.triggers)[idx]
        self._render_triggers()

    # ---- Então…
    def _render(self) -> None:
        _clear(self.steps_list)
        for i, step in enumerate(self.steps):
            self.steps_list.append(self._make_row(i, step))
        if not self.steps:
            lab = Gtk.Label(label="Nenhuma ação ainda. Adicione uma ação ou um atraso.", xalign=0, margin_top=6,
                            margin_bottom=6)
            lab.add_css_class("dim-label")
            self.steps_list.append(Gtk.ListBoxRow(activatable=False, selectable=False, child=lab))
        n = len(self.steps)
        self.steps_count.set_label(f"{n} de {logic.SA_MAX_STEPS} ações. Arraste pela alça ou use as setas para reordenar.")

    def _make_row(self, i: int, step: dict) -> Gtk.ListBoxRow:
        row = StepRow(activatable=False, selectable=False)
        row.add_css_class("step-row")
        box = Gtk.Box(spacing=8, margin_top=4, margin_bottom=4)
        handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle.add_css_class("drag-handle")
        handle.set_tooltip_text("Arraste para reordenar")
        box.append(handle)
        num = Gtk.Label(label=str(i + 1))
        num.add_css_class("step-num")
        num.set_size_request(24, -1)
        box.append(num)
        if step.get("type") == "delay":
            lab = Gtk.Label(label="Aguardar", xalign=0)
            spin = Gtk.SpinButton.new_with_range(logic.SA_DELAY_MIN, logic.SA_DELAY_MAX, 50)
            spin.set_value(step.get("ms", 500))
            spin.update_property([Gtk.AccessibleProperty.LABEL], [f"Atraso da ação {i + 1} em milissegundos"])
            spin.connect("value-changed", lambda sp, idx=i: self.steps[idx].update({"ms": int(sp.get_value())}))
            ms = Gtk.Label(label="ms")
            ms.add_css_class("dim-label")
            for w in (lab, spin, ms):
                box.append(w)
            box.append(Gtk.Box(hexpand=True))
        else:
            lab = Gtk.Label(label=logic.step_summary(step), xalign=0, hexpand=True, ellipsize=3)
            box.append(lab)
            box.append(_flat_btn("media-playback-start-symbolic", "Testar esta ação", lambda s=step: self.ctx.test_action(s)))
            box.append(_flat_btn("document-edit-symbolic", "Editar ação", lambda idx=i: self._edit_step(idx)))
        up = _flat_btn("go-up-symbolic", "Mover para cima", lambda idx=i: self._move(idx, idx - 1))
        down = _flat_btn("go-down-symbolic", "Mover para baixo", lambda idx=i: self._move(idx, idx + 1))
        up.set_sensitive(i > 0)
        down.set_sensitive(i < len(self.steps) - 1)
        box.append(up)
        box.append(down)
        box.append(_flat_btn("edit-delete-symbolic", "Remover ação", lambda idx=i: self._remove(idx)))
        row.set_child(box)
        src = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        src.connect("prepare", lambda _s, _x, _y, idx=i: Gdk.ContentProvider.new_for_value(idx))
        handle.add_controller(src)
        dst = Gtk.DropTarget.new(GObject.TYPE_INT, Gdk.DragAction.MOVE)
        dst.connect("drop", lambda _t, value, _x, _y, idx=i: self._move(int(value), idx) or True)
        row.add_controller(dst)
        return row

    def _move(self, src: int, dst: int) -> None:
        self.steps = logic.move_step(self.steps, src, dst)
        self._render()

    def _remove(self, idx: int) -> None:
        del self.steps[idx]
        self._render()

    def _add_delay(self) -> None:
        if len(self.steps) >= logic.SA_MAX_STEPS:
            self.ctx.toast(f"No máximo {logic.SA_MAX_STEPS} ações")
            return
        self.steps.append({"type": "delay", "ms": 500})
        self._render()

    def _edit_step(self, idx: int | None) -> None:
        if idx is None and len(self.steps) >= logic.SA_MAX_STEPS:
            self.ctx.toast(f"No máximo {logic.SA_MAX_STEPS} ações")
            return

        def done(action: dict) -> None:
            try:
                step = logic.validate_step(action)
            except ValueError as e:
                self.ctx.toast(str(e))
                return
            if idx is None:
                self.steps.append(step)
            else:
                self.steps[idx] = step
            self._render()
        StepDialog(self.ctx, self.steps[idx] if idx is not None else None, done).present(self.get_root())

    # ---- Experimentar
    def _try(self) -> None:
        if self._running:
            self._cancel_run()
            self._set_running(False)
            self.ctx.toast("Experimento interrompido")
            return
        if self.sid and not self.is_dirty():
            self.ctx.test_action({"type": "smart_action", "id": self.sid})
            return
        try:
            steps = [logic.validate_step(s) for s in self.steps]
        except ValueError as e:
            self.ctx.toast(str(e))
            return
        if not steps:
            self.ctx.toast("Adicione ao menos uma ação para experimentar")
            return
        self._set_running(True)
        self.ctx.toast("Experimentando o rascunho (ainda não salvo)…")
        self._run_next(steps, 0)

    def _set_running(self, on: bool) -> None:
        self._running = on
        self.test_all.set_label("Parar" if on else "Experimentar")

    def _run_next(self, steps: list[dict], i: int) -> None:
        self._run_source = 0
        if i >= len(steps):
            self._set_running(False)
            self.ctx.toast("Experimento concluído")
            return
        step = steps[i]
        if step.get("type") == "delay":
            self._run_source = GLib.timeout_add(int(step["ms"]), lambda: self._run_next(steps, i + 1) and False)
            return

        def done(ok, error) -> None:
            if not self._running:
                return
            if error or ok is False:
                self._set_running(False)
                self.ctx.toast(f"Ação {i + 1} falhou: {error or 'o serviço recusou'}")
                return
            self._run_next(steps, i + 1)
        self.ctx.client.run_action(step, done)

    def _cancel_run(self) -> None:
        if self._run_source:
            GLib.source_remove(self._run_source)
            self._run_source = 0
        self._running = False
        if hasattr(self, "test_all"):
            self.test_all.set_label("Experimentar")

    # ---- salvar
    def _ask_name(self, save: bool = True) -> None:
        def done(name: str, desc: str, icon: str) -> None:
            self.name, self.description, self.icon = name, desc, icon
            self._render_id()
            if save:
                self._save()
        NameDialog(self.name, self.description, self.icon, done).present(self.get_root())

    def _build(self) -> dict:
        sa = {"name": self.name, "description": self.description, "icon": self.icon, "steps": self.steps,
              "triggers": self.triggers}
        if self.enabled is not None:
            sa["enabled"] = self.enabled
        if self.sid:
            sa["id"] = self.sid
        return logic.validate_smart_action(sa)

    def _save(self) -> None:
        try:
            sa = self._build()
        except ValueError as e:
            self.ctx.toast(str(e))
            return

        def saved(res, error) -> None:
            if error:
                self.ctx.toast(error)
                return
            sid, warnings = res
            self.sid = sid or self.sid
            self._apply_buttons(self.sid, warnings)
        self.ctx.client.save_smart_action(sa, saved)

    def _apply_buttons(self, sid: str, warnings: list[str]) -> None:
        """Grava/remove as atribuições de botão e fecha o editor."""
        new = {(b["device_id"], b["app_id"], b["cid"]): b for b in self.buttons}
        old = {(b["device_id"], b["app_id"], b["cid"]): b for b in self._orig_buttons}
        jobs = [(k, {"type": "smart_action", "id": sid}) for k in new if k not in old]
        jobs += [(k, {"type": "default"} if not k[1] else None) for k in old if k not in new]
        failures: list[str] = []

        def finish() -> None:
            if failures:
                self.ctx.toast("Smart Action salva, mas um botão não foi atualizado: " + failures[0])
            else:
                self.ctx.toast("Smart Action salva")
            for w in warnings[:3]:
                self.ctx.toast("Aviso: " + w)
            self._saved = self._snapshot()
            self._on_close()

        def step(i: int) -> None:
            if i >= len(jobs):
                finish()
                return
            (dev, app, cid), action = jobs[i]

            def cb(ok, error) -> None:
                if error or ok is False:
                    failures.append(error or "o serviço recusou")
                step(i + 1)
            self.ctx.client.set_profile_assignment(dev, app, cid, action, cb)
        step(0)
