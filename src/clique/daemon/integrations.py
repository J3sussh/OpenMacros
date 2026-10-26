"""Backends das ações nativas (MPRIS, volume, abrir, janelas EWMH, seleção). Todos injetáveis."""

from __future__ import annotations

import logging
import shutil
import subprocess
from urllib.parse import quote

log = logging.getLogger(__name__)

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_METHODS = {"play_pause": "PlayPause", "next": "Next", "previous": "Previous", "stop": "Stop"}
MEDIA_FALLBACK_KEYS = {"play_pause": "KEY_PLAYPAUSE", "next": "KEY_NEXTSONG",
                       "previous": "KEY_PREVIOUSSONG", "stop": "KEY_STOPCD"}


# ----------------------------------------------------------------- MPRIS
def pick_player(names: list[str], statuses: dict[str, str], wanted: str | None) -> str | None:
    """Player pelo nome (case-insensitive); senão o que está tocando; senão o primeiro."""
    if not names:
        return None
    if wanted:
        w = wanted.lower()
        for n in names:
            short = n[len(MPRIS_PREFIX):].split(".")[0].lower()
            if short == w:
                return n
        return None  # pediu um player específico e ele não existe
    for n in names:
        if statuses.get(n) == "Playing":
            return n
    return names[0]


class MprisController:
    """Fala MPRIS pelo barramento de sessão (Gio). `list_names/status/call` são sobrescritíveis."""

    def __init__(self, timeout_ms: int = 500):
        self.timeout_ms = timeout_ms

    def _bus(self):
        from gi.repository import Gio
        return Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def list_names(self) -> list[str]:
        from gi.repository import Gio, GLib
        r = self._bus().call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                  "ListNames", None, GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE,
                                  self.timeout_ms, None)
        return sorted(n for n in r.unpack()[0] if n.startswith(MPRIS_PREFIX))

    def status(self, name: str) -> str:
        from gi.repository import Gio, GLib
        r = self._bus().call_sync(name, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Get",
                                  GLib.Variant("(ss)", ("org.mpris.MediaPlayer2.Player", "PlaybackStatus")),
                                  None, Gio.DBusCallFlags.NONE, self.timeout_ms, None)
        return str(r.unpack()[0])

    def call(self, name: str, method: str) -> None:
        from gi.repository import Gio
        self._bus().call_sync(name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", method,
                              None, None, Gio.DBusCallFlags.NONE, self.timeout_ms, None)

    def run(self, op: str, player: str | None = None) -> bool:
        """True se um player recebeu o comando; False => usar o fallback de teclas."""
        try:
            names = self.list_names()
            statuses = {}
            if not player:
                for n in names:
                    try:
                        statuses[n] = self.status(n)
                    except Exception:
                        pass
            target = pick_player(names, statuses, player)
            if not target:
                return False
            self.call(target, MPRIS_METHODS[op])
            return True
        except Exception as e:
            log.info("MPRIS indisponível (%s)", e)
            return False


# ----------------------------------------------------------------- volume
def _run(argv: list[str]) -> bool:
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=1.5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class VolumeController:
    def __init__(self, runner=_run, which=shutil.which):
        self.runner, self.which = runner, which

    @staticmethod
    def pactl_cmd(op: str, step: int) -> list[str]:
        if op == "mute":
            return ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]
        return ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{'+' if op == 'up' else '-'}{step}%"]

    @staticmethod
    def wpctl_cmd(op: str, step: int) -> list[str]:
        if op == "mute":
            return ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]
        return ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{step}%{'+' if op == 'up' else '-'}"]

    def run(self, op: str, step: int = 5) -> bool:
        for tool, build in (("pactl", self.pactl_cmd), ("wpctl", self.wpctl_cmd)):
            if self.which(tool) and self.runner(build(op, step)):
                return True
        return False


# ----------------------------------------------------------------- abrir
class Opener:
    def open_uri(self, uri: str) -> bool:
        exe = shutil.which("xdg-open")
        if not exe:
            return False
        subprocess.Popen([exe, uri], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True

    def launch_desktop(self, target: str) -> bool:
        from gi.repository import Gio
        info = (Gio.DesktopAppInfo.new_from_filename(target) if target.startswith("/")
                else Gio.DesktopAppInfo.new(target))
        return bool(info and info.launch([], None))


def desktop_exists(target: str) -> bool:
    import os
    if target.startswith("/"):
        return os.path.isfile(target)
    try:
        from gi.repository import Gio
        return Gio.DesktopAppInfo.new(target) is not None
    except Exception:
        return False


# ----------------------------------------------------------------- digitação (layout US)
_SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
            "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\", ":": ";", '"': "'", "<": ",", ">": ".",
            "?": "/", "~": "`"}
_PLAIN = {"-": "MINUS", "=": "EQUAL", "[": "LEFTBRACE", "]": "RIGHTBRACE", "\\": "BACKSLASH", ";": "SEMICOLON",
          "'": "APOSTROPHE", ",": "COMMA", ".": "DOT", "/": "SLASH", "`": "GRAVE", " ": "SPACE",
          "\n": "ENTER", "\t": "TAB"}


def text_to_keys(text: str) -> tuple[list[tuple[str, bool]], int]:
    """Texto -> [(KEY_*, shift)] no layout US; devolve também quantos caracteres foram ignorados."""
    out: list[tuple[str, bool]] = []
    skipped = 0
    for ch in text:
        if ch.isascii() and ch.isalpha():
            out.append((f"KEY_{ch.upper()}", ch.isupper()))
        elif ch.isascii() and ch.isdigit():
            out.append((f"KEY_{ch}", False))
        elif ch in _SHIFTED:
            base = _SHIFTED[ch]
            name = base if base.isdigit() else _PLAIN[base]
            out.append((f"KEY_{name}", True))
        elif ch in _PLAIN:
            out.append((f"KEY_{_PLAIN[ch]}", False))
        else:
            skipped += 1
    if skipped:
        log.warning("type_text: %d caractere(s) sem mapeamento foram ignorados", skipped)
    return out, skipped


