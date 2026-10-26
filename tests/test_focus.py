from openmacros.daemon import focus as f
from openmacros.daemon.timers import ManualScheduler


def test_app_id_rules():
    a = f.app_from_props(("Navigator", "firefox"), "Título", 12, "firefox-esr")
    assert a["app_id"] == "firefox" and a["exe"] == "firefox-esr" and a["pid"] == 12
    assert f.app_from_props(("xfce4-terminal", "Xfce4-terminal"))["app_id"] == "xfce4-terminal"
    assert f.app_from_props(None, "", 1, "Obsidian")["app_id"] == "obsidian"      # sem WM_CLASS -> exe
    assert f.app_from_props((), "", 0, "")["app_id"] == ""                       # nada -> ""


def test_exe_name_missing_process():
    assert f.exe_name(0) == "" and f.exe_name(999999999) == ""


def test_null_and_fake_watchers():
    got = []
    w = f.FakeFocusWatcher()
    w.start(got.append)
    w.set_active("firefox")
    w.set_active("")
    assert [a["app_id"] for a in got] == ["firefox", ""]
    f.NullFocusWatcher("teste").start(got.append)  # só loga


def test_make_watcher_wayland_and_no_display(monkeypatch):
    sched = ManualScheduler()
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("DISPLAY", ":0")
    assert isinstance(f.make_focus_watcher(sched), f.NullFocusWatcher)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("DISPLAY")
    assert isinstance(f.make_focus_watcher(sched), f.NullFocusWatcher)


def test_x11_debounce_and_dedupe(monkeypatch):
    sched = ManualScheduler()
    w = f.X11FocusWatcher(sched)
    seq = iter(["a", "a", "b", "b"])
    monkeypatch.setattr(w, "read_active", lambda: f.app_from_props((next(seq),), "", 0, ""))
    got = []
    w.callback = got.append
    for _ in range(3):  # rajada de PropertyNotify: um só check após 120 ms
        w._schedule()
    assert sched.pending == 1
    sched.advance(119)
    assert got == []
    sched.advance(1)
    assert [a["app_id"] for a in got] == ["a"]
    w._schedule(); sched.advance(120)   # a de novo: não emite
    assert len(got) == 1
    w._schedule(); sched.advance(120)   # b
    assert [a["app_id"] for a in got] == ["a", "b"]


def test_read_active_survives_vanished_window():
    from Xlib import error
    w = f.X11FocusWatcher(ManualScheduler())

    class Boom:
        def screen(self):
            raise error.ConnectionClosedError("janela sumiu")
    w.display = Boom()
    assert w.read_active()["app_id"] == ""
