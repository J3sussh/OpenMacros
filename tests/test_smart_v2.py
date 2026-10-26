"""Smart Actions v2 (docs/design/SMART_ACTIONS.md §1-4): formato, gatilhos, proteções, ações novas, D-Bus, estatísticas.

Tudo com fakes: nada de X real, uinput, pactl, systemctl, suspend/lock/screenshot de verdade.
"""
import json

import pytest
from evdev import ecodes

from openmacros.daemon import backup, smart
from openmacros.daemon import manager as mg
from openmacros.daemon.actions import (ActionExecutor, NullBackend, RecordingExecutor, smart_warnings,
                                   validate_action, validate_smart_action)
from openmacros.daemon.config import Config
from openmacros.daemon.fake import FakeBackend
from openmacros.daemon.focus import FakeFocusWatcher, app_from_props
from openmacros.daemon.notify import RecordingNotifier
from openmacros.daemon.timers import ManualScheduler
from openmacros.daemon.triggers import FakeAppWatcher, FakeShortcuts, UnavailableShortcuts

M720 = "logi:FA4E720A"
GEN = "logi:FA4E0001"
MUTE = {"type": "volume", "op": "mute"}
CTRL_ALT_P = ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_P"]


class Rec:
    def __init__(self, ret=True):
        self.calls, self.ret = [], ret

    def run(self, *a):
        self.calls.append(a)
        return self.ret


class Sel:
    def __init__(self, primary="", clipboard="anterior"):
        self.primary, self.clipboard = primary, clipboard
        self.writes, self.cleared = [], 0

    def read_primary(self):
        return self.primary

    def read_clipboard(self):
        return self.clipboard

    def write_clipboard(self, t):
        self.writes.append(t)
        self.clipboard = t
        return True

    def clear_clipboard(self):
        self.cleared += 1
        self.clipboard = None
        return True


class Opener:
    def __init__(self):
        self.uris = []

    def open_uri(self, u):
        self.uris.append(u)
        return True

    def launch_desktop(self, t):
        return True


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def sa_json(name="SA", triggers=None, steps=None, **kw):
    return json.dumps({"name": name, "triggers": triggers or [], "steps": steps or [MUTE], **kw})


def sid_of(result: str) -> str:
    return json.loads(result)["id"]


@pytest.fixture
def env(tmp_path):
    sched, be, note, clock = ManualScheduler(), NullBackend(), RecordingNotifier(), Clock()
    ex = ActionExecutor(be, scheduler=sched, media=Rec(), volume=Rec(), windows=Rec(), selection=Sel(),
                        opener=Opener(), apps=Rec(), system=Rec())
    watcher, shortcuts = FakeAppWatcher(), FakeShortcuts()
    mgr = mg.Manager(Config(tmp_path / "c.json"), ex, sched, FakeFocusWatcher(), notifier=note,
                     app_watcher=watcher, shortcuts=shortcuts, clock=clock)
    mgr.debug = True
    mgr.backends.append(FakeBackend())
    mgr.signals = []
    mgr.listeners.append(lambda n, *a: mgr.signals.append((n, a)))
    mgr.rescan()
    mgr.start_focus()
    mgr.note, mgr.sched, mgr.clock_, mgr.watcher, mgr.shortcuts = note, sched, clock, watcher, shortcuts
    mgr.dev, mgr.path, mgr.ex = mgr.devices[M720], tmp_path / "c.json", ex
    return mgr


def sigs(env, name):
    return [a for n, a in env.signals if n == name]


def app(app_id):
    return app_from_props((app_id, app_id), app_id, 0, app_id)


def fired(env):
    return [a[0] for a in sigs(env, "smart_action_triggered")]


# ------------------------------------------------------------------ §1 formato e migração
def test_v1_entries_are_migrated_with_defaults(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"version": 1, "devices": {}, "smart_actions": {
        "sa_old": {"name": "Antiga", "icon": "x", "steps": [MUTE]}}}))
    cfg = Config(p)
    sa = cfg.smart_actions["sa_old"]
    assert sa["enabled"] is True and sa["triggers"] == [] and sa["description"] == ""
    assert sa["stats"]["runs"] == 0 and sa["stats"]["last_run"] is None and sa["stats"]["created"]
    assert cfg.data["version"] == 1  # versão do config inalterada
    mgr = mg.Manager(cfg, ActionExecutor(NullBackend(), scheduler=ManualScheduler()), ManualScheduler())
    got = json.loads(mgr.get_smart_actions())["sa_old"]
    assert got["id"] == "sa_old" and got["trigger_errors"] == [] and got["enabled"] is True


