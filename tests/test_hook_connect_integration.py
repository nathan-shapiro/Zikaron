"""`zikaron.hook.connect.connect_once`: the spawn-if-absent branch, against real subprocesses.

Integration tier: every test here spawns a real `python3` subprocess to answer the socket, which
is exactly what `coding-standards.md` §4 reserves the `integration` marker for.
"""

import socket
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from zikaron.hook.connect import HookTransportError, connect_once

pytestmark = pytest.mark.integration

#: A tiny script that binds the socket after a deliberate delay and answers exactly one
#: `health()` — simulates a service that is genuinely starting rather than already dead, so
#: `connect_once`'s spawn-and-poll branch has something real to observe rather than an instantly
#: bound socket that would never exercise the polling loop meaningfully.
_DELAYED_SERVER_SCRIPT: Final = """
import json
import socket
import sys
import time

sock_path, delay_ms, store_path, store_id = sys.argv[1:5]
time.sleep(int(delay_ms) / 1000)
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(sock_path)
server.listen(1)
connection, _ = server.accept()
buffer = b""
while not buffer.endswith(b"\\n"):
    chunk = connection.recv(4096)
    if not chunk:
        break
    buffer += chunk
request = json.loads(buffer.decode("utf-8"))
response = {
    "jsonrpc": "2.0",
    "id": request.get("id", 1),
    "result": {"ready": True, "store_path": store_path, "store_id": store_id},
}
connection.sendall((json.dumps(response) + "\\n").encode("utf-8"))
connection.close()
server.close()
"""


@pytest.fixture
def delayed_server_script(tmp_path: Path) -> Path:
    script = tmp_path / "delayed_server.py"
    script.write_text(_DELAYED_SERVER_SCRIPT, encoding="utf-8")
    return script


def test_spawns_and_waits_for_a_slow_but_real_service(
    tmp_path: Path, delayed_server_script: Path
) -> None:
    sock_path = tmp_path / "test.sock"
    store_db_path = tmp_path / "memory.db"
    command = [
        sys.executable,
        str(delayed_server_script),
        str(sock_path),
        "200",  # bind 200ms after spawn — inside connect.HEALTH_POLL_DEADLINE_SECONDS
        str(store_db_path),
        "the-store-id",
    ]
    sock = connect_once(
        sock_path, store_db_path=store_db_path, store_id="the-store-id", server_command=command
    )
    sock.close()


def test_a_spawn_too_slow_to_answer_before_the_deadline_raises(
    tmp_path: Path, delayed_server_script: Path
) -> None:
    """The single-attempt contract: this must raise rather than retry a second start-if-absent
    sequence, per the user's explicit instruction that the hook makes exactly one attempt."""
    sock_path = tmp_path / "test.sock"
    store_db_path = tmp_path / "memory.db"
    command = [
        sys.executable,
        str(delayed_server_script),
        str(sock_path),
        "5000",  # far longer than connect.HEALTH_POLL_DEADLINE_SECONDS
        str(store_db_path),
        "irrelevant",
    ]
    process = subprocess.Popen(command)  # noqa: S603 — a fixed, test-constructed argv.
    try:
        with pytest.raises(HookTransportError):
            connect_once(
                sock_path,
                store_db_path=store_db_path,
                store_id=None,
                server_command=["python3", "-c", "pass"],  # never invoked: process already spawned
            )
    finally:
        process.kill()
        process.wait(timeout=5.0)


def test_vets_and_clears_a_stale_socket_before_spawning(tmp_path: Path) -> None:
    """A socket file left behind by a service that died without cleaning up — `architecture.md`:
    "`ECONNREFUSED`... is the signature of a service that died without cleaning up — unlink and
    respawn rather than reporting an error." Simulated with a bound-but-not-listening socket,
    then a real spawn that must succeed despite the stale file being present.
    """
    sock_path = tmp_path / "test.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(sock_path))
    stale.close()  # bound and closed: the file exists, but nothing is listening (ECONNREFUSED)

    store_db_path = tmp_path / "memory.db"
    script = tmp_path / "immediate_server.py"
    script.write_text(_DELAYED_SERVER_SCRIPT, encoding="utf-8")
    command = [
        sys.executable,
        str(script),
        str(sock_path),
        "0",
        str(store_db_path),
        "fresh-id",
    ]
    sock = connect_once(
        sock_path, store_db_path=store_db_path, store_id="fresh-id", server_command=command
    )
    sock.close()
