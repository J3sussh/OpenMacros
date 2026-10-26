"""Lógica pura (sem GTK): ações, atalhos, layouts, textos. Testável sem display."""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# ---------------------------------------------------------------- teclas evdev

_CODES: dict[int, str] = {
    1: "ESC", 12: "MINUS", 13: "EQUAL", 14: "BACKSPACE", 15: "TAB", 26: "LEFTBRACE",
    27: "RIGHTBRACE", 28: "ENTER", 29: "LEFTCTRL", 39: "SEMICOLON", 40: "APOSTROPHE",
    41: "GRAVE", 42: "LEFTSHIFT", 43: "BACKSLASH", 51: "COMMA", 52: "DOT", 53: "SLASH",
    54: "RIGHTSHIFT", 55: "KPASTERISK", 56: "LEFTALT", 57: "SPACE", 58: "CAPSLOCK",
    69: "NUMLOCK", 70: "SCROLLLOCK", 74: "KPMINUS", 78: "KPPLUS", 83: "KPDOT",
    96: "KPENTER", 97: "RIGHTCTRL", 98: "KPSLASH", 99: "SYSRQ", 100: "RIGHTALT",
    102: "HOME", 103: "UP", 104: "PAGEUP", 105: "LEFT", 106: "RIGHT", 107: "END",
    108: "DOWN", 109: "PAGEDOWN", 110: "INSERT", 111: "DELETE", 113: "MUTE",
    114: "VOLUMEDOWN", 115: "VOLUMEUP", 119: "PAUSE", 125: "LEFTMETA", 126: "RIGHTMETA",
    127: "COMPOSE", 158: "BACK", 159: "FORWARD", 163: "NEXTSONG", 164: "PLAYPAUSE",
    165: "PREVIOUSSONG",
}
for _i, _c in enumerate("1234567890"):
    _CODES[2 + _i] = _c
for _i, _c in enumerate("QWERTYUIOP"):
    _CODES[16 + _i] = _c
for _i, _c in enumerate("ASDFGHJKL"):
    _CODES[30 + _i] = _c
for _i, _c in enumerate("ZXCVBNM"):
    _CODES[44 + _i] = _c
for _i in range(10):
    _CODES[59 + _i] = f"F{_i + 1}"
_CODES[87], _CODES[88] = "F11", "F12"
for _i, _c in enumerate(["KP7", "KP8", "KP9"]):
    _CODES[71 + _i] = _c
for _i, _c in enumerate(["KP4", "KP5", "KP6"]):
    _CODES[75 + _i] = _c
for _i, _c in enumerate(["KP1", "KP2", "KP3", "KP0"]):
    _CODES[79 + _i] = _c
for _i in range(12):
    _CODES[183 + _i] = f"F{13 + _i}"

EVDEV_CODE_NAMES: dict[int, str] = {k: "KEY_" + v for k, v in _CODES.items()}

MODIFIER_KEYS = ("KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT",
                 "KEY_LEFTALT", "KEY_RIGHTALT", "KEY_LEFTMETA", "KEY_RIGHTMETA")

_ACCEL_MODS = {
    "control": "KEY_LEFTCTRL", "primary": "KEY_LEFTCTRL", "ctrl": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT", "alt": "KEY_LEFTALT", "mod1": "KEY_LEFTALT",
    "super": "KEY_LEFTMETA", "meta": "KEY_LEFTMETA", "hyper": "KEY_LEFTMETA",
}
_MOD_ORDER = ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_LEFTALT", "KEY_LEFTMETA"]

_KEYVAL_NAMES = {
    "return": "KEY_ENTER", "kp_enter": "KEY_KPENTER", "escape": "KEY_ESC", "tab": "KEY_TAB",
    "iso_left_tab": "KEY_TAB", "space": "KEY_SPACE", "backspace": "KEY_BACKSPACE",
    "delete": "KEY_DELETE", "insert": "KEY_INSERT", "home": "KEY_HOME", "end": "KEY_END",
    "page_up": "KEY_PAGEUP", "page_down": "KEY_PAGEDOWN", "left": "KEY_LEFT",
    "right": "KEY_RIGHT", "up": "KEY_UP", "down": "KEY_DOWN", "minus": "KEY_MINUS",
    "equal": "KEY_EQUAL", "bracketleft": "KEY_LEFTBRACE", "bracketright": "KEY_RIGHTBRACE",
    "semicolon": "KEY_SEMICOLON", "apostrophe": "KEY_APOSTROPHE", "grave": "KEY_GRAVE",
    "backslash": "KEY_BACKSLASH", "comma": "KEY_COMMA", "period": "KEY_DOT",
    "slash": "KEY_SLASH", "print": "KEY_SYSRQ", "pause": "KEY_PAUSE",
    "caps_lock": "KEY_CAPSLOCK", "num_lock": "KEY_NUMLOCK", "scroll_lock": "KEY_SCROLLLOCK",
    "menu": "KEY_COMPOSE",
    "xf86audioraisevolume": "KEY_VOLUMEUP", "xf86audiolowervolume": "KEY_VOLUMEDOWN",
    "xf86audiomute": "KEY_MUTE", "xf86audioplay": "KEY_PLAYPAUSE",
    "xf86audionext": "KEY_NEXTSONG", "xf86audioprev": "KEY_PREVIOUSSONG",
    "xf86back": "KEY_BACK", "xf86forward": "KEY_FORWARD",
}


def keyval_name_to_evdev(name: str) -> str:
    """Nome de keyval GDK ('c', 'F5', 'Page_Up') -> 'KEY_*'. ValueError se desconhecido."""
    n = name.strip().lower()
    if n in _KEYVAL_NAMES:
        return _KEYVAL_NAMES[n]
    if len(n) == 1 and n.isalnum() and n.isascii():
        return "KEY_" + n.upper()
    if re.fullmatch(r"f([1-9]|1\d|2[0-4])", n):
        return "KEY_" + n.upper()
    m = re.fullmatch(r"kp_(\d)", n)
    if m:
        return f"KEY_KP{m.group(1)}"
    raise ValueError(f"tecla desconhecida: {name!r}")


def accel_to_evdev(accel: str) -> list[str]:
    """Acelerador GTK ('<Control><Shift>c') -> ['KEY_LEFTCTRL','KEY_LEFTSHIFT','KEY_C']."""
    accel = accel.strip()
    mods: set[str] = set()
    pos = 0
    while pos < len(accel) and accel[pos] == "<":
        end = accel.find(">", pos)
        if end < 0:
            raise ValueError(f"acelerador inválido: {accel!r}")
        mod = _ACCEL_MODS.get(accel[pos + 1:end].lower())
        if mod is None:
            raise ValueError(f"modificador desconhecido em {accel!r}")
        mods.add(mod)
        pos = end + 1
    rest = accel[pos:]
    keys = [m for m in _MOD_ORDER if m in mods]
    if rest:
        keys.append(keyval_name_to_evdev(rest))
    if not keys:
        raise ValueError("acelerador vazio")
    return keys


def keys_from_hardware(keycode: int, ctrl: bool, shift: bool, alt: bool, meta: bool) -> list[str] | None:
    """Combinação a partir do keycode de hardware GTK (evdev+8) e modificadores.
    Retorna None se a tecla pressionada for só um modificador / desconhecida."""
    name = EVDEV_CODE_NAMES.get(keycode - 8)
    if name is None or name in MODIFIER_KEYS:
        return None
    keys = [k for k, on in zip(_MOD_ORDER, (ctrl, shift, alt, meta)) if on]
    return keys + [name]


_PRETTY = {
    "LEFTCTRL": "Ctrl", "RIGHTCTRL": "Ctrl", "LEFTSHIFT": "Shift", "RIGHTSHIFT": "Shift",
    "LEFTALT": "Alt", "RIGHTALT": "AltGr", "LEFTMETA": "Super", "RIGHTMETA": "Super",
    "ENTER": "Enter", "ESC": "Esc", "SPACE": "Espaço", "PAGEUP": "Page Up",
    "PAGEDOWN": "Page Down", "SYSRQ": "Print Screen", "DOT": ".", "COMMA": ",",
    "LEFT": "←", "RIGHT": "→", "UP": "↑", "DOWN": "↓",
}


def pretty_keys(keys: list[str]) -> str:
    out = []
    for k in keys:
        base = k[4:] if k.startswith("KEY_") else k
        out.append(_PRETTY.get(base, base.capitalize() if len(base) > 1 and not re.fullmatch(r"F\d+|KP.*", base) else base))
    return " + ".join(out)


