"""Before/after commands around a session, with the fake client."""

import json
import os
import shlex
import subprocess
import sys

from helpers import button, click, entry_for, log_text, pump, type_into

# Stands in for `ssh -D`: listens on the port it is given, writes its pid, then waits.
TUNNEL = """import os, socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen()
open(sys.argv[2], "w").write(str(os.getpid()))
print("tunnel up on", sys.argv[1], flush=True)
time.sleep(120)
"""


def alive(pid: int) -> bool:
    """Whether the process still runs (a zombie counts as gone)."""
    if sys.platform == "win32":  # os.kill(pid, 0) would terminate it on Windows
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) in out.split()
    if os.path.exists("/proc"):
        try:
            with open(f"/proc/{pid}/stat") as f:
                return f.read().split(")")[-1].split()[0] != "Z"
        except FileNotFoundError:
            return False
    out = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    return out.returncode == 0 and not out.stdout.strip().startswith("Z")


def q(path) -> str:
    """Quote a path for the shell that runs the before/after commands."""
    return f'"{path}"' if sys.platform == "win32" else shlex.quote(str(path))


def python(code: str) -> str:
    """A command line that runs Python code, the same under sh and cmd.exe."""
    return f'{q(sys.executable)} -c "{code}"'


def fill(ui, host, **fields):
    """Type the host like a user, set the shell commands directly (test_ui covers typing)."""
    type_into(ui, entry_for(ui, ui.vars["host"]), host)
    for key, text in fields.items():
        ui.vars[key].set(text)


def ended(ui):
    return lambda: ui.running_list.size() == 0


def test_tunnel_runs_beside_the_session_and_is_stopped(make_ui, fake_client, home):
    script, pidfile, after = home / "tunnel.py", home / "tunnel.pid", home / "after.txt"
    script.write_text(TUNNEL)
    ui = make_ui()
    ui.vars["pre_async"].set(True)
    fill(ui, host="rdp.example.com",
         pre=f"{q(sys.executable)} {q(script)} %L {q(pidfile)}",
         pre_wait="127.0.0.1:%L",
         proxy="socks5://127.0.0.1:%L",
         post=python(f"open(r'{after}', 'w').write('bye %h')"))
    click(ui, button(ui, "Connect"))
    pump(ui, ended(ui))

    log = log_text(ui)
    port = log.split("tunnel up on ")[1].split()[0]
    got = json.loads(fake_client.read_text())
    assert f"/proxy:socks5://127.0.0.1:{port}" in got["stdin"].splitlines()
    assert "before: stopped" in log and not alive(int(pidfile.read_text()))
    assert after.read_text().strip() == "bye rdp.example.com"
    order = [log.index(s) for s in ("tunnel up", "started:", "exited with code 7",
                                    "before: stopped", "after: exited with code 0")]
    assert order == sorted(order)


def test_failing_before_command_stops_the_connection(make_ui, fake_client, home):
    after = home / "after.txt"
    ui = make_ui()
    fill(ui, host="rdp.example.com", pre=python("print('nope'); raise SystemExit(3)"),
         post=python(f"open(r'{after}', 'w')"))
    click(ui, button(ui, "Connect"))
    pump(ui, ended(ui))

    log = log_text(ui)
    assert "before: nope" in log and "before: failed with code 3, not connecting" in log
    assert not fake_client.exists()  # the client never ran
    assert after.exists()  # the after command runs however the session ended


def test_ssh_tunnel_preset(make_ui, fake_client, monkeypatch):
    from freerdp_tk import app
    monkeypatch.setattr(app.simpledialog, "askstring", lambda *a, **k: "me@bastion")
    ui = make_ui()
    ui._ssh_tunnel()
    assert ui.vars["pre"].get() == ("ssh -N -D 127.0.0.1:%L -o ExitOnForwardFailure=yes "
                                    "-o BatchMode=yes me@bastion")
    assert ui.vars["pre_async"].get() and ui.vars["pre_cleanup"].get()
    assert ui.vars["proxy"].get() == "socks5://127.0.0.1:%L"
    assert "/proxy:socks5://127.0.0.1:%L" in ui.preview.get("1.0", "end")  # filled at connect
