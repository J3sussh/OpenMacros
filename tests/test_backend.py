"""HidppBackend/RealDevice contra um dispositivo HID++ simulado (sem hardware)."""
import json

from openmacros.daemon.actions import ActionExecutor, NullBackend
from openmacros.daemon.config import Config
from openmacros.daemon.hidpp_backend import HidppBackend
from openmacros.daemon.manager import Manager
from openmacros.hidpp import messages as m
from openmacros.hidpp.fake import SimulatedDevice
from openmacros.hidpp.transport import FakeTransport, HidrawInfo

NAME = b"M720 Triathlon"
CTRL = {0: bytes.fromhex("0052003a7100020301"), 1: bytes.fromhex("00d000ad7100020301")}


def make_sim():
    state = {"mode": 0x03}

    def reprog_h(fn, p):
        if fn == 0:
            return bytes([2])
        if fn == 1:
            return CTRL[p[0]]
        return p

    handlers = {
        0x0003: lambda fn, p: bytes([1, 0x1A, 0x2B, 0x3C, 0x4D]),
        0x0005: lambda fn, p: (bytes([len(NAME)]) if fn == 0 else
                               NAME[p[0]:p[0] + 16].ljust(16, b"\0") if fn == 1 else b"\x03"),
        0x1000: lambda fn, p: bytes([50, 30, 0]),
        0x1814: lambda fn, p: bytes([3, 1]),
        0x1B04: reprog_h,
        0x2205: lambda fn, p: b"\x01\x00" if fn == 0 else p,
        0x2121: lambda fn, p: bytes([state["mode"]]) if fn == 1 else p,
    }
    return SimulatedDevice([0x0003, 0x0005, 0x1000, 0x1814, 0x1B04, 0x2205, 0x2121], handlers, index=0xFF)


def test_backend_with_direct_device(tmp_path):
    sim = make_sim()
    tr = FakeTransport(sim.respond)
    mgr = Manager(Config(None), ActionExecutor(NullBackend()))
    be = HidppBackend(mgr)
    be.attach(HidrawInfo("/dev/fake", 0x0005, 0x046D, 0xB015, "M720", True), tr)
    d = json.loads(mgr.get_devices())[0]
    assert d["id"] == "logi:1A2B3C4D"
    assert d["name"] == "M720 Triathlon" and d["connection"] == "bluetooth" and d["layout"] == "m720"
    assert d["battery"]["level"] == 50
    assert [c["cid"] for c in d["controls"]] == [0x52, 0xD0]
    assert d["controls"][1]["raw_xy"] and d["controls"][1]["default_task"] == 0xAD
    assert d["settings"]["pointer_speed"]["value"] == 256
    assert d["settings"]["hires_scroll"]["value"] is True
    assert d["hosts"] == {"count": 3, "current": 1}

    # atribuir gestos grava exatamente 00 D0 33 00 00 00
    mgr.set_assignment(d["id"], 0xD0, json.dumps({"type": "gestures"}))
    assert sim.received[-1][:2] == (0x1B04, 3)
    assert sim.received[-1][2][:6] == bytes.fromhex("00D033000000")

    # notificação de KeyReport chega ao roteador
    seen = []
    mgr.executor.perform = lambda ev: seen.append(ev)
    tr.push(sim.notify(0x1B04, 0, bytes.fromhex("00D0")))
    tr.push(sim.notify(0x1B04, 1, bytes.fromhex("0000" "0000")))
    tr.push(sim.notify(0x1B04, 0, b""))
    be.entries["/dev/fake"].channel.pump()
    assert [e.kind for e in seen] == ["trigger"] and seen[0].action["type"] == "default"
    assert sim.received[-1][0] == 0x1B04
