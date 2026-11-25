import os
import stat
import sys
import time
import tkinter as tk

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

# Stands in for a FreeRDP 3 client: answers /version (with $FAKE_VERSION when
# set), then records what it was given (argv and stdin) and exits with code 7,
# so a test can check both ends. /list:monitor prints $FAKE_MONITORS.
# Given the password in $FAKE_REJECT it exits with $FAKE_REJECT_CODE (default
# 132, authentication failed) instead, like a server that turns it down. With
# $FAKE_255=silent it exits with 255 and says nothing, as FreeRDP's SDL client
# does when SDL cannot start its video (a desktop with no monitor); with
# $FAKE_255=said, it says a line first. /codec-list prints $FAKE_DECODERS (none by
# default); $FAKE_NO_CODEC_FIRST: a client from before /codec-first, $FAKE_NO_HIDPI one
# from before /sdl-hidpi. $FAKE_SAY is a
# line it says once connected, and $FAKE_STAY the seconds it then stays. $FAKE_SLOW: the
# seconds it takes to answer /version, /help, /codec-list and /list:monitor.
FAKE_CLIENT = """
import json, os, sys, time
if sys.argv[1:] in (["/version"], ["/help"], ["/codec-list"], ["/list:monitor"]):
    time.sleep(float(os.environ.get("FAKE_SLOW", "0")))  # a busy computer, a slow start
if sys.argv[1:] == ["/list:monitor"]:  # two monitors, unless $FAKE_MONITORS says otherwise
    print(os.environ.get("FAKE_MONITORS", "listing 2 monitors:\\n"
          "     * [1] [Built-in Retina Display] 1512x982\\t+0+0\\n"
          "       [2] [DELL U2720Q] 2560x1440\\t+-2560+0"))
    sys.exit(0)
if sys.argv[1:] == ["/codec-list"]:
    if os.environ.get("FAKE_NO_CODEC_FIRST"):
        print("Unexpected keyword /codec-list")
        sys.exit(23)
    print(os.environ.get("FAKE_DECODERS") or "no hardware video decoder")
    sys.exit(0)
if sys.argv[1:] == ["/help"]:  # FreeRDP 3's; $FAKE_NO_STATS: no overlay, $FAKE_NO_ASTATS: no server rows
    print("    /args-from:<file>|stdin|fd:<number>|env:<name>")
    if not os.environ.get("FAKE_NO_CODEC_FIRST"):
        print("    /codec-first:hardware[:<id>[,<id>...]]|software  Which video decoder goes first")
    if not os.environ.get("FAKE_NO_HIDPI"):
        print("    /sdl-hidpi:points|pixels|scale:<N>[,<id>:points|pixels|scale:<N>...]")
    if not os.environ.get("FAKE_NO_STATS"):
        print("    +sdl-info                         Enable the stats and info overlay")
        if not os.environ.get("FAKE_NO_ASTATS"):  # a client from before the server's rows
            print("    +astats                           The server's statistics")
    sys.exit(0)
if sys.argv[1:] == ["/version"]:
    print(f"This is FreeRDP version {os.environ.get('FAKE_VERSION', '3.99.0')} (fake)")
    sys.exit(0)
stdin = sys.stdin.read()
with open(os.environ["FAKE_RECORD"], "w") as f:
    json.dump({"argv": sys.argv, "stdin": stdin}, f)
reject = os.environ.get("FAKE_REJECT")
if reject and "/p:" + reject in stdin.splitlines():
    sys.exit(int(os.environ.get("FAKE_REJECT_CODE", "132")))
if os.environ.get("FAKE_255") == "said":
    print("[ERROR][fake] - something else went wrong")
if os.environ.get("FAKE_255"):
    sys.exit(255)
print("[INFO][fake] - connected")
if os.environ.get("FAKE_SAY"):
    print(os.environ["FAKE_SAY"], flush=True)
    import time
    time.sleep(float(os.environ.get("FAKE_STAY", "0")))
sys.exit(7)
"""


class MemoryKeyring(KeyringBackend):
    """A keyring in a dict, counted as safe for the tests."""

    priority = 1

    def __init__(self):
        super().__init__()
        self.items: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.items.get((service, username))

    def set_password(self, service, username, password):
        self.items[(service, username)] = password

    def delete_password(self, service, username):
        if self.items.pop((service, username), None) is None:
            raise PasswordDeleteError(service)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch):
    """Every test gets an empty keyring of its own, never the real one."""
    from freerdp_tk import credentials
    store = MemoryKeyring()
    keyring.set_keyring(store)
    monkeypatch.setattr(credentials, "SAFE", credentials.SAFE | {f"{__name__}.MemoryKeyring"})
    return store


@pytest.fixture(autouse=True)
def english(monkeypatch):
    """The window in English, whatever the language of the machine running the tests."""
    from freerdp_tk import i18n
    monkeypatch.setenv("FREERDP_TK_LANG", "en")
    i18n.use("en")
    yield
    i18n.use("en")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway home and config dir: no real profiles, no ~/projects/FreeRDP builds."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.delenv("FREERDP_TK_TREES", raising=False)
    return tmp_path


@pytest.fixture
def fake_client(home, monkeypatch):
    """Put the fake client first on PATH; returns the file it records into."""
    bin_dir = home / "bin"
    bin_dir.mkdir()
    script = bin_dir / "fake_client.py"
    script.write_text(FAKE_CLIENT, encoding="utf-8")
    if sys.platform == "win32":  # found through PATHEXT, run by cmd.exe
        (bin_dir / "sdl-freerdp3.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n',
                                                  encoding="utf-8")
        rest = os.environ["PATH"]  # keeps System32: cmd.exe, taskkill
    else:
        client = bin_dir / "sdl-freerdp3"
        client.write_text(f"#!{sys.executable}\n" + FAKE_CLIENT, encoding="utf-8")
        client.chmod(client.stat().st_mode | stat.S_IEXEC)
        rest = "/usr/bin:/bin"  # not /usr/local/bin or ~/.local/bin: no real clients
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{rest}")
    record = home / "record.json"
    monkeypatch.setenv("FAKE_RECORD", str(record))
    return record


@pytest.fixture
def make_ui(home):
    """Open the real window; call it once the PATH a test wants is in place."""

    def make():
        from freerdp_tk import app
        root = tk.Tk()
        window = app.App(root)
        windows.append(window)
        root.update()  # map it, so it has a size and a place on screen
        end = time.monotonic() + 15
        while window.keyring.pending:  # the keyring check at startup
            assert time.monotonic() < end, "the keyring check did not come back"
            root.update()
            time.sleep(0.01)
        return window

    windows = []
    yield make
    for window in windows:
        window.keyring.close(timeout=5)
        window.root.destroy()
