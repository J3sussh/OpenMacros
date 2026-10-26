"""Ambiente gráfico tardio: o serviço pode subir antes de o login gráfico exportar DISPLAY/XAUTHORITY.

No XFCE o `graphical-session.target` não é ativado, então a unidade sobe com `default.target`, às vezes
antes de o ambiente do systemd --user conhecer o DISPLAY. O autostart da sessão roda
`systemctl --user import-environment` (e reinicia o serviço); como cinto e suspensório, o próprio serviço
relê o ambiente do gerenciador com `systemctl --user show-environment` enquanto não houver tela.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess

log = logging.getLogger(__name__)

KEYS = ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE")
_TIMEOUT = 2.0


def _unquote(value: str) -> str:
    """Valores de `show-environment`: crus ou entre aspas de shell ($'…' / '…')."""
    try:
        if value.startswith("$'") and value.endswith("'"):
            return value[2:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        if value[:1] in "'\"":
            parts = shlex.split(value)
            return parts[0] if parts else ""
    except ValueError:
        pass
    return value


def parse_environment(text: str, keys=KEYS) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        name, sep, value = line.partition("=")
        if sep and name in keys and value:
            out[name] = _unquote(value)
    return out


def import_from_systemd(environ=None, run=subprocess.run) -> list[str]:
    """Se não há DISPLAY nem WAYLAND_DISPLAY, copia as variáveis gráficas do ambiente do systemd --user.
    Devolve os nomes importados. Nunca levanta."""
    env = os.environ if environ is None else environ
    if env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return []
    try:
        r = run(["systemctl", "--user", "show-environment"], stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if r.returncode != 0:
        return []
    got = parse_environment(r.stdout)
    if not (got.get("DISPLAY") or got.get("WAYLAND_DISPLAY")):
        return []
    imported = []
    for k, v in got.items():
        if not env.get(k):
            env[k] = v
            imported.append(k)
    log.info("ambiente gráfico importado do systemd --user: %s", ", ".join(imported))
    return imported
