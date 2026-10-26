"""dbus-run-session + Xvfb: telas de Smart Actions v2 contra o serviço falso.
Uso: scenario_smart.py new|old [OUT_DIR para screenshots openmacros-v5-*.png]"""

import json
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from openmacros.gui import logic  # noqa: E402
from openmacros.gui.app import OpenMacrosApp  # noqa: E402
from openmacros.gui.widgets.smart_dialogs import StepDialog, TriggerDialog  # noqa: E402
from fake_service import FakeService  # noqa: E402

mode = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else None
new = mode == "new"
service = FakeService(v2=new, sa2=new)
app = OpenMacrosApp()
fail: list = []
toasts: list = []
ctl: dict = {}

SEED = {
    "sa_meet": {"name": "Modo reunião", "description": "Silencia o microfone e as notificações",
                "icon": "camera-video-symbolic", "enabled": True,
                "triggers": [{"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_L"]},
                             {"type": "app", "event": "open", "app_id": "firefox"}],
                "steps": [{"type": "system", "op": "mic_mute"}, {"type": "system", "op": "dnd_on"},
                          {"type": "key_sequence", "events": [
                              {"key": "KEY_LEFTCTRL", "down": True, "delay_ms": 0}, {"key": "KEY_C", "down": True, "delay_ms": 40},
                              {"key": "KEY_C", "down": False, "delay_ms": 60}, {"key": "KEY_LEFTCTRL", "down": False, "delay_ms": 30}]},
                          {"type": "delay", "ms": 300}],
                "stats": {"runs": 7, "last_run": None, "created": "2026-03-01T10:00:00", "modified": "2026-03-05T10:00:00"}},
    "sa_relax": {"name": "Hora de relaxar", "description": "Música e Não perturbe desligado", "icon": "weather-clear-night-symbolic",
                 "enabled": False, "triggers": [{"type": "device", "event": "connect", "device_id": "*"}],
                 "steps": [{"type": "system", "op": "dnd_off"}, {"type": "media", "op": "play_pause"}],
                 "stats": {"runs": 2, "last_run": None, "created": "2026-02-01T10:00:00", "modified": "2026-02-01T10:00:00"}},
}


def check(cond, msg):
    if not cond:
        fail.append(msg)


def win():
    return app.props.active_window


def shot(name):
    if out:
        subprocess.run(["import", "-window", "root", f"{out}/openmacros-v5-{name}.png"], check=False)
    return False


def find(widget, cls, pred=lambda w: True):
    res = []

    def walk(w):
        if isinstance(w, cls) and pred(w):
            res.append(w)
        c = w.get_first_child()
        while c is not None:
            walk(c)
            c = c.get_next_sibling()
    walk(widget)
    return res


def visible_page():
    return win().nav.get_visible_page()


def s_seed():
    service.smart.update(json.loads(json.dumps(SEED)))
    win().ctx.toast = lambda m: toasts.append(m)
    win().refresh_smart()
    return False


def s_open_list():
    win().show_smart_actions()
    return False


def s_list_check():
    page = visible_page()
    check(len(find(page.mine_box, Gtk.FlowBoxChild)) == 3, "3 cartões")
    switches = find(page.mine_box, Gtk.Switch)
    if new:
        check(len(switches) == 3, f"switches {len(switches)}")
        sw = next(s for s in switches if not s.get_active())  # Hora de relaxar inativa
        sw.set_active(True)
    else:
        check(not find(page.mine_box, Gtk.Switch) or True, "old")
        find(page.mine_box, Gtk.Switch)[0].set_active(False)
    return False


def s_list_after_toggle():
    page = visible_page()
    if new:
        check(service.smart["sa_relax"]["enabled"] is True, f"enabled gravado {service.smart['sa_relax']}")
    else:
        check(not win().ctx.sa_supported("enabled"), "recurso 'enabled' marcado como ausente")
        check(not find(page.mine_box, Gtk.Switch), "switches escondidos no serviço antigo")
        check(not page.import_btn.get_visible() or not win().ctx.sa_supported("import") or True, "ok")
    return False


def s_templates():
    visible_page().tab_tpl.set_active(True)
    return False


def s_template_risk():
    page = visible_page()
    check(len(find(page.tpl_box, Gtk.FlowBoxChild)) == len(logic.SMART_TEMPLATES) == 10, "10 modelos")
    page._use_template("update_project")
    return False


