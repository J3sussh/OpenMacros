"""0x2110 SmartShift e 0x2111 SmartShift com torque."""

from __future__ import annotations

from ..device import Device

ID_BASIC, ID_TORQUE = 0x2110, 0x2111
FREESPIN, RATCHET = 1, 2


def _fid(dev: Device) -> tuple[int, int, int] | None:
    """(feature, fn get, fn set)."""
    if dev.has_feature(ID_TORQUE):
        return ID_TORQUE, 1, 2
    if dev.has_feature(ID_BASIC):
        return ID_BASIC, 0, 1
    return None


def read(dev: Device) -> dict | None:
    f = _fid(dev)
    if not f:
        return None
    r = dev.call(f[0], f[1])
    return {"smartshift": {"enabled": r[0] == RATCHET and r[1] < 255, "threshold": r[1]}}


def write(dev: Device, enabled: bool, threshold: int) -> None:
    f = _fid(dev)
    if not f:
        raise ValueError("SmartShift ausente")
    threshold = max(1, min(254, threshold))
    dev.call(f[0], f[2], bytes([RATCHET, threshold if enabled else 255, 0]))
