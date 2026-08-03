"""`zikaron.service.context.ActivityTracker` — the idle/in-flight bookkeeping lifecycle depends
on."""

import time

from zikaron.service.context import ActivityTracker


def test_starts_with_zero_in_flight() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    assert tracker.in_flight == 0


def test_begin_request_increments_in_flight() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    tracker.begin_request()
    assert tracker.in_flight == 1
    tracker.begin_request()
    assert tracker.in_flight == 2


def test_end_request_decrements_in_flight() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    tracker.begin_request()
    tracker.begin_request()
    tracker.end_request()
    assert tracker.in_flight == 1


def test_begin_and_end_both_refresh_last_activity() -> None:
    stale = time.monotonic() - 1000
    tracker = ActivityTracker(last_activity=stale)
    tracker.begin_request()
    assert tracker.idle_for() < 1.0
    tracker.last_activity = stale
    tracker.end_request()
    assert tracker.idle_for() < 1.0


def test_may_stop_is_false_while_a_request_is_in_flight_even_past_the_timeout() -> None:
    stale = time.monotonic() - 1000
    tracker = ActivityTracker(last_activity=stale, in_flight=1)
    assert tracker.may_stop(idle_timeout=1.0) is False


def test_may_stop_is_false_before_the_timeout_elapses() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    assert tracker.may_stop(idle_timeout=1000.0) is False


def test_may_stop_is_true_once_idle_past_the_timeout_with_nothing_in_flight() -> None:
    stale = time.monotonic() - 10
    tracker = ActivityTracker(last_activity=stale, in_flight=0)
    assert tracker.may_stop(idle_timeout=0.01) is True


def test_end_request_can_bring_in_flight_below_zero_is_not_the_callers_job_to_prevent() -> None:
    """`server.py`'s own `try`/`finally` guarantees a matched `begin`/`end` pair per request; this
    type does not re-defend against a caller that violates that pairing, since the only caller is
    the one function that already guarantees it."""
    tracker = ActivityTracker(last_activity=time.monotonic(), in_flight=0)
    tracker.end_request()
    assert tracker.in_flight == -1
