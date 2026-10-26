"""Contrato v2 / B: segredos, ai_prompt, colagem, preferências, backup, perfil vazio, bateria, OSD."""
import json

import pytest
from evdev import ecodes

from openmacros.daemon import backup
from openmacros.daemon import manager as mg
from openmacros.daemon import preferences as P
from openmacros.daemon.actions import ActionExecutor, NullBackend, validate_action
from openmacros.daemon.config import Config
from openmacros.daemon.fake import FakeBackend
from openmacros.daemon.focus import FakeFocusWatcher
from openmacros.daemon.gestures import ActionEvent
from openmacros.daemon.notify import BatteryAlerts, RecordingNotifier
from openmacros.daemon.secrets import find_secret
from openmacros.daemon.timers import ManualScheduler

M720 = "logi:FA4E720A"
GEN = "logi:FA4E0001"
KEYS_A = {"type": "keys", "keys": ["KEY_A"]}
KEYS_B = {"type": "keys", "keys": ["KEY_B"]}


# ------------------------------------------------------------------ B2: detector de segredos
@pytest.mark.parametrize("text,kind", [
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "jwt"),
    ("chave AK" "IAIOSFODNN7EXAMPLE usada", "aws_access_key"),
    ("AS" "IAY34FZKBOKMUTVV7A", "aws_access_key"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIE...", "private_key"),
    ("-----BEGIN PRIVATE KEY-----", "private_key"),
    ("curl -H 'Authorization: Bearer abc123def456ghi' x", "authorization_header"),
    ("Authorization: Basic dXNlcjpwYXNz", "authorization_header"),
    ("token Bearer a1b2c3d4e5f6g7h8", "bearer_token"),
    ("password=hunter2", "credential_assignment"),
    ("PASSWD = secreto", "credential_assignment"),
    ("senha: abc123", "credential_assignment"),
    ("DB_PASSWORD: 'p@ssw0rd'", "credential_assignment"),
    ("api_key = sk_live_whatever", "credential_assignment"),
    ("x-api-key: 12345abcde", "credential_assignment"),
    ("$2b$12$KIXQJ3b2pU1h7l9cV0g8UuY8m4vD5rR1sQ2wE3tY4uI5oP6aS7dFg", "bcrypt_hash"),
    ("$6$saltsalt$qFmFH.bQmmtXzyBY0DZiI9JMeSQvdLQ2yIXbJ2sD5f4k1e8Yx6d0pM3nB7vC2zL9aS", "sha512crypt_hash"),
    ("$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$RdescudvJCsgt3ub", "argon2_hash"),
    ("aad3b435b51404eeaad3b435b51404ee:31d6cfe0d16ae931b73c59d7e0c089c0", "ntlm_hash"),
    ("5d41402abc4b2a76b9719d911017c592", "hex_hash"),
    ("da39a3ee5e6b4b0d3255bfef95601890afd80709", "hex_hash"),
    ("gh" "p_1234567890abcdefghijklmnopqrstuvwxyzAB", "github_token"),
    ("gi" "thub_pat_11ABCDEFG0abcdefghijkl_mnopqrstuvwxyz", "github_token"),
    ("xo" "xb-123456789012-abcdefghijkl", "slack_token"),
    ("sk-proj-abcdefghijklmnopqrstuvwx", "api_token"),
    ("sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx", "api_token"),
    ("tok: Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MEFCQ0RFRkdISUo=", "token"),
    ("aB3dE5gH7jK9mN1pQ3sT5vX7zA2cE4gI6kM8oQ0s", "token"),
])
def test_secret_positives(text, kind):
    assert find_secret(text) == kind


@pytest.mark.parametrize("text", [
    "",
    "Explique como funciona a ordenação de listas em Python, por favor.",
    "A configuração de autenticação é importante: não use senhas fracas nem reutilize a senha.",
    "A nova senha: criada com sucesso. Authorization required para continuar.",
    "O Bearer authentication é um esquema HTTP; veja também a seção sobre tokens.",
    "https://exemplo.com.br/2024/12/como-configurar-o-servidor-de-impressao-em-rede",
    "/home/user/Documentos/Projeto2024/Relatorio/final-versao-corrigida.pdf",
    "pneumoultramicroscopicossilicovulcanoconiose é uma palavra muito longa",
    "Reunião às 14h30 com João, Conceição e Ângela sobre o orçamento de R$ 12.345,67.",
    "def password_hash(user): return user.name  # senha tratada em outro lugar",
    "cat /etc/passwd | grep root",
    "O número 12345678901234567890123456789012345 não é um hash.",
    "commit 3f2a9c1 corrige o bug",
    "2023-12-31-reuniao-trimestral-de-planejamento-estrategico",
])
def test_secret_negatives(text):
    assert find_secret(text) is None


