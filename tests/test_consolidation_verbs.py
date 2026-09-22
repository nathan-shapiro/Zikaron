"""The three consolidator write verbs: `zikaron.core.consolidation.verbs`.

Default tier, unmarked: a real store, because every claim here is about rows, versions, supersession
edges, dispositions, receipts and the exact events that committed beside them.

Each test serves a real group first, through `next_group`, and takes its `expected_version` values
out of the payload the way a consolidator must — the payload is what mints the receipts, so a test
that invented a version would be testing a call no consolidator could make.
"""

from pathlib import Path

import pytest

from tests.consolidation_fixtures import AGENT_SESSION, consolidator, detail_of
from zikaron.core.consolidation import serving, verbs
from zikaron.core.consolidation.groups import Disposition, GroupStatus
from zikaron.core.consolidation.payload import (
    Discarded,
    GroupConflict,
    Merged,
    MergeTarget,
    NamedRow,
    NamedRows,
    Promoted,
    ServedGroup,
)
from zikaron.core.consolidation.runs import RunStatus
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records.memory import Rewrite, Tier

_RECORD = ("the proto toolchain is pinned", "the pinned protoc version lives in requirements.txt")
_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same drift shows up in the dev container")
_NEW = Rewrite(gist="proto drift, consolidated", content="pin protoc; the drift bites everywhere")


def _named(record: object) -> NamedRow:
    """One payload record as the `{uuid, expected_version}` pair a verb takes."""
    return NamedRow(uuid=record.uuid, expected_version=record.expected_version)  # type: ignore[attr-defined]


async def _serve_one(c: object, *, op_id: str = "op1") -> ServedGroup:
    served = await serving.next_group(c.harness.store.connection, call=c.call(op_id=op_id))  # type: ignore[attr-defined]
    assert isinstance(served, ServedGroup)
    return served


async def test_merge_rewrites_the_target_and_supersedes_what_it_absorbed(tmp_path: Path) -> None:
    """The whole verb: the target's prose and version move, every absorbed row is retired with
    `superseded_by = target.uuid` (D25, so it demotes rather than hides), and the group closes
    because its last member was dispositioned."""
    async with consolidator(tmp_path) as c:
        record = await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        member = await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve_one(c)
        assert served.anchor is not None
        outcome = await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(row=_named(served.anchor), rewrite=_NEW),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="merge"),
        )
        assert isinstance(outcome, Merged)
        assert outcome.uuid == record
        assert outcome.version == 2
        assert outcome.remaining_uuids == ()
        assert outcome.group_complete is True
        assert await c.row(record) == ("long_term", True, None, 2)
        assert await c.row(member) == ("journal", False, record, 2)
        assert await c.member_rows(served.group_id) == [(member, 1, 1, Disposition.MERGED)]
        assert (await c.groups())[0][5] is GroupStatus.COMPLETE
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.COMPLETE]


async def test_merge_emits_one_event_per_row_it_mutated(tmp_path: Path) -> None:
    """The size fields are present on the `target` row and null on every `absorbed` one, because
    only the target authored prose — and `n_absorbed` is the call's own count on every row of the
    call."""
    async with consolidator(tmp_path) as c:
        await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve_one(c)
        assert served.anchor is not None
        await c.clear_events()
        await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(row=_named(served.anchor), rewrite=_NEW),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="merge"),
        )
        details = detail_of(await c.events(), "merge")
        assert [one["role"] for one in details] == ["target", "absorbed"]
        assert details[0]["n_absorbed"] == 1
        assert details[1]["n_absorbed"] == 1
        assert details[0]["token_count"] is not None
        assert [
            details[1][field] for field in ("token_count", "gist_tokens", "n_chunks", "truncated")
        ] == [
            None,
            None,
            None,
            None,
        ]


