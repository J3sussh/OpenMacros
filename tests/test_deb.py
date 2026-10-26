"""packaging/deb/build-deb.sh: gera o .deb e confere conteúdo, control e scripts de manutenção (sem instalar)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "packaging" / "deb" / "build-deb.sh"

pytestmark = pytest.mark.skipif(shutil.which("dpkg-deb") is None or shutil.which("bash") is None,
                                reason="dpkg-deb/bash ausente")

ESSENTIAL = [
    "usr/bin/openmacros", "usr/bin/openmacrosd", "usr/bin/openmacros-tray",
    "usr/lib/python3/dist-packages/openmacros/__init__.py",
    "usr/lib/python3/dist-packages/openmacros/gui/data/style.css",
    "usr/lib/python3/dist-packages/openmacros/gui/data/apps.json",
    "usr/lib/python3/dist-packages/openmacros/gui/data/art/m720.svg",
    "usr/lib/python3/dist-packages/openmacros/gui/data/layouts/m720.json",
    "usr/lib/systemd/user/openmacrosd.service",
    "usr/share/applications/io.github.openmacros.App.desktop",
    "etc/xdg/autostart/io.github.openmacros.Tray.desktop",
    "etc/xdg/autostart/io.github.openmacros.Session.desktop",
    "usr/share/icons/hicolor/scalable/apps/io.github.openmacros.App.svg",
    "usr/share/icons/hicolor/symbolic/apps/io.github.openmacros.App-symbolic.svg",
    "usr/lib/udev/rules.d/70-openmacros.rules",
    "usr/share/doc/openmacros-plus/copyright",
    "usr/share/doc/openmacros-plus/changelog.Debian.gz",
    "usr/share/metainfo/io.github.openmacros.App.metainfo.xml",
]


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120, check=True).stdout


@pytest.fixture(scope="module")
def deb(tmp_path_factory):
    out = tmp_path_factory.mktemp("deb-out")
    r = subprocess.run(["bash", str(BUILD), "--version", "9.8.7", "--out", str(out)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    path = out / "openmacros-plus_9.8.7_all.deb"
    assert path.is_file() and r.stdout.strip().endswith(path.name)
    return path


@pytest.fixture(scope="module")
def listing(deb):
    entries = {}
    for line in sh("dpkg-deb", "-c", str(deb)).splitlines():
        parts = line.split(None, 5)
        entries[parts[5].split(" ->")[0].removeprefix("./")] = (parts[0], parts[1])
    return entries


def test_essential_files(listing):
    for f in ESSENTIAL:
        assert f in listing, f"faltando {f}"


def test_no_pycache_tests_or_junk(listing):
    for name in listing:
        assert "__pycache__" not in name and not name.endswith((".pyc", ".pyo")), name
        assert "/tests/" not in name and "/test_" not in name, name
    assert all(owner == "root/root" for _, owner in listing.values())
    assert listing["usr/bin/openmacros"][0].startswith("-rwxr-xr-x")


def test_control(deb):
    ctl = sh("dpkg-deb", "-f", str(deb))
    fields = dict(re.findall(r"^([A-Za-z-]+): (.*)$", ctl, re.M))
    assert fields["Package"] == "openmacros-plus" and fields["Version"] == "9.8.7"
    assert fields["Architecture"] == "all" and fields["Section"] == "utils" and fields["Priority"] == "optional"
    assert fields["Maintainer"] == "OpenMacros+ maintainers <contact email>"
    assert fields["Homepage"] == "https://github.com/<user>/openmacros-plus"
    deps = sh("dpkg-deb", "-f", str(deb), "Depends")
    for d in ("python3 (>= 3.12)", "python3-gi", "gir1.2-gtk-4.0", "gir1.2-adw-1 (>= 1.5)", "gir1.2-gtk-3.0",
              "gir1.2-ayatanaappindicator3-0.1", "python3-evdev", "python3-pyudev", "python3-xlib", "xclip | xsel"):
        assert d in deps, d
    assert "Description:" in ctl


def test_maintainer_scripts(deb, tmp_path):
    ctl = tmp_path / "ctl"
    sh("dpkg-deb", "-e", str(deb), str(ctl))
    for s in ("postinst", "prerm", "postrm"):
        p = ctl / s
        assert p.stat().st_mode & 0o777 == 0o755, s
        assert p.read_text().startswith("#!/bin/sh"), s
        subprocess.run(["sh", "-n", str(p)], check=True)
    post = (ctl / "postinst").read_text()
    for needle in ("udevadm control --reload-rules", "udevadm trigger", "systemctl --global enable", "modprobe uinput"):
        assert needle in post
    assert "systemctl --global disable" in (ctl / "prerm").read_text()
    assert "udevadm control --reload-rules" in (ctl / "postrm").read_text()
    assert "HOME" not in post and ".config" not in post  # nunca mexe em arquivos de usuários
    conffiles = (ctl / "conffiles").read_text().split()
    assert "/etc/xdg/autostart/io.github.openmacros.Tray.desktop" in conffiles


def test_unit_and_launchers(deb, tmp_path):
    sh("dpkg-deb", "-x", str(deb), str(tmp_path))
    unit = (tmp_path / "usr/lib/systemd/user/openmacrosd.service").read_text()
    assert "ExecStart=/usr/bin/openmacrosd\n" in unit and "WantedBy=default.target" in unit
    assert "NoNewPrivileges=yes" in unit and ".local/bin" not in unit
    for name, mod in (("openmacros", "openmacros.gui.app"), ("openmacrosd", "openmacros.daemon.main"),
                      ("openmacros-tray", "openmacros.tray.main")):
        text = (tmp_path / "usr/bin" / name).read_text()
        assert text.startswith("#!/usr/bin/python3\n") and f"from {mod} import main" in text


def test_metainfo_is_well_formed_xml(deb, tmp_path):
    import xml.etree.ElementTree as ET
    sh("dpkg-deb", "-x", str(deb), str(tmp_path))
    root = ET.parse(tmp_path / "usr/share/metainfo/io.github.openmacros.App.metainfo.xml").getroot()
    assert root.findtext("id") == "io.github.openmacros.App"
    assert root.find("releases/release").get("version") == "9.8.7"
