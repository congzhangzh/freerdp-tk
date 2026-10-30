"""The freerdp-tk window: a small Tkinter launcher for the FreeRDP 3 SDL client.

Runs on Linux, Windows and macOS with the Python standard library and keyring.
It keeps a list of saved connections, builds a FreeRDP command line from a
form and shows each client's output in a log pane. Passwords never go to a
file: they stay in memory, and in the system keyring when a connection is set
to remember its password (see credentials.py).

The "(auto)" client is the first SDL client found on PATH or in a local
FreeRDP build tree. The arguments are piped in with /args-from:stdin, so the
password never shows up in the process list; that needs FreeRDP 3, so older
clients are refused rather than given /p:<password> on the command line.

Each connection can run a command before the client starts (to open an SSH
tunnel, say) and one after it ends. The before command either runs to the end
first, or keeps running beside the session, optionally until a port answers,
and is then stopped together with everything it started (its process group,
or its process tree on Windows).
"""

import functools
import json
import os
import queue
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from freerdp_tk import credentials
from freerdp_tk.supervise import EXIT_MARK, GRACE

APP = "freerdp-tk"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
EXE = ".exe" if IS_WIN else ""
AUTO = "(auto: SDL client)"
OLD_AUTO = "(auto: prefer SDL)"  # what older versions saved for auto

# The SDL client: the actively developed one, the same on Linux, Windows and
# macOS. A FreeRDP build names it sdl-freerdp, with "3" appended when binaries
# are versioned, or sdl3-freerdp when it builds the SDL2 client beside it.
CLIENT_NAMES = ["sdl3-freerdp3", "sdl3-freerdp", "sdl-freerdp3", "sdl-freerdp"]
BUILD_GLOB = "client/SDL/SDL3/*freerdp*"
GFX_CHOICES = ["(default)", "off", "AVC444", "AVC420", "RFX", "progressive", "AV1:i444",
               "AV1:i420"]
CERT_CHOICES = ["tofu", "ignore", "deny"]
LOG_LEVELS = ["(default)", "OFF", "FATAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"]
HIDDEN = "********"
# The few characters outside ASCII that the window shows. A Tk built
# without Xft, as in the standalone Pythons that uv and the kit's releases
# bring, draws with X core fonts, which often lack them and show something
# else; use_glyphs() swaps in plain ASCII there.
FANCY_GLYPHS = {"dots": "\u2026", "dot": "\u2022", "arrow": "\u2192"}
PLAIN_GLYPHS = {"dots": "...", "dot": "*", "arrow": "->"}
GLYPHS = dict(FANCY_GLYPHS)

FIELDS = {  # name -> default; everything a saved connection stores
    "client": AUTO, "host": "", "port": "", "user": "", "domain": "", "gateway": "",
    "cert": "tofu", "fullscreen": False, "size": "1600x900", "dynamic": True,
    "multimon": False, "monitors": "", "gfx": "(default)", "clipboard": True, "sound": True,
    "microphone": False, "home_drive": False, "drive": "", "log_level": "(default)",
    "extra": "", "proxy": "", "pre": "", "pre_async": False, "pre_cleanup": True,
    "pre_wait": "", "post": "", "remember_password": True,
}
PLACEHOLDERS = "%h host   %p port   %u user   %L a free local port   %% a %"
WAIT_TIMEOUT = 30  # seconds to wait for the before command's port
# Client exit codes that mean "try another password" (SDL3 client,
# sdl_utils.hpp): authentication failed, logon failure, wrong password, no
# or missing credentials. Not a locked, expired or disabled account: another
# password would not help there.
BAD_PASSWORD = {132, 134, 154, 159}
SUPERVISE = str(Path(__file__).with_name("supervise.py"))


def config_dir() -> Path:
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP


