"""The one property every stored instant is compared under, pinned rather than observed.

Stored timestamps are ordered without ever being parsed — by a plain `<` in Python, and by `MIN`
and `ORDER BY` inside SQL, where parsing is not on offer. That only works because of how this
format is shaped, and the shape has one sharp edge: `datetime.isoformat()` omits the microseconds
field exactly when it is zero, so two instants in the same second are spelled with different
lengths.
It comes out right — `+` precedes `.`, so the zero-microsecond spelling sorts first, which is where
it belongs — and the whole point of this file is that "comes out right" is checked here instead of
being rediscovered at whichever call site it eventually fails at.
"""

import itertools
import random
from datetime import UTC, datetime, timedelta

import pytest

from zikaron.core.clock import timestamp

_BASE = datetime(2026, 9, 15, 1, 39, 12, 0, tzinfo=UTC)

#: The boundary cases the format's one optional field creates, plus ordinary neighbours.
_BOUNDARIES = (
    _BASE,
    _BASE + timedelta(microseconds=1),
    _BASE + timedelta(microseconds=999_999),
    _BASE + timedelta(seconds=1),
    _BASE + timedelta(seconds=1, microseconds=1),
    _BASE - timedelta(microseconds=1),
    datetime(2026, 1, 1, tzinfo=UTC),
    datetime(2030, 12, 31, 23, 59, 59, 999_999, tzinfo=UTC),
)


def test_the_two_spellings_the_format_produces_are_different_lengths() -> None:
    """The fact that makes this file necessary, asserted so the test below cannot go vacuous by
    the format quietly becoming fixed-width."""
    without = _BASE.isoformat()
    with_microseconds = (_BASE + timedelta(microseconds=1)).isoformat()
    assert len(without) != len(with_microseconds)
    assert without.endswith("+00:00")
    assert with_microseconds.endswith("+00:00")


@pytest.mark.parametrize(("first", "second"), list(itertools.permutations(_BOUNDARIES, 2)))
def test_string_order_agrees_with_time_order_on_every_boundary_case(
    first: datetime, second: datetime
) -> None:
    """Both orderings of every pair, which is why the parameters are not named earlier/later: the
    claim is a biconditional, and it has to hold in the direction where the first argument is the
    later instant just as much as in the other."""
    assert (first < second) == (first.isoformat() < second.isoformat())


def test_string_order_agrees_with_time_order_over_a_wide_random_sample() -> None:
    """Seeded, so a failure is reproducible rather than a story about one run."""
    rng = random.Random(20260915)  # noqa: S311 — sampling instants, not generating a secret
    start = datetime(2020, 1, 1, tzinfo=UTC)
    instants = [
        start
        + timedelta(
            seconds=rng.randrange(0, 3600 * 24 * 4000),
            microseconds=rng.choice([0, 0, 1, 999_999, rng.randrange(10**6)]),
        )
        for _ in range(400)
    ]
    for earlier, later in itertools.combinations(instants, 2):
        assert (earlier < later) == (earlier.isoformat() < later.isoformat())


def test_the_clock_produces_that_format() -> None:
    """The property above is about the format; this is what ties it to what actually gets stored."""
    now = timestamp()
    assert now.endswith("+00:00")
    assert datetime.fromisoformat(now).tzinfo is not None
    assert datetime.fromisoformat(now).isoformat() == now
