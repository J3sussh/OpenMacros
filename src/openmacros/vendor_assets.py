"""Importador local (opcional) de imagens de dispositivos a partir de um arquivo que o próprio
usuário baixou (instalador offline oficial ``logioptionsplus_installer_offline.exe`` ou ``depots.zip``).

Regra legal: o repositório nunca contém imagens/dados da Logitech. Este módulo só lê o arquivo
escolhido pelo usuário e grava, para uso local, em ``$XDG_DATA_HOME/openmacros/vendor/<pid>/``
(padrão ``~/.local/share/openmacros/vendor``). Nada é redistribuído.

Formatos:
* ``.exe`` offline: contém um ZIP embutido (último EOCD ``PK\\x05\\x06``; início do ZIP =
  ``eocd - cd_size - cd_offset``). Lemos o ZIP por uma "view" com deslocamento, sem copiar.
* ZIP com arquivos ``*.depot``: ``u32 magic 0x20170110, u32 header_len, header JSON
  {"files":[{"name","mode"}]}``, depois ``u32 size + bytes`` por arquivo (lidos em streaming).
* ``logioptionsplus.depot`` -> ``data/devices/devices_initial.json`` mapeia PID -> depot.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import struct
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

DEPOT_MAGIC = 0x20170110
EOCD_SIG = b"PK\x05\x06"
LFH_SIG = b"PK\x03\x04"
MAIN_DEPOT = "logioptionsplus.depot"
DEVICES_JSON = "data/devices/devices_initial.json"

MAX_JSON = 64 * 1024 * 1024
MAX_IMAGE = 32 * 1024 * 1024
_IMAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.webp$")
_JSON_KEEP = ("manifest.json", "metadata.json")

Progress = Callable[[int, int, str], None]


class VendorError(Exception):
    """Erro legível (arquivo inválido, formato desconhecido, etc.)."""


class Cancelled(VendorError):
    pass


# ---------------------------------------------------------------- caminhos

def vendor_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "openmacros" / "vendor"


def migrate_legacy_vendor() -> bool:
    """Migração única do nome antigo (Clique): copia ``~/.local/share/clique`` para ``.../openmacros`` se o novo
    não existir. O diretório antigo é preservado."""
    from .migrate import migrate_legacy_dir
    new = vendor_dir().parent
    return migrate_legacy_dir(new.with_name("clique"), new)


def vendor_pid_dir(pid: str, root: Path | None = None) -> Path:
    pid = pid.lower()
    if not re.fullmatch(r"[0-9a-f]{4}", pid):
        raise ValueError(f"PID inválido: {pid!r}")
    return (root or vendor_dir()) / pid


# ---------------------------------------------------------------- ZIP embutido

class OffsetFile(io.RawIOBase):
    """Janela [start, end) de um arquivo, vista como um arquivo que começa em 0."""

    def __init__(self, raw, start: int, end: int):
        super().__init__()
        self._raw, self._start, self._end = raw, start, end
        self._pos = 0

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        length = self._end - self._start
        if whence == io.SEEK_SET:
            pos = offset
        elif whence == io.SEEK_CUR:
            pos = self._pos + offset
        else:
            pos = length + offset
        self._pos = max(0, pos)
        return self._pos

    def readinto(self, b):
        remaining = self._end - self._start - self._pos
        if remaining <= 0:
            return 0
        n = min(len(b), remaining)
        self._raw.seek(self._start + self._pos)
        data = self._raw.read(n)
        b[:len(data)] = data
        self._pos += len(data)
        return len(data)


def find_embedded_zip(raw, size: int, max_candidates: int = 64) -> tuple[int, int]:
    """Procura, de trás para frente, o último EOCD válido. Retorna (start, end) do ZIP."""
    chunk = 1 << 20
    pos_end = size
    tried = 0
    carry = b""
    while pos_end > 0 and tried < max_candidates:
        pos_start = max(0, pos_end - chunk)
        raw.seek(pos_start)
        buf = raw.read(pos_end - pos_start) + carry
        idx = len(buf)
        while True:
            idx = buf.rfind(EOCD_SIG, 0, idx)
            if idx < 0:
                break
            eocd_off = pos_start + idx
            tried += 1
            rec = _check_eocd(raw, size, eocd_off)
            if rec:
                return rec
            if tried >= max_candidates:
                break
        carry = buf[:3]
        pos_end = pos_start
    raise VendorError("Nenhum ZIP válido encontrado no arquivo (esperado: instalador offline ou depots.zip).")


def _check_eocd(raw, size: int, eocd_off: int) -> tuple[int, int] | None:
    raw.seek(eocd_off)
    head = raw.read(22)
    if len(head) < 22:
        return None
    _sig, _d, _cd, _n1, _n2, cd_size, cd_offset, clen = struct.unpack("<4s4H2LH", head)
    end = eocd_off + 22 + clen
    if end > size or cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF:
        return None
    start = eocd_off - cd_size - cd_offset
    if start < 0:
        return None
    raw.seek(start)
    if raw.read(4) != LFH_SIG:
        return None
    return start, end


class Archive:
    """Abre .exe (ZIP embutido) ou .zip. Use como gerenciador de contexto."""

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        try:
            self._raw = open(self.path, "rb")
        except OSError as e:
            raise VendorError(f"Não foi possível abrir o arquivo: {e.strerror or e}") from e
        try:
            size = os.fstat(self._raw.fileno()).st_size
            start, end = find_embedded_zip(self._raw, size)
            self._view = OffsetFile(self._raw, start, end)
            self.zip = zipfile.ZipFile(self._view)
        except zipfile.BadZipFile as e:
            self._raw.close()
            raise VendorError(f"ZIP inválido: {e}") from e
        except Exception:
            self._raw.close()
            raise

    def close(self) -> None:
        self.zip.close()
        self._raw.close()

    def __enter__(self): return self
    def __exit__(self, *a): self.close()

    def find(self, basename: str) -> str | None:
        for n in self.zip.namelist():
            if n == basename or n.rsplit("/", 1)[-1] == basename:
                return n
        return None


# ---------------------------------------------------------------- formato .depot

class _Limited:
    def __init__(self, f, size: int):
        self._f, self.size, self.left = f, size, size

    def read(self, n: int = -1) -> bytes:
        if n < 0 or n > self.left:
            n = self.left
        data = self._f.read(n)
        if len(data) < n:
            raise VendorError("depot truncado")
        self.left -= len(data)
        return data

    def drain(self) -> None:
        while self.left:
            self.read(min(self.left, 1 << 20))


def iter_depot(f) -> Iterator[tuple[str, _Limited]]:
    """Itera (nome, leitor) em streaming; o que não for lido é descartado ao avançar."""
    head = f.read(8)
    if len(head) < 8:
        raise VendorError("depot vazio")
    magic, hlen = struct.unpack("<II", head)
    if magic != DEPOT_MAGIC:
        raise VendorError(f"magic de depot inesperado: {magic:#x}")
    if hlen > 4 * 1024 * 1024:
        raise VendorError("cabeçalho de depot grande demais")
    try:
        header = json.loads(f.read(hlen))
        entries = [str(e["name"]) for e in header["files"]]
    except (ValueError, KeyError, TypeError) as e:
        raise VendorError(f"cabeçalho de depot inválido: {e}") from e
    for name in entries:
        raw = f.read(4)
        if len(raw) < 4:
            raise VendorError("depot truncado")
        (size,) = struct.unpack("<I", raw)
        lim = _Limited(f, size)
        yield name, lim
        lim.drain()


def read_depot_files(f, wanted: set[str] | None = None, max_size: int = MAX_JSON,
                     stop_when_found: bool = False) -> dict[str, bytes]:
    """Lê arquivos (por nome exato, ou por `wanted(name)` se for callable) de um depot em streaming."""
    out: dict[str, bytes] = {}
    for name, rd in iter_depot(f):
        if wanted is not None and name not in wanted:
            continue
        if rd.size > max_size:
            continue
        out[name] = rd.read()
        if stop_when_found and wanted is not None and wanted <= set(out):
            break
    return out


# ---------------------------------------------------------------- mapa de dispositivos

@dataclass(frozen=True)
class DeviceEntry:
    depot: str
    name: str
    model_id: str = ""
    pids: tuple[str, ...] = ()
    programmable: tuple[int, ...] = ()


def parse_devices_initial(data: bytes | str) -> dict[str, DeviceEntry]:
    """PID (hex minúsculo, 4 dígitos) -> DeviceEntry."""
    try:
        doc = json.loads(data)
        devices = doc["devices"]
    except (ValueError, KeyError, TypeError) as e:
        raise VendorError(f"devices_initial.json inválido: {e}") from e
    out: dict[str, DeviceEntry] = {}
    for dev in devices:
        depot = dev.get("depot")
        if not depot or not re.fullmatch(r"[A-Za-z0-9_.-]+", str(depot)):
            continue
        pids: list[str] = []
        for mode in dev.get("modes") or []:
            for itf in mode.get("interfaces") or []:
                m = re.fullmatch(r"046d_([0-9a-fA-F]{4})", str(itf.get("id", "")))
                if m and m.group(1).lower() not in pids:
                    pids.append(m.group(1).lower())
        prog = (dev.get("capabilities") or {}).get("specialKeys", {}).get("programmable") or []
        entry = DeviceEntry(str(depot), str(dev.get("displayName", "")), str(dev.get("modelId", "")),
                            tuple(pids), tuple(int(c) for c in prog if isinstance(c, int)))
        for pid in pids:
            out.setdefault(pid, entry)
    return out


def load_device_map(arc: Archive) -> dict[str, DeviceEntry]:
    name = arc.find(MAIN_DEPOT)
    if name is None:
        raise VendorError("O arquivo não contém logioptionsplus.depot (não parece ser o instalador offline).")
    with arc.zip.open(name) as f:
        files = read_depot_files(f, {DEVICES_JSON}, stop_when_found=True)
    if DEVICES_JSON not in files:
        raise VendorError("devices_initial.json não encontrado no depot principal.")
    return parse_devices_initial(files[DEVICES_JSON])


# ---------------------------------------------------------------- imagens / layout

def webp_size(data: bytes) -> tuple[int, int] | None:
    """Largura/altura de um WebP (VP8, VP8L, VP8X) sem dependências."""
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    kind = data[12:16]
    if kind == b"VP8X":
        w = 1 + int.from_bytes(data[24:27], "little")
        h = 1 + int.from_bytes(data[27:30], "little")
        return w, h
    if kind == b"VP8L" and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return w, h
    return None


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _side(label: dict | None, x_pct: float) -> str:
    """Posição do rótulo em relação ao marcador: label.x/y em {-1,0,1}."""
    lx, ly = (label or {}).get("x", 0), (label or {}).get("y", 0)
    if lx < 0:
        return "left"
    if lx > 0:
        return "right"
    if ly < 0:
        return "up"
    if ly > 0:
        return "down"
    return "right" if x_pct >= 50 else "left"


def build_layout(pid: str, display_name: str, metadata: dict, manifest: dict,
                 sizes: dict[str, tuple[int, int]]) -> dict:
    """Converte metadata.json + manifest.json do depot no layout.json do OpenMacros+.

    marker.x/y do metadata são porcentagens (0..100) da própria imagem (verificado sobrepondo
    os marcadores sobre side.webp); aqui viram frações 0..1."""
    resources: dict[str, str] = {}
    devs = manifest.get("devices") or []
    for res in (devs[0].get("resources") if devs else manifest.get("resources")) or []:
        if isinstance(res, dict) and "key" in res and "src" in res:
            resources[str(res["key"])] = str(res["src"])
    images = {i.get("key"): i for i in metadata.get("images") or [] if isinstance(i, dict)}

    def aspect(src: str | None, key: str) -> float:
        if src and src in sizes:
            w, h = sizes[src]
            return w / h
        o = (images.get(key) or {}).get("origin") or {}
        return float(o.get("width", 1)) / float(o.get("height", 1) or 1)

    def markers(key: str, cid_only: bool) -> list[dict]:
        out = []
        for a in (images.get(key) or {}).get("assignments") or []:
            mk = a.get("marker") or {}
            x, y = float(mk.get("x", 50)), float(mk.get("y", 50))
            slot = str(a.get("slotId", ""))
            m = re.search(r"_c(\d+)$", slot)
            item = {"x": round(_clamp01(x / 100), 4), "y": round(_clamp01(y / 100), 4),
                    "side": _side(a.get("label"), x)}
            if m:
                item["cid"] = int(m.group(1))
            elif cid_only:
                continue
            else:
                item["id"] = str(a.get("slotName", slot)).lower().replace("slot_name_", "")
            out.append(item)
        return out

    front = resources.get("device_image")
    buttons = resources.get("device_buttons_image")
    point = resources.get("device_point_scroll_image")
    layout: dict = {
        "version": 1, "name": pid, "display_name": display_name,
        "source": "importado localmente do Logi Options+ (imagens da Logitech)",
        "front": front, "front_aspect": aspect(front, "device_image"),
        "buttons": {"art": buttons, "aspect": aspect(buttons, "device_buttons_image"),
                    "markers": markers("device_buttons_image", True)},
        "point_scroll": {"art": point, "aspect": aspect(point, "device_point_scroll_image"),
                         "markers": markers("device_point_scroll_image", False)},
        "easy_switch": {k.replace("easy_switch_indicator_", ""): v for k, v in resources.items()
                        if k.startswith("easy_switch_indicator_")},
    }
    gest = {}
    for a in (images.get("device_gesture_buttons_image") or {}).get("assignments") or []:
        d = a.get("slotDir")
        mk = a.get("marker") or {}
        if d in ("click", "up", "down", "left", "right"):
            gest[d] = {"x": mk.get("x", 50) / 100, "y": mk.get("y", 50) / 100}
    if gest:
        layout["gestures"] = gest
    return layout


def extract_device_assets(arc: Archive, depot: str) -> dict[str, bytes]:
    """Lê do depot do dispositivo apenas imagens .webp (nomes simples) e manifest/metadata."""
    name = arc.find(f"{depot}.depot")
    if name is None:
        raise VendorError(f"depot {depot}.depot não encontrado no arquivo")
    out: dict[str, bytes] = {}
    with arc.zip.open(name) as f:
        for fname, rd in iter_depot(f):
            if fname in _JSON_KEEP and rd.size <= MAX_JSON:
                out[fname] = rd.read()
            elif _IMAGE_RE.match(fname) and rd.size <= MAX_IMAGE:
                out[fname] = rd.read()
    return out


@dataclass
class ImportResult:
    imported: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def import_assets(path: str | os.PathLike, pids: list[str] | None, progress: Progress | None = None,
                  root: Path | None = None, cancel: Callable[[], bool] | None = None) -> ImportResult:
    """Importa para ``root`` (padrão ``vendor_dir()``). ``pids=None`` importa todos."""
    root = root or vendor_dir()
    report = progress or (lambda *_: None)
    result = ImportResult()
    with Archive(path) as arc:
        report(0, 1, "Lendo o mapa de dispositivos…")
        dmap = load_device_map(arc)
        if pids is None:
            wanted = sorted(dmap)
        else:
            wanted = [p.lower() for p in pids]
            result.missing = [p for p in wanted if p not in dmap]
            wanted = [p for p in wanted if p in dmap]
        # agrupa PIDs por depot para ler cada depot uma vez
        by_depot: dict[str, list[str]] = {}
        for p in wanted:
            by_depot.setdefault(dmap[p].depot, []).append(p)
        total = len(by_depot)
        for i, (depot, plist) in enumerate(sorted(by_depot.items())):
            if cancel and cancel():
                raise Cancelled("Importação cancelada")
            report(i, total, f"Importando {dmap[plist[0]].name or depot}…")
            try:
                assets = extract_device_assets(arc, depot)
                _write_device(root, plist, dmap[plist[0]], assets)
            except VendorError:
                result.missing.extend(plist)
                continue
            result.imported.extend(plist)
        report(total, total, "Concluído")
    root.mkdir(parents=True, exist_ok=True)
    (root / "source.json").write_text(json.dumps({"path": str(path)}), encoding="utf-8")
    return result


def _write_device(root: Path, pids: list[str], entry: DeviceEntry, assets: dict[str, bytes]) -> None:
    try:
        metadata = json.loads(assets["metadata.json"])
        manifest = json.loads(assets["manifest.json"])
    except (KeyError, ValueError) as e:
        raise VendorError(f"metadados ausentes/inválidos em {entry.depot}") from e
    sizes = {n: s for n, d in assets.items() if n.endswith(".webp") and (s := webp_size(d))}
    root.mkdir(parents=True, exist_ok=True)
    for pid in pids:
        layout = build_layout(pid, entry.name, metadata, manifest, sizes)
        tmp = Path(tempfile.mkdtemp(prefix=f".{pid}-", dir=root))
        try:
            for name, data in assets.items():
                if name.endswith(".webp"):
                    (tmp / name).write_bytes(data)
            (tmp / "layout.json").write_text(json.dumps(layout, indent=1), encoding="utf-8")
            dest = vendor_pid_dir(pid, root)
            if dest.exists():
                shutil.rmtree(dest)
            os.replace(tmp, dest)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise


# ---------------------------------------------------------------- consulta / remoção

def load_vendor_layout(pid: str | None, root: Path | None = None) -> tuple[dict, Path] | None:
    """(layout_dict, pasta) se houver arte importada válida para o PID."""
    try:
        d = vendor_pid_dir(pid or "", root)
        data = json.loads((d / "layout.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return (data, d) if isinstance(data, dict) and data.get("version") == 1 else None


def saved_source(root: Path | None = None) -> str | None:
    try:
        return json.loads(((root or vendor_dir()) / "source.json").read_text(encoding="utf-8")).get("path")
    except (OSError, ValueError, AttributeError):
        return None


def imported_pids(root: Path | None = None) -> list[str]:
    r = root or vendor_dir()
    try:
        return sorted(p.name for p in r.iterdir() if (p / "layout.json").is_file())
    except OSError:
        return []


def remove_all(root: Path | None = None) -> None:
    shutil.rmtree(root or vendor_dir(), ignore_errors=True)