async def test_merge_rebuilds_the_targets_indexes(tmp_path: Path) -> None:
    """A merged record's chunks are rebuilt atomically with its version bump (D28), and the lexical
    index is resynced — so the old prose is unmatchable and the new prose matches."""
    async with consolidator(tmp_path) as c:
        record = await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve_one(c)
        assert served.anchor is not None
        await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(row=_named(served.anchor), rewrite=_NEW),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="merge"),
        )
        matched = await c.harness.store.connection.execute_fetchall(
            "SELECT m.uuid FROM memory_fts JOIN memory m ON m.rowid = memory_fts.rowid "
            "WHERE memory_fts MATCH ?",
            ("consolidated",),
        )
        assert [str(uuid) for (uuid,) in matched] == [record]
        stale = await c.harness.store.connection.execute_fetchall(
            "SELECT m.uuid FROM memory_fts JOIN memory m ON m.rowid = memory_fts.rowid "
            "WHERE memory_fts MATCH ?",
            ("toolchain",),
        )
        assert record not in [str(uuid) for (uuid,) in stale]
        chunks = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_chunk WHERE memory_uuid = ?", (record,)
        )
        assert int(str(next(iter(chunks))[0])) >= 1


async def test_merge_refuses_a_target_outside_the_authorization_set(tmp_path: Path) -> None:
    """The persisted authorization set — not the events — is the authority, and `not_authorized`
    deliberately covers every uuid outside it **whether or not it exists**, so the rejection cannot
    be used to discover what the store holds."""
    async with consolidator(tmp_path) as c:
        await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        member = await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve_one(c)
        # A journal member is the row that can *never* be in the authorization set: members are
        # what a group is dispositioned over and candidates are what it is shown against, and the
        # two sets are disjoint by construction. A merely unrelated long-term record would be a
        # weaker fixture, since the candidate query authorizes up to four of those.
        assert member not in {uuid for uuid, *_ in await c.authorization_rows(served.group_id)}
        with pytest.raises(ZikaronError) as raised:
            await verbs.merge(
                c.harness.store.connection,
                group_id=served.group_id,
                target=MergeTarget(row=NamedRow(uuid=member, expected_version=1), rewrite=_NEW),
                absorb=[_named(served.journal_entries[0])],
                call=c.call(op_id="merge"),
            )
        assert raised.value.code is ErrorCode.BAD_MERGE_TARGET
        assert raised.value.data["reason"] == "not_authorized"


async def test_merge_refuses_an_unknown_uuid_the_same_way_as_an_unauthorized_one(
    tmp_path: Path,
) -> None:
    """Same code, same reason, same payload — which is what keeps the error from being an existence
    oracle for a consolidator that has no `fetch`."""
    async with consolidator(tmp_path) as c:
        await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve_one(c)
        with pytest.raises(ZikaronError) as raised:
            await verbs.merge(
                c.harness.store.connection,
                group_id=served.group_id,
                target=MergeTarget(
                    row=NamedRow(uuid="00000000-0000-4000-8000-000000000000", expected_version=1),
                    rewrite=_NEW,
                ),
                absorb=[_named(served.journal_entries[0])],
                call=c.call(op_id="merge"),
            )
        assert raised.value.code is ErrorCode.BAD_MERGE_TARGET
        assert raised.value.data["reason"] == "not_authorized"


