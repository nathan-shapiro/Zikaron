"""`Store.create`/`Store.open`, checked against `schema.md` §"Creating the dense index", §`meta`,
and invariants 1, 3 and 11 — the three `build-plan.md`'s M2 brief names for this milestone.
"""

import struct
from contextlib import suppress
from pathlib import Path

import aiosqlite
import pytest

import zikaron.core.store.store as store_module
from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.errors import ERROR_SPECS, BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.store import meta
from zikaron.core.store.embedder import Embedder, FakeEmbedder
from zikaron.core.store.meta import StoreMeta
from zikaron.core.store.store import (
    SUPPORTED_SCHEMA_VERSION,
    Store,
    _open_connection,
    _physical_vec0_width,
)

_DB_FILENAME = "memory.db"


def _config(tmp_path: Path) -> EffectiveConfig:
    """The effective config with both files absent — every key at its built-in default."""
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


def _default_embedder() -> FakeEmbedder:
    return FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)


# ---------------------------------------------------------------------------
# Carried from M1: this build's schema version must agree with errors.py's own
# declaration, never restate it.
# ---------------------------------------------------------------------------


def test_supported_schema_version_agrees_with_errors_pys_fixed_declaration() -> None:
    spec = ERROR_SPECS[ErrorCode.SCHEMA_INCOMPATIBLE]
    (supported_field,) = [f for f in spec.data_fields if f.name == "supported"]
    assert supported_field.values == (SUPPORTED_SCHEMA_VERSION,)


async def _create_then_close(
    store_dir: Path, config: EffectiveConfig, embedder: Embedder | None = None
) -> StoreMeta:
    """Create a store, read its `meta`, and close it — returning what the caller may still assert
    on.

    Many tests here need a **closed** store as their setup: something they do next reopens it,
    chmods it, symlinks it, or reconfigures the layer it was created from. The close is therefore
    part of the arrangement rather than cleanup, and it belongs in one helper that holds the store
    with `async with` like every other test in the suite, instead of a bare create-then-close pair
    per test.
    """
    async with await Store.create(
        store_dir, config, embedder if embedder is not None else _default_embedder()
    ) as store:
        return store.meta


async def _open_then_close(store_dir: Path, config: EffectiveConfig) -> StoreMeta:
    """Open a store, read its `meta`, and close it.

    The companion to `_create_then_close`, for a test whose assertion *is* that the open succeeds:
    the returned `meta` is what a caller compares, and a raise is the failure.
    """
    async with await Store.open(store_dir, config) as store:
        return store.meta


# ---------------------------------------------------------------------------
# Create -> close -> open round trip
# ---------------------------------------------------------------------------


