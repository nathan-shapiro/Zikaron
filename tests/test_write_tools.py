"""The tool-facing write verbs: `write.tools.remember` / `amend` / `retire`.

Default tier, unmarked: a real store on `tmp_path` with a deterministic `FakeEncoder`
(`coding-standards.md` §4). `Harness` supplies the store and config; a `WriteCall` is built
directly here rather than through `Harness`, since dedup policy is this layer's own addition and
not something the shared retrieval fixture has any reason to carry.
"""

import unittest.mock
from collections.abc import Sequence
from pathlib import Path

import aiosqlite
import pytest

from tests.retrieval_fixtures import Harness, ctx, harness
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.indexing.writes import IndexingContext
from zikaron.core.records import memory as records
from zikaron.core.records.memory import CallParams, ConflictRecord, Rewrite
from zikaron.core.write import dedup
from zikaron.core.write.tools import (
    Amended,
    Conflict,
    Remembered,
    Retired,
    WriteCall,
    amend,
    remember,
    retire,
)

_GIST = "protobuf codegen fails silently on staging"
_CONTENT = "the proto compiler version drifts from the one pinned in requirements.txt"
_GIST_NEAR_DUPLICATE = "protobuf codegen fails silently on staging too"
_CONTENT_NEAR_DUPLICATE = _CONTENT + " as well"


def _write_call(
    h: Harness,
    *,
    call_ctx: CallParams | None = None,
    dedup_threshold: float = 0.0,
    dedup_max: int = 3,
) -> WriteCall:
    index = IndexingContext.for_store(h.store, h.config, h.encoder)
    return WriteCall(
        ctx=call_ctx if call_ctx is not None else ctx(),
        index=index,
        retrieval=h.read_call().settings,
        dedup_threshold=dedup_threshold,
        dedup_max=dedup_max,
    )


# ---------------------------------------------------------------------------
# WriteCall's own bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dedup_threshold", [-0.01, 1.01])
async def test_write_call_rejects_a_dedup_threshold_outside_zero_one(
    tmp_path: Path, dedup_threshold: float
) -> None:
    """`schema.md` §"Configuration keys": `dedup_threshold` ranges `[0, 1]`, checked at
    construction so a caller cannot reach `dedup.offer` with a value outside it."""
    async with harness(tmp_path) as h:
        with pytest.raises(ValueError, match="dedup_threshold"):
            _write_call(h, dedup_threshold=dedup_threshold)


@pytest.mark.parametrize("dedup_max", [-1, 21])
async def test_write_call_rejects_a_dedup_max_outside_zero_twenty(
    tmp_path: Path, dedup_max: int
) -> None:
    """`schema.md` §"Configuration keys": `dedup_max` ranges `0`-`20`."""
    async with harness(tmp_path) as h:
        with pytest.raises(ValueError, match="dedup_max"):
            _write_call(h, dedup_max=dedup_max)


# ---------------------------------------------------------------------------
# remember: writes unconditionally, dedup never blocks
# ---------------------------------------------------------------------------


async def test_remember_with_no_candidates_reports_no_near_duplicates(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        outcome = await remember(
            h.store.connection,
            rewrite=Rewrite(gist=_GIST, content=_CONTENT),
            call=_write_call(h),
        )
        assert isinstance(outcome, Remembered)
        assert outcome.near_duplicates == ()
        assert outcome.version == 1


async def test_remember_writes_the_row_even_when_a_near_duplicate_exists(tmp_path: Path) -> None:
    """D32's never-lose guarantee, exercised at this layer: `remember` never refuses a write on a
    dedup match, however high the directed cosine. The row is live regardless, and the hand-back is
    advisory only."""
    async with harness(tmp_path) as h:
        call = _write_call(h, dedup_threshold=0.0, dedup_max=3)
        first = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        second = await remember(
            h.store.connection,
            rewrite=Rewrite(gist=_GIST_NEAR_DUPLICATE, content=_CONTENT_NEAR_DUPLICATE),
            call=call,
        )
        assert second.uuid != first.uuid
        assert second.version == 1
        assert [candidate.uuid for candidate in second.near_duplicates] == [first.uuid]

        rows = await h.store.connection.execute_fetchall(
            "SELECT active FROM memory WHERE uuid IN (?, ?)", (first.uuid, second.uuid)
        )
        assert [int(row[0]) for row in rows] == [1, 1]


async def test_remember_respects_dedup_max_and_dedup_threshold(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        loose = _write_call(h, dedup_threshold=0.0, dedup_max=3)
        strict = _write_call(h, dedup_threshold=0.999, dedup_max=3)
        await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=loose
        )
        no_offer = await remember(
            h.store.connection,
            rewrite=Rewrite(gist=_GIST_NEAR_DUPLICATE, content=_CONTENT_NEAR_DUPLICATE),
            call=strict,
        )
        assert no_offer.near_duplicates == ()


async def test_remember_rejects_a_gist_over_the_bound_before_any_write(tmp_path: Path) -> None:
    """`gist_max_tokens` is the one bound `zikaron_memory_remember` rejects an agent write for, and
    the rejection happens before anything is written — `FakeEncoder` counts whitespace-delimited
    tokens, so a gist of 65 space-separated words is unambiguously over the default 64."""
    async with harness(tmp_path) as h:
        over_budget_gist = " ".join(f"word{i}" for i in range(65))
        with pytest.raises(ZikaronError) as excinfo:
            await remember(
                h.store.connection,
                rewrite=Rewrite(gist=over_budget_gist, content=_CONTENT),
                call=_write_call(h),
            )
        assert excinfo.value.code is ErrorCode.BOUNDS
        rows = await h.store.connection.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(rows))[0]) == 0


