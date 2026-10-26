"""The distribution's own FreeRDP client, started from the window.

Skipped when no FreeRDP 3 SDL client is installed. It connects to a closed local
port, so no server is needed: the client must read its arguments from stdin,
try that address and fail, and the window must show its output and exit code.
It also lists the monitors, in the format parse_monitors() reads.
"""

import re
import socket

import pytest

from freerdp_tk import app
from helpers import button, click, entry_for, log_text, pump, type_into


@pytest.fixture
def real_client(home):
    clients = app.find_clients()
    if not clients or app.client_major_version(clients[0]) < 3:
        pytest.skip("no FreeRDP 3 SDL client installed")
    return clients[0]


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_client_reads_args_from_stdin(make_ui, real_client):
    ui = make_ui()
    port = closed_port()
    type_into(ui, entry_for(ui, ui.vars["host"]), "127.0.0.1")
    type_into(ui, entry_for(ui, ui.vars["port"]), str(port))
    type_into(ui, entry_for(ui, ui.vars["user"]), "alice")
    type_into(ui, entry_for(ui, ui.password), "s3cret!")
    click(ui, button(ui, "Connect"))

    pump(ui, lambda: "exited with code" in log_text(ui), timeout=60)
    log = log_text(ui)
    print(log)
    assert f"started: {real_client} /v:127.0.0.1 /port:{port}" in log
    code = int(re.search(r"exited with code (-?\d+)", log).group(1))
    assert code != 0  # nothing listens there
    assert "s3cret" not in log
    # the client got /v and /port through stdin: its own messages name the target
    assert str(port) in log.split("started:", 1)[1].split("\n", 1)[1]


def test_real_client_lists_monitors(real_client):
    monitors, output = app.list_monitors(real_client)
    print(output)
    assert monitors, output  # the virtual X server's screen, in the format parse_monitors reads
    assert all(m["id"].isdigit() for m in monitors)
