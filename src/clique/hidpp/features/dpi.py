"""0x2201 Adjustable DPI."""

from __future__ import annotations

from ..device import Device

FEATURE_ID = 0x2201


def parse_dpi_list(data: bytes) -> list[int]:
    """Lista de u16 BE (após o byte de sensor); valores 0xE000+n indicam passo entre vizinhos."""
    vals = [int.from_bytes(data[i:i + 2], "big") for i in range(0, len(data) - 1, 2)]
    out: list[int] = []
    i = 0
    while i < len(vals) and vals[i]:
        v = vals[i]
        if v >= 0xE000 and out and i + 1 < len(vals):
            step, hi = v - 0xE000, vals[i + 1]
            if step:
                cur = out[-1] + step
                while cur <= hi and len(out) < 512:
                    out.append(cur)
                    cur += step
            i += 2
            continue
        out.append(v)
        i += 1
    return out


def read(dev: Device) -> dict:
    lst = parse_dpi_list(dev.call(FEATURE_ID, 1, b"\x00")[1:])
    cur = int.from_bytes(dev.call(FEATURE_ID, 2, b"\x00")[1:3], "big")
    return {"dpi": {"value": cur, "choices": lst}}


def set_dpi(dev: Device, value: int) -> None:
    dev.call(FEATURE_ID, 3, b"\x00" + value.to_bytes(2, "big"))
