"""The indexed write verbs, against `design/schema.md` invariants 1, 2, 4, 12, 13 and 10.

Default tier: a real store on `tmp_path` — real SQLite, real FTS5, the real `sqlite-vec` extension —
with a deterministic `FakeEncoder`. The store is genuine because invariant 2 is a claim about SQLite
transactions and cannot be checked against a stand-in, and it stays unmarked because `sqlite-vec` is
an in-process pinned extension rather than something that leaves the process
(`coding-standards.md` §4). The encoder is fake because the claims here are about *what is written*,
which makes the expected bytes predictable. `test_indexing_integration.py` runs the same paths
against the real model, which is what the `integration` marker is for.
"""

import json
import math
import sqlite3
import struct
import unittest.mock
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final, cast

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder, vector_for
from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.errors import ErrorCode, IndexStage, RowState, ZikaronError
from zikaron.core.events import EVENT_SPECS, EventKind
from zikaron.core.indexing import lexical as lexical_module
from zikaron.core.indexing import vectors as vectors_module
from zikaron.core.indexing import writes
from zikaron.core.indexing.vectors import IndexIdentity
from zikaron.core.indexing.writes import IndexedCall, IndexingContext
from zikaron.core.records import memory as records
from zikaron.core.records.memory import CallParams, Rewrite
from zikaron.core.store.store import Store

_MAX_DEPTH: Final = 32
_GIST: Final = "protobuf codegen fails silently on staging"
_CONTENT: Final = "the proto compiler version drifts from the one pinned in requirements.txt"


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


def _ctx(session_id: str = "s1", client_kind: str = "mcp", op_id: str = "op1") -> CallParams:
    return CallParams(
        session_id=session_id, client_kind=client_kind, op_id=op_id, max_depth=_MAX_DEPTH
    )


async def _open_store(tmp_path: Path, encoder: FakeEncoder) -> Store:
    return await Store.create(tmp_path / ".zikaron", _config(tmp_path), encoder)


def _call(
    store: Store,
    tmp_path: Path,
    encoder: FakeEncoder,
    *,
    ctx: CallParams | None = None,
    chunk_max_tokens: int | None = None,
) -> IndexedCall:
    index = IndexingContext.for_store(store, _config(tmp_path), encoder)
    if chunk_max_tokens is not None:
        index = IndexingContext(
            encoder=encoder,
            chunk_max_tokens=chunk_max_tokens,
            gist_max_tokens=index.gist_max_tokens,
            identity=index.identity,
        )
    return IndexedCall(ctx=ctx if ctx is not None else _ctx(), index=index)


async def _chunk_rows(store: Store, uuid: str) -> list[tuple[Any, ...]]:
    rows = await store.connection.execute_fetchall(
        "SELECT chunk_id, part_index, token_count, truncated, embed_model, embed_dim "
        "FROM memory_chunk WHERE memory_uuid = ? ORDER BY part_index",
        (uuid,),
    )
    return [tuple(row) for row in rows]


async def _vector_rowids(store: Store) -> list[int]:
    rows = await store.connection.execute_fetchall("SELECT rowid FROM memory_vec")
    return sorted(int(row[0]) for row in rows)


async def _stored_vector(store: Store, chunk_id: int) -> tuple[float, ...]:
    rows = await store.connection.execute_fetchall(
        "SELECT embedding FROM memory_vec WHERE rowid = ?", (chunk_id,)
    )
    blob = bytes(next(iter(rows))[0])
    return struct.unpack(f"<{len(blob) // 4}f", blob)


async def _fts_uuids(store: Store, term: str) -> list[str]:
    quoted = '"' + term.replace('"', '""') + '"'
    rows = await store.connection.execute_fetchall(
        "SELECT m.uuid FROM memory_fts f JOIN memory m ON m.rowid = f.rowid "
        "WHERE memory_fts MATCH ? ORDER BY m.uuid",
        (quoted,),
    )
    return [str(row[0]) for row in rows]


async def _events(store: Store, uuid: str) -> list[tuple[str, dict[str, object]]]:
    """Every event about `uuid`, in `id` order, with `detail` parsed.

    Parsed rather than compared as text so an assertion states the fields and their values, and
    can also state their **order** — which `EVENT_SPECS` fixes, so that two implementations of one
    kind produce the same payload rather than merely equivalent ones.
    """
    rows = await store.connection.execute_fetchall(
        "SELECT kind, detail FROM event WHERE memory_uuid = ? ORDER BY id", (uuid,)
    )
    return [(str(kind), dict(json.loads(str(detail)))) for kind, detail in rows]


async def _receipts(store: Store, uuid: str) -> list[tuple[str, int, str]]:
    rows = await store.connection.execute_fetchall(
        "SELECT client_kind, version, source FROM read_receipt WHERE memory_uuid = ? "
        "ORDER BY version",
        (uuid,),
    )
    return [(str(kind), int(version), str(source)) for kind, version, source in rows]


