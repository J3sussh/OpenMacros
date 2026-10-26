"""Rótulos legíveis (pt-BR) de ações, para OSD e para o sinal ActionTriggered. Puro."""

from __future__ import annotations

import os

ARROWS = {"up": "↑", "down": "↓", "left": "←", "right": "→", "click": "●"}
_MODS = {"KEY_LEFTCTRL": "Ctrl", "KEY_RIGHTCTRL": "Ctrl", "KEY_LEFTSHIFT": "Shift", "KEY_RIGHTSHIFT": "Shift",
         "KEY_LEFTALT": "Alt", "KEY_RIGHTALT": "AltGr", "KEY_LEFTMETA": "Super", "KEY_RIGHTMETA": "Super"}
_KEYNAMES = {"LEFT": "←", "RIGHT": "→", "UP": "↑", "DOWN": "↓", "PAGEUP": "PgUp", "PAGEDOWN": "PgDn",
             "MINUS": "-", "EQUAL": "=", "GRAVE": "`", "SPACE": "Espaço", "ENTER": "Enter", "ESC": "Esc",
             "TAB": "Tab", "BACKSPACE": "Backspace", "DELETE": "Del", "INSERT": "Ins"}
_PRESETS = {
    "Ctrl+C": "Copiar", "Ctrl+V": "Colar", "Ctrl+X": "Recortar", "Ctrl+Z": "Desfazer",
    "Ctrl+Y": "Refazer", "Ctrl+Shift+Z": "Refazer", "Ctrl+T": "Nova aba", "Ctrl+W": "Fechar aba",
    "Ctrl+Shift+T": "Reabrir aba", "Alt+←": "Voltar", "Alt+→": "Avançar",
    "Ctrl+PgUp": "Aba anterior", "Ctrl+PgDn": "Próxima aba", "Ctrl+Shift+P": "Paleta de comandos",
}
_MEDIA = {"play_pause": "Reproduzir/Pausar", "next": "Próxima faixa", "previous": "Faixa anterior", "stop": "Parar"}
_VOLUME = {"up": "Volume +", "down": "Volume −", "mute": "Mudo"}
_WINDOW = {"close": "Fechar janela", "minimize": "Minimizar janela", "maximize": "Maximizar janela",
           "fullscreen": "Tela cheia", "next": "Próxima janela", "previous": "Janela anterior"}
_SERVICES = {"claude": "Claude", "chatgpt": "ChatGPT", "perplexity": "Perplexity", "gemini": "Gemini"}
_BUTTONS = {"BTN_LEFT": "Botão esquerdo", "BTN_RIGHT": "Botão direito", "BTN_MIDDLE": "Botão do meio",
            "BTN_SIDE": "Botão lateral", "BTN_EXTRA": "Botão extra"}


_APP_OPS = {"open": "Abrir", "close": "Fechar", "focus": "Ir para"}
_SYSTEM = {"lock": "Bloquear a tela", "screenshot": "Captura de tela", "screenshot_area": "Captura de área",
           "suspend": "Suspender", "show_desktop": "Mostrar área de trabalho", "mic_mute": "Microfone mudo",
           "dnd_on": "Não perturbe: ligar", "dnd_off": "Não perturbe: desligar",
           "dnd_toggle": "Não perturbe", "empty_trash": "Esvaziar a lixeira"}


def keys_label(keys: list[str]) -> str:
    parts = []
    for k in keys:
        if k in _MODS:
            parts.append(_MODS[k])
        else:
            n = k.removeprefix("KEY_")
            parts.append(_KEYNAMES.get(n, n if len(n) > 1 else n.upper()))
    # modificadores primeiro, na ordem Ctrl, Shift, Alt, ...
    combo = "+".join(parts)
    return _PRESETS.get(combo, combo)


def action_label(a: dict, smart_name=lambda sid: None) -> str:
    """Rótulo curto da ação ('' para default/disabled/gestures)."""
    t = a.get("type")
    if t == "keys":
        return keys_label(a.get("keys", []))
    if t == "mouse_button":
        return _BUTTONS.get(a.get("button"), str(a.get("button", "")).removeprefix("BTN_").title())
    if t == "media":
        return _MEDIA.get(a.get("op"), "Mídia")
    if t == "volume":
        return _VOLUME.get(a.get("op"), "Volume")
    if t == "window":
        return _WINDOW.get(a.get("op"), "Janela")
    if t == "open":
        tgt = str(a.get("target", ""))
        return "Abrir " + (tgt if len(tgt) <= 40 else tgt[:37] + "…")
    if t == "type_text":
        return "Digitar texto"
    if t == "ai_prompt":
        return "Perguntar à IA (" + _SERVICES.get(a.get("service"), "IA") + ")"
    if t == "smart_action":
        return smart_name(a.get("id")) or "Smart Action"
    if t == "app":
        tgt = os.path.basename(str(a.get("target", ""))).removesuffix(".desktop")
        return f"{_APP_OPS.get(a.get('op'), 'App')} {tgt}"
    if t == "key_sequence":
        return "Sequência de teclas"
    if t == "system":
        return _SYSTEM.get(a.get("op"), "Sistema")
    if t == "command":
        argv = a.get("argv") or [""]
        return "Executar " + os.path.basename(argv[0])
    if t == "change_host":
        return f"Easy-Switch: canal {int(a.get('host', 0)) + 1}"
    return ""


def trigger_label(a: dict, direction: str = "", smart_name=lambda sid: None) -> str:
    """'Gesto ↑ — Nova aba' para gestos; só o rótulo da ação para botões comuns."""
    base = action_label(a, smart_name)
    if direction in ("up", "down", "left", "right"):
        return f"Gesto {ARROWS[direction]} — {base}" if base else f"Gesto {ARROWS[direction]}"
    return base
