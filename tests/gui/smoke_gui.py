"""Smoke test com display: abre a janela contra o serviço falso e percorre as telas.
Uso: dbus-run-session -- python tests/gui/smoke_gui.py [dir-screenshots]"""

import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from clique.gui.app import CliqueApp  # noqa: E402
from clique.gui.window import CliqueWindow  # noqa: E402
from fake_service import FakeService  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else None
service = FakeService()
app = CliqueApp()
state = {}


def shot(name):
    if out:
        subprocess.run(["import", "-window", "root", f"{out}/clique-{name}.png"], check=False)
    return False


def win():
    return app.props.active_window


def open_dev(i):
    w = win()
    w.devices_page.emit("device-activated", i)
    return False


def tab(name):
    win().device_page.stack.set_visible_child_name(name)
    return False


def picker(cid):
    page = win().device_page.stack.get_child_by_name("buttons")
    page._on_marker(page.art, cid)
    return False


def close_dialogs():
    d = win().get_visible_dialog() if hasattr(win(), "get_visible_dialog") else None
    if d:
        d.close()
    return False


def pop():
    win().nav.pop()
    return False


steps = [
    (5000, lambda: shot("1-devices")),
    (5200, lambda: open_dev("046d:405e:ABCD1234")),
    (7200, lambda: shot("2-buttons")),
    (7400, lambda: picker(208)),
    (9400, lambda: shot("3-picker-gestures")),
    (9600, close_dialogs),
    (9800, lambda: tab("pointer")),
    (11000, lambda: shot("4-pointer")),
    (11200, lambda: tab("easyswitch")),
    (12400, lambda: shot("5-easyswitch")),
    (12600, lambda: tab("about")),
    (13800, lambda: shot("6-about")),
    (14000, pop),
    (14200, lambda: open_dev("046d:b35b:KB1")),
    (16200, lambda: shot("7-keyboard-offline")),
    (17000, lambda: app.quit() or False),
]
for ms, fn in steps:
    GLib.timeout_add(ms, fn)
app.run([])
print("SMOKE DONE")
