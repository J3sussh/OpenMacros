from openmacros.hidpp.transport import FakeTransport, enumerate_hidraw


def _node(root, name, hid_id, desc):
    d = root / name / "device"
    d.mkdir(parents=True)
    (d / "uevent").write_text(f"HID_ID={hid_id}\nHID_NAME=Test\n")
    (d / "report_descriptor").write_bytes(desc)


def test_enumerate_filters_vendor_and_descriptor(tmp_path):
    hidpp = b"\x06\x00\xff\x85\x10\x95\x06\x85\x11\x95\x13"
    _node(tmp_path, "hidraw0", "0003:0000046D:0000C52B", b"\x05\x01\x09\x02")      # mouse comum
    _node(tmp_path, "hidraw1", "0003:0000046D:0000C52B", hidpp)                     # HID++
    _node(tmp_path, "hidraw2", "0003:00001234:00000001", hidpp)                     # outro vendor
    _node(tmp_path, "hidraw3", "0005:0000046D:0000B015", hidpp)                     # bluetooth
    infos = enumerate_hidraw(str(tmp_path), "/dev")
    assert [(i.path, i.pid, i.has_hidpp) for i in infos] == [
        ("/dev/hidraw0", 0xC52B, False), ("/dev/hidraw1", 0xC52B, True), ("/dev/hidraw3", 0xB015, True)]
    assert infos[2].is_bluetooth


def test_fake_transport_read_empty():
    assert FakeTransport().read(0) is None