def find_clients() -> list[str]:
    """SDL clients on PATH, then in local FreeRDP build trees.

    PATH decides first: a client in an earlier folder comes before one in a
    later folder, whatever their names (a release puts its own bin/ first,
    and its sdl-freerdp must not lose to the system's sdl-freerdp3);
    CLIENT_NAMES orders the clients within one folder. Build trees are
    searched in ~/projects/FreeRDP and in every source tree listed in
    $FREERDP_TK_TREES (separated like PATH).
    """
    found = []
    for folder in os.environ.get("PATH", os.defpath).split(os.pathsep):
        if folder:
            found += [p for p in (shutil.which(n, path=folder) for n in CLIENT_NAMES) if p]
    trees = [Path.home() / "projects" / "FreeRDP"]
    extra = os.environ.get("FREERDP_TK_TREES", "").split(os.pathsep)
    trees += [Path(t).expanduser() for t in extra if t]
    for tree in dict.fromkeys(trees):
        for build in sorted(tree.glob("build*")):
            for path in sorted(build.glob(BUILD_GLOB)):
                if path.is_file() and os.access(path, os.X_OK) and path.suffix in ("", EXE):
                    found.append(str(path))
    # one program once, under the first path found: /bin and /usr/bin are one
    # folder on merged-/usr systems (Debian, Fedora), and both are on PATH
    unique: dict[str, str] = {}
    for path in found:
        unique.setdefault(os.path.realpath(path), path)
    return list(unique.values())


def client_major_version(client: str) -> int:
    """Major FreeRDP version of a client, 0 when it cannot be told."""
    try:
        out = subprocess.run([client, "/version"], capture_output=True, text=True, timeout=5,
                             **no_console()).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    match = re.search(r"version (\d+)\.", out)
    return int(match.group(1)) if match else 0


MONITOR_LINE = re.compile(  # "  * [1] [DELL U2720Q] 2560x1440\t+0+0" from sdl_list_monitors()
    r"^\s*(\*?)\s*\[(\d+)\]\s*\[(.*)\]\s+(\d+x\d+)\s+(\+-?\d+\+-?\d+)\s*$")


def parse_monitors(output: str) -> list[dict]:
    """The monitors in the output of the SDL client's /list:monitor."""
    return [{"id": m[2], "name": m[3], "size": m[4], "at": m[5], "primary": m[1] == "*"}
            for m in map(MONITOR_LINE.match, output.splitlines()) if m]


def list_monitors(client: str) -> tuple[list[dict], str]:
    """The monitors the client sees, and its whole output for when there are none.

    /list:monitor must be on the command line: read from stdin, the client
    prints its usage instead. There is nothing secret in it.
    """
    try:
        done = subprocess.run([client, "/list:monitor"], capture_output=True, text=True,
                              errors="replace", timeout=15, **no_console())
    except (OSError, subprocess.SubprocessError) as e:
        return [], str(e)
    return parse_monitors(done.stdout), (done.stdout + done.stderr).strip()


def no_console() -> dict:
    """Keep Windows from opening a console window for every child process."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def expand(text: str, values: dict | None) -> str:
    """Fill in %h, %p, %u, %L and %%; any other % stays. No values: leave text as it is."""
    return re.sub(r"%([hpuL%])", lambda m: values[m.group(1)], text) if values else text


def spawn(command: str) -> subprocess.Popen:
    """Run a command through the shell, as the leader of its own process group."""
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
             if IS_WIN else {"start_new_session": True})
    return subprocess.Popen(command, shell=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            errors="replace", **group)


def kill_tree(proc: subprocess.Popen, grace: float = 3.0):
    """Stop a command started by spawn() and what is left of its process group.

    POSIX: SIGTERM to the group, SIGKILL after grace seconds. Windows: taskkill
    /T walks the tree by parent process, so it misses orphans. Only a fallback:
    sessions contain their before command in a Helper.
    """
    if IS_WIN:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       **no_console())
        return
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 1.0)):
        deadline = time.monotonic() + wait
        try:
            os.killpg(proc.pid, sig)
            while time.monotonic() < deadline:
                proc.poll()  # reap the shell, or the group never looks empty
                os.killpg(proc.pid, 0)
                time.sleep(0.05)
        except (ProcessLookupError, PermissionError):
            return  # the group is gone


class Helper:
    """A before command: its output, its exit code, and a way to stop it.

    contain=False: a plain process group, left running at the end (stop() is
    only for aborting). contain=True: everything it starts is stopped by stop(),
    or if freerdp-tk dies. POSIX runs it under supervise.py; Windows puts it in
    a job object that the kernel kills when freerdp-tk's handle to it closes.
    """

    def __init__(self, command: str, contain: bool):
        self.code: int | None = None
        self.exited = threading.Event()
        self.job = None
        if contain and not IS_WIN:
            self.proc = subprocess.Popen([sys.executable, SUPERVISE, command],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, errors="replace",
                                         start_new_session=True)
        elif contain:
            self.proc = subprocess.Popen(
                command, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, errors="replace",
                creationflags=CREATE_SUSPENDED | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW)
            self.job = win_job_for(self.proc)  # joins before it runs a single instruction
        else:
            self.proc = spawn(command)
        self.supervised = contain and not IS_WIN
        if not self.supervised:
            threading.Thread(target=self._wait, daemon=True).start()

    def _wait(self):
        self.code = self.proc.wait()
        self.exited.set()

    def lines(self):
        """The command's output, line by line, until no process holds the pipe any more."""
        for line in self.proc.stdout:
            if self.supervised and line.startswith(EXIT_MARK):
                self.code = int(line[len(EXIT_MARK):])
                self.exited.set()
            else:
                yield line.rstrip("\n")
        if self.supervised:  # a supervisor that died without a mark; else _wait has the code
            self.exited.set()

    def wait(self) -> int:
        self.exited.wait()
        return -1 if self.code is None else self.code

    def running(self) -> bool:
        return not self.exited.is_set()

    def stop(self):
        """Stop the command and everything it started; returns once they are gone."""
        if self.supervised:
            try:
                self.proc.stdin.close()  # the supervisor's signal to stop it all
                self.proc.wait(timeout=GRACE + 10)
            except (OSError, subprocess.TimeoutExpired):
                kill_tree(self.proc)
        elif self.job:
            win_kill_job(self.job)
            self.job = None
        else:
            kill_tree(self.proc)


