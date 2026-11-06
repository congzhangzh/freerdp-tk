"""Starting without Tk, and the glyphs for a Tk without Xft; no display needed."""

import json
import sys

import pytest

from freerdp_tk import app, start


def test_uvx_starts_again_with_uvs_own_python(monkeypatch):
    monkeypatch.setenv("UV", "/opt/uv/uv")
    monkeypatch.delenv(start.AGAIN, raising=False)
    monkeypatch.setattr(sys, "argv", ["freerdp-tk", "--flag"])
    assert start.again_with_uv("0.3.1") == [
        "/opt/uv/uv", "tool", "run", "--from", "freerdp-tk==0.3.1", "freerdp-tk", "--flag"]


def test_the_second_start_asks_uv_for_its_own_python(monkeypatch):
    monkeypatch.setattr(start, "has_tk", lambda: False)
    monkeypatch.setenv("UV", "/opt/uv/uv")
    monkeypatch.setenv("UV_PYTHON_PREFERENCE", "system")  # the user's, overridden
    monkeypatch.setenv(start.AGAIN, "")  # empty: not tried yet; undone after the test
    monkeypatch.setattr("freerdp_tk.__version__", "0.3.1")
    monkeypatch.setattr(sys, "argv", ["freerdp-tk"])
    started = []
    monkeypatch.setattr(start.os, "execv", lambda path, argv: started.append(argv))
    monkeypatch.setattr(start.subprocess, "call", lambda argv: started.append(argv) or 0)
    with pytest.raises(SystemExit):  # the stand-in execv() returns, then call() and exit
        start.main()
    assert started[0] == ["/opt/uv/uv", "tool", "run", "--from", "freerdp-tk==0.3.1", "freerdp-tk"]
    assert start.os.environ["UV_PYTHON_PREFERENCE"] == "only-managed"
    assert start.os.environ[start.AGAIN] == "1"


@pytest.mark.parametrize("uv, again, version", [
    ("", "", "0.3.1"),          # not started by uv
    ("/opt/uv/uv", "1", "0.3.1"),  # the second start has no Tk either
    ("/opt/uv/uv", "", "0.0.0"),   # a source checkout
    ("/opt/uv/uv", "", "0.3.1.dev2+g5483caf"),  # between releases: not on PyPI
])
def test_no_second_start(monkeypatch, uv, again, version):
    for name, value in (("UV", uv), (start.AGAIN, again)):
        if value:
            monkeypatch.setenv(name, value)
        else:
            monkeypatch.delenv(name, raising=False)
    assert start.again_with_uv(version) is None


def test_without_tk_it_says_what_to_do(monkeypatch):
    monkeypatch.setattr(start, "has_tk", lambda: False)
    monkeypatch.delenv("UV", raising=False)
    with pytest.raises(SystemExit) as stop:
        start.main()
    assert "uvx --managed-python freerdp-tk" in str(stop.value.code)
    assert "python3-tk" in str(stop.value.code)


class FakeTk:
    def __init__(self, system, fonts):
        self.answers = {("tk", "windowingsystem"): system,
                        ("::tk::pkgconfig", "get", "fontsystem"): fonts}

    def call(self, *words):
        return self.answers[words]


class FakeRoot:
    def __init__(self, system, fonts):
        self.tk = FakeTk(system, fonts)


@pytest.mark.parametrize("system, fonts, plain", [
    ("x11", "x11", True),    # Tk without Xft: X core fonts
    ("x11", "xft", False),
    ("win32", "", False),
    ("aqua", "", False),
])
def test_glyphs(monkeypatch, system, fonts, plain):
    from freerdp_tk import app
    monkeypatch.setattr(app, "GLYPHS", dict(app.GLYPHS))
    assert app.use_glyphs(FakeRoot(system, fonts)) is plain
    assert app.GLYPHS["dots"] == ("..." if plain else "…")
    assert app.GLYPHS["dot"] == ("*" if plain else "•")


@pytest.fixture
def prefs(tmp_path, monkeypatch):
    """The client's settings file, in a home of its own."""
    monkeypatch.setattr(app, "IS_WIN", False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "freerdp" / "sdl-freerdp.json"


def test_the_first_start_moves_the_hotkeys_off_right_shift(prefs):
    app.move_client_hotkeys()
    assert json.loads(prefs.read_text()) == {"SDL_KeyModMask": ["KMOD_RALT", "KMOD_RSHIFT"]}


def test_a_settings_file_that_exists_is_left_alone(prefs):
    prefs.parent.mkdir()
    prefs.write_text('{ "SDL_Fullscreen": true }')
    app.move_client_hotkeys()
    assert prefs.read_text() == '{ "SDL_Fullscreen": true }'


def test_a_folder_that_cannot_be_written_stops_nothing(prefs):
    prefs.parent.write_text("a file where the folder should be")
    app.move_client_hotkeys()
    assert prefs.parent.read_text() == "a file where the folder should be"


def test_the_client_looks_under_dot_config_on_a_mac_too(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "IS_WIN", False)
    monkeypatch.setattr(app, "IS_MAC", True)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", "")  # empty must not mean the current folder
    assert app.client_prefs_file() == tmp_path / ".config" / "freerdp" / "sdl-freerdp.json"


def test_windows_keeps_it_in_appdata(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "IS_WIN", True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert app.client_prefs_file() == tmp_path / "freerdp" / "sdl-freerdp.json"