async def test_remember_rejects_empty_content_before_any_write(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        with pytest.raises(ZikaronError) as excinfo:
            await remember(
                h.store.connection, rewrite=Rewrite(gist=_GIST, content=""), call=_write_call(h)
            )
        assert excinfo.value.code is ErrorCode.BOUNDS
        rows = await h.store.connection.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(rows))[0]) == 0


async def test_a_failure_during_dedup_search_leaves_no_trace_of_the_remember(
    tmp_path: Path,
) -> None:
    """Invariant 2/10 re-asserted for `remember`: the dedup search runs *inside* the same
    transaction as the write it reports on, so a failure there rolls back the row, its indexes and
    its own-write receipt — `remember` has no rejection carve-out, since a fresh row has no prior
    state for invariant 10's carve-out to preserve."""
    async with harness(tmp_path) as h:
        call = _write_call(h)
        with (
            unittest.mock.patch.object(
                dedup, "offer", side_effect=RuntimeError("killed mid-write")
            ),
            pytest.raises(RuntimeError, match="killed mid-write"),
        ):
            await remember(
                h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
            )
        for table in ("memory", "memory_chunk", "memory_vec", "event", "read_receipt"):
            rows = await h.store.connection.execute_fetchall(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            assert int(next(iter(rows))[0]) == 0, f"{table} kept a row from a rolled-back write"


async def test_remember_emits_dedup_offered_once_per_candidate_and_a_single_remember_event(
    tmp_path: Path,
) -> None:
    async with harness(tmp_path) as h:
        call = _write_call(h, dedup_threshold=0.0, dedup_max=3)
        first = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        await h.clear_events()
        second = await remember(
            h.store.connection,
            rewrite=Rewrite(gist=_GIST_NEAR_DUPLICATE, content=_CONTENT_NEAR_DUPLICATE),
            call=call,
        )
        events = await h.events()
        kinds = [kind for kind, _uuid, _detail in events]
        assert kinds.count("remember") == 1
        assert kinds.count("dedup_offered") == 1
        dedup_events = [(uuid, detail) for kind, uuid, detail in events if kind == "dedup_offered"]
        (uuid, detail) = dedup_events[0]
        assert uuid == first.uuid
        assert detail["created_uuid"] == second.uuid


# ---------------------------------------------------------------------------
# amend: full rewrite, or a conflict in one round trip
# ---------------------------------------------------------------------------


async def test_amend_rewrites_the_row_and_bumps_the_version(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        outcome = await amend(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            rewrite=Rewrite(gist="fixed: pin the proto compiler", content="pinned in ci.yaml"),
            call=_write_call(h),
        )
        assert isinstance(outcome, Amended)
        assert outcome.version == written.version + 1

        rows = await h.store.connection.execute_fetchall(
            "SELECT gist, content FROM memory WHERE uuid = ?", (written.uuid,)
        )
        gist, content = next(iter(rows))
        assert str(gist) == "fixed: pin the proto compiler"
        assert str(content) == "pinned in ci.yaml"


async def test_amend_on_a_stale_version_returns_a_conflict_with_the_full_current_record(
    tmp_path: Path,
) -> None:
    """`architecture.md`'s promise: "a conflict returns the full record and its receipt in one
    round trip" — checked here by re-amending with what the conflict handed back, with no second
    `fetch` call in between."""
    async with harness(tmp_path) as h:
        call = _write_call(h)
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        # A second session amends first, moving the version the first session still holds.
        # Fetching earns the receipt `amend` requires; a session that never touched this uuid
        # has none, whatever version it presents.
        s2 = _write_call(h, call_ctx=ctx(session_id="s2"))
        await records.fetch(h.store.connection, uuids=[written.uuid], ctx=s2.ctx)
        await amend(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            call=s2,
        )

        outcome = await amend(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            rewrite=Rewrite(gist="stale rewrite", content="stale rewrite"),
            call=call,
        )
        assert isinstance(outcome, Conflict)
        assert isinstance(outcome.current, ConflictRecord)
        assert outcome.current.uuid == written.uuid
        assert outcome.current.gist == "g2"
        assert outcome.current.version == written.version + 1

        # The round trip: re-amend at exactly the version the conflict just handed back, with no
        # intervening fetch call — the receipt the conflict minted is what licenses this.
        retried = await amend(
            h.store.connection,
            uuid=written.uuid,
            version=outcome.current.version,
            rewrite=Rewrite(gist="g3", content="c3"),
            call=call,
        )
        assert isinstance(retried, Amended)
        assert retried.version == outcome.current.version + 1


async def test_amend_on_an_unknown_uuid_raises_not_found_rather_than_returning_a_conflict(
    tmp_path: Path,
) -> None:
    """`not_found` has no second response shape — only `version_conflict` is translated."""
    async with harness(tmp_path) as h:
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                h.store.connection,
                uuid="00000000-0000-0000-0000-000000000000",
                version=1,
                rewrite=Rewrite(gist=_GIST, content=_CONTENT),
                call=_write_call(h),
            )
        assert excinfo.value.code is ErrorCode.NOT_FOUND


async def test_amend_without_a_receipt_raises_no_read_receipt(tmp_path: Path) -> None:
    """A caller that never fetched or wrote the row gets `no_read_receipt`, not a conflict — the
    version it presented is correct, so there is nothing stale to hand back."""
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                h.store.connection,
                uuid=written.uuid,
                version=written.version,
                rewrite=Rewrite(gist="g2", content="c2"),
                call=_write_call(h, call_ctx=ctx(session_id="never-fetched")),
            )
        assert excinfo.value.code is ErrorCode.NO_READ_RECEIPT


