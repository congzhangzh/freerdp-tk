import json

import pytest

from freerdp_tk import app, i18n
from freerdp_tk.app import build_args


def test_minimal():
    assert build_args({"host": " pc.example.com "}, "")[:2] == ["/v:pc.example.com", "/cert:tofu"]


def test_password_and_options():
    args = build_args({"host": "h", "user": "alice", "domain": "LAB", "gfx": "AV1:i444",
                       "fullscreen": True, "clipboard": False}, "pw")
    assert {"/u:alice", "/d:LAB", "/p:pw", "/gfx:AV1:i444", "/f", "-clipboard"} <= set(args)
    assert not any(a.startswith("/size:") for a in args)  # full screen wins over a size


def test_extra_arguments_are_split_like_a_shell():
    assert build_args({"host": "h", "extra": "/scale:140 '/t:a b' /t:\"c d\""}, "")[-3:] == [
        "/scale:140", "/t:a b", "/t:c d"]


def test_backslashes_in_extra_arguments(monkeypatch):
    monkeypatch.setattr(app, "IS_WIN", True)  # a path separator there, not an escape
    assert app.split_extra(r'/drive:s,C:\share "/t:a b"') == [r"/drive:s,C:\share", "/t:a b"]
    monkeypatch.setattr(app, "IS_WIN", False)
    assert app.split_extra(r"/t:a\ b") == ["/t:a b"]
    assert app.split_extra("/t:#1 /scale:140") == ["/t:#1", "/scale:140"]


def test_drive_is_named_after_the_folder():
    assert "/drive:share,/srv/share" in build_args({"host": "h", "drive": "/srv/share"}, "")


def test_monitor_list_is_parsed():
    output = ("listing 3 monitors:\n"
              "     * [1] [Built-in Retina Display] 1512x982\t+0+0\n"
              "       [4] [DELL U2720Q] 2560x1440\t+-2560+0\n"
              "       [5] [] 1920x1080\t+1512+-200\n")
    assert app.parse_monitors(output) == [
        {"id": "1", "name": "Built-in Retina Display", "size": "1512x982", "at": "+0+0",
         "primary": True},
        {"id": "4", "name": "DELL U2720Q", "size": "2560x1440", "at": "+-2560+0",
         "primary": False},
        {"id": "5", "name": "", "size": "1920x1080", "at": "+1512+-200", "primary": False}]
    assert app.parse_monitors("listing 0 monitors:\n") == []


def test_chosen_monitors():
    args = build_args({"host": "h", "monitors": " 2, 3"}, "")
    assert "/multimon" in args and "/monitors:2,3" in args  # the client needs one or the other
    args = build_args({"host": "h", "monitors": "2", "fullscreen": True}, "")
    assert "/f" in args and "/monitors:2" in args and "/multimon" not in args
    args = build_args({"host": "h", "monitors": "2", "multimon": True}, "")
    assert args.count("/multimon") == 1
    assert not any(a.startswith(("/monitors", "/multimon")) for a in build_args({"host": "h"}, ""))


@pytest.mark.parametrize("gfx", ["AV2:i444", "AV2:i420"])
def test_av2_is_offered_and_passed_as_is(gfx):
    """The kit's clients take /gfx:AV2:i444 and /gfx:AV2:i420, as for AV1."""
    assert gfx in app.GFX_CHOICES
    assert f"/gfx:{gfx}" in build_args({"host": "h", "gfx": gfx}, "")


def test_live_stats_pass_sdl_info():
    """Show live stats: the SDL3 client's overlay from the start (+sdl-info); off by default."""
    assert app.FIELDS["stats"] is False
    assert "+sdl-info" not in build_args({"host": "h"}, "")
    args = build_args({"host": "h", "stats": True}, "")
    assert args.count("+sdl-info") == 1


@pytest.fixture
def prefs(home):
    """Write the client's settings file (None: none there); stats_keys() reads it."""
    def write(content):
        path = app.client_prefs_file()
        if content is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content if isinstance(content, str) else json.dumps(content))
        return app.stats_keys()
    return write


def test_the_stats_keys_are_the_ones_the_client_reads(prefs, monkeypatch):
    """Not a fixed text: the user's own settings file may keep Right Shift alone, or
    name other keys; what it leaves out is the client's default."""
    monkeypatch.setattr(app, "IS_MAC", False)  # the PC's key names; the Mac's below
    assert prefs(None) == "Right Shift + I"  # no file: the client's defaults
    assert prefs({"SDL_Info": "SDL_SCANCODE_S"}) == "Right Shift + S"
    app.client_prefs_file().unlink()
    app.move_client_hotkeys()  # what freerdp-tk writes when there is none
    assert app.stats_keys() == "Right Alt + Right Shift + I"
    monkeypatch.setattr(app, "IS_MAC", True)
    assert app.stats_keys() == "Right Option + Right Shift + I"
    monkeypatch.setattr(app, "IS_MAC", False)
    assert prefs({"SDL_KeyModMask": ["KMOD_LCTRL", "SDL_KMOD_LALT"],
                  "SDL_Info": "SDL_SCANCODE_F9"}) == "Left Ctrl + Left Alt + F9"
    assert prefs({"SDL_KeyModMask": ["KMOD_RSHIFT"], "SDL_Info": "nonsense"}) == \
        "Right Shift + I"  # the client falls back to I


