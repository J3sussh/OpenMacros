"""Tela inicial: dispositivos como imagens grandes lado a lado (carrossel horizontal)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GObject, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..widgets.imaging import new_picture, set_image  # noqa: E402


class DeviceTile(Gtk.Button):
    def __init__(self, device: dict):
        super().__init__()
        self.device_id = device["id"]
        self.add_css_class("flat")
        self.add_css_class("device-tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
        self.picture = new_picture(logic.art_path(device), (200, 250), (280, 360))
        self.name = Gtk.Label(justify=Gtk.Justification.CENTER, wrap=True, max_width_chars=26)
        self.name.add_css_class("tile-name")
        self.battery_icon = Gtk.Image()
        self.battery_label = Gtk.Label()
        self.battery_label.add_css_class("caption")
        bat = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        bat.add_css_class("tile-battery")
        bat.append(self.battery_icon)
        bat.append(self.battery_label)
        self.status = Gtk.Label()
        self.status.add_css_class("caption")
        self.status.add_css_class("dim-label")
        for w in (self.picture, self.name, bat, self.status):
            box.append(w)
        self.set_child(box)
        self.update(device)

    def update(self, device: dict) -> None:
        online = bool(device.get("online", True))
        set_image(self.picture, logic.art_path(device))
        self.name.set_label(device.get("name", "Dispositivo").upper())
        bat = device.get("battery")
        self.battery_icon.set_from_icon_name(logic.battery_icon(bat))
        self.battery_label.set_label(logic.battery_text(bat))
        conn = logic.connection_label(device.get("connection"))
        self.status.set_label(conn if online else f"{conn} · offline")
        (self.remove_css_class if online else self.add_css_class)("offline")
        self.update_property([Gtk.AccessibleProperty.LABEL], [
            f"{device.get('name', '')}, {logic.battery_text(bat)}, {conn}" + ("" if online else ", offline")])


class DevicesPage(Adw.NavigationPage):
    __gsignals__ = {
        "device-activated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "rescan": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "add-device": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "smart-actions": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(title="Dispositivos", tag="devices")
        self._tiles: dict[str, DeviceTile] = {}
        self.add_css_class("home-page")
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("flat")
        title = Gtk.Label(label="CLIQUE")
        title.add_css_class("app-title")
        header.set_title_widget(title)
        menu = Gio.Menu()
        menu.append("Importar imagens do Logi Options+…", "win.import-art")
        menu.append("Procurar dispositivos", "win.rescan")
        menu.append("Sobre o Clique", "app.about")
        mb = Gtk.MenuButton(icon_name="emblem-system-symbolic", menu_model=menu, tooltip_text="Menu")
        mb.update_property([Gtk.AccessibleProperty.LABEL], ["Menu principal"])
        header.pack_end(mb)
        sa = Gtk.Button(icon_name="system-run-symbolic", tooltip_text="Smart Actions")
        sa.update_property([Gtk.AccessibleProperty.LABEL], ["Smart Actions"])
        sa.connect("clicked", lambda *_: self.emit("smart-actions"))
        header.pack_start(sa)
        view.add_top_bar(header)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        loading = Adw.StatusPage(title="Procurando dispositivos…")
        loading.set_child(Adw.Spinner())
        empty = Adw.StatusPage(
            icon_name="input-mouse-symbolic", title="Nenhum dispositivo encontrado",
            description="Conecte um mouse ou teclado Logitech (receptor, Bluetooth ou cabo) e procure novamente.")
        self.tiles = Gtk.Box(spacing=48, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                             margin_start=32, margin_end=32, margin_top=16, margin_bottom=16)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.tiles)
        self.stack.add_named(loading, "loading")
        self.stack.add_named(empty, "empty")
        self.stack.add_named(scroller, "grid")

        add = Gtk.Button(label="ADICIONAR DISPOSITIVO", halign=Gtk.Align.CENTER, margin_bottom=28, margin_top=6)
        add.add_css_class("outline-pill")
        add.connect("clicked", lambda *_: self.emit("add-device"))
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.stack.set_vexpand(True)
        body.append(self.stack)
        body.append(add)
        view.set_content(body)
        self.set_child(view)

    def set_loading(self) -> None:
        self.stack.set_visible_child_name("loading")

    def set_devices(self, devices: list[dict]) -> None:
        ids = [d["id"] for d in devices]
        for dev_id in list(self._tiles):
            if dev_id not in ids:
                self.tiles.remove(self._tiles.pop(dev_id))
        for d in devices:
            tile = self._tiles.get(d["id"])
            if tile is None:
                tile = DeviceTile(d)
                tile.connect("clicked", lambda t: self.emit("device-activated", t.device_id))
                self._tiles[d["id"]] = tile
                self.tiles.append(tile)
            else:
                tile.update(d)
        self.stack.set_visible_child_name("grid" if devices else "empty")

    def update_device(self, device: dict) -> None:
        tile = self._tiles.get(device["id"])
        if tile:
            tile.update(device)
