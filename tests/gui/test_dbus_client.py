"""Cliente D-Bus contra o serviço falso, em um barramento de sessão privado (dbus-run-session)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from openmacros.gui.dbus_client import parse_device, parse_devices

HERE = Path(__file__).resolve().parent


def test_parse():
    assert parse_devices('[{"id": "a"}, {"x": 1}]') == [{"id": "a"}]
    assert parse_device('{"id": "a"}') == {"id": "a"}
    with pytest.raises(ValueError):
        parse_devices("{}")
    with pytest.raises(ValueError):
        parse_device("[]")
    with pytest.raises(json.JSONDecodeError):
        parse_devices("nope")


@pytest.mark.skipif(shutil.which("dbus-run-session") is None, reason="sem dbus-run-session")
def test_client_against_fake_service():
    r = subprocess.run(["dbus-run-session", "--", sys.executable, str(HERE / "client_scenario.py")],
                       capture_output=True, text=True, timeout=60,
                       env={**__import__("os").environ, "PYTHONPATH": str(HERE.parents[1] / "src") + ":" + str(HERE)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SCENARIO OK" in r.stdout