@pytest.mark.parametrize("content", ["{ not json", "[]", {"SDL_KeyModMask": ["KMOD_BOGUS"]},
                                     {"SDL_KeyModMask": []}, {"SDL_KeyModMask": ["KMOD_NUM"]}])
def test_no_stats_keys_when_they_cannot_be_told(prefs, content):
    """Nothing rather than keys that may be wrong: a file the client cannot read the
    same way, or a modifier it refuses (it then turns its hotkeys off)."""
    assert prefs(content) is None


def test_the_stats_keys_in_french(prefs, monkeypatch):
    """On French keyboards Right Alt is labelled Alt Gr (a PC's; a Mac's says Option)."""
    monkeypatch.setattr(app, "IS_MAC", False)
    try:
        i18n.use("fr")
        app.move_client_hotkeys()
        assert app.stats_keys() == "Alt Gr + Maj droite + I"
    finally:
        i18n.use("en")


def test_has_stats_asks_the_client_help(fake_client, monkeypatch):
    client = app.find_clients()[0]
    assert app.has_stats(client) is True
    monkeypatch.setenv("FAKE_NO_STATS", "1")
    assert app.has_stats(client) is False
    assert app.has_stats(client + "-not-there") is None


def test_several_monitors_as_separate_screens_by_default():
    """/multimon sends the layout: the remote desktop gets each monitor as its own."""
    args = build_args({"host": "h", "multimon": True}, "")
    assert "/multimon" in args and "/span" not in args


@pytest.mark.parametrize("v", [{"multimon": True}, {"monitors": "1,2"}])
def test_several_monitors_as_one_big_screen(v):
    """/span sends no layout: the remote desktop gets one monitor over all of them."""
    args = build_args({"host": "h", "multimon_mode": app.ONE_BIG, **v}, "")
    assert args.index("/span") == args.index("/multimon") + 1


def test_one_big_screen_means_nothing_on_one_monitor():
    assert "/span" not in build_args({"host": "h", "multimon_mode": app.ONE_BIG}, "")


NVIDIA = "0 D3D11VA NVIDIA GeForce RTX 5070 Laptop GPU (AV1 4:2:0 decode)"
AMD = "1 D3D11VA AMD Radeon(TM) 610M (AV1 4:2:0 decode)"


def test_video_decoding_passes_codec_first():
    """Hardware first on any GPU is the client's default: nothing is passed, so a client
    from before /codec-first still connects. A GPU passes its /codec-list id; Software
    first passes software, whatever the GPU says."""
    assert app.FIELDS["decoding"] == app.HARDWARE_FIRST and app.FIELDS["gpu"] == app.ANY_GPU
    assert not any(a.startswith("/codec-first") for a in build_args({"host": "h"}, ""))
    assert "/codec-first:hardware:1" in build_args({"host": "h", "gpu": AMD}, "")
    args = build_args({"host": "h", "decoding": app.SOFTWARE_FIRST, "gpu": AMD}, "")
    assert [a for a in args if a.startswith("/codec-first")] == ["/codec-first:software"]


def test_the_decoders_come_from_codec_list(fake_client, monkeypatch):
    client = app.find_clients()[0]
    assert app.list_decoders(client) == []  # it says: no hardware video decoder
    monkeypatch.setenv("FAKE_DECODERS", f"{NVIDIA}\n{AMD}")
    assert app.list_decoders(client) == [NVIDIA, AMD]
    monkeypatch.setenv("FAKE_NO_CODEC_FIRST", "1")
    assert app.list_decoders(client) is None
    assert app.list_decoders(client + "-not-there") is None


@pytest.mark.parametrize("line, decoder", [
    ("[12:00:00:000] [1:2] [INFO][com.freerdp.codec.av1] - [av1_init]: AV1 decoder: D3D11VA 1 "
     "AMD Radeon(TM) 610M (hardware), dav1d as fallback",
     (True, "AMD Radeon(TM) 610M (D3D11VA 1)")),
    ("AV1 decoder: D3D11VA 0 NVIDIA GeForce RTX 5070 Laptop GPU (hardware), dav1d as fallback",
     (True, "NVIDIA GeForce RTX 5070 Laptop GPU (D3D11VA 0)")),
    ("AV1 decoder: dav1d (software; /codec-first:software)", (False, "dav1d")),
    ("AV1 decoder: dav1d (software, no GPU with a D3D11VA AV1 decoder)", (False, "dav1d")),
    ("AV1 decoder: dav1d (software; no device of /codec-first, /codec-list lists them)",
     (False, "dav1d")),
    ("AV1 decoder: VideoToolbox (hardware), software as fallback", (True, "VideoToolbox")),
    ("AV1 decoder: software (/codec-first:software)", (False, "software")),
    ("[INFO][fake] - connected", None),
])
def test_the_decoder_a_log_line_names(line, decoder):
    """The client's own words (FreeRDP libfreerdp/codec/av1.c) on the AV1 decoder it runs."""
    assert app.decoder_of(line) == decoder
