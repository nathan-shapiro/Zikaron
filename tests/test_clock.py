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

from zikaron.core.clock import seconds_since, timestamp

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


class TestHowLongAgoAStoredInstantWas:
    """The one question ordering cannot answer, so it parses. `None` rather than a refusal wherever
    the value is not one of these instants: the caller is a diagnostic report, and losing one field
    of it beats losing the report over a row somebody edited by hand."""

    def test_an_instant_this_clock_produced_reads_as_just_now(self) -> None:
        elapsed = seconds_since(timestamp())
        assert elapsed is not None
        assert 0 <= elapsed < 60

    def test_an_older_instant_reads_as_longer_ago(self) -> None:
        earlier = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        elapsed = seconds_since(earlier)
        assert elapsed is not None
        assert elapsed == pytest.approx(3 * 3600, abs=60)

    def test_an_instant_still_in_the_future_reads_as_negative_rather_than_clamped(self) -> None:
        """A clock that moved backwards, or a row written by a machine that is ahead. Reporting it
        as zero would hide that, and the honest answer is what a reader needs in order to doubt
        the row."""
        later = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        elapsed = seconds_since(later)
        assert elapsed is not None
        assert elapsed < 0

    def test_something_that_is_not_an_instant_at_all_has_no_age(self) -> None:
        assert seconds_since("yesterday") is None

    def test_an_instant_with_no_zone_has_no_age(self) -> None:
        """It names no point in time without one, and guessing a zone would make the answer depend
        on where the reader happens to be."""
        assert seconds_since("2026-09-15T01:39:12") is None
