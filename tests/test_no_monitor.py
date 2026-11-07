"""A desktop with no monitor (a GNOME session whose remote session is gone: its
Xwayland screen is 0x0, and on Wayland SDL adds no display) gives the client
nowhere to show the remote desktop. FreeRDP's SDL client then exits with 255 and
says nothing; Connect says why instead."""

from freerdp_tk import app
from helpers import button, click, entry_for, log_text, pump, type_into


def connect(ui):
    type_into(ui, entry_for(ui, ui.vars["host"]), "rdp.example.com")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")
    click(ui, button(ui, "Connect"))


def zero_screen(ui, monkeypatch):
    monkeypatch.setattr(ui, "winfo_screenwidth", lambda: 0)
    monkeypatch.setattr(ui, "winfo_screenheight", lambda: 0)


def test_no_monitor_is_refused_and_says_why(make_ui, fake_client, monkeypatch):
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setenv("FAKE_MONITORS", "listing 0 monitors:")
    ui = make_ui()
    zero_screen(ui, monkeypatch)
    connect(ui)
    assert len(errors) == 1 and "no monitor" in errors[0] and "0x0" in errors[0]
    assert not fake_client.exists()  # never started


def test_a_screen_tk_saw_as_0x0_but_with_a_monitor_now_connects(make_ui, fake_client,
                                                                 monkeypatch):
    """Tk can keep the 0x0 it saw at start after a monitor came: the client's own
    /list:monitor decides."""
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    ui = make_ui()
    zero_screen(ui, monkeypatch)
    connect(ui)
    pump(ui, fake_client.exists)
    assert errors == [] and fake_client.exists()


def test_a_screen_with_a_size_starts_no_monitor_listing(make_ui, fake_client, monkeypatch):
    asked = []
    monkeypatch.setattr(app, "list_monitors", lambda client: asked.append(client) or ([], ""))
    ui = make_ui()
    monkeypatch.setattr(ui, "winfo_screenwidth", lambda: 1280)
    monkeypatch.setattr(ui, "winfo_screenheight", lambda: 800)
    connect(ui)
    pump(ui, fake_client.exists)
    assert asked == []  # the usual case costs no process


def test_a_wordless_255_is_explained(make_ui, fake_client, monkeypatch):
    monkeypatch.setenv("FAKE_255", "silent")
    ui = make_ui()
    connect(ui)
    pump(ui, lambda: "exited with code 255" in log_text(ui))
    pump(ui, lambda: "without a word" in log_text(ui))
    assert "no monitor" in log_text(ui)


def test_a_255_with_words_is_left_alone(make_ui, fake_client, monkeypatch):
    monkeypatch.setenv("FAKE_255", "said")
    ui = make_ui()
    connect(ui)
    pump(ui, lambda: "exited with code 255" in log_text(ui))
    assert "without a word" not in log_text(ui)
