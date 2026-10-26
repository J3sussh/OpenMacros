"""Bandeja do OpenMacros+: AyatanaAppIndicator3 (GTK3). Executável: `openmacros-tray` ou `python3 -m openmacros.tray`."""

from __future__ import annotations

import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from ..paths import icon_search_dirs  # noqa: E402
from . import model  # noqa: E402
from .client import TrayClient  # noqa: E402

TRAY_ID = "io.github.openmacros.Tray"
DESKTOP_ID = "io.github.openmacros.App.desktop"


def _icon_dirs() -> list[str]:
    """Diretórios extras de ícones (repositório em modo dev, /usr/share/openmacros); o tema do sistema já é usado."""
    return [str(d) for d in icon_search_dirs()]


def app_name(app_id: str) -> str:
    for cand in (f"{app_id}.desktop", f"{app_id.lower()}.desktop"):
        info = Gio.DesktopAppInfo.new(cand)
        if info is not None:
            return info.get_display_name()
    return app_id[:1].upper() + app_id[1:]


def open_app() -> None:
    info = Gio.DesktopAppInfo.new(DESKTOP_ID)
    try:
        if info is not None and info.launch([], None):
            return
    except GLib.Error:
        pass
    try:
        subprocess.Popen(["openmacros"], start_new_session=True)
    except OSError as e:
        print(f"openmacros-tray: não consegui abrir o OpenMacros+: {e}", file=sys.stderr)


class Tray:
    def __init__(self, app: Gio.Application):
        self.app = app
        self.client = TrayClient(self._changed)
        self.indicator = AppIndicator.Indicator.new(TRAY_ID, model.ICON_MISSING,
                                                    AppIndicator.IndicatorCategory.HARDWARE)
        icons = _icon_dirs()
        if icons:
            self.indicator.set_icon_theme_path(icons[0])
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("OpenMacros+")
        self._rebuild_id = 0
        self._look: tuple | None = None
        self._spec: tuple | None = None
        self._changed()

    def start(self) -> None:
        self.client.start()

    # ---- atualização (agrupa rajadas de sinais; só recria o que mudou, para o menu não piscar)
    def _changed(self) -> None:
        if not self._rebuild_id:
            self._rebuild_id = GLib.timeout_add(80, self._rebuild)

    def _rebuild(self) -> bool:
        self._rebuild_id = 0
        devs = self.client.devices
        look = (model.tray_icon(devs), model.tooltip(devs))
        spec = model.menu_spec(devs, app_name)
        if look != self._look:
            self._look = look
            self.indicator.set_icon_full(*look)
        if spec != self._spec:
            self._spec = spec
            self.indicator.set_menu(self._menu(spec))
        return False

    def _menu(self, spec: tuple) -> Gtk.Menu:
        menu = Gtk.Menu()
        for entry in spec:
            kind = entry[0]
            if kind == "sep":
                menu.append(Gtk.SeparatorMenuItem())
            elif kind == "label":
                item = Gtk.MenuItem(label=entry[1])
                item.set_sensitive(False)
                menu.append(item)
            elif kind == "easy":
                _k, title, dev_id, hosts = entry
                item = Gtk.MenuItem(label=title)
                sub = Gtk.Menu()
                for idx, label, current in hosts:
                    row = Gtk.CheckMenuItem(label=label)
                    row.set_draw_as_radio(True)
                    row.set_active(current)
                    if not current:
                        row.connect("activate", lambda _w, i=idx, d=dev_id: self.client.change_host(d, i))
                    else:
                        row.set_sensitive(False)
                    sub.append(row)
                item.set_submenu(sub)
                menu.append(item)
            elif kind == "open":
                item = Gtk.MenuItem(label="Abrir OpenMacros+")
                item.connect("activate", lambda *_: open_app())
                menu.append(item)
            elif kind == "quit":
                item = Gtk.MenuItem(label="Sair")
                item.connect("activate", lambda *_: self.app.quit())
                menu.append(item)
        menu.show_all()
        return menu


def main(argv: list[str] | None = None) -> int:
    app = Gio.Application(application_id=TRAY_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
    holder: dict = {}

    def activate(_app) -> None:
        if "tray" not in holder:
            holder["tray"] = Tray(app)
            holder["tray"].start()
            app.hold()

    app.connect("activate", activate)
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
