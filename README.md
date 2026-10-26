# freerdp-tk

A small launcher window for the [FreeRDP](https://www.freerdp.com/) remote desktop clients.
It runs on Linux, Windows and macOS and needs Python with its built-in Tkinter, plus the [keyring](https://pypi.org/project/keyring/) package, which installs with it.

![freerdp-tk: saved connections on the left, connection settings on the right, the generated command line, and the log of a running session](https://raw.githubusercontent.com/congzhangzh/freerdp-tk/main/docs/screenshot.png)

- **Saved connections:** a list you can filter. Double-click one to connect, or select several and connect them all at once.
- **Picks a client for you:** it finds the FreeRDP clients on your `PATH` and in local build trees. "(auto)" prefers the SDL client, then X11, Wayland and Windows.
- **Form instead of flags:** display, graphics codec (including AV1), clipboard, sound, microphone, drive sharing, log level, plus a box for extra arguments.
- **Live command preview:** shows the exact command line, with the password hidden, and copies it for you.
- **Session log:** runs several sessions at once and shows each client's output.

## Install

```bash
uv tool install freerdp-tk   # or: pipx install freerdp-tk
freerdp-tk
```

You also need a FreeRDP client, for example:

| Platform | Client |
|----------|--------|
| Debian / Ubuntu | `sudo apt install freerdp3-sdl` (or `freerdp3-x11`) |
| Fedora | `sudo dnf install freerdp` |
| macOS | `brew install freerdp` |
| Windows | a FreeRDP build containing `sdl-freerdp.exe` or `wfreerdp.exe`, on your `PATH` |

On Linux, a system Python may need its Tk package (`sudo apt install python3-tk`). The Pythons that `uv` installs already include Tk.

## Passwords

- **Saved in the system keyring, never in a file.** With *Remember it in the system keyring* ticked (the default), the password goes to the system's own store: Credential Manager on Windows, the Keychain on macOS, the Secret Service (GNOME Keyring, KeePassXC) or KWallet on Linux. From then on a double-click connects without asking. The connections file only keeps whether the box is ticked.
- The password dialog has the same box: untick it, and the password stays in memory only, until the window closes. *Forget* removes a saved password. Deleting a connection removes its password too, unless another saved connection logs in to the same account.
- **A rejected password is asked for again.** When the client exits because the server turned the password down (exit codes 132, 134, 154 and 159 of the X11 and SDL clients), freerdp-tk asks for another one and connects again; with the box ticked, the new password replaces the saved one. A locked, expired or disabled account is not asked again, since another password would not help.
- An entry is named after the account it logs in to, `freerdp-tk/<domain\user>@<host>:<port>`, not after the connection. Renaming a connection keeps its password, and two connections to one account share it.
- **No usable keyring** (on Linux: no Secret Service or KWallet, or no D-Bus session, as over plain SSH): the box is greyed out with the reason, and passwords are asked for and kept in memory only. freerdp-tk never falls back to a file. A locked keyring is unlocked through the system's own prompt; if that fails or is cancelled, freerdp-tk asks for the password instead.
- **What the keyring protects:** the password on disk, and from the other users of the computer. A program that runs as you can usually read it: Credential Manager and an unlocked Secret Service hand it to any process of your session, while the Keychain asks you first unless the program is on the entry's access list.
- With FreeRDP 3, all arguments are passed to the client through standard input (`/args-from:stdin`). The password therefore never appears in the process list (`ps`, Task Manager).
- FreeRDP 2 has no such option, so the password goes on the command line, and the log warns you about it.

## Before and after commands (SSH tunnels and more)

The *Before / after* tab runs your own commands around a session:

- **Before connecting:** runs to the end before the client starts; if it fails, the client does not start. Tick *Keep it running during the session* for a command that stays up beside the session, such as a tunnel. *Then wait until* `host:port` holds the client back until that port answers.
- **Stop it when the session ends:** ends the before command and everything it started, also if freerdp-tk itself crashes or is killed:
  - **Linux:** a small supervisor runs the command as a *child subreaper*, so even daemons that fork twice and leave the process group stay under it. Each is sent SIGTERM, then SIGKILL after 3 seconds.
  - **Windows:** the command runs in a job object that the system closes, and with it everything inside, when freerdp-tk lets go of it.
  - **macOS:** the same supervisor, but macOS has no subreaper: a daemon that forks twice and leaves the process group survives.
- **After disconnecting:** runs once the session is over, however it ended.
- **Client proxy:** passed to the client as `/proxy:`.

Placeholders work in all of these and in the extra arguments: `%h` host, `%p` port, `%u` user, `%L` a free local port picked for this session, `%%` a percent sign.

**Fill in: SSH tunnel…** sets it all up for the common case. It asks for a jump host and fills in:

```
before:      ssh -N -D 127.0.0.1:%L -o ExitOnForwardFailure=yes -o BatchMode=yes me@bastion
wait until:  127.0.0.1:%L
proxy:       socks5://127.0.0.1:%L
```

The RDP server then only has to be reachable from the jump host, and the client still connects by its real name, so the certificate check is unchanged. ssh runs without a terminal, so it must log in with a key or an agent, and it must already know the jump host's key (connect once with `ssh` in a terminal).

## Where things are kept

| What | Where |
|------|-------|
| Saved connections | `~/.config/freerdp-tk/profiles.json` (Linux), `~/Library/Application Support/freerdp-tk/` (macOS), `%APPDATA%\freerdp-tk\` (Windows) |
| Extra FreeRDP source trees to search for built clients | `FREERDP_TK_TREES`, separated like `PATH`. `~/projects/FreeRDP` is always searched. |

## Limitation

The client runs without a terminal, so it cannot ask questions while connecting, such as whether to trust a new certificate. Pick a certificate policy (`tofu`, `ignore` or `deny`) on the Connection tab instead. The default, `tofu`, trusts a server's certificate the first time you connect.

## Development

```bash
uv run --with-editable . python -m freerdp_tk   # run from the checkout
uv build                                         # build the sdist and wheel into dist/
```

The screenshot above is rendered from demo data in a virtual X server, so no real hosts end up in it. Regenerate it after changing the UI:

```bash
xvfb-run -s "-screen 0 1400x1000x24" \
    uv run --with pillow --with-editable . python scripts/screenshot.py docs/screenshot.png
```

### Releasing to PyPI

Releases are published by GitHub Actions through [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no API token is needed. The version is taken from the git tag.

One-time setup:
1. On PyPI, open *Your projects → Publishing → Add a new pending publisher* and enter: project `freerdp-tk`, owner `congzhangzh`, repository `freerdp-tk`, workflow `release.yml`, environment `pypi`.
2. On GitHub, create an environment named `pypi` (*Settings → Environments*).

Each release after that:

```bash
git tag 0.2.0          # the version, no prefix
git push origin 0.2.0
```

The workflow builds the package, checks that it installs on Linux, Windows and macOS, and then uploads it to PyPI.

## License

Apache-2.0, the same license as FreeRDP.
