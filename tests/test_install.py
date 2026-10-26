"""scripts/install.sh e uninstall.sh em HOME temporário (sem systemctl real, sem sudo, sem tocar no usuário real)."""
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
INSTALL = REPO / "scripts" / "install.sh"
UNINSTALL = REPO / "scripts" / "uninstall.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash ausente")


def run(script, home, *args, extra_env=None, path=None, skip_systemctl=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
    env.update(HOME=str(home), OPENMACROS_UDEV_DIR=str(home / "udev"))
    if skip_systemctl:
        env["OPENMACROS_SKIP_SYSTEMCTL"] = "1"
    if path:
        env["PATH"] = path
    env.update(extra_env or {})
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=60)


def tree(home):
    return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(home.rglob("*")) if p.is_file()}


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home dir"  # com espaço, de propósito
    (h / "udev").mkdir(parents=True)
    return h


def fake_bin(tmp_path, **scripts):
    """Diretório com executáveis falsos (nome -> corpo sh); devolve (dir, PATH com ele na frente)."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    for name, body in scripts.items():
        (d / name).write_text("#!/bin/sh\n" + body + "\n")
        (d / name).chmod(0o755)
    return d, f"{d}:{os.environ['PATH']}"


def test_install_creates_everything_in_user_dirs(home):
    r = run(INSTALL, home)
    assert r.returncode == 0, r.stdout + r.stderr
    for n in ("openmacrosd", "openmacros", "openmacros-tray"):
        f = home / ".local/bin" / n
        assert f.stat().st_mode & stat.S_IXUSR
        text = f.read_text()
        assert text.startswith("#!/bin/sh") and f"PYTHONPATH='{REPO}/src'" in text and "python3" in text
        assert "scripts/install.sh" in text  # marca: só removemos/sobrescrevemos o que é nosso
        assert subprocess.run(["sh", "-n", str(f)]).returncode == 0
    assert "-m openmacros.daemon.main" in (home / ".local/bin/openmacrosd").read_text()
    assert "-m openmacros.gui" in (home / ".local/bin/openmacros").read_text()
    assert "-m openmacros.tray" in (home / ".local/bin/openmacros-tray").read_text()
    unit = (home / ".config/systemd/user/openmacrosd.service").read_text()
    # HOME com espaço: ExecStart absoluto entre aspas em vez de %h
    assert f'ExecStart="{home}/.local/bin/openmacrosd"' in unit and "NoNewPrivileges=yes" in unit
    assert "WantedBy=default.target" in unit and "WantedBy=graphical-session" not in unit
    assert "PartOf=graphical-session.target" not in unit
    app = (home / ".local/share/applications/io.github.openmacros.App.desktop").read_text()
    assert f'Exec="{home}/.local/bin/openmacros"' in app and "Icon=io.github.openmacros.App" in app
    tray = (home / ".config/autostart/io.github.openmacros.Tray.desktop").read_text()
    assert f'Exec="{home}/.local/bin/openmacros-tray"' in tray
    session = (home / ".config/autostart/io.github.openmacros.Session.desktop").read_text()
    assert "import-environment DISPLAY XAUTHORITY" in session and "restart openmacrosd.service" in session
    icon = home / ".local/share/icons/hicolor/scalable/apps/io.github.openmacros.App.svg"
    assert icon.exists() == (REPO / "data/icons/io.github.openmacros.App.svg").exists()
    # nada fora de HOME de teste foi criado em /etc; udev só impresso
    assert "sudo install -m 644" in r.stdout and "70-openmacros.rules" in r.stdout
    assert "sudo rm" not in r.stdout


def test_unit_uses_percent_h_when_home_is_plain(tmp_path):
    h = tmp_path / "plainhome"
    (h / "udev").mkdir(parents=True)
    assert run(INSTALL, h).returncode == 0
    unit = (h / ".config/systemd/user/openmacrosd.service").read_text()
    assert "ExecStart=%h/.local/bin/openmacrosd" in unit


def test_help_does_not_print_shell_options():
    for script in (INSTALL, UNINSTALL):
        r = run(script, REPO, "-h")
        assert r.returncode == 0 and "set -euo pipefail" not in r.stdout and "pipefail" not in r.stdout
        assert "Uso" in r.stdout or "scripts/" in r.stdout


def test_install_is_idempotent(home):
    assert run(INSTALL, home).returncode == 0
    first = tree(home)
    r = run(INSTALL, home, "--no-start")
    assert r.returncode == 0, r.stderr
    assert tree(home) == first
    assert not list(home.rglob("*.bak*")) and "cópia salva" not in r.stderr


def test_install_prints_udev_command_and_skips_when_current(home):
    r = run(INSTALL, home)
    assert "sudo install -m 644" in r.stdout and "70-openmacros.rules" in r.stdout
    shutil.copy(REPO / "data/udev/70-openmacros.rules", home / "udev/70-openmacros.rules")
    r = run(INSTALL, home)
    assert "já instalada" in r.stdout and "sudo" not in r.stdout


def test_install_pipx_mode_calls_pipx_with_system_site_packages(home, tmp_path):
    log = tmp_path / "pipx.log"
    _, path = fake_bin(tmp_path, pipx=f'echo "$@" >> "{log}"')
    r = run(INSTALL, home, "--pipx", path=path)
    assert r.returncode == 0, r.stderr
    assert log.read_text().split() == ["install", "--system-site-packages", "--force", str(REPO)]
    assert not (home / ".local/bin/openmacrosd").exists()  # lançadores ficam por conta do pipx
    assert (home / ".config/systemd/user/openmacrosd.service").exists()


def test_install_rejects_unknown_option(home):
    assert run(INSTALL, home, "--bogus").returncode == 2


# ------------------------------------------------------------------ não sobrescrever o que não é nosso
def test_foreign_launcher_is_skipped_with_warning(home):
    bin_ = home / ".local/bin"
    bin_.mkdir(parents=True)
    mine = bin_ / "openmacros"
    mine.write_text("#!/bin/sh\necho launcher do usuario\n")
    r = run(INSTALL, home)
    assert r.returncode == 0, r.stderr
    assert mine.read_text() == "#!/bin/sh\necho launcher do usuario\n"
    assert "não foi gerado pelo OpenMacros+" in r.stderr and str(mine) in r.stderr
    assert "scripts/install.sh" in (bin_ / "openmacrosd").read_text()  # os demais foram instalados


def test_foreign_unit_and_desktop_are_backed_up_not_lost(home):
    unit = home / ".config/systemd/user/openmacrosd.service"
    app = home / ".local/share/applications/io.github.openmacros.App.desktop"
    for f, text in ((unit, "[Service]\nExecStart=/opt/meu/openmacrosd --custom\n"),
                    (app, "[Desktop Entry]\nName=Outro\nExec=outro\n")):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    r = run(INSTALL, home)
    assert r.returncode == 0, r.stderr
    assert (unit.parent / "openmacrosd.service.bak").read_text() == "[Service]\nExecStart=/opt/meu/openmacrosd --custom\n"
    assert (app.parent / (app.name + ".bak")).read_text() == "[Desktop Entry]\nName=Outro\nExec=outro\n"
    assert "WantedBy=default.target" in unit.read_text()
    assert r.stderr.count("cópia salva em") == 2
    # reinstalar não gera novos .bak (agora os arquivos são nossos)
    r = run(INSTALL, home)
    assert len(list(home.rglob("*.bak*"))) == 2 and "cópia salva" not in r.stderr


def test_previous_version_files_without_mark_are_upgraded_in_place(home):
    unit = home / ".config/systemd/user/openmacrosd.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Unit]\nDescription=OpenMacros+ - antigo\nPartOf=graphical-session.target\n")
    assert run(INSTALL, home).returncode == 0
    assert not list(home.rglob("*.bak*")) and "default.target" in unit.read_text()


def test_launcher_preserves_pythonpath_and_quotes_weird_paths(tmp_path):
    h = tmp_path / 'we ird "$HOME" `x` %h \\ dir'
    (h / "udev").mkdir(parents=True)
    assert run(INSTALL, h).returncode == 0
    text = (h / ".local/bin/openmacrosd").read_text()
    # troca o interpretador por printenv: mostra o PYTHONPATH que o lançador entregaria
    line = next(ln for ln in text.splitlines() if ln.startswith("exec env"))
    stub = h / "stub"
    py = line.split('"${PYTHONPATH:+:$PYTHONPATH}" ', 1)[1]
    stub.write_text(text.replace(py, "printenv PYTHONPATH"))
    out = subprocess.run(["sh", str(stub)], env={**os.environ, "PYTHONPATH": "/tmp/x y"}, capture_output=True,
                         text=True)
    assert out.stdout.strip() == f"{REPO}/src:/tmp/x y", out.stderr
    out = subprocess.run(["sh", str(stub)], env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                         capture_output=True, text=True)
    assert out.stdout.strip() == f"{REPO}/src"


def test_launcher_with_repo_path_special_chars(tmp_path):
    """Lançador também funciona se o repositório estiver num caminho com aspas/espaço/$: copia o script."""
    repo = tmp_path / "re po $x \"q\" 'a'"
    shutil.copytree(REPO / "scripts", repo / "scripts")
    shutil.copytree(REPO / "data", repo / "data")
    (repo / "src").mkdir()
    h = tmp_path / "h"
    (h / "udev").mkdir(parents=True)
    r = run(repo / "scripts/install.sh", h)
    assert r.returncode == 0, r.stderr
    text = (h / ".local/bin/openmacrosd").read_text()
    line = next(ln for ln in text.splitlines() if ln.startswith("exec env"))
    py = line.split('"${PYTHONPATH:+:$PYTHONPATH}" ', 1)[1]
    stub = h / "stub"
    stub.write_text(text.replace(py, "printenv PYTHONPATH"))
    out = subprocess.run(["sh", str(stub)], env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                         capture_output=True, text=True)
    assert out.stdout.strip() == f"{repo}/src", out.stderr


def test_desktop_exec_escaping_roundtrips_through_glib(tmp_path):
    pytest.importorskip("gi")
    from gi.repository import Gio, GLib
    h = tmp_path / 'we ird "q" $HOME `x` \\ dir'  # (GLib recusa validar Exec com "%%" no caminho; ver abaixo)
    (h / "udev").mkdir(parents=True)
    assert run(INSTALL, h).returncode == 0
    for name, d in (("openmacros", ".local/share/applications/io.github.openmacros.App.desktop"),
                    ("openmacros-tray", ".config/autostart/io.github.openmacros.Tray.desktop")):
        path = str(h / d)
        assert Gio.DesktopAppInfo.new_from_filename(path) is not None  # GLib aceita e acha o executável
        kf = GLib.KeyFile()  # o que o lançador de apps faz: desescapa a string e separa como shell
        kf.load_from_file(path, GLib.KeyFileFlags.NONE)
        ok, argv = GLib.shell_parse_argv(kf.get_string("Desktop Entry", "Exec"))
        assert argv == [f"{h}/.local/bin/{name}"]


def test_desktop_exec_percent_is_doubled(tmp_path):
    h = tmp_path / "pct%fdir"
    (h / "udev").mkdir(parents=True)
    assert run(INSTALL, h).returncode == 0
    app = (h / ".local/share/applications/io.github.openmacros.App.desktop").read_text()
    assert f'Exec="{h}/.local/bin/openmacros"'.replace("%", "%%") in app


def test_systemd_exec_escaping_for_special_home(tmp_path):
    h = tmp_path / 'we ird "q" $HOME %h \\ dir'
    (h / "udev").mkdir(parents=True)
    assert run(INSTALL, h).returncode == 0
    unit = (h / ".config/systemd/user/openmacrosd.service").read_text()
    line = next(ln for ln in unit.splitlines() if ln.startswith("ExecStart="))
    expected = str(h / ".local/bin/openmacrosd").replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") \
        .replace("$", "$$")
    assert line == f'ExecStart="{expected}"'


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze ausente")
def test_installed_unit_passes_systemd_analyze_verify(tmp_path):
    h = tmp_path / "plain"
    (h / "udev").mkdir(parents=True)
    assert run(INSTALL, h).returncode == 0
    unit = h / ".config/systemd/user/openmacrosd.service"
    r = subprocess.run(["systemd-analyze", "--user", "verify", str(unit)], capture_output=True, text=True,
                       timeout=30, env={**os.environ, "HOME": str(h)})
    bad = [ln for ln in r.stderr.splitlines() if "Unknown" in ln or "Invalid" in ln or "Failed to parse" in ln]
    assert not bad, r.stderr


# ------------------------------------------------------------------ systemctl (falso)
def test_install_systemctl_sequence_with_fake_systemctl(home, tmp_path):
    log = tmp_path / "ctl.log"
    _, path = fake_bin(tmp_path, systemctl=f'echo "$@" >> "{log}"', **{"update-desktop-database": "true",
                                                                         "gtk-update-icon-cache": "true"})
    stale = home / ".config/systemd/user/graphical-session.target.wants/openmacrosd.service"
    stale.parent.mkdir(parents=True)
    stale.symlink_to("../openmacrosd.service")  # instalação antiga habilitada no alvo errado
    r = run(INSTALL, home, path=path, skip_systemctl=False)
    assert r.returncode == 0, r.stderr
    calls = log.read_text().splitlines()
    assert calls == ["--user daemon-reload", "--user disable openmacrosd.service",
                     "--user import-environment DISPLAY XAUTHORITY WAYLAND_DISPLAY XDG_SESSION_TYPE",
                     "--user enable --now openmacrosd.service", "--user restart openmacrosd.service"]


# ------------------------------------------------------------------ uninstall
def test_uninstall_removes_only_our_files(home):
    run(INSTALL, home)
    other = home / ".local/bin/outro"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("#!/bin/sh\n")
    mine_but_foreign = home / ".local/bin/openmacros"
    mine_but_foreign.write_text("#!/bin/sh\necho launcher do usuario\n")  # não é nosso: preservado
    cfg = home / ".config/openmacros/config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{}")
    r = run(UNINSTALL, home)
    assert r.returncode == 0, r.stderr
    left = set(tree(home))
    assert ".local/bin/outro" in left and ".local/bin/openmacros" in left and ".config/openmacros/config.json" in left
    assert not any(n in left for n in (".local/bin/openmacrosd", ".local/bin/openmacros-tray",
                                       ".config/systemd/user/openmacrosd.service",
                                       ".config/autostart/io.github.openmacros.Tray.desktop",
                                       ".config/autostart/io.github.openmacros.Session.desktop",
                                       ".local/share/applications/io.github.openmacros.App.desktop"))
    run(UNINSTALL, home, "--purge")
    assert not cfg.exists()


def test_uninstall_keeps_foreign_unit_desktop_and_icon(home):
    unit = home / ".config/systemd/user/openmacrosd.service"
    app = home / ".local/share/applications/io.github.openmacros.App.desktop"
    icon = home / ".local/share/icons/hicolor/scalable/apps/io.github.openmacros.App.svg"
    for f, text in ((unit, "[Service]\nExecStart=/opt/x\n"), (app, "[Desktop Entry]\nName=Outro\n"),
                    (icon, "<svg/>")):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    r = run(UNINSTALL, home)
    assert r.returncode == 0
    assert unit.exists() and app.exists() and icon.exists()
    assert r.stderr.count("mantido") >= 3


def test_uninstall_pipx_only_when_package_points_to_this_repo(home, tmp_path):
    log = tmp_path / "pipx.log"

    def pipx(src):
        listing = json.dumps({"venvs": {"openmacros-plus": {"metadata": {"main_package": {
            "package": "openmacros-plus", "package_or_url": src}}}}})
        body = (f'case "$1" in list) case "$2" in --json) echo \'{listing}\';; *) echo "openmacros-plus 0.1.0";; esac;;'
                f' uninstall) echo "$@" >> "{log}";; esac')
        return fake_bin(tmp_path, pipx=body)[1]

    r = run(UNINSTALL, home, path=pipx("/outro/repositorio"))
    assert r.returncode == 0 and not log.exists() and "não aponta para este repositório" in r.stderr
    r = run(UNINSTALL, home, path=pipx(str(REPO)))
    assert r.returncode == 0 and log.read_text().split() == ["uninstall", "openmacros-plus"]
    log.unlink()
    r = run(UNINSTALL, home, path=pipx("file://" + str(REPO)))
    assert log.read_text().split() == ["uninstall", "openmacros-plus"]


@pytest.mark.skipif(shutil.which("dbus-run-session") is None, reason="dbus-run-session ausente")
def test_installed_daemon_launcher_starts_in_fake_mode(home):
    run(INSTALL, home)
    r = subprocess.run(
        ["dbus-run-session", "--", "timeout", "3", str(home / ".local/bin/openmacrosd")],
        env={**os.environ, "OPENMACROS_FAKE": "1", "HOME": str(home)}, capture_output=True, text=True, timeout=30)
    assert r.returncode == 124, r.stdout + r.stderr  # ficou rodando até o timeout
    assert "modo simulado" in r.stderr and "Traceback" not in r.stderr


# ------------------------------------------------------------------ artefatos do nome antigo (Clique)
OLD_MARK = "# Gerado por scripts/install.sh (modo dev).\n"


def make_legacy(home):
    files = {
        ".local/bin/clique": "#!/bin/sh\n" + OLD_MARK, ".local/bin/cliqued": "#!/bin/sh\n" + OLD_MARK,
        ".local/bin/clique-tray": "#!/bin/sh\n" + OLD_MARK,
        ".config/systemd/user/cliqued.service": "# Gerado por scripts/install.sh\n[Service]\nExecStart=x\n",
        ".local/share/applications/io.github.clique.App.desktop": "[Desktop Entry]\nName=Clique\n",
        ".config/autostart/io.github.clique.Tray.desktop": "[Desktop Entry]\nName=Clique (bandeja)\n",
        ".config/autostart/io.github.clique.Session.desktop": "[Desktop Entry]\nName=Clique (sessão)\n",
    }
    for rel, text in files.items():
        f = home / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    icon = home / ".local/share/icons/hicolor/scalable/apps/io.github.clique.App.svg"
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "data/icons/io.github.openmacros.App.svg", icon)
    return [home / r for r in files] + [icon]


def test_install_warns_about_legacy_artifacts_without_removing(home):
    legacy = make_legacy(home)
    r = run(INSTALL, home)
    assert r.returncode == 0, r.stderr
    assert "instalação antiga" in r.stderr and "cliqued.service" in r.stderr
    assert all(f.exists() for f in legacy)


def test_uninstall_legacy_removes_only_signed_old_artifacts(home):
    legacy = make_legacy(home)
    foreign = home / ".local/bin/clique-tray"
    foreign.write_text("#!/bin/sh\necho meu\n")  # mesmo nome, sem marca: preservado
    run(INSTALL, home)
    r = run(UNINSTALL, home, "--legacy")
    assert r.returncode == 0, r.stderr
    left = [f for f in legacy if f.exists()]
    assert left == [foreign] and "clique-tray" in r.stderr
    assert (home / ".local/bin/openmacrosd").exists()  # a instalação atual não foi tocada


def test_uninstall_also_cleans_legacy_and_purge_removes_old_config(home):
    legacy = make_legacy(home)
    old_cfg = home / ".config/clique/config.json"
    old_cfg.parent.mkdir(parents=True)
    old_cfg.write_text("{}")
    r = run(UNINSTALL, home, "--purge")
    assert r.returncode == 0, r.stderr
    assert not any(f.exists() for f in legacy) and not old_cfg.parent.exists()
