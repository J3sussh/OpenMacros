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
from . import notify
from . import preferences
from . import smart
from .gestures import ActionEvent
from .secrets import find_secret

log = logging.getLogger(__name__)

SIMPLE_TYPES = {"default", "disabled", "keys", "mouse_button", "remap", "command", "change_host"}
NATIVE_TYPES = {"media", "volume", "open", "type_text", "window", "ai_prompt", "smart_action",
                "app", "key_sequence", "system"}
DIRECTIONS = ("click", "up", "down", "left", "right")
TYPE_METHODS = ("paste", "keys")
AI_DELIVERIES = ("clipboard", "url")
MAX_TEXT = 2000
MAX_TEMPLATE = 4000  # alinhado com a GUI (o texto do passo type_text continua em MAX_TEXT)
MAX_STEPS = 32
MAX_SEQUENCE_EVENTS = 400
MAX_EVENT_DELAY = 10000
APP_OPS = ("open", "close", "focus")
SYSTEM_OPS = ("lock", "screenshot", "screenshot_area", "suspend", "show_desktop", "mic_mute",
              "dnd_on", "dnd_off", "dnd_toggle", "empty_trash")
PASTE_GAP_MS = 150  # entre uma colagem e o próximo passo que escreve no CLIPBOARD (o app ainda lê o texto)
_APP_TARGET_RE = re.compile(r"^[A-Za-z0-9_.+-]{1,128}$")
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


def _check_app_target(t, check: bool) -> str:
    """`firefox.desktop` (ou caminho absoluto de um .desktop) ou um nome simples (`firefox`)."""
    if not isinstance(t, str) or not t or len(t) > 2048 or any(ord(c) < 32 for c in t):
        raise ValueError("'target' inválido")
    if t.endswith(".desktop"):
        return _check_open_target(t, check)
    if not _APP_TARGET_RE.match(t):
        raise ValueError("'target' deve ser um .desktop ou um nome de aplicativo simples (ex.: firefox)")
    return t


def _check_key_events(events) -> list[dict]:
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_SEQUENCE_EVENTS:
        raise ValueError(f"'events' deve ter de 1 a {MAX_SEQUENCE_EVENTS} eventos")
    out = []
    for e in events:
        if not isinstance(e, dict) or not isinstance(e.get("down"), bool):
            raise ValueError("cada evento precisa de 'key' e 'down' (booleano)")
        key_code(e.get("key"))
        out.append({"key": e["key"], "down": e["down"],
                    "delay_ms": _int_in(e.get("delay_ms", 0), 0, MAX_EVENT_DELAY, "delay_ms")})
    return out


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
        method = a.get("method", "paste")
        if method not in TYPE_METHODS:
            raise ValueError("'method' deve ser 'paste' ou 'keys'")
        return {"type": t, "text": text, "method": method}
    if t == "window":
        if a.get("op") not in ("close", "minimize", "maximize", "fullscreen", "next", "previous"):
            raise ValueError("'op' de window inválido")
        return {"type": t, "op": a["op"]}
    if t == "ai_prompt":
        if a.get("service") not in ("claude", "chatgpt", "perplexity", "gemini"):
            raise ValueError("'service' inválido")
        tpl = a.get("template", "Explique: {selection}")
        if not isinstance(tpl, str) or not tpl or len(tpl) > MAX_TEMPLATE:
            raise ValueError(f"'template' deve ter de 1 a {MAX_TEMPLATE} caracteres")
        out = {"type": t, "service": a["service"], "template": tpl}
        if "delivery" in a:
            if a["delivery"] not in AI_DELIVERIES:
                raise ValueError("'delivery' deve ser 'clipboard' ou 'url'")
            out["delivery"] = a["delivery"]  # ausente => preferência ai_delivery_default (padrão clipboard)
        return out
    if t == "app":
        if a.get("op") not in APP_OPS:
            raise ValueError("'op' de app deve ser open, close ou focus")
        return {"type": t, "op": a["op"], "target": _check_app_target(a.get("target"), check_command)}
    if t == "key_sequence":
        return {"type": t, "events": _check_key_events(a.get("events"))}
    if t == "system":
        if a.get("op") not in SYSTEM_OPS:
            raise ValueError("'op' de system inválido")
        return {"type": t, "op": a["op"]}
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


