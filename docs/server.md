# The other side: installing FreeRDP's shadow server

freerdp-tk connects to any RDP server. To share a computer's own screen with it, the
[rdp-release-kit](https://github.com/congzhangzh/rdp-release-kit) builds FreeRDP's **shadow
server** for Linux, Windows and macOS, from the same FreeRDP as the bundled client. It shares
the desktop that is already there (the one you see on that computer's screen), and sends it
in AV2 to clients that offer it (freerdp-tk's bundled client, FreeRDP Web), AV1 to the others,
and H.264 to the rest (Windows' own Remote Desktop client, most others) where the system has an
encoder.

## The codecs each server sends

| Codec | Linux | Windows | macOS |
|---|---|---|---|
| AV2 (to clients that offer it) | yes | yes | yes |
| AV1 | yes | yes | yes |
| H.264 (AVC420) | no: it has no H.264 encoder, a client without AV1 or AV2 gets RemoteFX or the older bitmap codecs | yes, through Media Foundation | yes, through VideoToolbox (in hardware where the Mac has it) |
| H.264 AVC444 | no | off for now: its picture turned blocky with Media Foundation | off by default (it sent 15–18 times the bytes); remove `-gfx-avc444` from the plist to allow it |
| H.265 | not yet | not yet | not yet |

AV1 and AV2 are software encodes on every host (libaom, libavm); AV2 costs the server more
processor time. AV1 only: `/gfx-av2:off` in place of `/gfx-av2` (Linux: the unit's
`ExecStart`; Windows: the install line; macOS: the plist).

Download it from the kit's **[latest release](https://github.com/congzhangzh/rdp-release-kit/releases/latest)**;
the release's `SHA256SUMS` has the checksums.

## Keep RDP off the internet

RDP servers are a frequent target. Let the server listen on 127.0.0.1 only and reach it over
SSH. In freerdp-tk: *Before / after → Fill in: SSH tunnel…*, with the server itself as the
jump host, and `127.0.0.1` as the *Host* on the *Connection* tab. The tunnel then opens on
that computer's own loopback, and nothing but SSH is open to the network.

## Linux (GNOME on Wayland or X11, or any X11 desktop)

`freerdp-host-<version>-linux-x86_64.tar.xz` (or `-aarch64`). In the desktop session you want
to share, as your own user:

```sh
tar -xJf freerdp-host-*-linux-$(uname -m).tar.xz
mkdir -p ~/.local/opt ~/.config/systemd/user
mv freerdp-host-*-linux-$(uname -m) ~/.local/opt/freerdp-host
cp ~/.local/opt/freerdp-host/freerdp-shadow.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now freerdp-shadow.service
```

It binds to 127.0.0.1 only, starts with the desktop session, and logs to
`journalctl --user -u freerdp-shadow`. You log in as the account whose desktop it is.
More (an earlier version, Xfce or MATE, removing it): the kit's
[Installing the Linux host](https://github.com/congzhangzh/rdp-release-kit#installing-the-linux-host).

## Windows

The Windows host archive. In an administrator's PowerShell, in its folder:

```powershell
.\freerdp-shadow-service.exe install --allow-sas -- /bind-address:127.0.0.1 /gfx-av1 /gfx-av2 -gfx-avc444
```

It runs as a service, starts with Windows, and shares the console: the desktop of whoever is
logged in, and the logon and lock screens too. If Windows' own Remote Desktop is on, it holds
port 3389: add `/port:3388`. For the SSH tunnel, turn on Windows' *OpenSSH Server*
(optional feature). `--allow-sas` lets it send Ctrl+Alt+Del; leave it out if you don't want
that. Remove it with `.\freerdp-shadow-service.exe uninstall`. The archive's `README.txt` has
the rest.

## macOS

The macOS host archive (Apple Silicon; the kit builds none for Intel Macs), then:

```sh
cp -R FreeRDP-Shadow.app /Applications/
xattr -dr com.apple.quarantine /Applications/FreeRDP-Shadow.app
cp org.freerdp.shadow.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.freerdp.shadow.plist
```

The first start asks for two permissions in *System Settings → Privacy & Security*: *Screen &
System Audio Recording* and *Accessibility*. Allow *FreeRDP Shadow* in both, then
`launchctl kickstart -k gui/$(id -u)/org.freerdp.shadow`. The app is signed without a developer
certificate, so macOS asks again after each update. For the SSH tunnel, turn on *Remote Login*
in *System Settings → General → Sharing*. The archive's `README.txt` has the rest, and how to
remove it.