if IS_WIN:
    import ctypes
    from ctypes import wintypes

    CREATE_SUSPENDED = 0x4
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                  wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    class _BasicLimits(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class _ExtendedLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [("Basic", _BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    def win_job_for(proc: subprocess.Popen):
        """Put a process started with CREATE_SUSPENDED in a new kill-on-close job, then resume it.

        Its children join the job as they are born and cannot leave it (no
        breakaway allowed). Only freerdp-tk holds the job's handle: when that
        closes, even because freerdp-tk crashed, the kernel ends the whole job.
        Returns None, after resuming, when the job cannot be set up.
        """
        handle = int(proc._handle)
        job = _kernel32.CreateJobObjectW(None, None)
        info = _ExtendedLimits()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = job and _kernel32.SetInformationJobObject(job, 9, ctypes.byref(info),
                                                       ctypes.sizeof(info))  # 9: extended
        ok = ok and _kernel32.AssignProcessToJobObject(job, handle)
        _ntdll.NtResumeProcess(handle)
        if ok:
            return job
        if job:
            _kernel32.CloseHandle(job)
        return None

    def win_kill_job(job):
        _kernel32.TerminateJobObject(job, 1)
        _kernel32.CloseHandle(job)
else:
    CREATE_SUSPENDED = 0


def split_extra(text: str) -> list[str]:
    """Split the extra arguments like a shell: quotes group words and are removed.

    On Windows a backslash is a path separator, not an escape, so C:\\share stays.
    """
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # a # is text, as with shlex.split
    if IS_WIN:
        lexer.escape = ""
    return list(lexer)


def build_args(v: dict, password: str, values: dict | None = None) -> list[str]:
    """Client arguments for the connection settings v, without the program name.

    values fills the placeholders in the proxy and the extra arguments.
    """
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
    if v["proxy"].strip():
        args.append(f"/proxy:{expand(v['proxy'].strip(), values)}")
    args.append(f"/cert:{v['cert']}")
    if v["fullscreen"]:
        args.append("/f")
    elif v["size"].strip():
        args.append(f"/size:{v['size'].strip()}")
    if v["dynamic"]:
        args.append("/dynamic-resolution")
    monitors = re.findall(r"\d+", v["monitors"])
    if v["multimon"] or (monitors and not v["fullscreen"]):  # /monitors needs one of the two
        args.append("/multimon")
    if monitors:
        args.append(f"/monitors:{','.join(monitors)}")
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
    return args + split_extra(expand(v["extra"], values))


def join_command(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if IS_WIN else shlex.join(argv)


def pick_monitors(root: tk.Tk, monitors: list[dict], chosen: list[str]) -> list[str] | None:
    """Tick the monitors to use; their IDs, None when cancelled."""
    top = tk.Toplevel(root)
    top.title(APP)
    top.transient(root)
    top.resizable(False, False)
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Full screen on these monitors:").pack(anchor="w", pady=(0, 4))
    ticks = []
    for m in monitors:
        var = tk.BooleanVar(value=m["id"] in chosen)
        ticks.append((m["id"], var))
        text = f"{m['id']}: {m['name'] or 'monitor'}, {m['size']} at {m['at']}"
        ttk.Checkbutton(frame, text=text + (" (primary)" if m["primary"] else ""),
                        variable=var).pack(anchor="w")
    answer = []

    def ok(_=None):
        answer.append([i for i, var in ticks if var.get()])
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right")
    ttk.Button(buttons, text="OK", command=ok).pack(side="right", padx=4)
    top.bind("<Return>", ok)
    top.bind("<Escape>", lambda _: top.destroy())
    top.wait_visibility()
    top.grab_set()
    top.wait_window()
    return answer[0] if answer else None


def use_glyphs(root: tk.Tk) -> bool:
    """Plain ASCII glyphs when Tk draws with X core fonts; True when it does."""
    try:
        core = (root.tk.call("tk", "windowingsystem") == "x11"
                and root.tk.call("::tk::pkgconfig", "get", "fontsystem") != "xft")
    except tk.TclError:  # a Tk that does not say
        core = False
    GLYPHS.update(PLAIN_GLYPHS if core else FANCY_GLYPHS)
    return core


def ask_password(root: tk.Tk, prompt: str, remember: bool,
                 problem: str = "") -> tuple[str, bool] | None:
    """Ask for a password, with a box to tick for saving it in the system keyring.

    Returns (password, remember), None when cancelled. With a problem (no
    usable keyring) the box is greyed out, the reason is shown under it and
    remember comes back as it went in.
    """
    top = tk.Toplevel(root)
    top.title(APP)
    top.transient(root)
    top.resizable(False, False)
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    password, keep = tk.StringVar(), tk.BooleanVar(value=remember)
    answer = []
    ttk.Label(frame, text=prompt).pack(anchor="w")
    entry = ttk.Entry(frame, textvariable=password, show=GLYPHS["dot"], width=36)
    entry.pack(fill="x", pady=(4, 6))
    box = ttk.Checkbutton(frame, text="Save it in the system keyring", variable=keep)
    box.pack(anchor="w")
    if problem:
        box.state(["disabled"])
        ttk.Label(frame, text=problem, foreground="gray", wraplength=320).pack(anchor="w")

    def ok(_=None):
        answer.append((password.get(), keep.get()))
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right")
    ttk.Button(buttons, text="OK", command=ok).pack(side="right", padx=4)
    top.bind("<Return>", ok)
    top.bind("<Escape>", lambda _: top.destroy())
    entry.focus_set()
    top.wait_visibility()
    top.grab_set()  # modal, like simpledialog
    top.wait_window()
    return answer[0] if answer else None


class Session:
    """One connection, run from start to end by its own thread.

    The steps: the before command, the client, stopping the before command,
    the after command. Every line of output goes to the queue, and (self, None)
    when the session is over.
    """

    count = 0

    def __init__(self, name: str, v: dict, values: dict, argv: list[str], stdin: str,
                 notes: list[str], out: queue.Queue):
        Session.count += 1
        self.name = name
        self.label = f"{name} [{Session.count}]"
        self.v, self.values, self.argv, self.stdin, self.notes = v, values, argv, stdin, notes
        quote = (lambda x: x) if IS_WIN else shlex.quote
        self.shell_values = {k: quote(x) if k in "hu" else x for k, x in values.items()}
        self.out = out
        self.client: subprocess.Popen | None = None
        self.helper: subprocess.Popen | None = None  # the before command
        self.stopping = False
        self.code: int | None = None  # the client's exit code
        threading.Thread(target=self._run, daemon=True).start()

    def say(self, text: str):
        self.out.put((self, text))

    def stop(self):
        """Disconnect: end the client, or the before command it is still waiting for."""
        self.stopping = True
        if self.client and self.client.poll() is None:
            self.client.terminate()
        elif self.helper and not self.v["pre_async"]:
            threading.Thread(target=self.helper.stop, daemon=True).start()

    def stop_helper(self):
        if self.helper and self.v["pre_cleanup"]:
            self.helper.stop()
            self.say("before: stopped")
            self.helper = None

    def _pump(self, proc: subprocess.Popen, prefix: str = ""):
        for line in proc.stdout:
            self.say(prefix + line.rstrip("\n"))

    def _pump_helper(self, helper: Helper):
        for line in helper.lines():
            self.say("before: " + line)

    def _run(self):
        try:
            if self._before() and not self.stopping:
                self._connect()
        finally:
            self.stop_helper()
            self._after()
            self.out.put((self, None))

    def _before(self) -> bool:
        command = expand(self.v["pre"].strip(), self.shell_values)
        if not command:
            return True
        self.say(f"before: {command}")
        try:
            self.helper = Helper(command, contain=self.v["pre_cleanup"])
        except OSError as e:
            self.say(f"before: cannot start: {e}")
            return False
        pump = threading.Thread(target=self._pump_helper, args=(self.helper,), daemon=True)
        pump.start()
        if not self.v["pre_async"]:
            code = self.helper.wait()
            pump.join(timeout=1)  # its last lines first, unless something it left holds the pipe
            if code:
                self.say(f"before: failed with code {code}, not connecting")
            return code == 0
        wait = expand(self.v["pre_wait"].strip(), self.values)
        return not wait or self._wait_for(wait)

    def _wait_for(self, address: str) -> bool:
        host, _, port = address.rpartition(":")
        if not host or not port.isdigit():
            self.say(f"before: wait for '{address}': expected host:port")
            return False
        deadline = time.monotonic() + WAIT_TIMEOUT
        while time.monotonic() < deadline and not self.stopping:
            if not self.helper.running():
                self.say(f"before: exited with code {self.helper.wait()} before "
                         f"{address} answered, not connecting")
                return False
            try:
                socket.create_connection((host.strip("[]"), int(port)), timeout=1).close()
                return True
            except OSError:
                time.sleep(0.2)
        if not self.stopping:
            self.say(f"before: {address} did not answer within {WAIT_TIMEOUT} s, not connecting")
        return False

    def _connect(self):
        try:
            self.client = subprocess.Popen(self.argv, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, errors="replace", **no_console())
        except OSError as e:
            self.say(f"cannot start {self.argv[0]}: {e}")
            return
        self.client.stdin.write(self.stdin)
        self.client.stdin.close()  # nothing is left to answer prompts, so they fail fast
        for note in self.notes:
            self.say(note)
        self._pump(self.client)
        self.code = self.client.wait()
        self.say(f"exited with code {self.code}")

    def _after(self):
        command = expand(self.v["post"].strip(), self.shell_values)
        if not command:
            return
        self.say(f"after: {command}")
        try:
            proc = spawn(command)
        except OSError as e:
            self.say(f"after: cannot start: {e}")
            return
        self._pump(proc, "after: ")
        self.say(f"after: exited with code {proc.wait()}")


class App(ttk.Frame):
    def __init__(self, root: tk.Tk):
        super().__init__(root, padding=8)
        self.root = root
        use_glyphs(root)
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
        self.keyring = credentials.Worker()  # keyring calls, off the Tk thread
        self.keyring_problem: str | None = None  # "" when passwords can be saved; None: unknown
        self.reading: set[str] = set()  # connections waiting for their saved password

        self._build()
        self.pack(fill="both", expand=True)
        for var in (*self.vars.values(), self.password):
            var.trace_add("write", lambda *_: self._refresh_preview())
        self.filter.trace_add("write", lambda *_: self._refresh_saved())
        self._refresh_saved()
        self._refresh_preview()
        self._log(f"clients found: {', '.join(self.clients) or 'none'}")
        self.keyring.run(credentials.problem, lambda problem, _: self._keyring_checked(problem))
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
        tabs.add(self._hooks_tab(tabs), text="Before / after")
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
        ttk.Button(client, text=GLYPHS["dots"], width=3,
                   command=self._browse_client).pack(side="left")
        self._row(f, 1, "Client", client)
        host = ttk.Entry(f, textvariable=self.vars["host"])
        self._row(f, 2, "Host", host)
        host.focus_set()
        self._row(f, 3, "Port", ttk.Entry(f, textvariable=self.vars["port"], width=8))
        self._row(f, 4, "User", ttk.Entry(f, textvariable=self.vars["user"]))
        self._row(f, 5, "Domain", ttk.Entry(f, textvariable=self.vars["domain"]))
        password = ttk.Frame(f)
        ttk.Entry(password, textvariable=self.password, show=GLYPHS["dot"]).pack(
            side="left", fill="x", expand=True)
        self.forget = ttk.Button(password, text="Forget", width=7, command=self._forget_password)
        self.forget.pack(side="left")
        self._row(f, 6, "Password", password)
        self.remember = ttk.Checkbutton(f, text="Remember it in the system keyring",
                                        variable=self.vars["remember_password"])
        self.remember.grid(row=7, column=1, sticky="w")
        self.no_keyring = ttk.Label(  # shown once the keyring turns out to be unusable
            f, text="No system keyring: passwords stay in memory (the log says why)",
            foreground="gray")
        self._row(f, 9, "Gateway", ttk.Entry(f, textvariable=self.vars["gateway"]))
        self._row(f, 10, "Certificate", ttk.Combobox(f, textvariable=self.vars["cert"],
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
        monitors = ttk.Frame(f)
        ttk.Entry(monitors, textvariable=self.vars["monitors"]).pack(
            side="left", fill="x", expand=True)
        self.list_monitors = ttk.Button(monitors, text=f"List{GLYPHS['dots']}",
                                        command=self._pick_monitors)
        self.list_monitors.pack(side="left")
        self._row(f, 4, "Monitors", monitors)
        ttk.Label(f, text=f"Full screen on just these (IDs from List{GLYPHS['dots']}); "
                          "empty: as above", foreground="gray").grid(row=5, column=1, sticky="w")
        self._row(f, 6, "Graphics codec", ttk.Combobox(f, textvariable=self.vars["gfx"],
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
        ttk.Button(drive, text=GLYPHS["dots"], width=3,
                   command=self._browse_drive).pack(side="left")
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

    def _hooks_tab(self, parent):
        f = self._grid(parent)
        self._row(f, 0, "Before connecting", ttk.Entry(f, textvariable=self.vars["pre"]))
        self._check(f, 1, "Keep it running during the session (don't wait for it to end)",
                    "pre_async")
        self._check(f, 2, "Stop it, and all it started, when the session ends", "pre_cleanup")
        self._row(f, 3, "Then wait until", ttk.Entry(f, textvariable=self.vars["pre_wait"]))
        self._row(f, 4, "Client proxy", ttk.Entry(f, textvariable=self.vars["proxy"]))
        self._row(f, 5, "After disconnecting", ttk.Entry(f, textvariable=self.vars["post"]))
        ttk.Label(f, text=PLACEHOLDERS, foreground="gray").grid(row=6, column=1, sticky="w")
        ttk.Button(f, text=f"Fill in: SSH tunnel{GLYPHS['dots']}", command=self._ssh_tunnel).grid(
            row=7, column=1, sticky="w", pady=(6, 0))
        return f

    def _ssh_tunnel(self):
        """The common case in one step: a SOCKS tunnel through an SSH jump host."""
        jump = simpledialog.askstring(
            APP, "SSH jump host: user@host[:port], or a Host from ~/.ssh/config", parent=self.root)
        if not jump or not jump.strip():
            return
        self.vars["pre"].set("ssh -N -D 127.0.0.1:%L -o ExitOnForwardFailure=yes "
                             f"-o BatchMode=yes {jump.strip()}")
        self.vars["pre_async"].set(True)
        self.vars["pre_cleanup"].set(True)
        self.vars["pre_wait"].set("127.0.0.1:%L")
        self.vars["proxy"].set("socks5://127.0.0.1:%L")

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
        typed, v = self.password.get(), self._form()
        if self._launch(name, v, typed or self.passwords.get(name)) and typed:
            if typed != self.passwords.get(name) and v["remember_password"]:
                self._store_password(v, typed)  # a new one, typed into the form
            self.passwords[name] = typed

    def _launch(self, name: str, v: dict, password: str | None) -> bool:
        """Start one client; False when it did not start and the user was told why.

        Without a password: the one saved in the system keyring, else ask. The
        keyring is read in the background, so then True means the client is on
        its way, not that it started.
        """
        v = {**FIELDS, **v}
        client = self._resolve_client(v["client"])
        if not client:
            messagebox.showerror(APP, f"{name}: no FreeRDP SDL client found. Install FreeRDP 3 "
                                      "with its SDL client, or choose one under Connection "
                                      f"{GLYPHS['arrow']} Client.")
            return False
        if client not in self.versions:
            self.versions[client] = client_major_version(client)
        if self.versions[client] < 3:
            messagebox.showerror(APP, f"{name}: {client} is not a FreeRDP 3 client. freerdp-tk "
                                      "passes the password on standard input "
                                      "(/args-from:stdin), which needs FreeRDP 3.")
            return False
        if not v["host"].strip():
            messagebox.showerror(APP, "Enter a host to connect to.")
            return False
        if password is not None or not v["user"].strip():
            return self._start(name, v, client, password)
        if not v["remember_password"] or self.keyring_problem:
            return self._ask_and_start(name, v, client)
        if name not in self.reading:  # not twice when Connect is clicked again meanwhile
            self.reading.add(name)
            self.keyring.run(functools.partial(credentials.load, v),
                             lambda found, error: self._loaded(name, v, client, found, error))
        return True

    def _loaded(self, name: str, v: dict, client: str, password: str | None, error):
        """The keyring answered: connect with the saved password, or ask for one."""
        self.reading.discard(name)
        if error:
            self._log(f"{name}: cannot read the saved password: {error}")
        if password is None:
            self._ask_and_start(name, v, client)
            return
        self.passwords[name] = password  # read the keyring once per window
        self._start(name, v, client, password)

    def _ask_and_start(self, name: str, v: dict, client: str) -> bool:
        password = self._ask_password(name, v, f"Password for {v['user']} on {name}")
        return password is not None and self._start(name, v, client, password)

    def _start(self, name: str, v: dict, client: str, password: str | None) -> bool:
        values = {"h": v["host"].strip(), "p": v["port"].strip() or "3389",
                  "u": v["user"].strip(), "L": str(free_port()), "%": "%"}
        try:
            args = build_args(v, password or "", values)
        except ValueError as e:
            messagebox.showerror(APP, f"{name}: extra arguments: {e}")
            return False
        if any("\n" in a or "\r" in a for a in args):
            messagebox.showerror(APP, f"{name}: values must not contain line breaks.")
            return False

        shown = build_args(v, HIDDEN if password else "", values)
        notes = [f"started: {join_command([client, *shown])}"]
        stdin = "".join(a + "\n" for a in args)
        session = Session(name, v, values, [client, "/args-from:stdin"], stdin, notes,
                          self.output)
        self.sessions.append(session)
        self.running_list.insert("end", session.label)
        return True

    def _ask_password(self, name: str, v: dict, prompt: str) -> str | None:
        """Ask for the password of v, and save it if the box is left ticked."""
        answer = ask_password(self.root, prompt, v["remember_password"],
                              self.keyring_problem or "")
        if answer is None:
            return None
        password, remember = answer
        self.passwords[name] = password
        self._set_remember(name, remember)
        if remember:
            self._store_password(v, password)
        return password

    def _rejected(self, session: Session):
        """The server turned the password down: ask for another one and connect again."""
        name, v = session.name, session.v
        self.passwords.pop(name, None)  # neither memory nor the keyring has the right one
        if not v["user"].strip():
            return
        self._log(f"{name}: the server did not accept the password")
        password = self._ask_password(
            name, {**v, "remember_password": self._remembers(name, v)},
            f"The server did not accept the password for {v['user']} on {name}.\n"
            "Try another one:")
        if password is not None:
            self._launch(name, v, password)

    def _remembers(self, name: str, v: dict) -> bool:
        """The remember box of a connection as it is now, which the dialog may have changed."""
        return self.saved.get(name, v).get("remember_password", v["remember_password"])

    def _disconnect(self):
        for index in self.running_list.curselection():
            self.sessions[index].stop()

    def _drain_output(self):
        try:
            while True:
                session, line = self.output.get_nowait()
                if line is not None:
                    self._log(line, session)
                elif session in self.sessions:
                    index = self.sessions.index(session)
                    self.sessions.pop(index)
                    self.running_list.delete(index)
                    if session.code in BAD_PASSWORD and not session.stopping:
                        self.after_idle(self._rejected, session)
        except queue.Empty:
            pass
        for done in self.keyring.finished():
            self.after_idle(done)  # not here: a password dialog would hold up the output
        self.after(100, self._drain_output)

    def _log(self, text: str, session: Session | None = None):
        prefix = f"[{session.label}] " if session else ""
        at_end = self.log.yview()[1] >= 0.999
        self.log.insert("end", prefix + text + "\n")
        if at_end:
            self.log.see("end")

    def _quit(self):
        running = self.sessions
        if running and not messagebox.askyesno(
                APP, f"{len(running)} session(s) still running. Close them and quit?"):
            return
        for s in running:  # their after commands do not run: the window is going away
            s.stop()
            s.stop_helper()
        self.keyring.close(timeout=3)  # let a password being saved get there
        self.root.destroy()

    # ---- saved connections ------------------------------------------------

    def _load_saved(self) -> dict:
        try:
            data = json.loads(self.store.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        for v in data.values():  # older versions stored "" or OLD_AUTO for auto
            if v.get("client", "") in ("", OLD_AUTO):
                v["client"] = AUTO
        return data

    def _write_saved(self, refresh: bool = True):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(self.saved, indent=2), encoding="utf-8")
        if refresh:
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
        old, v = self.saved.get(name), self._form()
        self.saved[name] = v
        self.name.set(name)
        if self.password.get():
            self.passwords[name] = self.password.get()
        self._write_saved()
        self._refresh_saved(select=name)
        if old and (credentials.key(old) != credentials.key(v) or not v["remember_password"]):
            self._release_password(old)  # it logs in elsewhere now, or is not to be kept
        password = self.passwords.get(name)
        if v["remember_password"] and password:
            self._store_password(v, password)
        self._log(f"saved '{name}' to {self.store}")

    def _delete(self):
        names = self._selected_names()
        if names and messagebox.askyesno(APP, f"Delete {', '.join(names)}?"):
            gone = [self.saved.pop(name) for name in names if name in self.saved]
            for name in names:
                self.passwords.pop(name, None)
            self._write_saved()
            for v in gone:
                self._release_password(v)

    # ---- the system keyring -----------------------------------------------

    def _keyring_checked(self, problem: str):
        self.keyring_problem = problem
        if problem:
            self._log(f"passwords are not saved: {problem}")
            for widget in (self.forget, self.remember):
                widget.state(["disabled"])
            self.no_keyring.grid(row=8, column=1, sticky="w")

    def _store_password(self, v: dict, password: str):
        """Save the password of v in the background; a warning says when that fails."""
        k = credentials.key(v)
        if self.keyring_problem or not k:
            return

        def done(_, error):
            if error:
                messagebox.showwarning(APP, f"The password was not saved.\n\n{error}")
            else:
                self._log(f"saved the password of {k[1]} on {v['host'].strip()} "
                          "in the system keyring")

        self.keyring.run(functools.partial(credentials.save, dict(v), password), done)

    def _forget(self, v: dict, done=None):
        """Remove the saved password of v in the background; then done(), if it worked."""
        def finished(_, error):
            if error:
                self._log(f"cannot remove the saved password: {error}")
            elif done:
                done()

        self.keyring.run(functools.partial(credentials.forget, dict(v)), finished)

    def _release_password(self, v: dict):
        """Forget the saved password of a connection that is gone or changed, unless
        another saved connection still uses the same one."""
        v = {**FIELDS, **v}
        k = credentials.key(v)
        if not v["remember_password"] or not k or self.keyring_problem:
            return
        if not any(credentials.key(other) == k and {**FIELDS, **other}["remember_password"]
                   for other in self.saved.values()):
            self._forget(v)

    def _forget_password(self):
        """The Forget button: remove the saved password of the account in the form."""
        v = self._form()
        if not credentials.key(v):
            messagebox.showerror(APP, "Enter the host and the user whose password to forget.")
            return
        self.password.set("")
        self.passwords.pop(self.name.get().strip() or v["host"].strip(), None)
        self._forget(v, lambda: self._log(f"forgot the saved password of {credentials.key(v)[1]} "
                                          f"on {v['host'].strip()}"))

    def _set_remember(self, name: str, remember: bool):
        """Keep the remember box of a connection as the password dialog left it."""
        if self.name.get().strip() == name:
            self.vars["remember_password"].set(remember)
        saved = self.saved.get(name)
        if saved is not None and saved.get("remember_password", True) != remember:
            saved["remember_password"] = remember
            self._write_saved(refresh=False)  # keep the selection, mid-connect

    # ---- file pickers -----------------------------------------------------

    def _browse_client(self):
        path = filedialog.askopenfilename(title="FreeRDP client")
        if path:
            self.vars["client"].set(path)

    def _pick_monitors(self):
        """List…: ask the client which monitors it sees, then tick the ones to use."""
        client = self._resolve_client(self.vars["client"].get())
        if not client:
            messagebox.showerror(APP, "No FreeRDP SDL client found to list the monitors.")
            return
        result = []
        thread = threading.Thread(target=lambda: result.append(list_monitors(client)),
                                  daemon=True)  # SDL can take a while to start
        thread.start()
        self.list_monitors.state(["disabled"])

        def wait():
            if thread.is_alive():
                self.after(50, wait)
                return
            self.list_monitors.state(["!disabled"])
            monitors, output = result[0]
            if not monitors:
                self._log(f"{client} /list:monitor: {output or 'no output'}")
                messagebox.showerror(APP, "The client found no monitors (the log has its "
                                          "output).")
                return
            chosen = re.findall(r"\d+", self.vars["monitors"].get())
            picked = pick_monitors(self.root, monitors, chosen)
            if picked is not None:
                self.vars["monitors"].set(",".join(picked))

        wait()

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