def validate_smart_action(obj, *, check_command: bool = True, keep_stats: bool = False) -> dict:
    """Smart Action v2 -> normalizado: {"id"?, "name", "description", "icon", "enabled", "triggers", "steps"}.
    Entradas v1 (sem triggers/enabled/description) recebem padrões. `stats` é só leitura: ignorado na
    entrada, a menos que `keep_stats` (leitura da config / backup) — nesse caso é saneado."""
    if not isinstance(obj, dict):
        raise ValueError("Smart Action deve ser um objeto")
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValueError("'name' deve ter de 1 a 80 caracteres")
    desc = obj.get("description", "")
    if not isinstance(desc, str) or len(desc) > smart.MAX_DESCRIPTION:
        raise ValueError(f"'description' deve ter até {smart.MAX_DESCRIPTION} caracteres")
    icon = obj.get("icon", "")
    if not isinstance(icon, str) or len(icon) > 80:
        raise ValueError("'icon' inválido")
    enabled = obj.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("'enabled' deve ser booleano")
    steps = obj.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"'steps' deve ter de 1 a {MAX_STEPS} passos")
    out = {"name": name.strip(), "description": desc, "icon": icon, "enabled": enabled,
           "triggers": smart.validate_triggers(obj.get("triggers", [])),
           "steps": [validate_action(s, nested=True, check_command=check_command, in_macro=True) for s in steps]}
    if keep_stats:
        out["stats"] = smart.sanitize_stats(obj.get("stats"))
    if "id" in obj:
        if not isinstance(obj["id"], str) or not _ID_RE.match(obj["id"]):
            raise ValueError("'id' inválido")
        out["id"] = obj["id"]
    return out


def smart_warnings(sa: dict) -> list[str]:
    """Avisos (não bloqueiam): passos `type_text` cujo texto o detector de segredos acusa. Nunca ecoa o texto."""
    out = []
    for i, step in enumerate(sa.get("steps", []), 1):
        if step.get("type") == "type_text":
            label = find_secret(step.get("text", ""))
            if label:
                out.append(f"Passo {i}: o texto parece conter um segredo ({label}); "
                           "não guarde senhas ou dados sensíveis em Smart Actions")
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
        self.ui = UInput(caps, name="OpenMacros+ virtual input")

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


def writes_clipboard(step: dict) -> bool:
    """Passo que escreve no CLIPBOARD (colagem de type_text ou prompt de IA)."""
    return (step["type"] == "type_text" and step.get("method", "paste") == "paste") or step["type"] == "ai_prompt"


class SmartActionRunner:
    """Executa macros em passos com delays via scheduler; uma execução por vez por Smart Action.

    Ganchos (opcionais): `on_start(id)` ao começar e `on_finish(id)` ao terminar (estatísticas, proteção
    contra laços). Smart Action desativada só roda como execução manual (`RunAction`/Experimentar)."""

    def __init__(self, executor: "ActionExecutor", scheduler):
        self.executor, self.scheduler = executor, scheduler
        self.running: set[str] = set()
        self.on_start: Callable[[str], None] | None = None
        self.on_finish: Callable[[str], None] | None = None

    def run(self, sa_id: str, dev_id: str = "", *, manual: bool | None = None) -> bool:
        if sa_id in self.running:
            log.info("Smart Action %s já está executando; clique ignorado", sa_id)
            return False
        sa = self.executor.smart_lookup(sa_id) if self.executor.smart_lookup else None
        if not sa:
            log.warning("Smart Action %s não existe", sa_id)
            return False
        if manual is None:
            manual = self.executor.manual
        if not manual and sa.get("enabled", True) is False:
            log.info("Smart Action %s está desativada; ignorada", sa_id)
            return False
        steps = list(sa["steps"])[:MAX_STEPS]  # snapshot: edições durante a execução não afetam
        self.running.add(sa_id)
        self._hook(self.on_start, sa_id)
        self._step(sa_id, steps, 0, dev_id, 0)
        return True

    @staticmethod
    def _hook(fn, sa_id: str) -> None:
        if fn:
            try:
                fn(sa_id)
            except Exception:
                log.exception("gancho da Smart Action %s falhou", sa_id)

    def _finish(self, sa_id: str) -> None:
        self.running.discard(sa_id)
        self._hook(self.on_finish, sa_id)

    def _step(self, sa_id: str, steps: list[dict], i: int, dev_id: str, gap: int) -> None:
        """`gap`: ms ainda a esperar antes de o próximo passo escrever no CLIPBOARD (após uma colagem)."""
        try:
            while i < len(steps):
                step = steps[i]
                i += 1
                if step["type"] == "delay":
                    rest = max(0, gap - step["ms"])
                    self.scheduler.call_later(step["ms"], lambda j=i, g=rest: self._step(sa_id, steps, j, dev_id, g))
                    return
                if step["type"] in ("smart_action", "gestures"):
                    continue  # defesa em profundidade: sem recursão
                if gap > 0 and writes_clipboard(step):
                    # o Ctrl+V anterior ainda está sendo entregue: não troque o CLIPBOARD embaixo dele
                    self.scheduler.call_later(gap, lambda j=i - 1: self._step(sa_id, steps, j, dev_id, 0))
                    return
                state = {"sync": True, "done": False}

                def cont(j=i, st=state):
                    if st["sync"]:
                        st["done"] = True
                    else:
                        self._step(sa_id, steps, j, dev_id, 0)
                try:
                    self.executor.perform_step(step, dev_id, cont)
                except Exception:
                    log.exception("passo %d da Smart Action %s falhou", i, sa_id)
                    state["done"] = True
                state["sync"] = False
                if not state["done"]:
                    return  # passo assíncrono (key_sequence): `cont` retoma
                if step["type"] == "type_text" and step.get("method", "paste") == "paste":
                    gap = PASTE_GAP_MS
        except BaseException:
            self._finish(sa_id)
            raise
        self._finish(sa_id)


