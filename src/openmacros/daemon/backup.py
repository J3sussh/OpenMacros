"""Exportação/importação da configuração (B5). Funções puras: validam com os mesmos validadores de entrada."""

from __future__ import annotations

import copy
import datetime
import json
import re

from . import preferences, profiles
from .actions import validate_action, validate_smart_action

EXPORT_VERSION = 1
MAX_IMPORT_BYTES = 512 * 1024
MAX_DEVICES = 64
MAX_PROFILES = 200
MAX_SMART_ACTIONS = 200
SETTING_KEYS = ("pointer_speed", "dpi", "hires_scroll", "scroll_invert", "smartshift")
_DEV_RE = re.compile(r"^[A-Za-z0-9:_.-]{1,64}$")
_SA_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def check_setting(key: str, v):
    """Valida o valor cru de uma setting sem conhecer o dispositivo (faixas largas; o dispositivo reaplica)."""
    if key not in SETTING_KEYS:
        raise ValueError(f"chave de setting desconhecida: {key!r}")
    if key in ("hires_scroll", "scroll_invert"):
        if not isinstance(v, bool):
            raise ValueError(f"'{key}' espera booleano")
    elif key == "pointer_speed":
        if not _is_int(v) or not 1 <= v <= 65535:
            raise ValueError("'pointer_speed' deve ser inteiro entre 1 e 65535")
    elif key == "dpi":
        if not _is_int(v) or not 1 <= v <= 65535:
            raise ValueError("'dpi' deve ser inteiro entre 1 e 65535")
    elif key == "smartshift":
        if (not isinstance(v, dict) or not isinstance(v.get("enabled"), bool)
                or not _is_int(v.get("threshold")) or not 1 <= v["threshold"] <= 255):
            raise ValueError("'smartshift' espera {'enabled': bool, 'threshold': 1..255}")
        v = {"enabled": v["enabled"], "threshold": v["threshold"]}
    return v


def _assignments(obj, where: str, *, in_profile: bool) -> dict:
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: 'assignments' deve ser um objeto")
    out = {}
    for cid, act in obj.items():
        if not isinstance(cid, str) or not cid.isdigit() or not 1 <= int(cid) <= 0xFFFF:
            raise ValueError(f"{where}: CID inválido {cid!r}")
        try:
            a = validate_action(act, check_command=False)
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"{where}: ação do botão {cid} inválida: {e}") from e
        if in_profile and a["type"] == "remap":
            raise ValueError(f"{where}: 'remap' só vale no perfil global")
        out[str(int(cid))] = a
    return out


def _settings(obj, where: str, *, wrapped: bool) -> dict:
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: 'settings' deve ser um objeto")
    out = {}
    for key, v in obj.items():
        try:
            if wrapped:  # perfis guardam {"value": v} (smartshift: {"enabled","threshold"})
                if not isinstance(v, dict):
                    raise ValueError("formato inválido")
                if key == "smartshift":
                    out[key] = check_setting(key, v)
                elif "value" in v:
                    out[key] = {"value": check_setting(key, v["value"])}
                else:
                    raise ValueError("falta 'value'")
            else:
                out[key] = check_setting(key, v)
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"{where}: setting {key!r} inválida: {e}") from e
    return out


def _device(dev_id: str, d) -> dict:
    where = f"dispositivo {dev_id}"
    if not isinstance(d, dict):
        raise ValueError(f"{where}: deve ser um objeto")
    entry = {"assignments": _assignments(d.get("assignments", {}), where, in_profile=False),
             "settings": _settings(d.get("settings", {}), where, wrapped=False)}
    profs = d.get("profiles", {})
    if not isinstance(profs, dict):
        raise ValueError(f"{where}: 'profiles' deve ser um objeto")
    if len(profs) > MAX_PROFILES:
        raise ValueError(f"{where}: perfis demais (máx. {MAX_PROFILES})")
    out_profs = {}
    for app, p in profs.items():
        if not isinstance(app, str) or not app or len(app) > 128 or any(ord(c) < 32 for c in app):
            raise ValueError(f"{where}: app_id de perfil inválido")
        if not isinstance(p, dict):
            raise ValueError(f"{where}/{app}: perfil deve ser um objeto")
        pa = _assignments(p.get("assignments", {}), f"{where}/{app}", in_profile=True)
        ps = _settings(p.get("settings", {}), f"{where}/{app}", wrapped=True)
        if pa or ps:  # perfil vazio some (B4)
            out_profs[app] = {"assignments": pa, "settings": ps}
    if out_profs:
        entry["profiles"] = out_profs
    return entry


def smart_refs(action) -> set[str]:
    """Ids de Smart Actions referenciados por uma ação (inclui gestos aninhados)."""
    out: set[str] = set()
    if isinstance(action, dict):
        if action.get("type") == "smart_action":
            out.add(action["id"])
        for v in action.values():
            if isinstance(v, dict):
                out |= smart_refs(v)
    return out


