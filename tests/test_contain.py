"""A contained before command is stopped with everything it started, even after a crash."""

import subprocess
import sys
import time

import pytest

from freerdp_tk.app import Helper
from helpers import alive

LINUX, WIN = sys.platform.startswith("linux"), sys.platform == "win32"

# Started as `python child.py spawn <dir>`: starts the kinds of children that
# escape a plain process-group kill, writes each one's pid to <dir>/<kind>.pid.
CHILD = r"""import os, signal, subprocess, sys, time
mode, where = sys.argv[1], sys.argv[2]

def note(kind):
    with open(os.path.join(where, kind + ".pid"), "w") as f:
        f.write(str(os.getpid()))

def child(kind, **kw):
    return subprocess.Popen([sys.executable, __file__, kind, where], **kw)

if mode == "spawn":
    child("plain")
    if os.name == "nt":
        child("detached", creationflags=0x8 | 0x200)  # DETACHED_PROCESS, new group
        child("orphan")
    else:
        child("ignore-term")
        child("setsid")
        child("daemon")
    note("spawner")
    time.sleep(120)
elif mode == "orphan":  # starts a child, then exits: the child loses its parent
    child("orphan-child")
elif mode == "daemon":  # the classic double fork, out of the process group
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            note("daemon")
            time.sleep(120)
else:
    if mode == "ignore-term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if mode == "setsid":
        os.setsid()
    note(mode)
    time.sleep(120)
"""

KINDS = (["spawner", "plain", "detached", "orphan-child"] if WIN else
         ["spawner", "plain", "ignore-term", "setsid", "daemon"])


def start(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(CHILD)
    q = (lambda p: f'"{p}"') if WIN else (lambda p: f"'{p}'")
    return f"{q(sys.executable)} {q(script)} spawn {q(tmp_path)}"


def pids(tmp_path, timeout=15.0) -> dict[str, int]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        files = {k: tmp_path / f"{k}.pid" for k in KINDS}
        if all(f.exists() and f.read_text() for f in files.values()):
            return {k: int(f.read_text()) for k, f in files.items()}
        time.sleep(0.1)
    raise AssertionError(f"children did not start: {sorted(p.name for p in tmp_path.iterdir())}")


def gone(found: dict[str, int], timeout=15.0) -> dict[str, int]:
    """Those still alive after up to timeout seconds."""
    end = time.monotonic() + timeout
    while (left := {k: p for k, p in found.items() if alive(p)}) and time.monotonic() < end:
        time.sleep(0.2)
    return left


def expected_escapes() -> set[str]:
    # macOS has no child subreaper: a double-forked daemon goes to launchd for good.
    return set() if LINUX or WIN else {"daemon"}


def kill_all(found):
    for pid in found.values():
        if alive(pid):
            argv = ["taskkill", "/F", "/PID", str(pid)] if WIN else ["kill", "-9", str(pid)]
            subprocess.run(argv,
                           capture_output=True)


def test_stop_ends_everything_it_started(tmp_path):
    helper = Helper(start(tmp_path), contain=True)
    found = pids(tmp_path)
    try:
        helper.stop()
        assert set(gone(found)) == expected_escapes()
    finally:
        kill_all(found)


LAUNCHER = """import sys, time
from freerdp_tk.app import Helper
helper = Helper(sys.argv[1], contain=True)
print("ready", flush=True)
time.sleep(120)
"""


def test_children_end_when_freerdp_tk_dies(tmp_path):
    """The launcher is killed hard (SIGKILL / TerminateProcess): no code of ours runs."""
    launcher = subprocess.Popen([sys.executable, "-c", LAUNCHER, start(tmp_path)],
                                stdout=subprocess.PIPE, text=True)
    found = pids(tmp_path)
    try:
        assert launcher.stdout.readline().strip() == "ready"
        launcher.kill()
        launcher.wait()
        assert set(gone(found)) == expected_escapes()
    finally:
        kill_all(found)


@pytest.mark.skipif(WIN, reason="POSIX process groups")
def test_plain_helper_is_left_running(tmp_path):
    """Without "Stop it", nothing is stopped at the end: that is the user's choice."""
    helper = Helper(start(tmp_path), contain=False)
    found = pids(tmp_path)
    try:
        del helper
        time.sleep(0.5)
        assert all(alive(p) for p in found.values())
    finally:
        kill_all(found)