def test_migrate_is_idempotent_and_fixes_bad_fields():
    once = smart.migrate({"name": "x", "steps": [], "enabled": "sim", "triggers": "nada", "stats": {"runs": -3}})
    assert once["enabled"] is True and once["triggers"] == [] and once["stats"]["runs"] == 0
    assert smart.migrate(once, now="2000") == once


def test_validate_smart_action_v2_fields():
    out = validate_smart_action({"name": " x ", "description": "d", "enabled": False,
                                 "triggers": [{"type": "device", "event": "connect"}], "steps": [MUTE],
                                 "stats": {"runs": 99}})
    assert out["name"] == "x" and out["enabled"] is False and out["description"] == "d"
    assert out["triggers"] == [{"type": "device", "event": "connect", "device_id": "*"}]
    assert "stats" not in out  # só leitura: ignorado na entrada
    assert validate_smart_action({"name": "x", "steps": [MUTE], "stats": {"runs": 4}}, keep_stats=True
                                 )["stats"]["runs"] == 4
    for bad in ({"name": "x", "steps": [MUTE], "enabled": "sim"},
                {"name": "x", "steps": [MUTE], "description": "d" * 301},
                {"name": "x", "steps": [MUTE], "triggers": [{"type": "device", "event": "connect"}] * 6},
                {"name": "x", "steps": [MUTE], "triggers": "x"}):
        with pytest.raises(ValueError):
            validate_smart_action(bad)


# ------------------------------------------------------------------ §2 validação de gatilhos
@pytest.mark.parametrize("trigger", [
    {"type": "shortcut", "keys": CTRL_ALT_P},
    {"type": "shortcut", "keys": ["KEY_F13"]},
    {"type": "shortcut", "keys": ["KEY_F24"]},
    {"type": "shortcut", "keys": ["KEY_PLAYPAUSE"]},
    {"type": "shortcut", "keys": ["KEY_LEFTMETA", "KEY_LEFTSHIFT", "KEY_1"]},
    {"type": "app", "event": "open", "app_id": "Firefox"},
    {"type": "app", "event": "focus", "app_id": "burp-startburp"},
    {"type": "device", "event": "disconnect", "device_id": "*"},
    {"type": "device", "event": "connect", "device_id": M720},
])
def test_valid_triggers(trigger):
    out = smart.validate_trigger(trigger)
    assert out["type"] == trigger["type"]
    if trigger["type"] == "app":
        assert out["app_id"] == trigger["app_id"].lower()


@pytest.mark.parametrize("trigger", [
    {"type": "shortcut", "keys": ["KEY_P"]},                         # sem modificador
    {"type": "shortcut", "keys": ["KEY_F12"]},                       # F1..F12 precisam de modificador
    {"type": "shortcut", "keys": ["KEY_LEFTCTRL"]},                  # só modificador
    {"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_A", "KEY_B"]},  # duas teclas principais
    {"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTCTRL", "KEY_A"]},
    {"type": "shortcut", "keys": ["KEY_RIGHTALT", "KEY_A"]},         # AltGr depende do layout
    {"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_NOPE"]},
    {"type": "shortcut", "keys": ["BTN_LEFT", "KEY_LEFTCTRL"]},
    {"type": "shortcut", "keys": []}, {"type": "shortcut"},
    {"type": "app", "event": "minimize", "app_id": "x"}, {"type": "app", "event": "open"},
    {"type": "app", "event": "open", "app_id": ""}, {"type": "app", "event": "open", "app_id": "a\nb"},
    {"type": "device", "event": "boot"}, {"type": "device", "event": "connect", "device_id": "a b"},
    {"type": "usb"}, "texto", None,
])
def test_invalid_triggers(trigger):
    with pytest.raises(ValueError):
        smart.validate_trigger(trigger)


def test_shortcut_keycodes_and_labels():
    c = smart.parse_shortcut(CTRL_ALT_P)
    assert c == smart.Combo(ecodes.KEY_P + 8, smart.CTRL | smart.ALT)
    assert smart.parse_shortcut(["KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_P"]).mods == smart.CTRL
    assert smart.combo_label(CTRL_ALT_P) == "Ctrl+Alt+P"
    assert smart.combo_label(["KEY_LEFTMETA", "KEY_F5"]) == "Super+F5"


