"""Localização de ícones em modo dev (repositório) e instalado (/usr/share/openmacros)."""
from pathlib import Path

from openmacros import paths


def test_dev_checkout_finds_repo_icons(tmp_path):
    (tmp_path / "pyproject.toml").write_text("")
    pkg = tmp_path / "src" / "openmacros"
    pkg.mkdir(parents=True)
    (tmp_path / "data" / "icons").mkdir(parents=True)
    assert paths.icon_search_dirs(pkg, ()) == [tmp_path / "data" / "icons"]


def test_installed_layout_ignores_repo_and_uses_share(tmp_path):
    pkg = tmp_path / "usr/lib/python3/dist-packages/openmacros"
    pkg.mkdir(parents=True)
    (tmp_path / "usr/lib/python3/data/icons").mkdir(parents=True)  # lixo que o cálculo antigo (parents[3]) acharia
    share = tmp_path / "usr/share/openmacros"
    (share / "icons").mkdir(parents=True)
    assert paths.icon_search_dirs(pkg, (share, tmp_path / "ausente")) == [share / "icons"]


def test_real_repo_has_icon():
    assert any(Path(d, "io.github.openmacros.App.svg").is_file() for d in paths.icon_search_dirs()) \
        or not (paths.PACKAGE_DIR.parent.parent / "pyproject.toml").is_file()