async def _row(store: Store, uuid: str) -> tuple[Any, ...]:
    rows = await store.connection.execute_fetchall(
        "SELECT gist, content, version, token_count, active FROM memory WHERE uuid = ?", (uuid,)
    )
    return tuple(next(iter(rows)))


def _norm(vector: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    """`vector` scaled to unit length — what the write path stores, given any embedder's output."""
    scale = _norm(vector)
    return tuple(value / scale for value in vector)


# ---------------------------------------------------------------------------
# remember: what one write leaves behind
# ---------------------------------------------------------------------------


async def test_remember_writes_the_row_both_indexes_the_receipt_and_one_event(
    tmp_path: Path,
) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )

        gist, content, version, token_count, active = await _row(store, written.memory.uuid)
        assert (gist, content, version, active) == (_GIST, _CONTENT, 1, 1)
        assert token_count == written.plan.content_tokens

        chunks = await _chunk_rows(store, written.memory.uuid)
        assert len(chunks) == 1
        (chunk_id, part_index, chunk_tokens, truncated, embed_model, embed_dim) = chunks[0]
        assert (part_index, truncated) == (0, 0)
        assert chunk_tokens == written.plan.chunks[0].token_count
        assert (embed_model, embed_dim) == (store.meta.embed_model, store.meta.embed_dim)

        assert await _vector_rowids(store) == [chunk_id], "invariant 1: vec rowid is the chunk_id"
        assert await _fts_uuids(store, "requirements.txt") == [written.memory.uuid]
        assert await _fts_uuids(store, "protobuf") == [written.memory.uuid]

        assert await _receipts(store, written.memory.uuid) == [("mcp", 1, "own_write")]

        events = await _events(store, written.memory.uuid)
        assert [kind for kind, _ in events] == ["remember"]
        assert events[0][1] == {
            "version": 1,
            "token_count": written.plan.content_tokens,
            "gist_tokens": written.plan.gist_tokens,
            "n_chunks": 1,
            "truncated": False,
        }
        assert list(events[0][1]) == list(EVENT_SPECS[EventKind.REMEMBER].field_names)


async def test_remember_writes_one_chunk_and_one_vector_per_part(tmp_path: Path) -> None:
    """Invariant 1, on the property that actually matters: not that the id sets match, but that
    each vector is the embedding of *its own* chunk's assembled sequence. Matching sets alone would
    still hold if the vectors were paired with the wrong parts, and every chunk would then describe
    a different chunk's prose — a wrong answer to every dense query, with nothing to notice it."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder, chunk_max_tokens=3)
        content = "\n\n".join(["a1 a2 a3", "b1 b2 b3", "c1"])
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=content), call=call
        )
        chunks = await _chunk_rows(store, written.memory.uuid)
        assert [row[1] for row in chunks] == [0, 1, 2]
        assert await _vector_rowids(store) == sorted(int(row[0]) for row in chunks)
        for part_index, row in enumerate(chunks):
            expected = _unit(
                vector_for(written.plan.chunks[part_index].embedded_text(_GIST), encoder.dim)
            )
            assert await _stored_vector(store, int(row[0])) == pytest.approx(expected, abs=1e-6), (
                f"part {part_index}'s vector does not describe part {part_index}'s text"
            )
        detail = (await _events(store, written.memory.uuid))[0][1]
        assert detail["n_chunks"] == 3


async def test_stored_vectors_are_unit_length_even_though_the_encoder_returns_longer_ones(
    tmp_path: Path,
) -> None:
    """`retrieval.md`: the corpus is L2-normalized at write time, which the cosine conversion
    `cos = 1 - d^2/2` depends on. The fake encoder deliberately returns unnormalized vectors, so a
    write path that merely trusted its embedder would fail here."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        (chunk_id, *_rest) = (await _chunk_rows(store, written.memory.uuid))[0]
        stored = await _stored_vector(store, int(chunk_id))
        raw = vector_for(written.plan.chunks[0].embedded_text(_GIST), encoder.dim)
        assert _norm(raw) > 1.5, "the fixture must not accidentally hand over a unit vector"
        assert _norm(stored) == pytest.approx(1.0, abs=1e-5)
        scale = _norm(raw)
        assert stored == pytest.approx(tuple(value / scale for value in raw), abs=1e-6)


