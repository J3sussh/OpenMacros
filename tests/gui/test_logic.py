import pytest

from openmacros.gui import logic


def test_accel_to_evdev():
    assert logic.accel_to_evdev("<Control>c") == ["KEY_LEFTCTRL", "KEY_C"]
    assert logic.accel_to_evdev("<Shift><Control><Alt>F5") == ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_LEFTALT", "KEY_F5"]
    assert logic.accel_to_evdev("<Super>Tab") == ["KEY_LEFTMETA", "KEY_TAB"]
    assert logic.accel_to_evdev("Page_Up") == ["KEY_PAGEUP"]
    assert logic.accel_to_evdev("<Primary>1") == ["KEY_LEFTCTRL", "KEY_1"]
    with pytest.raises(ValueError):
        logic.accel_to_evdev("<Bogus>x")
    with pytest.raises(ValueError):
        logic.accel_to_evdev("")


def test_keys_from_hardware():
    # keycode GTK = evdev + 8 ; C = 46
    assert logic.keys_from_hardware(46 + 8, True, False, False, False) == ["KEY_LEFTCTRL", "KEY_C"]
    assert logic.keys_from_hardware(29 + 8, True, False, False, False) is None  # só Ctrl
    assert logic.keys_from_hardware(59 + 8, False, True, False, False) == ["KEY_LEFTSHIFT", "KEY_F1"]


