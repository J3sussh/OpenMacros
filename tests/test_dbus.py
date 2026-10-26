import os
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(shutil.which("dbus-run-session") is None, reason="dbus-run-session ausente")
def test_dbus_service_fake_mode():
    driver = os.path.join(os.path.dirname(__file__), "dbus_driver.py")
    r = subprocess.run(["dbus-run-session", "--", sys.executable, driver],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "OK" in r.stdout, r.stdout + r.stderr
