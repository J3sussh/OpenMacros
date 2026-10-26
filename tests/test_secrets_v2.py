"""Detector de segredos: cobertura da revisão (cookies, URLs, flags, hashes extras) + sem ReDoS."""
import time

import pytest

from openmacros.daemon.secrets import find_secret

JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
TOK32 = "aB3dE5gH7jK9mN1pQ3sT5vX7zA2cE4gI"


@pytest.mark.parametrize("text,kind", [
    # cookies
    ("Cookie: session=abc123def456", "cookie"),
    ("curl -H 'Cookie: PHPSESSID=8f3k2j4h5g6' https://x.com", "cookie"),
    ("Set-Cookie: id=a3fWa; Expires=Wed, 21 Oct 2026 07:28:00 GMT; HttpOnly", "cookie"),
    ("set-cookie: token=zzzz9999; Path=/", "cookie"),
    # credenciais em URL
    ("git clone https://usuario:s3nh4@github.com/org/repo.git", "url_credentials"),
    ("postgres://admin:hunter2@db.interno:5432/prod", "url_credentials"),
    ("ftp://u:p@ftp.exemplo.com/arquivo", "url_credentials"),
    # tokens em atribuição
    ("access_token = abcdef123456", "credential_assignment"),
    ('{"refresh_token": "1//0gAbCdEfGh123"}', "credential_assignment"),
    ("AUTH_TOKEN=xyz987abc654", "credential_assignment"),
    ("session-token: a1b2c3d4e5", "credential_assignment"),
    ("export SESSION_TOKEN='abc'", "credential_assignment"),
    # hashes crypt/kerberos
    ("$1$saltsalt$qJH7.wvC3OjgThYSd6jYb0", "md5crypt_hash"),
    ("$5$saltsalt$5B8vYYiY.CVt1RlTTf8KbXBH3hsxY/GNooZaBBGWEc5", "sha256crypt_hash"),
    ("$5$rounds=5000$saltsalt$5B8vYYiY.CVt1RlTTf8KbXBH3hsxY/GNooZaBBGWEc5", "sha256crypt_hash"),
    ("$6$rounds=5000$saltsalt$Zr1XqwVZrW2lLo3p9ZPuY.vN7tDrl4T9lUHbs0uvoI9xGE2JdaQ4n8u8QL0v2yU1x2Y4mC1d9v6", "sha512crypt_hash"),
    ("root:$apr1$Pq1v6D2e$kJ9vUq9m0a3dXrRk7H1ZP0:", "apr1_hash"),
    ("$y$j9T$F5Jx5fExrKuPp53xLKQ..1$X3DX6M94c7o.9agCG9G317fhZg9SqC.5i5rd.RhAtQ7", "yescrypt_hash"),
    ("$krb5tgs$23$*svc$CORP.LOCAL$cifs/dc*$a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6$0123456789abcdef", "krb5_hash"),
    ("$krb5asrep$23$user@CORP.LOCAL:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6$0123456789abcdef", "krb5_hash"),
    # tokens de serviços
    ("npm_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", "npm_token"),
    ("xa" "pp-1-A0123456789-1234567890123-abcdef0123456789abcdef", "slack_app_token"),
    ("xo" "xe-1-abcdefghijklmnop", "slack_token"),
    # flags de linha de comando
    ("mysql -u root --password hunter2 -h db", "password_flag"),
    ("mysql --password=hunter2", "credential_assignment"),
    ("tool --token=abcd", "password_flag"),
    ("tool --api-key 'my secret key'", "password_flag"),
    ("cmd --pass s3cr3t!", "password_flag"),
    ("sshpass -p 'minha senha' ssh user@host", "sshpass"),
    ("sshpass -f x -p hunter2 ssh u@h", "sshpass"),
    ("sshpass -phunter2 ssh u@h", "sshpass"),
    ("curl -u admin:s3cret https://api.exemplo.com", "curl_credentials"),
    ("curl -s --user 'admin:s3 cret' https://x", "curl_credentials"),
    ("curl -X POST -u bob:pw123 -d x https://y", "curl_credentials"),
    # tokens dentro de URL
    (f"https://api.exemplo.com/v1/me?access_token={TOK32}", "credential_assignment"),
    (f"https://x.com/cb?state=1&token={TOK32}&x=2", "url_token"),
    (f"https://x.com/cb?sig={TOK32}", "url_token"),
    (f"https://x.com/cb?api_key={TOK32}", "credential_assignment"),
    # os anteriores continuam valendo
    (JWT, "jwt"),
    ("password=hunter2", "credential_assignment"),
    ("5d41402abc4b2a76b9719d911017c592", "hex_hash"),
])
def test_secret_positives(text, kind):
    assert find_secret(text) == kind


