"""The real window, driven like a user, with the fake client recording what it gets."""

import json
import os

import pytest

from helpers import (button, click, entry_for, has_xdotool, log_text, pump, type_into, widgets,
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


def program(path):
    """An empty executable at path (with .exe on Windows)."""
    from freerdp_tk import app
    path = path.with_name(path.name + app.EXE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    path.chmod(0o755)
    return str(path)


def test_only_sdl_clients_are_found(home, monkeypatch):
    from freerdp_tk import app
    on_path = [program(home / "bin" / n) for n in ("xfreerdp3", "wfreerdp", "sdl-freerdp3")]
    build = home / "projects" / "FreeRDP" / "build" / "client"
    program(build / "SDL" / "SDL2" / "sdl2-freerdp")
    sdl3 = program(build / "SDL" / "SDL3" / "sdl3-freerdp")
    monkeypatch.setenv("PATH", str(home / "bin"))
    found = [os.path.normcase(c) for c in app.find_clients()]  # which() gives PATHEXT's .EXE
    assert found == [os.path.normcase(on_path[2]), os.path.normcase(sdl3)]


def test_the_first_folder_on_path_wins(home, monkeypatch):
    from freerdp_tk import app
    # a release's launcher puts its own bin/ before the system's folders;
    # its sdl-freerdp must come before the system's sdl-freerdp3, which
    # comes first by name
    own = program(home / "release" / "bin" / "sdl-freerdp")
    system = program(home / "usr" / "bin" / "sdl-freerdp3")
    monkeypatch.setenv("PATH", os.pathsep.join([str(home / "release" / "bin"),
                                                str(home / "usr" / "bin")]))
    found = [os.path.normcase(c) for c in app.find_clients()]
    assert found == [os.path.normcase(own), os.path.normcase(system)]


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_one_program_is_listed_once(home, monkeypatch):
    from freerdp_tk import app
    # merged /usr: /bin is a link to /usr/bin, and PATH has both
    real = program(home / "usr" / "bin" / "sdl-freerdp3")
    (home / "bin").symlink_to(home / "usr" / "bin")
    monkeypatch.setenv("PATH", os.pathsep.join([str(home / "usr" / "bin"), str(home / "bin")]))
    assert app.find_clients() == [real]


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


def test_list_and_pick_monitors(make_ui, fake_client, monkeypatch):
    from freerdp_tk import app
    shown = []

    def pick(root, monitors, chosen):
        shown.append(([(m["id"], m["name"], m["primary"]) for m in monitors], chosen))
        return ["2"]

    monkeypatch.setattr(app, "pick_monitors", pick)
    ui = make_ui()
    ui.vars["monitors"].set("1")
    click(ui, button(ui, f"List{app.GLYPHS['dots']}"))
    pump(ui, lambda: ui.vars["monitors"].get() == "2")
    assert shown == [([("1", "Built-in Retina Display", True), ("2", "DELL U2720Q", False)],
                      ["1"])]
    assert "/monitors:2" in ui.preview.get("1.0", "end")
    assert button(ui, f"List{app.GLYPHS['dots']}").instate(["!disabled"])


def test_no_monitors_listed(make_ui, fake_client, monkeypatch):
    from freerdp_tk import app
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setenv("FAKE_MONITORS", "listing 0 monitors:")
    ui = make_ui()
    click(ui, button(ui, f"List{app.GLYPHS['dots']}"))
    pump(ui, lambda: errors)
    assert "found no monitors" in errors[0] and "listing 0 monitors:" in log_text(ui)


def test_the_monitor_dialog(make_ui):
    from freerdp_tk import app
    ui = make_ui()
    monitors = app.parse_monitors("  * [1] [A] 1920x1080\t+0+0\n    [3] [B] 1920x1080\t+1920+0")

    def answer():
        dialog = next(w for w in widgets(ui) if w.winfo_class() == "Toplevel")
        boxes = [w for w in widgets(ui) if w.winfo_class() == "TCheckbutton"
                 and w.winfo_toplevel() is dialog]
        click(ui, next(b for b in boxes if b.cget("text").startswith("3:")))  # tick 3
        click(ui, next(b for b in boxes if b.cget("text").startswith("1:")))  # untick 1
        click(ui, next(w for w in widgets(ui) if w.winfo_class() == "TButton"
                       and w.winfo_toplevel() is dialog and w.cget("text") == "OK"))

    ui.root.after(200, answer)
    assert app.pick_monitors(ui.root, monitors, ["1"]) == ["3"]
