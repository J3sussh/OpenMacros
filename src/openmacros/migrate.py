"""Migração única de diretórios do nome antigo do projeto (Clique) para o atual (OpenMacros+)."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def migrate_legacy_dir(old: Path, new: Path) -> bool:
    """Migração única do nome antigo (Clique): se `new` não existe e `old` existe, COPIA `old` para `new`
    (o diretório antigo é preservado). Retorna True se copiou. Falhas são logadas, nunca propagadas."""
    tmp = new.with_name(f"{new.name}.migrating-{os.getpid()}")
    try:
        if os.path.lexists(new) or not old.is_dir() or old.is_symlink():
            return False
        shutil.rmtree(tmp, ignore_errors=True)
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(old, tmp, symlinks=True)
        os.rename(tmp, new)
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        log.warning("migração %s -> %s falhou: %s", old, new, e)
        return False
    log.info("migração única: %s copiado para %s (o diretório antigo foi mantido)", old, new)
    return True
