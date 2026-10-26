import json

import pytest

from clique.daemon import manager as mg
from clique.daemon.actions import ActionExecutor, NullBackend
from clique.daemon.config import Config
from clique.daemon.fake import FakeBackend


@pytest.fixture
def mgr(tmp_path):
    be = NullBackend()
    mgr = mg.Manager(Config(tmp_path / "c.json"), ActionExecutor(be))
    mgr.signals = []
    mgr.listeners.append(lambda name, *a: mgr.signals.append((name, a)))
    mgr.backends.append(FakeBackend())
    mgr.rescan()
    mgr.nullbe = be
    return mgr


M720 = "logi:FA4E720A"
GEN = "logi:FA4E0001"


def test_two_fake_devices(mgr):
    devs = json.loads(mgr.get_devices())
    assert {d["id"] for d in devs} == {M720, GEN}
    m720 = json.loads(mgr.get_device(M720))
    assert [c["cid"] for c in m720["controls"]] == [82, 83, 86, 91, 93, 208]
    assert m720["hosts"]["count"] == 3 and m720["battery"]["level"] == 50
    assert "dpi" not in m720["settings"] and "dpi" in json.loads(mgr.get_device(GEN))["settings"]
    assert json.loads(mgr.get_device(GEN))["battery"] is None


def test_set_assignment_updates_and_signals(mgr):
    mgr.signals.clear()
    assert mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}))
    d = json.loads(mgr.get_device(M720))
    assert d["assignments"]["82"]["keys"] == ["KEY_LEFTCTRL", "KEY_C"]
    assert mgr.signals[-1][0] == "device_updated" and mgr.signals[-1][1][0] == M720
    # persistiu
    assert mgr.config.device(M720)["assignments"]["82"]["type"] == "keys"


def test_gesture_requires_rawxy(mgr):
    g = json.dumps({"type": "gestures"})
    assert mgr.set_assignment(M720, 208, g)
    with pytest.raises(mg.Unsupported):
        mgr.set_assignment(M720, 82, g)


def test_errors(mgr):
    with pytest.raises(mg.NotFound):
        mgr.get_device("nope")
    with pytest.raises(mg.InvalidArgument):
        mgr.set_assignment(M720, 82, "{bad")
    with pytest.raises(mg.InvalidArgument):
        mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_NOPE"]}))
    with pytest.raises(mg.Unsupported):
        mgr.set_assignment(M720, 0x50, json.dumps({"type": "disabled"}))
    with pytest.raises(mg.Unsupported):
        mgr.set_setting(M720, "dpi", "800")
    with pytest.raises(mg.InvalidArgument):
        mgr.set_setting(M720, "pointer_speed", "99999")
    with pytest.raises(mg.InvalidArgument):
        mgr.set_setting(M720, "hires_scroll", '"yes"')
    with pytest.raises(mg.InvalidArgument):
        mgr.set_setting(M720, "bogus", "1")
    with pytest.raises(mg.Unsupported):
        mgr.change_host(GEN, 1)
    with pytest.raises(mg.InvalidArgument):
        mgr.change_host(M720, 3)


def test_settings_and_host(mgr):
    assert mgr.set_setting(M720, "pointer_speed", "300")
    assert mgr.set_setting(M720, "scroll_invert", "true")
    assert mgr.set_setting(GEN, "dpi", "1600")
    assert mgr.change_host(M720, 2)
    m720 = json.loads(mgr.get_device(M720))
    assert m720["settings"]["pointer_speed"]["value"] == 300
    assert m720["settings"]["scroll_invert"]["value"] is True
    assert m720["hosts"]["current"] == 2
    assert json.loads(mgr.get_device(GEN))["settings"]["dpi"]["value"] == 1600


def test_reset(mgr):
    mgr.set_assignment(M720, 82, json.dumps({"type": "disabled"}))
    assert mgr.reset_device(M720)
    assert json.loads(mgr.get_device(M720))["assignments"] == {}
    assert mgr.devices[M720].reporting == {}


def test_button_event_runs_action(mgr):
    from evdev import ecodes
    mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_A"]}))
    dev = mgr.devices[M720]
    dev.simulate("key_report", [82])
    dev.simulate("key_report", [])
    assert mgr.nullbe.log == [("key", ecodes.KEY_A, 1), ("key", ecodes.KEY_A, 0)]