async def test_promote_flips_one_matching_member_in_place(tmp_path: Path) -> None:
    """Exactly one `absorb` row whose gist and content are byte-identical to the arguments ⇒ flip
    that row's tier in place, version still bumping. One mutated row, **one** event,
    `role='flipped'`, `form='in_place'`, `n_absorbed=1` — because the flipped row *is* the absorbed
    member and a singular role cannot say both."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        await c.clear_events()
        outcome = await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=Rewrite(gist=_A[0], content=_A[1]),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="promote"),
        )
        assert isinstance(outcome, Promoted)
        assert outcome.uuid == member
        assert outcome.version == 2
        assert await c.row(member) == ("long_term", True, None, 2)
        details = detail_of(await c.events(), "promote")
        assert [(one["role"], one["form"], one["n_absorbed"]) for one in details] == [
            ("flipped", "in_place", 1)
        ]
        assert details[0]["n_chunks"] == 1
        assert details[0]["truncated"] is False


async def test_an_in_place_promotion_reports_the_size_the_store_holds(tmp_path: Path) -> None:
    """Read off stored state rather than recomputed by a preflight: the row's own `token_count`, its
    own chunk rows, and the stored gist counted with the deployed tokenizer. A preflight run under a
    `chunk_max_tokens` that had moved since the row was written would report an `n_chunks` the store
    does not contain — asserted by moving it and checking the event still describes the index."""
    async with consolidator(tmp_path, overrides="[indexing]\nchunk_max_tokens = 64\n") as c:
        member = await c.write(gist="a short gist", content="one two three four five six", minute=1)
        stored = await c.harness.store.connection.execute_fetchall(
            "SELECT token_count FROM memory WHERE uuid = ?", (member,)
        )
        served = await _serve_one(c)
        await c.clear_events()
        await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=Rewrite(gist="a short gist", content="one two three four five six"),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="promote"),
        )
        detail = detail_of(await c.events(), "promote")[0]
        assert detail["token_count"] == int(str(next(iter(stored))[0]))
        assert detail["gist_tokens"] == 3
        assert detail["n_chunks"] == 1


async def test_promote_authors_a_new_long_term_record_when_the_prose_differs(
    tmp_path: Path,
) -> None:
    """The new-row form: insert a long-term record at version 1 and retire every absorbed row with
    `superseded_by` set to the new uuid. One `created` event plus one `absorbed` event per row."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=5.0)
        served = await _serve_one(c)
        assert len(served.journal_entries) == 2
        await c.clear_events()
        outcome = await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=_NEW,
            absorb=[_named(record) for record in served.journal_entries],
            call=c.call(op_id="promote"),
        )
        assert isinstance(outcome, Promoted)
        assert outcome.uuid not in {first, second}
        assert outcome.version == 1
        assert await c.row(outcome.uuid) == ("long_term", True, None, 1)
        assert await c.row(first) == ("journal", False, outcome.uuid, 2)
        assert await c.row(second) == ("journal", False, outcome.uuid, 2)
        details = detail_of(await c.events(), "promote")
        assert [(one["role"], one["form"]) for one in details] == [
            ("created", "new_row"),
            ("absorbed", "new_row"),
            ("absorbed", "new_row"),
        ]
        assert details[0]["n_absorbed"] == 2


async def test_a_promoted_new_record_has_at_least_one_chunk(tmp_path: Path) -> None:
    """Invariant 12 for the one verb that creates a row outside the ordinary write path: a memory
    with zero vectors would be invisible to the dense arm while looking perfectly healthy."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        outcome = await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=_NEW,
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="promote"),
        )
        assert isinstance(outcome, Promoted)
        rows = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_chunk c JOIN memory_vec v ON v.rowid = c.chunk_id "
            "WHERE c.memory_uuid = ?",
            (outcome.uuid,),
        )
        assert int(str(next(iter(rows))[0])) >= 1


async def test_two_absorbed_rows_share_one_replacement(tmp_path: Path) -> None:
    """Convergence is deliberate and common: the supersession graph is a rooted converging forest,
    not a forest of chains, and `promote` absorbing two rows writes both edges to the same
    record."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=5.0)
        served = await _serve_one(c)
        outcome = await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=_NEW,
            absorb=[_named(record) for record in served.journal_entries],
            call=c.call(op_id="promote"),
        )
        assert isinstance(outcome, Promoted)
        rows = await c.harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory WHERE superseded_by = ?", (outcome.uuid,)
        )
        assert int(str(next(iter(rows))[0])) == 2


