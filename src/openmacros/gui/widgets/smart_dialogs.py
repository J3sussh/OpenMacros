"""Diálogos do editor de Smart Actions: gatilho ("Se…"), ação ("Então…") e nome/descrição ao salvar."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from .action_panel import ActionList  # noqa: E402
from .key_capture import KeyCapture  # noqa: E402


def _caption(text: str = "", css: str = "dim-label") -> Gtk.Label:
    lab = Gtk.Label(label=text, xalign=0, wrap=True)
    lab.add_css_class("caption")
    if css:
        lab.add_css_class(css)
    return lab


def step_category(step: dict | None) -> str:
    """Categoria do seletor "Então…" a que um passo pertence."""
    t = (step or {}).get("type")
    return {"delay": "delay", "app": "app", "open": "app", "keys": "keys", "key_sequence": "keys",
            "type_text": "text", "system": "system", "volume": "system", "window": "system",
            "media": "media", "ai_prompt": "ai", "command": "command"}.get(t, "app")


class StepDialog(Adw.Dialog):
    """Escolhe/edita a ação de um passo por categoria (Aplicativo, Tecla, Texto, Sistema, Mídia, IA, Atraso, Comando)."""

    def __init__(self, ctx, step: dict | None, on_done: Callable[[dict], None]):
        super().__init__(title="Então…", content_width=480, content_height=700)
        self._on_done = on_done
        self._lists: dict[str, ActionList] = {}
        self.chip_btns: dict[str, Gtk.ToggleButton] = {}
        cur = step_category(step)

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2,
                            column_spacing=6, row_spacing=6, margin_start=14, margin_end=14, margin_top=6,
                            homogeneous=False)
        chips.update_property([Gtk.AccessibleProperty.LABEL], ["Categoria da ação"])
        self.stack = Gtk.Stack(vexpand=True)
        group = None
        for cat, label in logic.STEP_CATEGORIES:
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("profile-chip")
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.connect("toggled", lambda b, c=cat: b.get_active() and self.stack.set_visible_child_name(c))
            chips.append(btn)
            self.chip_btns[cat] = btn
            btn.get_parent().set_focusable(False)
            btn.get_parent().set_halign(Gtk.Align.START)
            if cat == "delay":
                page = self._delay_page(step)
            else:
                lst = ActionList(self._picked, False, 3, ctx, steps=True, allow_smart=False, category=cat)
                if step and cat == cur:
                    lst.set_action(step)
                self._lists[cat] = lst
                page = lst
            page.set_margin_start(14)
            page.set_margin_end(14)
            self.stack.add_named(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=page), cat)
            btn.set_active(cat == cur)
        self.stack.set_visible_child_name(cur)
        outer.append(chips)
        outer.append(self.stack)
        view.set_content(outer)
        self.set_child(view)

    def _delay_page(self, step: dict | None) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=14, margin_bottom=14)
        box.append(_caption("Espera um tempo antes da próxima ação.", ""))
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Label(label="Aguardar", xalign=0))
        self.delay_spin = Gtk.SpinButton.new_with_range(logic.SA_DELAY_MIN, logic.SA_DELAY_MAX, 50)
        self.delay_spin.set_value(step.get("ms", 500) if step and step.get("type") == "delay" else 500)
        self.delay_spin.update_property([Gtk.AccessibleProperty.LABEL], ["Atraso em milissegundos"])
        row.append(self.delay_spin)
        row.append(_caption("ms"))
        box.append(row)
        ok = Gtk.Button(label="Aplicar", halign=Gtk.Align.END)
        ok.add_css_class("suggested-action")
        ok.connect("clicked", lambda *_: self._picked({"type": "delay", "ms": int(self.delay_spin.get_value())}))
        box.append(ok)
        return box

    def _picked(self, action: dict) -> None:
        self.close()
        self._on_done(action)


class NameDialog(Adw.Dialog):
    """Nome, descrição e ícone da Smart Action (aparece ao salvar)."""

    def __init__(self, name: str, description: str, icon: str, on_save: Callable[[str, str, str], None]):
        super().__init__(title="Salvar Smart Action", content_width=440)
        self._on_save = on_save
        self.icon = icon if icon in logic.SA_ICONS else logic.SA_DEFAULT_ICON
        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancelar")
        cancel.connect("clicked", lambda *_: self.close())
        self.save_btn = Gtk.Button(label="Salvar")
        self.save_btn.add_css_class("suggested-action")
        self.save_btn.connect("clicked", self._save)
        header.pack_start(cancel)
        header.pack_end(self.save_btn)
        view.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=8, margin_bottom=18,
                      margin_start=16, margin_end=16)
        grp = Adw.PreferencesGroup()
        self.name_row = Adw.EntryRow(title="Nome", text=name)
        self.name_row.connect("entry-activated", self._save)
        self.name_row.connect("changed", lambda *_: self._check())
        self.desc_row = Adw.EntryRow(title="Descrição (opcional)", text=description)
        self.desc_row.connect("entry-activated", self._save)
        grp.add(self.name_row)
        grp.add(self.desc_row)
        box.append(grp)
        lab = Gtk.Label(label="Ícone", xalign=0)
        lab.add_css_class("card-title")
        box.append(lab)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=10, column_spacing=6,
                           row_spacing=6, homogeneous=True)
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
            flow.append(b)
            b.get_parent().set_focusable(False)
        box.append(flow)
        self.note = _caption(logic.SA_SECRETS_NOTE)
        box.append(self.note)
        view.set_content(box)
        self.set_child(view)
        self.set_focus(self.name_row)
        self._check()

    def _check(self) -> None:
        self.save_btn.set_sensitive(bool(self.name_row.get_text().strip()))

    def _save(self, *_a) -> None:
        name = self.name_row.get_text().strip()
        if not name:
            return
        self.close()
        self._on_save(name, self.desc_row.get_text().strip(), self.icon)


class TriggerDialog(Adw.Dialog):
    """Cria/edita um gatilho: Botão do dispositivo, Atalho, Aplicativo ou Dispositivo."""

    def __init__(self, ctx, trigger: dict | None, on_done: Callable[[dict], None]):
        super().__init__(title="Gatilho", content_width=460, content_height=440)
        self.ctx = ctx
        self._on_done = on_done
        t = trigger or {}
        self._keys: list[str] = list(t.get("keys") or []) if t.get("type") == "shortcut" else []
        self._app_id: str = t.get("app_id", "") if t.get("type") == "app" else ""
        self._types = [k for k, _ in logic.TRIGGER_TYPES]
        self._devs = [d for d in ctx.devices.values()]
        self._btn_devs = [d for d in self._devs if any(logic.is_configurable(c) for c in d.get("controls") or [])]

        view = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancelar")
        cancel.connect("clicked", lambda *_: self.close())
        self.ok = Gtk.Button(label="Aplicar" if trigger else "Adicionar")
        self.ok.add_css_class("suggested-action")
        self.ok.connect("clicked", self._apply)
        header.pack_start(cancel)
        header.pack_end(self.ok)
        view.add_top_bar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=8, margin_bottom=18,
                      margin_start=16, margin_end=16)
        grp = Adw.PreferencesGroup()
        self.type_row = Adw.ComboRow(title="Quando…")
        self.type_row.set_model(Gtk.StringList.new([v for _, v in logic.TRIGGER_TYPES]))
        grp.add(self.type_row)
        box.append(grp)

        self.stack = Gtk.Stack(vhomogeneous=False)
        self.stack.add_named(self._button_page(t), "button")
        self.stack.add_named(self._shortcut_page(), "shortcut")
        self.stack.add_named(self._app_page(t), "app")
        self.stack.add_named(self._device_page(t), "device")
        box.append(self.stack)
        self.error = Gtk.Label(xalign=0, wrap=True, visible=False)
        self.error.add_css_class("error")
        box.append(self.error)
        view.set_content(Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=box))
        self.set_child(view)

        kind = t.get("type", "shortcut")
        self.type_row.set_selected(self._types.index(kind) if kind in self._types else 1)
        if trigger:
            self.type_row.set_sensitive(False)
        self.type_row.connect("notify::selected", self._on_type)
        self._on_type()

    # ---- páginas
    def _button_page(self, t: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        grp = Adw.PreferencesGroup()
        self.b_dev = Adw.ComboRow(title="Dispositivo")
        self.b_dev.set_model(Gtk.StringList.new([d.get("name", d["id"]) + ("" if d.get("online", True) else " (offline)")
                                                 for d in self._btn_devs]))
        self.b_btn = Adw.ComboRow(title="Botão")
        self.b_prof = Adw.ComboRow(title="Perfil")
        for r in (self.b_dev, self.b_btn, self.b_prof):
            grp.add(r)
        box.append(grp)
        self.b_note = _caption("")
        box.append(self.b_note)
        box.append(_caption("Ao salvar, o botão passa a executar esta Smart Action no lugar da ação atual."))
        self._b_controls: list[dict] = []
        self._b_apps: list[str] = []
        if t.get("type") == "button":
            for i, d in enumerate(self._btn_devs):
                if d["id"] == t.get("device_id"):
                    self.b_dev.set_selected(i)
        self.b_dev.connect("notify::selected", lambda *_: self._fill_buttons(t))
        self.b_btn.connect("notify::selected", lambda *_: self._button_note())
        self.b_prof.connect("notify::selected", lambda *_: self._button_note())
        self._fill_buttons(t if t.get("type") == "button" else {})
        return box

    def _fill_buttons(self, t: dict) -> None:
        if not self._btn_devs:
            self.b_btn.set_model(Gtk.StringList.new([]))
            self.b_prof.set_model(Gtk.StringList.new([]))
            self.b_note.set_label("Nenhum dispositivo com botões configuráveis está disponível agora.")
            return
        dev = self._btn_devs[min(self.b_dev.get_selected(), len(self._btn_devs) - 1)]
        self._b_controls = [c for c in dev.get("controls") or [] if logic.is_configurable(c)]
        self._b_apps = [""] + logic.profile_app_ids(dev)
        self.b_btn.set_model(Gtk.StringList.new([c.get("name", f"Controle {c['cid']}") for c in self._b_controls]))
        self.b_prof.set_model(Gtk.StringList.new(["Todos os aplicativos"]
                                                 + [self.ctx.apps.name_of(a) for a in self._b_apps[1:]]))
        if t.get("type") == "button":
            for i, c in enumerate(self._b_controls):
                if int(c["cid"]) == int(t.get("cid", -1)):
                    self.b_btn.set_selected(i)
            if t.get("app_id") in self._b_apps:
                self.b_prof.set_selected(self._b_apps.index(t["app_id"]))
        self._button_note()

    def _button_note(self) -> None:
        if not self._btn_devs or not self._b_controls or not self._b_apps:
            return
        dev = self._btn_devs[min(self.b_dev.get_selected(), len(self._btn_devs) - 1)]
        c = self._b_controls[min(self.b_btn.get_selected(), len(self._b_controls) - 1)]
        app = self._b_apps[min(max(self.b_prof.get_selected(), 0), len(self._b_apps) - 1)]
        cur, _src = logic.effective_action(dev, app, int(c["cid"]))
        self.b_note.set_label("Ação atual deste botão: " + logic.describe_action(cur, self.ctx.smart_actions))

    def _shortcut_page(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Label(label="Atalho:", xalign=0))
        self.capture = KeyCapture()
        self.capture.set_keys(self._keys)
        self.capture.connect("keys-changed", lambda *_: setattr(self, "_keys", list(self.capture.keys)))
        row.append(self.capture)
        box.append(row)
        box.append(_caption("Clique no botão e pressione a combinação. Use ao menos um modificador (Ctrl, Alt, Super "
                            "ou Shift); teclas F13–F24 e de mídia podem ficar sozinhas. Funciona em sessões X11; "
                            "combinações já usadas por outro programa não podem ser registradas."))
        return box

    def _app_page(self, t: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        grp = Adw.PreferencesGroup()
        self.app_row = Adw.ActionRow(title="Aplicativo", subtitle="Nenhum escolhido")
        pick = Gtk.Button(label="Escolher…", valign=Gtk.Align.CENTER)
        pick.connect("clicked", self._pick_app)
        self.app_row.add_suffix(pick)
        self.app_ev = Adw.ComboRow(title="Evento")
        self._app_events = list(logic.APP_EVENTS)
        self.app_ev.set_model(Gtk.StringList.new(list(logic.APP_EVENTS.values())))
        if t.get("type") == "app" and t.get("event") in self._app_events:
            self.app_ev.set_selected(self._app_events.index(t["event"]))
        grp.add(self.app_row)
        grp.add(self.app_ev)
        box.append(grp)
        box.append(_caption("Abrir: a primeira janela do aplicativo aparece. Fechar: a última some. Primeiro plano: o "
                            "aplicativo ganha o foco."))
        self._show_app()
        return box

    def _show_app(self) -> None:
        if self._app_id:
            self.app_row.set_subtitle(f"{self.ctx.apps.name_of(self._app_id)} ({self._app_id})")
        else:
            self.app_row.set_subtitle("Nenhum escolhido")

    def _pick_app(self, *_a) -> None:
        from .app_picker import AppPickerDialog

        def picked(e) -> None:
            self._app_id = e.app_id
            self._show_app()
        AppPickerDialog(self.ctx, picked, running=True).present(self)

    def _device_page(self, t: dict) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        grp = Adw.PreferencesGroup()
        self.d_dev = Adw.ComboRow(title="Dispositivo")
        self.d_dev.set_model(Gtk.StringList.new(["Qualquer dispositivo"] + [d.get("name", d["id"]) for d in self._devs]))
        self.d_ev = Adw.ComboRow(title="Evento")
        self._dev_events = list(logic.DEVICE_EVENTS)
        self.d_ev.set_model(Gtk.StringList.new(list(logic.DEVICE_EVENTS.values())))
        if t.get("type") == "device":
            if t.get("event") in self._dev_events:
                self.d_ev.set_selected(self._dev_events.index(t["event"]))
            for i, d in enumerate(self._devs):
                if d["id"] == t.get("device_id"):
                    self.d_dev.set_selected(i + 1)
        grp.add(self.d_dev)
        grp.add(self.d_ev)
        box.append(grp)
        box.append(_caption("Também vale quando o dispositivo volta de outro computador pelo Easy-Switch."))
        return box

    # ---- resultado
    def _on_type(self, *_a) -> None:
        self.stack.set_visible_child_name(self._types[self.type_row.get_selected()])
        self.error.set_visible(False)

    def build(self) -> dict:
        """Gatilho a partir do formulário (ValueError se incompleto)."""
        kind = self._types[self.type_row.get_selected()]
        if kind == "shortcut":
            return logic.validate_trigger({"type": "shortcut", "keys": self._keys})
        if kind == "app":
            return logic.validate_trigger({"type": "app", "event": self._app_events[self.app_ev.get_selected()],
                                           "app_id": self._app_id})
        if kind == "device":
            i = self.d_dev.get_selected()
            return logic.validate_trigger({"type": "device", "event": self._dev_events[self.d_ev.get_selected()],
                                           "device_id": "*" if i == 0 else self._devs[i - 1]["id"]})
        if not self._btn_devs or not self._b_controls:
            raise ValueError("nenhum botão configurável disponível")
        dev = self._btn_devs[min(self.b_dev.get_selected(), len(self._btn_devs) - 1)]
        c = self._b_controls[min(self.b_btn.get_selected(), len(self._b_controls) - 1)]
        app = self._b_apps[min(self.b_prof.get_selected(), len(self._b_apps) - 1)]
        return {"type": "button", "device_id": dev["id"], "device_name": dev.get("name", dev["id"]), "app_id": app,
                "cid": int(c["cid"]), "label": c.get("name", f"Controle {c['cid']}")}

    def _apply(self, *_a) -> None:
        try:
            trig = self.build()
        except ValueError as e:
            self.error.set_label(str(e))
            self.error.set_visible(True)
            return
        self.close()
        self._on_done(trig)


__all__ = ["StepDialog", "NameDialog", "TriggerDialog", "step_category"]
