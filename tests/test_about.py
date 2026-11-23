"""About: the MANIFEST the bundled client carries, freerdp-tk's own commit, and the window."""

import json
import subprocess
from pathlib import Path

import pytest

from freerdp_tk import about
from helpers import button, click, pump, widgets

FREERDP = "b91abbc81cba56af55cf54b2544b07cbeba9e61d"
KIT = "e462e7c0123456789abcdef0123456789abcdef0"
UPSTREAM = "6dddcd3" + "2" * 33
SDL = "9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3"
OLD = f"""sdl3-freerdp 20261114.3 for Linux x86_64, built 2026-11-15
build environment: AlmaLinux 9.8 (Olive Jaguar), ldd (GNU libc) 2.34

sources (sources.lock):
  freerdp   20261114.3 {FREERDP}
  sdl3      3.4.18   {SDL}
  freerdp_tk 20261112.1 8cd8eafdd1a36183ef7dc389888c93dd0e5f2b37
  python    3.13.17+20261021 f829adc9d888e76c8801b4799ed444188d35239fcae3a9808a99ec5cb0d8d92c
  freerdp_tk needs (its uv.lock): cffi 2.1.1, keyring 25.7.0

WITH_AAD=ON
WITH_GFX_AV1=ON
"""
NEW = OLD.replace("build environment: AlmaLinux 9.8 (Olive Jaguar), ldd (GNU libc) 2.34\n",
                  "build environment: AlmaLinux 9.8 (Olive Jaguar), ldd (GNU libc) 2.34\n"
                  f"kit: rdp-release-kit {KIT}\n"
                  f"freerdp-upstream: master {UPSTREAM} +59 2026-11-13\n") \
    .replace(f"{FREERDP}\n", f"{FREERDP} https://github.com/congzhangzh/FreeRDP\n") \
    .replace(f"{SDL}\n", f"{SDL} https://github.com/libsdl-org/SDL/releases/download/"
                         "release-3.4.18/SDL3-3.4.18.tar.gz\n")


def test_the_new_manifest():
    m = about.parse_manifest(NEW)
    assert (m.release, m.platform, m.built) == ("20261114.3", "Linux x86_64", "2026-11-15")
    assert m.kit_commit == KIT and m.kit_release is None  # the kit picks it after the build
    assert [s.name for s in m.client_sources] == ["freerdp", "sdl3"]  # not the kit's pack
    freerdp, sdl = m.client_sources
    assert freerdp.commit == FREERDP and freerdp.commit_link() == \
        f"https://github.com/congzhangzh/FreeRDP/commit/{FREERDP}"
    assert sdl.commit is None and sdl.digest == SDL and sdl.commit_link() is None
    assert sdl.url.endswith("SDL3-3.4.18.tar.gz")
    assert about.kit_links(m) == (None, f"https://github.com/congzhangzh/rdp-release-kit/commit/{KIT}")
    assert m.upstream == ("master", UPSTREAM, 59, "2026-11-13")
    assert about.upstream_link(m) == f"https://github.com/FreeRDP/FreeRDP/commit/{UPSTREAM}"
    assert about.parse_manifest(NEW.replace(" 2026-11-13", "")).upstream[3] is None  # no date


WINDOWS = """sdl-freerdp.exe 20261115.4 for Windows x86_64, built 2026-11-15
toolchain: llvm-mingw 20261020 (clang, libc++, UCRT)

sources (sources.lock):
  freerdp    20261115.4 5be282e0a95f2e5040c063b2fb2a6ba60c3075ed
  sdl3       3.4.18   9c75cf16330322c217dedd2e0609f1124f1b54b8633e763467b4684d0f4334a3
"""


