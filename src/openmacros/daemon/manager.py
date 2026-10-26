"""Gerenciador: dispositivos, configuração, roteamento de botões e API do serviço."""

from __future__ import annotations

import copy
import json
import logging
import secrets
import time
from typing import Any, Callable, Protocol

from ..hidpp import messages as m
from . import backup, labels, notify, preferences, profiles, session_env, smart
from .actions import ActionExecutor, smart_warnings, validate_action, validate_smart_action
from .config import Config
from .focus import EMPTY_APP, NullFocusWatcher, app_from_props, display_kind, make_focus_watcher
from .gestures import ActionEvent, ButtonRouter
from .timers import GLibScheduler
from .triggers import TriggerEngine, UnavailableShortcuts

log = logging.getLogger(__name__)

MAX_JSON_BYTES = 64 * 1024
MAX_RECENT_APPS = 30
MAX_SMART_ACTIONS = 200
SETTINGS_DEBOUNCE_MS = 300
TRIGGER_MIN_INTERVAL = 2.0   # s: cada Smart Action dispara por gatilho no máximo 1x a cada 2 s
TRIGGER_SUPPRESS = 2.0       # s: após terminar, gatilhos app/device dela mesma ficam ignorados
STORM_WINDOW, STORM_MAX = 30.0, 6   # laço entre Smart Actions: no máx. 6 disparos por 30 s
X_RETRY_FAST_MS, X_RETRY_SLOW_MS, X_RETRY_FAST_TRIES = 3000, 30000, 20
SETTING_KEYS = ("pointer_speed", "dpi", "hires_scroll", "scroll_invert", "smartshift")


class ManagerError(Exception):
    dbus_name = "io.github.openmacros.Error.InvalidArgument"


class NotFound(ManagerError):
    dbus_name = "io.github.openmacros.Error.NotFound"


class Unsupported(ManagerError):
    dbus_name = "io.github.openmacros.Error.Unsupported"


class DeviceOffline(ManagerError):
    dbus_name = "io.github.openmacros.Error.DeviceOffline"


class InvalidArgument(ManagerError):
    dbus_name = "io.github.openmacros.Error.InvalidArgument"


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


def display_app_name(app: dict) -> str:
    """Nome legível do app em foco (Gio.DesktopAppInfo se achar; senão o app_id capitalizado)."""
    app_id = app.get("app_id", "")
    try:
        from gi.repository import Gio
        for cand in (f"{app_id}.desktop", f"{app_id.lower()}.desktop"):
            info = Gio.DesktopAppInfo.new(cand)
            if info is not None and info.get_name():
                return info.get_name()
    except Exception:
        pass
    return app_id[:1].upper() + app_id[1:]


def raw_setting(key: str, spec: dict):
    """Valor atual de uma setting no formato aceito por set_setting."""
    if key == "smartshift":
        return {"enabled": spec["enabled"], "threshold": spec["threshold"]}
    return spec.get("value")


