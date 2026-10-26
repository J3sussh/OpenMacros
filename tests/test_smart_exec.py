"""Execução das ações novas (app, key_sequence, system), CLIPBOARD (revisão) e ambiente gráfico tardio."""
import json
import os
import stat

import pytest
from evdev import ecodes

from openmacros.daemon import integrations as integ
from openmacros.daemon import manager as mg
from openmacros.daemon import session_env
from openmacros.daemon.actions import (ActionExecutor, NullBackend, RecordingExecutor, validate_action,
                                   validate_smart_action)
from openmacros.daemon.config import Config
from openmacros.daemon.focus import FakeFocusWatcher, NullFocusWatcher
from openmacros.daemon.gestures import ActionEvent
from openmacros.daemon.notify import RecordingNotifier
from openmacros.daemon.timers import ManualScheduler
from openmacros.daemon.triggers import FakeShortcuts, UnavailableShortcuts

A = ecodes.KEY_A
CTRL, V = ecodes.KEY_LEFTCTRL, ecodes.KEY_V


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


def make(**kw):
    be = kw.pop("backend", None) or NullBackend()
    sched = ManualScheduler()
    ex = ActionExecutor(be, scheduler=sched, media=Rec(), volume=kw.pop("volume", Rec()), windows=Rec(),
                        selection=kw.pop("selection", Sel()), opener=Opener(), notifier=RecordingNotifier(),
                        apps=kw.pop("apps", Rec()), system=kw.pop("system", Rec()), **kw)
    return ex, be, sched


def trig(ex, action, dev="d"):
    ex.perform(ActionEvent("trigger", action, 0, dev))


def seq(*evs):
    return {"type": "key_sequence", "events": [{"key": k, "down": d, "delay_ms": ms} for k, d, ms in evs]}


# ------------------------------------------------------------------ key_sequence
def test_key_sequence_plays_with_delays_without_blocking():
    ex, be, sched = make()
    trig(ex, seq(("KEY_A", True, 0), ("KEY_A", False, 50), ("KEY_B", True, 100), ("KEY_B", False, 0)))
    assert be.log == [("key", A, 1)]                    # parou no atraso (50 ms) sem bloquear
    sched.advance(49)
    assert len(be.log) == 1
    sched.advance(1)
    assert be.log[-1] == ("key", A, 0) and len(be.log) == 2
    sched.advance(100)
    assert be.log[2:] == [("key", ecodes.KEY_B, 1), ("key", ecodes.KEY_B, 0)]
    assert sched.pending == 0 and ex._sequences == []


def test_key_sequence_releases_everything_at_the_end():
    ex, be, sched = make()
    trig(ex, seq(("KEY_LEFTCTRL", True, 0), ("KEY_LEFTSHIFT", True, 0), ("KEY_A", True, 10)))
    sched.advance(10)
    # terminou com tudo pressionado: solta em ordem inversa
    assert be.log[-3:] == [("key", A, 0), ("key", ecodes.KEY_LEFTSHIFT, 0), ("key", CTRL, 0)]
    pressed = {(c) for (_, c, v) in be.log if v == 1} - {c for (_, c, v) in be.log if v == 0}
    assert pressed == set()


def test_key_sequence_releases_on_error():
    class Flaky(NullBackend):
        def key(self, code, value):
            if code == ecodes.KEY_B and value == 1:
                raise OSError("uinput caiu")
            super().key(code, value)
    ex, be, sched = make(backend=Flaky())
    trig(ex, seq(("KEY_LEFTCTRL", True, 0), ("KEY_B", True, 0), ("KEY_C", True, 0)))
    assert be.log == [("key", CTRL, 1), ("key", CTRL, 0)]  # soltou o que estava preso; C nunca foi enviado
    assert ex._sequences == []


def test_key_sequence_aborted_by_shutdown_releases_keys_and_cancels_timer():
    ex, be, sched = make()
    trig(ex, seq(("KEY_LEFTCTRL", True, 0), ("KEY_A", True, 5000)))
    assert be.log == [("key", CTRL, 1)] and sched.pending == 1
    ex.release_everything()
    assert be.log[-1] == ("key", CTRL, 0) and sched.pending == 0 and ex._sequences == []


