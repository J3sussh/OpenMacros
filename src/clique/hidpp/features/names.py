"""0x0005 Device Name & Type."""

from __future__ import annotations

from ..device import Device

FEATURE_ID = 0x0005
TYPES = {0: "keyboard", 1: "remote", 2: "numpad", 3: "mouse", 4: "touchpad", 5: "trackball",
         6: "presenter", 7: "receiver"}
KIND = {"keyboard": "keyboard", "mouse": "mouse", "trackball": "trackball", "touchpad": "touchpad"}


def get_name(dev: Device) -> str | None:
    if not dev.has_feature(FEATURE_ID):
        return None
    length = dev.call(FEATURE_ID, 0)[0]
    out = b""
    while len(out) < length:
        chunk = dev.call(FEATURE_ID, 1, bytes([len(out)]))
        if not chunk.rstrip(b"\x00"):
            break
        out += chunk
    return out[:length].split(b"\x00")[0].decode("utf-8", "replace")


def get_type(dev: Device) -> str:
    if not dev.has_feature(FEATURE_ID):
        return "other"
    return KIND.get(TYPES.get(dev.call(FEATURE_ID, 2)[0], ""), "other")
