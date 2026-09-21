"""`open_connection`'s own job: establish a connection, or leave nothing behind.

The properties that matter to every caller are here rather than in either database's own suite,
because both databases depend on them and neither owns them: a failure after `aiosqlite.connect`
has already succeeded must close what it opened, a failed *connect* is named by the caller rather
than by this module, and a failed connect must not leave its worker thread running past the event
loop it was made on. The last of those reaches into a private attribute of the driver, so the
attribute itself is pinned here too.
"""

import asyncio
import threading
from pathlib import Path

import aiosqlite
import pytest

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.store.connection import open_connection
from zikaron.core.store.ddl import PRAGMAS


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_failed_connect_leaves_no_thread_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connect that fails must not leave its worker thread running past the loop it was made on.

    Written as a measurement rather than as an assertion about the code, because nothing else in
    the gate can tell the two states apart: both branches of the wait run either way, so coverage
    cannot move, and the version matrix errors only on deprecations.

    Two independent signals, from one loop.

    * **The thread's own death.** Abandoned, it calls `call_soon_threadsafe` on a closed loop,
      raises `RuntimeError: Event loop is closed`, fails the same way reporting that, and dies
      unhandled — which pytest raises as `PytestUnhandledThreadExceptionWarning`, made a failure
      by the marker above. **Reliable in this position**: with the wait removed from
      `open_connection`, this test was red on 5 runs of 5, and green on 5 of 5 with it.
    * **The thread still running when the call returns.** The wait joins it, so a pass here is
      deterministic; a failure is not guaranteed without the wait, which is what the twenty
      iterations are for. Measured by a separate probe at 50 iterations — not by this test, which
      runs 20 — with the wait bypassed: 3, 5 and 11 threads still alive across three trials,
      against 0 of 50 on every trial with it.

    Neither signal fires on every iteration, which is why both are here and why the count is twenty
    rather than one. Synchronous on purpose: each iteration needs its own event loop, closed while
    the abandoned thread would still be draining, and `asyncio.run` is what gives it.
    """
    connectors: list[aiosqlite.Connection] = []
    real_connect = aiosqlite.connect

    def _recording(database: str | Path, *, uri: bool = False) -> aiosqlite.Connection:
        connector = real_connect(database, uri=uri)
        connectors.append(connector)
        return connector

    monkeypatch.setattr(aiosqlite, "connect", _recording)

    for _ in range(20):
        with pytest.raises(aiosqlite.Error):
            asyncio.run(
                open_connection(tmp_path / "absent.db", pragmas=PRAGMAS, existing_only=True)
            )

    assert len(connectors) == 20
    assert [connector for connector in connectors if connector._thread.is_alive()] == []


def test_aiosqlite_still_keeps_its_worker_on_the_attribute_we_wait_on() -> None:
    """Pin the private attribute `join_abandoned_worker` reaches for, so a bump cannot mute it.

    That function tolerates the attribute's absence, which is right for a test that
    substitutes the connect and wrong for a real library that moved it — there the wait would
    become a silent no-op and the thread would start outliving its loop again with nothing to say
    so. This is the test that says so, and it belongs in the matrix because a dependency bump is
    exactly the change that would trip it.

    The connection is never awaited, so no thread is started and nothing is opened: `__await__` is
    what starts the worker, and `__del__` returns early while `_connection` is `None`.
    """
    connector = aiosqlite.connect(":memory:")
    assert isinstance(connector._thread, threading.Thread)
    assert not connector._thread.is_alive()


async def test_open_connection_closes_on_a_pragma_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`open_connection` connects, then loads the extension, then applies every pragma — any
    of which can fail after `aiosqlite.connect` has already succeeded. A failure applying a
    pragma must close the connection before propagating, or the caller — which only wraps its
    *own* work afterwards — would be handed nothing to close."""
    db_path = tmp_path / "memory.db"

    real_execute = aiosqlite.Connection.execute

    async def _fail_on_pragma(
        self: aiosqlite.Connection, sql: str, parameters: object = None
    ) -> object:
        if sql.strip().upper().startswith("PRAGMA"):
            raise RuntimeError("simulated pragma failure")
        return await real_execute(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "execute", _fail_on_pragma)

    with pytest.raises(RuntimeError, match="simulated pragma failure"):
        _ = await open_connection(db_path, pragmas=PRAGMAS)

    monkeypatch.undo()
    # A fresh connection afterwards must succeed — proof the failed attempt left no dangling
    # connection or lock on the file.
    async with aiosqlite.connect(db_path) as fresh:
        await fresh.execute("SELECT 1")


