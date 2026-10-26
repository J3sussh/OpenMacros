import json

from clique.daemon.config import Config


def test_roundtrip_and_atomic(tmp_path):
    p = tmp_path / "sub" / "config.json"
    c = Config(p)
    c.set_assignment("logi:A", 82, {"type": "disabled"})
    c.set_setting("logi:A", "pointer_speed", 300)
    assert json.loads(p.read_text())["version"] == 1
    assert not [f for f in p.parent.iterdir() if f.name != "config.json"]
    c2 = Config(p)
    assert c2.device("logi:A") == {"assignments": {"82": {"type": "disabled"}},
                                   "settings": {"pointer_speed": 300}, "profiles": {}, "baseline": {}}


def test_clear_device(tmp_path):
    c = Config(tmp_path / "c.json")
    c.set_assignment("x", 1, {"type": "default"})
    c.clear_device("x")
    assert Config(tmp_path / "c.json").device("x") == {"assignments": {}, "settings": {}, "profiles": {},
                                                       "baseline": {}}


def test_corrupt_file_backed_up(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{nope")
    c = Config(p)
    assert c.data["devices"] == {}
    assert len(list(tmp_path.glob("c.json.bak*"))) == 1


def test_in_memory():
    c = Config(None)
    c.set_setting("x", "dpi", 800)
    assert c.device("x")["settings"]["dpi"] == 800


def test_existing_backup_not_overwritten(tmp_path):
    (tmp_path / "c.json.bak").write_text("antigo")
    for _ in range(2):
        (tmp_path / "c.json").write_text("{nope")
        Config(tmp_path / "c.json")
    assert (tmp_path / "c.json.bak").read_text() == "antigo"
    assert len(list(tmp_path.glob("c.json.bak-*"))) == 2


def test_invalid_entries_discarded(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"version": 1, "devices": {
        "ok": {"assignments": {"82": {"type": "disabled"}, "x": {"type": "disabled"}, "83": 5},
               "settings": {"dpi": 800}},
        "bad1": [], "bad2": {"assignments": [], "settings": {}}}}))
    c = Config(p)
    assert set(c.data["devices"]) == {"ok"}
    assert c.device("ok")["assignments"] == {"82": {"type": "disabled"}}


def test_default_path_ignores_relative_xdg(monkeypatch, tmp_path):
    from clique.daemon.config import default_path
    monkeypatch.setenv("XDG_CONFIG_HOME", "relativo/dir")
    assert default_path().is_absolute() and "relativo" not in str(default_path())
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_path() == tmp_path / "clique" / "config.json"


def test_profiles_and_smart_actions_roundtrip(tmp_path):
    p = tmp_path / "c.json"
    c = Config(p)
    c.set_profile_assignment("d", "firefox", 83, {"type": "disabled"})
    c.set_profile_setting("d", "firefox", "scroll_invert", {"value": True})
    c.set_baseline("d", "scroll_invert", False)
    c.put_smart_action("sa_1", {"name": "x", "icon": "", "steps": [{"type": "volume", "op": "up"}]})
    c2 = Config(p)
    d = c2.device("d")
    assert d["profiles"]["firefox"] == {"assignments": {"83": {"type": "disabled"}},
                                        "settings": {"scroll_invert": {"value": True}}}
    assert d["baseline"] == {"scroll_invert": False} and "sa_1" in c2.smart_actions
    assert c2.remove_profile("d", "firefox") and not c2.remove_profile("d", "firefox")
    assert c2.delete_smart_action("sa_1") and not c2.delete_smart_action("sa_1")


def test_profile_and_smart_validation_on_load(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"version": 1, "devices": {
        "d": {"assignments": {}, "settings": {}, "baseline": [1],
              "profiles": {"ok": {"assignments": {"83": {"type": "disabled"}, "x": {"type": "disabled"}, "84": 3},
                                  "settings": {"a": {"value": 1}, "b": 5}},
                           "bad": [], "bad2": {"assignments": [], "settings": {}}}},
        "e": {"assignments": {}, "settings": {}, "profiles": "lixo"}},
        "smart_actions": {"sa_ok": {"name": "n", "steps": [{"type": "volume", "op": "up"}]},
                          "sa_bad": {"name": 1, "steps": []}, "sa_bad2": [], "sa_bad3": {"name": "n", "steps": [5]}}}))
    c = Config(p)
    assert set(c.device("d")["profiles"]) == {"ok"}
    assert c.device("d")["profiles"]["ok"] == {"assignments": {"83": {"type": "disabled"}},
                                                "settings": {"a": {"value": 1}}}
    assert c.device("d")["baseline"] == {} and c.device("e")["profiles"] == {}
    assert set(c.smart_actions) == {"sa_ok"}
    p.write_text(json.dumps({"version": 1, "devices": {}, "smart_actions": [1]}))
    assert Config(p).smart_actions == {}