# ------------------------------------------------------------------ executor com fakes
class Rec:
    def __init__(self, ret=True):
        self.calls, self.ret = [], ret

    def run(self, *a):
        self.calls.append(a)
        return self.ret


class Opener:
    def __init__(self):
        self.uris = []

    def open_uri(self, u):
        self.uris.append(u)
        return True

    def launch_desktop(self, t):
        return True


class Sel:
    def __init__(self, primary="", clipboard="anterior"):
        self.primary, self.clipboard = primary, clipboard
        self.writes = []

    def read_primary(self):
        return self.primary

    def read_clipboard(self):
        return self.clipboard

    def write_clipboard(self, t):
        self.writes.append(t)
        self.clipboard = t
        return True

    cleared = 0

    def clear_clipboard(self):
        self.cleared += 1
        self.clipboard = None
        return True


def make_ex(selection=None, app_id="", prefs=None):
    be, sched, note = NullBackend(), ManualScheduler(), RecordingNotifier()
    ex = ActionExecutor(be, scheduler=sched, media=Rec(), volume=Rec(), opener=Opener(), windows=Rec(),
                        selection=selection or Sel(), notifier=note)
    ex.app_id_lookup = lambda: app_id
    if prefs is not None:
        ex.prefs_lookup = lambda: {**P.DEFAULTS, **prefs}
    return ex, be, sched, note


def trig(ex, action):
    ex.perform(ActionEvent("trigger", action, 0, "d"))


AI = {"type": "ai_prompt", "service": "claude", "template": "Explique: {selection}"}


def test_ai_default_is_clipboard_with_home_url_and_notification():
    sel = Sel("trecho comum")
    ex, _, _, note = make_ex(sel)
    trig(ex, AI)
    assert ex.opener.uris == ["https://claude.ai/new"]
    assert sel.writes == ["Explique: trecho comum"]
    assert note.summaries() == ["Prompt copiado — cole com Ctrl+V"]


@pytest.mark.parametrize("service,home", [
    ("claude", "https://claude.ai/new"), ("chatgpt", "https://chatgpt.com/"),
    ("perplexity", "https://www.perplexity.ai/"), ("gemini", "https://gemini.google.com/app")])
def test_ai_home_urls(service, home):
    ex, *_ = make_ex(Sel("x"))
    trig(ex, {**AI, "service": service})
    assert ex.opener.uris == [home]


def test_ai_url_delivery_puts_prompt_in_query_only_when_chosen():
    sel = Sel("a b")
    ex, *_ = make_ex(sel)
    trig(ex, {**AI, "delivery": "url"})
    assert ex.opener.uris == ["https://claude.ai/new?q=Explique%3A%20a%20b"] and sel.writes == []


def test_ai_preference_default_url_is_used_when_action_has_no_delivery():
    sel = Sel("a b")
    ex, *_ = make_ex(sel, prefs={"ai_delivery_default": "url"})
    trig(ex, AI)
    assert ex.opener.uris[0].startswith("https://claude.ai/new?q=")
    trig(ex, {**AI, "delivery": "clipboard"})  # a ação explícita vence a preferência
    assert ex.opener.uris[1] == "https://claude.ai/new"


def test_ai_secret_forces_clipboard_even_with_url():
    sel = Sel("password=hunter2 e mais texto")
    ex, _, _, note = make_ex(sel)
    trig(ex, {**AI, "delivery": "url"})
    assert ex.opener.uris == ["https://claude.ai/new"]  # nada de ?q=
    assert "hunter2" not in ex.opener.uris[0]
    assert sel.writes and "hunter2" in sel.writes[0]
    assert note.summaries() == ["Seleção parece conter um segredo — não foi para a URL"]


