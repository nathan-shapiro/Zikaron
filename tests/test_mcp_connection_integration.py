"""`zikaron.mcp.connection.ServiceConnection` — real start-if-absent, and real recovery from a
service that died between two calls, against a real spawned `zikaron-service` subprocess.

Integration tier throughout (`coding-standards.md` §4): every test here lets `ServiceConnection`
spawn a real `python -m zikaron.service.main` process and speaks real Unix-domain-socket JSON-RPC
to it — `test_service_lifecycle_integration.py` already covers `connect_start_if_absent`'s own
race conditions exhaustively at that layer, so these tests are deliberately narrower: they check
the MCP-specific behavior built *on top* of that sequence — one `ServiceConnection` serving several
tool calls over one held socket, and recovering exactly once when that socket turns out to be dead.
"""

import asyncio
import os
import shutil
import signal
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path

import aiosqlite
import pytest

from zikaron.mcp.connection import ServiceConnection

pytestmark = pytest.mark.integration

#: Generous relative to spike 3's measured ~101 ms cold start, to absorb slower CI environments —
#: the same figure `test_service_lifecycle_integration.py` uses for the identical reason.
_SPAWN_DEADLINE_SECONDS = 15.0


async def _health_pid(connection: ServiceConnection) -> int:
    """This connection's own live server's pid, via a real `health()` call — the one RPC method
    that needs no store mutation and so is safe to use purely as a liveness/identity probe."""
    envelope = connection.envelope(kind="mcp")
    response = await connection.request("health", {}, envelope=envelope)
    result = response["result"]
    assert isinstance(result, dict)
    return int(result["pid"])


def _wait_until_pid_gone(pid: int, *, deadline_seconds: float) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    raise TimeoutError(f"pid {pid} was still alive after {deadline_seconds}s")


@pytest.fixture
async def connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ServiceConnection]:
    """A `ServiceConnection` over a fresh, empty store directory — `memory.db` does not exist yet,
    so the very first request through it exercises the create-on-absent path end to end (the
    service creates the store on its own first startup, per `architecture.md` §"First run") on
    top of the ordinary start-if-absent sequence, rather than requiring a separate setup step to
    pre-create the store the way `test_service_lifecycle_integration.py`'s own fixtures do.

    `XDG_RUNTIME_DIR` is pointed at a short, uniquely-named directory under `/tmp` rather than
    nested inside `tmp_path` itself: `tmp_path`'s own path already encodes this module's and this
    test's full name, and `<that path>/runtime/<32-char-hash>.sock` routinely exceeds `AF_UNIX`'s
    ~108-byte `sun_path` limit once a test's own name is descriptive — measured directly against
    this project's own test-naming convention, not a hypothetical. Production faces the identical
    constraint and resolves it the same way (`security.runtime_dir`'s `/tmp/zikaron-<uid>`
    fallback, and `$XDG_RUNTIME_DIR` itself when the desktop session sets it, are both short by
    construction), so a short directory here is the realistic case, not a workaround unique to
    the test.
    """
    runtime_dir = Path(tempfile.gettempdir()) / f"zikaron-test-{uuid.uuid4().hex[:8]}"
    runtime_dir.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    conn = ServiceConnection(tmp_path)
    try:
        yield conn
    finally:
        pid: int | None = None
        with suppress(OSError, ConnectionError, KeyError, TypeError):
            pid = await _health_pid(conn)
        conn.close()
        if pid is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            with suppress(TimeoutError):
                _wait_until_pid_gone(pid, deadline_seconds=5.0)
        shutil.rmtree(runtime_dir, ignore_errors=True)


async def test_the_first_request_spawns_the_service_and_creates_the_store(
    connection: ServiceConnection,
) -> None:
    pid = await _health_pid(connection)
    assert pid > 0


async def test_a_second_request_reuses_the_held_connection_without_respawning(
    connection: ServiceConnection,
) -> None:
    first_pid = await _health_pid(connection)
    second_pid = await _health_pid(connection)
    assert first_pid == second_pid


async def test_recovery_from_a_dead_service_respawns_and_the_next_call_succeeds(
    connection: ServiceConnection,
) -> None:
    """M10's own done-when, and the operator's own instruction: the service may die (crash, or
    idle self-stop) between two tool calls, and `ServiceConnection` must recover rather than fail
    the next call outright — `architecture.md`'s own client rule, "retry once through the full
    start-if-absent sequence before falling back," exercised here against a service actually
    killed out from under a held connection rather than only reasoned about.
    """
    first_pid = await _health_pid(connection)

    os.kill(first_pid, signal.SIGKILL)
    _wait_until_pid_gone(first_pid, deadline_seconds=5.0)

    # The next call must recover: `request()`'s own retry-once loop finds the held socket dead
    # (the killed server can no longer answer it), closes it, and runs `connect_start_if_absent`
    # again — which spawns a fresh server, since `-32020`/`ECONNREFUSED`/`ENOENT` is exactly the
    # "service died without cleaning up" signature that sequence exists to recover from.
    second_pid = await _health_pid(connection)
    assert second_pid > 0
    assert second_pid != first_pid, "recovery must reach a genuinely new server process"


