"""Fusion, demotion and ordering — `retrieval.md` §"The fused score", §"Total order",
§"Supersession".

Everything here is pure, so these tests need no store and can assert exact values. That matters more
than usual: the design's tie problem is about **bit-identical** fused scores (measured: every hybrid
query has at least one, and 12.5% have one inside the top five), so a test that compared scores
approximately would not be testing the case the total order exists for.

Two constructions produce exact ties on purpose. A **structural** tie is two rows each returned by
one arm at the same rank — the shape the report identifies as pervasive — which ties the score *and*
the best rank, leaving tier, recency and uuid to decide. A **powers-of-two** tie uses `rrf_k = 2`
with ranks 2 and 6+6, so `1/4 == 1/8 + 1/8` holds exactly in binary while the two rows differ in
best rank; that is how step 2 gets tested without relying on float luck.
"""

from collections.abc import Mapping, Sequence
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zikaron.core.errors import ErrorCode, RowState, ZikaronError
from zikaron.core.events import Demotion, StopReason
from zikaron.core.records.memory import Tier
from zikaron.core.retrieval import ranking
from zikaron.core.retrieval.arms import Arm, ArmOutcome, ArmRow
from zikaron.core.retrieval.ranking import Penalties, PoolRow, RankedMemory

_RRF_K: Final = 60
_DEPTH: Final = 50
_NO_PENALTY: Final = Penalties(superseded=1.0, retired=1.0)
_HALF: Final = Penalties(superseded=0.5, retired=0.25)


