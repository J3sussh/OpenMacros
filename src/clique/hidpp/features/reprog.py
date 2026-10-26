"""0x1B04 Special Keys & Mouse Buttons (reprogramáveis)."""

from __future__ import annotations

from dataclasses import dataclass

from ..device import Device

FEATURE_ID = 0x1B04

GESTURE_CIDS = frozenset({0xC3, 0xD0})

# flags1 de getControlInfo
F_REPROGRAMMABLE, F_DIVERTABLE, F_PERSIST_DIVERTABLE = 0x10, 0x20, 0x40
F_VIRTUAL = 0x80  # controle virtual (sem botão físico)
# flags2 de getControlInfo
F2_RAW_XY = 0x01

# flags1 de set/getControlReporting
R_DIVERT, R_DIVERT_VALID = 0x01, 0x02
R_PERSIST, R_PERSIST_VALID = 0x04, 0x08
R_RAWXY, R_RAWXY_VALID = 0x10, 0x20


@dataclass(frozen=True)
class ControlInfo:
    cid: int
    tid: int
    flags: int
    pos: int
    group: int
    gmask: int
    flags2: int

    @property
    def reprogrammable(self) -> bool:
        return bool(self.flags & F_REPROGRAMMABLE)

    @property
    def virtual(self) -> bool:
        return bool(self.flags & F_VIRTUAL)

    @property
    def divertable(self) -> bool:
        return bool(self.flags & (F_DIVERTABLE | F_PERSIST_DIVERTABLE))

    @property
    def raw_xy_capable(self) -> bool:
        """Capacidade anunciada pelo firmware (o M720 anuncia em todo botão desviável)."""
        return bool(self.flags2 & F2_RAW_XY)

    @property
    def raw_xy(self) -> bool:
        """Útil para gestos: capaz de rawXY e é um botão de gestos conhecido."""
        return self.raw_xy_capable and self.cid in GESTURE_CIDS


@dataclass(frozen=True)
class Reporting:
    cid: int
    divert: bool
    persist: bool
    raw_xy: bool
    remap: int


def encode_set_reporting(cid: int, *, divert: bool | None = None, persist: bool | None = None,
                         raw_xy: bool | None = None, remap: int = 0, flags2: int = 0) -> bytes:
    """Parâmetros da fn3: CID BE, flags1, remap BE, flags2 (6 bytes). None = não alterar."""
    f1 = 0
    for val, bit, valid in ((divert, R_DIVERT, R_DIVERT_VALID),
                            (persist, R_PERSIST, R_PERSIST_VALID),
                            (raw_xy, R_RAWXY, R_RAWXY_VALID)):
        if val is not None:
            f1 |= valid | (bit if val else 0)
    return cid.to_bytes(2, "big") + bytes([f1]) + remap.to_bytes(2, "big") + bytes([flags2])


def parse_event(function: int, params: bytes):
    """Evento 0 -> ("key_report", [cids]); evento 1 -> ("raw_xy", dx, dy); senão None."""
    if function == 0:
        cids = [int.from_bytes(params[i:i + 2], "big") for i in range(0, 8, 2)]
        return ("key_report", [c for c in cids if c])
    if function == 1:
        return ("raw_xy",
                int.from_bytes(params[0:2], "big", signed=True),
                int.from_bytes(params[2:4], "big", signed=True))
    return None


class ReprogControls:
    def __init__(self, dev: Device):
        self.dev = dev

    def count(self) -> int:
        return self.dev.call(FEATURE_ID, 0)[0]

    def info(self, index: int) -> ControlInfo:
        r = self.dev.call(FEATURE_ID, 1, bytes([index]))
        return ControlInfo(int.from_bytes(r[0:2], "big"), int.from_bytes(r[2:4], "big"),
                           r[4], r[5], r[6], r[7], r[8])

    def controls(self) -> list[ControlInfo]:
        return [self.info(i) for i in range(self.count())]

    def get_reporting(self, cid: int) -> Reporting:
        r = self.dev.call(FEATURE_ID, 2, cid.to_bytes(2, "big"))
        f1 = r[2]
        return Reporting(int.from_bytes(r[0:2], "big"), bool(f1 & R_DIVERT), bool(f1 & R_PERSIST),
                         bool(f1 & R_RAWXY), int.from_bytes(r[3:5], "big"))

    def set_reporting(self, cid: int, **kw) -> None:
        self.dev.call(FEATURE_ID, 3, encode_set_reporting(cid, **kw))

    def reset_all(self) -> None:
        self.dev.call(FEATURE_ID, 5)
