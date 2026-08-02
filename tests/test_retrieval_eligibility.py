"""The one eligibility predicate and the closed table of consumer filters, against `schema.md`.

`schema.md` §"Consumer filters" states the contract as *"a filter that is not in this table does not
exist"*, which is a claim about the whole package rather than about one function — so the guards
here are of two kinds. The table guards read the design document at test time and compare it against
`CONSUMER_FILTERS`, so an edit on either side fails; the structural guards assert that no other
module in `zikaron/core/retrieval` writes a row-state predicate into SQL at all, which is what makes
"the predicate has one implementation" checkable instead of merely intended.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from tests import design_tables
from zikaron.core.retrieval import eligibility
from zikaron.core.retrieval.eligibility import CONSUMER_FILTERS, Consumer, Scope

_ELIGIBILITY_HEADING: Final = "## Retrieval eligibility — one predicate, three row states"
_FILTERS_HEADING: Final = (
    "### Consumer filters — the base predicate, plus exactly one named filter per read path"
)
_STATE_COLUMNS: Final = ("State", "Rows", "Default retrieval", "`include_retired=true`")
_FILTER_COLUMNS: Final = ("Consumer", "Filter on top of `ELIGIBLE`", "Why this filter")

#: `schema.md`'s table names `fetch` to say it is **not** a predicate path, so it is deliberately
#: not a `Consumer`. Named here so the count check below asserts that reading rather than assuming
#: it.
_NOT_A_PREDICATE_PATH: Final = "fetch"

#: Every module of the retrieval package other than the one allowed to name a row state in SQL.
_PACKAGE: Final = Path(eligibility.__file__).parent


def _design_states() -> design_tables.Table:
    return design_tables.table_with_columns("schema.md", _ELIGIBILITY_HEADING, _STATE_COLUMNS)


def _design_filters() -> design_tables.Table:
    return design_tables.table_with_columns("schema.md", _FILTERS_HEADING, _FILTER_COLUMNS)


def _consumer_of(cell: str) -> str:
    """The consumer named by a table row's first cell, which the design decorates with prose.

    The cells read `push (\\`surface\\`)`, `**dedup candidates (D15)**`, and so on, so the guard
    matches the parenthesised or emphasised name a `Consumer` member is named after rather than the
    whole cell. Matching loosely here would be the wrong economy — it is the *set* of consumers this
    guard exists to pin — so the extraction is exact and a cell it cannot classify fails.
    """
    plain = cell.replace("*", "").replace("`", "").strip()
    for member in Consumer:
        if re.search(rf"\b{member.value}\b", plain):
            return member.value
    if plain.startswith(_NOT_A_PREDICATE_PATH):
        return _NOT_A_PREDICATE_PATH
    raise AssertionError(f"schema.md names a consumer this code has no member for: {cell!r}")


def test_design_table_and_code_name_the_same_consumers() -> None:
    """Every row of `schema.md`'s filter table is a `Consumer`, except `fetch`, which is stated not
    to be a predicate path at all. A sixth read path cannot appear on either side alone."""
    named = [_consumer_of(row["Consumer"]) for row in _design_filters()]
    assert sorted(named) == sorted([*(member.value for member in Consumer), _NOT_A_PREDICATE_PATH])
    assert set(CONSUMER_FILTERS) == set(Consumer)


def test_fetch_is_documented_as_not_a_predicate_path() -> None:
    """The reason `fetch` has no `Consumer` member is stated in the design, not assumed here.

    Guarding the *reason* and not only the absence: if the design ever gave `fetch` a real filter,
    the test above would still pass — the row would simply be classified as `fetch` again — while
    this one fails, which is the direction that matters.
    """
    row = next(r for r in _design_filters() if _consumer_of(r["Consumer"]) == _NOT_A_PREDICATE_PATH)
    assert "not a predicate path" in row["Filter on top of `ELIGIBLE`"]


@pytest.mark.parametrize(
    ("consumer", "expected_columns"),
    [
        (Consumer.SURFACE, ()),
        (Consumer.SEARCH, ()),
        (Consumer.DEDUP, ("active",)),
        (Consumer.CONSOLIDATION, ("tier", "active")),
        (Consumer.ORPHAN, ("tier", "active")),
    ],
)
def test_each_filter_constrains_the_columns_the_design_states_and_no_others(
    consumer: Consumer, expected_columns: tuple[str, ...]
) -> None:
    """Which columns each consumer may constrain, read off the design's own cell.

    Deliberately only half the check, and the weaker half: column *presence* cannot tell `active =
    1` from `active = 0`, nor a conjunction from a disjunction. What each filter *means* is pinned
    by the real-store matrix in `test_retrieval_arms.py`, which asserts the exact uuid set every
    consumer admits. This one exists for the other direction — a consumer silently gaining a column
    the design does not give it — which a behavioural test on a fixed fixture would not necessarily
    reveal.
    """
    row = next(r for r in _design_filters() if _consumer_of(r["Consumer"]) == consumer.value)
    stated = row["Filter on top of `ELIGIBLE`"]
    code = CONSUMER_FILTERS[consumer].predicate or ""
    for column in ("active", "tier"):
        assert (column in code) == (column in expected_columns), (consumer, column, code)
        if column in expected_columns:
            assert column in stated, (consumer, column, stated)
    if not expected_columns:
        assert CONSUMER_FILTERS[consumer].predicate is None
        assert "none" in stated.lower()


@pytest.mark.parametrize("consumer", [Consumer.DEDUP, Consumer.ORPHAN])
def test_the_two_self_excluding_consumers_are_the_two_the_design_says_exclude(
    consumer: Consumer,
) -> None:
    row = next(r for r in _design_filters() if _consumer_of(r["Consumer"]) == consumer.value)
    assert "exclude" in row["Filter on top of `ELIGIBLE`"]
    assert CONSUMER_FILTERS[consumer].excludes_self


@pytest.mark.parametrize("consumer", [Consumer.SURFACE, Consumer.CONSOLIDATION])
def test_a_consumer_the_design_states_no_exclusion_for_does_not_exclude(
    consumer: Consumer,
) -> None:
    row = next(r for r in _design_filters() if _consumer_of(r["Consumer"]) == consumer.value)
    assert "exclude" not in row["Filter on top of `ELIGIBLE`"]
    assert not CONSUMER_FILTERS[consumer].excludes_self


def test_include_retired_belongs_to_search_alone() -> None:
    """`schema.md`: "`include_retired` widens the predicate only to rows nobody replaced — the
    deliberate archaeology case — and stays on `search` alone." Read off the design's own row."""
    widening = [
        _consumer_of(row["Consumer"])
        for row in _design_filters()
        if "include_retired" in row["Filter on top of `ELIGIBLE`"]
    ]
    assert widening == [Consumer.SEARCH.value]
    allowed = [
        consumer.value
        for consumer, rule in CONSUMER_FILTERS.items()
        if rule.include_retired_allowed
    ]
    assert allowed == [Consumer.SEARCH.value]


