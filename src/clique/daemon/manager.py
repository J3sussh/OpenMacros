"""Gerenciador: dispositivos, configuração, roteamento de botões e API do serviço."""

from __future__ import annotations

import copy
import json
import logging
import secrets
from typing import Any, Callable, Protocol

from ..hidpp import messages as m
from . import profiles
from .actions import ActionExecutor, validate_action, validate_smart_action
from .config import Config
from .focus import EMPTY_APP, NullFocusWatcher, make_focus_watcher
from .gestures import ActionEvent, ButtonRouter
from .timers import GLibScheduler

log = logging.getLogger(__name__)

MAX_JSON_BYTES = 64 * 1024
MAX_RECENT_APPS = 30
MAX_SMART_ACTIONS = 200
SETTINGS_DEBOUNCE_MS = 300
SETTING_KEYS = ("pointer_speed", "dpi", "hires_scroll", "scroll_invert", "smartshift")


class ManagerError(Exception):
    dbus_name = "io.github.clique.Error.InvalidArgument"


class NotFound(ManagerError):
    dbus_name = "io.github.clique.Error.NotFound"


class Unsupported(ManagerError):
    dbus_name = "io.github.clique.Error.Unsupported"


class DeviceOffline(ManagerError):
    dbus_name = "io.github.clique.Error.DeviceOffline"


class InvalidArgument(ManagerError):
    dbus_name = "io.github.clique.Error.InvalidArgument"


class ManagedDevice(Protocol):
    id: str
    online: bool
    on_event: Callable[..., None] | None  # (kind, *args): key_report, raw_xy, updated, online, offline

    def describe(self) -> dict: ...
    def apply_control(self, cid: int, action: dict) -> None: ...
    def set_setting(self, key: str, value: Any) -> None: ...
    def change_host(self, host: int) -> None: ...
    def reset_controls(self) -> None: ...
    def close(self) -> None: ...


def plan_reporting(action: dict) -> tuple[bool, bool, int]:
    """Ação -> (divert, raw_xy, remap_cid) para a feature 0x1B04."""
    t = action["type"]
    if t == "default":
        return False, False, 0
    if t == "remap":
        return False, False, action["cid"]
    if t == "gestures":
        return True, True, 0
    return True, False, 0


def raw_setting(key: str, spec: dict):
    """Valor atual de uma setting no formato aceito por set_setting."""
    if key == "smartshift":
        return {"enabled": spec["enabled"], "threshold": spec["threshold"]}
    return spec.get("value")


