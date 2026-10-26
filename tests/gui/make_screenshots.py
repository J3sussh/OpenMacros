"""Gera as capturas oficiais do README em docs/screenshots/ (tema Adwaita claro, 1200x800, dados fictícios).

Uso:  tests/gui/make_screenshots.py [DIR_SAIDA]      (padrão: docs/screenshots)
Tudo roda isolado: Xvfb, D-Bus de sessão próprio, serviço fake (OPENMACROS_FAKE=1) e XDG_* temporários.
Nunca lê nem grava ~/.config, ~/.local nem fotos importadas da Logitech (só a arte SVG própria).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def outer() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "docs" / "screenshots").resolve()
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="om-shots-"))
    env = {k: v for k, v in os.environ.items() if k not in ("DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY")}
    env.update(
        XDG_DATA_HOME=str(tmp / "data"), XDG_CONFIG_HOME=str(tmp / "config"), XDG_CACHE_HOME=str(tmp / "cache"),
        XDG_RUNTIME_DIR=str(tmp / "run"), HOME=str(tmp / "home"),
        GDK_BACKEND="x11", OPENMACROS_FAKE="1", LANG="pt_BR.UTF-8", LC_ALL="C.UTF-8",
        GSETTINGS_BACKEND="memory", NO_AT_BRIDGE="1", GTK_USE_PORTAL="0", ADW_DISABLE_PORTAL="1", GDK_DEBUG="no-portals",
        PYTHONPATH=f"{ROOT / 'src'}:{HERE}", OM_SHOTS_OUT=str(out), OM_SHOTS_INNER="1")
    for d in ("data", "config", "cache", "home"):
        (tmp / d).mkdir()
    (tmp / "run").mkdir(mode=0o700)
    for v in ("3.0", "4.0"):  # libadwaita puro (sem o tema do sistema, ex.: Kali)
        (tmp / "config" / f"gtk-{v}").mkdir(parents=True)
        (tmp / "config" / f"gtk-{v}" / "settings.ini").write_text(
            "[Settings]\ngtk-icon-theme-name=Adwaita\ngtk-application-prefer-dark-theme=false\n"
            + ("gtk-theme-name=Adwaita\n" if v == "3.0" else ""))
    xvfb = ["xvfb-run", "-a", "-s", "-screen 0 1200x800x24"]
    rc = 0
    try:
        for mode in ("gtk4", "tray"):
            env["OM_SHOTS_MODE"] = mode
            rc |= subprocess.run(xvfb + ["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve())],
                                 env=env, timeout=240).returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rc


def shot(name: str, crop: str | None = None) -> bool:
    cmd = ["import", "-window", "root"]
    if crop:
        cmd += ["-crop", crop, "+repage"]
    subprocess.run(cmd + [f"{os.environ['OM_SHOTS_OUT']}/{name}.png"], check=False)
    return False


def gtk4() -> None:
    import json
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk

    from openmacros.gui import logic
    from openmacros.gui.app import OpenMacrosApp

    daemon = subprocess.Popen([sys.executable, "-m", "openmacros.daemon.main"])
    bus = None
    import time
    for _ in range(50):  # espera o serviço aparecer no barramento
        time.sleep(0.2)
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            r = bus.call_sync("io.github.openmacros", "/io/github/openmacros", "io.github.openmacros.Manager1",
                              "GetDevices", None, None, Gio.DBusCallFlags.NONE, 1000, None)
            devs = json.loads(r.unpack()[0])
            if devs:
                break
        except GLib.Error:
            continue
    m720 = next(d for d in devs if "M720" in d["name"])["id"]

    def call(method, sig, *args):
        bus.call_sync("io.github.openmacros", "/io/github/openmacros", "io.github.openmacros.Manager1", method,
                      GLib.Variant(sig, args), None, Gio.DBusCallFlags.NONE, 3000, None)

    def keys(*k):
        return json.dumps({"type": "keys", "keys": list(k)})

    # dados de exemplo: globais + perfil do Firefox (o restante fica herdado e esmaecido)
    call("SetAssignment", "(sqs)", m720, 83, keys("KEY_LEFTCTRL", "KEY_C"))
    call("SetAssignment", "(sqs)", m720, 86, keys("KEY_LEFTCTRL", "KEY_V"))
    call("SetAssignment", "(sqs)", m720, 91, keys("KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_TAB"))
    call("SetAssignment", "(sqs)", m720, 93, keys("KEY_LEFTCTRL", "KEY_TAB"))
    call("SetProfileAssignment", "(ssqs)", m720, "firefox", 91, keys("KEY_LEFTCTRL", "KEY_PAGEUP"))
    call("SetProfileAssignment", "(ssqs)", m720, "firefox", 93, keys("KEY_LEFTCTRL", "KEY_PAGEDOWN"))

    gest = {"type": "gestures", "click": {"type": "default"}, "up": {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_T"]},
            "down": {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_W"]},
            "left": {"type": "keys", "keys": ["KEY_LEFTALT", "KEY_LEFT"]},
            "right": {"type": "keys", "keys": ["KEY_LEFTALT", "KEY_RIGHT"]}, "threshold": 50}
    call("SetAssignment", "(sqs)", m720, 208, json.dumps(gest))
    for tid in ("work", "meeting", "my_sites", "search_web", "ask_ai", "brb"):
        sa = logic.smart_from_template(tid)
        call("SaveSmartAction", "(s)", json.dumps(sa))

    Gtk.init_check()
    nologo = Gtk.CssProvider()  # o libadwaita do Kali desenha um logo na barra de título; remove
    nologo.load_from_string("headerbar, headerbar *, .titlebar, window, window.background { background-image: none; }\nwindowcontrols { opacity: 0; }")
    from gi.repository import Gdk
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), nologo, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    Gtk.Settings.get_default().props.gtk_decoration_layout = ":"  # sem botões de janela (estilo do Kali)
    app = OpenMacrosApp()

    def win():
        return app.props.active_window

    def dev_page():
        return win().device_page

    def buttons():
        return dev_page().stack.get_child_by_name("buttons")

    def open_dev():
        dev = next(i for i, d in win().devices.items() if "M720" in d["name"])
        win().devices_page.emit("device-activated", dev)
        return False

    def prep():
        Gtk.Settings.get_default().props.gtk_icon_theme_name = "Adwaita"
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        win().set_default_size(1200, 800)
        return False

    def debug_app(app_id):
        call("DebugSetActiveApp", "(s)", app_id)
        return False

    def select_app(app_id):
        if app_id and app_id not in logic.profile_app_ids(dev_page().device):
            dev_page().pending.append(app_id)
        dev_page().select_app(app_id)
        return False

    def hot(cid):
        buttons()._on_marker(None, cid)
        return False

    def page(name):
        dev_page().stack.set_visible_child_name(name)
        return False

    def home():
        while win().nav.get_visible_page() is not win().devices_page:
            win().nav.pop()
        return False

    def smart_list():
        win().devices_page.emit("smart-actions")
        return False

    def smart_editor(template):
        d = logic.smart_from_template(template)
        d["name"] = "Abrir meus sites"
        d["description"] = "Abre meus sites quando o Firefox abre."
        d["triggers"] = [{"type": "app", "event": "open", "app_id": "firefox"},
                         {"type": "shortcut", "keys": ["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_H"]},
                         {"type": "device", "event": "connect", "device_id": "*"}]
        win().ctx.open_smart_editor(d, None)
        return False

    def pop():
        win().nav.pop()
        return False

    def prefs():
        win().show_preferences()
        return False

    def about():
        app.activate_action("about", None)
        return False

    def close_dialog():
        d = win().get_visible_dialog()
        if d:
            d.force_close()
        return False

    def quit_():
        app.quit()
        return False

    S = shot
    steps = [
        prep, lambda: None, lambda: None, lambda: S("home"),
        open_dev, lambda: page("buttons"), lambda: S("buttons"),
        lambda: debug_app("firefox"), lambda: select_app("firefox"), lambda: hot(86), lambda: S("app-profiles"),
        lambda: select_app(""), lambda: debug_app(""), lambda: hot(83), lambda: S("action-panel"),
        lambda: hot(208), lambda: S("gestures"),
        lambda: page("pointer"), lambda: S("pointer"),
        home, smart_list, lambda: S("smart-actions"),
        lambda: smart_editor("my_sites"), lambda: S("smart-editor"),
        pop, pop, prefs, lambda: S("preferences"), close_dialog,
        about, lambda: S("about"), close_dialog,
        quit_,
    ]
    for i, fn in enumerate(steps):
        GLib.timeout_add(3500 + i * 1500, fn)
    app.run([])
    daemon.terminate()


def tray() -> None:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gio, GLib, Gtk

    from openmacros.tray import main as tm

    daemon = subprocess.Popen([sys.executable, "-m", "openmacros.daemon.main"])
    app = Gio.Application(application_id="io.github.openmacros.TrayShot")
    st = {}
    Gtk.Settings.get_default().props.gtk_icon_theme_name = "Adwaita"

    def activate(_a):
        t = tm.Tray(app)
        t.start()
        app.hold()
        win = Gtk.Window(title="host", default_width=420, default_height=40, decorated=False)
        win.move(60, 20)
        win.show_all()
        st.update(t=t, win=win)

        def pop():
            menu = t._menu(tm.model.menu_spec(t.client.devices, tm.app_name))
            menu.popup_at_widget(win, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)
            st["menu"] = menu
            return False

        def snap():
            w = st["menu"].get_window()
            if w is not None:
                _, x, y = w.get_origin()
                shot("tray", f"{w.get_width() + 24}x{w.get_height() + 24}+{max(x - 12, 0)}+{max(y - 12, 0)}")
            else:
                shot("tray")
            return False
        GLib.timeout_add(4500, pop)
        GLib.timeout_add(6000, snap)
        GLib.timeout_add(6800, lambda: (app.quit(), False)[1])

    app.connect("activate", activate)
    import time
    time.sleep(2.5)
    app.run([])
    daemon.terminate()


if __name__ == "__main__":
    if os.environ.get("OM_SHOTS_INNER"):
        (gtk4 if os.environ["OM_SHOTS_MODE"] == "gtk4" else tray)()
    else:
        sys.exit(outer())
