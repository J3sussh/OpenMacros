"""Ações nativas com backends mockados: nada de mídia/volume/navegador reais."""
import pytest
from evdev import ecodes

from clique.daemon.actions import (ActionExecutor, NullBackend, SmartActionRunner, validate_action,
                                   validate_smart_action)
from clique.daemon.gestures import ActionEvent
from clique.daemon.timers import ManualScheduler


class Rec:
    def __init__(self, ret=True):
        self.calls, self.ret = [], ret

    def run(self, *a):
        self.calls.append(a)
        return self.ret


class Opener:
    def __init__(self):
        self.uris, self.desktops = [], []

    def open_uri(self, u):
        self.uris.append(u)
        return True

    def launch_desktop(self, t):
        self.desktops.append(t)
        return True


class Sel:
    def __init__(self, text=""):
        self.text, self.clip = text, []

    def read_primary(self):
        return self.text

    def write_clipboard(self, t):
        self.clip.append(t)
        return True


def make(**kw):
    be = NullBackend()
    sched = ManualScheduler()
    ex = ActionExecutor(be, scheduler=sched, media=kw.get("media", Rec()), volume=kw.get("volume", Rec()),
                        opener=kw.get("opener", Opener()), windows=kw.get("windows", Rec()),
                        selection=kw.get("selection", Sel()))
    return ex, be, sched


def trig(ex, action, dev="d", cid=0):
    ex.perform(ActionEvent("trigger", action, cid, dev))


def test_media_uses_mpris_then_falls_back_to_keys():
    media = Rec(True)
    ex, be, _ = make(media=media)
    trig(ex, {"type": "media", "op": "next", "player": "spotify"})
    assert media.calls == [("next", "spotify")] and be.log == []
    media.ret = False
    trig(ex, {"type": "media", "op": "play_pause"})
    assert be.log == [("key", ecodes.KEY_PLAYPAUSE, 1), ("key", ecodes.KEY_PLAYPAUSE, 0)]
    be.log.clear()
    trig(ex, {"type": "media", "op": "previous"})
    assert be.log[0] == ("key", ecodes.KEY_PREVIOUSSONG, 1)


def test_volume_fallback_to_keys():
    vol = Rec(True)
    ex, be, _ = make(volume=vol)
    trig(ex, {"type": "volume", "op": "up", "step": 10})
    assert vol.calls == [("up", 10)] and be.log == []
    vol.ret = False
    trig(ex, {"type": "volume", "op": "mute", "step": 5})
    assert be.log[0] == ("key", ecodes.KEY_MUTE, 1)


def test_open_url_and_desktop():
    op = Opener()
    ex, *_ = make(opener=op)
    trig(ex, {"type": "open", "target": "https://exemplo.org/x"})
    trig(ex, {"type": "open", "target": "firefox.desktop"})
    assert op.uris == ["https://exemplo.org/x"] and op.desktops == ["firefox.desktop"]


def test_type_text_events_and_unmappable_skipped():
    ex, be, _ = make()
    trig(ex, {"type": "type_text", "text": "Hi é"})
    sh, h, i_, sp = ecodes.KEY_LEFTSHIFT, ecodes.KEY_H, ecodes.KEY_I, ecodes.KEY_SPACE
    assert be.log == [("key", sh, 1), ("key", h, 1), ("key", h, 0), ("key", sh, 0),
                      ("key", i_, 1), ("key", i_, 0), ("key", sp, 1), ("key", sp, 0)]


def test_window_dispatch():
    w = Rec(True)
    ex, *_ = make(windows=w)
    trig(ex, {"type": "window", "op": "close"})
    assert w.calls == [("close",)]


def test_ai_prompt_claude_and_gemini():
    op, sel = Opener(), Sel("trecho selecionado")
    ex, *_ = make(opener=op, selection=sel)
    trig(ex, {"type": "ai_prompt", "service": "claude", "template": "Explique: {selection}"})
    assert op.uris == ["https://claude.ai/new?q=Explique%3A%20trecho%20selecionado"] and sel.clip == []
    trig(ex, {"type": "ai_prompt", "service": "gemini", "template": "Resuma: {selection}"})
    assert op.uris[-1] == "https://gemini.google.com/app" and sel.clip == ["Resuma: trecho selecionado"]


