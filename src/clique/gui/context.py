"""Contexto compartilhado entre páginas: cliente D-Bus, toasts e estado global (apps, Smart Actions)."""

from __future__ import annotations

from typing import Callable

from .apps import AppIndex
from .dbus_client import CliqueClient


class PageContext:
    def __init__(self, client: CliqueClient, toast: Callable[[str], None]):
        self.client = client
        self.toast = toast
        self.apps = AppIndex()
        self.smart_actions: dict[str, dict] = {}
        self.active_app: dict = {}
        # preenchido pela janela: abre o editor de Smart Action (dict opcional = rascunho, id opcional)
        self.open_smart_editor: Callable[[dict | None, str | None], None] = lambda draft, sid: None

    def reporter(self, on_ok: Callable[[], None] | None = None) -> Callable:
        """Callback para chamadas D-Bus: mostra toast em falha."""
        def cb(value, error):
            if error:
                self.toast(error)
            elif value is False:
                self.toast("O serviço recusou a operação")
            elif on_ok:
                on_ok()
        return cb

    def test_action(self, action: dict) -> None:
        """Botão 'Testar': executa a ação agora (RunAction)."""
        self.client.run_action(action, self.reporter(lambda: self.toast("Ação executada")))
