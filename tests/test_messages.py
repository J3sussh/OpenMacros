import pytest

from clique.hidpp import messages as m


def test_encode_v2_long_by_default():
    raw = m.encode_v2(1, 5, 3, 7, b"\x00\xd0")
    assert len(raw) == 20
    assert raw[:6] == bytes([0x11, 1, 5, 0x37, 0x00, 0xD0])


def test_encode_v2_short_and_very_long():
    assert len(m.encode_v2(1, 0, 1, 1, b"", min_report=m.SHORT)) == 7
    assert len(m.encode_v2(1, 0, 1, 1, bytes(17))) == 64
    with pytest.raises(ValueError):
        m.encode_v2(1, 0, 1, 1, bytes(61))


def test_encode_v1_short():
    raw = m.encode_v1(0xFF, 0x81, 0xB5, b"\x03")
    assert raw == bytes([0x10, 0xFF, 0x81, 0xB5, 0x03, 0, 0])


def test_parse_roundtrip():
    raw = m.encode_v2(2, 9, 4, 3, b"abc")
    msg = m.parse(raw)
    assert (msg.device_index, msg.feature_index, msg.function, msg.sw_id) == (2, 9, 4, 3)
    assert msg.params[:3] == b"abc"
    assert msg.to_bytes() == raw


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        m.parse(b"\x01\x02\x03\x04")
    with pytest.raises(ValueError):
        m.parse(b"\x11\x01\x00")


def test_error_v1():
    msg = m.parse(bytes([0x10, 1, 0x8F, 0x00, 0x11, 0x01, 0x00]))
    e = m.error_for(msg)
    assert isinstance(e, m.Hidpp10Error) and e.code == 1


def test_error_v2():
    msg = m.parse(bytes([0x11, 1, 0xFF, 4, 0x2A, 0x02]) + bytes(14))
    e = m.error_for(msg)
    assert isinstance(e, m.Hidpp20Error)
    assert (e.code, e.feature_index, e.function) == (2, 4, 2)
    assert m.error_matches_v2(msg, 1, 4, 2, 0xA)
    assert not m.error_matches_v2(msg, 1, 4, 2, 0xB)
