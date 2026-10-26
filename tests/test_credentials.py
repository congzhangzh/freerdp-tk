"""Passwords in the system keyring, here an in-memory one (see conftest.py)."""

import functools
import sys
import threading
import time

import keyring
import pytest
from keyring.backends import chainer, null
from keyring.errors import KeyringLocked

from freerdp_tk import credentials
from freerdp_tk.credentials import CredentialError

LAB = {"host": "RDP.example.com", "port": "", "user": "Alice", "domain": "LAB"}


def test_key_names_the_account():
    assert credentials.key(LAB) == ("freerdp-tk/lab\\alice@rdp.example.com:3389", "LAB\\Alice")
    assert credentials.key({"host": " h ", "port": "3390", "user": "bob"}) == (
        "freerdp-tk/bob@h:3390", "bob")


def test_no_key_without_host_or_user():
    assert credentials.key({"host": "h", "user": " "}) is None
    assert credentials.key({"user": "alice"}) is None
    assert credentials.load({"host": "h"}) is None
    credentials.forget({"host": "h"})  # nothing to do
    with pytest.raises(CredentialError):
        credentials.save({"host": "h"}, "pw")


def test_save_load_forget(memory_keyring):
    assert credentials.problem() == ""
    assert credentials.load(LAB) is None
    credentials.save(LAB, "s3cret!")
    assert credentials.load({**LAB, "host": "rdp.EXAMPLE.com", "port": "3389"}) == "s3cret!"
    credentials.save(LAB, "n3w")
    assert memory_keyring.items == {credentials.key(LAB): "n3w"}  # replaced, not added
    credentials.forget(LAB)
    credentials.forget(LAB)  # already gone: no error
    assert memory_keyring.items == {}


def test_only_safe_backends_are_used():
    keyring.set_keyring(null.Keyring())
    assert "keyring.backends.null.Keyring" in credentials.problem()
    with pytest.raises(CredentialError):
        credentials.load(LAB)
    with pytest.raises(CredentialError):
        credentials.save(LAB, "pw")


def test_a_chain_uses_its_first_safe_backend(memory_keyring, monkeypatch):
    monkeypatch.setattr(chainer.ChainerBackend, "backends", [null.Keyring(), memory_keyring])
    keyring.set_keyring(chainer.ChainerBackend())
    credentials.save(LAB, "pw")
    assert memory_keyring.items == {credentials.key(LAB): "pw"}


def test_backend_errors_become_credential_errors(memory_keyring, monkeypatch):
    def locked(*_):
        raise KeyringLocked("Failed to unlock the collection!")

    monkeypatch.setattr(memory_keyring, "get_password", locked)
    with pytest.raises(CredentialError, match="Failed to unlock"):
        credentials.load(LAB)

    monkeypatch.setattr(memory_keyring, "get_password", lambda *_: 1 / 0)
    with pytest.raises(CredentialError, match="division"):
        credentials.load(LAB)


def test_without_the_keyring_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # import keyring now fails
    assert "not installed" in credentials.problem()


def test_the_worker_keeps_order_and_hands_back_results_and_errors():
    worker, got = credentials.Worker(), []
    caller = threading.get_ident()

    def done(result, error):
        got.append((result, str(error) if error else None, threading.get_ident() == caller))

    worker.run(functools.partial(credentials.save, LAB, "pw"), done)
    worker.run(functools.partial(credentials.load, LAB), done)
    worker.run(lambda: 1 / 0, done)
    end = time.monotonic() + 5
    while worker.pending and time.monotonic() < end:
        for callback in worker.finished():
            callback()
        time.sleep(0.01)
    worker.close(timeout=5)
    assert got == [(None, None, True), ("pw", None, True), (None, "division by zero", True)]
    assert not worker.thread.is_alive()
