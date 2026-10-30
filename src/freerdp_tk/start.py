"""Starts freerdp-tk, first making sure this Python has Tk.

The window is Tk, and a Python without Tk cannot import it. Many Linux
desktops have such a Python (Tk is a package of its own, python3-tk), and
uv takes it when it is there: plain uvx freerdp-tk would end in "No module
named 'tkinter'". Started by uv (it sets $UV), freerdp-tk then starts again
with uv's own Python, which has Tk, as uvx --managed-python does (through
UV_PYTHON_PREFERENCE, which overrides one the user set; the flag would
clash with it); otherwise it says what to install.
"""

import os
import subprocess
import sys

AGAIN = "FREERDP_TK_MANAGED_PYTHON"  # set on the second start: never a third


def has_tk() -> bool:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    return True


def again_with_uv(version: str) -> list[str] | None:
    """The command that starts this freerdp-tk with uv's own Python, or None:
    not started by uv, already tried, or a version that uv cannot fetch by
    number (a source checkout, a build between releases)."""
    uv = os.environ.get("UV")
    numbered = version.replace(".", "").isdigit() and version != "0.0.0"
    if not uv or os.environ.get(AGAIN) or not numbered:
        return None
    return [uv, "tool", "run", "--from", f"freerdp-tk=={version}", "freerdp-tk", *sys.argv[1:]]


def no_tk_message() -> str:
    return (f"freerdp-tk needs Tk, and this Python has none: {sys.executable}\n"
            "Run it with uv's own Python, which has Tk:\n"
            "    uvx --managed-python freerdp-tk\n"
            "or install Tk for this Python: sudo apt install python3-tk (Debian, Ubuntu),\n"
            "sudo dnf install python3-tkinter (Fedora), brew install python-tk (Homebrew).")


def main():
    if not has_tk():
        from freerdp_tk import __version__
        command = again_with_uv(__version__)
        if command is None:
            sys.exit(no_tk_message())
        print("freerdp-tk: this Python has no Tk; starting again with uv's own Python",
              file=sys.stderr)
        os.environ[AGAIN] = "1"
        os.environ["UV_PYTHON_PREFERENCE"] = "only-managed"
        if os.name == "posix":
            os.execv(command[0], command)
        sys.exit(subprocess.call(command))
    from freerdp_tk.app import main as start_window
    start_window()