async def test_every_active_memory_has_at_least_one_chunk(tmp_path: Path) -> None:
    """Invariant 12. A memory with zero vectors is invisible to the dense arm while looking
    perfectly healthy, which is why this is an invariant rather than an expectation."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder, chunk_max_tokens=2)
        for content in (_CONTENT, "one", "a b\n\nc d\n\ne f"):
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=content), call=call
            )
        rows = await store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM memory m WHERE m.active = 1 "
            "AND NOT EXISTS (SELECT 1 FROM memory_chunk c WHERE c.memory_uuid = m.uuid)"
        )
        assert int(next(iter(rows))[0]) == 0


async def test_two_stores_index_the_same_prose_identically(tmp_path: Path) -> None:
    """Determinism end to end: the same prose produces the same chunk boundaries *and* the same
    stored bytes in a fresh store, which is what makes a reindex comparable to what it replaced."""
    written_state: list[tuple[list[Any], list[tuple[float, ...]]]] = []
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        encoder = FakeEncoder()
        async with await _open_store(root, encoder) as store:
            call = _call(store, root, encoder, chunk_max_tokens=4)
            content = "\n\n".join(["alpha beta gamma delta epsilon", "zeta eta"])
            written = await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=content), call=call
            )
            chunks = await _chunk_rows(store, written.memory.uuid)
            stored = [await _stored_vector(store, int(row[0])) for row in chunks]
            written_state.append(([list(row[1:]) for row in chunks], stored))
    assert written_state[0] == written_state[1]


# ---------------------------------------------------------------------------
# amend: atomic rewrite of prose and both indexes
# ---------------------------------------------------------------------------


async def test_amend_rewrites_the_row_replaces_the_chunks_and_resyncs_the_lexical_index(
    tmp_path: Path,
) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )

        amended = await writes.amend(
            store.connection,
            uuid=written.memory.uuid,
            version=written.memory.version,
            rewrite=Rewrite(gist="protobuf codegen fails on prod-eu", content="pin the compiler"),
            call=call,
        )

        gist, content, version, token_count, _active = await _row(store, written.memory.uuid)
        assert (gist, content, version) == (
            "protobuf codegen fails on prod-eu",
            "pin the compiler",
            2,
        )
        assert token_count == amended.plan.content_tokens

        after_chunks = await _chunk_rows(store, written.memory.uuid)
        assert len(after_chunks) == 1
        chunk_id = int(after_chunks[0][0])
        # `chunk_id` may well be the *same* integer as before: `memory_chunk.chunk_id` is an
        # `INTEGER PRIMARY KEY` with no `AUTOINCREMENT`, so SQLite reuses the id of a deleted row.
        # That is safe here only because vectors are deleted before chunks and reinserted after —
        # the identity that matters is not the number but which vector sits at it, so this asserts
        # the vector is the *new* prose's rather than the id having changed.
        expected = _unit(vector_for(amended.plan.chunks[0].embedded_text(amended.memory.gist), 384))
        assert await _stored_vector(store, chunk_id) == pytest.approx(expected, abs=1e-6)
        assert await _vector_rowids(store) == [chunk_id], (
            "the superseded vector is gone: an orphan vector is a silent false positive"
        )

        assert await _fts_uuids(store, "requirements.txt") == [], "a stale term stayed matchable"
        assert await _fts_uuids(store, "staging") == [], "a stale gist term stayed matchable"
        assert await _fts_uuids(store, "prod-eu") == [written.memory.uuid]
        assert await _fts_uuids(store, "protobuf") == [written.memory.uuid]

        events = await _events(store, written.memory.uuid)
        assert [kind for kind, _ in events] == ["remember", "amend"]
        assert events[1][1] == {
            "from_version": 1,
            "to_version": 2,
            "token_count": amended.plan.content_tokens,
            "gist_tokens": amended.plan.gist_tokens,
            "n_chunks": 1,
            "truncated": False,
        }
        assert list(events[1][1]) == list(EVENT_SPECS[EventKind.AMEND].field_names)
        assert await _receipts(store, written.memory.uuid) == [("mcp", 2, "own_write")]


async def test_amend_from_one_chunk_to_several_leaves_no_stale_chunk_or_vector(
    tmp_path: Path,
) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder, chunk_max_tokens=2)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content="one two"), call=call
        )
        assert len(await _chunk_rows(store, written.memory.uuid)) == 1

        await writes.amend(
            store.connection,
            uuid=written.memory.uuid,
            version=1,
            rewrite=Rewrite(gist=_GIST, content="a b\n\nc d\n\ne f"),
            call=call,
        )
        chunks = await _chunk_rows(store, written.memory.uuid)
        assert [row[1] for row in chunks] == [0, 1, 2]
        assert await _vector_rowids(store) == sorted(int(row[0]) for row in chunks)


async def test_deleting_a_memorys_vectors_precedes_deleting_its_chunk_rows(
    tmp_path: Path,
) -> None:
    """`indexing.md`: "Delete vectors before chunks." `memory_vec` has no foreign key, so
    chunks-first would leave a vector nothing identifies if the sequence were interrupted — a
    silent false positive in retrieval, where the reverse order leaves a detectable orphan chunk."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        statements: list[str] = []
        original = store.connection.execute

        async def spy(sql: str, parameters: Iterable[object] | None = None) -> aiosqlite.Cursor:
            statements.append(sql)
            return await original(sql) if parameters is None else await original(sql, parameters)

        with unittest.mock.patch.object(store.connection, "execute", new=spy):
            await writes.amend(
                store.connection,
                uuid=written.memory.uuid,
                version=1,
                rewrite=Rewrite(gist=_GIST, content="rewritten"),
                call=call,
            )
        deletes = [sql for sql in statements if sql.startswith("DELETE FROM memory_")]
        assert deletes == [
            "DELETE FROM memory_vec WHERE rowid = ?",
            "DELETE FROM memory_chunk WHERE memory_uuid = ?",
        ]


