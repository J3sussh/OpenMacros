import json

import pytest
from evdev import ecodes

from clique.daemon import manager as mg
from clique.daemon.actions import ActionExecutor, NullBackend
from clique.daemon.config import Config
from clique.daemon.fake import FakeBackend
from clique.daemon.focus import FakeFocusWatcher
from clique.daemon.timers import ManualScheduler

M720 = "logi:FA4E720A"
KEYS_A = {"type": "keys", "keys": ["KEY_A"]}
KEYS_B = {"type": "keys", "keys": ["KEY_B"]}


class Rec:
    def __init__(self):
        self.calls = []

    def run(self, *a):
        self.calls.append(a)
        return True


@pytest.fixture
def env(tmp_path):
    sched = ManualScheduler()
    be = NullBackend()
    media = Rec()
    ex = ActionExecutor(be, scheduler=sched, media=media, volume=Rec(), windows=Rec())
    focus = FakeFocusWatcher()
    mgr = mg.Manager(Config(tmp_path / "c.json"), ex, sched, focus)
    mgr.debug = True
    mgr.backends.append(FakeBackend())
    mgr.signals = []
    mgr.listeners.append(lambda n, *a: mgr.signals.append((n, a)))
    mgr.rescan()
    mgr.start_focus()
    mgr.be, mgr.sched, mgr.media, mgr.dev = be, sched, media, mgr.devices[M720]
    return mgr


def act(mgr, app, cid, action):
    return mgr.set_profile_assignment(M720, app, cid, json.dumps(action))


def test_app_switch_changes_effective_action(env):
    act(env, "", 82, KEYS_A)
    act(env, "firefox", 82, KEYS_B)
    env.dev.simulate("key_report", [82]); env.dev.simulate("key_report", [])
    assert env.be.log == [("key", ecodes.KEY_A, 1), ("key", ecodes.KEY_A, 0)]
    env.be.log.clear()
    env.debug_set_active_app("firefox")
    env.dev.simulate("key_report", [82]); env.dev.simulate("key_report", [])
    assert env.be.log == [("key", ecodes.KEY_B, 1), ("key", ecodes.KEY_B, 0)]
    env.be.log.clear()
    env.debug_set_active_app("code")          # sem perfil -> global
    env.dev.simulate("key_report", [82]); env.dev.simulate("key_report", [])
    assert env.be.log[0] == ("key", ecodes.KEY_A, 1)


def test_no_firmware_writes_on_app_switch_for_buttons(env):
    act(env, "", 82, KEYS_A)
    act(env, "firefox", 83, {"type": "disabled"})
    before = dict(env.dev.reporting)
    writes = []
    orig = env.dev.apply_control
    env.dev.apply_control = lambda c, a: (writes.append(c), orig(c, a))[1]
    for app in ("firefox", "code", "", "firefox"):
        env.debug_set_active_app(app)
    assert writes == [] and env.dev.reporting == before


def test_divert_is_union_of_all_profiles(env):
    act(env, "firefox", 83, KEYS_A)           # só um perfil de app desvia o 83
    assert env.dev.reporting[83] == (True, False, 0)
    assert 82 not in env.dev.reporting
    act(env, "code", 208, {"type": "gestures"})
    assert env.dev.reporting[208] == (True, True, 0)
    env.remove_profile(M720, "firefox")       # nenhum perfil desvia mais o 83
    assert env.dev.reporting[83] == (False, False, 0)
    assert env.dev.reporting[208] == (True, True, 0)


def test_default_in_diverted_cid_reemits_original_button(env):
    act(env, "firefox", 83, KEYS_A)           # 83 desviado; global = default
    env.dev.simulate("key_report", [83])      # app sem perfil: re-emite BTN_SIDE
    env.dev.simulate("key_report", [])
    assert env.be.log == [("key", ecodes.BTN_SIDE, 1), ("key", ecodes.BTN_SIDE, 0)]
    env.be.log.clear()
    act(env, "firefox", 91, KEYS_A)
    env.dev.simulate("key_report", [91]); env.dev.simulate("key_report", [])
    assert env.be.log == [("rel", ecodes.REL_HWHEEL, -1)]


def test_app_switch_while_button_pressed_releases_old_app_action(env):
    act(env, "", 82, KEYS_A)
    act(env, "firefox", 82, KEYS_B)
    env.dev.simulate("key_report", [82])                      # segura no app global
    assert env.be.log == [("key", ecodes.KEY_A, 1)]
    env.debug_set_active_app("firefox")                       # troca de app com o botão pressionado
    assert env.be.log[-1] == ("key", ecodes.KEY_A, 0)         # soltou o que pressionou no app antigo
    assert env.executor._held == {}
    env.dev.simulate("key_report", [])                        # soltar depois não gera eventos duplicados
    assert env.be.log == [("key", ecodes.KEY_A, 1), ("key", ecodes.KEY_A, 0)]
    env.dev.simulate("key_report", [82])                      # novo clique usa a ação do novo app
    assert env.be.log[-1] == ("key", ecodes.KEY_B, 1)