def test_release_event_does_not_rerun_oneshot_actions():
    media = Rec()
    ex, *_ = make(media=media)
    ex.perform(ActionEvent("press", {"type": "media", "op": "next"}, 82, "d"))
    ex.perform(ActionEvent("release", {"type": "media", "op": "next"}, 82, "d"))
    assert len(media.calls) == 1


def test_default_reemit_hold_and_hwheel():
    ex, be, _ = make()
    ex.perform(ActionEvent("press", {"type": "default"}, 0x53, "d"))
    ex.perform(ActionEvent("release", {"type": "default"}, 0x53, "d"))
    assert be.log == [("key", ecodes.BTN_SIDE, 1), ("key", ecodes.BTN_SIDE, 0)]
    be.log.clear()
    ex.perform(ActionEvent("press", {"type": "default"}, 0x5D, "d"))
    ex.perform(ActionEvent("release", {"type": "default"}, 0x5D, "d"))
    ex.perform(ActionEvent("press", {"type": "default"}, 0x5B, "d"))
    assert be.log == [("rel", ecodes.REL_HWHEEL, 1), ("rel", ecodes.REL_HWHEEL, -1)]
    be.log.clear()
    ex.perform(ActionEvent("press", {"type": "default"}, 0xD0, "d"))  # sem equivalente
    assert be.log == []
    ex.perform(ActionEvent("trigger", {"type": "default", "cid": 0x52}, 0x83, "d"))  # destino de remap
    assert be.log[0] == ("key", ecodes.BTN_MIDDLE, 1)


# ---------------------------------------------------------------- validação
@pytest.mark.parametrize("ok", [
    {"type": "media", "op": "play_pause"}, {"type": "media", "op": "next", "player": "spotify"},
    {"type": "volume", "op": "up"}, {"type": "volume", "op": "down", "step": 50},
    {"type": "open", "target": "https://a.b/c"}, {"type": "open", "target": "file:///tmp/x.txt"},
    {"type": "open", "target": "http://localhost:8080/"},
    {"type": "type_text", "text": "x" * 2000}, {"type": "window", "op": "fullscreen"},
    {"type": "ai_prompt", "service": "perplexity"}, {"type": "smart_action", "id": "sa_ab12cd"},
])
def test_validate_new_ok(ok):
    assert validate_action(ok)["type"] == ok["type"]


@pytest.mark.parametrize("bad", [
    {"type": "media", "op": "rewind"}, {"type": "media", "op": "next", "player": "a b; rm"},
    {"type": "volume", "op": "up", "step": 0}, {"type": "volume", "op": "up", "step": 51},
    {"type": "volume", "op": "loud"},
    {"type": "open", "target": "javascript:alert(1)"}, {"type": "open", "target": "ftp://x/y"},
    {"type": "open", "target": "/etc/passwd"}, {"type": "open", "target": "nao-existe-xyz.desktop"},
    {"type": "open", "target": "https://"}, {"type": "open", "target": "https://a/\nb"},
    {"type": "type_text", "text": ""}, {"type": "type_text", "text": "x" * 2001},
    {"type": "window", "op": "explode"}, {"type": "ai_prompt", "service": "bing"},
    {"type": "ai_prompt", "service": "claude", "template": ""},
    {"type": "smart_action", "id": "../x"}, {"type": "smart_action"},
    {"type": "delay", "ms": 100},                      # delay só em Smart Action
])
def test_validate_new_rejects(bad):
    with pytest.raises(ValueError):
        validate_action(bad)


