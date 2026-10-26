"""Gatilhos e ações em X11 de verdade, mas só em um Xvfb PRÓPRIO (nunca o DISPLAY do usuário).

Faz o papel do gerenciador de janelas (propriedades _NET_CLIENT_LIST na raiz, mensagens de cliente) e injeta
teclas pelo XTEST. Sem Xvfb instalado, os testes são pulados.
"""
import json
import os
import select
import shutil
import subprocess
import time

import pytest

pytest.importorskip("Xlib")
from gi.repository import GLib  # noqa: E402
from Xlib import X, Xatom, display as xdisplay, error as xerror  # noqa: E402
from Xlib.ext import xtest  # noqa: E402

from openmacros.daemon import integrations as integ  # noqa: E402
from openmacros.daemon import manager as mg  # noqa: E402
from openmacros.daemon import smart  # noqa: E402
from openmacros.daemon.actions import ActionExecutor, NullBackend  # noqa: E402
from openmacros.daemon.config import Config  # noqa: E402
from openmacros.daemon.notify import RecordingNotifier  # noqa: E402
from openmacros.daemon.timers import GLibScheduler  # noqa: E402
from openmacros.daemon.triggers import TriggerEngine  # noqa: E402
from openmacros.daemon.xtriggers import X11AppWatcher, X11ShortcutBackend  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("Xvfb") is None, reason="Xvfb ausente")

KC = lambda code: code + 8  # noqa: E731  evdev -> keycode do X
from evdev import ecodes  # noqa: E402

CTRL_ALT_P = ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_P"]


@pytest.fixture(scope="module")
def xserver():
    r, w = os.pipe()
    p = subprocess.Popen(["Xvfb", "-displayfd", str(w), "-nolisten", "tcp", "-screen", "0", "640x480x24"],
                         pass_fds=(w,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.close(w)
    ready = select.select([r], [], [], 15)[0]
    num = os.read(r, 32).decode().strip() if ready else ""
    os.close(r)
    if not num:
        p.kill()
        pytest.skip("Xvfb não subiu")
    deadline = time.monotonic() + 10  # o número sai antes de o socket aceitar conexões: espere ficar pronto
    while True:
        try:
            xdisplay.Display(f":{num}").close()
            break
        except Exception:
            if time.monotonic() > deadline:
                p.kill()
                pytest.skip("Xvfb não aceitou conexões")
            time.sleep(0.05)
    mp = pytest.MonkeyPatch()
    mp.setenv("DISPLAY", f":{num}")
    mp.delenv("XAUTHORITY", raising=False)
    mp.setenv("XDG_SESSION_TYPE", "x11")
    mp.delenv("WAYLAND_DISPLAY", raising=False)
    yield f":{num}"
    mp.undo()
    p.terminate()
    p.wait(10)


def pump(ms=400, until=None):
    ctx = GLib.MainContext.default()
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        while ctx.iteration(False):
            pass
        if until and until():
            return True
        time.sleep(0.01)
    return bool(until and until())


class Wm:
    """Faz de conta de gerenciador de janelas + clientes + teclado virtual (XTEST)."""

    def __init__(self):
        self.d = xdisplay.Display()
        self.root = self.d.screen().root
        self.clients = []   # conexões abertas (as janelas somem se a conexão fechar)
        self.wins = {}

    def window(self, cls, wtype=None):
        c = xdisplay.Display()
        self.clients.append(c)
        w = c.screen().root.create_window(0, 0, 10, 10, 0, c.screen().root_depth)
        w.set_wm_class(cls.lower(), cls)
        w.change_property(c.intern_atom("_NET_WM_PID"), Xatom.CARDINAL, 32, [os.getpid()])
        if wtype:
            w.change_property(c.intern_atom("_NET_WM_WINDOW_TYPE"), Xatom.ATOM, 32, [c.intern_atom(wtype)])
        c.sync()
        self.wins[w.id] = (c, w)
        return w.id

    def set_clients(self, ids, stacking=True):
        for name in ("_NET_CLIENT_LIST",) + (("_NET_CLIENT_LIST_STACKING",) if stacking else ()):
            self.root.change_property(self.d.intern_atom(name), Xatom.WINDOW, 32, list(ids))
        self.d.sync()

    def key(self, *codes, down_up=True):
        for c in codes:
            xtest.fake_input(self.d, X.KeyPress, KC(c))
        for c in reversed(codes):
            xtest.fake_input(self.d, X.KeyRelease, KC(c))
        self.d.sync()

    def hold(self, code, down):
        xtest.fake_input(self.d, X.KeyPress if down else X.KeyRelease, KC(code))
        self.d.sync()

    def grab_redirect(self):
        self.root.change_attributes(event_mask=X.SubstructureRedirectMask, onerror=xerror.CatchError())
        self.d.sync()

    def client_messages(self):
        out = []
        while self.d.pending_events():
            ev = self.d.next_event()
            if ev.type == X.ClientMessage:
                out.append((ev.window.id, self.d.get_atom_name(ev.client_type), list(ev.data[1])))
        return out

    def close(self):
        for c in self.clients + [self.d]:
            try:
                c.close()
            except Exception:
                pass


@pytest.fixture
def wm(xserver):
    w = Wm()
    yield w
    w.close()


# ------------------------------------------------------------------ atalhos (XGrabKey)
def test_shortcut_backend_grabs_and_fires_with_numlock_and_capslock_variants(wm):
    be = X11ShortcutBackend()
    got = []
    be.start(got.append)
    try:
        combo = smart.parse_shortcut(CTRL_ALT_P)
        assert be.sync({combo}) == {}
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_P)
        assert pump(2000, lambda: len(got) == 1) and got == [combo]
        wm.hold(ecodes.KEY_CAPSLOCK, True)
        wm.hold(ecodes.KEY_CAPSLOCK, False)                      # CapsLock ligado
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_P)
        assert pump(2000, lambda: len(got) == 2)
        wm.hold(ecodes.KEY_NUMLOCK, True)
        wm.hold(ecodes.KEY_NUMLOCK, False)                       # + NumLock ligado
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_P)
        assert pump(2000, lambda: len(got) == 3)
        for k in (ecodes.KEY_CAPSLOCK, ecodes.KEY_NUMLOCK):
            wm.hold(k, True)
            wm.hold(k, False)
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_P)                # outra combinação: ignorada
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_LEFTSHIFT, ecodes.KEY_P)
        pump(300)
        assert len(got) == 3
        assert be.sync(set()) == {}                              # liberou tudo
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_P)
        pump(300)
        assert len(got) == 3
    finally:
        be.stop()


