"""`zikaron.core.records.memory` — invariants 4-10, checked against `design/schema.md` and
`design/architecture.md` §"Validation precedence".
"""

import asyncio
import json
import sqlite3
import unittest.mock
from pathlib import Path
from typing import cast

import aiosqlite
import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.errors import ErrorCode, RowState, ZikaronError
from zikaron.core.events import (
    ArmTermination,
    FetchDetail,
    QueryShape,
    SearchDetail,
    StopReason,
)
from zikaron.core.records import supersession
from zikaron.core.records.memory import (
    CallParams,
    ConflictRecord,
    Memory,
    Rewrite,
    Tier,
    amend,
    amend_within_transaction,
    commit_or_roll_back,
    create,
    create_within_transaction,
    fetch,
    log_event,
    retire,
    retire_within_transaction,
)
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store

_MAX_DEPTH = 32


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


async def _open_store(tmp_path: Path) -> Store:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    embedder = FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)
    return await Store.create(store_dir, config, embedder)


def _ctx(session_id: str = "s1", client_kind: str = "mcp", op_id: str = "op1") -> CallParams:
    return CallParams(
        session_id=session_id, client_kind=client_kind, op_id=op_id, max_depth=_MAX_DEPTH
    )


async def _event_kinds(store: Store, memory_uuid: str | None = None) -> list[str]:
    if memory_uuid is None:
        rows = await store.connection.execute_fetchall("SELECT kind FROM event ORDER BY id")
    else:
        rows = await store.connection.execute_fetchall(
            "SELECT kind FROM event WHERE memory_uuid = ? ORDER BY id", (memory_uuid,)
        )
    return [str(row[0]) for row in rows]


async def _event_rows_of_kind(
    store: Store, *, memory_uuid: str, kind: str
) -> list[dict[str, object]]:
    """Every event row of `kind` for `memory_uuid`, as its parsed `detail` JSON, in `id` order —
    for asserting exact cardinality and full detail content, not merely that a kind occurred."""
    rows = await store.connection.execute_fetchall(
        "SELECT detail FROM event WHERE memory_uuid = ? AND kind = ? ORDER BY id",
        (memory_uuid, kind),
    )
    return [json.loads(str(row[0])) for row in rows]


async def _receipt_count(store: Store, memory_uuid: str) -> int:
    rows = await store.connection.execute_fetchall(
        "SELECT COUNT(*) FROM read_receipt WHERE memory_uuid = ?", (memory_uuid,)
    )
    return int(next(iter(rows))[0])


# ---------------------------------------------------------------------------
# create / fetch basics — not invariants of their own, but the substrate every test below needs
# ---------------------------------------------------------------------------


