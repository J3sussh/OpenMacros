"""Leitura segura de arquivos escolhidos pelo usuário (backup, Smart Actions importadas)."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

MAX_IMPORT_BYTES = 512 * 1024
TOO_BIG = "Arquivo grande demais para ser do OpenMacros+ (máx. 512 KiB)"


def decode_text(raw: bytes) -> str:
    """UTF-8 com ou sem BOM (UnicodeDecodeError se não for texto UTF-8)."""
    return bytes(raw).decode("utf-8-sig")


def read_text_limited(f: Gio.File, done: Callable[[str | None, str | None], None],
                      limit: int = MAX_IMPORT_BYTES) -> None:
    """Confere o tamanho com query_info ANTES de carregar; done(texto, None) ou done(None, mensagem)."""
    def loaded(src, res) -> None:
        try:
            data, _ = src.load_bytes_finish(res)
            raw = data.get_data()
        except GLib.Error as e:
            done(None, f"Não foi possível ler o arquivo: {e.message}")
            return
        if len(raw) > limit:
            done(None, TOO_BIG)
            return
        try:
            done(decode_text(raw), None)
        except UnicodeDecodeError:
            done(None, "O arquivo não é texto UTF-8")

    def queried(src, res) -> None:
        try:
            info = src.query_info_finish(res)
        except GLib.Error as e:
            done(None, f"Não foi possível ler o arquivo: {e.message}")
            return
        if info.get_file_type() != Gio.FileType.REGULAR:
            done(None, "Escolha um arquivo comum, não uma pasta ou dispositivo")
            return
        if info.get_size() > limit:
            done(None, TOO_BIG)
            return
        src.load_bytes_async(None, loaded)

    f.query_info_async("standard::size,standard::type", Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
                       None, queried)