def test_the_three_row_states_are_the_three_the_design_defines() -> None:
    """The base predicate admits exactly the two states the design marks eligible by default, and
    the widened one admits the third — read from the design's own state table."""
    states = {row["State"].replace("*", "").strip(): row for row in _design_states()}
    assert set(states) == {"live", "superseded", "retired outright"}
    assert "excluded" in states["retired outright"]["Default retrieval"]
    for state in ("live", "superseded"):
        assert "eligible" in states[state]["Default retrieval"]
    for row in states.values():
        assert "eligible" in row["`include_retired=true`"]


def test_base_clause_admits_live_and_superseded_and_excludes_retired_outright() -> None:
    clause, params = Scope(Consumer.SEARCH).where()
    assert params == ()
    assert clause == "(m.active = 1 OR m.superseded_by IS NOT NULL)"


def test_widened_clause_states_the_base_as_a_true_conjunct_rather_than_omitting_it() -> None:
    """A widening is visible as a widening. An absent `WHERE` and a deliberately widened one look
    identical to a reader of the SQL, and only one of them is a decision."""
    clause, _ = Scope(Consumer.SEARCH, include_retired=True).where()
    assert clause == "1 = 1"


def test_exclusion_is_a_bound_parameter_and_not_text() -> None:
    clause, params = Scope(Consumer.DEDUP, exclude_uuid="u1").where()
    assert params == ("u1",)
    assert "u1" not in clause
    assert clause.endswith("m.uuid <> ?")


def test_include_retired_on_a_consumer_that_may_not_widen_is_refused() -> None:
    """Refused at construction, because the failure is a silent widening rather than an error: a
    dedup search that admitted retired rows would offer the agent an `amend` it cannot perform."""
    with pytest.raises(ValueError, match="may not set include_retired"):
        Scope(Consumer.DEDUP, include_retired=True, exclude_uuid="u1")


def test_a_missing_self_exclusion_is_refused() -> None:
    with pytest.raises(ValueError, match="excludes_self=True"):
        Scope(Consumer.DEDUP)


def test_a_self_exclusion_on_a_consumer_that_states_none_is_refused() -> None:
    with pytest.raises(ValueError, match="excludes_self=False"):
        Scope(Consumer.SURFACE, exclude_uuid="u1")


def _sql_text(path: Path) -> str:
    """Every string literal in one module, concatenated — where SQL lives if it lives anywhere."""
    source = path.read_text(encoding="utf-8")
    literals = re.findall(r'"([^"\n]*)"', source) + re.findall(r"'([^'\n]*)'", source)
    return "\n".join(literals)


@pytest.mark.parametrize(
    "module",
    sorted(
        path.name
        for path in _PACKAGE.glob("*.py")
        if path.name not in {"eligibility.py", "__init__.py"}
    ),
)
def test_no_other_retrieval_module_writes_a_row_state_into_sql(module: str) -> None:
    """The done-when condition, structurally: one eligibility implementation, used by all consumers.

    A consumer cannot pass a filter — `Scope` takes a `Consumer`, not a predicate — but it could
    still *write* one into its own statement, and that is the drift this checks for. The scan looks
    at string literals only, so the prose explaining why a filter exists is not mistaken for one.

    `__init__` is exempt because it holds only a docstring, and `eligibility` is the module the rule
    is about. A hit here is not automatically a defect; it is a filter that has to be moved into the
    design's table first.
    """
    text = _sql_text(_PACKAGE / module)
    for banned in ("active =", "active=", "tier =", "tier=", "superseded_by IS"):
        assert banned not in text, f"{module} names a row state in SQL: {banned!r}"


def test_the_scan_above_can_actually_fail() -> None:
    """The guard is only worth having if it fires, so it is pointed at the module that must trip it.

    `eligibility.py` is exempt from the scan precisely because it *does* contain these fragments;
    running the same scan against it is what shows the scan is looking at the right thing rather
    than passing because it matches nothing anywhere.
    """
    text = _sql_text(_PACKAGE / "eligibility.py")
    assert "active = 1" in text
    assert "tier = 'long_term'" in text
