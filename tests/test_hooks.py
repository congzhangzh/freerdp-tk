"""Before/after commands around a session, with the fake client."""

import json
import shlex
import sys
import time

import pytest
from helpers import alive, button, click, entry_for, log_text, pump, type_into

# Stands in for `ssh -D`: listens on the port it is given, writes its pid, then waits.
TUNNEL = """import os, socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", int(sys.argv[1])))
s.listen()
open(sys.argv[2], "w").write(str(os.getpid()))
print("tunnel up on", sys.argv[1], flush=True)
time.sleep(120)
"""


# Stands in for a script that starts a proxy and returns: the proxy is the
# tunnel above, up only a second later.
STARTER = """import subprocess, sys
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1); " + open(sys.argv[1]).read(),
                  *sys.argv[2:]], stdout=sys.stdout)
"""


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
    assert ui.vars["pre_wait_kind"].get() == app.WAIT_PORT


def test_wait_also_follows_a_command_that_runs_to_its_end(make_ui, fake_client, home):
    starter, tunnel, pidfile = home / "starter.py", home / "tunnel.py", home / "tunnel.pid"
    starter.write_text(STARTER)
    tunnel.write_text(TUNNEL)
    ui = make_ui()
    fill(ui, host="rdp.example.com",
         pre=f"{q(sys.executable)} {q(starter)} {q(tunnel)} %L {q(pidfile)}",
         pre_wait="127.0.0.1:%L")
    click(ui, button(ui, "Connect"))
    pump(ui, ended(ui))

    log = log_text(ui)
    assert log.index("tunnel up") < log.index("started:")
    assert fake_client.exists() and not alive(int(pidfile.read_text()))


def test_wait_for_output(make_ui, fake_client, home):
    script, pidfile = home / "tunnel.py", home / "tunnel.pid"
    script.write_text("import time; time.sleep(0.5); " + TUNNEL)
    ui = make_ui()
    ui.vars["pre_async"].set(True)
    fill(ui, host="rdp.example.com", pre=f"{q(sys.executable)} {q(script)} %L {q(pidfile)}",
         pre_wait_kind="the output shows", pre_wait=r"up on %L$")
    click(ui, button(ui, "Connect"))
    pump(ui, ended(ui))

    log = log_text(ui)
    assert log.index("tunnel up") < log.index("started:")
    assert fake_client.exists() and not alive(int(pidfile.read_text()))


def test_output_that_never_comes_gives_up(make_ui, fake_client):
    ui = make_ui()
    ui.vars["pre_async"].set(True)
    fill(ui, host="rdp.example.com",
         pre=python("import time; print('hello', flush=True); time.sleep(120)"),
         pre_wait_kind="the output shows", pre_wait="ready", pre_timeout="1")
    click(ui, button(ui, "Connect"))
    pump(ui, ended(ui))

    assert "gave up waiting for output 'ready' after 1 s, not connecting" in log_text(ui)
    assert not fake_client.exists()


def test_wait_for_seconds(make_ui, fake_client):
    ui = make_ui()
    fill(ui, host="rdp.example.com", pre=python("pass"),
         pre_wait_kind="seconds have passed", pre_wait="1")
    began = time.monotonic()
    click(ui, button(ui, "Connect"))
    pump(ui, fake_client.exists)

    assert time.monotonic() - began >= 1
    pump(ui, ended(ui))


def test_timeout_stops_a_command_that_never_ends(make_ui, fake_client, home):
    pidfile, after = home / "stuck.pid", home / "after.txt"
    ui = make_ui()
    fill(ui, host="rdp.example.com", pre_timeout="1",
         pre=python(f"import os, time; open(r'{pidfile}', 'w').write(str(os.getpid())); "
                    "time.sleep(120)"),
         post=python(f"open(r'{after}', 'w')"))
    click(ui, button(ui, "Connect"))
    pump(ui, ended(ui))

    assert "still running after 1 s, not connecting" in log_text(ui)
    assert not fake_client.exists() and after.exists()
    assert not alive(int(pidfile.read_text()))


@pytest.mark.parametrize("fields, message", [
    ({"pre_wait": "nonsense"}, "expected host:port"),
    ({"pre_wait": "x", "pre_wait_kind": "seconds have passed"}, "wait for 'x': expected seconds"),
    ({"pre_wait": "(", "pre_wait_kind": "the output shows"}, "wait for output '('"),
    ({"pre_timeout": "soon"}, "give up after 'soon': expected seconds"),
])
def test_a_typing_mistake_starts_nothing(make_ui, fake_client, home, fields, message):
    marker = home / "ran.txt"
    ui = make_ui()
    fill(ui, host="rdp.example.com", pre=python(f"open(r'{marker}', 'w')"), **fields)
    click(ui, button(ui, "Connect"))
    pump(ui, ended(ui))

    assert message in log_text(ui)
    assert not marker.exists() and not fake_client.exists()
