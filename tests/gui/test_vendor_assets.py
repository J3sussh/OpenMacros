import io
import json
import os
import struct
import zipfile
from pathlib import Path

import pytest

from clique import vendor_assets as va

REAL = Path("/home/victor/re/logi-options/offline/depots.zip")


def make_depot(files: dict[str, bytes]) -> bytes:
    header = json.dumps({"files": [{"name": n, "mode": 33206} for n in files]}).encode()
    out = struct.pack("<II", va.DEPOT_MAGIC, len(header)) + header
    for data in files.values():
        out += struct.pack("<I", len(data)) + data
    return out


def fake_webp(w: int, h: int) -> bytes:
    bits = (w - 1) | ((h - 1) << 14)
    body = b"\x2f" + bits.to_bytes(4, "little") + b"\x00" * 8
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(body)) + b"WEBP" + b"VP8L" + struct.pack("<I", len(body)) + body


DEVICES = {"devices": [
    {"modelId": "6xyz", "displayName": "Mouse Teste", "depot": "mouse_teste",
     "modes": [{"interfaces": [{"type": "DEVIO", "id": "046d_aaaa"}]}, {"interfaces": [{"type": "DEVIO", "id": "046d_BBBB"}]}],
     "capabilities": {"specialKeys": {"programmable": [82, 83]}}},
    {"modelId": "7", "displayName": "Outro", "depot": "outro",
     "modes": [{"interfaces": [{"type": "DEVIO", "id": "046d_cccc"}]}]},
]}
METADATA = {"images": [
    {"key": "device_image", "origin": {"width": 100, "height": 100}},
    {"key": "device_buttons_image", "origin": {"width": 100, "height": 100}, "assignments": [
        {"slotId": "mouse-teste-xyz_c82", "marker": {"x": 66, "y": 14}, "label": {"x": 0, "y": -1}},
        {"slotId": "mouse-teste-xyz_c83", "marker": {"x": 28, "y": 55}, "label": {"x": -1, "y": 0}},
        {"slotId": "mouse-teste-xyz-left", "marker": {"x": 1, "y": 1}, "label": {"x": -1, "y": 0}}]},
    {"key": "device_point_scroll_image", "assignments": [
        {"slotId": "x_mouse_settings", "slotName": "SLOT_NAME_POINTER_SETTINGS", "marker": {"x": 78, "y": 50}, "label": {"x": 1}}]},
    {"key": "device_gesture_buttons_image", "assignments": [
        {"slotDir": "up", "marker": {"x": 45, "y": -23}}]},
]}
MANIFEST = {"devices": [{"modelId": "6xyz", "resources": [
    {"key": "device_image", "src": "front.webp"}, {"key": "device_buttons_image", "src": "side.webp"},
    {"key": "device_point_scroll_image", "src": "side.webp"},
    {"key": "easy_switch_indicator_1", "src": "easy_switch_indicator_1.webp"}]}]}


