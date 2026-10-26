"""Diálogo para escolher um aplicativo (recentes desta sessão + instalados, com busca)."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..apps import AppEntry  # noqa: E402


def app_icon(entry: AppEntry, size: int = 32) -> Gtk.Image:
    img = Gtk.Image()
    if entry.icon is not None:
        img.set_from_gicon(entry.icon)
    else:
        img.set_from_icon_name("application-x-executable-symbolic")
    img.set_pixel_size(size)
    return img


MAX_ROWS = 60


class AppPickerDialog(Adw.Dialog):
    def __init__(self, ctx, on_pick: Callable[[AppEntry], None], installed_only: bool = False, exclude: set | None = None,
                 running: bool = False):
        super().__init__(title="Escolher aplicativo", content_width=440, content_height=580)
        self._ctx = ctx
        self._on_pick = on_pick
        self._exclude = exclude or set()
        self._recent: list[AppEntry] = []
        self._recent_title = "Em execução" if running else "Recentes (nesta sessão)"
        self._installed = ctx.apps.installed()

        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12, margin_end=12, margin_bottom=12)
        self.search = Gtk.SearchEntry(placeholder_text="Buscar aplicativo…")
        self.search.connect("search-changed", lambda *_: self._rebuild())
        box.append(self.search)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("action-list")
        self.list.connect("row-activated", self._activated)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, child=self.list)
        box.append(sw)
        view.set_content(box)
        self.set_child(view)
        self.set_focus(self.search)
        self._rebuild()
        if running:
            ctx.client.get_running_apps(self._got_running)
        elif not installed_only:
            ctx.client.get_recent_apps(self._got_recent)

    def _got_running(self, apps, error) -> None:
        if error:  # serviço sem GetRunningApps: cai para os recentes da sessão
            self._recent_title = "Recentes (nesta sessão)"
            self._ctx.client.get_recent_apps(self._got_recent)
            return
        self._got_recent(apps, None)

    def _got_recent(self, apps, error) -> None:
        if error or not apps:
            return
        seen = set()
        self._recent = []
        for a in apps:
            aid = str(a.get("app_id", ""))
            if aid and aid not in seen:
                seen.add(aid)
                self._recent.append(self._ctx.apps.entry(aid))
        self._rebuild()

    def _section(self, title: str) -> None:
        lab = Gtk.Label(label=title.upper(), xalign=0, margin_top=10, margin_bottom=4, margin_start=6)
        lab.add_css_class("section-title")
        row = Gtk.ListBoxRow(activatable=False, selectable=False, child=lab)
        self.list.append(row)

    def _add(self, entry: AppEntry) -> None:
        box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4)
        box.append(app_icon(entry))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        name = Gtk.Label(label=entry.name, xalign=0, ellipsize=3)
        sub = Gtk.Label(label=entry.app_id, xalign=0, ellipsize=3)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        texts.append(name)
        texts.append(sub)
        box.append(texts)
        row = Gtk.ListBoxRow(child=box)
        row.add_css_class("action-row")
        row.entry = entry  # type: ignore[attr-defined]
        self.list.append(row)

    def _rebuild(self) -> None:
        while (child := self.list.get_first_child()) is not None:
            self.list.remove(child)
        q = self.search.get_text()
        recent = [e for e in logic.filter_apps(self._recent, q) if e.app_id not in self._exclude]
        rids = {e.app_id for e in recent}
        installed = [e for e in logic.filter_apps(self._installed, q) if e.app_id not in self._exclude]
        if recent:
            self._section(self._recent_title)
            for e in recent:
                self._add(e)
        if installed:
            self._section("Instalados")
            shown = [e for e in installed if e.app_id not in rids or not recent]
            for e in shown[:MAX_ROWS]:
                self._add(e)
            if len(shown) > MAX_ROWS:
                self._section(f"+{len(shown) - MAX_ROWS} aplicativos — digite para filtrar")
        if not recent and not installed:
            self._section("Nenhum aplicativo encontrado")

    def _activated(self, _lb, row) -> None:
        entry = getattr(row, "entry", None)
        if entry is not None:
            self.close()
            self._on_pick(entry)
