"""Render the README screenshot with demo data.

Run it in a virtual X server, so nothing from your own desktop, hosts or
saved connections ends up in the picture:

    xvfb-run -s "-screen 0 1400x1000x24" \
        uv run --with pillow --with-editable . python scripts/screenshot.py docs/screenshot.png
"""

import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()  # keep real profiles out of it

from PIL import ImageGrab  # noqa: E402

from freerdp_tk import app  # noqa: E402

DEMO_CLIENTS = ["/usr/bin/sdl-freerdp3", "/usr/bin/xfreerdp3", "/usr/bin/wlfreerdp3"]
DEMO = {
    "build-server": {"host": "192.0.2.10", "user": "ci", "gfx": "AVC444"},
    "lab-windows-11": {"host": "192.0.2.21", "user": "alice", "domain": "LAB",
                       "gfx": "AV1:i444", "drive": "/home/alice/shared"},
    "lab-windows-server": {"host": "192.0.2.22", "user": "alice", "domain": "LAB"},
    "media-pc": {"host": "media.example.net", "user": "alice", "fullscreen": True},
    "office-desktop": {"host": "rdp.example.com", "user": "alice", "gateway": "gw.example.com",
                       "multimon": True},
}
SELECTED = "lab-windows-11"
LOG = [
    "[lab-windows-server [4211]] started: /usr/bin/sdl-freerdp3 /v:192.0.2.22 /u:alice /d:LAB "
    "'/p:********' /cert:tofu /size:1600x900 /dynamic-resolution +clipboard /sound",
    "[lab-windows-server [4211]] [INFO][com.freerdp.client.sdl] - connected to 192.0.2.22:3389",
    "[lab-windows-server [4211]] [INFO][com.freerdp.channels.rdpgfx] - using codec AVC444v2",
]


def main(out: str):
    app.find_clients = lambda: list(DEMO_CLIENTS)
    root = tk.Tk()
    root.title("FreeRDP")
    style = tk.ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    ui = app.App(root)
    ui.saved = {name: {**app.FIELDS, **v} for name, v in DEMO.items()}
    ui._refresh_saved(select=SELECTED)
    ui._on_select()
    ui.password.set("demo-password")
    ui.running_list.insert("end", "lab-windows-server [4211]")
    ui.log.delete("1.0", "end")
    ui.log.insert("end", "\n".join(LOG) + "\n")
    root.geometry("1000x600+0+0")

    def shoot():
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        box = (x, y, x + root.winfo_width(), y + root.winfo_height())
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        ImageGrab.grab(bbox=box).save(out, optimize=True)
        print(f"wrote {out} ({box[2] - box[0]}x{box[3] - box[1]})")
        root.destroy()

    root.after(800, shoot)
    root.mainloop()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshot.png")