# ------------------------------------------------------------------ §3 validação de ações novas
def test_validate_new_actions():
    assert validate_action({"type": "app", "op": "open", "target": "firefox.desktop"},
                           check_command=False)["target"] == "firefox.desktop"
    assert validate_action({"type": "app", "op": "close", "target": "firefox"}) == \
        {"type": "app", "op": "close", "target": "firefox"}
    for bad in ({"type": "app", "op": "kill", "target": "firefox"}, {"type": "app", "op": "open"},
                {"type": "app", "op": "open", "target": "rm -rf /"}, {"type": "app", "op": "open", "target": "a/b"},
                {"type": "app", "op": "open", "target": ""}):
        with pytest.raises(ValueError):
            validate_action(bad, check_command=False)
    ev = [{"key": "KEY_A", "down": True, "delay_ms": 0}, {"key": "KEY_A", "down": False, "delay_ms": 30}]
    assert validate_action({"type": "key_sequence", "events": ev})["events"] == ev
    assert validate_action({"type": "key_sequence", "events": [{"key": "KEY_A", "down": True}]})["events"][0][
        "delay_ms"] == 0
    assert len(validate_action({"type": "key_sequence", "events": ev * 200})["events"]) == 400
    for bad in ([], ev * 201, [{"key": "KEY_A"}], [{"key": "KEY_NOPE", "down": True}],
                [{"key": "KEY_A", "down": True, "delay_ms": 10001}], [{"key": "KEY_A", "down": 1}], "x"):
        with pytest.raises(ValueError):
            validate_action({"type": "key_sequence", "events": bad})
    for op in ("lock", "screenshot", "screenshot_area", "suspend", "show_desktop", "mic_mute", "dnd_on",
               "dnd_off", "dnd_toggle", "empty_trash"):
        assert validate_action({"type": "system", "op": op}) == {"type": "system", "op": op}
    with pytest.raises(ValueError):
        validate_action({"type": "system", "op": "reboot"})


def test_command_is_allowed_in_steps_and_ai_template_up_to_4000():
    sa = validate_smart_action({"name": "x", "steps": [{"type": "command", "argv": ["/bin/true"]}]})
    assert sa["steps"][0]["type"] == "command"
    ai = {"type": "ai_prompt", "service": "claude", "template": "x" * 4000}
    assert validate_action(ai)["template"] == "x" * 4000
    with pytest.raises(ValueError):
        validate_action({**ai, "template": "x" * 4001})
    with pytest.raises(ValueError):
        validate_action({"type": "type_text", "text": "x" * 2001})  # o texto continua em 2000


def test_type_text_secret_warnings_do_not_echo_the_text(env):
    r = json.loads(env.save_smart_action(sa_json(steps=[
        {"type": "type_text", "text": "password=hunter2"}, MUTE, {"type": "type_text", "text": "olá, tudo bem"}])))
    assert len(r["warnings"]) == 1 and "Passo 1" in r["warnings"][0] and "hunter2" not in r["warnings"][0]
    assert smart_warnings({"steps": [MUTE]}) == []
    r2 = json.loads(env.save_smart_action(sa_json()))
    assert r2["warnings"] == [] and r2["id"].startswith("sa_")


# ------------------------------------------------------------------ SaveSmartAction / stats
def test_save_returns_json_and_stats_are_read_only(env):
    r = json.loads(env.save_smart_action(sa_json("A", stats={"runs": 99, "last_run": "x"})))
    sa = json.loads(env.get_smart_actions())[r["id"]]
    assert sa["stats"]["runs"] == 0 and sa["stats"]["last_run"] is None
    created = sa["stats"]["created"]
    env.run_action(json.dumps({"type": "smart_action", "id": r["id"]}))
    env.run_action(json.dumps({"type": "smart_action", "id": r["id"]}))
    sa = json.loads(env.get_smart_actions())[r["id"]]
    assert sa["stats"]["runs"] == 2 and sa["stats"]["last_run"]
    # editar preserva runs/created (a GUI não consegue zerar nem forjar)
    env.save_smart_action(json.dumps({**{"id": r["id"], "name": "B", "steps": [MUTE]}, "stats": {"runs": 0}}))
    sa = json.loads(env.get_smart_actions())[r["id"]]
    assert sa["name"] == "B" and sa["stats"]["runs"] == 2 and sa["stats"]["created"] == created
    assert json.loads(env.path.read_text())["smart_actions"][r["id"]]["stats"]["runs"] == 2  # persistiu
    with pytest.raises(mg.NotFound):
        env.save_smart_action(json.dumps({"id": "sa_nada", "name": "x", "steps": [MUTE]}))
    with pytest.raises(mg.InvalidArgument):
        env.save_smart_action(sa_json(triggers=[{"type": "shortcut", "keys": ["KEY_P"]}]))


