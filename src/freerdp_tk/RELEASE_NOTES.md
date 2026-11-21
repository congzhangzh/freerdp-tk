# freerdp-tk release notes

Newest first, one section per release tag `yyyymmdd.index`, the same version as on PyPI.
Before a tag, rename "Unreleased" to that version: a release without its section stops
before anything is published. The window shows these notes under *About*.
Releases before 2026-11-07 had `0.x` tags; their sections keep those versions, with the date.

## 20261121.1

- Under the hood: the bundled client is FreeRDP 20261120.2 (rdp-release-kit 20261121.1).

## 20261120.2

- Under the hood: the bundled client is FreeRDP 20261120.1 (rdp-release-kit 20261120.4).

## 20261120.1

- Under the hood: the bundled client is FreeRDP 20261119.1 (rdp-release-kit 20261120.1).

## 20261118.4

- Under the hood: the bundled client is FreeRDP 20261118.3 (rdp-release-kit 20261118.4).

## 20261118.3

- Under the hood: the bundled client is FreeRDP 20261118.2 (rdp-release-kit 20261118.3).

## 20261118.2

- Under the hood: the bundled client is FreeRDP 20261117.7 (rdp-release-kit 20261118.2).

## 20261118.1

- Under the hood: the bundled client is FreeRDP 20261117.6 (rdp-release-kit 20261118.1).

## 20261117.3

- Under the hood: the bundled client is FreeRDP 20261117.4 (rdp-release-kit 20261117.4).

## 20261117.2

- **About tells exactly what you run.** Each version comes with its commit, a link to that
  very change: freerdp-tk's, the bundled FreeRDP's and its upstream base, and the kit release
  the client came from. The client in use shows as bundled or installed; an installed one says
  its own version. *Details* lists what the bundled client was built from, and *Copy* puts all
  of it on the clipboard for a bug report, with your home folder as `~`.

## 20261115.6

- Under the hood: the bundled client is FreeRDP 20261115.4 (rdp-release-kit 20261115.10).

## 20261115.5

- Under the hood: the bundled client is FreeRDP 20261115.3 (rdp-release-kit 20261115.9).

## 20261115.4

- Nothing changes in the window. freerdp-tk now updates itself only when its bundled FreeRDP
  changes; 20261115.3 was such an update with nothing new in it.
- Under the hood: the bundled client stays FreeRDP 20261115.1 (rdp-release-kit 20261115.8).

## 20261115.3

- Under the hood: the bundled client is FreeRDP 20261115.1 (rdp-release-kit 20261115.8).

## 20261115.2

- **Live stats with a tick.** *Display* has a new *Show live stats*: the session starts with
  the overlay of codec, frames per second, bandwidth and round trip already on, saved with each
  connection. The tab names the keys that show or hide it in a session, as your client's
  settings have them: Right Alt + Right Shift + I as freerdp-tk sets them up (Right Option +
  Right Shift + I on a Mac). It needs a client that knows the overlay, as the bundled one does;
  with an older one, Connect says so instead of failing.
- **The graphics codec you pick is the one you get.** Picking *AV1* used to get you AV2 from a
  server that prefers it, because the bundled client still offered both; the same happened with
  *AVC420*, *AVC444*, *RFX* or *progressive*. Now the client offers only the codec you pick;
  with *(default)* the server still chooses. *Show live stats* shows which one runs.
- Under the hood: the bundled client is FreeRDP 20261115.1 (rdp-release-kit 20261115.7).

## 20261115.1

- **See what your session is doing.** Press Right Alt + Right Shift + I in a session (Right
  Option + Right Shift + I on a Mac), or type `+sdl-info` under *Extra arguments* to have it from
  the start, and the remote desktop shows, over the picture, which client you run on the left
  and the live numbers on the right: codec, frames per second, decode time, size, bandwidth,
  round trip, sound. The same keys hide it. Off by default; showing it never changes the
  session size.
- **The touchpad scrolls smoothly.** Small, slow touchpad scrolls used to be lost; now they add up.
- **AV1 and AV2 are offered again,** and an AV1 session on a very wide screen (over about
  2300 pixels) shows its picture instead of staying black.
- Under the hood: the bundled FreeRDP client is release 20261114.3 (was 20261111.4).