class Manager:
    def __init__(self, config: Config, executor: ActionExecutor | None = None, scheduler=None, focus=None,
                 notifier=None, app_namer=None, app_watcher=None, shortcuts=None, clock=time.monotonic):
        self.config = config
        self.scheduler = scheduler or GLibScheduler()
        self.executor = executor or ActionExecutor(scheduler=self.scheduler)
        self.executor.smart_lookup = self._smart_lookup
        self.executor.change_host_cb = self._change_host_cb
        if notifier is not None:
            self.executor.notifier = notifier
        self.notifier = self.executor.notifier
        self.executor.prefs_lookup = self.preferences
        self.executor.app_id_lookup = lambda: self.active_app["app_id"]
        self.app_namer = app_namer or display_app_name
        self.battery_alerts = notify.BatteryAlerts()
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
        # gatilhos das Smart Actions (v2)
        self.clock = clock
        self.app_watcher = app_watcher
        self._injected_shortcuts = shortcuts
        self._real_x = focus is None          # produção: observadores X11 reais (e nova tentativa sem DISPLAY)
        self._x_retry = None
        self._x_tries = 0
        self.triggers = TriggerEngine(self._valid_smart_actions, self._fire_trigger, self._report_trigger_error)
        self._last_fire: dict[str, float] = {}
        self._fires: dict[str, list[float]] = {}
        self._suppress_until: dict[str, float] = {}
        self._online: dict[str, bool] = {}
        self._settled = False                 # 1ª varredura concluída: antes disso "online" é estado inicial
        self.executor.smart.on_start = self._smart_started
        self.executor.smart.on_finish = self._smart_finished

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
        """Observadores de foco/janelas/atalhos. Sem DISPLAY (serviço subiu antes do login gráfico) tenta de novo."""
        if self._real_x:
            session_env.import_from_systemd()
            self.focus = make_focus_watcher(self.scheduler)
        try:
            self.focus.start(self.on_focus_changed)
        except Exception as e:
            log.warning("não foi possível observar o foco (%s); só o perfil global valerá", e)
            self.focus = NullFocusWatcher(str(e))
            self.focus.start(self.on_focus_changed)
        self._start_trigger_sources()
        if self._real_x and display_kind() == "no-display":
            self._schedule_x_retry()

    def _start_trigger_sources(self) -> None:
        """App watcher e backend de atalhos: injetados (testes/fake) ou X11 reais conforme o ambiente."""
        if self._real_x:
            kind = display_kind()
            xlib_ok = True
            try:
                import Xlib  # noqa: F401
            except ImportError:
                xlib_ok = False
            if kind == "x11" and xlib_ok:
                if self.app_watcher is None:
                    try:
                        from .xtriggers import X11AppWatcher
                        w = X11AppWatcher(self.scheduler)
                        w.start(self._on_apps_changed)
                        self.app_watcher = w
                    except Exception as e:
                        log.warning("gatilhos de aplicativo indisponíveis (%s)", e)
                try:
                    from .xtriggers import X11ShortcutBackend
                    self.triggers.attach_shortcuts(X11ShortcutBackend())
                except Exception as e:
                    log.warning("atalhos globais indisponíveis (%s)", e)
                    self.triggers.attach_shortcuts(UnavailableShortcuts(f"não foi possível usar o X11 ({e})"))
            else:
                reason = ("atalhos globais indisponíveis no Wayland" if kind == "wayland"
                          else "atalhos globais indisponíveis: sem acesso ao X11 (DISPLAY ainda não definido)"
                          if kind == "no-display" else "atalhos globais indisponíveis: python-xlib ausente")
                self.triggers.attach_shortcuts(UnavailableShortcuts(reason))
        else:
            if self.app_watcher is not None:
                self.app_watcher.start(self._on_apps_changed)
            if self._injected_shortcuts is not None:
                self.triggers.attach_shortcuts(self._injected_shortcuts)

    def _schedule_x_retry(self) -> None:
        if self._x_retry is None:
            delay = X_RETRY_FAST_MS if self._x_tries < X_RETRY_FAST_TRIES else X_RETRY_SLOW_MS
            self._x_retry = self.scheduler.call_later(delay, self._x_retry_tick)

    def _x_retry_tick(self) -> None:
        self._x_retry = None
        self._x_tries += 1
        session_env.import_from_systemd()
        if display_kind() == "no-display":
            self._schedule_x_retry()
            return
        log.info("ambiente gráfico disponível; iniciando foco, janelas e atalhos")
        if self.focus is not None:
            self.focus.stop()
        self.start_focus()

    def _on_apps_changed(self, opened: list[dict], closed: list[dict]) -> None:
        for a in opened:
            self.triggers.on_app_event("open", a["app_id"])
        for a in closed:
            self.triggers.on_app_event("close", a["app_id"])

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
        if app["app_id"]:
            self.triggers.on_app_event("focus", app["app_id"])
        profile_changed = profile_active = False
        for dev_id, dev in list(self.devices.items()):
            cfg = self._cfg(dev_id)
            self._refresh_router(dev_id)  # solta o que foi pressionado no app anterior
            if profiles.active_profile(cfg, prev) != profiles.active_profile(cfg, app["app_id"]):
                profile_changed = True
                self._notify_updated(dev_id)
            profile_active = profile_active or bool(profiles.active_profile(cfg, app["app_id"]))
            if dev.online:
                self._schedule_settings(dev_id)
        if profile_changed and self.preferences()["osd_profile"]:
            name = self.app_namer(app) if profile_active else "Todos os aplicativos"
            self.notifier.notify("profile", f"Perfil: {name}", timeout_ms=1200, urgency=notify.URGENCY_LOW)

    def debug_set_active_app(self, app_id: str) -> None:
        if not self.debug:
            raise Unsupported("disponível só em modo simulado")
        self._check_app_id(app_id, allow_empty=True)
        if app_id and hasattr(self.app_watcher, "add_app"):
            self.app_watcher.add_app(app_from_props((app_id, app_id), app_id, 0, app_id))  # simula "abrir"
        if hasattr(self.focus, "set_active"):
            self.focus.set_active(app_id)
        else:
            raise Unsupported("sem observador de foco simulado")

    def get_active_app(self) -> str:
        return json.dumps(self.active_app, ensure_ascii=False)

    def get_recent_apps(self) -> str:
        return json.dumps(self.recent_apps, ensure_ascii=False)

    def get_running_apps(self) -> str:
        """ActiveApp de cada aplicativo com janela aberta (seletor de gatilho da GUI)."""
        apps = self.app_watcher.running_apps() if self.app_watcher is not None else []
        return json.dumps(apps, ensure_ascii=False)

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
            self._check_battery(dev)
        self._emit("devices_changed")
        self._emit("device_updated", dev.id, json.dumps(self.device_dict(dev.id), ensure_ascii=False))
        self._track_online(dev.id, dev.online)

    def remove_device(self, dev_id: str) -> None:
        dev = self.devices.pop(dev_id, None)
        self.routers.pop(dev_id, None)
        self._hw.pop(dev_id, None)
        self.battery_alerts.forget(dev_id)
        self._cancel_settings(dev_id)
        self.executor.release_all(dev_id)
        if dev:
            dev.on_event = None
            dev.close()
            self._emit("devices_changed")
            self._track_online(dev_id, False)
        self._online.pop(dev_id, None)

    def rescan(self) -> None:
        for b in self.backends:
            try:
                b.scan(self)
            except Exception:
                log.exception("falha na varredura de dispositivos")
        self._settled = True

    def close(self) -> None:
        if self._x_retry is not None:
            self.scheduler.cancel(self._x_retry)
            self._x_retry = None
        self.triggers.detach_shortcuts()
        if self.app_watcher is not None:
            try:
                self.app_watcher.stop()
            except Exception:
                log.debug("falha ao parar o observador de janelas", exc_info=True)
        self.executor.flush_clipboard()  # não deixa o texto colado (pode ser senha) no CLIPBOARD ao sair
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

    def _smart_lookup(self, sa_id: str, keep_stats: bool = False) -> dict | None:
        sa = self.config.smart_actions.get(sa_id)
        try:
            return validate_smart_action(sa, check_command=False, keep_stats=keep_stats) if sa else None
        except ValueError:
            log.warning("Smart Action %s inválida", sa_id)
            return None

    def _valid_smart_actions(self) -> dict[str, dict]:
        out = {}
        for sid in self.config.smart_actions:
            sa = self._smart_lookup(sid)
            if sa:
                out[sid] = sa
        return out

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
        restoring = profiles.baseline_keys_in_use(cfg, app)
        for key, raw in profiles.settings_targets(cfg, app).items():
            if key not in current or raw_setting(key, current[key]) == raw:
                if key in restoring:
                    self.config.clear_baseline(dev.id, key)
                continue
            try:
                dev.set_setting(key, raw)
                changed = True
                if key in restoring:
                    self.config.clear_baseline(dev.id, key)
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
            self._notify_connection(dev, True)
            self._check_battery(dev)
            self._track_online(dev.id, True)
        elif kind == "offline":
            self.executor.release_all(dev.id)
            if router:
                router.reset()
            self._cancel_settings(dev.id)
            self._emit("devices_changed")
            self._notify_updated(dev.id)
            self._notify_connection(dev, False)
            self._track_online(dev.id, False)
        elif kind == "updated":
            self._notify_updated(dev.id)
            self._check_battery(dev)

    # --- gatilhos de Smart Actions ---
    def _track_online(self, dev_id: str, online: bool) -> None:
        """connect/disconnect só nas transições reais e depois da 1ª varredura (estado inicial não dispara)."""
        prev = self._online.get(dev_id, False)
        self._online[dev_id] = online
        if self._settled and online != prev:
            self.triggers.on_device_event("connect" if online else "disconnect", dev_id)

    def _fire_trigger(self, sa_id: str, trigger: dict) -> None:
        """Proteções: ativa, 1x/2 s, nunca enquanto executa, sem laço (app/device) nem tempestade."""
        sa = self._smart_lookup(sa_id)
        if not sa or not sa["enabled"] or sa_id in self.executor.smart.running:
            return
        now = self.clock()
        if trigger["type"] in ("app", "device") and now < self._suppress_until.get(sa_id, 0.0):
            return  # efeito da própria execução (ex.: "ao abrir o Firefox -> abrir o Firefox")
        if now - self._last_fire.get(sa_id, -1e9) < TRIGGER_MIN_INTERVAL:
            return
        recent = [t for t in self._fires.get(sa_id, []) if now - t < STORM_WINDOW]
        if len(recent) >= STORM_MAX:
            if len(recent) == STORM_MAX:  # avisa uma vez por rajada
                recent.append(now)
                self._emit_error("", f"Smart Action '{sa['name']}' disparando em excesso (possível laço); "
                                     "gatilhos ignorados por 30 s")
            self._fires[sa_id] = recent
            return
        recent.append(now)
        self._fires[sa_id] = recent
        self._last_fire[sa_id] = now
        self._emit("smart_action_triggered", sa_id, json.dumps(trigger, ensure_ascii=False))
        if self.preferences()["osd_gestures"]:
            self.notifier.notify("smart", f"Smart Action: {sa['name']}", timeout_ms=1500,
                                 urgency=notify.URGENCY_LOW)
        self.executor.smart.run(sa_id, "", manual=False)

    def _report_trigger_error(self, msg: str) -> None:
        self._emit_error("", msg)

    def _smart_started(self, sa_id: str) -> None:
        sa = self.config.smart_actions.get(sa_id)
        if not isinstance(sa, dict):
            return
        st = sa["stats"] = smart.sanitize_stats(sa.get("stats"))
        st["runs"] += 1
        st["last_run"] = smart.now_iso()
        try:
            self.config.save()
        except OSError as e:
            log.warning("não foi possível gravar as estatísticas da Smart Action: %s", e)
        self._emit("smart_actions_changed")

    def _smart_finished(self, sa_id: str) -> None:
        self._suppress_until[sa_id] = self.clock() + TRIGGER_SUPPRESS

    # --- notificações ---
    def _notify_connection(self, dev: ManagedDevice, online: bool) -> None:
        if self.preferences()["notify_connection"]:
            name = dev.describe().get("name", dev.id)
            self.notifier.notify(f"connection:{dev.id}", f"{name} {'conectado' if online else 'desconectado'}",
                                 timeout_ms=3000, urgency=notify.URGENCY_LOW)

    def _check_battery(self, dev: ManagedDevice) -> None:
        if not dev.online:
            return
        prefs = self.preferences()
        d = dev.describe()
        for kind in self.battery_alerts.update(dev.id, d.get("battery"), prefs["battery_threshold"]):
            if not prefs["notify_battery"]:
                continue
            level, name = d["battery"]["level"], d.get("name", dev.id)
            if kind == "critical":
                self.notifier.notify(f"battery:{dev.id}", f"Bateria crítica: {name}", f"{level} % restante",
                                     urgency=notify.URGENCY_CRITICAL)
            else:
                self.notifier.notify(f"battery:{dev.id}", f"Bateria baixa: {name}", f"{level} % restante",
                                     urgency=notify.URGENCY_NORMAL)

    def _run(self, dev_id: str, events: list[ActionEvent]) -> None:
        for ev in events:
            if ev.action["type"] == "change_host":
                if ev.kind in ("press", "trigger"):
                    self._change_host_cb(dev_id, ev.action["host"])
            else:
                self.executor.perform(ev)
            if ev.kind in ("press", "trigger"):
                self._announce(dev_id, ev)

    def _smart_name(self, sid) -> str | None:
        sa = self.config.smart_actions.get(sid)
        return sa.get("name") if isinstance(sa, dict) else None

    def _announce(self, dev_id: str, ev: ActionEvent) -> None:
        """ActionTriggered (GUI/bandeja) e OSD de gesto."""
        label = labels.trigger_label(ev.action, ev.direction, self._smart_name)
        if not label:
            return
        self._emit("action_triggered", dev_id, ev.cid, label)
        if ev.direction in ("up", "down", "left", "right") and self.preferences()["osd_gestures"]:
            self.notifier.notify("gesture", label, timeout_ms=800, urgency=notify.URGENCY_LOW)

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
    def _check_size(text: str, limit: int = MAX_JSON_BYTES) -> None:
        if not isinstance(text, str) or len(text.encode("utf-8")) > limit:
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
            sa = self._smart_lookup(sid, keep_stats=True)
            if sa:
                sa["id"] = sid
                sa["trigger_errors"] = self.triggers.trigger_errors(sid)
                out[sid] = sa
        return json.dumps(out, ensure_ascii=False)

    def _new_smart_id(self) -> str:
        if len(self.config.smart_actions) >= MAX_SMART_ACTIONS:
            raise InvalidArgument("limite de Smart Actions atingido")
        sa_id = "sa_" + secrets.token_hex(3)
        while sa_id in self.config.smart_actions:
            sa_id = "sa_" + secrets.token_hex(3)
        return sa_id

    def save_smart_action(self, sa_json: str) -> str:
        """Cria (sem `id`) ou atualiza. Devolve JSON {"id", "warnings": [...]}."""
        self._check_size(sa_json)
        try:
            sa = validate_smart_action(json.loads(sa_json))
        except (ValueError, TypeError, RecursionError) as e:
            raise InvalidArgument(f"Smart Action inválida: {e}") from e
        sa_id = sa.pop("id", None)
        now = smart.now_iso()
        if sa_id is None:
            sa_id = self._new_smart_id()
            sa["stats"] = smart.new_stats(now)
        elif sa_id not in self.config.smart_actions:
            raise NotFound(f"Smart Action não encontrada: {sa_id}")
        else:  # stats são só leitura: preserva e atualiza `modified`
            sa["stats"] = smart.sanitize_stats(self.config.smart_actions[sa_id].get("stats"), now)
            sa["stats"]["modified"] = now
        self.config.put_smart_action(sa_id, sa)
        self.triggers.sync_shortcuts()
        self._emit("smart_actions_changed")
        return json.dumps({"id": sa_id, "warnings": smart_warnings(sa)}, ensure_ascii=False)

    def set_smart_action_enabled(self, sa_id: str, enabled: bool) -> bool:
        sa = self.config.smart_actions.get(sa_id)
        if not isinstance(sa, dict):
            raise NotFound(f"Smart Action não encontrada: {sa_id}")
        if sa.get("enabled", True) != bool(enabled):
            sa["enabled"] = bool(enabled)
            sa["stats"] = smart.sanitize_stats(sa.get("stats"))
            sa["stats"]["modified"] = smart.now_iso()
            self.config.save()
            self.triggers.sync_shortcuts()
            self._emit("smart_actions_changed")
        return True

    def export_smart_action(self, sa_id: str) -> str:
        sa = self._smart_lookup(sa_id)
        if sa is None:
            raise NotFound(f"Smart Action não encontrada: {sa_id}")
        doc = {"openmacros_smart_action": 1, **{k: sa[k] for k in ("name", "description", "icon", "enabled",
                                                                 "triggers", "steps")}}
        return json.dumps(doc, ensure_ascii=False, indent=2)

    def import_smart_action(self, text: str) -> str:
        """Cria uma Smart Action nova (id novo) a partir de um arquivo exportado. Entra DESATIVADA: um arquivo
        de terceiros com gatilho de atalho/aplicativo e passos `command` não deve rodar sem o usuário ligar."""
        self._check_size(text)
        try:
            doc = json.loads(text)
            if not isinstance(doc, dict) or doc.get("openmacros_smart_action") != 1 \
                    or isinstance(doc.get("openmacros_smart_action"), bool):
                raise ValueError("não é uma Smart Action exportada pelo OpenMacros+")
            doc = {k: v for k, v in doc.items() if k not in ("openmacros_smart_action", "id", "stats")}
            sa = validate_smart_action(doc, check_command=False)
        except (ValueError, TypeError, RecursionError) as e:
            raise InvalidArgument(f"Smart Action inválida: {e}") from e
        sa["enabled"] = False
        sa["stats"] = smart.new_stats()
        sa_id = self._new_smart_id()
        self.config.put_smart_action(sa_id, sa)
        self.triggers.sync_shortcuts()
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
        self.triggers.sync_shortcuts()
        self._emit("smart_actions_changed")
        return True

    def run_action(self, action_json: str) -> bool:
        action = self._parse_action(action_json)
        if action["type"] in ("gestures", "change_host", "remap", "default", "disabled"):
            raise InvalidArgument(f"'{action['type']}' não pode ser executada diretamente")
        self.executor.run(action)
        return True

    # --- preferências ---
    def preferences(self) -> dict:
        return preferences.with_defaults(self.config.preferences)

    def get_preferences(self) -> str:
        return json.dumps(self.preferences())

    def set_preference(self, key: str, value_json: str) -> bool:
        self._check_size(value_json)
        try:
            value = preferences.validate_preference(key, json.loads(value_json))
        except (ValueError, RecursionError) as e:  # JSONDecodeError é ValueError
            raise InvalidArgument(f"preferência inválida: {e}") from e
        if self.config.preferences.get(key, preferences.DEFAULTS[key]) != value or key not in self.config.preferences:
            self.config.set_preference(key, value)
            self._emit("preferences_changed", self.get_preferences())
        return True

    # --- backup ---
    def export_config(self) -> str:
        return json.dumps(backup.export_dict(self.config.data), ensure_ascii=False, indent=2)

    def import_config(self, text: str, merge: bool) -> bool:
        self._check_size(text, backup.MAX_IMPORT_BYTES)
        try:
            imported = backup.parse_import(text)
            devices, sas, prefs = backup.plan_import(self.config.data, imported, bool(merge))
        except ValueError as e:
            raise InvalidArgument(str(e)) from e
        try:
            self.config.replace_sections(devices, sas, prefs)
        except OSError as e:
            raise InvalidArgument(f"não foi possível gravar a configuração: {e}") from e
        for dev_id, dev in list(self.devices.items()):
            if dev.online:
                try:
                    self._sync_controls(dev)
                    self._sync_settings(dev)
                except Exception:
                    log.exception("reaplicação após importar falhou em %s", dev_id)
            self._refresh_router(dev_id)
            self._notify_updated(dev_id)
        self.triggers.sync_shortcuts()
        self._emit("smart_actions_changed")
        self._emit("preferences_changed", self.get_preferences())
        return True
