"""Retentativa com backoff, isolamento de falhas por dispositivo e callbacks GLib resilientes."""
import time

from gi.repository import GLib

from openmacros.daemon import hidpp_backend as hb
from openmacros.daemon.actions import ActionExecutor, NullBackend
from openmacros.daemon.config import Config
from openmacros.daemon.manager import Manager
from openmacros.hidpp import messages as m
from openmacros.hidpp.fake import SimulatedDevice
from openmacros.hidpp.transport import FakeTransport, HidrawInfo


def _mgr():
    return Manager(Config(None), ActionExecutor(NullBackend()))


def _sysfs(tmp_path, hid_id, name="hidraw0"):
    d = tmp_path / name / "device"
    d.mkdir(parents=True)
    (d / "uevent").write_text(f"HID_ID={hid_id}\nHID_NAME=T\n")
    (d / "report_descriptor").write_bytes(b"\x85\x11\x95\x13")


def _iterate(seconds, until):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        ctx.iteration(False)
        time.sleep(0.01)


def test_direct_device_retried_until_it_answers(tmp_path, monkeypatch):
    _sysfs(tmp_path, "0005:0000046D:0000B015")
    monkeypatch.setattr(hb, "CHANNEL_TIMEOUT", 0.05)
    monkeypatch.setattr(hb, "RETRY_DELAYS_MS", (50, 100, 100))
    sim = SimulatedDevice([0x0005], {0x0005: lambda fn, p: bytes([1]) if fn == 0 else b"X".ljust(16, b"\0")},
                          index=0xFF)
    attempts = []

    def factory(path):
        attempts.append(path)
        # as duas primeiras vezes o mouse ainda não responde (Easy-Switch acabou de voltar)
        return FakeTransport(sim.respond if len(attempts) >= 3 else None)
    monkeypatch.setattr(hb, "HidrawTransport", factory)
    monkeypatch.setattr(hb.os.path, "exists", lambda p: True)
    mgr = _mgr()
    be = hb.HidppBackend(mgr, str(tmp_path))
    monkeypatch.setattr(hb, "enumerate_hidraw", lambda sysfs: [HidrawInfo("/dev/hidraw0", 5, 0x46D, 0xB015, "T", True)])
    be.scan()
    assert not mgr.devices and "/dev/hidraw0" not in be.entries  # primeira tentativa falhou e fechou tudo
    _iterate(3, lambda: mgr.devices)
    assert len(mgr.devices) == 1 and len(attempts) == 3
    assert "/dev/hidraw0" in be.entries
    be.close()


def test_gives_up_after_backoff(tmp_path, monkeypatch):
    monkeypatch.setattr(hb, "CHANNEL_TIMEOUT", 0.02)
    monkeypatch.setattr(hb, "RETRY_DELAYS_MS", (20, 20, 20))
    n = []
    monkeypatch.setattr(hb, "HidrawTransport", lambda p: (n.append(1), FakeTransport(None))[1])
    monkeypatch.setattr(hb.os.path, "exists", lambda p: True)
    info = HidrawInfo("/dev/hidraw0", 5, 0x46D, 0xB015, "T", True)
    monkeypatch.setattr(hb, "enumerate_hidraw", lambda sysfs: [info])
    be = hb.HidppBackend(_mgr())
    be.scan()
    _iterate(2, lambda: "/dev/hidraw0" in be._gave_up)
    assert len(n) == 4 and "/dev/hidraw0" in be._gave_up and not be.entries
    be.scan()  # não tenta de novo enquanto o nó existir
    assert len(n) == 4


def test_one_failing_device_does_not_drop_receiver(monkeypatch):
    sims = {1: SimulatedDevice([], index=1), 2: SimulatedDevice([], index=2)}

    def responder(raw):
        msg = m.parse(raw)
        if msg.device_index == 0xFF:  # registros do receptor
            body = bytes(16) if msg.sub_id == 0x83 else b"\x00\x09\x00"
            rid = m.LONG if msg.sub_id == 0x83 else m.SHORT
            return [m.Message(rid, 0xFF, msg.sub_id, msg.address, body[:3 if rid == m.SHORT else 16]).to_bytes()]
        sim = sims.get(msg.device_index)
        return sim.respond(raw) if sim else [bytes([0x10, msg.device_index, 0x8F, 0, msg.byte3, 0x09, 0])]

    calls = []
    real_refresh = hb.RealDevice.refresh

    def refresh(self):
        calls.append(self.dev.index)
        if self.dev.index == 1:
            raise m.Hidpp20Error(4)
        self.id, self._d, self.online = "logi:TWO", {"name": "B", "controls": [], "settings": {}}, True
    monkeypatch.setattr(hb.RealDevice, "refresh", refresh)
    mgr = _mgr()
    be = hb.HidppBackend(mgr)
    tr = FakeTransport(responder)
    be.attach(HidrawInfo("/dev/hidraw9", 3, 0x46D, 0xC52B, "R", True), tr)
    assert calls == [1, 2]
    assert "logi:TWO" in mgr.devices and "/dev/hidraw9" in be.entries and not tr.closed
    monkeypatch.setattr(hb.RealDevice, "refresh", real_refresh)


def test_on_readable_never_raises_and_drop_on_close(monkeypatch):
    be = hb.HidppBackend(_mgr())
    tr = FakeTransport(None)
    entry = hb._Entry(HidrawInfo("/dev/x", 3, 0x46D, 0xB015, "T", True), tr, None)
    be.entries["/dev/x"] = entry

    class Boom:
        def pump(self):
            raise ValueError("bug")
    entry.channel = Boom()
    assert be._on_readable(0, GLib.IOCondition.IN, entry) is True  # mantém a fonte

    from openmacros.hidpp.transport import TransportClosed

    class Gone:
        def pump(self):
            raise TransportClosed("sumiu")
    entry.channel = Gone()
    assert be._on_readable(0, GLib.IOCondition.IN, entry) is False
    assert "/dev/x" not in be.entries and tr.closed