def test_runs_counted_for_button_trigger_and_manual(env):
    sid = sid_of(env.save_smart_action(sa_json(triggers=[{"type": "app", "event": "open", "app_id": "x"}])))
    env.set_assignment(M720, 86, json.dumps({"type": "smart_action", "id": sid}))
    env.dev.simulate("key_report", [86])
    env.dev.simulate("key_report", [])
    env.clock_.t += 5  # fora da janela de supressão (2 s) da execução anterior
    env.watcher.add_app(app("x"))
    env.run_action(json.dumps({"type": "smart_action", "id": sid}))
    assert json.loads(env.get_smart_actions())[sid]["stats"]["runs"] == 3


# ------------------------------------------------------------------ enabled
def test_disabled_smart_action_ignores_triggers_and_buttons_but_manual_run_works(env):
    sid = sid_of(env.save_smart_action(sa_json(triggers=[{"type": "app", "event": "open", "app_id": "x"}])))
    env.set_assignment(M720, 86, json.dumps({"type": "smart_action", "id": sid}))
    assert env.set_smart_action_enabled(sid, False) is True
    assert json.loads(env.get_smart_actions())[sid]["enabled"] is False
    env.watcher.add_app(app("x"))
    env.dev.simulate("key_report", [86])
    env.dev.simulate("key_report", [])
    assert env.ex.volume.calls == [] and fired(env) == []
    env.run_action(json.dumps({"type": "smart_action", "id": sid}))  # "Experimentar" continua funcionando
    assert env.ex.volume.calls == [("mute", 5)]
    env.clock_.t += 5
    env.set_smart_action_enabled(sid, True)
    env.watcher.set_apps([])
    env.watcher.add_app(app("x"))
    assert fired(env) == [sid]
    assert len(sigs(env, "smart_actions_changed")) >= 3
    with pytest.raises(mg.NotFound):
        env.set_smart_action_enabled("sa_nada", True)


# ------------------------------------------------------------------ gatilho app
def test_app_open_close_focus_and_initial_state(tmp_path):
    sched = ManualScheduler()
    watcher = FakeAppWatcher()
    watcher.set_apps([app("firefox")])  # já aberto antes de o serviço subir
    focus = FakeFocusWatcher()
    ex = ActionExecutor(NullBackend(), scheduler=sched, volume=Rec(), selection=Sel())
    mgr = mg.Manager(Config(tmp_path / "c.json"), ex, sched, focus, notifier=RecordingNotifier(),
                     app_watcher=watcher, clock=Clock())
    mgr.signals = []
    mgr.listeners.append(lambda n, *a: mgr.signals.append((n, a)))
    ids = {}
    for ev in ("open", "close", "focus"):
        ids[ev] = sid_of(mgr.save_smart_action(sa_json(ev, triggers=[{"type": "app", "event": ev,
                                                                      "app_id": "firefox"}])))
    mgr.start_focus()
    assert fired(mgr) == []                      # estado inicial NÃO dispara "open"
    watcher.set_apps([])                         # fechou a última janela -> close
    assert fired(mgr) == [ids["close"]]
    mgr.clock = lambda: 2000.0
    mgr.signals.clear()
    watcher.add_app(app("firefox"))              # reabriu -> open
    assert fired(mgr) == [ids["open"]]
    mgr.clock = lambda: 3000.0
    focus.set_active("firefox")                  # ganhou o foco
    assert ids["focus"] in fired(mgr)
    mgr.signals.clear()
    watcher.add_app(app("firefox"))              # 2ª janela do mesmo app: já estava aberto -> nada
    assert fired(mgr) == []


def test_app_trigger_matches_case_insensitive_and_ignores_other_apps(env):
    sid = sid_of(env.save_smart_action(sa_json(triggers=[{"type": "app", "event": "open", "app_id": "FireFox"}])))
    env.watcher.add_app(app("chromium"))
    assert fired(env) == []
    env.watcher.add_app(app("firefox"))
    assert fired(env) == [sid]


