"""The real window, driven like a user, with the fake client recording what it gets."""

import json
import os
from pathlib import Path

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


def test_the_client_in_the_wheel_comes_first(home, monkeypatch):
    """Auto tries the wheel's client before an installed one (a distribution's is
    often older); the installed one stays in the list, one pick away."""
    from freerdp_tk import app
    own = program(home / "wheel" / "client" / "sdl-freerdp")
    monkeypatch.setattr(app, "BUNDLED", Path(own))
    monkeypatch.setenv("PATH", str(home / "bin"))
    assert app.find_clients() == [own]
    installed = program(home / "bin" / "sdl-freerdp3")
    found = [os.path.normcase(c) for c in app.find_clients()]
    assert found == [os.path.normcase(own), os.path.normcase(installed)]


def test_auto_passes_over_a_wheel_client_that_cannot_start(make_ui, fake_client, monkeypatch,
                                                          home):
    """The wheel's client first must not block a working installed one, on a
    system that lacks a library it needs."""
    from freerdp_tk import app
    own = program(home / "wheel" / "client" / "sdl-freerdp")
    real = app.probe_client
    monkeypatch.setattr(app, "probe_client",
                        lambda c: (None, "no libpulse.so.0") if c == own else real(c))
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    ui = make_ui()
    ui.clients = [own, ui.clients[0]]  # the fake one stands for the installed client
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")
    click(ui, button(ui, "Connect"))
    pump(ui, fake_client.exists)
    assert errors == [] and fake_client.exists()
    assert ui._resolve_client(app.AUTO) == ui.clients[1]  # the preview agrees


def test_when_no_client_starts_connect_says_why(make_ui, fake_client, monkeypatch, home):
    from freerdp_tk import app
    own = program(home / "wheel" / "client" / "sdl-freerdp")
    monkeypatch.setattr(app, "probe_client", lambda c: (None, "no libpulse.so.0"))
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    ui = make_ui()
    ui.clients = [own, ui.clients[0]]
    assert ui._launch("demo", {"host": "rdp.example.com"}, "s3cret!") is False
    assert len(errors) == 1 and "did not start" in errors[0] and own in errors[0]
    assert not fake_client.exists()


def test_auto_passes_over_an_old_client(make_ui, fake_client, monkeypatch, home):
    from freerdp_tk import app
    own = program(home / "wheel" / "client" / "sdl-freerdp")
    monkeypatch.setattr(app, "BUNDLED", Path(own))
    monkeypatch.setenv("FAKE_VERSION", "2.11.7")
    real = app.probe_client
    monkeypatch.setattr(app, "probe_client", lambda c: (3, "") if c == own else real(c))
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    ui = make_ui()
    old = next(c for c in ui.clients if c != own)  # the fake one, not a real client
    ui.clients = [old, own]  # an old client first, as when the wheel has none of its own
    ui.vars["client"].set(app.AUTO)
    assert ui._resolve_client(app.AUTO) != own  # the preview starts no program to learn it
    ui._ask_versions()
    assert ui._resolve_client(app.AUTO) == own
    assert not errors


def test_a_client_that_cannot_start_says_why(make_ui, fake_client, monkeypatch):
    from freerdp_tk import app
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setattr(app, "probe_client", lambda client: (None, "no libpulse.so.0"))
    ui = make_ui()
    assert ui._launch("demo", {"host": "rdp.example.com"}, None) is False
    assert len(errors) == 1 and "did not start" in errors[0] and "libpulse" in errors[0]


def test_an_old_client_is_refused(make_ui, fake_client, monkeypatch):
    from freerdp_tk import app
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setenv("FAKE_VERSION", "2.11.7")
    ui = make_ui()
    ui.clients = ui.clients[:1]  # the fake one alone: auto would pass over it to a real one
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")
    click(ui, button(ui, "Connect"))
    assert len(errors) == 1 and "is not a FreeRDP 3 client" in errors[0]
    assert not fake_client.exists()  # never started: the password stays off the command line


