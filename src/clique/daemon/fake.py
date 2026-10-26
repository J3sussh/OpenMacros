"""Dispositivos simulados (CLIQUE_FAKE=1) para desenvolver a GUI sem hardware."""

from __future__ import annotations

import copy
from typing import Any

from ..hidpp.cids import cid_name
from .manager import Manager, plan_reporting


class FakeDevice:
    def __init__(self, *, id: str, name: str, model_id: str, kind: str, connection: str, layout: str,
                 controls: list[dict], settings: dict, hosts: dict | None, battery: dict | None,
                 features: list[str]):
        self.id = id
        self.online = True
        self.on_event = None
        self._d = {
            "id": id, "name": name, "model_id": model_id, "kind": kind, "connection": connection,
            "online": True, "battery": battery, "features": features, "controls": controls,
            "settings": settings, "layout": layout,
        }
        if hosts:
            self._d["hosts"] = hosts
        self.reporting: dict[int, tuple[bool, bool, int]] = {}  # estado "no firmware"

    def describe(self) -> dict:
        d = copy.deepcopy(self._d)
        d["online"] = self.online
        return d

    def apply_control(self, cid: int, action: dict) -> None:
        self.reporting[cid] = plan_reporting(action)

    def set_setting(self, key: str, value: Any) -> None:
        s = self._d["settings"][key]
        if key == "smartshift":
            s.update(value)
        else:
            s["value"] = value

    def change_host(self, host: int) -> None:
        self._d["hosts"]["current"] = host

    def reset_controls(self) -> None:
        self.reporting.clear()

    def close(self) -> None:
        pass

    # utilitários para testes/desenvolvimento
    def simulate(self, kind: str, *args) -> None:
        if self.on_event:
            self.on_event(kind, *args)


def _control(cid: int, *, raw_xy: bool = False, task: int = 0) -> dict:
    return {"cid": cid, "name": cid_name(cid), "remappable": True, "divertable": True,
            "raw_xy": raw_xy, "default_task": task}


def make_m720() -> FakeDevice:
    return FakeDevice(
        id="logi:FA4E720A", name="M720 Triathlon", model_id="405e", kind="mouse",
        connection="receiver", layout="m720",
        controls=[_control(82, task=82), _control(83, task=83), _control(86, task=86),
                  _control(91, task=91), _control(93, task=93), _control(208, raw_xy=True, task=156)],
        settings={"pointer_speed": {"value": 256, "min": 46, "max": 511},
                  "hires_scroll": {"value": True}, "scroll_invert": {"value": False}},
        hosts={"count": 3, "current": 1, "names": ["BSIT-0661", "Hackbook", "HY300"]},
        battery={"level": 50, "status": "discharging", "approximate": True},
        features=["0x0000", "0x0001", "0x0003", "0x0005", "0x1000", "0x1814", "0x1815",
                  "0x1b04", "0x2205", "0x2121"])


def make_generic() -> FakeDevice:
    return FakeDevice(
        id="logi:FA4E0001", name="Mouse genérico", model_id="c077", kind="mouse",
        connection="usb", layout="generic-mouse",
        controls=[_control(82, task=82), _control(83, task=83), _control(86, task=86)],
        settings={"dpi": {"value": 1000, "choices": [400, 800, 1000, 1600, 3200]}},
        hosts=None, battery=None,
        features=["0x0000", "0x0001", "0x0005", "0x1b04", "0x2201"])


class FakeBackend:
    def scan(self, manager: Manager) -> None:
        for make in (make_m720, make_generic):
            dev = make()
            if dev.id not in manager.devices:
                manager.add_device(dev)