def test_key_sequence_is_a_blocking_step_inside_smart_actions():
    vol = Rec()
    ex, be, sched = make(volume=vol)
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [
        seq(("KEY_A", True, 0), ("KEY_A", False, 200)), {"type": "volume", "op": "up"}]})
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert vol.calls == [] and "sa_1" in ex.smart.running      # espera a sequência terminar
    sched.advance(200)
    assert vol.calls == [("up", 5)] and ex.smart.running == set()


def test_key_sequence_error_does_not_leave_smart_action_stuck():
    class Dead(NullBackend):
        def key(self, code, value):
            raise OSError("sem uinput")
    vol = Rec()
    ex, be, sched = make(backend=Dead(), volume=vol)
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [
        seq(("KEY_A", True, 0)), {"type": "volume", "op": "up"}]})
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert vol.calls == [("up", 5)] and ex.smart.running == set()


def test_recording_executor_records_key_sequence_without_running_it():
    ex = RecordingExecutor(scheduler=ManualScheduler())
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [seq(("KEY_A", True, 9000))]})
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert [e["action"]["type"] for e in ex.executed] == ["smart_action", "key_sequence"]
    assert ex.smart.running == set()


# ------------------------------------------------------------------ app / system (executor com fakes)
def test_app_and_system_actions_dispatch_to_controllers():
    apps, system = Rec(), Rec()
    ex, be, _ = make(apps=apps, system=system)
    trig(ex, {"type": "app", "op": "focus", "target": "firefox"})
    trig(ex, {"type": "system", "op": "lock"})
    assert apps.calls == [("focus", "firefox")] and system.calls == [("lock",)]


def test_mic_mute_falls_back_to_the_mic_key_and_others_only_log():
    system = Rec(False)
    ex, be, _ = make(system=system)
    trig(ex, {"type": "system", "op": "mic_mute"})
    assert be.log == [("key", ecodes.KEY_MICMUTE, 1), ("key", ecodes.KEY_MICMUTE, 0)]
    be.log.clear()
    trig(ex, {"type": "system", "op": "dnd_on"})
    trig(ex, {"type": "system", "op": "suspend"})
    assert be.log == []


def test_system_actions_never_run_for_real_in_recording_executor():
    ex = RecordingExecutor(scheduler=ManualScheduler())
    for op in ("suspend", "lock", "empty_trash", "screenshot"):
        ex.run({"type": "system", "op": op})
    assert [e["action"]["op"] for e in ex.executed] == ["suspend", "lock", "empty_trash", "screenshot"]


# ------------------------------------------------------------------ SystemController
class SysHarness:
    def __init__(self, tools, ok=(), out=None):
        self.tools, self.ok, self.out, self.calls = set(tools), set(ok), out, []
        self.ctl = integ.SystemController(runner=self.runner, capture=self.capture,
                                          which=lambda n: f"/usr/bin/{n}" if n in self.tools else None,
                                          ewmh=Rec())

    def runner(self, argv, wait=True):
        self.calls.append((argv, wait))
        return os.path.basename(argv[0]) in self.ok

    def capture(self, argv):
        self.calls.append((argv, "capture"))
        return self.out


def test_system_lock_falls_back_in_order():
    h = SysHarness({"loginctl", "xflock4", "xdg-screensaver"}, ok={"xflock4"})
    assert h.ctl.run("lock") is True
    assert [c[0][0] for c in h.calls] == ["loginctl", "xflock4"]
    h = SysHarness({"xdg-screensaver"}, ok={"xdg-screensaver"})
    assert h.ctl.run("lock") and h.calls[0][0] == ["xdg-screensaver", "lock"]
    assert SysHarness(set()).ctl.run("lock") is False


def test_system_screenshot_suspend_trash_and_mic_commands():
    cases = {
        "screenshot": (["xfce4-screenshooter", "-f"], "xfce4-screenshooter"),
        "screenshot_area": (["xfce4-screenshooter", "-r"], "xfce4-screenshooter"),
        "suspend": (["systemctl", "suspend"], "systemctl"),
        "empty_trash": (["gio", "trash", "--empty"], "gio"),
        "mic_mute": (["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"], "pactl"),
    }
    for op, (argv, tool) in cases.items():
        h = SysHarness({tool}, ok={tool})
        assert h.ctl.run(op) is True and h.calls[0][0] == argv, op
    h = SysHarness({"gnome-screenshot"}, ok={"gnome-screenshot"})  # sem o do XFCE: cai no GNOME
    assert h.ctl.run("screenshot_area") and h.calls[0][0] == ["gnome-screenshot", "-a"]
    h = SysHarness({"wpctl"}, ok={"wpctl"})                         # sem pactl: wpctl
    assert h.ctl.run("mic_mute") and h.calls[0][0][:3] == ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@"]


