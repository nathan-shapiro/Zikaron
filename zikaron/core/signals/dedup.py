"""Signal 2 — dedup offered → resolved, D15's near-duplicate hand-back outcome.

`schema.md` §"D30's six signals, as queries", row 2: the unit is the `dedup_offered` **row**, one
per near-duplicate a `remember` handed back. For an offer of the pre-existing row `X` against the
just-created row `N` (`dedup_offered.memory_uuid = X`, `detail.created_uuid = N`), let `A` = a
qualifying `amend` on `X` exists and `R` = a qualifying `retire` of `N` with
`detail.superseded_by = X` exists — both bounded identically, by `event.id > offer.id` **and**
`event.at ≤ offer.at + signal_horizon_days`, since both are the *same* offer's own deadline, not two
independent ones.

`A ∧ R` closes **early**, before the deadline: it is the best outcome the offer could reach —
folding the lesson into the existing row and discarding the redundant one — so nothing later can
improve it and there is no reason to wait for the deadline before publishing it. Every other
combination stays **pending** until `now >` the deadline, which is what keeps a classification
from being published before it can no longer change: an amend-only offer must not be reported as a
failure while an in-deadline `retire` could still complete it into `fully_resolved`. At maturity,
the remaining three combinations are named exhaustively: `A ∧ ¬R` = amended-but-duplicate-left-live,
`¬A ∧ R` = duplicate-discarded-without-amend (the agent deferred to the existing row and discarded
its own new one without folding anything in — a distinct, legitimate behaviour, not a degenerate
case), `¬A ∧ ¬R` = ignored. Five reported numbers: those four classes plus `pending`, with the rate
taken over the four matured classes only.

Single-client: `dedup_offered`, `amend` and `retire` are all `mcp`-only calls (`remember`'s dedup
search runs inside the same transaction as the write, and both `amend`/`retire` are agent verbs), so
no linked-session restriction applies here the way it does for signals 1 and 3.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

import aiosqlite

from zikaron.core.events import EventKind
from zikaron.core.signals.horizon import has_passed

# One row per `dedup_offered` event: the offer's own `(id, at)` — what both `A` and `R`'s deadline
# is measured from — and whether a qualifying `amend`/`retire` exists **by id order alone**, with no
# deadline bound applied in SQL, for the identical reason `repair.py` keeps the deadline test in
# Python: a value SQLite's own date functions compute is not string-comparable with this store's own
# `timestamp()` format. `earliest_amend_at`/`earliest_retire_at` being non-null says only that a
# candidate follow-up exists after the offer *by id*; whether it also lands inside the deadline is
# decided in Python against the exact timestamp returned.
_DEDUP_OFFERS = """
SELECT
    o.id AS offer_id,
    o.at AS offer_at,
    (SELECT MIN(a.at) FROM event AS a
      WHERE a.kind = ?
        AND a.memory_uuid = o.memory_uuid
        AND a.id > o.id) AS earliest_amend_at,
    (SELECT MIN(r.at) FROM event AS r
      WHERE r.kind = ?
        AND r.memory_uuid = json_extract(o.detail, '$.created_uuid')
        AND json_extract(r.detail, '$.superseded_by') = o.memory_uuid
        AND r.id > o.id) AS earliest_retire_at
