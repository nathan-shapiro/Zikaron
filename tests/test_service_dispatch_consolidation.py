"""`zikaron.service.dispatch_consolidation` — `plan_groups`, `next_group`, and the three
consolidator write verbs, against a real store."""

from pathlib import Path

import pytest

from tests.fake_encoder import FakeEncoder, unit_at
from tests.service_fixtures import envelope, open_context
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.events import ClientKind
from zikaron.core.indexing.chunking import PREFIX_SEPARATOR
from zikaron.service import dispatch, dispatch_consolidation
from zikaron.service.context import ServiceContext
from zikaron.service.dispatch_consolidation import (
    BusyResult,
    GroupConflictResult,
    RunDoneResult,
    ServedGroupResult,
)

_AGENT = envelope(session_id="agent-session", kind="mcp", pid=100)
_CONSOLIDATOR = envelope(session_id="agent-session", kind=ClientKind.CONSOLIDATOR.value, pid=4242)

# Two prose pairs at a 10-degree angle: cosine ~0.985, comfortably above the default
# `orphan_edge_cutoff` (0.65), and each other's only neighbour, so they satisfy `mutual_k`'s
# default of 5 trivially and form one orphan group deterministically.
_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same compiler drift shows up in the dev container")


async def _set_long_term(ctx: ServiceContext, uuid: str) -> None:
    await ctx.store.connection.execute(
        "UPDATE memory SET tier = 'long_term' WHERE uuid = ?", (uuid,)
    )
    await ctx.store.connection.commit()


async def _write_orphan_pair(ctx: ServiceContext) -> tuple[str, str]:
    assert isinstance(ctx.encoder, FakeEncoder)
    for gist, content, degrees in ((*_A, 0.0), (*_B, 10.0)):
        embedded = f"{gist}{PREFIX_SEPARATOR}{content}"
        ctx.encoder.planned[embedded] = unit_at(degrees, ctx.encoder.dim)
    first = await dispatch.remember(
        ctx.store.connection, ctx, _AGENT, {"gist": _A[0], "content": _A[1]}
    )
    second = await dispatch.remember(
        ctx.store.connection, ctx, _AGENT, {"gist": _B[0], "content": _B[1]}
    )
    return first.uuid, second.uuid


# A long-term anchor plus one journal member at a close angle, so the anchored group's `merge`
# target is legally the long-term row rather than a journal member — `merge` only ever accepts a
# row already in the group's persisted anchor/candidate set, never a fellow journal member, so an
# orphan pair (no long-term row at all) has nothing legal to `merge` into.
_ANCHOR = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_MEMBER = ("proto codegen also fails locally", "the same compiler drift shows up in the container")


async def _write_anchored_pair(ctx: ServiceContext) -> tuple[str, str]:
    """Returns `(anchor_uuid, member_uuid)` — the anchor already `tier='long_term'`."""
    assert isinstance(ctx.encoder, FakeEncoder)
    for gist, content, degrees in ((*_ANCHOR, 0.0), (*_MEMBER, 10.0)):
        embedded = f"{gist}{PREFIX_SEPARATOR}{content}"
        ctx.encoder.planned[embedded] = unit_at(degrees, ctx.encoder.dim)
    anchor = await dispatch.remember(
        ctx.store.connection, ctx, _AGENT, {"gist": _ANCHOR[0], "content": _ANCHOR[1]}
    )
    await _set_long_term(ctx, anchor.uuid)
    member = await dispatch.remember(
        ctx.store.connection, ctx, _AGENT, {"gist": _MEMBER[0], "content": _MEMBER[1]}
    )
    return anchor.uuid, member.uuid


# A third long-term row, close to the member's own angle so the candidate query — built from the
# served set's gists — surfaces it as a genuine `RankedRecord`. Kept distinct from `_ANCHOR` so
# retrieval does not simply return the anchor a second time.
_CANDIDATE = (
    "proto codegen breaks in CI too",
    "the pinned compiler version in CI drifts from the dev container's",
)


async def _write_anchor_member_and_candidate(ctx: ServiceContext) -> tuple[str, str, str]:
    """Returns `(anchor_uuid, member_uuid, candidate_uuid)` — anchor and candidate both
    `tier='long_term'`, so `next_group`'s `candidates` field is genuinely non-empty rather than
    the accidentally-untested-empty case every other fixture in this file produces."""
    assert isinstance(ctx.encoder, FakeEncoder)
    for gist, content, degrees in (
        (*_ANCHOR, 0.0),
        (*_MEMBER, 10.0),
        (*_CANDIDATE, 12.0),
    ):
        embedded = f"{gist}{PREFIX_SEPARATOR}{content}"
        ctx.encoder.planned[embedded] = unit_at(degrees, ctx.encoder.dim)
    anchor = await dispatch.remember(
        ctx.store.connection, ctx, _AGENT, {"gist": _ANCHOR[0], "content": _ANCHOR[1]}
    )
    await _set_long_term(ctx, anchor.uuid)
    member = await dispatch.remember(
        ctx.store.connection, ctx, _AGENT, {"gist": _MEMBER[0], "content": _MEMBER[1]}
    )
    candidate = await dispatch.remember(
        ctx.store.connection, ctx, _AGENT, {"gist": _CANDIDATE[0], "content": _CANDIDATE[1]}
    )
    await _set_long_term(ctx, candidate.uuid)
    return anchor.uuid, member.uuid, candidate.uuid


