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
first, or keeps running beside the session; either way the client can then
wait for a port, for a line of its output or for some seconds. The command is
stopped together with everything it started (its process group, or its
process tree on Windows).
"""

import functools
import json
import math
import os
import platform
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
import webbrowser
from pathlib import Path
from tkinter import filedialog, font, messagebox, simpledialog, ttk

from freerdp_tk import __version__, about, credentials, i18n
from freerdp_tk.i18n import tr
from freerdp_tk.supervise import EXIT_MARK, GRACE

APP = "freerdp-tk"
PROJECT = "https://github.com/congzhangzh/freerdp-tk"
RELEASE_NOTES = Path(__file__).parent / "RELEASE_NOTES.md"  # in the wheel, so they work offline
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
# The wheels of most platforms carry a client (scripts/bundle_client.py); a
# source checkout and the plain wheel have none.
BUNDLED = Path(__file__).parent / "client" / f"sdl-freerdp{EXE}"
BUNDLED_TAIL = ("freerdp_tk", "client", f"sdl-freerdp{EXE}")  # where any wheel keeps it
HOTKEY_PREFS = '{ "SDL_KeyModMask": ["KMOD_RALT", "KMOD_RSHIFT"] }\n'
GFX_CHOICES = ["(default)", "off", "AVC444", "AVC420", "RFX", "progressive", "AV1:i444",
               "AV1:i420", "AV2:i444", "AV2:i420"]  # AV1, AV2: only clients built with them
CERT_CHOICES = ["tofu", "ignore", "deny"]
LOG_LEVELS = ["(default)", "OFF", "FATAL", "ERROR", "WARN", "INFO", "DEBUG", "TRACE"]
HIDDEN = "********"
CHANGED = "#c2410c"  # readable on the light and the dark themes
# The few characters outside ASCII that the window shows. A Tk built
# without Xft, as in the standalone Pythons that uv and the kit's releases
# bring, draws with X core fonts, which often lack them and show something
# else; use_glyphs() swaps in plain ASCII there.
FANCY_GLYPHS = {"dots": "\u2026", "dot": "\u2022", "arrow": "\u2192"}
PLAIN_GLYPHS = {"dots": "...", "dot": "*", "arrow": "->"}
GLYPHS = dict(FANCY_GLYPHS)

WAIT_PORT, WAIT_OUTPUT, WAIT_TIME = "a port answers", "the output shows", "seconds have passed"
# What the remote desktop sees with several monitors: each as its own (/multimon sends the
# layout), or one big monitor over all of them (/span: no layout is sent). Here, each
# monitor shows its part of the remote desktop either way.
SEPARATE, ONE_BIG = "separate screens", "one big screen"
MULTIMON_MODES = (SEPARATE, ONE_BIG)
# Which AV1 decoder goes first in the client (/codec-first): the GPU's, with the software
# one (dav1d) as its fallback, or the software one. Hardware first with any GPU is the
# client's default, so it passes nothing and older clients still connect.
HARDWARE_FIRST, SOFTWARE_FIRST = "Hardware first", "Software first"
DECODINGS = (HARDWARE_FIRST, SOFTWARE_FIRST)
ANY_GPU = "Automatic"  # else a line of the client's /codec-list, which starts with its id
CODEC_FIRST = "/codec-first"
# How a window on a display with more pixels than points (a Retina Mac, a 2x Wayland output,
# Windows at 150 %) asks the server for its session (/sdl-hidpi). Following the OS is the
# client's own default (points: the session in points at each monitor's own scale, which the
# system scales up), so it passes nothing and older clients still connect. Pixels asks for
# every pixel (what clients did before /sdl-hidpi); Scale for the points times N % (50 to
# 400), drawn to fit the window. A monitor of /list:monitor can have a setting of its own
# (Points among them, against a default of Pixels, say); "Same as default" is one that has
# none.
FOLLOW_OS, POINTS, PIXELS, SCALE = "Follow the OS (per monitor)", "Points", "Pixels", "Scale"
HIDPI_MODES = (FOLLOW_OS, PIXELS, SCALE)
SAME_AS_DEFAULT = "Same as default"
OWN_MODES = (SAME_AS_DEFAULT, POINTS, PIXELS, SCALE)
SDL_HIDPI = "/sdl-hidpi"
MIN_SCALE, MAX_SCALE = 50, 400
FIELDS = {  # name -> default; everything a saved connection stores
    "client": AUTO, "host": "", "port": "", "user": "", "domain": "", "gateway": "",
    "cert": "tofu", "fullscreen": False, "size": "1600x900", "dynamic": True,
    "multimon": False, "multimon_mode": SEPARATE, "monitors": "", "gfx": "(default)",
    "decoding": HARDWARE_FIRST, "gpu": ANY_GPU, "hidpi": FOLLOW_OS, "hidpi_scale": "150",
    "hidpi_monitors": "", "stats": False, "clipboard": True, "sound": True,
    "microphone": False, "camera": False, "home_drive": False, "drive": "", "log_level": "(default)",
    "extra": "", "proxy": "", "pre": "", "pre_async": False, "pre_cleanup": True,
    "pre_wait_kind": WAIT_PORT, "pre_wait": "", "pre_timeout": "", "post": "",
    "remember_password": True,
}
PLACEHOLDERS = "%h host   %p port   %u user   %L a free local port   %% a %"
WAIT_KINDS = (WAIT_PORT, WAIT_OUTPUT, WAIT_TIME)
# Choices that the lists show translated; the form and the saved file keep them in English.
SHOWN_CHOICES = (AUTO, *WAIT_KINDS, *MULTIMON_MODES, *DECODINGS, ANY_GPU, *HIDPI_MODES,
                 SAME_AS_DEFAULT, POINTS, "(default)", "off")
WAIT_TIMEOUT = 30  # seconds to wait for the before command when no limit is set
MAX_SECONDS = 86400  # threading's timeouts overflow far above this; nobody waits a day
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


def client_prefs_file() -> Path:
    """The SDL client's own settings file. It is not config_dir(): the client
    keeps it under ~/.config on macOS too (winpr's XDG_CONFIG_HOME lookup)."""
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "freerdp" / "sdl-freerdp.json"


def move_client_hotkeys() -> None:
    """Move the client's hotkeys off Right Shift alone, where a capital D typed
    with that key ends the session. Only a file that does not exist is written
    (mode "x"): one that does is the user's, whatever it holds. Failing to write
    costs only the better default, so it stops nothing."""
    path = client_prefs_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as f:
            f.write(HOTKEY_PREFS)
    except OSError:
        pass


def is_bundled(choice: str) -> bool:
    """A client choice that is the client of a freerdp-tk wheel: this one's, or
    another's. uvx unpacks each release into a folder of its own in uv's cache,
    and the old folders stay, so a path saved into one of them keeps running the
    client of that old release, which a newer server may no longer understand."""
    choice = choice.strip()
    if not choice:
        return False
    path = Path(choice)
    tail = tuple(part.lower() for part in path.parts[-3:]) if IS_WIN else path.parts[-3:]
    return tail == BUNDLED_TAIL or is_ours(choice)


def is_ours(client: str) -> bool:
    """The client in this freerdp-tk's own wheel."""
    try:
        return Path(client.strip()).samefile(BUNDLED)
    except OSError:
        return False


def saved_client(choice: str) -> str:
    """What a client choice is saved as. A wheel's client is saved as auto, which
    takes this freerdp-tk's own client first: a path would outlive the release.
    So is what older versions saved for auto ("" or OLD_AUTO)."""
    if choice.strip() in ("", OLD_AUTO) or is_bundled(choice):
        return AUTO
    return choice


def modifier_name(entry: str) -> str | None:
    """The key cap of one SDL_KeyModMask entry (KMOD_RALT or SDL_KMOD_RALT), in the
    window's language; None for one that names no key to hold (KMOD_NUM, say)."""
    mac = IS_MAC
    names = {
        "LSHIFT": tr("Left Shift"), "RSHIFT": tr("Right Shift"), "SHIFT": tr("Shift"),
        "LCTRL": tr("Left Control") if mac else tr("Left Ctrl"),
        "RCTRL": tr("Right Control") if mac else tr("Right Ctrl"),
        "CTRL": tr("Control") if mac else tr("Ctrl"),
        "LALT": tr("Left Option") if mac else tr("Left Alt"),
        "RALT": tr("Right Option") if mac else tr("Right Alt"),
        "ALT": tr("Option") if mac else tr("Alt"),
        "LGUI": tr("Left Command") if mac else tr("Left Windows"),
        "RGUI": tr("Right Command") if mac else tr("Right Windows"),
        "GUI": tr("Command") if mac else tr("Windows"),
    }
    return names.get(entry.removeprefix("SDL_").removeprefix("KMOD_"))


def stats_keys() -> str | None:
    """The keys that show or hide the client's stats overlay in a session, as the
    client reads them from its settings file (client_prefs_file(), the one
    move_client_hotkeys() writes): the modifiers of SDL_KeyModMask, then the key
    SDL_Info. What the file leaves out is the client's default, Right Shift and I.
    None when that cannot be told for sure: the file cannot be read, or names a
    modifier the client would refuse (it then turns its hotkeys off)."""
    try:
        prefs = json.loads(client_prefs_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        prefs = {}
    except (OSError, ValueError):
        return None
    if not isinstance(prefs, dict):
        return None
    mask = prefs.get("SDL_KeyModMask")
    if not isinstance(mask, list):  # the client's default, as it reads a missing one
        mask = ["KMOD_RSHIFT"]
    names = [modifier_name(m) if isinstance(m, str) else None for m in mask]
    if not names or None in names:
        return None
    key = prefs.get("SDL_Info")
    if not (isinstance(key, str) and key.startswith("SDL_SCANCODE_") and len(key) > 13):
        key = "SDL_SCANCODE_I"  # the client's default, also for a name it does not know
    key = key.removeprefix("SDL_SCANCODE_")
    return " + ".join([*names, key if len(key) == 1 else key.title()])


STATS_ARG = "+sdl-info"
# This computer's cameras for the remote desktop (MS-RDPECAM): the client announces each
# camera it has and the remote app picks one, so a tick is all it takes. Off by default.
CAMERA_ARG = "/dvc:rdpecam"
# A client has the camera channel when its /buildconfig says so (FreeRDP lists its CHANNEL_
# options there since release-20261128.2); /help does not name channels.
CAMERA_BUILT = "CHANNEL_RDPECAM_CLIENT=ON"
CAMERA_SINCE = "20261128.2"  # the kit's first FreeRDP with the camera channel and that line
# What a FreeRDP server measured, sent over its statistics channel (FreeRDP::Advanced::Stats,
# the kit's FreeRDP since 20261121.5): the overlay's rows Server frames and Server times.
# The flag opens the client's end only; a server without the channel never opens its own,
# and the overlay has no server rows. A client that does not know the flag stops on it
# ("Unexpected keyword", exit 23), so it goes only to a client whose help lists it.
SERVER_STATS_ARG = "+astats"


def client_help(client: str) -> str | None:
    """What the client's /help says, when it looks like FreeRDP 3's (it lists
    /args-from); None when it cannot be told (no answer in time, another help)."""
    try:
        done = subprocess.run([client, "/help"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=VERSION_TIMEOUT, **no_console())
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout + done.stderr
    return text if STATS_ARG in text or "/args-from" in text else None


def client_buildconfig(client: str) -> str | None:
    """What the client's /buildconfig says (its build options); None when it cannot be told
    (no answer in time, no build configuration in what it said)."""
    try:
        done = subprocess.run([client, "/buildconfig"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=VERSION_TIMEOUT, **no_console())
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout + done.stderr
    return text if "Build configuration:" in text else None


def has_stats(client: str) -> bool | None:
    """Whether the client draws the stats overlay: its /help lists +sdl-info.
    None when it cannot be told."""
    text = client_help(client)
    return None if text is None else STATS_ARG in text


def codec_first_args(v: dict) -> list[str]:
    """The client's /codec-first for Video decoding and its GPU: nothing for the
    client's own default, hardware first on any GPU."""
    if v["decoding"] == SOFTWARE_FIRST:
        return [f"{CODEC_FIRST}:software"]
    gpu = re.match(r"\s*(\d+)(\s|$)", v["gpu"])
    return [f"{CODEC_FIRST}:hardware:{gpu[1]}"] if gpu else []


def scale_ok(scale: str) -> bool:
    """Whether the client takes scale as its N in scale:N: a whole number, 50 to 400."""
    scale = scale.strip()
    return bool(re.fullmatch(r"[0-9]{2,3}", scale)) and MIN_SCALE <= int(scale) <= MAX_SCALE


def hidpi_setting(mode: str, scale: str) -> str:
    """The client's name of a HiDPI choice: points, pixels or scale:N."""
    return {PIXELS: "pixels", SCALE: f"scale:{scale.strip()}"}.get(mode, "points")


HIDPI_OWN = re.compile(r"([0-9]+):(points|pixels|scale:([0-9]+))")


def hidpi_own(text: str) -> dict[str, str]:
    """The monitors with a setting of their own, by their /list:monitor id, from the
    saved "<id>:<setting>,..." (the client's own syntax); a part it would not take is
    left out."""
    own = {}
    for part in text.split(","):
        m = HIDPI_OWN.fullmatch(part.strip())
        if m and (m[3] is None or scale_ok(m[3])):
            own[m[1]] = m[2]
    return own


def hidpi_args(v: dict) -> list[str]:
    """The client's /sdl-hidpi for the HiDPI choice and the monitors' own settings:
    nothing when every monitor follows the OS (the client's default, points). The
    own settings alone keep that default: /sdl-hidpi:2:scale:150."""
    parts = [hidpi_setting(v["hidpi"], v["hidpi_scale"])] if v["hidpi"] in (PIXELS, SCALE) \
        else []
    parts += [f"{i}:{setting}" for i, setting in hidpi_own(v["hidpi_monitors"]).items()]
    return [f"{SDL_HIDPI}:{','.join(parts)}"] if parts else []


def list_decoders(client: str) -> list[str] | None:
    """The hardware video decoders the client's /codec-list names, a line each, its
    id first ("0 D3D11VA NVIDIA GeForce RTX 5070 Laptop GPU (AV1 4:2:0 decode)" on
    Windows, "0 VA-API <driver's vendor string> (/dev/dri/renderD128) (AV1 4:2:0 decode)"
    on Linux, VideoToolbox on a Mac); [] when it says there are none; None when it
    cannot be told (an older client)."""
    try:
        done = subprocess.run([client, "/codec-list"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=VERSION_TIMEOUT, **no_console())
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [line.strip() for line in done.stdout.splitlines()]
    found = [line for line in lines if re.match(r"\d+ \S", line)]
    if found or (done.returncode == 0 and "no hardware video decoder" in lines):
        return found
    return None


def decoder_of(line: str) -> tuple[bool, str] | None:
    """The AV1 decoder a client log line says runs, as (hardware, its name):
    "AV1 decoder: D3D11VA 1 AMD Radeon(TM) 610M (hardware), dav1d as fallback" is
    (True, "AMD Radeon(TM) 610M (D3D11VA 1)"); VA-API on Linux names the driver's vendor
    string and the render node, "VA-API 0 <vendor> (/dev/dri/renderD128) (hardware)", as
    (True, "<vendor> (/dev/dri/renderD128) (VA-API 0)"). "AV1 decoder: dav1d (software;
    /codec-first:software)" is (False, "dav1d"). None for any other line."""
    said = re.search(r"AV1 decoder: (.+)$", line)
    if not said:
        return None
    text = said[1].strip()
    gpu = re.match(r"(\S+) (\d+) (.+?) \(hardware\)", text)
    if gpu:
        return True, f"{gpu[3]} ({gpu[1]} {gpu[2]})"
    name = text.split(" (", 1)[0].split(",", 1)[0].strip()
    if "(hardware)" in text:  # VideoToolbox: one, with no device to name
        return True, name
    return False, name


# The client's line for each monitor of a layout it sends (FreeRDP 20261123.6 and newer,
# sdl::hidpi::layoutText): "HiDPI: 2 points (display 2x, 1280x832 -> desktop 200/180)"
HIDPI_LINE = re.compile(r"HiDPI: (\d+) (points|pixels|scale:\d+) \(display ([\d.]+)x, "
                        r"(\d+x\d+) -> desktop (\d+)/(\d+)\)")


def hidpi_of(line: str) -> tuple[str, str, str] | None:
    """The HiDPI mode a client log line says one monitor runs in, as (its display id, its
    mode, the rest): "... HiDPI: 2 points (display 2x, 1280x832 -> desktop 200/180)" is
    ("2", "points", "display 2x, 1280x832, desktop 200 %"). None for any other line."""
    said = HIDPI_LINE.search(line)
    if not said:
        return None
    return said[1], said[2], f"display {said[3]}x, {said[4]}, desktop {said[5]} %"


def find_clients() -> list[str]:
    """The client in the wheel, then SDL clients on PATH, then in local FreeRDP
    build trees: the order auto tries them in.

    The wheel's client comes first: it is the one freerdp-tk was released and
    tested with, and a distribution's client is often older (no AV1, say). A
    client installed by hand stays one pick away, in the Client list. After it
    PATH decides: a client in an earlier folder comes before one in a later
    folder, whatever their names (the kit's pack puts its own bin/ first, and
    its sdl-freerdp must not lose to the system's sdl-freerdp3); CLIENT_NAMES
    orders the clients within one folder. Build trees are searched in
    ~/projects/FreeRDP and in every source tree listed in $FREERDP_TK_TREES
    (separated like PATH).
    """
    found = [str(BUNDLED)] if BUNDLED.is_file() else []
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


VERSION_TIMEOUT = 15  # seconds for "/version": a busy computer can take a while to start it


def probe_client(client: str) -> tuple[int | None, str]:
    """Runs "client /version" once: (its major FreeRDP version, None when it cannot
    be told; what it said when it could not start at all, such as a library it
    lacks, else ""). A busy computer can be slow to start a client: slow is
    neither old nor broken, so a timeout gives (None, "")."""
    try:
        done = subprocess.run([client, "/version"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=VERSION_TIMEOUT,
                              **no_console())
    except subprocess.TimeoutExpired:
        return None, ""
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    match = re.search(r"version (\d+)\.", done.stdout)
    if match:
        return int(match.group(1)), ""
    return None, done.stderr.strip() if done.returncode else ""


def ask_versions(clients: list[str], versions: dict[str, int]) -> tuple[dict, dict, dict]:
    """Auto's walk: the clients in order until one is FreeRDP 3, each asked its version
    unless known. Returns the versions with what it learnt, the clients it could not tell
    (with what each said if it did not start) and those that did not start. Runs the
    clients, so the window calls it on another thread."""
    versions, unknown, cannot_start = dict(versions), {}, {}
    for client in clients:
        if client in versions:
            major = versions[client]
        else:
            major, error = probe_client(client)
            if major is None:
                unknown[client] = error
                if error:
                    cannot_start[client] = error
                    continue
                break
            versions[client] = major
        if major >= 3:
            break
    return versions, unknown, cannot_start


def resolve_client(choice: str, clients: list[str], versions: dict[str, int],
                   cannot_start: dict[str, str]) -> str:
    """The program to run for a client choice; "" when there is none."""
    choice = choice.strip()
    if choice in ("", AUTO):
        usable = [c for c in clients if versions.get(c, 3) >= 3 and c not in cannot_start]
        return next(iter(usable or clients), "")
    return choice if shutil.which(choice) or Path(choice).is_file() else ""


def gather(choice: str, clients: list[str], versions: dict[str, int], helps: dict[str, str],
           cannot_start: dict[str, str], screen: tuple[int, int],
           buildconfigs: dict[str, str] | None = None, camera: bool = False) -> dict:
    """All Connect asks the client programs, each of which can take seconds to start (more
    on a busy computer), so the window asks it on another thread and stays responsive:
    the versions (Auto's walk, or the chosen client's), the client to run, its /help (None
    when it could not be read), with camera its /buildconfig (whether it has the camera
    channel), and whether the desktop has no monitor (a 0x0 screen that /list:monitor
    confirms). The window's caches go in as copies; it merges the answers."""
    unknown = {}
    if choice.strip() in ("", AUTO):
        versions, unknown, cannot_start = ask_versions(clients, versions)
    client = resolve_client(choice, clients, versions, cannot_start)
    if client and client not in versions and client not in unknown:
        major, error = probe_client(client)
        if major is None:
            unknown[client] = error
        else:
            versions = {**versions, client: major}
    text = helps.get(client) if client else None
    if client and text is None:
        text = client_help(client)
    built = (buildconfigs or {}).get(client) if client else None
    if client and camera and built is None:
        built = client_buildconfig(client)
    return {"versions": versions, "unknown": unknown, "cannot_start": cannot_start,
            "auto": choice.strip() in ("", AUTO), "client": client, "help": text,
            "buildconfig": built, "no_monitor": bool(client) and no_monitor(screen, client)}


def client_major_version(client: str) -> int | None:
    """Major FreeRDP version of a client, None when it cannot be told (it did not
    start, did not answer in time, or said no version). Unknown is not old."""
    return probe_client(client)[0]


def client_start_error(client: str) -> str:
    """What a client says when it cannot even start; "" when it started or was slow."""
    return probe_client(client)[1]


# "  * [1] [DELL U2720Q] 2560x1440\t+0+0" from sdl_list_monitors(). Fields may follow: the
# monitor's OS scale, "\t150%" (FreeRDP 20261123.5 and newer, SDL_GetDisplayContentScale),
# then its pixel density, "\t2x" (after 20261123.6; 2x on a Retina Mac). Any field is
# optional and one not known here is left alone, so a newer client still lists.
MONITOR_LINE = re.compile(r"^\s*(\*?)\s*\[(\d+)\]\s*\[(.*)\]\s+(\d+x\d+)\s+(\+-?\d+\+-?\d+)"
                          r"((?:\s+\S+)*)\s*$")
SCALE_FIELD = re.compile(r"(?:^|\s)(\d+(?:\.\d+)?)\s*%")
DENSITY_FIELD = re.compile(r"(?:^|\s)(\d+(?:\.\d+)?)x(?=\s|$)")


def parse_monitors(output: str) -> list[dict]:
    """The monitors in the output of the SDL client's /list:monitor; "scale" is the OS
    scale in per cent and "density" the pixels per point, None when the client does not
    say."""
    monitors = []
    for m in map(MONITOR_LINE.match, output.splitlines()):
        if m:
            scale, density = SCALE_FIELD.search(m[6]), DENSITY_FIELD.search(m[6])
            monitors.append({"id": m[2], "name": m[3], "size": m[4], "at": m[5],
                             "primary": m[1] == "*",
                             "scale": round(float(scale[1])) if scale else None,
                             "density": float(density[1]) if density else None})
    return monitors


def dpi_at(x: int, y: int) -> int | None:
    """Windows: the DPI of the monitor under the point (x, y), 96 at 100 %; None when it
    cannot be told (no monitor there, a Windows before 8.1)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32, shcore = ctypes.windll.user32, ctypes.windll.shcore
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        monitor = user32.MonitorFromPoint(wintypes.POINT(x, y), 0)  # MONITOR_DEFAULTTONULL
        dpi_x, dpi_y = wintypes.UINT(), wintypes.UINT()
        if not monitor or shcore.GetDpiForMonitor(  # MDT_EFFECTIVE_DPI: the OS scale
                monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) != 0:
            return None
    except (AttributeError, OSError):
        return None
    return dpi_x.value or None


def add_os_scales(monitors: list[dict]) -> list[dict]:
    """Fill in the OS scale the client did not give, on Windows from the monitor under the
    middle of each one (the client's coordinates are pixels there, as freerdp-tk's once it
    is per-monitor DPI aware). Elsewhere it stays unknown."""
    if not IS_WIN:
        return monitors
    for m in monitors:
        at = re.fullmatch(r"\+(-?\d+)\+(-?\d+)", m["at"])
        if m.get("scale") is None and at:
            width, height = map(int, m["size"].split("x"))
            dpi = dpi_at(int(at[1]) + width // 2, int(at[2]) + height // 2)
            m["scale"] = round(dpi * 100 / 96) if dpi else None
    return monitors


PER_MONITOR_AWARE_V2 = -4  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2


def set_dpi_awareness() -> bool:
    """Windows: tell it that freerdp-tk draws for each monitor's own DPI, so the window is
    sharp at 150 % rather than drawn at 96 DPI and stretched. Before Tk starts: it reads the
    DPI once. True when it took; nothing off Windows, and a Windows before 10 (1703) without
    the call keeps the old blur."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_int
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        return bool(user32.SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2))
    except (AttributeError, OSError):
        return False


def window_dpi(root: tk.Tk) -> int | None:
    """Windows: the DPI of the monitor the window is on, 96 at 100 %; None off Windows, on
    an older Windows, or when it cannot be told."""
    if not IS_WIN:
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetDpiForWindow.restype = ctypes.c_uint
        user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
        return user32.GetDpiForWindow(root.winfo_id()) or None
    except (AttributeError, OSError):
        return None


def match_tk_scaling(root: tk.Tk) -> float | None:
    """Windows: Tk's points to pixels from the DPI of the monitor the window opens on (1.0
    is 72 DPI; 2.08 is 150 %), so text and widgets have their size there. The factor set,
    None when nothing was set (off Windows, an older Windows)."""
    dpi = window_dpi(root)
    if not dpi:
        return None
    root.tk.call("tk", "scaling", dpi / 72)
    return dpi / 72


def rescale_tk(root: tk.Tk, old: int, new: int) -> bool:
    """What Windows asks of a window whose monitor's DPI went from old to new
    (WM_DPICHANGED, which Tk 8.6 does not handle): Tk's scaling; the fonts, those sized in
    pixels by the ratio, those in points again so Tk works them out anew; the window and its
    smallest size by the ratio (not when maximized: Windows sizes that one). False when Tk
    already went by the new DPI itself, so nothing is scaled twice."""
    if abs(float(root.tk.call("tk", "scaling")) * 72 - new) < 0.5:
        return False
    root.tk.call("tk", "scaling", new / 72)
    ratio = new / old
    for name in font.names(root):
        f = font.nametofont(name, root)
        size = int(f.cget("size"))
        f.configure(size=round(size * ratio) if size < 0 else size)
    if root.wm_state() != "zoomed":
        width, height = root.winfo_width(), root.winfo_height()
        if width > 1 and height > 1:
            root.geometry(f"{round(width * ratio)}x{round(height * ratio)}")
    small = root.wm_minsize()
    if small and all(small):
        root.wm_minsize(round(small[0] * ratio), round(small[1] * ratio))
    return True


DPI_POLL_MS = 500  # how often the window looks at its monitor's DPI (one cheap call)


def follow_dpi(root: tk.Tk) -> bool:
    """Windows: keep Tk at the DPI of the monitor the window is on, when it is moved to a
    monitor of another scale or the scale is changed in Settings. Windows tells a per-monitor
    aware window so with WM_DPICHANGED, which Tk 8.6 ignores, so the window asks for its DPI
    every DPI_POLL_MS instead. True when it follows; nothing off Windows."""
    last = window_dpi(root)
    if not last:
        return False

    def look():
        nonlocal last
        now = window_dpi(root)
        if now and now != last:
            rescale_tk(root, last, now)
            last = now
        root.after(DPI_POLL_MS, look)

    root.after(DPI_POLL_MS, look)
    return True


def list_monitors(client: str) -> tuple[list[dict], str]:
    """The monitors the client sees, and its whole output for when there are none.

    /list:monitor must be on the command line: read from stdin, the client
    prints its usage instead. There is nothing secret in it.
    """
    try:
        done = subprocess.run([client, "/list:monitor"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15, **no_console())
    except (OSError, subprocess.SubprocessError) as e:
        return [], str(e)
    return parse_monitors(done.stdout), (done.stdout + done.stderr).strip()


# FreeRDP's SDL client returns -1 (255) without a word when SDL cannot start its
# video, such as on a desktop with no monitor: Wayland adds no display then
# ("The video driver did not add any displays"), so SDL_Init fails.
SILENT_EXIT = 255
SILENT_EXIT_NOTE = ("the client ended without a word (code 255): FreeRDP's SDL client does "
                    "that when it cannot open its video, such as on a desktop with no "
                    "monitor right now")


def no_monitor(screen: tuple[int, int], client: str) -> bool:
    """True when the desktop has no monitor, so a client has nowhere to show the
    remote desktop: a screen of 0x0 (as Xwayland reports while a GNOME session
    has no monitor) that the client confirms with /list:monitor. Tk may keep the
    size it saw at start, so 0x0 alone is only a hint and costs no process."""
    if screen[0] > 0 and screen[1] > 0:
        return False
    monitors, _ = list_monitors(client)
    return not monitors


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


def seconds(text: str, field: str) -> float:
    """A positive number of seconds from a form field; ValueError names the field."""
    try:
        value = float(text)
    except ValueError:
        value = -1
    if not 0 < value <= MAX_SECONDS:  # also refuses nan and inf
        raise ValueError(f"{field} '{text}': expected seconds")
    return value


def port_answers(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def spawn(command: str) -> subprocess.Popen:
    """Run a command through the shell, as the leader of its own process group."""
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
             if IS_WIN else {"start_new_session": True})
    return subprocess.Popen(command, shell=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", **group)


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
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                         errors="replace", start_new_session=True,
                                         env={**os.environ, "PYTHONUTF8": "1"})
        elif contain:
            self.proc = subprocess.Popen(
                command, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
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


def build_args(v: dict, password: str, values: dict | None = None,
               server_stats: bool = True, camera: bool = True) -> list[str]:
    """Client arguments for the connection settings v, without the program name.

    values fills the placeholders in the proxy and the extra arguments. server_stats:
    with live stats, also the server's rows (+astats); False for a client without them.
    camera: False for a client without the camera channel, which then gets none.
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
        if v["multimon_mode"] == ONE_BIG:
            args.append("/span")
    if monitors:
        args.append(f"/monitors:{','.join(monitors)}")
    if v["gfx"] == "off":
        args.append("-gfx")
    elif v["gfx"] != "(default)":
        args.append(f"/gfx:{v['gfx']}")
    args += codec_first_args(v)
    args += hidpi_args(v)
    if v["stats"]:  # the SDL3 client's overlay: codec, frames per second, bandwidth, round trip
        args.append(STATS_ARG)
        if server_stats:  # and what the server measured
            args.append(SERVER_STATS_ARG)
    args.append("+clipboard" if v["clipboard"] else "-clipboard")
    if v["sound"]:
        args.append("/sound")
    if v["microphone"]:
        args.append("/microphone")
    if v["camera"] and camera:
        args.append(CAMERA_ARG)
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


def pick_monitors(root: tk.Tk, monitors: list[dict], chosen: list[str],
                  own: dict[str, str]) -> tuple[list[str], dict[str, str]] | None:
    """Tick the monitors to use, and give any of them a HiDPI setting of its own (points,
    pixels or scale:N, as the client names them). Returns their IDs and the own settings;
    None when cancelled. A setting saved for a monitor this computer does not list stays."""
    top = tk.Toplevel(root)
    top.title(APP)
    top.transient(root)
    top.resizable(False, False)
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=tr("Full screen on these monitors:")).grid(row=0, column=0,
                                                                    sticky="w", pady=(0, 4))
    ttk.Label(frame, text=tr("OS scale")).grid(row=0, column=1, sticky="w", padx=8)
    ttk.Label(frame, text=tr("HiDPI of its own")).grid(row=0, column=2, columnspan=3,
                                                       sticky="w")
    names = {c: tr(c) for c in OWN_MODES}
    back = {name: c for c, name in names.items()}
    rows = []
    for row, m in enumerate(monitors, start=1):
        var = tk.BooleanVar(value=m["id"] in chosen)
        text = tr("{id}: {name}, {size} at {at}", id=m["id"], name=m["name"] or tr("monitor"),
                  size=m["size"], at=m["at"])
        ttk.Checkbutton(frame, text=tr("{text} (primary)", text=text) if m["primary"] else text,
                        variable=var).grid(row=row, column=0, sticky="w")
        density = m.get("density")
        known = ([f"{m['scale']} %"] if m.get("scale") else []) + \
            ([f"{density:g}x"] if density and density != 1 else [])  # 2x on a Retina Mac
        ttk.Label(frame, text=", ".join(known) or tr("unknown"),
                  foreground="" if known else "gray").grid(row=row, column=1, sticky="w", padx=8)
        setting = own.get(m["id"], "")
        mode = {"points": POINTS, "pixels": PIXELS}.get(setting, SCALE if setting else
                                                         SAME_AS_DEFAULT)
        shown = tk.StringVar(value=names[mode])
        percent = tk.StringVar(value=setting.removeprefix("scale:") if mode == SCALE else "150")
        ttk.Combobox(frame, textvariable=shown, values=list(names.values()), state="readonly",
                     width=16).grid(row=row, column=2, sticky="w", pady=1)
        spin = ttk.Spinbox(frame, textvariable=percent, from_=MIN_SCALE, to=MAX_SCALE,
                           increment=25, width=5)
        spin.grid(row=row, column=3, sticky="w", padx=(4, 0))
        ttk.Label(frame, text="%").grid(row=row, column=4, sticky="w")

        def scale_state(*_, shown=shown, spin=spin):
            spin.state(["!disabled"] if back.get(shown.get()) == SCALE else ["disabled"])

        shown.trace_add("write", scale_state)
        scale_state()
        rows.append((m["id"], var, shown, percent))
    answer = []

    def ok(_=None):
        settings = {i: s for i, s in own.items() if i not in {r[0] for r in rows}}
        for i, _, shown, percent in rows:
            mode = back.get(shown.get(), SAME_AS_DEFAULT)
            if mode == SCALE and not scale_ok(percent.get()):
                messagebox.showerror(APP, tr("Monitor {id}: the scale is a whole number from "
                                             "50 to 400.", id=i), parent=top)
                return
            if mode != SAME_AS_DEFAULT:
                settings[i] = hidpi_setting(mode, percent.get())
        answer.append(([i for i, var, _, _ in rows if var.get()], settings))
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=len(monitors) + 1, column=0, columnspan=5, sticky="ew", pady=(10, 0))
    ttk.Button(buttons, text=tr("Cancel"), command=top.destroy).pack(side="right")
    ttk.Button(buttons, text=tr("OK"), command=ok).pack(side="right", padx=4)
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
    box = ttk.Checkbutton(frame, text=tr("Save it in the system keyring"), variable=keep)
    box.pack(anchor="w")
    if problem:
        box.state(["disabled"])
        ttk.Label(frame, text=problem, foreground="gray", wraplength=320).pack(anchor="w")

    def ok(_=None):
        answer.append((password.get(), keep.get()))
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text=tr("Cancel"), command=top.destroy).pack(side="right")
    ttk.Button(buttons, text=tr("OK"), command=ok).pack(side="right", padx=4)
    top.bind("<Return>", ok)
    top.bind("<Escape>", lambda _: top.destroy())
    entry.focus_set()
    top.wait_visibility()
    top.grab_set()  # modal, like simpledialog
    top.wait_window()
    return answer[0] if answer else None


def release_notes() -> str:
    """The release notes, newest first, as the package carries them."""
    try:
        return RELEASE_NOTES.read_text(encoding="utf-8")
    except OSError:
        return ""


def show_text(root: tk.Tk, title: str, text: str):
    """A window with text to read and copy, such as the release notes."""
    top = tk.Toplevel(root)
    top.title(title)
    top.transient(root)
    frame = ttk.Frame(top, padding=8)
    frame.pack(fill="both", expand=True)
    box = tk.Text(frame, wrap="word", width=90, height=30)
    bar = ttk.Scrollbar(frame, command=box.yview)
    box.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    box.pack(side="left", fill="both", expand=True)
    box.insert("1.0", text)
    box.configure(state="disabled")  # read only, still selectable
    ttk.Button(top, text=tr("Close"), command=top.destroy).pack(pady=(0, 8))
    return top


LINK = "#2563eb"  # readable on the light and the dark themes


def short(sha: str) -> str:
    return sha[:7]


def version_date(version: str) -> str | None:
    """The day of a dated version (20261115.6 -> 2026-11-15); None for any other."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})\.\d+$", version)
    return "-".join(m.groups()) if m else None


def client_says(client: str) -> str | None:
    """What a client says it is (/version), its own words; None when it says nothing.
    Starts the client, so never on the Tk thread."""
    try:
        done = subprocess.run([client, "/version"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=VERSION_TIMEOUT,
                              **no_console())
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [line.strip() for line in done.stdout.splitlines() if line.strip()]
    return " / ".join(lines[:2]) or None


class About(tk.Toplevel):
    """Who this is and what it runs: freerdp-tk's version and commit, the client in
    use (bundled or installed; for the bundled one, from MANIFEST, its FreeRDP release
    and commit, the kit release it came from, and under Details what it was built from),
    and what the window runs on. Each commit links to its page; Copy gives all of it as
    text, the home folder as ~. What takes time (git, the client's /version, keyring)
    is asked off the Tk thread and filled in when it comes; what is not known is left
    out, never guessed."""

    def __init__(self, root: tk.Tk, client: str | None, core_fonts: bool | None = None):
        super().__init__(root)
        self.root = root
        self.title(tr("About"))
        self.transient(root)
        self.resizable(False, False)
        self.client = client
        self.bundled = bool(client) and is_ours(client)
        self.manifest = about.read_manifest(client) if client else None
        self.commit: str | None = None
        self.says: str | None = None
        self.keyring_text: str | None = None
        self.core_fonts = core_fonts
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        heading = font.nametofont("TkDefaultFont").copy()
        heading.configure(size=heading.cget("size") + 4, weight="bold")
        self.heading_font = heading  # keep it alive with the window
        ttk.Label(frame, text=f"{APP} {__version__}", font=heading).pack(anchor="w")
        ttk.Label(frame, text=tr("Remote desktops, low cost and high performance.")).pack(
            anchor="w")
        when = version_date(__version__)
        ttk.Label(frame, text=tr("released {date}", date=when) if when
                  else tr("development build"), foreground="gray").pack(anchor="w")
        self.grid_frame = ttk.Frame(frame)
        self.grid_frame.pack(fill="x", pady=(8, 0))
        self.grid_frame.columnconfigure(1, weight=1)
        self.details = ttk.Frame(frame)
        self.details_shown = False
        buttons = ttk.Frame(frame)
        buttons.pack(side="bottom", fill="x", pady=(12, 0))
        self.details_button = ttk.Button(buttons, text=tr("Details"), command=self._toggle_details)
        self.details_button.pack(side="left")
        ttk.Button(buttons, text=tr("Release notes"),
                   command=lambda: show_text(root, tr("Release notes"), release_notes())
                   ).pack(side="left", padx=4)
        ttk.Button(buttons, text=tr("Copy"), command=self.copy).pack(side="left")
        ttk.Button(buttons, text=tr("Close"), command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _: self.destroy())
        self._fill()
        self._ask()

    # ---- the rows ----------------------------------------------------------

    def _row(self, label: str, *parts):
        """One row: a gray label, then texts and (text, url) links side by side."""
        row = self.grid_frame.grid_size()[1]
        ttk.Label(self.grid_frame, text=label, foreground="gray").grid(
            row=row, column=0, sticky="nw", padx=(0, 10), pady=1)
        cell = ttk.Frame(self.grid_frame)
        cell.grid(row=row, column=1, sticky="w", pady=1)
        for part in parts:
            if isinstance(part, tuple):
                link_label(cell, *part).pack(side="left", padx=(0, 6))
            elif part:
                ttk.Label(cell, text=part).pack(side="left", padx=(0, 6))

    def _section(self, title: str):
        row = self.grid_frame.grid_size()[1]
        ttk.Label(self.grid_frame, text=title, font="TkHeadingFont").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(8, 2))

    def _fill(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self._row(tr("Commit"), (short(self.commit), about.commit_link(self.commit))
                  if self.commit else tr("not known"))
        self._row(tr("License"), "Apache-2.0")
        self._row(tr("Project"), (PROJECT, PROJECT))
        self._section(tr("Client in use"))
        if not self.client:
            self._row(tr("Program"), tr("<no client found>"))
        else:
            self._row(tr("Program"), about.home_as_tilde(self.client))
            self._row(tr("Kind"), tr("bundled with freerdp-tk") if self.bundled
                      else tr("installed on this computer"))
            m = self.manifest
            if m:
                freerdp = m.source("freerdp")
                link = freerdp.commit_link() if freerdp else None
                self._row("FreeRDP", m.release or (freerdp.version if freerdp else ""),
                          (short(freerdp.commit), link) if freerdp and freerdp.commit and link
                          else (short(freerdp.commit) if freerdp and freerdp.commit else ""))
                if m.upstream:
                    branch, sha, ahead, date = m.upstream
                    self._row(tr("Based on"), f"FreeRDP {branch}",
                              (short(sha), about.upstream_link(m)),
                              (f"({date}) " if date else "")
                              + tr("+ {count} of our commits", count=ahead))
                if m.kit_release or m.kit_commit:
                    page, commit = about.kit_links(m)
                    self._row(tr("From"), (f"rdp-release-kit {m.kit_release}", page)
                              if m.kit_release else "rdp-release-kit",
                              (short(m.kit_commit), commit) if m.kit_commit else "")
                if m.built:
                    self._row(tr("Built"), tr("{date} for {platform}", date=m.built,
                                              platform=m.platform or "?"))
            elif not self.bundled:
                self._row(tr("Says"), self.says or tr("(asking the client{dots})",
                                                      dots=GLYPHS["dots"]))
        self._section(tr("Runs on"))
        self._row("Python", platform.python_version())
        tk_text = str(self.root.tk.call("info", "patchlevel"))
        if self.core_fonts is not None and not (IS_WIN or IS_MAC):
            tk_text += " " + (tr("(X core fonts, no Xft)") if self.core_fonts else tr("(with Xft)"))
        self._row("Tk", tk_text)
        self._row("keyring", self.keyring_text or tr("(asking{dots})", dots=GLYPHS["dots"]))

    def _toggle_details(self):
        self.details_shown = not self.details_shown
        if not self.details_shown:
            self.details.pack_forget()
            return
        for child in self.details.winfo_children():
            child.destroy()
        sources = self.manifest.client_sources if self.manifest else []
        ttk.Label(self.details, text=tr("Built from") if sources
                  else tr("Built from: not known for this client"),
                  font="TkHeadingFont").grid(row=0, column=0, columnspan=4, sticky="w",
                                             pady=(8, 2))
        for row, src in enumerate(sources, 1):
            ttk.Label(self.details, text=src.name).grid(row=row, column=0, sticky="w",
                                                        padx=(0, 10))
            ttk.Label(self.details, text=src.version).grid(row=row, column=1, sticky="w",
                                                           padx=(0, 10))
            link = src.commit_link()
            if link:
                link_label(self.details, short(src.commit), link).grid(row=row, column=2,
                                                                       sticky="w", padx=(0, 10))
            elif src.hash:
                ttk.Label(self.details, text=f"sha256 {src.hash[:12]}" if src.digest
                          else short(src.hash) if src.commit else src.hash[:12],
                          foreground="gray").grid(row=row, column=2,
                                                                      sticky="w", padx=(0, 10))
            if src.url:
                link_label(self.details, about.url_name(src.url), src.url).grid(
                    row=row, column=3, sticky="w")
        self.details.pack(fill="x", before=self.details_button.master)

    # ---- what takes time ---------------------------------------------------

    def _ask(self):
        """git and the client's /version on a thread of their own; keyring on its worker,
        through ask_keyring (App passes its own)."""
        answers: queue.Queue = queue.Queue()
        client = self.client if self.client and not self.bundled and not self.manifest else None

        def work():
            answers.put(("commit", about.build_commit()))
            if client:
                answers.put(("says", client_says(client) or tr("nothing (it gave no version)")))

        threading.Thread(target=work, daemon=True).start()

        def collect():
            if not self.winfo_exists():
                return
            changed = False
            while True:
                try:
                    name, value = answers.get_nowait()
                except queue.Empty:
                    break
                setattr(self, name, value)
                changed = True
            if changed:
                self._fill()
            self.after(100, collect)

        self.after(50, collect)

    def keyring_said(self, text: str):
        if self.winfo_exists():
            self.keyring_text = text
            self._fill()

    # ---- Copy ---------------------------------------------------------------

    def report(self) -> str:
        """All of it as text, full commits, the home folder as ~: for a bug report."""
        lines = [f"{APP} {__version__}" + (f" (commit {self.commit})" if self.commit else "")]
        if not self.client:
            lines.append("client: none found")
        else:
            lines.append(f"client: {self.client} ("
                         + ("bundled" if self.bundled else "installed") + ")")
            m = self.manifest
            if m:
                freerdp = m.source("freerdp")
                lines.append(f"FreeRDP {m.release or '?'}"
                             + (f" (commit {freerdp.commit})" if freerdp and freerdp.commit else ""))
                if m.upstream:
                    branch, sha, ahead, date = m.upstream
                    lines.append(f"based on FreeRDP {branch} {sha}"
                                 + (f" ({date})" if date else "") + f" + {ahead} of our commits")
                if m.kit_release or m.kit_commit:
                    lines.append(f"rdp-release-kit {m.kit_release or '?'}"
                                 + (f" (commit {m.kit_commit})" if m.kit_commit else ""))
                if m.built:
                    lines.append(f"built {m.built} for {m.platform or '?'}"
                                 + (f" ({m.environment})" if m.environment else ""))
                for src in m.client_sources:
                    lines.append("  " + "  ".join(x for x in (src.name, src.version, src.hash,
                                                             src.url) if x))
            elif self.says:
                lines.append(f"client says: {self.says}")
        tk_text = str(self.root.tk.call("info", "patchlevel"))
        if self.core_fonts is not None and not (IS_WIN or IS_MAC):
            tk_text += " (X core fonts, no Xft)" if self.core_fonts else " (with Xft)"
        lines.append(f"Python {platform.python_version()}, Tk {tk_text}, "
                     f"{sys.platform} {platform.machine()}")
        if self.keyring_text:
            lines.append(self.keyring_text)
        return about.home_as_tilde("\n".join(lines)) + "\n"

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.report())


def link_label(parent, text: str, url: str) -> ttk.Label:
    """Text that opens url in the browser when clicked, and only then."""
    label = ttk.Label(parent, text=text, foreground=LINK, cursor="hand2")
    label.url = url  # what it opens, for the tests
    label.bind("<Button-1>", lambda _: webbrowser.open(url))
    return label


def show_about(root: tk.Tk, client: str | None, core_fonts: bool | None = None) -> About:
    return About(root, client, core_fonts)


def ask_unsaved(root: tk.Tk, question: str, changed: list[str]) -> str | None:
    """Ask what to do with changes that are about to go: "save", "discard", None to stay."""
    top = tk.Toplevel(root)
    top.title(APP)
    top.transient(root)
    top.resizable(False, False)
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=question).pack(anchor="w")
    ttk.Label(frame, text=tr("Changed: {fields}", fields=", ".join(changed)), foreground="gray",
              wraplength=360).pack(anchor="w", pady=(4, 0))
    answer = []

    def choose(choice: str):
        answer.append(choice)
        top.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text=tr("Cancel"), command=top.destroy).pack(side="right")
    ttk.Button(buttons, text=tr("Discard"), command=lambda: choose("discard")).pack(side="right",
                                                                                    padx=4)
    save = ttk.Button(buttons, text=tr("Save"), command=lambda: choose("save"))
    save.pack(side="right")
    top.bind("<Return>", lambda _: choose("save"))
    top.bind("<Escape>", lambda _: top.destroy())
    save.focus_set()
    top.wait_visibility()
    top.grab_set()
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
        self.wanted: re.Pattern | None = None  # the output line the wait looks for
        self.seen = threading.Event()  # it came by
        self.wait_began = 0.0
        self.code: int | None = None  # the client's exit code
        self.decoding = ""  # the kind of video decoder it says it runs, once it says so
        self.hidpi: dict[str, tuple[str, str]] = {}  # display id -> (mode, the rest), as said
        self.no_server_rows = False  # live stats, but the client has no +astats
        self.no_camera = False  # the camera ticked, but the client has no camera channel
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

    def _pump(self, proc: subprocess.Popen, prefix: str = "") -> int:
        """Log what proc says, line by line; returns how many lines it said."""
        said = 0
        for line in proc.stdout:
            self.say(prefix + line.rstrip("\n"))
            said += 1
        return said

    def _pump_helper(self, helper: Helper):
        for line in helper.lines():
            self.say("before: " + line)
            if self.wanted and self.wanted.search(line):
                self.seen.set()

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
        try:  # before anything starts: a typing mistake must not leave a tunnel behind
            limit = self.v["pre_timeout"].strip()
            limit = seconds(limit, "give up after") if limit else None
            wait = self._wait_plan()
        except ValueError as e:
            self.say(f"before: {e}, not connecting")
            return False
        self.say(f"before: {command}")
        started = time.monotonic()
        try:
            self.helper = Helper(command, contain=self.v["pre_cleanup"])
        except OSError as e:
            self.say(f"before: cannot start: {e}")
            return False
        pump = threading.Thread(target=self._pump_helper, args=(self.helper,), daemon=True)
        pump.start()
        if not self.v["pre_async"]:
            if not self.helper.exited.wait(limit):
                self.say(f"before: still running after {limit:g} s, not connecting")
                self.helper.stop()
                return False
            code = self.helper.wait()
            pump.join(timeout=1)  # its last lines first, unless something it left holds the pipe
            if code:
                self.say(f"before: failed with code {code}, not connecting")
                return False
        if not wait:
            return True
        what, ready = wait
        if self.v["pre_wait_kind"] == WAIT_TIME:  # waiting is the point, nothing to give up on
            return self._wait_for(what, ready, math.inf, 0)
        if limit:  # all the before step may take, so what the command took counts
            return self._wait_for(what, ready, started + limit, limit)
        return self._wait_for(what, ready, time.monotonic() + WAIT_TIMEOUT, WAIT_TIMEOUT)

    def _wait_plan(self) -> tuple | None:
        """What "Then wait until" asks for: (a name for it, a check), or None for nothing."""
        text = self.v["pre_wait"].strip()
        if not text:
            return None
        kind = self.v["pre_wait_kind"]
        if kind == WAIT_OUTPUT:
            escaped = {k: re.escape(x) for k, x in self.values.items()}
            try:
                self.wanted = re.compile(expand(text, escaped))
            except re.error as e:
                raise ValueError(f"wait for output '{text}': {e}") from None
            return f"output '{text}'", self.seen.is_set
        if kind == WAIT_TIME:
            delay = seconds(text, "wait for")
            return f"{delay:g} s", lambda: time.monotonic() - self.wait_began >= delay
        address = expand(text, self.values)
        host, _, port = address.rpartition(":")
        if not host or not port.isdigit():
            raise ValueError(f"wait for '{address}': expected host:port")
        return address, functools.partial(port_answers, host.strip("[]"), int(port))

    def _wait_for(self, what: str, ready, deadline: float, limit: float) -> bool:
        self.say(f"before: waiting for {what}")
        self.wait_began = time.monotonic()
        while not self.stopping:
            if self.v["pre_async"] and not self.helper.running():  # else it was meant to end
                self.say(f"before: exited with code {self.helper.wait()} while waiting "
                         f"for {what}, not connecting")
                return False
            if ready():
                return True
            if time.monotonic() >= deadline:
                self.say(f"before: gave up waiting for {what} after {limit:g} s, not connecting")
                return False
            time.sleep(0.1)
        return False

    def _connect(self):
        try:
            self.client = subprocess.Popen(self.argv, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace",
                                           **no_console())
        except OSError as e:
            self.say(f"cannot start {self.argv[0]}: {e}")
            return
        self.client.stdin.write(self.stdin)
        self.client.stdin.close()  # nothing is left to answer prompts, so they fail fast
        for note in self.notes:
            self.say(note)
        said = self._pump(self.client)
        self.code = self.client.wait()
        self.say(f"exited with code {self.code}")
        if self.code == SILENT_EXIT and not said:
            self.say(SILENT_EXIT_NOTE)

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
        core_fonts = self.core_fonts = use_glyphs(root)
        self.settings_file = config_dir() / "settings.json"
        self.settings = self._load_settings()
        code, language_note = i18n.choose(self.settings.get("language", i18n.AUTO), core_fonts)
        i18n.use(code)
        try:  # the buttons of Tk's own dialogs on X11, where Tk has words for them
            root.tk.call("::msgcat::mclocale", code)
        except tk.TclError:
            pass
        self.vars = {k: tk.BooleanVar(value=v) if isinstance(v, bool) else tk.StringVar(value=v)
                     for k, v in FIELDS.items()}
        self.name = tk.StringVar()
        self.password = tk.StringVar()
        self.filter = tk.StringVar()
        self.store = config_dir() / "profiles.json"
        self.load_notes: list[str] = []  # what _load_saved changed, logged once the log is up
        self.saved = self._load_saved()
        self.passwords: dict[str, str] = {}  # per saved connection, memory only
        self.sessions: list[Session] = []
        self.output: queue.Queue = queue.Queue()
        self.versions: dict[str, int] = {}  # known versions only: an unknown one is asked again
        self.cannot_start: dict[str, str] = {}  # auto passes over these; asked at each Connect
        self.helps: dict[str, str] = {}  # client -> its /help, once it could be read
        self.decoders: dict[str, list[str]] = {}  # client -> its /codec-list, once known
        self.asking: set[str] = set()  # connections whose client programs are being asked
        self.buildconfigs: dict[str, str] = {}  # client -> its /buildconfig, once read
        self.asking_decoders: set[str] = set()  # clients asked for /codec-list right now
        self.decoder_session: Session | None = None  # whose decoder the live view shows
        self.hidpi_session: Session | None = None  # whose HiDPI modes it shows
        self.rows_session: Session | None = None  # whose missing server rows it shows
        self.camera_session: Session | None = None  # whose missing camera it shows
        self.clients = find_clients()
        self.keyring = credentials.Worker()  # keyring calls, off the Tk thread
        self.keyring_problem: str | None = None  # "" when passwords can be saved; None: unknown
        self.reading: set[str] = set()  # connections waiting for their saved password
        self.current: str | None = None  # the saved connection in the form; None: a new one
        self.marks: list[tuple[ttk.Widget, set[str]]] = []  # what lights up, for which fields
        self.tab_titles: dict[ttk.Frame, str] = {}

        self._build()
        self.original = self._values()  # what counts as changed, and what Reset goes back to
        self.pack(fill="both", expand=True)
        for var in (*self.vars.values(), self.password):
            var.trace_add("write", lambda *_: self._refresh_preview())
        for var in (*self.vars.values(), self.password, self.name):
            var.trace_add("write", lambda *_: self._refresh_changes())
        self.filter.trace_add("write", lambda *_: self._refresh_saved())
        self._refresh_saved()
        self._refresh_preview()
        self._log(f"clients found: {', '.join(self.clients) or 'none'}")
        for note in self.load_notes:
            self._log(note)
        if language_note:
            self._log(language_note)
        self.keyring.run(credentials.problem, lambda problem, _: self._keyring_checked(problem))
        self.after(100, self._drain_output)
        root.protocol("WM_DELETE_WINDOW", self._quit)

    # ---- layout -----------------------------------------------------------

    def _build(self):
        # A change lights up the label, not the field: the native themes of Windows and
        # macOS ignore a field's background. Tk drops the font along with this object.
        self.bold = font.Font(root=self.root, font="TkDefaultFont", weight="bold")
        for widget in ("TLabel", "TCheckbutton"):
            ttk.Style(self.root).configure(f"Changed.{widget}", foreground=CHANGED, font=self.bold)
        upper = ttk.Frame(self)
        upper.pack(fill="x")

        side = ttk.Frame(upper)
        side.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(side, text=tr("Saved connections")).pack(anchor="w")
        ttk.Entry(side, textvariable=self.filter).pack(fill="x", pady=(2, 4))
        self.saved_list = tk.Listbox(side, width=26, height=14, selectmode="extended",
                                     exportselection=False)
        self.saved_list.pack(fill="both", expand=True)
        self.saved_list.bind("<<ListboxSelect>>", lambda _: self._on_select())
        self.saved_list.bind("<Double-Button-1>", lambda _: self._connect())
        row = ttk.Frame(side)
        row.pack(fill="x", pady=(4, 0))
        self.new_menu = tk.Menu(row, tearoff=0)
        self.new_menu.add_command(label=tr("Empty connection"), command=self._new)
        self.new_menu.add_command(label=tr("Copy of this connection"), command=self._copy)
        ttk.Menubutton(row, text=tr("New"), width=-5, menu=self.new_menu).pack(side="left")
        ttk.Button(row, text=tr("Save"), width=-6, command=self._save).pack(side="left", padx=2)
        ttk.Button(row, text=tr("Delete"), width=-6, command=self._delete).pack(side="left")

        form = ttk.Frame(upper)
        form.pack(side="left", fill="both", expand=True)
        self.tabs = ttk.Notebook(form)
        self.tabs.pack(fill="both", expand=True)
        for title, tab in ((tr("Connection"), self._connection_tab),
                           (tr("Display"), self._display_tab),
                           (tr("Devices"), self._devices_tab),
                           (tr("Before / after"), self._hooks_tab),
                           (tr("Advanced"), self._advanced_tab)):
            frame = tab(self.tabs)
            self.tabs.add(frame, text=title)
            self.tab_titles[frame] = title
        # the GPU list asks the client ahead, in the background, once Display shows
        self.tabs.bind("<<NotebookTabChanged>>", lambda _: self.tabs.select() == str(
            self.gpu_box.master) and self._fill_gpus(background=True), add="+")
        row = ttk.Frame(form)
        row.pack(fill="x", pady=(4, 0))
        self.reset_button = ttk.Button(row, text=tr("Reset"), width=-6, command=self._reset)
        self.reset_button.pack(side="right")
        self.change_note = ttk.Label(row, style="Changed.TLabel")
        self.change_note.pack(side="left")

        ttk.Label(self, text=tr("Command")).pack(anchor="w", pady=(8, 0))
        self.preview = tk.Text(self, height=3, wrap="word", relief="flat",
                               background=self.root.cget("background"))
        self.preview.pack(fill="x")

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=6)
        self.connect_button = ttk.Button(buttons, text=tr("Connect"), command=self._connect)
        self.connect_button.pack(side="left")
        ttk.Button(buttons, text=tr("Disconnect"), command=self._disconnect).pack(side="left", padx=4)
        ttk.Button(buttons, text=tr("Copy command"), command=self._copy_command).pack(side="left")
        ttk.Button(buttons, text=tr("Clear log"),
                   command=lambda: self.log.delete("1.0", "end")).pack(side="right")
        ttk.Button(buttons, text=tr("About"), command=self._about).pack(side="right")
        self._language_button(buttons).pack(side="right", padx=4)

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes)
        ttk.Label(left, text=tr("Running")).pack(anchor="w")
        self.running_list = tk.Listbox(left, width=26, selectmode="extended",
                                       exportselection=False)
        self.running_list.pack(fill="both", expand=True)
        # which video decoder the newest session that said so runs: the GPU's or the software one
        self.decoder_note = ttk.Label(left, text="", wraplength=200, justify="left")
        self.decoder_note.pack(anchor="w", fill="x")
        # the HiDPI mode of each monitor of the newest session that said so
        self.hidpi_live = ttk.Label(left, text="", wraplength=200, justify="left")
        self.hidpi_live.pack(anchor="w", fill="x")
        # live stats without the server's rows: the client is too old for them. freerdp-tk
        # cannot add a row to the client's own overlay, so it says so here, where Running is
        self.rows_note = ttk.Label(left, text="", wraplength=200, justify="left")
        self.rows_note.pack(anchor="w", fill="x")
        # the camera ticked, but the client cannot share one: said here, not left silent
        self.camera_note = ttk.Label(left, text="", wraplength=200, justify="left")
        self.camera_note.pack(anchor="w", fill="x")
        panes.add(left, weight=0)
        right = ttk.Frame(panes)
        ttk.Label(right, text=tr("Log")).pack(anchor="w")
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

    def _row(self, frame, row, label, widget, *keys):
        text = ttk.Label(frame, text=label)
        text.grid(row=row, column=0, sticky="w", pady=2, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="ew", pady=2)
        self.marks.append((text, set(keys)))

    def _check(self, frame, row, label, key):
        box = ttk.Checkbutton(frame, text=label, variable=self.vars[key])
        box.grid(row=row, column=0, columnspan=2, sticky="w", pady=2)
        self.marks.append((box, {key}))

    def _choices(self, parent, key: str, choices: list[str], **options) -> ttk.Combobox:
        """A list that shows its choices in the window's language, while the form keeps
        them in English, as they are saved and compared. Anything else, a client's
        path say, shows as it is. The two variables follow each other."""
        var, shown = self.vars[key], tk.StringVar()
        names = {c: tr(c) for c in choices if c in SHOWN_CHOICES}
        back = {name: c for c, name in names.items()}

        def show(*_):
            text = names.get(var.get(), var.get())
            if shown.get() != text:
                shown.set(text)

        def keep(*_):
            value = back.get(shown.get(), shown.get())
            if var.get() != value:
                var.set(value)

        var.trace_add("write", show)
        shown.trace_add("write", keep)
        show()
        return ttk.Combobox(parent, textvariable=shown, values=[names.get(c, c) for c in choices],
                            **options)

    def _about(self):
        self.about = show_about(self.root, self._resolve_client(self.vars["client"].get()) or None,
                                self.core_fonts)
        window = self.about
        self.keyring.run(credentials.describe,
                         lambda text, error: window.keyring_said(text or str(error)))

    def _language_button(self, parent) -> ttk.Menubutton:
        """The language of the window: the system's, or one chosen here, from the next start.
        Each language is named in itself and in English, so a font without Chinese or
        Japanese still leaves the way back readable."""
        self.language = tk.StringVar(value=self.settings.get("language", i18n.AUTO))
        menu = tk.Menu(parent, tearoff=0)
        menu.add_radiobutton(label=tr("Same as the system"), value=i18n.AUTO,
                             variable=self.language, command=self._choose_language)
        for code, name in i18n.LANGUAGES.items():
            menu.add_radiobutton(label=name, value=code, variable=self.language,
                                 command=self._choose_language)
        self.language_menu = menu
        return ttk.Menubutton(parent, text=i18n.LANGUAGES[i18n.language], menu=menu)

    def _choose_language(self):
        choice = self.language.get()
        if choice == self.settings.get("language", i18n.AUTO):
            return
        self.settings["language"] = choice
        self._write_settings()
        coming = choice if choice in i18n.LANGUAGES else i18n.system_language() or "en"
        if coming != i18n.language:  # said in the language that is coming
            messagebox.showinfo(APP, i18n.tr_in(
                coming, "freerdp-tk shows this language the next time it starts."))

    def _load_settings(self) -> dict:
        """The window's own settings (the language), apart from the saved connections."""
        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_settings(self):
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        except OSError as e:
            self._log(f"cannot save the settings: {e}")

    def _connection_tab(self, parent):
        f = self._grid(parent)
        self._row(f, 0, tr("Name"), ttk.Entry(f, textvariable=self.name), "name")
        client = ttk.Frame(f)
        self._choices(client, "client", [AUTO, *self.clients]).pack(side="left", fill="x",
                                                                    expand=True)
        ttk.Button(client, text=GLYPHS["dots"], width=3,
                   command=self._browse_client).pack(side="left")
        self._row(f, 1, tr("Client"), client, "client")
        host = ttk.Entry(f, textvariable=self.vars["host"])
        self._row(f, 2, tr("Host"), host, "host")
        host.focus_set()
        self._row(f, 3, tr("Port"), ttk.Entry(f, textvariable=self.vars["port"], width=8), "port")
        self._row(f, 4, tr("User"), ttk.Entry(f, textvariable=self.vars["user"]), "user")
        self._row(f, 5, tr("Domain"), ttk.Entry(f, textvariable=self.vars["domain"]), "domain")
        password = ttk.Frame(f)
        ttk.Entry(password, textvariable=self.password, show=GLYPHS["dot"]).pack(
            side="left", fill="x", expand=True)
        self.forget = ttk.Button(password, text=tr("Forget"), width=-7, command=self._forget_password)
        self.forget.pack(side="left")
        self._row(f, 6, tr("Password"), password, "password")
        self.remember = ttk.Checkbutton(f, text=tr("Remember it in the system keyring"),
                                        variable=self.vars["remember_password"])
        self.remember.grid(row=7, column=1, sticky="w")
        self.marks.append((self.remember, {"remember_password"}))
        self.no_keyring = ttk.Label(  # shown once the keyring turns out to be unusable
            f, text=tr("No system keyring: passwords stay in memory (the log says why)"),
            foreground="gray")
        self._row(f, 9, tr("Gateway"), ttk.Entry(f, textvariable=self.vars["gateway"]), "gateway")
        self._row(f, 10, tr("Certificate"), ttk.Combobox(f, textvariable=self.vars["cert"],
                                                         values=CERT_CHOICES, state="readonly"),
                  "cert")
        return f

    def _display_tab(self, parent):
        f = self._grid(parent)
        self._check(f, 0, tr("Full screen"), "fullscreen")
        self._row(f, 1, tr("Window size"), ttk.Combobox(
            f, textvariable=self.vars["size"],
            values=["1280x720", "1600x900", "1920x1080", "2560x1440", "80%", "100%"]), "size")
        self._check(f, 2, tr("Resize the remote desktop with the window"), "dynamic")
        self._check(f, 3, tr("Use all monitors"), "multimon")
        self._row(f, 4, tr("Several monitors as"),
                  self._choices(f, "multimon_mode", list(MULTIMON_MODES), state="readonly"),
                  "multimon_mode")
        monitors = ttk.Frame(f)
        ttk.Entry(monitors, textvariable=self.vars["monitors"]).pack(
            side="left", fill="x", expand=True)
        self.list_monitors = ttk.Button(monitors, text=tr("List{dots}", dots=GLYPHS["dots"]),
                                        command=self._pick_monitors)
        self.list_monitors.pack(side="left")
        self._row(f, 5, tr("Monitors"), monitors, "monitors")
        ttk.Label(f, text=tr("Full screen on just these (IDs from List{dots}); empty: as above",
                             dots=GLYPHS["dots"]),
                  foreground="gray").grid(row=6, column=1, sticky="w")
        hidpi = ttk.Frame(f)
        self.hidpi_box = self._choices(hidpi, "hidpi", list(HIDPI_MODES), state="readonly",
                                       width=28)
        self.hidpi_box.pack(side="left")
        self.hidpi_scale = ttk.Spinbox(hidpi, textvariable=self.vars["hidpi_scale"],
                                       from_=MIN_SCALE, to=MAX_SCALE, increment=25, width=5)
        self.hidpi_scale.pack(side="left", padx=(4, 0))
        ttk.Label(hidpi, text="%").pack(side="left")
        self._row(f, 7, tr("HiDPI"), hidpi, "hidpi", "hidpi_scale", "hidpi_monitors")
        self.hidpi_note = ttk.Label(f, text="", foreground="gray")
        self.hidpi_note.grid(row=8, column=1, sticky="w")
        for key in ("hidpi", "hidpi_monitors"):
            self.vars[key].trace_add("write", lambda *_: self._hidpi_state())
        self._hidpi_state()
        self._row(f, 9, tr("Graphics codec"), self._choices(f, "gfx", GFX_CHOICES,
                                                            state="readonly"),
                  "gfx")
        self._row(f, 10, tr("Video decoding"), self._choices(f, "decoding", list(DECODINGS),
                                                             state="readonly"),
                  "decoding")
        self.gpu_box = self._choices(f, "gpu", [ANY_GPU], state="readonly",
                                     postcommand=lambda: self._fill_gpus(background=True))
        self._row(f, 11, tr("GPU"), self.gpu_box, "gpu")
        self.gpu_note = ttk.Label(f, text="", foreground="gray")
        self.gpu_note.grid(row=12, column=1, sticky="w")
        self.vars["decoding"].trace_add("write", lambda *_: self._gpu_state())
        self._gpu_state()
        self._check(f, 13, tr("Show live stats"), "stats")
        keys = stats_keys()
        if keys:  # nothing rather than keys that may be wrong
            ttk.Label(f, text=tr("Show or hide them in a session: {keys}", keys=keys),
                      foreground="gray").grid(row=14, column=1, sticky="w")
        return f

    def _hidpi_state(self):
        """The scale is only Scale's; the note says which monitors have a setting of
        their own, given under Monitors, List{dots}."""
        scale = self.vars["hidpi"].get() == SCALE
        self.hidpi_scale.state(["!disabled"] if scale else ["disabled"])
        own = hidpi_own(self.vars["hidpi_monitors"].get())
        if own:
            text = tr("Monitors with their own: {list}",
                      list=", ".join(f"{i}: {setting}" for i, setting in own.items()))
        else:
            text = tr("Each monitor goes by its own density; List{dots} above gives one a "
                      "setting of its own", dots=GLYPHS["dots"])
        self.hidpi_note.configure(text=text)

    def _gpu_state(self):
        """The GPU picks a hardware decoder, so it has nothing to pick with Software first."""
        software = self.vars["decoding"].get() == SOFTWARE_FIRST
        self.gpu_box.configure(state="disabled" if software else "readonly")

    def _fill_gpus(self, background: bool = False):
        """Fill the GPU list from the client's /codec-list, and say when there is nothing
        to pick. In the background (the window's own calls: Display shown, the list
        opened) the client is asked on another thread, and the list fills when it answers;
        until then the note says so."""
        client = self._resolve_client(self.vars["client"].get())
        if client and client not in self.decoders and background:
            if client not in self.asking_decoders:
                self.asking_decoders.add(client)
                result = []
                threading.Thread(target=lambda: result.append(list_decoders(client)),
                                 daemon=True).start()

                def wait():
                    if not result:
                        self.after(50, wait)
                        return
                    self.asking_decoders.discard(client)
                    if result[0] is not None:
                        self.decoders[client] = result[0]
                    if self._resolve_client(self.vars["client"].get()) == client:
                        self._show_gpus(result[0])

                wait()
            self.gpu_note.configure(text=tr("Asking the client for its video decoders{dots}",
                                            dots=GLYPHS["dots"]))
            return
        if not client:
            found = None
        elif client in self.decoders:
            found = self.decoders[client]
        else:
            found = list_decoders(client)
            if found is not None:
                self.decoders[client] = found
        self._show_gpus(found)

    def _show_gpus(self, found: list[str] | None):
        """The GPU list and its note for what /codec-list said (None: it could not)."""
        gpus, chosen = list(found or []), self.vars["gpu"].get()
        if chosen != ANY_GPU and chosen not in gpus:  # saved on another computer, say
            gpus.append(chosen)
        self.gpu_box.configure(values=[tr(ANY_GPU), *gpus])
        if found is None:
            note = tr("The client cannot list its video decoders (it needs FreeRDP 20261122.2 "
                      "or newer).")
        elif not found:
            note = tr("The client lists no GPU to pick here; Hardware first still takes any "
                      "it can use.")
        else:
            note = ""
        self.gpu_note.configure(text=note)

    def _devices_tab(self, parent):
        f = self._grid(parent)
        self._check(f, 0, tr("Clipboard"), "clipboard")
        self._check(f, 1, tr("Play remote sound here"), "sound")
        self._check(f, 2, tr("Microphone"), "microphone")
        self._check(f, 3, tr("Camera"), "camera")
        ttk.Label(f, text=tr("Share this computer's camera"), foreground="gray").grid(
            row=4, column=1, sticky="w")
        self._check(f, 5, tr("Share home folder"), "home_drive")
        drive = ttk.Frame(f)
        ttk.Entry(drive, textvariable=self.vars["drive"]).pack(side="left", fill="x", expand=True)
        ttk.Button(drive, text=GLYPHS["dots"], width=3,
                   command=self._browse_drive).pack(side="left")
        self._row(f, 6, tr("Share folder"), drive, "drive")
        return f

    def _advanced_tab(self, parent):
        f = self._grid(parent)
        self._row(f, 0, tr("Log level"), self._choices(f, "log_level", LOG_LEVELS,
                                                       state="readonly"),
                  "log_level")
        self._row(f, 1, tr("Extra arguments"), ttk.Entry(f, textvariable=self.vars["extra"]), "extra")
        ttk.Label(f, text=tr("e.g.  {example}", example="/scale:140 +auto-reconnect /kbd:layout:0x409"),
                  foreground="gray").grid(row=2, column=1, sticky="w")
        return f

    def _hooks_tab(self, parent):
        f = self._grid(parent)
        self._row(f, 0, tr("Before connecting"), ttk.Entry(f, textvariable=self.vars["pre"]), "pre")
        self._check(f, 1, tr("Keep it running during the session (don't wait for it to end)"),
                    "pre_async")
        self._check(f, 2, tr("Stop it, and all it started, when the session ends"),
                    "pre_cleanup")
        wait = ttk.Frame(f)
        self._choices(wait, "pre_wait_kind", WAIT_KINDS, state="readonly", width=18).pack(
            side="left", padx=(0, 4))
        ttk.Entry(wait, textvariable=self.vars["pre_wait"]).pack(
            side="left", fill="x", expand=True)
        self._row(f, 3, tr("Then wait until"), wait, "pre_wait_kind", "pre_wait")
        limit = ttk.Frame(f)
        ttk.Entry(limit, textvariable=self.vars["pre_timeout"], width=8).pack(side="left")
        ttk.Label(limit, text=tr("seconds (empty: {timeout} for the wait, no limit on the "
                                 "command)", timeout=WAIT_TIMEOUT),
                  foreground="gray").pack(side="left", padx=(6, 0))
        self._row(f, 4, tr("Give up after"), limit, "pre_timeout")
        self._row(f, 5, tr("Client proxy"), ttk.Entry(f, textvariable=self.vars["proxy"]), "proxy")
        self._row(f, 6, tr("After disconnecting"), ttk.Entry(f, textvariable=self.vars["post"]), "post")
        ttk.Label(f, text=tr(PLACEHOLDERS), foreground="gray").grid(row=7, column=1, sticky="w")
        ttk.Button(f, text=tr("Fill in: SSH tunnel{dots}", dots=GLYPHS["dots"]),
                   command=self._ssh_tunnel).grid(row=8, column=1, sticky="w", pady=(6, 0))
        return f

    def _ssh_tunnel(self):
        """The common case in one step: a SOCKS tunnel through an SSH jump host."""
        jump = simpledialog.askstring(
            APP, tr("SSH jump host: user@host[:port], or a Host from ~/.ssh/config"),
            parent=self.root)
        if not jump or not jump.strip():
            return
        self.vars["pre"].set("ssh -N -D 127.0.0.1:%L -o ExitOnForwardFailure=yes "
                             f"-o BatchMode=yes {jump.strip()}")
        self.vars["pre_async"].set(True)
        self.vars["pre_cleanup"].set(True)
        self.vars["pre_wait_kind"].set(WAIT_PORT)
        self.vars["pre_wait"].set("127.0.0.1:%L")
        self.vars["proxy"].set("socks5://127.0.0.1:%L")

    # ---- command line -----------------------------------------------------

    def _form(self) -> dict:
        return {k: var.get() for k, var in self.vars.items()}

    def _resolve_client(self, choice: str) -> str:
        """The program to run for a client choice; "" when there is none."""
        return resolve_client(choice, self.clients, self.versions, self.cannot_start)

    def _knows(self, client: str, arg: str) -> bool:
        """False only when the client's own help does not list arg: an older client
        stops on an unknown argument ("Unexpected keyword", exit 23) a second after
        Connect. Unknown is tried; a help that could be read is kept (gather() asks)."""
        text = self.helps.get(client)
        return True if text is None else arg in text

    def _ask_versions(self) -> dict[str, str]:
        """Auto takes the first client that is FreeRDP 3 and starts: a FreeRDP 2
        client must not hide one further down, nor one that cannot start (the
        wheel's, say, on a system without a library it needs) an installed one.
        Only before connecting: _resolve_client runs on every key press, for the
        command preview, and must not start programs. Returns the clients it
        could not tell, with what each said if it did not start, so Connect asks
        none a second time; auto takes the first that started, since unknown is
        not old. Those that did not start are asked again at the next Connect."""
        self.versions, unknown, self.cannot_start = ask_versions(self.clients, self.versions)
        return unknown

    def _gather_args(self, v: dict) -> tuple:
        """gather()'s arguments for the connection v: copies of the window's caches as they
        are now, read on the Tk thread."""
        return (v["client"], list(self.clients), dict(self.versions), dict(self.helps),
                dict(self.cannot_start), (self.winfo_screenwidth(), self.winfo_screenheight()),
                dict(self.buildconfigs), bool(v.get("camera")))

    def _take(self, asked: dict):
        """Keep what gather() learnt: the versions it could tell, the clients Auto passed
        over this time, a /help that could be read."""
        self.versions.update(asked["versions"])
        if asked["auto"]:
            self.cannot_start = dict(asked["cannot_start"])
        if asked["client"] and asked["help"] is not None:
            self.helps[asked["client"]] = asked["help"]
        if asked["client"] and asked.get("buildconfig") is not None:
            self.buildconfigs[asked["client"]] = asked["buildconfig"]

    def _has_camera(self, client: str) -> bool:
        """Whether the client has the camera channel, by its /buildconfig. One that could
        not be read is tried (like _knows); one that says nothing of it has none."""
        text = self.buildconfigs.get(client)
        return True if text is None else CAMERA_BUILT in text

    def _command_text(self) -> str:
        v = self._form()
        client = self._resolve_client(v["client"]) or tr("<no client found>")
        try:
            args = build_args(v, HIDDEN if self.password.get() else "",
                              server_stats=self._knows(client, SERVER_STATS_ARG),
                              camera=self._has_camera(client))
        except ValueError as e:  # unbalanced quotes in the extra arguments
            return tr("error in extra arguments: {error}", error=e)
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
        if len(names) > 1:  # several saved connections: start each one as saved, in turn
            def one(i: int):
                if i < len(names):
                    self._launch_soon(names[i], self.saved[names[i]],
                                      self.passwords.get(names[i]),
                                      lambda started: started and one(i + 1))
            one(0)
            return
        name = self.name.get().strip() or self.vars["host"].get().strip()
        typed, v = self.password.get(), self._form()

        def started(ok: bool):
            if ok and typed:
                if typed != self.passwords.get(name) and v["remember_password"]:
                    self._store_password(v, typed)  # a new one, typed into the form
                self.passwords[name] = typed
                if name == self.current:  # kept now, as a Save would have kept it
                    self.original["password"] = typed
                    self._refresh_changes()

        self._launch_soon(name, v, typed or self.passwords.get(name), started)

    def _launch_soon(self, name: str, v: dict, password: str | None, then=None):
        """Connect from the window: gather() on another thread, so the window never
        freezes while the client programs start, then _launch with its answers and
        then(started). Connect clicked again meanwhile for the same name does nothing."""
        if name in self.asking:
            return
        self.asking.add(name)
        v = {**FIELDS, **v}
        result = []
        caches = self._gather_args(v)

        def ask():
            try:
                result.append(gather(*caches))
            except Exception as e:  # noqa: BLE001 - said in the log, never a dead thread
                result.append(e)

        threading.Thread(target=ask, daemon=True).start()

        def wait():
            if not result:
                self.after(50, wait)
                return
            self.asking.discard(name)
            if isinstance(result[0], Exception):
                self._log(f"{name}: could not ask the client: {result[0]}")
                started = False
            else:
                started = self._launch(name, v, password, result[0])
            if then:
                then(started)

        wait()

    def _launch(self, name: str, v: dict, password: str | None,
                asked: dict | None = None) -> bool:
        """Start one client; False when it did not start and the user was told why.

        asked: gather()'s answers; without them it asks here, on this thread (the
        window's Connect asks on another, _launch_soon). Without a password: the one
        saved in the system keyring, else ask. The keyring is read in the background,
        so then True means the client is on its way, not that it started.
        """
        v = {**FIELDS, **v}
        if asked is None:
            asked = gather(*self._gather_args(v))
        self._take(asked)
        unknown, client = asked["unknown"], asked["client"]
        if not client:
            messagebox.showerror(APP, tr("{name}: no FreeRDP SDL client found. Install FreeRDP 3 "
                                         "with its SDL client, or choose one under Connection "
                                         "{arrow} Client.", name=name, arrow=GLYPHS["arrow"]))
            return False
        if client not in self.versions:
            error = unknown.get(client, "")
            if error:  # it cannot start at all, such as a library it lacks
                messagebox.showerror(APP, tr("{name}: {client} did not start:\n{error}",
                                             name=name, client=client, error=error))
                return False
            # tried anyway: a FreeRDP 2 client then fails on /args-from:stdin, in its
            # own words in the log, and the next Connect asks again
            self._log(f"{name}: could not tell {client}'s version; trying it "
                      "(freerdp-tk needs FreeRDP 3)")
        if self.versions.get(client, 3) < 3:
            messagebox.showerror(APP, tr("{name}: {client} is not a FreeRDP 3 client. freerdp-tk "
                                         "passes the password on standard input "
                                         "(/args-from:stdin), which needs FreeRDP 3.",
                                         name=name, client=client))
            return False
        if not v["host"].strip():
            messagebox.showerror(APP, tr("Enter a host to connect to."))
            return False
        if v["stats"] and not self._knows(client, STATS_ARG):
            messagebox.showerror(APP, tr("{name}: {client} has no live stats. Untick Display "
                                         "{arrow} Show live stats, or pick the bundled client.",
                                         name=name, client=client, arrow=GLYPHS["arrow"])
                                 if BUNDLED.is_file() else
                                 tr("{name}: {client} has no live stats. Untick Display "
                                    "{arrow} Show live stats, or pick a newer client.",
                                    name=name, client=client, arrow=GLYPHS["arrow"]))
            return False
        if v["camera"] and client not in self.buildconfigs:
            self._log(f"{name}: could not tell whether {client} has the camera channel; "
                      "trying it")
        elif v["camera"] and not self._has_camera(client):
            # without the channel the client would get an argument it cannot use
            self._log(f"{name}: {client} has no camera channel (FreeRDP {CAMERA_SINCE} and "
                      "newer); connecting without the camera")
        if v["stats"] and not self._knows(client, SERVER_STATS_ARG):
            # the overlay without the server's rows: the client would stop on the argument
            self._log(f"{name}: {client} has no {SERVER_STATS_ARG} (FreeRDP 20261121.5 and "
                      "newer); live stats without the server's rows")
        if codec_first_args(v) and not self._knows(client, CODEC_FIRST):
            messagebox.showerror(APP, tr("{name}: {client} cannot choose its video decoder. Set "
                                         "Display {arrow} Video decoding to Hardware first and "
                                         "its GPU to Automatic, or pick the bundled client.",
                                         name=name, client=client, arrow=GLYPHS["arrow"])
                                 if BUNDLED.is_file() else
                                 tr("{name}: {client} cannot choose its video decoder. Set "
                                    "Display {arrow} Video decoding to Hardware first and "
                                    "its GPU to Automatic, or pick a newer client.",
                                    name=name, client=client, arrow=GLYPHS["arrow"]))
            return False
        if v["hidpi"] == SCALE and not scale_ok(v["hidpi_scale"]):
            messagebox.showerror(APP, tr("{name}: the HiDPI scale is a whole number from 50 to "
                                         "400.", name=name))
            return False
        if hidpi_args(v) and not self._knows(client, SDL_HIDPI):
            # its windows ask for every pixel, as Pixels does; it would stop on the argument
            self._log(f"{name}: {client} has no {SDL_HIDPI} (FreeRDP 20261123.4 and newer); "
                      "connecting without the HiDPI settings")
            v = {**v, "hidpi": FOLLOW_OS, "hidpi_monitors": ""}
        if asked["no_monitor"]:
            messagebox.showerror(APP, tr("{name}: this desktop has no monitor right now (its "
                                         "screen is 0x0), so the client has nowhere to show "
                                         "the remote desktop. Connect again once a monitor "
                                         "or a remote session is attached.", name=name))
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
        password = self._ask_password(name, v, tr("Password for {user} on {name}",
                                                       user=v["user"], name=name))
        return password is not None and self._start(name, v, client, password)

    def _start(self, name: str, v: dict, client: str, password: str | None) -> bool:
        values = {"h": v["host"].strip(), "p": v["port"].strip() or "3389",
                  "u": v["user"].strip(), "L": str(free_port()), "%": "%"}
        try:
            server_stats = self._knows(client, SERVER_STATS_ARG)
            camera = self._has_camera(client)
            args = build_args(v, password or "", values, server_stats, camera)
        except ValueError as e:
            messagebox.showerror(APP, tr("{name}: extra arguments: {error}", name=name, error=e))
            return False
        if any("\n" in a or "\r" in a for a in args):
            messagebox.showerror(APP, tr("{name}: values must not contain line breaks.", name=name))
            return False

        shown = build_args(v, HIDDEN if password else "", values, server_stats, camera)
        notes = [f"started: {join_command([client, *shown])}"]
        stdin = "".join(a + "\n" for a in args)
        session = Session(name, v, values, [client, "/args-from:stdin"], stdin, notes,
                          self.output)
        self.sessions.append(session)
        self.running_list.insert("end", session.label)
        if v["camera"] and not camera:  # asked for, but this client cannot share one
            session.no_camera = True
            self._relabel(session)
            self.camera_session = session
            self.camera_note.configure(text=tr(
                "{session}: no camera (this client cannot share one; it needs FreeRDP {version} "
                "or newer)", session=session.label, version=CAMERA_SINCE))
        if v["stats"] and not server_stats:  # where the overlay's server rows would be
            session.no_server_rows = True
            self._relabel(session)
            self.rows_session = session
            self.rows_note.configure(text=tr(
                "{session}: live stats without the server's rows; they need FreeRDP "
                "20261121.5 or newer", session=session.label))
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
            tr("The server did not accept the password for {user} on {name}.\nTry another one:",
               user=v["user"], name=name))
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
                    if (decoder := decoder_of(line)) and session in self.sessions:
                        self._show_decoder(session, *decoder)
                    if (hidpi := hidpi_of(line)) and session in self.sessions:
                        self._show_hidpi(session, *hidpi)
                elif session in self.sessions:
                    index = self.sessions.index(session)
                    self.sessions.pop(index)
                    self.running_list.delete(index)
                    if self.decoder_session is session:
                        self.decoder_session = None
                        self.decoder_note.configure(text="")
                    if self.rows_session is session:
                        self.rows_session = None
                        self.rows_note.configure(text="")
                    if self.camera_session is session:
                        self.camera_session = None
                        self.camera_note.configure(text="")
                    if self.hidpi_session is session:
                        self.hidpi_session = None
                        self.hidpi_live.configure(text="")
                    if session.code in BAD_PASSWORD and not session.stopping:
                        self.after_idle(self._rejected, session)
        except queue.Empty:
            pass
        for done in self.keyring.finished():
            self.after_idle(done)  # not here: a password dialog would hold up the output
        self.after(100, self._drain_output)

    def _show_decoder(self, session: Session, hardware: bool, name: str):
        """The live view of the decoder: its kind beside the session in Running, and
        the whole of it under the list."""
        session.decoding = tr("hardware") if hardware else tr("software")
        self._relabel(session)
        self.decoder_session = session
        self.decoder_note.configure(
            text=tr("{session}: hardware decoding on {gpu}", session=session.label, gpu=name)
            if hardware else
            tr("{session}: software decoding ({decoder})", session=session.label, decoder=name))

    def _show_hidpi(self, session: Session, display: str, mode: str, rest: str):
        """The live view of HiDPI: each monitor's mode beside the session in Running (one
        word when they agree), and the whole of it under the list. A monitor keeps the mode
        of the last layout sent for it."""
        session.hidpi[display] = (mode, rest)
        self._relabel(session)
        self.hidpi_session = session
        self.hidpi_live.configure(text=tr(
            "{session}: HiDPI {monitors}", session=session.label,
            monitors="; ".join(f"{i} {m} ({r})" for i, (m, r) in sorted(
                session.hidpi.items(), key=lambda item: int(item[0])))))

    def _relabel(self, session: Session):
        """A session's line in Running: its name, then what it said of its decoder and of
        its monitors' HiDPI modes, and "no server rows" for live stats without them."""
        monitors = sorted(session.hidpi.items(), key=lambda item: int(item[0]))
        modes = {mode for _, (mode, _) in monitors}
        hidpi = modes.pop() if len(modes) == 1 else ", ".join(f"{i} {m}" for i, (m, _) in monitors)
        index = self.sessions.index(session)
        picked = index in self.running_list.curselection()
        self.running_list.delete(index)
        self.running_list.insert(index, f" {GLYPHS['dot']} ".join(
            part for part in (session.label, session.decoding, hidpi,
                              tr("no server rows") if session.no_server_rows else "",
                              tr("no camera") if session.no_camera else "") if part))
        if picked:
            self.running_list.selection_set(index)

    def _log(self, text: str, session: Session | None = None):
        prefix = f"[{session.label}] " if session else ""
        at_end = self.log.yview()[1] >= 0.999
        self.log.insert("end", prefix + text + "\n")
        if at_end:
            self.log.see("end")

    def _quit(self):
        if not self._may_leave():
            return
        running = self.sessions
        if running and not messagebox.askyesno(
                APP, tr("{count} session(s) still running. Close them and quit?", count=len(running))):
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
        for name, v in data.items():
            client = v.get("client", "")
            v["client"] = saved_client(client)
            if v["client"] != client and is_bundled(client) and not is_ours(client):
                self.load_notes.append(
                    f"'{name}': its client {client} came with another freerdp-tk; it uses "
                    f"auto now, this freerdp-tk's own client (saved at the next Save)")
        return data

    def _write_saved(self, refresh: bool = True):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(self.saved, indent=2), encoding="utf-8")
        if refresh:
            self._refresh_saved()

    def _refresh_saved(self):
        needle = self.filter.get().strip().lower()
        self.visible = [n for n in sorted(self.saved, key=str.lower)
                        if needle in n.lower() or needle in self.saved[n].get("host", "").lower()]
        self.saved_list.delete(0, "end")
        for name in self.visible:
            self.saved_list.insert("end", name)
        self._select_current()
        self._refresh_changes()

    def _select_current(self):
        self.saved_list.selection_clear(0, "end")
        if self.current in self.visible:
            self.saved_list.selection_set(self.visible.index(self.current))
        self._update_connect_label()

    def _selected_names(self) -> list[str]:
        return [self.visible[i] for i in self.saved_list.curselection()]

    def _update_connect_label(self):
        count = len(self._selected_names())
        self.connect_button.configure(text=tr("Connect {count}", count=count) if count > 1
                                      else tr("Connect"))

    def _values(self) -> dict:
        """The whole form: the password counts too, a Save would keep it."""
        return {"name": self.name.get(), "password": self.password.get(), **self._form()}

    def _changed(self) -> set[str]:
        return {k for k, v in self._values().items() if v != self.original[k]}

    def _refresh_changes(self):
        """Light up what differs from the saved connection: the label of each field, the
        tab it is on (it may be out of sight), the connection in the list, and a count."""
        changed = self._changed()
        lit = [widget for widget, keys in self.marks if keys & changed]
        for widget, _ in self.marks:
            style = f"Changed.{widget.winfo_class()}" if widget in lit else ""
            if widget.cget("style") != style:
                widget.configure(style=style)
        for tab, title in self.tab_titles.items():
            self.tabs.tab(tab, text=f"{title} *" if any(w.master is tab for w in lit) else title)
        for i, name in enumerate(self.visible):
            dirty = changed and name == self.current
            self.saved_list.itemconfigure(i, foreground=CHANGED if dirty else "",
                                          selectbackground=CHANGED if dirty else "",
                                          selectforeground="white" if dirty else "")
        if changed:
            note = (tr("{count} unsaved changes", count=len(changed)) if len(changed) > 1
                    else tr("1 unsaved change"))
        else:
            note = tr("Not saved yet") if self.current is None and self.name.get() else ""
        self.change_note.configure(text=note)
        self.reset_button.state(["!disabled" if changed else "disabled"])

    def _may_leave(self) -> bool:
        """Whether the form may stop showing this connection; asks when that loses changes."""
        changed = self._changed()
        if not changed:
            return True
        labels = [widget.cget("text") for widget, keys in self.marks if keys & changed]
        answer = ask_unsaved(self.root, tr("Save the changes to {name}?", name=self.current)
                             if self.current else tr("Save this new connection?"), labels)
        return self._save() if answer == "save" else answer == "discard"

    def _fill(self, name: str, data: dict, password: str):
        """Put a connection in the form; it is what the form now counts changes from."""
        self.name.set(name)
        for key, default in FIELDS.items():
            self.vars[key].set(data.get(key, default))
        self.password.set(password)
        self.original = self._values()
        self._refresh_changes()

    def _on_select(self):
        names = self._selected_names()
        self._update_connect_label()
        if len(names) != 1 or names[0] == self.current:
            return  # the one in the form: clicking it again must not undo the edits
        if self._may_leave():
            self.current = names[0]
            self._fill(self.current, self.saved[self.current],
                       self.passwords.get(self.current, ""))
        self._select_current()  # the one that stayed, after Cancel

    def _new(self):
        if self._may_leave():
            self.current = None
            self._fill("", {}, "")
            self._select_current()

    def _copy(self):
        """A new connection from the form as it stands. Nothing is lost, so nothing is asked:
        changes go along, the connection they came from stays as saved, and the changes
        still show, against that connection."""
        base = self.name.get().strip() or self.vars["host"].get().strip()
        if not base:
            return
        name, n = f"{base} copy", 1
        while name in self.saved:
            n += 1
            name = f"{base} copy {n}"
        self.current = None
        self.original["name"] = name
        self.name.set(name)
        self._select_current()

    def _reset(self):
        self._fill(self.original["name"], self.original, self.original["password"])

    def _save(self) -> bool:
        name = self.name.get().strip() or self.vars["host"].get().strip()
        if not name:
            messagebox.showerror(APP, tr("Enter a name or a host first."))
            return False
        client = saved_client(self.vars["client"].get())
        if self.vars["client"].get() != client:  # the form shows what is saved
            self.vars["client"].set(client)
        old, v = self.saved.get(name), self._form()
        self.saved[name] = v
        self.current = name
        self.name.set(name)
        if self.password.get():
            self.passwords[name] = self.password.get()
        self.original = self._values()
        self._write_saved()
        if old and (credentials.key(old) != credentials.key(v) or not v["remember_password"]):
            self._release_password(old)  # it logs in elsewhere now, or is not to be kept
        password = self.passwords.get(name)
        if v["remember_password"] and password:
            self._store_password(v, password)
        self._log(f"saved '{name}' to {self.store}")
        return True

    def _delete(self):
        names = self._selected_names()
        if names and messagebox.askyesno(APP, tr("Delete {names}?", names=", ".join(names))):
            gone = [self.saved.pop(name) for name in names if name in self.saved]
            for name in names:
                self.passwords.pop(name, None)
            if self.current in names:  # gone: the form must not look like it is still saved
                self.current = None
                self._fill("", {}, "")
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
                messagebox.showwarning(APP, tr("The password was not saved.\n\n{error}", error=error))
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
            messagebox.showerror(APP, tr("Enter the host and the user whose password to forget."))
            return
        self.original["password"] = ""
        self.password.set("")
        self.passwords.pop(self.name.get().strip() or v["host"].strip(), None)
        self._forget(v, lambda: self._log(f"forgot the saved password of {credentials.key(v)[1]} "
                                          f"on {v['host'].strip()}"))

    def _set_remember(self, name: str, remember: bool):
        """Keep the remember box of a connection as the password dialog left it."""
        if name == self.current:
            self.original["remember_password"] = remember
        if self.name.get().strip() == name:
            self.vars["remember_password"].set(remember)
        saved = self.saved.get(name)
        if saved is not None and saved.get("remember_password", True) != remember:
            saved["remember_password"] = remember
            self._write_saved(refresh=False)  # keep the selection, mid-connect

    # ---- file pickers -----------------------------------------------------

    def _browse_client(self):
        path = filedialog.askopenfilename(title=tr("FreeRDP client"))
        if path:
            self.vars["client"].set(path)

    def _pick_monitors(self):
        """List…: ask the client which monitors it sees, then tick the ones to use and
        give any its own HiDPI setting."""
        client = self._resolve_client(self.vars["client"].get())
        if not client:
            messagebox.showerror(APP, tr("No FreeRDP SDL client found to list the monitors."))
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
                messagebox.showerror(APP, tr("The client found no monitors (the log has its "
                                             "output)."))
                return
            chosen = re.findall(r"\d+", self.vars["monitors"].get())
            own = hidpi_own(self.vars["hidpi_monitors"].get())
            picked = pick_monitors(self.root, add_os_scales(monitors), chosen, own)
            if picked is not None:
                self.vars["monitors"].set(",".join(picked[0]))
                self.vars["hidpi_monitors"].set(",".join(f"{i}:{setting}"
                                                         for i, setting in picked[1].items()))

        wait()

    def _browse_drive(self):
        path = filedialog.askdirectory(title=tr("Folder to share"))
        if path:
            self.vars["drive"].set(path)


def main():
    move_client_hotkeys()
    set_dpi_awareness()  # Windows, before Tk reads the DPI
    root = tk.Tk()
    match_tk_scaling(root)
    root.title(f"{APP} {__version__}")  # not "FreeRDP": the session window's ("FreeRDP: host")
    root.minsize(760, 640)
    follow_dpi(root)  # Windows: a monitor of another scale, or the scale changed
    style = ttk.Style(root)
    if not (IS_WIN or IS_MAC) and "clam" in style.theme_names():
        style.theme_use("clam")  # the default X11 theme looks dated
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
