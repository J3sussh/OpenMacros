"""Codec HID++ 1.0 e 2.0: relatórios short (0x10), long (0x11) e very long (0x12)."""

from __future__ import annotations

from dataclasses import dataclass

SHORT, LONG, VERY_LONG = 0x10, 0x11, 0x12
REPORT_SIZES = {SHORT: 7, LONG: 20, VERY_LONG: 64}
MAX_PARAMS = {SHORT: 3, LONG: 16, VERY_LONG: 60}

DEVICE_INDEX_DIRECT = 0xFF  # receptor (registros) e dispositivos diretos (BT/USB)

V1_ERROR = 0x8F
V2_ERROR = 0xFF

V1_ERRORS = {
    0x00: "success", 0x01: "invalid sub id", 0x02: "invalid address",
    0x03: "invalid value", 0x04: "connect fail", 0x05: "too many devices",
    0x06: "already exists", 0x07: "busy", 0x08: "unknown device",
    0x09: "resource error", 0x0A: "request unavailable",
    0x0B: "invalid param value", 0x0C: "wrong pin code",
}
V2_ERRORS = {
    0x00: "no error", 0x01: "unknown", 0x02: "invalid argument",
    0x03: "out of range", 0x04: "hardware error", 0x05: "internal error",
    0x06: "invalid feature index", 0x07: "invalid function id", 0x08: "busy",
    0x09: "unsupported",
}


class HidppError(Exception):
    """Erro de protocolo HID++."""


class Hidpp10Error(HidppError):
    def __init__(self, code: int, sub_id: int = 0, address: int = 0):
        self.code, self.sub_id, self.address = code, sub_id, address
        super().__init__(f"HID++ 1.0: {V1_ERRORS.get(code, hex(code))} (sub 0x{sub_id:02x}, addr 0x{address:02x})")


class Hidpp20Error(HidppError):
    def __init__(self, code: int, feature_index: int = 0, function: int = 0):
        self.code, self.feature_index, self.function = code, feature_index, function
        super().__init__(f"HID++ 2.0: {V2_ERRORS.get(code, hex(code))} (feature idx {feature_index}, fn {function})")


class HidppTimeout(HidppError):
    """Sem resposta dentro do prazo."""


@dataclass(frozen=True)
class Message:
    report_id: int
    device_index: int
    byte2: int  # feature index (2.0) ou sub_id (1.0)
    byte3: int  # fn<<4|swid (2.0) ou endereço (1.0)
    params: bytes

    # visões HID++ 2.0
    @property
    def feature_index(self) -> int:
        return self.byte2

    @property
    def function(self) -> int:
        return self.byte3 >> 4

    @property
    def sw_id(self) -> int:
        return self.byte3 & 0x0F

    # visões HID++ 1.0
    @property
    def sub_id(self) -> int:
        return self.byte2

    @property
    def address(self) -> int:
        return self.byte3

    @property
    def is_v1_error(self) -> bool:
        return self.byte2 == V1_ERROR

    @property
    def is_v2_error(self) -> bool:
        return self.byte2 == V2_ERROR

    @property
    def is_receiver_notification(self) -> bool:
        return 0x40 <= self.byte2 < 0x80

    def to_bytes(self) -> bytes:
        size = REPORT_SIZES[self.report_id]
        body = bytes([self.report_id, self.device_index, self.byte2, self.byte3]) + self.params
        return body.ljust(size, b"\x00")


def _pick_report(n_params: int, min_report: int) -> int:
    for rid in (SHORT, LONG, VERY_LONG):
        if rid >= min_report and n_params <= MAX_PARAMS[rid]:
            return rid
    raise ValueError(f"parâmetros demais para HID++: {n_params}")


def encode_v2(device_index: int, feature_index: int, function: int, sw_id: int,
              params: bytes = b"", min_report: int = LONG) -> bytes:
    """Requisição HID++ 2.0. Por padrão usa long (aceito por todos os receptores)."""
    if not 0 <= function <= 15 or not 0 <= sw_id <= 15:
        raise ValueError("function/sw_id devem caber em 4 bits")
    rid = _pick_report(len(params), min_report)
    return Message(rid, device_index, feature_index, (function << 4) | sw_id, bytes(params)).to_bytes()


def encode_v1(device_index: int, sub_id: int, address: int, params: bytes = b"",
              min_report: int = SHORT) -> bytes:
    rid = _pick_report(len(params), min_report)
    return Message(rid, device_index, sub_id, address, bytes(params)).to_bytes()


def parse(raw: bytes) -> Message:
    if len(raw) < 4 or raw[0] not in REPORT_SIZES:
        raise ValueError(f"relatório HID++ inválido: {raw[:4].hex()}")
    if len(raw) < REPORT_SIZES[raw[0]]:
        raise ValueError("relatório truncado")
    size = REPORT_SIZES[raw[0]]
    return Message(raw[0], raw[1], raw[2], raw[3], bytes(raw[4:size]))


def error_for(msg: Message) -> HidppError | None:
    """Converte um relatório de erro em exceção (ou None se não for erro)."""
    if msg.is_v1_error:
        return Hidpp10Error(msg.params[1], msg.byte3, msg.params[0])
    if msg.is_v2_error:
        return Hidpp20Error(msg.params[1], msg.byte3, msg.params[0] >> 4)
    return None


def matches_v2(msg: Message, device_index: int, feature_index: int, function: int, sw_id: int) -> bool:
    return (msg.device_index == device_index and msg.feature_index == feature_index
            and msg.function == function and msg.sw_id == sw_id)


def error_matches_v2(msg: Message, device_index: int, feature_index: int, function: int, sw_id: int) -> bool:
    return (msg.device_index == device_index and msg.is_v2_error and msg.byte3 == feature_index
            and msg.params[0] == (function << 4 | sw_id))


def error_matches_v1(msg: Message, device_index: int, sub_id: int, address: int) -> bool:
    return (msg.device_index == device_index and msg.is_v1_error and msg.byte3 == sub_id
            and msg.params[0] == address)
