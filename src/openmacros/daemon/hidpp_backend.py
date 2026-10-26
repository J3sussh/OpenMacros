"""Dispositivos reais via hidraw: RealDevice e HidppBackend (integração com GLib)."""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass, field
from typing import Any

from ..hidpp import messages as m
from ..hidpp.channel import Channel
from ..hidpp.cids import cid_name
from ..hidpp.device import Device
from ..hidpp.features import battery, dpi, hosts, names, pointer, reprog, smartshift, wheel
from ..hidpp.receiver import Receiver, is_receiver
from ..hidpp.transport import (HidrawInfo, HidrawTransport, Transport, TransportClosed,
                               enumerate_hidraw)
from .manager import Manager, plan_reporting

log = logging.getLogger(__name__)


class RealDevice:
    def __init__(self, dev: Device, *, pid: int, connection: str, serial_hint: str = ""):
        self.dev = dev
        self.pid = pid
        self.connection = connection
        self.serial_hint = serial_hint
        self.online = False
        self.on_event = None
        self.id = ""
        self._d: dict = {}
        self._controls: dict[int, reprog.ControlInfo] = {}
        self.dev.listener = self._on_feature_event

    # --- inicialização / releitura ---
    def refresh(self) -> None:
        d = self.dev
        d.ping()
        d.enumerate_features()
        name = names.get_name(d) or "Dispositivo Logitech"
        kind = names.get_type(d)
        unit = d.unit_id()
        if not unit or not unit.strip("0"):  # ausente ou zerado: usa serial do receptor + índice
            unit = self.serial_hint or f"{(d.wpid or self.pid):04X}{d.index:02X}"
        wpid = d.wpid
        if wpid is None and self.connection == "receiver":
            ids = d.model_ids()  # ordem dos transportes não é garantida: melhor esforço
            wpid = ids[-1] if len(ids) > 1 else (ids[0] if ids else None)
        model = f"{(wpid or self.pid):04x}"
        self.id = f"logi:{unit}"
        data: dict[str, Any] = {
            "id": self.id, "name": name, "model_id": model, "kind": kind,
            "connection": self.connection, "online": True, "battery": None,
            "features": [f"0x{f:04x}" for f in d.feature_ids], "controls": [], "settings": {},
            "layout": ("m720" if "M720" in name
                       else "generic-keyboard" if kind == "keyboard" else "generic-mouse"),
        }
        self._d = data
        self._read_battery()
        self._read_controls()
        self._reset_diverts()
        self._read_settings()
        h = hosts.get_hosts(d)
        if h:
            h["names"] = hosts.label_current(hosts.host_names(d, h["count"]), h, socket.gethostname())
            data["hosts"] = h
        self.online = True

    def _read_battery(self) -> None:
        try:
            self._d["battery"] = battery.read(self.dev)
        except m.HidppError as e:
            log.debug("bateria: %s", e)

    def _read_controls(self) -> None:
        if not self.dev.has_feature(reprog.FEATURE_ID):
            return
        rc = reprog.ReprogControls(self.dev)
        out = []
        self._controls = {}
        for info in rc.controls():
            self._controls[info.cid] = info
            if info.virtual:  # sem botão físico: não expor na GUI
                continue
            out.append({"cid": info.cid, "name": cid_name(info.cid), "remappable": info.reprogrammable,
                        "divertable": info.divertable, "raw_xy": info.raw_xy, "default_task": info.tid})
        self._d["controls"] = out

    def _reset_diverts(self) -> None:
        """Limpa diverts herdados (ex.: daemon anterior caiu); o Manager reaplica a config depois."""
        if self._controls:
            try:
                reprog.ReprogControls(self.dev).reset_all()
            except m.HidppError as e:
                log.debug("reset_all: %s", e)

    def _read_settings(self) -> None:
        s: dict = {}
        d = self.dev
        for feat, reader in ((pointer.FEATURE_ID, pointer.read), (dpi.FEATURE_ID, dpi.read),
                             (wheel.FEATURE_ID, wheel.read)):
            if d.has_feature(feat):
                try:
                    s.update(reader(d))
                except m.HidppError as e:
                    log.debug("setting 0x%04x: %s", feat, e)
        try:
            ss = smartshift.read(d)
            if ss:
                s.update(ss)
        except m.HidppError:
            pass
        self._d["settings"] = s

    # --- ManagedDevice ---
    def describe(self) -> dict:
        d = dict(self._d)
        d["online"] = self.online
        return d

    def apply_control(self, cid: int, action: dict) -> None:
        divert, raw_xy, remap = plan_reporting(action)
        reprog.ReprogControls(self.dev).set_reporting(
            cid, divert=divert, raw_xy=raw_xy if self._controls[cid].raw_xy else None, remap=remap)

    def set_setting(self, key: str, value: Any) -> None:
        d = self.dev
        s = self._d["settings"]
        if key == "pointer_speed":
            pointer.set_speed(d, value)
            s[key]["value"] = value
        elif key == "dpi":
            dpi.set_dpi(d, value)
            s[key]["value"] = value
        elif key == "hires_scroll":
            wheel.set_flag(d, wheel.M_HIRES, value)
            s[key]["value"] = value
        elif key == "scroll_invert":
            wheel.set_flag(d, wheel.M_INVERT, value)
            s[key]["value"] = value
        elif key == "smartshift":
            smartshift.write(d, value["enabled"], value["threshold"])
            s[key] = dict(value)
        else:
            raise m.HidppError(f"chave desconhecida: {key}")

    def change_host(self, host: int) -> None:
        hosts.change_host(self.dev, host)
        self._d["hosts"]["current"] = host

    def reset_controls(self) -> None:
        reprog.ReprogControls(self.dev).reset_all()

    def close(self) -> None:
        self.online = False
        self.dev.listener = None

    # --- conectividade ---
    def set_online(self, online: bool) -> None:
        if online == self.online:
            return
        if online:
            try:
                self.refresh()
            except m.HidppError as e:
                log.warning("falha ao reler %s: %s", self.id, e)
                return
        else:
            self.online = False
        if self.on_event:
            self.on_event("online" if online else "offline")

    # --- eventos de feature ---
    def _on_feature_event(self, fid: int, function: int, params: bytes) -> None:
        if not self.on_event:
            return
        if fid == reprog.FEATURE_ID:
            ev = reprog.parse_event(function, params)
            if ev:
                self.on_event(*ev)
        elif fid in (battery.ID_STATUS, battery.ID_UNIFIED) and function == 0:
            self._d["battery"] = battery.parse(fid, params)
            self.on_event("updated")