async def test_recovery_preserves_the_store_across_the_respawn(
    connection: ServiceConnection,
) -> None:
    """Recovery must reconnect to the *same* store — killing the service and letting a fresh one
    spawn must not silently create a second, different store at the same path, which would be
    exactly the identity confusion `architecture.md`'s "store identity is verified, not assumed"
    section exists to prevent.
    """
    first_pid = await _health_pid(connection)
    first_response = await connection.request(
        "remember",
        {"gist": "recovery test row", "content": "written before the kill"},
        envelope=connection.envelope(kind="mcp"),
    )
    written = first_response["result"]
    assert isinstance(written, dict)
    written_uuid = written["uuid"]
    assert isinstance(written_uuid, str)

    os.kill(first_pid, signal.SIGKILL)
    _wait_until_pid_gone(first_pid, deadline_seconds=5.0)

    fetch_response = await connection.request(
        "fetch", {"uuids": [written_uuid]}, envelope=connection.envelope(kind="mcp")
    )
    result = fetch_response["result"]
    assert isinstance(result, dict)
    assert result["missing"] == []
    records = result["records"]
    assert isinstance(records, list)
    (record,) = records
    assert isinstance(record, dict)
    assert record["uuid"] == written_uuid


async def test_a_request_waiting_out_real_store_contention_still_succeeds(
    connection: ServiceConnection,
) -> None:
    """`connect_start_if_absent` hands back a socket whose timeout is set for the *connect*
    phase alone (`lifecycle._CONNECT_TIMEOUT_SECONDS`, 1 s) — `ServiceConnection` must reset it
    before using the same socket for ordinary requests, since a genuinely contended write may
    legitimately take up to `PRAGMA busy_timeout = 5000`'s full 5 s to resolve
    (`zikaron/core/store/ddl.py`), and a 1 s request timeout would cut that wait off first. This
    holds the store's own write lock for real, for longer than 1 s but less than 5 s, via a raw
    `aiosqlite` connection racing an ordinary MCP `remember` call — proving the call's real
    success response is received rather than the transport socket timing out and reporting
    `AmbiguousMutationError`.
    """
    # The very first request establishes the socket and creates the store — needed before a raw
    # connection to the same `memory.db` file can hold a lock on it.
    await _health_pid(connection)
    store_dir = connection._location.store_dir
    db_path = store_dir / "memory.db"

    lock_acquired = asyncio.Event()

    async def _hold_the_write_lock_for(seconds: float) -> None:
        async with aiosqlite.connect(db_path) as holder:
            await holder.execute("BEGIN IMMEDIATE")
            await holder.execute(
                "INSERT INTO meta (key, value) VALUES ('probe', 'holding the write lock')"
            )
            lock_acquired.set()
            await asyncio.sleep(seconds)
            await holder.rollback()

    hold_seconds = 2.0
    holder_task = asyncio.create_task(_hold_the_write_lock_for(hold_seconds))
    # Wait for `BEGIN IMMEDIATE` to have genuinely committed the lock acquisition, rather than a
    # fixed sleep guessing how long that takes — the property under test is "does the MCP request
    # survive waiting out contention already in progress," and a request that raced the holder to
    # acquire the lock first would not be testing that at all.
    await asyncio.wait_for(lock_acquired.wait(), timeout=5.0)

    started = time.monotonic()
    response = await connection.request(
        "remember",
        {"gist": "written while another connection held the lock", "content": "content"},
        envelope=connection.envelope(kind="mcp"),
    )
    elapsed = time.monotonic() - started

    await holder_task

    assert "result" in response, f"expected a success, got {response!r}"
    assert elapsed > 1.0, (
        "the request must have genuinely waited past the old 1 s connect-phase timeout, or this "
        "test cannot tell the fix apart from a lock the request happened not to contend on"
    )
    assert elapsed < hold_seconds + 2.0, (
        f"the request took {elapsed:.1f}s — suspiciously long for a lock held only "
        f"{hold_seconds}s, suggesting it waited out the service's own busy_timeout instead of "
        "the holder releasing when expected"
    )