FROM event AS o
WHERE o.kind = ?
"""


class DedupOutcome(Enum):
    """The five reported classes. `PENDING` is excluded from the rate."""

    FULLY_RESOLVED = "fully_resolved"
    AMENDED_BUT_DUPLICATE_LEFT_LIVE = "amended_but_duplicate_left_live"
    DUPLICATE_DISCARDED_WITHOUT_AMEND = "duplicate_discarded_without_amend"
    IGNORED = "ignored"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class DedupResolution:
    """One classified count per outcome, plus the horizon this classification used.

    `signal_horizon_days` travels with the result rather than being left implicit, because
    `schema.md` states both queries must report the horizon they used alongside the rate — the same
    counts under two horizons are two different estimands, not a re-run of one. Five named fields
    rather than a `dict[DedupOutcome, int]`: a mapping value on a `frozen=True` dataclass is frozen
    only at the field-assignment level — `result.counts[DedupOutcome.PENDING] = -1` would still
    mutate it in place, defeating both the immutability the type claims and the `[0, 1]` boundedness
    every rate below is documented as holding by construction. Every count field is checked
    non-negative at construction for the identical reason `LinkCoverage`/`ConflictRate` check
    theirs: a negative count here could come only from a defect in whoever built this value, and
    catching it at construction is cheaper than discovering it via a rate exceeding 1.
    """

    fully_resolved: int
    amended_but_duplicate_left_live: int
    duplicate_discarded_without_amend: int
    ignored: int
    pending: int
    signal_horizon_days: int

    def __post_init__(self) -> None:
        for outcome, count in self._by_outcome().items():
            if count < 0:
                raise ValueError(f"{outcome.value} count must be non-negative, got {count}")

    def _by_outcome(self) -> Mapping[DedupOutcome, int]:
        """This result's five counts, keyed by the outcome each names — a read-only view built on
        demand rather than stored, so nothing outside `__post_init__` and `count_for` needs to agree
        on how the five fields map onto the five enum members."""
        return {
            DedupOutcome.FULLY_RESOLVED: self.fully_resolved,
            DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE: self.amended_but_duplicate_left_live,
            DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND: self.duplicate_discarded_without_amend,
            DedupOutcome.IGNORED: self.ignored,
            DedupOutcome.PENDING: self.pending,
        }

    def count_for(self, outcome: DedupOutcome) -> int:
        """This result's count for one outcome, for a caller that has an `DedupOutcome` value
        rather than the field name it corresponds to — a test iterating `DedupOutcome`, say."""
        return self._by_outcome()[outcome]

    @property
    def n_matured(self) -> int:
        return (
            self.fully_resolved
            + self.amended_but_duplicate_left_live
            + self.duplicate_discarded_without_amend
            + self.ignored
        )

    @property
    def fully_resolved_rate(self) -> float | None:
        """`fully_resolved / n_matured`, or `None` over an empty denominator.

        Bounded in `[0, 1]` by construction: `fully_resolved` is one of exactly four non-negative
        terms summing to `n_matured`, so it can never exceed the sum it is drawn from.
        """
        if self.n_matured == 0:
            return None
        return self.fully_resolved / self.n_matured


def _classify(
    offer_at: str,
    *,
    earliest_amend_at: str | None,
    earliest_retire_at: str | None,
    now: str,
    signal_horizon_days: int,
) -> DedupOutcome:
    """One offer's outcome, given its own deadline and its two candidate follow-up timestamps.

    A candidate timestamp that exists but landed after the offer's own deadline is treated
    identically to no candidate at all — `event.at ≤ deadline` is part of what makes `A`/`R` true,
    not a separate filter applied after the fact — which is why this checks `has_passed(offer_at,
    now=candidate_at, ...)` rather than checking existence alone.
    """
    a = earliest_amend_at is not None and not has_passed(
        offer_at, now=earliest_amend_at, signal_horizon_days=signal_horizon_days
    )
    r = earliest_retire_at is not None and not has_passed(
        offer_at, now=earliest_retire_at, signal_horizon_days=signal_horizon_days
    )
    if a and r:
        return DedupOutcome.FULLY_RESOLVED
    if has_passed(offer_at, now=now, signal_horizon_days=signal_horizon_days):
        if a and not r:
            return DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE
        if r and not a:
            return DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND
        return DedupOutcome.IGNORED
    return DedupOutcome.PENDING


async def dedup_resolution(
    db: aiosqlite.Connection, *, now: str, signal_horizon_days: int
) -> DedupResolution:
    """Classify every `dedup_offered` row into one of the five outcomes as of `now`.

    `A ∧ R` is checked and may close a classification as `fully_resolved` **before** testing whether
    the deadline has passed — `_classify` mirrors that ordering exactly, since the design states the
    early close as a property of the two follow-ups existing within the deadline, independent of
    whether `now` has moved past it yet.
    """
    rows = await db.execute_fetchall(
        _DEDUP_OFFERS,
        (EventKind.AMEND.value, EventKind.RETIRE.value, EventKind.DEDUP_OFFERED.value),
    )
    counts: dict[DedupOutcome, int] = dict.fromkeys(DedupOutcome, 0)
    for _offer_id, offer_at, earliest_amend_at, earliest_retire_at in rows:
        outcome = _classify(
            str(offer_at),
            earliest_amend_at=None if earliest_amend_at is None else str(earliest_amend_at),
            earliest_retire_at=None if earliest_retire_at is None else str(earliest_retire_at),
            now=now,
            signal_horizon_days=signal_horizon_days,
        )
        counts[outcome] += 1
    return DedupResolution(
        fully_resolved=counts[DedupOutcome.FULLY_RESOLVED],
        amended_but_duplicate_left_live=counts[DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE],
        duplicate_discarded_without_amend=counts[DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND],
        ignored=counts[DedupOutcome.IGNORED],
        pending=counts[DedupOutcome.PENDING],
        signal_horizon_days=signal_horizon_days,
    )
