"""Changes in the form: what shows them, and what happens to them on the way out."""

import json

import pytest

from freerdp_tk import app
from helpers import (button, click, entry_for, has_xdotool, pump, settle, type_into, widgets,
                     xdo_click)


def must_not_ask(*_):
    raise AssertionError("asked about unsaved changes")


def answer_with(choice, asked=None):
    def ask(root, question, changed):
        if asked is not None:
            asked.append((question, changed))
        return choice
    return ask


@pytest.fixture
def ui(make_ui, fake_client):
    """A window with two saved connections, showing lab."""
    window = make_ui()
    for name, host in (("office", "office.example.com"), ("lab", "rdp.example.com")):
        window.name.set(name)
        window.vars["host"].set(host)
        click(window, button(window, "Save"))
    settle(window)
    assert not window._changed() and window.current == "lab"
    return window


def label(ui, text):
    return next(w for w in widgets(ui) if w.winfo_class() in ("TLabel", "TCheckbutton")
                and w.cget("text") == text)


def lit(ui, text) -> bool:
    return label(ui, text).cget("style").startswith("Changed.")


def tab_titles(ui):
    return [ui.tabs.tab(t, "text") for t in ui.tabs.tabs()]


def pick(ui, name):
    ui.saved_list.selection_clear(0, "end")
    ui.saved_list.selection_set(ui.visible.index(name))
    ui._on_select()


def on_disk(ui):
    return json.loads(ui.store.read_text())


def test_a_change_lights_up_and_can_be_typed_away(ui):
    assert not lit(ui, "Port")
    assert ui.change_note.cget("text") == "" and ui.reset_button.instate(["disabled"])
    type_into(ui, entry_for(ui, ui.vars["port"]), "3390")
    assert lit(ui, "Port") and not lit(ui, "Host")
    assert ui.change_note.cget("text") == "1 unsaved change"
    assert ui.reset_button.instate(["!disabled"])
    assert tab_titles(ui)[0] == "Connection *"
    row = ui.visible.index("lab")
    assert ui.saved_list.itemcget(row, "selectbackground") == app.CHANGED
    assert ui.saved_list.get(row) == "lab"  # a name to compare, not to decorate
    ui.vars["port"].set("")  # back as it was: nothing left to save
    assert not lit(ui, "Port") and ui.change_note.cget("text") == ""
    assert tab_titles(ui)[0] == "Connection"
    assert ui.saved_list.itemcget(row, "selectbackground") == ""


def test_the_tab_of_a_field_out_of_sight_says_so(ui):
    ui.vars["fullscreen"].set(True)
    ui.vars["pre_wait"].set("127.0.0.1:%L")
    assert lit(ui, "Full screen") and lit(ui, "Then wait until")
    assert tab_titles(ui) == ["Connection", "Display *", "Devices", "Before / after *", "Advanced"]
    assert ui.change_note.cget("text") == "2 unsaved changes"


def test_every_field_shows_up_somewhere(ui):
    marked = set().union(*(keys for _, keys in ui.marks))
    assert marked == {"name", "password", *app.FIELDS}


def test_a_typed_password_counts_but_is_never_named(ui, monkeypatch):
    asked = []
    monkeypatch.setattr(app, "ask_unsaved", answer_with(None, asked))
    ui.password.set("s3cret!")
    assert lit(ui, "Password")
    pick(ui, "office")
    assert asked == [("Save the changes to lab?", ["Password"])]


def test_reset_goes_back_to_what_is_saved(ui):
    ui.passwords["lab"] = "known"
    pick(ui, "office")
    pick(ui, "lab")
    ui.name.set("renamed")
    ui.vars["host"].set("elsewhere.example.com")
    ui.vars["clipboard"].set(False)
    ui.password.set("typed")
    click(ui, ui.reset_button)
    assert ui.name.get() == "lab" and ui.vars["host"].get() == "rdp.example.com"
    assert ui.vars["clipboard"].get() is True and ui.password.get() == "known"
    assert not ui._changed() and ui.reset_button.instate(["disabled"])
    assert on_disk(ui)["lab"]["host"] == "rdp.example.com"


