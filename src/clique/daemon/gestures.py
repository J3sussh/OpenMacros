"""Máquina de estados de gestos e roteamento de botões desviados. Pura (sem I/O)."""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_THRESHOLD = 50
_PASSIVE = ('disabled', 'remap')  # 'default' num CID desviado re-emite o botão original
ANGLE_LIMIT = 30.0  # graus em torno de um eixo


class GestureTracker:
    """Acumula dx/dy enquanto o botão está pressionado. Dispara no máximo uma vez por pressão."""

    def __init__(self, threshold: int = DEFAULT_THRESHOLD):
        self.threshold = max(1, int(threshold))
        self.active = False
        self.fired = False
        self.dx = 0
        self.dy = 0

    def press(self) -> None:
        self.active, self.fired, self.dx, self.dy = True, False, 0, 0

    def move(self, dx: int, dy: int) -> str | None:
        if not self.active or self.fired:
            return None
        self.dx += dx
        self.dy += dy
        ax, ay = abs(self.dx), abs(self.dy)
        if ax >= self.threshold and math.degrees(math.atan2(ay, ax)) <= ANGLE_LIMIT:
            self.fired = True
            return "right" if self.dx > 0 else "left"
        if ay >= self.threshold and math.degrees(math.atan2(ax, ay)) <= ANGLE_LIMIT:
            self.fired = True
            return "down" if self.dy > 0 else "up"
        return None

    def release(self) -> str | None:
        """'click' se soltou sem disparar; None caso contrário."""
        was_active, fired = self.active, self.fired
        self.active = False
        return "click" if was_active and not fired else None


@dataclass(frozen=True)
class ActionEvent:
    kind: str     # "press" | "release" | "trigger"
    action: dict
    cid: int
    dev_id: str = ""


class ButtonRouter:
    """Recebe KeyReport/RawXY de um dispositivo e devolve ActionEvents."""

    def __init__(self, assignments: dict[int, dict] | None = None, dev_id: str = ""):
        self.dev_id = dev_id
        self.assignments: dict[int, dict] = {}
        self.pressed: set[int] = set()
        self.trackers: dict[int, GestureTracker] = {}
        self.set_assignments(assignments or {})

    def set_assignments(self, assignments: dict[int, dict]) -> list[ActionEvent]:
        """Troca as atribuições. Devolve 'release' para botões pressionados cuja ação mudou/sumiu."""
        out: list[ActionEvent] = []
        for cid in sorted(self.pressed):
            old, new = self.assignments.get(cid), assignments.get(cid)
            if old != new:
                self.pressed.discard(cid)
                if old and old["type"] not in _PASSIVE and old["type"] != "gestures":
                    out.append(ActionEvent("release", old, cid, self.dev_id))
        old_trackers = self.trackers
        old_assignments = self.assignments
        self.assignments = dict(assignments)
        self.trackers = {}
        for cid, a in assignments.items():
            if a.get("type") != "gestures":
                continue
            # gesto em andamento com a mesma configuração mantém o acumulado
            if cid in self.pressed and old_assignments.get(cid) == a and cid in old_trackers:
                self.trackers[cid] = old_trackers[cid]
            else:
                self.trackers[cid] = GestureTracker(a.get("threshold", DEFAULT_THRESHOLD))
        return out

    def reset(self) -> None:
        self.pressed.clear()
        for t in self.trackers.values():
            t.release()

    def on_key_report(self, cids: list[int]) -> list[ActionEvent]:
        now = set(cids)
        out: list[ActionEvent] = []
        for cid in sorted(now - self.pressed):
            act = self.assignments.get(cid)
            if act is None:
                continue
            self.pressed.add(cid)
            if act["type"] == "gestures":
                self.trackers[cid].press()
            elif act["type"] not in _PASSIVE:
                out.append(ActionEvent("press", act, cid, self.dev_id))
        for cid in sorted(self.pressed - now):
            self.pressed.discard(cid)
            act = self.assignments.get(cid)
            if act is None:
                continue
            if act["type"] == "gestures":
                res = self.trackers[cid].release()
                if res == "click":
                    out.extend(self._trigger(act.get("click"), cid))
            elif act["type"] not in _PASSIVE:
                out.append(ActionEvent("release", act, cid, self.dev_id))
        return out

    def on_raw_xy(self, dx: int, dy: int) -> list[ActionEvent]:
        out: list[ActionEvent] = []
        for cid in sorted(self.pressed):
            tr = self.trackers.get(cid)
            if tr is None:
                continue
            direction = tr.move(dx, dy)
            if direction:
                out.extend(self._trigger(self.assignments[cid].get(direction), cid, direction))
        return out

    def _trigger(self, action: dict | None, cid: int, direction: str = "click") -> list[ActionEvent]:
        if not action or action.get("type") == "disabled":
            return []
        if action.get("type") == "default":
            # só o clique tem um "padrão" a re-emitir (botão original)
            return [ActionEvent("trigger", action, cid, self.dev_id)] if direction == "click" else []
        return [ActionEvent("trigger", action, cid, self.dev_id)]
