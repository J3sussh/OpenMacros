import pytest

from openmacros.daemon.actions import ActionExecutor, NullBackend, validate_action
from openmacros.daemon.gestures import ActionEvent
from evdev import ecodes


def test_validate_ok():
    assert validate_action({"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]})["keys"][1] == "KEY_C"
    g = validate_action({"type": "gestures", "up": {"type": "keys", "keys": ["KEY_UP"]}})
    assert g["threshold"] == 50 and g["click"] == {"type": "default"} and g["left"] == {"type": "disabled"}


@pytest.mark.parametrize("bad", [
    {}, {"type": "x"}, {"type": "keys", "keys": []}, {"type": "keys", "keys": ["FOO"]},
    {"type": "keys", "keys": ["KEY_NOPE"]}, {"type": "mouse_button", "button": "KEY_A"},
    {"type": "command", "argv": "ls"}, {"type": "command", "argv": []},
    {"type": "change_host", "host": -1}, {"type": "remap", "cid": True},
    {"type": "gestures", "up": {"type": "gestures"}}, {"type": "gestures", "threshold": 0},
    "str",
])
def test_validate_rejects(bad):
    with pytest.raises(ValueError):
        validate_action(bad)


def test_executor_keys_hold_and_release():
    be = NullBackend()
    ex = ActionExecutor(be)
    a = {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}
    ex.perform(ActionEvent("press", a, 1))
    ex.perform(ActionEvent("release", a, 1))
    ctrl, c = ecodes.KEY_LEFTCTRL, ecodes.KEY_C
    assert be.log == [("key", ctrl, 1), ("key", c, 1), ("key", c, 0), ("key", ctrl, 0)]


def test_executor_default_reemits_button():
    be = NullBackend()
    ActionExecutor(be).perform(ActionEvent("trigger", {"type": "default"}, 0x53))
    assert be.log == [("key", ecodes.BTN_SIDE, 1), ("key", ecodes.BTN_SIDE, 0)]


def test_executor_command(tmp_path):
    import time
    out = tmp_path / "ran"
    ActionExecutor(NullBackend()).perform(
        ActionEvent("trigger", {"type": "command", "argv": ["touch", str(out)]}, 1))
    for _ in range(50):
        if out.exists():
            break
        time.sleep(0.05)
    assert out.exists()


def test_command_validation():
    assert validate_action({"type": "command", "argv": ["touch", "/tmp/x"]})
    assert validate_action({"type": "command", "argv": ["/bin/true"]})
    for bad in (["/nao/existe"], ["programa-que-nao-existe-xyz"], ["/etc/passwd"]):
        with pytest.raises(ValueError):
            validate_action({"type": "command", "argv": bad})
    # na carga da config não exige que o programa ainda exista
    assert validate_action({"type": "command", "argv": ["sumiu-xyz"]}, check_command=False)


class FailingBackend(NullBackend):
    def __init__(self, fail_on_code):
        super().__init__()
        self.fail_on_code = fail_on_code

    def key(self, code, value):
        if code == self.fail_on_code and value == 1:
            raise OSError("uinput morreu")
        super().key(code, value)


def test_rollback_when_press_fails_midway():
    ctrl, c = ecodes.KEY_LEFTCTRL, ecodes.KEY_C
    be = FailingBackend(c)
    ex = ActionExecutor(be)
    a = {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}
    ex.perform(ActionEvent("press", a, 1, "d"))
    assert be.log == [("key", ctrl, 1), ("key", ctrl, 0)]  # CTRL solto
    assert ex._held == {}


def test_held_is_per_device_and_release_all():
    be = NullBackend()
    ex = ActionExecutor(be)
    a = {"type": "keys", "keys": ["KEY_A"]}
    b = {"type": "keys", "keys": ["KEY_B"]}
    ex.perform(ActionEvent("press", a, 82, "dev1"))
    ex.perform(ActionEvent("press", b, 82, "dev2"))  # mesmo CID, outro dispositivo
    assert set(ex._held) == {("dev1", 82), ("dev2", 82)}
    be.log.clear()
    ex.release_all("dev1")
    assert be.log == [("key", ecodes.KEY_A, 0)]
    ex.perform(ActionEvent("release", b, 82, "dev2"))
    assert be.log[-1] == ("key", ecodes.KEY_B, 0) and ex._held == {}