# ---------------------------------------------------------------- presets

@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    keys: tuple[str, ...]


PRESETS: tuple[Preset, ...] = (
    Preset("copy", "Copiar", ("KEY_LEFTCTRL", "KEY_C")),
    Preset("paste", "Colar", ("KEY_LEFTCTRL", "KEY_V")),
    Preset("undo", "Desfazer", ("KEY_LEFTCTRL", "KEY_Z")),
    Preset("redo", "Refazer", ("KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_Z")),
    Preset("vol_up", "Aumentar volume", ("KEY_VOLUMEUP",)),
    Preset("vol_down", "Diminuir volume", ("KEY_VOLUMEDOWN",)),
    Preset("mute", "Mudo", ("KEY_MUTE",)),
    Preset("play_pause", "Reproduzir / pausar", ("KEY_PLAYPAUSE",)),
    Preset("next_track", "Próxima faixa", ("KEY_NEXTSONG",)),
    Preset("prev_track", "Faixa anterior", ("KEY_PREVIOUSSONG",)),
    Preset("desk_prev", "Área de trabalho anterior", ("KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_LEFT")),
    Preset("desk_next", "Próxima área de trabalho", ("KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_RIGHT")),
    Preset("show_windows", "Mostrar janelas", ("KEY_LEFTMETA", "KEY_TAB")),
    Preset("show_desktop", "Mostrar área de trabalho", ("KEY_LEFTMETA", "KEY_D")),
    Preset("screenshot", "Captura de tela", ("KEY_SYSRQ",)),
    Preset("browser_back", "Navegador: voltar", ("KEY_BACK",)),
    Preset("browser_forward", "Navegador: avançar", ("KEY_FORWARD",)),
)
PRESETS_BY_ID = {p.id: p for p in PRESETS}

MOUSE_BUTTONS: tuple[tuple[str, str], ...] = (
    ("BTN_LEFT", "Esquerdo"), ("BTN_RIGHT", "Direito"), ("BTN_MIDDLE", "Meio"),
    ("BTN_SIDE", "Lateral (voltar)"), ("BTN_EXTRA", "Lateral (avançar)"),
    ("BTN_BACK", "Traseiro"), ("BTN_FORWARD", "Frontal"),
)
MOUSE_BUTTON_LABELS = dict(MOUSE_BUTTONS)

# tipos de ação oferecidos pelo seletor: (kind, rótulo)
KINDS: tuple[tuple[str, str], ...] = (
    ("default", "Padrão"),
    ("preset", "Predefinições"),
    ("keys", "Atalho de teclado"),
    ("mouse_button", "Botão do mouse"),
    ("command", "Executar comando"),
    ("change_host", "Trocar de computador"),
    ("gestures", "Gestos"),
    ("disabled", "Desativado"),
)
GESTURE_SLOTS: tuple[tuple[str, str], ...] = (
    ("click", "Clique"), ("up", "Para cima"), ("down", "Para baixo"),
    ("left", "Para a esquerda"), ("right", "Para a direita"),
)
DEFAULT_THRESHOLD = 50

MEDIA_OPS = {"play_pause": "Reproduzir / pausar", "next": "Próxima faixa", "previous": "Faixa anterior",
             "stop": "Parar"}
VOLUME_OPS = {"up": "Aumentar volume", "down": "Diminuir volume", "mute": "Mudo"}
WINDOW_OPS = {"close": "Fechar janela", "minimize": "Minimizar janela", "maximize": "Maximizar janela",
              "fullscreen": "Tela cheia", "next": "Próxima janela", "previous": "Janela anterior"}
APP_OPS = {"open": "Abrir", "close": "Fechar", "focus": "Trazer para frente"}
SYSTEM_OPS = {"lock": "Bloquear a tela", "screenshot": "Captura de tela inteira", "screenshot_area": "Captura de área",
              "suspend": "Suspender", "show_desktop": "Mostrar/ocultar a área de trabalho",
              "mic_mute": "Alternar microfone mudo", "dnd_on": "Ativar Não perturbe",
              "dnd_off": "Desativar Não perturbe", "dnd_toggle": "Alternar Não perturbe",
              "empty_trash": "Esvaziar a lixeira"}
KEY_SEQ_MAX_EVENTS = 400
KEY_SEQ_MAX_DELAY = 10000
KEY_SEQ_FIXED_DELAY = 50
AI_SERVICES = {"claude": "Claude", "chatgpt": "ChatGPT", "perplexity": "Perplexity",
               "gemini": "Gemini (copia o prompt)"}
AI_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("Explique", "Explique de forma simples: {selection}"),
    ("Resuma", "Resuma o texto a seguir em tópicos curtos: {selection}"),
    ("Traduza para português", "Traduza para português: {selection}"),
    ("Revise este código", "Revise este código e aponte erros e melhorias:\n{selection}"),
    ("Personalizado", ""),
)
MAX_TYPE_TEXT = 2000
TYPE_METHODS = ("paste", "keys")
AI_DELIVERIES = {"clipboard": "Área de transferência (recomendado)", "url": "Na URL"}
DEFAULT_PREFERENCES: dict = {
    "notify_battery": True, "battery_threshold": 15, "osd_profile": True, "osd_gestures": True,
    "notify_connection": False, "ai_delivery_default": "clipboard",
}
BATTERY_THRESHOLD_RANGE = (5, 50)


def normalize_preferences(prefs: dict | None) -> dict:
    """Preenche padrões e descarta valores de tipo inválido."""
    out = dict(DEFAULT_PREFERENCES)
    for k, v in (prefs or {}).items():
        d = DEFAULT_PREFERENCES.get(k)
        if d is None:
            continue
        if isinstance(d, bool) and isinstance(v, bool):
            out[k] = v
        elif isinstance(d, int) and not isinstance(d, bool) and isinstance(v, int) and not isinstance(v, bool):
            lo, hi = BATTERY_THRESHOLD_RANGE
            out[k] = max(lo, min(hi, v))
        elif isinstance(d, str) and v in AI_DELIVERIES:
            out[k] = v
    return out


def validate_import(text: str) -> dict:
    """Valida superficialmente um arquivo de backup (ValueError com mensagem legível)."""
    import json as _json
    try:
        data = _json.loads(text)
    except ValueError as e:
        raise ValueError("O arquivo não é um JSON válido") from e
    if not isinstance(data, dict) or "openmacros_export" not in data:
        raise ValueError("Este arquivo não parece ser um backup do OpenMacros+")
    if data.get("openmacros_export") != 1:
        raise ValueError("Versão de backup não suportada")
    return data


def backup_filename(now=None) -> str:
    import datetime as _dt
    return "openmacros-backup-" + (now or _dt.datetime.now()).strftime("%Y%m%d-%H%M") + ".json"


def preset_for_keys(keys: list[str]) -> Preset | None:
    t = tuple(keys)
    for p in PRESETS:
        if p.keys == t:
            return p
    return None


# ---------------------------------------------------------------- ações (JSON)