# ---------------------------------------------------------------------------
# retire: soft only, or a conflict in one round trip
# ---------------------------------------------------------------------------


async def test_retire_outright_deactivates_the_row(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        outcome = await retire(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            superseded_by=None,
            call=_write_call(h),
        )
        assert isinstance(outcome, Retired)
        assert outcome.version == written.version + 1
        rows = await h.store.connection.execute_fetchall(
            "SELECT active, superseded_by FROM memory WHERE uuid = ?", (written.uuid,)
        )
        active, superseded_by = next(iter(rows))
        assert int(active) == 0
        assert superseded_by is None


async def test_retire_with_superseded_by_stays_retrievable_and_demoted(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        older = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        newer = await remember(
            h.store.connection,
            rewrite=Rewrite(gist=_GIST_NEAR_DUPLICATE, content=_CONTENT_NEAR_DUPLICATE),
            call=_write_call(h),
        )
        outcome = await retire(
            h.store.connection,
            uuid=older.uuid,
            version=older.version,
            superseded_by=newer.uuid,
            call=_write_call(h),
        )
        assert isinstance(outcome, Retired)
        rows = await h.store.connection.execute_fetchall(
            "SELECT active, superseded_by FROM memory WHERE uuid = ?", (older.uuid,)
        )
        active, superseded_by = next(iter(rows))
        assert int(active) == 0
        assert str(superseded_by) == newer.uuid


async def test_retire_on_a_stale_version_returns_a_conflict_with_the_full_current_record(
    tmp_path: Path,
) -> None:
    async with harness(tmp_path) as h:
        call = _write_call(h)
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        s2 = _write_call(h, call_ctx=ctx(session_id="s2"))
        await records.fetch(h.store.connection, uuids=[written.uuid], ctx=s2.ctx)
        await amend(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            call=s2,
        )
        outcome = await retire(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            superseded_by=None,
            call=call,
        )
        assert isinstance(outcome, Conflict)
        assert outcome.current.version == written.version + 1
        assert outcome.current.gist == "g2"

        # Re-decide in one round trip: retire at the version the conflict just handed back.
        retried = await retire(
            h.store.connection,
            uuid=written.uuid,
            version=outcome.current.version,
            superseded_by=None,
            call=call,
        )
        assert isinstance(retried, Retired)


async def test_retire_of_an_already_inactive_row_raises_inactive_row(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        retired = await retire(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            superseded_by=None,
            call=_write_call(h),
        )
        assert isinstance(retired, Retired)
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                h.store.connection,
                uuid=written.uuid,
                version=retired.version,
                superseded_by=None,
                call=_write_call(h),
            )
        assert excinfo.value.code is ErrorCode.INACTIVE_ROW


async def test_retire_with_a_bad_supersession_edge_raises_bad_supersession(tmp_path: Path) -> None:
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                h.store.connection,
                uuid=written.uuid,
                version=written.version,
                superseded_by=written.uuid,
                call=_write_call(h),
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION


# ---------------------------------------------------------------------------
# Every rejection path emits exactly the events the signals need, and no others
# ---------------------------------------------------------------------------


async def test_a_version_conflict_from_amend_commits_exactly_one_event_and_one_receipt(
    tmp_path: Path,
) -> None:
    async with harness(tmp_path) as h:
        call = _write_call(h)
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        s2 = _write_call(h, call_ctx=ctx(session_id="s2"))
        await records.fetch(h.store.connection, uuids=[written.uuid], ctx=s2.ctx)
        await amend(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            call=s2,
        )
        await h.clear_events()
        outcome = await amend(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            rewrite=Rewrite(gist="stale", content="stale"),
            call=call,
        )
        assert isinstance(outcome, Conflict)
        kinds = [kind for kind, _uuid, _detail in await h.events()]
        assert kinds == ["version_conflict"]
        rows = await h.store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ? AND session_id = ? "
            "AND version = ?",
            (written.uuid, call.ctx.session_id, outcome.current.version),
        )
        assert [str(row[0]) for row in rows] == ["conflict"]


async def test_a_version_conflict_from_retire_commits_exactly_one_event_and_one_receipt(
    tmp_path: Path,
) -> None:
    """The identical carve-out, exercised for `retire` rather than `amend`, since the two verbs
    reach `version_conflict` through different row-level entry points
    (`indexing.writes.amend` vs. `records.memory.retire`) and neither test proves the other."""
    async with harness(tmp_path) as h:
        call = _write_call(h)
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=call
        )
        s2 = _write_call(h, call_ctx=ctx(session_id="s2"))
        await records.fetch(h.store.connection, uuids=[written.uuid], ctx=s2.ctx)
        await amend(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            rewrite=Rewrite(gist="g2", content="c2"),
            call=s2,
        )
        await h.clear_events()
        outcome = await retire(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            superseded_by=None,
            call=call,
        )
        assert isinstance(outcome, Conflict)
        kinds = [kind for kind, _uuid, _detail in await h.events()]
        assert kinds == ["version_conflict"]
        rows = await h.store.connection.execute_fetchall(
            "SELECT source FROM read_receipt WHERE memory_uuid = ? AND session_id = ? "
            "AND version = ?",
            (written.uuid, call.ctx.session_id, outcome.current.version),
        )
        assert [str(row[0]) for row in rows] == ["conflict"]