async def test_existing_only_refuses_to_create_an_absent_database(tmp_path: Path) -> None:
    db_path = tmp_path / "absent.db"

    with pytest.raises(aiosqlite.Error):
        _ = await open_connection(db_path, pragmas=PRAGMAS, existing_only=True)

    assert not db_path.exists()


async def test_a_connect_failure_is_named_by_the_caller_when_one_says_how(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "absent.db"

    def _named(_error: aiosqlite.Error) -> ZikaronError:
        return ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            key="store_dir",
            value=str(db_path),
            expected="an existing database",
        )

    with pytest.raises(ZikaronError) as caught:
        _ = await open_connection(
            db_path, pragmas=PRAGMAS, existing_only=True, connect_failure=_named
        )

    assert caught.value.code is ErrorCode.BAD_CONFIG
    assert isinstance(caught.value.__cause__, aiosqlite.Error)


async def test_connect_failure_does_not_rename_a_pragma_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mapper is scoped to the connect, and that scope is behaviour rather than an
    implementation detail: a caller whose mapper says *this store has not been created* would be
    saying something false about a database that connected and then refused a pragma. Verified by
    letting the connect succeed and failing the step after it."""
    db_path = tmp_path / "memory.db"
    real_execute = aiosqlite.Connection.execute

    async def _fail_on_pragma(
        self: aiosqlite.Connection, sql: str, parameters: object = None
    ) -> object:
        if sql.strip().upper().startswith("PRAGMA"):
            raise RuntimeError("simulated pragma failure")
        return await real_execute(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "execute", _fail_on_pragma)

    def _unreachable(_error: aiosqlite.Error) -> ZikaronError:
        raise AssertionError("the connect succeeded; this mapper must not be consulted")

    with pytest.raises(RuntimeError, match="simulated pragma failure"):
        _ = await open_connection(db_path, pragmas=PRAGMAS, connect_failure=_unreachable)


async def test_the_pragmas_the_caller_asked_for_are_the_ones_applied(tmp_path: Path) -> None:
    """Asserted as observable connection state rather than as a list of statements that were
    issued, because what a caller depends on is the state — and a test that only compared a tuple
    against a document would pass while the tuple was applied to nothing."""
    db, _inode = await open_connection(tmp_path / "memory.db", pragmas=PRAGMAS)
    try:
        ((journal_mode,),) = list(await db.execute_fetchall("PRAGMA journal_mode"))
        ((busy_timeout,),) = list(await db.execute_fetchall("PRAGMA busy_timeout"))
        ((vec_version,),) = list(await db.execute_fetchall("SELECT vec_version()"))
    finally:
        await db.close()

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 5000
    assert isinstance(vec_version, str)


async def test_a_pragma_the_caller_did_not_ask_for_is_not_applied(tmp_path: Path) -> None:
    """The parameter exists because two schemas want different sets, so the test that matters is
    that an omitted pragma stays omitted — not that a named one arrives. `foreign_keys` is the
    one this distinction was introduced for: it defaults off, and a connection opened without it
    must still have it off however the opener happens to be written."""
    db, _inode = await open_connection(
        tmp_path / "memory.db", pragmas=("PRAGMA busy_timeout = 1234",)
    )
    try:
        ((foreign_keys,),) = list(await db.execute_fetchall("PRAGMA foreign_keys"))
        ((busy_timeout,),) = list(await db.execute_fetchall("PRAGMA busy_timeout"))
    finally:
        await db.close()

    assert int(foreign_keys) == 0
    assert int(busy_timeout) == 1234
