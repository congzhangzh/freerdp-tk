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
         "primary": True, "scale": None, "density": None},
        {"id": "4", "name": "DELL U2720Q", "size": "2560x1440", "at": "+-2560+0",
         "primary": False, "scale": None, "density": None},
        {"id": "5", "name": "", "size": "1920x1080", "at": "+1512+-200", "primary": False,
         "scale": None, "density": None}]
    assert app.parse_monitors("listing 0 monitors:\n") == []


# Two monitors of different OS scale, as a newer client lists them (a trailing N %)
TWO_SCALES = ("listing 2 monitors:\n"
              "     * [1] [Built-in Retina Display] 1512x982\t+0+0\t200%\n"
              "       [2] [DELL U2720Q] 2560x1440\t+1512+0\t100%\n")


def test_the_monitor_list_gives_each_os_scale():
    monitors = app.parse_monitors(TWO_SCALES)
    assert [(m["id"], m["scale"]) for m in monitors] == [("1", 200), ("2", 100)]
    assert app.parse_monitors("  [3] [X] 1920x1080\t+0+0\t150.0 %")[0]["scale"] == 150


def test_following_the_os_passes_no_hidpi():
    """Following the OS is the client's default (points, each monitor at its own scale):
    nothing is passed, so a client from before /sdl-hidpi still connects."""
    assert app.FIELDS["hidpi"] == app.FOLLOW_OS and app.FIELDS["hidpi_monitors"] == ""
    assert not any(a.startswith("/sdl-hidpi") for a in build_args({"host": "h"}, ""))
    assert app.hidpi_args({**app.FIELDS, "hidpi_scale": "175"}) == []


@pytest.mark.parametrize("hidpi, scale, own, arg", [
    (app.PIXELS, "150", "", "/sdl-hidpi:pixels"),
    (app.SCALE, "175", "", "/sdl-hidpi:scale:175"),
    (app.SCALE, " 50 ", "", "/sdl-hidpi:scale:50"),
    (app.FOLLOW_OS, "150", "2:scale:150", "/sdl-hidpi:2:scale:150"),  # the default stays
    (app.PIXELS, "150", "1:points,2:scale:125", "/sdl-hidpi:pixels,1:points,2:scale:125"),
    # parts the client would not take are left out, not passed for it to stop on
    (app.FOLLOW_OS, "150", "2:scale:999,x:pixels,3:huge,,4:pixels", "/sdl-hidpi:4:pixels"),
])
def test_hidpi_passes_sdl_hidpi(hidpi, scale, own, arg):
    v = {"host": "h", "hidpi": hidpi, "hidpi_scale": scale, "hidpi_monitors": own}
    assert [a for a in build_args(v, "") if a.startswith("/sdl-hidpi")] == [arg]


def test_each_monitor_of_its_own_scale_gets_its_setting():
    """From the two monitors of a /list:monitor, the Retina one asks for every pixel and
    the other one follows the default: only the first is named."""
    monitors = app.parse_monitors(TWO_SCALES)
    own = {m["id"]: "pixels" for m in monitors if m["scale"] > 100}
    v = {"host": "h", "monitors": ",".join(m["id"] for m in monitors),
         "hidpi_monitors": ",".join(f"{i}:{s}" for i, s in own.items())}
    args = build_args(v, "")
    assert {"/multimon", "/monitors:1,2", "/sdl-hidpi:1:pixels"} <= set(args)


@pytest.mark.parametrize("scale, ok", [("50", True), ("400", True), ("150", True),
                                       ("49", False), ("401", False), ("1.5", False),
                                       ("", False), ("٣٠٠", False), ("0150", False)])
def test_scale_ok(scale, ok):
    assert app.scale_ok(scale) is ok


class FakeUser32:
    """What SetProcessDpiAwarenessContext and GetDpiForWindow see; returns as Windows."""

    def __init__(self, answer=1, dpi=144):
        self.calls, self.answer, self.dpi = [], answer, dpi

        class Function:
            def __init__(this, name, result):
                this.name, this.result = name, result

            def __call__(this, *args):
                self.calls.append((this.name, args))
                return this.result() if callable(this.result) else this.result

        self.SetProcessDpiAwarenessContext = Function("awareness", lambda: self.answer)
        self.GetDpiForWindow = Function("dpi", lambda: self.dpi)


class FakeWindll:
    def __init__(self, user32):
        self.user32 = user32


def test_windows_is_told_freerdp_tk_is_per_monitor_dpi_aware(monkeypatch):
    import ctypes
    user32 = FakeUser32()
    monkeypatch.setattr(ctypes, "windll", FakeWindll(user32), raising=False)
    monkeypatch.setattr(app, "IS_WIN", False)
    assert app.set_dpi_awareness() is False and user32.calls == []  # a no-op off Windows
    monkeypatch.setattr(app, "IS_WIN", True)
    assert app.set_dpi_awareness() is True
    assert user32.calls == [("awareness", (-4,))]  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    user32.answer = 0  # it refuses (set before, by a manifest say): nothing more to do
    assert app.set_dpi_awareness() is False