async def test_a_no_receipt_rejection_from_amend_commits_exactly_one_event_and_no_receipt(
    tmp_path: Path,
) -> None:
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        await h.clear_events()
        never_fetched = _write_call(h, call_ctx=ctx(session_id="never-fetched"))
        with pytest.raises(ZikaronError) as excinfo:
            await amend(
                h.store.connection,
                uuid=written.uuid,
                version=written.version,
                rewrite=Rewrite(gist="g2", content="c2"),
                call=never_fetched,
            )
        assert excinfo.value.code is ErrorCode.NO_READ_RECEIPT
        kinds = [kind for kind, _uuid, _detail in await h.events()]
        assert kinds == ["no_receipt"]
        rows = await h.store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM read_receipt WHERE memory_uuid = ? AND session_id = ?",
            (written.uuid, never_fetched.ctx.session_id),
        )
        assert int(next(iter(rows))[0]) == 0


async def test_a_no_receipt_rejection_from_retire_commits_exactly_one_event_and_no_receipt(
    tmp_path: Path,
) -> None:
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        await h.clear_events()
        never_fetched = _write_call(h, call_ctx=ctx(session_id="never-fetched"))
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                h.store.connection,
                uuid=written.uuid,
                version=written.version,
                superseded_by=None,
                call=never_fetched,
            )
        assert excinfo.value.code is ErrorCode.NO_READ_RECEIPT
        kinds = [kind for kind, _uuid, _detail in await h.events()]
        assert kinds == ["no_receipt"]
        rows = await h.store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM read_receipt WHERE memory_uuid = ? AND session_id = ?",
            (written.uuid, never_fetched.ctx.session_id),
        )
        assert int(next(iter(rows))[0]) == 0