async def test_create_close_open_round_trips(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    embedder = _default_embedder()

    async with await Store.create(store_dir, config, embedder) as created:
        assert created.meta.schema_version == SUPPORTED_SCHEMA_VERSION
        assert created.meta.embed_model == "BAAI/bge-small-en-v1.5"
        assert created.meta.embed_dim == 384
        assert created.meta.chunk_max_tokens == 450
        assert len(created.meta.store_id) == 36

    async with await Store.open(store_dir, config) as reopened:
        assert reopened.meta == created.meta


async def test_reopening_twice_yields_the_same_meta_both_times(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _create_then_close(store_dir, config)
    first = await _open_then_close(store_dir, config)
    second = await _open_then_close(store_dir, config)
    assert first == second


async def test_context_manager_closes_on_exit(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as store:
        await store.connection.execute("SELECT 1")
    # A second query on the now-closed connection must fail — proof __aexit__ actually closed
    # it. `aiosqlite` raises a bare `ValueError` for this case rather than a more specific type,
    # so that is the exception this test names.
    with pytest.raises(ValueError, match="no active connection"):
        await store.connection.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Dimension mismatch is rejected before any table exists
# ---------------------------------------------------------------------------


async def test_dimension_mismatch_is_rejected_before_the_store_directory_exists(
    tmp_path: Path,
) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)  # embed_dim defaults to 384
    mismatched = FakeEmbedder(model_name="some-other-model", dim=768)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.create(store_dir, config, mismatched)

    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["source"] == BadConfigSource.FILE
    assert not store_dir.exists()


async def test_dimension_mismatch_is_rejected_even_if_the_store_dir_already_exists(
    tmp_path: Path,
) -> None:
    """A pre-existing empty directory (e.g. left by an earlier failed attempt) must not let the
    check be skipped, and no `memory.db` may appear inside it either."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    config = _config(tmp_path)
    mismatched = FakeEmbedder(model_name="some-other-model", dim=768)

    with pytest.raises(ZikaronError):
        await Store.create(store_dir, config, mismatched)

    assert not (store_dir / _DB_FILENAME).exists()


async def test_a_matching_embedder_creates_successfully(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _create_then_close(
        store_dir, config, FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)
    )
    assert (store_dir / _DB_FILENAME).exists()


async def test_open_on_a_missing_store_creates_no_database_file(tmp_path: Path) -> None:
    """`open` documents opening an *existing* store; a missing one must be reported, not
    silently created — `aiosqlite.connect`'s ordinary default behaviour creates an empty
    `memory.db` on first touch, which is exactly the mutation this operation must not perform.
    The directory itself may legitimately exist (an operator ran `mkdir .zikaron` by hand, or a
    prior `Store.create` failed before `memory.db` was ever opened) without the database file
    existing inside it."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    config = _config(tmp_path)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert not (store_dir / _DB_FILENAME).exists()


async def test_open_raises_filenotfound_when_the_path_becomes_unstatable_right_after_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`memory.db` deleted, with nothing recreated at all, strictly *after* the real connect call
    has already returned but *before* `_open_connection`'s own `opened_inode = db_path.stat()`
    read runs. That read itself is what fails here — a plain `FileNotFoundError`, since there is
    genuinely nothing left to `stat` at the path — rather than reaching the pragma-application
    loop that follows it at all. This is the accepted, documented gap `_open_connection`'s own
    docstring names explicitly: a replacement landing in this exact narrow window is detected as
    a failure (the store cannot be opened), but not classified as a `store_identity` mismatch,
    since this build deliberately does not implement the VFS-level mechanism that would be
    required to distinguish the two here. This test exists to confirm that failure surfaces as a
    plain `FileNotFoundError` propagating unmodified, not silently swallowed or misclassified —
    **and, separately, that the already-established connection is genuinely closed rather than
    abandoned**: `aiosqlite.connect()` succeeding before this failure means a real, worker-
    thread-backed connection already exists at the moment the `stat()` raises, and a version of
    this function that read the inode *outside* the cleanup boundary left exactly that
    connection unclosed on this path — a genuine resource leak this project's own history has
    already paid for once (a leaked, worker-thread-backed handle keeps the whole interpreter
    alive after all other work is done, per `coding-standards.md` §6).
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()):
        pass
    db_path = store_dir / _DB_FILENAME

    real_connect_method = aiosqlite.Connection._connect
    established_connection: aiosqlite.Connection | None = None

    async def _connect_then_delete_with_nothing_recreated(
        self: aiosqlite.Connection,
    ) -> aiosqlite.Connection:
        nonlocal established_connection
        result = await real_connect_method(self)
        established_connection = result
        db_path.unlink()
        return result

    monkeypatch.setattr(
        aiosqlite.Connection, "_connect", _connect_then_delete_with_nothing_recreated
    )

    with pytest.raises(FileNotFoundError):
        await Store.open(store_dir, config)

    assert established_connection is not None, (
        "the connect must have genuinely succeeded before the stat() failure for this test to "
        "mean anything"
    )
    # A query against the closed connection must fail with `aiosqlite`'s own "no active
    # connection" `ValueError` — the identical proof-of-closure pattern
    # `test_context_manager_closes_on_exit` already establishes for the ordinary close path,
    # applied here to confirm the *failure* path closes it too.
    with pytest.raises(ValueError, match="no active connection"):
        await established_connection.execute("SELECT 1")


async def test_open_on_a_file_that_exists_but_aiosqlite_connect_itself_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file genuinely exists and is readable, but `aiosqlite.connect()` itself still raises,
    which must still be reported as `BAD_CONFIG` exactly like the missing-file case above.
    `aiosqlite.connect()` is monkeypatched directly to raise a real `aiosqlite.Error` subclass,
    rather than trying to construct a genuine filesystem condition that triggers a *connect-time*
    rejection specifically: SQLite's own file-format validation is lazy — a plainly non-SQLite
    file connects successfully and only fails on the first actual query, which a different,
    pre-existing exception path already handles — so a real connect-time `aiosqlite.Error` is
    narrow enough (permission edge cases, resource exhaustion) that a direct, deterministic
    construction of the classification logic itself is the more faithful test of what this
    branch is actually for.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    db_path = store_dir / _DB_FILENAME
    db_path.write_bytes(b"exists and is readable, but aiosqlite.connect will still reject it")
    config = _config(tmp_path)

    async def _connect_always_rejects(*_args: object, **_kwargs: object) -> aiosqlite.Connection:
        raise aiosqlite.OperationalError("deliberately rejected, for this test")

    monkeypatch.setattr(aiosqlite, "connect", _connect_always_rejects)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG

    monkeypatch.undo()
    async with aiosqlite.connect(db_path) as fresh:
        with pytest.raises(aiosqlite.Error):
            # `SELECT 1` alone would succeed even against this garbage file — it is a pure
            # literal, never touching the database's own on-disk format — so this uses the exact
            # pragma `_open_connection`'s own pragma-application loop applies first
            # (`ddl.PRAGMAS`), which genuinely does need to read/rewrite the file header and is
            # what surfaces "file is not a database" against a plainly non-SQLite file.
            await fresh.execute("PRAGMA journal_mode = WAL")


async def test_open_on_a_store_directory_that_does_not_exist_at_all_creates_nothing(
    tmp_path: Path,
) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)

    with pytest.raises(ZikaronError):
        await Store.open(store_dir, config)
    assert not store_dir.exists()


