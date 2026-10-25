import os
import stat
import sys
import tkinter as tk

import pytest

# Stands in for a FreeRDP 3 client: answers /version, then records what it was
# given (argv and stdin) and exits with code 7, so a test can check both ends.
FAKE_CLIENT = f"""#!{sys.executable}
import json, os, sys
if sys.argv[1:] == ["/version"]:
    print("This is FreeRDP version 3.99.0 (fake)")
    sys.exit(0)
with open(os.environ["FAKE_RECORD"], "w") as f:
    json.dump({{"argv": sys.argv, "stdin": sys.stdin.read()}}, f)
print("[INFO][fake] - connected")
sys.exit(7)
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME and config dir: no real profiles, no ~/projects/FreeRDP builds."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("FREERDP_TK_TREES", raising=False)
    return tmp_path


@pytest.fixture
def fake_client(home, monkeypatch):
    """Put the fake client alone on PATH; returns the file it records into."""
    if sys.platform == "win32":
        pytest.skip("the fake client is a shebang script")
    bin_dir = home / "bin"
    bin_dir.mkdir()
    client = bin_dir / "sdl-freerdp3"
    client.write_text(FAKE_CLIENT)
    client.chmod(client.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/usr/bin:/bin")
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
