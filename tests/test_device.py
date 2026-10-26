import pytest

from clique.hidpp import messages as m
from clique.hidpp.device import FeatureNotSupported
from clique.hidpp.features import battery, hosts, names, pointer, smartshift, wheel, dpi


def test_ping_and_featureset(make_device):
    dev, sim, tr, ch = make_device([0x0003, 0x0005, 0x1000, 0x1B04, 0x2205])
    assert dev.ping() == (4, 2)
    feats = dev.enumerate_features()
    assert feats[0x0000] == 0 and feats[0x0001] == 1
    assert feats[0x0003] == 2 and feats[0x1B04] == 5 and feats[0x2205] == 6
    assert dev.feature_ids == [0x0000, 0x0001, 0x0003, 0x0005, 0x1000, 0x1B04, 0x2205]
    assert dev.has_feature(0x1B04)
    assert not dev.has_feature(0x2201)


def test_feature_cache_avoids_roundtrips(make_device):
    dev, sim, tr, ch = make_device([0x1000])
    dev.feature_index(0x1000)
    n = len(tr.written)
    dev.feature_index(0x1000)
    assert len(tr.written) == n


def test_missing_feature_call(make_device):
    dev, *_ = make_device([0x1000])
    with pytest.raises(FeatureNotSupported):
        dev.call(0x2201, 0)


def test_hidpp20_error_raised(make_device):
    dev, *_ = make_device([0x1000], handlers={})  # sem handler -> erro 7
    with pytest.raises(m.Hidpp20Error) as ei:
        dev.call(0x1000, 0)
    assert ei.value.code == 7


def test_ping_hidpp10_device():
    from clique.hidpp.channel import Channel
    from clique.hidpp.device import Device
    from clique.hidpp.transport import FakeTransport

    def responder(raw):
        req = m.parse(raw)
        return [bytes([0x10, req.device_index, 0x8F, req.byte2, req.byte3, 0x01, 0x00])]
    dev = Device(Channel(FakeTransport(responder), timeout=0.2), 2)
    assert dev.ping() == (1, 0)


def test_timeout(make_device):
    dev, *_ = make_device([])
    dev.channel.transport.responder = None
    with pytest.raises(m.HidppTimeout):
        dev.ping()


def test_name_and_type(make_device):
    name = b"M720 Triathlon"
    handlers = {0x0005: lambda fn, p: (bytes([len(name)]) if fn == 0 else
                                       name[p[0]:p[0] + 16].ljust(16, b"\0") if fn == 1 else b"\x03")}
    dev, *_ = make_device([0x0005], handlers)
    assert names.get_name(dev) == "M720 Triathlon"
    assert names.get_type(dev) == "mouse"


def test_battery_variants(make_device):
    dev, *_ = make_device([0x1000], {0x1000: lambda fn, p: bytes([50, 30, 0])})
    assert battery.read(dev) == {"level": 50, "status": "discharging", "approximate": True}
    dev2, *_ = make_device([0x1004], {0x1004: lambda fn, p: bytes([80, 4, 1])})
    assert battery.read(dev2)["status"] == "charging"


def test_hosts(make_device):
    dev, *_ = make_device([0x1814], {0x1814: lambda fn, p: bytes([3, 1])})
    assert hosts.get_hosts(dev) == {"count": 3, "current": 1}
    hosts.change_host(dev, 2)  # sem resposta é tolerado


def test_change_host_bytes(make_device):
    dev, sim, tr, ch = make_device([0x1814], {0x1814: lambda fn, p: b""})
    hosts.change_host(dev, 2)
    assert sim.received[-1] == (0x1814, 1, bytes([2]) + bytes(15))


def test_wheel_read_modify_write(make_device):
    state = {"mode": 0x01}

    def h(fn, p):
        if fn == 1:
            return bytes([state["mode"]])
        state["mode"] = p[0]
        return bytes([p[0]])
    dev, *_ = make_device([0x2121], {0x2121: h})
    wheel.set_flag(dev, wheel.M_INVERT, True)
    wheel.set_flag(dev, wheel.M_HIRES, True)
    assert state["mode"] == 0x07  # target preservado
    assert wheel.read(dev) == {"hires_scroll": {"value": True}, "scroll_invert": {"value": True}}


