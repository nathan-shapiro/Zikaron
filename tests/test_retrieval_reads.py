"""`search` and `surface` end to end — the M5 done-when conditions, invariants 18 and 20.

The five things the build plan asks this milestone to demonstrate are each a test here: a superseded
row surfaces demoted and ordered **behind its replacement**; one memory never occupies two of five
slots; `dense_stop_reason` distinguishes exhausted from cut on a fixture sized to each case; every
event the read path writes carries the label it was handed; and the arm depths recorded on the event
satisfy invariant 20 against the `fusion_depth` on the same row.

Events are asserted as an **exact ordered list** of `(kind, memory_uuid, detail)`, with the detail's
key order compared against `EVENT_SPECS`. Excluding the setup's kinds by name was the alternative,
and it is the arrangement in which an unexpected extra event goes unnoticed.

Contention and driver failures are provoked for real rather than injected: a second connection
commits mid-call to make the read's own snapshot stale, and dropping the `event` table produces a
driver error that is genuinely not contention. Neither needs a fabricated exception.
"""

import re
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests import retrieval_fixtures as fx
from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import ErrorCode, RowState, ZikaronError
from zikaron.core.events import (
    EVENT_SPECS,
    ArmTermination,
    Demotion,
    EventKind,
    QueryShape,
    SearchDetail,
    StopReason,
)
from zikaron.core.records.memory import Tier
from zikaron.core.retrieval import block, reads
from zikaron.core.retrieval.ranking import PoolRow, RankedMemory
from zikaron.core.retrieval.retrieve import retrieve as real_retrieve

_TERM: Final = "PGHOST"
_PROMPT: Final = "why do the integration tests need PGHOST"

#: A block line naming a memory. Matched rather than counted by prefix, so the count cannot be
#: thrown off by the preamble or the header.
_NUMBERED: Final = re.compile(r"^\d+\. \[")


def _detail_keys(kind: EventKind) -> tuple[str, ...]:
    return EVENT_SPECS[kind].field_names


async def _receipt_count(harness: fx.Harness) -> int:
    rows = await harness.store.connection.execute_fetchall("SELECT count(*) FROM read_receipt")
    return int(next(iter(rows))[0])


def _numbered_lines(printed: str) -> list[str]:
    """The block's memory lines — those beginning `<n>. [`, which nothing else in it does."""
    return [line for line in printed.splitlines() if _NUMBERED.match(line)]


async def test_an_empty_store_prints_nothing_but_still_records_the_call(tmp_path: Path) -> None:
    """ "A memory system having a quiet day should be invisible" — no header, no empty block. The
    `surface_call` row exists anyway, which is the whole reason that kind is per-call: without it a
    quiet push and a push that never happened are the same absence of evidence.

    The depths are the honest ones for an empty store rather than nulls: `chunk_count` is 0, so the
    dense probe is trivially covered and 0 *is* the true eligible total.
    """
    async with fx.harness(tmp_path) as harness:
        printed = await reads.surface(
            harness.store.connection, prompt=_PROMPT, call=harness.read_call()
        )
        assert printed == ""

        events = await harness.events()
        assert [(kind, uuid) for kind, uuid, _ in events] == [(EventKind.SURFACE_CALL, None)]
        detail = events[0][2]
        assert tuple(detail) == _detail_keys(EventKind.SURFACE_CALL)
        assert detail["n_returned"] == 0
        assert detail["n_demoted"] == 0
        assert detail["dense_depth_reached"] == 0
        assert detail["dense_stop_reason"] == StopReason.INDEX_EXHAUSTED.value
        assert detail["lexical_depth_reached"] == 0
        assert detail["lexical_stop_reason"] == StopReason.INDEX_EXHAUSTED.value


