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
        return {"type": "type_text", "text": text}
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
        return {"type": "ai_prompt", "service": service, "template": template}
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
    if t in ("open", "type_text", "window", "ai_prompt", "smart_action"):
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


def supported_tabs(device: dict) -> list[str]:
    tabs = []
    if any(is_configurable(c) for c in device.get("controls") or []):
        tabs.append("buttons")
    if any(k in (device.get("settings") or {}) for k in POINTER_SETTINGS):
        tabs.append("pointer")
    hosts = device.get("hosts")
    if hosts and int(hosts.get("count", 0)) > 0:
        tabs.append("easyswitch")
    tabs.append("about")
    return tabs


def friendly_error(message: str) -> str:
    """Remove o prefixo 'GDBus.Error:...' e traduz erros conhecidos."""
    m = re.match(r"^(?:GDBus\.Error:)?io\.github\.clique\.Error\.(\w+):\s*(.*)$", message.strip(), re.S)
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
    """Variáveis de cor do libadwaita para o tema claro/escuro do Clique."""
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

def action_sections(allow_gestures: bool = False, smart_actions: dict | None = None,
                    allow_smart: bool = True, steps: bool = False) -> list[tuple[str, list[tuple[str, str]]]]:
    """Seções do painel: [(título, [(item_id, rótulo)])]. item_id: 'default', 'gestures',
    'preset:<id>', 'media:<op>', 'volume:<op>', 'window', 'open', 'type_text', 'ai_prompt',
    'smart:<id>', 'smart_new', 'keys', 'mouse_button', 'command', 'change_host', 'disabled'."""
    def pr(*ids):
        return [(f"preset:{i}", PRESETS_BY_ID[i].label) for i in ids]
    rec = [] if steps else [("default", "Padrão")]
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
            ("type_text", "Digitar texto")] + pr("show_desktop", "screenshot")),
        ("IA", [("ai_prompt", "Perguntar à IA sobre a seleção")]),
    ]
    if allow_smart and not steps:
        sa = [(f"smart:{sid}", d.get("name", sid)) for sid, d in sorted((smart_actions or {}).items(),
                                                                       key=lambda kv: kv[1].get("name", "").lower())]
        out.append(("Smart Actions", sa + [("smart_new", "Criar Smart Action…")]))
    adv = [("keys", "Atalho de teclado"), ("mouse_button", "Botão do mouse"),
           ("command", "Executar comando"), ("change_host", "Trocar de computador")]
    if not steps:
        adv.append(("disabled", "Desativar"))
    out.append(("Avançado", adv))
    return out


PARAM_ITEMS = ("keys", "mouse_button", "command", "change_host", "window", "open", "type_text", "ai_prompt")


def item_id_for_action(action: dict | None) -> str:
    kind, p = classify_action(action)
    if kind == "preset":
        return f"preset:{p['preset']}"
    if kind in ("media", "volume"):
        return f"{kind}:{p['op']}"
    if kind == "smart_action":
        return f"smart:{p['id']}"
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
SA_DELAY_MIN, SA_DELAY_MAX = 10, 10000
SA_ICONS = ("system-run-symbolic", "weather-clear-symbolic", "media-playback-start-symbolic",
            "emblem-favorite-symbolic", "web-browser-symbolic", "utilities-terminal-symbolic",
            "audio-headphones-symbolic", "applications-engineering-symbolic", "user-home-symbolic",
            "starred-symbolic")
SA_DEFAULT_ICON = SA_ICONS[0]


def validate_step(step: dict) -> dict:
    """Valida um passo (Action ou delay); devolve cópia normalizada. ValueError se inválido."""
    if not isinstance(step, dict):
        raise ValueError("passo inválido")
    t = step.get("type")
    if t == "delay":
        ms = int(step.get("ms", 0))
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
    if kind in ("media", "volume", "open", "type_text", "window", "ai_prompt", "change_host", "default", "disabled"):
        return build_action(kind, **p)
    raise ValueError(f"passo inválido: {t}")


def validate_smart_action(sa: dict) -> dict:
    name = str(sa.get("name", "")).strip()
    if not name:
        raise ValueError("dê um nome à Smart Action")
    steps = [validate_step(s) for s in sa.get("steps") or []]
    if not steps:
        raise ValueError("adicione ao menos um passo")
    if len(steps) > SA_MAX_STEPS:
        raise ValueError(f"no máximo {SA_MAX_STEPS} passos")
    icon = sa.get("icon") if sa.get("icon") in SA_ICONS else SA_DEFAULT_ICON
    out = {"name": name[:60], "icon": icon, "steps": steps}
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


SMART_TEMPLATES: tuple[dict, ...] = (
    {"id": "focus", "name": "Modo foco", "icon": "weather-clear-symbolic",
     "description": "Abre o Obsidian e começa a tocar o Spotify.",
     "steps": [{"type": "open", "target": "obsidian.desktop"}, {"type": "open", "target": "spotify.desktop"},
               {"type": "delay", "ms": 2500}, {"type": "media", "op": "play_pause", "player": "spotify"}]},
    {"id": "research", "name": "Pesquisa", "icon": "web-browser-symbolic",
     "description": "Abre três sites de pesquisa.",
     "steps": [{"type": "open", "target": "https://duckduckgo.com"}, {"type": "delay", "ms": 400},
               {"type": "open", "target": "https://scholar.google.com"}, {"type": "delay", "ms": 400},
               {"type": "open", "target": "https://en.wikipedia.org"}]},
    {"id": "pentest", "name": "Pentest", "icon": "utilities-terminal-symbolic",
     "description": "Abre o Burp Suite e um terminal e digita um comando (sem Enter).",
     "steps": [{"type": "open", "target": "burpsuite.desktop"}, {"type": "delay", "ms": 1500},
               {"type": "open", "target": "xfce4-terminal.desktop"}, {"type": "delay", "ms": 1200},
               {"type": "type_text", "text": "nmap -sV -T4 "}]},
)


def smart_from_template(template_id: str) -> dict:
    """Cópia editável (sem id) de um modelo pronto."""
    for t in SMART_TEMPLATES:
        if t["id"] == template_id:
            return {"name": t["name"], "icon": t["icon"], "steps": json.loads(json.dumps(t["steps"]))}
    raise ValueError(f"modelo desconhecido: {template_id}")
