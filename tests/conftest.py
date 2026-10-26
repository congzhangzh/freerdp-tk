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
# 132, authentication failed) instead, like a server that turns it down.
FAKE_CLIENT = """
import json, os, sys
if sys.argv[1:] == ["/list:monitor"]:  # two monitors, unless $FAKE_MONITORS says otherwise
    print(os.environ.get("FAKE_MONITORS", "listing 2 monitors:\\n"
          "     * [1] [Built-in Retina Display] 1512x982\\t+0+0\\n"
          "       [2] [DELL U2720Q] 2560x1440\\t+-2560+0"))
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
print("[INFO][fake] - connected")
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
    script.write_text(FAKE_CLIENT)
    if sys.platform == "win32":  # found through PATHEXT, run by cmd.exe
        (bin_dir / "sdl-freerdp3.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n')
        rest = os.environ["PATH"]  # keeps System32: cmd.exe, taskkill
    else:
        client = bin_dir / "sdl-freerdp3"
        client.write_text(f"#!{sys.executable}\n" + FAKE_CLIENT)
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
