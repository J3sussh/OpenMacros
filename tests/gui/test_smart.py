"""Smart Actions v2: lógica pura, riscos de importação, gravador, bandeja robusta e cenário de GUI."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from openmacros.gui import logic
from openmacros.tray import model

HERE = Path(__file__).resolve().parent
ENV = {**os.environ, "PYTHONPATH": str(HERE.parents[1] / "src") + ":" + str(HERE)}


def test_parse_save_result_both_formats():
    assert logic.parse_save_result("sa_ab12cd") == ("sa_ab12cd", [])
    assert logic.parse_save_result('{"id": "sa_1", "warnings": ["cuidado", 3]}') == ("sa_1", ["cuidado", "3"])
    assert logic.parse_save_result('{"id": "sa_1"}') == ("sa_1", [])
    assert logic.parse_save_result("{quebrado") == ("{quebrado", [])


def test_triggers_validation():
    ok = logic.validate_trigger({"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_P"]})
    assert ok["keys"][-1] == "KEY_P"
    assert logic.validate_trigger({"type": "shortcut", "keys": ["KEY_F13"]})
    assert logic.validate_trigger({"type": "shortcut", "keys": ["KEY_PLAYPAUSE"]})
    for bad in ({"type": "shortcut", "keys": ["KEY_P"]}, {"type": "shortcut", "keys": []},
                {"type": "shortcut", "keys": ["KEY_LEFTCTRL"]}, {"type": "app", "event": "x", "app_id": "a"},
                {"type": "app", "event": "open", "app_id": ""}, {"type": "device", "event": "boom"},
                {"type": "nope"}, "x"):
        with pytest.raises(ValueError):
            logic.validate_trigger(bad)
    assert logic.validate_trigger({"type": "device", "event": "connect"})["device_id"] == "*"


def test_describe_and_summary():
    sa = {"triggers": [{"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_P"]},
                       {"type": "app", "event": "open", "app_id": "firefox"}], "steps": [1, 2, 3, 4]}
    assert logic.smart_summary(sa, str.title) == "Se Ctrl+Alt+P · Ao abrir Firefox → 4 ações"
    assert logic.smart_summary({"steps": [1]}) == "Sem gatilho → 1 ação"
    devs = {"d": {"name": "M720", "controls": [{"cid": 83, "name": "Voltar"}],
                  "assignments": {"83": {"type": "smart_action", "id": "sa_1"}},
                  "profiles": {"code": {"assignments": {"83": {"type": "smart_action", "id": "sa_1"}}}}}}
    b = logic.button_triggers(devs, "sa_1")
    assert [(x["app_id"], x["cid"]) for x in b] == [("", 83), ("code", 83)]
    assert logic.button_triggers(devs, None) == []


def test_sorting():
    sas = {"a": {"name": "Zeta", "stats": {"runs": 5, "modified": "2026-01-01"}},
           "b": {"name": "alfa", "stats": {"runs": 9, "modified": "2026-03-01"}},
           "c": {"name": "Meio", "stats": {"runs": 1, "created": "2026-02-01"}}}
    assert [k for k, _ in logic.sort_smart_actions(sas, "alpha")] == ["b", "c", "a"]
    assert [k for k, _ in logic.sort_smart_actions(sas, "used")] == ["b", "a", "c"]
    assert [k for k, _ in logic.sort_smart_actions(sas, "recent")] == ["b", "c", "a"]


def test_new_actions_build_and_describe():
    assert logic.build_action("app", op="focus", target="firefox") == {"type": "app", "op": "focus", "target": "firefox"}
    assert logic.build_action("system", op="mic_mute") == {"type": "system", "op": "mic_mute"}
    assert logic.action_for_simple_item("system:lock") == {"type": "system", "op": "lock"}
    assert logic.item_id_for_action({"type": "system", "op": "lock"}) == "system:lock"
    assert logic.describe_action({"type": "app", "op": "open", "target": "firefox.desktop"}) == "Abrir: firefox"
    for bad in (("app", {"op": "x", "target": "a"}), ("app", {"op": "open", "target": ""}), ("system", {"op": "rm"})):
        with pytest.raises(ValueError):
            logic.build_action(bad[0], **bad[1])
    for step in ({"type": "system", "op": "dnd_toggle"}, {"type": "app", "op": "close", "target": "x"}):
        assert logic.validate_step(step) == step


def test_key_events_validation_and_recorder():
    ev = [{"key": "KEY_A", "down": True, "delay_ms": 0}, {"key": "KEY_A", "down": False, "delay_ms": 20}]
    assert logic.build_action("key_sequence", events=ev)["events"] == ev
    for bad in ([], None, [{"key": "A", "down": True, "delay_ms": 0}],
                [{"key": "KEY_A", "down": True, "delay_ms": 10001}], [{"key": "KEY_A", "down": True, "delay_ms": -1}],
                [ev[0]] * (logic.KEY_SEQ_MAX_EVENTS + 1)):
        with pytest.raises(ValueError):
            logic.validate_key_events(bad)
    r = logic.KeySequenceRecorder(False)
    assert r.feed("KEY_LEFTCTRL", True, 1000) and r.feed("KEY_C", True, 1130)
    assert not r.feed("KEY_C", True, 1140)         # repetição automática
    assert not r.feed("KEY_X", False, 1150)        # soltar sem ter apertado
    r.feed("KEY_C", False, 1200)
    r.release_all()                                # Ctrl ficou preso: é solto ao parar
    assert [(e["key"], e["down"], e["delay_ms"]) for e in r.events] == [
        ("KEY_LEFTCTRL", True, 0), ("KEY_C", True, 130), ("KEY_C", False, 70), ("KEY_LEFTCTRL", False, 0)]
    r.resume()
    r.feed("KEY_A", True, 99999)                   # tempo parado entre gravações não conta
    assert r.events[-1]["delay_ms"] == 0
    f = logic.KeySequenceRecorder(True)
    f.feed("KEY_A", True, 0)
    f.feed("KEY_A", False, 5000)
    assert f.events[1]["delay_ms"] == logic.KEY_SEQ_FIXED_DELAY
    slow = logic.KeySequenceRecorder(False)
    slow.feed("KEY_A", True, 0)
    slow.feed("KEY_A", False, 60000)
    assert slow.events[1]["delay_ms"] == logic.KEY_SEQ_MAX_DELAY
    cap = logic.KeySequenceRecorder(False)
    for i in range(logic.KEY_SEQ_MAX_EVENTS + 20):
        cap.feed("KEY_A", i % 2 == 0, i * 10)
    assert len(cap.events) == logic.KEY_SEQ_MAX_EVENTS and cap.full
    assert "Ctrl" in logic.events_preview(r.events)


def test_smart_action_validation_v2():
    sa = logic.validate_smart_action({"name": "x", "description": "  d  \n e ", "enabled": False,
                                      "triggers": [{"type": "app", "event": "focus", "app_id": "code"}],
                                      "steps": [{"type": "system", "op": "lock"}]})
    assert sa["description"] == "d e" and sa["enabled"] is False and sa["triggers"][0]["app_id"] == "code"
    with pytest.raises(ValueError):
        logic.validate_smart_action({"name": "x", "steps": [{"type": "delay", "ms": 20}],
                                     "triggers": [{"type": "device", "event": "connect"}] * 6})
    assert logic.trigger_error_map({"trigger_errors": [{"index": 1, "message": "ocupada"}, {"index": "x"}]}) == {1: "ocupada"}


def test_templates_v2():
    assert len(logic.SMART_TEMPLATES) == 10
    names = {t["name"] for t in logic.SMART_TEMPLATES}
    assert {"Modo de trabalho", "Modo reunião", "Hora de relaxar", "Volto em breve", "Pentest"} <= names
    for t in logic.SMART_TEMPLATES:
        d = logic.smart_from_template(t["id"])
        assert logic.validate_smart_action(d)["name"] == t["name"]
        assert d["triggers"] is not t.get("triggers")
    sites = logic.smart_from_template("my_sites")
    assert sites["triggers"][0]["type"] == "app" and sites["triggers"][0]["event"] == "open"
    assert any("comando" in r for r in logic.collect_risks(logic.smart_from_template("update_project")))
    assert logic.collect_risks(logic.smart_from_template("meeting")) == []


def test_import_risks():
    backup = {"openmacros_export": 1, "devices": {"d": {
        "assignments": {"83": {"type": "command", "argv": ["sh", "-c", "curl x | sh"]},
                        "208": {"type": "gestures", "up": {"type": "type_text", "text": "segredo"},
                                "down": {"type": "open", "target": "file:///etc/passwd"}, "click": {"type": "default"}}},
        "profiles": {"code": {"assignments": {"1": {"type": "open", "target": "/home/x/a.desktop"}}}}}},
        "smart_actions": {"s": {"steps": [{"type": "key_sequence", "events": [{"key": "KEY_A", "down": True, "delay_ms": 0}]},
                                          {"type": "open", "target": "firefox.desktop"},
                                          {"type": "open", "target": "https://example.org"},
                                          {"type": "app", "op": "open", "target": "/opt/x.desktop"}],
                                  "triggers": [{"type": "app", "event": "open", "app_id": "firefox"}]}}}
    risks = logic.collect_risks(backup)
    assert len(risks) == 6, risks
    assert any("curl" in r for r in risks) and any("file:///etc/passwd" in r for r in risks)
    assert not any("segredo" in r for r in risks)  # o conteúdo digitado nunca é exibido
    assert logic.collect_risks({"openmacros_export": 1, "devices": {"d": {"assignments": {"1": {"type": "keys", "keys": ["KEY_A"]}}}}}) == []
    assert logic.validate_smart_import('{"openmacros_smart_action": 1}')
    for bad in ("x", "[]", '{"openmacros_export": 1}', '{"openmacros_smart_action": 2}'):
        with pytest.raises(ValueError):
            logic.validate_smart_import(bad)


def test_host_count_tolerant():
    assert logic.host_count({"hosts": {"count": "3"}}) == 3
    assert logic.host_count({"hosts": {"count": "abc"}}) == 0
    assert logic.host_count({"hosts": {"count": None}}, 3) == 3
    assert logic.host_count({"hosts": "x"}) == 0 and logic.host_count({}) == 0
    assert logic.host_count({"hosts": {"count": 99999}}) == 16
    assert logic.supported_tabs({"controls": [], "settings": {}, "hosts": {"count": "x"}}) == ["about"]


def test_tray_malformed_hosts_and_menu_spec():
    for hosts in ({"count": "x"}, {"count": None}, {"count": [1]}, "texto", 5, {"count": 2, "names": "ab"}):
        d = {"name": "M720", "online": True, "hosts": hosts}
        labels = model.host_labels(d)
        assert isinstance(labels, list) and all(len(t) == 3 for t in labels)
    a = {"id": "a", "name": "M720", "online": True, "battery": {"level": 80}, "hosts": {"count": 2, "current": 0}}
    b = json.loads(json.dumps(a))
    b["features"] = ["0x1"]  # mudança invisível
    assert model.menu_spec([a], str.upper) == model.menu_spec([b], str.upper)
    c = json.loads(json.dumps(a))
    c["battery"]["level"] = 79
    assert model.menu_spec([a], str.upper) != model.menu_spec([c], str.upper)
    assert model.menu_spec(None, str.upper)[0] == ("label", "Serviço do OpenMacros+ não está em execução")
    assert model.menu_spec([a], str.upper)[-2:] == (("open",), ("quit",))


def test_fileio_limit_and_bom(tmp_path):
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    from openmacros.gui.widgets import fileio
    assert fileio.decode_text(b"\xef\xbb\xbf{\"a\": 1}") == '{"a": 1}'
    ok, big, bom = tmp_path / "ok.json", tmp_path / "big.json", tmp_path / "bom.json"
    ok.write_text('{"openmacros_export": 1}')
    big.write_bytes(b" " * (fileio.MAX_IMPORT_BYTES + 1))
    bom.write_bytes(b"\xef\xbb\xbf" + b'{"openmacros_export": 1}')
    results = {}
    loop = GLib.MainLoop()

    def run(name, path):
        fileio.read_text_limited(Gio.File.new_for_path(str(path)), lambda t, e: (results.__setitem__(name, (t, e)),
                                                                                  len(results) == 4 and loop.quit()))
    run("ok", ok)
    run("big", big)
    run("bom", bom)
    run("dir", tmp_path)
    GLib.timeout_add(5000, loop.quit)
    loop.run()
    assert results["ok"] == ('{"openmacros_export": 1}', None)
    assert results["bom"] == ('{"openmacros_export": 1}', None)
    assert results["big"][0] is None and "512 KiB" in results["big"][1]
    assert results["dir"][0] is None and results["dir"][1]


def test_toast_has_no_markup():
    import gi
    gi.require_version("Adw", "1")
    from openmacros.gui.toasts import new_toast
    t = new_toast("<b>x</b> & y")
    assert t.get_title() == "<b>x</b> & y" and t.get_use_markup() is False


@pytest.mark.skipif(shutil.which("dbus-run-session") is None or shutil.which("xvfb-run") is None,
                    reason="sem dbus-run-session/xvfb-run")
@pytest.mark.parametrize("mode", ["new", "old"])
def test_smart_ui(mode, tmp_path):
    env = {**ENV, "XDG_DATA_HOME": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c"),
           "GSK_RENDERER": "cairo", "LIBGL_ALWAYS_SOFTWARE": "1"}
    r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x900x24", "dbus-run-session", "--",
                        sys.executable, str(HERE / "scenario_smart.py"), mode],
                       capture_output=True, text=True, timeout=150, env=env)
    assert r.returncode == 0, r.stdout + r.stderr[-3000:]
    assert "SCENARIO OK" in r.stdout
