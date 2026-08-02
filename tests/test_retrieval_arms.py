"""The two arms and their termination reporting — `schema.md` invariant 20, `retrieval.md` §"The
dense arm's overfetch loop, and the three ways it can stop".

Invariant 20's content is that an arm's stop reason is checkable against the depth printed beside
it, so the tests come in two layers. The first constructs `ArmOutcome` directly and asserts that
every inconsistent pair is **refused** — the invariant is enforced where the claim is made, not
where it is logged, so an arm that could not classify itself honestly cannot exist to be reported.
The second runs the real arms against a real store on fixtures sized to land on each reason in turn,
which is what shows the classification is reachable rather than merely well formed.

Both arms are run against real indexes: a stop reason is a statement about what `vec0` and FTS5
returned, and the exact bm25 tie the uuid tiebreak exists for is reproducible only against the real
tokenizer and ranking function.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from tests import retrieval_fixtures as fx
from zikaron.core.events import StopReason
from zikaron.core.retrieval import arms
from zikaron.core.retrieval.arms import MAX_DOUBLINGS, Arm, ArmOutcome, ArmRow
from zikaron.core.retrieval.eligibility import CONSUMER_FILTERS, Consumer, Scope

_SURFACE: Final = Scope(Consumer.SURFACE)

#: One term every row of the eligibility matrix carries, so a single arm can see the whole
#: population.
_SHARED: Final = "eligibilitymatrix"


def _outcome(
    *,
    arm: Arm = Arm.DENSE,
    fusion_depth: int = 2,
    depth_reached: int | None = 2,
    stop_reason: StopReason | None = StopReason.INDEX_EXHAUSTED,
    n_rows: int | None = None,
) -> ArmOutcome:
    kept = n_rows if n_rows is not None else min(depth_reached or 0, fusion_depth)
    return ArmOutcome(
        arm=arm,
        rows=tuple(ArmRow(uuid=f"u{index}", rank=index + 1) for index in range(kept)),
        fusion_depth=fusion_depth,
        depth_reached=depth_reached,
        stop_reason=stop_reason,
    )


def test_a_consistent_outcome_is_accepted() -> None:
    assert _outcome().stop_reason is StopReason.INDEX_EXHAUSTED


def test_a_depth_without_a_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="must be null together"):
        _outcome(stop_reason=None)


def test_a_reason_without_a_depth_is_refused() -> None:
    with pytest.raises(ValueError, match="must be null together"):
        _outcome(depth_reached=None, n_rows=0)


def test_a_skipped_arm_reports_both_fields_null_and_no_rows() -> None:
    """The one case invariant 20's "null iff null" clause exists for. Zero and `index_exhausted`
    would together assert the arm read the index and found nothing, which a skipped arm did not."""
    skipped = ArmOutcome.skipped(fusion_depth=50)
    assert skipped.arm is Arm.LEXICAL
    assert skipped.depth_reached is None
    assert skipped.stop_reason is None
    assert skipped.rows == ()


def test_the_dense_arm_cannot_be_skipped() -> None:
    """It always runs, which is what makes "a prompt of pure punctuation still gets an answer" true.
    A null/null dense pair is representable and would be a false report, so it is refused."""
    with pytest.raises(ValueError, match="only the lexical arm can be skipped"):
        ArmOutcome(arm=Arm.DENSE, rows=(), fusion_depth=50, depth_reached=None, stop_reason=None)


def test_a_skipped_arm_carrying_rows_is_refused() -> None:
    """A depth of zero told two ways: an outcome that reports no depth while holding fused rows
    claims to have contributed memories it never admits retrieving."""
    with pytest.raises(ValueError, match="can fuse no rows"):
        ArmOutcome(
            arm=Arm.LEXICAL,
            rows=(ArmRow(uuid="u1", rank=1),),
            fusion_depth=50,
            depth_reached=None,
            stop_reason=None,
        )


def test_a_depth_beyond_the_probe_target_is_refused() -> None:
    with pytest.raises(ValueError, match="exceeds probe target"):
        _outcome(depth_reached=4, n_rows=2)


@pytest.mark.parametrize(
    ("depth_reached", "stop_reason"),
    [
        (3, StopReason.INDEX_EXHAUSTED),
        (3, StopReason.PROBE_CAP_HIT),
        (2, StopReason.DEPTH_REACHED),
        (0, StopReason.DEPTH_REACHED),
    ],
)
def test_a_reason_the_depth_contradicts_is_refused(
    depth_reached: int, stop_reason: StopReason
) -> None:
    """`depth_reached` **iff** the depth is exactly `fusion_depth + 1`, in both directions.

    Both directions matter and only one is obvious. An arm claiming a cut it did not make overstates
    what the bound did; an arm that found the surplus and then called it exhaustion understates what
    the store holds. The surplus row exists precisely so neither is a matter of the writer's word.
    """
    with pytest.raises(ValueError, match="disagrees with"):
        _outcome(depth_reached=depth_reached, stop_reason=stop_reason, n_rows=2)


def test_the_lexical_arm_may_not_claim_a_capped_probe() -> None:
    """`probe_cap_hit` is unreachable on an arm with no probe to cap — a consequence of the arm
    being one limited statement over an ordered cursor, not an assumption about the data."""
    with pytest.raises(ValueError, match="no probe to cap"):
        _outcome(arm=Arm.LEXICAL, depth_reached=1, stop_reason=StopReason.PROBE_CAP_HIT, n_rows=1)


def test_an_outcome_whose_row_count_disagrees_with_its_depth_is_refused() -> None:
    """The number fused is `min(depth, fusion_depth)`, which is what makes the recorded depth a
    statement about the arm rather than about the cut applied to it."""
    with pytest.raises(ValueError, match="rows fused from depth_reached"):
        _outcome(depth_reached=2, n_rows=1)


def test_an_arm_whose_ranks_are_not_one_based_is_refused() -> None:
    """The rank base is load-bearing and silently so: rebasing to 0 leaves every arm's internal
    order unchanged while changing every fused score, so `rrf_k = 60` would name a different
    denominator than the one every measured figure came from. Nothing downstream can see a uniform
    shift, which is why the ranks are checked where they are made."""
    with pytest.raises(ValueError, match=r"ranks must be 1\.\.2"):
        ArmOutcome(
            arm=Arm.DENSE,
            rows=(ArmRow(uuid="u0", rank=0), ArmRow(uuid="u1", rank=1)),
            fusion_depth=2,
            depth_reached=2,
            stop_reason=StopReason.INDEX_EXHAUSTED,
        )


def test_an_arm_with_a_gap_in_its_ranks_is_refused() -> None:
    with pytest.raises(ValueError, match=r"ranks must be 1\.\.2"):
        ArmOutcome(
            arm=Arm.LEXICAL,
            rows=(ArmRow(uuid="u1", rank=1), ArmRow(uuid="u3", rank=3)),
            fusion_depth=2,
            depth_reached=2,
            stop_reason=StopReason.INDEX_EXHAUSTED,
        )


@pytest.mark.parametrize("expected_arm", [Arm.DENSE, Arm.LEXICAL])
async def test_both_arms_number_their_rows_from_one(tmp_path: Path, expected_arm: Arm) -> None:
    """The same rule as the guard above, observed on the real statements rather than constructed."""
    async with fx.harness(tmp_path) as harness:
        for index in range(3):
            await harness.write(gist=f"g{index} PGHOST", content=f"content {index}")
        if expected_arm is Arm.DENSE:
            outcome = await arms.dense_arm(
                harness.store.connection,
                vector=fx.query_vector_for("g0 PGHOST", "content 0"),
                scope=_SURFACE,
                fusion_depth=50,
                chunk_overfetch=8,
            )
        else:
            outcome = await arms.lexical_arm(
                harness.store.connection,
                expression='"PGHOST"',
                scope=_SURFACE,
                fusion_depth=50,
            )
        assert [row.rank for row in outcome.rows] == [1, 2, 3]


def test_cosine_conversion_is_exact_at_both_ends() -> None:
    """`cos = 1 - d^2/2` over unit vectors: coincident is 1.0, orthogonal 0.0 at `d = sqrt(2)`."""
    assert arms.cosine_from_distance(0.0) == 1.0
    assert arms.cosine_from_distance(2.0**0.5) == pytest.approx(0.0)


async def test_an_empty_store_reports_a_covered_probe_rather_than_a_silent_zero(
    tmp_path: Path,
) -> None:
    """`chunk_count` is 0, so the probe is trivially covered: depth 0 and `index_exhausted`, which
    is the true eligible total rather than a short answer of unknown provenance."""
    async with fx.harness(tmp_path) as harness:
        outcome = await arms.dense_arm(
            harness.store.connection,
            vector=fx.query_vector_for("nothing", "here"),
            scope=_SURFACE,
            fusion_depth=50,
            chunk_overfetch=8,
        )
        assert outcome.depth_reached == 0
        assert outcome.stop_reason is StopReason.INDEX_EXHAUSTED
        assert outcome.rows == ()


async def test_equality_is_exhaustion_not_a_cut(tmp_path: Path) -> None:
    """A store holding exactly `fusion_depth` eligible memories has had nothing cut and has nothing
    more to give, so equality is exhaustion. Calling it a cut would assert "more may exist" in the
    one case where the arm has provably returned everything."""
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist="alpha", content="first memory")
        await harness.write(gist="beta", content="second memory")
        outcome = await arms.dense_arm(
            harness.store.connection,
            vector=fx.query_vector_for("alpha", "first memory"),
            scope=_SURFACE,
            fusion_depth=2,
            chunk_overfetch=8,
        )
        assert outcome.depth_reached == 2
        assert outcome.stop_reason is StopReason.INDEX_EXHAUSTED
        assert len(outcome.rows) == 2


async def test_a_surplus_licenses_depth_reached_and_outranks_coverage(tmp_path: Path) -> None:
    """Surplus first, so exactly one reason applies: the extra row *proves* an eligible memory was
    cut, whether or not the probe also happened to read every chunk — and here it did."""
    async with fx.harness(tmp_path) as harness:
        for index in range(3):
            await harness.write(gist=f"g{index}", content=f"content {index}")
        outcome = await arms.dense_arm(
            harness.store.connection,
            vector=fx.query_vector_for("g0", "content 0"),
            scope=_SURFACE,
            fusion_depth=2,
            chunk_overfetch=8,
        )
        assert outcome.depth_reached == 3
        assert outcome.stop_reason is StopReason.DEPTH_REACHED
        assert len(outcome.rows) == 2


async def test_an_uncovered_probe_with_no_surplus_reports_completeness_unknown(
    tmp_path: Path,
) -> None:
    """`probe_cap_hit` is the field to watch when tuning `chunk_overfetch`, and it is not an error.

    Built to be genuinely uncovered: the doublings run `1, 2, 4, 8, 16` chunks against an index of
    eighteen, and all but one memory is retired outright, so the arm finds no surplus *and* leaves
    index unprobed. Reporting that as exhaustion would make a mis-set `chunk_overfetch`
    indistinguishable from a small store working correctly.
    """
    async with fx.harness(tmp_path) as harness:
        kept = await harness.write(gist="kept", content="the one eligible memory")
        for index in range(MAX_DOUBLINGS**2 + 1):
            uuid = await harness.write(gist=f"gone{index}", content=f"retired {index}")
            await harness.retire(uuid)
        assert kept

        outcome = await arms.dense_arm(
            harness.store.connection,
            vector=fx.query_vector_for("kept", "the one eligible memory"),
            scope=_SURFACE,
            fusion_depth=1,
            chunk_overfetch=1,
        )
        assert outcome.depth_reached == 1
        assert outcome.stop_reason is StopReason.PROBE_CAP_HIT
        assert [row.uuid for row in outcome.rows] == [kept]


async def test_eligibility_is_applied_after_the_join(tmp_path: Path) -> None:
    """`vec0` cannot filter on `memory`'s columns, which is the whole reason the loop exists: a
    retired-outright row occupies chunk slots in the probe and must not occupy an arm slot."""
    async with fx.harness(tmp_path) as harness:
        live = await harness.write(gist="live", content="still true")
        gone = await harness.write(gist="gone", content="no longer true")
        await harness.retire(gone)
        outcome = await arms.dense_arm(
            harness.store.connection,
            vector=fx.query_vector_for("gone", "no longer true"),
            scope=_SURFACE,
            fusion_depth=50,
            chunk_overfetch=8,
        )
        assert [row.uuid for row in outcome.rows] == [live]


async def test_a_multi_chunk_memory_occupies_one_arm_slot_at_its_best_chunk(
    tmp_path: Path,
) -> None:
    """D28's rollup, which `indexing.md` calls mandatory rather than an optimization: without it a
    five-chunk memory can occupy all five injected slots.

    Two things are asserted together because either alone can pass while the rollup is wrong. The
    memory appears **once**, and its representative is its **third** chunk — the query vector is
    that chunk's own stored vector, so the memory can only reach distance 0 if `min` over its chunks
    is what the arm took. A rollup that used the first chunk, or that emitted one row per chunk,
    fails one of the two.

    The premise is asserted rather than assumed: `chunk_max_tokens` is lowered to its floor and the
    paragraphs sized so that no two fit together, because at the default 450 this fixture is one
    chunk and the whole test would be vacuous while still passing.
    """
    paragraphs = [" ".join(f"p{index}w{word}" for word in range(40)) for index in range(3)]
    async with fx.harness(tmp_path, overrides="[indexing]\nchunk_max_tokens = 64\n") as harness:
        gist = "many parts"
        chunked = await harness.write(gist=gist, content="\n\n".join(paragraphs))
        other = await harness.write(gist="other", content="unrelated prose")

        counted = await harness.store.connection.execute_fetchall(
            "SELECT count(*) FROM memory_chunk WHERE memory_uuid = ?", (chunked,)
        )
        assert int(next(iter(counted))[0]) == len(paragraphs)

        outcome = await arms.dense_arm(
            harness.store.connection,
            vector=fx.query_vector_for(gist, paragraphs[2]),
            scope=_SURFACE,
            fusion_depth=50,
            chunk_overfetch=8,
        )

        assert [row.uuid for row in outcome.rows] == [chunked, other]
        assert outcome.rows[0].distance == pytest.approx(0.0)
        assert outcome.depth_reached == 2


async def test_the_dense_arm_breaks_an_exact_distance_tie_on_uuid(tmp_path: Path) -> None:
    """Two memories with identical prose store identical vectors, so their distances tie exactly.

    Without the tiebreak their ranks — and therefore the `1/(k + rank)` each contributes — would
    fall to the query plan, which is nondeterminism one level below the fused-score ties the total
    order deals with.
    """
    async with fx.harness(tmp_path) as harness:
        gist, content = "duplicate", "the same prose twice"
        first = await harness.write(gist=gist, content=content)
        second = await harness.write(gist=gist, content=content)
        outcome = await arms.dense_arm(
            harness.store.connection,
            vector=fx.query_vector_for(gist, content),
            scope=_SURFACE,
            fusion_depth=50,
            chunk_overfetch=8,
        )
        tied = [row.uuid for row in outcome.rows]
        assert tied == sorted([first, second])
        assert outcome.rows[0].distance == outcome.rows[1].distance


async def _captured_sql(harness: fx.Harness, run: Callable[[], Awaitable[object]]) -> list[str]:
    """Every statement one arm sent to the store, captured by wrapping the connection's own method.

    Needed because an `ORDER BY` tiebreak is a clause whose *effect* is only observable when the
    engine's natural order disagrees with it — and on a tie SQLite is free to agree by accident,
    which is exactly what let a behavioural-only test pass with the clause deleted. So the clause is
    pinned directly, and the behavioural test beside it says what it is for.
    """
    statements: list[str] = []
    original = harness.store.connection.execute_fetchall

    async def recording(sql: str, parameters: object = None) -> object:
        statements.append(sql)
        return await original(sql, parameters)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(harness.store.connection, "execute_fetchall", recording)
        await run()
    return statements


async def test_the_dense_arm_asks_the_store_to_break_ties_on_uuid(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist="g", content="c")

        async def probe() -> object:
            return await arms.dense_arm(
                harness.store.connection,
                vector=fx.query_vector_for("g", "c"),
                scope=_SURFACE,
                fusion_depth=2,
                chunk_overfetch=8,
            )

        statements = await _captured_sql(harness, probe)
        knn = [sql for sql in statements if "MATCH" in sql]
        assert knn
        assert all("ORDER BY best ASC, c.memory_uuid ASC" in sql for sql in knn)


async def test_the_lexical_arm_asks_the_store_to_break_ties_on_uuid(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist="g", content="PGHOST")

        async def probe() -> object:
            return await arms.lexical_arm(
                harness.store.connection,
                expression='"PGHOST"',
                scope=_SURFACE,
                fusion_depth=2,
            )

        statements = await _captured_sql(harness, probe)
        assert any("ORDER BY bm25(memory_fts) ASC, m.uuid ASC" in sql for sql in statements)


async def test_the_dense_arm_is_deterministic(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        for index in range(5):
            await harness.write(gist=f"g{index}", content=f"content {index}")
        vector = fx.query_vector_for("g2", "content 2")
        first = await arms.dense_arm(
            harness.store.connection,
            vector=vector,
            scope=_SURFACE,
            fusion_depth=3,
            chunk_overfetch=8,
        )
        second = await arms.dense_arm(
            harness.store.connection,
            vector=vector,
            scope=_SURFACE,
            fusion_depth=3,
            chunk_overfetch=8,
        )
        assert first == second


@dataclass(frozen=True, slots=True)
class _Population:
    """One row of every state in both tiers, plus the row an internal query would be asking *from*.

    Named fields rather than a dict because every expectation below is written in terms of them, and
    a matrix whose expected sets were keyed by string would be one typo away from asserting nothing.
    """

    live_journal: str
    live_long_term: str
    superseded_journal: str
    superseded_long_term: str
    retired_journal: str
    retired_long_term: str
    querying: str


async def _every_row_state(harness: fx.Harness) -> _Population:
    """Build the population, all six states sharing one query term so one arm can see them all."""

    async def row(gist: str, *, tier: str) -> str:
        uuid = await harness.write(gist=f"{gist} {_SHARED}", content=f"{_SHARED} {gist}")
        if tier != "journal":
            await harness.set_tier(uuid, tier)
        return uuid

    live_journal = await row("live journal", tier="journal")
    live_long_term = await row("live long term", tier="long_term")
    superseded_journal = await row("superseded journal", tier="journal")
    superseded_long_term = await row("superseded long term", tier="long_term")
    retired_journal = await row("retired journal", tier="journal")
    retired_long_term = await row("retired long term", tier="long_term")
    querying = await row("the querying row", tier="journal")

    await harness.retire(superseded_journal, superseded_by=live_journal)
    await harness.retire(superseded_long_term, superseded_by=live_long_term)
    await harness.retire(retired_journal)
    await harness.retire(retired_long_term)
    return _Population(
        live_journal=live_journal,
        live_long_term=live_long_term,
        superseded_journal=superseded_journal,
        superseded_long_term=superseded_long_term,
        retired_journal=retired_journal,
        retired_long_term=retired_long_term,
        querying=querying,
    )


def _expected(consumer: Consumer, rows: _Population, *, include_retired: bool) -> set[str]:
    """The exact set `schema.md` §"Consumer filters" admits for one consumer, written out.

    Written as sets of named rows rather than derived from the code's own predicate, which is the
    whole point: a matrix computed from `CONSUMER_FILTERS` would agree with any filter the code
    happened to hold, including a wrong one.
    """
    eligible_by_default = {
        rows.live_journal,
        rows.live_long_term,
        rows.superseded_journal,
        rows.superseded_long_term,
        rows.querying,
    }
    everything = eligible_by_default | {rows.retired_journal, rows.retired_long_term}
    if consumer in {Consumer.SURFACE, Consumer.SEARCH}:
        return everything if include_retired else eligible_by_default
    if consumer is Consumer.DEDUP:
        # The base predicate ANDed with `active = 1`: live rows in either tier, minus the querying
        # row.
        return {rows.live_journal, rows.live_long_term}
    if consumer is Consumer.CONSOLIDATION:
        return {rows.live_long_term}
    return {rows.live_journal}


@pytest.mark.parametrize(
    ("consumer", "include_retired"),
    [
        (Consumer.SURFACE, False),
        (Consumer.SEARCH, False),
        (Consumer.SEARCH, True),
        (Consumer.DEDUP, False),
        (Consumer.CONSOLIDATION, False),
        (Consumer.ORPHAN, False),
    ],
)
async def test_every_consumer_admits_exactly_the_rows_the_design_gives_it(
    tmp_path: Path, consumer: Consumer, include_retired: bool
) -> None:
    """The done-when condition as a behavioural oracle: one predicate, five consumers, exact sets.

    Every row state appears in both tiers, so each filter has something it must exclude and
    something it must keep — which is what distinguishes `active = 1` from `active = 0`, `tier =
    'long_term'` from `tier = 'journal'`, and a conjunction from a disjunction. A test comparing the
    code's predicate against the code's own filter table could not tell any of those apart.
    """
    async with fx.harness(tmp_path) as harness:
        rows = await _every_row_state(harness)
        excludes_self = CONSUMER_FILTERS[consumer].excludes_self
        scope = Scope(
            consumer,
            include_retired=include_retired,
            exclude_uuid=rows.querying if excludes_self else None,
        )

        outcome = await arms.lexical_arm(
            harness.store.connection,
            expression=f'"{_SHARED}"',
            scope=scope,
            fusion_depth=50,
        )

        expected = _expected(consumer, rows, include_retired=include_retired)
        if excludes_self:
            expected -= {rows.querying}
        assert {row.uuid for row in outcome.rows} == expected


async def test_the_dense_arm_admits_the_same_set_as_the_lexical_one(tmp_path: Path) -> None:
    """One predicate, both arms. The matrix above runs on the lexical arm because one FTS row is one
    memory; this asserts the dense arm is filtered identically, which is the half of "one
    eligibility implementation" that a single-arm matrix would leave to inspection."""
    async with fx.harness(tmp_path) as harness:
        rows = await _every_row_state(harness)
        for consumer in (Consumer.SURFACE, Consumer.CONSOLIDATION, Consumer.ORPHAN):
            excludes_self = CONSUMER_FILTERS[consumer].excludes_self
            scope = Scope(consumer, exclude_uuid=rows.querying if excludes_self else None)
            dense = await arms.dense_arm(
                harness.store.connection,
                vector=fx.query_vector_for(f"live journal {_SHARED}", f"{_SHARED} live journal"),
                scope=scope,
                fusion_depth=50,
                chunk_overfetch=8,
            )
            lexical = await arms.lexical_arm(
                harness.store.connection,
                expression=f'"{_SHARED}"',
                scope=scope,
                fusion_depth=50,
            )
            assert {row.uuid for row in dense.rows} == {row.uuid for row in lexical.rows}, consumer


