"""0x1814 Change Host e 0x1815 Hosts Info (Easy-Switch)."""

from __future__ import annotations

from .. import messages as m
from ..device import Device
from ..transport import TransportClosed

ID_CHANGE, ID_INFO = 0x1814, 0x1815


def get_hosts(dev: Device) -> dict | None:
    """{"count": n, "current": i} (0-based) ou None."""
    if dev.has_feature(ID_CHANGE):
        r = dev.call(ID_CHANGE, 0)
        return {"count": r[0], "current": r[1]}
    if dev.has_feature(ID_INFO):
        r = dev.call(ID_INFO, 0)
        return {"count": r[1], "current": r[2]}
    return None


def host_names(dev: Device, count: int) -> list[str] | None:
    """0x1815 fn1 getHostInfo(i) -> [i, status, bustype, ?, nameLen...]; fn4 getHostName(i, offset).
    Melhor esforço: devolve None se algo falhar."""
    if not dev.has_feature(ID_INFO):
        return None
    names = []
    try:
        for i in range(count):
            info = dev.call(ID_INFO, 1, bytes([i]))
            name_len = info[5] if len(info) > 5 else 0
            out = b""
            while len(out) < name_len:
                r = dev.call(ID_INFO, 4, bytes([i, len(out)]))
                chunk = r[2:]
                if not chunk.rstrip(b"\x00"):
                    break
                out += chunk
            names.append(out[:name_len].decode("utf-8", "replace"))
    except m.HidppError:
        return None
    return names if any(names) else None  # firmware do M720 devolve nomes vazios


def label_current(names: list[str] | None, hosts_info: dict, local_name: str) -> list[str]:
    """Nomes por canal, com o canal atual rotulado como esta máquina: se o dispositivo está conectado
    aqui, o host do canal em uso é este computador. Canais sem nome ficam "" (a UI mostra "Computador N")."""
    count, cur = hosts_info["count"], hosts_info.get("current")
    out = (list(names or []) + [""] * count)[:count]
    if isinstance(cur, int) and 0 <= cur < count and not out[cur]:
        out[cur] = local_name
    return out


def change_host(dev: Device, host: int) -> None:
    """Dispara a troca; o dispositivo costuma desconectar sem responder (timeout ou hidraw
    fechado são o resultado esperado, sobretudo no Bluetooth)."""
    idx = dev.feature_index(ID_CHANGE)
    if idx is None:
        raise m.HidppError("Change Host (0x1814) ausente")
    try:
        dev.channel.request_v2(dev.index, idx, 1, bytes([host]), timeout=0.3)
    except (m.HidppTimeout, TransportClosed):
        pass
