"""Saved passwords in the window, with the in-memory keyring from conftest.py."""

import json

import keyring
from keyring.backends import null
from keyring.errors import KeyringLocked

from freerdp_tk import app, credentials
from helpers import button, click, entry_for, log_text, pump, type_into, widgets

LAB = {"host": "rdp.example.com", "user": "alice"}


def fill(ui, name, password=""):
    type_into(ui, entry_for(ui, ui.name), name)
    type_into(ui, entry_for(ui, ui.vars["host"]), LAB["host"])
    type_into(ui, entry_for(ui, ui.vars["user"]), LAB["user"])
    if password:
        type_into(ui, entry_for(ui, ui.password), password)


def select(ui, name):
    ui.saved_list.selection_clear(0, "end")
    ui.saved_list.selection_set(ui.visible.index(name))
    ui._on_select()


def connect(ui, record) -> list[str]:
    """Connect what is selected; the arguments the fake client got."""
    record.unlink(missing_ok=True)
    click(ui, button(ui, "Connect"))
    pump(ui, lambda: ui.running_list.size() == 0 and record.exists())
    return json.loads(record.read_text())["stdin"].splitlines()


def no_prompt(*_):
    raise AssertionError("asked for a password")


def prompt(answer, asked=None):
    def ask(root, text, remember, problem=""):
        if asked is not None:
            asked.append((text, remember, problem))
        return answer
    return ask


def test_saved_once_then_used_by_the_next_window(make_ui, fake_client, memory_keyring,
                                                  monkeypatch):
    ui = make_ui()
    fill(ui, "lab", "s3cret!")
    click(ui, button(ui, "Save"))
    assert memory_keyring.items == {credentials.key(LAB): "s3cret!"}
    assert "s3cret" not in ui.store.read_text()  # the file has the flag, not the password
    assert json.loads(ui.store.read_text())["lab"]["remember_password"] is True

    again = make_ui()  # as after a restart: nothing in memory
    monkeypatch.setattr(app, "ask_password", no_prompt)
    select(again, "lab")
    assert again.password.get() == ""  # selecting does not read the keyring
    assert "/p:s3cret!" in connect(again, fake_client)
    assert "s3cret" not in log_text(again)


def test_the_prompt_saves_when_ticked(make_ui, fake_client, memory_keyring, monkeypatch):
    ui = make_ui()
    fill(ui, "lab")
    click(ui, button(ui, "Save"))
    assert memory_keyring.items == {}  # no password known yet
    asked = []
    monkeypatch.setattr(app, "ask_password", prompt(("pw1", True), asked))
    assert "/p:pw1" in connect(ui, fake_client)
    assert asked == [("Password for alice on lab", True, "")]
    assert memory_keyring.items == {credentials.key(LAB): "pw1"}


def test_the_prompt_unticked_saves_nothing_and_is_remembered(make_ui, fake_client,
                                                              memory_keyring, monkeypatch):
    ui = make_ui()
    fill(ui, "lab")
    click(ui, button(ui, "Save"))
    monkeypatch.setattr(app, "ask_password", prompt(("pw1", False)))
    assert "/p:pw1" in connect(ui, fake_client)
    assert memory_keyring.items == {}
    assert ui.vars["remember_password"].get() is False
    assert json.loads(ui.store.read_text())["lab"]["remember_password"] is False


def test_a_new_password_typed_into_the_form_replaces_the_saved_one(make_ui, fake_client,
                                                                   memory_keyring):
    memory_keyring.set_password(*credentials.key(LAB), "old")
    ui = make_ui()
    fill(ui, "lab", "new")
    assert "/p:new" in connect(ui, fake_client)
    assert memory_keyring.items == {credentials.key(LAB): "new"}


def test_unticking_and_saving_forgets(make_ui, fake_client, memory_keyring):
    ui = make_ui()
    fill(ui, "lab", "pw")
    click(ui, button(ui, "Save"))
    ui.vars["remember_password"].set(False)
    click(ui, button(ui, "Save"))
    assert memory_keyring.items == {}


def test_delete_keeps_a_password_another_connection_uses(make_ui, fake_client, memory_keyring,
                                                         monkeypatch):
    monkeypatch.setattr(app.messagebox, "askyesno", lambda *a, **k: True)
    ui = make_ui()
    fill(ui, "lab", "pw")
    click(ui, button(ui, "Save"))
    ui.name.set("lab copy")
    click(ui, button(ui, "Save"))
    select(ui, "lab")
    click(ui, button(ui, "Delete"))
    assert memory_keyring.items == {credentials.key(LAB): "pw"}  # "lab copy" uses it
    select(ui, "lab copy")
    click(ui, button(ui, "Delete"))
    assert memory_keyring.items == {}