def test_system_dnd_xfce_and_unsupported():
    NOTIFYD = ["-c", "xfce4-notifyd", "-p", "/do-not-disturb"]
    h = SysHarness({"xfconf-query"}, ok={"xfconf-query"})
    assert h.ctl.run("dnd_on") and h.calls[0][0] == ["/usr/bin/xfconf-query", *NOTIFYD, "-n", "-t", "bool", "-s", "true"]
    h = SysHarness({"xfconf-query"}, ok={"xfconf-query"})
    h.ctl.run("dnd_off")
    assert h.calls[0][0][-1] == "false"
    h = SysHarness({"xfconf-query"}, ok={"xfconf-query"}, out="true\n")
    h.ctl.run("dnd_toggle")
    assert h.calls[-1][0][-1] == "false"                       # estava ligado -> desliga
    h = SysHarness({"xfconf-query"}, ok={"xfconf-query"}, out="false\n")
    h.ctl.run("dnd_toggle")
    assert h.calls[-1][0][-1] == "true"
    assert SysHarness(set()).ctl.run("dnd_on") is False        # outros DEs: unsupported (só log)


def test_system_show_desktop_uses_ewmh():
    h = SysHarness(set())
    ewmh = Rec()
    ewmh.toggle_show_desktop = lambda: ewmh.calls.append(("toggle",))
    h.ctl._ewmh = ewmh
    assert h.ctl.run("show_desktop") and ewmh.calls == [("toggle",)] and h.calls == []


# ------------------------------------------------------------------ AppController
class FakeEwmh:
    def __init__(self, windows):
        self.windows = windows            # wid -> app dict, ordem = empilhamento (embaixo -> em cima)
        self.msgs = []

    def client_list_stacking(self):
        return list(self.windows)

    def client_list(self):
        return list(self.windows)

    def window_app(self, wid):
        return self.windows.get(wid, {})

    def is_normal(self, wid):
        return True

    def client_message(self, wid, atom, data):
        self.msgs.append((wid, atom, list(data)))


def win(app_id, exe=""):
    return {"app_id": app_id, "exe": exe, "title": "", "pid": 0, "wm_class": []}


def test_app_controller_close_focus_open():
    ewmh = FakeEwmh({10: win("firefox"), 11: win("code"), 12: win("firefox"), 13: win("outro")})
    opener = Rec()
    opener.launch_app = lambda t: opener.calls.append(("launch", t)) or True
    ctl = integ.AppController(opener, ewmh, resolve=lambda t: {"firefox"})
    assert ctl.run("close", "firefox.desktop") is True
    assert ewmh.msgs == [(10, "_NET_CLOSE_WINDOW", [0, 2]), (12, "_NET_CLOSE_WINDOW", [0, 2])]
    ewmh.msgs.clear()
    assert ctl.run("focus", "firefox") and ewmh.msgs == [(12, "_NET_ACTIVE_WINDOW", [2, 0, 0])]  # a mais recente
    ewmh.windows.clear()
    assert ctl.run("close", "firefox") is False                  # nada aberto
    assert ctl.run("focus", "firefox") is True and opener.calls == [("launch", "firefox")]  # sem janela: abre
    assert ctl.run("open", "firefox") and opener.calls[-1] == ("launch", "firefox")


def test_app_controller_matches_by_exe_and_survives_errors():
    ewmh = FakeEwmh({1: win("", exe="Obsidian")})
    ctl = integ.AppController(Rec(), ewmh, resolve=lambda t: {"obsidian"})
    assert ctl.run("focus", "obsidian") and ewmh.msgs
    ewmh.client_list_stacking = lambda: (_ for _ in ()).throw(RuntimeError("x11 morreu"))
    assert ctl.run("close", "obsidian") is False


