"""Another process's hold on a store, and a wait budget small enough to measure against.

Shared by the tests of `architecture.md` §Lifecycle's transaction rules. The other writer is a raw
`sqlite3` connection, because what those rules defend against is a writer outside this process —
the indexer, a second service, an operator's shell — which no in-process lock can see.
"""

import asyncio
import contextlib
import json
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from zikaron.core.store import ddl
from zikaron.service import server
from zikaron.service.context import ServiceContext


def patch_budget(monkeypatch: pytest.MonkeyPatch, milliseconds: int) -> None:
    """Make every wait budget `milliseconds`. A serving connection runs at `busy_timeout = 0`
    whatever it opened with, so the constant is the whole of it."""
    monkeypatch.setattr(ddl, "BUSY_TIMEOUT_MS", milliseconds)


class ExternalWriter:
    """Raw connections onto a store, standing in for a writer in another process.

    The held lock is one connection, used only on the thread that made it — `sqlite3` refuses any
    other. Each `commit_a_write` opens a connection of its own, because it runs on a worker thread
    and a verb with two transactions starts a second while the first still waits for the lock: two
    in flight at once, measured. Sharing one connection between them failed CI's macOS job with
    SQLite's *API misuse* and crashed its 3.14 job in a native thread.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._connection = _connect(db_path)
        self._holding = False

    def hold(self) -> None:
        """Take the write lock and keep it until `release`."""
        self._connection.execute("BEGIN IMMEDIATE")
        self._holding = True

    def release(self) -> None:
        if self._holding:
            self._connection.execute("ROLLBACK")
            self._holding = False

    def release_after(self, seconds: float) -> None:
        """Release the lock `seconds` from now, from the running loop."""
        asyncio.get_running_loop().call_later(seconds, self.release)

    def commit_a_write(self) -> int:
        """Commit one row to a table of its own, waiting for the lock if another connection holds
        it, and return the instant it committed at, in `time.monotonic_ns()`."""
        with contextlib.closing(_connect(self._db_path)) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS external_probe (at INTEGER)")
            connection.execute("INSERT INTO external_probe (at) VALUES (?)", (0,))
            return time.monotonic_ns()

    def close(self) -> None:
        self.release()
        self._connection.close()


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


@contextlib.contextmanager
def external_writer(db_path: Path) -> Iterator[ExternalWriter]:
    writer = ExternalWriter(db_path)
    try:
        yield writer
    finally:
        writer.close()


def line(method: str, params: dict[str, object], request_id: int = 1) -> bytes:
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    return (json.dumps(request) + "\n").encode("utf-8")


def client(session_id: str = "s1", *, kind: str = "mcp", pid: int = 100) -> dict[str, object]:
    return {"session_id": session_id, "kind": kind, "pid": pid}


async def call(
    ctx: ServiceContext, method: str, params: dict[str, object], *, kind: str = "mcp"
) -> dict[str, object]:
    """One request through the dispatcher, as its parsed response."""
    response = await server._handle_line(ctx, line(method, {**params, "client": client(kind=kind)}))
    assert response is not None
    parsed = json.loads(response)
    assert isinstance(parsed, dict)
    return parsed


def error_of(response: dict[str, object]) -> tuple[int, dict[str, object]] | None:
    """The response's error code and data, or `None` for a result."""
    error = response.get("error")
    if error is None:
        return None
    assert isinstance(error, dict)
    data = error.get("data", {})
    assert isinstance(data, dict)
    return int(error["code"]), data
