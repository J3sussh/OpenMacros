"""Smoke v3 (integrações): GUI + serviço (fake próprio ou daemon real com OPENMACROS_FAKE=1) e screenshots.
Uso (xvfb-run + dbus-run-session, XDG_DATA_HOME isolado):
  python tests/gui/smoke_gui3.py OUT_DIR own|daemon [ARQUIVO_DEPOTS]"""

import os
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

out, mode = sys.argv[1], sys.argv[2]
depots = sys.argv[3] if len(sys.argv) > 3 else None
tag = "v3" if mode == "own" else "v3d"

from openmacros import vendor_assets as va  # noqa: E402
from openmacros.gui import logic  # noqa: E402

if depots:
    va.import_assets(depots, ["405e", "b015"])

daemon = None
if mode == "daemon":
    daemon = subprocess.Popen([sys.executable, "-m", "openmacros.daemon.main"], env={**os.environ, "OPENMACROS_FAKE": "1"})
    time.sleep(2.5)
else:
    from fake_service import FakeService
    service = FakeService()

from openmacros.gui.app import OpenMacrosApp  # noqa: E402

app = OpenMacrosApp()
bus = Gio.bus_get_sync(Gio.BusType.SESSION)


def shot(name):
    subprocess.run(["import", "-window", "root", f"{out}/openmacros-{tag}-{name}.png"], check=False)
    return False


def win():
    return app.props.active_window


def dev_page():
    return win().device_page


def buttons():
    return dev_page().stack.get_child_by_name("buttons")


def open_dev():
    dev = next(i for i, d in win().devices.items() if "M720" in d["name"])
    win().devices_page.emit("device-activated", dev)
    return False


def debug_app(app_id):
    bus.call("io.github.openmacros", "/io/github/openmacros", "io.github.openmacros.Manager1", "DebugSetActiveApp",
             GLib.Variant("(s)", (app_id,)), None, Gio.DBusCallFlags.NONE, 3000, None, None)
    return False


def select_app(app_id):
    if app_id not in dev_page().pending and app_id not in logic.profile_app_ids(dev_page().device):
        dev_page().pending.append(app_id)
    dev_page().select_app(app_id)
    return False


def hot(cid):
    buttons()._on_marker(None, cid)
    return False


def scroll_to_item(item_id):
    lv = buttons().panel.list_view
    row = lv._rows[item_id]
    rev = lv._editors.get(item_id)
    if rev is not None:
        lv._on_row_activated(None, row)
    sw = buttons().panel._scroll_holder["list"]

    def go():
        r = row.translate_coordinates(lv, 0, 0)
        if r:
            sw.get_vadjustment().set_value(max(0, r[1] - 20))
        return False
    GLib.timeout_add(400, go)
    return False


def page(name):
    dev_page().stack.set_visible_child_name(name)
    return False


def home():
    while win().nav.get_visible_page() is not win().devices_page:
        win().nav.pop()
    return False


def smart_list():
    win().devices_page.emit("smart-actions")
    return False


def smart_editor(template):
    win().ctx.open_smart_editor(logic.smart_from_template(template), None)
    return False


def scheme(dark):
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK if dark else Adw.ColorScheme.FORCE_LIGHT)
    return False


def pop():
    win().nav.pop()
    return False


def picker():
    from openmacros.gui.widgets.app_picker import AppPickerDialog
    AppPickerDialog(win().ctx, lambda e: None).present(win())
    return False


def close_dialog():
    d = win().get_visible_dialog()
    if d:
        d.force_close()
    return False


def suggest_current():
    buttons()._suggest()
    return False


def quit_():
    app.quit()
    return False


steps = [
    lambda: shot("0-home"), open_dev, lambda: debug_app("firefox"), lambda: select_app("firefox"),
    lambda: shot("1-profiles-firefox"),
    lambda: hot(91), lambda: shot("2-panel-override"),
    lambda: hot(83), lambda: shot("2b-panel-inherited"),
    lambda: scroll_to_item("ai_prompt"), lambda: shot("3-panel-ia"),
    lambda: scroll_to_item("open"), lambda: shot("3b-panel-open"),
    picker, lambda: shot("3c-app-picker"), close_dialog,
    lambda: page("pointer"), lambda: shot("4-pointer-firefox"),
    lambda: page("buttons"), lambda: select_app(""), lambda: debug_app("code"), lambda: shot("5-global-indicator"),
    home, smart_list, lambda: shot("6-smart-list"),
    lambda: smart_editor("pentest"), lambda: shot("7-smart-editor"),
    lambda: scheme(True), lambda: shot("8-dark-editor"),
    pop, pop, open_dev, lambda: select_app("firefox"), lambda: hot(208), lambda: shot("9-dark-panel-gestures"),
    quit_,
]
T = 1400
for i, fn in enumerate(steps):
    GLib.timeout_add(3500 + i * T, fn)
app.run([])
if daemon:
    daemon.terminate()
print("SMOKE DONE", flush=True)
