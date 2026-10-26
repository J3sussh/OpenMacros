"""Resolução de perfis por aplicativo. Funções puras sobre o dict de config de um dispositivo.

`cfg` = {"assignments": {...}, "settings": {...}, "profiles": {app: {"assignments","settings"}},
"baseline": {...}} com ações já normalizadas.
"""

from __future__ import annotations

import copy

DEFAULT = {"type": "default"}
_PASSIVE = ("default", "remap")


def unwrap_setting(key: str, stored):
    """Perfis guardam no formato do Device JSON ({"value": v} / {"enabled","threshold"})."""
    if key == "smartshift":
        return {"enabled": stored["enabled"], "threshold": stored["threshold"]}
    return stored["value"] if isinstance(stored, dict) else stored


def wrap_setting(key: str, raw):
    return dict(raw) if key == "smartshift" else {"value": raw}


def _profile(cfg: dict, app_id: str) -> dict | None:
    return cfg.get("profiles", {}).get(app_id) if app_id else None


def diverted_cids(cfg: dict) -> set[int]:
    """CIDs com ação ≠ default/remap em QUALQUER perfil (global ou de aplicativo)."""
    out: set[int] = set()
    sources = [cfg.get("assignments", {})] + [p.get("assignments", {}) for p in cfg.get("profiles", {}).values()]
    for src in sources:
        for cid, a in src.items():
            if a.get("type") not in _PASSIVE:
                out.add(int(cid))
    return out


def effective_action(cfg: dict, app_id: str, cid: int, diverted: bool = True) -> dict:
    """App → global → default. `remap` em perfil de app é ignorado (é do firmware)."""
    prof = _profile(cfg, app_id)
    if prof:
        a = prof.get("assignments", {}).get(str(cid))
        if a is not None and a.get("type") != "remap":
            return a
    g = cfg.get("assignments", {}).get(str(cid))
    if g is None:
        return DEFAULT
    if g.get("type") == "remap" and diverted:
        # o CID está desviado (divert vence o remap do firmware): re-emite o botão de destino
        return {"type": "default", "cid": g["cid"]}
    return g


def effective_assignments(cfg: dict, app_id: str) -> dict[int, dict]:
    """Ações efetivas dos CIDs desviados (os únicos que geram eventos)."""
    return {cid: effective_action(cfg, app_id, cid) for cid in sorted(diverted_cids(cfg))}


def hardware_plan(cfg: dict) -> dict[int, dict]:
    """Estado desejado no firmware por CID (independe do app em foco)."""
    cids = {int(c) for c in cfg.get("assignments", {})}
    for p in cfg.get("profiles", {}).values():
        cids |= {int(c) for c in p.get("assignments", {})}
    plan: dict[int, dict] = {}
    for cid in cids:
        acts = [cfg.get("assignments", {}).get(str(cid))] + [
            p.get("assignments", {}).get(str(cid)) for p in cfg.get("profiles", {}).values()]
        active = [a for a in acts if a and a.get("type") not in _PASSIVE]
        g = cfg.get("assignments", {}).get(str(cid))
        if any(a["type"] == "gestures" for a in active):
            plan[cid] = {"type": "gestures"}
        elif active:
            plan[cid] = {"type": "disabled"}  # só "desviar"
        elif g and g.get("type") == "remap":
            plan[cid] = g
        else:
            plan[cid] = DEFAULT
    return plan


def active_profile(cfg: dict, app_id: str) -> str:
    return app_id if app_id and app_id in cfg.get("profiles", {}) else ""


def settings_targets(cfg: dict, app_id: str) -> dict:
    """Valor desejado por chave: perfil do app → global → baseline (valor original do dispositivo)."""
    keys = set(cfg.get("settings", {}))
    for p in cfg.get("profiles", {}).values():
        keys |= set(p.get("settings", {}))
    out = {}
    prof = _profile(cfg, app_id)
    for key in keys:
        if prof and key in prof.get("settings", {}):
            out[key] = unwrap_setting(key, prof["settings"][key])
        elif key in cfg.get("settings", {}):
            out[key] = cfg["settings"][key]
        elif key in cfg.get("baseline", {}):
            out[key] = cfg["baseline"][key]
    return out


def keys_needing_baseline(cfg: dict, app_id: str) -> set[str]:
    """Chaves que o perfil ativo sobrepõe e que não têm valor global nem baseline gravado."""
    prof = _profile(cfg, app_id)
    if not prof:
        return set()
    return {k for k in prof.get("settings", {})
            if k not in cfg.get("settings", {}) and k not in cfg.get("baseline", {})}


def strip_smart_action(obj, sa_id: str):
    """Troca referências a uma Smart Action por `default` (recursivo em gestos). Devolve cópia."""
    if isinstance(obj, dict):
        if obj.get("type") == "smart_action" and obj.get("id") == sa_id:
            return dict(DEFAULT)
        return {k: strip_smart_action(v, sa_id) if isinstance(v, dict) else v for k, v in obj.items()}
    return copy.deepcopy(obj)