def test_app_ids_for_target_forms():
    ids = integ.app_ids_for("org.mozilla.firefox.desktop")
    assert {"org.mozilla.firefox", "firefox"} <= ids
    assert "firefox" in integ.app_ids_for("firefox")
    assert integ.app_ids_for("/usr/share/applications/Foo.desktop") >= {"foo"}


# ------------------------------------------------------------------ CLIPBOARD (itens da revisão)
def test_paste_restore_clears_clipboard_when_original_was_not_text():
    sel = Sel(clipboard=None)
    ex, _, sched = make(selection=sel)
    trig(ex, {"type": "type_text", "text": "senha-colada"})
    sched.advance(600)
    assert sel.cleared == 1 and sel.clipboard is None and sel.writes == ["senha-colada"]


def test_ai_prompt_cancels_pending_restore_and_discards_saved_clipboard():
    sel = Sel(primary="trecho", clipboard="original")
    ex, _, sched = make(selection=sel)
    trig(ex, {"type": "type_text", "text": "colado"})            # restore agendado para +600 ms
    trig(ex, {"type": "ai_prompt", "service": "claude", "template": "Explique: {selection}"})
    sched.advance(5000)
    assert sel.clipboard == "Explique: trecho"                     # o prompt NÃO foi apagado pelo restore
    assert sel.writes == ["colado", "Explique: trecho"] and sel.cleared == 0
    assert ex._clip_saved is None and ex._clip_pending is False and ex._clip_timer is None
    # uma colagem nova depois começa do zero: salva o clipboard atual (o prompt)
    trig(ex, {"type": "type_text", "text": "outro"})
    sched.advance(600)
    assert sel.clipboard == "Explique: trecho"


def test_flush_clipboard_restores_pending_immediately():
    sel = Sel(clipboard="original")
    ex, _, sched = make(selection=sel)
    trig(ex, {"type": "type_text", "text": "colado"})
    assert sel.clipboard == "colado"
    ex.flush_clipboard()
    assert sel.clipboard == "original" and sched.pending == 0
    ex.flush_clipboard()                                           # sem pendência: nada a fazer
    assert sel.writes == ["colado", "original"]


def test_flush_clipboard_clears_when_there_was_no_text_original():
    sel = Sel(clipboard=None)
    ex, _, _ = make(selection=sel)
    trig(ex, {"type": "type_text", "text": "senha"})
    ex.flush_clipboard()
    assert sel.clipboard is None and sel.cleared == 1


def test_manager_close_flushes_pending_clipboard(tmp_path):
    sel, sched = Sel(clipboard="original"), ManualScheduler()
    ex = ActionExecutor(NullBackend(), scheduler=sched, selection=sel, media=Rec(), volume=Rec())
    mgr = mg.Manager(Config(tmp_path / "c.json"), ex, sched, FakeFocusWatcher(), notifier=RecordingNotifier())
    trig(ex, {"type": "type_text", "text": "colado"})
    mgr.close()                                                    # SIGTERM -> loop.quit() -> manager.close()
    assert sel.clipboard == "original"


def test_smart_action_waits_150ms_between_paste_and_next_clipboard_write():
    sel = Sel(clipboard="orig")
    ex, be, sched = make(selection=sel)
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [
        {"type": "type_text", "text": "um"}, {"type": "type_text", "text": "dois"},
        {"type": "volume", "op": "up"}]})
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert sel.writes == ["um"] and ex.volume.calls == []          # o 2º colar espera (Ctrl+V do 1º ainda em voo)
    sched.advance(149)
    assert sel.writes == ["um"]
    sched.advance(1)
    assert sel.writes == ["um", "dois"] and ex.volume.calls == [("up", 5)]
    sched.advance(600)
    assert sel.clipboard == "orig" and sel.writes[-1] == "orig"    # um único restore, do original
    assert ex.smart.running == set()


def test_paste_gap_does_not_delay_non_clipboard_steps_and_is_absorbed_by_delays():
    sel = Sel(clipboard="orig")
    ex, be, sched = make(selection=sel)
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [
        {"type": "type_text", "text": "um"}, {"type": "volume", "op": "mute"},
        {"type": "delay", "ms": 200}, {"type": "type_text", "text": "dois"}]})
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert ex.volume.calls == [("mute", 5)]                         # passo que não usa o clipboard não espera
    sched.advance(200)
    assert sel.writes[:2] == ["um", "dois"]                         # o delay de 200 ms já cobriu os 150 ms


