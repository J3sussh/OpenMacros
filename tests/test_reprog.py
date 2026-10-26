from clique.hidpp.features import reprog


def test_divert_rawxy_gesture_button_exact_bytes():
    assert reprog.encode_set_reporting(0xD0, divert=True, raw_xy=True) == bytes.fromhex("00D033000000")


def test_other_encodings():
    assert reprog.encode_set_reporting(0x53, divert=False) == bytes.fromhex("005302000000")
    assert reprog.encode_set_reporting(0xD0, divert=False, raw_xy=False) == bytes.fromhex("00D022000000")
    assert reprog.encode_set_reporting(0x52, divert=False, remap=0x53) == bytes.fromhex("005202005300")
    assert reprog.encode_set_reporting(0x52, divert=True, persist=True) == bytes.fromhex("00520F000000")
    assert reprog.encode_set_reporting(0x52) == bytes.fromhex("005200000000")


def test_set_reporting_on_the_wire(make_device):
    dev, sim, tr, ch = make_device([0x1B04], {0x1B04: lambda fn, p: p})
    reprog.ReprogControls(dev).set_reporting(0xD0, divert=True, raw_xy=True)
    fid, fn, params = sim.received[-1]
    assert (fid, fn) == (0x1B04, 3)
    assert params[:6] == bytes.fromhex("00D033000000")
    # relatório long, function 3 no nibble alto do byte 3
    assert tr.written[-1][0] == 0x11 and tr.written[-1][3] >> 4 == 3


def test_controls_info_and_reporting(make_device):
    infos = {0: bytes.fromhex("0052" "0052" "70" "00" "02" "03" "01"),
             1: bytes.fromhex("00D0" "009C" "71" "00" "02" "03" "01")}

    def h(fn, p):
        if fn == 0:
            return bytes([2])
        if fn == 1:
            return infos[p[0]]
        if fn == 2:
            return bytes.fromhex("00D0" "11" "0000" "00")
        raise KeyError
    dev, *_ = make_device([0x1B04], {0x1B04: h})
    rc = reprog.ReprogControls(dev)
    cs = rc.controls()
    assert [c.cid for c in cs] == [0x52, 0xD0]
    assert not cs[0].raw_xy and cs[1].raw_xy
    assert cs[0].raw_xy_capable
    assert cs[1].reprogrammable and cs[1].divertable and cs[1].tid == 0x9C
    r = rc.get_reporting(0xD0)
    assert r.divert and r.raw_xy and not r.persist and r.remap == 0


def test_events():
    assert reprog.parse_event(0, bytes.fromhex("00D000520000") + bytes(10)) == ("key_report", [0xD0, 0x52])
    assert reprog.parse_event(0, bytes(16)) == ("key_report", [])
    assert reprog.parse_event(1, bytes.fromhex("0005FFF6") + bytes(12)) == ("raw_xy", 5, -10)
    assert reprog.parse_event(7, bytes(16)) is None
