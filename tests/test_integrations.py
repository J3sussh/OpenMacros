from openmacros.daemon import integrations as i


def test_pick_player():
    names = ["org.mpris.MediaPlayer2.vlc", "org.mpris.MediaPlayer2.spotify",
             "org.mpris.MediaPlayer2.firefox.instance123"]
    st = {names[0]: "Paused", names[1]: "Playing", names[2]: "Paused"}
    assert i.pick_player(names, st, "firefox") == names[2]          # pelo nome (ignora sufixo instance)
    assert i.pick_player(names, st, "SPOTIFY") == names[1]
    assert i.pick_player(names, st, "naoexiste") is None
    assert i.pick_player(names, st, None) == names[1]                # o que está tocando
    assert i.pick_player(names, {}, None) == names[0]                # senão o primeiro
    assert i.pick_player([], {}, None) is None


class FakeMpris(i.MprisController):
    def __init__(self, names, statuses):
        self.names, self.statuses, self.calls = names, statuses, []

    def list_names(self):
        return self.names

    def status(self, name):
        return self.statuses[name]

    def call(self, name, method):
        self.calls.append((name, method))


def test_mpris_run():
    n = ["org.mpris.MediaPlayer2.a", "org.mpris.MediaPlayer2.b"]
    c = FakeMpris(n, {n[0]: "Paused", n[1]: "Playing"})
    assert c.run("play_pause") and c.calls == [(n[1], "PlayPause")]
    assert c.run("next", "a") and c.calls[-1] == (n[0], "Next")
    assert not c.run("next", "zzz")                      # player pedido ausente -> fallback
    assert not FakeMpris([], {}).run("stop")             # sem players -> fallback


def test_mpris_errors_fall_back():
    class Broken(FakeMpris):
        def list_names(self):
            raise RuntimeError("sem barramento")
    assert not Broken([], {}).run("next")


def test_volume_commands_and_fallback():
    assert i.VolumeController.pactl_cmd("up", 5) == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"]
    assert i.VolumeController.pactl_cmd("down", 10)[-1] == "-10%"
    assert i.VolumeController.pactl_cmd("mute", 5) == ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]
    assert i.VolumeController.wpctl_cmd("up", 5) == ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"]
    assert i.VolumeController.wpctl_cmd("down", 5)[-1] == "5%-"
    ran = []
    v = i.VolumeController(runner=lambda argv: (ran.append(argv[0]), argv[0] == "wpctl")[1],
                           which=lambda t: "/usr/bin/" + t)
    assert v.run("up") and ran == ["pactl", "wpctl"]       # pactl falhou -> wpctl
    v = i.VolumeController(runner=lambda argv: False, which=lambda t: None)
    assert not v.run("up")


def test_text_to_keys():
    keys, skipped = i.text_to_keys("Aa1!\n")
    assert keys == [("KEY_A", True), ("KEY_A", False), ("KEY_1", False), ("KEY_1", True), ("KEY_ENTER", False)]
    assert skipped == 0
    keys, skipped = i.text_to_keys("é ok€")
    assert [k for k, _ in keys] == ["KEY_SPACE", "KEY_O", "KEY_K"] and skipped == 2
    assert i.text_to_keys("?")[0] == [("KEY_SLASH", True)]
    assert i.text_to_keys("_")[0] == [("KEY_MINUS", True)]


def test_all_mapped_keys_exist_in_evdev():
    from evdev import ecodes
    import string
    text = string.ascii_letters + string.digits + string.punctuation + " \n\t"
    keys, skipped = i.text_to_keys(text)
    assert skipped == 0 and all(isinstance(ecodes.ecodes.get(k), int) for k, _ in keys)


def test_pick_window():
    stack = [10, 20, 30, 40]               # 40 = topo (ativo)
    assert i.pick_window(stack, 40, "next") == 10      # percorre por recência
    assert i.pick_window(stack, 40, "previous") == 30  # alterna com a anterior
    assert i.pick_window([10], 10, "next") is None
    assert i.pick_window(stack, 999, "previous") == 30  # ativa desconhecida -> trata como topo


class FakeEwmh:
    def __init__(self, stack, active):
        self.stack, self.active, self.msgs = stack, active, []

    def active_window(self):
        return self.active

    def client_list_stacking(self):
        return self.stack

    def is_normal(self, w):
        return w != 20  # 20 = dock

    def client_message(self, wid, atom, data):
        self.msgs.append((wid, atom, data))

    def atom_id(self, name):
        return {"_NET_WM_STATE_MAXIMIZED_VERT": 1, "_NET_WM_STATE_MAXIMIZED_HORZ": 2,
                "_NET_WM_STATE_FULLSCREEN": 3}[name]


def test_window_controller_ops():
    e = FakeEwmh([10, 20, 30], 30)
    w = i.WindowController(e)
    assert w.run("close") and e.msgs[-1] == (30, "_NET_CLOSE_WINDOW", [0, 2])
    assert w.run("minimize") and e.msgs[-1] == (30, "WM_CHANGE_STATE", [3])
    assert w.run("maximize") and e.msgs[-1] == (30, "_NET_WM_STATE", [2, 1, 2, 2])
    assert w.run("fullscreen") and e.msgs[-1] == (30, "_NET_WM_STATE", [2, 3, 0, 2])
    assert w.run("next") and e.msgs[-1] == (10, "_NET_ACTIVE_WINDOW", [2, 0, 0])   # dock 20 ignorado
    assert w.run("previous") and e.msgs[-1][0] == 10
    assert not w.run("bogus")


def test_window_controller_no_active_or_errors():
    assert not i.WindowController(FakeEwmh([], 0)).run("close")

    class Bad(FakeEwmh):
        def active_window(self):
            raise RuntimeError("X caiu")
    assert not i.WindowController(Bad([1, 2], 1)).run("close")


def test_ai_request_urls():
    url, clip = i.build_ai_request("claude", "Explique: {selection}", "a b&c", "url")
    assert url == "https://claude.ai/new?q=Explique%3A%20a%20b%26c" and clip is None
    assert i.build_ai_request("chatgpt", "{selection}", "x", "url")[0] == "https://chatgpt.com/?q=x"
    assert i.build_ai_request("perplexity", "{selection}", "x", "url")[0].startswith("https://www.perplexity.ai/search?q=")
    url, clip = i.build_ai_request("gemini", "Resuma: {selection}", "texto")
    assert url == "https://gemini.google.com/app" and clip == "Resuma: texto"
    url, _ = i.build_ai_request("claude", "{selection}", "x" * 50000, "url")
    assert len(url) < 7000