def build_action(kind: str, **p) -> dict:
    """Monta o JSON de Action. Levanta ValueError se os parâmetros forem inválidos."""
    if kind in ("default", "disabled"):
        return {"type": kind}
    if kind == "preset":
        preset = PRESETS_BY_ID.get(p.get("preset", ""))
        if preset is None:
            raise ValueError("predefinição inválida")
        return {"type": "keys", "keys": list(preset.keys)}
    if kind == "keys":
        keys = [str(k) for k in p.get("keys") or []]
        if not keys or not all(k.startswith("KEY_") for k in keys):
            raise ValueError("capture um atalho de teclado")
        return {"type": "keys", "keys": keys}
    if kind == "mouse_button":
        btn = p.get("button", "")
        if btn not in MOUSE_BUTTON_LABELS:
            raise ValueError("botão inválido")
        return {"type": "mouse_button", "button": btn}
    if kind == "command":
        text = str(p.get("command", "")).strip()
        try:
            argv = shlex.split(text)
        except ValueError as e:
            raise ValueError(f"comando inválido: {e}") from e
        if not argv:
            raise ValueError("informe um comando")
        return {"type": "command", "argv": argv}
    if kind == "change_host":
        host = int(p.get("host", 0))
        if host < 0:
            raise ValueError("computador inválido")
        return {"type": "change_host", "host": host}  # 0-based, como ChangeHost
    if kind == "media":
        op = p.get("op", "")
        if op not in MEDIA_OPS:
            raise ValueError("operação de mídia inválida")
        out = {"type": "media", "op": op}
        if str(p.get("player", "")).strip():
            out["player"] = str(p["player"]).strip().lower()
        return out
    if kind == "volume":
        op = p.get("op", "")
        if op not in VOLUME_OPS:
            raise ValueError("operação de volume inválida")
        out = {"type": "volume", "op": op}
        if op != "mute":
            out["step"] = max(1, min(100, int(p.get("step", 5))))
        return out
    if kind == "open":
        target = str(p.get("target", "")).strip()
        if not target:
            raise ValueError("informe uma URL, arquivo ou aplicativo")
        return {"type": "open", "target": target}
    if kind == "type_text":
        text = str(p.get("text", ""))
        if not text:
            raise ValueError("informe o texto a digitar")
        if len(text) > MAX_TYPE_TEXT:
            raise ValueError(f"texto longo demais (máx. {MAX_TYPE_TEXT} caracteres)")
        out = {"type": "type_text", "text": text}
        if p.get("method") == "keys":
            out["method"] = "keys"
        return out
    if kind == "window":
        op = p.get("op", "")
        if op not in WINDOW_OPS:
            raise ValueError("operação de janela inválida")
        return {"type": "window", "op": op}
    if kind == "ai_prompt":
        service = p.get("service", "")
        template = str(p.get("template", "")).strip()
        if service not in AI_SERVICES:
            raise ValueError("serviço de IA inválido")
        if not template:
            raise ValueError("informe o modelo do prompt")
        if len(template) > 4000:
            raise ValueError("modelo longo demais")
        delivery = p.get("delivery")
        if delivery is not None and delivery not in AI_DELIVERIES:
            raise ValueError("entrega inválida")
        out = {"type": "ai_prompt", "service": service, "template": template}
        if delivery:
            out["delivery"] = delivery
        return out
    if kind == "app":
        op, target = p.get("op", ""), str(p.get("target", "")).strip()
        if op not in APP_OPS:
            raise ValueError("operação de aplicativo inválida")
        if not target:
            raise ValueError("escolha um aplicativo")
        return {"type": "app", "op": op, "target": target}
    if kind == "system":
        op = p.get("op", "")
        if op not in SYSTEM_OPS:
            raise ValueError("operação de sistema inválida")
        return {"type": "system", "op": op}
    if kind == "key_sequence":
        return {"type": "key_sequence", "events": validate_key_events(p.get("events"))}
    if kind == "smart_action":
        sid = str(p.get("id", "")).strip()
        if not sid:
            raise ValueError("Smart Action inválida")
        return {"type": "smart_action", "id": sid}
    if kind == "gestures":
        slots = p.get("slots") or {}
        out: dict = {"type": "gestures"}
        for key, _ in GESTURE_SLOTS:
            out[key] = slots.get(key) or {"type": "default"}
        out["threshold"] = int(p.get("threshold", DEFAULT_THRESHOLD))
        return out
    raise ValueError(f"tipo de ação desconhecido: {kind}")


def classify_action(action: dict | None) -> tuple[str, dict]:
    """Inverso de build_action: (kind, params) para preencher o seletor."""
    if not isinstance(action, dict):
        return "default", {}
    t = action.get("type", "default")
    if t == "disabled":
        return "disabled", {}
    if t == "keys":
        keys = list(action.get("keys") or [])
        preset = preset_for_keys(keys)
        if preset:
            return "preset", {"preset": preset.id}
        return "keys", {"keys": keys}
    if t == "mouse_button":
        return "mouse_button", {"button": action.get("button", "BTN_LEFT")}
    if t == "command":
        return "command", {"command": shlex.join(action.get("argv") or [])}
    if t == "change_host":
        return "change_host", {"host": int(action.get("host", 0))}
    if t == "media":
        return "media", {"op": action.get("op", "play_pause"), "player": action.get("player", "")}
    if t == "volume":
        return "volume", {"op": action.get("op", "up"), "step": int(action.get("step", 5))}
    if t in ("open", "type_text", "window", "ai_prompt", "smart_action", "app", "system", "key_sequence"):
        return t, {k: v for k, v in action.items() if k != "type"}
    if t == "gestures":
        slots = {k: action.get(k) or {"type": "default"} for k, _ in GESTURE_SLOTS}
        return "gestures", {"slots": slots, "threshold": int(action.get("threshold", DEFAULT_THRESHOLD))}
    return "default", {}


def _short(text: str, n: int = 24) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe_action(action: dict | None, smart_actions: dict | None = None) -> str:
    kind, p = classify_action(action)
    if isinstance(action, dict) and action.get("type") == "remap":
        return f"Remapeado (CID {action.get('cid')})"
    if kind == "default":
        return "Padrão"
    if kind == "disabled":
        return "Desativado"
    if kind == "preset":
        return PRESETS_BY_ID[p["preset"]].label
    if kind == "keys":
        return pretty_keys(p["keys"])
    if kind == "mouse_button":
        return "Botão " + MOUSE_BUTTON_LABELS.get(p["button"], p["button"]).lower()
    if kind == "command":
        argv = (action or {}).get("argv") or [""]
        return f"Comando: {Path(argv[0]).name}"
    if kind == "change_host":
        return f"Computador {p['host'] + 1}"
    if kind == "gestures":
        return "Gestos"
    if kind == "media":
        return MEDIA_OPS.get(p["op"], p["op"]) + (f" ({p['player']})" if p.get("player") else "")
    if kind == "volume":
        return VOLUME_OPS.get(p["op"], p["op"])
    if kind == "window":
        return WINDOW_OPS.get(p["op"], p["op"])
    if kind == "open":
        return "Abrir: " + _short(p["target"].removesuffix(".desktop"))
    if kind == "type_text":
        return "Digitar: " + _short(p["text"], 18)
    if kind == "ai_prompt":
        return "IA: " + AI_SERVICES.get(p["service"], p["service"]).split(" (")[0]
    if kind == "smart_action":
        sa = (smart_actions or {}).get(p["id"])
        return sa["name"] if sa else "Smart Action"
    if kind == "app":
        return f"{APP_OPS.get(p.get('op'), 'Aplicativo')}: " + _short(str(p.get("target", "")).removesuffix(".desktop"))
    if kind == "system":
        return SYSTEM_OPS.get(p.get("op"), "Sistema")
    if kind == "key_sequence":
        return "Sequência de teclas: " + events_summary(p.get("events"))
    return "Padrão"


# ---------------------------------------------------------------- dispositivos

def battery_icon(battery: dict | None) -> str:
    if not battery:
        return "battery-missing-symbolic"
    level = max(0, min(100, int(battery.get("level", 0))))
    status = str(battery.get("status", "")).lower()
    if status == "full" or (status == "charging" and level >= 100):
        return "battery-level-100-charged-symbolic"
    step = min(100, round(level / 10) * 10)
    if status == "charging":
        return f"battery-level-{step}-charging-symbolic"
    return f"battery-level-{step}-symbolic"


def battery_text(battery: dict | None) -> str:
    if not battery:
        return "Bateria indisponível"
    pre = "~" if battery.get("approximate") else ""
    txt = f"{pre}{int(battery.get('level', 0))}%"
    if str(battery.get("status", "")).lower() == "charging":
        txt += " (carregando)"
    return txt


CONNECTION_LABELS = {"receiver": "Receptor USB", "bluetooth": "Bluetooth", "usb": "Cabo USB"}


def connection_label(conn: str | None) -> str:
    return CONNECTION_LABELS.get(conn or "", "Desconhecida")


def art_name(device: dict) -> str:
    layout = device.get("layout") or ""
    if layout and (DATA_DIR / "art" / f"{layout}.svg").is_file():
        return layout
    return "generic-keyboard" if device.get("kind") == "keyboard" else "generic-mouse"


def vendor_info(device: dict):
    """(layout_dict, pasta) da arte importada localmente para o model_id do dispositivo, ou None."""
    from .. import vendor_assets
    return vendor_assets.load_vendor_layout(str(device.get("model_id") or ""))


def _vendor_file(info, name: str | None) -> Path | None:
    if not info or not name or "/" in name or name.startswith("."):
        return None
    f = info[1] / name
    return f if f.is_file() else None


def art_path(device: dict) -> Path:
    """Imagem principal (frontal) do dispositivo: arte importada se houver, senão SVG próprio."""
    front = _vendor_file(vendor_info(device), (vendor_info(device) or ({},))[0].get("front"))
    return front or DATA_DIR / "art" / f"{art_name(device)}.svg"