@pytest.mark.parametrize("verb", ["amend", "remember"])
async def test_remember_bounds_rejection_commits_no_event_at_all(tmp_path: Path, verb: str) -> None:
    """`bounds` rejects before anything is written — for `remember`, and for the analogous
    over-budget-gist case an `amend` call would hit — so no `event` row of any kind exists to be
    left over, unlike `version_conflict`/`no_receipt`, which are invariant 10's own carve-out."""
    async with harness(tmp_path) as h:
        over_budget_gist = " ".join(f"word{i}" for i in range(65))
        if verb == "amend":
            written = await remember(
                h.store.connection,
                rewrite=Rewrite(gist=_GIST, content=_CONTENT),
                call=_write_call(h),
            )
            await h.clear_events()
            with pytest.raises(ZikaronError) as excinfo:
                await amend(
                    h.store.connection,
                    uuid=written.uuid,
                    version=written.version,
                    rewrite=Rewrite(gist=over_budget_gist, content=_CONTENT),
                    call=_write_call(h),
                )
        else:
            await h.clear_events()
            with pytest.raises(ZikaronError) as excinfo:
                await remember(
                    h.store.connection,
                    rewrite=Rewrite(gist=over_budget_gist, content=_CONTENT),
                    call=_write_call(h),
                )
        assert excinfo.value.code is ErrorCode.BOUNDS
        assert await h.events() == []


@pytest.mark.parametrize("verb", ["amend", "retire"])
async def test_not_found_rejection_commits_no_event_at_all(tmp_path: Path, verb: str) -> None:
    """`not_found` fires at the existence rung, before any receipt or event work runs for either
    verb — no carve-out applies to it."""
    async with harness(tmp_path) as h:
        await h.clear_events()
        missing = "00000000-0000-0000-0000-000000000000"
        call = _write_call(h)

        async def _reject() -> None:
            if verb == "amend":
                await amend(
                    h.store.connection,
                    uuid=missing,
                    version=1,
                    rewrite=Rewrite(gist=_GIST, content=_CONTENT),
                    call=call,
                )
            else:
                await retire(
                    h.store.connection, uuid=missing, version=1, superseded_by=None, call=call
                )

        with pytest.raises(ZikaronError) as excinfo:
            await _reject()
        assert excinfo.value.code is ErrorCode.NOT_FOUND
        assert await h.events() == []


@pytest.mark.parametrize("verb", ["amend", "retire"])
async def test_inactive_row_rejection_commits_no_event_at_all(tmp_path: Path, verb: str) -> None:
    """`inactive_row` fires at the state-legality rung, after version and receipt have both
    already cleared — checked here on a row this same call already holds a fresh receipt for, so
    the rejection is attributable to state alone."""
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        retired = await retire(
            h.store.connection,
            uuid=written.uuid,
            version=written.version,
            superseded_by=None,
            call=_write_call(h),
        )
        assert isinstance(retired, Retired)
        await h.clear_events()
        call = _write_call(h)

        async def _reject() -> None:
            if verb == "amend":
                await amend(
                    h.store.connection,
                    uuid=written.uuid,
                    version=retired.version,
                    rewrite=Rewrite(gist="g2", content="c2"),
                    call=call,
                )
            else:
                await retire(
                    h.store.connection,
                    uuid=written.uuid,
                    version=retired.version,
                    superseded_by=None,
                    call=call,
                )

        with pytest.raises(ZikaronError) as excinfo:
            await _reject()
        assert excinfo.value.code is ErrorCode.INACTIVE_ROW
        assert await h.events() == []