async def test_the_block_carries_the_frame_the_order_and_whole_uuids(tmp_path: Path) -> None:
    """Three load-bearing properties in one output: the untrusted-reference-data frame at the top,
    the stated best-first order, and **whole** uuids — the `…` in the design's sample is elision in
    that document, and a four-character prefix is not something `zikaron_memory_fetch` can
    resolve."""
    async with fx.harness(tmp_path) as harness:
        uuid = await harness.write(gist=f"integration tests need {_TERM}", content="set it in CI")
        await harness.clear_events()

        printed = await reads.surface(
            harness.store.connection, prompt=_PROMPT, call=harness.read_call()
        )

        assert printed.startswith(block.HEADER)
        assert block.PREAMBLE in printed
        assert "most relevant first" in printed
        assert f"1. [{uuid}] integration tests need {_TERM}" in printed
        assert "…" not in printed


async def test_surface_writes_its_call_row_before_its_per_memory_rows(tmp_path: Path) -> None:
    """One `surface_call`, then one `surface` per returned memory, all sharing one `op_id` — and
    every row carrying the session label it was handed, which is M5's share of invariant 18."""
    async with fx.harness(tmp_path) as harness:
        first = await harness.write(gist=f"{_TERM} must be set", content=f"{_TERM} {_TERM} {_TERM}")
        second = await harness.write(gist=f"{_TERM} note", content="mentions it once")
        await harness.clear_events()

        await reads.surface(harness.store.connection, prompt=_PROMPT, call=harness.read_call())

        events = await harness.events()
        assert [kind for kind, _, _ in events] == [
            EventKind.SURFACE_CALL,
            EventKind.SURFACE,
            EventKind.SURFACE,
        ]
        assert [uuid for _, uuid, _ in events][1:] == [first, second]
        assert all(tuple(detail) == _detail_keys(EventKind.SURFACE) for _, _, detail in events[1:])
        assert [detail["rank"] for _, _, detail in events[1:]] == [1, 2]
        assert {(session, kind, op) for session, kind, op in await harness.envelopes()} == {
            ("s1", "mcp", "op1")
        }


async def test_every_event_the_read_path_writes_carries_a_non_null_session_label(
    tmp_path: Path,
) -> None:
    """Invariant 18, at this layer's own boundary. Normalizing a bootstrap null is the service's job
    (`architecture.md` §"Resolution is a preamble"); what the read path owes the invariant is that
    every row it writes carries the label it was given — including in the nothing-eligible case,
    where the only row is the `surface_call` and there is no memory row to carry it instead."""
    async with fx.harness(tmp_path) as harness:
        call = harness.read_call(call_ctx=fx.ctx(session_id="zk-minted", op_id="op-42"))
        await reads.surface(harness.store.connection, prompt=_PROMPT, call=call)
        await reads.search(harness.store.connection, text=_PROMPT, call=call)

        envelopes = await harness.envelopes()
        assert envelopes
        assert all(session is not None and session == "zk-minted" for session, _, _ in envelopes)
        assert all(op == "op-42" for _, _, op in envelopes)


async def test_search_returns_the_seven_fields_the_tool_surface_states(tmp_path: Path) -> None:
    """No `version` among them, which is the same fact as `search` minting no receipt: a row seen
    only as a gist is a row the agent may not write, and holding a version would imply a licence it
    has not earned."""
    async with fx.harness(tmp_path) as harness:
        uuid = await harness.write(gist=f"{_TERM} matters", content="in CI only")
        await harness.clear_events()
        before = await _receipt_count(harness)

        hits = await reads.search(harness.store.connection, text=_PROMPT, call=harness.read_call())

        assert [hit.uuid for hit in hits] == [uuid]
        assert hits[0].gist == f"{_TERM} matters"
        assert hits[0].tier is Tier.JOURNAL
        assert hits[0].state is RowState.LIVE
        assert hits[0].superseded_by is None
        assert hits[0].created_at
        assert hits[0].updated_at
        assert not hasattr(hits[0], "version")

        # Compared against the count before rather than against zero: the fixture's own `remember`
        # legitimately minted an `own_write` receipt, and asserting zero would be asserting that the
        # write path did not do its job.
        assert await _receipt_count(harness) == before