# ---------------------------------------------------------------------------
# Invariant 2: one transaction, all of it or none of it
# ---------------------------------------------------------------------------


async def test_a_failure_after_every_index_write_leaves_no_trace_of_the_remember(
    tmp_path: Path,
) -> None:
    """Invariant 2, simulated as the design asks — by raising mid-transaction. The event insert is
    the last statement, so at the moment this raises the row, the lexical index, the chunks, the
    vectors and the size are all staged."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        with (
            unittest.mock.patch.object(
                records, "log_event", side_effect=RuntimeError("killed mid-write")
            ),
            pytest.raises(RuntimeError, match="killed mid-write"),
        ):
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )

        for table in ("memory", "memory_chunk", "memory_vec", "event", "read_receipt"):
            rows = await store.connection.execute_fetchall(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            assert int(next(iter(rows))[0]) == 0, f"{table} kept a row from a rolled-back write"
        assert await _fts_uuids(store, "protobuf") == []


async def test_a_failure_between_deleting_and_rewriting_the_index_leaves_the_old_index_intact(
    tmp_path: Path,
) -> None:
    """The sharpest form of invariant 2 for `amend`: by the time this raises, the row's prose has
    been rewritten, the lexical postings have been swapped and the old chunks and vectors have been
    deleted. Either all of that survives or none of it does."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        before_chunks = await _chunk_rows(store, written.memory.uuid)

        with (
            unittest.mock.patch.object(
                vectors_module, "insert_chunks", side_effect=RuntimeError("killed mid-write")
            ),
            pytest.raises(RuntimeError, match="killed mid-write"),
        ):
            await writes.amend(
                store.connection,
                uuid=written.memory.uuid,
                version=1,
                rewrite=Rewrite(gist="new gist", content="new content"),
                call=call,
            )

        assert await _row(store, written.memory.uuid) == (
            _GIST,
            _CONTENT,
            1,
            written.plan.content_tokens,
            1,
        )
        assert await _chunk_rows(store, written.memory.uuid) == before_chunks
        assert await _vector_rowids(store) == [int(before_chunks[0][0])]
        assert await _fts_uuids(store, "requirements.txt") == [written.memory.uuid]
        assert await _fts_uuids(store, "content") == []
        assert [kind for kind, _ in await _events(store, written.memory.uuid)] == ["remember"]
        assert await _receipts(store, written.memory.uuid) == [("mcp", 1, "own_write")]


async def test_a_store_level_failure_inside_the_transaction_is_index_failed_at_index_write(
    tmp_path: Path,
) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        with (
            unittest.mock.patch.object(
                vectors_module, "insert_chunks", side_effect=aiosqlite.OperationalError("disk I/O")
            ),
            pytest.raises(ZikaronError) as raised,
        ):
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED
        assert raised.value.data["stage"] == IndexStage.INDEX_WRITE
        rows = await store.connection.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(rows))[0]) == 0


async def test_a_locked_store_is_store_busy_naming_the_verb_not_a_terminal_index_failure(
    tmp_path: Path,
) -> None:
    """`store_busy` is the one error the design tells a caller it may retry, so contention must not
    be collapsed into `index_failed` — a retryable answer reported as a terminal one costs the
    caller the retry. The result code is read off the exception rather than its message text.

    A second connection holds a write transaction while this one tries to open its own, with the
    waiting connection's `busy_timeout` lowered so the test does not sit out the real five seconds.
    """
    encoder = FakeEncoder()
    async with (
        await _open_store(tmp_path, encoder) as store,
        aiosqlite.connect(store.path) as holder,
    ):
        await store.connection.execute("PRAGMA busy_timeout = 50")
        await holder.execute("BEGIN IMMEDIATE")
        await holder.execute(
            "INSERT INTO meta (key, value) VALUES ('probe', 'holding the write lock')"
        )

        call = _call(store, tmp_path, encoder)
        with pytest.raises(ZikaronError) as raised:
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.STORE_BUSY
        assert raised.value.data == {"verb": "remember"}


async def test_a_failing_commit_is_reported_and_leaves_the_connection_clean(
    tmp_path: Path,
) -> None:
    """A `COMMIT` that fails means the write did not happen — and the transaction can still be open.

    Reporting the failure is only half of it. If the transaction were left open, every staged row
    would still be visible on this connection, the next `BEGIN` would fail as a nested one, and
    whatever committed next would durably publish a write already announced as failed. So this
    asserts all three: the wire code, a connection out of any transaction with nothing visible to a
    *second* connection, and a subsequent write succeeding with no cleanup of the test's own.
    """
    encoder = FakeEncoder()
    async with (
        await _open_store(tmp_path, encoder) as store,
        aiosqlite.connect(store.path) as onlooker,
    ):
        call = _call(store, tmp_path, encoder)

        async def failing_commit() -> None:
            raise aiosqlite.OperationalError("disk full")

        with (
            unittest.mock.patch.object(store.connection, "commit", new=failing_commit),
            pytest.raises(ZikaronError) as raised,
        ):
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED
        assert raised.value.data["stage"] == IndexStage.INDEX_WRITE

        assert not store.connection.in_transaction, "a reported failure left the write staged"
        visible = await onlooker.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(visible))[0]) == 0

        # No test-side rollback between the failure and this write: if the connection had been left
        # dirty, this `BEGIN` would fail rather than the write succeeding.
        recovered = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content="a later write"), call=call
        )
        assert recovered.memory.version == 1


