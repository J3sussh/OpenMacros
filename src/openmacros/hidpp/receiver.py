"""Receptores Unifying / Bolt / Nano (HID++ 1.0)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from . import messages as m
from .channel import Channel
from .device import Device

log = logging.getLogger(__name__)

RECEIVER_PIDS = {
    0xC52B: "unifying", 0xC532: "unifying", 0xC52F: "nano", 0xC534: "nano",
    0xC539: "lightspeed", 0xC53A: "lightspeed", 0xC53D: "lightspeed", 0xC545: "lightspeed",
    0xC548: "bolt", 0xC54D: "lightspeed",
}

SET_REGISTER, GET_REGISTER, GET_LONG_REGISTER = 0x80, 0x81, 0x83
REG_NOTIFICATIONS = 0x00
REG_CONNECTION_STATE = 0x02
REG_PAIRING_INFO = 0xB5
NOTIF_DISCONNECT, NOTIF_CONNECT = 0x40, 0x41
MAX_DEVICES = 6


def is_receiver(pid: int) -> bool:
    return pid in RECEIVER_PIDS


@dataclass
class ConnectionEvent:
    index: int
    connected: bool
    wpid: int | None
    kind: int | None


class Receiver:
    def __init__(self, channel: Channel, pid: int):
        self.channel = channel
        self.pid = pid
        self.family = RECEIVER_PIDS.get(pid, "unknown")

    def enable_notifications(self) -> None:
        """Garante notificações sem fio + 'software present' (0x000900); só escreve se faltar."""
        want = b"\x00\x09\x00"
        cur = self.channel.request_v1(m.DEVICE_INDEX_DIRECT, GET_REGISTER, REG_NOTIFICATIONS)[:3]
        if cur != want:
            self.channel.request_v1(m.DEVICE_INDEX_DIRECT, SET_REGISTER, REG_NOTIFICATIONS, want)

    def trigger_connections(self) -> None:
        """Faz o receptor reenviar as notificações de conexão de todos os pareados."""
        self.channel.request_v1(m.DEVICE_INDEX_DIRECT, SET_REGISTER, REG_CONNECTION_STATE, b"\x02\x00\x00")

    def serial(self) -> str | None:
        try:
            r = self.channel.request_v1(m.DEVICE_INDEX_DIRECT, GET_LONG_REGISTER, REG_PAIRING_INFO, b"\x03")
        except m.HidppError:
            return None
        return r[1:5].hex().upper()

    def pairing_info(self, index: int) -> tuple[int, int] | None:
        """(wpid, tipo de dispositivo) do registro 0xB5 (sub 0x20+n-1), Unifying/Nano.
        Bolt usa outro formato: retorna None e o chamador cai em outros métodos."""
        if self.family == "bolt":
            return None
        try:
            r = self.channel.request_v1(m.DEVICE_INDEX_DIRECT, GET_LONG_REGISTER, REG_PAIRING_INFO,
                                        bytes([0x20 + index - 1]), timeout=0.5)
        except m.HidppError:
            return None
        wpid = int.from_bytes(r[3:5], "big")
        return (wpid, r[6]) if wpid else None

    def enumerate_online(self) -> list[Device]:
        """Faz ping nos índices 1..6; quem responder está online."""
        devices = []
        for idx in range(1, MAX_DEVICES + 1):
            dev = Device(self.channel, idx, via_receiver=True)
            try:
                dev.ping(timeout=0.3)
            except (m.HidppTimeout, m.Hidpp10Error):
                continue
            except m.HidppError:
                continue
            info = self.pairing_info(idx)
            if info:
                dev.wpid = info[0]
            devices.append(dev)
        return devices

    @staticmethod
    def parse_connection(msg: m.Message) -> ConnectionEvent | None:
        """Interpreta 0x40 (desconectou) e 0x41 (conectou)."""
        if msg.sub_id == NOTIF_DISCONNECT:
            return ConnectionEvent(msg.device_index, False, None, None)
        if msg.sub_id == NOTIF_CONNECT:
            flags = msg.params[0]
            connected = not (flags & 0x40)
            wpid = (msg.params[2] << 8) | msg.params[1]
            return ConnectionEvent(msg.device_index, connected, wpid, flags & 0x0F)
        return None