def _row(
    uuid: str,
    *,
    tier: Tier = Tier.JOURNAL,
    active: bool = True,
    superseded_by: str | None = None,
    created_at: str = "2026-01-01T00:00:00+00:00",
) -> PoolRow:
    return PoolRow(
        uuid=uuid,
        tier=tier,
        gist=f"gist of {uuid}",
        active=active,
        superseded_by=superseded_by,
        created_at=created_at,
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _outcome(arm: Arm, uuids: Sequence[str], *, fusion_depth: int = _DEPTH) -> ArmOutcome:
    """One arm that returned `uuids` in order and reached the end of its cursor.

    A distance is attached on the dense side only, ascending with the rank, so a test can tell the
    rolled-up distance apart from the rank it produced.
    """
    return ArmOutcome(
        arm=arm,
        rows=tuple(
            ArmRow(uuid=uuid, rank=rank, distance=None if arm is Arm.LEXICAL else 0.1 * rank)
            for rank, uuid in enumerate(uuids, start=1)
        ),
        fusion_depth=fusion_depth,
        depth_reached=len(uuids),
        stop_reason=StopReason.INDEX_EXHAUSTED,
    )


def _ranked(
    *,
    dense: Sequence[str] = (),
    lexical: Sequence[str] = (),
    rows: Mapping[str, PoolRow],
    rrf_k: int = _RRF_K,
    penalties: Penalties = _NO_PENALTY,
) -> tuple[RankedMemory, ...]:
    return ranking.rank(
        dense=_outcome(Arm.DENSE, dense),
        lexical=_outcome(Arm.LEXICAL, lexical),
        rows=rows,
        rrf_k=rrf_k,
        penalties=penalties,
    )


def _order(pool: Sequence[RankedMemory]) -> list[str]:
    return [ranked.row.uuid for ranked in pool]


def test_the_formula_is_one_over_k_plus_a_one_based_rank() -> None:
    """The formula every quality figure in `retrieval.md` was measured through. Rebasing the rank to
    0 would leave `rrf_k = 60` naming a different denominator, so the config default and the
    measurements would stop describing the same pipeline with nothing failing."""
    assert ranking.rrf_score([1], rrf_k=60) == 1.0 / 61
    assert ranking.rrf_score([1, 1], rrf_k=60) == 2.0 / 61
    assert ranking.rrf_score([], rrf_k=60) == 0.0


def test_a_row_both_arms_returned_scores_the_sum_of_both_terms() -> None:
    rows = {"a": _row("a")}
    (only,) = _ranked(dense=["a"], lexical=["a"], rows=rows)
    assert only.fused_score == 2.0 / 61
    assert only.dense_rank == 1
    assert only.lexical_rank == 1


def test_an_arm_that_missed_a_row_contributes_nothing_rather_than_a_worst_rank() -> None:
    """Which is what makes the measured arm-agreement defect a fact about the score rather than
    about a convention: a row only one arm found keeps that arm's term and no other."""
    rows = {"a": _row("a")}
    (only,) = _ranked(dense=["a"], rows=rows)
    assert only.fused_score == 1.0 / 61
    assert only.lexical_rank is None
    assert only.best_distance == pytest.approx(0.1)


def test_best_rank_is_the_minimum_over_the_arms_that_returned_the_row() -> None:
    rows = {"a": _row("a"), "b": _row("b")}
    pool = _ranked(dense=["b", "a"], lexical=["a"], rows=rows)
    by_uuid = {ranked.row.uuid: ranked for ranked in pool}
    assert by_uuid["a"].best_rank == 1
    assert by_uuid["b"].best_rank == 1
    assert by_uuid["a"].dense_rank == 2
    assert by_uuid["a"].lexical_rank == 1


def test_a_row_missing_from_the_pool_load_is_dropped_rather_than_guessed_at() -> None:
    """One read transaction makes this unreachable; it is handled rather than assumed away, and
    handled by omission, since there is nothing truthful to report about a row that is not there."""
    pool = _ranked(dense=["a", "vanished"], rows={"a": _row("a")})
    assert _order(pool) == ["a"]


@pytest.mark.parametrize(
    ("active", "superseded_by", "expected_state", "expected_demotion", "factor"),
    [
        (True, None, RowState.LIVE, None, 1.0),
        (False, "other", RowState.SUPERSEDED, Demotion.SUPERSEDED, 0.5),
        (False, None, RowState.RETIRED, Demotion.RETIRED, 0.25),
    ],
)
def test_each_row_state_gets_its_own_penalty(
    active: bool,
    superseded_by: str | None,
    expected_state: RowState,
    expected_demotion: Demotion | None,
    factor: float,
) -> None:
    """Two separate config keys with equal defaults, kept separate out of honesty rather than
    symmetry — nothing measured distinguishes the two demoted states — so they are given *different*
    values here, which is the only way to see that each is applied to its own state."""
    rows = {"a": _row("a", active=active, superseded_by=superseded_by)}
    (only,) = _ranked(dense=["a"], rows=rows, penalties=_HALF)
    assert only.row.state is expected_state
    assert only.row.demotion is expected_demotion
    assert only.demoted == (expected_demotion is not None)
    assert only.fused_score == (1.0 / 61) * factor


def test_the_penalties_cannot_compound_because_the_states_are_exclusive() -> None:
    """`superseded_by` is either null or not, so no row can take both multipliers. Asserted on the
    type rather than on one fixture: the property is what keeps a twice-demoted row impossible."""
    superseded = _row("a", active=False, superseded_by="b")
    retired = _row("b", active=False)
    assert (superseded.demotion, retired.demotion) == (Demotion.SUPERSEDED, Demotion.RETIRED)
    assert _HALF.factor(superseded.demotion) == 0.5
    assert _HALF.factor(retired.demotion) == 0.25


def test_a_demoted_row_can_still_outrank_a_live_one_on_a_large_enough_score_gap() -> None:
    """The penalty is a multiplier, not a partition: D25 demotes rather than hides, and the measured
    83-100% presence of a harmful superseded record in the injected five is the reason the block
    labels rows instead of relying on the penalty to bury them."""
    rows = {"weak": _row("weak"), "strong": _row("strong", active=False, superseded_by="weak")}
    pool = _ranked(dense=["strong"], lexical=["strong"], rows=rows, penalties=_HALF)
    pool_with_weak = _ranked(
        dense=["strong", "weak"], lexical=["strong"], rows=rows, penalties=_HALF
    )
    assert _order(pool) == ["strong"]
    assert _order(pool_with_weak)[0] == "weak", "the repair puts the replacement first"
    assert pool_with_weak[1].fused_score == (2.0 / 61) * 0.5


def test_step_1_orders_by_fused_score_descending() -> None:
    rows = {"a": _row("a"), "b": _row("b")}
    pool = _ranked(dense=["a", "b"], lexical=["a"], rows=rows)
    assert _order(pool) == ["a", "b"]


def test_step_2_prefers_the_row_one_arm_ranked_first() -> None:
    """`rrf_k = 2` with one arm's rank 2 against both arms' rank 6 makes `1/4 == 1/8 + 1/8` hold
    **exactly** in binary, so the scores tie bit-identically and the best rank is what decides. A
    document one arm ranked first is a better bet than one both arms ranked sixth."""
    fillers = [f"f{index}" for index in range(9)]
    rows = {name: _row(name) for name in ("sharp", "broad", *fillers)}
    pool = _ranked(
        dense=[fillers[0], "sharp", fillers[1], fillers[2], fillers[3], "broad"],
        lexical=[fillers[4], fillers[5], fillers[6], fillers[7], fillers[8], "broad"],
        rows=rows,
        rrf_k=2,
    )
    scores = {ranked.row.uuid: ranked.fused_score for ranked in pool}
    assert scores["sharp"] == scores["broad"] == 0.25
    order = _order(pool)
    assert order.index("sharp") < order.index("broad")


def test_step_3_prefers_long_term_over_journal() -> None:
    """A structural tie — each row returned by one arm at the same rank — so the score and the best
    rank are identical and the tier is what decides. Consolidated prose has been reviewed by the
    consolidator; `~/Memory` reached the same tiebreak independently."""
    rows = {
        "j": _row("j", tier=Tier.JOURNAL),
        "l": _row("l", tier=Tier.LONG_TERM),
    }
    pool = _ranked(dense=["j"], lexical=["l"], rows=rows)
    assert [ranked.fused_score for ranked in pool] == [1.0 / 61, 1.0 / 61]
    assert _order(pool) == ["l", "j"]


def test_step_4_prefers_the_newer_row_inside_a_journal_block() -> None:
    rows = {
        "old": _row("old", created_at="2026-01-01T00:00:00+00:00"),
        "new": _row("new", created_at="2026-06-01T00:00:00+00:00"),
    }
    pool = _ranked(dense=["old"], lexical=["new"], rows=rows)
    assert _order(pool) == ["new", "old"]


def test_step_4_does_not_apply_to_long_term_rows() -> None:
    """D27's recency tiebreak is **journal-local**, and an earlier draft applied it to every tie.
    Since exact ties are pervasive rather than rare, that made the shipped ranking contradict the
    stated policy in executable behaviour: nothing about a long-term record's age is a claim about
    its truth, so two tied long-term rows fall through to `uuid`.

    The fixture is built so the two rules disagree — the *older* row sorts first by uuid — which is
    the only arrangement where a passing test distinguishes them.
    """
    rows = {
        "a-older": _row("a-older", tier=Tier.LONG_TERM, created_at="2026-01-01T00:00:00+00:00"),
        "b-newer": _row("b-newer", tier=Tier.LONG_TERM, created_at="2026-06-01T00:00:00+00:00"),
    }
    pool = _ranked(dense=["b-newer"], lexical=["a-older"], rows=rows)
    assert _order(pool) == ["a-older", "b-newer"]


def test_a_journal_row_and_a_long_term_row_never_compare_on_recency() -> None:
    """Which is what makes the constant recency key for long-term rows well defined: step 3 has
    already partitioned the remaining ties by tier, so the value is only ever compared against
    another long-term row's copy of it. Here the journal row is newer and still loses."""
    rows = {
        "journal": _row("journal", created_at="2026-06-01T00:00:00+00:00"),
        "long": _row("long", tier=Tier.LONG_TERM, created_at="2026-01-01T00:00:00+00:00"),
    }
    pool = _ranked(dense=["journal"], lexical=["long"], rows=rows)
    assert _order(pool) == ["long", "journal"]


def test_step_5_is_uuid_ascending() -> None:
    """Arbitrary, and that is the point: it guarantees a total order, so the same store and query
    always produce the same list."""
    rows = {"b": _row("b"), "a": _row("a")}
    pool = _ranked(dense=["b"], lexical=["a"], rows=rows)
    assert _order(pool) == ["a", "b"]


def test_rows_created_at_the_same_instant_fall_through_to_uuid() -> None:
    """Same-millisecond writes are the common case in a burst, so the recency step has to tolerate
    equal timestamps rather than assume distinct ones."""
    rows = {"b": _row("b"), "a": _row("a")}
    pool = _ranked(dense=["b"], lexical=["a"], rows=rows)
    assert _order(pool) == ["a", "b"]


def test_ranking_is_deterministic() -> None:
    rows = {name: _row(name) for name in ("a", "b", "c", "d")}
    first = _ranked(dense=["c", "a", "d"], lexical=["b", "a"], rows=rows)
    second = _ranked(dense=["c", "a", "d"], lexical=["b", "a"], rows=rows)
    assert first == second


def test_the_repair_puts_a_replacement_ahead_of_the_row_it_replaced() -> None:
    rows = {
        "old": _row("old", active=False, superseded_by="new"),
        "new": _row("new"),
    }
    pool = _ranked(dense=["old", "new"], lexical=["old"], rows=rows, penalties=_NO_PENALTY)
    assert _order(pool) == ["new", "old"]


def test_the_repair_resolves_a_chain_transitively() -> None:
    """`A -> B -> C` gives `C, B, A`: each row waits on at most one other, so the wait-for relation
    is a forest and the pass needs no graph walk of its own."""
    rows = {
        "a": _row("a", active=False, superseded_by="b"),
        "b": _row("b", active=False, superseded_by="c"),
        "c": _row("c"),
    }
    pool = _ranked(dense=["a", "b", "c"], rows=rows)
    assert _order(pool) == ["c", "b", "a"]


def test_the_repair_handles_two_rows_sharing_one_replacement() -> None:
    """The case that made "immediately above" unsatisfiable: `merge` absorbing `A` and `B` into `C`
    writes both edges, so no linear order can put `C` immediately above both. Precedence can."""
    rows = {
        "a": _row("a", active=False, superseded_by="c"),
        "b": _row("b", active=False, superseded_by="c"),
        "c": _row("c"),
    }
    pool = _ranked(dense=["a", "b", "c"], rows=rows)
    assert _order(pool)[0] == "c"
    assert set(_order(pool)[1:]) == {"a", "b"}


def test_a_replacement_absent_from_the_pool_blocks_nothing() -> None:
    """The repair reorders what retrieved; it cannot promote what did not. That limit is why the
    penalty exists too, and why D25 says ranking cannot fix this on its own."""
    rows = {"old": _row("old", active=False, superseded_by="elsewhere")}
    pool = _ranked(dense=["old"], rows=rows)
    assert _order(pool) == ["old"]


def test_the_repair_runs_before_the_cut_so_a_replacement_can_be_promoted_into_the_budget() -> None:
    """The pool this function returns is uncut, so a replacement that *lost on score* is already
    ahead of the row it replaces by the time the caller slices. That is the measured case the repair
    exists for: the correct answer is provably present and losing.

    Stated as the two facts that together mean promotion, rather than as one expected list: the
    replacement scores **less** than the row it replaces, and still precedes it — so a budget of two
    returns the replacement and leaves the superseded row out, which scoring alone would invert.
    """
    rows = {
        "old": _row("old", active=False, superseded_by="new"),
        "filler": _row("filler"),
        "new": _row("new"),
    }
    pool = _ranked(dense=["old", "filler", "new"], lexical=["old", "filler"], rows=rows)
    scores = {ranked.row.uuid: ranked.fused_score for ranked in pool}
    order = _order(pool)

    assert scores["new"] < scores["old"]
    assert order.index("new") < order.index("old")
    assert "new" in order[:2]
    assert "old" not in order[:2]


def test_a_cyclic_pool_is_refused_rather_than_answered_from() -> None:
    """Unreachable under invariant 6, which checks acyclicity on every edge write — so this is a
    corrupt store, and the honest answer is an error. Falling back to the pre-repair order would
    answer the query with a *plausible* list from a graph that cannot be trusted, which is the one
    outcome worse than raising, since putting the replacement first is the whole point."""
    rows = {
        "a": _row("a", active=False, superseded_by="b"),
        "b": _row("b", active=False, superseded_by="a"),
    }
    with pytest.raises(ZikaronError) as raised:
        _ranked(dense=["a", "b"], rows=rows)
    assert raised.value.code is ErrorCode.BAD_SUPERSESSION
    assert raised.value.data["reason"] == "cycle"


@given(
    better=st.integers(min_value=1, max_value=400),
    worse=st.integers(min_value=1, max_value=400),
    rrf_k=st.integers(min_value=1, max_value=1000),
)
def test_rrf_is_monotone_in_each_arms_rank(better: int, worse: int, rrf_k: int) -> None:
    """A property `coding-standards.md` §4 names outright. It is what makes the fused score a
    *ranking* rather than an arbitrary combination: no arm can improve a row's rank and lower its
    score, and no arm can worsen a rank and raise it."""
    if better > worse:
        better, worse = worse, better
    assert ranking.rrf_score([better], rrf_k=rrf_k) >= ranking.rrf_score([worse], rrf_k=rrf_k)
    assert ranking.rrf_score([better, better], rrf_k=rrf_k) >= ranking.rrf_score(
        [better, worse], rrf_k=rrf_k
    )


@given(
    ranks=st.lists(st.integers(min_value=1, max_value=400), min_size=1, max_size=2),
    rrf_k=st.integers(min_value=1, max_value=1000),
)
def test_every_arm_term_is_positive_so_being_found_never_hurts(
    ranks: list[int], rrf_k: int
) -> None:
    """The other half of monotonicity, and the one that keeps the arms complementary rather than
    competing: appearing in a second arm can only raise a row's score."""
    assert ranking.rrf_score(ranks, rrf_k=rrf_k) > 0.0
    assert ranking.rrf_score([*ranks, 400], rrf_k=rrf_k) > ranking.rrf_score(ranks, rrf_k=rrf_k)