async def test_search_records_its_own_kind_with_the_uuids_it_returned(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        uuid = await harness.write(gist=f"{_TERM} matters", content="in CI only")
        await harness.clear_events()

        await reads.search(
            harness.store.connection, text=_PROMPT, call=harness.read_call(), include_retired=True
        )

        events = await harness.events()
        assert [kind for kind, _, _ in events] == [EventKind.SEARCH]
        detail = events[0][2]
        assert tuple(detail) == _detail_keys(EventKind.SEARCH)
        assert detail["uuids"] == [uuid]
        assert detail["include_retired"] is True
        assert detail["query_chars"] == len(_PROMPT)
        assert detail["n_returned"] == 1


async def test_search_records_a_cut_set_and_its_count_agrees_with_the_uuids(
    tmp_path: Path,
) -> None:
    """`n_returned` describes the returned set, not the candidate pool — the same distinction
    `n_demoted` needs, and the fixture is built the same way: more memories match than the budget
    admits, so a count taken from the pool would differ from the uuids beside it."""
    async with fx.harness(tmp_path) as harness:
        for index in range(4):
            await harness.write(gist=f"{_TERM} note {index}", content=f"detail {index}")
        await harness.clear_events()

        hits = await reads.search(
            harness.store.connection, text=_PROMPT, call=harness.read_call(), limit=2
        )

        detail = (await harness.events())[0][2]
        assert len(hits) == 2
        assert detail["n_returned"] == 2
        assert detail["uuids"] == [hit.uuid for hit in hits]


def test_a_search_detail_whose_count_disagrees_with_its_uuids_is_refused() -> None:
    """Enforced where the payload is built, so the two cannot drift apart in any producer."""
    with pytest.raises(ValueError, match="uuids were listed"):
        SearchDetail(
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
            n_returned=3,
            uuids=("only-one",),
        )


async def test_a_superseded_row_surfaces_demoted_and_behind_its_replacement(
    tmp_path: Path,
) -> None:
    """The milestone's own done-when, and D25's measured case: blanket suppression was rejected
    because "why did we pin to 2.3.1 back then" needs exactly the historical record, so the row
    stays eligible — demoted, labelled, and ordered behind the row that replaced it.

    The fixture is built so scoring alone would invert it: the superseded row matches the query term
    three times to the replacement's once, so it outranks the replacement on BM25 and is dragged
    back by the penalty and the repair rather than by luck.
    """
    async with fx.harness(tmp_path) as harness:
        old = await harness.write(
            gist=f"pin urllib3 for {_TERM}", content=f"{_TERM} {_TERM} {_TERM} old advice"
        )
        new = await harness.write(gist=f"unpin urllib3 for {_TERM}", content="current advice")
        await harness.retire(old, superseded_by=new)
        await harness.clear_events()

        printed = await reads.surface(
            harness.store.connection, prompt=_PROMPT, call=harness.read_call()
        )

        assert printed.index(new) < printed.index(old)
        assert f"[{old}] (superseded by {new})" in printed
        assert f"[{new}] pin" not in printed

        events = await harness.events()
        call_detail = events[0][2]
        assert call_detail["n_returned"] == 2
        assert call_detail["n_demoted"] == 1
        surfaced = {uuid: detail for _, uuid, detail in events[1:]}
        assert surfaced[new]["demoted"] is False
        assert surfaced[new]["demotion"] is None
        assert surfaced[old]["demoted"] is True
        assert surfaced[old]["demotion"] == Demotion.SUPERSEDED.value


async def test_n_demoted_counts_the_returned_set_and_not_the_pool(tmp_path: Path) -> None:
    """The event carries no pool size, so `n_demoted` has to mean the returned set or it means
    nothing checkable. The fixture is the only shape that can tell the two apart: a demoted row is
    in the pool and **outside** the budget, so counting the pool would report 1 where the truth is
    0.

    It is also the demotion machinery working end to end — the replacement is promoted ahead of the
    row it replaced, so the one slot goes to the live record rather than the superseded one.
    """
    async with fx.harness(tmp_path) as harness:
        old = await harness.write(
            gist=f"old {_TERM} advice", content=f"{_TERM} {_TERM} {_TERM} superseded"
        )
        new = await harness.write(gist=f"new {_TERM} advice", content="current")
        await harness.retire(old, superseded_by=new)
        await harness.clear_events()

        printed = await reads.surface(
            harness.store.connection, prompt=_PROMPT, call=harness.read_call(), limit=1
        )

        assert _numbered_lines(printed) == [f"1. [{new}] new {_TERM} advice"]
        events = await harness.events()
        detail = events[0][2]
        assert detail["n_returned"] == 1
        assert detail["n_demoted"] == 0
        assert [uuid for _, uuid, _ in events[1:]] == [new]


async def test_a_retired_outright_row_is_excluded_by_default_and_demoted_under_include_retired(
    tmp_path: Path,
) -> None:
    """`include_retired` widens *what may appear*, not *what is currently true*: the agent asked to
    see history, not to have it compete on equal terms with the present."""
    async with fx.harness(tmp_path) as harness:
        live = await harness.write(gist=f"{_TERM} is set", content="current")
        gone = await harness.write(gist=f"{_TERM} was unset", content="historical")
        await harness.retire(gone)
        await harness.clear_events()
        call = harness.read_call()

        default = await reads.search(harness.store.connection, text=_PROMPT, call=call)
        assert [hit.uuid for hit in default] == [live]

        widened = await reads.search(
            harness.store.connection, text=_PROMPT, call=call, include_retired=True
        )
        assert sorted(hit.uuid for hit in widened) == sorted([live, gone])
        assert next(hit for hit in widened if hit.uuid == gone).state is RowState.RETIRED
        assert next(hit.uuid for hit in widened) == live, "history does not outrank the present"


async def test_one_memory_never_occupies_two_of_five_slots(tmp_path: Path) -> None:
    """D28's rollup and the memory-level dedup, at the level the budget is actually spent.

    The premise is asserted rather than assumed: `chunk_max_tokens` is at its floor and the
    paragraphs are sized so no two fit together, because at the default this memory is one chunk and
    the test would pass while checking nothing.
    """
    paragraphs = [
        f"{_TERM} " + " ".join(f"p{index}w{word}" for word in range(40)) for index in range(4)
    ]
    async with fx.harness(tmp_path, overrides="[indexing]\nchunk_max_tokens = 64\n") as harness:
        chunked = await harness.write(gist=f"{_TERM} everywhere", content="\n\n".join(paragraphs))
        counted = await harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_chunk WHERE memory_uuid = ?", (chunked,)
        )
        assert int(next(iter(counted))[0]) == len(paragraphs)
        await harness.clear_events()

        hits = await reads.search(harness.store.connection, text=_PROMPT, call=harness.read_call())

        assert [hit.uuid for hit in hits] == [chunked]
        events = await harness.events()
        assert events[0][2]["uuids"] == [chunked]


