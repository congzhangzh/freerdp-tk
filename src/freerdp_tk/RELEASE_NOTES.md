# freerdp-tk release notes

Newest first, one section per release tag `yyyymmdd.index`, the same version as on PyPI.
Before a tag, rename "Unreleased" to that version: a release without its section stops
before anything is published. The window shows these notes under *About*.

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
