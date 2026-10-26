"""Contexto compartilhado entre páginas: cliente D-Bus, toasts e estado global (apps, Smart Actions)."""

from __future__ import annotations

from typing import Callable

from .apps import AppIndex
from .dbus_client import OpenMacrosClient


class PageContext:
    def __init__(self, client: OpenMacrosClient, toast: Callable[[str], None]):
        self.client = client
        self.toast = toast
        self.apps = AppIndex()
        self.smart_actions: dict[str, dict] = {}
        self.devices: dict[str, dict] = {}  # preenchido pela janela (para gatilhos "Botão do dispositivo")
        # recursos de Smart Actions v2 que o serviço em execução não conhece (UnknownMethod) ficam escondidos
        self.sa_unsupported: set[str] = set()
        self.active_app: dict = {}
        # preferências globais (V2/B6); prefs_supported=False se o serviço não tem GetPreferences
        self.preferences: dict = {}
        self.prefs_supported = False
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

    def sa_supported(self, feature: str) -> bool:
        return feature not in self.sa_unsupported

    def sa_failed(self, feature: str, error: str | None) -> bool:
        """True (e marca o recurso como ausente) se o erro for UnknownMethod."""
        from .dbus_client import is_unsupported
        if is_unsupported(error):
            self.sa_unsupported.add(feature)
            return True
        return False
