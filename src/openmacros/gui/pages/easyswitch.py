"""Aba EASY-SWITCH: foto à esquerda e canais à direita."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import logic  # noqa: E402
from ..widgets.imaging import new_picture  # noqa: E402


class _Channel(Gtk.Box):
    def __init__(self, index: int, badge_path: str | None, on_switch):
        super().__init__(spacing=14)
        self.add_css_class("openmacros-card")
        self.add_css_class("channel")
        self.index = index
        if badge_path:
            badge = new_picture(badge_path, (44, 48))
            self.append(badge)
        else:
            num = Gtk.Label(label=str(index + 1))
            num.add_css_class("channel-number")
            num.set_size_request(40, 40)
            self.append(num)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0, ellipsize=3)
        self.title.add_css_class("card-title")
        self.sub = Gtk.Label(xalign=0, ellipsize=3)
        self.sub.add_css_class("dim-label")
        texts.append(self.title)
        texts.append(self.sub)
        self.append(texts)
        self.current = Gtk.Label(label="Atual", valign=Gtk.Align.CENTER)
        self.current.add_css_class("chip")
        self.button = Gtk.Button(label="Trocar", valign=Gtk.Align.CENTER)
        self.button.add_css_class("pill-small")
        self.button.connect("clicked", lambda *_: on_switch(index))
        self.append(self.current)
        self.append(self.button)

    def set_state(self, name: str | None, is_current: bool) -> None:
        self.title.set_label(name or f"Computador {self.index + 1}")
        self.sub.set_label(f"Canal {self.index + 1}")
        self.current.set_visible(is_current)
        self.button.set_visible(not is_current)
        (self.add_css_class if is_current else self.remove_css_class)("current")


class EasySwitchPage(Gtk.ScrolledWindow):
    def __init__(self, device: dict, ctx):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.ctx = ctx
        self.dev_id = device["id"]
        outer = Gtk.Box(spacing=40, margin_top=24, margin_bottom=24, margin_start=24, margin_end=24,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        pic = new_picture(logic.art_path(device), (200, 300), (340, 520))
        outer.append(pic)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER)
        right.set_size_request(380, -1)
        title = Gtk.Label(label="Easy-Switch", xalign=0)
        title.add_css_class("page-title")
        desc = Gtk.Label(label="Escolha o computador em que este dispositivo está conectado. "
                               "Os canais são os mesmos das teclas Easy-Switch.", xalign=0, wrap=True)
        desc.add_css_class("dim-label")
        right.append(title)
        right.append(desc)
        badges = logic.easy_switch_images(device, dark=Adw.StyleManager.get_default().get_dark())
        self.channels: list[_Channel] = []
        for i in range(logic.host_count(device)):
            ch = _Channel(i, str(badges[i + 1]) if (i + 1) in badges else None, self._switch)
            right.append(ch)
            self.channels.append(ch)
        outer.append(right)
        self.set_child(Adw.Clamp(maximum_size=980, child=outer))
        self.update(device)

    def _switch(self, host: int) -> None:
        self.ctx.client.change_host(self.dev_id, host, self.ctx.reporter(
            lambda: self.ctx.toast(f"Trocando para o computador {host + 1}…")))

    def update(self, device: dict) -> None:
        hosts = device.get("hosts") or {}
        names = hosts.get("names") or []
        for i, ch in enumerate(self.channels):
            ch.set_state(names[i] if i < len(names) and names[i] else None, i == hosts.get("current"))
