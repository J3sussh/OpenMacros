"""Foto/arte do dispositivo com hotspots: círculo + linha fina + rótulo (nome do botão e ação)."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from .imaging import plain_picture  # noqa: E402

DOT = 20  # diâmetro do hotspot (px)
LINE = 26  # comprimento da linha até o rótulo (px)


class Hotspot(Gtk.Box):
    """Hotspot clicável: [círculo]--linha--[rótulo]; a posição do rótulo vem de marker.side."""

    def __init__(self, marker: logic.Marker, name: str, on_click):
        vertical = marker.side in ("up", "down")
        super().__init__(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL)
        self.marker = marker
        self.control_name = name
        self.add_css_class("hotspot-box")
        self.dot = Gtk.Button()
        self.dot.add_css_class("hotspot")
        self.dot.set_size_request(DOT, DOT)
        self.dot.set_halign(Gtk.Align.CENTER)
        self.dot.set_valign(Gtk.Align.CENTER)
        self.dot.set_tooltip_text(name)
        self.line = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL)
        self.line.add_css_class("hotspot-line")
        self.line.set_size_request(1 if vertical else LINE, LINE if vertical else 1)
        self.line.set_halign(Gtk.Align.CENTER)
        self.line.set_valign(Gtk.Align.CENTER)

        self.name_label = Gtk.Label(label=name, xalign=0)
        self.name_label.add_css_class("hotspot-name")
        self.action_label = Gtk.Label(label="", xalign=0)
        self.action_label.add_css_class("hotspot-action")
        lbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.inherit_label = Gtk.Label(label="(Todos os apps)", xalign=0)
        self.inherit_label.add_css_class("hotspot-inherit")
        self.inherit_label.set_visible(False)
        lbox.append(self.name_label)
        lbox.append(self.action_label)
        lbox.append(self.inherit_label)
        self.label_btn = Gtk.Button(child=lbox)
        self.label_btn.add_css_class("hotspot-label")
        self.label_btn.set_valign(Gtk.Align.CENTER)
        self.label_btn.set_halign(Gtk.Align.CENTER if vertical else Gtk.Align.FILL)

        if marker.side in ("right", "down"):
            seq = (self.dot, self.line, self.label_btn)
        else:
            seq = (self.label_btn, self.line, self.dot)
        for w in seq:
            self.append(w)
        self.dot.connect("clicked", lambda *_: on_click(marker.cid))
        self.label_btn.connect("clicked", lambda *_: on_click(marker.cid))
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self.add_css_class("hover"))
        motion.connect("leave", lambda *_: self.remove_css_class("hover"))
        self.add_controller(motion)

    def set_action_text(self, text: str, inherited: bool = False) -> None:
        self.action_label.set_label(text)
        self.inherit_label.set_visible(inherited)
        (self.add_css_class if inherited else self.remove_css_class)("inherited")
        extra = " (herdado de Todos os aplicativos)" if inherited else ""
        for w in (self.dot, self.label_btn):
            w.update_property([Gtk.AccessibleProperty.LABEL], [f"{self.control_name}: {text}{extra}"])

    def set_selected(self, selected: bool) -> None:
        (self.add_css_class if selected else self.remove_css_class)("selected")


class DeviceArt(Gtk.Widget):
    """Desenha a imagem (Gtk.Picture) e posiciona os hotspots por coordenadas relativas 0..1."""

    __gtype_name__ = "OpenMacrosDeviceArt"
    __gsignals__ = {"marker-clicked": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self, image_path: str, aspect: float, with_labels_margin: bool = True):
        super().__init__()
        self._aspect = aspect
        self._margin = with_labels_margin
        self._markers: dict[int, Hotspot] = {}
        self._picture = plain_picture(image_path)
        self._picture.set_parent(self)
        self.set_hexpand(True)
        self.set_vexpand(True)

    def add_marker(self, marker: logic.Marker, control_name: str) -> None:
        h = Hotspot(marker, control_name, lambda cid: self.emit("marker-clicked", cid))
        h.set_parent(self)
        self._markers[marker.cid] = h

    def set_action_text(self, cid: int, text: str, inherited: bool = False) -> None:
        if cid in self._markers:
            self._markers[cid].set_action_text(text, inherited)

    def set_selected(self, cid: int | None) -> None:
        for c, h in self._markers.items():
            h.set_selected(c == cid)

    def _margin_px(self, width: float) -> float:
        return min(200.0, width * 0.26) if self._margin else 0.0

    def _art_rect(self, width: int, height: int) -> tuple[float, float, float, float]:
        m = self._margin_px(width)
        aw, ah = max(1.0, width - 2 * m), max(1.0, float(height) - 2 * 28)
        if aw / ah > self._aspect:
            aw = ah * self._aspect
        else:
            ah = aw / self._aspect
        return (width - aw) / 2, (height - ah) / 2, aw, ah

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 320, 560, -1, -1
        return 380, 620, -1, -1

    def do_size_allocate(self, width, height, baseline):
        x, y, w, h = self._art_rect(width, height)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), int(w), int(h)
        self._picture.size_allocate(rect, -1)
        half = DOT / 2
        for m in self._markers.values():
            _, nat_w, _, _ = m.measure(Gtk.Orientation.HORIZONTAL, -1)
            _, nat_h, _, _ = m.measure(Gtk.Orientation.VERTICAL, nat_w)
            px, py = x + m.marker.x * w, y + m.marker.y * h
            side = m.marker.side
            if side == "right":
                left, top = px - half, py - nat_h / 2
            elif side == "left":
                left, top = px + half - nat_w, py - nat_h / 2
            elif side == "up":
                left, top = px - nat_w / 2, py + half - nat_h
            else:
                left, top = px - nat_w / 2, py - half
            r = Gdk.Rectangle()
            r.x, r.y, r.width, r.height = int(left), int(top), int(nat_w), int(nat_h)
            m.size_allocate(r, -1)

    def do_dispose(self):
        for m in list(self._markers.values()):
            m.unparent()
        self._markers.clear()
        if self._picture is not None:
            self._picture.unparent()
            self._picture = None
        Gtk.Widget.do_dispose(self)