def test_two_matching_triggers_fire_once_per_event(env):
    sid = sid_of(env.save_smart_action(sa_json(triggers=[
        {"type": "app", "event": "open", "app_id": "x"}, {"type": "app", "event": "open", "app_id": "x"}])))
    env.watcher.add_app(app("x"))
    assert fired(env) == [sid] and len(env.ex.volume.calls) == 1


def test_get_running_apps(env):
    env.watcher.set_apps([app("zeta"), app("alfa")])
    got = json.loads(env.get_running_apps())
    assert [a["app_id"] for a in got] == ["alfa", "zeta"] and set(got[0]) >= {"app_id", "title", "pid", "exe"}
    bare = mg.Manager(Config(None), ActionExecutor(NullBackend()))
    assert json.loads(bare.get_running_apps()) == []


# ------------------------------------------------------------------ gatilho device
def test_device_connect_disconnect_and_initial_scan_does_not_fire(tmp_path):
    sched, clock = ManualScheduler(), Clock()
    ex = ActionExecutor(NullBackend(), scheduler=sched, volume=Rec(), selection=Sel())
    mgr = mg.Manager(Config(tmp_path / "c.json"), ex, sched, FakeFocusWatcher(), notifier=RecordingNotifier(),
                     clock=clock)
    mgr.signals = []
    mgr.listeners.append(lambda n, *a: mgr.signals.append((n, a)))
    on = sid_of(mgr.save_smart_action(sa_json("on", triggers=[{"type": "device", "event": "connect",
                                                               "device_id": "*"}])))
    off = sid_of(mgr.save_smart_action(sa_json("off", triggers=[{"type": "device", "event": "disconnect",
                                                                 "device_id": M720}])))
    other = sid_of(mgr.save_smart_action(sa_json("other", triggers=[{"type": "device", "event": "disconnect",
                                                                     "device_id": GEN}])))
    mgr.backends.append(FakeBackend())
    mgr.rescan()                                  # dispositivos já presentes: estado inicial
    assert fired(mgr) == []
    dev = mgr.devices[M720]
    dev.online = False
    dev.simulate("offline")
    assert fired(mgr) == [off]
    clock.t += 10
    dev.online = True
    dev.simulate("online")                        # inclui a volta do Easy-Switch
    assert fired(mgr) == [off, on]
    clock.t += 10
    dev.simulate("online")                        # já online: sem transição
    assert fired(mgr) == [off, on]
    mgr.remove_device(GEN)                        # desplugou: disconnect do GEN
    assert fired(mgr)[-1] == other


def test_new_device_after_first_scan_fires_connect(tmp_path):
    sched = ManualScheduler()
    mgr = mg.Manager(Config(tmp_path / "c.json"), ActionExecutor(NullBackend(), scheduler=sched, volume=Rec(),
                                                                 selection=Sel()), sched, FakeFocusWatcher(),
                     notifier=RecordingNotifier(), clock=Clock())
    mgr.signals = []
    mgr.listeners.append(lambda n, *a: mgr.signals.append((n, a)))
    sid = sid_of(mgr.save_smart_action(sa_json(triggers=[{"type": "device", "event": "connect"}])))
    mgr.rescan()  # sem backends: só marca a varredura inicial como feita
    mgr.backends.append(FakeBackend())
    mgr.rescan()
    assert fired(mgr) == [sid]


# ------------------------------------------------------------------ proteções
def test_trigger_rate_limit_one_per_two_seconds(env):
    sid = sid_of(env.save_smart_action(sa_json(triggers=[{"type": "app", "event": "open", "app_id": "x"}])))
    env.watcher.add_app(app("x"))
    for t in (0.5, 1.9):
        env.clock_.t += t
        env.watcher.set_apps([])
        env.watcher.add_app(app("x"))
    # (0.5 s e 2.4 s depois do 1º disparo: o 2º foi barrado; o 3º passou de 2 s)
    assert fired(env) == [sid, sid]
    assert len(env.ex.volume.calls) == 2