def test_ai_empty_selection_notifies_and_opens_nothing():
    for empty in ("", "   \n"):
        sel = Sel(empty)
        ex, _, _, note = make_ex(sel)
        trig(ex, AI)
        assert ex.opener.uris == [] and sel.writes == []
        assert note.summaries() == ["Nada selecionado"]


def test_validate_ai_delivery_and_type_text_method():
    assert "delivery" not in validate_action(AI)
    assert validate_action({**AI, "delivery": "url"})["delivery"] == "url"
    with pytest.raises(ValueError):
        validate_action({**AI, "delivery": "email"})
    assert validate_action({"type": "type_text", "text": "olá"})["method"] == "paste"
    assert validate_action({"type": "type_text", "text": "x", "method": "keys"})["method"] == "keys"
    with pytest.raises(ValueError):
        validate_action({"type": "type_text", "text": "x", "method": "magic"})
    with pytest.raises(ValueError):
        validate_action({"type": "type_text", "text": "x" * 2001})


# ------------------------------------------------------------------ B1: colagem
def test_paste_sends_ctrl_v_and_restores_clipboard_later():
    sel = Sel(clipboard="meu clipboard")
    ex, be, sched, _ = make_ex(sel, app_id="firefox")
    trig(ex, {"type": "type_text", "text": "ação é ç ã — ünïcode", "method": "paste"})
    assert sel.writes == ["ação é ç ã — ünïcode"]
    ctrl, v = ecodes.KEY_LEFTCTRL, ecodes.KEY_V
    assert be.log == [("key", ctrl, 1), ("key", v, 1), ("key", v, 0), ("key", ctrl, 0)]
    sched.advance(599)
    assert sel.writes == ["ação é ç ã — ünïcode"]  # ainda não restaurou
    sched.advance(1)
    assert sel.writes[-1] == "meu clipboard" and sel.clipboard == "meu clipboard"


def test_paste_in_terminal_uses_ctrl_shift_v():
    ex, be, _, _ = make_ex(app_id="xfce4-terminal")
    trig(ex, {"type": "type_text", "text": "ls"})  # método padrão = paste
    ctrl, sh, v = ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTSHIFT, ecodes.KEY_V
    assert be.log == [("key", ctrl, 1), ("key", sh, 1), ("key", v, 1),
                      ("key", v, 0), ("key", sh, 0), ("key", ctrl, 0)]


def test_back_to_back_pastes_restore_the_original_clipboard():
    sel = Sel(clipboard="original")
    ex, _, sched, _ = make_ex(sel)
    trig(ex, {"type": "type_text", "text": "um"})
    sched.advance(300)
    trig(ex, {"type": "type_text", "text": "dois"})
    sched.advance(600)
    assert sel.clipboard == "original" and sel.writes == ["um", "dois", "original"]


def test_paste_without_previous_text_clipboard_clears_pasted_text_after_restore_delay():
    sel = Sel(clipboard=None)
    ex, _, sched, _ = make_ex(sel)
    trig(ex, {"type": "type_text", "text": "x"})
    sched.advance(599)
    assert sel.cleared == 0 and sel.clipboard == "x"
    sched.advance(1)
    assert sel.writes == ["x"] and sel.cleared == 1 and sel.clipboard is None  # a senha colada não fica lá


def test_paste_failure_to_write_clipboard_sends_no_keys():
    class Broken(Sel):
        def write_clipboard(self, t):
            return False
    ex, be, _, _ = make_ex(Broken())
    trig(ex, {"type": "type_text", "text": "x"})  # erro é logado, não propaga
    assert be.log == []


def test_keys_method_keeps_old_behaviour():
    sel = Sel()
    ex, be, _, _ = make_ex(sel)
    trig(ex, {"type": "type_text", "text": "a", "method": "keys"})
    assert sel.writes == [] and be.log == [("key", ecodes.KEY_A, 1), ("key", ecodes.KEY_A, 0)]


