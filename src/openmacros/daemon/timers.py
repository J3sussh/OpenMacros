"""Agendamento: GLib em produção, ManualScheduler nos testes."""

from __future__ import annotations

import itertools
from typing import Callable


class GLibScheduler:
    def call_later(self, ms: int, fn: Callable[[], None]) -> int:
        from gi.repository import GLib

        def run():
            try:
                fn()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("timer falhou")
            return False
        return GLib.timeout_add(max(0, int(ms)), run)

    def cancel(self, handle: int) -> None:
        from gi.repository import GLib
        try:
            GLib.source_remove(handle)
        except Exception:
            pass


class ManualScheduler:
    """Relógio manual: `advance(ms)` dispara o que venceu, em ordem de prazo."""

    def __init__(self):
        self.now = 0
        self._ids = itertools.count(1)
        self._pending: dict[int, tuple[int, int, Callable[[], None]]] = {}

    def call_later(self, ms: int, fn: Callable[[], None]) -> int:
        h = next(self._ids)
        self._pending[h] = (self.now + max(0, int(ms)), h, fn)
        return h

    def cancel(self, handle: int) -> None:
        self._pending.pop(handle, None)

    def advance(self, ms: int = 0) -> None:
        target = self.now + ms
        while True:
            due = sorted(v for v in self._pending.values() if v[0] <= target)
            if not due:
                break
            when, h, fn = due[0]
            self._pending.pop(h, None)
            self.now = max(self.now, when)
            fn()
        self.now = target

    @property
    def pending(self) -> int:
        return len(self._pending)