def has_vendor_art(device: dict) -> bool:
    return _vendor_file(vendor_info(device), (vendor_info(device) or ({},))[0].get("front")) is not None


def easy_switch_images(device: dict, dark: bool = False) -> dict[int, Path]:
    """Indicadores 1..N importados (vazio sem arte importada)."""
    info = vendor_info(device)
    if not info:
        return {}
    out = {}
    for key, name in (info[0].get("easy_switch") or {}).items():
        if key.endswith("_dark") != dark:
            continue
        num = key.removesuffix("_dark")
        f = _vendor_file(info, name)
        if f and num.isdigit():
            out[int(num)] = f
    return out


POINTER_SETTINGS = ("pointer_speed", "dpi", "hires_scroll", "scroll_invert", "smartshift")


# Clique principal e secundário: remapear pode deixar o mouse inutilizável.
PROTECTED_CIDS = frozenset({0x50, 0x51})


def is_configurable(control: dict) -> bool:
    """Fica de fora: botões esquerdo/direito e controles sem remap nem divert."""
    if int(control.get("cid", 0)) in PROTECTED_CIDS:
        return False
    return bool(control.get("remappable") or control.get("divertable"))


def host_count(device: dict, default: int = 0) -> int:
    """Número de slots Easy-Switch, tolerante a dado malformado (0..16)."""
    hosts = device.get("hosts") if isinstance(device, dict) else None
    if not isinstance(hosts, dict):
        return default
    try:
        n = int(hosts.get("count", default))
    except (TypeError, ValueError):
        return default
    return max(0, min(16, n))


def supported_tabs(device: dict) -> list[str]:
    tabs = []
    if any(is_configurable(c) for c in device.get("controls") or []):
        tabs.append("buttons")
    if any(k in (device.get("settings") or {}) for k in POINTER_SETTINGS):
        tabs.append("pointer")
    if host_count(device) > 0:
        tabs.append("easyswitch")
    tabs.append("about")
    return tabs


def friendly_error(message: str) -> str:
    """Remove o prefixo 'GDBus.Error:...' e traduz erros conhecidos."""
    m = re.match(r"^(?:GDBus\.Error:)?io\.github\.openmacros\.Error\.(\w+):\s*(.*)$", message.strip(), re.S)
    if not m:
        m2 = re.match(r"^GDBus\.Error:[\w.]+:\s*(.*)$", message.strip(), re.S)
        return m2.group(1) if m2 else message
    kind, rest = m.groups()
    base = {
        "NotFound": "Dispositivo não encontrado",
        "Unsupported": "Recurso não suportado por este dispositivo",
        "DeviceOffline": "O dispositivo está offline",
        "InvalidArgument": "Valor inválido",
    }.get(kind, kind)
    return f"{base}: {rest}" if rest else base


# ---------------------------------------------------------------- layouts

@dataclass(frozen=True)
class Marker:
    cid: int
    x: float
    y: float
    side: str = "right"


@dataclass(frozen=True)
class Layout:
    name: str
    art: str
    aspect: float
    markers: tuple[Marker, ...]
    art_path: str | None = None  # caminho absoluto (arte importada); None = SVG embutido em data/art