def test_gesture_in_progress_dropped_on_app_switch(env):
    g = {"type": "gestures", "threshold": 40, "up": {"type": "keys", "keys": ["KEY_UP"]}}
    act(env, "", 208, g)
    act(env, "firefox", 208, {"type": "disabled"})
    env.dev.simulate("key_report", [208])
    env.debug_set_active_app("firefox")
    env.dev.simulate("raw_xy", 0, -100)
    env.dev.simulate("key_report", [])
    assert env.be.log == []


def test_profile_validation_errors(env):
    with pytest.raises(mg.InvalidArgument):
        act(env, "firefox", 82, {"type": "remap", "cid": 83})   # remap só global
    with pytest.raises(mg.InvalidArgument):
        act(env, "firefox", 82, {"type": "smart_action", "id": "sa_nope"})
    with pytest.raises(mg.InvalidArgument):
        env.set_profile_assignment(M720, "x" * 200, 82, json.dumps(KEYS_A))
    with pytest.raises(mg.Unsupported):
        act(env, "firefox", 82, {"type": "gestures"})
    with pytest.raises(mg.Unsupported):
        act(env, "firefox", 0x50, KEYS_A)
    with pytest.raises(mg.NotFound):
        env.set_profile_assignment("nope", "firefox", 82, json.dumps(KEYS_A))
    with pytest.raises(mg.InvalidArgument):
        env.remove_profile(M720, "")


def test_null_removes_override_and_cleans_firmware(env):
    act(env, "firefox", 83, KEYS_A)
    assert env.set_profile_assignment(M720, "firefox", 83, "null")
    assert env.dev.reporting[83] == (False, False, 0)
    assert json.loads(env.get_device(M720))["profiles"]["firefox"]["assignments"] == {}


def test_device_json_has_profiles_and_active_profile(env):
    act(env, "firefox", 83, KEYS_A)
    d = json.loads(env.get_device(M720))
    assert d["profiles"]["firefox"]["assignments"]["83"] == KEYS_A and d["active_profile"] == ""
    env.signals.clear()
    env.debug_set_active_app("firefox")
    d = json.loads(env.get_device(M720))
    assert d["active_profile"] == "firefox"
    names = [n for n, _ in env.signals]
    assert "active_app_changed" in names and "device_updated" in names   # active_profile mudou
    env.signals.clear()
    env.debug_set_active_app("code")      # code não tem perfil: active_profile volta a ""
    assert json.loads(env.get_device(M720))["active_profile"] == ""
    env.signals.clear()
    env.debug_set_active_app("vlc")       # "" -> "" : sem device_updated
    assert [n for n, _ in env.signals] == ["active_app_changed"]


def test_recent_apps_order_dedupe_and_cap(env):
    for a in ("a", "b", "a", ""):
        env.debug_set_active_app(a)
    assert [x["app_id"] for x in json.loads(env.get_recent_apps())] == ["a", "b"]
    for i in range(40):
        env.debug_set_active_app(f"app{i}")
    assert len(json.loads(env.get_recent_apps())) == 30
    assert json.loads(env.get_active_app())["app_id"] == "app39"


def test_debug_only_in_fake_mode(env):
    env.debug = False
    with pytest.raises(mg.Unsupported):
        env.debug_set_active_app("x")


# ---------------------------------------------------------------- settings por app
def test_settings_per_app_debounce_and_only_when_changed(env):
    env.set_profile_setting(M720, "firefox", "scroll_invert", "true")
    assert json.loads(env.get_device(M720))["profiles"]["firefox"]["settings"] == {"scroll_invert": {"value": True}}
    writes = []
    orig = env.dev.set_setting
    env.dev.set_setting = lambda k, v: (writes.append((k, v)), orig(k, v))[1]
    env.debug_set_active_app("firefox")
    env.sched.advance(299)
    assert writes == []                                   # ainda no debounce
    env.debug_set_active_app("code"); env.debug_set_active_app("firefox")   # rajada reinicia o timer
    env.sched.advance(299)
    assert writes == []
    env.sched.advance(1)
    assert writes == [("scroll_invert", True)]
    assert json.loads(env.get_device(M720))["settings"]["scroll_invert"]["value"] is True
    env.debug_set_active_app("firefox2")                  # outro app sem perfil -> restaura o baseline
    env.sched.advance(300)
    assert writes[-1] == ("scroll_invert", False)
    n = len(writes)
    env.debug_set_active_app("firefox3"); env.sched.advance(300)
    assert len(writes) == n                               # efetivo não mudou: nenhuma escrita


