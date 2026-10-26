"""Onde achar ícones fora do tema padrão: repositório (modo dev) e instalação por pacote.

Instalado (.deb), o ícone vai para /usr/share/icons/hicolor, que o GTK já pesquisa; os diretórios
daqui são extras e só entram na lista se existirem. Sem GTK: pode ser importado por GUI e bandeja."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
SYSTEM_DATA_DIRS = (Path("/usr/share/openmacros"), Path("/usr/local/share/openmacros"))


def _repo_root(package_dir: Path) -> Path | None:
    """Raiz do repositório quando o código roda de src/openmacros (tem pyproject.toml ao lado de src)."""
    root = package_dir.parent.parent
    if package_dir.parent.name == "src" and (root / "pyproject.toml").is_file():
        return root
    return None


def icon_search_dirs(package_dir: Path = PACKAGE_DIR, system_dirs: tuple[Path, ...] = SYSTEM_DATA_DIRS) -> list[Path]:
    """Diretórios extras de ícones que existem: data/icons do repositório, depois <share>/openmacros/icons."""
    cands: list[Path] = []
    if (root := _repo_root(package_dir)) is not None:
        cands.append(root / "data" / "icons")
    cands.extend(d / "icons" for d in system_dirs)
    return [c for c in cands if c.is_dir()]
