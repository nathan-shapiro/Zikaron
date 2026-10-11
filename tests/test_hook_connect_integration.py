"""`zikaron.hook.connect.connect_once`: the spawn-if-absent branch, against real subprocesses.

Integration tier: every test here spawns a real `python3` subprocess to answer the socket, which
is exactly what `coding-standards.md` §4 reserves the `integration` marker for.
"""

import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

import pytest

from zikaron.hook import connect
from zikaron.hook.connect import HookTransportError, ServiceStartingError, connect_once

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


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[subprocess.Popen[bytes]]]:
    """Every child `connect_once` spawns, killed and reaped afterwards: a service that never
    answered is still running when the attempt gives up on it, by construction."""
    children: list[subprocess.Popen[bytes]] = []
    real_spawn = connect._spawn_detached

    def _recording_spawn(server_command: Sequence[str]) -> subprocess.Popen[bytes]:
        child = real_spawn(server_command)
        children.append(child)
        return child

    monkeypatch.setattr(connect, "_spawn_detached", _recording_spawn)
    yield children
    for child in children:
        child.kill()
        child.wait(timeout=5.0)


def test_spawns_and_waits_for_a_slow_but_real_service_and_calls_it_cold(
    tmp_path: Path, socket_dir: Path, delayed_server_script: Path
) -> None:
    sock_path = socket_dir / "test.sock"
    store_db_path = tmp_path / "memory.db"
    command = [
        sys.executable,
        str(delayed_server_script),
        str(sock_path),
        "200",  # bind 200ms after spawn — well inside the poll deadline below
        str(store_db_path),
        "the-store-id",
    ]
    connection = connect_once(
        sock_path,
        store_db_path=store_db_path,
        store_id="the-store-id",
        server_command=command,
        poll_deadline=time.monotonic() + 10.0,
    )
    connection.sock.close()
    assert connection.cold_start is True


def test_a_spawn_still_starting_at_the_deadline_is_service_starting_error(
    tmp_path: Path,
    socket_dir: Path,
    delayed_server_script: Path,
    spawned: list[subprocess.Popen[bytes]],
) -> None:
    """The single-attempt contract: this must raise rather than retry a second start-if-absent
    sequence — and with the subclass that says the start is slow, since the child is alive."""
    sock_path = socket_dir / "test.sock"
    store_db_path = tmp_path / "memory.db"
    command = [
        sys.executable,
        str(delayed_server_script),
        str(sock_path),
        "5000",  # far longer than the poll deadline below
        str(store_db_path),
        "irrelevant",
    ]
    with pytest.raises(ServiceStartingError):
        connect_once(
            sock_path,
            store_db_path=store_db_path,
            store_id=None,
            server_command=command,
            poll_deadline=time.monotonic() + 0.5,
        )
    assert len(spawned) == 1
    assert spawned[0].poll() is None, "the child must still be running when the attempt gives up"


def test_a_spawn_that_exits_ends_the_poll_before_its_deadline(
    tmp_path: Path, socket_dir: Path, spawned: list[subprocess.Popen[bytes]]
) -> None:
    """A service that cannot start must not cost the caller its whole deadline, and must not read
    as one still starting: the poll ends when its child exits."""
    sock_path = socket_dir / "test.sock"
    started = time.monotonic()
    with pytest.raises(HookTransportError) as raised:
        connect_once(
            sock_path,
            store_db_path=tmp_path / "memory.db",
            store_id=None,
            server_command=[sys.executable, "-c", "raise SystemExit(3)"],
            poll_deadline=started + 60.0,
        )
    assert not isinstance(raised.value, ServiceStartingError)
    assert time.monotonic() - started < 30.0, "the poll waited for its deadline, not its child"
    assert spawned[0].returncode == 3


def test_vets_and_clears_a_stale_socket_before_spawning(tmp_path: Path, socket_dir: Path) -> None:
    """A socket file left behind by a service that died without cleaning up — `architecture.md`:
    "`ECONNREFUSED`... is the signature of a service that died without cleaning up — unlink and
    respawn rather than reporting an error." Simulated with a bound-but-not-listening socket,
    then a real spawn that must succeed despite the stale file being present.
    """
    sock_path = socket_dir / "test.sock"
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
    connection = connect_once(
        sock_path,
        store_db_path=store_db_path,
        store_id="fresh-id",
        server_command=command,
        poll_deadline=time.monotonic() + 10.0,
    )
    connection.sock.close()
