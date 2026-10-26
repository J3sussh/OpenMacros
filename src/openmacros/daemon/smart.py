"""Smart Actions v2: formato, migração e gatilhos (puro, sem E/S). Contrato em docs/design/SMART_ACTIONS.md."""

from __future__ import annotations

import datetime
import re
from typing import NamedTuple

MAX_TRIGGERS = 5
MAX_DESCRIPTION = 300
MAX_SHORTCUT_KEYS = 6
APP_EVENTS = ("open", "close", "focus")
DEVICE_EVENTS = ("connect", "disconnect")
_APP_ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
_DEV_RE = re.compile(r"^[A-Za-z0-9:_.-]{1,64}$")

# bits próprios (independentes do X11); o backend X11 traduz para ControlMask etc.
CTRL, SHIFT, ALT, SUPER = 1, 2, 4, 8
MOD_NAMES = ((CTRL, "Ctrl"), (ALT, "Alt"), (SUPER, "Super"), (SHIFT, "Shift"))
_MODIFIERS = {"KEY_LEFTCTRL": CTRL, "KEY_RIGHTCTRL": CTRL, "KEY_LEFTSHIFT": SHIFT, "KEY_RIGHTSHIFT": SHIFT,
              "KEY_LEFTALT": ALT, "KEY_LEFTMETA": SUPER, "KEY_RIGHTMETA": SUPER}
# sem modificador obrigatório: F13..F24 e teclas de mídia/atalhos de hardware
_FREE_KEYS = frozenset(
    [f"KEY_F{n}" for n in range(13, 25)]
    + ["KEY_PLAYPAUSE", "KEY_PLAYCD", "KEY_PAUSECD", "KEY_NEXTSONG", "KEY_PREVIOUSSONG", "KEY_STOPCD",
       "KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE", "KEY_BRIGHTNESSUP", "KEY_BRIGHTNESSDOWN",
       "KEY_CALC", "KEY_MAIL", "KEY_HOMEPAGE", "KEY_WWW", "KEY_SEARCH", "KEY_COMPUTER", "KEY_MEDIA",
       "KEY_PROG1", "KEY_PROG2", "KEY_PROG3", "KEY_PROG4", "KEY_SCREENLOCK", "KEY_SLEEP", "KEY_FILE"])
X_KEYCODE_OFFSET = 8  # evdev -> keycode do X (xkb "evdev")


class Combo(NamedTuple):
    keycode: int  # keycode do X
    mods: int     # CTRL|SHIFT|ALT|SUPER


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _code(name) -> int:
    from evdev import ecodes
    if not isinstance(name, str) or not name.startswith("KEY_"):
        raise ValueError(f"tecla inválida: {name!r}")
    code = ecodes.ecodes.get(name)
    if not isinstance(code, int):
        raise ValueError(f"tecla desconhecida: {name!r}")
    return code


def parse_shortcut(keys) -> Combo:
    """Lista de KEY_* -> Combo (keycode do X + bits de modificadores). Levanta ValueError legível."""
    if not isinstance(keys, list) or not 1 <= len(keys) <= MAX_SHORTCUT_KEYS:
        raise ValueError(f"'keys' deve ser uma lista de 1 a {MAX_SHORTCUT_KEYS} teclas")
    if len(set(keys)) != len(keys):
        raise ValueError("teclas repetidas no atalho")
    mods, main = 0, []
    for k in keys:
        _code(k)
        if k == "KEY_RIGHTALT":
            raise ValueError("AltGr não pode ser usado em atalhos (depende do layout do teclado)")
        if k in _MODIFIERS:
            mods |= _MODIFIERS[k]
        else:
            main.append(k)
    if len(main) != 1:
        raise ValueError("o atalho precisa de exatamente uma tecla além dos modificadores")
    if not mods and main[0] not in _FREE_KEYS:
        raise ValueError("o atalho precisa de ao menos um modificador (Ctrl, Alt, Super ou Shift); "
                         "só F13–F24 e teclas de mídia dispensam")
    code = _code(main[0]) + X_KEYCODE_OFFSET
    if code > 255:
        raise ValueError(f"a tecla {main[0]} não pode ser capturada no X11")
    return Combo(code, mods)


def combo_label(keys: list[str]) -> str:
    """'Ctrl+Alt+P' (para mensagens)."""
    try:
        combo = parse_shortcut(keys)
    except ValueError:
        return "+".join(str(k) for k in keys)
    main = next(k for k in keys if k not in _MODIFIERS).removeprefix("KEY_")
    main = main.upper() if len(main) == 1 else main.capitalize()
    return "+".join([n for bit, n in MOD_NAMES if combo.mods & bit] + [main])


def validate_trigger(t) -> dict:
    if not isinstance(t, dict) or not isinstance(t.get("type"), str):
        raise ValueError("gatilho deve ser um objeto com 'type'")
    kind = t["type"]
    if kind == "shortcut":
        parse_shortcut(t.get("keys"))
        return {"type": kind, "keys": list(t["keys"])}
    if kind == "app":
        if t.get("event") not in APP_EVENTS:
            raise ValueError("'event' de app deve ser open, close ou focus")
        app_id = t.get("app_id")
        if not isinstance(app_id, str) or not _APP_ID_RE.match(app_id.strip()):
            raise ValueError("'app_id' inválido")
        return {"type": kind, "event": t["event"], "app_id": app_id.strip().lower()}
    if kind == "device":
        if t.get("event") not in DEVICE_EVENTS:
            raise ValueError("'event' de device deve ser connect ou disconnect")
        dev = t.get("device_id", "*")
        if dev != "*" and (not isinstance(dev, str) or not _DEV_RE.match(dev)):
            raise ValueError("'device_id' inválido")
        return {"type": kind, "event": t["event"], "device_id": dev}
    raise ValueError(f"tipo de gatilho desconhecido: {kind!r}")


def validate_triggers(triggers) -> list[dict]:
    if not isinstance(triggers, list) or len(triggers) > MAX_TRIGGERS:
        raise ValueError(f"'triggers' deve ser uma lista com no máximo {MAX_TRIGGERS} gatilhos")
    out = []
    for i, t in enumerate(triggers):
        try:
            out.append(validate_trigger(t))
        except (ValueError, TypeError) as e:
            raise ValueError(f"gatilho {i + 1}: {e}") from e
    return out


def new_stats(now: str | None = None) -> dict:
    now = now or now_iso()
    return {"runs": 0, "last_run": None, "created": now, "modified": now}


def sanitize_stats(stats, now: str | None = None) -> dict:
    """Leitura tolerante: campos ausentes/inválidos recebem padrões."""
    base = new_stats(now)
    if not isinstance(stats, dict):
        return base
    runs = stats.get("runs")
    if isinstance(runs, int) and not isinstance(runs, bool) and runs >= 0:
        base["runs"] = runs
    for k in ("last_run", "created", "modified"):
        v = stats.get(k)
        if isinstance(v, str) and len(v) <= 40:
            base[k] = v
    return base


def migrate(sa: dict, now: str | None = None) -> dict:
    """Formato v1 -> v2: acrescenta padrões ausentes (idempotente; não valida os passos)."""
    out = dict(sa)
    out.setdefault("description", "")
    out.setdefault("icon", "")
    if not isinstance(out.get("enabled"), bool):
        out["enabled"] = True
    if not isinstance(out.get("triggers"), list):
        out["triggers"] = []
    out["stats"] = sanitize_stats(out.get("stats"), now)
    return out