def test_smart_action_validation():
    ok = {"name": " Dia ", "steps": [{"type": "volume", "op": "mute"}, {"type": "delay", "ms": 500},
                                     {"type": "open", "target": "https://a.b"}]}
    out = validate_smart_action(ok)
    assert out["name"] == "Dia" and out["icon"] == "" and len(out["steps"]) == 3
    bad = [
        {"name": "x", "steps": []},
        {"name": "x", "steps": [{"type": "volume", "op": "up"}] * 33},
        {"name": "x", "steps": [{"type": "delay", "ms": 5}]},
        {"name": "x", "steps": [{"type": "delay", "ms": 10001}]},
        {"name": "x", "steps": [{"type": "smart_action", "id": "sa_1"}]},
        {"name": "x", "steps": [{"type": "gestures"}]},
        {"name": "", "steps": [{"type": "volume", "op": "up"}]},
        {"steps": [{"type": "volume", "op": "up"}]},
    ]
    for b in bad:
        with pytest.raises(ValueError):
            validate_smart_action(b)
    assert len(validate_smart_action({"name": "x", "steps": [{"type": "volume", "op": "up"}] * 32})["steps"]) == 32


def test_gesture_directions_accept_new_actions():
    g = validate_action({"type": "gestures", "up": {"type": "media", "op": "next"},
                         "down": {"type": "smart_action", "id": "sa_1"}})
    assert g["up"]["type"] == "media" and g["down"]["id"] == "sa_1"


# ---------------------------------------------------------------- Smart Actions
def test_smart_action_order_delays_and_non_blocking():
    vol, media = Rec(), Rec()
    ex, be, sched = make(volume=vol, media=media)
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [
        {"type": "volume", "op": "mute"}, {"type": "delay", "ms": 500}, {"type": "media", "op": "next"},
        {"type": "delay", "ms": 100}, {"type": "volume", "op": "up"}]}) if i == "sa_1" else None
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert vol.calls == [("mute", 5)] and media.calls == []          # parou no delay sem bloquear
    sched.advance(499)
    assert media.calls == []
    sched.advance(1)
    assert media.calls == [("next", None)] and len(vol.calls) == 1
    sched.advance(99)
    assert len(vol.calls) == 1
    sched.advance(1)
    assert vol.calls == [("mute", 5), ("up", 5)]
    assert ex.smart.running == set() and sched.pending == 0


def test_smart_action_not_reentrant_and_reusable_after_end():
    vol = Rec()
    ex, be, sched = make(volume=vol)
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [
        {"type": "delay", "ms": 100}, {"type": "volume", "op": "up"}]})
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    trig(ex, {"type": "smart_action", "id": "sa_1"})   # clique repetido enquanto executa
    sched.advance(100)
    assert len(vol.calls) == 1
    trig(ex, {"type": "smart_action", "id": "sa_1"})   # pode rodar de novo depois
    sched.advance(100)
    assert len(vol.calls) == 2


def test_smart_action_no_recursion_even_if_config_is_tampered():
    vol = Rec()
    ex, be, sched = make(volume=vol)
    tampered = {"name": "m", "steps": [{"type": "smart_action", "id": "sa_1"}, {"type": "volume", "op": "up"}]}
    ex.smart_lookup = lambda i: tampered
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert len(vol.calls) == 1 and ex.smart.running == set()


def test_smart_action_failing_step_does_not_stop_or_leak():
    class Boom(Rec):
        def run(self, *a):
            raise RuntimeError("x")
    media, vol = Boom(), Rec()
    ex, *_ = make(media=media, volume=vol)
    ex.smart_lookup = lambda i: {"name": "m", "steps": [{"type": "media", "op": "next"},
                                                        {"type": "volume", "op": "up", "step": 5}]}
    trig(ex, {"type": "smart_action", "id": "sa_x"})
    assert vol.calls == [("up", 5)] and ex.smart.running == set()


def test_unknown_smart_action_ignored():
    ex, *_ = make()
    ex.smart_lookup = lambda i: None
    trig(ex, {"type": "smart_action", "id": "sa_none"})
    assert ex.smart.running == set()


def test_smart_action_change_host_uses_device_callback():
    ex, *_ = make()
    seen = []
    ex.change_host_cb = lambda d, h: seen.append((d, h))
    ex.smart_lookup = lambda i: {"name": "m", "steps": [{"type": "change_host", "host": 2}]}
    trig(ex, {"type": "smart_action", "id": "sa_x"}, dev="devA")
    assert seen == [("devA", 2)]
