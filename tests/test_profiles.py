from clique.daemon import profiles as p

KEYS_A = {"type": "keys", "keys": ["KEY_A"]}
KEYS_B = {"type": "keys", "keys": ["KEY_B"]}
GEST = {"type": "gestures", "click": {"type": "default"}, "up": {"type": "disabled"}, "down": {"type": "disabled"},
        "left": {"type": "disabled"}, "right": {"type": "disabled"}, "threshold": 50}

CFG = {
    "assignments": {"82": KEYS_A, "83": {"type": "remap", "cid": 82}},
    "settings": {"pointer_speed": 300},
    "baseline": {},
    "profiles": {
        "firefox": {"assignments": {"82": KEYS_B, "86": KEYS_A, "91": {"type": "default"}, "83": {"type": "remap", "cid": 86}},
                    "settings": {"scroll_invert": {"value": True}, "pointer_speed": {"value": 100}}},
        "code": {"assignments": {"208": GEST}, "settings": {}},
    },
}


def test_resolution_app_then_global_then_default():
    assert p.effective_action(CFG, "firefox", 82) == KEYS_B          # app vence
    assert p.effective_action(CFG, "firefox", 86) == KEYS_A          # só no app
    assert p.effective_action(CFG, "code", 82) == KEYS_A             # herda global
    assert p.effective_action(CFG, "", 82) == KEYS_A
    assert p.effective_action(CFG, "code", 93) == {"type": "default"}  # nada definido
    assert p.effective_action(CFG, "desconhecido", 82) == KEYS_A


def test_default_explicit_in_app_overrides_global():
    cfg = {"assignments": {"91": KEYS_A}, "settings": {}, "profiles": {"x": {"assignments": {"91": {"type": "default"}},
                                                                            "settings": {}}}}
    assert p.effective_action(cfg, "x", 91) == {"type": "default"}
    assert p.effective_action(cfg, "", 91) == KEYS_A


def test_remap_in_app_profile_is_ignored():
    # global remap em CID desviado vira re-emissão do botão de destino; remap no perfil de app é ignorado
    assert p.effective_action(CFG, "firefox", 83) == {"type": "default", "cid": 82}
    assert p.effective_action(CFG, "firefox", 83, diverted=False) == {"type": "remap", "cid": 82}


def test_diverted_union_over_all_profiles():
    assert p.diverted_cids(CFG) == {82, 86, 208}  # 91 default e 83 remap não desviam
    assert p.diverted_cids({"assignments": {}, "profiles": {}}) == set()


def test_effective_assignments_only_diverted():
    eff = p.effective_assignments(CFG, "code")
    assert eff == {82: KEYS_A, 86: {"type": "default"}, 208: GEST}
    eff = p.effective_assignments(CFG, "firefox")
    assert eff[82] == KEYS_B and eff[86] == KEYS_A and eff[208] == {"type": "default"}


def test_hardware_plan():
    plan = p.hardware_plan(CFG)
    assert plan[82] == {"type": "disabled"}      # desviado por algum perfil
    assert plan[208] == {"type": "gestures"}     # gestos pedem rawXY
    assert plan[91] == {"type": "default"}
    assert plan[83] == {"type": "remap", "cid": 82}  # remap global no firmware (nenhum perfil desvia o 83)
    # se um perfil desvia um CID com remap global, o divert vence
    cfg = {"assignments": {"83": {"type": "remap", "cid": 82}}, "profiles": {"x": {"assignments": {"83": KEYS_A}}}}
    assert p.hardware_plan(cfg)[83] == {"type": "disabled"}


def test_settings_overlay_and_baseline():
    assert p.settings_targets(CFG, "firefox") == {"pointer_speed": 100, "scroll_invert": True}
    # fora do perfil: global onde existe; sem global nem baseline, a chave não é tocada
    assert p.settings_targets(CFG, "code") == {"pointer_speed": 300}
    assert p.keys_needing_baseline(CFG, "firefox") == {"scroll_invert"}
    cfg = dict(CFG, baseline={"scroll_invert": False})
    assert p.settings_targets(cfg, "code") == {"pointer_speed": 300, "scroll_invert": False}
    assert p.keys_needing_baseline(cfg, "firefox") == set()


def test_smartshift_wrapping_roundtrip():
    raw = {"enabled": True, "threshold": 30}
    assert p.unwrap_setting("smartshift", p.wrap_setting("smartshift", raw)) == raw
    assert p.unwrap_setting("dpi", p.wrap_setting("dpi", 800)) == 800


def test_active_profile_and_strip():
    assert p.active_profile(CFG, "firefox") == "firefox"
    assert p.active_profile(CFG, "other") == "" and p.active_profile(CFG, "") == ""
    g = dict(GEST, up={"type": "smart_action", "id": "sa_1"}, click={"type": "smart_action", "id": "sa_2"})
    out = p.strip_smart_action(g, "sa_1")
    assert out["up"] == {"type": "default"} and out["click"]["id"] == "sa_2"
    assert p.strip_smart_action({"type": "smart_action", "id": "sa_1"}, "sa_1") == {"type": "default"}