def test_pointer_and_dpi(make_device):
    dev, *_ = make_device([0x2205], {0x2205: lambda fn, p: (b"\x01\x00" if fn == 0 else p[:2])})
    assert pointer.read(dev)["pointer_speed"]["value"] == 256
    assert dpi.parse_dpi_list(bytes([0x03, 0x20, 0xE0, 0x32, 0x03, 0xE8, 0, 0])) == [800, 850, 900, 950, 1000]
    assert dpi.parse_dpi_list(bytes([0x01, 0x90, 0x03, 0x20, 0, 0])) == [400, 800]


def test_smartshift(make_device):
    dev, sim, *_ = make_device([0x2110], {0x2110: lambda fn, p: bytes([2, 30, 0]) if fn == 0 else p})
    assert smartshift.read(dev) == {"smartshift": {"enabled": True, "threshold": 30}}
    smartshift.write(dev, True, 40)
    assert sim.received[-1][2][:3] == bytes([2, 40, 0])
    smartshift.write(dev, False, 40)
    assert sim.received[-1][2][:3] == bytes([2, 255, 0])


def test_notifications_dispatch(make_device):
    dev, sim, tr, ch = make_device([0x1B04])
    dev.enumerate_features()
    got = []
    dev.listener = lambda fid, fn, p: got.append((fid, fn, bytes(p[:4])))
    ch.notification_handler = lambda msg: dev.handle_notification(msg)
    tr.push(sim.notify(0x1B04, 0, bytes([0x00, 0xD0, 0, 0])))
    ch.pump()
    assert got == [(0x1B04, 0, bytes([0, 0xD0, 0, 0]))]


def test_notification_during_request_is_queued(make_device):
    dev, sim, tr, ch = make_device([0x1000], {0x1000: lambda fn, p: bytes([50, 0, 0])})
    dev.enumerate_features()
    got = []
    ch.notification_handler = got.append
    orig = tr.responder

    def responder(raw):
        out = list(orig(raw))
        return [sim.notify(0x1000, 0, b"\x10\x00\x00")] + out
    tr.responder = responder
    assert dev.call(0x1000, 0)[0] == 50
    assert len(got) == 1


def test_late_response_does_not_become_key_report(make_device):
    dev, sim, tr, ch = make_device([0x1B04])
    dev.enumerate_features()
    idx = dev._idx[0x1B04]
    got = []
    dev.listener = lambda fid, fn, p: got.append((fid, fn))
    ch.notification_handler = dev.handle_notification
    # resposta atrasada de getCount (fn0, sw_id 5): tem o mesmo formato de um evento KeyReport
    tr.push(m.encode_v2(1, idx, 0, 5, bytes([8])))
    ch.pump()
    assert got == []
    # mesmo que chegasse ao dispositivo, sw_id != 0 é ignorado
    dev.handle_notification(m.parse(m.encode_v2(1, idx, 0, 5, bytes([8]))))
    assert got == []
    tr.push(m.encode_v2(1, idx, 0, 6, bytes([8])))  # outra atrasada, antes da notificação real
    tr.push(sim.notify(0x1B04, 0, bytes([0, 0xD0])))  # notificação real (sw_id 0)
    ch.pump()
    assert got == [(0x1B04, 0)]


def test_negative_cache_after_enumeration(make_device):
    dev, sim, tr, ch = make_device([0x1000])
    dev.enumerate_features()
    n = len(tr.written)
    assert dev.feature_index(0x2201) is None
    assert len(tr.written) == n


def test_busy_error_is_retried(make_device):
    dev, sim, tr, ch = make_device([0x1000], {0x1000: lambda fn, p: bytes([7])})
    dev.enumerate_features()
    orig, state = sim.respond, {"n": 0}

    def responder(raw):
        msg = m.parse(raw)
        if msg.feature_index == dev._idx[0x1000] and state["n"] < 2:
            state["n"] += 1  # duas vezes 'busy' (código 8) e depois responde
            return [m.Message(m.LONG, 1, 0xFF, msg.feature_index, bytes([msg.byte3, 8])).to_bytes()]
        return orig(raw)
    tr.responder = responder
    assert dev.call(0x1000, 0)[0] == 7 and state["n"] == 2
