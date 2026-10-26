"""Preferências globais (config.json -> "preferences"): padrões e validação. Puro."""

from __future__ import annotations

DEFAULTS: dict = {
    "notify_battery": True,
    "battery_threshold": 15,
    "osd_profile": True,
    "osd_gestures": True,
    "notify_connection": False,
    "ai_delivery_default": "clipboard",
}
THRESHOLD_MIN, THRESHOLD_MAX = 5, 50
AI_DELIVERIES = ("clipboard", "url")


def validate_preference(key: str, value):
    """Devolve o valor normalizado ou levanta ValueError com mensagem legível."""
    if key not in DEFAULTS:
        raise ValueError(f"preferência desconhecida: {key}")
    if key == "battery_threshold":
        if not isinstance(value, int) or isinstance(value, bool) or not THRESHOLD_MIN <= value <= THRESHOLD_MAX:
            raise ValueError(f"'battery_threshold' deve ser inteiro entre {THRESHOLD_MIN} e {THRESHOLD_MAX}")
    elif key == "ai_delivery_default":
        if value not in AI_DELIVERIES:
            raise ValueError("'ai_delivery_default' deve ser 'clipboard' ou 'url'")
    elif not isinstance(value, bool):
        raise ValueError(f"'{key}' espera booleano")
    return value


def validate_preferences(obj) -> dict:
    """Valida um objeto parcial de preferências (importação). Chaves desconhecidas são rejeitadas."""
    if not isinstance(obj, dict):
        raise ValueError("'preferences' deve ser um objeto")
    return {k: validate_preference(k, v) for k, v in obj.items()}


def sanitize_preferences(obj) -> dict:
    """Leitura tolerante do config.json: descarta chaves/valores inválidos."""
    out: dict = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            try:
                out[k] = validate_preference(k, v)
            except ValueError:
                pass
    return out


def with_defaults(stored: dict) -> dict:
    return {**DEFAULTS, **stored}
