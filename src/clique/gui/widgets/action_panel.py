"""Painel lateral de ações (estilo Options+): lista agrupada em seções + editor de gestos em cruz."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, GObject, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from .key_capture import KeyCapture  # noqa: E402

NO_TEST = ("default", "disabled", "gestures", "smart_new")


def _text_view(min_height: int = 64) -> tuple[Gtk.ScrolledWindow, Gtk.TextView]:
    tv = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6, left_margin=8, right_margin=8)
    tv.add_css_class("clique-text")
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=min_height, hexpand=True)
    sw.add_css_class("clique-text-frame")
    sw.set_child(tv)
    return sw, tv


def _get_text(tv: Gtk.TextView) -> str:
    b = tv.get_buffer()
    return b.get_text(b.get_start_iter(), b.get_end_iter(), False)


class ActionList(Gtk.Box):
    """Lista de ações em seções. `on_action(action)` ao escolher/confirmar; `ctx` dá Smart Actions,
    apps instalados e o botão 'Testar'."""

    def __init__(self, on_action: Callable[[dict], None], allow_gestures: bool, host_count: int, ctx=None,
                 steps: bool = False, allow_smart: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._on_action = on_action
        self._ctx = ctx
        self._host_count = max(1, host_count)
        self._rows: dict[str, Gtk.ListBoxRow] = {}
        self._checks: dict[str, Gtk.Image] = {}
        self._editors: dict[str, Gtk.Revealer] = {}
        self._steps = steps
        self.set_margin_bottom(8)
        smart = ctx.smart_actions if ctx else {}
        for title, items in logic.action_sections(allow_gestures, smart, allow_smart and not steps, steps):
            head = Gtk.Label(label=title.upper(), xalign=0)
            head.add_css_class("section-title")
            head.set_margin_top(14)
            head.set_margin_bottom(4)
            self.append(head)
            lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lb.add_css_class("action-list")
            lb.connect("row-activated", self._on_row_activated)
            self.append(lb)
            for item_id, label in items:
                self._add_item(lb, item_id, label)

    # ---- construção
    def _add_item(self, lb: Gtk.ListBox, item_id: str, label: str) -> None:
        row = Gtk.ListBoxRow()
        row.item_id = item_id  # type: ignore[attr-defined]
        row.add_css_class("action-row")
        box = Gtk.Box(spacing=8)
        lab = Gtk.Label(label=label, xalign=0, hexpand=True, ellipsize=3)
        box.append(lab)
        if self._ctx and item_id not in NO_TEST and logic.action_for_simple_item(item_id) is not None:
            t = Gtk.Button(icon_name="media-playback-start-symbolic", tooltip_text="Testar", valign=Gtk.Align.CENTER)
            t.add_css_class("flat")
            t.add_css_class("circular")
            t.add_css_class("test-btn")
            t.update_property([Gtk.AccessibleProperty.LABEL], [f"Testar: {label}"])
            t.connect("clicked", lambda *_a, i=item_id: self._test_simple(i))
            box.append(t)
        check = Gtk.Image.new_from_icon_name("object-select-symbolic")
        check.add_css_class("action-check")
        check.set_opacity(0)
        box.append(check)
        row.set_child(box)
        lb.append(row)
        self._rows[item_id] = row
        self._checks[item_id] = check
        editor = self._make_editor(item_id)
        if editor is not None:
            rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, child=editor)
            erow = Gtk.ListBoxRow(activatable=False, selectable=False)
            erow.add_css_class("editor-row")
            erow.set_child(rev)
            lb.append(erow)
            self._editors[item_id] = rev

    def _buttons(self, item_id: str, apply: bool = True) -> Gtk.Box:
        box = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        if self._ctx:
            t = Gtk.Button(label="Testar")
            t.connect("clicked", lambda *_: self._run(item_id, test=True))
            box.append(t)
        if apply:
            b = Gtk.Button(label="Aplicar")
            b.add_css_class("suggested-action")
            b.connect("clicked", lambda *_: self._run(item_id))
            box.append(b)
        return box

    def _vbox(self, *widgets: Gtk.Widget) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12, margin_bottom=10)
        for w in widgets:
            box.append(w)
        return box

    def _make_editor(self, item_id: str) -> Gtk.Widget | None:
        if item_id == "keys":
            self.capture = KeyCapture()
            self.capture.connect("keys-changed", lambda *_: self._run("keys"))
            row = Gtk.Box(spacing=8)
            row.append(Gtk.Label(label="Atalho:", xalign=0))
            row.append(self.capture)
            return self._vbox(row, self._buttons("keys", apply=False))
        if item_id == "mouse_button":
            self.button_dd = Gtk.DropDown.new_from_strings([b[1] for b in logic.MOUSE_BUTTONS])
            return self._vbox(self.button_dd, self._buttons(item_id))
        if item_id == "change_host":
            self.host_dd = Gtk.DropDown.new_from_strings([f"Computador {i + 1}" for i in range(self._host_count)])
            return self._vbox(self.host_dd, self._buttons(item_id))
        if item_id == "command":
            self.command_entry = Gtk.Entry(placeholder_text="ex.: xdg-open https://exemplo.org", hexpand=True)
            self.command_entry.connect("activate", lambda *_: self._run("command"))
            return self._vbox(self.command_entry, self._buttons(item_id))
        if item_id == "window":
            self.window_ops = list(logic.WINDOW_OPS)
            self.window_dd = Gtk.DropDown.new_from_strings(list(logic.WINDOW_OPS.values()))
            return self._vbox(self.window_dd, self._buttons(item_id))
        if item_id == "open":
            self.open_entry = Gtk.Entry(placeholder_text="https://… ou caminho do arquivo ou app", hexpand=True)
            self.open_entry.connect("activate", lambda *_: self._run("open"))
            pick = Gtk.Button(label="Escolher aplicativo instalado…")
            pick.connect("clicked", self._pick_app)
            return self._vbox(self.open_entry, pick, self._buttons(item_id))
        if item_id == "type_text":
            sw, self.text_view = _text_view()
            hint = Gtk.Label(label=f"O texto é digitado como se você o escrevesse (máx. {logic.MAX_TYPE_TEXT} caracteres).",
                             xalign=0, wrap=True)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            return self._vbox(sw, hint, self._buttons(item_id))
        if item_id == "ai_prompt":
            self.ai_services = list(logic.AI_SERVICES)
            self.ai_service_dd = Gtk.DropDown.new_from_strings(list(logic.AI_SERVICES.values()))
            self.ai_preset_dd = Gtk.DropDown.new_from_strings([t[0] for t in logic.AI_TEMPLATES])
            sw, self.ai_template = _text_view(72)
            self.ai_preset_dd.connect("notify::selected", self._on_ai_preset)
            self.ai_preset_dd.set_selected(0)
            self.ai_template.get_buffer().set_text(logic.AI_TEMPLATES[0][1])
            hint = Gtk.Label(label="{selection} é trocado pelo texto selecionado. Nada é enviado sem você ver a "
                                   "página aberta; o Gemini só recebe o prompt copiado para a área de transferência.",
                             xalign=0, wrap=True)
            hint.add_css_class("dim-label")
            hint.add_css_class("caption")
            lab1 = Gtk.Label(label="Serviço", xalign=0)
            lab2 = Gtk.Label(label="Modelo de prompt", xalign=0)
            for lb in (lab1, lab2):
                lb.add_css_class("caption")
                lb.add_css_class("dim-label")
            return self._vbox(lab1, self.ai_service_dd, lab2, self.ai_preset_dd, sw, hint, self._buttons(item_id))
        return None

    def _on_ai_preset(self, dd, _p) -> None:
        tpl = logic.AI_TEMPLATES[dd.get_selected()][1]
        if tpl:
            self.ai_template.get_buffer().set_text(tpl)

    def _pick_app(self, *_a) -> None:
        from .app_picker import AppPickerDialog
        if self._ctx is None:
            return
        AppPickerDialog(self._ctx, lambda e: self.open_entry.set_text(e.desktop_id or e.app_id),
                        installed_only=True).present(self.get_root())

    # ---- ações
    def _params_action(self, item_id: str) -> dict:
        """Monta a ação do editor de parâmetros (ValueError se incompleto)."""
        if item_id == "keys":
            return logic.build_action("keys", keys=self.capture.keys)
        if item_id == "mouse_button":
            return logic.build_action("mouse_button", button=logic.MOUSE_BUTTONS[self.button_dd.get_selected()][0])
        if item_id == "change_host":
            return logic.build_action("change_host", host=self.host_dd.get_selected())
        if item_id == "command":
            return logic.build_action("command", command=self.command_entry.get_text())
        if item_id == "window":
            return logic.build_action("window", op=self.window_ops[self.window_dd.get_selected()])
        if item_id == "open":
            return logic.build_action("open", target=self.open_entry.get_text())
        if item_id == "type_text":
            return logic.build_action("type_text", text=_get_text(self.text_view))
        if item_id == "ai_prompt":
            return logic.build_action("ai_prompt", service=self.ai_services[self.ai_service_dd.get_selected()],
                                      template=_get_text(self.ai_template))
        raise ValueError(item_id)

    def _run(self, item_id: str, test: bool = False) -> None:
        try:
            action = self._params_action(item_id)
        except ValueError as e:
            self.error_hint(str(e))
            return
        if test and self._ctx:
            self._ctx.test_action(action)
        else:
            self._on_action(action)

    def _test_simple(self, item_id: str) -> None:
        action = logic.action_for_simple_item(item_id)
        if action and self._ctx:
            self._ctx.test_action(action)

    def error_hint(self, text: str) -> None:
        if self.get_root():
            self.activate_action("win.toast", GLib.Variant("s", text))

    def _on_row_activated(self, _lb, row) -> None:
        item_id = getattr(row, "item_id", None)
        if item_id is None:
            return
        if item_id == "smart_new":
            if self._ctx:
                self._ctx.open_smart_editor(None, None)
            return
        simple = logic.action_for_simple_item(item_id)
        if simple is not None:
            self._on_action(simple)
            return
        if item_id == "gestures":
            self._on_action(logic.build_action("gestures"))
            return
        rev = self._editors.get(item_id)
        if rev is not None:
            show = not rev.get_reveal_child()
            for k, other in self._editors.items():
                other.set_reveal_child(k == item_id and show)
            if show and item_id == "keys":
                self.capture.grab_focus()
            elif show and item_id == "command":
                self.command_entry.grab_focus()

    # ---- estado
    def set_action(self, action: dict | None) -> None:
        current = logic.item_id_for_action(action)
        kind, p = logic.classify_action(action)
        for item_id, check in self._checks.items():
            check.set_opacity(1.0 if item_id == current else 0.0)
            (self._rows[item_id].add_css_class if item_id == current else self._rows[item_id].remove_css_class)("selected")
        for item_id, rev in self._editors.items():
            rev.set_reveal_child(item_id == current and current in logic.PARAM_ITEMS)
        if kind == "keys":
            self.capture.set_keys(p["keys"])
        elif kind == "mouse_button":
            ids = [b[0] for b in logic.MOUSE_BUTTONS]
            if p["button"] in ids:
                self.button_dd.set_selected(ids.index(p["button"]))
        elif kind == "change_host":
            self.host_dd.set_selected(min(p["host"], self._host_count - 1))
        elif kind == "command":
            self.command_entry.set_text(p["command"])
        elif kind == "window":
            self.window_dd.set_selected(self.window_ops.index(p["op"]) if p["op"] in self.window_ops else 0)
        elif kind == "open":
            self.open_entry.set_text(p["target"])
        elif kind == "type_text":
            self.text_view.get_buffer().set_text(p["text"])
        elif kind == "ai_prompt":
            if p["service"] in self.ai_services:
                self.ai_service_dd.set_selected(self.ai_services.index(p["service"]))
            self.ai_template.get_buffer().set_text(p["template"])


class GestureEditor(Gtk.Box):
    """Mini-diagrama em cruz (cima/baixo/esquerda/direita/clique) + lista para a direção escolhida."""

    def __init__(self, on_change: Callable[[dict], None], host_count: int, ctx=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._on_change = on_change
        self._ctx = ctx
        self.action: dict = logic.build_action("gestures")
        self.slot = "click"
        self._cells: dict[str, tuple[Gtk.Button, Gtk.Label]] = {}

        hint = Gtk.Label(label="Segure o botão e mova o mouse na direção desejada. Solto sem mover, vale o clique.",
                         wrap=True, xalign=0)
        hint.add_css_class("dim-label")
        self.append(hint)
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        grid.add_css_class("gesture-cross")
        titles = dict(logic.GESTURE_SLOTS)
        for slot, row, col in logic.GESTURE_CROSS:
            btn = Gtk.Button()
            btn.add_css_class("gesture-cell")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            t = Gtk.Label(label=titles[slot].upper())
            t.add_css_class("gesture-title")
            a = Gtk.Label(label="", ellipsize=3, max_width_chars=11)
            a.add_css_class("gesture-action")
            box.append(t)
            box.append(a)
            btn.set_child(box)
            btn.set_size_request(92, 56)
            btn.connect("clicked", self._select, slot)
            grid.attach(btn, col, row, 1, 1)
            self._cells[slot] = (btn, a)
        self.append(grid)

        self.slot_title = Gtk.Label(xalign=0)
        self.slot_title.add_css_class("section-title")
        self.append(self.slot_title)
        self.list = ActionList(self._slot_action, allow_gestures=False, host_count=host_count, ctx=ctx, allow_smart=False)
        self.append(self.list)

        self.slider_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        stitle = Gtk.Label(label="SENSIBILIDADE", xalign=0)
        stitle.add_css_class("section-title")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.update_property([Gtk.AccessibleProperty.LABEL], ["Sensibilidade dos gestos"])
        self.scale.connect("value-changed", self._on_scale)
        ends = Gtk.Box()
        for txt, xa in (("Menos sensível", 0.0), ("Mais sensível", 1.0)):
            lb = Gtk.Label(label=txt, hexpand=True, xalign=xa)
            lb.add_css_class("caption")
            lb.add_css_class("dim-label")
            ends.append(lb)
        for w in (stitle, self.scale, ends):
            self.slider_card.append(w)
        self.slider_card.set_margin_top(10)
        self.append(self.slider_card)
        self._timer = 0
        self._loading = False

    def set_action(self, action: dict | None) -> None:
        kind, p = logic.classify_action(action)
        self.action = action if kind == "gestures" else logic.build_action("gestures")
        self._refresh()

    def _refresh(self) -> None:
        _, p = logic.classify_action(self.action)
        sa = self._ctx.smart_actions if self._ctx else None
        for slot, (btn, label) in self._cells.items():
            label.set_label(logic.describe_action(p["slots"][slot], sa))
            (btn.add_css_class if slot == self.slot else btn.remove_css_class)("selected")
        titles = dict(logic.GESTURE_SLOTS)
        self.slot_title.set_label(f"AÇÃO: {titles[self.slot].upper()}")
        self.list.set_action(p["slots"][self.slot])
        self._loading = True
        self.scale.set_value(logic.threshold_to_sensitivity(p["threshold"]))
        self._loading = False

    def _select(self, _btn, slot: str) -> None:
        self.slot = slot
        self._refresh()

    def _slot_action(self, new: dict) -> None:
        self.action = logic.set_gesture_slot(self.action, self.slot, new)
        self._refresh()
        self._on_change(self.action)

    def _on_scale(self, scale) -> None:
        if self._loading:
            return
        if self._timer:
            GLib.source_remove(self._timer)

        def fire():
            self._timer = 0
            _, p = logic.classify_action(self.action)
            self.action = logic.build_action("gestures", slots=p["slots"],
                                             threshold=logic.sensitivity_to_threshold(scale.get_value()))
            self._on_change(self.action)
            return False
        self._timer = GLib.timeout_add(300, fire)


class ActionPanel(Gtk.Box):
    """Painel à direita: título do botão, contexto de perfil, lista de ações (ou editor de gestos)."""

    __gsignals__ = {"close": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "inherit": (GObject.SignalFlags.RUN_FIRST, None, ()),
                    "suggest": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, ctx=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("action-panel")
        self.set_size_request(340, -1)
        self._ctx = ctx
        self._apply: Callable[[dict], None] | None = None
        self.action: dict | None = None

        head = Gtk.Box(spacing=6, margin_top=14, margin_start=18, margin_end=10, margin_bottom=4)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.title = Gtk.Label(xalign=0, wrap=True)
        self.title.add_css_class("panel-title")
        self.subtitle = Gtk.Label(label="Escolha o que este botão faz", xalign=0, wrap=True)
        self.subtitle.add_css_class("dim-label")
        titles.append(self.title)
        titles.append(self.subtitle)
        close = Gtk.Button(icon_name="window-close-symbolic", valign=Gtk.Align.START, tooltip_text="Fechar painel")
        close.add_css_class("flat")
        close.add_css_class("circular")
        close.connect("clicked", lambda *_: self.emit("close"))
        head.append(titles)
        head.append(close)
        self.append(head)

        # contexto de perfil (só com um aplicativo selecionado)
        self.profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=18, margin_end=18,
                                   margin_top=4, margin_bottom=4)
        self.inherit_btn = Gtk.Button(label="Usar o padrão de Todos os aplicativos")
        self.inherit_btn.add_css_class("pill-small")
        self.inherit_btn.connect("clicked", lambda *_: self.emit("inherit"))
        self.suggest_btn = Gtk.Button(label="Usar sugestão do catálogo")
        self.suggest_btn.add_css_class("pill-small")
        self.suggest_btn.connect("clicked", lambda *_: self.emit("suggest"))
        self.suggest_hint = Gtk.Label(xalign=0, wrap=True)
        self.suggest_hint.add_css_class("caption")
        self.suggest_hint.add_css_class("dim-label")
        for w in (self.inherit_btn, self.suggest_btn, self.suggest_hint):
            self.profile_box.append(w)
        self.profile_box.set_visible(False)
        self.append(self.profile_box)

        self.stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._scroll_holder: dict[str, Gtk.ScrolledWindow] = {}
        self.append(self.stack)
        self.list_view: ActionList | None = None
        self.gesture_view: GestureEditor | None = None

    def set_profile_context(self, app_name: str | None, has_override: bool, suggestion: dict | None) -> None:
        """app_name None = perfil global (esconde os botões de perfil)."""
        self.profile_box.set_visible(app_name is not None)
        if app_name is None:
            self.subtitle.set_label("Escolha o que este botão faz")
            return
        self.subtitle.set_label(f"Perfil: {app_name}")
        self.inherit_btn.set_visible(has_override)
        self.suggest_btn.set_visible(suggestion is not None)
        self.suggest_hint.set_visible(suggestion is not None)
        if suggestion is not None:
            self.suggest_hint.set_label("Sugestão: " + logic.describe_action(suggestion))

    def show_control(self, name: str, action: dict | None, raw_xy: bool, host_count: int,
                     apply: Callable[[dict], None]) -> None:
        self.title.set_label(name)
        self._apply = apply
        self.action = action
        for child in list(self._scroll_holder.values()):
            self.stack.remove(child)
        self._scroll_holder.clear()
        self.list_view = ActionList(self._on_list_action, raw_xy, host_count, self._ctx)
        self._add_page("list", self.list_view)
        self.gesture_view = None
        if raw_xy:
            self.gesture_view = GestureEditor(self._on_gesture_change, host_count, self._ctx)
            back = Gtk.Button(label="‹ Outras ações", halign=Gtk.Align.START)
            back.add_css_class("flat")
            back.connect("clicked", lambda *_: self._show_list())
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(back)
            box.append(self.gesture_view)
            self._add_page("gestures", box)
        self.refresh(action)

    def _add_page(self, name: str, child: Gtk.Widget) -> None:
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        child.set_margin_start(18)
        child.set_margin_end(18)
        child.set_margin_bottom(14)
        sw.set_child(child)
        self.stack.add_named(sw, name)
        self._scroll_holder[name] = sw

    def refresh(self, action: dict | None) -> None:
        self.action = action
        kind, _ = logic.classify_action(action)
        self.list_view.set_action(action)
        if self.gesture_view is not None:
            self.gesture_view.set_action(action)
        self.stack.set_visible_child_name("gestures" if kind == "gestures" and self.gesture_view else "list")

    def _show_list(self) -> None:
        self.stack.set_visible_child_name("list")

    def _on_list_action(self, action: dict) -> None:
        self.action = action
        if self._apply:
            self._apply(action)
        self.refresh(action)

    def _on_gesture_change(self, action: dict) -> None:
        self.action = action
        if self._apply:
            self._apply(action)
