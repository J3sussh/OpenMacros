"""0x1000 Battery Status e 0x1004 Unified Battery."""

from __future__ import annotations

from ..device import Device

ID_STATUS, ID_UNIFIED = 0x1000, 0x1004
STATUS_1000 = {0: "discharging", 1: "charging", 2: "charging", 3: "full", 4: "charging",
               5: "error", 6: "error"}
STATUS_1004 = {0: "discharging", 1: "charging", 2: "charging", 3: "full", 4: "charging",
               5: "error", 6: "error", 7: "error"}


def parse(feature_id: int, params: bytes) -> dict:
    if feature_id == ID_STATUS:
        return {"level": params[0], "status": STATUS_1000.get(params[2], "unknown"),
                "approximate": True}
    # 0x1004: [%, nível(bitmask), status, ...]
    return {"level": params[0], "status": STATUS_1004.get(params[2], "unknown"),
            "approximate": False}


def read(dev: Device) -> dict | None:
    if dev.has_feature(ID_UNIFIED):
        return parse(ID_UNIFIED, dev.call(ID_UNIFIED, 1))
    if dev.has_feature(ID_STATUS):
        return parse(ID_STATUS, dev.call(ID_STATUS, 0))
    return None
