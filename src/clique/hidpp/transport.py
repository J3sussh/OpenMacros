"""Transporte hidraw (e FakeTransport para testes)."""

from __future__ import annotations

import errno
import glob
import os
import select
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable

LOGITECH_VID = 0x046D


class TransportClosed(OSError):
    """O dispositivo desapareceu ou o descritor foi fechado."""


class Transport(ABC):
    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, timeout: float) -> bytes | None:
        """Lê um relatório; None se esgotar o prazo (segundos)."""

    def fileno(self) -> int | None:
        return None

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class HidrawTransport(Transport):
    def __init__(self, path: str):
        self.path = path
        self._fd: int | None = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)

    def fileno(self) -> int | None:
        return self._fd

    def write(self, data: bytes) -> None:
        if self._fd is None:
            raise TransportClosed("fechado")
        try:
            n = os.write(self._fd, data)
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.EIO, errno.EBADF, errno.EPIPE):
                raise TransportClosed(str(e)) from e
            raise
        if n != len(data):
            raise OSError("escrita parcial no hidraw")

    def read(self, timeout: float) -> bytes | None:
        if self._fd is None:
            raise TransportClosed("fechado")
        poller = select.poll()
        poller.register(self._fd, select.POLLIN)
        try:
            events = poller.poll(max(0, int(timeout * 1000)))
        except InterruptedError:
            return None
        if not events:
            return None
        if events[0][1] & (select.POLLERR | select.POLLHUP | select.POLLNVAL) and not events[0][1] & select.POLLIN:
            raise TransportClosed("hidraw desconectado")
        try:
            data = os.read(self._fd, 64)
        except BlockingIOError:
            return None
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.EIO, errno.EBADF):
                raise TransportClosed(str(e)) from e
            raise
        if not data:
            raise TransportClosed("EOF")
        return data

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None


class FakeTransport(Transport):
    """Transporte em memória: `responder(bytes) -> iterable[bytes]` produz respostas."""

    def __init__(self, responder: Callable[[bytes], Iterable[bytes] | None] | None = None):
        self.responder = responder
        self.written: list[bytes] = []
        self._rx: deque[bytes] = deque()
        self.closed = False

    def push(self, raw: bytes) -> None:
        self._rx.append(bytes(raw))

    def write(self, data: bytes) -> None:
        if self.closed:
            raise TransportClosed("fechado")
        self.written.append(bytes(data))
        if self.responder:
            for r in self.responder(bytes(data)) or ():
                self._rx.append(bytes(r))

    def read(self, timeout: float) -> bytes | None:
        if self.closed:
            raise TransportClosed("fechado")
        return self._rx.popleft() if self._rx else None

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class HidrawInfo:
    path: str
    bus: int
    vid: int
    pid: int
    name: str
    has_hidpp: bool

    @property
    def is_bluetooth(self) -> bool:
        return self.bus == 0x0005


def _parse_uevent(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition("=")
        out[k] = v
    return out


def _report_ids(desc: bytes) -> set[int]:
    """Percorre os itens do descritor HID e coleta os Report IDs (item 0x85)."""
    ids: set[int] = set()
    i = 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:  # item longo: 0xFE, tamanho, tag, dados
            i += 3 + (desc[i + 1] if i + 1 < len(desc) else 0)
            continue
        size = (0, 1, 2, 4)[b & 0x03]
        if b & 0xFC == 0x84 and size == 1 and i + 1 < len(desc):
            ids.add(desc[i + 1])
        i += 1 + size
    return ids


def _descriptor_has_hidpp(desc: bytes) -> bool:
    # Report ID 0x11 (long). Bluetooth LE expõe só o long; receptores têm short também.
    return 0x11 in _report_ids(desc)


def enumerate_hidraw(sysfs: str = "/sys/class/hidraw", dev_dir: str = "/dev") -> list[HidrawInfo]:
    """Lista nós hidraw Logitech (vendor 046d) que expõem relatórios HID++."""
    found = []
    for entry in sorted(glob.glob(os.path.join(sysfs, "hidraw*"))):
        try:
            with open(os.path.join(entry, "device", "uevent"), encoding="utf-8", errors="replace") as f:
                uev = _parse_uevent(f.read())
            bus_s, vid_s, pid_s = uev["HID_ID"].split(":")
            bus, vid, pid = int(bus_s, 16), int(vid_s, 16), int(pid_s, 16)
        except (OSError, KeyError, ValueError):
            continue
        if vid != LOGITECH_VID:
            continue
        try:
            with open(os.path.join(entry, "device", "report_descriptor"), "rb") as f:
                has = _descriptor_has_hidpp(f.read())
        except OSError:
            has = False
        found.append(HidrawInfo(os.path.join(dev_dir, os.path.basename(entry)), bus, vid, pid,
                                uev.get("HID_NAME", ""), has))
    return found
