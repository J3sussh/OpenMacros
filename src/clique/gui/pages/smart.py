"""Smart Actions: lista, modelos prontos e editor de passos."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GObject, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..widgets.action_panel import ActionList  # noqa: E402


def _icon_label(icon: str, title: str, subtitle: str) -> Gtk.Box:
    box = Gtk.Box(spacing=14)
    img = Gtk.Image.new_from_icon_name(icon)
    img.set_pixel_size(24)
    img.add_css_class("sa-icon")
    texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
    t = Gtk.Label(label=title, xalign=0, ellipsize=3)
    t.add_css_class("card-title")
    s = Gtk.Label(label=subtitle, xalign=0, ellipsize=3)
    s.add_css_class("dim-label")
    texts.append(t)
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


class SmartActionsPage(Adw.NavigationPage):
    """Lista das Smart Actions do usuário + modelos prontos."""

    def __init__(self, ctx):
        super().__init__(title="Smart Actions", tag="smart")
        self.ctx = ctx
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        title = Gtk.Label(label="SMART ACTIONS")
        title.add_css_class("device-title")
        header.set_title_widget(title)
        new = Gtk.Button(label="Criar", tooltip_text="Criar uma Smart Action em branco")
        new.add_css_class("suggested-action")
        new.connect("clicked", lambda *_: self.ctx.open_smart_editor(None, None))
        header.pack_end(new)
        view.add_top_bar(header)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=20, margin_bottom=28,
                           margin_start=20, margin_end=20)
        intro = Gtk.Label(label="Smart Actions são sequências de passos (abrir apps, atalhos, textos, esperas) que "
                                "você atribui a um botão. Elas rodam no Clique, sem travar a interface.",
                          wrap=True, xalign=0)
        intro.add_css_class("dim-label")
        self.box.append(intro)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.box.append(self.list_box)
        head = Gtk.Label(label="MODELOS PRONTOS", xalign=0, margin_top=14)
        head.add_css_class("section-title")
        self.box.append(head)
        for t in logic.SMART_TEMPLATES:
            card = Gtk.Box(spacing=10)
            card.add_css_class("clique-card")
            card.append(_icon_label(t["icon"], t["name"], t["description"]))
            use = Gtk.Button(label="Usar modelo", valign=Gtk.Align.CENTER)
            use.add_css_class("pill-small")
            use.connect("clicked", lambda *_a, tid=t["id"]: self.ctx.open_smart_editor(logic.smart_from_template(tid), None))
            card.append(use)
            self.box.append(card)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=Adw.Clamp(maximum_size=760, child=self.box))
        view.set_content(sw)
        self.set_child(view)
        self.refresh()

    def refresh(self) -> None:
        while (c := self.list_box.get_first_child()) is not None:
            self.list_box.remove(c)
        sas = self.ctx.smart_actions
        if not sas:
            empty = Gtk.Label(label="Você ainda não criou nenhuma Smart Action. Comece por um modelo abaixo.", xalign=0)
            empty.add_css_class("clique-card")
            self.list_box.append(empty)
            return
        for sid, sa in sorted(sas.items(), key=lambda kv: kv[1].get("name", "").lower()):
            n = len(sa.get("steps") or [])
            card = Gtk.Box(spacing=6)
            card.add_css_class("clique-card")
            card.append(_icon_label(sa.get("icon") or logic.SA_DEFAULT_ICON, sa.get("name", sid),
                                    f"{n} passo{'s' if n != 1 else ''}"))
            card.append(_flat_btn("media-playback-start-symbolic", "Testar",
                                  lambda s=sid: self.ctx.test_action({"type": "smart_action", "id": s})))
            card.append(_flat_btn("document-edit-symbolic", "Editar", lambda s=sid, d=sa: self.ctx.open_smart_editor(d, s)))
            card.append(_flat_btn("user-trash-symbolic", "Excluir", lambda s=sid: self._delete(s)))
            self.list_box.append(card)

    def _delete(self, sid: str) -> None:
        name = self.ctx.smart_actions.get(sid, {}).get("name", sid)
        dlg = Adw.AlertDialog.new(f"Excluir “{name}”?", "Botões que usam esta Smart Action voltam ao padrão.")
        dlg.add_response("cancel", "Cancelar")
        dlg.add_response("delete", "Excluir")
        dlg.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_close_response("cancel")
        dlg.connect("response", lambda _d, r: r == "delete" and self.ctx.client.delete_smart_action(
            sid, self.ctx.reporter()))
        dlg.present(self.get_root())


class StepDialog(Adw.Dialog):
    """Escolhe/edita a ação de um passo."""

    def __init__(self, ctx, step: dict | None, on_done):
        super().__init__(title="Ação do passo", content_width=440, content_height=600)
        self._on_done = on_done
        self.lst = ActionList(self._picked, False, 3, ctx, steps=True, allow_smart=False)
        self.lst.set_margin_start(14)
        self.lst.set_margin_end(14)
        if step and step.get("type") != "delay":
            self.lst.set_action(step)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.lst))
        self.set_child(view)

    def _picked(self, action: dict) -> None:
        self.close()
        self._on_done(action)


class StepRow(Gtk.ListBoxRow):
    pass


class SmartEditorPage(Adw.NavigationPage):
    def __init__(self, ctx, draft: dict | None, sid: str | None, on_close):
        super().__init__(title="Editar Smart Action" if sid else "Nova Smart Action")
        self.ctx = ctx
        self.sid = sid
        self._on_close = on_close
        d = draft or {}
        self.steps: list[dict] = [dict(s) for s in d.get("steps") or []]
        self.icon = d.get("icon") if d.get("icon") in logic.SA_ICONS else logic.SA_DEFAULT_ICON

        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        t = Gtk.Label(label=("EDITAR SMART ACTION" if sid else "NOVA SMART ACTION"))
        t.add_css_class("device-title")
        header.set_title_widget(t)
        save = Gtk.Button(label="Salvar")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._save())
        header.pack_end(save)
        view.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin_top=20, margin_bottom=28,
                      margin_start=20, margin_end=20)
        # nome + ícone
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("clique-card")
        lab = Gtk.Label(label="Nome", xalign=0)
        lab.add_css_class("card-title")
        self.name_entry = Gtk.Entry(text=d.get("name", ""), placeholder_text="Ex.: Modo foco", max_length=60)
        self.name_entry.update_property([Gtk.AccessibleProperty.LABEL], ["Nome da Smart Action"])
        card.append(lab)
        card.append(self.name_entry)
        lab2 = Gtk.Label(label="Ícone", xalign=0, margin_top=6)
        lab2.add_css_class("card-title")
        card.append(lab2)
        self.icon_flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=10,
                                     column_spacing=6, row_spacing=6, homogeneous=True)
        self._icon_btns: dict[str, Gtk.ToggleButton] = {}
        group = None
        for ic in logic.SA_ICONS:
            b = Gtk.ToggleButton(icon_name=ic)
            b.add_css_class("flat")
            b.add_css_class("icon-choice")
            b.update_property([Gtk.AccessibleProperty.LABEL], [f"Ícone {ic.removesuffix('-symbolic')}"])
            if group is None:
                group = b
            else:
                b.set_group(group)
            b.set_active(ic == self.icon)
            b.connect("toggled", lambda btn, i=ic: btn.get_active() and setattr(self, "icon", i))
            self.icon_flow.append(b)
            self._icon_btns[ic] = b
        card.append(self.icon_flow)
        box.append(card)

        # passos
        steps_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        steps_card.add_css_class("clique-card")
        st = Gtk.Label(label="Passos", xalign=0)
        st.add_css_class("card-title")
        sub = Gtk.Label(label="Arraste pela alça ou use as setas para reordenar. Máximo de 32 passos.", xalign=0, wrap=True)
        sub.add_css_class("dim-label")
        steps_card.append(st)
        steps_card.append(sub)
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
        foot = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        self.test_all = Gtk.Button(label="Testar tudo")
        self.test_all.connect("clicked", lambda *_: self.ctx.test_action({"type": "smart_action", "id": self.sid}))
        self.test_all.set_tooltip_text("Salve a Smart Action para testá-la inteira")
        foot.append(self.test_all)
        box.append(foot)
        view.set_content(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                            child=Adw.Clamp(maximum_size=760, child=box)))
        self.set_child(view)
        self._render()

    # ---- passos
    def _render(self) -> None:
        while (c := self.steps_list.get_first_child()) is not None:
            self.steps_list.remove(c)
        self.test_all.set_sensitive(self.sid is not None)
        for i, step in enumerate(self.steps):
            self.steps_list.append(self._make_row(i, step))
        if not self.steps:
            lab = Gtk.Label(label="Nenhum passo ainda. Adicione uma ação ou um atraso.", xalign=0, margin_top=6, margin_bottom=6)
            lab.add_css_class("dim-label")
            self.steps_list.append(Gtk.ListBoxRow(activatable=False, selectable=False, child=lab))

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
            spin.update_property([Gtk.AccessibleProperty.LABEL], [f"Atraso do passo {i + 1} em milissegundos"])
            spin.connect("value-changed", lambda sp, idx=i: self.steps[idx].update({"ms": int(sp.get_value())}))
            ms = Gtk.Label(label="ms")
            ms.add_css_class("dim-label")
            for w in (lab, spin, ms):
                box.append(w)
            spacer = Gtk.Box(hexpand=True)
            box.append(spacer)
        else:
            lab = Gtk.Label(label=logic.step_summary(step), xalign=0, hexpand=True, ellipsize=3)
            box.append(lab)
            box.append(_flat_btn("media-playback-start-symbolic", "Testar este passo", lambda s=step: self.ctx.test_action(s)))
            box.append(_flat_btn("document-edit-symbolic", "Editar passo", lambda idx=i: self._edit_step(idx)))
        up = _flat_btn("go-up-symbolic", "Mover para cima", lambda idx=i: self._move(idx, idx - 1))
        down = _flat_btn("go-down-symbolic", "Mover para baixo", lambda idx=i: self._move(idx, idx + 1))
        up.set_sensitive(i > 0)
        down.set_sensitive(i < len(self.steps) - 1)
        box.append(up)
        box.append(down)
        box.append(_flat_btn("edit-delete-symbolic", "Remover passo", lambda idx=i: self._remove(idx)))
        row.set_child(box)
        # arrastar e soltar
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
            self.ctx.toast(f"No máximo {logic.SA_MAX_STEPS} passos")
            return
        self.steps.append({"type": "delay", "ms": 500})
        self._render()

    def _edit_step(self, idx: int | None) -> None:
        if idx is None and len(self.steps) >= logic.SA_MAX_STEPS:
            self.ctx.toast(f"No máximo {logic.SA_MAX_STEPS} passos")
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

    # ---- salvar
    def _save(self) -> None:
        sa = {"name": self.name_entry.get_text(), "icon": self.icon, "steps": self.steps}
        if self.sid:
            sa["id"] = self.sid
        try:
            sa = logic.validate_smart_action(sa)
        except ValueError as e:
            self.ctx.toast(str(e))
            return

        def saved(sid, error):
            if error:
                self.ctx.toast(error)
                return
            self.sid = sid or self.sid
            self.ctx.toast("Smart Action salva")
            self._on_close()
        self.ctx.client.save_smart_action(sa, saved)