def parse_import(text: str) -> dict:
    """JSON de exportação -> {"devices"?, "smart_actions"?, "preferences"?} normalizado.
    Levanta ValueError com mensagem legível."""
    if not isinstance(text, str):
        raise ValueError("conteúdo inválido")
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise ValueError(f"arquivo grande demais (máx. {MAX_IMPORT_BYTES // 1024} KiB)")
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError) as e:
        raise ValueError(f"JSON inválido: {e}") from e
    if not isinstance(obj, dict) or "openmacros_export" not in obj:
        raise ValueError("não é um arquivo de exportação do OpenMacros+")
    if not _is_int(obj["openmacros_export"]) or obj["openmacros_export"] != EXPORT_VERSION:
        raise ValueError(f"versão de exportação não suportada: {obj['openmacros_export']!r}")
    out: dict = {}
    if "devices" in obj:
        devs = obj["devices"]
        if not isinstance(devs, dict):
            raise ValueError("'devices' deve ser um objeto")
        if len(devs) > MAX_DEVICES:
            raise ValueError(f"dispositivos demais (máx. {MAX_DEVICES})")
        out["devices"] = {}
        for dev_id, d in devs.items():
            if not isinstance(dev_id, str) or not _DEV_RE.match(dev_id):
                raise ValueError(f"id de dispositivo inválido: {dev_id!r}")
            out["devices"][dev_id] = _device(dev_id, d)
    if "smart_actions" in obj:
        sas = obj["smart_actions"]
        if not isinstance(sas, dict):
            raise ValueError("'smart_actions' deve ser um objeto")
        if len(sas) > MAX_SMART_ACTIONS:
            raise ValueError(f"Smart Actions demais (máx. {MAX_SMART_ACTIONS})")
        out["smart_actions"] = {}
        for sid, sa in sas.items():
            if not isinstance(sid, str) or not _SA_RE.match(sid):
                raise ValueError(f"id de Smart Action inválido: {sid!r}")
            try:
                norm = validate_smart_action(sa, check_command=False, keep_stats=True)
            except (ValueError, TypeError, RecursionError) as e:
                raise ValueError(f"Smart Action {sid}: {e}") from e
            if norm.pop("id", sid) != sid:
                raise ValueError(f"Smart Action {sid}: 'id' não confere com a chave")
            out["smart_actions"][sid] = norm
    if "preferences" in obj:
        out["preferences"] = preferences.validate_preferences(obj["preferences"])
    return out


def export_dict(data: dict) -> dict:
    """Config -> objeto de exportação (sem baseline nem estado volátil)."""
    devices = {}
    for dev_id, d in data.get("devices", {}).items():
        entry = {"assignments": copy.deepcopy(d.get("assignments", {})),
                 "settings": copy.deepcopy(d.get("settings", {}))}
        if d.get("profiles"):
            entry["profiles"] = copy.deepcopy(d["profiles"])
        devices[dev_id] = entry
    return {
        "openmacros_export": EXPORT_VERSION,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(),
        "devices": devices,
        "smart_actions": copy.deepcopy(data.get("smart_actions", {})),
        "preferences": preferences.with_defaults(data.get("preferences", {})),
    }


def merge_device(old: dict, new: dict) -> dict:
    out = copy.deepcopy(old)
    out.setdefault("assignments", {}).update(copy.deepcopy(new["assignments"]))
    out.setdefault("settings", {}).update(copy.deepcopy(new["settings"]))
    for app, p in new.get("profiles", {}).items():
        dst = out.setdefault("profiles", {}).setdefault(app, {"assignments": {}, "settings": {}})
        dst["assignments"].update(copy.deepcopy(p["assignments"]))
        dst["settings"].update(copy.deepcopy(p["settings"]))
    return out


def plan_import(current: dict, imported: dict, merge: bool) -> tuple[dict, dict, dict]:
    """(devices, smart_actions, preferences) finais. `replace` troca só as seções presentes no arquivo.
    O `baseline` (volátil) dos dispositivos já conhecidos é preservado."""
    devices = copy.deepcopy(current.get("devices", {}))
    sas = copy.deepcopy(current.get("smart_actions", {}))
    prefs = copy.deepcopy(current.get("preferences", {}))
    if "devices" in imported:
        if merge:
            for dev_id, d in imported["devices"].items():
                devices[dev_id] = merge_device(devices.get(dev_id, {}), d)
            # os limites valem também DEPOIS da mescla (antes só valiam para o arquivo importado)
            if len(devices) > MAX_DEVICES:
                raise ValueError(f"dispositivos demais após mesclar (máx. {MAX_DEVICES})")
            for dev_id in imported["devices"]:
                if len(devices[dev_id].get("profiles", {})) > MAX_PROFILES:
                    raise ValueError(f"{dev_id}: perfis demais após mesclar (máx. {MAX_PROFILES})")
        else:
            new = {}
            for dev_id, d in imported["devices"].items():
                entry = copy.deepcopy(d)
                base = devices.get(dev_id, {}).get("baseline")
                if base:
                    entry["baseline"] = base
                new[dev_id] = entry
            devices = new
    if "smart_actions" in imported:
        sas = {**sas, **copy.deepcopy(imported["smart_actions"])} if merge else copy.deepcopy(imported["smart_actions"])
        if len(sas) > MAX_SMART_ACTIONS:
            raise ValueError(f"Smart Actions demais após mesclar (máx. {MAX_SMART_ACTIONS})")
    if "preferences" in imported:
        prefs = {**prefs, **imported["preferences"]} if merge else dict(imported["preferences"])
    # referências a Smart Actions inexistentes: as do arquivo são erro; as antigas viram `default`
    for dev_id, d in devices.items():
        for src in [d.get("assignments", {})] + [p.get("assignments", {}) for p in d.get("profiles", {}).values()]:
            for cid, a in list(src.items()):
                missing = smart_refs(a) - set(sas)
                if not missing:
                    continue
                if dev_id in imported.get("devices", {}):
                    raise ValueError(f"o botão {cid} de {dev_id} usa a Smart Action inexistente {sorted(missing)[0]!r}")
                for sid in missing:
                    a = profiles.strip_smart_action(a, sid)
                src[cid] = a
    return devices, sas, prefs