@pytest.mark.parametrize("text", [
    "Preciso configurar o cookie de sessão do navegador para o teste, qual é a melhor forma?",
    "Cookie: biscoito de chocolate é o meu preferido",
    "O servidor define um Set-Cookie: com o atributo HttpOnly para proteger a sessão.",
    "Veja https://usuario@exemplo.com/pagina e http://localhost:3000/@fulano/post",
    "Acesse ssh://git@github.com:org/repo e depois http://exemplo.com:8080/caminho",
    "O access token expira em uma hora; renove o refresh token antes disso.",
    "O token de acesso: expirado, gere outro depois.",
    "a opção --password é obrigatória neste comando, e --token também",
    "use a flag --pass para informar o valor e depois --secret para o resto",
    "O sshpass lê a senha de um arquivo; o curl aceita -u para usuário e senha.",
    "curl -u usuario https://exemplo.com (pede a senha no terminal)",
    "curl -s https://exemplo.com/api?x=1 | jq .",
    "custa $5$ por mês, ou $1$ no plano básico; $6$ não existe",
    "O preço é $1$ou$2$ reais",
    "https://exemplo.com/busca?q=como-configurar-o-servidor-de-impressao-em-rede-linux&page=2",
    "https://exemplo.com/cb?token=curto&key=abc",
    "https://exemplo.com/cb?key=abcdefghijklmnopqrstuvwxyzabcdefghij",     # 32+ sem dígito
    "Escolha a senha com cuidado e nunca compartilhe sua senha com ninguém.",
    "npm install e depois npm run build; veja o pacote npm_modules",
    "A reunião é às 14h; confirme a presença até sexta-feira, por favor.",
    "Explique a diferença entre autenticação e autorização em APIs REST.",
    "SELECT * FROM usuarios WHERE nome = 'João' AND idade > 30;",
    "O hash SHA-256 é uma função criptográfica de 256 bits (64 caracteres hexadecimais).",
])
def test_secret_negatives_ptbr_prose_and_benign_text(text):
    assert find_secret(text) is None


PATHOLOGICAL = [
    "a" * 8192, "0" * 8192, "f" * 8191 + "g", "A1" * 4096, "=" * 8192, " " * 8192, "$" * 8192,
    "eyJ" * 2730, "eyJ" + "a" * 8189, "eyJaaaaaaaa." * 680, "$6$" * 2730, "$6$" + "a" * 8189,
    "$1$a" * 2000, "$y$" * 2730, "$krb5tgs$" * 900, "password " * 900, "password=" * 900,
    "password" + " " * 8184, "Authorization " * 580, "Authorization" + " " * 8179, "Authorization: " + "a" * 8177,
    "Bearer " * 1170, "Bearer " + "a" * 8185, "sshpass " * 1000, "sshpass " + "x " * 4000, "curl " * 1600,
    "curl " + "-u " * 2700, "curl -u " + "a:" * 4000, "://" * 2700, "://" + "a" * 8189, "://a:" * 1600,
    "://" + "a" * 60 + ":" + "b" * 8100, "Cookie: " * 1000, "Cookie: " + "a=" * 4000, "Set-Cookie:" * 740,
    "--password " * 740, "--password=" + "x" * 8180, "--" * 4096, "-" * 8192, "?token=" * 1170,
    "?token=" + "a1" * 4090, "&key=" + "a" * 8187, "xa" "pp-" * 1630, "npm_" * 2048, "xox" * 2730,
    "-----BEGIN " * 740, "-----BEGIN " + "A " * 4000, ("a" * 31 + " ") * 256, ("a1" * 16 + " ") * 248,
    "a" * 4000 + "=" + "b" * 4000, "_" * 8192, "/" * 8192, "a/" * 4096, "a.b" * 2730, "A-" * 4096,
    "Authorization: Basic " + "x" * 8100, "api_key" + "=" * 8180, "senha:" + " " * 8180 + "x",
    "aad3b435b51404ee" * 512, "0123456789abcdef" * 512, "0123456789abcdefg" * 481,
]


@pytest.mark.parametrize("text", PATHOLOGICAL, ids=[f"{i}" for i in range(len(PATHOLOGICAL))])
def test_no_redos_on_8kib_pathological_input(text):
    text = text[:8192]
    t0 = time.perf_counter()
    find_secret(text)
    assert time.perf_counter() - t0 < 0.05, f"{(time.perf_counter() - t0) * 1000:.0f} ms"