def test_a_client_of_unknown_version_is_tried(make_ui, fake_client, monkeypatch):
    """A client whose /version cannot be read (too slow on a busy computer, or no
    version in its answer) is started all the same, with a word in the log: unknown
    is not old (kit run 41180196907 refused a FreeRDP 3 client that way)."""
    from freerdp_tk import app
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setenv("FAKE_VERSION", "unknown")
    ui = make_ui()
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")
    click(ui, button(ui, "Connect"))
    pump(ui, fake_client.exists)
    assert errors == [] and fake_client.exists()
    assert "could not tell" in log_text(ui)


def test_auto_asks_an_unknown_client_once(make_ui, fake_client, monkeypatch):
    """Auto with a client it cannot tell: one /version per Connect, not one for auto
    and one more for Connect, since each can wait VERSION_TIMEOUT on the Tk thread."""
    from freerdp_tk import app
    asked = []
    monkeypatch.setattr(app, "probe_client", lambda c: asked.append(c) or (None, ""))
    ui = make_ui()
    ui.clients = ui.clients[:1]
    ui.vars["client"].set(app.AUTO)
    ui._launch("demo", {"host": "rdp.example.com", "client": app.AUTO}, "s3cret!")
    pump(ui, fake_client.exists)
    assert asked == ui.clients and fake_client.exists()
    assert ui.clients[0] not in ui.versions  # unknown is asked again next time


def test_auto_saved_by_an_older_version_is_still_auto(make_ui, fake_client):
    from freerdp_tk import app
    ui = make_ui()
    ui.store.parent.mkdir(parents=True, exist_ok=True)
    ui.store.write_text(json.dumps({"lab": {"host": "h", "client": app.OLD_AUTO}}))
    assert make_ui().saved["lab"]["client"] == app.AUTO


def old_wheel_client(home):
    """The client of an older freerdp-tk, in the folder uvx unpacked that release into."""
    site = home / ".cache" / "uv" / "archive-v0" / "CiSoZQU4" / "lib" / "site-packages"
    return program(site / "freerdp_tk" / "client" / "sdl-freerdp")


def test_a_wheel_client_is_saved_as_auto(home, monkeypatch):
    """Any freerdp-tk's own client, this one's or an older release's, is auto: a path
    into a release's folder would run that release's client after the next upgrade.
    A client the user chose elsewhere stays as chosen."""
    from freerdp_tk import app
    own = program(home / "wheel" / "client" / "sdl-freerdp")
    monkeypatch.setattr(app, "BUNDLED", Path(own))
    for auto in (old_wheel_client(home), own, f" {own} ", "", app.OLD_AUTO, app.AUTO):
        assert app.saved_client(auto) == app.AUTO, auto
    build = program(home / "projects" / "FreeRDP" / "build" / "client" / "SDL" / "SDL3"
                    / "sdl-freerdp")
    for chosen in ("/usr/bin/sdl-freerdp3", "sdl-freerdp3", build,
                   str(home / "freerdp_tk" / "sdl-freerdp")):
        assert app.saved_client(chosen) == chosen


def test_a_client_saved_from_an_older_release_becomes_auto(make_ui, fake_client, home):
    """Seen on macOS (2026-11-12): profiles held the client of 20261106.3 in an old uv
    cache folder; it could not read the server's AV2 and the session closed at once."""
    from freerdp_tk import app
    old = old_wheel_client(home)
    ui = make_ui()
    ui.store.parent.mkdir(parents=True, exist_ok=True)
    ui.store.write_text(json.dumps({"lab": {"host": "h", "client": old},
                                    "mine": {"host": "h", "client": "/usr/bin/sdl-freerdp3"}}))
    again = make_ui()
    assert again.saved["lab"]["client"] == app.AUTO
    assert again.saved["mine"]["client"] == "/usr/bin/sdl-freerdp3"
    log = log_text(again)
    assert f"'lab': its client {old} came with another freerdp-tk" in log
    assert "'mine'" not in log
    again.saved_list.selection_set(again.visible.index("lab"))
    again._on_select()
    assert again.name.get() == "lab"
    assert again.vars["client"].get() == app.AUTO and not again._changed()
    click(again, button(again, "Save"))
    assert json.loads(again.store.read_text())["lab"]["client"] == app.AUTO