def test_shortcut_without_modifier_f13_and_super(wm):
    be = X11ShortcutBackend()
    got = []
    be.start(got.append)
    try:
        f13 = smart.parse_shortcut(["KEY_F13"])
        sup = smart.parse_shortcut(["KEY_LEFTMETA", "KEY_LEFTSHIFT", "KEY_1"])
        assert be.sync({f13, sup}) == {}
        wm.key(ecodes.KEY_F13)
        wm.key(ecodes.KEY_LEFTMETA, ecodes.KEY_LEFTSHIFT, ecodes.KEY_1)
        assert pump(2000, lambda: len(got) == 2) and set(got) == {f13, sup}
    finally:
        be.stop()


def test_shortcut_conflict_with_another_client_reports_badaccess_and_leaves_no_partial_grab(wm):
    other = xdisplay.Display()
    try:
        root = other.screen().root
        combo = smart.parse_shortcut(CTRL_ALT_P)
        root.grab_key(KC(ecodes.KEY_P), X.ControlMask | X.Mod1Mask | X.LockMask, True, X.GrabModeAsync,
                      X.GrabModeAsync)                            # só a variante com CapsLock já é de outro
        other.sync()
        be = X11ShortcutBackend()
        got = []
        be.start(got.append)
        try:
            errs = be.sync({combo, smart.parse_shortcut(["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_Q"])})
            assert list(errs) == [combo] and "em uso" in errs[combo]
            wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_Q)
            assert pump(2000, lambda: len(got) == 1)              # a outra combinação segue valendo
            # nenhuma variante parcial ficou registrada: libere a do outro e registre de novo
            root.ungrab_key(KC(ecodes.KEY_P), X.ControlMask | X.Mod1Mask | X.LockMask)
            other.sync()
            assert be.sync({combo}) == {}
        finally:
            be.stop()
    finally:
        other.close()


def test_trigger_engine_end_to_end_with_real_x(wm):
    fired = []
    sas = {"sa_1": {"name": "Ctrl+Alt+P", "enabled": True, "steps": [],
                    "triggers": [{"type": "shortcut", "keys": CTRL_ALT_P}]}}
    eng = TriggerEngine(lambda: sas, lambda sid, t: fired.append((sid, t["type"])))
    eng.attach_shortcuts(X11ShortcutBackend())
    try:
        assert eng.trigger_errors("sa_1") == []
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_P)
        assert pump(2000, lambda: fired) and fired == [("sa_1", "shortcut")]
    finally:
        eng.detach_shortcuts()


