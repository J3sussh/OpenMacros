"""Dispositivo HID++ 2.0 simulado para testes (responde a um FakeTransport)."""

from __future__ import annotations

from typing import Callable

from . import messages as m

Handler = Callable[[int, bytes], bytes]  # (function, params) -> params de resposta


class SimulatedDevice:
    """Implementa root (0x0000) e featureset (0x0001); demais features via handlers.

    `features` é a lista ordenada de IDs a partir do índice 1.
    """

    def __init__(self, features: list[int], handlers: dict[int, Handler] | None = None,
                 index: int = 1, protocol: tuple[int, int] = (4, 2),
                 versions: dict[int, int] | None = None):
        self.index = index
        self.protocol = protocol
        self.features = [0x0001, *[f for f in features if f != 0x0001]]
        self.handlers = handlers or {}
        self.versions = versions or {}
        self.received: list[tuple[int, int, bytes]] = []  # (feature_id, fn, params)

    def _fid_at(self, idx: int) -> int | None:
        return self.features[idx - 1] if 1 <= idx <= len(self.features) else None

    def respond(self, raw: bytes) -> list[bytes]:
        msg = m.parse(raw)
        if msg.device_index != self.index:
            return []
        fn, sw, idx = msg.function, msg.sw_id, msg.feature_index

        def reply(params: bytes) -> list[bytes]:
            return [m.encode_v2(self.index, idx, fn, sw, params)]

        def err(code: int) -> list[bytes]:
            return [m.Message(m.LONG, self.index, 0xFF, idx, bytes([fn << 4 | sw, code])).to_bytes()]

        if idx == 0:
            if fn == 0:
                fid = int.from_bytes(msg.params[:2], "big")
                if fid == 0:
                    return reply(bytes([0, 0, 0]))
                if fid in self.features:
                    return reply(bytes([self.features.index(fid) + 1, 0, self.versions.get(fid, 0)]))
                return reply(bytes([0, 0, 0]))
            if fn == 1:
                return reply(bytes([self.protocol[0], self.protocol[1], msg.params[2]]))
            return err(7)
        fid = self._fid_at(idx)
        if fid is None:
            return err(6)
        if fid == 0x0001:
            if fn == 0:
                return reply(bytes([len(self.features)]))
            if fn == 1:
                f = self._fid_at(msg.params[0])
                if f is None:
                    return err(2)
                return reply(f.to_bytes(2, "big") + bytes([0, self.versions.get(f, 0)]))
            return err(7)
        self.received.append((fid, fn, msg.params))
        h = self.handlers.get(fid)
        if h is None:
            return err(7)
        try:
            return reply(h(fn, msg.params))
        except KeyError:
            return err(7)

    def notify(self, fid: int, function: int, params: bytes) -> bytes:
        idx = self.features.index(fid) + 1
        return m.encode_v2(self.index, idx, function, 0, params)
