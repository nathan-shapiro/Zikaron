"""`open_connection`'s own job: establish a connection, or leave nothing behind.

The two properties that matter to every caller are here rather than in either database's own
suite, because both databases depend on them and neither owns them: a failure after
`aiosqlite.connect` has already succeeded must close what it opened, and a failed *connect* is
named by the caller rather than by this module.
"""

from pathlib import Path

import aiosqlite
import pytest

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.store.connection import open_connection
from zikaron.core.store.ddl import PRAGMAS


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
