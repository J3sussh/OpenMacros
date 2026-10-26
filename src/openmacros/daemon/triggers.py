"""Gatilhos das Smart Actions v2 ("Se…"): atalho global, aplicativo e dispositivo.

Este módulo é puro (sem X11): o `TriggerEngine` casa eventos com os gatilhos das Smart Actions e decide
o que registrar no teclado; o X11 fica em `xtriggers.py` e os backends são injetáveis (testes/Wayland).
As proteções (desativada, 1x/2 s, sem laço) ficam no Manager, que recebe `fire(id, trigger)`.
"""

from __future__ import annotations

import logging
from typing import Callable

from . import smart

log = logging.getLogger(__name__)


class UnavailableShortcuts:
    """Atalhos globais indisponíveis (Wayland, sem X, sem python-xlib): todo atalho vira erro legível."""
    available = False

    def __init__(self, reason: str):
        self.reason = reason

    def start(self, callback) -> None:
        pass

    def sync(self, combos) -> dict:
        return {c: self.reason for c in combos}

    def stop(self) -> None:
        pass


class FakeShortcuts:
    """Modo OPENMACROS_FAKE/testes: aceita tudo (ou falha o que estiver em `fail`) e deixa disparar à mão."""
    available = True
    reason = ""

    def __init__(self, fail: dict | None = None):
        self.callback = None
        self.fail = dict(fail or {})
        self.grabbed: set = set()

    def start(self, callback) -> None:
        self.callback = callback

    def sync(self, combos) -> dict:
        errs = {c: self.fail[c] for c in combos if c in self.fail}
        self.grabbed = {c for c in combos if c not in errs}
        return errs

    def press(self, combo) -> None:
        if combo in self.grabbed and self.callback:
            self.callback(combo)

    def stop(self) -> None:
        self.grabbed = set()


class TriggerEngine:
    def __init__(self, smart_actions: Callable[[], dict], fire: Callable[[str, dict], None],
                 report_error: Callable[[str], None] = lambda msg: None):
        self.smart_actions = smart_actions  # () -> {id: Smart Action validada (com triggers/enabled/name)}
        self.fire = fire
        self.report_error = report_error
        self.shortcuts = None
        self.errors: dict[str, list[dict]] = {}
        self._wanted: dict[smart.Combo, tuple[str, int]] = {}

    # --- atalhos ---
    def attach_shortcuts(self, backend) -> None:
        if self.shortcuts is not None:
            self.shortcuts.stop()
        self.shortcuts = backend
        backend.start(self.on_combo)
        self.sync_shortcuts()

    def detach_shortcuts(self) -> None:
        if self.shortcuts is not None:
            self.shortcuts.stop()
        self.shortcuts = None
        self._wanted = {}

    def trigger_errors(self, sa_id: str) -> list[dict]:
        return list(self.errors.get(sa_id, []))

    def sync_shortcuts(self) -> None:
        """Recalcula o que registrar (só Smart Actions ativas) e atualiza `errors`. Avisa só erros novos."""
        old = {(sid, e["index"], e["message"]) for sid, es in self.errors.items() for e in es}
        sas = self.smart_actions()
        backend = self.shortcuts
        wanted: dict[smart.Combo, tuple[str, int]] = {}
        errors: dict[str, list[dict]] = {}
        names: dict[str, str] = {}

        def err(sid: str, idx: int, msg: str) -> None:
            errors.setdefault(sid, []).append({"index": idx, "message": msg})

        for sid, sa in sas.items():
            if not sa.get("enabled", True):
                continue  # desativada não segura a combinação (outros programas podem usá-la)
            for i, t in enumerate(sa.get("triggers", [])):
                if t.get("type") != "shortcut":
                    continue
                try:
                    combo = smart.parse_shortcut(t["keys"])
                except (ValueError, KeyError) as e:
                    err(sid, i, str(e))
                    continue
                label = smart.combo_label(t["keys"])
                if backend is None or not backend.available:
                    err(sid, i, f"Atalho {label}: " + (getattr(backend, "reason", "") or "atalhos globais indisponíveis"))
                elif combo in wanted:
                    other = names.get(wanted[combo][0], wanted[combo][0])
                    err(sid, i, f"Atalho {label} já é usado pela Smart Action '{other}'")
                else:
                    wanted[combo] = (sid, i)
                    names[sid] = sa.get("name", sid)
        if backend is not None and backend.available:
            failed = backend.sync(set(wanted))
            for combo, msg in failed.items():
                sid, i = wanted.pop(combo)
                label = smart.combo_label(sas[sid]["triggers"][i]["keys"])
                err(sid, i, f"Atalho {label} indisponível: {msg}")
        self._wanted, self.errors = wanted, errors
        for sid, es in errors.items():
            for e in es:
                if (sid, e["index"], e["message"]) not in old:
                    self.report_error(f"Smart Action '{sas[sid].get('name', sid)}': {e['message']}")

    def on_combo(self, combo: smart.Combo) -> None:
        hit = self._wanted.get(combo)
        if not hit:
            return
        sa = self.smart_actions().get(hit[0])
        if sa and hit[1] < len(sa.get("triggers", [])):
            self.fire(hit[0], sa["triggers"][hit[1]])

    # --- aplicativo / dispositivo ---
    def on_app_event(self, event: str, app_id: str) -> None:
        """event: open | close | focus. `app_id` em minúsculas (regra do FocusWatcher)."""
        app_id = (app_id or "").lower()
        if app_id:
            self._match("app", event, lambda t: t.get("app_id") == app_id)

    def on_device_event(self, event: str, dev_id: str) -> None:
        """event: connect | disconnect."""
        self._match("device", event, lambda t: t.get("device_id", "*") in ("*", dev_id))

    def _match(self, kind: str, event: str, pred) -> None:
        for sid, sa in list(self.smart_actions().items()):
            if not sa.get("enabled", True):
                continue
            for t in sa.get("triggers", []):
                if t.get("type") == kind and t.get("event") == event and pred(t):
                    self.fire(sid, t)
                    break  # um disparo por Smart Action e evento ("Ou" entre gatilhos)


