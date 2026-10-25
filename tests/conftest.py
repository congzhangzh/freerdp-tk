import os
import stat
import sys
import tkinter as tk

import pytest

# Stands in for a FreeRDP 3 client: answers /version, then records what it was
# given (argv and stdin) and exits with code 7, so a test can check both ends.
FAKE_CLIENT = """
import json, os, sys
if sys.argv[1:] == ["/version"]:
    print("This is FreeRDP version 3.99.0 (fake)")
    sys.exit(0)
with open(os.environ["FAKE_RECORD"], "w") as f:
    json.dump({"argv": sys.argv, "stdin": sys.stdin.read()}, f)
print("[INFO][fake] - connected")
sys.exit(7)
"""


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
    roots = []

    def make():
        from freerdp_tk import app
        root = tk.Tk()
        roots.append(root)
        window = app.App(root)
        root.update()  # map it, so it has a size and a place on screen
        return window

    yield make
    for root in roots:
        root.destroy()
