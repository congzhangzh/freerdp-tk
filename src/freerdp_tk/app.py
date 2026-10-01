"""The freerdp-tk window: a small Tkinter launcher for the FreeRDP command-line clients.

Runs on Linux, Windows and macOS with nothing but the Python standard library.
It keeps a list of saved connections (never passwords), builds a FreeRDP
command line from a form and shows each client's output in a log pane.

The "(auto)" client picks the best client found, preferring the SDL client.
On FreeRDP 3 the arguments are piped in with /args-from:stdin, so the
password never shows up in the process list. FreeRDP 2 has no such option
and gets /p:<password> on the command line instead.
"""

import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

APP = "freerdp-tk"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
EXE = ".exe" if IS_WIN else ""
AUTO = "(auto: prefer SDL)"

# Client flavours, best first. The SDL client is the actively developed,
# cross-platform one, so it wins whenever it is available.
KINDS = ["sdl3", "sdl", "sdl2", "x11", "wayland", "windows", "other"]
CLIENT_NAMES = ["sdl-freerdp3", "sdl3-freerdp3", "sdl3-freerdp", "sdl-freerdp", "sdl2-freerdp3",
                "sdl2-freerdp", "xfreerdp3", "xfreerdp", "wlfreerdp3", "wlfreerdp", "wfreerdp"]
BUILD_GLOBS = ["client/SDL/SDL3/*freerdp*", "client/SDL/SDL2/*freerdp*", "client/X11/xfreerdp*",
               "client/Wayland/wlfreerdp*", "client/Windows/wfreerdp*"]
GFX_CHOICES = ["(default)", "off", "AVC444", "AVC420", "RFX", "progressive", "AV1:i444",
               "AV1:i420"]
CERT_CHOICES = ["tofu", "ignore", "deny"]
LOG_LEVELS = ["(default)", "OFF", "FATAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"]
HIDDEN = "********"

FIELDS = {  # name -> default; everything a saved connection stores
    "client": AUTO, "host": "", "port": "", "user": "", "domain": "", "gateway": "",
    "cert": "tofu", "fullscreen": False, "size": "1600x900", "dynamic": True,
    "multimon": False, "gfx": "(default)", "clipboard": True, "sound": True,
    "microphone": False, "home_drive": False, "drive": "", "log_level": "(default)",
    "extra": "",
}


def config_dir() -> Path:
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP


def client_kind(path: str) -> str:
    name = Path(path).name.lower()
    for kind, marker in (("sdl3", "sdl3"), ("sdl2", "sdl2"), ("sdl", "sdl"), ("x11", "xfreerdp"),
                         ("wayland", "wlfreerdp"), ("windows", "wfreerdp")):
        if marker in name:
            return kind
    return "other"


def find_clients() -> list[str]:
    """Clients on PATH and in local FreeRDP build trees, best first.

    Build trees are searched in ~/projects/FreeRDP and in every source tree
    listed in $FREERDP_TK_TREES (separated like PATH).
    """
    found = [p for p in (shutil.which(n) for n in CLIENT_NAMES) if p]
    trees = [Path.home() / "projects" / "FreeRDP"]
    extra = os.environ.get("FREERDP_TK_TREES", "").split(os.pathsep)
    trees += [Path(t).expanduser() for t in extra if t]
    for tree in dict.fromkeys(trees):
        for build in sorted(tree.glob("build*")):
            for pattern in BUILD_GLOBS:
                for path in sorted(build.glob(pattern)):
                    if path.is_file() and os.access(path, os.X_OK) and path.suffix in ("", EXE):
                        found.append(str(path))
    unique = list(dict.fromkeys(found))
    return sorted(unique, key=lambda p: KINDS.index(client_kind(p)))  # stable: PATH first


def client_major_version(client: str) -> int:
    """Major FreeRDP version of a client, 0 when it cannot be told."""
    try:
        out = subprocess.run([client, "/version"], capture_output=True, text=True, timeout=5,
                             **no_console()).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    match = re.search(r"version (\d+)\.", out)
    return int(match.group(1)) if match else 0