# ------------------------------------------------------------------ janelas abertas (_NET_CLIENT_LIST)
def test_app_watcher_open_close_initial_state_and_filters(wm):
    ff1, code = wm.window("Firefox"), wm.window("Code")
    dock = wm.window("Xfce4-panel", "_NET_WM_WINDOW_TYPE_DOCK")
    wm.set_clients([ff1, dock])
    events = []
    w = X11AppWatcher(GLibScheduler())
    w.start(lambda opened, closed: events.append(([a["app_id"] for a in opened], [a["app_id"] for a in closed])))
    try:
        assert events == []                                       # estado inicial: nada
        assert [a["app_id"] for a in w.running_apps()] == ["firefox"]   # dock ignorado
        wm.set_clients([ff1, dock, code])
        assert pump(2000, lambda: events) and events == [(["code"], [])]
        ff2 = wm.window("Firefox")
        wm.set_clients([ff1, dock, code, ff2])
        pump(500)
        assert events == [(["code"], [])]                         # 2ª janela do firefox: não é "open"
        wm.set_clients([dock, code, ff2])                         # fechou uma: ainda aberto
        pump(500)
        assert events == [(["code"], [])]
        wm.set_clients([dock])                                    # fechou as últimas
        assert pump(2000, lambda: len(events) == 2)
        assert events[1][0] == [] and sorted(events[1][1]) == ["code", "firefox"]
        assert w.running_apps() == []
    finally:
        w.stop()


def test_app_watcher_debounces_bursts_into_one_callback(wm):
    wins = [wm.window(c) for c in ("A1", "B1", "C1")]
    wm.set_clients([])
    events = []
    w = X11AppWatcher(GLibScheduler())
    w.start(lambda o, c: events.append(sorted(a["app_id"] for a in o)))
    try:
        for i in range(1, 4):
            wm.set_clients(wins[:i])
        assert pump(2000, lambda: events) and events == [["a1", "b1", "c1"]]
    finally:
        w.stop()


# ------------------------------------------------------------------ ação app / system sobre X real
def test_app_controller_close_and_focus_send_ewmh_messages(wm):
    wm.grab_redirect()
    ff1, other, ff2 = wm.window("Firefox"), wm.window("Code"), wm.window("Firefox")
    wm.set_clients([ff1, other, ff2])
    ctl = integ.AppController(Rec(), resolve=lambda t: {"firefox"})
    try:
        assert ctl.run("close", "firefox.desktop") is True
        msgs = wm.client_messages()
        assert [(m[0], m[1]) for m in msgs] == [(ff1, "_NET_CLOSE_WINDOW"), (ff2, "_NET_CLOSE_WINDOW")]
        assert ctl.run("focus", "firefox") is True
        assert [(m[0], m[1]) for m in wm.client_messages()] == [(ff2, "_NET_ACTIVE_WINDOW")]  # a mais recente
        assert integ.AppController(Rec(), ctl.ewmh, resolve=lambda t: {"zzz"}).run("close", "zzz") is False
    finally:
        ctl.ewmh.d.close()


def test_show_desktop_toggles_net_showing_desktop(wm):
    wm.grab_redirect()
    ctl = integ.SystemController()
    try:
        assert ctl.run("show_desktop") is True
        first = wm.client_messages()[-1]
        assert first[1] == "_NET_SHOWING_DESKTOP" and first[2][0] == 1
        wm.root.change_property(wm.d.intern_atom("_NET_SHOWING_DESKTOP"), Xatom.CARDINAL, 32, [1])
        wm.d.sync()
        assert ctl.run("show_desktop") is True
        last = wm.client_messages()[-1]
        assert last[1] == "_NET_SHOWING_DESKTOP" and last[2][0] == 0
    finally:
        ctl.ewmh.d.close()


class Rec:
    def __init__(self):
        self.calls = []

    def launch_app(self, t):
        self.calls.append(t)
        return True


# ------------------------------------------------------------------ Manager em produção (observadores X reais)
def test_manager_real_x_services_fire_app_and_shortcut_triggers(wm, tmp_path):
    sched = GLibScheduler()
    vol = type("V", (), {"calls": [], "run": lambda self, *a: self.calls.append(a) or True})()
    ex = ActionExecutor(NullBackend(), scheduler=sched, volume=vol, notifier=RecordingNotifier())
    mgr = mg.Manager(Config(tmp_path / "c.json"), ex, sched, notifier=RecordingNotifier())
    ff = wm.window("Burp")
    wm.set_clients([])
    sid = json.loads(mgr.save_smart_action(json.dumps({
        "name": "X", "steps": [{"type": "volume", "op": "mute"}],
        "triggers": [{"type": "app", "event": "open", "app_id": "burp"},
                     {"type": "shortcut", "keys": CTRL_ALT_P}]})))["id"]
    mgr.start_focus()
    try:
        assert type(mgr.app_watcher).__name__ == "X11AppWatcher"
        assert json.loads(mgr.get_smart_actions())[sid]["trigger_errors"] == []
        wm.set_clients([ff])
        assert pump(3000, lambda: vol.calls) and vol.calls == [("mute", 5)]
        assert [a["app_id"] for a in json.loads(mgr.get_running_apps())] == ["burp"]
        mgr.clock = lambda: time.monotonic() + 10                # passa a janela de 2 s
        wm.key(ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT, ecodes.KEY_P)
        assert pump(3000, lambda: len(vol.calls) == 2)
    finally:
        mgr.close()