async def test_discard_retires_outright_and_records_the_reason_only_in_the_log(
    tmp_path: Path,
) -> None:
    """`active=0`, `superseded_by NULL` (D16), the prose untouched — so "we decided this was noise"
    stays recoverable from the event log if that judgment was wrong."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        await c.clear_events()
        outcome = await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[0])],
            reason="one-off, not tribal knowledge",
            call=c.call(op_id="discard"),
        )
        assert isinstance(outcome, Discarded)
        assert outcome.retired == 1
        assert outcome.group_complete is True
        assert await c.row(member) == ("journal", False, None, 2)
        details = detail_of(await c.events(), "discard")
        assert [one["reason"] for one in details] == ["one-off, not tribal knowledge"]
        prose = await c.harness.store.connection.execute_fetchall(
            "SELECT gist, content FROM memory WHERE uuid = ?", (member,)
        )
        assert tuple(str(value) for value in next(iter(prose))) == (_A[0], _A[1])


async def test_a_mixed_group_takes_three_calls_and_closes_on_the_last(tmp_path: Path) -> None:
    """Completion is tracked per journal row, never per group: one write verb does **not** close a
    group, and `remaining_uuids` shrinks within each call rather than describing the state it
    started from."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        second = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=2.0)
        third = await c.write(
            gist="proto drift on CI too",
            content="the same protoc mismatch on the build box",
            minute=3,
            degrees=4.0,
        )
        served = await _serve_one(c)
        assert [record.uuid for record in served.journal_entries] == [first, second, third]

        promoted = await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=_NEW,
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="p"),
        )
        assert isinstance(promoted, Promoted)
        assert promoted.remaining_uuids == (second, third)
        assert promoted.group_complete is False

        discarded = await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[1])],
            reason="duplicate of the promoted record",
            call=c.call(op_id="d"),
        )
        assert isinstance(discarded, Discarded)
        assert discarded.remaining_uuids == (third,)
        assert discarded.group_complete is False

        re_served = await _serve_one(c, op_id="s2")
        assert [record.uuid for record in re_served.journal_entries] == [third]
        assert re_served.serve_count == 2
        merged = await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(
                row=NamedRow(uuid=promoted.uuid, expected_version=promoted.version),
                rewrite=Rewrite(gist=_NEW.gist, content=f"{_NEW.content}; and on CI"),
            ),
            absorb=[_named(re_served.journal_entries[0])],
            call=c.call(op_id="m"),
        )
        assert isinstance(merged, Merged)
        assert merged.remaining_uuids == ()
        assert merged.group_complete is True
        assert (await c.groups())[0][5] is GroupStatus.COMPLETE


async def test_a_version_conflict_returns_every_conflicting_record_and_mutates_nothing(
    tmp_path: Path,
) -> None:
    """All versions are validated **before** anything mutates, and one mismatch returns the current
    record for **every** conflicting uuid so the model can re-decide in one round trip. The conflict
    also mints a receipt at the current version — without which that retry would fail for want of
    one, since the consolidator has no `fetch`."""
    async with consolidator(tmp_path) as c:
        record = await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        member = await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await _serve_one(c)
        assert served.anchor is not None
        await c.amend(member, gist=_A[0], content="a primary agent got here first")
        await c.clear_events()
        outcome = await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(row=_named(served.anchor), rewrite=_NEW),
            absorb=[_named(served.journal_entries[0])],
            call=c.call(op_id="merge"),
        )
        assert isinstance(outcome, GroupConflict)
        assert [one.uuid for one in outcome.current] == [member]
        assert outcome.current[0].version == 2
        assert outcome.current[0].content == "a primary agent got here first"
        assert outcome.remaining_uuids == (member,)
        assert await c.row(record) == ("long_term", True, None, 1)
        assert await c.member_rows(served.group_id) == [(member, 1, 1, None)]
        assert detail_of(await c.events(), "version_conflict") == [
            {"verb": "merge", "expected_version": 1, "actual_version": 2}
        ]
        assert ("consolidator", member, 2, "conflict") in {
            (kind, uuid, version, source) for _, kind, uuid, version, source in await c.receipts()
        }


