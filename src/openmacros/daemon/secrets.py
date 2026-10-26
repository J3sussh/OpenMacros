"""Detector de segredos em texto (puro, sem I/O). Usado pelo ai_prompt para nunca mandar um segredo na URL.

Conservador: prefere um falso positivo (o prompt vai para o CLIPBOARD em vez da URL) a vazar uma
credencial no histórico do navegador. Texto comum em português não deve disparar.
"""

from __future__ import annotations

import math
import re

_I = re.IGNORECASE

# (rótulo, regex) — padrões inequívocos
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("authorization_header", re.compile(
        r"\bAuthorization\s*:\s*(?:(?:Basic|Bearer|Digest|Token|NTLM|Negotiate)\s+\S+|[A-Za-z0-9._~+/=-]{16,})", _I)),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack_token", re.compile(r"\bxox[abprsoe]-[A-Za-z0-9-]{10,}")),
    ("slack_app_token", re.compile(r"\bxapp-[A-Za-z0-9-]{20,}")),
    ("npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{30,}")),
    ("cookie", re.compile(r"(?<![A-Za-z0-9-])(?:Set-)?Cookie\s*:\s*[^\s=;]{1,64}=[^\s;]{4,}", _I)),
    ("url_credentials", re.compile(r"://[^\s/:@]{1,64}:[^\s/@]{1,128}@")),
    ("sshpass", re.compile(r"\bsshpass\b[^\n|;&]{0,64}?\s-p\s*(?:'[^']+'|\"[^\"]+\"|\S+)")),
    ("curl_credentials", re.compile(
        r"\bcurl\b[^\n|;&]{0,120}?\s(?:-u|--user)(?:\s+|=)['\"]?[^\s:'\"]{1,64}:[^\s'\"]+")),
    ("api_token", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|"
                             r"glpat-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{35})")),
    ("bcrypt_hash", re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{20,}")),
    ("md5crypt_hash", re.compile(r"\$1\$[^\s$]{0,16}\$[./A-Za-z0-9]{20,}")),
    ("sha256crypt_hash", re.compile(r"\$5\$(?:rounds=\d+\$)?[^\s$]{0,16}\$[./A-Za-z0-9]{20,}")),
    ("sha512crypt_hash", re.compile(r"\$6\$(?:rounds=\d+\$)?[^\s$]{0,16}\$[./A-Za-z0-9]{20,}")),
    ("apr1_hash", re.compile(r"\$apr1\$[^\s$]{0,8}\$[./A-Za-z0-9]{20,}")),
    ("yescrypt_hash", re.compile(r"\$y\$[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{0,64}\$[./A-Za-z0-9]{20,}")),
    ("krb5_hash", re.compile(r"\$krb5(?:tgs|asrep)\$\S{20,}")),
    ("argon2_hash", re.compile(r"\$argon2(?:id|i|d)\$\S{10,}")),
    ("ntlm_hash", re.compile(r"\baad3b435b51404ee", _I)),
]
_BEARER = re.compile(r"\bBearer\s+([A-Za-z0-9._~+/=-]{10,})")
_ASSIGN = re.compile(
    r"(?<![A-Za-z0-9])(?:password|passwd|senha|secret|api[_-]?key|(?:access|refresh|auth|session)[_-]?token)(?![A-Za-z])[\"']?\s*(=|:)\s*[\"']?([^\s\"']{1,})", _I)
_FLAG = re.compile(
    r"(?<![\w-])--?(?:password|passwd|pass|pwd|secret|token|api-?key|auth-?token|access-?token)(=|\s+)(['\"]?)([^\s'\"]+)",
    _I)
_URL_TOKEN = re.compile(
    r"[?&;](?:access_token|refresh_token|id_token|auth_token|token|api_?key|apikey|secret|sig|signature|"
    r"password|session|auth|key)=([A-Za-z0-9._~%+/=-]{32,})", _I)
_ALNUM_RUN = re.compile(r"[0-9A-Za-z]{32,}")
_HEX_ONLY = re.compile(r"[0-9a-fA-F]+")
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9_+/=-]{32,}")
_STRIP = "\"'`()[]{}<>,;:.!?"


def _entropy(s: str) -> float:
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(ch) for ch in set(s)))


def _generic_token(tok: str) -> bool:
    if not _TOKEN_CHARS.fullmatch(tok) or tok.startswith("/") or tok.count("/") > 2:
        return False
    has_digit = any(c.isdigit() for c in tok)
    has_upper = any(c.isupper() for c in tok)
    has_lower = any(c.islower() for c in tok)
    if not has_digit or not (has_upper or has_lower):
        return False
    if has_upper and has_lower:
        return True  # misto maiúsc./minúsc./dígitos: típico de base64/aleatório (slugs são minúsculos)
    return "-" not in tok and "_" not in tok and _entropy(tok) >= 3.5


def find_secret(text: str) -> str | None:
    """Rótulo do primeiro tipo de segredo encontrado, ou None."""
    if not isinstance(text, str) or not text:
        return None
    for label, rx in _PATTERNS:
        if rx.search(text):
            return label
    for m in _BEARER.finditer(text):
        tok = m.group(1)
        if any(c.isdigit() or c in "._~+/=-" for c in tok):
            return "bearer_token"
    for m in _ASSIGN.finditer(text):
        sep, val = m.group(1), m.group(2).rstrip(".,;!?)")
        # "senha: criada" é prosa; "senha=x" / "senha: abc123" é credencial
        if val and (sep == "=" or any(not c.isalpha() for c in val)):
            return "credential_assignment"
    for m in _FLAG.finditer(text):
        sep, quote, val = m.group(1), m.group(2), m.group(3).rstrip(".,;!?)")
        # "--password=x" é atribuição; "--password x" só se o valor tiver cara de senha (aspas/dígito/símbolo):
        # "a opção --password é obrigatória" é prosa
        if val and (sep == "=" or quote or any(not c.isalpha() for c in val)):
            return "password_flag"
    for m in _URL_TOKEN.finditer(text):
        v = m.group(1)
        if any(c.isdigit() for c in v) and any(c.isalpha() for c in v):
            return "url_token"
    for m in _ALNUM_RUN.finditer(text):  # varredura linear (nada de lookahead aninhado: sem ReDoS)
        run = m.group(0)
        if _HEX_ONLY.fullmatch(run) and any(c.isdigit() for c in run) and any(c in "abcdefABCDEF" for c in run):
            return "hex_hash"
    for raw in text.split():
        tok = raw.strip(_STRIP)
        if len(tok) >= 32 and _generic_token(tok):
            return "token"
    return None


def contains_secret(text: str) -> bool:
    return find_secret(text) is not None