def test_the_forget_button(make_ui, fake_client, memory_keyring):
    memory_keyring.set_password(*credentials.key(LAB), "pw")
    ui = make_ui()
    fill(ui, "lab", "pw")
    click(ui, button(ui, "Forget"))
    assert memory_keyring.items == {}
    assert ui.password.get() == ""
    assert "forgot the saved password of alice on rdp.example.com" in log_text(ui)


def test_without_a_system_keyring(make_ui, fake_client, monkeypatch):
    keyring.set_keyring(null.Keyring())
    ui = make_ui()
    assert "passwords are not saved: no system keyring" in log_text(ui)
    assert button(ui, "Forget").instate(["disabled"])
    asked = []
    monkeypatch.setattr(app, "ask_password", prompt(("pw", True), asked))
    fill(ui, "lab")
    assert "/p:pw" in connect(ui, fake_client)
    assert "no system keyring" in asked[0][2]  # the dialog says why the box is grey


def test_a_locked_keyring_asks_instead(make_ui, fake_client, memory_keyring, monkeypatch):
    def locked(*_):
        raise KeyringLocked("Failed to unlock the collection!")

    memory_keyring.set_password(*credentials.key(LAB), "pw")
    monkeypatch.setattr(memory_keyring, "get_password", locked)
    monkeypatch.setattr(app, "ask_password", prompt(("typed", False)))
    ui = make_ui()
    fill(ui, "lab")
    assert "/p:typed" in connect(ui, fake_client)
    assert "cannot read the saved password" in log_text(ui)


def test_the_password_dialog(make_ui):
    ui = make_ui()

    def answer():
        dialog = next(w for w in widgets(ui) if w.winfo_class() == "Toplevel")
        entry = next(w for w in widgets(ui) if w.winfo_class() == "TEntry"
                     and w.winfo_toplevel() is dialog)
        box = next(w for w in widgets(ui) if w.winfo_class() == "TCheckbutton"
                   and w.winfo_toplevel() is dialog)
        type_into(ui, entry, "s3cret!")
        click(ui, box)  # untick it
        click(ui, next(w for w in widgets(ui) if w.winfo_class() == "TButton"
                       and w.winfo_toplevel() is dialog and w.cget("text") == "OK"))

    ui.root.after(200, answer)
    assert app.ask_password(ui.root, "Password for alice on lab", True) == ("s3cret!", False)


def test_a_rejected_saved_password_is_asked_again_and_replaced(make_ui, fake_client,
                                                               memory_keyring, monkeypatch):
    memory_keyring.set_password(*credentials.key(LAB), "old")
    monkeypatch.setenv("FAKE_REJECT", "old")
    asked = []
    monkeypatch.setattr(app, "ask_password", prompt(("new", True), asked))
    ui = make_ui()
    fill(ui, "lab")
    click(ui, button(ui, "Connect"))
    pump(ui, lambda: fake_client.exists() and "/p:new" in fake_client.read_text()
         and ui.running_list.size() == 0)
    assert len(asked) == 1 and "did not accept the password for alice on lab" in asked[0][0]
    assert memory_keyring.items == {credentials.key(LAB): "new"}
    assert "exited with code 132" in log_text(ui)


def test_a_rejected_password_cancelled_stays_off(make_ui, fake_client, memory_keyring,
                                                 monkeypatch):
    memory_keyring.set_password(*credentials.key(LAB), "old")
    monkeypatch.setenv("FAKE_REJECT", "old")
    asked = []
    monkeypatch.setattr(app, "ask_password", prompt(None, asked))
    ui = make_ui()
    fill(ui, "lab")
    assert "/p:old" in connect(ui, fake_client)
    pump(ui, lambda: asked)
    assert "lab" not in ui.passwords  # the next connect reads the keyring again
    assert memory_keyring.items == {credentials.key(LAB): "old"}  # cancelling changes nothing


def test_a_locked_account_is_not_asked_again(make_ui, fake_client, memory_keyring, monkeypatch):
    memory_keyring.set_password(*credentials.key(LAB), "old")
    monkeypatch.setenv("FAKE_REJECT", "old")
    monkeypatch.setenv("FAKE_REJECT_CODE", "135")  # account locked out
    asked = []  # not no_prompt: Tk only prints what an after_idle callback raises
    monkeypatch.setattr(app, "ask_password", prompt(None, asked))
    ui = make_ui()
    fill(ui, "lab")
    assert "/p:old" in connect(ui, fake_client)
    for _ in range(10):
        ui.root.update()  # give an after_idle prompt its chance
    assert "exited with code 135" in log_text(ui) and asked == []