def test_the_windows_manifest():
    """The Windows client's MANIFEST (kit 20261115.10, as it is in the zip) names its
    program sdl-freerdp.exe and has a toolchain line: release run 44096546539 stopped
    on it."""
    m = about.parse_manifest(WINDOWS)
    assert (m.release, m.platform, m.built) == ("20261115.4", "Windows x86_64", "2026-11-15")
    assert m.environment == "llvm-mingw 20261020 (clang, libc++, UCRT)"
    assert m.source("freerdp").commit == "5be282e0a95f2e5040c063b2fb2a6ba60c3075ed"
    assert about.parse_manifest(WINDOWS.replace("\n", "\r\n")).release == "20261115.4"


def test_an_old_manifest_still_reads():
    m = about.parse_manifest(OLD)
    assert m.release == "20261114.3" and m.kit_commit is None and m.upstream is None
    freerdp = m.source("freerdp")
    assert freerdp.url == "" and freerdp.commit_link().endswith(f"/FreeRDP/commit/{FREERDP}")


@pytest.mark.parametrize("text", ["", "garbage\n\x00\x01", "sources (sources.lock):\n  x\n",
                                  "kit: rdp-release-kit\n", "sdl3-freerdp for, built\n"])
def test_a_malformed_manifest_never_raises(text):
    m = about.parse_manifest(text)
    assert m.release is None and all(s.name != "x" for s in m.sources)


def test_the_manifest_beside_a_client_and_its_kit_release(tmp_path):
    client = tmp_path / "client" / "sdl-freerdp"
    client.parent.mkdir()
    assert about.read_manifest(str(client)) is None  # none there
    (client.parent / "MANIFEST").write_text(NEW, encoding="utf-8")
    # bundle_client.py writes it
    (client.parent / "KIT_RELEASE").write_text("20261117.2\n", encoding="utf-8")
    m = about.read_manifest(str(client))
    assert m.kit_release == "20261117.2" and about.kit_links(m)[0].endswith("/tag/20261117.2")
    (client.parent / "KIT_RELEASE").write_text("not a release\n", encoding="utf-8")
    assert about.read_manifest(str(client)).kit_release is None
    unpacked = tmp_path / "pack" / "bin" / "sdl-freerdp"  # a kit archive unpacked by hand
    unpacked.parent.mkdir(parents=True)
    (tmp_path / "pack" / "MANIFEST").write_text(OLD, encoding="utf-8")
    assert about.read_manifest(str(unpacked)).release == "20261114.3"
    (client.parent / "MANIFEST").write_bytes(b"\xff\xfe nothing a MANIFEST says")
    assert about.read_manifest(str(client)) is None