def test_trigger_not_fired_while_running_and_suppresses_own_app_events(env):
    # "ao abrir x -> abrir x": a própria ação reabre o app (evento open) durante a execução + 2 s
    steps = [{"type": "app", "op": "open", "target": "x"}, {"type": "delay", "ms": 500}, MUTE]
    sid = sid_of(env.save_smart_action(sa_json(triggers=[{"type": "app", "event": "open", "app_id": "x"}],
                                               steps=steps)))
    env.ex.apps.run = lambda op, target: env.watcher.add_app(app(target)) or True
    env.watcher.add_app(app("x"))          # dispara; passo 1 "abre" x => open de novo (ignorado: executando)
    assert fired(env) == [sid] and sid in env.ex.smart.running
    env.sched.advance(500)
    assert env.ex.smart.running == set() and env.ex.volume.calls == [("mute", 5)]
    env.clock_.t += 1.0                     # 1 s depois de terminar: ainda dentro dos 2 s de supressão
    env.watcher.set_apps([])
    env.watcher.add_app(app("x"))
    assert fired(env) == [sid]
    env.clock_.t += 2.5                     # fora da janela: dispara de novo
    env.watcher.set_apps([])
    env.watcher.add_app(app("x"))
    assert fired(env) == [sid, sid]


def test_cross_smart_action_loop_is_cut_off(env):
    """A abre B e B abre A: a rajada é cortada (no máx. 6 disparos/30 s por Smart Action) e avisada."""
    a = sid_of(env.save_smart_action(sa_json("A", triggers=[{"type": "app", "event": "open", "app_id": "a"}],
                                             steps=[{"type": "app", "op": "open", "target": "b"}])))
    b = sid_of(env.save_smart_action(sa_json("B", triggers=[{"type": "app", "event": "open", "app_id": "b"}],
                                             steps=[{"type": "app", "op": "open", "target": "a"}])))

    def open_app(op, target):
        env.watcher.set_apps([])
        env.watcher.add_app(app(target))
        return True
    env.ex.apps.run = open_app
    for _ in range(40):
        env.clock_.t += 2.1
        env.watcher.set_apps([])
        env.watcher.add_app(app("a"))
    assert len(fired(env)) <= 2 * 6 + 2
    assert any("excesso" in a[1] for a in sigs(env, "error"))
    assert a != b


def test_trigger_osd_and_signal_payload(env):
    trig = {"type": "app", "event": "open", "app_id": "x"}
    sid = sid_of(env.save_smart_action(sa_json("Modo reunião", triggers=[trig])))
    env.watcher.add_app(app("x"))
    sid_sig, payload = sigs(env, "smart_action_triggered")[0]
    assert sid_sig == sid and json.loads(payload) == trig
    assert env.note.sent[-1]["summary"] == "Smart Action: Modo reunião" and env.note.sent[-1]["category"] == "smart"
    env.set_preference("osd_gestures", "false")
    n = len(env.note.sent)
    env.clock_.t += 5
    env.watcher.set_apps([])
    env.watcher.add_app(app("x"))
    assert len(env.note.sent) == n and len(fired(env)) == 2  # o sinal sai, o OSD não


# ------------------------------------------------------------------ gatilho atalho
def test_shortcut_trigger_fires_and_released_when_disabled_or_deleted(env):
    trig = {"type": "shortcut", "keys": CTRL_ALT_P}
    sid = sid_of(env.save_smart_action(sa_json(triggers=[trig])))
    combo = smart.parse_shortcut(CTRL_ALT_P)
    assert env.shortcuts.grabbed == {combo}
    env.shortcuts.press(combo)
    assert fired(env) == [sid] and json.loads(sigs(env, "smart_action_triggered")[0][1]) == trig
    env.set_smart_action_enabled(sid, False)
    assert env.shortcuts.grabbed == set()          # desativada libera a combinação
    env.shortcuts.press(combo)
    assert len(fired(env)) == 1
    env.set_smart_action_enabled(sid, True)
    assert env.shortcuts.grabbed == {combo}
    env.delete_smart_action(sid)
    assert env.shortcuts.grabbed == set()


