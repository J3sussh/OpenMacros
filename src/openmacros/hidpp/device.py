"""Dispositivo HID++ 2.0: root, featureset, cache de features, despacho de eventos."""

from __future__ import annotations

import logging
from typing import Callable

from . import messages as m
from .channel import Channel

log = logging.getLogger(__name__)

ROOT = 0x0000
FEATURE_SET = 0x0001
DEVICE_INFO = 0x0003


class FeatureNotSupported(m.HidppError):
    pass


class Device:
    def __init__(self, channel: Channel, index: int, *, wpid: int | None = None,
                 via_receiver: bool = False):
        self.channel = channel
        self.index = index
        self.wpid = wpid
        self.via_receiver = via_receiver
        self.protocol: tuple[int, int] | None = None
        self._idx: dict[int, int] = {ROOT: 0}      # feature id -> índice
        self._ids: dict[int, int] = {0: ROOT}      # índice -> feature id
        self.feature_versions: dict[int, int] = {}
        self._enumerated = False
        self.listener: Callable[[int, int, bytes], None] | None = None  # (feature_id, event, params)

    # --- root ---
    def ping(self, timeout: float | None = None) -> tuple[int, int]:
        """Retorna a versão do protocolo. HID++ 1.0 devolve erro 'invalid sub id' -> (1, 0)."""
        try:
            r = self.channel.request_v2(self.index, 0, 1, b"\x00\x00\xa5", timeout=timeout)
        except m.Hidpp10Error as e:
            if e.code == 0x01:
                self.protocol = (1, 0)
                return self.protocol
            raise
        self.protocol = (r[0], r[1])
        return self.protocol

    def get_feature(self, feature_id: int) -> tuple[int, int, int] | None:
        """Root fn0: (índice, tipo, versão) ou None se ausente."""
        r = self.channel.request_v2(self.index, 0, 0, feature_id.to_bytes(2, "big"))
        if r[0] == 0:
            return None
        return r[0], r[1], r[2]

    def feature_index(self, feature_id: int) -> int | None:
        if feature_id in self._idx:
            return self._idx[feature_id]
        if self._enumerated:
            return None  # cache negativo: o featureset já listou tudo
        info = self.get_feature(feature_id)
        if info is None:
            return None
        self._idx[feature_id] = info[0]
        self._ids[info[0]] = feature_id
        self.feature_versions[feature_id] = info[2]
        return info[0]

    def has_feature(self, feature_id: int) -> bool:
        return self.feature_index(feature_id) is not None

    def enumerate_features(self) -> dict[int, int]:
        """Usa a feature 0x0001 para listar tudo. Retorna {feature_id: índice}."""
        idx = self.feature_index(FEATURE_SET)
        if idx is None:
            return dict(self._idx)
        count = self.channel.request_v2(self.index, idx, 0)[0]
        for i in range(1, count + 1):
            r = self.channel.request_v2(self.index, idx, 1, bytes([i]))
            fid = int.from_bytes(r[0:2], "big")
            self._idx[fid] = i
            self._ids[i] = fid
            self.feature_versions[fid] = r[3]
        self._enumerated = True
        return dict(self._idx)

    @property
    def feature_ids(self) -> list[int]:
        return sorted(self._idx)

    def call(self, feature_id: int, function: int, params: bytes = b"") -> bytes:
        idx = self.feature_index(feature_id)
        if idx is None:
            raise FeatureNotSupported(f"feature 0x{feature_id:04x} ausente")
        return self.channel.request_v2(self.index, idx, function, params)

    # --- 0x0003 ---
    def unit_id(self) -> str | None:
        if not self.has_feature(DEVICE_INFO):
            return None
        r = self.call(DEVICE_INFO, 0)
        return r[1:5].hex().upper()

    def model_ids(self) -> list[int]:
        """IDs de modelo (u16) por transporte, da 0x0003; zeros omitidos."""
        if not self.has_feature(DEVICE_INFO):
            return []
        r = self.call(DEVICE_INFO, 0)
        ids = [int.from_bytes(r[7 + 2 * i:9 + 2 * i], "big") for i in range(3)]
        return [i for i in ids if i]

    # --- notificações ---
    def handle_notification(self, msg: m.Message) -> None:
        fid = self._ids.get(msg.feature_index)
        if msg.sw_id != 0 or fid is None or self.listener is None:
            return
        self.listener(fid, msg.function, msg.params)