async def test_create_inserts_a_live_journal_row_at_version_one(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        assert created.version == 1
        assert created.tier is Tier.JOURNAL
        assert created.active is True
        assert created.superseded_by is None
        assert created.resolved_state is RowState.LIVE


async def test_create_with_empty_content_rolls_back_on_the_tables_own_check_constraint(
    tmp_path: Path,
) -> None:
    """`create`'s own docstring: non-emptiness is enforced by the table's `CHECK` constraint,
    which raises `sqlite3.IntegrityError` rather than a `ZikaronError` — this layer's fence
    leaves that boundary to the tool-facing `bounds` rejection. The failed `INSERT` must still
    roll back cleanly rather than leave a half-open transaction behind for the next call."""
    async with await _open_store(tmp_path) as store:
        with pytest.raises(sqlite3.IntegrityError):
            await create(store.connection, gist="g", content="   ", session_id="s1")
        # The connection is usable afterwards — proof the rollback actually ran, since a
        # dangling open transaction would make this next write hang or raise instead.
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        assert created.version == 1


async def test_fetch_mints_a_receipt_and_reports_missing_uuids(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        records, missing = await fetch(
            store.connection, uuids=[created.uuid, "does-not-exist"], ctx=_ctx()
        )
        assert [r.uuid for r in records] == [created.uuid]
        assert missing == ["does-not-exist"]
        assert await _receipt_count(store, created.uuid) == 1


async def test_fetch_collapses_duplicate_uuids_to_one_record_in_first_occurrence_order(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        a = await create(store.connection, gist="ga", content="ca", session_id="s1")
        b = await create(store.connection, gist="gb", content="cb", session_id="s1")
        records, missing = await fetch(store.connection, uuids=[b.uuid, a.uuid, b.uuid], ctx=_ctx())
        assert [r.uuid for r in records] == [b.uuid, a.uuid]
        assert missing == []


# ---------------------------------------------------------------------------
# Invariant 4: retire never deletes
# ---------------------------------------------------------------------------


async def test_invariant_4_retire_sets_active_zero_and_leaves_the_row_readable(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        retired = await retire(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        assert retired.active is False
        assert retired.gist == created.gist
        assert retired.content == created.content
        rows = await store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM memory WHERE uuid = ?", (created.uuid,)
        )
        assert int(next(iter(rows))[0]) == 1


# ---------------------------------------------------------------------------
# Invariant 5: retired vs. superseded are distinct row states
# ---------------------------------------------------------------------------


async def test_invariant_5_retired_outright_has_no_superseded_by(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        retired = await retire(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        assert retired.superseded_by is None
        assert retired.resolved_state is RowState.RETIRED


async def test_invariant_5_superseded_has_active_zero_and_superseded_by_set(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        old = await create(store.connection, gist="old", content="old", session_id="s1")
        new = await create(store.connection, gist="new", content="new", session_id="s1")
        await fetch(store.connection, uuids=[old.uuid], ctx=_ctx())
        superseded = await retire(
            store.connection,
            uuid=old.uuid,
            version=old.version,
            superseded_by=new.uuid,
            ctx=_ctx(),
        )
        assert superseded.active is False
        assert superseded.superseded_by == new.uuid
        assert superseded.resolved_state is RowState.SUPERSEDED


async def test_invariant_5_active_zero_does_not_imply_superseded_by_not_null(
    tmp_path: Path,
) -> None:
    """`active=0` alone does not imply `superseded_by` is set: an outright retirement is
    `active=0, superseded_by IS NULL`, and a caller that inferred otherwise from `active` alone
    would be wrong here."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        retired = await retire(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        assert retired.active is False
        assert retired.superseded_by is None


# ---------------------------------------------------------------------------
# Invariant 6: the supersession graph — no self-edge, no cycle, target-state precondition,
# one immutable outbound edge, and the three acceptance tests the invariant names by name.
# ---------------------------------------------------------------------------


async def test_an_unknown_target_precedes_the_sources_own_stale_version(tmp_path: Path) -> None:
    """The ladder's existence rung covers every named uuid before version or receipt is checked
    for any of them: a `retire` naming a stale source version *and* an unknown `superseded_by`
    target must report the target's own `NOT_FOUND` — not `VERSION_CONFLICT` on the source,
    which is what checking the source's version before the target's existence would report."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )
        # `created.version` is now stale (the amend above bumped it), and the target does not
        # exist at all.
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                superseded_by="does-not-exist",
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.NOT_FOUND
        assert excinfo.value.data["uuid"] == "does-not-exist"

        # Nothing committed on this rejection at all, per the ladder's "existence has written
        # nothing yet" rule — no conflict receipt for the source, and no event beyond the one
        # already committed by the setup calls above. The only receipt present is the amend's
        # own `own_write` one; the earlier `fetch` receipt was already revoked by that same
        # amend's version bump (invariant 9), before this test's own `retire` call ever ran.
        rows = await store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ?", (created.uuid,)
        )
        assert [str(r[0]) for r in rows] == ["own_write"]
        kinds = await _event_kinds(store, created.uuid)
        assert kinds == ["fetch"]


async def test_an_unknown_target_precedes_the_sources_own_missing_receipt(
    tmp_path: Path,
) -> None:
    """As the version case above, but for the receipt rung: a `retire` naming a source with no
    receipt at all *and* an unknown `superseded_by` target must still report the target's own
    `NOT_FOUND`, not `NO_READ_RECEIPT` on the source."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        # No fetch at all — the source holds no receipt for any version.
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                superseded_by="does-not-exist",
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.NOT_FOUND
        assert excinfo.value.data["uuid"] == "does-not-exist"

        rows = await store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ?", (created.uuid,)
        )
        assert list(rows) == []
        kinds = await _event_kinds(store, created.uuid)
        assert kinds == []


async def test_invariant_6_a_self_edge_is_rejected(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                superseded_by=created.uuid,
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == "self_edge"


async def test_invariant_6_a_cycle_is_rejected(tmp_path: Path) -> None:
    """A -> B exists; closing B -> A would be a cycle and must be refused."""
    async with await _open_store(tmp_path) as store:
        a = await create(store.connection, gist="a", content="a", session_id="s1")
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        await retire(
            store.connection, uuid=a.uuid, version=a.version, superseded_by=b.uuid, ctx=_ctx()
        )
        await fetch(store.connection, uuids=[b.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=b.uuid,
                version=b.version,
                superseded_by=a.uuid,
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == "cycle"


async def test_invariant_6_target_already_retired_outright_is_rejected(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        target = await create(store.connection, gist="t", content="t", session_id="s1")
        await fetch(store.connection, uuids=[target.uuid], ctx=_ctx())
        retired_target = await retire(
            store.connection,
            uuid=target.uuid,
            version=target.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        source = await create(store.connection, gist="s", content="s", session_id="s1")
        await fetch(store.connection, uuids=[source.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=source.uuid,
                version=source.version,
                superseded_by=retired_target.uuid,
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == "target_retired_outright"


async def test_invariant_6_superseded_target_is_a_legal_replacement(tmp_path: Path) -> None:
    """A replacement may itself be superseded — that is how A -> B -> C arises."""
    async with await _open_store(tmp_path) as store:
        a = await create(store.connection, gist="a", content="a", session_id="s1")
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        await retire(
            store.connection, uuid=a.uuid, version=a.version, superseded_by=b.uuid, ctx=_ctx()
        )
        c = await create(store.connection, gist="c", content="c", session_id="s1")
        await fetch(store.connection, uuids=[c.uuid], ctx=_ctx())
        superseded = await retire(
            store.connection, uuid=c.uuid, version=c.version, superseded_by=b.uuid, ctx=_ctx()
        )
        assert superseded.superseded_by == b.uuid


async def test_invariant_6_a_walk_that_hits_the_depth_cap_is_an_error(tmp_path: Path) -> None:
    """A store deep enough that the cycle walk cannot resolve within `max_depth` steps must fail
    closed rather than hang."""
    async with await _open_store(tmp_path) as store:
        ctx = CallParams(session_id="s1", client_kind="mcp", op_id="op1", max_depth=2)
        head = await create(store.connection, gist="head", content="head", session_id="s1")
        current = head
        for _ in range(4):
            nxt = await create(store.connection, gist="n", content="n", session_id="s1")
            await fetch(store.connection, uuids=[current.uuid], ctx=ctx)
            current = await retire(
                store.connection,
                uuid=current.uuid,
                version=current.version,
                superseded_by=nxt.uuid,
                ctx=ctx,
            )
            current = nxt
        # `current` is now the live tip of a chain 4 edges deep. Fetching it and resolving its
        # own (non-existent) supersession is fine; the cap bites on a *write* whose cycle walk
        # must traverse further than `max_depth` allows.
        probe = await create(store.connection, gist="probe", content="probe", session_id="s1")
        await fetch(store.connection, uuids=[probe.uuid], ctx=ctx)
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=probe.uuid,
                version=probe.version,
                superseded_by=head.uuid,
                ctx=ctx,
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == "depth_cap_hit"


async def test_invariant_6_acceptance_a_to_b_to_c_traversal(tmp_path: Path) -> None:
    """The invariant's own named acceptance test: A -> B -> C, then fetch A and confirm the walk
    resolves to C."""
    async with await _open_store(tmp_path) as store:
        c = await create(store.connection, gist="c", content="c", session_id="s1")
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        a = await create(store.connection, gist="a", content="a", session_id="s1")
        await fetch(store.connection, uuids=[b.uuid], ctx=_ctx())
        await retire(
            store.connection, uuid=b.uuid, version=b.version, superseded_by=c.uuid, ctx=_ctx()
        )
        await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        await retire(
            store.connection, uuid=a.uuid, version=a.version, superseded_by=b.uuid, ctx=_ctx()
        )
        records, _missing = await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        (fetched_a,) = records
        assert fetched_a.superseded_by == b.uuid
        assert fetched_a.superseded_by_latest == c.uuid
        assert fetched_a.superseded_by_latest_state == RowState.LIVE


async def _attempt_retire(
    connection: aiosqlite.Connection, *, from_uuid: str, to_uuid: str
) -> object:
    """Run one `retire(from_uuid, superseded_by=to_uuid)` and return either the resulting
    `Memory` or the exception it raised, rather than letting either propagate — a shared helper
    for the concurrent-race tests below, whose racing coroutines need to compare outcomes after
    the fact instead of having `asyncio.gather` raise on the first one to fail.
    """
    try:
        return await retire(
            connection,
            uuid=from_uuid,
            version=1,
            superseded_by=to_uuid,
            ctx=_ctx(session_id="racer"),
        )
    except ZikaronError as error:
        return error
    except sqlite3.OperationalError as error:
        # Both connections hold a deferred transaction with a read already taken by the time
        # they reach a synchronization point, so the loser of a write race can surface as
        # SQLite's own lock contention rather than as a `ZikaronError` this module raises — a
        # real, legitimate race outcome, not a defect in the retire path itself.
        return error


async def test_invariant_6_acceptance_two_concurrent_attempts_to_close_a_cycle(
    tmp_path: Path,
) -> None:
    """The invariant's own named acceptance test, run as a genuine check-then-write race: two
    initially-**live, edgeless** rows, `a` and `b`. One connection attempts `a -> b`, the other
    attempts `b -> a`, concurrently. Both are synchronized to complete their own read-side
    validation — the cycle walk inside `supersession.validate_new_edge` — before either is
    allowed to proceed to its `UPDATE`, so both genuinely observe the same edgeless initial
    graph rather than one attempt's read landing after the other's write. That is what a
    sequential test on one connection, or two attempts against an *already*-illegal graph,
    cannot expose: with no edge yet written, each attempt's own validation is legal on its own,
    and only SQLite's single-writer serialization at the `UPDATE` step can decide which one
    actually gets to keep it — a race exactly at the boundary invariant 6 has to hold across."""
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    embedder = FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)
    async with await Store.create(store_dir, config, embedder) as setup_store:
        a = await create(setup_store.connection, gist="a", content="a", session_id="s1")
        b = await create(setup_store.connection, gist="b", content="b", session_id="s1")
        # Receipts minted once, from the setup connection — invariant 9 scopes a receipt to
        # `(session_id, client_kind)`, not to a connection, so both racing connections below can
        # present the same one.
        await fetch(setup_store.connection, uuids=[a.uuid, b.uuid], ctx=_ctx(session_id="racer"))

    async with (
        await Store.open(store_dir, config) as left,
        await Store.open(store_dir, config) as right,
    ):
        real_validate = supersession.validate_new_edge
        both_validated = asyncio.Event()
        validated_count = 0
        lock = asyncio.Lock()

        async def _validate_then_synchronize(
            db: aiosqlite.Connection, *, from_uuid: str, to_uuid: str, max_depth: int
        ) -> None:
            """Runs the real validation (both attempts' reads land, on an edgeless graph),
            then blocks every racer until the other has *also* finished validating, so neither
            attempt's `UPDATE` can start before both attempts' reads have both already run."""
            nonlocal validated_count
            await real_validate(db, from_uuid=from_uuid, to_uuid=to_uuid, max_depth=max_depth)
            async with lock:
                validated_count += 1
                if validated_count == 2:
                    both_validated.set()
            await both_validated.wait()

        with unittest.mock.patch.object(
            supersession, "validate_new_edge", side_effect=_validate_then_synchronize
        ):
            a_to_b, b_to_a = await asyncio.gather(
                _attempt_retire(left.connection, from_uuid=a.uuid, to_uuid=b.uuid),
                _attempt_retire(right.connection, from_uuid=b.uuid, to_uuid=a.uuid),
            )

        assert validated_count == 2, "the synchronization point was never reached by both racers"

        outcomes = [a_to_b, b_to_a]
        successes = [outcome for outcome in outcomes if isinstance(outcome, Memory)]
        rejections = [
            outcome
            for outcome in outcomes
            if isinstance(outcome, ZikaronError | sqlite3.OperationalError)
        ]
        # Both attempts validated against the same edgeless graph, so both passed their own
        # cycle check legitimately — this is exactly the race invariant 6 has to survive. What
        # decides the outcome now is SQLite's single-writer lock at the `UPDATE` step, not
        # either attempt's own logic, so exactly one commits and the other loses the write race,
        # surfacing as `sqlite3.OperationalError` (this connection's own transaction already
        # holds a conflicting lock) rather than a `ZikaronError` this module raises — a real,
        # legitimate outcome of the race, not a defect. Two successes is the only truly
        # disallowed outcome: it would mean both `a->b` and `b->a` committed, which is a cycle
        # by definition.
        assert len(successes) + len(rejections) == 2
        assert len(successes) <= 1

        # A connection whose attempt ended in `OperationalError` may still be sitting inside an
        # errored transaction; roll it back explicitly before reading through it below, since a
        # driver-level failure — unlike this module's own `ZikaronError` rejections — is not
        # guaranteed to have already resolved the transaction state on its own.
        for connection, outcome in ((left, a_to_b), (right, b_to_a)):
            if isinstance(outcome, sqlite3.OperationalError):
                await connection.connection.rollback()

        # The graph is acyclic either way. Whichever edge (if any) survived, walking from its
        # tail must terminate without ever reaching back to where it started.
        records, _missing = await fetch(left.connection, uuids=[a.uuid, b.uuid], ctx=_ctx())
        by_uuid = {record.uuid: record for record in records}
        if by_uuid[a.uuid].superseded_by == b.uuid:
            assert by_uuid[b.uuid].superseded_by != a.uuid
        if by_uuid[b.uuid].superseded_by == a.uuid:
            assert by_uuid[a.uuid].superseded_by != b.uuid


async def test_invariant_6_acceptance_retiring_a_replacement_outright_makes_a_terminal_component(
    tmp_path: Path,
) -> None:
    """The invariant's own named acceptance test: A -> B, then an outright retire(B) must
    succeed and produce a terminal component, not an error or a corrupted graph."""
    async with await _open_store(tmp_path) as store:
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        a = await create(store.connection, gist="a", content="a", session_id="s1")
        await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        await retire(
            store.connection, uuid=a.uuid, version=a.version, superseded_by=b.uuid, ctx=_ctx()
        )
        await fetch(store.connection, uuids=[b.uuid], ctx=_ctx())
        retired_b = await retire(
            store.connection, uuid=b.uuid, version=b.version, superseded_by=None, ctx=_ctx()
        )
        assert retired_b.active is False
        assert retired_b.superseded_by is None

        records, _missing = await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        (fetched_a,) = records
        assert fetched_a.superseded_by == b.uuid
        assert fetched_a.superseded_by_latest == b.uuid
        assert fetched_a.superseded_by_latest_state == RowState.RETIRED


async def test_invariant_6_superseded_by_is_immutable_once_set(tmp_path: Path) -> None:
    """A row already superseded is `active=0`, so a second `retire` naming a different target is
    caught as `inactive_row` before any supersession check runs — the edge is immutable because
    nothing can reach the code that would re-point it."""
    async with await _open_store(tmp_path) as store:
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        c = await create(store.connection, gist="c", content="c", session_id="s1")
        a = await create(store.connection, gist="a", content="a", session_id="s1")
        await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        superseded = await retire(
            store.connection, uuid=a.uuid, version=a.version, superseded_by=b.uuid, ctx=_ctx()
        )
        await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=a.uuid,
                version=superseded.version,
                superseded_by=c.uuid,
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.INACTIVE_ROW


# ---------------------------------------------------------------------------
# Invariant 7: immediate edge for storage, resolved root for display
# ---------------------------------------------------------------------------


async def test_invariant_7_fetch_omits_superseded_by_latest_for_a_root_row(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        records, _missing = await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        (fetched,) = records
        assert fetched.superseded_by is None
        assert fetched.superseded_by_latest is None
        assert fetched.superseded_by_latest_state is None


async def test_invariant_7_two_absorbed_rows_resolve_to_the_same_replacement(
    tmp_path: Path,
) -> None:
    """Two rows superseded by the same target both resolve `superseded_by_latest` to it —
    convergence, not only chains, per invariant 6's "rooted converging forest"."""
    async with await _open_store(tmp_path) as store:
        target = await create(store.connection, gist="t", content="t", session_id="s1")
        a = await create(store.connection, gist="a", content="a", session_id="s1")
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        await fetch(store.connection, uuids=[a.uuid, b.uuid], ctx=_ctx())
        await retire(
            store.connection,
            uuid=a.uuid,
            version=a.version,
            superseded_by=target.uuid,
            ctx=_ctx(),
        )
        await retire(
            store.connection,
            uuid=b.uuid,
            version=b.version,
            superseded_by=target.uuid,
            ctx=_ctx(),
        )
        records, _missing = await fetch(store.connection, uuids=[a.uuid, b.uuid], ctx=_ctx())
        assert {r.superseded_by_latest for r in records} == {target.uuid}


# ---------------------------------------------------------------------------
# Invariant 8: version is monotonic and bumped on every mutation
# ---------------------------------------------------------------------------


async def test_invariant_8_amend_bumps_version_by_exactly_one(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        amended = await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )
        assert amended.version == created.version + 1


async def test_invariant_8_retire_bumps_version_by_exactly_one(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        retired = await retire(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        assert retired.version == created.version + 1


async def test_invariant_8_version_never_decreases_across_repeated_amends(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        current = await create(store.connection, gist="g0", content="c0", session_id="s1")
        versions = [current.version]
        for i in range(1, 5):
            await fetch(store.connection, uuids=[current.uuid], ctx=_ctx())
            current = await amend(
                store.connection,
                uuid=current.uuid,
                version=current.version,
                rewrite=Rewrite(gist=f"g{i}", content=f"c{i}"),
                ctx=_ctx(),
            )
            versions.append(current.version)
        assert versions == sorted(versions)
        assert len(set(versions)) == len(versions)


# ---------------------------------------------------------------------------
# Invariant 9: a write requires a read receipt for every row it mutates
# ---------------------------------------------------------------------------


async def test_invariant_9_amend_without_a_receipt_is_rejected(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="g2", content="c2"),
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.NO_READ_RECEIPT
        assert excinfo.value.data["uuids"] == [created.uuid]
        assert excinfo.value.data["hint"] == "re-read it through fetch or next_group"


async def test_invariant_9_a_version_bump_revokes_other_receipts_but_not_the_writers_own(
    tmp_path: Path,
) -> None:
    """The build plan's own done-when criterion, verbatim: "a version bump provably revokes
    other clients' receipts but not the writer's"."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        # Two different sessions both fetch the row at version 1, minting a receipt each.
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx(session_id="writer"))
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx(session_id="onlooker"))
        assert await _receipt_count(store, created.uuid) == 2

        amended = await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(session_id="writer"),
        )

        # Only one receipt survives: the writer's own, at the new version.
        assert await _receipt_count(store, created.uuid) == 1
        rows = await store.connection.execute_fetchall(
            "SELECT session_id, version FROM read_receipt WHERE memory_uuid = ?", (created.uuid,)
        )
        [(surviving_session, surviving_version)] = rows
        assert surviving_session == "writer"
        assert surviving_version == amended.version

        # The onlooker's now-revoked receipt can no longer license a write at the old version.
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="g3", content="c3"),
                ctx=_ctx(session_id="onlooker"),
            )
        assert excinfo.value.code is ErrorCode.VERSION_CONFLICT


async def test_invariant_9_minting_is_idempotent_on_a_repeat_fetch(tmp_path: Path) -> None:
    """`schema.md`: minting is an upsert refreshing `at`/`source`, since a repeat delivery at the
    same version must not violate `read_receipt`'s primary key."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        assert await _receipt_count(store, created.uuid) == 1


async def test_invariant_9_a_receipt_is_scoped_to_session_and_client_kind_together(
    tmp_path: Path,
) -> None:
    """`schema.md`: the receipt key is `(session_id, client_kind, memory_uuid, version)`, not
    `session_id` alone — a consolidator receipt for one session must not license an `mcp` write
    for that same session. This is the build plan's own done-when criterion: "a consolidator
    receipt does not license a `kind='mcp'` amend"."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(
            store.connection,
            uuids=[created.uuid],
            ctx=_ctx(session_id="shared", client_kind="consolidator"),
        )
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="g2", content="c2"),
                ctx=_ctx(session_id="shared", client_kind="mcp"),
            )
        assert excinfo.value.code is ErrorCode.NO_READ_RECEIPT


async def test_invariant_9_own_write_licenses_a_further_amend_with_no_extra_fetch(
    tmp_path: Path,
) -> None:
    """`own_write` mints a receipt at the new version, so the same session may amend again
    immediately — D6's "read before amend" is satisfied by having just authored the prose."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        first = await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )
        second = await amend(
            store.connection,
            uuid=created.uuid,
            version=first.version,
            rewrite=Rewrite(gist="g3", content="c3"),
            ctx=_ctx(),
        )
        assert second.version == first.version + 1


async def test_invariant_9_the_version_check_precedes_the_receipt_check(tmp_path: Path) -> None:
    """`architecture.md`: version runs before receipt, so a stale-version call with no receipt
    at all still reports `version_conflict`, not `no_read_receipt` — the informative error for
    the common lost-update race."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )
        # A second caller who never fetched at all, presenting the now-stale original version.
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="g3", content="c3"),
                ctx=_ctx(session_id="never-fetched"),
            )
        assert excinfo.value.code is ErrorCode.VERSION_CONFLICT


async def test_invariant_9_conflict_mints_a_receipt_the_caller_can_retry_with(
    tmp_path: Path,
) -> None:
    """D26's "re-decide in one round trip": the conflict payload's receipt licenses an immediate
    retry at the current version, with no extra `fetch` call."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx(session_id="racer"))
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx(session_id="winner"))
        winning = await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="w", content="w"),
            ctx=_ctx(session_id="winner"),
        )
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="r", content="r"),
                ctx=_ctx(session_id="racer"),
            )
        current_record = cast(ConflictRecord, excinfo.value.data["current"])
        assert current_record.version == winning.version

        retried = await amend(
            store.connection,
            uuid=created.uuid,
            version=winning.version,
            rewrite=Rewrite(gist="r2", content="r2"),
            ctx=_ctx(session_id="racer"),
        )
        assert retried.version == winning.version + 1


async def test_invariant_9_a_version_conflicts_current_is_one_conflict_record_never_a_list(
    tmp_path: Path,
) -> None:
    """`architecture.md`'s tool surface states
    `zikaron_memory_amend`/`zikaron_memory_retire`'s conflict shape
    as `{conflict: true, current: CONFLICT_RECORD}` — one object. The list form
    (`current: [CONFLICT_RECORD, ...]`) belongs only to the four consolidator verbs, so `amend`'s
    own conflict payload must never wrap in a list."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx(session_id="winner"))
        winning = await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="w", content="w"),
            ctx=_ctx(session_id="winner"),
        )
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="stale", content="stale"),
                ctx=_ctx(session_id="stale-caller"),
            )
        current = excinfo.value.data["current"]
        assert not isinstance(current, list)
        assert isinstance(current, ConflictRecord)
        assert current == ConflictRecord(
            uuid=created.uuid,
            gist="w",
            content="w",
            version=winning.version,
            tier=Tier.JOURNAL,
            state=RowState.LIVE,
            superseded_by=None,
            superseded_by_latest=None,
            superseded_by_latest_state=None,
        )


async def test_invariant_9_amend_rejects_an_already_inactive_row(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        retired = await retire(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=retired.version,
                rewrite=Rewrite(gist="g2", content="c2"),
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.INACTIVE_ROW
        assert excinfo.value.data["state"] == RowState.RETIRED


async def test_invariant_9_retire_rejects_an_already_inactive_row(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        old = await create(store.connection, gist="old", content="old", session_id="s1")
        new = await create(store.connection, gist="new", content="new", session_id="s1")
        await fetch(store.connection, uuids=[old.uuid], ctx=_ctx())
        superseded = await retire(
            store.connection,
            uuid=old.uuid,
            version=old.version,
            superseded_by=new.uuid,
            ctx=_ctx(),
        )
        await fetch(store.connection, uuids=[old.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                store.connection,
                uuid=old.uuid,
                version=superseded.version,
                superseded_by=None,
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.INACTIVE_ROW
        assert excinfo.value.data["state"] == RowState.SUPERSEDED


async def test_invariant_9_no_uuid_ever_reports_inactive_row_state_live(tmp_path: Path) -> None:
    """`RowState.LIVE` is excluded from `INACTIVE_ROW_STATES` by construction (`errors.py`); this
    confirms the exclusion holds end to end through every raise site this module actually uses."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        retired = await retire(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=retired.version,
                rewrite=Rewrite(gist="x", content="x"),
                ctx=_ctx(),
            )
        assert excinfo.value.data["state"] != RowState.LIVE


# ---------------------------------------------------------------------------
# Invariant 10: events commit with their mutation — success and rejection alike
# ---------------------------------------------------------------------------


async def test_invariant_10_fetch_emits_one_event_per_distinct_uuid(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid, "unknown", created.uuid], ctx=_ctx())
        kinds = await _event_kinds(store)
        assert kinds == ["fetch", "fetch"]


async def test_invariant_10_retire_emits_its_event_in_the_same_call_as_the_mutation(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        await fetch(store.connection, uuids=[b.uuid], ctx=_ctx())
        retired = await retire(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=b.uuid,
            ctx=_ctx(),
        )
        retire_events = await _event_rows_of_kind(store, memory_uuid=created.uuid, kind="retire")
        assert retire_events == [
            {
                "from_version": created.version,
                "to_version": retired.version,
                "superseded_by": b.uuid,
            }
        ]


async def test_invariant_10_a_version_conflict_commits_its_event_and_receipt_despite_raising(
    tmp_path: Path,
) -> None:
    """The carve-out: "a rejected call commits no domain mutation but does commit its audit
    events and, for a version conflict, the receipt for the record it returned"."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )
        with pytest.raises(ZikaronError):
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="stale", content="stale"),
                ctx=_ctx(session_id="stale-caller"),
            )
        kinds = await _event_kinds(store, created.uuid)
        assert "version_conflict" in kinds
        rows = await store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ? AND session_id = ?",
            (created.uuid, "stale-caller"),
        )
        assert [str(r[0]) for r in rows] == ["conflict"]

        # The row's own content is untouched by the rejected call.
        records, _missing = await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        (fetched,) = records
        assert fetched.gist == "g2"


async def test_invariant_10_a_no_receipt_rejection_commits_its_event_despite_raising(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        with pytest.raises(ZikaronError):
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="g2", content="c2"),
                ctx=_ctx(),
            )
        kinds = await _event_kinds(store, created.uuid)
        assert "no_receipt" in kinds
        # A no_receipt rejection mints no receipt of its own.
        assert await _receipt_count(store, created.uuid) == 0


async def test_invariant_10_a_not_found_rejection_commits_no_event_at_all(
    tmp_path: Path,
) -> None:
    """`not_found` carries no documented minting/logging obligation in `architecture.md` §Errors
    (unlike `version_conflict`/`no_read_receipt`), so a rejected `amend` of an unknown uuid must
    leave the event log untouched."""
    async with await _open_store(tmp_path) as store:
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid="does-not-exist",
                version=1,
                rewrite=Rewrite(gist="g", content="c"),
                ctx=_ctx(),
            )
        assert excinfo.value.code is ErrorCode.NOT_FOUND
        kinds = await _event_kinds(store)
        assert kinds == []


async def test_invariant_10_a_bad_supersession_rejection_commits_no_event_at_all(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        with pytest.raises(ZikaronError):
            await retire(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                superseded_by=created.uuid,
                ctx=_ctx(),
            )
        kinds = await _event_kinds(store, created.uuid)
        assert "fetch" in kinds
        assert "retire" not in kinds
        assert "version_conflict" not in kinds
        assert "no_receipt" not in kinds


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


async def test_determinism_resolving_the_same_chain_twice_gives_the_same_answer(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        c = await create(store.connection, gist="c", content="c", session_id="s1")
        b = await create(store.connection, gist="b", content="b", session_id="s1")
        a = await create(store.connection, gist="a", content="a", session_id="s1")
        await fetch(store.connection, uuids=[b.uuid], ctx=_ctx())
        await retire(
            store.connection, uuid=b.uuid, version=b.version, superseded_by=c.uuid, ctx=_ctx()
        )
        await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        await retire(
            store.connection, uuid=a.uuid, version=a.version, superseded_by=b.uuid, ctx=_ctx()
        )

        first, _ = await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        second, _ = await fetch(store.connection, uuids=[a.uuid], ctx=_ctx())
        assert first[0].superseded_by_latest == second[0].superseded_by_latest
        assert first[0].superseded_by_latest_state == second[0].superseded_by_latest_state


# ---------------------------------------------------------------------------
# Transaction composability: the wire-facing verbs open their own transaction, but the
# `<verb>_within_transaction` cores must compose into a wider transaction a caller already owns.
# ---------------------------------------------------------------------------


async def test_the_public_verb_raises_on_a_nested_begin(tmp_path: Path) -> None:
    """The negative control for the composability tests below: calling the transaction-owning
    wrapper from inside an already-open transaction must fail exactly as `create`'s own
    docstring says, proving the distinction between the wrapper and the neutral core is real
    rather than only nominal."""
    async with await _open_store(tmp_path) as store:
        await store.connection.execute("BEGIN")
        with pytest.raises(sqlite3.OperationalError, match="cannot start a transaction"):
            await create(store.connection, gist="g", content="c", session_id="s1")
        await store.connection.rollback()


async def test_create_within_transaction_composes_with_a_sentinel_write_in_one_commit(
    tmp_path: Path,
) -> None:
    """A composing caller opens one transaction, calls the neutral core, does its own
    further write, and commits once — proving the neutral form does not itself open or close a
    transaction and so does not conflict with an outer owner."""
    async with await _open_store(tmp_path) as store:
        await store.connection.execute("BEGIN")
        created = await create_within_transaction(
            store.connection, gist="g", content="c", session_id="s1"
        )
        # A stand-in for a composing caller's further write inside the same transaction (a chunk
        # row, here represented by a second ordinary statement against a table this layer owns).
        await store.connection.execute(
            "UPDATE memory SET token_count = 99 WHERE uuid = ?", (created.uuid,)
        )
        await store.connection.commit()

        rows = await store.connection.execute_fetchall(
            "SELECT token_count FROM memory WHERE uuid = ?", (created.uuid,)
        )
        assert next(iter(rows))[0] == 99


async def test_a_failure_after_the_neutral_core_rolls_back_both_writes_together(
    tmp_path: Path,
) -> None:
    """The composition acceptance test: a row operation plus a sentinel downstream write, with a
    failure injected before the outer commit. Neither write must survive — proving the two are
    genuinely one atomic unit under the composing caller's transaction, not two transactions that
    merely happened not to conflict."""
    async with await _open_store(tmp_path) as store:
        await store.connection.execute("BEGIN")
        created = await create_within_transaction(
            store.connection, gist="g", content="c", session_id="s1"
        )
        with pytest.raises(sqlite3.IntegrityError):
            # The sentinel downstream write: a deliberately illegal statement standing in for a
            # failed chunking step, inside the same transaction the row write just joined.
            await store.connection.execute(
                "UPDATE memory SET tier = 'not_a_real_tier' WHERE uuid = ?", (created.uuid,)
            )
        await store.connection.rollback()

        rows = await store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM memory WHERE uuid = ?", (created.uuid,)
        )
        assert int(next(iter(rows))[0]) == 0


async def test_amend_within_transaction_composes_with_a_sentinel_write_in_one_commit(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())

        await store.connection.execute("BEGIN")
        _, amended = await amend_within_transaction(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )
        await store.connection.execute(
            "UPDATE memory SET token_count = 42 WHERE uuid = ?", (created.uuid,)
        )
        await store.connection.commit()

        rows = await store.connection.execute_fetchall(
            "SELECT version, token_count FROM memory WHERE uuid = ?", (created.uuid,)
        )
        (version, token_count) = next(iter(rows))
        assert version == amended.version
        assert token_count == 42


async def test_retire_within_transaction_composes_with_a_sentinel_write_in_one_commit(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())

        await store.connection.execute("BEGIN")
        retired = await retire_within_transaction(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            superseded_by=None,
            ctx=_ctx(),
        )
        await store.connection.execute(
            "UPDATE memory SET token_count = 7 WHERE uuid = ?", (created.uuid,)
        )
        await store.connection.commit()

        rows = await store.connection.execute_fetchall(
            "SELECT active, token_count FROM memory WHERE uuid = ?", (created.uuid,)
        )
        (active, token_count) = next(iter(rows))
        assert bool(active) is False
        assert retired.active is False
        assert token_count == 7


async def test_a_rejection_inside_a_composed_amend_commits_only_the_audit_receipt(
    tmp_path: Path,
) -> None:
    """Invariant 10's carve-out holds under composition too, as long as the composing caller
    itself decides commit-vs-rollback the same way the wrapper does (`commit_or_roll_back`)
    rather than always rolling back — the neutral core itself commits nothing (see
    `_reject_version_conflict`'s own docstring), so an outer caller that used a bare
    `except: rollback()` would lose the carve-out under composition, which is exactly the shape
    of hole this design closes by moving the decision to the transaction owner."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )

        await store.connection.execute("BEGIN")
        error: BaseException | None = None
        try:
            with pytest.raises(ZikaronError) as excinfo:
                await amend_within_transaction(
                    store.connection,
                    uuid=created.uuid,
                    version=created.version,
                    rewrite=Rewrite(gist="stale", content="stale"),
                    ctx=_ctx(session_id="stale-caller"),
                )
            error = excinfo.value
        finally:
            await commit_or_roll_back(store.connection, error)
        assert excinfo.value.code is ErrorCode.VERSION_CONFLICT

        rows = await store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ? AND session_id = ?",
            (created.uuid, "stale-caller"),
        )
        assert [str(r[0]) for r in rows] == ["conflict"]


async def test_a_sentinel_write_staged_before_a_composed_rejection_is_not_accidentally_committed(
    tmp_path: Path,
) -> None:
    """The hole: a composing caller that writes
    something of its own *before* calling into the authorization ladder, and then hits a
    version conflict, must not have that earlier write durably committed alongside the
    rejection's own receipt and event. Proven by using a bare `except: rollback()` — the wrong
    policy for a composing caller to use, on purpose — which is what a caller unaware of
    `commit_or_roll_back`'s contract might reach for; because the neutral core itself never
    commits (this is the actual fix, not a favorable choice of caller policy), even that wrong
    policy loses the sentinel correctly, since there is nothing already committed for it to
    fail to undo."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )

        await store.connection.execute("BEGIN")
        try:
            # The sentinel: a composing caller's own write, staged before it ever reaches the
            # authorization ladder: the ordering that makes committing a rejection unsafe.
            await store.connection.execute(
                "UPDATE memory SET token_count = 123 WHERE uuid = ?", (created.uuid,)
            )
            with pytest.raises(ZikaronError) as excinfo:
                await amend_within_transaction(
                    store.connection,
                    uuid=created.uuid,
                    version=created.version,
                    rewrite=Rewrite(gist="stale", content="stale"),
                    ctx=_ctx(session_id="stale-caller"),
                )
            assert excinfo.value.code is ErrorCode.VERSION_CONFLICT
        finally:
            await store.connection.rollback()

        rows = await store.connection.execute_fetchall(
            "SELECT token_count FROM memory WHERE uuid = ?", (created.uuid,)
        )
        assert next(iter(rows))[0] == 0
        # The rejection's own receipt is lost too under this policy — the price of a composing
        # caller using the wrong one, and exactly what motivates `commit_or_roll_back` existing
        # as the one place that gets to decide correctly, per the previous test.
        receipt_rows = await store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ? AND session_id = ?",
            (created.uuid, "stale-caller"),
        )
        assert list(receipt_rows) == []


# ---------------------------------------------------------------------------
# Invariant 10, proven by failure injection: co-occurrence after a successful call is not proof
# of atomicity on its own, since it would look identical if the coupled writes were separately
# committed. These inject a real failure between the coupled writes and confirm that *none* of
# them survive — the transaction genuinely rolls back as one unit rather than several.
# ---------------------------------------------------------------------------


async def test_invariant_10_a_failure_between_retires_row_write_and_its_event_loses_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lets `retire`'s row `UPDATE` itself actually run, then fails the very next `execute` —
    the own-write receipt mint inside `_bump_version_and_mint_own_write` — and confirms the row,
    its version, its receipt set and the event log are all left exactly as they were before the
    call. A row `UPDATE` that ran and then rolled back is the specific case co-occurrence checks
    cannot distinguish from one that never ran at all."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())

        real_execute = store.connection.__class__.execute
        seen_the_row_update = False
        failure_fired = False

        async def _execute_then_fail_right_after_the_update(
            self: object, sql: str, parameters: object = None
        ) -> object:
            nonlocal seen_the_row_update, failure_fired
            normalized = sql.strip().upper()
            if seen_the_row_update and not failure_fired:
                failure_fired = True
                raise RuntimeError("simulated failure right after retire's row UPDATE")
            if normalized.startswith("UPDATE MEMORY SET ACTIVE"):
                seen_the_row_update = True
            return await real_execute(self, sql, parameters)

        monkeypatch.setattr(
            store.connection.__class__, "execute", _execute_then_fail_right_after_the_update
        )
        with pytest.raises(RuntimeError, match="simulated failure"):
            await retire(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                superseded_by=None,
                ctx=_ctx(),
            )
        monkeypatch.undo()
        assert seen_the_row_update, "the row UPDATE never ran, so this test proved nothing"
        assert failure_fired, "the injected failure never fired, so this test proved nothing"

        # The row is untouched: still active, still at its original version — despite the row
        # UPDATE itself having actually executed inside the now-rolled-back transaction.
        rows = await store.connection.execute_fetchall(
            "SELECT active, version FROM memory WHERE uuid = ?", (created.uuid,)
        )
        (active, version) = next(iter(rows))
        assert bool(active) is True
        assert version == created.version
        # No event of any kind survived the rollback — not merely "no retire event", which
        # would miss a stray event of some other kind slipping through uncommitted.
        kinds = await _event_kinds(store, created.uuid)
        assert kinds == ["fetch"]
        assert await _receipt_count(store, created.uuid) == 1  # only the earlier `fetch` receipt
        receipt_rows = await store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ?", (created.uuid,)
        )
        assert [str(r[0]) for r in receipt_rows] == ["fetch"]


async def test_invariant_10_a_failure_between_fetchs_receipt_and_its_event_loses_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails the statement immediately after `fetch` mints its receipt for a found row — the
    event-log `INSERT` that would otherwise follow it — and confirms neither the receipt nor any
    partial event survives."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")

        real_execute = store.connection.__class__.execute

        async def _execute_then_fail_on_event_insert(
            self: object, sql: str, parameters: object = None
        ) -> object:
            if sql.strip().upper().startswith("INSERT INTO EVENT"):
                raise RuntimeError("simulated failure right after fetch's receipt mint")
            return await real_execute(self, sql, parameters)

        monkeypatch.setattr(
            store.connection.__class__, "execute", _execute_then_fail_on_event_insert
        )
        with pytest.raises(RuntimeError, match="simulated failure"):
            await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        monkeypatch.undo()

        assert await _receipt_count(store, created.uuid) == 0
        kinds = await _event_kinds(store, created.uuid)
        assert kinds == []


async def test_invariant_10_a_version_conflict_is_committed_by_the_transaction_owner(
    tmp_path: Path,
) -> None:
    """`amend`'s own `finally: await commit_or_roll_back(db, error)` runs unconditionally, and
    for a `VERSION_CONFLICT` — one of `commit_or_roll_back`'s two carve-out codes — that means
    committing, not rolling back: `_reject_version_conflict` itself only staged the receipt and
    event and raised, never touching the transaction, so `amend`'s own `finally` block is the
    one place that actually commits them. This test proves that end to end through the real
    public `amend` wrapper, and also checks the connection is left fully usable afterward."""
    async with await _open_store(tmp_path) as store:
        created = await create(store.connection, gist="g", content="c", session_id="s1")
        await fetch(store.connection, uuids=[created.uuid], ctx=_ctx())
        await amend(
            store.connection,
            uuid=created.uuid,
            version=created.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            ctx=_ctx(),
        )

        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                store.connection,
                uuid=created.uuid,
                version=created.version,
                rewrite=Rewrite(gist="stale", content="stale"),
                ctx=_ctx(session_id="stale-caller"),
            )
        assert excinfo.value.code is ErrorCode.VERSION_CONFLICT

        # The conflict's receipt and event survived amend's own finally block, because that
        # block committed them — not because there was nothing left for a rollback to undo.
        kinds = await _event_kinds(store, created.uuid)
        assert "version_conflict" in kinds
        rows = await store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ? AND session_id = ?",
            (created.uuid, "stale-caller"),
        )
        assert [str(r[0]) for r in rows] == ["conflict"]

        # And the connection itself is still fully usable — proof the commit left it in a clean
        # state, ready for the very retry the conflict receipt exists to license.
        conflict_record = cast(ConflictRecord, excinfo.value.data["current"])
        healthy = await amend(
            store.connection,
            uuid=created.uuid,
            version=conflict_record.version,
            rewrite=Rewrite(gist="recovered", content="recovered"),
            ctx=_ctx(session_id="stale-caller"),
        )
        assert healthy.gist == "recovered"


async def test_a_per_call_kind_may_not_name_a_memory(tmp_path: Path) -> None:
    """`EVENT_SPECS[kind].names_memory` is a contract about the *column*, not only about the detail.

    A per-call kind that named a memory, or a per-memory kind that named none, would leave the
    signals joining on a column whose meaning changed with the writer — so the disagreement is
    refused where the row is written rather than left for a query to average over.

    This is the only shape mismatch still reachable from a call site: the detail carries its own
    kind and its own field types, so filing a payload under the wrong kind, or giving a field the
    wrong name or type, no longer type-checks.
    """
    async with await _open_store(tmp_path) as store:
        with pytest.raises(ValueError, match="names_memory=False"):
            await log_event(
                store.connection,
                ctx=_ctx(),
                detail=SearchDetail(
                    query_chars=1,
                    limit=5,
                    fusion_depth=50,
                    arms=ArmTermination(
                        dense_depth_reached=0,
                        dense_stop_reason=StopReason.INDEX_EXHAUSTED,
                        lexical_depth_reached=0,
                        lexical_stop_reason=StopReason.INDEX_EXHAUSTED,
                    ),
                    query=QueryShape(query_tokens=1, query_truncated=False, lexical_skipped=False),
                    include_retired=False,
                    n_returned=0,
                    uuids=(),
                ),
                memory_uuid="not-mine",
            )


async def test_a_per_memory_kind_must_name_one(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        with pytest.raises(ValueError, match="names_memory=True"):
            await log_event(
                store.connection,
                ctx=_ctx(),
                detail=FetchDetail(version=1, found=True),
                memory_uuid=None,
            )
