"""The system keyring itself, not the in-memory one: only where FREERDP_TK_REAL_KEYRING is set.

It writes a throwaway entry to the keyring of whoever runs it, so it is off
by default. CI turns it on: Linux in an isolated D-Bus session with its own
GNOME Keyring, Windows in the runner's Credential Manager.
"""

import os
import sys
import uuid

import keyring
import keyring.core
import pytest

from freerdp_tk import credentials

pytestmark = pytest.mark.skipif(
    not os.environ.get("FREERDP_TK_REAL_KEYRING"),
    reason="writes to the system keyring; set FREERDP_TK_REAL_KEYRING=1")

EXPECTED = {"linux": "keyring.backends.SecretService.Keyring",
            "win32": "keyring.backends.Windows.WinVaultKeyring",
            "darwin": "keyring.backends.macOS.Keyring"}


@pytest.fixture
def system_keyring():
    keyring.core.init_backend()  # undo the in-memory one from conftest.py
    return credentials.backend()


@pytest.fixture
def account():
    v = {"host": "freerdp-tk-test.invalid", "user": f"test-{uuid.uuid4().hex[:8]}",
         "domain": "CI"}
    yield v
    credentials.forget(v)


def test_the_expected_backend(system_keyring):
    assert credentials._name(system_keyring) == EXPECTED[sys.platform]
    assert credentials.problem() == ""


def test_save_replace_forget(system_keyring, account):
    assert credentials.load(account) is None
    credentials.save(account, "first pässword")
    credentials.save(account, "second pässword")
    assert credentials.load(account) == "second pässword"
    if sys.platform == "win32":  # replaced in place: no "user@service" copy of the old one
        service, user = credentials.key(account)
        assert system_keyring._read_credential(f"{user}@{service}") is None
    credentials.forget(account)
    assert credentials.load(account) is None