## 20261112.2

- **A connection saved with the bundled client keeps up with upgrades.** `uvx` unpacks each
  release into a folder of its own, and the old folders stay: a connection that saved the
  bundled client as its path kept running that release's client after an upgrade (an old
  client cannot read the AV2 of newer servers, and the session closed at once). Now the
  bundled client, picked from the Client list, is saved as auto, and a saved path to another
  freerdp-tk's client is read as auto, with a line in the log. A client you chose elsewhere
  stays as you chose it.

## 20261112.1

- **A newer bundled client: FreeRDP release-20261111.4** (rdp-release-kit 20261112.1), was
  20261106.3. It sends AV2 the way FreeRDP merged it, so AV2 works with servers built from
  FreeRDP's master and with the kit's xrdp; the old client's AV2 did not match them.
- In the client too: a graphics surface that reaches past the window's edge is cut off
  instead of shrunk; a key or mouse event the connection cannot send no longer counts as a
  failure; files on the clipboard are offered only where they can be opened.

## 20261108.1

- **Several monitors as separate screens or one big screen.** With *Use all monitors* (or a
  monitor list) a new choice says what the remote desktop gets: each monitor as its own screen
  (`/multimon`, as before), or one wide screen over all of them (`/span`).
- **Auto takes the client that came with freerdp-tk first**, the one this release was tested
  with, not an older one from the distribution (no AV1). A client you installed stays in the
  Client list, and auto still falls back to it when the bundled one is missing, is not
  FreeRDP 3 or does not start.
- **The window is called freerdp-tk and shows its version**, not "FreeRDP", which is the
  session window's name. New: *About*, with these notes.

## 20261107.3

- **A busy computer no longer gets its client refused.** A client that does not tell its
  version in time is tried, with a line in the log; only a known FreeRDP 2 is refused.
- **A desktop without a monitor says so** instead of the client ending with code 255 and no
  word (a GNOME session whose remote session is gone has no monitor).
- **AV2** in the graphics codec list, beside AV1 (needs a client built with it, such as the
  bundled one).
- A release now waits for the tests of its commit and publishes only when they passed.

## 20261107.2

- The window in **Chinese, Japanese and French**, chosen from the system or by hand.

## 20261107.1

- **Unsaved changes show**, and freerdp-tk asks before they are lost.
- Releases are now dated tags, `yyyymmdd.index`.

## 0.5.0 · 2026-11-06

- **A before command can be waited for properly.** "Then wait until" now works for a command
  that starts a proxy or tunnel and returns, not only for one kept running beside the session,
  so the client no longer starts before the tunnel is up. You can wait for a port to answer,
  for a line in the command's output (a regular expression), or for a fixed pause.
- **A limit for the whole before step.** "Give up after" stops the wait, and a command that
  was to run to its end, when it takes too long. Left empty, saved connections behave as
  before: 30 seconds for a wait, no limit on the command.
- **A typing mistake leaves no tunnel behind.** The fields are checked before the command
  starts.

## 0.4.1 · 2026-11-06

- **A capital D typed with Right Shift no longer ends your session.** The client's own
  hotkeys start with Right Shift alone (Right Shift + D disconnects). On first run freerdp-tk
  now writes the client's settings file asking for Right Alt + Right Shift instead. A settings
  file you already have is left as it is.
- Under the hood: the file is the client's own (under `~/.config`, on macOS too), so it does
  not follow freerdp-tk's folder. The bundled client is still release 20261106.3.

## 0.4.0 · 2026-11-06

- **`uvx freerdp-tk` needs nothing else.** The wheels for Linux, macOS and Windows carry the
  FreeRDP client, so there is no client to install first. A client you installed yourself
  still wins. Where no wheel fits (musl, an older glibc) the plain package finds a client on
  PATH, as before.
- **A client that cannot start says why** (for example, no libpulse) instead of being called
  "not a FreeRDP 3 client".
- **Auto passes over a FreeRDP 2 client** instead of letting it hide the bundled one.
- **The README says how to move the client's hotkeys off Right Shift.**
- Under the hood: the bundled client is rdp-release-kit's portable build, release 20261106.3,
  pinned by SHA-256. It is package
  data, not a wheel script, so `uv tool install` does not refuse to overwrite an
  `sdl-freerdp` already in `~/.local/bin`.

