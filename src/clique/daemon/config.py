"""Persistência em ~/.config/clique/config.json (escrita atômica)."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)
VERSION = 1


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "")
    if not os.path.isabs(base):  # a spec XDG manda ignorar valores relativos
        base = os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "clique" / "config.json"


class Config:
    """`path=None` mantém tudo em memória (modo simulado/testes)."""

    def __init__(self, path: Path | str | None):
        self.path = Path(path) if path else None
        self.data: dict = {"version": VERSION, "devices": {}, "smart_actions": {}}
        self.load()

    def load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("devices", {}), dict):
                raise ValueError("estrutura inválida")
        except (OSError, ValueError, RecursionError) as e:
            bak = self._backup_name()
            log.warning("config ilegível (%s); movendo para %s", e, bak)
            try:
                os.replace(self.path, bak)
            except OSError:
                pass
            return
        self.data = {"version": VERSION, "devices": self._sanitize(data.get("devices", {})),
                     "smart_actions": self._sanitize_smart(data.get("smart_actions", {}))}

    def _backup_name(self) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bak = self.path.with_name(f"{self.path.name}.bak-{stamp}")
        n = 1
        while bak.exists():  # nunca sobrescreve backups existentes
            bak = self.path.with_name(f"{self.path.name}.bak-{stamp}-{n}")
            n += 1
        return bak

    @staticmethod
    def _sanitize(devices: dict) -> dict:
        out: dict = {}
        for dev_id, d in devices.items():
            if not isinstance(d, dict):
                log.warning("config: dispositivo %r inválido descartado", dev_id)
                continue
            asg = d.get("assignments", {})
            st = d.get("settings", {})
            if not isinstance(asg, dict) or not isinstance(st, dict):
                log.warning("config: %r com assignments/settings inválidos descartado", dev_id)
                continue
            good = {}
            for cid, act in asg.items():
                if cid.isdigit() and isinstance(act, dict) and "type" in act:
                    good[cid] = act
                else:
                    log.warning("config: atribuição inválida %r/%r descartada", dev_id, cid)
            entry = {"assignments": good, "settings": dict(st)}
            profiles = Config._sanitize_profiles(dev_id, d.get("profiles", {}))
            if profiles:
                entry["profiles"] = profiles
            base = d.get("baseline", {})
            if isinstance(base, dict) and base:
                entry["baseline"] = dict(base)
            out[str(dev_id)] = entry
        return out

    @staticmethod
    def _sanitize_profiles(dev_id, profiles) -> dict:
        if not isinstance(profiles, dict):
            log.warning("config: profiles de %r inválido descartado", dev_id)
            return {}
        out = {}
        for app, p in profiles.items():
            if not isinstance(p, dict) or not isinstance(p.get("assignments", {}), dict) \
                    or not isinstance(p.get("settings", {}), dict):
                log.warning("config: perfil %r/%r inválido descartado", dev_id, app)
                continue
            good = {c: a for c, a in p.get("assignments", {}).items()
                    if c.isdigit() and isinstance(a, dict) and "type" in a}
            good_settings = {k: v for k, v in p.get("settings", {}).items() if isinstance(v, dict)}
            out[str(app)] = {"assignments": good, "settings": good_settings}
        return out

    @staticmethod
    def _sanitize_smart(sas) -> dict:
        if not isinstance(sas, dict):
            log.warning("config: smart_actions inválido descartado")
            return {}
        out = {}
        for sid, sa in sas.items():
            if (isinstance(sa, dict) and isinstance(sa.get("name"), str)
                    and isinstance(sa.get("steps"), list) and all(isinstance(x, dict) for x in sa["steps"])):
                out[str(sid)] = sa
            else:
                log.warning("config: Smart Action %r inválida descartada", sid)
        return out

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _dev(self, dev_id: str) -> dict:
        d = self.data["devices"].setdefault(dev_id, {})
        d.setdefault("assignments", {})
        d.setdefault("settings", {})
        return d

    def device(self, dev_id: str) -> dict:
        """Cópia da config do dispositivo (assignments/settings)."""
        d = self.data["devices"].get(dev_id) or {}
        return copy.deepcopy({"assignments": d.get("assignments", {}), "settings": d.get("settings", {}),
                              "profiles": d.get("profiles", {}), "baseline": d.get("baseline", {})})

    def snapshot_device(self, dev_id: str):
        return copy.deepcopy(self.data["devices"].get(dev_id))

    def restore_device(self, dev_id: str, snap) -> None:
        if snap is None:
            self.data["devices"].pop(dev_id, None)
        else:
            self.data["devices"][dev_id] = snap
        self.save()

    # --- perfis por aplicativo ---
    def set_profile_assignment(self, dev_id: str, app_id: str, cid: int, action: dict | None) -> None:
        prof = self._dev(dev_id).setdefault("profiles", {}).setdefault(app_id, {"assignments": {}, "settings": {}})
        if action is None:
            prof["assignments"].pop(str(cid), None)
        else:
            prof["assignments"][str(cid)] = action
        self.save()

    def set_profile_setting(self, dev_id: str, app_id: str, key: str, stored: dict | None) -> None:
        prof = self._dev(dev_id).setdefault("profiles", {}).setdefault(app_id, {"assignments": {}, "settings": {}})
        if stored is None:
            prof["settings"].pop(key, None)
        else:
            prof["settings"][key] = stored
        self.save()

    def remove_profile(self, dev_id: str, app_id: str) -> bool:
        profiles = self._dev(dev_id).get("profiles", {})
        existed = profiles.pop(app_id, None) is not None
        if existed:
            self.save()
        return existed

    def set_baseline(self, dev_id: str, key: str, raw) -> None:
        self._dev(dev_id).setdefault("baseline", {})[key] = raw
        self.save()

    # --- Smart Actions (globais) ---
    @property
    def smart_actions(self) -> dict:
        return self.data.setdefault("smart_actions", {})

    def put_smart_action(self, sa_id: str, sa: dict) -> None:
        self.smart_actions[sa_id] = sa
        self.save()

    def delete_smart_action(self, sa_id: str) -> bool:
        existed = self.smart_actions.pop(sa_id, None) is not None
        if existed:
            self.save()
        return existed

    def replace_devices_data(self, mapper) -> None:
        """Aplica mapper(dict_dispositivo) a cada dispositivo e salva (usado ao apagar Smart Actions)."""
        for d in self.data["devices"].values():
            mapper(d)
        self.save()

    def set_assignment(self, dev_id: str, cid: int, action: dict) -> None:
        self._dev(dev_id)["assignments"][str(cid)] = action
        self.save()

    def set_setting(self, dev_id: str, key: str, value) -> None:
        self._dev(dev_id)["settings"][key] = value
        self.save()

    def clear_device(self, dev_id: str) -> None:
        if self.data["devices"].pop(dev_id, None) is not None:
            self.save()
