"""`zikaron.service.context.ActivityTracker` — the idle bookkeeping and the in-flight registry that
lifecycle and the wedge diagnostics read."""

import time

from zikaron.service.context import ActivityTracker


def test_starts_with_zero_in_flight() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    assert tracker.in_flight == 0


def test_begin_request_registers_each_request() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    tracker.begin_request("memory_search")
    assert tracker.in_flight == 1
    tracker.begin_request("memory_search")
    assert tracker.in_flight == 2


def test_end_request_removes_exactly_the_request_it_is_given() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    first = tracker.begin_request("memory_search")
    second = tracker.begin_request("memory_remember")
    tracker.end_request(first)
    assert tracker.requests() == (second,)


def test_requests_are_listed_oldest_first() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    older = tracker.begin_request("memory_plan_groups")
    older.started -= 10
    newer = tracker.begin_request("memory_search")
    assert tracker.requests() == (older, newer)


def test_a_request_is_described_by_method_session_and_age() -> None:
    """The session is `unresolved` until the envelope resolves, which is how a request wedged before
    that is reported."""
    tracker = ActivityTracker(last_activity=time.monotonic())
    request = tracker.begin_request("memory_remember")
    request.started -= 42
    assert request.describe().startswith("method=memory_remember session=unresolved age=42.")
    request.session_id = "s1"
    assert "session=s1 " in request.describe()


def test_begin_and_end_both_refresh_last_activity() -> None:
    stale = time.monotonic() - 1000
    tracker = ActivityTracker(last_activity=stale)
    request = tracker.begin_request("memory_search")
    assert tracker.idle_for() < 1.0
    tracker.last_activity = stale
    tracker.end_request(request)
    assert tracker.idle_for() < 1.0


def test_may_stop_is_false_while_a_request_is_in_flight_even_past_the_timeout() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    tracker.begin_request("memory_search")
    tracker.last_activity = time.monotonic() - 1000
    assert tracker.may_stop(idle_timeout=1.0) is False


def test_may_stop_is_false_before_the_timeout_elapses() -> None:
    tracker = ActivityTracker(last_activity=time.monotonic())
    assert tracker.may_stop(idle_timeout=1000.0) is False


def test_may_stop_is_true_once_idle_past_the_timeout_with_nothing_in_flight() -> None:
    stale = time.monotonic() - 10
    tracker = ActivityTracker(last_activity=stale)
    assert tracker.may_stop(idle_timeout=0.01) is True