def no_console() -> dict:
    """Keep Windows from opening a console window for every child process."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}


def build_args(v: dict, password: str) -> list[str]:
    """Client arguments for the connection settings v, without the program name."""
    v = {**FIELDS, **v}
    args = [f"/v:{v['host'].strip()}"]
    if v["port"].strip():
        args.append(f"/port:{v['port'].strip()}")
    if v["user"].strip():
        args.append(f"/u:{v['user'].strip()}")
    if v["domain"].strip():
        args.append(f"/d:{v['domain'].strip()}")
    if password:
        args.append(f"/p:{password}")
    if v["gateway"].strip():
        args.append(f"/gateway:g:{v['gateway'].strip()}")
    args.append(f"/cert:{v['cert']}")
    if v["fullscreen"]:
        args.append("/f")
    elif v["size"].strip():
        args.append(f"/size:{v['size'].strip()}")
    if v["dynamic"]:
        args.append("/dynamic-resolution")
    if v["multimon"]:
        args.append("/multimon")
    if v["gfx"] == "off":
        args.append("-gfx")
    elif v["gfx"] != "(default)":
        args.append(f"/gfx:{v['gfx']}")
    args.append("+clipboard" if v["clipboard"] else "-clipboard")
    if v["sound"]:
        args.append("/sound")
    if v["microphone"]:
        args.append("/microphone")
    if v["home_drive"]:
        args.append("+home-drive")
    if v["drive"].strip():
        path = v["drive"].strip()
        args.append(f"/drive:{Path(path).name or 'share'},{path}")
    if v["log_level"] != "(default)":
        args.append(f"/log-level:{v['log_level']}")
    return args + shlex.split(v["extra"], posix=not IS_WIN)


def join_command(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if IS_WIN else shlex.join(argv)


class Session:
    """One running client, with a thread that forwards its output to a queue."""

    def __init__(self, label: str, proc: subprocess.Popen, out: queue.Queue):
        self.label = label
        self.proc = proc
        threading.Thread(target=self._pump, args=(out,), daemon=True).start()

    def _pump(self, out: queue.Queue):
        for line in self.proc.stdout:
            out.put((self, line.rstrip("\n")))
        out.put((self, None))


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=8)
        self.root = root
        self.vars = {k: tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=v)
                     for k, v in FIELDS.items()}
        self.name = tk.StringVar()
        self.password = tk.StringVar()
        self.filter = tk.StringVar()
        self.store = config_dir() / "profiles.json"
        self.saved = self._load_saved()
        self.passwords: dict[str, str] = {}  # per saved connection, memory only
        self.sessions: list[Session] = []
        self.output: queue.Queue = queue.Queue()
        self.versions: dict[str, int] = {}
        self.clients = find_clients()

        self._build()
        self.pack(fill="both", expand=True)
        for var in (*self.vars.values(), self.password):
            var.trace_add("write", lambda *_: self._refresh_preview())
        self.filter.trace_add("write", lambda *_: self._refresh_saved())
        self._refresh_saved()
        self._refresh_preview()
        self._log(f"clients found: {', '.join(self.clients) or 'none'}")
        self.after(100, self._drain_output)
        root.protocol("WM_DELETE_WINDOW", self._quit)

    # ---- layout -----------------------------------------------------------

    def _build(self):
        upper = ttk.Frame(self)
        upper.pack(fill="x")

        side = ttk.Frame(upper)
        side.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(side, text="Saved connections").pack(anchor="w")
        ttk.Entry(side, textvariable=self.filter).pack(fill="x", pady=(2, 4))
        self.saved_list = tk.Listbox(side, width=26, height=14, selectmode="extended",
                                     exportselection=False)
        self.saved_list.pack(fill="both", expand=True)
        self.saved_list.bind("<<ListboxSelect>>", lambda _: self._on_select())
        self.saved_list.bind("<Double-Button-1>", lambda _: self._connect())
        row = ttk.Frame(side)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="New", width=6, command=self._new).pack(side="left")
        ttk.Button(row, text="Save", width=6, command=self._save).pack(side="left", padx=2)
        ttk.Button(row, text="Delete", width=6, command=self._delete).pack(side="left")

        tabs = ttk.Notebook(upper)
        tabs.pack(side="left", fill="both", expand=True)
        tabs.add(self._connection_tab(tabs), text="Connection")
        tabs.add(self._display_tab(tabs), text="Display")
        tabs.add(self._devices_tab(tabs), text="Devices")
        tabs.add(self._advanced_tab(tabs), text="Advanced")

        ttk.Label(self, text="Command").pack(anchor="w", pady=(8, 0))
        self.preview = tk.Text(self, height=3, wrap="word", relief="flat",
                               background=self.root.cget("background"))
        self.preview.pack(fill="x")

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=6)
        self.connect_button = ttk.Button(buttons, text="Connect", command=self._connect)
        self.connect_button.pack(side="left")
        ttk.Button(buttons, text="Disconnect", command=self._disconnect).pack(side="left", padx=4)
        ttk.Button(buttons, text="Copy command", command=self._copy_command).pack(side="left")
        ttk.Button(buttons, text="Clear log",
                   command=lambda: self.log.delete("1.0", "end")).pack(side="right")

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        ttk.Label(left, text="Running").pack(anchor="w")
        self.running_list = tk.Listbox(left, width=26, selectmode="extended",
                                       exportselection=False)
        self.running_list.pack(fill="both", expand=True)
        panes.add(left, weight=0)
        right = ttk.Frame(panes)
        ttk.Label(right, text="Log").pack(anchor="w")
        self.log = tk.Text(right, height=10, wrap="none", font="TkFixedFont")
        scroll = ttk.Scrollbar(right, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)
        panes.add(right, weight=1)

        self.root.bind("<Return>", lambda _: self._connect())

    def _grid(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=8)
        frame.columnconfigure(1, weight=1)
        return frame

    def _row(self, frame, row, label, widget):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="ew", pady=2)

    def _check(self, frame, row, label, key):
        ttk.Checkbutton(frame, text=label, variable=self.vars[key]).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2)

    def _connection_tab(self, parent):
        f = self._grid(parent)
        self._row(f, 0, "Name", ttk.Entry(f, textvariable=self.name))
        client = ttk.Frame(f)
        ttk.Combobox(client, textvariable=self.vars["client"], values=[AUTO, *self.clients]).pack(
            side="left", fill="x", expand=True)
        ttk.Button(client, text="…", width=3, command=self._browse_client).pack(side="left")
        self._row(f, 1, "Client", client)
        host = ttk.Entry(f, textvariable=self.vars["host"])
        self._row(f, 2, "Host", host)
        host.focus_set()
        self._row(f, 3, "Port", ttk.Entry(f, textvariable=self.vars["port"], width=8))
        self._row(f, 4, "User", ttk.Entry(f, textvariable=self.vars["user"]))
        self._row(f, 5, "Domain", ttk.Entry(f, textvariable=self.vars["domain"]))
        self._row(f, 6, "Password", ttk.Entry(f, textvariable=self.password, show="•"))
        self._row(f, 7, "Gateway", ttk.Entry(f, textvariable=self.vars["gateway"]))
        self._row(f, 8, "Certificate", ttk.Combobox(f, textvariable=self.vars["cert"],
                                                    values=CERT_CHOICES, state="readonly"))
        return f

    def _display_tab(self, parent):
        f = self._grid(parent)
        self._check(f, 0, "Full screen", "fullscreen")
        self._row(f, 1, "Window size", ttk.Combobox(
            f, textvariable=self.vars["size"],
            values=["1280x720", "1600x900", "1920x1080", "2560x1440", "80%", "100%"]))
        self._check(f, 2, "Resize the remote desktop with the window", "dynamic")
        self._check(f, 3, "Use all monitors", "multimon")
        self._row(f, 4, "Graphics codec", ttk.Combobox(f, textvariable=self.vars["gfx"],
                                                       values=GFX_CHOICES, state="readonly"))
        return f

    def _devices_tab(self, parent):
        f = self._grid(parent)
        self._check(f, 0, "Clipboard", "clipboard")
        self._check(f, 1, "Play remote sound here", "sound")
        self._check(f, 2, "Microphone", "microphone")
        self._check(f, 3, "Share home folder", "home_drive")
        drive = ttk.Frame(f)
        ttk.Entry(drive, textvariable=self.vars["drive"]).pack(side="left", fill="x", expand=True)
        ttk.Button(drive, text="…", width=3, command=self._browse_drive).pack(side="left")
        self._row(f, 4, "Share folder", drive)
        return f

    def _advanced_tab(self, parent):
        f = self._grid(parent)
        self._row(f, 0, "Log level", ttk.Combobox(f, textvariable=self.vars["log_level"],
                                                  values=LOG_LEVELS, state="readonly"))
        self._row(f, 1, "Extra arguments", ttk.Entry(f, textvariable=self.vars["extra"]))
        ttk.Label(f, text="e.g.  /scale:140 +auto-reconnect /kbd:layout:0x409",
                  foreground="gray").grid(row=2, column=1, sticky="w")
        return f

    # ---- command line -----------------------------------------------------

    def _form(self) -> dict:
        return {k: var.get() for k, var in self.vars.items()}

    def _resolve_client(self, choice: str) -> str:
        """The program to run for a client choice; "" when there is none."""
        choice = choice.strip()
        if choice in ("", AUTO):
            return self.clients[0] if self.clients else ""
        return choice if shutil.which(choice) or Path(choice).is_file() else ""

    def _command_text(self) -> str:
        v = self._form()
        client = self._resolve_client(v["client"]) or "<no client found>"
        try:
            args = build_args(v, HIDDEN if self.password.get() else "")
        except ValueError as e:  # unbalanced quotes in the extra arguments
            return f"error in extra arguments: {e}"
        return join_command([client, *args])

    def _refresh_preview(self):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", self._command_text())
        self.preview.configure(state="disabled")

    def _copy_command(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self._command_text())
        self._log("command copied (password hidden)")

    # ---- sessions ---------------------------------------------------------

    def _connect(self):
        names = self._selected_names()
        if len(names) > 1:  # several saved connections: start each one as saved
            for name in names:
                if not self._launch(name, self.saved[name], self.passwords.get(name)):
                    break
            return
        name = self.name.get().strip() or self.vars["host"].get().strip()
        password = self.password.get() or self.passwords.get(name)
        if self._launch(name, self._form(), password) and self.password.get():
            self.passwords[name] = self.password.get()

    def _launch(self, name: str, v: dict, password: str | None) -> bool:
        """Start one client; False when it did not start and the user was told why."""
        v = {**FIELDS, **v}
        client = self._resolve_client(v["client"])
        if not client:
            messagebox.showerror(APP, f"{name}: no FreeRDP client found. Choose one under "
                                      "Connection → Client.")
            return False
        if not v["host"].strip():
            messagebox.showerror(APP, "Enter a host to connect to.")
            return False
        if password is None and v["user"].strip():
            password = simpledialog.askstring(APP, f"Password for {v['user']} on {name}",
                                              show="•", parent=self.root)
            if password is None:
                return False
            self.passwords[name] = password
        try:
            args = build_args(v, password or "")
        except ValueError as e:
            messagebox.showerror(APP, f"{name}: extra arguments: {e}")
            return False
        if any("\n" in a or "\r" in a for a in args):
            messagebox.showerror(APP, f"{name}: values must not contain line breaks.")
            return False

        if client not in self.versions:
            self.versions[client] = client_major_version(client)
        via_stdin = self.versions[client] >= 3
        argv = [client, "/args-from:stdin"] if via_stdin else [client, *args]
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace",
                                    **no_console())
        except OSError as e:
            messagebox.showerror(APP, f"Cannot start {client}:\n{e}")
            return False
        if via_stdin:
            proc.stdin.write("".join(a + "\n" for a in args))
        proc.stdin.close()  # nothing is left to answer prompts, so they fail fast

        session = Session(f"{name} [{proc.pid}]", proc, self.output)
        self.sessions.append(session)
        self.running_list.insert("end", session.label)
        if not via_stdin:
            self._log("note: not a FreeRDP 3 client, the password is on the command line",
                      session)
        shown = build_args(v, HIDDEN if password else "")
        self._log(f"started: {join_command([client, *shown])}", session)
        return True

    def _disconnect(self):
        for index in self.running_list.curselection():
            proc = self.sessions[index].proc
            if proc.poll() is None:
                proc.terminate()

    def _drain_output(self):
        try:
            while True:
                session, line = self.output.get_nowait()
                if line is not None:
                    self._log(line, session)
                    continue
                code = session.proc.wait()
                self._log(f"exited with code {code}", session)
                index = self.sessions.index(session)
                self.sessions.pop(index)
                self.running_list.delete(index)
        except queue.Empty:
            pass
        self.after(100, self._drain_output)

    def _log(self, text: str, session: Session | None = None):
        prefix = f"[{session.label}] " if session else ""
        at_end = self.log.yview()[1] >= 0.999
        self.log.insert("end", prefix + text + "\n")
        if at_end:
            self.log.see("end")

    def _quit(self):
        running = [s for s in self.sessions if s.proc.poll() is None]
        if running and not messagebox.askyesno(
                APP, f"{len(running)} session(s) still running. Close them and quit?"):
            return
        for s in running:
            s.proc.terminate()
        self.root.destroy()

    # ---- saved connections ------------------------------------------------

    def _load_saved(self) -> dict:
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        for v in data.values():  # files from older versions stored "" for auto
            if not v.get("client"):
                v["client"] = AUTO
        return data

    def _write_saved(self):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(self.saved, indent=2), encoding="utf-8")
        self._refresh_saved()

    def _refresh_saved(self, select: str | None = None):
        needle = self.filter.get().strip().lower()
        self.visible = [n for n in sorted(self.saved, key=str.lower)
                        if needle in n.lower() or needle in self.saved[n].get("host", "").lower()]
        self.saved_list.delete(0, "end")
        for name in self.visible:
            self.saved_list.insert("end", name)
        if select in self.visible:
            self.saved_list.selection_set(self.visible.index(select))
        self._update_connect_label()

    def _selected_names(self) -> list[str]:
        return [self.visible[i] for i in self.saved_list.curselection()]

    def _update_connect_label(self):
        count = len(self._selected_names())
        self.connect_button.configure(text=f"Connect {count}" if count > 1 else "Connect")

    def _on_select(self):
        names = self._selected_names()
        self._update_connect_label()
        if len(names) != 1:
            return
        name = names[0]
        data = self.saved[name]
        self.name.set(name)
        for key, default in FIELDS.items():
            self.vars[key].set(data.get(key, default))
        self.password.set(self.passwords.get(name, ""))

    def _new(self):
        self.saved_list.selection_clear(0, "end")
        self.name.set("")
        for key, default in FIELDS.items():
            self.vars[key].set(default)
        self.password.set("")
        self._update_connect_label()

    def _save(self):
        name = self.name.get().strip() or self.vars["host"].get().strip()
        if not name:
            messagebox.showerror(APP, "Enter a name or a host first.")
            return
        self.saved[name] = self._form()
        self.name.set(name)
        if self.password.get():
            self.passwords[name] = self.password.get()
        self._write_saved()
        self._refresh_saved(select=name)
        self._log(f"saved '{name}' to {self.store} (without password)")

    def _delete(self):
        names = self._selected_names()
        if names and messagebox.askyesno(APP, f"Delete {', '.join(names)}?"):
            for name in names:
                self.saved.pop(name, None)
                self.passwords.pop(name, None)
            self._write_saved()

    # ---- file pickers -----------------------------------------------------

    def _browse_client(self):
        path = filedialog.askopenfilename(title="FreeRDP client")
        if path:
            self.vars["client"].set(path)

    def _browse_drive(self):
        path = filedialog.askdirectory(title="Folder to share")
        if path:
            self.vars["drive"].set(path)


def main():
    root = tk.Tk()
    root.title("FreeRDP")
    root.minsize(760, 640)
    style = ttk.Style(root)
    if not (IS_WIN or IS_MAC) and "clam" in style.theme_names():
        style.theme_use("clam")  # the default X11 theme looks dated
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
