"""The `signal_horizon_days` maturity rule, shared by every signal that joins two events.

Two of the six signals ask an open-ended question — was this event ever followed by a qualifying
one? — which has no closing condition on its own: a late follow-up can retroactively resolve an old
pair, so the same historical window would report a different rate depending on when the query runs.
`schema.md` §"`signal_horizon_days`" closes it with a deadline measured from the **earlier** event,
not a test applied at query time, so a classification made after the deadline passes is fixed for
good. This module is the one place the deadline arithmetic lives, since both joined-pair signals —
dedup resolution and amend-after-surface — measure it from the same kind of earlier event, and a
second statement of it is how one signal comes to apply a different horizon than the other by
accident.

Deliberately takes `now` as an explicit parameter rather than reading a clock: every deadline
comparison elsewhere in this codebase (`consolidation.runs.Run.has_lapsed`) does the same, because a
function that reads its own clock cannot be run twice on one fixture and asked whether it agrees
with itself.
"""

from datetime import datetime, timedelta


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def deadline(earlier_at: str, *, signal_horizon_days: int) -> str:
    """`earlier_at` plus `signal_horizon_days`, in the store's own timestamp format.

    Derived from the joined pair's own earlier timestamp rather than from a second clock read, so
    that a query re-run later against the same rows recomputes the identical deadline.
    """
    return (_parse(earlier_at) + timedelta(days=signal_horizon_days)).isoformat()


def has_passed(earlier_at: str, *, now: str, signal_horizon_days: int) -> bool:
    """Whether `now` is strictly after `earlier_at`'s own deadline.

    The one test every joined-pair signal needs and no two of them may restate differently: a pair
    is **pending**, and excluded from its rate, exactly when this is `False` and no qualifying
    follow-up has been found; it is permanently matured exactly when this is `True`. Kept as a bare
    predicate rather than folded into a richer classification type, because the signals that use it
    disagree on what "qualifying follow-up" means — one follow-up for amend-after-surface, two
    independent ones for dedup resolution — so the shared part is exactly this comparison and no
    more; forcing both through one shared outcome type would either under-fit dedup's four matured
    classes or duplicate this arithmetic anyway.
    """
    return _parse(now) > _parse(deadline(earlier_at, signal_horizon_days=signal_horizon_days))