def test_gesture_event_changes_host(mgr):
    mgr.set_assignment(M720, 208, json.dumps(
        {"type": "gestures", "threshold": 40, "left": {"type": "change_host", "host": 0}}))
    dev = mgr.devices[M720]
    dev.simulate("key_report", [208])
    dev.simulate("raw_xy", -50, 0)
    dev.simulate("key_report", [])
    assert json.loads(mgr.get_device(M720))["hosts"]["current"] == 0


def test_reapply_on_reconnect(tmp_path):
    cfg = Config(tmp_path / "c.json")
    cfg.set_assignment(M720, 208, {"type": "gestures", "click": {"type": "default"}, "up": {"type": "disabled"},
                                   "down": {"type": "disabled"}, "left": {"type": "disabled"},
                                   "right": {"type": "disabled"}, "threshold": 50})
    cfg.set_setting(M720, "pointer_speed", 111)
    mgr = mg.Manager(cfg, ActionExecutor(NullBackend()))
    mgr.backends.append(FakeBackend())
    mgr.rescan()
    dev = mgr.devices[M720]
    assert dev.reporting[208] == (True, True, 0)
    assert dev.describe()["settings"]["pointer_speed"]["value"] == 111


def test_offline_rejects(mgr):
    dev = mgr.devices[M720]
    dev.online = False
    dev.simulate("offline")
    assert json.loads(mgr.get_device(M720))["online"] is False
    with pytest.raises(mg.DeviceOffline):
        mgr.set_setting(M720, "pointer_speed", "300")


def test_offline_and_replace_release_held_keys(mgr):
    from evdev import ecodes
    mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}))
    dev = mgr.devices[M720]
    dev.simulate("key_report", [82])
    assert mgr.nullbe.log[-1] == ("key", ecodes.KEY_C, 1)
    dev.online = False
    dev.simulate("offline")  # desconectou com a tecla pressionada
    assert mgr.nullbe.log[-2:] == [("key", ecodes.KEY_C, 0), ("key", ecodes.KEY_LEFTCTRL, 0)]
    assert mgr.executor._held == {}


def test_changing_assignment_releases_pressed(mgr):
    from evdev import ecodes
    mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_A"]}))
    mgr.devices[M720].simulate("key_report", [82])
    mgr.set_assignment(M720, 82, json.dumps({"type": "disabled"}))
    assert mgr.nullbe.log == [("key", ecodes.KEY_A, 1), ("key", ecodes.KEY_A, 0)]


def test_reset_and_remove_release(mgr):
    mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_A"]}))
    mgr.devices[M720].simulate("key_report", [82])
    mgr.reset_device(M720)
    assert mgr.executor._held == {}
    mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_A"]}))
    mgr.devices[M720].simulate("key_report", [82])
    mgr.remove_device(M720)
    assert mgr.executor._held == {}


def test_close_releases_everything(mgr):
    mgr.set_assignment(M720, 82, json.dumps({"type": "keys", "keys": ["KEY_A"]}))
    mgr.devices[M720].simulate("key_report", [82])
    mgr.close()
    assert mgr.executor._held == {}


def test_size_limit_and_command_validation(mgr):
    with pytest.raises(mg.InvalidArgument):
        mgr.set_assignment(M720, 82, "[" * 100000)
    with pytest.raises(mg.InvalidArgument):
        mgr.set_assignment(M720, 82, "x" * 70000)
    with pytest.raises(mg.InvalidArgument):
        mgr.set_assignment(M720, 82, json.dumps({"type": "command", "argv": ["nao-existe-xyz"]}))
    assert mgr.set_assignment(M720, 82, json.dumps({"type": "command", "argv": ["true"]}))


def test_recording_executor_logs_instead_of_executing(tmp_path):
    from clique.daemon.actions import RecordingExecutor
    from clique.daemon.timers import ManualScheduler
    sched = ManualScheduler()
    ex = RecordingExecutor(scheduler=sched)
    m = mg.Manager(Config(None), ex, sched)
    m.backends.append(FakeBackend())
    m.rescan()
    m.set_assignment(M720, 82, json.dumps({"type": "open", "target": "https://exemplo.org"}))
    m.devices[M720].simulate("key_report", [82])
    m.devices[M720].simulate("key_report", [])
    m.run_action(json.dumps({"type": "volume", "op": "mute"}))
    assert [e["action"]["type"] for e in ex.executed] == ["open", "open", "volume"]
    assert ex.backend.log == []     # nada de uinput