async def test_plan_groups_on_an_empty_store_returns_the_pre_close_run(tmp_path: Path) -> None:
    """`plan_groups`'s own docstring: the returned `Run` carries its *pre-close* status even
    though a run with zero groups is closed `complete` in the store the instant it is planned —
    this asserts the dispatch layer serializes exactly what `core` returns, not a second
    "is it really complete" opinion of its own."""
    async with open_context(tmp_path) as ctx:
        result = await dispatch_consolidation.plan_groups(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert result.status == "active"
        assert isinstance(result.run_id, str)
        stored_status = list(
            await ctx.store.connection.execute_fetchall(
                "SELECT status FROM consolidation_run WHERE run_id = ?", (result.run_id,)
            )
        )
        assert stored_status[0][0] == "complete"


async def test_next_group_on_an_empty_run_reports_done(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        result = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(result, RunDoneResult)
        assert result.as_json() == {"done": True}


async def test_a_second_worker_with_a_different_pid_is_told_busy(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        await _write_orphan_pair(ctx)
        await dispatch_consolidation.next_group(ctx.store.connection, ctx, _CONSOLIDATOR, {})

        stranger = envelope(
            session_id="agent-session", kind=ClientKind.CONSOLIDATOR.value, pid=9999
        )
        result = await dispatch_consolidation.next_group(ctx.store.connection, ctx, stranger, {})
        assert isinstance(result, BusyResult)
        assert result.holder_pid == 4242


async def test_next_group_serves_the_anchored_group_and_merge_completes_it(
    tmp_path: Path,
) -> None:
    async with open_context(tmp_path) as ctx:
        anchor, member = await _write_anchored_pair(ctx)
        served = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(served, ServedGroupResult)
        member_uuids = {entry.record.uuid for entry in served.journal_entries}
        assert member_uuids == {member}
        assert served.anchor is not None
        assert served.anchor.record.uuid == anchor
        assert set(served.anchor.as_json()) == {
            "uuid",
            "expected_version",
            "gist",
            "content",
            "created_at",
        }

        merged = await dispatch_consolidation.consolidator_merge(
            ctx.store.connection,
            ctx,
            _CONSOLIDATOR,
            {
                "group_id": served.group_id,
                "target": {"uuid": anchor, "expected_version": 1},
                "gist": "merged gist",
                "content": "merged content",
                "absorb": [{"uuid": member, "expected_version": 1}],
            },
        )
        assert not isinstance(merged, GroupConflictResult)
        assert merged.version == 2
        assert merged.group_complete is True
        assert merged.remaining_uuids == ()


async def test_next_group_serves_a_non_empty_candidates_list_in_the_flat_wire_shape(
    tmp_path: Path,
) -> None:
    """The load-bearing shape assertion: `candidates` is a list of **flat**
    `{uuid, expected_version, gist, content, created_at, rank}` objects, per `architecture.md`'s
    `next_group` contract — never a nested `{record: {...}, rank}`, which every other fixture in
    this file cannot catch because its own `candidates` list is empty."""
    async with open_context(tmp_path) as ctx:
        anchor, _member, candidate = await _write_anchor_member_and_candidate(ctx)
        served = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(served, ServedGroupResult)
        assert served.anchor is not None
        # Which of the two long-term rows anchors the group is D29's own ranking to decide, not
        # this test's — what matters here is that one of them anchored and the *other* survived
        # as a genuine, non-empty candidate in the flat shape the wire contract states.
        assert served.anchor.record.uuid in (anchor, candidate)
        assert len(served.candidates) >= 1
        candidate_json = served.candidates[0].as_json()
        assert set(candidate_json) == {
            "uuid",
            "expected_version",
            "gist",
            "content",
            "created_at",
            "rank",
        }
        served_uuids = {
            served.anchor.record.uuid,
            *(one.as_json()["uuid"] for one in served.candidates),
        }
        assert served_uuids == {anchor, candidate}
        assert isinstance(candidate_json["rank"], int)


async def test_merge_on_a_conflicting_version_returns_a_group_conflict_shape(
    tmp_path: Path,
) -> None:
    async with open_context(tmp_path) as ctx:
        anchor, member = await _write_anchored_pair(ctx)
        served = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(served, ServedGroupResult)

        result = await dispatch_consolidation.consolidator_merge(
            ctx.store.connection,
            ctx,
            _CONSOLIDATOR,
            {
                "group_id": served.group_id,
                "target": {"uuid": anchor, "expected_version": 99},
                "gist": "merged gist",
                "content": "merged content",
                "absorb": [{"uuid": member, "expected_version": 1}],
            },
        )
        assert isinstance(result, GroupConflictResult)
        assert len(result.current) == 1
        assert result.current[0].record.uuid == anchor


async def test_promote_new_row_creates_a_long_term_record(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        first, second = await _write_orphan_pair(ctx)
        served = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(served, ServedGroupResult)

        promoted = await dispatch_consolidation.consolidator_promote(
            ctx.store.connection,
            ctx,
            _CONSOLIDATOR,
            {
                "group_id": served.group_id,
                "gist": "promoted gist",
                "content": "promoted content",
                "absorb": [
                    {"uuid": first, "expected_version": 1},
                    {"uuid": second, "expected_version": 1},
                ],
            },
        )
        assert not isinstance(promoted, GroupConflictResult)
        assert promoted.group_complete is True
        assert promoted.uuid not in (first, second)


async def test_discard_retires_both_members_and_records_the_reason(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        first, second = await _write_orphan_pair(ctx)
        served = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(served, ServedGroupResult)

        result = await dispatch_consolidation.consolidator_discard(
            ctx.store.connection,
            ctx,
            _CONSOLIDATOR,
            {
                "group_id": served.group_id,
                "absorb": [
                    {"uuid": first, "expected_version": 1},
                    {"uuid": second, "expected_version": 1},
                ],
                "reason": "duplicate noise",
            },
        )
        assert not isinstance(result, GroupConflictResult)
        assert result.retired == 2
        assert result.group_complete is True


async def test_merge_with_a_repeated_absorb_uuid_is_rejected_as_bounds(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        first, second = await _write_orphan_pair(ctx)
        served = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(served, ServedGroupResult)

        with pytest.raises(ZikaronError) as excinfo:
            await dispatch_consolidation.consolidator_merge(
                ctx.store.connection,
                ctx,
                _CONSOLIDATOR,
                {
                    "group_id": served.group_id,
                    "target": {"uuid": first, "expected_version": 1},
                    "gist": "g",
                    "content": "c",
                    "absorb": [
                        {"uuid": second, "expected_version": 1},
                        {"uuid": second, "expected_version": 1},
                    ],
                },
            )
        assert excinfo.value.code is ErrorCode.BOUNDS
        assert excinfo.value.data["field"] == "absorb"


async def test_merge_naming_a_group_from_a_stranger_worker_is_rejected(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        first, second = await _write_orphan_pair(ctx)
        served = await dispatch_consolidation.next_group(
            ctx.store.connection, ctx, _CONSOLIDATOR, {}
        )
        assert isinstance(served, ServedGroupResult)

        stranger = envelope(
            session_id="agent-session", kind=ClientKind.CONSOLIDATOR.value, pid=9999
        )
        with pytest.raises(ZikaronError) as excinfo:
            await dispatch_consolidation.consolidator_merge(
                ctx.store.connection,
                ctx,
                stranger,
                {
                    "group_id": served.group_id,
                    "target": {"uuid": first, "expected_version": 1},
                    "gist": "g",
                    "content": "c",
                    "absorb": [{"uuid": second, "expected_version": 1}],
                },
            )
        assert excinfo.value.code is ErrorCode.GROUP_EXPIRED


async def test_a_primary_agent_envelope_calling_a_consolidator_method_is_a_bounds_error(
    tmp_path: Path,
) -> None:
    """`server.py` dispatches purely by method name — nothing about the method table itself
    prevents an `mcp`-kind client from naming `next_group` (or any of the other four consolidator
    methods) directly, since method name and `client.kind` are independent fields of one request.
    This must be a declared, actionable `BOUNDS` error naming the field, never the opaque
    protocol-level internal error `ConsolidationCall`'s own receipt-scoping invariant would
    otherwise produce."""
    async with open_context(tmp_path) as ctx:
        primary_agent = envelope(session_id="agent-session", kind="mcp", pid=100)
        with pytest.raises(ZikaronError) as excinfo:
            await dispatch_consolidation.next_group(ctx.store.connection, ctx, primary_agent, {})
        assert excinfo.value.code is ErrorCode.BOUNDS
        assert excinfo.value.data["field"] == "client.kind"
