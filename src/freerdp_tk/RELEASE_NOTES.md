# freerdp-tk release notes

Newest first, one section per release tag `yyyymmdd.index`, the same version as on PyPI.
Before a tag, rename "Unreleased" to that version: a release without its section stops
before anything is published. The window shows these notes under *About*.

## Unreleased

- **Live stats with a tick.** *Display* has a new *Show live stats*: the session starts with
  the overlay of codec, frames per second, bandwidth and round trip already on, saved with each
  connection. The tab names the keys that show or hide it in a session, as your client's
  settings have them: Right Alt + Right Shift + I as freerdp-tk sets them up (Right Option +
  Right Shift + I on a Mac). It needs a client that knows the overlay, as the bundled one does;
  with an older one, Connect says so instead of failing.

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