async def test_bad_supersession_rejection_commits_no_event_at_all(tmp_path: Path) -> None:
    """`bad_supersession` is `retire`'s own state-legality rung; `amend` has no equivalent."""
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        await h.clear_events()
        with pytest.raises(ZikaronError) as excinfo:
            await retire(
                h.store.connection,
                uuid=written.uuid,
                version=written.version,
                superseded_by=written.uuid,
                call=_write_call(h),
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert await h.events() == []


async def test_a_locked_store_during_remember_is_store_busy_not_index_failed(
    tmp_path: Path,
) -> None:
    """Invariant 10's cross-cutting re-assertion for `write.tools.remember`'s own transaction
    wrapper: contention is an ordinary, reachable production outcome under real concurrent access,
    not a malformed-state guard, and it must be reported as `store_busy` — retryable — rather than
    collapsed into `index_failed`, which the caller cannot retry. `indexing.writes`'s own
    `_failure_map` is proven correct by M4's own test at this same boundary; this is the identical
    real-lock scenario proven again at `write.tools`'s own newly introduced transaction, since a
    caller reaching `remember`'s `_in_one_transaction`/`_failure_map` never goes through
    `indexing.writes.remember`'s transaction-owning wrapper at all — it composes the neutral
    `remember_within_transaction` core directly, so M4's test does not exercise this layer's own
    mapping.

    A second connection holds a write transaction while this one tries to open its own, with the
    waiting connection's `busy_timeout` lowered so the test does not sit out the real five seconds.
    """
    async with harness(tmp_path) as h:
        await h.store.connection.execute("PRAGMA busy_timeout = 50")
        async with aiosqlite.connect(h.store.path) as holder:
            await holder.execute("BEGIN IMMEDIATE")
            await holder.execute(
                "INSERT INTO meta (key, value) VALUES ('probe', 'holding the write lock')"
            )
            with pytest.raises(ZikaronError) as excinfo:
                await remember(
                    h.store.connection,
                    rewrite=Rewrite(gist=_GIST, content=_CONTENT),
                    call=_write_call(h),
                )
        assert excinfo.value.code is ErrorCode.STORE_BUSY
        assert excinfo.value.data == {"verb": "remember"}
        rows = await h.store.connection.execute_fetchall("SELECT COUNT(*) FROM memory")
        assert int(next(iter(rows))[0]) == 0
        assert await h.events() == []


# ---------------------------------------------------------------------------
# Invariant 2/10 re-asserted for amend and retire: a mid-write failure leaves nothing behind
# ---------------------------------------------------------------------------


async def _matches_term(h: Harness, uuid: str, term: str) -> bool:
    """Whether `uuid`'s row is findable through `memory_fts` on the exact term `term`, mirroring
    `test_indexing_writes.py`'s own `_fts_uuids` — a `MATCH` query, not a plain column read.
    `memory_fts` is external-content (`content='memory'`), so selecting `f.gist`/`f.content`
    directly re-reads the **current** row through the join rather than revealing which terms the
    inverted index itself still holds; only a `MATCH` proves that."""
    quoted = '"' + term.replace('"', '""') + '"'
    rows = await h.store.connection.execute_fetchall(
        "SELECT 1 FROM memory_fts f JOIN memory m ON m.rowid = f.rowid "
        "WHERE memory_fts MATCH ? AND m.uuid = ?",
        (quoted, uuid),
    )
    return len(list(rows)) > 0


async def _full_snapshot(h: Harness, uuid: str, *, fts_terms: Sequence[str]) -> dict[str, object]:
    """Every piece of state one write can touch for `uuid`, so a rollback test can compare the
    whole thing before and after rather than the two or three columns its own name happens to
    mention — the same discipline `retrieval_fixtures.Harness.events` uses for the event log,
    applied to every table a write can reach.

    Args:
        fts_terms: every term a rollback test's own fixture cares about — its own current terms,
            whose matchability must survive, and the attempted rewrite's terms, which must not
            newly match. `_matches_term`'s `MATCH` query is what proves the *index* rather than the
            content-table row the external-content join would otherwise re-read.
    """
    row = await h.store.connection.execute_fetchall("SELECT * FROM memory WHERE uuid = ?", (uuid,))
    chunks = await h.store.connection.execute_fetchall(
        "SELECT * FROM memory_chunk WHERE memory_uuid = ? ORDER BY part_index", (uuid,)
    )
    vector_ids = [int(c[0]) for c in chunks]
    vectors = []
    for chunk_id in vector_ids:
        rows = await h.store.connection.execute_fetchall(
            "SELECT embedding FROM memory_vec WHERE rowid = ?", (chunk_id,)
        )
        vectors.append(bytes(next(iter(rows))[0]) if rows else None)
    fts_matches = {term: await _matches_term(h, uuid, term) for term in fts_terms}
    receipts = await h.store.connection.execute_fetchall(
        "SELECT session_id, client_kind, version, source FROM read_receipt "
        "WHERE memory_uuid = ? ORDER BY session_id, client_kind, version",
        (uuid,),
    )
    return {
        "row": [tuple(r) for r in row],
        "chunks": [tuple(c) for c in chunks],
        "vectors": vectors,
        "fts_matches": fts_matches,
        "receipts": [tuple(r) for r in receipts],
        "events": await h.events(),
    }


async def test_a_failure_during_amends_index_replacement_leaves_the_old_row_and_index_intact(
    tmp_path: Path,
) -> None:
    """By the time `_write_index` runs, `amend`'s authorization has already passed and the old
    lexical postings and chunks have already been removed — the sharpest point invariant 2 can be
    tested at for this verb. Every table a write touches — the row, its chunks, its vectors, its
    FTS postings, its receipts and the event log — must all read exactly as they did before the
    call, not only the two or three columns most likely to change. Old and new prose use disjoint
    marker terms, so `_matches_term`'s `MATCH` query on each proves the *inverted index* — old
    terms still findable, new terms not newly findable — rather than the content-table row an
    external-content join would otherwise re-read regardless of what the index actually holds."""
    old_term = "oldmarkerterm"
    new_term = "newmarkerterm"
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection,
            rewrite=Rewrite(gist=f"gist with {old_term}", content=f"content with {old_term}"),
            call=_write_call(h),
        )
        before = await _full_snapshot(h, written.uuid, fts_terms=(old_term, new_term))
        with (
            unittest.mock.patch(
                "zikaron.core.indexing.writes._write_index",
                side_effect=RuntimeError("killed mid-write"),
            ),
            pytest.raises(RuntimeError, match="killed mid-write"),
        ):
            await amend(
                h.store.connection,
                uuid=written.uuid,
                version=written.version,
                rewrite=Rewrite(gist=f"gist with {new_term}", content=f"content with {new_term}"),
                call=_write_call(h),
            )
        after = await _full_snapshot(h, written.uuid, fts_terms=(old_term, new_term))
        assert after == before
        assert before["fts_matches"] == {old_term: True, new_term: False}