CHANNEL_TIMEOUT = 1.0
RETRY_DELAYS_MS = (500, 2000, 5000)  # Easy-Switch de volta: o mouse demora a responder ao ping


@dataclass
class _Entry:
    info: HidrawInfo
    transport: Transport
    channel: Channel
    receiver: Receiver | None = None
    slots: dict[int, RealDevice] = field(default_factory=dict)
    watch: int = 0


class HidppBackend:
    """Descobre nós hidraw, integra a leitura ao GLib e faz hotplug."""

    def __init__(self, manager: Manager, sysfs: str = "/sys/class/hidraw"):
        self.manager = manager
        self.sysfs = sysfs
        self.entries: dict[str, _Entry] = {}
        self._gave_up: set[str] = set()          # sem permissão / esgotou tentativas, até o nó sumir
        self._retry: dict[str, int] = {}         # path -> fonte GLib de retentativa pendente
        self._attempts: dict[str, int] = {}

    # --- varredura ---
    def scan(self, manager: Manager | None = None) -> None:
        infos = {i.path: i for i in enumerate_hidraw(self.sysfs) if i.has_hidpp}
        for path in list(self.entries):
            if path not in infos:
                self._drop(path)
        for path in list(self._gave_up | set(self._attempts)):
            if path not in infos:
                self._forget(path)
        for path, info in infos.items():
            if path in self.entries or path in self._gave_up or path in self._retry:
                continue
            try:
                self._try_open(info)
            except Exception:
                log.exception("falha ao processar %s", path)

    def _forget(self, path: str) -> None:
        self._gave_up.discard(path)
        self._attempts.pop(path, None)
        src = self._retry.pop(path, 0)
        if src:
            _remove_source(src)

    def _try_open(self, info: HidrawInfo) -> None:
        path = info.path
        try:
            self.attach(info, HidrawTransport(path))
        except PermissionError:
            log.warning("sem permissão em %s (instale a regra udev)", path)
            self._gave_up.add(path)
            return
        except (m.HidppError, OSError) as e:
            n = self._attempts.get(path, 0)
            if n < len(RETRY_DELAYS_MS):
                self._attempts[path] = n + 1
                log.debug("%s sem resposta (%s); nova tentativa em %dms", path, e, RETRY_DELAYS_MS[n])
                from gi.repository import GLib
                self._retry[path] = GLib.timeout_add(RETRY_DELAYS_MS[n], self._retry_cb, info)
            else:
                log.debug("%s: desistindo (%s)", path, e)
                self._gave_up.add(path)
            return
        self._attempts.pop(path, None)

    def _retry_cb(self, info: HidrawInfo) -> bool:
        self._retry.pop(info.path, None)
        try:
            if os.path.exists(info.path) and info.path not in self.entries:
                self._try_open(info)
        except Exception:
            log.exception("falha na retentativa de %s", info.path)
        return False

    def attach(self, info: HidrawInfo, transport: Transport) -> _Entry:
        """Registra um transporte (também usado por testes com FakeTransport).
        Em falha do sondagem, fecha tudo e propaga o erro."""
        channel = Channel(transport, timeout=CHANNEL_TIMEOUT)
        entry = _Entry(info, transport, channel)
        self.entries[info.path] = entry
        channel.notification_handler = lambda msg, e=entry: self._on_notification(e, msg)
        try:
            self._probe(entry)
            fd = transport.fileno()
            if fd is not None:
                from gi.repository import GLib
                entry.watch = GLib.io_add_watch(
                    fd, GLib.PRIORITY_DEFAULT,
                    GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                    self._on_readable, entry)
        except BaseException:
            self._drop(info.path)  # fecha o fd e remove de entries
            raise
        return entry

    def _probe(self, entry: _Entry) -> None:
        info = entry.info
        if is_receiver(info.pid):
            rcv = Receiver(entry.channel, info.pid)
            entry.receiver = rcv
            try:
                rcv.enable_notifications()
            except (m.HidppError, OSError) as e:
                log.debug("receptor: notificações: %s", e)
            serial = rcv.serial() or ""
            for dev in rcv.enumerate_online():
                try:  # falha de UM dispositivo não derruba o receptor
                    self._register(entry, dev.index, dev, serial)
                except m.HidppError as e:
                    log.warning("dispositivo %d do receptor: %s", dev.index, e)
        else:
            dev = Device(entry.channel, m.DEVICE_INDEX_DIRECT)
            self._register(entry, dev.index, dev, "")

    def _register(self, entry: _Entry, index: int, dev: Device, serial: str) -> None:
        conn = "receiver" if entry.receiver else ("bluetooth" if entry.info.is_bluetooth else "usb")
        rd = entry.slots.get(index) or RealDevice(dev, pid=entry.info.pid, connection=conn,
                                                   serial_hint=f"{serial}{index}" if serial else "")
        rd.dev = dev
        dev.listener = rd._on_feature_event
        rd.refresh()
        entry.slots[index] = rd
        self.manager.add_device(rd)

    # --- E/S ---
    def _on_readable(self, fd, condition, entry: _Entry) -> bool:
        """Callback GLib: nunca propaga exceção (a fonte só some em desconexão)."""
        from gi.repository import GLib
        try:
            if condition & GLib.IOCondition.IN:
                entry.channel.pump()
            elif condition & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
                raise TransportClosed("hup")
        except TransportClosed:
            entry.watch = 0
            self._safe_drop(entry.info.path)
            return False
        except Exception:
            log.exception("erro ao ler %s", entry.info.path)
        return True

    def _safe_drop(self, path: str) -> None:
        try:
            self._drop(path)
        except Exception:
            log.exception("erro ao fechar %s", path)

    def _on_notification(self, entry: _Entry, msg: m.Message) -> None:
        if msg.is_receiver_notification and entry.receiver:
            ev = Receiver.parse_connection(msg)
            if ev is None:
                return
            slot = entry.slots.get(ev.index)
            if not ev.connected:
                if slot:
                    slot.set_online(False)
                return
            if slot:
                slot.set_online(True)
            else:
                dev = Device(entry.channel, ev.index, wpid=ev.wpid, via_receiver=True)
                if not dev.wpid:
                    info = entry.receiver.pairing_info(ev.index)
                    dev.wpid = info[0] if info else None
                try:
                    self._register(entry, ev.index, dev, entry.receiver.serial() or "")
                except m.HidppError as e:
                    log.warning("novo dispositivo %d: %s", ev.index, e)
            return
        slot = entry.slots.get(msg.device_index)
        if slot:
            slot.dev.handle_notification(msg)

    def _drop(self, path: str) -> None:
        entry = self.entries.pop(path, None)
        if not entry:
            return
        if entry.watch:
            _remove_source(entry.watch)
            entry.watch = 0
        try:
            for slot in entry.slots.values():
                slot.set_online(False)  # mantém no gerenciador como offline
        finally:
            entry.transport.close()

    def close(self) -> None:
        for p in list(self._retry):
            self._forget(p)
        for p in list(self.entries):
            self._safe_drop(p)


def _remove_source(src: int) -> None:
    from gi.repository import GLib
    GLib.source_remove(src)
