"""Which state a corpus reports, and the order the answers are decided in.

The order is behaviour rather than an implementation detail: during a rebuild two conditions are
genuinely true at once, and which one is reported decides whether a caller searches a corpus it
should not. So it is tested exhaustively — every pair of conditions, not a sample.
"""

import itertools
from collections.abc import Iterator

import pytest

from zikaron.core.knowledge import meta
from zikaron.core.knowledge.state import (
    PRECEDENCE,
    KnowledgeState,
    StateInputs,
    never_built,
    resolve,
)

_CONDITIONS = (
    "unreadable",
    "database_absent",
    "root_missing",
    "encoder_mismatch",
    "never_built",
    "indexing",
)

#: Which state each condition produces when it is the only one true.
_ALONE = {
    "unreadable": KnowledgeState.ERROR,
    "database_absent": KnowledgeState.REINDEX_REQUIRED,
    "root_missing": KnowledgeState.ROOT_MISSING,
    "encoder_mismatch": KnowledgeState.REINDEX_REQUIRED,
    "never_built": KnowledgeState.REINDEX_REQUIRED,
    "indexing": KnowledgeState.INDEXING,
}


def _inputs(*true: str) -> StateInputs:
    return StateInputs(**{condition: condition in true for condition in _CONDITIONS})


def _all_combinations() -> Iterator[tuple[str, ...]]:
    for size in range(len(_CONDITIONS) + 1):
        yield from itertools.combinations(_CONDITIONS, size)


def test_nothing_wrong_is_ok() -> None:
    assert resolve(_inputs()) is KnowledgeState.OK


@pytest.mark.parametrize("condition", _CONDITIONS)
def test_each_condition_alone_produces_its_own_state(condition: str) -> None:
    assert resolve(_inputs(condition)) is _ALONE[condition]


@pytest.mark.parametrize("conditions", list(_all_combinations()))
def test_the_reported_state_is_always_the_highest_precedence_one_that_holds(
    conditions: tuple[str, ...],
) -> None:
    """Exhaustive over all 64 combinations rather than a sample, because the whole content of this
    function is what happens when several conditions hold together."""
    expected = KnowledgeState.OK
    for condition in conditions:
        candidate = _ALONE[condition]
        if PRECEDENCE.index(candidate) < PRECEDENCE.index(expected):
            expected = candidate
    assert resolve(_inputs(*conditions)) is expected


def test_a_corpus_being_rebuilt_reports_that_it_cannot_be_trusted_rather_than_its_progress() -> (
    None
):
    """The case the ordering exists for: a build is genuinely running *and* the corpus cannot be
    trusted. Reporting progress would invite a search the corpus cannot honestly answer."""
    assert resolve(_inputs("encoder_mismatch", "indexing")) is KnowledgeState.REINDEX_REQUIRED
    assert resolve(_inputs("never_built", "indexing")) is KnowledgeState.REINDEX_REQUIRED


def test_an_unreadable_database_outranks_everything() -> None:
    """A refresh does not obviously repair a corrupt file, so it must not be reported as something
    a refresh fixes — an operator needs the difference."""
    assert resolve(_inputs(*_CONDITIONS)) is KnowledgeState.ERROR


def test_the_precedence_lists_every_state_exactly_once() -> None:
    """A state missing from the order would be unreachable; one listed twice would make the
    comparison above depend on which position was found first."""
    assert sorted(PRECEDENCE, key=str) == sorted(KnowledgeState, key=str)
    assert len(set(PRECEDENCE)) == len(PRECEDENCE)


def test_a_corpus_is_unbuilt_until_a_completion_instant_is_recorded() -> None:
    """Read as a persisted fact rather than as an emptiness test, because a first build that
    crashed after committing some files has rows — and reporting a corpus trustworthy on the
    strength of having *some* rows would claim a currency nothing backs."""
    assert never_built({})
    assert not never_built({meta.LAST_SCAN_COMPLETED_AT_KEY: "2026-01-01T00:00:00+00:00"})