def test_shortcut_conflicts_go_to_trigger_errors_and_error_signal_once(env):
    combo = smart.parse_shortcut(CTRL_ALT_P)
    env.shortcuts.fail[combo] = "já está em uso por outro programa"
    sid = sid_of(env.save_smart_action(sa_json("Reunião", triggers=[
        {"type": "app", "event": "open", "app_id": "x"}, {"type": "shortcut", "keys": CTRL_ALT_P}])))
    errs = json.loads(env.get_smart_actions())[sid]["trigger_errors"]
    assert len(errs) == 1 and errs[0]["index"] == 1 and "Ctrl+Alt+P" in errs[0]["message"]
    assert "em uso" in errs[0]["message"]
    es = sigs(env, "error")
    assert len(es) == 1 and es[0][0] == "" and "Reunião" in es[0][1]
    both = [{"type": "app", "event": "open", "app_id": "x"}, {"type": "shortcut", "keys": CTRL_ALT_P}]
    env.save_smart_action(json.dumps({"id": sid, "name": "Reunião", "steps": [MUTE], "triggers": both}))
    assert len(sigs(env, "error")) == 1            # mesmo erro: não repete o toast
    env.shortcuts.fail.clear()
    env.save_smart_action(json.dumps({"id": sid, "name": "Reunião", "steps": [MUTE], "triggers": both}))
    assert json.loads(env.get_smart_actions())[sid]["trigger_errors"] == []


def test_same_shortcut_in_two_smart_actions_second_gets_error(env):
    a = sid_of(env.save_smart_action(sa_json("A", triggers=[{"type": "shortcut", "keys": CTRL_ALT_P}])))
    b = sid_of(env.save_smart_action(sa_json("B", triggers=[{"type": "shortcut", "keys": CTRL_ALT_P}])))
    sas = json.loads(env.get_smart_actions())
    assert sas[a]["trigger_errors"] == [] and "já é usado" in sas[b]["trigger_errors"][0]["message"]
    env.shortcuts.press(smart.parse_shortcut(CTRL_ALT_P))
    assert fired(env) == [a]


def test_shortcuts_unavailable_report_reason_and_still_work_for_other_triggers(tmp_path):
    sched = ManualScheduler()
    mgr = mg.Manager(Config(tmp_path / "c.json"), ActionExecutor(NullBackend(), scheduler=sched, volume=Rec(),
                                                                 selection=Sel()), sched, FakeFocusWatcher(),
                     notifier=RecordingNotifier(), shortcuts=UnavailableShortcuts("atalhos globais indisponíveis "
                                                                                  "no Wayland"), clock=Clock())
    mgr.start_focus()
    sid = sid_of(mgr.save_smart_action(sa_json(triggers=[{"type": "shortcut", "keys": CTRL_ALT_P}])))
    errs = json.loads(mgr.get_smart_actions())[sid]["trigger_errors"]
    assert errs and "Wayland" in errs[0]["message"]


def test_import_config_resyncs_shortcuts(env):
    doc = {"openmacros_export": 1, "smart_actions": {"sa_imp": {
        "name": "I", "steps": [MUTE], "triggers": [{"type": "shortcut", "keys": CTRL_ALT_P}]}}}
    env.import_config(json.dumps(doc), True)
    assert env.shortcuts.grabbed == {smart.parse_shortcut(CTRL_ALT_P)}


# ------------------------------------------------------------------ exportar / importar
def test_export_and_import_smart_action(env):
    sid = sid_of(env.save_smart_action(sa_json("Modo reunião", description="mic mudo", icon="camera-video-symbolic",
                                               triggers=[{"type": "shortcut", "keys": CTRL_ALT_P}])))
    env.run_action(json.dumps({"type": "smart_action", "id": sid}))
    exp = json.loads(env.export_smart_action(sid))
    assert exp["openmacros_smart_action"] == 1 and "id" not in exp and "stats" not in exp
    assert set(exp) == {"openmacros_smart_action", "name", "description", "icon", "enabled", "triggers", "steps"}
    new = env.import_smart_action(json.dumps(exp))
    assert new != sid and new.startswith("sa_")
    got = json.loads(env.get_smart_actions())[new]
    assert got["name"] == "Modo reunião" and got["stats"]["runs"] == 0
    assert got["enabled"] is False                     # entra desativada (arquivo de terceiros)
    assert "já é usado" not in json.dumps(got["trigger_errors"])  # desativada não disputa a combinação
    with pytest.raises(mg.NotFound):
        env.export_smart_action("sa_nada")


