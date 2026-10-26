"""Smoke v2 com display: daemon fake real (CLIQUE_FAKE=1) + GUI; percorre telas e tira screenshots.
Uso (dentro de xvfb-run + dbus-run-session, com XDG_DATA_HOME isolado):
  python tests/gui/smoke_gui2.py OUT_DIR vendor|svg [ARQUIVO_DEPOTS]"""

import os
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib  # noqa: E402

out, mode = sys.argv[1], sys.argv[2]
depots = sys.argv[3] if len(sys.argv) > 3 else None
tag = "v2" if mode == "vendor" else "v2svg"

from clique import vendor_assets as va  # noqa: E402

if mode == "vendor":
    res = va.import_assets(depots, ["405e", "b015"])
    print("importado:", res.imported, res.missing, flush=True)

daemon = subprocess.Popen([sys.executable, "-m", "clique.daemon.main"], env={**os.environ, "CLIQUE_FAKE": "1"})
time.sleep(2.5)

from clique.gui.app import CliqueApp  # noqa: E402

app = CliqueApp()
M720 = None


def shot(name):
    subprocess.run(["import", "-window", "root", f"{out}/clique-{tag}-{name}.png"], check=False)
    return False


def win():
    return app.props.active_window


def open_dev():
    global M720
    M720 = next(i for i, d in win().devices.items() if "M720" in d["name"])
    win().devices_page.emit("device-activated", M720)
    return False


def page(name):
    win().device_page.stack.set_visible_child_name(name)
    return False


def hot(cid):
    win().device_page.stack.get_child_by_name("buttons")._on_marker(None, cid)
    return False


def gestures():
    bp = win().device_page.stack.get_child_by_name("buttons")
    bp.panel._on_list_action(__import__("clique.gui.logic", fromlist=["x"]).build_action("gestures"))
    return False


def slot(s):
    bp = win().device_page.stack.get_child_by_name("buttons")
    gv = bp.panel.gesture_view
    gv._select(None, s)
    return False


def set_slot_action():
    bp = win().device_page.stack.get_child_by_name("buttons")
    bp.panel.gesture_view.list._on_action({"type": "keys", "keys": ["KEY_VOLUMEUP"]})
    return False


def dbg():
    bp = win().device_page.stack.get_child_by_name("buttons")
    print("DBG", bp.get_width(), bp.art.get_width(), bp.revealer.get_width(), bp.panel.get_width(), flush=True)
    return False


def dark():
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    return False


def light():
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
    return False


def resize(w, h):
    win().set_default_size(w, h)
    return False


def importer():
    win().show_import()
    return False


def add_dev():
    win().show_add_device()
    return False


def close_dialog():
    d = win().get_visible_dialog()
    if d:
        d.force_close()
    return False


def pop():
    win().nav.pop()
    return False


def quit_():
    app.quit()
    return False


T = 1300
steps = [
    lambda: shot("1-home"), add_dev, lambda: shot("1b-add-device"), close_dialog,
    open_dev, lambda: shot("2-buttons"), dbg,
    lambda: hot(82), lambda: shot("3-panel"),
    lambda: hot(208), gestures, lambda: shot("4-gestures"),
    lambda: slot("up"), set_slot_action, lambda: shot("4b-gestures-up"),
    lambda: page("pointer"), lambda: shot("5-pointer"),
    lambda: page("easyswitch"), lambda: shot("6-easyswitch"),
    lambda: page("about"), lambda: shot("6b-about"),
    lambda: page("buttons"), lambda: hot(86), dark, lambda: shot("7-dark-buttons"),
    lambda: page("pointer"), lambda: shot("7b-dark-pointer"),
    pop, lambda: shot("7c-dark-home"), light,
    importer, lambda: shot("8-import-dialog"), close_dialog,
    lambda: resize(520, 760), open_dev, lambda: shot("9-narrow"),
    quit_,
]
for i, fn in enumerate(steps):
    GLib.timeout_add(3500 + i * T, fn)
app.run([])
daemon.terminate()
print("SMOKE DONE", flush=True)