def test_smart_action_paste_then_ai_prompt_also_waits():
    sel = Sel(primary="x", clipboard="orig")
    ex, _, sched = make(selection=sel)
    ex.smart_lookup = lambda i: validate_smart_action({"name": "m", "steps": [
        {"type": "type_text", "text": "um"},
        {"type": "ai_prompt", "service": "claude", "template": "T {selection}"}]})
    trig(ex, {"type": "smart_action", "id": "sa_1"})
    assert sel.writes == ["um"]
    sched.advance(150)
    assert sel.writes == ["um", "T x"]
    sched.advance(2000)
    assert sel.clipboard == "T x"                                   # restore do paste não apaga o prompt


# ------------------------------------------------------------------ Selection (ferramentas falsas)
def fake_clip_tools(tmp_path, *, targets="TARGETS\nUTF8_STRING\n", content="antigo", xclip_fails_targets=False,
                    names=("xclip", "xsel")):
    store = tmp_path / "clip.bin"
    store.write_bytes(content if isinstance(content, bytes) else content.encode())
    log = tmp_path / "calls.log"
    tfile = tmp_path / "targets.txt"
    tfile.write_text(targets)
    paths = {}
    for n in names:
        f = tmp_path / n
        if n == "xclip":
            body = (f'echo "xclip $*" >> "{log}"\n'
                    f'case "$*" in\n *"-t TARGETS"*) {"exit 1" if xclip_fails_targets else f"cat {tfile}"};;\n'
                    f' *"-i"*) cat > "{store}";;\n *"-o"*) cat "{store}";;\nesac\n')
        else:
            body = (f'echo "xsel $*" >> "{log}"\n'
                    f'case "$*" in *"-bc"*) : > "{store}";; *"-bi"*) cat > "{store}";; *"-bo"*) cat "{store}";; esac\n')
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(0o755)
        paths[n] = str(f)
    return store, paths, log


def test_read_clipboard_checks_targets_first_and_reads_text(tmp_path):
    store, paths, log = fake_clip_tools(tmp_path)
    sel = integ.Selection(which=paths.get, wayland=lambda: False)
    assert sel.read_clipboard() == "antigo"
    calls = log.read_text().splitlines()
    assert calls[0].endswith("-o -selection clipboard -t TARGETS") and calls[1].endswith("-t UTF8_STRING")
    assert not any(c.startswith("xsel") for c in calls)


def test_read_clipboard_requires_text_target_and_never_falls_back_to_xsel(tmp_path):
    store, paths, log = fake_clip_tools(tmp_path, targets="TARGETS\nimage/png\n")
    sel = integ.Selection(which=paths.get, wayland=lambda: False)
    assert sel.read_clipboard() is None
    assert "-t UTF8_STRING" not in log.read_text() and "xsel" not in log.read_text()
    store, paths, log = fake_clip_tools(tmp_path, xclip_fails_targets=True)   # "target TARGETS not available"
    assert integ.Selection(which=paths.get, wayland=lambda: False).read_clipboard() is None
    assert "xsel" not in log.read_text()


def test_read_clipboard_accepts_text_plain_targets(tmp_path):
    store, paths, log = fake_clip_tools(tmp_path, targets="TARGETS\ntext/plain;charset=utf-8\ntext/plain\n")
    assert integ.Selection(which=paths.get, wayland=lambda: False).read_clipboard() == "antigo"
    assert "-t text/plain;charset=utf-8" in log.read_text()


def test_read_clipboard_uses_xsel_only_when_there_is_no_xclip(tmp_path):
    store, paths, log = fake_clip_tools(tmp_path, names=("xsel",))
    assert integ.Selection(which=paths.get, wayland=lambda: False).read_clipboard() == "antigo"