# ----------------------------------------------------------------- janelas (EWMH)
def pick_window(stack: list[int], active: int, op: str) -> int | None:
    """Alvo de next/previous na _NET_CLIENT_LIST_STACKING (de baixo para cima).
    A janela ativada vai ao topo, então 'next' percorre por recência e 'previous' alterna."""
    if len(stack) < 2:
        return None
    idx = stack.index(active) if active in stack else len(stack) - 1
    return stack[(idx + 1) % len(stack)] if op == "next" else stack[(idx - 1) % len(stack)]


class XlibEwmh:
    """E/S EWMH com python-xlib (conexão própria e preguiçosa)."""

    def __init__(self):
        self.d = None

    def _display(self):
        if self.d is None:
            from Xlib import display
            self.d = display.Display()
        return self.d

    def _atom(self, name):
        return self._display().intern_atom(name)

    def _root(self):
        return self._display().screen().root

    def active_window(self) -> int:
        from Xlib import X
        p = self._root().get_full_property(self._atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
        return int(p.value[0]) if p is not None and len(p.value) else 0

    def client_list_stacking(self) -> list[int]:
        from Xlib import X
        p = self._root().get_full_property(self._atom("_NET_CLIENT_LIST_STACKING"), X.AnyPropertyType)
        return [int(v) for v in p.value] if p is not None else []

    def is_normal(self, wid: int) -> bool:
        """Janela comum (exclui docks/desktop e skip-taskbar/hidden)."""
        from Xlib import X, error
        try:
            w = self._display().create_resource_object("window", wid)
            t = w.get_full_property(self._atom("_NET_WM_WINDOW_TYPE"), X.AnyPropertyType)
            if t is not None and list(t.value) and self._atom("_NET_WM_WINDOW_TYPE_NORMAL") not in list(t.value):
                return False
            s = w.get_full_property(self._atom("_NET_WM_STATE"), X.AnyPropertyType)
            bad = {self._atom("_NET_WM_STATE_SKIP_TASKBAR"), self._atom("_NET_WM_STATE_HIDDEN")}
            return not (s is not None and bad & set(s.value))
        except error.XError:
            return False

    def client_message(self, wid: int, atom_name: str, data: list[int]) -> None:
        from Xlib import X, protocol
        d = self._display()
        win = d.create_resource_object("window", wid)
        ev = protocol.event.ClientMessage(window=win, client_type=self._atom(atom_name),
                                          data=(32, (list(data) + [0] * 5)[:5]))
        self._root().send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        d.flush()
        d.sync()

    def atom_id(self, name: str) -> int:
        return self._atom(name)


class WindowController:
    def __init__(self, ewmh=None):
        self._ewmh = ewmh

    @property
    def ewmh(self):
        if self._ewmh is None:
            self._ewmh = XlibEwmh()
        return self._ewmh

    def run(self, op: str) -> bool:
        try:
            e = self.ewmh
            if op in ("next", "previous"):
                stack = [w for w in e.client_list_stacking() if e.is_normal(w)]
                target = pick_window(stack, e.active_window(), op)
                if target is None:
                    return False
                e.client_message(target, "_NET_ACTIVE_WINDOW", [2, 0, 0])
                return True
            win = e.active_window()
            if not win:
                return False
            if op == "close":
                e.client_message(win, "_NET_CLOSE_WINDOW", [0, 2])
            elif op == "minimize":
                e.client_message(win, "WM_CHANGE_STATE", [3])  # IconicState (ICCCM)
            elif op == "maximize":
                e.client_message(win, "_NET_WM_STATE", [2, e.atom_id("_NET_WM_STATE_MAXIMIZED_VERT"),
                                                        e.atom_id("_NET_WM_STATE_MAXIMIZED_HORZ"), 2])
            elif op == "fullscreen":
                e.client_message(win, "_NET_WM_STATE", [2, e.atom_id("_NET_WM_STATE_FULLSCREEN"), 0, 2])
            else:
                return False
            return True
        except Exception as ex:
            log.warning("ação de janela '%s' falhou: %s", op, ex)
            return False


# ----------------------------------------------------------------- IA / seleção
SELECTION_LIMIT = 8 * 1024
AI_URLS = {
    "claude": "https://claude.ai/new?q=",
    "chatgpt": "https://chatgpt.com/?q=",
    "perplexity": "https://www.perplexity.ai/search?q=",
}
GEMINI_URL = "https://gemini.google.com/app"
MAX_PROMPT_CHARS = 6000


class Selection:
    def read_primary(self) -> str:
        exe = shutil.which("xclip")
        if not exe:
            return ""
        try:
            r = subprocess.run([exe, "-o", "-selection", "primary"], stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=0.3)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if r.returncode != 0:
            return ""
        return r.stdout[:SELECTION_LIMIT].decode("utf-8", "ignore")

    def write_clipboard(self, text: str) -> bool:
        exe = shutil.which("xclip")
        if not exe:
            return False
        try:
            p = subprocess.Popen([exe, "-selection", "clipboard"], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            p.stdin.write(text.encode("utf-8"))
            p.stdin.close()
            return True
        except OSError:
            return False


def build_ai_request(service: str, template: str, selection: str) -> tuple[str, str | None]:
    """(url, texto para o CLIPBOARD ou None)."""
    prompt = template.replace("{selection}", selection)[:MAX_PROMPT_CHARS]
    if service == "gemini":
        return GEMINI_URL, prompt
    return AI_URLS[service] + quote(prompt, safe=""), None