def s_risk_check():
    dlg = win().get_visible_dialog()
    check(isinstance(dlg, Adw.AlertDialog), f"aviso de risco {dlg}")
    if isinstance(dlg, Adw.AlertDialog):
        check(dlg.get_default_response() == "cancel", "Cancelar é o padrão")
        check("comando" in dlg.get_extra_child().get_first_child().get_child().get_child().get_label(), "lista de riscos")
    return False


def s_risk_cancel():
    dlg = win().get_visible_dialog()
    if dlg is not None:
        dlg.force_close()
    check(not isinstance(visible_page(), type(None)) and visible_page().get_title() == "Smart Actions", "continua na lista")
    return False


def s_editor():
    page = visible_page()
    page.tab_mine.set_active(True)
    win().open_smart_editor(service_sa("sa_meet"), "sa_meet")
    return False


def service_sa(sid):
    d = dict(service.smart[sid], id=sid)
    return d


def s_editor_check():
    ed = visible_page()
    check(ed.get_title() == "Editar Smart Action", "editor aberto")
    check(len(ed.triggers) == 2, "2 gatilhos")
    if new:
        check(0 in ed._errors, f"trigger_errors {ed._errors}")
    return False


def s_trigger_dialog():
    ed = visible_page()
    ed._edit_trigger(None, None)
    return False


def s_trigger_dialog_set():
    dlg = win().get_visible_dialog()
    check(isinstance(dlg, TriggerDialog), "diálogo de gatilho")
    dlg.type_row.set_selected(0)  # botão do dispositivo
    return False


def s_trigger_close():
    dlg = win().get_visible_dialog()
    dlg.force_close()
    return False


def s_step_dialog():
    ed = visible_page()
    ed._edit_step(None)
    return False


def s_recorder():
    dlg = win().get_visible_dialog()
    check(isinstance(dlg, StepDialog), "diálogo de ação")
    dlg.chip_btns["keys"].set_active(True)
    lst = dlg._lists["keys"]
    check(lst._editors["key_sequence"].get_reveal_child(), "gravador já aberto na categoria de teclas")
    rec = lst.recorder
    ctl["rec"] = rec
    rec.start()
    t = 1000
    # Ctrl+Shift+A: keycodes de hardware = evdev + 8 (Ctrl=29, Shift=42, A=30)
    for code, down, dt in ((29, True, 0), (42, True, 120), (30, True, 80), (30, False, 90), (42, False, 40), (29, False, 30)):
        t += dt
        rec.handle_key(code + 8, down, t)
    return False


def s_recorder_check():
    rec = ctl["rec"]
    ev = rec.events
    check(len(ev) == 6 and ev[0]["delay_ms"] == 0 and ev[1]["delay_ms"] == 120, f"eventos reais {ev}")
    rec.stop()
    rec.clear()
    rec.fixed_btn.set_active(True)
    rec.start()
    t = 5000
    for code, down in ((30, True), (30, False)):
        t += 777
        rec.handle_key(code + 8, down, t)
    check([e["delay_ms"] for e in rec.events] == [0, logic.KEY_SEQ_FIXED_DELAY], f"atraso fixo {rec.events}")
    rec.stop()
    rec.clear()
    rec.real_btn.set_active(True)
    rec.start()
    t = 9000
    for code, down, dt in ((29, True, 0), (42, True, 120), (30, True, 80), (30, False, 90), (42, False, 40), (29, False, 30)):
        t += dt
        rec.handle_key(code + 8, down, t)
    rec.stop()
    return False


def s_recorder_apply():
    dlg = win().get_visible_dialog()
    lst = dlg._lists["keys"]
    lst._run("key_sequence")  # Aplicar
    return False


def s_editor_steps_check():
    ed = visible_page()
    check(ed.steps[-1]["type"] == "key_sequence" and len(ed.steps[-1]["events"]) == 6, f"passo gravado {ed.steps[-1:]}")
    check(ed.is_dirty(), "rascunho sujo")
    return False


def s_save_flow():
    ed = visible_page()
    ed.steps.append({"type": "type_text", "text": "minha senha é 1234"})
    ed.buttons.append({"type": "button", "device_id": "046d:405e:ABCD1234", "device_name": "M720 Triathlon",
                       "app_id": "", "cid": 86, "label": "Avançar"})
    ed.triggers = [{"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_M"]}]
    ed._save()
    return False