async def test_open_on_an_existing_db_with_no_meta_table_raises_bad_config_not_a_raw_error(
    tmp_path: Path,
) -> None:
    """`existing_only=True` stops `open` from *creating* a missing store, but says nothing
    about a `memory.db` that exists yet is internally broken — `meta` dropped by hand, or a
    process that died between creating the file and running its DDL. That case must still
    fail at the Zikaron boundary, not as a raw `sqlite3.OperationalError`."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute("DROP TABLE meta")
        await created.connection.commit()

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["source"] == BadConfigSource.META


async def test_a_same_width_wrong_model_embedder_is_rejected_before_the_store_dir_exists(
    tmp_path: Path,
) -> None:
    """The dimension check alone is not enough: `architecture.md`'s hard `embed_model` coupling
    means every vector in the store must have actually come from the model `meta` names, not
    merely one that happens to emit the same width. An embedder of the right width but the wrong
    name must be rejected exactly like a dimension mismatch — before any table exists."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)  # embed_model defaults to BAAI/bge-small-en-v1.5
    right_width_wrong_model = FakeEmbedder(model_name="some/other-model", dim=384)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.create(store_dir, config, right_width_wrong_model)

    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "embedding.embed_model"
    assert not store_dir.exists()


async def test_create_closes_the_connection_if_the_transaction_never_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure partway through the `CREATE` sequence must leave nothing behind: neither an
    open connection with no caller left holding it, nor a partially-created schema.

    Injected after several real statements have actually run — not by replacing the whole
    method before `BEGIN` executes, which would only prove the caller's own cleanup path closes
    a connection it never used for anything. The count is chosen to fall strictly between
    `ddl.FIXED_STATEMENTS`' first and last statement, so at least one real `CREATE` commits to
    the connection's pending transaction before the injected failure fires."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)

    real_execute = aiosqlite.Connection.execute
    calls_before_failure = 5
    call_count = 0

    async def _execute_then_fail_partway(
        self: aiosqlite.Connection, sql: str, parameters: object = None
    ) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == calls_before_failure:
            raise RuntimeError("simulated failure partway through the CREATE sequence")
        return await real_execute(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "execute", _execute_then_fail_partway)
    with pytest.raises(RuntimeError, match="simulated failure partway"):
        await Store.create(store_dir, config, _default_embedder())
    assert call_count == calls_before_failure  # confirms the injected failure actually fired

    monkeypatch.undo()
    # Reconnect independently — not through Store, which would re-run the same CREATE sequence
    # and mask a partially-committed schema by simply adding to it — and confirm no table from
    # the failed attempt survived. An uncommitted `BEGIN` rolls back with the connection close
    # that `create`'s own exception handler performs.
    async with aiosqlite.connect(store_dir / _DB_FILENAME) as fresh:
        tables = await fresh.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
        assert list(tables) == []

    # A fresh create must succeed afterwards — proof the failed attempt left no dangling lock.
    await _create_then_close(store_dir, config)