def test_the_build_commit(tmp_path, monkeypatch):
    commit = tmp_path / "COMMIT"
    monkeypatch.setattr(about, "COMMIT_FILE", commit)
    commit.write_text("0213f32" + "0" * 33 + "\n", encoding="utf-8")
    assert about.build_commit() == "0213f32" + "0" * 33  # a release's
    commit.write_text("not a commit\n", encoding="utf-8")
    here = Path(about.__file__).resolve().parents[2]
    if (here / ".git").exists():  # a source checkout asks git
        head = subprocess.run(["git", "-C", str(here), "rev-parse", "HEAD"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace").stdout.strip()
        assert about.build_commit() == head
    monkeypatch.setattr(about, "__file__", str(tmp_path / "a" / "b" / "about.py"))
    assert about.build_commit() is None  # neither: nothing, not a guess


@pytest.mark.parametrize("url, name", [
    ("https://github.com/libsdl-org/SDL/releases/download/release-3.4.18/SDL3-3.4.18.tar.gz",
     "github.com/libsdl-org/SDL"),
    ("https://github.com/congzhangzh/FreeRDP", "github.com/congzhangzh/FreeRDP"),
    ("https://www.openssl.org/source/openssl-3.5.9.tar.gz", "openssl.org"),
    ("https://zlib.net/zlib-1.3.2.tar.xz", "zlib.net"),
    ("https://code.videolan.org/videolan/dav1d.git", "code.videolan.org/videolan/dav1d"),
])
def test_a_url_shows_as_a_short_name(url, name):
    """The window stays narrow: the link goes to the whole url."""
    assert about.url_name(url) == name


def test_the_home_folder_is_left_out():
    assert about.home_as_tilde("/home/alice/.cache/x", "/home/alice") == "~/.cache/x"
    assert about.home_as_tilde("/usr/bin/x", "/") == "/usr/bin/x"


def links(window):
    return {w.cget("text"): w.url for w in widgets(window) if hasattr(w, "url")}


def labels(window):
    return [w.cget("text") for w in widgets(window) if w.winfo_class() == "TLabel"]


def open_about(ui):
    click(ui, button(ui, "About"))
    pump(ui, lambda: getattr(ui, "about", None) is not None)
    pump(ui, lambda: ui.about.keyring_text is not None)  # the keyring worker answered
    return ui.about


def test_about_with_the_bundled_client(make_ui, home, monkeypatch, tmp_path):
    from freerdp_tk import app
    own = home / "wheel" / "client" / "sdl-freerdp"
    own.parent.mkdir(parents=True)
    own.write_text("", encoding="utf-8")
    own.chmod(0o755)
    (own.parent / "MANIFEST").write_text(NEW, encoding="utf-8")
    (own.parent / "KIT_RELEASE").write_text("20261117.2\n", encoding="utf-8")
    monkeypatch.setattr(app, "BUNDLED", own)
    commit = tmp_path / "COMMIT"
    commit.write_text("0213f32" + "1" * 33, encoding="utf-8")
    monkeypatch.setattr(about, "COMMIT_FILE", commit)
    ui = make_ui()
    window = open_about(ui)
    pump(ui, lambda: window.commit is not None)
    found = links(window)
    assert found["0213f32"] == f"https://github.com/congzhangzh/freerdp-tk/commit/0213f32{'1' * 33}"
    assert found["b91abbc"] == f"https://github.com/congzhangzh/FreeRDP/commit/{FREERDP}"
    assert found["rdp-release-kit 20261117.2"].endswith("/releases/tag/20261117.2")
    assert found["e462e7c"].endswith(f"/rdp-release-kit/commit/{KIT}")
    assert found["6dddcd3"] == f"https://github.com/FreeRDP/FreeRDP/commit/{UPSTREAM}"
    assert "(2026-11-13) + 59 of our commits" in labels(window)
    texts = labels(window)
    assert f"freerdp-tk {app.__version__}" in texts and "bundled with freerdp-tk" in texts
    shown = str(Path("~", "wheel", "client", "sdl-freerdp"))  # \\ on Windows
    assert shown in texts  # the home folder as ~
    click(ui, button(window, "Details"))
    assert "sdl3" in labels(window) and "freerdp_tk" not in labels(window)
    assert f"sha256 {SDL[:12]}" in labels(window)  # a tarball digest: no commit, no link
    assert links(window)["github.com/libsdl-org/SDL"].endswith("SDL3-3.4.18.tar.gz")
    click(ui, button(window, "Copy"))
    report = ui.root.clipboard_get()
    assert f"commit 0213f32{'1' * 33}" in report and f"commit {FREERDP}" in report
    assert f"rdp-release-kit 20261117.2 (commit {KIT})" in report
    assert f"based on FreeRDP master {UPSTREAM} (2026-11-13) + 59 of our commits" in report
    assert str(home) not in report and f"client: {shown} (bundled)" in report
    window.destroy()


def test_about_with_an_installed_client_asks_it(make_ui, fake_client, home):
    ui = make_ui()
    window = open_about(ui)
    assert "installed on this computer" in labels(window)
    pump(ui, lambda: window.says is not None)
    assert "This is FreeRDP version 3.99.0 (fake)" in labels(window)  # its own words
    click(ui, button(window, "Details"))
    assert "Built from: not known for this client" in labels(window)
    window.destroy()


def test_about_with_no_client(make_ui, home, monkeypatch):
    monkeypatch.setenv("PATH", str(home / "nothing"))
    ui = make_ui()
    window = open_about(ui)
    assert "<no client found>" in labels(window)
    window.destroy()
