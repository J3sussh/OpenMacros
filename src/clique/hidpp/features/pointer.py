"""0x2205 Pointer Speed."""

from __future__ import annotations

from ..device import Device

FEATURE_ID = 0x2205
MIN, MAX = 0x002E, 0x01FF


def read(dev: Device) -> dict:
    v = int.from_bytes(dev.call(FEATURE_ID, 0)[0:2], "big")
    return {"pointer_speed": {"value": v, "min": MIN, "max": MAX}}


def set_speed(dev: Device, value: int) -> None:
    dev.call(FEATURE_ID, 1, value.to_bytes(2, "big"))
