"""Canal request/response sobre um Transport, com fila de notificações."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable

from . import messages as m
from .transport import Transport, TransportClosed

log = logging.getLogger(__name__)
_INVALID: m.Message = m.Message(0, 0, 0, 0, b"")  # sentinela


def is_notification(msg: m.Message) -> bool:
    """Notificação de verdade: do receptor (0x40..0x7F) ou HID++ 2.0 com sw_id 0.
    Respostas atrasadas (sw_id != 0, registros/erros 0x80+) não podem virar eventos."""
    if msg.is_receiver_notification:
        return True
    return msg.byte2 < 0x40 and msg.sw_id == 0


class Channel:
    def __init__(self, transport: Transport, timeout: float = 1.5):
        self.transport = transport
        self.timeout = timeout
        self.notification_handler: Callable[[m.Message], None] | None = None
        self._sw = 0
        self._pending: deque[m.Message] = deque()
        self._dispatching = False

    def next_sw_id(self) -> int:
        self._sw = self._sw % 15 + 1  # 1..15; 0 é reservado a notificações
        return self._sw

    def _read_msg(self, timeout: float) -> m.Message | None:
        raw = self.transport.read(timeout)
        if raw is None:
            return None
        try:
            return m.parse(raw)
        except ValueError:
            return _INVALID  # ex.: relatórios de movimento do mouse (id 0x02) no mesmo hidraw

    def _wait(self, is_reply: Callable[[m.Message], bool], is_err: Callable[[m.Message], bool],
              timeout: float | None) -> m.Message:
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        try:
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise m.HidppTimeout("sem resposta")
                msg = self._read_msg(left)
                if msg is None or msg is _INVALID:
                    continue
                if is_err(msg):
                    raise m.error_for(msg)  # type: ignore[misc]
                if is_reply(msg):
                    return msg
                if msg.is_v2_error or msg.is_v1_error:
                    continue  # erro de outra requisição (atrasada)
                if not is_notification(msg):
                    continue  # resposta atrasada
                self._pending.append(msg)
        finally:
            self.dispatch_pending()

    def request_v2(self, device_index: int, feature_index: int, function: int,
                   params: bytes = b"", timeout: float | None = None) -> bytes:
        for attempt in range(4):
            sw = self.next_sw_id()
            self.transport.write(m.encode_v2(device_index, feature_index, function, sw, params))
            try:
                msg = self._wait(
                    lambda x: m.matches_v2(x, device_index, feature_index, function, sw),
                    lambda x: (m.error_matches_v2(x, device_index, feature_index, function, sw)
                               # dispositivo HID++ 1.0 responde com erro 0x8F ao pedido 2.0
                               or m.error_matches_v1(x, device_index, feature_index, function << 4 | sw)),
                    timeout)
                return msg.params
            except m.Hidpp20Error as e:
                if e.code != 8 or attempt == 3:  # 8 = busy: tenta de novo
                    raise
                time.sleep(0.05 * (attempt + 1))
        raise m.HidppTimeout("sem resposta")

    def request_v1(self, device_index: int, sub_id: int, address: int,
                   params: bytes = b"", timeout: float | None = None) -> bytes:
        self.transport.write(m.encode_v1(device_index, sub_id, address, params))
        msg = self._wait(
            lambda x: x.device_index == device_index and x.sub_id == sub_id and x.address == address,
            lambda x: m.error_matches_v1(x, device_index, sub_id, address),
            timeout)
        return msg.params

    def send_v2_no_reply(self, device_index: int, feature_index: int, function: int,
                         params: bytes = b"") -> None:
        self.transport.write(m.encode_v2(device_index, feature_index, function,
                                         self.next_sw_id(), params))

    def pump(self) -> None:
        """Lê tudo o que estiver disponível e despacha notificações. Levanta TransportClosed."""
        while True:
            msg = self._read_msg(0)
            if msg is None:
                break
            if msg is _INVALID:
                continue
            if is_notification(msg):
                self._pending.append(msg)
        self.dispatch_pending()

    def dispatch_pending(self) -> None:
        if self._dispatching:
            return
        self._dispatching = True
        try:
            while self._pending:
                msg = self._pending.popleft()
                if self.notification_handler:
                    try:
                        self.notification_handler(msg)
                    except TransportClosed:
                        raise
                    except Exception:
                        log.exception("erro ao tratar notificação")
        finally:
            self._dispatching = False