def build_zip(extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(va.MAIN_DEPOT, make_depot({
            "manifest.json": b"{}", "big.bin": os.urandom(5000),
            va.DEVICES_JSON: json.dumps(DEVICES).encode(), "later.bin": b"x" * 10}))
        z.writestr("mouse_teste.depot", make_depot({
            "front.webp": fake_webp(300, 400), "side.webp": fake_webp(200, 400),
            "easy_switch_indicator_1.webp": fake_webp(10, 10),
            "metadata.json": json.dumps(METADATA).encode(), "manifest.json": json.dumps(MANIFEST).encode(),
            "../evil.webp": b"nope", "sub/dir.webp": b"nope", "OnboardData.json": b"{}"}))
        z.writestr("outro.depot", make_depot({"metadata.json": b"{}"}))  # sem manifest -> falha tolerada
        for n, d in (extra or {}).items():
            z.writestr(n, d)
    return buf.getvalue()


@pytest.fixture
def zip_path(tmp_path):
    p = tmp_path / "depots.zip"
    p.write_bytes(build_zip())
    return p


@pytest.fixture
def exe_path(tmp_path):
    # "instalador": prefixo (PE falso) + ZIP + lixo final contendo um EOCD falso
    fake_eocd = va.EOCD_SIG + struct.pack("<4H2LH", 0, 0, 1, 1, 50, 99999, 0)
    p = tmp_path / "logioptionsplus_installer_offline.exe"
    p.write_bytes(b"MZ" + os.urandom(3000) + va.EOCD_SIG + b"\x00" * 18 + build_zip() + b"trailer" + fake_eocd + b"\x00" * 40)
    return p


def test_webp_size():
    assert va.webp_size(fake_webp(1228, 1920)) == (1228, 1920)
    assert va.webp_size(b"nope") is None


def test_parse_devices_initial():
    m = va.parse_devices_initial(json.dumps(DEVICES))
    assert set(m) == {"aaaa", "bbbb", "cccc"}
    assert m["bbbb"].depot == "mouse_teste" and m["aaaa"].programmable == (82, 83)
    with pytest.raises(va.VendorError):
        va.parse_devices_initial("{}")


def test_iter_depot_streaming_and_limits():
    blob = make_depot({"a": b"1234", "b": b"56"})
    got = {}
    for name, rd in va.iter_depot(io.BytesIO(blob)):
        if name == "b":
            got[name] = rd.read()  # "a" é descartado automaticamente
    assert got == {"b": b"56"}
    assert va.read_depot_files(io.BytesIO(blob), {"a"}, stop_when_found=True) == {"a": b"1234"}
    with pytest.raises(va.VendorError):
        list(va.iter_depot(io.BytesIO(b"\x00" * 16)))
    with pytest.raises(va.VendorError):
        list(va.iter_depot(io.BytesIO(blob[:-1])))  # truncado: o dreno do último falha ao avançar


def test_build_layout():
    sizes = {"front.webp": (300, 400), "side.webp": (200, 400)}
    lay = va.build_layout("aaaa", "Mouse Teste", METADATA, MANIFEST, sizes)
    assert lay["front"] == "front.webp" and lay["buttons"]["art"] == "side.webp"
    assert lay["buttons"]["aspect"] == 0.5 and lay["front_aspect"] == 0.75
    ms = {m["cid"]: m for m in lay["buttons"]["markers"]}
    assert set(ms) == {82, 83}  # slots de gesto/sem _cNN ignorados
    assert ms[82] == {"x": 0.66, "y": 0.14, "side": "up", "cid": 82}
    assert ms[83]["side"] == "left" and ms[83]["y"] == 0.55
    assert lay["point_scroll"]["markers"][0]["id"] == "pointer_settings"
    assert lay["easy_switch"] == {"1": "easy_switch_indicator_1.webp"}
    assert lay["gestures"]["up"]["y"] == -0.23


@pytest.mark.parametrize("which", ["zip", "exe"])
def test_import_pids(which, zip_path, exe_path, tmp_path):
    src = zip_path if which == "zip" else exe_path
    root = tmp_path / "vendor"
    calls = []
    res = va.import_assets(src, ["AAAA", "dddd"], progress=lambda *a: calls.append(a), root=root)
    assert res.imported == ["aaaa"] and res.missing == ["dddd"]
    d = root / "aaaa"
    assert sorted(p.name for p in d.iterdir()) == ["easy_switch_indicator_1.webp", "front.webp", "layout.json", "side.webp"]
    assert not (root / "evil.webp").exists() and not (tmp_path / "evil.webp").exists()
    layout, folder = va.load_vendor_layout("aaaa", root)
    assert folder == d and layout["buttons"]["aspect"] == 0.5
    assert va.load_vendor_layout("bbbb", root) is None
    assert va.saved_source(root) == str(src)
    assert calls and calls[-1][0] == calls[-1][1]


def test_import_all_tolerates_broken_depot(zip_path, tmp_path):
    root = tmp_path / "v"
    res = va.import_assets(zip_path, None, root=root)
    assert sorted(res.imported) == ["aaaa", "bbbb"] and res.missing == ["cccc"]
    assert va.imported_pids(root) == ["aaaa", "bbbb"]
    va.import_assets(zip_path, ["aaaa"], root=root)  # reimporta por cima
    va.remove_all(root)
    assert va.imported_pids(root) == []


def test_cancel(zip_path, tmp_path):
    with pytest.raises(va.Cancelled):
        va.import_assets(zip_path, None, root=tmp_path / "v", cancel=lambda: True)


def test_invalid_files(tmp_path):
    p = tmp_path / "x.exe"
    p.write_bytes(os.urandom(5000))
    with pytest.raises(va.VendorError):
        va.import_assets(p, ["aaaa"], root=tmp_path / "v")
    with pytest.raises(va.VendorError):
        va.import_assets(tmp_path / "nao-existe", ["aaaa"], root=tmp_path / "v")
    z = tmp_path / "semmain.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.depot", b"x")
    with pytest.raises(va.VendorError):
        va.import_assets(z, ["aaaa"], root=tmp_path / "v")


def test_vendor_dir_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert va.vendor_dir() == tmp_path / "clique" / "vendor"
    with pytest.raises(ValueError):
        va.vendor_pid_dir("../x")


@pytest.mark.skipif(not REAL.exists(), reason="depots.zip real ausente")
def test_real_archive_b015(tmp_path):
    root = tmp_path / "vendor"
    res = va.import_assets(REAL, ["b015"], root=root)
    assert res.imported == ["b015"]
    layout, d = va.load_vendor_layout("b015", root)
    assert {m["cid"] for m in layout["buttons"]["markers"]} == {82, 83, 86, 91, 93, 208}
    assert (d / "side.webp").stat().st_size > 1000 and (d / "front.webp").exists()
    assert 0.6 < layout["buttons"]["aspect"] < 0.7
