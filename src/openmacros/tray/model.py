"""Lógica pura da bandeja (sem GTK): ícone, rótulos e escolha do dispositivo de menor bateria."""

from __future__ import annotations

ICON_MISSING = "battery-missing-symbolic"
ICON_APP = "io.github.openmacros.App-symbolic"


def level_of(device: dict) -> int | None:
    bat = device.get("battery")
    if not isinstance(bat, dict) or not isinstance(bat.get("level"), (int, float)):
        return None
    return max(0, min(100, int(bat["level"])))


def lowest_battery(devices: list[dict]) -> dict | None:
    """Dispositivo online com a menor bateria conhecida (None se nenhum informa bateria)."""
    cand = [d for d in devices if d.get("online", True) and level_of(d) is not None]
    return min(cand, key=level_of) if cand else None


def battery_icon_name(device: dict | None) -> str:
    if device is None:
        return ICON_APP
    level = level_of(device)
    if level is None:
        return ICON_APP
    step = min(100, round(level / 10) * 10)
    status = str((device.get("battery") or {}).get("status", "")).lower()
    if status == "charging":
        return f"battery-level-{step}-charging-symbolic"
    return f"battery-level-{step}-symbolic"


def tray_icon(devices: list[dict] | None) -> str:
    """None = serviço fora do ar."""
    if devices is None:
        return ICON_MISSING
    return battery_icon_name(lowest_battery(devices))


def device_label(device: dict) -> str:
    name = str(device.get("name") or "Dispositivo").replace("Triathlon", "").strip() or "Dispositivo"
    if not device.get("online", True):
        return f"{name} — offline"
    level = level_of(device)
    if level is None:
        return name
    pre = "~" if (device.get("battery") or {}).get("approximate") else ""
    suffix = " (carregando)" if str((device.get("battery") or {}).get("status", "")).lower() == "charging" else ""
    return f"{name} — {pre}{level} %{suffix}"


def host_labels(device: dict) -> list[tuple[int, str, bool]]:
    """(índice 0-based, rótulo, é o atual) para o submenu Easy-Switch; [] se não houver."""
    hosts = device.get("hosts")
    if not isinstance(hosts, dict):
        return []
    try:
        count = max(0, min(16, int(hosts.get("count") or 0)))  # dado malformado: sem submenu
    except (TypeError, ValueError):
        return []
    names = hosts.get("names")
    names = names if isinstance(names, list) else []
    cur = hosts.get("current")
    return [(i, (str(names[i]) if i < len(names) and names[i] else f"Computador {i + 1}"), i == cur)
            for i in range(count)]


def active_profile_label(devices: list[dict], name_of) -> str:
    for d in devices:
        app = d.get("active_profile")
        if app:
            return f"Perfil ativo: {name_of(app)}"
    return "Perfil ativo: Todos os aplicativos"


def tooltip(devices: list[dict] | None) -> str:
    if devices is None:
        return "OpenMacros+ — serviço fora do ar"
    if not devices:
        return "OpenMacros+ — nenhum dispositivo"
    return "OpenMacros+\n" + "\n".join(device_label(d) for d in devices)


def menu_spec(devices: list[dict] | None, name_of) -> tuple:
    """Estrutura visível do menu (comparável): só reconstrói o menu quando algo visível mudou."""
    spec: list[tuple] = []
    if devices is None:
        spec.append(("label", "Serviço do OpenMacros+ não está em execução"))
    elif not devices:
        spec.append(("label", "Nenhum dispositivo conectado"))
    else:
        for d in devices:
            spec.append(("label", device_label(d)))
        spec.append(("sep",))
        spec.append(("label", active_profile_label(devices, name_of)))
        switchable = [d for d in devices if d.get("online", True) and host_labels(d)]
        for d in switchable:
            title = "Easy-Switch" if len(switchable) == 1 else f"Easy-Switch — {device_label(d).split(' — ')[0]}"
            spec.append(("easy", title, str(d.get("id", "")), tuple(host_labels(d))))
    spec.append(("sep",))
    spec.append(("open",))
    spec.append(("quit",))
    return tuple(spec)
