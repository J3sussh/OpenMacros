"""0x2121 Hi-Res Wheel."""

from __future__ import annotations

from ..device import Device

FEATURE_ID = 0x2121
M_TARGET, M_HIRES, M_INVERT = 0x01, 0x02, 0x04


def get_mode(dev: Device) -> int:
    return dev.call(FEATURE_ID, 1)[0]


def read(dev: Device) -> dict:
    mode = get_mode(dev)
    return {"hires_scroll": {"value": bool(mode & M_HIRES)},
            "scroll_invert": {"value": bool(mode & M_INVERT)}}


def set_flag(dev: Device, flag: int, on: bool) -> None:
    mode = get_mode(dev)
    mode = (mode | flag) if on else (mode & ~flag)
    dev.call(FEATURE_ID, 2, bytes([mode & 0xFF]))
