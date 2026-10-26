"""dbus-run-session + Xvfb: abre a janela real contra o serviço falso e confere F2/F3/F4/F5/F7.
Uso: scenario_ui.py new|old [OUT_DIR para screenshots]"""

import json
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from openmacros.gui.app import OpenMacrosApp  # noqa: E402
from openmacros.gui.widgets.preferences import PreferencesDialog  # noqa: E402
from fake_service import FakeService  # noqa: E402

mode = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else None
service = FakeService(v2=(mode == "new"))
app = OpenMacrosApp()
fail = []


def check(cond, msg):
    if not cond:
        fail.append(msg)


def win():
    return app.props.active_window


def shot(name):
    if out:
        subprocess.run(["import", "-window", "root", f"{out}/openmacros-v4-{name}.png"], check=False)
    return False


def menu_labels():
    m = win().devices_page.menu
    return [m.get_item_attribute_value(i, "label", None).get_string() for i in range(m.get_n_items())]


def find(widget, cls, pred=lambda w: True):
    out_ = []

    def walk(w):
        if isinstance(w, cls) and pred(w):
            out_.append(w)
        c = w.get_first_child()
        while c is not None:
            walk(c)
            c = c.get_next_sibling()
    walk(widget)
    return out_


def step_menu():
    labels = menu_labels()
    if mode == "new":
        check(labels[0] == "Preferências", f"menu {labels}")
    else:
        check("Preferências" not in labels, f"menu antigo {labels}")
    return False


def step_prefs():
    if mode == "old":
        return False
    win().show_preferences()
    return False


def step_prefs_check():
    if mode == "old":
        return False
    dlg = win().get_visible_dialog()
    check(isinstance(dlg, PreferencesDialog), "diálogo de preferências")
    dlg.row_threshold.set_value(40)
    dlg.row_profile.set_active(False)
    return False


def step_prefs_verify():
    if mode == "old":
        return False
    check(service.prefs["osd_profile"] is False, f"osd_profile gravado: {service.prefs}")
    check(service.prefs["battery_threshold"] == 40, f"threshold gravado: {service.prefs}")
    win().get_visible_dialog().force_close()
    return False


def open_dev():
    dev = next(i for i, d in win().devices.items() if "M720" in d["name"])
    win().devices_page.emit("device-activated", dev)
    return False


def scroll_to(item_id):
    panel = win().device_page.stack.get_child_by_name("buttons").panel
    lv = panel.list_view
    row = lv._rows[item_id]
    sw = panel._scroll_holder["list"]

    def go():
        r = row.translate_coordinates(lv, 0, 0)
        if r:
            sw.get_vadjustment().set_value(max(0, r[1] - 20))
        return False
    GLib.timeout_add(300, go)
    return False


def panel_ai():
    b = win().device_page.stack.get_child_by_name("buttons")
    b._on_marker(None, 83)
    lv = b.panel.list_view
    lv._on_row_activated(None, lv._rows["ai_prompt"])
    if mode == "new":
        check(lv.ai_delivery_dd.get_selected() == 0, "entrega padrão = clipboard")
        lv.ai_delivery_dd.set_selected(1)
        check(not (lv._params_action("ai_prompt").get("delivery") is None), "delivery presente")
        check(lv._params_action("ai_prompt")["delivery"] == "url", "delivery url")
        lv.ai_delivery_dd.set_selected(0)
        check(lv._params_action("ai_prompt")["delivery"] == "clipboard", "delivery clipboard")
    else:
        check("delivery" not in lv._params_action("ai_prompt"), "daemon antigo: sem delivery")
    return False


def panel_type():
    lv = win().device_page.stack.get_child_by_name("buttons").panel.list_view
    lv._on_row_activated(None, lv._rows["type_text"])
    lv.text_view.get_buffer().set_text("ação — çãõ")
    check(lv._params_action("type_text") == {"type": "type_text", "text": "ação — çãõ"}, "type_text padrão (paste)")
    lv.keys_switch.set_active(True)
    check(lv._params_action("type_text")["method"] == "keys", "type_text keys")
    lv.keys_switch.set_active(False)
    return False


def tab_about():
    win().device_page.stack.set_visible_child_name("about")
    return False


def f7():
    page = win().device_page
    page.select_app("firefox")
    check("firefox" in page.device["profiles"], "pré-condição")
    dev = json.loads(json.dumps(page.device))
    dev["profiles"] = {}
    win()._on_device_updated(None, dev["id"], dev)
    labels = [b.get_child().get_last_child().get_label() for b in find(page.profile_bar, __import__("gi").repository.Gtk.ToggleButton)]
    check("firefox" in page.pending or page.selected_app == "firefox", "selecionado permanece")
    page.stack.set_visible_child_name("buttons")
    page.select_app("")
    labels = [b.get_child().get_last_child().get_label() for b in find(page.profile_bar, __import__("gi").repository.Gtk.ToggleButton)]
    check(len(labels) == 1, f"chip do perfil vazio sumiu: {labels} {page.pending} {page._seen} {page.device.get('profiles')}")
    return False


def quit_():
    app.quit()
    return False


steps = [step_menu, lambda: shot("0-home"), step_prefs, lambda: shot("1-prefs"), step_prefs_check, step_prefs_verify,
         open_dev, panel_ai, lambda: scroll_to("ai_prompt"), lambda: shot("2-ai"), panel_type, lambda: scroll_to("type_text"), lambda: shot("3-type"), tab_about,
         lambda: shot("4-about"), f7, quit_]
for i, fn in enumerate(steps):
    GLib.timeout_add(3000 + i * 1200, fn)
GLib.timeout_add(40000, lambda: (fail.append("timeout"), app.quit()))
app.run([])
if fail:
    print("FAIL", fail)
    sys.exit(1)
print("SCENARIO OK")