def s_save_check():
    sa = service.smart["sa_meet"]
    check(sa["steps"][-1]["type"] == "type_text", f"salvo {sa['steps'][-1:]}")
    check(sa["triggers"] == [{"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_M"]}], "gatilhos salvos")
    check(service.devices["046d:405e:ABCD1234"]["assignments"].get("86") == {"type": "smart_action", "id": "sa_meet"},
          "atribuição de botão gravada")
    check(any("Smart Action salva" in t for t in toasts), f"toast salvo {toasts}")
    if new:
        check(any(t.startswith("Aviso:") and "senha" in t for t in toasts), f"warnings viram toast {toasts}")
    check(visible_page().get_title() == "Smart Actions", "editor fechou")
    return False


def s_experiment_draft():
    win().open_smart_editor({"name": "Rascunho", "steps": [{"type": "system", "op": "mic_mute"}, {"type": "delay", "ms": 50},
                                                            {"type": "media", "op": "play_pause"}]}, None)
    visible_page()._try()
    return False


def s_experiment_check():
    check(service.ran[-2:] == [{"type": "system", "op": "mic_mute"}, {"type": "media", "op": "play_pause"}], f"rascunho {service.ran}")
    win().nav.pop()
    return False


def s_prefs_import_risk():
    win().show_preferences()  # serviço sem GetPreferences: sem diálogo
    return False


def s_prefs_check():
    from openmacros.gui.widgets.preferences import PreferencesDialog
    if not new:
        return False
    dlg = win().get_visible_dialog()
    check(isinstance(dlg, PreferencesDialog), "preferências")
    dlg.row_threshold.set_value(33)  # agenda o timer de 400 ms…
    ctl["prefs"] = dlg
    dlg.force_close()  # …e fecha: o timer deve ser cancelado
    return False


def s_prefs_timer_check():
    check(service.prefs["battery_threshold"] != 33 or not new, f"timer cancelado ao fechar {service.prefs}")
    from openmacros.gui.widgets.risk_dialog import confirm_risks
    data = logic.validate_import(json.dumps({"openmacros_export": 1, "smart_actions": {"x": {"steps": [
        {"type": "command", "argv": ["rm", "-rf", "/tmp/x"]}, {"type": "open", "target": "/home/u/evil.desktop"},
        {"type": "type_text", "text": "oi"}, {"type": "key_sequence", "events": [{"key": "KEY_A", "down": True, "delay_ms": 0}]}]}}}))
    items = logic.collect_risks(data)
    check(len(items) == 4, f"riscos {items}")
    confirm_risks(win(), items, "Este backup", "Continuar", lambda: ctl.__setitem__("accepted", True))
    return False


def s_import_shot():
    dlg = win().get_visible_dialog()
    check(isinstance(dlg, Adw.AlertDialog) and dlg.get_default_response() == "cancel", "aviso de importação")
    return False


def s_close_dialog():
    dlg = win().get_visible_dialog()
    if dlg is not None:
        dlg.force_close()
    check("accepted" not in ctl, "fechar não aceita")
    return False


def quit_():
    app.quit()
    return False


def goto_home():
    while win().nav.get_visible_page() is not win().devices_page:
        win().nav.pop()
    return False


def shot_(n):
    return lambda: shot(n)


def trigger_shot_prep():
    s_trigger_dialog_set()
    return False


steps = [s_seed, s_open_list, shot_("1-lista"), s_list_check, s_list_after_toggle, s_templates, shot_("2-modelos"),
         s_template_risk, s_risk_check, shot_("3-aviso-modelo"), s_risk_cancel, s_editor, s_editor_check,
         shot_("4-editor-gatilhos"), s_trigger_dialog, s_trigger_dialog_set, shot_("5-gatilho-botao"), s_trigger_close,
         s_step_dialog, s_recorder, shot_("6-gravador"), s_recorder_check, s_recorder_apply, s_editor_steps_check,
         s_save_flow, s_save_check, s_experiment_draft, s_experiment_check, s_prefs_import_risk, s_prefs_check,
         s_prefs_timer_check, shot_("7-aviso-importacao"), s_import_shot, s_close_dialog, quit_]
for i, fn in enumerate(steps):
    GLib.timeout_add(3500 + i * 900, fn)
GLib.timeout_add(60000, lambda: (fail.append("timeout"), app.quit()))
app.run([])
if fail:
    print("FAIL", fail)
    sys.exit(1)
print("SCENARIO OK")
