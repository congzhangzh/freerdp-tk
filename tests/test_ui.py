"""The real window, driven like a user, with the fake client recording what it gets."""

import json

import pytest

from helpers import (button, click, entry_for, has_xdotool, log_text, pump, type_into,
                     xdo_click, xdo_type)


def check_session(ui, record):
    pump(ui, lambda: "exited with code 7" in log_text(ui))
    got = json.loads(record.read_text())
    assert got["argv"][1:] == ["/args-from:stdin"]  # nothing secret in the process list
    lines = got["stdin"].splitlines()
    assert {"/v:rdp.example.com", "/u:alice", "/p:s3cret!"} <= set(lines)
    log = log_text(ui)
    assert "connected" in log and "s3cret" not in log  # client output, password hidden
    assert ui.running_list.size() == 0  # the finished session was reaped


def test_connect_with_tk_events(make_ui, fake_client):
    ui = make_ui()
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    type_into(ui, entry_for(ui, ui.vars["user"]), "alice")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")

    preview = ui.preview.get("1.0", "end")
    assert "/v:rdp.example.com" in preview and "s3cret" not in preview

    click(ui, button(ui, "Connect"))
    check_session(ui, fake_client)


@pytest.mark.skipif(not has_xdotool(), reason="needs xdotool")
def test_connect_with_the_x_pointer(make_ui, fake_client):
    ui = make_ui()
    xdo_type(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    xdo_type(ui, entry_for(ui, ui.vars["user"]), "alice")
    xdo_type(ui, entry_for(ui, ui.password), "s3cret!")
    xdo_click(ui, button(ui, "Connect"))
    check_session(ui, fake_client)


def test_save_and_reload_a_connection(make_ui, fake_client, home):
    ui = make_ui()
    type_into(ui, entry_for(ui, ui.name), "lab")
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")
    click(ui, button(ui, "Save"))
    assert ui.saved_list.get(0, "end") == ("lab",)
    stored = (home / "cfg" / "freerdp-tk" / "profiles.json").read_text()
    assert "rdp.example.com" in stored and "s3cret" not in stored  # never on disk

    again = make_ui()  # a second window reads the same file
    assert again.saved_list.get(0, "end") == ("lab",)