async def test_the_dense_arm_reports_a_cut_when_the_store_holds_more_than_the_depth(
    tmp_path: Path,
) -> None:
    """The paired half of the empty-store case: same two fields, opposite reason, on a fixture sized
    to overflow a lowered `fusion_depth`. Together they are what makes the pair informative rather
    than decorative."""
    async with fx.harness(tmp_path, overrides="[retrieval]\nfusion_depth = 2\n") as harness:
        for index in range(4):
            await harness.write(gist=f"{_TERM} note {index}", content=f"detail {index}")
        await harness.clear_events()

        await reads.surface(harness.store.connection, prompt=_PROMPT, call=harness.read_call())

        detail = (await harness.events())[0][2]
        assert detail["fusion_depth"] == 2
        assert detail["dense_depth_reached"] == 3
        assert detail["dense_stop_reason"] == StopReason.DEPTH_REACHED.value
        assert detail["lexical_depth_reached"] == 3
        assert detail["lexical_stop_reason"] == StopReason.DEPTH_REACHED.value


@pytest.mark.parametrize("arm", ["dense", "lexical"])
async def test_the_recorded_reason_is_derivable_from_the_recorded_depth(
    tmp_path: Path, arm: str
) -> None:
    """Invariant 20 as the log's own reader would check it: `depth_reached` and `stop_reason` are on
    the same event row as the `fusion_depth` they are compared against, so the check survives a
    config change and needs no appeal to state the event does not carry."""
    async with fx.harness(tmp_path, overrides="[retrieval]\nfusion_depth = 2\n") as harness:
        for index in range(4):
            await harness.write(gist=f"{_TERM} note {index}", content=f"detail {index}")
        await harness.clear_events()
        await reads.surface(harness.store.connection, prompt=_PROMPT, call=harness.read_call())

        detail = (await harness.events())[0][2]
        depth = detail[f"{arm}_depth_reached"]
        reason = detail[f"{arm}_stop_reason"]
        fusion_depth = detail["fusion_depth"]
        assert isinstance(depth, int)
        assert isinstance(fusion_depth, int)
        assert 0 <= depth <= fusion_depth + 1
        assert (reason == StopReason.DEPTH_REACHED.value) == (depth == fusion_depth + 1)