def test_an_old_windows_without_the_call_is_left_alone(monkeypatch):
    import ctypes
    monkeypatch.setattr(app, "IS_WIN", True)
    monkeypatch.setattr(ctypes, "windll", FakeWindll(object()), raising=False)  # no such call
    assert app.set_dpi_awareness() is False
    root = type("Root", (), {"winfo_id": lambda self: 42})()
    assert app.match_tk_scaling(root) is None


def test_tk_scaling_follows_the_monitor_dpi(monkeypatch):
    import ctypes
    user32 = FakeUser32(dpi=144)  # 150 %
    monkeypatch.setattr(ctypes, "windll", FakeWindll(user32), raising=False)
    set_to = []

    class Root:
        tk = type("Tcl", (), {"call": lambda self, *args: set_to.append(args)})()

        def winfo_id(self):
            return 42

    monkeypatch.setattr(app, "IS_WIN", False)
    assert app.match_tk_scaling(Root()) is None and set_to == []
    monkeypatch.setattr(app, "IS_WIN", True)
    assert app.match_tk_scaling(Root()) == 2.0
    assert set_to == [("tk", "scaling", 2.0)] and user32.calls == [("dpi", (42,))]
    user32.dpi = 0  # Windows could not tell: Tk keeps its own
    assert app.match_tk_scaling(Root()) is None and len(set_to) == 1


def test_windows_fills_in_the_os_scale_the_client_does_not_give(monkeypatch):
    """An older client lists no scale; on Windows it comes from the monitor under the
    middle of each one, and a scale the client gave is kept."""
    asked = []
    monkeypatch.setattr(app, "dpi_at", lambda x, y: asked.append((x, y)) or 144)
    output = ("     * [1] [A] 1920x1080\t+0+0\n"
              "       [2] [B] 2560x1440\t+-2560+0\t125%\n")
    monkeypatch.setattr(app, "IS_WIN", False)
    assert [m["scale"] for m in app.add_os_scales(app.parse_monitors(output))] == [None, 125]
    assert asked == []
    monkeypatch.setattr(app, "IS_WIN", True)
    assert [m["scale"] for m in app.add_os_scales(app.parse_monitors(output))] == [150, 125]
    assert asked == [(960, 540)]
    monkeypatch.setattr(app, "dpi_at", lambda x, y: None)
    assert app.add_os_scales(app.parse_monitors(output))[0]["scale"] is None


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
            path.write_text(content if isinstance(content, str) else json.dumps(content),
                            encoding="utf-8")
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


INTEL_VENDOR = "Intel iHD driver for Intel(R) Gen Graphics - 25.3.4 () (/dev/dri/renderD129)"
VAAPI = ["0 VA-API Mesa Gallium driver 25.2.3 for AMD Radeon 780M (radeonsi, phoenix) "
         "(/dev/dri/renderD128) (AV1 4:2:0 decode)",
         f"1 VA-API {INTEL_VENDOR} (AV1 4:2:0 decode)"]


def test_the_linux_decoders_come_from_codec_list_too(fake_client, monkeypatch):
    """The Linux client lists the render nodes with a VA-API AV1 decoder; an entry picks
    that one by its id, and none listed (no such GPU, no libva) leaves nothing to pick."""
    client = app.find_clients()[0]
    monkeypatch.setenv("FAKE_DECODERS", "\n".join(VAAPI))
    assert app.list_decoders(client) == VAAPI
    assert app.codec_first_args({"decoding": app.HARDWARE_FIRST, "gpu": VAAPI[1]}) == \
        ["/codec-first:hardware:1"]
    monkeypatch.setenv("FAKE_DECODERS", "no hardware video decoder")
    assert app.list_decoders(client) == []


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
    # Linux (FreeRDP 20261123.1, av1.c and av1_vaapi.c): the id of /codec-list, then the
    # driver's vendor string, which may hold parentheses of its own, and the render node
    ("[INFO][com.freerdp.codec.av1] - [av1_init]: AV1 decoder: VA-API 0 Mesa Gallium driver "
     "25.2.3 for AMD Radeon 780M (radeonsi, phoenix, LLVM 20.1.8, DRM 3.64) (/dev/dri/renderD128) "
     "(hardware), dav1d as fallback",
     (True, "Mesa Gallium driver 25.2.3 for AMD Radeon 780M (radeonsi, phoenix, LLVM 20.1.8, "
            "DRM 3.64) (/dev/dri/renderD128) (VA-API 0)")),
    (f"AV1 decoder: VA-API 1 {INTEL_VENDOR} (hardware), dav1d as fallback",
     (True, f"{INTEL_VENDOR} (VA-API 1)")),
    ("AV1 decoder: dav1d (software, no GPU with a VA-API AV1 decoder)", (False, "dav1d")),
    ("VA-API: AV1 decoder 1920x1080 on /dev/dri/renderD128", None),  # not the decoder's line
    ("AV1 decoder: VideoToolbox (hardware), software as fallback", (True, "VideoToolbox")),
    ("AV1 decoder: software (/codec-first:software)", (False, "software")),
    ("[INFO][fake] - connected", None),
])
def test_the_decoder_a_log_line_names(line, decoder):
    """The client's own words (FreeRDP libfreerdp/codec/av1.c) on the AV1 decoder it runs."""
    assert app.decoder_of(line) == decoder


