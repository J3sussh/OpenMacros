"""Backends das ações nativas (MPRIS, volume, abrir, janelas EWMH, seleção). Todos injetáveis."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
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

    def launch_app(self, target: str) -> bool:
        """`firefox.desktop`, caminho de .desktop ou nome simples (`firefox`: id do .desktop, StartupWMClass,
        executável do .desktop; por último um executável no PATH)."""
        if target.endswith(".desktop"):
            return self.launch_desktop(target)
        info = find_desktop_info(target)
        if info is not None:
            return bool(info.launch([], None))
        exe = shutil.which(target)
        if not exe:
            return False
        subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True


def _desktop_info(target: str):
    from gi.repository import Gio
    if target.startswith("/"):
        return Gio.DesktopAppInfo.new_from_filename(target)
    return Gio.DesktopAppInfo.new(target)


def find_desktop_info(name: str):
    """Gio.DesktopAppInfo para um nome simples; None se não achar."""
    try:
        from gi.repository import Gio
        info = Gio.DesktopAppInfo.new(f"{name}.desktop")
        if info is not None:
            return info
        low = name.lower()
        for cand in Gio.AppInfo.get_all():
            ident = (cand.get_id() or "").removesuffix(".desktop").lower()
            wm = (getattr(cand, "get_startup_wm_class", lambda: None)() or "").lower()
            exe = os.path.basename(cand.get_executable() or "").lower()
            if low in (ident, wm, exe) and cand.should_show():
                return cand
    except Exception as e:
        log.debug("busca de .desktop para %r falhou: %s", name, e)
    return None


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

    def client_list(self) -> list[int]:
        from Xlib import X
        p = self._root().get_full_property(self._atom("_NET_CLIENT_LIST"), X.AnyPropertyType)
        return [int(v) for v in p.value] if p is not None else []

    def window_app(self, wid: int) -> dict:
        """ActiveApp da janela ({} se sumiu): mesma regra de app_id do FocusWatcher."""
        from Xlib import error
        from .focus import read_window_app
        try:
            return read_window_app(self._display(), wid)
        except error.XError:
            return {}

    def toggle_show_desktop(self) -> None:
        from Xlib import X
        p = self._root().get_full_property(self._atom("_NET_SHOWING_DESKTOP"), X.AnyPropertyType)
        showing = bool(p is not None and len(p.value) and p.value[0])
        self.client_message(self._root().id, "_NET_SHOWING_DESKTOP", [0 if showing else 1])


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


# ----------------------------------------------------------------- aplicativos (ação `app`)
def app_ids_for(target: str) -> set[str]:
    """app_ids (minúsculos) que uma janela do alvo pode ter: id do .desktop, último trecho de um id
    reverso (org.mozilla.firefox -> firefox), StartupWMClass e executável do .desktop."""
    base = os.path.basename(target).removesuffix(".desktop").lower()
    ids = {base}
    if "." in base:
        ids.add(base.rsplit(".", 1)[-1])
    try:
        info = _desktop_info(target) if target.endswith(".desktop") else find_desktop_info(target)
        if info is not None:
            wm = (info.get_startup_wm_class() or "").lower()
            exe = os.path.basename(info.get_executable() or "").lower()
            ids |= {x for x in (wm, exe) if x}
    except Exception:
        pass
    return ids


class AppController:
    """open/close/focus de aplicativos: abrir via .desktop/Gio, fechar/focar via EWMH (_NET_CLIENT_LIST)."""

    def __init__(self, opener=None, ewmh=None, resolve=app_ids_for):
        self.opener = opener if opener is not None else Opener()
        self._ewmh = ewmh
        self.resolve = resolve

    @property
    def ewmh(self):
        if self._ewmh is None:
            self._ewmh = XlibEwmh()
        return self._ewmh

    def _matching(self, target: str) -> list[int]:
        """Janelas do app, da mais antiga para a mais recente (ordem de empilhamento)."""
        e = self.ewmh
        ids = self.resolve(target)
        stack = e.client_list_stacking() or e.client_list()
        out = []
        for wid in stack:
            app = e.window_app(wid)
            if app and (app.get("app_id") in ids or (app.get("exe") or "").lower() in ids) and e.is_normal(wid):
                out.append(wid)
        return out

    def run(self, op: str, target: str) -> bool:
        try:
            if op == "open":
                return self._open(target)
            wins = self._matching(target)
            if op == "close":
                for w in wins:
                    self.ewmh.client_message(w, "_NET_CLOSE_WINDOW", [0, 2])
                return bool(wins)
            if op == "focus":
                if not wins:
                    return self._open(target)  # sem janela: abre
                self.ewmh.client_message(wins[-1], "_NET_ACTIVE_WINDOW", [2, 0, 0])
                return True
        except Exception as ex:
            log.warning("ação de app '%s %s' falhou: %s", op, target, ex)
        return False

    def _open(self, target: str) -> bool:
        launch = getattr(self.opener, "launch_app", None) or self.opener.launch_desktop
        return bool(launch(target))


# ----------------------------------------------------------------- sistema (ação `system`)
def _exec(argv: list[str], wait: bool = True, timeout: float = 2.0) -> bool:
    try:
        if not wait:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _exec_out(argv: list[str], timeout: float = 1.5) -> str | None:
    try:
        r = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


class SystemController:
    """Operações de sistema por ferramentas externas (todas injetáveis: nada roda de verdade nos testes)."""

    NOTIFYD = ["-c", "xfce4-notifyd", "-p", "/do-not-disturb"]
    # op -> [(argv, esperar_saída)] tentados em ordem até um funcionar
    COMMANDS = {
        "lock": [(["loginctl", "lock-session"], True), (["xflock4"], True), (["xdg-screensaver", "lock"], True)],
        "screenshot": [(["xfce4-screenshooter", "-f"], False), (["gnome-screenshot"], False)],
        "screenshot_area": [(["xfce4-screenshooter", "-r"], False), (["gnome-screenshot", "-a"], False)],
        "suspend": [(["systemctl", "suspend"], False)],
        "mic_mute": [(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"], True),
                     (["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"], True)],
        "empty_trash": [(["gio", "trash", "--empty"], False), (["trash-empty"], False)],
    }

    def __init__(self, runner=_exec, capture=_exec_out, which=shutil.which, ewmh=None):
        self.runner, self.capture, self.which = runner, capture, which
        self._ewmh = ewmh

    @property
    def ewmh(self):
        if self._ewmh is None:
            self._ewmh = XlibEwmh()
        return self._ewmh

    def run(self, op: str) -> bool:
        try:
            if op == "show_desktop":
                self.ewmh.toggle_show_desktop()
                return True
            if op in ("dnd_on", "dnd_off", "dnd_toggle"):
                return self._dnd(op)
            for argv, wait in self.COMMANDS.get(op, []):
                if self.which(argv[0]) and self.runner(argv, wait):
                    return True
        except Exception as ex:
            log.warning("ação de sistema '%s' falhou: %s", op, ex)
        return False

    def _dnd(self, op: str) -> bool:
        exe = self.which("xfconf-query")
        if not exe:
            log.info("não perturbe: só o XFCE (xfconf-query) é suportado")
            return False
        if op == "dnd_toggle":
            cur = self.capture([exe, *self.NOTIFYD])
            on = not (cur or "").strip().lower() == "true"
        else:
            on = op == "dnd_on"
        return self.runner([exe, *self.NOTIFYD, "-n", "-t", "bool", "-s", "true" if on else "false"], True)


# ----------------------------------------------------------------- terminais
TERMINAL_APP_IDS = frozenset({
    "xfce4-terminal", "qterminal", "gnome-terminal-server", "gnome-terminal", "kitty", "alacritty", "konsole",
    "terminator", "xterm", "uxterm", "urxvt", "tilix", "foot", "wezterm", "wezterm-gui", "lxterminal",
    "mate-terminal", "terminology", "st", "st-256color", "sakura", "guake", "tilda", "yakuake", "hyper",
    "cool-retro-term", "ptyxis", "blackbox", "ghostty", "com.mitchellh.ghostty", "org.wezfurlong.wezterm",
    "xfce4-terminal-wrapper", "io.elementary.terminal", "deepin-terminal", "rxvt",
})


def is_terminal(app_id: str) -> bool:
    return (app_id or "").lower() in TERMINAL_APP_IDS


# ----------------------------------------------------------------- IA / seleção / CLIPBOARD
SELECTION_LIMIT = 8 * 1024
AI_URLS = {
    "claude": "https://claude.ai/new?q=",
    "chatgpt": "https://chatgpt.com/?q=",
    "perplexity": "https://www.perplexity.ai/search?q=",
}
AI_HOME_URLS = {
    "claude": "https://claude.ai/new",
    "chatgpt": "https://chatgpt.com/",
    "perplexity": "https://www.perplexity.ai/",
    "gemini": "https://gemini.google.com/app",
}
GEMINI_URL = AI_HOME_URLS["gemini"]
MAX_PROMPT_CHARS = 6000
CLIP_TIMEOUT = 0.3
CLIP_RESTORE_MS = 600
CLIPBOARD_LIMIT = 1024 * 1024  # salvar/restaurar o CLIPBOARD: sem o corte de 8 KiB da seleção
TEXT_TARGETS = ("UTF8_STRING", "text/plain;charset=utf-8", "text/plain")


def _run_quiet(argv: list[str]) -> bool:
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=CLIP_TIMEOUT).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _wayland() -> bool:
    import os
    return bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("DISPLAY")


def _capture_bytes(argv: list[str], limit: int, *, truncate: bool, timeout: float = CLIP_TIMEOUT) -> bytes | None:
    """Saída de `argv` (stdout) lida com limite de memória e prazo total.

    `truncate=True`: corta em `limit` bytes (seleção PRIMARY, só para montar um prompt).
    `truncate=False`: passou de `limit` => None + log (nunca devolve um texto cortado, que seria
    gravado de volta no CLIPBOARD como se fosse o original). Erro, código != 0 ou prazo => None."""
    import select
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    buf = bytearray()
    cut = False
    ok = False
    try:
        fd = p.stdout.fileno()
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                return None
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            buf += chunk
            if len(buf) > limit:
                if not truncate:
                    log.warning("CLIPBOARD maior que %d KiB: não será salvo/restaurado", limit // 1024)
                    return None
                cut = True
                break
        if cut:
            ok = True
        else:
            try:
                ok = p.wait(timeout=max(0.05, deadline - time.monotonic())) == 0
            except subprocess.TimeoutExpired:
                return None
    except OSError:
        return None
    finally:
        if p.poll() is None:
            p.kill()
        p.stdout.close()
        try:
            p.wait(timeout=1)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass
    return bytes(buf[:limit]) if ok else None


class Selection:
    """PRIMARY (leitura) e CLIPBOARD (leitura/escrita) via xclip/xsel (X11) ou wl-clipboard (Wayland)."""

    def __init__(self, which=shutil.which, wayland=_wayland):
        self.which, self.wayland = which, wayland

    def _capture(self, argv: list[str], limit: int = SELECTION_LIMIT, truncate: bool = True) -> str | None:
        raw = _capture_bytes(argv, limit, truncate=truncate)
        return None if raw is None else raw.decode("utf-8", "ignore")

    def read_primary(self) -> str:
        if self.wayland() and (exe := self.which("wl-paste")):
            return self._capture([exe, "--primary", "--no-newline"]) or ""
        if exe := self.which("xclip"):
            return self._capture([exe, "-o", "-selection", "primary"]) or ""
        if exe := self.which("xsel"):
            return self._capture([exe, "-po"]) or ""
        return ""

    def _clip_text(self, argv: list[str]) -> str | None:
        """Texto inteiro (até CLIPBOARD_LIMIT) para salvar/restaurar: sem o corte de 8 KiB da PRIMARY."""
        raw = _capture_bytes(argv, CLIPBOARD_LIMIT, truncate=False)
        if raw is None:
            return None
        try:
            return raw.decode("utf-8") or None
        except UnicodeDecodeError:
            return None  # não é texto UTF-8: não dá para restaurar fielmente

    def read_clipboard(self) -> str | None:
        """Texto atual do CLIPBOARD (até 1 MiB); None se vazio, não-texto, grande demais, sem ferramenta ou
        timeout. Com xclip consulta TARGETS antes: sem UTF8_STRING/text/plain não lê (nem tenta o xsel)."""
        if self.wayland() and (exe := self.which("wl-paste")):
            return self._clip_text([exe, "--no-newline", "--type", "text"])
        if exe := self.which("xclip"):
            targets = self._capture([exe, "-o", "-selection", "clipboard", "-t", "TARGETS"], 16 * 1024)
            if targets is None:
                return None  # o xclip diz que não há alvo disponível: o xsel diria o mesmo (ou leria lixo)
            names = set(targets.split())
            pick = next((t for t in TEXT_TARGETS if t in names), None)
            if pick is None:
                return None
            return self._clip_text([exe, "-o", "-selection", "clipboard", "-t", pick])
        if exe := self.which("xsel"):
            return self._clip_text([exe, "-bo"])
        return None

    def clear_clipboard(self) -> bool:
        """Esvazia o CLIPBOARD (para não deixar um texto colado, possivelmente uma senha, lá)."""
        if self.wayland() and (exe := self.which("wl-copy")):
            return _run_quiet([exe, "--clear"])
        if exe := self.which("xsel"):
            if _run_quiet([exe, "-bc"]):
                return True
        if self.which("xclip"):
            return self.write_clipboard("")  # xclip sem entrada define uma seleção vazia
        return False

    def write_clipboard(self, text: str) -> bool:
        """Coloca `text` no CLIPBOARD. As ferramentas fazem fork para segurar a seleção; esperamos o pai
        sair (<= 300 ms) para o Ctrl+V seguinte já encontrar o dono da seleção."""
        if self.wayland() and (exe := self.which("wl-copy")):
            cmds = [[exe]]
        else:
            cmds = []
            if exe := self.which("xclip"):
                cmds.append([exe, "-selection", "clipboard", "-i"])
            if exe := self.which("xsel"):
                cmds.append([exe, "-bi"])
        for argv in cmds:
            try:
                p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                p.stdin.write(text.encode("utf-8"))
                p.stdin.close()
            except OSError:
                continue
            try:
                if p.wait(timeout=CLIP_TIMEOUT) != 0:
                    continue
            except subprocess.TimeoutExpired:
                pass  # ainda segurando a seleção: provavelmente ok
            return True
        return False


def build_ai_request(service: str, template: str, selection: str, delivery: str = "clipboard"
                     ) -> tuple[str, str | None]:
    """(url, texto para o CLIPBOARD ou None).

    `clipboard` (padrão): abre só a página inicial do serviço e o prompt vai ao CLIPBOARD.
    `url`: prompt em `?q=` (o histórico do navegador guarda); Gemini não tem parâmetro, então sempre clipboard.
    """
    prompt = template.replace("{selection}", selection)[:MAX_PROMPT_CHARS]
    if delivery != "url" or service == "gemini":
        return AI_HOME_URLS[service], prompt
    return AI_URLS[service] + quote(prompt, safe=""), None
