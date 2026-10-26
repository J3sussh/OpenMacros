"""Aviso antes de importar/instalar conteúdo que executa programas, abre arquivos ou digita textos."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

MAX_SHOWN = 8


def risk_body(items: list[str]) -> str:
    shown = items[:MAX_SHOWN]
    lines = ["• " + t for t in shown]
    if len(items) > MAX_SHOWN:
        lines.append(f"… e mais {len(items) - MAX_SHOWN}")
    return "\n".join(lines)


def confirm_risks(parent: Gtk.Widget | None, items: list[str], what: str, accept_label: str,
                  on_accept: Callable[[], None]) -> Adw.AlertDialog | None:
    """Sem itens de risco: chama on_accept direto (devolve None). Com itens: mostra a lista, com
    **Cancelar** como resposta padrão (Enter/Esc cancelam)."""
    if not items:
        on_accept()
        return None
    dlg = Adw.AlertDialog.new(
        "Este conteúdo executa ações no seu computador",
        f"{what} contém ações que rodam programas, abrem arquivos ou digitam textos. "
        "Só continue se você confia na origem.")
    dlg.set_body_use_markup(False)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    lab = Gtk.Label(label=risk_body(items), xalign=0, wrap=True, selectable=False, max_width_chars=60)
    lab.add_css_class("monospace")
    lab.add_css_class("caption")
    lab.update_property([Gtk.AccessibleProperty.LABEL], ["Ações de risco: " + "; ".join(items[:MAX_SHOWN])])
    sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True, max_content_height=220,
                            child=lab)
    box.append(sw)
    dlg.set_extra_child(box)
    dlg.add_response("cancel", "Cancelar")
    dlg.add_response("accept", accept_label)
    dlg.set_response_appearance("accept", Adw.ResponseAppearance.DESTRUCTIVE)
    dlg.set_default_response("cancel")
    dlg.set_close_response("cancel")
    dlg.connect("response", lambda _d, r: r == "accept" and on_accept())
    dlg.present(parent)
    return dlg