def test_reset_on_a_new_connection_empties_it(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    ui.new_menu.invoke(0)
    ui.vars["host"].set("draft.example.com")
    click(ui, ui.reset_button)
    assert ui.vars["host"].get() == "" and not ui._changed()


def test_switching_without_changes_asks_nothing(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    pick(ui, "office")
    assert ui.vars["host"].get() == "office.example.com"


def test_discard_drops_the_changes(ui, monkeypatch):
    asked = []
    monkeypatch.setattr(app, "ask_unsaved", answer_with("discard", asked))
    ui.vars["port"].set("3390")
    ui.vars["sound"].set(False)
    pick(ui, "office")
    assert asked == [("Save the changes to lab?", ["Port", "Play remote sound here"])]
    assert ui.vars["host"].get() == "office.example.com" and ui.vars["port"].get() == ""
    assert not ui._changed() and ui.current == "office"
    assert on_disk(ui)["lab"]["port"] == ""


def test_save_keeps_them_and_still_switches(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", answer_with("save"))
    ui.vars["port"].set("3390")
    pick(ui, "office")
    assert on_disk(ui)["lab"]["port"] == "3390"
    assert ui.vars["host"].get() == "office.example.com" and ui.current == "office"
    assert ui._selected_names() == ["office"]


def test_cancel_stays_with_the_changes(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", answer_with(None))
    ui.vars["port"].set("3390")
    pick(ui, "office")
    assert ui.vars["host"].get() == "rdp.example.com" and ui.vars["port"].get() == "3390"
    assert ui.current == "lab" and ui._selected_names() == ["lab"]
    assert lit(ui, "Port")


def test_a_failed_save_stays(ui, monkeypatch):
    errors = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda title, text: errors.append(text))
    monkeypatch.setattr(app, "ask_unsaved", answer_with("save"))
    ui.new_menu.invoke(0)
    ui.vars["port"].set("3390")  # neither a name nor a host to save it under
    pick(ui, "office")
    assert errors and ui.current is None and ui.vars["port"].get() == "3390"


def test_clicking_the_one_in_the_form_keeps_the_edits(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    ui.vars["port"].set("3390")
    pick(ui, "lab")
    assert ui.vars["port"].get() == "3390"


def test_selecting_several_leaves_the_form_alone(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    ui.vars["port"].set("3390")
    ui.saved_list.selection_set(0, "end")
    ui._on_select()
    assert ui.vars["port"].get() == "3390" and ui.current == "lab"


def test_filtering_keeps_the_selection(ui):
    ui.filter.set("rdp")
    assert ui._selected_names() == ["lab"]
    ui.filter.set("")
    assert ui._selected_names() == ["lab"]


def test_new_asks_too(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", answer_with(None))
    ui.vars["port"].set("3390")
    ui.new_menu.invoke(0)
    assert ui.vars["host"].get() == "rdp.example.com"  # cancelled
    monkeypatch.setattr(app, "ask_unsaved", answer_with("discard"))
    ui.new_menu.invoke(0)
    assert ui.vars["host"].get() == "" and ui.current is None and ui._selected_names() == []


def test_a_new_connection_is_asked_about_as_new(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    ui.new_menu.invoke(0)
    pick(ui, "office")  # an empty form has nothing to lose
    ui.new_menu.invoke(0)
    ui.vars["host"].set("draft.example.com")
    asked = []
    monkeypatch.setattr(app, "ask_unsaved", answer_with("save", asked))
    pick(ui, "lab")
    assert asked == [("Save this new connection?", ["Host"])]
    assert on_disk(ui)["draft.example.com"]["host"] == "draft.example.com"
    assert ui.current == "lab"


def test_copy_starts_a_new_connection_from_this_one(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    ui.new_menu.invoke(1)
    assert ui.name.get() == "lab copy" and ui.vars["host"].get() == "rdp.example.com"
    assert ui.current is None and ui._selected_names() == []
    assert ui.change_note.cget("text") == "Not saved yet"
    assert "lab copy" not in on_disk(ui)
    click(ui, button(ui, "Save"))
    assert on_disk(ui)["lab copy"]["host"] == "rdp.example.com"
    assert ui._selected_names() == ["lab copy"]


def test_a_copy_takes_the_edits_and_leaves_the_original_as_saved(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    ui.vars["port"].set("3390")
    ui.new_menu.invoke(1)
    assert ui.vars["port"].get() == "3390" and lit(ui, "Port")
    assert on_disk(ui)["lab"]["port"] == ""
    click(ui, ui.reset_button)  # back to what lab holds, still as the copy
    assert ui.vars["port"].get() == "" and ui.name.get() == "lab copy"


def test_an_untouched_copy_is_not_worth_a_question(ui, monkeypatch):
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    ui.new_menu.invoke(1)
    pick(ui, "office")
    assert ui.current == "office" and "lab copy" not in on_disk(ui)


def test_copies_get_names_of_their_own(ui):
    ui.new_menu.invoke(1)
    click(ui, button(ui, "Save"))
    pick(ui, "lab")
    ui.new_menu.invoke(1)
    assert ui.name.get() == "lab copy 2"


def test_copying_an_empty_form_does_nothing(ui):
    ui.new_menu.invoke(0)
    ui.new_menu.invoke(1)
    assert ui.name.get() == "" and not ui._changed()


def test_deleting_the_one_in_the_form_empties_it(ui, monkeypatch):
    monkeypatch.setattr(app.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(app, "ask_unsaved", must_not_ask)
    click(ui, button(ui, "Delete"))
    assert ui.current is None and ui.vars["host"].get() == "" and not ui._changed()
    pick(ui, "office")


def test_connecting_keeps_a_typed_password_so_it_stops_counting(ui, fake_client):
    ui.password.set("s3cret!")
    assert ui._changed() == {"password"}
    click(ui, button(ui, "Connect"))
    pump(ui, lambda: fake_client.exists() and ui.running_list.size() == 0)
    settle(ui)
    assert not ui._changed()


def test_forget_is_not_a_change(ui):
    ui.vars["user"].set("alice")
    click(ui, button(ui, "Save"))
    ui.password.set("s3cret!")
    click(ui, button(ui, "Save"))
    click(ui, button(ui, "Forget"))
    settle(ui)
    assert not ui._changed()


def test_closing_the_window_asks_too(ui, monkeypatch):
    closed = []
    monkeypatch.setattr(ui.root, "destroy", lambda: closed.append(True))
    monkeypatch.setattr(app, "ask_unsaved", answer_with(None))
    ui.vars["port"].set("3390")
    ui._quit()
    assert not closed
    monkeypatch.setattr(app, "ask_unsaved", answer_with("save"))
    ui._quit()
    assert closed and on_disk(ui)["lab"]["port"] == "3390"


def dialog_button(ui, text):
    return next(w for w in widgets(ui) if w.winfo_class() == "TButton"
                and w.cget("text") == text and w.winfo_toplevel() is not ui.root)


def when_the_dialog_is_up(ui, press, text):
    """Press a button of the dialog; the event loop runs next inside its wait."""
    def poll():
        try:
            target = dialog_button(ui, text)
            if not target.winfo_viewable():
                raise StopIteration
        except StopIteration:
            ui.root.after(20, poll)
            return
        press(ui, target)
    ui.root.after(20, poll)


@pytest.mark.parametrize("text, expected", [("Save", "save"), ("Discard", "discard"),
                                            ("Cancel", None)])
def test_the_dialog(ui, text, expected):
    when_the_dialog_is_up(ui, click, text)
    assert app.ask_unsaved(ui.root, "Save the changes to lab?", ["Port"]) == expected


def test_clicking_a_row_with_tk_events(ui):
    ui.vars["port"].set("3390")
    row = ui.visible.index("office")
    x, y, width, height = ui.saved_list.bbox(row)
    when_the_dialog_is_up(ui, click, "Discard")
    ui.saved_list.event_generate("<ButtonPress-1>", x=x + width // 2, y=y + height // 2)
    ui.saved_list.event_generate("<ButtonRelease-1>", x=x + width // 2, y=y + height // 2)
    pump(ui, lambda: ui.current == "office")
    assert ui.vars["port"].get() == ""


@pytest.mark.skipif(not has_xdotool(), reason="needs xdotool")
def test_clicking_a_row_with_the_x_pointer(ui):
    # the dialog opens inside the press of a real click: its grab has to take over
    # from the pointer grab the X server holds until the release
    import subprocess
    ui.vars["port"].set("3390")
    x, y, width, height = ui.saved_list.bbox(ui.visible.index("office"))
    at = ui.saved_list.winfo_rootx() + x + width // 2, ui.saved_list.winfo_rooty() + y + height // 2
    when_the_dialog_is_up(ui, xdo_click, "Cancel")
    subprocess.run(["xdotool", "mousemove", "--sync", *map(str, at), "click", "1"], check=True)
    pump(ui, lambda: not [w for w in widgets(ui) if w.winfo_class() == "Toplevel"]
         and ui._selected_names() == ["lab"])
    assert ui.vars["port"].get() == "3390" and ui.current == "lab"