## 0.3.2 · 2026-10-30

- **The same client is no longer listed twice.** On systems where `/bin` is a link to
  `/usr/bin`, the client list showed one program under two paths; each program now appears
  once.

## 0.3.1 · 2026-10-30

- **Auto follows your PATH order.** With the distribution's own client installed, the
  client from a release folder that comes first on PATH was passed over; now the folder
  order decides, and the names only order clients inside one folder.
- **`uvx freerdp-tk` works on a Linux desktop whose Python has no Tk.** It starts again with
  uv's own Python, once, instead of ending with "No module named 'tkinter'"; elsewhere it
  says what to install.
- **"List..." and the password dots show up right** on a Tk without Xft (uv's Pythons): the
  window uses `...`, `*` and `->` there instead of glyphs that came out as other characters.

## 0.3.0 · 2026-10-26

- **Passwords are remembered in the system keyring** (Windows Credential Manager, macOS
  Keychain, Secret Service, KWallet). A "Remember it in the system keyring" box is ticked by
  default. Connect uses the password in memory, then the keyring, and only then asks. *Forget*
  removes it; deleting a connection or changing its account removes it too, unless another
  connection uses the same account. Selecting a connection never opens the keyring, so
  browsing the list brings up no unlock prompt. Without a usable keyring the box is greyed
  out and the log says why.
- **A wrong password is asked for again.** When the server rejects it, freerdp-tk drops the
  password, asks for another one, saves it if the box is ticked, and connects again.
  Cancelling keeps the saved one. A locked-out, expired or disabled account is not asked
  again, because another password would not help.
- **The window no longer freezes on a slow keyring.** An unlock prompt or a Secret Service
  that cannot start no longer blocks the window; Connect reads the password in the
  background.
- **Choose the monitors to use.** A *Monitors* field on the Display tab, with *List...* to
  tick the monitors the client reports; without full screen, `/multimon` is added too.
  The IDs are SDL display IDs and can change when monitors are plugged in or out.
- **Only the FreeRDP 3 SDL client is used.** Auto finds only it (same on Linux, Windows and
  macOS), and a client that is not FreeRDP 3 is refused instead of being given the password
  on its command line. Connections saved with "(auto: prefer SDL)" stay on auto.
- Under the hood: `keyring>=25` is a dependency; tests also run against the real keyring
  (Linux, Windows) and the macOS Keychain in CI.

## 0.2.0 · 2026-10-25

- **Run a command before and after a session.** The before command either runs to the end
  first (the client does not start if it fails) or keeps running beside the session, can hold
  the client back until a port answers, and is stopped with everything it started when the
  session ends, even if freerdp-tk crashes. (On macOS a double-forked daemon that left the
  group can escape; Linux and Windows stop all of it.)
- **A client proxy field and the placeholders `%h %p %u %L %%`** let the commands and the
  client meet on a port (`%L` is a free local port).
- **"Fill in: SSH tunnel"** sets this up for the common case: `ssh -D` to a jump host and
  the client through it as a SOCKS5 proxy, so the RDP server needs no open port and keeps
  its real name for the certificate check.
- **Extra arguments with quotes work on Windows.** `/t:"a b"` used to reach the client as
  `/t:"a` and `b"`; paths like `C:\share` stay whole.
- **A failing before command reports its real exit code** on Windows, not -1.
- Under the hood: tests run in a virtual X server and on Windows x64 and macOS arm64; release
  tags have no `v` prefix from here on.

## v0.1.1 · 2026-10-01

- A screenshot in the README, also shown on PyPI. (No change to the program.)

## v0.1.0 · 2026-10-01

- **The first release.** A small window for starting FreeRDP sessions on Linux, Windows and
  macOS: saved connections, a client picker that prefers SDL, a form for the common options
  with a live command preview, and a log for each session.
- **The password stays off the command line.** Arguments go to FreeRDP 3 clients through
  `/args-from:stdin`, so the password never shows in the process list.
- Under the hood: packaged with hatchling, version from the git tag, published to PyPI by
  GitHub Actions with trusted publishing.
