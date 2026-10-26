"""The real window, driven like a user, with the fake client recording what it gets."""

import json

import pytest

from helpers import (button, click, entry_for, has_xdotool, log_text, pump, type_into,
                     xdo_click, xdo_type)


def check_session(ui, record):
    pump(ui, lambda: ui.running_list.size() == 0)
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
    stored = ui.store.read_text()
    assert ui.store.is_relative_to(home)  # the throwaway one, not the real profiles
    assert "rdp.example.com" in stored and "s3cret" not in stored  # never on disk

    again = make_ui()  # a second window reads the same file
    assert again.saved_list.get(0, "end") == ("lab",)


def test_only_sdl_clients_are_found(home, monkeypatch):
    from freerdp_tk import app

    def program(path):
        path = path.with_name(path.name + app.EXE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        path.chmod(0o755)
        return str(path)

    on_path = [program(home / "bin" / n) for n in ("xfreerdp3", "wfreerdp", "sdl-freerdp3")]
    build = home / "projects" / "FreeRDP" / "build" / "client"
    program(build / "SDL" / "SDL2" / "sdl2-freerdp")
    sdl3 = program(build / "SDL" / "SDL3" / "sdl3-freerdp")
    monkeypatch.setenv("PATH", str(home / "bin"))
    assert app.find_clients() == [on_path[2], sdl3]


def test_an_old_client_is_refused(make_ui, fake_client, monkeypatch):
    from freerdp_tk import app
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setenv("FAKE_VERSION", "2.11.7")
    ui = make_ui()
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")
    click(ui, button(ui, "Connect"))
    assert len(errors) == 1 and "is not a FreeRDP 3 client" in errors[0]
    assert not fake_client.exists()  # never started: the password stays off the command line


def test_auto_saved_by_an_older_version_is_still_auto(make_ui, fake_client):
    from freerdp_tk import app
    ui = make_ui()
    ui.store.parent.mkdir(parents=True, exist_ok=True)
    ui.store.write_text(json.dumps({"lab": {"host": "h", "client": app.OLD_AUTO}}))
    assert make_ui().saved["lab"]["client"] == app.AUTO
