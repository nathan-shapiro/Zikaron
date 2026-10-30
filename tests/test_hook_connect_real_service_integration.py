"""`zikaron.hook.connect.connect_once` against the real `zikaron.service.main` process.

Integration tier, per `coding-standards.md` §4: a real spawned subprocess, real `fastembed`,
real `sqlite-vec`. This is the actual production peer `connect_once` talks to under kiro, distinct
from `test_hook_connect_integration.py`'s hand-rolled fake service scripts, which exist to isolate
`connect_once`'s own socket-level logic (single-answer-per-connection, spawn timing) from the real
service's cold-start cost.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Final

import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.store.store import Store
from zikaron.hook.connect import connect_once, default_server_command
from zikaron.service import paths

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("generous_hook_deadlines")]


#: Generous on purpose, and past the shipped cold-start deadline: these tests assert that cold
#: start-if-absent **works** — connect, spawn, poll, reuse — not that it beats the deadline a user
#: waits on. Losing that race on a slow enough machine is a specified outcome, which
#: `test_hook_connect_integration.py` covers against a fake service, so asserting a real cold start
#: fits the shipped value would make these tests depend on the machine rather than the code.
_MECHANISM_DEADLINE_SECONDS: Final = 30.0


MODEL: Final = "BAAI/bge-small-en-v1.5"


@pytest.fixture(scope="module")
def encoder() -> FastEmbedEncoder:
    return FastEmbedEncoder.load(MODEL)


def _config(store_dir: Path) -> EffectiveConfig:
    return resolve(store_dir / "system.toml", store_dir / "config.toml")


async def _create_store(store_dir: Path, encoder: FastEmbedEncoder) -> str:
    async with await Store.create(store_dir, _config(store_dir.parent), encoder) as created:
        return created.meta.store_id


@pytest.fixture
def store(tmp_path: Path, encoder: FastEmbedEncoder) -> tuple[Path, str]:
    store_dir = tmp_path / "project" / ".zikaron"
    store_dir.mkdir(parents=True)
    store_id = asyncio.run(_create_store(store_dir, encoder))
    return store_dir, store_id


def _reap(pid: int, *, deadline_seconds: float) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if reaped_pid != 0:
            return
        time.sleep(0.02)
    raise TimeoutError(f"pid {pid} never exited")


def _kill_and_reap(pid: int) -> None:
    with suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    with suppress(TimeoutError):
        _reap(pid, deadline_seconds=10.0)


def _read_health_pid(sock: socket.socket) -> int:
    """Ask the real service's own `health()` again over the still-open connection for its pid,
    purely so this test's own cleanup can terminate the exact process it caused to spawn —
    `connect_once` itself never needs a pid and does not track one; this is test bookkeeping only.
    """
    sock.sendall(b'{"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}\n')
    buffer = b""
    while not buffer.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed before a full response was read")
        buffer += chunk
    parsed = json.loads(buffer.decode("utf-8"))
    pid = parsed["result"]["pid"]
    assert isinstance(pid, int)
    return pid


def test_connects_to_a_cold_started_real_service(store: tuple[Path, str], socket_dir: Path) -> None:
    store_dir, store_id = store
    sock_path = socket_dir / "test.sock"
    command = default_server_command(sock_path, store_dir)
    connection = connect_once(
        sock_path,
        store_db_path=store_dir / "memory.db",
        store_id=store_id,
        server_command=command,
        poll_deadline=time.monotonic() + _MECHANISM_DEADLINE_SECONDS,
    )
    health_pid = _read_health_pid(connection.sock)
    connection.sock.close()
    _kill_and_reap(health_pid)
    assert connection.cold_start is True


def test_connecting_to_an_already_warm_real_service_reuses_it(
    store: tuple[Path, str], socket_dir: Path
) -> None:
    """A second `connect_once` call against a store the first call already warmed must connect
    directly rather than spawning a second server — the ordinary case every real
    `UserPromptSubmit` after the first in a session goes through."""
    store_dir, store_id = store
    sock_path = socket_dir / "test.sock"
    command = default_server_command(sock_path, store_dir)

    first = connect_once(
        sock_path,
        store_db_path=store_dir / "memory.db",
        store_id=store_id,
        server_command=command,
        poll_deadline=time.monotonic() + _MECHANISM_DEADLINE_SECONDS,
    )
    first_pid = _read_health_pid(first.sock)
    first.sock.close()
    try:
        second = connect_once(
            sock_path,
            store_db_path=store_dir / "memory.db",
            store_id=store_id,
            server_command=[sys.executable, "-c", "raise SystemExit(1)"],  # must never run
            poll_deadline=time.monotonic() + _MECHANISM_DEADLINE_SECONDS,
        )
        second_pid = _read_health_pid(second.sock)
        second.sock.close()
        assert second_pid == first_pid
        assert second.cold_start is False
    finally:
        _kill_and_reap(first_pid)


#: How long a second start is watched: past the moment it would have bound over the first had
#: nothing stopped it, since a start over an existing store binds before its model loads.
_TAKEOVER_WATCH_SECONDS: Final = 3.0


def test_a_second_start_for_a_served_store_does_not_take_it_over(
    store: tuple[Path, str], socket_dir: Path
) -> None:
    """The case start-if-absent's own lock cannot cover, since a client holds that only through its
    poll: a start that outlived one client's poll is started again by the next. The second service
    must wait for the store rather than open it beside the first — `asyncio.start_unix_server`
    would remove the first one's socket file and bind its own in its place."""
    store_dir, store_id = store
    sock_path = socket_dir / "test.sock"
    command = default_server_command(sock_path, store_dir)
    first = connect_once(
        sock_path,
        store_db_path=store_dir / "memory.db",
        store_id=store_id,
        server_command=command,
        poll_deadline=time.monotonic() + _MECHANISM_DEADLINE_SECONDS,
    )
    first_pid = _read_health_pid(first.sock)
    first.sock.close()
    second = subprocess.Popen(  # noqa: S603 — the service's own argv, built above.
        command,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        watched_until = time.monotonic() + _TAKEOVER_WATCH_SECONDS
        while time.monotonic() < watched_until:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(5.0)
                probe.connect(str(sock_path))
                assert _read_health_pid(probe) == first_pid
            time.sleep(0.1)
        assert second.poll() is None, "the second start should still be waiting for the store"
        held_by = paths.service_lock_path(sock_path).read_text(encoding="ascii")
        assert held_by == f"{first_pid}\n", "the first service should still hold the store"
    finally:
        second.kill()
        second.wait(timeout=10.0)
        _kill_and_reap(first_pid)