async def test_a_connection_whose_rollback_also_fails_is_closed_rather_than_left_in_circulation(
    tmp_path: Path,
) -> None:
    """The double failure: the `COMMIT` fails and the compensating `ROLLBACK` fails too.

    The transaction state then cannot be repaired, so every later use of this connection risks
    committing the very write this call reported as failed — durable, and silent. Closing it turns
    that into a loud failure on next use. Disrupting another holder of a borrowed connection is the
    accepted cost: the holder gets an error it can act on, where the alternative is a memory the
    store told the agent it had not stored.
    """
    encoder = FakeEncoder()
    async with (
        await _open_store(tmp_path, encoder) as store,
        aiosqlite.connect(store.path) as onlooker,
    ):
        call = _call(store, tmp_path, encoder)

        async def failing_commit() -> None:
            raise aiosqlite.OperationalError("disk full")

        async def failing_rollback() -> None:
            raise aiosqlite.OperationalError("cannot roll back either")

        with (
            unittest.mock.patch.object(store.connection, "commit", new=failing_commit),
            unittest.mock.patch.object(store.connection, "rollback", new=failing_rollback),
            pytest.raises(ZikaronError) as raised,
        ):
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED

        visible = await onlooker.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(visible))[0]) == 0, "a reported failure published rows anyway"
        with pytest.raises(ValueError, match="no active connection"):
            await store.connection.execute("SELECT 1")


async def test_an_extended_busy_result_is_still_contention_rather_than_a_terminal_failure(
    tmp_path: Path,
) -> None:
    """SQLite reports *extended* results, so an exact-name test for `SQLITE_BUSY` misses the case
    that actually arises under WAL: a reader whose snapshot went stale before it tried to write gets
    `SQLITE_BUSY_SNAPSHOT`. Classifying on the primary code in the low byte is what keeps that
    retryable rather than terminal — and the retry is how the `version_conflict` behind it becomes
    observable at all."""

    class SnapshotBusy(aiosqlite.OperationalError):
        sqlite_errorcode = sqlite3.SQLITE_BUSY_SNAPSHOT
        sqlite_errorname = "SQLITE_BUSY_SNAPSHOT"

    assert SnapshotBusy.sqlite_errorcode & 0xFF == sqlite3.SQLITE_BUSY
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        with (
            unittest.mock.patch.object(
                vectors_module, "insert_chunks", side_effect=SnapshotBusy("snapshot is stale")
            ),
            pytest.raises(ZikaronError) as raised,
        ):
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.STORE_BUSY
        assert raised.value.data == {"verb": "remember"}


async def test_a_real_stale_snapshot_during_an_amend_is_reported_as_contention(
    tmp_path: Path,
) -> None:
    """The same case without injection, and deterministic rather than raced: the amend's own
    transaction reads the row, a second connection commits, and the amend's first write then cannot
    promote its stale snapshot. Ordered by construction — the second connection's commit is driven
    from inside the amend — so there is no timing window to be flaky about."""
    encoder = FakeEncoder()
    async with (
        await _open_store(tmp_path, encoder) as store,
        aiosqlite.connect(store.path) as other,
    ):
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        original_resync = lexical_module.resync

        async def commit_elsewhere_first(
            db: aiosqlite.Connection, **kwargs: lexical_module.Document | int
        ) -> None:
            await other.execute("BEGIN IMMEDIATE")
            await other.execute("INSERT INTO meta (key, value) VALUES ('probe', 'other writer')")
            await other.commit()
            await original_resync(db, **kwargs)  # type: ignore[arg-type]

        with (
            unittest.mock.patch.object(lexical_module, "resync", new=commit_elsewhere_first),
            pytest.raises(ZikaronError) as raised,
        ):
            await writes.amend(
                store.connection,
                uuid=written.memory.uuid,
                version=1,
                rewrite=Rewrite(gist=_GIST, content="rewritten under a stale snapshot"),
                call=call,
            )
        assert raised.value.code is ErrorCode.STORE_BUSY
        assert raised.value.data == {"verb": "amend"}
        assert not store.connection.in_transaction
        assert (await _row(store, written.memory.uuid))[:3] == (_GIST, _CONTENT, 1)