async def test_a_conflict_does_not_refresh_the_lease(tmp_path: Path) -> None:
    """A `{conflict: true}` response mutates nothing, so it must not buy the lease more time —
    letting it would mean a consolidator achieving nothing at all could hold the store
    indefinitely."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        before = await c.expires_at(served.run_id)
        await c.amend(member, gist=_A[0], content="a primary agent got here first")
        outcome = await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[0])],
            reason="noise",
            call=c.call(op_id="discard"),
        )
        assert isinstance(outcome, GroupConflict)
        assert await c.expires_at(served.run_id) == before


async def test_a_missing_receipt_raises_and_still_commits_its_audit_events(tmp_path: Path) -> None:
    """Invariant 10's carve-out, re-asserted for the consolidation verbs: a rejected call commits no
    domain mutation but **does** commit its audit events. The version is right and the receipt is
    not, which is exactly what D26 exists to catch — an agent that guessed a version it never
    read."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        await c.harness.store.connection.execute("DELETE FROM read_receipt")
        await c.harness.store.connection.commit()
        await c.clear_events()
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[_named(served.journal_entries[0])],
                reason="noise",
                call=c.call(op_id="discard"),
            )
        assert raised.value.code is ErrorCode.NO_READ_RECEIPT
        assert raised.value.data["uuids"] == [member]
        assert detail_of(await c.events(), "no_receipt") == [
            {"verb": "discard", "version_presented": 1}
        ]
        assert await c.row(member) == ("journal", True, None, 1)
        assert await c.member_rows(served.group_id) == [(member, 1, 1, None)]


async def test_a_consolidator_receipt_does_not_license_a_primary_agent_write(
    tmp_path: Path,
) -> None:
    """`read_receipt`'s key includes `client_kind`, so a serve's receipts are the consolidator's
    alone. Without that column a serve would license the primary agent to amend a row it never
    fetched."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await _serve_one(c)
        minted = {
            (kind, uuid) for _, kind, uuid, _, source in await c.receipts() if source == "group"
        }
        assert minted == {("consolidator", member)}
        assert not [
            row for row in await c.receipts() if row[0] == AGENT_SESSION and row[4] == "group"
        ]


@pytest.mark.parametrize("absorb_uuids", [[], ["stranger"]])
async def test_an_absorb_list_that_is_empty_or_names_a_non_member_is_refused(
    tmp_path: Path, absorb_uuids: list[str]
) -> None:
    """Silence and typos cannot complete a group. An empty list and a uuid outside the group are the
    same answer — `not_in_group`, uuids only — and both change nothing."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        absorb = [NamedRow(uuid=uuid, expected_version=1) for uuid in absorb_uuids]
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=absorb,
                reason="noise",
                call=c.call(op_id="discard"),
            )
        assert raised.value.code is ErrorCode.NOT_IN_GROUP
        assert raised.value.data["uuids"] == absorb_uuids
        assert await c.member_rows(served.group_id) == [(member, 1, 1, None)]


async def test_an_already_dispositioned_member_is_refused(tmp_path: Path) -> None:
    """A model that named a dispositioned uuid again would earn a guaranteed rejection, which is
    why a re-serve excludes it from the payload in the first place."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=2.0)
        served = await _serve_one(c)
        first = _named(served.journal_entries[0])
        await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[first],
            reason="noise",
            call=c.call(op_id="d1"),
        )
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[first],
                reason="noise again",
                call=c.call(op_id="d2"),
            )
        assert raised.value.code is ErrorCode.NOT_IN_GROUP


async def test_a_member_retired_after_the_serve_answers_not_in_group_on_the_retry(
    tmp_path: Path,
) -> None:
    """Rung 6's one producer, end to end. A primary agent retires a served member: the first call
    gets `version_conflict` with a fresh receipt, and the **retry** — now correct at every earlier
    rung — arrives at rung 6 holding a row that is `active=0`. That row is *vacated in fact and not
    yet recorded*, so the answer is `not_in_group` rather than a new code, and the rejected call
    writes no disposition: only a serve may say otherwise."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        await c.harness.retire(member, call_ctx=None)
        conflict = await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[0])],
            reason="noise",
            call=c.call(op_id="d1"),
        )
        assert isinstance(conflict, GroupConflict)
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[NamedRow(uuid=member, expected_version=conflict.current[0].version)],
                reason="noise",
                call=c.call(op_id="d2"),
            )
        assert raised.value.code is ErrorCode.NOT_IN_GROUP
        assert raised.value.data["uuids"] == [member]
        assert await c.member_rows(served.group_id) == [(member, 1, 1, None)]


async def test_a_repeated_absorb_uuid_is_a_bounds_error() -> None:
    """Rung 1, and independent of store state: a uuid twice would bump one row's `version` twice for
    one logical action and report an `n_absorbed` that counted it twice."""
    with pytest.raises(ZikaronError) as raised:
        NamedRows(absorb=(NamedRow(uuid="u", expected_version=1),) * 2)
    assert raised.value.code is ErrorCode.BOUNDS
    assert raised.value.data["field"] == "absorb"


