"""Which state a corpus reports, and the order the answers are decided in.

The order is behaviour rather than an implementation detail: during a rebuild two conditions are
genuinely true at once, and which one is reported decides whether a caller searches a corpus it
should not. So it is tested exhaustively — every pair of conditions, not a sample.
"""

import dataclasses
import itertools
import re
from collections.abc import Iterator
from typing import Final

import pytest

from tests.design_tables import section_lines, table_with_columns
from zikaron.core.knowledge import meta
from zikaron.core.knowledge.state import (
    PRECEDENCE,
    KnowledgeState,
    StateInputs,
    never_built,
    resolve,
)

#: Every input `resolve` decides from, read off the type rather than written out — so a new one
#: fails here, loudly and everywhere, instead of being silently left out of the exhaustive sweep
#: below. That sweep is the whole value of this file, and it is only exhaustive over what it knows.
_DOCUMENT: Final = "knowledge-index.md"
_HEADING: Final = "### 8.5 `zikaron_knowledge_list` and `zikaron_knowledge_status`"
_BACKTICKED: Final = re.compile(r"`([^`]+)`")

#: The cardinal words a cause count could reasonably be written as, so the guard reads the prose
#: rather than requiring the prose to be written as a digit.
_CARDINALS: Final = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

_CONDITIONS = tuple(field.name for field in dataclasses.fields(StateInputs))

#: Which state each condition produces when it is the only one true. Compared against `_CONDITIONS`
#: by a test, because a condition missing from here would simply not be swept.
_ALONE = {
    "unreadable": KnowledgeState.ERROR,
    "database_absent": KnowledgeState.REINDEX_REQUIRED,
    "root_missing": KnowledgeState.ROOT_MISSING,
    "encoder_mismatch": KnowledgeState.REINDEX_REQUIRED,
    "width_mismatch": KnowledgeState.REINDEX_REQUIRED,
    "never_built": KnowledgeState.REINDEX_REQUIRED,
    "indexing": KnowledgeState.INDEXING,
}


def test_every_input_has_a_state_of_its_own_recorded() -> None:
    """The guard on the sweep. An input absent from `_ALONE` would be absent from every combination
    the exhaustive test generates, so the test would go on passing over a smaller space."""
    assert set(_ALONE) == set(_CONDITIONS)


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
    """Exhaustive over every combination rather than a sample, because the whole content of this
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


class TestTheDesignSaysWhatThisModuleDoes:
    """The state table is the row a reader of `list`'s output goes to, and it is where the cause
    count drifted once already: §8.4 was rewritten to four and the table forty lines below went on
    saying three, through a whole review round. Counting the causes mechanically is the count-first
    discipline this corpus prescribes for that class, applied to the one enumeration that has
    actually slipped."""

    def _row(self, state: KnowledgeState) -> str:
        table = table_with_columns(_DOCUMENT, _HEADING, ("`state`", "meaning"))
        rows = [row for row in table if row["`state`"].strip("`") == state.value]
        if len(rows) != 1:
            pytest.fail(f"{len(rows)} rows for {state.value!r} in {_DOCUMENT} / {_HEADING}")
        return rows[0]["meaning"]

    def test_the_table_lists_every_state_and_no_other(self) -> None:
        table = table_with_columns(_DOCUMENT, _HEADING, ("`state`", "meaning"))
        listed = {row["`state`"].strip("`") for row in table}
        assert listed == {state.value for state in KnowledgeState}

    def test_the_precedence_sentence_matches_the_order_this_module_applies(self) -> None:
        """Stated as prose in the design and as a tuple here, and the order is behaviour: it decides
        which of two true conditions a caller is told about."""
        sentence = next(
            line
            for line in section_lines(_DOCUMENT, _HEADING)
            if line.startswith("**Precedence, top-down:")
        )
        assert _BACKTICKED.findall(sentence) == [state.value for state in PRECEDENCE]

    def test_the_stated_cause_count_is_the_number_of_causes_there_are(self) -> None:
        """The exact drift this guards: a cardinal word in prose against the inputs that actually
        produce the state."""
        meaning = self._row(KnowledgeState.REINDEX_REQUIRED)
        stated = next(_CARDINALS[word] for word in meaning.split() if word.lower() in _CARDINALS)
        causes = sum(1 for state in _ALONE.values() if state is KnowledgeState.REINDEX_REQUIRED)
        assert stated == causes