async def test_a_failure_opening_the_transaction_is_mapped_rather_than_escaping_raw(
    tmp_path: Path,
) -> None:
    """`BEGIN` is a statement like any other and can fail like any other. A raw `sqlite3` exception
    escaping here would leave whoever serializes the response with no code to send."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        original = store.connection.execute

        async def refuse_begin(
            sql: str, parameters: Iterable[object] | None = None
        ) -> aiosqlite.Cursor:
            if sql == "BEGIN":
                raise aiosqlite.OperationalError("cannot start a transaction within a transaction")
            return await original(sql) if parameters is None else await original(sql, parameters)

        with (
            unittest.mock.patch.object(store.connection, "execute", new=refuse_begin),
            pytest.raises(ZikaronError) as raised,
        ):
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED
        assert raised.value.data["stage"] == IndexStage.INDEX_WRITE
        rows = await store.connection.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(rows))[0]) == 0


# ---------------------------------------------------------------------------
# Invariant 10's carve-out, and what a rejected amend must not touch
# ---------------------------------------------------------------------------


async def test_a_version_conflict_commits_its_audit_trail_and_touches_neither_index(
    tmp_path: Path,
) -> None:
    """The defect this design note exists to prevent. Invariant 10's carve-out **commits** a
    `version_conflict`'s event and receipt, so any index work staged before the version check would
    be durably committed by a rejected amend — leaving a live row with no lexical index. The FTS
    resync therefore names the values it removes rather than letting FTS5 read them out of the
    content table, which is what allows it to run after authorization."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        before_chunks = await _chunk_rows(store, written.memory.uuid)

        with pytest.raises(ZikaronError) as raised:
            await writes.amend(
                store.connection,
                uuid=written.memory.uuid,
                version=99,
                rewrite=Rewrite(gist="new gist", content="new content"),
                call=call,
            )
        assert raised.value.code is ErrorCode.VERSION_CONFLICT

        assert await _fts_uuids(store, "requirements.txt") == [written.memory.uuid]
        assert await _fts_uuids(store, "content") == []
        assert await _chunk_rows(store, written.memory.uuid) == before_chunks
        assert (await _row(store, written.memory.uuid))[:3] == (_GIST, _CONTENT, 1)

        kinds = [kind for kind, _ in await _events(store, written.memory.uuid)]
        assert kinds == ["remember", "version_conflict"], "the audit event must survive"
        assert ("mcp", 1, "conflict") in await _receipts(store, written.memory.uuid)


async def test_an_amend_without_a_receipt_commits_its_event_and_touches_neither_index(
    tmp_path: Path,
) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        writer = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=writer
        )
        stranger = _call(store, tmp_path, encoder, ctx=_ctx(session_id="s2", op_id="op2"))

        with pytest.raises(ZikaronError) as raised:
            await writes.amend(
                store.connection,
                uuid=written.memory.uuid,
                version=1,
                rewrite=Rewrite(gist="new gist", content="new content"),
                call=stranger,
            )
        assert raised.value.code is ErrorCode.NO_READ_RECEIPT
        assert [kind for kind, _ in await _events(store, written.memory.uuid)] == [
            "remember",
            "no_receipt",
        ]
        assert await _fts_uuids(store, "requirements.txt") == [written.memory.uuid]
        assert (await _row(store, written.memory.uuid))[:3] == (_GIST, _CONTENT, 1)


async def test_amending_a_retired_row_is_refused_and_writes_nothing_at_all(tmp_path: Path) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        await records.retire(
            store.connection, uuid=written.memory.uuid, version=1, superseded_by=None, ctx=_ctx()
        )
        with pytest.raises(ZikaronError) as raised:
            await writes.amend(
                store.connection,
                uuid=written.memory.uuid,
                version=2,
                rewrite=Rewrite(gist="new gist", content="new content"),
                call=call,
            )
        assert raised.value.code is ErrorCode.INACTIVE_ROW
        assert raised.value.data["state"] == RowState.RETIRED
        assert [kind for kind, _ in await _events(store, written.memory.uuid)] == [
            "remember",
            "retire",
        ]


