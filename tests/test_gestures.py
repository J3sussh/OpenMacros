from openmacros.daemon.gestures import ButtonRouter, GestureTracker

KEYS = {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}
GEST = {"type": "gestures", "threshold": 50, "click": {"type": "default"},
        "up": {"type": "keys", "keys": ["KEY_UP"]}, "down": {"type": "keys", "keys": ["KEY_DOWN"]},
        "left": {"type": "keys", "keys": ["KEY_LEFT"]}, "right": {"type": "disabled"}}


def test_tracker_directions():
    for moves, expected in [((60, 0), "right"), ((-60, 5), "left"), ((3, 60), "down"), ((0, -70), "up")]:
        t = GestureTracker(50)
        t.press()
        assert t.move(*moves) == expected


def test_tracker_accumulates_and_fires_once():
    t = GestureTracker(50)
    t.press()
    assert t.move(20, 0) is None
    assert t.move(20, 0) is None
    assert t.move(20, 0) == "right"
    assert t.move(100, 0) is None
    assert t.release() is None


def test_tracker_diagonal_does_not_fire():
    t = GestureTracker(50)
    t.press()
    assert t.move(60, 60) is None  # 45 graus
    assert t.move(100, 0) == "right"  # 160/60 -> ~20 graus


def test_tracker_click():
    t = GestureTracker(50)
    t.press()
    t.move(10, 10)
    assert t.release() == "click"
    assert t.release() is None  # sem pressão ativa


def test_tracker_new_press_resets():
    t = GestureTracker(50)
    t.press()
    t.move(60, 0)
    t.release()
    t.press()
    assert t.move(0, 60) == "down"


def test_router_gesture_sequence():
    r = ButtonRouter({0xD0: GEST})
    assert r.on_key_report([0xD0]) == []
    assert r.on_raw_xy(0, -30) == []
    ev = r.on_raw_xy(2, -30)
    assert len(ev) == 1 and ev[0].kind == "trigger" and ev[0].action["keys"] == ["KEY_UP"]
    assert r.on_raw_xy(0, -100) == []
    assert r.on_key_report([]) == []  # disparou: sem clique


def test_router_gesture_click_default_reemits_original():
    r = ButtonRouter({0xD0: GEST})
    r.on_key_report([0xD0])
    ev = r.on_key_report([])
    assert [(e.kind, e.action["type"], e.cid) for e in ev] == [("trigger", "default", 0xD0)]


def test_router_disabled_direction_is_silent():
    r = ButtonRouter({0xD0: GEST})
    r.on_key_report([0xD0])
    assert r.on_raw_xy(80, 0) == []


def test_router_plain_press_release():
    r = ButtonRouter({0x52: KEYS, 0x53: {"type": "disabled"}})
    ev = r.on_key_report([0x52, 0x53])
    assert [(e.kind, e.cid) for e in ev] == [("press", 0x52)]
    assert r.on_key_report([0x53]) [0].kind == "release"
    assert r.on_key_report([]) == []


def test_router_ignores_unassigned_and_xy_without_gesture():
    r = ButtonRouter({0x52: KEYS})
    assert r.on_key_report([0x99]) == []
    assert r.on_raw_xy(100, 100) == []


def test_set_assignments_releases_pressed_when_changed():
    r = ButtonRouter({0x52: KEYS, 0x53: KEYS}, "dev")
    r.on_key_report([0x52, 0x53])
    ev = r.set_assignments({0x52: KEYS, 0x53: {"type": "disabled"}})  # 0x53 mudou
    assert [(e.kind, e.cid, e.dev_id) for e in ev] == [("release", 0x53, "dev")]
    assert r.pressed == {0x52}
    ev = r.set_assignments({})  # 0x52 sumiu
    assert [(e.kind, e.cid) for e in ev] == [("release", 0x52)]
    assert r.on_key_report([]) == []  # nada de release duplicado


def test_events_carry_dev_id():
    r = ButtonRouter({0x52: KEYS}, "devX")
    assert r.on_key_report([0x52])[0].dev_id == "devX"
