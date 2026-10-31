"""client_major_version(): a client's major FreeRDP version, or None when it cannot
be told. Unknown is not old: a busy computer can be slow to start a client, and a
timeout once made freerdp-tk refuse a FreeRDP 3 client (kit run 41180196907)."""

import os
import stat
import sys

import pytest

from freerdp_tk import app


def fake_client(tmp_path, body: str):
    """A stand-in for a client: a Python script that answers /version with body."""
    script = tmp_path / "client.py"
    script.write_text(body)
    if sys.platform == "win32":
        launcher = tmp_path / "client.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\n')
    else:
        launcher = tmp_path / "client"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR)
    return str(launcher)


@pytest.mark.parametrize("said, major", [
    ("This is FreeRDP version 3.32.3-dev0 (n/a)", 3),
    ("This is FreeRDP version 2.11.7 (2.11.7)", 2),
])
def test_a_version_it_says(tmp_path, said, major):
    assert app.client_major_version(fake_client(tmp_path, f"print({said!r})")) == major


def test_no_version_is_unknown(tmp_path):
    assert app.client_major_version(fake_client(tmp_path, "print('usage: client ...')")) is None


def test_a_client_that_does_not_start_is_unknown(tmp_path):
    assert app.client_major_version(str(tmp_path / "no-such-client")) is None


def test_too_slow_is_unknown_not_old(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "VERSION_TIMEOUT", 0.5)
    slow = fake_client(tmp_path, "import time; time.sleep(5); print('This is FreeRDP version 3.0.0')")
    assert app.client_major_version(slow) is None
