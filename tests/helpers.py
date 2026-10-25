"""Drive the freerdp-tk window from a test.

Two ways to act on a widget, from the inside out:
- Tk events (type_into, click): event_generate delivers key and mouse events
  straight to one widget, through the same class bindings a user's input hits.
  No pointer is involved; the widget is the target, x/y are relative to it.
- X events (xdo_type, xdo_click): xdotool moves the real X pointer to screen
  coordinates and clicks there. The X server, not the test, decides which
  window gets the click, so the widget's position on screen has to be known.
  Tk reports it: winfo_rootx/rooty is the widget's top-left corner on screen.
"""

import shutil
import subprocess
import time
import tkinter as tk

KEYSYMS = {".": "period", "-": "minus", "@": "at", "!": "exclam", " ": "space", ":": "colon"}


def pump(ui, until, timeout=15.0):
    """Run the Tk event loop by hand until until() holds."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        ui.root.update()
        if until():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out; log so far:\n{log_text(ui)}")


def widgets(ui):
    todo = [ui.root]
    while todo:
        w = todo.pop()
        todo += w.winfo_children()
        yield w


def entry_for(ui, var) -> tk.Widget:
    """The entry bound to a Tk variable: find a field by what it holds, not where it is."""
    for w in widgets(ui):
        if w.winfo_class() in ("TEntry", "Entry") and w.cget("textvariable") == str(var):
            return w
    raise LookupError(var)


def button(ui, text) -> tk.Widget:
    """The button labelled text, as a user would find it."""
    for w in widgets(ui):
        if w.winfo_class() in ("TButton", "Button") and w.cget("text") == text:
            return w
    raise LookupError(text)


def log_text(ui) -> str:
    return ui.log.get("1.0", "end")


def type_into(ui, widget, text):
    widget.focus_force()
    ui.root.update()
    for ch in text:
        widget.event_generate("<KeyPress>", keysym=KEYSYMS.get(ch, ch))
    ui.root.update()


def click(ui, widget):
    """Press and release button 1 in the middle of the widget (widget-relative x/y)."""
    x, y = widget.winfo_width() // 2, widget.winfo_height() // 2
    widget.event_generate("<Enter>", x=x, y=y)
    widget.event_generate("<ButtonPress-1>", x=x, y=y)
    widget.event_generate("<ButtonRelease-1>", x=x, y=y)
    ui.root.update()


def screen_center(widget) -> tuple[int, int]:
    """Where the widget's middle is on the screen, in X pixels."""
    widget.update_idletasks()
    return (widget.winfo_rootx() + widget.winfo_width() // 2,
            widget.winfo_rooty() + widget.winfo_height() // 2)


def has_xdotool() -> bool:
    return shutil.which("xdotool") is not None


def xdo_click(ui, widget):
    x, y = screen_center(widget)
    hit = ui.root.winfo_containing(x, y)  # Tk's own hit test at that screen point
    if hit is not widget:
        raise AssertionError(f"{widget} is not at screen point {x},{y} ({hit} is; screen "
                             f"{ui.root.winfo_screenwidth()}x{ui.root.winfo_screenheight()})")
    subprocess.run(["xdotool", "mousemove", "--sync", str(x), str(y), "click", "1"], check=True)
    ui.root.update()


def xdo_type(ui, widget, text):
    xdo_click(ui, widget)  # a click gives the entry the keyboard focus
    subprocess.run(["xdotool", "type", "--delay", "5", text], check=True)
    ui.root.update()
