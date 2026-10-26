"""Barra de perfis por aplicativo: 'Todos os aplicativos' + chips dos apps + '+'."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GObject, Gtk  # noqa: E402

from .app_picker import app_icon  # noqa: E402


class ProfileBar(Gtk.Box):
    __gsignals__ = {
        "app-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "add-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "remove-requested": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "suggest-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(spacing=8, margin_start=16, margin_end=16, margin_top=4, margin_bottom=6)
        self.add_css_class("profile-bar")
        self.chips = Gtk.Box(spacing=6)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL, vscrollbar_policy=Gtk.PolicyType.NEVER,
                                hexpand=True, child=self.chips)
        self.append(sw)
        self.suggest = Gtk.Button(label="Aplicar sugestões", valign=Gtk.Align.CENTER,
                                  tooltip_text="Aplica as sugestões do catálogo para este aplicativo")
        self.suggest.add_css_class("pill-small")
        self.suggest.connect("clicked", lambda *_: self.emit("suggest-requested"))
        self.append(self.suggest)
        self._syncing = False

    def set_state(self, apps: list[str], selected: str, entry_of, can_suggest: bool) -> None:
        """apps: ids com perfil (ou pendentes); entry_of(app_id) -> AppEntry."""
        self._syncing = True
        while (c := self.chips.get_first_child()) is not None:
            self.chips.remove(c)
        group = None

        def make_chip(app_id: str, label: str, icon_entry=None) -> Gtk.Widget:
            nonlocal group
            btn = Gtk.ToggleButton()
            btn.add_css_class("profile-chip")
            inner = Gtk.Box(spacing=8)
            if icon_entry is not None:
                inner.append(app_icon(icon_entry, 18))
            inner.append(Gtk.Label(label=label))
            btn.set_child(inner)
            if group is None:
                group = btn
            else:
                btn.set_group(group)
            btn.set_active(app_id == selected)
            btn.connect("toggled", self._toggled, app_id)
            return btn

        self.chips.append(make_chip("", "Todos os aplicativos"))
        for app_id in apps:
            entry = entry_of(app_id)
            holder = Gtk.Box()
            holder.add_css_class("chip-holder")
            holder.append(make_chip(app_id, entry.name, entry))
            if app_id == selected:
                menu = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Opções do perfil",
                                      valign=Gtk.Align.CENTER)
                menu.add_css_class("flat")
                menu.add_css_class("circular")
                pop = Gtk.Popover()
                rm = Gtk.Button(label="Remover perfil")
                rm.add_css_class("destructive-action")
                rm.connect("clicked", lambda *_a, a=app_id, p=pop: (p.popdown(), self.emit("remove-requested", a)))
                pop.set_child(rm)
                menu.set_popover(pop)
                holder.append(menu)
            self.chips.append(holder)
        add = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Adicionar aplicativo", valign=Gtk.Align.CENTER)
        add.add_css_class("circular")
        add.add_css_class("profile-add")
        add.update_property([Gtk.AccessibleProperty.LABEL], ["Adicionar perfil de aplicativo"])
        add.connect("clicked", lambda *_: self.emit("add-requested"))
        self.chips.append(add)
        self.suggest.set_visible(can_suggest)
        self._syncing = False

    def _toggled(self, btn, app_id: str) -> None:
        if btn.get_active() and not self._syncing:
            self.emit("app-selected", app_id)
