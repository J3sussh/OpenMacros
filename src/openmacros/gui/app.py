"""Ponto de entrada da GUI: Adw.Application (io.github.openmacros.App)."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .logic import DATA_DIR, palette_css  # noqa: E402
from ..paths import icon_search_dirs  # noqa: E402
from ..vendor_assets import migrate_legacy_vendor  # noqa: E402
from .window import OpenMacrosWindow  # noqa: E402

APP_ID = "io.github.openmacros.App"
ICON_NAME = "io.github.openmacros.App"


class OpenMacrosApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Adw.Application.do_startup(self)
        try:
            migrate_legacy_vendor()  # ~/.local/share/clique -> ~/.local/share/openmacros (cópia única)
        except Exception:
            pass
        display = Gdk.Display.get_default()
        self._palette = Gtk.CssProvider()
        if display is not None:
            sheet = Gtk.CssProvider()
            sheet.load_from_path(str(DATA_DIR / "style.css"))
            Gtk.StyleContext.add_provider_for_display(display, self._palette, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Gtk.StyleContext.add_provider_for_display(display, sheet, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
            theme = Gtk.IconTheme.get_for_display(display)
            for icons in icon_search_dirs():  # repositório (dev) ou /usr/share/openmacros; o .deb usa o tema hicolor
                theme.add_search_path(str(icons))
        Gtk.Window.set_default_icon_name(ICON_NAME)
        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", lambda *_: self._apply_palette())
        self._apply_palette()
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._show_about)
        self.add_action(about)

    def _apply_palette(self) -> None:
        self._palette.load_from_string(palette_css(Adw.StyleManager.get_default().get_dark()))

    def _show_about(self, *_a) -> None:
        dlg = Adw.AboutDialog(
            application_name="OpenMacros+", application_icon=ICON_NAME, developer_name="Projeto OpenMacros+",
            version="0.1", license_type=Gtk.License.GPL_3_0,
            comments="Configurador de mouses e teclados Logitech para Linux.\n"
                     "Projeto independente, sem vínculo com a Logitech. Imagens importadas, se houver, pertencem à "
                     "Logitech e ficam apenas nesta máquina.")
        dlg.present(self.props.active_window)

    def do_activate(self):
        win = self.props.active_window or OpenMacrosWindow(self)
        win.present()


def main(argv: list[str] | None = None) -> int:
    return OpenMacrosApp().run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
