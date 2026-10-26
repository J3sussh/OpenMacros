"""Validação e execução de ações (uinput via evdev; subprocess; MPRIS; EWMH; Smart Actions)."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from typing import Callable
from urllib.parse import urlparse

from ..hidpp.cids import CID_TO_BUTTON, CID_TO_REL
from . import integrations as integ
from .gestures import ActionEvent

log = logging.getLogger(__name__)

SIMPLE_TYPES = {"default", "disabled", "keys", "mouse_button", "remap", "command", "change_host"}
NATIVE_TYPES = {"media", "volume", "open", "type_text", "window", "ai_prompt", "smart_action"}
DIRECTIONS = ("click", "up", "down", "left", "right")
MAX_TEXT = 2000
MAX_STEPS = 32
MIN_DELAY, MAX_DELAY = 10, 10000
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_PLAYER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _ecodes():
    from evdev import ecodes
    return ecodes


def key_code(name: str) -> int:
    if not isinstance(name, str) or not (name.startswith("KEY_") or name.startswith("BTN_")):
        raise ValueError(f"tecla inválida: {name!r}")
    code = _ecodes().ecodes.get(name)
    if not isinstance(code, int):
        raise ValueError(f"tecla desconhecida: {name!r}")
    return code


def _check_executable(exe: str) -> None:
    if os.path.isabs(exe):
        ok = os.path.isfile(exe) and os.access(exe, os.X_OK)
    else:
        ok = shutil.which(exe) is not None
    if not ok:
        raise ValueError(f"programa não encontrado ou não executável: {exe!r}")


def _int_in(v, lo, hi, what) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ValueError(f"'{what}' deve ser inteiro entre {lo} e {hi}")
    return v


def _check_open_target(t, check: bool) -> str:
    if not isinstance(t, str) or not t or len(t) > 2048 or any(ord(c) < 32 for c in t):
        raise ValueError("'target' inválido")
    if t.endswith(".desktop"):
        if check and not integ.desktop_exists(t):
            raise ValueError(f"arquivo .desktop não encontrado: {t!r}")
        return t
    u = urlparse(t)
    if u.scheme not in ("http", "https", "file"):
        raise ValueError("esquema não permitido (use http, https, file ou um .desktop)")
    if u.scheme in ("http", "https") and not u.netloc:
        raise ValueError("URL sem host")
    if u.scheme == "file" and not u.path:
        raise ValueError("file:// sem caminho")
    return t


def validate_action(a, *, nested: bool = False, check_command: bool = True, in_macro: bool = False) -> dict:
    """Valida o JSON de Action; retorna o dict normalizado ou levanta ValueError.
    `in_macro`: passo de Smart Action (aceita `delay`; proíbe `smart_action`)."""
    if not isinstance(a, dict) or "type" not in a:
        raise ValueError("ação deve ser um objeto com 'type'")
    t = a["type"]
    if t in ("default", "disabled"):
        return {"type": t}
    if t == "delay":
        if not in_macro:
            raise ValueError("'delay' só existe dentro de Smart Actions")
        return {"type": t, "ms": _int_in(a.get("ms"), MIN_DELAY, MAX_DELAY, "ms")}
    if t == "keys":
        keys = a.get("keys")
        if not isinstance(keys, list) or not keys or len(keys) > 8:
            raise ValueError("'keys' deve ser uma lista de 1 a 8 teclas")
        for k in keys:
            key_code(k)
        return {"type": t, "keys": list(keys)}
    if t == "mouse_button":
        key_code(a.get("button"))
        if not a["button"].startswith("BTN_"):
            raise ValueError("'button' deve ser BTN_*")
        return {"type": t, "button": a["button"]}
    if t == "remap":
        return {"type": t, "cid": _int_in(a.get("cid"), 1, 0xFFFF, "cid")}
    if t == "command":
        argv = a.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            raise ValueError("'argv' deve ser lista não vazia de strings")
        if check_command:
            _check_executable(argv[0])
        return {"type": t, "argv": list(argv)}
    if t == "change_host":
        return {"type": t, "host": _int_in(a.get("host"), 0, 14, "host")}
    if t == "media":
        if a.get("op") not in integ.MPRIS_METHODS:
            raise ValueError("'op' de media inválido")
        out = {"type": t, "op": a["op"]}
        if a.get("player"):
            if not isinstance(a["player"], str) or not _PLAYER_RE.match(a["player"]):
                raise ValueError("'player' inválido")
            out["player"] = a["player"]
        return out
    if t == "volume":
        if a.get("op") not in ("up", "down", "mute"):
            raise ValueError("'op' de volume inválido")
        return {"type": t, "op": a["op"], "step": _int_in(a.get("step", 5), 1, 50, "step")}
    if t == "open":
        return {"type": t, "target": _check_open_target(a.get("target"), check_command)}
    if t == "type_text":
        text = a.get("text")
        if not isinstance(text, str) or not text or len(text) > MAX_TEXT:
            raise ValueError(f"'text' deve ter de 1 a {MAX_TEXT} caracteres")
        return {"type": t, "text": text}
    if t == "window":
        if a.get("op") not in ("close", "minimize", "maximize", "fullscreen", "next", "previous"):
            raise ValueError("'op' de window inválido")
        return {"type": t, "op": a["op"]}
    if t == "ai_prompt":
        if a.get("service") not in ("claude", "chatgpt", "perplexity", "gemini"):
            raise ValueError("'service' inválido")
        tpl = a.get("template", "Explique: {selection}")
        if not isinstance(tpl, str) or not tpl or len(tpl) > MAX_TEXT:
            raise ValueError("'template' inválido")
        return {"type": t, "service": a["service"], "template": tpl}
    if t == "smart_action":
        if in_macro:
            raise ValueError("Smart Actions não podem conter outras Smart Actions")
        if not isinstance(a.get("id"), str) or not _ID_RE.match(a["id"]):
            raise ValueError("'id' de Smart Action inválido")
        return {"type": t, "id": a["id"]}
    if t == "gestures":
        if nested:
            raise ValueError("gestos não podem ser aninhados")
        out: dict = {"type": t}
        for d in DIRECTIONS:
            out[d] = (validate_action(a[d], nested=True, check_command=check_command) if d in a
                      else {"type": "default" if d == "click" else "disabled"})
        out["threshold"] = _int_in(a.get("threshold", 50), 1, 2000, "threshold")
        return out
    raise ValueError(f"tipo de ação desconhecido: {t!r}")


def validate_smart_action(obj, *, check_command: bool = True) -> dict:
    """{"id"?, "name", "icon"?, "steps": [Action|delay]} -> normalizado."""
    if not isinstance(obj, dict):
        raise ValueError("Smart Action deve ser um objeto")
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError("'name' deve ter de 1 a 80 caracteres")
    icon = obj.get("icon", "")
    if not isinstance(icon, str) or len(icon) > 80:
        raise ValueError("'icon' inválido")
    steps = obj.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"'steps' deve ter de 1 a {MAX_STEPS} passos")
    out = {"name": name.strip(), "icon": icon,
           "steps": [validate_action(s, nested=True, check_command=check_command, in_macro=True) for s in steps]}
    if "id" in obj:
        if not isinstance(obj["id"], str) or not _ID_RE.match(obj["id"]):
            raise ValueError("'id' inválido")
        out["id"] = obj["id"]
    return out


class NullBackend:
    """Backend sem uinput (testes)."""

    def __init__(self):
        self.log: list[tuple[str, int, int]] = []

    def key(self, code: int, value: int) -> None:
        self.log.append(("key", code, value))

    def rel(self, code: int, value: int) -> None:
        self.log.append(("rel", code, value))


def _minimal_keys() -> list[int]:
    """Teclas de teclado (KEY_*) e botões de mouse BTN_LEFT..BTN_TASK; sem joystick/caneta."""
    e = _ecodes()
    keys = {v for k, v in e.ecodes.items() if isinstance(v, int) and k.startswith("KEY_") and v < 0x100}
    keys.update(range(e.BTN_LEFT, e.BTN_TASK + 1))
    return sorted(keys)


class UInputBackend:
    def __init__(self):
        from evdev import UInput, ecodes
        # EV_REL faz o libinput tratar os BTN_* como botões de ponteiro
        caps = {ecodes.EV_KEY: _minimal_keys(),
                ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_HWHEEL]}
        self.ui = UInput(caps, name="Clique virtual input")

    def key(self, code: int, value: int) -> None:
        from evdev import ecodes
        self.ui.write(ecodes.EV_KEY, code, value)
        self.ui.syn()

    def rel(self, code: int, value: int) -> None:
        from evdev import ecodes
        self.ui.write(ecodes.EV_REL, code, value)
        self.ui.syn()

    def close(self) -> None:
        self.ui.close()


UINPUT_RETRY_SECONDS = 5.0


class SmartActionRunner:
    """Executa macros em passos com delays via scheduler; uma execução por vez por Smart Action."""

    def __init__(self, executor: "ActionExecutor", scheduler):
        self.executor, self.scheduler = executor, scheduler
        self.running: set[str] = set()

    def run(self, sa_id: str, dev_id: str = "") -> bool:
        if sa_id in self.running:
            log.info("Smart Action %s já está executando; clique ignorado", sa_id)
            return False
        sa = self.executor.smart_lookup(sa_id) if self.executor.smart_lookup else None
        if not sa:
            log.warning("Smart Action %s não existe", sa_id)
            return False
        steps = list(sa["steps"])[:MAX_STEPS]  # snapshot: edições durante a execução não afetam
        self.running.add(sa_id)
        self._step(sa_id, steps, 0, dev_id)
        return True

    def _step(self, sa_id: str, steps: list[dict], i: int, dev_id: str) -> None:
        try:
            while i < len(steps):
                step = steps[i]
                i += 1
                if step["type"] == "delay":
                    self.scheduler.call_later(step["ms"], lambda: self._step(sa_id, steps, i, dev_id))
                    return
                if step["type"] in ("smart_action", "gestures"):
                    continue  # defesa em profundidade: sem recursão
                try:
                    self.executor.perform(ActionEvent("trigger", step, 0, dev_id))
                except Exception:
                    log.exception("passo %d da Smart Action %s falhou", i, sa_id)
        except BaseException:
            self.running.discard(sa_id)
            raise
        self.running.discard(sa_id)


class ActionExecutor:
    def __init__(self, backend=None, *, scheduler=None, media=None, volume=None, opener=None,
                 windows=None, selection=None):
        from .timers import GLibScheduler
        self._backend = backend
        self._next_try = 0.0
        self._held: dict[tuple[str, int], list[int]] = {}  # (dev_id, cid) -> códigos pressionados
        self._children: list[subprocess.Popen] = []
        self._reaper = 0
        self.scheduler = scheduler or GLibScheduler()
        self.media = media or integ.MprisController()
        self.volume = volume or integ.VolumeController()
        self.opener = opener or integ.Opener()
        self.windows = windows or integ.WindowController()
        self.selection = selection or integ.Selection()
        self.smart_lookup: Callable[[str], dict | None] | None = None
        self.change_host_cb: Callable[[str, int], None] | None = None
        self.smart = SmartActionRunner(self, self.scheduler)

    @property
    def backend(self):
        """UInput é criado sob demanda; se falhar, tenta de novo após alguns segundos."""
        if self._backend is None:
            now = time.monotonic()
            if now < self._next_try:
                raise OSError("uinput indisponível")
            try:
                self._backend = UInputBackend()
            except Exception as e:  # sem permissão em /dev/uinput, etc.
                self._next_try = now + UINPUT_RETRY_SECONDS
                log.warning("uinput indisponível (%s); nova tentativa em %ds", e, UINPUT_RETRY_SECONDS)
                raise OSError(str(e)) from e
        return self._backend

    def _codes(self, action: dict, cid: int = 0) -> list[int]:
        t = action["type"]
        if t == "keys":
            return [key_code(k) for k in action["keys"]]
        if t == "mouse_button":
            return [key_code(action["button"])]
        if t == "default":
            btn = CID_TO_BUTTON.get(action.get("cid", cid))
            return [key_code(btn)] if btn else []
        return []

    def _release_codes(self, codes: list[int]) -> None:
        for c in reversed(codes):
            try:
                self.backend.key(c, 0)
            except OSError as e:
                log.error("falha ao soltar tecla %s: %s", c, e)

    def release_all(self, dev_id: str) -> None:
        """Solta tudo o que este dispositivo mantém pressionado (offline, troca de config, saída)."""
        for key in [k for k in self._held if k[0] == dev_id]:
            self._release_codes(self._held.pop(key))

    def release_everything(self) -> None:
        for dev_id in {k[0] for k in self._held}:
            self.release_all(dev_id)

    def release_all_for(self, key: tuple[str, int]) -> None:
        if key in self._held:
            self._release_codes(self._held.pop(key))

    def _press(self, codes: list[int], held: list[int]) -> None:
        """Pressiona em ordem registrando em `held`; se falhar no meio, o chamador solta o já feito."""
        for c in codes:
            self.backend.key(c, 1)
            held.append(c)

    def _tap(self, codes: list[int]) -> None:
        held: list[int] = []
        try:
            self._press(codes, held)
        finally:
            self._release_codes(held)

    def run(self, action: dict, dev_id: str = "") -> None:
        """Executa uma ação já (botão Testar / Smart Actions)."""
        self.perform(ActionEvent("trigger", action, 0, dev_id))

    def perform(self, ev: ActionEvent) -> None:
        a = ev.action
        t = a["type"]
        k = (ev.dev_id, ev.cid)
        try:
            if t in ("keys", "mouse_button", "default"):
                self._perform_hold(ev, k)
            elif ev.kind not in ("press", "trigger"):
                return  # as demais ações disparam só ao pressionar
            elif t == "command":
                self._spawn(a["argv"])
            elif t == "media":
                if not self.media.run(a["op"], a.get("player")):
                    self._tap([key_code(integ.MEDIA_FALLBACK_KEYS[a["op"]])])
            elif t == "volume":
                if not self.volume.run(a["op"], a.get("step", 5)):
                    key = {"up": "KEY_VOLUMEUP", "down": "KEY_VOLUMEDOWN", "mute": "KEY_MUTE"}[a["op"]]
                    self._tap([key_code(key)])
            elif t == "open":
                tgt = a["target"]
                ok = self.opener.launch_desktop(tgt) if tgt.endswith(".desktop") else self.opener.open_uri(tgt)
                if not ok:
                    log.warning("não foi possível abrir %s", tgt)
            elif t == "type_text":
                self._type_text(a["text"])
            elif t == "window":
                if not self.windows.run(a["op"]):
                    log.info("ação de janela '%s' sem efeito", a["op"])
            elif t == "ai_prompt":
                self._ai_prompt(a)
            elif t == "smart_action":
                self.smart.run(a["id"], ev.dev_id)
            elif t == "change_host":
                if self.change_host_cb and ev.dev_id:
                    self.change_host_cb(ev.dev_id, a["host"])
        except (OSError, ValueError) as e:
            log.error("falha ao executar ação %s: %s", t, e)

    def _perform_hold(self, ev: ActionEvent, k: tuple[str, int]) -> None:
        a = ev.action
        if a["type"] == "default" and a.get("cid", ev.cid) in CID_TO_REL:
            if ev.kind in ("press", "trigger"):  # roda horizontal: um passo por clique
                name, val = CID_TO_REL[a.get("cid", ev.cid)]
                self.backend.rel(_ecodes().ecodes[name], val)
            return
        codes = self._codes(a, ev.cid)
        if ev.kind == "press":
            self.release_all_for(k)
            held = self._held.setdefault(k, [])
            try:
                self._press(codes, held)
            except OSError:
                self._release_codes(self._held.pop(k, []))
                raise
        elif ev.kind == "release":
            self._release_codes(self._held.pop(k, []))
        else:  # trigger
            self._tap(codes)

    def _type_text(self, text: str) -> None:
        keys, _ = integ.text_to_keys(text)
        shift = key_code("KEY_LEFTSHIFT")
        for name, need_shift in keys:
            code = key_code(name)
            if need_shift:
                self.backend.key(shift, 1)
            try:
                self.backend.key(code, 1)
                self.backend.key(code, 0)
            finally:
                if need_shift:
                    self.backend.key(shift, 0)

    def _ai_prompt(self, a: dict) -> None:
        sel = self.selection.read_primary()[:integ.SELECTION_LIMIT]
        url, clip = integ.build_ai_request(a["service"], a["template"], sel)
        if clip is not None and not self.selection.write_clipboard(clip):
            log.warning("não foi possível copiar o prompt para a área de transferência")
        if not self.opener.open_uri(url):
            log.warning("não foi possível abrir %s", url)

    # --- processos filhos ---
    def _spawn(self, argv: list[str]) -> None:
        self._reap()
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        self._children.append(proc)
        if not self._reaper:
            try:
                from gi.repository import GLib
                self._reaper = GLib.timeout_add_seconds(2, self._reap_tick)
            except Exception:
                pass

    def _reap(self) -> None:
        self._children = [p for p in self._children if p.poll() is None]

    def _reap_tick(self) -> bool:
        self._reap()
        if not self._children:
            self._reaper = 0
            return False
        return True


class RecordingExecutor(ActionExecutor):
    """Modo CLIQUE_FAKE: registra as ações em vez de executá-las (sem uinput/pactl/xdg-open)."""

    def __init__(self, *a, **kw):
        super().__init__(NullBackend(), *a, **kw)
        self.executed: list[dict] = []

    def perform(self, ev: ActionEvent) -> None:
        a = ev.action
        if a["type"] == "smart_action":
            self.executed.append({"kind": ev.kind, "action": a, "dev_id": ev.dev_id})
            log.info("[fake] %s %s", ev.kind, a)
            if ev.kind in ("press", "trigger"):
                self.smart.run(a["id"], ev.dev_id)
            return
        if a["type"] == "change_host":
            super().perform(ev)
            return
        self.executed.append({"kind": ev.kind, "action": a, "dev_id": ev.dev_id})
        log.info("[fake] %s %s", ev.kind, a)
