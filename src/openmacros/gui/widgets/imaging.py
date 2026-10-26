"""Carregamento de imagens para Gtk.Picture.

WebP é carregado como Gdk.Texture explicitamente (Gtk.Picture.set_filename não renderizou WebP
de forma confiável); SVG continua vetorial via set_filename."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

_cache: dict[tuple[str, float], Gdk.Texture] = {}


def _texture(path: str) -> Gdk.Texture | None:
    try:
        key = (path, os.stat(path).st_mtime)
    except OSError:
        return None
    tex = _cache.get(key)
    if tex is None:
        try:
            tex = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            return None
        if len(_cache) > 24:
            _cache.clear()
        _cache[key] = tex
    return tex


def set_image(picture, path: str | os.PathLike) -> None:
    """Aceita Gtk.Picture ou SizedPicture."""
    if isinstance(picture, SizedPicture):
        picture = picture.picture
    path = str(path)
    if path.lower().endswith(".svg"):
        picture.set_filename(path)
    else:
        picture.set_paintable(_texture(path))


def plain_picture(path: str | os.PathLike) -> Gtk.Picture:
    pic = Gtk.Picture()
    pic.set_content_fit(Gtk.ContentFit.CONTAIN)
    pic.set_can_shrink(True)
    pic.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
    set_image(pic, path)
    return pic


class SizedPicture(Gtk.Widget):
    """Imagem com tamanho mínimo/natural fixos (o tamanho intrínseco do WebP é enorme)."""

    __gtype_name__ = "OpenMacrosSizedPicture"

    def __init__(self, path, min_size: tuple[int, int], nat_size: tuple[int, int]):
        super().__init__()
        self._min, self._nat = min_size, nat_size
        self.picture = plain_picture(path)
        self.picture.set_parent(self)

    def do_measure(self, orientation, for_size):
        i = 0 if orientation == Gtk.Orientation.HORIZONTAL else 1
        return self._min[i], max(self._min[i], self._nat[i]), -1, -1

    def do_size_allocate(self, width, height, baseline):
        self.picture.allocate(width, height, baseline, None)

    def do_dispose(self):
        if self.picture is not None:
            self.picture.unparent()
            self.picture = None
        Gtk.Widget.do_dispose(self)


def new_picture(path: str | os.PathLike, min_size: tuple[int, int] = (64, 64),
                nat_size: tuple[int, int] | None = None) -> SizedPicture:
    return SizedPicture(path, min_size, nat_size or min_size)
