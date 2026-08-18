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
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Final

import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.store.store import Store
from zikaron.hook import connect as connect_module
from zikaron.hook.connect import connect_once, default_server_command

pytestmark = pytest.mark.integration


#: Generous on purpose, and **not** the shipped value. See `_mechanism_not_the_shipped_deadline`.
_MECHANISM_DEADLINE_SECONDS: Final = 30.0


@pytest.fixture(autouse=True)
def _mechanism_not_the_shipped_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests assert that cold start-if-absent **works**, not that it beats the user-facing
    deadline — because the design says it may lose that race, on purpose.

    `connect.HEALTH_POLL_DEADLINE_SECONDS` is 1.2 s and its own comment explains why it is short:
    *"a cold spawn racing this deadline and losing is exactly the case that must degrade (log to
    `hook.log`, relay on stdout) rather than make the user wait."* Losing is a **specified
    outcome**, and `test_hook_connect_integration.py` covers it against a fake service that binds
    5 s after spawn.

    So asserting a real cold start finishes inside 1.2 s asserts a guarantee this project declines
    to make, and whether it holds depends on the machine rather than the code. Measured on a loaded
    developer box (load ~6, three concurrent agent sessions): a real service takes **1184-1235 ms
    merely to bind its socket** — before `health()` can answer at all — because `main.py` assembles
    the store and loads the encoder *first*, deliberately, so it never advertises a store it could
    not open. Both tests here failed deterministically, and had passed all day at lower load.

    The number they were calibrated against never described this peer: `spike-results.md` §"Cold
    start" measured **~101 ms**, "dominated by Python interpreter start", against spike 3's toy
    server — no store, no `fastembed`. The shipped constant is still right for the *user*; it was
    simply never a claim about the real service's cold start.

    Overriding it here keeps these tests about the mechanism — connect, spawn, poll, reuse — and
    leaves the shipped value asserted where it belongs, in the fake-service timing tests.
    """
    monkeypatch.setattr(connect_module, "HEALTH_POLL_DEADLINE_SECONDS", _MECHANISM_DEADLINE_SECONDS)


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


def test_connects_to_a_cold_started_real_service(store: tuple[Path, str], tmp_path: Path) -> None:
    store_dir, store_id = store
    sock_path = tmp_path / "test.sock"
    command = default_server_command(sock_path, store_dir)
    sock = connect_once(
        sock_path,
        store_db_path=store_dir / "memory.db",
        store_id=store_id,
        server_command=command,
    )
    health_pid = _read_health_pid(sock)
    sock.close()
    _kill_and_reap(health_pid)


def test_connecting_to_an_already_warm_real_service_reuses_it(
    store: tuple[Path, str], tmp_path: Path
) -> None:
    """A second `connect_once` call against a store the first call already warmed must connect
    directly rather than spawning a second server — the ordinary case every real
    `userPromptSubmit` after the first in a session goes through."""
    store_dir, store_id = store
    sock_path = tmp_path / "test.sock"
    command = default_server_command(sock_path, store_dir)

    first = connect_once(
        sock_path, store_db_path=store_dir / "memory.db", store_id=store_id, server_command=command
    )
    first_pid = _read_health_pid(first)
    first.close()
    try:
        second = connect_once(
            sock_path,
            store_db_path=store_dir / "memory.db",
            store_id=store_id,
            server_command=[sys.executable, "-c", "raise SystemExit(1)"],  # must never run
        )
        second_pid = _read_health_pid(second)
        second.close()
        assert second_pid == first_pid
    finally:
        _kill_and_reap(first_pid)