def test_read_clipboard_is_not_cut_at_8kib_but_at_1mib(tmp_path):
    big = "ação " * 40000                      # ~240 KiB: bem acima dos 8 KiB da seleção PRIMARY
    store, paths, _ = fake_clip_tools(tmp_path, content=big)
    sel = integ.Selection(which=paths.get, wayland=lambda: False)
    assert sel.read_clipboard() == big and len(big.encode()) > 8 * 1024
    store, paths, _ = fake_clip_tools(tmp_path, content="x" * (integ.CLIPBOARD_LIMIT + 1))
    assert integ.Selection(which=paths.get, wayland=lambda: False).read_clipboard() is None   # grande demais
    store, paths, _ = fake_clip_tools(tmp_path, content="x" * integ.CLIPBOARD_LIMIT)
    assert len(integ.Selection(which=paths.get, wayland=lambda: False).read_clipboard()) == integ.CLIPBOARD_LIMIT
    # a PRIMARY continua cortada em 8 KiB
    store, paths, _ = fake_clip_tools(tmp_path, content="y" * 20000)
    assert len(integ.Selection(which=paths.get, wayland=lambda: False).read_primary()) == integ.SELECTION_LIMIT


def test_read_clipboard_non_utf8_empty_and_hanging_tool_return_none(tmp_path):
    store, paths, _ = fake_clip_tools(tmp_path, content=b"\xff\xfe\x00bad")
    assert integ.Selection(which=paths.get, wayland=lambda: False).read_clipboard() is None
    store, paths, _ = fake_clip_tools(tmp_path, content="")
    assert integ.Selection(which=paths.get, wayland=lambda: False).read_clipboard() is None
    hang = tmp_path / "hang"
    hang.write_text("#!/bin/sh\nsleep 5\n")
    hang.chmod(0o755)
    import time
    t0 = time.monotonic()
    assert integ.Selection(which=lambda n: str(hang) if n == "xclip" else None,
                           wayland=lambda: False).read_clipboard() is None
    assert time.monotonic() - t0 < 2


def test_clear_clipboard_prefers_xsel_then_xclip_empty(tmp_path):
    store, paths, log = fake_clip_tools(tmp_path, content="senha")
    assert integ.Selection(which=paths.get, wayland=lambda: False).clear_clipboard()
    assert store.read_bytes() == b"" and "xsel -bc" in log.read_text()
    (tmp_path / "x").mkdir()
    store, paths, log = fake_clip_tools(tmp_path / "x", content="senha", names=("xclip",))
    assert integ.Selection(which=paths.get, wayland=lambda: False).clear_clipboard()
    assert store.read_bytes() == b""
    assert integ.Selection(which=lambda n: None, wayland=lambda: False).clear_clipboard() is False


# ------------------------------------------------------------------ ambiente gráfico tardio
def test_session_env_parse_and_import():
    text = "PATH=/usr/bin\nDISPLAY=:1\nXAUTHORITY=$'/home/a b/.Xauth'\nWAYLAND_DISPLAY=\nOUTRA=1\n"
    assert session_env.parse_environment(text) == {"DISPLAY": ":1", "XAUTHORITY": "/home/a b/.Xauth"}
    env = {}

    class R:
        returncode, stdout = 0, text
    got = session_env.import_from_systemd(env, run=lambda *a, **k: R())
    assert sorted(got) == ["DISPLAY", "XAUTHORITY"] and env == {"DISPLAY": ":1", "XAUTHORITY": "/home/a b/.Xauth"}
    # já tem DISPLAY (ou Wayland): não consulta o systemd
    assert session_env.import_from_systemd({"DISPLAY": ":0"}, run=lambda *a, **k: 1 / 0) == []
    assert session_env.import_from_systemd({"WAYLAND_DISPLAY": "w"}, run=lambda *a, **k: 1 / 0) == []

    class Bad:
        returncode, stdout = 1, ""
    assert session_env.import_from_systemd({}, run=lambda *a, **k: Bad()) == []

    def boom(*a, **k):
        raise FileNotFoundError("sem systemctl")
    assert session_env.import_from_systemd({}, run=boom) == []

    class NoDisplay:
        returncode, stdout = 0, "PATH=/x\nXAUTHORITY=/a\n"
    e2 = {}
    assert session_env.import_from_systemd(e2, run=lambda *a, **k: NoDisplay()) == [] and e2 == {}


