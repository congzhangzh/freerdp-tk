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
processor time. AV1 only: `/gfx-av2:off` in place of `/gfx-av2` (Windows: the install line; Linux: the
unit's `ExecStart`; macOS: the plist).

Download it from the kit's **[latest release](https://github.com/congzhangzh/rdp-release-kit/releases/latest)**;
the release's `SHA256SUMS` has the checksums.

## Keep RDP off the internet

RDP servers are a frequent target. The kit's server listens on **127.0.0.1:3388** only, on
every OS (3389 stays free for the system's own RDP servers: Windows' Remote Desktop, GNOME
Remote Desktop, xrdp). Keep it that way and reach it over SSH. In freerdp-tk: *Before / after →
Fill in: SSH tunnel…*, with the server itself as the jump host; on the *Connection* tab,
`127.0.0.1` as the *Host* and **3388 as the *Port*** (an empty *Port* means RDP's usual 3389,
where the kit's server does not listen). The tunnel then opens on that computer's own
loopback, and nothing but SSH is open to the network.

Without freerdp-tk's tunnel, forward a local port yourself and connect freerdp-tk to
`127.0.0.1`, *Port* 13388:

```sh
ssh -N -L 13388:127.0.0.1:3388 user@host
```

## Windows

The Windows host archive. In an administrator's PowerShell, in its folder:

```powershell
.\freerdp-shadow-service.exe install --allow-sas -- /bind-address:127.0.0.1 /port:3388 /gfx-av1 /gfx-av2 -gfx-avc444
```

It runs as a service, starts at once and with Windows, on port 3388, and shares the console:
the desktop of whoever is logged in, and the logon and lock screens too. For the SSH tunnel,
turn on Windows' *OpenSSH Server* (optional feature). `--allow-sas` lets it send
Ctrl+Alt+Del; leave it out if you don't want that. Remove it with
`.\freerdp-shadow-service.exe uninstall`. Without a service, for the logged-on user's desktop
only: `.\freerdp-shadow-cli.exe /bind-address:127.0.0.1 /port:3388 /gfx-av1 /gfx-av2`. The
archive's `README.txt` has the rest.

## Linux (GNOME on Wayland or X11, or any X11 desktop)

`freerdp-host-<version>-linux-x86_64.tar.xz` (or `-aarch64`).

**With GNOME, as root: the session manager.** One service for every user of the computer,
there before anyone logs in: it hands each user, logged in with their own password, to a
shadow server in their own GNOME session, and can start a headless GNOME for a user who has
none (details: the kit's [session manager](https://github.com/congzhangzh/rdp-release-kit#the-session-manager-runs-as-root)):

```sh
sudo tar -xJf freerdp-host-*-linux-$(uname -m).tar.xz -C /opt
sudo mv /opt/freerdp-host-*-linux-$(uname -m) /opt/freerdp-host
sudo chown -R root:root /opt/freerdp-host
sudo cp /opt/freerdp-host/freerdp-shadow-sesman.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now freerdp-shadow-sesman.service
```

**Without root, or on another X11 desktop: the user unit**, as yourself, in the desktop session
you want to share (details: the kit's [user unit](https://github.com/congzhangzh/rdp-release-kit#the-user-unit-your-own-desktop-no-root)):

```sh
tar -xJf freerdp-host-*-linux-$(uname -m).tar.xz
mkdir -p ~/.local/opt ~/.config/systemd/user
mv freerdp-host-*-linux-$(uname -m) ~/.local/opt/freerdp-host
cp ~/.local/opt/freerdp-host/freerdp-shadow.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now freerdp-shadow.service
```

It starts with the desktop session, logs to `journalctl --user -u freerdp-shadow`, and lets in
the desktop's owner only. Both listen on 127.0.0.1:3388: install one or the other.

## macOS

The macOS host archive (Apple Silicon; the kit builds none for Intel Macs), then:

```sh
cp -R FreeRDP-Shadow.app /Applications/
xattr -dr com.apple.quarantine /Applications/FreeRDP-Shadow.app
cp org.freerdp.shadow.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.freerdp.shadow.plist
```

It listens on 127.0.0.1:3388 in your login session. The first start asks for two permissions
in *System Settings → Privacy & Security*: *Screen & System Audio Recording* and
*Accessibility*. Allow *FreeRDP Shadow* in both, then
`launchctl kickstart -k gui/$(id -u)/org.freerdp.shadow`. The app is signed without a developer
certificate, so macOS asks again after each update. For the SSH tunnel, turn on *Remote Login*
in *System Settings → General → Sharing*. The archive's `README.txt` has the rest, and how to
remove it.