async def test_retire_leaves_both_indexes_exactly_as_they_were(tmp_path: Path) -> None:
    """D16 and invariant 4: retire never deletes, so the chunks and postings stay and a superseded
    row remains retrievable. This is also why the indexed write path has two verbs, not three —
    `retire` changes no indexed column, so it has nothing for this layer to maintain."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder, chunk_max_tokens=3)
        written = await writes.remember(
            store.connection, rewrite=Rewrite(gist=_GIST, content="a b c\n\nd e f"), call=call
        )
        before_chunks = await _chunk_rows(store, written.memory.uuid)
        before_vectors = await _vector_rowids(store)

        await records.retire(
            store.connection, uuid=written.memory.uuid, version=1, superseded_by=None, ctx=_ctx()
        )

        assert await _chunk_rows(store, written.memory.uuid) == before_chunks
        assert await _vector_rowids(store) == before_vectors
        assert await _fts_uuids(store, "protobuf") == [written.memory.uuid]


# ---------------------------------------------------------------------------
# Rejections before anything is written
# ---------------------------------------------------------------------------


async def test_a_gist_over_its_bound_rejects_the_write_before_any_row_exists(
    tmp_path: Path,
) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        long_gist = " ".join(f"g{index}" for index in range(65))
        with pytest.raises(ZikaronError) as raised:
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=long_gist, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.BOUNDS
        rows = await store.connection.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(rows))[0]) == 0
        assert encoder.embedded == [], "nothing should have been embedded for a refused write"


@pytest.mark.parametrize(
    ("fault", "expected_embed_calls"),
    [
        ({"embed_error": RuntimeError("onnx exploded")}, 1),
        ({"vector_count_delta": 1}, 1),
        ({"vector_width": 7}, 1),
    ],
)
async def test_an_embedder_that_misbehaves_is_index_failed_at_the_embed_stage(
    tmp_path: Path, fault: dict[str, Any], expected_embed_calls: int
) -> None:
    """The three ways an embedder can be wrong without raising anything the store would notice: it
    fails, it returns a different number of vectors than there are chunks, or it returns the wrong
    width. Each would otherwise become a vector that does not describe its chunk."""
    encoder = FakeEncoder(**fault)
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        with pytest.raises(ZikaronError) as raised:
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.INDEX_FAILED
        assert raised.value.data["stage"] == IndexStage.EMBED
        assert len(encoder.embedded) == expected_embed_calls
        rows = await store.connection.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(rows))[0]) == 0


# ---------------------------------------------------------------------------
# The guards that fire only when something upstream is already inconsistent
# ---------------------------------------------------------------------------


async def test_a_degenerate_vector_is_refused_rather_than_stored_as_infinities(
    tmp_path: Path,
) -> None:
    """A zero-norm vector has no direction to normalize, and dividing by its norm would store
    `inf` — a row that then matches every query at an unspecifiable distance."""

    class ZeroEncoder(FakeEncoder):
        def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
            self.embedded.append(tuple(texts))
            return tuple((0.0,) * self.dim for _ in texts)

    encoder = ZeroEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        with pytest.raises(ZikaronError) as raised:
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.data["stage"] == IndexStage.EMBED


async def test_an_encoder_raising_a_zikaron_error_keeps_its_own_code(tmp_path: Path) -> None:
    """`index_failed` is for a failure the caller cannot act on. An encoder that raises a Zikaron
    rejection has already said something more specific, and masking it would tell an operator the
    index failed when the real answer was a configuration error."""
    encoder = FakeEncoder(
        embed_error=ZikaronError(ErrorCode.BOUNDS, field="content", limit=1, actual=0)
    )
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        with pytest.raises(ZikaronError) as raised:
            await writes.remember(
                store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        assert raised.value.code is ErrorCode.BOUNDS


async def test_writing_fewer_vectors_than_chunks_is_refused_at_the_insert(tmp_path: Path) -> None:
    """`embed_chunks` already checks the count, so reaching `insert_chunks` with a short list means
    the two have already disagreed. It is still checked here, because the alternative is a chunk row
    with no vector — invisible to the dense arm while looking perfectly healthy."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder, chunk_max_tokens=2)
        prepared = await writes.prepare(Rewrite(gist=_GIST, content="a b\n\nc d"), index=call.index)
        assert prepared.plan.n_chunks == 2
        await store.connection.execute("BEGIN")
        try:
            with pytest.raises(ZikaronError) as raised:
                await vectors_module.insert_chunks(
                    store.connection,
                    memory_uuid="unreferenced-uuid",
                    plan=prepared.plan,
                    vectors=prepared.vectors[:1],
                    identity=call.index.identity,
                )
            assert raised.value.data["stage"] == IndexStage.EMBED
        finally:
            await store.connection.rollback()


async def test_a_driver_that_reports_no_chunk_id_is_index_failed_rather_than_paired_wrongly(
    tmp_path: Path,
) -> None:
    """Invariant 1 has exactly one mechanism: the vector's rowid *is* the chunk row's id. If the
    driver does not report that id there is nothing to pair the vector with, and guessing one would
    attach it to whatever row happened to hold that number."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        prepared = await writes.prepare(Rewrite(gist=_GIST, content=_CONTENT), index=call.index)
        # A real row, because `memory_chunk.memory_uuid` is a foreign key: the guard under test is
        # about the chunk id the driver reports, not about referential integrity.
        row = await records.create(store.connection, gist=_GIST, content=_CONTENT, session_id="s1")
        original = store.connection.execute

        async def silent_cursor(
            sql: str, parameters: Iterable[object] | None = None
        ) -> aiosqlite.Cursor:
            cursor = await original(sql) if parameters is None else await original(sql, parameters)
            if sql.startswith("INSERT INTO memory_chunk"):
                return cast("aiosqlite.Cursor", _NoRowidCursor(cursor))
            return cursor

        await store.connection.execute("BEGIN")
        try:
            with (
                unittest.mock.patch.object(store.connection, "execute", new=silent_cursor),
                pytest.raises(ZikaronError) as raised,
            ):
                await vectors_module.insert_chunks(
                    store.connection,
                    memory_uuid=row.uuid,
                    plan=prepared.plan,
                    vectors=prepared.vectors,
                    identity=call.index.identity,
                )
            assert raised.value.data["stage"] == IndexStage.INDEX_WRITE
        finally:
            await store.connection.rollback()


async def test_a_missing_row_at_the_lexical_step_is_reported_rather_than_indexed_at_a_guess(
    tmp_path: Path,
) -> None:
    """`memory_fts` is linked by rowid alone, so a write that could not find one has nothing to
    index against. Unreachable through either verb — the row was just written in the same
    transaction — and checked because indexing at a guessed rowid would attach one memory's terms
    to another's record."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        with pytest.raises(ZikaronError) as raised:
            await writes._rowid_of(store.connection, "no-such-uuid")
        assert raised.value.code is ErrorCode.NOT_FOUND