def test_manager_without_display_retries_and_comes_up_when_display_appears(tmp_path, monkeypatch):
    state = {"display": False}
    made = []

    class XWatcher(FakeFocusWatcher):
        pass

    def fake_make(scheduler):
        if not state["display"]:
            return NullFocusWatcher("sem DISPLAY", retry=True)
        w = XWatcher()
        made.append(w)
        return w

    monkeypatch.setattr(mg, "make_focus_watcher", fake_make)
    monkeypatch.setattr(mg, "display_kind", lambda: "x11" if state["display"] else "no-display")
    pulls = []
    monkeypatch.setattr(mg.session_env, "import_from_systemd", lambda *a, **k: pulls.append(1) or [])
    import openmacros.daemon.xtriggers as xt
    shortcuts = []
    monkeypatch.setattr(xt, "X11ShortcutBackend", lambda: shortcuts.append(FakeShortcuts()) or shortcuts[-1])
    monkeypatch.setattr(xt, "X11AppWatcher", lambda sched: type("W", (), {
        "start": lambda self, cb: None, "stop": lambda self: None, "running_apps": lambda self: []})())
    sched = ManualScheduler()
    mgr = mg.Manager(Config(tmp_path / "c.json"), ActionExecutor(NullBackend(), scheduler=sched), sched)
    mgr.signals = []
    mgr.listeners.append(lambda n, *a: mgr.signals.append((n, a)))
    sa = json.loads(mgr.save_smart_action(json.dumps(
        {"name": "A", "steps": [{"type": "volume", "op": "mute"}],
         "triggers": [{"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_P"]}]})))["id"]
    mgr.start_focus()
    assert isinstance(mgr.focus, NullFocusWatcher) and sched.pending == 1   # tentará de novo
    errs = json.loads(mgr.get_smart_actions())[sa]["trigger_errors"]
    assert errs and "DISPLAY" in errs[0]["message"]
    sched.advance(3000)                                                       # ainda sem tela: segue tentando
    assert isinstance(mgr.focus, NullFocusWatcher) and sched.pending == 1 and len(pulls) >= 2
    state["display"] = True                                                   # o login gráfico exportou DISPLAY
    sched.advance(3000)
    assert mgr.focus is made[-1] and sched.pending == 0
    assert json.loads(mgr.get_smart_actions())[sa]["trigger_errors"] == [] and shortcuts
    mgr.close()


def test_manager_wayland_gets_unavailable_shortcuts_and_does_not_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "make_focus_watcher", lambda s: NullFocusWatcher("Wayland"))
    monkeypatch.setattr(mg, "display_kind", lambda: "wayland")
    monkeypatch.setattr(mg.session_env, "import_from_systemd", lambda *a, **k: [])
    sched = ManualScheduler()
    mgr = mg.Manager(Config(tmp_path / "c.json"), ActionExecutor(NullBackend(), scheduler=sched), sched)
    sa = json.loads(mgr.save_smart_action(json.dumps(
        {"name": "A", "steps": [{"type": "volume", "op": "mute"}],
         "triggers": [{"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_P"]}]})))["id"]
    mgr.start_focus()
    assert sched.pending == 0
    assert "Wayland" in json.loads(mgr.get_smart_actions())[sa]["trigger_errors"][0]["message"]
    assert isinstance(mgr.triggers.shortcuts, UnavailableShortcuts)


def test_make_focus_watcher_marks_no_display_as_retryable(monkeypatch):
    from openmacros.daemon import focus as f
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("DISPLAY", raising=False)
    w = f.make_focus_watcher(ManualScheduler())
    assert isinstance(w, f.NullFocusWatcher) and w.retry is True
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert f.make_focus_watcher(ManualScheduler()).retry is False


def test_systemd_unit_has_default_target_and_session_autostart_restarts_service():
    here = os.path.dirname(os.path.abspath(__file__))
    unit = open(os.path.join(here, "..", "data/systemd/openmacrosd.service"), encoding="utf-8").read()
    wanted = [ln for ln in unit.splitlines() if ln.startswith("WantedBy=")]
    assert wanted == ["WantedBy=default.target"]
    assert not [ln for ln in unit.splitlines() if ln.startswith(("PartOf=", "After=", "Requires="))]
    ses = open(os.path.join(here, "..", "data/io.github.openmacros.Session.desktop"), encoding="utf-8").read()
    assert "import-environment DISPLAY XAUTHORITY" in ses and "restart openmacrosd.service" in ses
    assert "NoDisplay=true" in ses and stat.S_ISREG(os.stat(os.path.join(here, "..", "pyproject.toml")).st_mode)