async def test_the_lexical_arm_reports_exhaustion_when_the_cursor_ends(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist="pghost", content="integration tests need PGHOST set")
        outcome = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=50
        )
        assert outcome.depth_reached == 1
        assert outcome.stop_reason is StopReason.INDEX_EXHAUSTED


async def test_the_lexical_arm_reports_a_cut_when_it_finds_its_surplus_row(
    tmp_path: Path,
) -> None:
    async with fx.harness(tmp_path) as harness:
        for index in range(3):
            await harness.write(gist=f"g{index}", content=f"PGHOST matters {index}")
        outcome = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=2
        )
        assert outcome.depth_reached == 3
        assert outcome.stop_reason is StopReason.DEPTH_REACHED
        assert len(outcome.rows) == 2


async def test_the_lexical_arm_orders_best_first(tmp_path: Path) -> None:
    """`bm25()` is negative in SQLite with better matches more negative, so ascending is best-first.
    Getting the sign wrong would invert the arm silently — every row still returned, in reverse."""
    async with fx.harness(tmp_path) as harness:
        focused = await harness.write(gist="PGHOST", content="PGHOST PGHOST")
        diluted = await harness.write(
            gist="setup notes", content="a long note mentioning PGHOST once " + "filler " * 40
        )
        outcome = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=50
        )
        assert [row.uuid for row in outcome.rows] == [focused, diluted]


