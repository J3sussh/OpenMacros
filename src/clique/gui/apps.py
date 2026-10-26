"""Aplicativos instalados (Gio.AppInfo): nomes e ícones vêm do sistema, não do repositório."""

from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

from . import logic  # noqa: E402


@dataclass
class AppEntry:
    app_id: str
    name: str
    icon: Gio.Icon | None = None
    desktop_id: str = ""


class AppIndex:
    def __init__(self):
        self._by_id: dict[str, AppEntry] = {}
        self._by_desktop: dict[str, AppEntry] = {}
        self._installed: list[AppEntry] = []
        self._built = False

    def _build(self) -> None:
        self._built = True
        seen: set[str] = set()
        for ai in Gio.AppInfo.get_all():
            if not ai.should_show():
                continue
            did = ai.get_id() or ""
            wm = ai.get_startup_wm_class() if isinstance(ai, Gio.DesktopAppInfo) else None
            ids = logic.app_ids_for_desktop(did, wm)
            if not ids or did in seen:
                continue
            seen.add(did)
            entry = AppEntry(ids[0], ai.get_display_name() or ids[0], ai.get_icon(), did)
            self._installed.append(entry)
            self._by_desktop[did] = entry
            for i in ids:
                self._by_id.setdefault(i, entry)
        self._installed.sort(key=lambda e: e.name.lower())

    def reset(self) -> None:
        self._by_id.clear()
        self._installed.clear()
        self._by_desktop.clear()
        self._built = False

    def installed(self) -> list[AppEntry]:
        if not self._built:
            self._build()
        return list(self._installed)

    def entry(self, app_id: str) -> AppEntry:
        """Entrada do app (sistema > catálogo > o próprio id)."""
        if not self._built:
            self._build()
        key = logic.resolve_app_id(app_id)
        found = self._by_id.get(app_id.lower()) or self._by_id.get(key)
        if found:
            return AppEntry(app_id, found.name, found.icon, found.desktop_id)
        cat = logic.catalog_entry(app_id)
        if cat:
            for did in cat.get("desktop") or []:
                inst = self._by_desktop.get(did)
                if inst:
                    return AppEntry(app_id, inst.name, inst.icon, inst.desktop_id)
            return AppEntry(app_id, cat.get("name", app_id), None, (cat.get("desktop") or [""])[0])
        return AppEntry(app_id, app_id.replace("-", " ").title())

    def name_of(self, app_id: str) -> str:
        return self.entry(app_id).name