def test_global_setting_wins_outside_profile(env):
    env.set_setting(M720, "pointer_speed", "300")
    env.set_profile_setting(M720, "code", "pointer_speed", "100")
    env.debug_set_active_app("code"); env.sched.advance(300)
    assert env.dev.describe()["settings"]["pointer_speed"]["value"] == 100
    env.debug_set_active_app(""); env.sched.advance(300)
    assert env.dev.describe()["settings"]["pointer_speed"]["value"] == 300


def test_set_profile_setting_active_app_applies_immediately_and_null_removes(env):
    env.debug_set_active_app("code")
    env.set_profile_setting(M720, "code", "pointer_speed", "123")
    assert env.dev.describe()["settings"]["pointer_speed"]["value"] == 123
    env.set_profile_setting(M720, "code", "pointer_speed", "null")
    assert json.loads(env.get_device(M720))["profiles"]["code"]["settings"] == {}
    with pytest.raises(mg.InvalidArgument):
        env.set_profile_setting(M720, "code", "pointer_speed", "99999")
    with pytest.raises(mg.Unsupported):
        env.set_profile_setting(M720, "code", "dpi", "800")
    with pytest.raises(mg.InvalidArgument):
        env.set_profile_setting(M720, "code", "bogus", "1")


def test_empty_app_setting_equals_global(env):
    env.set_profile_setting(M720, "", "scroll_invert", "true")
    assert env.config.device(M720)["settings"]["scroll_invert"] is True


def test_reconnect_reapplies_effective_profile(env):
    act(env, "", 208, {"type": "gestures"})
    env.set_profile_setting(M720, "code", "pointer_speed", "77")
    env.debug_set_active_app("code")
    env.dev.reporting.clear()
    env.dev._d["settings"]["pointer_speed"]["value"] = 256     # firmware voltou ao padrão
    env.dev.simulate("online")
    assert env.dev.reporting[208] == (True, True, 0)
    assert env.dev.describe()["settings"]["pointer_speed"]["value"] == 77


# ---------------------------------------------------------------- Smart Actions
SA = {"name": "Dia", "icon": "weather-clear-symbolic",
      "steps": [{"type": "media", "op": "play_pause"}, {"type": "delay", "ms": 50},
                {"type": "volume", "op": "mute"}]}


def test_smart_action_crud_and_run_via_button(env):
    sid = env.save_smart_action(json.dumps(SA))
    assert sid.startswith("sa_")
    assert json.loads(env.get_smart_actions())[sid]["steps"][0]["op"] == "play_pause"
    assert ("smart_actions_changed", ()) in env.signals
    sa2 = dict(SA, id=sid, name="Novo nome")
    assert env.save_smart_action(json.dumps(sa2)) == sid
    assert json.loads(env.get_smart_actions())[sid]["name"] == "Novo nome"
    act(env, "", 82, {"type": "smart_action", "id": sid})
    env.dev.simulate("key_report", [82]); env.dev.simulate("key_report", [])
    assert env.media.calls == [("play_pause", None)]
    env.sched.advance(50)
    assert env.executor.volume.calls == [("mute", 5)]
    with pytest.raises(mg.NotFound):
        env.save_smart_action(json.dumps(dict(SA, id="sa_zzz")))
    with pytest.raises(mg.InvalidArgument):
        env.save_smart_action(json.dumps({"name": "x", "steps": []}))
    with pytest.raises(mg.InvalidArgument):
        env.save_smart_action("x" * 70000)


def test_delete_smart_action_replaces_references_with_default(env):
    sid = env.save_smart_action(json.dumps(SA))
    other = env.save_smart_action(json.dumps(SA))
    ref = {"type": "smart_action", "id": sid}
    act(env, "", 82, ref)
    act(env, "firefox", 83, ref)
    act(env, "", 208, {"type": "gestures", "up": ref, "down": {"type": "smart_action", "id": other}})
    assert env.delete_smart_action(sid) is True
    d = json.loads(env.get_device(M720))
    assert d["assignments"]["82"] == {"type": "default"}
    assert d["profiles"]["firefox"]["assignments"]["83"] == {"type": "default"}
    g = d["assignments"]["208"]
    assert g["up"] == {"type": "default"} and g["down"]["id"] == other
    assert env.dev.reporting[82] == (False, False, 0)      # não é mais desviado
    assert env.dev.reporting[83] == (False, False, 0)
    assert env.delete_smart_action(sid) is False
    assert sid not in json.loads(env.get_smart_actions())


def test_run_action_direct(env):
    assert env.run_action(json.dumps({"type": "media", "op": "next", "player": "vlc"}))
    assert env.media.calls == [("next", "vlc")]
    for bad in ({"type": "gestures"}, {"type": "change_host", "host": 1}, {"type": "smart_action", "id": "sa_no"},
                {"type": "volume", "op": "bogus"}):
        with pytest.raises(mg.InvalidArgument):
            env.run_action(json.dumps(bad))
    with pytest.raises(mg.InvalidArgument):
        env.run_action("{")