class _KeySequence:
    """Reprodução de uma `key_sequence` em andamento (delays via scheduler; solta tudo no fim/erro)."""

    def __init__(self, events: list[dict], done):
        self.events, self.done = events, done
        self.i = 0
        self.waited = False
        self.held: list[int] = []
        self.timer = None


class ActionExecutor:
    def __init__(self, backend=None, *, scheduler=None, media=None, volume=None, opener=None,
                 windows=None, selection=None, notifier=None, apps=None, system=None):
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
        self.apps = apps or integ.AppController(self.opener)
        self.system = system or integ.SystemController()
        self.notifier = notifier or notify.NullNotifier()
        self.prefs_lookup: Callable[[], dict] = lambda: dict(preferences.DEFAULTS)
        self.app_id_lookup: Callable[[], str] = lambda: ""
        self._clip_saved: str | None = None   # CLIPBOARD original enquanto uma colagem está pendente
        self._clip_pending = False
        self._clip_timer = None
        self.manual = False  # True durante run(): "Experimentar"/RunAction ignoram `enabled`
        self._sequences: list[_KeySequence] = []
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
        for seq in list(self._sequences):
            self._finish_sequence(seq)
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
        """Executa uma ação já (botão Testar / RunAction): ignora `enabled` de Smart Actions."""
        self.manual = True
        try:
            self.perform(ActionEvent("trigger", action, 0, dev_id))
        finally:
            self.manual = False

    def perform_step(self, step: dict, dev_id: str, done: Callable[[], None]) -> None:
        """Passo de Smart Action; sempre acaba chamando `done` (já, ou depois no caso de key_sequence)."""
        if step["type"] == "key_sequence":
            self._start_sequence(step["events"], done)
            return
        self.perform(ActionEvent("trigger", step, 0, dev_id))
        done()

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
                self._type_text(a)
            elif t == "window":
                if not self.windows.run(a["op"]):
                    log.info("ação de janela '%s' sem efeito", a["op"])
            elif t == "ai_prompt":
                self._ai_prompt(a)
            elif t == "app":
                if not self.apps.run(a["op"], a["target"]):
                    log.info("ação de app '%s %s' sem efeito", a["op"], a["target"])
            elif t == "key_sequence":
                self._start_sequence(a["events"], None)
            elif t == "system":
                self._system(a["op"])
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

    # --- key_sequence ---
    def _start_sequence(self, events: list[dict], done) -> None:
        seq = _KeySequence(events, done)
        self._sequences.append(seq)
        self._advance_sequence(seq)

    def _advance_sequence(self, seq: _KeySequence) -> None:
        seq.timer = None
        try:
            while seq.i < len(seq.events):
                ev = seq.events[seq.i]
                if ev["delay_ms"] > 0 and not seq.waited:  # o atraso vem ANTES do evento
                    seq.waited = True
                    seq.timer = self.scheduler.call_later(ev["delay_ms"], lambda: self._advance_sequence(seq))
                    return
                seq.waited = False
                code = key_code(ev["key"])
                self.backend.key(code, 1 if ev["down"] else 0)
                if ev["down"]:
                    seq.held.append(code)
                elif code in seq.held:
                    seq.held.remove(code)
                seq.i += 1
        except Exception as e:
            log.error("key_sequence interrompida: %s", e)
        self._finish_sequence(seq)

    def _finish_sequence(self, seq: _KeySequence) -> None:
        """Solta tudo o que ficou pressionado (ordem inversa), cancela timer e avisa o chamador."""
        if seq not in self._sequences:
            return
        self._sequences.remove(seq)
        if seq.timer is not None:
            self.scheduler.cancel(seq.timer)
            seq.timer = None
        self._release_codes(seq.held)
        seq.held = []
        if seq.done:
            try:
                seq.done()
            except Exception:
                log.exception("retomada após key_sequence falhou")

    def _system(self, op: str) -> None:
        if self.system.run(op):
            return
        if op == "mic_mute":  # sem pactl/wpctl: tecla de microfone do teclado
            self._tap([key_code("KEY_MICMUTE")])
        else:
            log.info("ação de sistema '%s' indisponível neste ambiente", op)

    def _type_text(self, a: dict) -> None:
        if a.get("method", "paste") == "keys":
            self._type_keys(a["text"])
        else:
            self._paste_text(a["text"])

    def _type_keys(self, text: str) -> None:
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

    def _paste_text(self, text: str) -> None:
        """Coloca o texto no CLIPBOARD, envia Ctrl+V (Ctrl+Shift+V em terminais) e restaura o CLIPBOARD
        anterior ~600 ms depois (timer, não bloqueia)."""
        if not self._clip_pending:  # colagens em sequência preservam o CLIPBOARD *original*
            self._clip_saved = self.selection.read_clipboard()
        if not self.selection.write_clipboard(text):
            raise OSError("não foi possível usar a área de transferência (instale xclip ou xsel)")
        self._clip_pending = True
        if self._clip_timer is not None:
            self.scheduler.cancel(self._clip_timer)
        keys = ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_V"] if integ.is_terminal(self.app_id_lookup()) \
            else ["KEY_LEFTCTRL", "KEY_V"]
        try:
            self._tap([key_code(k) for k in keys])
        finally:
            self._clip_timer = self.scheduler.call_later(integ.CLIP_RESTORE_MS, self._restore_clipboard)

    def _restore_clipboard(self) -> None:
        self._clip_timer = None
        self._clip_pending = False
        saved, self._clip_saved = self._clip_saved, None
        if saved is not None:
            if not self.selection.write_clipboard(saved):
                log.warning("não foi possível restaurar o CLIPBOARD")
            return
        # o original não era texto (ou não pôde ser lido): não deixe o texto colado (pode ser uma senha) lá
        clear = getattr(self.selection, "clear_clipboard", None)
        if not (clear() if clear else self.selection.write_clipboard("")):
            log.warning("não foi possível limpar o CLIPBOARD")

    def flush_clipboard(self) -> None:
        """Restaura já o CLIPBOARD de uma colagem pendente (encerramento do serviço)."""
        if self._clip_timer is not None:
            self.scheduler.cancel(self._clip_timer)
        if self._clip_pending:
            self._restore_clipboard()

    def _drop_pending_clipboard(self) -> None:
        """O CLIPBOARD vai receber outro conteúdo de propósito: abandona o restore agendado."""
        if self._clip_timer is not None:
            self.scheduler.cancel(self._clip_timer)
            self._clip_timer = None
        self._clip_saved = None
        self._clip_pending = False

    def _ai_prompt(self, a: dict) -> None:
        sel = self.selection.read_primary()[:integ.SELECTION_LIMIT]
        if not sel.strip():
            self.notifier.notify("ai", "Nada selecionado", "Selecione um texto antes de usar a ação de IA.")
            return
        delivery = a.get("delivery") or self.prefs_lookup().get("ai_delivery_default", "clipboard")
        secret = find_secret(sel)
        forced = bool(secret) and delivery == "url"
        if forced:
            log.warning("ai_prompt: seleção parece conter um segredo (%s); entrega forçada para clipboard", secret)
            self.notifier.notify("ai", "Seleção parece conter um segredo — não foi para a URL",
                                 "O prompt foi copiado; cole com Ctrl+V.", urgency=notify.URGENCY_NORMAL)
            delivery = "clipboard"
        url, clip = integ.build_ai_request(a["service"], a["template"], sel, delivery)
        if clip is not None:
            self._drop_pending_clipboard()  # um restore atrasado apagaria o prompt recém-copiado
            if not self.selection.write_clipboard(clip):
                log.warning("não foi possível copiar o prompt para a área de transferência")
                self.notifier.notify("ai", "Não foi possível copiar o prompt", "Instale xclip ou xsel.")
                return
            if not forced:
                self.notifier.notify("ai", "Prompt copiado — cole com Ctrl+V")
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
    """Modo OPENMACROS_FAKE: registra as ações em vez de executá-las (sem uinput/pactl/xdg-open)."""

    def __init__(self, *a, **kw):
        super().__init__(NullBackend(), *a, **kw)
        self.executed: list[dict] = []

    def perform_step(self, step, dev_id, done) -> None:
        if step["type"] == "key_sequence":
            self.executed.append({"kind": "trigger", "action": step, "dev_id": dev_id})
            log.info("[fake] trigger %s", step)
            done()
            return
        super().perform_step(step, dev_id, done)

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