async def test_the_lexical_arm_breaks_an_exact_bm25_tie_on_uuid(tmp_path: Path) -> None:
    """The measured case: two documents matching one term at equal length return bit-identical
    `bm25()` values, so this tiebreak is what any claim of determinism on this arm rests on."""
    async with fx.harness(tmp_path) as harness:
        gist, content = "same", "PGHOST appears here"
        first = await harness.write(gist=gist, content=content)
        second = await harness.write(gist=gist, content=content)
        outcome = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=50
        )
        assert [row.uuid for row in outcome.rows] == sorted([first, second])


async def test_the_lexical_arm_applies_eligibility_and_the_consumer_filter(
    tmp_path: Path,
) -> None:
    """Two filters at once: a retired-outright row is excluded by the base predicate, and dedup's
    own `active = 1` also excludes the *superseded* row the base predicate would admit."""
    async with fx.harness(tmp_path) as harness:
        live = await harness.write(gist="live", content="PGHOST is set")
        replaced = await harness.write(gist="old", content="PGHOST was unset")
        gone = await harness.write(gist="gone", content="PGHOST irrelevant")
        await harness.retire(replaced, superseded_by=live)
        await harness.retire(gone)

        base = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=50
        )
        assert sorted(row.uuid for row in base.rows) == sorted([live, replaced])

        dedup = await arms.lexical_arm(
            harness.store.connection,
            expression='"PGHOST"',
            scope=Scope(Consumer.DEDUP, exclude_uuid="none-of-them"),
            fusion_depth=50,
        )
        assert [row.uuid for row in dedup.rows] == [live]


async def test_the_self_exclusion_removes_the_querying_row(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        querying = await harness.write(gist="self", content="PGHOST here")
        other = await harness.write(gist="other", content="PGHOST there")
        outcome = await arms.lexical_arm(
            harness.store.connection,
            expression='"PGHOST"',
            scope=Scope(Consumer.DEDUP, exclude_uuid=querying),
            fusion_depth=50,
        )
        assert [row.uuid for row in outcome.rows] == [other]


async def test_the_lexical_arm_is_deterministic(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        for index in range(4):
            await harness.write(gist=f"g{index}", content=f"PGHOST note {index}")
        first = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=3
        )
        second = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=3
        )
        assert first == second


async def test_a_query_matching_nothing_is_exhaustion_rather_than_an_error(
    tmp_path: Path,
) -> None:
    async with fx.harness(tmp_path) as harness:
        await harness.write(gist="unrelated", content="nothing to do with it")
        outcome = await arms.lexical_arm(
            harness.store.connection, expression='"PGHOST"', scope=_SURFACE, fusion_depth=50
        )
        assert outcome.rows == ()
        assert outcome.depth_reached == 0
        assert outcome.stop_reason is StopReason.INDEX_EXHAUSTED
