"""Toasts sem markup: textos dinâmicos (erros, nomes de Smart Actions, avisos do serviço) nunca são interpretados."""

from __future__ import annotations

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402


def new_toast(text: str, timeout: int = 4) -> Adw.Toast:
    toast = Adw.Toast(title=str(text), timeout=timeout)
    if hasattr(toast, "set_use_markup"):  # libadwaita >= 1.4
        toast.set_use_markup(False)
    return toast