class Manager:
    def __init__(self, config: Config, executor: ActionExecutor | None = None, scheduler=None, focus=None):
        self.config = config
        self.scheduler = scheduler or GLibScheduler()
        self.executor = executor or ActionExecutor(scheduler=self.scheduler)
        self.executor.smart_lookup = self._smart_lookup
        self.executor.change_host_cb = self._change_host_cb
        self.devices: dict[str, ManagedDevice] = {}
        self.routers: dict[str, ButtonRouter] = {}
        self.listeners: list[Callable[..., None]] = []
        self.backends: list[Any] = []
        self.focus = focus
        self.debug = False
        self.active_app: dict = dict(EMPTY_APP)
        self.recent_apps: list[dict] = []
        self._hw: dict[str, dict[int, dict]] = {}
        self._settings_timers: dict[str, int] = {}

    # --- sinais ---
    def _emit(self, name: str, *args) -> None:
        for cb in list(self.listeners):
            try:
                cb(name, *args)
            except Exception:
                log.exception("listener falhou")

    def _emit_error(self, dev_id: str, msg: str) -> None:
        log.error("%s: %s", dev_id, msg)
        self._emit("error", dev_id, msg)

    # --- foco ---
    def start_focus(self) -> None:
        if self.focus is None:
            self.focus = make_focus_watcher(self.scheduler)
        try:
            self.focus.start(self.on_focus_changed)
        except Exception as e:
            log.warning("não foi possível observar o foco (%s); só o perfil global valerá", e)
            self.focus = NullFocusWatcher(str(e))
            self.focus.start(self.on_focus_changed)

    def on_focus_changed(self, app: dict) -> None:
        prev = self.active_app["app_id"]
        self.active_app = dict(app)
        if app["app_id"]:
            self.recent_apps = [a for a in self.recent_apps if a["app_id"] != app["app_id"]]
            self.recent_apps.insert(0, dict(app))
            del self.recent_apps[MAX_RECENT_APPS:]
        self._emit("active_app_changed", json.dumps(self.active_app, ensure_ascii=False))
        if app["app_id"] == prev:
            return
        for dev_id, dev in list(self.devices.items()):
            cfg = self._cfg(dev_id)
            self._refresh_router(dev_id)  # solta o que foi pressionado no app anterior
            if profiles.active_profile(cfg, prev) != profiles.active_profile(cfg, app["app_id"]):
                self._notify_updated(dev_id)
            if dev.online:
                self._schedule_settings(dev_id)

    def debug_set_active_app(self, app_id: str) -> None:
        if not self.debug:
            raise Unsupported("disponível só em modo simulado")
        self._check_app_id(app_id, allow_empty=True)
        if hasattr(self.focus, "set_active"):
            self.focus.set_active(app_id)
        else:
            raise Unsupported("sem observador de foco simulado")

    def get_active_app(self) -> str:
        return json.dumps(self.active_app, ensure_ascii=False)

    def get_recent_apps(self) -> str:
        return json.dumps(self.recent_apps, ensure_ascii=False)

    # --- ciclo de vida ---
    def add_device(self, dev: ManagedDevice) -> None:
        old = self.devices.get(dev.id)
        if old is not None and old is not dev:
            old.on_event = None
            old.close()
        self.executor.release_all(dev.id)  # nada preso de um router/dispositivo anterior
        self.devices[dev.id] = dev
        self.routers[dev.id] = ButtonRouter(self._effective(dev.id), dev.id)
        dev.on_event = lambda kind, *a, _d=dev: self._on_event(_d, kind, *a)
        if dev.online:
            self._reapply(dev)
        self._emit("devices_changed")
        self._emit("device_updated", dev.id, json.dumps(self.device_dict(dev.id), ensure_ascii=False))

    def remove_device(self, dev_id: str) -> None:
        dev = self.devices.pop(dev_id, None)
        self.routers.pop(dev_id, None)
        self._hw.pop(dev_id, None)
        self._cancel_settings(dev_id)
        self.executor.release_all(dev_id)
        if dev:
            dev.on_event = None
            dev.close()
            self._emit("devices_changed")

    def rescan(self) -> None:
        for b in self.backends:
            try:
                b.scan(self)
            except Exception:
                log.exception("falha na varredura de dispositivos")

    def close(self) -> None:
        if self.focus is not None:
            try:
                self.focus.stop()
            except Exception:
                log.debug("falha ao parar o observador de foco", exc_info=True)
        for dev_id in list(self._settings_timers):
            self._cancel_settings(dev_id)
        self.executor.release_everything()
        for d in list(self.devices.values()):
            if d.online:  # não deixa divert preso no firmware
                try:
                    d.reset_controls()
                except Exception as e:
                    log.debug("reset ao sair falhou em %s: %s", d.id, e)
        for b in self.backends:
            if hasattr(b, "close"):
                b.close()
        for d in list(self.devices.values()):
            d.close()

    # --- config normalizada / resolução ---
    def _cfg(self, dev_id: str) -> dict:
        """Config do dispositivo com todas as ações validadas (inválidas são descartadas)."""
        raw = self.config.device(dev_id)

        def norm(mapping: dict, where: str) -> dict:
            out = {}
            for cid, a in mapping.items():
                try:
                    out[str(int(cid))] = validate_action(a, check_command=False)
                except (ValueError, KeyError, TypeError):
                    log.warning("ação inválida ignorada: %s/%s/%s", dev_id, where, cid)
            return out
        return {
            "assignments": norm(raw["assignments"], "global"),
            "settings": raw["settings"],
            "baseline": raw["baseline"],
            "profiles": {app: {"assignments": norm(p.get("assignments", {}), app),
                               "settings": dict(p.get("settings", {}))}
                         for app, p in raw["profiles"].items()},
        }

    def _effective(self, dev_id: str) -> dict[int, dict]:
        return profiles.effective_assignments(self._cfg(dev_id), self.active_app["app_id"])

    def _refresh_router(self, dev_id: str) -> None:
        router = self.routers.get(dev_id)
        if router:
            self._run(dev_id, router.set_assignments(self._effective(dev_id)))

    def _smart_lookup(self, sa_id: str) -> dict | None:
        sa = self.config.smart_actions.get(sa_id)
        try:
            return validate_smart_action(sa, check_command=False) if sa else None
        except ValueError:
            log.warning("Smart Action %s inválida", sa_id)
            return None

    def _change_host_cb(self, dev_id: str, host: int) -> None:
        try:
            self.change_host(dev_id, host)
        except ManagerError as e:
            self._emit_error(dev_id, str(e))

    # --- config -> dispositivo ---
    def _control_cids(self, dev: ManagedDevice) -> set[int]:
        return {c["cid"] for c in dev.describe().get("controls", [])}

    def _sync_controls(self, dev: ManagedDevice, strict: bool = False) -> None:
        """Leva o firmware ao estado do plano (união dos perfis); só escreve o que mudou."""
        plan = profiles.hardware_plan(self._cfg(dev.id))
        hw = self._hw.setdefault(dev.id, {})
        valid = self._control_cids(dev)
        for cid in sorted((set(plan) | set(hw)) & valid):
            new = plan.get(cid, profiles.DEFAULT)
            if new == hw.get(cid, profiles.DEFAULT):
                continue
            try:
                dev.apply_control(cid, new)
                hw[cid] = new
            except Exception as e:
                if strict:
                    raise
                self._emit_error(dev.id, f"não foi possível reaplicar o botão {cid}: {e}")

    def _sync_settings(self, dev: ManagedDevice, strict: bool = False) -> bool:
        """Grava no dispositivo as settings efetivas que diferem do estado atual."""
        cfg = self._cfg(dev.id)
        app = self.active_app["app_id"]
        current = dev.describe().get("settings", {})
        for key in profiles.keys_needing_baseline(cfg, app):
            if key in current:  # guarda o valor original para restaurar ao sair do perfil
                self.config.set_baseline(dev.id, key, raw_setting(key, current[key]))
                cfg["baseline"][key] = raw_setting(key, current[key])
        changed = False
        for key, raw in profiles.settings_targets(cfg, app).items():
            if key not in current or raw_setting(key, current[key]) == raw:
                continue
            try:
                dev.set_setting(key, raw)
                changed = True
            except Exception as e:
                if strict:
                    raise
                self._emit_error(dev.id, f"não foi possível aplicar '{key}': {e}")
        return changed

    def _reapply(self, dev: ManagedDevice) -> None:
        self._hw[dev.id] = {}  # o firmware voltou ao padrão
        self._sync_controls(dev)
        self._sync_settings(dev)

    def _schedule_settings(self, dev_id: str) -> None:
        self._cancel_settings(dev_id)
        self._settings_timers[dev_id] = self.scheduler.call_later(
            SETTINGS_DEBOUNCE_MS, lambda: self._settings_tick(dev_id))

    def _cancel_settings(self, dev_id: str) -> None:
        h = self._settings_timers.pop(dev_id, None)
        if h is not None:
            self.scheduler.cancel(h)

    def _settings_tick(self, dev_id: str) -> None:
        self._settings_timers.pop(dev_id, None)
        dev = self.devices.get(dev_id)
        if dev and dev.online and self._sync_settings(dev):
            self._notify_updated(dev_id)

    # --- eventos do dispositivo ---
    def _on_event(self, dev: ManagedDevice, kind: str, *args) -> None:
        router = self.routers.get(dev.id)
        if kind == "key_report" and router:
            self._run(dev.id, router.on_key_report(args[0]))
        elif kind == "raw_xy" and router:
            self._run(dev.id, router.on_raw_xy(args[0], args[1]))
        elif kind == "online":
            self.executor.release_all(dev.id)
            if router:
                router.reset()
            self._reapply(dev)
            self._emit("devices_changed")
            self._notify_updated(dev.id)
        elif kind == "offline":
            self.executor.release_all(dev.id)
            if router:
                router.reset()
            self._cancel_settings(dev.id)
            self._emit("devices_changed")
            self._notify_updated(dev.id)
        elif kind == "updated":
            self._notify_updated(dev.id)

    def _run(self, dev_id: str, events: list[ActionEvent]) -> None:
        for ev in events:
            if ev.action["type"] == "change_host":
                if ev.kind in ("press", "trigger"):
                    self._change_host_cb(dev_id, ev.action["host"])
            else:
                self.executor.perform(ev)

    def _notify_updated(self, dev_id: str) -> None:
        if dev_id in self.devices:
            self._emit("device_updated", dev_id, json.dumps(self.device_dict(dev_id), ensure_ascii=False))

    # --- API: leitura ---
    def _get(self, dev_id: str) -> ManagedDevice:
        dev = self.devices.get(dev_id)
        if dev is None:
            raise NotFound(f"dispositivo não encontrado: {dev_id}")
        return dev

    def _get_online(self, dev_id: str) -> ManagedDevice:
        dev = self._get(dev_id)
        if not dev.online:
            raise DeviceOffline(f"dispositivo desconectado: {dev.describe().get('name', dev_id)}")
        return dev

    def device_dict(self, dev_id: str) -> dict:
        dev = self._get(dev_id)
        d = dev.describe()
        cids = {str(c["cid"]) for c in d.get("controls", [])}
        cfg = self._cfg(dev_id)
        d["assignments"] = {c: a for c, a in cfg["assignments"].items() if c in cids}
        d["profiles"] = {app: {"assignments": {c: a for c, a in p["assignments"].items() if c in cids},
                               "settings": p["settings"]}
                         for app, p in cfg["profiles"].items()}
        d["active_profile"] = profiles.active_profile(cfg, self.active_app["app_id"])
        return d

    def get_devices(self) -> str:
        return json.dumps([self.device_dict(i) for i in self.devices], ensure_ascii=False)

    def get_device(self, dev_id: str) -> str:
        return json.dumps(self.device_dict(dev_id), ensure_ascii=False)

    # --- API: botões / perfis ---
    @staticmethod
    def _check_size(text: str) -> None:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_JSON_BYTES:
            raise InvalidArgument("JSON grande demais")

    @staticmethod
    def _check_app_id(app_id: str, allow_empty: bool = False) -> None:
        if not isinstance(app_id, str) or len(app_id) > 128 or any(ord(c) < 32 for c in app_id) \
                or (not app_id and not allow_empty):
            raise InvalidArgument("app_id inválido")

    def _parse_action(self, action_json: str) -> dict:
        self._check_size(action_json)
        try:
            action = validate_action(json.loads(action_json))
        except (ValueError, TypeError, RecursionError) as e:
            raise InvalidArgument(f"ação inválida: {e}") from e
        if action["type"] == "smart_action" and action["id"] not in self.config.smart_actions:
            raise InvalidArgument(f"Smart Action inexistente: {action['id']}")
        return action

    def set_assignment(self, dev_id: str, cid: int, action_json: str) -> bool:
        return self.set_profile_assignment(dev_id, "", cid, action_json)

    def set_profile_assignment(self, dev_id: str, app_id: str, cid: int, action_json: str) -> bool:
        dev = self._get_online(dev_id)
        self._check_app_id(app_id, allow_empty=True)
        self._check_size(action_json)
        if app_id and action_json.strip() == "null":
            action = None  # remove a sobreposição: volta a herdar do global
        else:
            action = self._parse_action(action_json)
            if app_id and action["type"] == "remap":
                raise InvalidArgument("'remap' só vale no perfil global (é do firmware)")
        ctrl = next((c for c in dev.describe().get("controls", []) if c["cid"] == cid), None)
        if ctrl is None:
            raise Unsupported(f"o dispositivo não tem o botão {cid}")
        if action:
            if action["type"] != "default" and not ctrl["remappable"]:
                raise Unsupported("este botão não pode ser reprogramado")
            if action["type"] not in ("default", "remap") and not ctrl["divertable"]:
                raise Unsupported("este botão não pode ser desviado para ações do host")
            if action["type"] == "gestures" and not ctrl.get("raw_xy"):
                raise Unsupported("este botão não suporta gestos (sem movimento bruto)")
        snap = self.config.snapshot_device(dev_id)
        if app_id:
            self.config.set_profile_assignment(dev_id, app_id, cid, action)
        else:
            self.config.set_assignment(dev_id, cid, action)
        try:
            self._sync_controls(dev, strict=True)
        except (m.HidppError, OSError) as e:
            self.config.restore_device(dev_id, snap)
            raise DeviceOffline(f"falha ao falar com o dispositivo: {e}") from e
        self._refresh_router(dev_id)
        self._notify_updated(dev_id)
        return True

    def remove_profile(self, dev_id: str, app_id: str) -> bool:
        dev = self._get(dev_id)
        self._check_app_id(app_id)
        existed = self.config.remove_profile(dev_id, app_id)
        if existed and dev.online:
            try:
                self._sync_controls(dev, strict=True)
            except (m.HidppError, OSError) as e:
                self._emit_error(dev_id, f"falha ao atualizar botões: {e}")
            self._refresh_router(dev_id)
            self._schedule_settings(dev_id)
        if existed:
            self._notify_updated(dev_id)
        return existed

    # --- API: settings ---
    def _parse_setting(self, dev: ManagedDevice, key: str, value_json: str, allow_null: bool):
        if key not in SETTING_KEYS:
            raise InvalidArgument(f"chave desconhecida: {key}")
        self._check_size(value_json)
        try:
            value = json.loads(value_json)
        except (ValueError, RecursionError) as e:
            raise InvalidArgument(f"JSON inválido: {e}") from e
        spec = dev.describe().get("settings", {}).get(key)
        if spec is None:
            raise Unsupported(f"o dispositivo não suporta '{key}'")
        if value is None and allow_null:
            return None
        return self._check_setting(key, value, spec)

    def set_setting(self, dev_id: str, key: str, value_json: str) -> bool:
        dev = self._get_online(dev_id)
        value = self._parse_setting(dev, key, value_json, allow_null=False)
        snap = self.config.snapshot_device(dev_id)
        self.config.set_setting(dev_id, key, value)
        try:
            self._sync_settings(dev, strict=True)
        except (m.HidppError, OSError) as e:
            self.config.restore_device(dev_id, snap)
            raise DeviceOffline(f"falha ao falar com o dispositivo: {e}") from e
        self._notify_updated(dev_id)
        return True

    def set_profile_setting(self, dev_id: str, app_id: str, key: str, value_json: str) -> bool:
        if app_id == "":
            return self.set_setting(dev_id, key, value_json)
        dev = self._get_online(dev_id)
        self._check_app_id(app_id)
        value = self._parse_setting(dev, key, value_json, allow_null=True)
        self.config.set_profile_setting(dev_id, app_id, key,
                                        None if value is None else profiles.wrap_setting(key, value))
        if app_id == self.active_app["app_id"]:
            try:
                self._sync_settings(dev, strict=True)
            except (m.HidppError, OSError) as e:
                raise DeviceOffline(f"falha ao falar com o dispositivo: {e}") from e
        self._notify_updated(dev_id)
        return True

    @staticmethod
    def _check_setting(key: str, v, spec: dict):
        def is_int(x):
            return isinstance(x, int) and not isinstance(x, bool)
        if key in ("hires_scroll", "scroll_invert"):
            if not isinstance(v, bool):
                raise InvalidArgument(f"'{key}' espera booleano")
        elif key == "pointer_speed":
            if not is_int(v) or not spec["min"] <= v <= spec["max"]:
                raise InvalidArgument(f"'pointer_speed' fora de {spec['min']}..{spec['max']}")
        elif key == "dpi":
            if not is_int(v) or ("choices" in spec and v not in spec["choices"]):
                raise InvalidArgument("DPI não suportado")
        elif key == "smartshift":
            if (not isinstance(v, dict) or not isinstance(v.get("enabled"), bool)
                    or not is_int(v.get("threshold")) or not 1 <= v["threshold"] <= 255):
                raise InvalidArgument("smartshift espera {'enabled': bool, 'threshold': 1..255}")
            v = {"enabled": v["enabled"], "threshold": v["threshold"]}
        return v

    def change_host(self, dev_id: str, host: int) -> bool:
        dev = self._get_online(dev_id)
        hosts = dev.describe().get("hosts")
        if not hosts:
            raise Unsupported("o dispositivo não tem Easy-Switch")
        if not 0 <= host < hosts["count"]:
            raise InvalidArgument(f"host fora de 0..{hosts['count'] - 1}")
        try:
            dev.change_host(host)
        except (m.HidppError, OSError) as e:
            raise DeviceOffline(f"falha ao falar com o dispositivo: {e}") from e
        self._notify_updated(dev_id)
        return True

    def reset_device(self, dev_id: str) -> bool:
        dev = self._get_online(dev_id)
        try:
            dev.reset_controls()
        except (m.HidppError, OSError) as e:
            raise DeviceOffline(f"falha ao falar com o dispositivo: {e}") from e
        self._hw[dev_id] = {}
        self.config.clear_device(dev_id)
        self.executor.release_all(dev_id)
        self._refresh_router(dev_id)
        self._notify_updated(dev_id)
        return True

    # --- API: Smart Actions e execução direta ---
    def get_smart_actions(self) -> str:
        out = {}
        for sid in self.config.smart_actions:
            sa = self._smart_lookup(sid)
            if sa:
                sa["id"] = sid
                out[sid] = sa
        return json.dumps(out, ensure_ascii=False)

    def save_smart_action(self, sa_json: str) -> str:
        self._check_size(sa_json)
        try:
            sa = validate_smart_action(json.loads(sa_json))
        except (ValueError, TypeError, RecursionError) as e:
            raise InvalidArgument(f"Smart Action inválida: {e}") from e
        sa_id = sa.pop("id", None)
        if sa_id is None:
            if len(self.config.smart_actions) >= MAX_SMART_ACTIONS:
                raise InvalidArgument("limite de Smart Actions atingido")
            sa_id = "sa_" + secrets.token_hex(3)
            while sa_id in self.config.smart_actions:
                sa_id = "sa_" + secrets.token_hex(3)
        elif sa_id not in self.config.smart_actions:
            raise NotFound(f"Smart Action não encontrada: {sa_id}")
        self.config.put_smart_action(sa_id, sa)
        self._emit("smart_actions_changed")
        return sa_id

    def delete_smart_action(self, sa_id: str) -> bool:
        if not self.config.delete_smart_action(sa_id):
            return False

        def strip(d: dict) -> None:
            for src in [d.get("assignments", {})] + [p.get("assignments", {}) for p in d.get("profiles", {}).values()]:
                for cid, a in list(src.items()):
                    src[cid] = profiles.strip_smart_action(a, sa_id)
        self.config.replace_devices_data(strip)
        for dev_id, dev in list(self.devices.items()):
            if dev.online:
                try:
                    self._sync_controls(dev)
                except Exception:
                    log.exception("resync após apagar Smart Action")
            self._refresh_router(dev_id)
            self._notify_updated(dev_id)
        self._emit("smart_actions_changed")
        return True

    def run_action(self, action_json: str) -> bool:
        action = self._parse_action(action_json)
        if action["type"] in ("gestures", "change_host", "remap", "default", "disabled"):
            raise InvalidArgument(f"'{action['type']}' não pode ser executada diretamente")
        self.executor.run(action)
        return True