def parse_layout(data: dict) -> Layout:
    """Valida o JSON de layout. ValueError em caso de erro."""
    try:
        w, h = data["aspect"]
        if w <= 0 or h <= 0:
            raise ValueError("aspect deve ser positivo")
        markers = []
        for m in data["markers"]:
            x, y = float(m["x"]), float(m["y"])
            side = m.get("side", "right")
            if not (0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError(f"marcador fora de 0..1: {m}")
            if side not in ("left", "right", "up", "down"):
                raise ValueError(f"side inválido: {side}")
            markers.append(Marker(int(m["cid"]), x, y, side))
        return Layout(str(data["name"]), str(data.get("art", data["name"])), float(w) / float(h), tuple(markers))
    except (KeyError, TypeError) as e:
        raise ValueError(f"layout inválido: {e!r}") from e


def load_layout(name: str | None) -> Layout | None:
    if not name or "/" in name or name.startswith("."):
        return None
    path = DATA_DIR / "layouts" / f"{name}.json"
    try:
        return parse_layout(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def auto_markers(cids: list[int]) -> tuple[Marker, ...]:
    """Fallback genérico: distribui os controles nas laterais da arte, alternando esquerda/direita."""
    left = cids[0::2]
    right = cids[1::2]
    out = []
    for cids_side, side, x in ((left, "left", 0.0), (right, "right", 1.0)):
        n = len(cids_side)
        for i, cid in enumerate(cids_side):
            out.append(Marker(cid, x, (i + 1) / (n + 1) if n else 0.5, side))
    return tuple(out)


def vendor_layout(device: dict) -> Layout | None:
    """Layout de botões a partir da arte importada (side.webp + marcadores), se existir."""
    info = vendor_info(device)
    if not info:
        return None
    sec = info[0].get("buttons") or {}
    art = _vendor_file(info, sec.get("art"))
    try:
        markers = tuple(Marker(int(m["cid"]), _unit(m["x"]), _unit(m["y"]), m.get("side", "right"))
                        for m in sec.get("markers") or [] if "cid" in m)
        aspect = float(sec.get("aspect") or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if art is None or not markers or aspect <= 0:
        return None
    return Layout(str(info[0].get("name", "vendor")), art.name, aspect, markers, str(art))


def _unit(v) -> float:
    return max(0.0, min(1.0, float(v)))


def layout_art_file(layout: Layout) -> Path:
    return Path(layout.art_path) if layout.art_path else DATA_DIR / "art" / f"{layout.art}.svg"


def resolve_layout(device: dict) -> tuple[Layout, bool]:
    """(layout, generico). Marcadores só para controles remapeáveis presentes."""
    remappable = [int(c["cid"]) for c in device.get("controls") or [] if is_configurable(c)]
    layout = vendor_layout(device) or load_layout(device.get("layout"))
    if layout is not None:
        present = tuple(m for m in layout.markers if m.cid in remappable)
        if present:
            # controles fora do layout ganham marcador na coluna da direita
            extra = [c for c in remappable if c not in {m.cid for m in layout.markers}]
            extra_markers = tuple(Marker(c, 1.0, (i + 1) / (len(extra) + 1), "right")
                                  for i, c in enumerate(extra))
            return Layout(layout.name, layout.art, layout.aspect, present + extra_markers, layout.art_path), False
    art = art_name(device)
    aspect = 520 / 260 if art == "generic-keyboard" else 400 / 520
    return Layout("generic", art, aspect, auto_markers(remappable)), True


def palette_css(dark: bool) -> str:
    """Variáveis de cor do libadwaita para o tema claro/escuro do OpenMacros+."""
    if dark:
        c = dict(window_bg="#1d1d1f", window_fg="#f5f5f7", card_bg="#2a2a2c", card_fg="#f5f5f7",
                 headerbar_bg="#1d1d1f", view_bg="#1d1d1f", accent_bg="#0a95d6", accent="#4cc3ff",
                 dialog_bg="#242426", popover_bg="#2a2a2c", shade="rgba(0,0,0,0.5)")
    else:
        c = dict(window_bg="#f2f2f2", window_fg="#1d1d1f", card_bg="#ffffff", card_fg="#1d1d1f",
                 headerbar_bg="#f2f2f2", view_bg="#f2f2f2", accent_bg="#0087c8", accent="#006fa6",
                 dialog_bg="#f7f7f7", popover_bg="#ffffff", shade="rgba(0,0,0,0.12)")
    lines = [
        f"@define-color window_bg_color {c['window_bg']};", f"@define-color window_fg_color {c['window_fg']};",
        f"@define-color card_bg_color {c['card_bg']};", f"@define-color card_fg_color {c['card_fg']};",
        f"@define-color headerbar_bg_color {c['headerbar_bg']};", f"@define-color view_bg_color {c['view_bg']};",
        f"@define-color accent_bg_color {c['accent_bg']};", f"@define-color accent_color {c['accent']};",
        f"@define-color dialog_bg_color {c['dialog_bg']};", f"@define-color popover_bg_color {c['popover_bg']};",
        f"@define-color card_shade_color {c['shade']};",
        ":root { --window-bg-color: %s; --window-fg-color: %s; --card-bg-color: %s; --card-fg-color: %s;"
        " --headerbar-bg-color: %s; --view-bg-color: %s; --accent-bg-color: %s; --accent-color: %s;"
        " --dialog-bg-color: %s; --popover-bg-color: %s; --card-shade-color: %s; }" % (
            c["window_bg"], c["window_fg"], c["card_bg"], c["card_fg"], c["headerbar_bg"], c["view_bg"],
            c["accent_bg"], c["accent"], c["dialog_bg"], c["popover_bg"], c["shade"]),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- painel lateral de ações

STEP_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("app", "Aplicativo"), ("keys", "Pressionamento de tecla"), ("text", "Texto"), ("system", "Sistema"),
    ("media", "Mídia"), ("ai", "IA"), ("delay", "Atraso"), ("command", "Comando"),
)


def step_category_sections(category: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Seções (uma só) de itens de um passo 'Então…' para a categoria; [] para 'delay' (editor próprio)."""
    def pr(*ids):
        return [(f"preset:{i}", PRESETS_BY_ID[i].label) for i in ids]
    title = dict(STEP_CATEGORIES)[category]
    items: list[tuple[str, str]]
    if category == "app":
        items = [("app", "Abrir, fechar ou trazer um aplicativo para frente"),
                 ("open", "Abrir site, arquivo ou aplicativo")]
    elif category == "keys":
        items = [("key_sequence", "Gravar sequência de teclas"), ("keys", "Atalho de teclado")] \
            + pr("copy", "paste", "undo", "redo")
    elif category == "text":
        items = [("type_text", "Digitar texto")]
    elif category == "system":
        items = ([(f"system:{op}", label) for op, label in SYSTEM_OPS.items()]
                 + [(f"volume:{op}", label) for op, label in VOLUME_OPS.items()] + [("window", "Controlar janela")])
    elif category == "media":
        items = [(f"media:{op}", label) for op, label in MEDIA_OPS.items()]
    elif category == "ai":
        items = [("ai_prompt", "Perguntar à IA sobre a seleção")]
    elif category == "command":
        items = [("command", "Executar comando")]
    else:
        return []
    return [(title, items)]


def action_sections(allow_gestures: bool = False, smart_actions: dict | None = None,
                    allow_smart: bool = True, steps: bool = False) -> list[tuple[str, list[tuple[str, str]]]]:
    """Seções do painel: [(título, [(item_id, rótulo)])]. item_id: 'default', 'gestures',
    'preset:<id>', 'media:<op>', 'volume:<op>', 'system:<op>', 'window', 'open', 'app', 'key_sequence',
    'type_text', 'ai_prompt', 'smart:<id>', 'smart_new', 'keys', 'mouse_button', 'command', 'change_host',
    'disabled'. Com steps=True, as seções seguem as categorias de STEP_CATEGORIES."""
    if steps:
        out = []
        for cat, _ in STEP_CATEGORIES:
            out += step_category_sections(cat)
        return out

    def pr(*ids):
        return [(f"preset:{i}", PRESETS_BY_ID[i].label) for i in ids]
    rec = [("default", "Padrão")]
    if allow_gestures:
        rec.append(("gestures", "Gestos"))
    rec += pr("show_windows")
    out = [
        ("Recomendadas", rec),
        ("Navegação", pr("browser_back", "browser_forward", "desk_prev", "desk_next")),
        ("Mídia", [(f"media:{op}", label) for op, label in MEDIA_OPS.items()]),
        ("Edição", pr("copy", "paste", "undo", "redo")),
        ("Sistema", [(f"volume:{op}", label) for op, label in VOLUME_OPS.items()]
         + [("window", "Controlar janela"), ("open", "Abrir aplicativo, site ou arquivo"),
            ("app", "Controlar aplicativo"), ("type_text", "Digitar texto")] + pr("show_desktop", "screenshot")
         + [(f"system:{op}", label) for op, label in SYSTEM_OPS.items() if op not in ("show_desktop", "screenshot")]),
        ("IA", [("ai_prompt", "Perguntar à IA sobre a seleção")]),
    ]
    if allow_smart:
        sa = [(f"smart:{sid}", d.get("name", sid)) for sid, d in sorted((smart_actions or {}).items(),
                                                                       key=lambda kv: kv[1].get("name", "").lower())]
        out.append(("Smart Actions", sa + [("smart_new", "Criar Smart Action…")]))
    adv = [("keys", "Atalho de teclado"), ("key_sequence", "Gravar sequência de teclas"),
           ("mouse_button", "Botão do mouse"), ("command", "Executar comando"),
           ("change_host", "Trocar de computador"), ("disabled", "Desativar")]
    out.append(("Avançado", adv))
    return out


PARAM_ITEMS = ("keys", "mouse_button", "command", "change_host", "window", "open", "type_text", "ai_prompt", "app",
              "key_sequence")


def item_id_for_action(action: dict | None) -> str:
    kind, p = classify_action(action)
    if kind == "preset":
        return f"preset:{p['preset']}"
    if kind in ("media", "volume"):
        return f"{kind}:{p['op']}"
    if kind == "smart_action":
        return f"smart:{p['id']}"
    if kind == "system":
        return f"system:{p.get('op')}"
    return kind


def action_for_simple_item(item_id: str) -> dict | None:
    """Ação imediata para itens sem parâmetros; None se precisa de parâmetros ou é item especial."""
    if item_id in ("default", "disabled"):
        return build_action(item_id)
    head, _, tail = item_id.partition(":")
    if head == "preset" and tail:
        return build_action("preset", preset=tail)
    if head in ("media", "volume") and tail:
        return build_action(head, op=tail)
    if head == "smart" and tail:
        return build_action("smart_action", id=tail)
    if head == "system" and tail in SYSTEM_OPS:
        return build_action("system", op=tail)
    return None


GESTURE_CROSS = (  # (slot, linha, coluna) do mini-diagrama em cruz
    ("up", 0, 1), ("left", 1, 0), ("click", 1, 1), ("right", 1, 2), ("down", 2, 1))
SENSITIVITY_MIN, SENSITIVITY_MAX = 10, 200


def threshold_to_sensitivity(threshold: int) -> int:
    """Slider 'Sensibilidade' (0..100, maior = mais sensível) <-> threshold (menor = mais sensível)."""
    t = max(SENSITIVITY_MIN, min(SENSITIVITY_MAX, int(threshold)))
    return round(100 * (SENSITIVITY_MAX - t) / (SENSITIVITY_MAX - SENSITIVITY_MIN))


def sensitivity_to_threshold(value: float) -> int:
    v = max(0.0, min(100.0, float(value)))
    return int(round(SENSITIVITY_MAX - v / 100 * (SENSITIVITY_MAX - SENSITIVITY_MIN)))


def set_gesture_slot(action: dict | None, slot: str, new: dict) -> dict:
    """Devolve uma ação 'gestures' com o slot trocado (cria a partir de padrões se preciso)."""
    kind, p = classify_action(action)
    slots = dict(p["slots"]) if kind == "gestures" else {}
    if slot not in dict(GESTURE_SLOTS):
        raise ValueError(f"slot de gesto inválido: {slot}")
    slots[slot] = new
    return build_action("gestures", slots=slots, threshold=p.get("threshold", DEFAULT_THRESHOLD) if kind == "gestures" else DEFAULT_THRESHOLD)


def speed_label(value: int, lo: int, hi: int) -> str:
    frac = (value - lo) / max(1, hi - lo)
    return "Lento" if frac < 0.34 else "Rápido" if frac > 0.66 else "Médio"


# ---------------------------------------------------------------- catálogo de apps e perfis

_catalog_cache: dict | None = None


def load_catalog() -> dict:
    """Catálogo próprio (data/apps.json): {'suggestion_sets': {...}, 'apps': {...}}."""
    global _catalog_cache
    if _catalog_cache is None:
        try:
            _catalog_cache = json.loads((DATA_DIR / "apps.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _catalog_cache = {"suggestion_sets": {}, "apps": {}}
    return _catalog_cache


def resolve_app_id(app_id: str) -> str:
    """Normaliza (minúsculas) e resolve aliases do catálogo."""
    a = (app_id or "").strip().lower()
    apps = load_catalog()["apps"]
    if a in apps:
        return a
    for key, entry in apps.items():
        if a in [x.lower() for x in entry.get("aliases", [])]:
            return key
    return a


def catalog_entry(app_id: str) -> dict | None:
    return load_catalog()["apps"].get(resolve_app_id(app_id))


def app_ids_for_desktop(desktop_id: str, wm_class: str | None = None) -> list[str]:
    """Possíveis app_id (WM_CLASS em minúsculas) de um .desktop."""
    ids: list[str] = []
    base = (desktop_id or "").removesuffix(".desktop")
    for cand in (wm_class or "", base, base.rsplit(".", 1)[-1] if "." in base else ""):
        c = cand.strip().lower()
        if c and c not in ids:
            ids.append(c)
    for key, entry in load_catalog()["apps"].items():
        if desktop_id in entry.get("desktop", []) and key not in ids:
            ids.append(key)
    return ids


def suggestions_for(app_id: str, controls: list[dict] | None = None) -> dict[str, dict]:
    """Sugestões do catálogo (cid em texto -> Action), restritas aos controles configuráveis do dispositivo."""
    entry = catalog_entry(app_id)
    if not entry or not entry.get("suggestions"):
        return {}
    sset = load_catalog()["suggestion_sets"].get(entry["suggestions"], {})
    out = {}
    allowed = None if controls is None else {str(c["cid"]) for c in controls if is_configurable(c)}
    for cid, action in (sset.get("assignments") or {}).items():
        if allowed is not None and cid not in allowed:
            continue
        kind, p = classify_action(action)
        out[cid] = build_action("gestures", **p) if kind == "gestures" else action
    return out


def profiles_of(device: dict) -> dict[str, dict]:
    return {a: p for a, p in (device.get("profiles") or {}).items() if isinstance(p, dict)}


def profile_app_ids(device: dict) -> list[str]:
    return sorted(profiles_of(device))


def supports_profiles(device: dict) -> bool:
    return "profiles" in device or "active_profile" in device


def effective_action(device: dict, app_id: str, cid: int) -> tuple[dict | None, str]:
    """(ação, origem) onde origem é 'app' (sobreposição do perfil) ou 'global'."""
    if app_id:
        a = (profiles_of(device).get(app_id, {}).get("assignments") or {}).get(str(cid))
        if a is not None:
            return a, "app"
    return (device.get("assignments") or {}).get(str(cid)), "global"


def effective_setting(device: dict, app_id: str, key: str) -> tuple[dict | None, bool]:
    """(valor da configuração, sobreposto_pelo_perfil)."""
    if app_id:
        v = (profiles_of(device).get(app_id, {}).get("settings") or {}).get(key)
        if v is not None:
            return v, True
    return (device.get("settings") or {}).get(key), False


def with_profile_assignment(device: dict, app_id: str, cid: int, action: dict | None) -> None:
    """Atualiza o JSON local (otimista): action None remove a sobreposição."""
    if not app_id:
        device.setdefault("assignments", {})[str(cid)] = action
        return
    prof = device.setdefault("profiles", {}).setdefault(app_id, {"assignments": {}, "settings": {}})
    if action is None:
        prof.setdefault("assignments", {}).pop(str(cid), None)
    else:
        prof.setdefault("assignments", {})[str(cid)] = action


def with_profile_setting(device: dict, app_id: str, key: str, value: dict | None) -> None:
    if not app_id:
        device.setdefault("settings", {}).setdefault(key, {}).update(value or {})
        return
    prof = device.setdefault("profiles", {}).setdefault(app_id, {"assignments": {}, "settings": {}})
    if value is None:
        prof.setdefault("settings", {}).pop(key, None)
    else:
        prof.setdefault("settings", {})[key] = value


def profile_indicator(device: dict, active_app: dict | None, name_of=lambda a: a) -> str:
    """Texto do indicador do topo ('' = esconder)."""
    prof = device.get("active_profile") or ""
    if prof:
        return f"Perfil ativo: {name_of(prof)}"
    app = (active_app or {}).get("app_id") or ""
    if app and supports_profiles(device):
        return f"Perfil ativo: Todos os aplicativos (em foco: {name_of(app)})"
    if supports_profiles(device):
        return "Perfil ativo: Todos os aplicativos"
    return ""


def filter_apps(entries: list, query: str) -> list:
    """Filtra entradas com .name/.app_id por substring (sem acento/maiúsculas)."""
    import unicodedata

    def norm(t: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if not unicodedata.combining(c))
    q = norm(query.strip())
    return [e for e in entries if not q or q in norm(e.name) or q in norm(e.app_id)]


# ---------------------------------------------------------------- Smart Actions

SA_MAX_STEPS = 32
SA_MAX_TRIGGERS = 5
SA_DELAY_MIN, SA_DELAY_MAX = 10, 10000
SA_ICONS = ("system-run-symbolic", "weather-clear-symbolic", "media-playback-start-symbolic",
            "emblem-favorite-symbolic", "web-browser-symbolic", "utilities-terminal-symbolic",
            "audio-headphones-symbolic", "applications-engineering-symbolic", "user-home-symbolic",
            "starred-symbolic", "camera-video-symbolic", "audio-input-microphone-symbolic",
            "system-search-symbolic", "view-refresh-symbolic", "camera-photo-symbolic",
            "weather-clear-night-symbolic", "input-keyboard-symbolic", "system-lock-screen-symbolic",
            "preferences-system-notifications-symbolic", "folder-open-symbolic")
SA_DEFAULT_ICON = SA_ICONS[0]
SA_NAME_MAX = 60
SA_DESCRIPTION_MAX = 200
SA_SORTS = (("recent", "Mais recentes"), ("alpha", "Ordem alfabética"), ("used", "Mais usadas"))
TRIGGER_TYPES = (("button", "Botão do dispositivo"), ("shortcut", "Atalho de teclado"),
                 ("app", "Aplicativo"), ("device", "Dispositivo"))
APP_EVENTS = {"open": "Abrir", "close": "Fechar", "focus": "Primeiro plano"}
APP_EVENT_PHRASES = {"open": "Ao abrir", "close": "Ao fechar", "focus": "Ao focar"}
DEVICE_EVENTS = {"connect": "Conectar", "disconnect": "Desconectar"}
SA_SECRETS_NOTE = "Não guarde senhas ou dados sensíveis em Smart Actions."

_MEDIA_KEYS = ("KEY_VOLUMEUP", "KEY_VOLUMEDOWN", "KEY_MUTE", "KEY_PLAYPAUSE", "KEY_NEXTSONG", "KEY_PREVIOUSSONG",
               "KEY_BACK", "KEY_FORWARD")
_CTRL_ALT_SUPER_SHIFT = set(MODIFIER_KEYS)


def validate_key_events(events) -> list[dict]:
    """Valida/normaliza eventos de key_sequence (ValueError se inválido)."""
    if not isinstance(events, list) or not events:
        raise ValueError("grave ao menos uma tecla")
    if len(events) > KEY_SEQ_MAX_EVENTS:
        raise ValueError(f"a sequência pode ter no máximo {KEY_SEQ_MAX_EVENTS} eventos")
    out = []
    for e in events:
        if not isinstance(e, dict):
            raise ValueError("evento de tecla inválido")
        key = str(e.get("key", ""))
        if not key.startswith("KEY_") or len(key) > 40:
            raise ValueError("tecla inválida na sequência")
        try:
            delay = int(e.get("delay_ms", 0))
        except (TypeError, ValueError) as err:
            raise ValueError("atraso inválido na sequência") from err
        if not 0 <= delay <= KEY_SEQ_MAX_DELAY:
            raise ValueError(f"atraso entre teclas deve ficar entre 0 e {KEY_SEQ_MAX_DELAY} ms")
        out.append({"key": key, "down": bool(e.get("down")), "delay_ms": delay})
    return out


def events_duration_ms(events) -> int:
    return sum(int(e.get("delay_ms", 0)) for e in events or [] if isinstance(e, dict))


def events_summary(events) -> str:
    n = len(events) if isinstance(events, list) else 0
    ms = events_duration_ms(events)
    return f"{n} evento{'s' if n != 1 else ''}" + (f", {ms / 1000:.1f} s".replace(".", ",") if ms >= 100 else "")


def events_preview(events, limit: int = 14) -> str:
    """Teclas na ordem em que foram pressionadas: 'Ctrl → C → Enter'."""
    names = []
    for e in events or []:
        if isinstance(e, dict) and e.get("down"):
            names.append(pretty_keys([e.get("key", "")]))
    shown = names[:limit]
    return " → ".join(shown) + (f" … (+{len(names) - limit})" if len(names) > limit else "")


class KeySequenceRecorder:
    """Estado puro do gravador: recebe (tecla, down, instante em ms) e produz eventos de key_sequence."""

    def __init__(self, fixed: bool = False, events: list | None = None):
        self.fixed = fixed
        self.events: list[dict] = [dict(e) for e in events or []]
        self._down: set[str] = {e["key"] for e in self.events if e["down"]} - {e["key"] for e in self.events if not e["down"]}
        self._last_ms: int | None = None

    @property
    def full(self) -> bool:
        return len(self.events) >= KEY_SEQ_MAX_EVENTS

    def resume(self) -> None:
        """Ao continuar, o tempo parado entre gravações não conta."""
        self._last_ms = None

    def feed(self, key: str, down: bool, now_ms: int) -> bool:
        """False se o evento foi ignorado (repetição automática, soltar sem apertar, limite)."""
        if self.full:
            return False
        if down and key in self._down:
            return False
        if not down and key not in self._down:
            return False
        if not self.events or self._last_ms is None:
            delay = 0 if not self.events else (KEY_SEQ_FIXED_DELAY if self.fixed else 0)
        elif self.fixed:
            delay = KEY_SEQ_FIXED_DELAY
        else:
            delay = max(0, min(KEY_SEQ_MAX_DELAY, int(now_ms - self._last_ms)))
        self._last_ms = now_ms
        (self._down.add if down else self._down.discard)(key)
        self.events.append({"key": key, "down": down, "delay_ms": delay})
        return True

    def release_all(self) -> None:
        """Solta tudo o que ficou pressionado ao parar (a sequência fica balanceada)."""
        for key in sorted(self._down):
            if self.full:
                break
            self.events.append({"key": key, "down": False, "delay_ms": 0})
        self._down.clear()

    def clear(self) -> None:
        self.events.clear()
        self._down.clear()
        self._last_ms = None


# ---- gatilhos

def validate_trigger(t: dict) -> dict:
    """Valida um gatilho de Smart Action (ValueError com mensagem legível)."""
    if not isinstance(t, dict):
        raise ValueError("gatilho inválido")
    kind = t.get("type")
    if kind == "shortcut":
        keys = [str(k) for k in t.get("keys") or []]
        if not keys or not all(k.startswith("KEY_") for k in keys) or len(keys) > 5:
            raise ValueError("capture a combinação de teclas do gatilho")
        main = [k for k in keys if k not in MODIFIER_KEYS]
        if len(main) != 1:
            raise ValueError("o atalho precisa de exatamente uma tecla além dos modificadores")
        has_mod = len(main) != len(keys)
        free = re.fullmatch(r"KEY_F(1[3-9]|2[0-4])", main[0]) or main[0] in _MEDIA_KEYS
        if not has_mod and not free:
            raise ValueError("use ao menos um modificador (Ctrl, Alt, Super ou Shift), ou uma tecla F13–F24/mídia")
        return {"type": "shortcut", "keys": keys}
    if kind == "app":
        event, app_id = t.get("event"), str(t.get("app_id", "")).strip()
        if event not in APP_EVENTS:
            raise ValueError("evento de aplicativo inválido")
        if not app_id:
            raise ValueError("escolha o aplicativo do gatilho")
        return {"type": "app", "event": event, "app_id": app_id}
    if kind == "device":
        event, dev = t.get("event"), str(t.get("device_id", "*")).strip() or "*"
        if event not in DEVICE_EVENTS:
            raise ValueError("evento de dispositivo inválido")
        return {"type": "device", "event": event, "device_id": dev}
    raise ValueError(f"tipo de gatilho desconhecido: {kind}")


def describe_trigger(t: dict, name_of=lambda a: a, device_name=lambda d: d) -> str:
    kind = t.get("type")
    if kind == "shortcut":
        return pretty_keys(list(t.get("keys") or [])).replace(" + ", "+")
    if kind == "app":
        return f"{APP_EVENT_PHRASES.get(t.get('event'), 'Ao mudar')} {name_of(str(t.get('app_id', '')))}"
    if kind == "device":
        dev = t.get("device_id", "*")
        who = "um dispositivo" if dev in ("*", "") else device_name(dev)
        return ("Ao conectar " if t.get("event") == "connect" else "Ao desconectar ") + who
    if kind == "button":
        return "Botão " + str(t.get("label", ""))
    return "Gatilho"


def button_triggers(devices: dict | None, sid: str | None) -> list[dict]:
    """Atribuições (global e por aplicativo) que apontam para a Smart Action `sid`."""
    out: list[dict] = []
    if not sid:
        return out
    for dev_id, dev in (devices or {}).items():
        names = {int(c["cid"]): c.get("name", f"Controle {c['cid']}") for c in dev.get("controls") or []
                 if isinstance(c, dict) and "cid" in c}
        scopes = [("", dev.get("assignments") or {})] + [(app, (p or {}).get("assignments") or {})
                                                         for app, p in profiles_of(dev).items()]
        for app, assigns in scopes:
            for cid, act in assigns.items():
                if isinstance(act, dict) and act.get("type") == "smart_action" and act.get("id") == sid:
                    try:
                        c = int(cid)
                    except ValueError:
                        continue
                    out.append({"type": "button", "device_id": dev_id, "device_name": dev.get("name", dev_id),
                                "app_id": app, "cid": c, "label": names.get(c, f"Controle {c}")})
    return out


def smart_summary(sa: dict, name_of=lambda a: a, device_name=lambda d: d, buttons: list[dict] | None = None) -> str:
    """'Se Ctrl+Alt+P · Ao abrir Firefox → 4 ações'."""
    parts = [describe_trigger(t, name_of, device_name) for t in sa.get("triggers") or [] if isinstance(t, dict)]
    parts += [describe_trigger(b) for b in buttons or []]
    n = len(sa.get("steps") or [])
    acts = f"{n} ação" if n == 1 else f"{n} ações"
    cond = ("Se " + " · ".join(parts)) if parts else "Sem gatilho"
    return f"{cond} → {acts}"


def sort_smart_actions(sas: dict, mode: str = "recent") -> list[tuple[str, dict]]:
    items = [(sid, sa) for sid, sa in (sas or {}).items() if isinstance(sa, dict)]

    def name(kv):
        return str(kv[1].get("name", "")).lower()

    def stat(kv, key):
        return (kv[1].get("stats") or {}).get(key)
    items.sort(key=name)
    if mode == "alpha":
        return items
    if mode == "used":
        items.sort(key=lambda kv: int(stat(kv, "runs") or 0), reverse=True)
        return items
    items.sort(key=lambda kv: str(stat(kv, "modified") or stat(kv, "created") or ""), reverse=True)
    return items


def parse_save_result(text: str) -> tuple[str, list[str]]:
    """SaveSmartAction: id puro (serviço antigo) ou JSON {"id", "warnings"}."""
    text = (text or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            return text, []
        if isinstance(data, dict):
            w = data.get("warnings")
            warnings = [str(x) for x in w] if isinstance(w, list) else []
            return str(data.get("id", "")), warnings
    return text, []


def trigger_error_map(sa: dict) -> dict[int, str]:
    out = {}
    for e in (sa or {}).get("trigger_errors") or []:
        if isinstance(e, dict) and isinstance(e.get("index"), int):
            out[e["index"]] = str(e.get("message", "Gatilho indisponível"))
    return out


# ---- avisos de importação (ações que executam programas, abrem arquivos ou digitam)

def _short_argv(argv, n: int = 70) -> str:
    try:
        text = shlex.join(str(a) for a in argv)
    except TypeError:
        text = str(argv)
    return _short(text, n)


def _risky_target(target: str) -> bool:
    t = target.strip()
    return t.lower().startswith("file:") or t.startswith(("/", "~")) or (t.lower().endswith(".desktop") and "/" in t)


def risk_of_action(a) -> str | None:
    """Descrição curta se a ação executa programas, abre arquivos/.desktop ou digita/envia teclas."""
    if not isinstance(a, dict):
        return None
    t = a.get("type")
    if t == "command":
        return "Executa o comando: " + _short_argv(a.get("argv") or [])
    if t in ("open", "app") and (t == "open" or a.get("op") == "open"):
        target = str(a.get("target", ""))
        if _risky_target(target):
            return "Abre o arquivo ou programa: " + _short(target, 70)
        return None
    if t == "type_text":
        n = len(str(a.get("text", "")))
        return f"Digita um texto de {n} caractere{'s' if n != 1 else ''} no aplicativo em foco"
    if t == "key_sequence":
        n = len(a.get("events") or [])
        return f"Reproduz uma sequência de {n} evento{'s' if n != 1 else ''} de teclado"
    return None


def collect_risks(data, limit: int = 40) -> list[str]:
    """Varre qualquer estrutura JSON (backup, Smart Action, modelo) e lista as ações de risco."""
    found: list[str] = []

    def walk(x, depth=0):
        if len(found) >= limit or depth > 12:
            return
        if isinstance(x, dict):
            r = risk_of_action(x) if "type" in x and not (x.get("type") == "app" and "event" in x) else None
            if r and r not in found:
                found.append(r)
            for k, v in x.items():
                if k in ("argv", "events", "text", "keys"):
                    continue
                walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1)
    walk(data)
    return found


def validate_smart_import(text: str) -> dict:
    """Valida superficialmente um arquivo de Smart Action exportada."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError("O arquivo não é um JSON válido") from e
    if not isinstance(data, dict) or "openmacros_smart_action" not in data:
        raise ValueError("Este arquivo não parece ser uma Smart Action do OpenMacros+")
    if data.get("openmacros_smart_action") != 1:
        raise ValueError("Versão de Smart Action não suportada")
    return data


# ---- validação

def validate_step(step: dict) -> dict:
    """Valida um passo (Action ou delay); devolve cópia normalizada. ValueError se inválido."""
    if not isinstance(step, dict):
        raise ValueError("passo inválido")
    t = step.get("type")
    if t == "delay":
        try:
            ms = int(step.get("ms", 0))
        except (TypeError, ValueError) as e:
            raise ValueError("atraso inválido") from e
        if not SA_DELAY_MIN <= ms <= SA_DELAY_MAX:
            raise ValueError(f"o atraso deve ficar entre {SA_DELAY_MIN} e {SA_DELAY_MAX} ms")
        return {"type": "delay", "ms": ms}
    if t in ("gestures", "smart_action"):
        raise ValueError("este tipo de ação não pode ser usado dentro de uma Smart Action")
    kind, p = classify_action(step)
    if t not in (None, "default") and kind == "default":
        raise ValueError(f"tipo de passo desconhecido: {t}")
    if kind == "preset":
        return build_action("keys", keys=step["keys"])
    if kind == "mouse_button" or kind == "keys":
        return build_action(kind, **p)
    if kind == "command":
        return build_action("command", command=p["command"])
    if kind in ("media", "volume", "open", "type_text", "window", "ai_prompt", "change_host", "default", "disabled",
                "app", "system", "key_sequence"):
        return build_action(kind, **p)
    raise ValueError(f"passo inválido: {t}")


def validate_smart_action(sa: dict) -> dict:
    name = str(sa.get("name", "")).strip()
    if not name:
        raise ValueError("dê um nome à Smart Action")
    steps = [validate_step(s) for s in sa.get("steps") or []]
    if not steps:
        raise ValueError("adicione ao menos uma ação em “Então…”")
    if len(steps) > SA_MAX_STEPS:
        raise ValueError(f"no máximo {SA_MAX_STEPS} ações")
    triggers_in = sa.get("triggers") or []
    if len(triggers_in) > SA_MAX_TRIGGERS:
        raise ValueError(f"no máximo {SA_MAX_TRIGGERS} gatilhos")
    icon = sa.get("icon") if sa.get("icon") in SA_ICONS else SA_DEFAULT_ICON
    out = {"name": name[:SA_NAME_MAX], "icon": icon, "steps": steps}
    desc = " ".join(str(sa.get("description", "")).split())[:SA_DESCRIPTION_MAX]
    if desc or "description" in sa:
        out["description"] = desc
    if "triggers" in sa:
        out["triggers"] = [validate_trigger(t) for t in triggers_in]
    if "enabled" in sa:
        out["enabled"] = bool(sa["enabled"])
    if sa.get("id"):
        out["id"] = str(sa["id"])
    return out


def step_summary(step: dict) -> str:
    if step.get("type") == "delay":
        return f"Aguardar {step.get('ms', 0)} ms"
    return describe_action(step)


def move_step(steps: list, src: int, dst: int) -> list:
    """Move o item `src` para a posição `dst` (nova lista)."""
    if not (0 <= src < len(steps)) or not (0 <= dst < len(steps)):
        return list(steps)
    out = list(steps)
    out.insert(dst, out.pop(src))
    return out


def _t(id, name, icon, description, steps, triggers=None):
    d = {"id": id, "name": name, "icon": icon, "description": description, "steps": steps}
    if triggers:
        d["triggers"] = triggers
    return d


def _k(*keys):
    return {"type": "keys", "keys": list(keys)}


SMART_TEMPLATES: tuple[dict, ...] = (
    _t("work", "Modo de trabalho", "applications-engineering-symbolic",
       "Ativa o Não perturbe, para a música e mostra a área de trabalho limpa.",
       [{"type": "system", "op": "dnd_on"}, {"type": "media", "op": "stop"}, {"type": "system", "op": "show_desktop"}]),
    _t("meeting", "Modo reunião", "camera-video-symbolic",
       "Silencia o microfone e as notificações.",
       [{"type": "system", "op": "mic_mute"}, {"type": "system", "op": "dnd_on"}]),
    _t("relax", "Hora de relaxar", "weather-clear-night-symbolic",
       "Desativa o Não perturbe e começa a tocar a música.",
       [{"type": "system", "op": "dnd_off"}, {"type": "media", "op": "play_pause"}]),
    _t("brb", "Volto em breve", "system-lock-screen-symbolic",
       "Para a mídia, silencia o microfone e bloqueia a tela.",
       [{"type": "media", "op": "stop"}, {"type": "system", "op": "mic_mute"}, {"type": "delay", "ms": 300},
        {"type": "system", "op": "lock"}]),
    _t("search_web", "Pesquisar a seleção na web", "system-search-symbolic",
       "Copia o texto selecionado, abre o DuckDuckGo e cola na busca.",
       [_k("KEY_LEFTCTRL", "KEY_C"), {"type": "delay", "ms": 200}, {"type": "open", "target": "https://duckduckgo.com"},
        {"type": "delay", "ms": 2500}, _k("KEY_LEFTCTRL", "KEY_V"), {"type": "delay", "ms": 150}, _k("KEY_ENTER")]),
    _t("ask_ai", "Perguntar à IA sobre a seleção", "starred-symbolic",
       "Envia o texto selecionado a um assistente de IA com um prompt pronto.",
       [{"type": "ai_prompt", "service": "claude", "template": "Explique de forma simples: {selection}"}]),
    _t("my_sites", "Abrir meus sites ao abrir o navegador", "web-browser-symbolic",
       "Quando o navegador abrir, abre também os sites que você usa todo dia. Troque o aplicativo e os sites.",
       [{"type": "open", "target": "https://duckduckgo.com"}, {"type": "delay", "ms": 400},
        {"type": "open", "target": "https://en.wikipedia.org"}],
       [{"type": "app", "event": "open", "app_id": "firefox"}]),
    _t("update_project", "Atualizar projeto", "view-refresh-symbolic",
       "Roda git pull no terminal. Troque ~/projeto pela pasta do seu projeto.",
       [{"type": "command", "argv": ["x-terminal-emulator", "-e", "sh", "-c",
                                     "cd ~/projeto && git pull; printf 'Enter para fechar…'; read _"]}]),
    _t("pentest", "Pentest", "utilities-terminal-symbolic",
       "Abre o Burp Suite e um terminal e digita um comando (sem Enter).",
       [{"type": "open", "target": "burpsuite.desktop"}, {"type": "delay", "ms": 1500},
        {"type": "open", "target": "xfce4-terminal.desktop"}, {"type": "delay", "ms": 1200},
        {"type": "type_text", "text": "nmap -sV -T4 "}]),
    _t("area_clip", "Captura de área para a área de transferência", "camera-photo-symbolic",
       "Seleciona uma região da tela e copia a imagem. Requer o xfce4-screenshooter.",
       [{"type": "command", "argv": ["xfce4-screenshooter", "-r", "-c"]}]),
)


def smart_from_template(template_id: str) -> dict:
    """Cópia editável (sem id) de um modelo pronto."""
    for t in SMART_TEMPLATES:
        if t["id"] == template_id:
            out = {k: json.loads(json.dumps(v)) for k, v in t.items() if k != "id"}
            out.setdefault("triggers", [])
            return out
    raise ValueError(f"modelo desconhecido: {template_id}")