async def test_an_unknown_group_is_refused(tmp_path: Path) -> None:
    async with consolidator(tmp_path) as c:
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id="no-such-group",
                absorb=[NamedRow(uuid="u", expected_version=1)],
                reason="noise",
                call=c.call(),
            )
        assert raised.value.code is ErrorCode.GROUP_UNKNOWN


async def test_a_complete_group_is_refused(tmp_path: Path) -> None:
    """Rung 2 checks the **run** before the group, which is the design's own order — so this code is
    reachable only while the run is still active, i.e. while another group of it is still open. A
    single-group run answers `group_expired` instead, because completing its one group completes the
    run, and that is correct rather than a gap: the group id is dead either way."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(
            gist="unrelated lesson", content="about something else entirely", minute=2, degrees=90.0
        )
        served = await _serve_one(c)
        first = _named(served.journal_entries[0])
        await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[first],
            reason="noise",
            call=c.call(op_id="d1"),
        )
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.ACTIVE]
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[first],
                reason="again",
                call=c.call(op_id="d2"),
            )
        assert raised.value.code is ErrorCode.GROUP_COMPLETE


async def test_a_deferred_group_is_refused_by_a_write_verb(tmp_path: Path) -> None:
    """`next_group` never returns this code — its loop marks the group `deferred` and moves on — so
    a write verb is the only place it can be raised."""
    async with consolidator(tmp_path, overrides="[consolidation]\nmax_group_serves = 1\n") as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(
            gist="unrelated lesson", content="about something else entirely", minute=2, degrees=90.0
        )
        served = await _serve_one(c)
        # The second call defers the first group and serves the second, which is what keeps the run
        # active — rung 2 checks the run first, so a deferred group in a *finished* run answers
        # `group_expired` instead.
        await serving.next_group(c.harness.store.connection, call=c.call(op_id="s2"))
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[_named(served.journal_entries[0])],
                reason="noise",
                call=c.call(op_id="d"),
            )
        assert raised.value.code is ErrorCode.GROUP_DEFERRED
        assert raised.value.data["serve_count"] == 1


async def test_a_lapsed_lease_refuses_a_write_verb_without_writing_the_expiry(
    tmp_path: Path,
) -> None:
    """`group_expired` reports the **stored** status and the **effective** one, and writes neither:
    expiry is a condition every reader derives, and only `plan_groups` stores it. An earlier draft
    had both rules and they could not both hold."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        await c.lapse_lease(served.run_id)
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[_named(served.journal_entries[0])],
                reason="noise",
                call=c.call(op_id="d"),
            )
        assert raised.value.code is ErrorCode.GROUP_EXPIRED
        assert raised.value.data["run_status"] == "active"
        assert raised.value.data["effective_status"] == "expired"
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.ACTIVE]


async def test_a_stranger_cannot_write_to_a_group_it_does_not_own(tmp_path: Path) -> None:
    """Ownership is the pair, so a second worker of the same session with a different pid is a
    stranger — which is what makes the one-worker guarantee `next_group` establishes actually
    hold."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await _serve_one(c)
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=served.group_id,
                absorb=[_named(served.journal_entries[0])],
                reason="noise",
                call=c.call(op_id="d", pid=99999),
            )
        assert raised.value.code is ErrorCode.GROUP_EXPIRED


async def test_a_successful_write_refreshes_the_lease(tmp_path: Path) -> None:
    """Progress buys time: a verb that dispositioned a member pushes `expires_at` out, so a
    consolidator making steady progress never reaches the lapsed-lease path at all."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=2.0)
        served = await _serve_one(c)
        before = await c.expires_at(served.run_id)
        await verbs.discard(
            c.harness.store.connection,
            group_id=served.group_id,
            absorb=[_named(served.journal_entries[0])],
            reason="noise",
            call=c.call(op_id="d"),
        )
        assert await c.expires_at(served.run_id) > before