async def test_a_query_with_no_surviving_terms_skips_the_lexical_arm_and_says_so(
    tmp_path: Path,
) -> None:
    """A prompt of pure punctuation still gets an answer, and the skipped arm reports **both**
    fields null — the one case invariant 20's "null iff null" clause exists for. Zero and
    `index_exhausted` would together assert the arm read the index and found nothing, which it did
    not."""
    async with fx.harness(tmp_path) as harness:
        uuid = await harness.write(gist=f"{_TERM} matters", content="in CI only")
        await harness.clear_events()

        printed = await reads.surface(
            harness.store.connection, prompt="?!?", call=harness.read_call()
        )

        assert uuid in printed
        detail = (await harness.events())[0][2]
        assert detail["lexical_skipped"] is True
        assert detail["lexical_depth_reached"] is None
        assert detail["lexical_stop_reason"] is None
        assert detail["dense_stop_reason"] == StopReason.INDEX_EXHAUSTED.value


async def test_an_over_length_prompt_is_truncated_and_recorded(tmp_path: Path) -> None:
    """The prefix is charged against the budget too, so the cap has to leave room for both: at eight
    tokens of BGE prefix, a sixteen-token model leaves six for the query itself."""
    async with fx.harness(
        tmp_path, encoder=FakeEncoder(max_sequence_tokens=16, n_special_tokens=2)
    ) as harness:
        await harness.write(gist=f"{_TERM} matters", content="in CI only")
        await harness.clear_events()
        prompt = " ".join(f"w{index}" for index in range(20))

        await reads.surface(harness.store.connection, prompt=prompt, call=harness.read_call())

        detail = (await harness.events())[0][2]
        assert detail["query_truncated"] is True
        assert detail["query_tokens"] == 20
        assert detail["prompt_chars"] == len(prompt)


@pytest.mark.parametrize("limit", [0, -1, 51])
async def test_a_limit_outside_its_bounds_is_refused(tmp_path: Path, limit: int) -> None:
    """`schema.md` §Bounds: 1-50. Checked here as well as at the boundary that deserializes the
    request, for the reason `EffectiveConfig` validates itself — "the only caller checks first" is a
    fact about today's call sites, not a property of this function."""
    async with fx.harness(tmp_path) as harness:
        with pytest.raises(ZikaronError) as raised:
            await reads.search(
                harness.store.connection, text=_PROMPT, call=harness.read_call(), limit=limit
            )
        assert raised.value.code is ErrorCode.BOUNDS
        assert raised.value.data["field"] == "limit"
        assert (await harness.events()) == [], "a rejected read writes nothing at all"


@pytest.mark.parametrize("limit", [1, 50])
async def test_the_bounds_themselves_are_accepted(tmp_path: Path, limit: int) -> None:
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist=f"{_TERM} matters", content="in CI only")
        hits = await reads.search(
            harness.store.connection, text=_PROMPT, call=harness.read_call(), limit=limit
        )
        assert len(hits) == 1