# ---------------------------------------------------------------------------
# Invariant 1: memory_vec.rowid == memory_chunk.chunk_id
#
# `schema.md` states this invariant as a bare comment beside the DDL (`-- INVARIANT:
# memory_vec.rowid == memory_chunk.chunk_id`), with no trigger, foreign key or CHECK enforcing
# it structurally — it is a write-discipline rule for whichever code writes a chunk and its
# vector together, which is M4's indexing path, not this milestone's. `Store` itself never
# inserts into `memory_chunk` or `memory_vec`, so there is no production code here for a test to
# invert: a "negative control" that hand-picks two different literal ids and shows SQL's own
# join semantics tell them apart would demonstrate the SQL engine works, not that any Zikaron
# code upholds the invariant, and dressing that up as an invariant test would be the "plausible
# answer instead of raising" failure shape the design corpus's own postmortems warn against.
#
# What M2 *can* state and verify honestly: the schema it creates gives the invariant somewhere
# to hold. Both tables exist with an explicit-rowid-compatible shape (`memory_chunk.chunk_id` is
# an `INTEGER PRIMARY KEY`, and `vec0` accepts an explicit `rowid` on insert, per M0 spike 1) —
# so a later writer *can* satisfy the invariant by construction, and nothing in the schema this
# milestone lays down makes it impossible to. Per `coding-standards.md`'s own instruction for a
# genuinely untestable invariant: say so, rather than skip it silently or fake a test that would
# pass unconditionally.
# ---------------------------------------------------------------------------