def test_build_and_classify_roundtrip():
    assert logic.build_action("preset", preset="copy") == {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}
    assert logic.classify_action({"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}) == ("preset", {"preset": "copy"})
    assert logic.classify_action({"type": "keys", "keys": ["KEY_A"]}) == ("keys", {"keys": ["KEY_A"]})
    assert logic.build_action("command", command="xdg-open 'https://a b'") == {
        "type": "command", "argv": ["xdg-open", "https://a b"]}
    assert logic.classify_action({"type": "command", "argv": ["a", "b c"]}) == ("command", {"command": "a 'b c'"})
    assert logic.build_action("change_host", host=1) == {"type": "change_host", "host": 1}
    assert logic.build_action("mouse_button", button="BTN_MIDDLE") == {"type": "mouse_button", "button": "BTN_MIDDLE"}
    for bad in (("keys", {"keys": []}), ("command", {"command": "  "}), ("mouse_button", {"button": "X"}),
                ("preset", {"preset": "nope"}), ("zzz", {})):
        with pytest.raises(ValueError):
            logic.build_action(bad[0], **bad[1])


def test_gestures():
    a = logic.build_action("gestures", slots={"up": {"type": "disabled"}}, threshold=70)
    assert a["type"] == "gestures" and a["threshold"] == 70
    assert a["up"] == {"type": "disabled"} and a["click"] == {"type": "default"}
    assert set(a) == {"type", "click", "up", "down", "left", "right", "threshold"}
    kind, p = logic.classify_action(a)
    assert kind == "gestures" and p["threshold"] == 70


def test_presets_cover_spec():
    assert len(logic.PRESETS) >= 17
    assert all(k.startswith("KEY_") for p in logic.PRESETS for k in p.keys)
    assert len({p.id for p in logic.PRESETS}) == len(logic.PRESETS)


def test_describe():
    assert logic.describe_action(None) == "Padrão"
    assert logic.describe_action({"type": "disabled"}) == "Desativado"
    assert logic.describe_action({"type": "keys", "keys": ["KEY_MUTE"]}) == "Mudo"
    assert logic.describe_action({"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_A"]}) == "Ctrl + A"
    assert logic.describe_action({"type": "change_host", "host": 1}) == "Computador 2"


def test_battery():
    assert logic.battery_icon({"level": 83, "status": "discharging"}) == "battery-level-80-symbolic"
    assert logic.battery_icon({"level": 50, "status": "charging"}) == "battery-level-50-charging-symbolic"
    assert logic.battery_icon(None) == "battery-missing-symbolic"
    assert logic.battery_text({"level": 80, "approximate": True}) == "~80%"


def test_layout_m720():
    lay = logic.load_layout("m720")
    assert lay is not None
    assert {m.cid for m in lay.markers} == {82, 83, 86, 91, 93, 208}
    assert all(0 <= m.x <= 1 and 0 <= m.y <= 1 for m in lay.markers)
    assert (logic.DATA_DIR / "art" / f"{lay.art}.svg").is_file()
    assert logic.load_layout("../etc") is None and logic.load_layout("nao-existe") is None


def test_parse_layout_invalid():
    with pytest.raises(ValueError):
        logic.parse_layout({"name": "x", "aspect": [1, 1], "markers": [{"cid": 1, "x": 2, "y": 0}]})
    with pytest.raises(ValueError):
        logic.parse_layout({"name": "x"})


def test_resolve_layout_and_tabs():
    dev = {"layout": "m720", "kind": "mouse", "controls": [
        {"cid": 80, "remappable": False, "divertable": False},
        {"cid": 82, "remappable": True}, {"cid": 83, "remappable": True}],
        "settings": {"hires_scroll": {"value": True}}, "hosts": {"count": 3, "current": 0}}
    lay, generic = logic.resolve_layout(dev)
    assert not generic and {m.cid for m in lay.markers} == {82, 83}
    assert logic.supported_tabs(dev) == ["buttons", "pointer", "easyswitch", "about"]
    dev2 = {"layout": "generic-mouse", "controls": [{"cid": c, "remappable": True} for c in (1, 2, 3)]}
    lay2, generic2 = logic.resolve_layout(dev2)
    assert generic2 and len(lay2.markers) == 3
    assert logic.supported_tabs({"controls": [], "settings": {}}) == ["about"]


def test_friendly_error():
    msg = "GDBus.Error:io.github.openmacros.Error.DeviceOffline: sem resposta"
    assert logic.friendly_error(msg) == "O dispositivo está offline: sem resposta"
    assert logic.friendly_error("outra coisa") == "outra coisa"


def test_action_sections_and_items():
    secs = dict(logic.action_sections(allow_gestures=True))
    assert list(secs) == ["Recomendadas", "Navegação", "Mídia", "Edição", "Sistema", "IA", "Smart Actions", "Avançado"]
    assert ("gestures", "Gestos") in secs["Recomendadas"]
    assert ("gestures", "Gestos") not in dict(logic.action_sections(False))["Recomendadas"]
    ids = [i for _, items in logic.action_sections(True) for i, _ in items]
    assert len(ids) == len(set(ids))
    native = {"play_pause", "next_track", "prev_track", "vol_up", "vol_down", "mute"}  # viraram media:/volume:
    assert {f"preset:{p.id}" for p in logic.PRESETS if p.id not in native} <= set(ids)
    assert {"media:play_pause", "volume:up", "window", "open", "type_text", "ai_prompt", "smart_new"} <= set(ids)
    assert logic.item_id_for_action({"type": "keys", "keys": ["KEY_MUTE"]}) == "preset:mute"
    assert logic.item_id_for_action({"type": "keys", "keys": ["KEY_A"]}) == "keys"
    assert logic.item_id_for_action(None) == "default"
    assert logic.action_for_simple_item("preset:copy")["keys"] == ["KEY_LEFTCTRL", "KEY_C"]
    assert logic.action_for_simple_item("keys") is None


def test_gesture_helpers():
    a = logic.set_gesture_slot(None, "up", {"type": "disabled"})
    assert a["up"] == {"type": "disabled"} and a["threshold"] == 50
    b = logic.set_gesture_slot(dict(a, threshold=80), "left", {"type": "default"})
    assert b["threshold"] == 80 and b["up"] == {"type": "disabled"}
    with pytest.raises(ValueError):
        logic.set_gesture_slot(None, "diagonal", {"type": "default"})
    for t in (10, 50, 200):
        assert logic.sensitivity_to_threshold(logic.threshold_to_sensitivity(t)) in (t - 1, t, t + 1)
    assert logic.threshold_to_sensitivity(10) == 100 and logic.threshold_to_sensitivity(200) == 0
    assert logic.speed_label(1, 1, 100) == "Lento" and logic.speed_label(100, 1, 100) == "Rápido"


def test_vendor_art_preferred(monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    d = tmp_path / "openmacros" / "vendor" / "405e"
    d.mkdir(parents=True)
    (d / "front.webp").write_bytes(b"x")
    (d / "side.webp").write_bytes(b"x")
    (d / "easy_switch_indicator_2.webp").write_bytes(b"x")
    (d / "layout.json").write_text(json.dumps({
        "version": 1, "name": "405e", "front": "front.webp",
        "buttons": {"art": "side.webp", "aspect": 0.64, "markers": [
            {"cid": 82, "x": 0.66, "y": 0.14, "side": "right"}, {"cid": 83, "x": 0.28, "y": 0.55, "side": "left"}]},
        "easy_switch": {"2": "easy_switch_indicator_2.webp", "3": "nao_existe.webp"}}))
    dev = {"model_id": "405e", "layout": "m720", "kind": "mouse",
           "controls": [{"cid": 82, "remappable": True}, {"cid": 83, "remappable": True}, {"cid": 99, "remappable": True}]}
    assert logic.art_path(dev) == d / "front.webp" and logic.has_vendor_art(dev)
    lay, generic = logic.resolve_layout(dev)
    assert not generic and lay.art_path == str(d / "side.webp") and abs(lay.aspect - 0.64) < 1e-9
    assert {m.cid for m in lay.markers} == {82, 83, 99}
    assert logic.layout_art_file(lay) == d / "side.webp"
    assert logic.easy_switch_images(dev) == {2: d / "easy_switch_indicator_2.webp"}
    other = dict(dev, model_id="ffff")
    assert not logic.has_vendor_art(other) and logic.art_path(other).suffix == ".svg"


# ---------------------------------------------------------------- integrações (INTEGRATIONS.md)

def test_new_action_types_roundtrip():
    cases = [
        ("media", {"op": "play_pause", "player": "Spotify"}, {"type": "media", "op": "play_pause", "player": "spotify"}),
        ("media", {"op": "next"}, {"type": "media", "op": "next"}),
        ("volume", {"op": "up", "step": 500}, {"type": "volume", "op": "up", "step": 100}),
        ("volume", {"op": "mute"}, {"type": "volume", "op": "mute"}),
        ("open", {"target": " https://a.b "}, {"type": "open", "target": "https://a.b"}),
        ("type_text", {"text": "nmap -sV"}, {"type": "type_text", "text": "nmap -sV"}),
        ("window", {"op": "close"}, {"type": "window", "op": "close"}),
        ("ai_prompt", {"service": "claude", "template": "Explique: {selection}"},
         {"type": "ai_prompt", "service": "claude", "template": "Explique: {selection}"}),
        ("smart_action", {"id": "sa_1"}, {"type": "smart_action", "id": "sa_1"}),
    ]
    for kind, params, expected in cases:
        assert logic.build_action(kind, **params) == expected
        k, p = logic.classify_action(expected)
        assert k == kind
        assert logic.build_action(k, **p) == expected


def test_new_action_validation():
    bad = [("media", {"op": "x"}), ("volume", {"op": "x"}), ("open", {"target": " "}), ("type_text", {"text": ""}),
           ("type_text", {"text": "a" * 2001}), ("window", {"op": "x"}),
           ("ai_prompt", {"service": "bing", "template": "x"}), ("ai_prompt", {"service": "claude", "template": " "}),
           ("smart_action", {"id": ""})]
    for kind, params in bad:
        with pytest.raises(ValueError):
            logic.build_action(kind, **params)


def test_describe_new_actions():
    sa = {"sa_1": {"name": "Modo foco"}}
    assert logic.describe_action({"type": "media", "op": "next"}) == "Próxima faixa"
    assert logic.describe_action({"type": "media", "op": "next", "player": "vlc"}) == "Próxima faixa (vlc)"
    assert logic.describe_action({"type": "volume", "op": "mute"}) == "Mudo"
    assert logic.describe_action({"type": "open", "target": "obsidian.desktop"}) == "Abrir: obsidian"
    assert logic.describe_action({"type": "ai_prompt", "service": "gemini", "template": "x"}) == "IA: Gemini"
    assert logic.describe_action({"type": "smart_action", "id": "sa_1"}, sa) == "Modo foco"
    assert logic.describe_action({"type": "smart_action", "id": "zz"}, sa) == "Smart Action"
    assert logic.describe_action({"type": "type_text", "text": "x" * 50}).endswith("…")


def test_items_for_new_actions():
    assert logic.item_id_for_action({"type": "media", "op": "stop"}) == "media:stop"
    assert logic.item_id_for_action({"type": "volume", "op": "down", "step": 5}) == "volume:down"
    assert logic.item_id_for_action({"type": "smart_action", "id": "sa_1"}) == "smart:sa_1"
    assert logic.item_id_for_action({"type": "window", "op": "close"}) == "window"
    assert logic.action_for_simple_item("media:next") == {"type": "media", "op": "next"}
    assert logic.action_for_simple_item("volume:up") == {"type": "volume", "op": "up", "step": 5}
    assert logic.action_for_simple_item("smart:sa_1") == {"type": "smart_action", "id": "sa_1"}
    assert logic.action_for_simple_item("open") is None and logic.action_for_simple_item("smart_new") is None
    secs = dict(logic.action_sections(False, {"b": {"name": "Zeta"}, "a": {"name": "alfa"}}))
    assert [i for i, _ in secs["Smart Actions"]] == ["smart:a", "smart:b", "smart_new"]
    steps = [i for _, items in logic.action_sections(False, {"a": {"name": "x"}}, steps=True) for i, _ in items]
    assert "default" not in steps and "disabled" not in steps and not any(i.startswith("smart") for i in steps)


def test_catalog():
    cat = logic.load_catalog()
    assert {"firefox", "code", "xfce4-terminal", "burp-startburp", "spotify", "obsidian"} <= set(cat["apps"])
    for app_id, entry in cat["apps"].items():
        if entry.get("suggestions"):
            assert entry["suggestions"] in cat["suggestion_sets"], app_id
    for name, sset in cat["suggestion_sets"].items():
        for cid, action in sset["assignments"].items():
            assert cid.isdigit()
            kind, p = logic.classify_action(action)
            assert kind != "default" or action.get("type") == "default", (name, cid)
            logic.build_action(kind, **p) if kind not in ("preset", "keys") else None
    assert logic.resolve_app_id("Navigator") == "firefox"
    assert logic.resolve_app_id("Desconhecido") == "desconhecido"
    assert logic.catalog_entry("firefox")["name"] == "Firefox"


def test_suggestions_for():
    controls = [{"cid": 91, "remappable": True}, {"cid": 93, "remappable": True},
                {"cid": 208, "remappable": True, "raw_xy": True}, {"cid": 80, "remappable": True}]
    sug = logic.suggestions_for("firefox", controls)
    assert sug["91"]["keys"] == ["KEY_LEFTCTRL", "KEY_PAGEUP"]
    assert sug["208"]["type"] == "gestures" and sug["208"]["up"]["keys"] == ["KEY_LEFTCTRL", "KEY_T"]
    assert set(sug["208"]) == {"type", "click", "up", "down", "left", "right", "threshold"}
    assert set(logic.suggestions_for("firefox", [{"cid": 91, "remappable": True}])) == {"91"}
    assert logic.suggestions_for("desconhecido", controls) == {}
    assert logic.suggestions_for("libreoffice-writer", controls) == {}
    assert logic.suggestions_for("spotify", controls)["93"] == {"type": "media", "op": "next", "player": "spotify"}


def test_app_ids_for_desktop():
    ids = logic.app_ids_for_desktop("firefox-esr.desktop", "Navigator")
    assert ids[0] == "navigator" and "firefox-esr" in ids
    assert "wireshark" in logic.app_ids_for_desktop("org.wireshark.Wireshark.desktop", None)
    assert logic.app_ids_for_desktop("org.gnome.Terminal.desktop")[0] == "org.gnome.terminal"


DEV = {"id": "d", "assignments": {"82": {"type": "disabled"}, "83": {"type": "keys", "keys": ["KEY_A"]}},
       "settings": {"scroll_invert": {"value": False}, "pointer_speed": {"value": 100, "min": 1, "max": 500}},
       "profiles": {"firefox": {"assignments": {"83": {"type": "keys", "keys": ["KEY_B"]}},
                                "settings": {"scroll_invert": {"value": True}}}},
       "active_profile": ""}


def test_effective_values():
    assert logic.effective_action(DEV, "firefox", 83) == ({"type": "keys", "keys": ["KEY_B"]}, "app")
    assert logic.effective_action(DEV, "firefox", 82) == ({"type": "disabled"}, "global")
    assert logic.effective_action(DEV, "", 83)[1] == "global"
    assert logic.effective_action(DEV, "nada", 83)[1] == "global"
    assert logic.effective_setting(DEV, "firefox", "scroll_invert") == ({"value": True}, True)
    assert logic.effective_setting(DEV, "firefox", "pointer_speed")[1] is False
    assert logic.effective_setting(DEV, "", "scroll_invert") == ({"value": False}, False)
    assert logic.profile_app_ids(DEV) == ["firefox"] and logic.supports_profiles(DEV)
    assert not logic.supports_profiles({"id": "x"})


def test_optimistic_profile_updates():
    import copy
    d = copy.deepcopy(DEV)
    logic.with_profile_assignment(d, "code", 83, {"type": "disabled"})
    assert d["profiles"]["code"]["assignments"]["83"] == {"type": "disabled"}
    logic.with_profile_assignment(d, "code", 83, None)
    assert "83" not in d["profiles"]["code"]["assignments"]
    logic.with_profile_assignment(d, "", 82, {"type": "default"})
    assert d["assignments"]["82"] == {"type": "default"}
    logic.with_profile_setting(d, "firefox", "scroll_invert", None)
    assert "scroll_invert" not in d["profiles"]["firefox"]["settings"]


def test_profile_indicator():
    name = str.title
    assert logic.profile_indicator(dict(DEV, active_profile="firefox"), {"app_id": "firefox"}, name) == "Perfil ativo: Firefox"
    assert "em foco: Code" in logic.profile_indicator(DEV, {"app_id": "code"}, name)
    assert logic.profile_indicator(DEV, None, name) == "Perfil ativo: Todos os aplicativos"
    assert logic.profile_indicator({"id": "x"}, {"app_id": "code"}, name) == ""


def test_filter_apps():
    from types import SimpleNamespace as NS
    apps = [NS(name="Visualizador de Imagens", app_id="eog"), NS(name="Firefox", app_id="firefox"), NS(name="Terminal", app_id="xfce4-terminal")]
    assert [a.app_id for a in logic.filter_apps(apps, "")] == ["eog", "firefox", "xfce4-terminal"]
    assert [a.app_id for a in logic.filter_apps(apps, "FIRE")] == ["firefox"]
    assert [a.app_id for a in logic.filter_apps(apps, "xfce")] == ["xfce4-terminal"]
    assert [a.app_id for a in logic.filter_apps(apps, "visualizacao")] == []
    assert [a.app_id for a in logic.filter_apps(apps, "visualizador")] == ["eog"]


def test_smart_action_validation():
    ok = logic.validate_smart_action({"name": " Foco ", "icon": "nao-existe", "steps": [
        {"type": "open", "target": "obsidian.desktop"}, {"type": "delay", "ms": 500},
        {"type": "keys", "keys": ["KEY_LEFTCTRL", "KEY_C"]}, {"type": "media", "op": "play_pause"}]})
    assert ok["name"] == "Foco" and ok["icon"] == logic.SA_DEFAULT_ICON and len(ok["steps"]) == 4
    assert logic.validate_smart_action({"id": "sa_1", "name": "x", "steps": [{"type": "delay", "ms": 10}]})["id"] == "sa_1"
    bad = [{"name": "", "steps": [{"type": "delay", "ms": 100}]}, {"name": "x", "steps": []},
           {"name": "x", "steps": [{"type": "delay", "ms": 5}]}, {"name": "x", "steps": [{"type": "delay", "ms": 20000}]},
           {"name": "x", "steps": [{"type": "smart_action", "id": "a"}]},
           {"name": "x", "steps": [{"type": "gestures"}]},
           {"name": "x", "steps": [{"type": "bogus"}]},
           {"name": "x", "steps": [{"type": "delay", "ms": 100}] * 33}]
    for sa in bad:
        with pytest.raises(ValueError):
            logic.validate_smart_action(sa)


def test_smart_templates_and_moves():
    assert len(logic.SMART_TEMPLATES) == 10 and "pentest" in {t["id"] for t in logic.SMART_TEMPLATES}
    for t in logic.SMART_TEMPLATES:
        sa = logic.smart_from_template(t["id"])
        logic.validate_smart_action(sa)
        sa["steps"].append({"type": "delay", "ms": 100})  # cópia editável: não altera o modelo
        assert len(logic.smart_from_template(t["id"])["steps"]) == len(t["steps"])
    assert sum(1 for s in logic.smart_from_template("pentest")["steps"] if s["type"] == "open") == 2
    with pytest.raises(ValueError):
        logic.smart_from_template("nao-existe")
    assert logic.move_step([1, 2, 3], 0, 2) == [2, 3, 1]
    assert logic.move_step([1, 2, 3], 2, 0) == [3, 1, 2]
    assert logic.move_step([1, 2, 3], 5, 0) == [1, 2, 3]
    assert logic.step_summary({"type": "delay", "ms": 300}) == "Aguardar 300 ms"