@pytest.mark.parametrize("line, said", [  # the lines TestSDLHiDpi's checkLayoutText pins
    ("[13:02:11:120] [3:4] [INFO][com.freerdp.client.SDL] - [sendLayout]: HiDPI: 2 points "
     "(display 2x, 1280x832 -> desktop 200/180)",
     ("2", "points", "display 2x, 1280x832, desktop 200 %")),
    ("HiDPI: 1 pixels (display 1x, 1920x1080 -> desktop 150/140)",
     ("1", "pixels", "display 1x, 1920x1080, desktop 150 %")),
    ("HiDPI: 3 scale:150 (display 2x, 2268x1472 -> desktop 100/100)",
     ("3", "scale:150", "display 2x, 2268x1472, desktop 100 %")),
    ("HiDPI: 4 points (display 1.5x, 1280x720 -> desktop 150/140)",
     ("4", "points", "display 1.5x, 1280x720, desktop 150 %")),
    ("[INFO][com.freerdp.client.SDL] - [sendLayout]: AV1 decoder: dav1d (software)", None),
    ("/sdl-hidpi:points|pixels|scale:<N>  How a window on a display ...", None),
])
def test_hidpi_of(line, said):
    assert app.hidpi_of(line) == said


def test_a_newer_client_gives_the_os_scale_in_its_monitor_list():
    """FreeRDP 20261123.5 and newer end each /list:monitor line with the scale."""
    line = "     * [1] [Built-in Retina Display] 1512x982\t+0+0\t200%"
    assert app.parse_monitors(line)[0]["scale"] == 200


@pytest.mark.parametrize("fields, scale, density", [  # TestSDLHiDpi's listMonitorFields
    ("\t100%\t2x", 100, 2.0), ("\t150%\t1x", 150, 1.0), ("\t125%\t1.5x", 125, 1.5),
    ("\t200%\t2x", 200, 2.0),
    ("\t150%", 150, None),  # FreeRDP 20261123.6: the scale alone
    ("", None, None),  # before 20261123.5
    ("\t150%\t1x\tsomething-new", 150, 1.0),  # a field not known here is left alone
])
def test_the_monitor_list_gives_scale_and_density(fields, scale, density):
    """The live Xvfb line of FreeRDP 51d01ba26, with each set of trailing fields: the
    monitor is listed whatever follows its position."""
    monitors = app.parse_monitors(f"     * [1] [screen] 1920x1080\t+0+0{fields}")
    assert [(m["id"], m["size"], m["at"], m["scale"], m["density"]) for m in monitors] == \
        [("1", "1920x1080", "+0+0", scale, density)]


def test_live_stats_ask_for_the_server_rows_too():
    """Show live stats: the overlay (+sdl-info) and what the server measured (+astats),
    which a client without it is not given."""
    def stats(args):
        return [x for x in args if x in ("+sdl-info", "+astats")]

    assert stats(build_args({"host": "h", "stats": True}, "")) == ["+sdl-info", "+astats"]
    assert stats(build_args({"host": "h", "stats": True}, "", server_stats=False)) == \
        ["+sdl-info"]
    assert stats(build_args({"host": "h"}, "")) == []


def test_the_camera_is_shared_only_when_ticked():
    """Off by default: no camera leaves this computer unless the connection asks for it."""
    assert app.FIELDS["camera"] is False
    assert not any(x.startswith("/dvc:rdpecam") for x in build_args({"host": "h"}, ""))
    assert "/dvc:rdpecam" in build_args({"host": "h", "camera": True}, "")
    # a client without the camera channel gets none
    assert "/dvc:rdpecam" not in build_args({"host": "h", "camera": True}, "", camera=False)


@pytest.mark.parametrize("said, has", [
    ("Build configuration: WITH_FFMPEG=ON CHANNEL_RDPECAM=ON CHANNEL_RDPECAM_CLIENT=ON", True),
    ("Build configuration: WITH_FFMPEG=ON CHANNEL_RDPECAM_CLIENT=OFF", False),
    ("Build configuration: WITH_FFMPEG=ON WITH_GFX_AZURE=ON", False),  # before 20261128.2
])
def test_the_camera_channel_is_read_from_buildconfig(said, has):
    assert (app.CAMERA_BUILT in said) is has