# ------------------------------------------------------------------ B3/B6: preferências
@pytest.fixture
def env(tmp_path):
    sched, be, note = ManualScheduler(), NullBackend(), RecordingNotifier()
    ex = ActionExecutor(be, scheduler=sched, media=Rec(), volume=Rec(), windows=Rec(), selection=Sel())
    mgr = mg.Manager(Config(tmp_path / "c.json"), ex, sched, FakeFocusWatcher(), notifier=note,
                     app_namer=lambda app: app["app_id"].title())
    mgr.debug = True
    mgr.backends.append(FakeBackend())
    mgr.signals = []
    mgr.listeners.append(lambda n, *a: mgr.signals.append((n, a)))
    mgr.rescan()
    mgr.start_focus()
    mgr.note, mgr.sched, mgr.dev, mgr.path = note, sched, mgr.devices[M720], tmp_path / "c.json"
    return mgr


def signals(env, name):
    return [a for n, a in env.signals if n == name]


def test_preferences_defaults_and_set(env):
    assert json.loads(env.get_preferences()) == P.DEFAULTS
    assert env.set_preference("battery_threshold", "30")
    assert env.set_preference("notify_connection", "true")
    assert env.set_preference("ai_delivery_default", '"url"')
    got = json.loads(env.get_preferences())
    assert got["battery_threshold"] == 30 and got["notify_connection"] is True and got["ai_delivery_default"] == "url"
    assert len(signals(env, "preferences_changed")) == 3
    assert json.loads(env.path.read_text())["preferences"]["battery_threshold"] == 30  # persistiu
    env.set_preference("battery_threshold", "30")  # sem mudança: sem sinal repetido
    assert len(signals(env, "preferences_changed")) == 3


@pytest.mark.parametrize("key,val", [
    ("battery_threshold", "4"), ("battery_threshold", "51"), ("battery_threshold", "true"),
    ("battery_threshold", "10.5"), ("battery_threshold", '"15"'), ("notify_battery", "1"),
    ("osd_profile", '"sim"'), ("ai_delivery_default", '"email"'), ("ai_delivery_default", "true"),
    ("nao_existe", "true"), ("notify_battery", "{bad"),
])
def test_preferences_rejected(env, key, val):
    with pytest.raises(mg.InvalidArgument):
        env.set_preference(key, val)
    assert json.loads(env.get_preferences()) == P.DEFAULTS


def test_preferences_boundaries(env):
    assert env.set_preference("battery_threshold", "5") and env.set_preference("battery_threshold", "50")


def test_preferences_survive_reload_and_bad_values_are_dropped(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"version": 1, "devices": {}, "preferences": {
        "battery_threshold": 20, "notify_battery": "yes", "bogus": 1}}))
    assert Config(p).preferences == {"battery_threshold": 20}


# ------------------------------------------------------------------ B3: bateria
def test_battery_alerts_state_machine():
    a = BatteryAlerts()
    b = lambda lvl, st="discharging": {"level": lvl, "status": st}
    assert a.update("d", b(50), 15) == []
    assert a.update("d", b(15), 15) == ["low"]
    assert a.update("d", b(14), 15) == []        # uma vez por ciclo
    assert a.update("d", b(19), 15) == []        # ainda não subiu 5 pontos acima (20)
    assert a.update("d", b(14), 15) == []        # não rearmou
    assert a.update("d", b(20), 15) == []        # rearma
    assert a.update("d", b(12), 15) == ["low"]
    assert a.update("d", b(5), 15) == ["critical"]
    assert a.update("d", b(4), 15) == []
    assert a.update("d", b(30, "charging"), 15) == []   # carregar rearma tudo
    assert a.update("d", b(10, "discharging"), 15) == ["low"]
    assert a.update("d", b(3, "discharging"), 15) == ["critical"]
    assert a.update("d", None, 15) == [] and a.update("d", {"level": None}, 15) == []


def test_battery_alerts_ignores_low_level_while_charging_and_critical_skips_low():
    a = BatteryAlerts()
    assert a.update("d", {"level": 4, "status": "charging"}, 15) == []
    assert a.update("e", {"level": 4, "status": "discharging"}, 15) == ["critical"]
    assert a.update("e", {"level": 4, "status": "discharging"}, 15) == []


def set_battery(env, level, status="discharging"):
    env.dev._d["battery"] = {"level": level, "status": status, "approximate": True}
    env.dev.simulate("updated")