async def test_a_failure_during_retires_own_event_write_leaves_the_row_unretired(
    tmp_path: Path,
) -> None:
    """`retire`'s own `retire` event is its last statement (`records.memory.retire_within_
    transaction`'s own ordering), so failing there is the sharpest point to prove invariant 2 for
    this verb. `retire` touches no index (`indexing.writes`'s own "two verbs, not three"), so the
    full snapshot's chunk/vector/FTS fields are expected to be identical before and after on their
    own terms — what this test adds over the narrower row-only check is the receipt set and the
    exact event list, neither of which a three-column comparison would catch drifting."""
    async with harness(tmp_path) as h:
        written = await remember(
            h.store.connection, rewrite=Rewrite(gist=_GIST, content=_CONTENT), call=_write_call(h)
        )
        before = await _full_snapshot(h, written.uuid, fts_terms=("proto",))
        real_log_event = records.log_event

        async def _fail_on_retire(db: object, **kwargs: object) -> None:
            detail = kwargs.get("detail")
            if type(detail).__name__ == "RetireDetail":
                raise RuntimeError("killed mid-write")
            await real_log_event(db, **kwargs)  # type: ignore[arg-type]

        with (
            unittest.mock.patch.object(records, "log_event", side_effect=_fail_on_retire),
            pytest.raises(RuntimeError, match="killed mid-write"),
        ):
            await retire(
                h.store.connection,
                uuid=written.uuid,
                version=written.version,
                superseded_by=None,
                call=_write_call(h),
            )
        after = await _full_snapshot(h, written.uuid, fts_terms=("proto",))
        assert after == before