class AppTracker:
    """Conjunto de app_ids com janela aberta, a partir de listas de janelas (_NET_CLIENT_LIST).
    A primeira atualização é o estado inicial: não gera eventos."""

    def __init__(self, read_window: Callable[[int], dict | None]):
        self.read_window = read_window  # wid -> ActiveApp | None (ignorar a janela)
        self._wins: dict[int, dict | None] = {}
        self.apps: dict[str, dict] = {}
        self._initial = True

    def update(self, wids: list[int]) -> tuple[list[dict], list[dict]]:
        wins = {w: (self._wins[w] if w in self._wins else self.read_window(w)) for w in wids}
        apps: dict[str, dict] = {}
        for a in wins.values():
            if a and a.get("app_id"):
                apps.setdefault(a["app_id"], a)
        opened = [a for k, a in apps.items() if k not in self.apps]
        closed = [a for k, a in self.apps.items() if k not in apps]
        self._wins, self.apps = wins, apps
        if self._initial:
            self._initial = False
            return [], []
        return opened, closed

    def running_apps(self) -> list[dict]:
        return sorted(self.apps.values(), key=lambda a: a["app_id"])


class FakeAppWatcher:
    """Modo OPENMACROS_FAKE/testes: a lista de apps é definida à mão."""

    def __init__(self):
        self.tracker = AppTracker(lambda wid: self._windows.get(wid))
        self._windows: dict[int, dict] = {}
        self.callback = None
        self._next = 1

    def start(self, callback) -> None:
        self.callback = callback
        self.tracker.update(list(self._windows))  # estado inicial: não gera eventos

    def set_apps(self, apps: list[dict]) -> None:
        self._windows = {i: a for i, a in enumerate(apps, 1)}
        self._refresh()

    def add_app(self, app: dict) -> None:
        self._windows[1000 + self._next] = app
        self._next += 1
        self._refresh()

    def _refresh(self) -> None:
        if self.callback is not None:  # antes do start() só acumula o estado inicial
            self._emit(self.tracker.update(list(self._windows)))

    def _emit(self, diff) -> None:
        if self.callback and (diff[0] or diff[1]):
            self.callback(*diff)

    def running_apps(self) -> list[dict]:
        return self.tracker.running_apps()

    def stop(self) -> None:
        pass