def test_manager_battery_notification_threshold_and_rearm(env):
    env.set_preference("battery_threshold", "20")
    set_battery(env, 25)
    assert env.note.sent == []
    set_battery(env, 20)
    assert [n["summary"] for n in env.note.sent] == ["Bateria baixa: M720 Triathlon"]
    assert env.note.sent[0]["category"] == f"battery:{M720}"
    set_battery(env, 18)
    set_battery(env, 17)
    assert len(env.note.sent) == 1
    set_battery(env, 25)  # subiu 5 pontos: rearmou
    set_battery(env, 19)
    assert len(env.note.sent) == 2
    set_battery(env, 5)
    assert env.note.sent[-1]["summary"].startswith("Bateria crítica") and env.note.sent[-1]["urgency"] == 2


def test_manager_battery_disabled_pref_is_silent(env):
    env.set_preference("notify_battery", "false")
    set_battery(env, 3)
    assert env.note.sent == []


def test_connection_notifications_follow_pref(env):
    env.dev.online = False
    env.dev.simulate("offline")
    assert env.note.sent == []
    env.set_preference("notify_connection", "true")
    env.dev.simulate("online")
    env.dev.online = False
    env.dev.simulate("offline")
    assert env.note.summaries() == ["M720 Triathlon conectado", "M720 Triathlon desconectado"]


# ------------------------------------------------------------------ B3: OSD
def test_profile_osd(env):
    env.set_profile_assignment(M720, "firefox", 83, json.dumps(KEYS_A))
    env.debug_set_active_app("firefox")
    assert env.note.sent[-1]["summary"] == "Perfil: Firefox" and env.note.sent[-1]["timeout_ms"] == 1200
    env.debug_set_active_app("burp")  # sem perfil: volta ao global
    assert env.note.sent[-1]["summary"] == "Perfil: Todos os aplicativos"
    n = len(env.note.sent)
    env.debug_set_active_app("outro")  # global -> global: nada
    assert len(env.note.sent) == n
    env.set_preference("osd_profile", "false")
    env.debug_set_active_app("firefox")
    assert len(env.note.sent) == n