async def test_invariant_1_has_no_enforcement_code_at_this_milestone_and_that_is_stated_here(
    tmp_path: Path,
) -> None:
    """Documents the honest scope rather than silently omitting the invariant. `Store` writes
    no row into `memory_chunk` or `memory_vec` anywhere in this module — confirmed by asserting
    both are empty immediately after creation — so there is no write path here whose inversion
    an invariant test could exercise. M4 owns that write path and owns this invariant's test."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as store:
        (chunk_count,) = next(
            iter(await store.connection.execute_fetchall("SELECT count(*) FROM memory_chunk"))
        )
        (vec_count,) = next(
            iter(await store.connection.execute_fetchall("SELECT count(*) FROM memory_vec"))
        )
        assert chunk_count == 0
        assert vec_count == 0


async def test_invariant_1_the_schema_created_here_permits_the_invariant_to_be_upheld(
    tmp_path: Path,
) -> None:
    """`memory_chunk.chunk_id` must be a rowid-aliasing `INTEGER PRIMARY KEY` and `memory_vec`
    must accept an explicit rowid on insert (M0 spike 1's proven pattern), or M4's write path
    could not satisfy the invariant even if it tried. This is a schema-shape check, not an
    invariant-violation test: it shows the precondition holds, not that any code enforces the
    conclusion, which is exactly the distinction the section comment above states."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as store:
        (chunk_id_column,) = list(
            await store.connection.execute_fetchall(
                "SELECT name, pk FROM pragma_table_info('memory_chunk') WHERE name = 'chunk_id'"
            )
        )
        assert chunk_id_column == ("chunk_id", 1)  # pk=1 -> INTEGER PRIMARY KEY, rowid alias

        vector = struct.pack("384f", *([0.1] * 384))
        await store.connection.execute(
            "INSERT INTO memory_vec (rowid, embedding) VALUES (42, ?)", (vector,)
        )
        (inserted_rowid,) = next(
            iter(await store.connection.execute_fetchall("SELECT rowid FROM memory_vec"))
        )
        assert inserted_rowid == 42  # the explicit rowid was honoured, not reassigned


# ---------------------------------------------------------------------------
# Invariant 3: the reindexing sentinel blocks open, including the present-on-open case
# ---------------------------------------------------------------------------


async def test_invariant_3_absence_of_the_sentinel_opens_normally(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _create_then_close(store_dir, config)
    await _open_then_close(store_dir, config)  # must not raise


async def test_invariant_3_a_present_sentinel_blocks_open_with_reindexing(
    tmp_path: Path,
) -> None:
    """Simulates a process that died mid-reindex, leaving the sentinel behind — the exact case
    the invariant exists to catch, since the store's dense index cannot be trusted mid-swap."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        since = "2026-08-01T12:00:00Z"
        await created.connection.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)", (meta.REINDEXING_KEY, since)
        )
        await created.connection.commit()

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    assert excinfo.value.code is ErrorCode.REINDEXING
    assert excinfo.value.data["since"] == since


async def test_invariant_3_the_reindexing_check_precedes_meta_validation(tmp_path: Path) -> None:
    """The sentinel must be checked even when `meta` is otherwise corrupt, since a process that
    died mid-reindex may have left `meta` in an inconsistent state too — REINDEXING must win over
    BAD_CONFIG, not the other way round."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)", (meta.REINDEXING_KEY, "since-x")
        )
        await created.connection.execute("DELETE FROM meta WHERE key = 'embed_dim'")
        await created.connection.commit()

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    assert excinfo.value.code is ErrorCode.REINDEXING


# ---------------------------------------------------------------------------
# Invariant 11: embed_model/embed_dim checked against meta on open, never a silent continue
# ---------------------------------------------------------------------------


async def test_invariant_11_a_matching_config_opens_normally(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _create_then_close(store_dir, config)
    await _open_then_close(store_dir, config)  # must not raise


async def test_invariant_11_a_disagreeing_embed_model_is_rejected_on_open(
    tmp_path: Path,
) -> None:
    store_dir = tmp_path / ".zikaron"
    creation_config = _config(tmp_path)
    await _create_then_close(store_dir, creation_config)

    different_model = tmp_path / "project-different-model.toml"
    different_model.write_text('[embedding]\nembed_model = "some/other-model"\n', encoding="utf-8")
    disagreeing_config = resolve(tmp_path / "system.toml", different_model)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, disagreeing_config)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["source"] == BadConfigSource.META


async def test_invariant_11_a_disagreeing_embed_dim_is_rejected_on_open(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    creation_config = _config(tmp_path)
    await _create_then_close(store_dir, creation_config)

    different_dim = tmp_path / "project-different-dim.toml"
    different_dim.write_text("[embedding]\nembed_dim = 768\n", encoding="utf-8")
    disagreeing_config = resolve(tmp_path / "system.toml", different_dim)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, disagreeing_config)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["source"] == BadConfigSource.META


async def test_invariant_11_never_silently_continues_on_mismatch(tmp_path: Path) -> None:
    """The design's own wording: a mismatch is a forced-reindex decision point, never a
    best-effort continue. Proven by showing `Store.open` never returns a `Store` in this case —
    the exception is the only outcome, there is no silent-success branch to also check."""
    store_dir = tmp_path / ".zikaron"
    await _create_then_close(store_dir, _config(tmp_path))

    different_dim = tmp_path / "different.toml"
    different_dim.write_text("[embedding]\nembed_dim = 999\n", encoding="utf-8")
    disagreeing = resolve(tmp_path / "system.toml", different_dim)

    result = None
    with suppress(ZikaronError):
        result = await Store.open(store_dir, disagreeing)
    assert result is None


async def test_invariant_11_a_physical_width_disagreeing_with_meta_is_rejected(
    tmp_path: Path,
) -> None:
    """`meta.embed_dim` can drift from the table it is supposed to describe even while it still
    agrees with the effective config — a hand-edited `meta` row, or a corrupted one — and
    `schema.md` requires the comparison to run against *both* the config and the physical
    `vec0` column, not the config alone. Simulated here by dropping and recreating `memory_vec`
    at a different width while leaving `meta.embed_dim` untouched, which is exactly the state a
    `meta` row could reach without the store's own creation path ever producing it."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute("DROP TABLE memory_vec")
        await created.connection.execute(
            "CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[768])"
        )
        await created.connection.commit()

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    error = excinfo.value
    assert error.code is ErrorCode.BAD_CONFIG
    assert error.data["source"] == BadConfigSource.META
    assert error.data["key"] == "embed_dim"


async def test_physical_vec0_width_is_bad_config_if_the_table_is_missing(tmp_path: Path) -> None:
    """`_physical_vec0_width` reads back the table its own caller's schema creation guarantees
    exists; a store somehow missing it entirely — dropped by hand, or corrupted — must be
    reported as a configuration defect rather than raising a bare `sqlite3` lookup error."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute("DROP TABLE memory_vec")
        await created.connection.commit()

        with pytest.raises(ZikaronError) as excinfo:
            await _physical_vec0_width(created.connection)
        assert excinfo.value.code is ErrorCode.BAD_CONFIG
        assert excinfo.value.data["key"] == "memory_vec"


async def test_physical_vec0_width_is_bad_config_if_the_ddl_text_has_no_width(
    tmp_path: Path,
) -> None:
    """The width is read back from `memory_vec`'s own recorded `CREATE VIRTUAL TABLE` text,
    which only ever exists in the `float[<n>]` shape `ddl.memory_vec_statement` writes — but a
    table named `memory_vec` created any other way would leave nothing for the pattern to
    match, and that must be reported rather than crash on an unpacked `None`."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute("DROP TABLE memory_vec")
        await created.connection.execute("CREATE TABLE memory_vec (embedding BLOB)")
        await created.connection.commit()

        with pytest.raises(ZikaronError) as excinfo:
            await _physical_vec0_width(created.connection)
        assert excinfo.value.code is ErrorCode.BAD_CONFIG
        assert excinfo.value.data["key"] == "memory_vec"


async def test_physical_vec0_width_refuses_a_non_vec0_table_that_merely_mentions_the_width(
    tmp_path: Path,
) -> None:
    """A bare `float[<n>]` substring search would accept this table: it is named `memory_vec`,
    it is an ordinary table (not `USING vec0`), and the exact text `float[384]` appears inside
    an unrelated `CHECK` constraint's string literal rather than in a real width declaration.
    The pattern must be anchored to the whole `CREATE VIRTUAL TABLE ... USING vec0 (embedding
    float[<n>])` shape, or a table that is not `vec0` at all could satisfy invariant 11's check
    by coincidence of substring."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute("DROP TABLE memory_vec")
        await created.connection.execute(
            "CREATE TABLE memory_vec (embedding BLOB CHECK (typeof(embedding) <> 'float[384]'))"
        )
        await created.connection.commit()

        with pytest.raises(ZikaronError) as excinfo:
            await _physical_vec0_width(created.connection)
        assert excinfo.value.code is ErrorCode.BAD_CONFIG
        assert excinfo.value.data["key"] == "memory_vec"


async def test_physical_vec0_width_refuses_the_whole_expected_phrase_quoted_as_a_literal(
    tmp_path: Path,
) -> None:
    """An even closer lookalike than the bare-substring case above: this table's `CHECK`
    constraint quotes the *entire* expected DDL phrase — `CREATE VIRTUAL TABLE memory_vec
    USING vec0 (embedding float[384])` verbatim — as one string literal, inside an ordinary
    (non-`vec0`) table. A pattern anchored to the shape but matched via `.search()` would still
    find that shape *somewhere in* the recorded SQL, since the literal contains it byte-for-
    byte; only matching against the *entire* recorded statement (`fullmatch`) correctly refuses
    this, because the table's actual `CREATE TABLE ...` wrapper is not, as a whole, that shape."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute("DROP TABLE memory_vec")
        await created.connection.execute(
            "CREATE TABLE memory_vec (embedding BLOB CHECK (embedding <> "
            "'CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[384])'))"
        )
        await created.connection.commit()

        with pytest.raises(ZikaronError) as excinfo:
            await _physical_vec0_width(created.connection)
        assert excinfo.value.code is ErrorCode.BAD_CONFIG
        assert excinfo.value.data["key"] == "memory_vec"


# ---------------------------------------------------------------------------
# schema_incompatible: a newer schema_version than this build supports
# ---------------------------------------------------------------------------


async def test_a_newer_schema_version_is_refused_as_schema_incompatible(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        await created.connection.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
        await created.connection.commit()

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    error = excinfo.value
    assert error.code is ErrorCode.SCHEMA_INCOMPATIBLE
    assert error.data == {"found": 2, "supported": SUPPORTED_SCHEMA_VERSION}


async def test_the_supported_schema_version_itself_opens_normally(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as created:
        assert created.meta.schema_version == SUPPORTED_SCHEMA_VERSION
    await _open_then_close(store_dir, config)  # must not raise


# ---------------------------------------------------------------------------
# Permissions actually applied
# ---------------------------------------------------------------------------


async def test_created_store_directory_and_db_file_have_correct_permissions(
    tmp_path: Path,
) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _create_then_close(store_dir, config)

    assert (store_dir.stat().st_mode & 0o777) == 0o700
    assert ((store_dir / _DB_FILENAME).stat().st_mode & 0o777) == 0o600


async def test_a_pre_existing_wide_db_file_is_tightened_before_any_fallible_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `memory.db` left behind wide by an earlier failed attempt, or widened by an operator's
    own `chmod`, must be tightened before `create` runs anything that can fail — not only after
    this call succeeds, which would leave the file exactly as wide as it was found if this call
    also fails. Verified here by starting with a `0644` file, injecting a failure inside the
    connection setup itself, and confirming the mode is already `0600` despite the failure."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    db_path = store_dir / _DB_FILENAME
    db_path.touch(mode=0o644)
    db_path.chmod(0o644)
    config = _config(tmp_path)

    async def _always_fail(_db_path: Path) -> tuple[aiosqlite.Connection, int]:
        raise RuntimeError("simulated connection setup failure")

    monkeypatch.setattr(store_module, "_open_connection", _always_fail)
    with pytest.raises(RuntimeError, match="simulated connection setup failure"):
        await Store.create(store_dir, config, _default_embedder())

    assert (db_path.stat().st_mode & 0o777) == 0o600


async def test_open_tightens_a_store_directory_left_wider_than_0700(tmp_path: Path) -> None:
    """A store's permissions are only ever enforced at creation unless `open` re-checks them
    too — so a directory an older build or an operator's `chmod` left at `0755` must be
    corrected on the very next open, not left broad indefinitely."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _create_then_close(store_dir, config)
    store_dir.chmod(0o755)
    (store_dir / _DB_FILENAME).chmod(0o644)

    await _open_then_close(store_dir, config)

    assert (store_dir.stat().st_mode & 0o777) == 0o700
    assert ((store_dir / _DB_FILENAME).stat().st_mode & 0o777) == 0o600


async def test_create_refuses_a_symlinked_store_directory(tmp_path: Path) -> None:
    """`architecture.md` §"Filesystem security": a store reached through a symlinked
    `.zikaron` must be refused rather than followed."""
    real_target = tmp_path / "real-target"
    real_target.mkdir(mode=0o700)
    store_dir = tmp_path / ".zikaron"
    store_dir.symlink_to(real_target)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.create(store_dir, _config(tmp_path), _default_embedder())
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "store_dir"


async def test_open_refuses_a_symlinked_store_directory(tmp_path: Path) -> None:
    real_target = tmp_path / "real-target"
    config = _config(tmp_path)
    await _create_then_close(real_target, config)
    store_dir = tmp_path / ".zikaron"
    store_dir.symlink_to(real_target)

    with pytest.raises(ZikaronError) as excinfo:
        await Store.open(store_dir, config)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "store_dir"


# ---------------------------------------------------------------------------
# Pragmas and extension loading actually active on the real connection
# ---------------------------------------------------------------------------


async def test_wal_and_busy_timeout_pragmas_are_active_on_create(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as store:
        (journal_mode,) = await store.connection.execute_fetchall("PRAGMA journal_mode")
        assert journal_mode[0].lower() == "wal"
        (busy_timeout,) = await store.connection.execute_fetchall("PRAGMA busy_timeout")
        assert busy_timeout[0] == 5000
        (foreign_keys,) = await store.connection.execute_fetchall("PRAGMA foreign_keys")
        assert foreign_keys[0] == 1


async def test_wal_and_busy_timeout_pragmas_are_active_on_open(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    await _create_then_close(store_dir, config)

    async with await Store.open(store_dir, config) as reopened:
        (journal_mode,) = await reopened.connection.execute_fetchall("PRAGMA journal_mode")
        assert journal_mode[0].lower() == "wal"


async def test_sqlite_vec_extension_is_loaded(tmp_path: Path) -> None:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()) as store:
        (version,) = await store.connection.execute_fetchall("SELECT vec_version()")
        assert isinstance(version[0], str)


async def test_open_connection_closes_on_a_pragma_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_open_connection` connects, then loads the extension, then applies every pragma — any
    of which can fail after `aiosqlite.connect` has already succeeded. A failure applying a
    pragma must close the connection before propagating, or the caller — which only wraps its
    *own* work afterwards — would be handed nothing to close."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    db_path = store_dir / _DB_FILENAME

    real_execute = aiosqlite.Connection.execute

    async def _fail_on_pragma(
        self: aiosqlite.Connection, sql: str, parameters: object = None
    ) -> object:
        if sql.strip().upper().startswith("PRAGMA"):
            raise RuntimeError("simulated pragma failure")
        return await real_execute(self, sql, parameters)

    monkeypatch.setattr(aiosqlite.Connection, "execute", _fail_on_pragma)

    with pytest.raises(RuntimeError, match="simulated pragma failure"):
        _ = await _open_connection(db_path)

    monkeypatch.undo()
    # A fresh connection afterwards must succeed — proof the failed attempt left no dangling
    # connection or lock on the file.
    async with aiosqlite.connect(db_path) as fresh:
        await fresh.execute("SELECT 1")


async def test_opened_inode_survives_a_replacement_during_later_open_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact race a round of independent review measured against this milestone's own first
    fix attempt: `Store.open`'s own `_validate_on_open` call runs real, awaited SQL *after*
    `_open_connection` has already returned — a version of the inode-drift baseline that read a
    fresh `stat()` at that later point, rather than the value `_open_connection` itself captured,
    would have silently adopted whichever file existed at the path by the time validation
    finished, not the one this store's own connection actually opened.

    Forced directly: `_validate_on_open` is monkeypatched so that, partway through its own
    execution — genuinely after `_open_connection` has already returned and captured
    `opened_inode` — `memory.db` is deleted and a different file is written at the identical
    path, then the real validation proceeds against the connection that is still bound to the
    *original* file. `Store.opened_inode` must still equal the original file's own inode,
    unaffected by a replacement that happened during this later step — proving the captured
    baseline predates, and is independent of, everything that runs after `_open_connection`
    itself returns.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir(mode=0o700)
    config = _config(tmp_path)
    async with await Store.create(store_dir, config, _default_embedder()):
        pass
    original_inode = (store_dir / _DB_FILENAME).stat().st_ino

    real_validate = Store._validate_on_open

    async def _validate_after_replacing_the_file(
        db: aiosqlite.Connection, cfg: EffectiveConfig
    ) -> meta.StoreMeta:
        db_path = store_dir / _DB_FILENAME
        db_path.unlink()
        db_path.write_text("a different file now lives at the identical path", encoding="utf-8")
        assert db_path.stat().st_ino != original_inode, (
            "the replacement must actually land at a different inode for this test to mean anything"
        )
        return await real_validate(db, cfg)

    monkeypatch.setattr(Store, "_validate_on_open", _validate_after_replacing_the_file)
    async with await Store.open(store_dir, config) as store:
        assert store.opened_inode == original_inode, (
            "opened_inode must be the inode this connection actually opened, unaffected by a "
            "replacement that happened during later validation — not a fresh stat of whatever "
            "currently sits at the path"
        )