@pytest.mark.parametrize("bad", [
    "não é json", "[]", "{}", '{"openmacros_smart_action": 2, "name": "x", "steps": [{"type":"volume","op":"mute"}]}',
    '{"openmacros_smart_action": true, "name": "x", "steps": [{"type":"volume","op":"mute"}]}',
    '{"openmacros_smart_action": 1, "name": "x", "steps": []}',
    '{"openmacros_smart_action": 1, "name": "x", "steps": [{"type":"smart_action","id":"sa_1"}]}',
    '{"openmacros_smart_action": 1, "name": "x", "steps": [{"type":"volume","op":"mute"}], '
    '"triggers": [{"type":"shortcut","keys":["KEY_P"]}]}',
])
def test_import_smart_action_rejects_invalid(env, bad):
    before = dict(env.config.smart_actions)
    with pytest.raises(mg.InvalidArgument):
        env.import_smart_action(bad)
    assert env.config.smart_actions == before


def test_import_ignores_foreign_id_and_stats_and_respects_limit(env):
    doc = {"openmacros_smart_action": 1, "id": "sa_hack", "stats": {"runs": 999}, "name": "x", "steps": [MUTE]}
    new = env.import_smart_action(json.dumps(doc))
    assert new != "sa_hack" and env.config.smart_actions[new]["stats"]["runs"] == 0
    for i in range(mg.MAX_SMART_ACTIONS - 1):
        env.config.smart_actions[f"sa_{i}"] = {"name": "n", "steps": [MUTE]}
    with pytest.raises(mg.InvalidArgument):
        env.import_smart_action(json.dumps(doc))


# ------------------------------------------------------------------ D-Bus (introspecção e autorização)
def test_dbus_interface_has_new_members_and_write_methods():
    from openmacros.daemon import dbus_service as ds
    xml = ds.introspection_xml(False)
    for name in ("SetSmartActionEnabled", "ExportSmartAction", "ImportSmartAction", "GetRunningApps",
                 "SmartActionTriggered", "SaveSmartAction"):
        assert f'name="{name}"' in xml
    assert {"SetSmartActionEnabled", "ImportSmartAction"} <= ds.WRITE_METHODS
    assert not {"ExportSmartAction", "GetRunningApps"} & ds.WRITE_METHODS


# ------------------------------------------------------------------ backup: limites também após mesclar
def _imp(devices=None, sas=None):
    doc = {"openmacros_export": 1}
    if devices is not None:
        doc["devices"] = devices
    if sas is not None:
        doc["smart_actions"] = sas
    return backup.parse_import(json.dumps(doc))


def test_backup_limits_apply_after_merge():
    cur = {"devices": {f"logi:D{i}": {"assignments": {}, "settings": {}} for i in range(backup.MAX_DEVICES)}}
    imported = _imp(devices={"logi:NOVO": {"assignments": {}, "settings": {}}})
    with pytest.raises(ValueError, match="dispositivos demais"):
        backup.plan_import(cur, imported, True)
    backup.plan_import(cur, imported, False)  # substituir: só o arquivo vale (1 dispositivo)
    # mesclar um dispositivo existente não passa do limite
    backup.plan_import(cur, _imp(devices={"logi:D0": {"assignments": {}, "settings": {}}}), True)

    profs = {f"app{i}": {"assignments": {"82": {"type": "keys", "keys": ["KEY_A"]}}, "settings": {}}
             for i in range(backup.MAX_PROFILES)}
    cur2 = {"devices": {"logi:D": {"assignments": {}, "settings": {}, "profiles": profs}}}
    more = _imp(devices={"logi:D": {"assignments": {}, "settings": {}, "profiles": {
        "outro": {"assignments": {"82": {"type": "keys", "keys": ["KEY_B"]}}, "settings": {}}}}})
    with pytest.raises(ValueError, match="perfis demais"):
        backup.plan_import(cur2, more, True)
    backup.plan_import(cur2, more, False)

    sas = {f"sa_{i}": {"name": "n", "steps": [MUTE]} for i in range(backup.MAX_SMART_ACTIONS)}
    with pytest.raises(ValueError, match="Smart Actions demais"):
        backup.plan_import({"smart_actions": sas}, _imp(sas={"sa_novo": {"name": "n", "steps": [MUTE]}}), True)


def test_backup_roundtrip_keeps_v2_fields_and_stats(env):
    sid = sid_of(env.save_smart_action(sa_json(triggers=[{"type": "device", "event": "connect"}],
                                               description="d", enabled=False)))
    exp = json.loads(env.export_config())
    assert exp["smart_actions"][sid]["triggers"] and exp["smart_actions"][sid]["enabled"] is False
    assert env.import_config(json.dumps(exp), False)
    again = json.loads(env.export_config())
    exp.pop("exported_at"), again.pop("exported_at")
    assert again == exp
