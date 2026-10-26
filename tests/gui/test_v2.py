"""F1–F7: lógica pura, modelo da bandeja e cenários D-Bus/GUI (dbus-run-session [+ xvfb-run])."""

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


def test_preferences_normalized():
    p = logic.normalize_preferences({"battery_threshold": 99, "osd_profile": "x", "ai_delivery_default": "url", "zzz": 1})
    assert p["battery_threshold"] == 50 and p["osd_profile"] is True and p["ai_delivery_default"] == "url"
    assert "zzz" not in p and logic.normalize_preferences(None) == logic.DEFAULT_PREFERENCES


def test_build_action_v2_fields():
    assert logic.build_action("type_text", text="é", method="paste") == {"type": "type_text", "text": "é"}
    assert logic.build_action("type_text", text="a", method="keys")["method"] == "keys"
    a = logic.build_action("ai_prompt", service="claude", template="x {selection}", delivery="url")
    assert a["delivery"] == "url"
    assert "delivery" not in logic.build_action("ai_prompt", service="claude", template="x")
    with pytest.raises(ValueError):
        logic.build_action("ai_prompt", service="claude", template="x", delivery="smtp")
    assert logic.classify_action(a)[1]["delivery"] == "url"


def test_validate_import():
    assert logic.validate_import('{"openmacros_export": 1}')
    for bad in ("nope", "[]", '{"a": 1}', '{"openmacros_export": 2}'):
        with pytest.raises(ValueError):
            logic.validate_import(bad)


def test_tray_model():
    m720 = {"name": "M720 Triathlon", "online": True, "battery": {"level": 83, "status": "discharging"},
            "hosts": {"count": 3, "current": 1, "names": ["A"]}, "active_profile": "firefox"}
    kb = {"name": "MX Keys", "online": True, "battery": {"level": 14, "status": "charging"}}
    off = {"name": "Off", "online": False, "battery": {"level": 1}}
    assert model.tray_icon(None) == "battery-missing-symbolic"
    assert model.tray_icon([m720, kb, off]) == "battery-level-10-charging-symbolic"
    assert model.tray_icon([m720]) == "battery-level-80-symbolic"
    assert model.tray_icon([]) == model.ICON_APP
    assert model.device_label(m720) == "M720 — 83 %"
    assert model.device_label(off) == "Off — offline"
    assert model.host_labels(m720) == [(0, "A", False), (1, "Computador 2", True), (2, "Computador 3", False)]
    assert model.active_profile_label([m720], str.upper) == "Perfil ativo: FIREFOX"
    assert model.active_profile_label([kb], str.upper) == "Perfil ativo: Todos os aplicativos"


def test_tray_does_not_import_gtk4():
    r = subprocess.run([sys.executable, "-c",
                        "import sys; import openmacros.tray.main; "
                        "import gi; print(gi.get_required_version('Gtk')); "
                        "assert 'openmacros.gui' not in sys.modules"],
                       capture_output=True, text=True, env=ENV, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "3.0"


@pytest.mark.skipif(shutil.which("dbus-run-session") is None, reason="sem dbus-run-session")
@pytest.mark.parametrize("mode", ["new", "old"])
def test_v2_dbus(mode):
    r = subprocess.run(["dbus-run-session", "--", sys.executable, str(HERE / "scenario_v2.py"), mode],
                       capture_output=True, text=True, timeout=60, env=ENV)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SCENARIO OK" in r.stdout


@pytest.mark.skipif(shutil.which("dbus-run-session") is None or shutil.which("xvfb-run") is None,
                    reason="sem dbus-run-session/xvfb-run")
@pytest.mark.parametrize("mode", ["new", "old"])
def test_v2_ui(mode, tmp_path):
    env = {**ENV, "XDG_DATA_HOME": str(tmp_path / "d"), "XDG_CONFIG_HOME": str(tmp_path / "c"),
           "GSK_RENDERER": "cairo", "LIBGL_ALWAYS_SOFTWARE": "1"}
    r = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x900x24", "dbus-run-session", "--",
                        sys.executable, str(HERE / "scenario_ui.py"), mode],
                       capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stdout + r.stderr[-3000:]
    assert "SCENARIO OK" in r.stdout