async def test_the_limit_cuts_the_returned_set_and_the_event_agrees(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        for index in range(4):
            await harness.write(gist=f"{_TERM} note {index}", content=f"detail {index}")
        await harness.clear_events()

        printed = await reads.surface(
            harness.store.connection, prompt=_PROMPT, call=harness.read_call(), limit=2
        )

        assert len(_numbered_lines(printed)) == 2
        events = await harness.events()
        assert events[0][2]["n_returned"] == 2
        assert len(events) == 3, "one call row plus one row per returned memory, and no more"


async def test_two_identical_calls_produce_byte_identical_output(tmp_path: Path) -> None:
    """Determinism asserted rather than assumed, on the whole path: same store, same prompt, same
    block, down to the bytes."""
    async with fx.harness(tmp_path) as harness:
        for index in range(4):
            await harness.write(gist=f"{_TERM} note {index}", content=f"detail {index}")
        call = harness.read_call()
        first = await reads.surface(harness.store.connection, prompt=_PROMPT, call=call)
        second = await reads.surface(harness.store.connection, prompt=_PROMPT, call=call)
        assert first == second
        assert first != ""


async def test_a_stale_snapshot_when_the_event_is_written_is_retryable_contention(
    tmp_path: Path,
) -> None:
    """One read is one transaction, so writing the instrumentation is a WAL snapshot upgrade — and a
    write committed elsewhere mid-call refuses it. `architecture.md` §Errors already defines
    `store_busy` to cover exactly that stale-snapshot case, and the caller may retry.

    Provoked for real and ordered by construction rather than raced: the other connection's commit
    is driven from inside the call, after the arms have taken their snapshot and before the event
    insert.
    """
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist=f"{_TERM} matters", content="in CI only")
        async with aiosqlite.connect(harness.store.path) as other:

            async def commit_elsewhere_first(*args: object, **kwargs: object) -> object:
                retrieved = await real_retrieve(*args, **kwargs)  # type: ignore[arg-type]
                await other.execute("BEGIN IMMEDIATE")
                await other.execute(
                    "INSERT INTO meta (key, value) VALUES ('probe', 'other writer')"
                )
                await other.commit()
                return retrieved

            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(reads, "retrieve", commit_elsewhere_first)
                with pytest.raises(ZikaronError) as raised:
                    await reads.surface(
                        harness.store.connection, prompt=_PROMPT, call=harness.read_call()
                    )
            assert raised.value.code is ErrorCode.STORE_BUSY
            assert raised.value.data == {"verb": "surface"}


async def test_a_driver_failure_that_is_not_contention_has_no_zikaron_code(
    tmp_path: Path,
) -> None:
    """ "A read has no `index_failed`" — that code's contract names index maintenance and a
    rolled-back write, and a read performs neither, so anything but contention propagates as itself
    and the service answers with a protocol-level internal error.

    A real driver failure rather than a fabricated one: with the `event` table gone, the
    instrumentation insert raises `no such table`, which carries no contention result code.
    """
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist=f"{_TERM} matters", content="in CI only")
        await harness.store.connection.execute("DROP TABLE event")
        await harness.store.connection.commit()

        with pytest.raises(aiosqlite.OperationalError, match="event"):
            await reads.surface(harness.store.connection, prompt=_PROMPT, call=harness.read_call())


def _pool_row(uuid: str, *, active: bool = True, superseded_by: str | None = None) -> RankedMemory:
    return RankedMemory(
        row=PoolRow(
            uuid=uuid,
            tier=Tier.JOURNAL,
            gist=f"gist of {uuid}",
            active=active,
            superseded_by=superseded_by,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        ),
        fused_score=0.5,
        dense_rank=1,
        lexical_rank=None,
        best_distance=0.1,
    )


def test_the_block_is_empty_when_there_is_nothing_to_print() -> None:
    assert block.render([]) == ""


def test_the_block_numbers_from_one_in_the_order_given() -> None:
    printed = block.render([_pool_row("a"), _pool_row("b")])
    lines = printed.splitlines()
    assert lines[-2].startswith("1. [a]")
    assert lines[-1].startswith("2. [b]")


def test_the_block_refuses_a_row_push_cannot_retrieve() -> None:
    """There is exactly one label and it is the superseded one, because `include_retired` belongs to
    `search` alone — so an outright-retired row here is a defect in the caller rather than a case
    for the format. Refused rather than given an invented label: the label's whole content is the
    replacement's uuid, and this row has none by definition."""
    with pytest.raises(ValueError, match="retired outright"):
        block.render([_pool_row("a", active=False)])