def test_choosing_the_wheel_client_saves_auto(make_ui, fake_client, home, monkeypatch):
    """The Client list shows the wheel's client as its path; picking it must not save
    that path, which the next release would leave behind."""
    from freerdp_tk import app
    own = program(home / "wheel" / "client" / "sdl-freerdp")
    monkeypatch.setattr(app, "BUNDLED", Path(own))
    ui = make_ui()
    from tkinter import ttk
    box = next(w for w in widgets(ui) if isinstance(w, ttk.Combobox)
               and own in w.cget("values"))
    box.set(own)
    pump(ui, lambda: ui.vars["client"].get() == own)
    type_into(ui, entry_for(ui, ui.name), "lab")
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    click(ui, button(ui, "Save"))
    assert json.loads(ui.store.read_text())["lab"]["client"] == app.AUTO
    assert ui.vars["client"].get() == app.AUTO and not ui._changed()
    assert ui._resolve_client(app.AUTO) == own  # auto still runs it


def test_the_window_is_called_freerdp_tk(home, monkeypatch):
    """Not "FreeRDP": a window list then shows which window is this one, and the
    session's own window ("FreeRDP: host", which the kit's demo looks for) stays apart."""
    import tkinter as tk
    from freerdp_tk import app
    titles = []

    def instead_of_the_loop(root):
        titles.append(root.title())
        for child in root.winfo_children():
            if isinstance(child, app.App):
                child.keyring.close(timeout=5)
        root.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", instead_of_the_loop)
    app.main()
    assert titles == [f"freerdp-tk {app.__version__}"]


def test_about_shows_the_version_and_the_release_notes(make_ui):
    from tkinter import ttk
    from freerdp_tk import app
    ui = make_ui()
    click(ui, button(ui, "About"))
    pump(ui, lambda: getattr(ui, "about", None) is not None)
    labels = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Label):
                labels.append(child.cget("text"))
            walk(child)

    walk(ui.about)
    assert f"freerdp-tk {app.__version__}" in labels
    assert any(text.startswith("FreeRDP client: ") for text in labels)
    notes = app.show_text(ui.root, "Release notes", app.release_notes())
    text = next(c for c in notes.winfo_children()[0].winfo_children()
                if c.winfo_class() == "Text").get("1.0", "end")
    assert "## 20261107.3" in text
    notes.destroy()
    ui.about.destroy()


def test_a_choice_box_is_found_by_its_choices(make_ui):
    """Outside drivers (the kit's demo, hook/drive.py) find a choice list by its
    values: since 20261107.2 its Combobox shows a display variable of its own, not
    the form variable, so finding it by the form variable fails. In English the
    values are the choices themselves, and setting the box sets the form."""
    from tkinter import ttk
    from freerdp_tk import app
    ui = make_ui()

    def boxes(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Combobox):
                yield child
            yield from boxes(child)

    found = [b for b in boxes(ui.root) if list(b.cget("values")) == app.GFX_CHOICES]
    assert len(found) == 1
    found[0].set("AV2:i444")
    pump(ui, lambda: ui.vars["gfx"].get() == "AV2:i444")


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


def test_several_monitors_as_one_big_screen(make_ui, fake_client):
    """The choice shows in the preview, and a saved connection from before it keeps
    separate screens, the old behaviour."""
    from freerdp_tk import app
    ui = make_ui()
    ui._fill("old", {"host": "h", "multimon": True}, "")
    assert ui.vars["multimon_mode"].get() == app.SEPARATE
    preview = lambda: ui.preview.get("1.0", "end")
    pump(ui, lambda: "/multimon" in preview())
    assert "/span" not in preview()
    ui.vars["multimon_mode"].set(app.ONE_BIG)
    pump(ui, lambda: "/multimon /span" in preview())


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