def test_gesture_osd_and_action_triggered(env):
    up = {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_T"]}
    env.set_assignment(M720, 208, json.dumps({"type": "gestures", "up": up}))
    env.dev.simulate("key_report", [208])
    env.dev.simulate("raw_xy", 0, -100)
    env.dev.simulate("key_report", [])
    assert signals(env, "action_triggered") == [(M720, 208, "Gesto ↑ — Nova aba")]
    assert env.note.sent[-1]["summary"] == "Gesto ↑ — Nova aba" and env.note.sent[-1]["timeout_ms"] == 800
    env.set_preference("osd_gestures", "false")
    env.dev.simulate("key_report", [208])
    env.dev.simulate("raw_xy", 0, -100)
    env.dev.simulate("key_report", [])
    assert len(signals(env, "action_triggered")) == 2 and len(env.note.sent) == 1


def test_plain_button_emits_action_triggered_without_osd(env):
    env.set_assignment(M720, 82, json.dumps({"type": "media", "op": "next"}))
    env.dev.simulate("key_report", [82])
    env.dev.simulate("key_report", [])
    assert signals(env, "action_triggered") == [(M720, 82, "Próxima faixa")]
    assert env.note.sent == []


# ------------------------------------------------------------------ B4: perfil vazio
def test_empty_profile_removed_after_last_assignment_null(env):
    env.set_profile_assignment(M720, "firefox", 83, json.dumps(KEYS_A))
    env.set_profile_assignment(M720, "firefox", 86, json.dumps(KEYS_B))
    env.set_profile_assignment(M720, "firefox", 83, "null")
    assert "firefox" in json.loads(env.get_device(M720))["profiles"]
    env.signals.clear()
    env.set_profile_assignment(M720, "firefox", 86, "null")
    assert json.loads(env.get_device(M720))["profiles"] == {}
    assert "profiles" not in env.config.data["devices"][M720]
    assert any(a[0] == M720 and json.loads(a[1])["profiles"] == {} for a in signals(env, "device_updated"))


def test_profile_with_setting_survives_assignment_null_and_vice_versa(env):
    env.set_profile_assignment(M720, "code", 83, json.dumps(KEYS_A))
    env.set_profile_setting(M720, "code", "scroll_invert", "true")
    env.set_profile_assignment(M720, "code", 83, "null")
    assert "code" in json.loads(env.get_device(M720))["profiles"]
    env.set_profile_setting(M720, "code", "scroll_invert", "null")
    assert json.loads(env.get_device(M720))["profiles"] == {}


def test_null_on_missing_profile_does_not_create_one(env):
    env.set_profile_assignment(M720, "ghost", 83, "null")
    env.set_profile_setting(M720, "ghost", "scroll_invert", "null")
    assert json.loads(env.get_device(M720))["profiles"] == {}


def test_empty_profile_active_app_returns_to_global_settings(env):
    env.set_profile_setting(M720, "code", "pointer_speed", "123")
    env.debug_set_active_app("code")
    env.sched.advance(300)
    assert env.dev.describe()["settings"]["pointer_speed"]["value"] == 123
    env.set_profile_setting(M720, "code", "pointer_speed", "null")
    env.sched.advance(300)
    assert json.loads(env.get_device(M720))["active_profile"] == ""
    assert env.dev.describe()["settings"]["pointer_speed"]["value"] == 256  # baseline restaurado


# ------------------------------------------------------------------ B5: backup
def populate(env):
    env.set_assignment(M720, 82, json.dumps(KEYS_A))
    env.set_setting(M720, "pointer_speed", "300")
    env.set_profile_assignment(M720, "firefox", 83, json.dumps(KEYS_B))
    env.set_profile_setting(M720, "firefox", "scroll_invert", "true")
    sid = json.loads(env.save_smart_action(json.dumps(
        {"name": "Mudo", "steps": [{"type": "volume", "op": "mute"}]})))["id"]
    env.set_assignment(M720, 86, json.dumps({"type": "smart_action", "id": sid}))
    env.set_preference("battery_threshold", "25")
    return sid


def test_export_shape_has_no_baseline(env):
    populate(env)
    env.config.set_baseline(M720, "scroll_invert", False)
    exp = json.loads(env.export_config())
    assert exp["openmacros_export"] == 1 and exp["exported_at"].endswith("+00:00")
    assert set(exp) == {"openmacros_export", "exported_at", "devices", "smart_actions", "preferences"}
    assert "baseline" not in exp["devices"][M720]
    assert exp["devices"][M720]["profiles"]["firefox"]["assignments"]["83"] == KEYS_B
    assert exp["preferences"] == {**P.DEFAULTS, "battery_threshold": 25}


def test_roundtrip_replace_into_fresh_manager(env, tmp_path):
    sid = populate(env)
    exported = env.export_config()
    sched = ManualScheduler()
    other = mg.Manager(Config(tmp_path / "other.json"),
                       ActionExecutor(NullBackend(), scheduler=sched, selection=Sel()), sched,
                       FakeFocusWatcher(), notifier=RecordingNotifier())
    other.backends.append(FakeBackend())
    other.signals = []
    other.listeners.append(lambda n, *a: other.signals.append(n))
    other.rescan()
    assert other.import_config(exported, False) is True
    again = json.loads(other.export_config())
    first = json.loads(exported)
    first.pop("exported_at"), again.pop("exported_at")
    assert again == first
    # reaplicou no dispositivo online
    d = json.loads(other.get_device(M720))
    assert d["assignments"]["82"] == KEYS_A and d["settings"]["pointer_speed"]["value"] == 300
    assert d["profiles"]["firefox"]["assignments"]["83"] == KEYS_B
    assert sid in json.loads(other.get_smart_actions())
    assert "smart_actions_changed" in other.signals and "preferences_changed" in other.signals
    assert json.loads((tmp_path / "other.json").read_text())["preferences"]["battery_threshold"] == 25  # persistiu


def test_import_replace_drops_old_data(env):
    populate(env)
    doc = {"openmacros_export": 1, "devices": {M720: {"assignments": {"83": KEYS_B}, "settings": {}}},
           "smart_actions": {}}
    assert env.import_config(json.dumps(doc), False)
    d = json.loads(env.get_device(M720))
    assert list(d["assignments"]) == ["83"] and d["profiles"] == {} and json.loads(env.get_smart_actions()) == {}
    assert json.loads(env.get_preferences())["battery_threshold"] == 25  # seção ausente: preservada


def test_import_merge_by_key(env):
    sid = populate(env)
    doc = {"openmacros_export": 1,
           "devices": {M720: {"assignments": {"83": KEYS_B},
                              "settings": {"hires_scroll": False},
                              "profiles": {"firefox": {"assignments": {"86": KEYS_A}, "settings": {}},
                                           "code": {"assignments": {"82": KEYS_B}, "settings": {}}}},
                       "logi:OUTRO": {"assignments": {"82": KEYS_A}, "settings": {}}},
           "smart_actions": {"sa_novo": {"name": "Novo", "steps": [{"type": "delay", "ms": 20}]}},
           "preferences": {"osd_profile": False}}
    assert env.import_config(json.dumps(doc), True)
    d = json.loads(env.get_device(M720))
    assert set(d["assignments"]) == {"82", "83", "86"}
    assert d["settings"]["pointer_speed"]["value"] == 300 and d["settings"]["hires_scroll"]["value"] is False
    assert set(d["profiles"]["firefox"]["assignments"]) == {"83", "86"}
    assert d["profiles"]["firefox"]["settings"]["scroll_invert"] == {"value": True}
    assert "code" in d["profiles"]
    assert set(json.loads(env.get_smart_actions())) == {sid, "sa_novo"}
    assert "logi:OUTRO" in env.config.data["devices"]
    prefs = json.loads(env.get_preferences())
    assert prefs["osd_profile"] is False and prefs["battery_threshold"] == 25


def test_import_applies_to_online_hardware(env):
    doc = {"openmacros_export": 1, "devices": {M720: {"assignments": {"82": KEYS_A}, "settings": {}}}}
    env.import_config(json.dumps(doc), True)
    assert env.dev.reporting[82] == (True, False, 0)  # desviado no "firmware"


GOOD = {"type": "keys", "keys": ["KEY_A"]}


@pytest.mark.parametrize("doc,fragment", [
    ("não é json", "JSON"),
    ("[]", "exportação"),
    ({"devices": {}}, "exportação"),
    ({"openmacros_export": 2}, "versão"),
    ({"openmacros_export": True}, "versão"),
    ({"openmacros_export": 1, "devices": []}, "devices"),
    ({"openmacros_export": 1, "devices": {"id com espaço": {}}}, "id de dispositivo"),
    ({"openmacros_export": 1, "devices": {M720: {"assignments": {"x": GOOD}}}}, "CID"),
    ({"openmacros_export": 1, "devices": {M720: {"assignments": {"82": {"type": "keys", "keys": ["KEY_NOPE"]}}}}}, "inválida"),
    ({"openmacros_export": 1, "devices": {M720: {"assignments": {"82": {"type": "magia"}}}}}, "inválida"),
    ({"openmacros_export": 1, "devices": {M720: {"settings": {"pointer_speed": "rápido"}}}}, "pointer_speed"),
    ({"openmacros_export": 1, "devices": {M720: {"settings": {"bogus": 1}}}}, "desconhecida"),
    ({"openmacros_export": 1, "devices": {M720: {"profiles": {"ff": {"assignments": {"82": {"type": "remap", "cid": 83}}}}}}}, "remap"),
    ({"openmacros_export": 1, "devices": {M720: {"profiles": {"ff": {"settings": {"dpi": 800}}}}}}, "dpi"),
    ({"openmacros_export": 1, "devices": {M720: {"assignments": {"82": {"type": "smart_action", "id": "sa_nada"}}}}}, "inexistente"),
    ({"openmacros_export": 1, "smart_actions": {"sa_1": {"name": "x", "steps": []}}}, "Smart Action"),
    ({"openmacros_export": 1, "smart_actions": {"sa_1": {"name": "x", "steps": [{"type": "smart_action", "id": "sa_2"}]}}}, "Smart Action"),
    ({"openmacros_export": 1, "smart_actions": {"id inválido!": {"name": "x", "steps": [GOOD]}}}, "id de Smart"),
    ({"openmacros_export": 1, "preferences": {"battery_threshold": 99}}, "battery_threshold"),
    ({"openmacros_export": 1, "preferences": {"nada": 1}}, "desconhecida"),
])
def test_import_rejects_invalid_and_changes_nothing(env, doc, fragment):
    populate(env)
    before = json.loads(env.export_config())
    text = doc if isinstance(doc, str) else json.dumps(doc)
    with pytest.raises(mg.InvalidArgument) as e:
        env.import_config(text, False)
    assert fragment in str(e.value)
    after = json.loads(env.export_config())
    before.pop("exported_at"), after.pop("exported_at")
    assert before == after


def test_import_size_limit_is_512kib(env):
    big = json.dumps({"openmacros_export": 1, "pad": "x" * (backup.MAX_IMPORT_BYTES + 10)})
    with pytest.raises(mg.InvalidArgument):
        env.import_config(big, True)
    mid = json.dumps({"openmacros_export": 1, "pad": "x" * (100 * 1024)})  # > 64 KiB mas < 512 KiB: aceito
    assert env.import_config(mid, True)


def test_import_merge_keeps_unknown_devices_and_command_without_path_check(env):
    doc = {"openmacros_export": 1, "devices": {M720: {"assignments": {
        "82": {"type": "command", "argv": ["/opt/inexistente/prog"]}}}}}
    assert env.import_config(json.dumps(doc), True)  # executável é checado ao executar, não ao importar


def test_authorization_lists_new_write_methods():
    from openmacros.daemon.dbus_service import WRITE_METHODS
    assert {"ImportConfig", "SetPreference"} <= WRITE_METHODS
    assert not {"ExportConfig", "GetPreferences"} & WRITE_METHODS


# ------------------------------------------------------------------ Selection (ferramentas falsas)
def _fake_tools(tmp_path, names):
    store = tmp_path / "clip.txt"
    store.write_text("antigo")
    paths = {}
    for n in names:
        f = tmp_path / n
        # -i/-bi/(wl-copy sem args) gravam stdin; -o/-bo/wl-paste imprimem o conteúdo
        f.write_text(f'#!/bin/sh\ncase "$*" in *TARGETS*) printf "TARGETS\\nUTF8_STRING\\n";;'
                     f' *"-o"*|*"-bo"*|*"--no-newline"*) cat "{store}";;'
                     f' *) cat > "{store}";; esac\n')
        f.chmod(0o755)
        paths[n] = str(f)
    return store, paths


def test_selection_x11_roundtrip_with_xclip(tmp_path):
    from openmacros.daemon.integrations import Selection
    store, paths = _fake_tools(tmp_path, ["xclip"])
    sel = Selection(which=paths.get, wayland=lambda: False)
    assert sel.read_clipboard() == "antigo"
    assert sel.write_clipboard("olá ação ü") is True
    assert store.read_text(encoding="utf-8") == "olá ação ü"


def test_selection_falls_back_to_xsel_and_wl_copy(tmp_path):
    from openmacros.daemon.integrations import Selection
    store, paths = _fake_tools(tmp_path, ["xsel"])
    sel = Selection(which=paths.get, wayland=lambda: False)
    assert sel.write_clipboard("via xsel") and store.read_text() == "via xsel"
    assert sel.read_clipboard() == "via xsel"
    (tmp_path / "w").mkdir()
    store, paths = _fake_tools(tmp_path / "w", ["wl-copy", "xclip"])
    wl = Selection(which=paths.get, wayland=lambda: True)
    assert wl.write_clipboard("via wl") and store.read_text() == "via wl"


def test_selection_without_tools_fails_cleanly():
    from openmacros.daemon.integrations import Selection
    sel = Selection(which=lambda n: None, wayland=lambda: False)
    assert sel.write_clipboard("x") is False and sel.read_clipboard() is None and sel.read_primary() == ""


def test_labels():
    from openmacros.daemon import labels
    assert labels.keys_label(["KEY_LEFTCTRL", "KEY_C"]) == "Copiar"
    assert labels.keys_label(["KEY_LEFTCTRL", "KEY_LEFTALT", "KEY_DELETE"]) == "Ctrl+Alt+Del"
    assert labels.trigger_label({"type": "window", "op": "close"}, "left") == "Gesto ← — Fechar janela"
    assert labels.trigger_label({"type": "default"}, "click") == ""