class _NoRowidCursor:
    """A cursor that answers `lastrowid` with `None`, as a driver with nothing to report would."""

    def __init__(self, wrapped: aiosqlite.Cursor) -> None:
        self._wrapped = wrapped

    @property
    def lastrowid(self) -> int | None:
        return None


# ---------------------------------------------------------------------------
# The encoder must be the one this store's index was built with
# ---------------------------------------------------------------------------


def test_an_encoder_disagreeing_with_the_stores_recorded_index_is_refused() -> None:
    """D20's silent-corruption case, arriving through the write path: a same-width model swap
    corrupts `vec0` with no schema protection, so the model *name* is what makes a stored vector's
    meaning checkable."""
    identity = IndexIdentity(embed_model="BAAI/bge-small-en-v1.5", embed_dim=384)
    with pytest.raises(ZikaronError) as wrong_model:
        IndexingContext(
            encoder=FakeEncoder(model_name="BAAI/bge-base-en-v1.5"),
            chunk_max_tokens=450,
            gist_max_tokens=64,
            identity=identity,
        )
    assert wrong_model.value.code is ErrorCode.BAD_CONFIG
    assert wrong_model.value.data["source"] == "meta"

    with pytest.raises(ZikaronError) as wrong_width:
        IndexingContext(
            encoder=FakeEncoder(dim=768),
            chunk_max_tokens=450,
            gist_max_tokens=64,
            identity=identity,
        )
    assert wrong_width.value.code is ErrorCode.BAD_CONFIG


async def test_for_store_takes_its_identity_from_meta_and_its_bounds_from_the_config(
    tmp_path: Path,
) -> None:
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        index = IndexingContext.for_store(store, _config(tmp_path), encoder)
        assert index.identity == IndexIdentity(
            embed_model=store.meta.embed_model, embed_dim=store.meta.embed_dim
        )
        assert (index.chunk_max_tokens, index.gist_max_tokens) == (450, 64)


# ---------------------------------------------------------------------------
# The composition seam the write-path milestone needs
# ---------------------------------------------------------------------------


async def test_the_neutral_cores_compose_into_a_wider_transaction_with_one_commit(
    tmp_path: Path,
) -> None:
    """D15's dedup search has to run in the same transaction as the `remember` it reports on, since
    it queries the vectors that write just inserted. This is that composition, with a sentinel
    write standing in for the dedup query's own bookkeeping."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        prepared = await writes.prepare(Rewrite(gist=_GIST, content=_CONTENT), index=call.index)

        await store.connection.execute("BEGIN")
        written = await writes.remember_within_transaction(
            store.connection, prepared=prepared, call=call
        )
        await store.connection.execute(
            "INSERT INTO event (at, session_id, client_kind, op_id, kind, memory_uuid, detail) "
            "VALUES ('t', 's1', 'mcp', 'op1', 'dedup_offered', ?, '{}')",
            (written.memory.uuid,),
        )
        await store.connection.commit()

        assert [kind for kind, _ in await _events(store, written.memory.uuid)] == [
            "remember",
            "dedup_offered",
        ]
        assert len(await _chunk_rows(store, written.memory.uuid)) == 1


async def test_a_composing_callers_transaction_rolls_back_the_whole_indexed_write(
    tmp_path: Path,
) -> None:
    """The other half of the seam: the neutral core touches the transaction on no path, so a
    composing caller that decides to roll back takes the index writes with it."""
    encoder = FakeEncoder()
    async with await _open_store(tmp_path, encoder) as store:
        call = _call(store, tmp_path, encoder)
        prepared = await writes.prepare(Rewrite(gist=_GIST, content=_CONTENT), index=call.index)

        await store.connection.execute("BEGIN")
        written = await writes.remember_within_transaction(
            store.connection, prepared=prepared, call=call
        )
        await store.connection.rollback()

        assert await _chunk_rows(store, written.memory.uuid) == []
        assert await _vector_rowids(store) == []
        assert await _fts_uuids(store, "protobuf") == []
