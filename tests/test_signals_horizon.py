"""`signals.horizon` — the `signal_horizon_days` deadline arithmetic and maturity predicate."""

from zikaron.core.signals.horizon import deadline, has_passed


def test_deadline_adds_exactly_the_stated_number_of_days() -> None:
    """`deadline` is `earlier_at + signal_horizon_days` days, with no drift in the time-of-day
    component — the arithmetic the design states, not an approximation of it.

    `isoformat()` drops the microsecond field entirely when it is exactly zero (Python's own
    behaviour, not this function's), so the fixture below uses a non-zero microsecond component to
    assert the *whole* format round-trips, not only the date arithmetic."""
    result = deadline("2026-01-01T00:00:00.500000+00:00", signal_horizon_days=30)
    assert result == "2026-01-31T00:00:00.500000+00:00"


def test_deadline_is_computed_from_the_earlier_event_not_a_second_clock_read() -> None:
    """Two calls with the same `earlier_at` produce byte-identical deadlines — the design's own
    reason for measuring from the earlier event rather than from when the query runs."""
    first = deadline("2026-01-01T00:00:00.000000+00:00", signal_horizon_days=30)
    second = deadline("2026-01-01T00:00:00.000000+00:00", signal_horizon_days=30)
    assert first == second


def test_has_passed_is_false_exactly_at_the_deadline() -> None:
    """The deadline is inclusive: `now == deadline` has not yet *passed* it — `schema.md`'s
    `pending` condition is `now ≤ deadline`, so equality must not read as matured."""
    earlier_at = "2026-01-01T00:00:00.000000+00:00"
    at_deadline = deadline(earlier_at, signal_horizon_days=30)
    assert has_passed(earlier_at, now=at_deadline, signal_horizon_days=30) is False


def test_has_passed_is_true_one_microsecond_after_the_deadline() -> None:
    earlier_at = "2026-01-01T00:00:00.000000+00:00"
    just_after = "2026-01-31T00:00:00.000001+00:00"
    assert has_passed(earlier_at, now=just_after, signal_horizon_days=30) is True


def test_has_passed_is_false_before_the_deadline() -> None:
    earlier_at = "2026-01-01T00:00:00.000000+00:00"
    before = "2026-01-15T00:00:00.000000+00:00"
    assert has_passed(earlier_at, now=before, signal_horizon_days=30) is False
