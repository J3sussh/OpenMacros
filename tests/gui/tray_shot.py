"""Captura do menu da bandeja (Xvfb): constrói o menu real contra o serviço falso e o exibe como popup."""
import subprocess
import sys

from gi.repository import GLib, Gio

from openmacros.tray import main as tm
from fake_service import FakeService

out = sys.argv[1]
service = FakeService()
app = Gio.Application(application_id="io.github.openmacros.TrayShot")
holder = {}


def activate(_a):
    from gi.repository import Gtk
    tray = tm.Tray(app)
    tray.start()
    app.hold()
    win = Gtk.Window(title="host", default_width=320, default_height=60)
    win.move(40, 40)
    win.show_all()
    holder["tray"], holder["win"] = tray, win

    def pop():
        menu = tray._menu(tray.client.devices)
        from gi.repository import Gdk
        menu.popup_at_widget(win, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
        holder["menu"] = menu
        return False
    GLib.timeout_add(2500, pop)
    GLib.timeout_add(3800, lambda: (subprocess.run(["import", "-window", "root", out], check=False), False)[1])
    GLib.timeout_add(4600, lambda: (app.quit(), False)[1])


app.connect("activate", activate)
app.run([])
print("TRAY SHOT DONE")
