"""D30's six write-policy signals, each as executable SQL over the committed `event` log.

`write-policy.md` §3 names what each signal tells us; `schema.md` §"D30's six signals, as queries"
and §"`signal_horizon_days`" are the normative numerator/denominator/deadline definitions this
package implements. Every function here is read-only aggregation over rows some other layer already
committed — nothing in this package calls `records.memory.log_event`, and nothing here decides what
gets logged.

One module per signal, grouped where two signals share an event population (`writes.py` holds
signals 1 and 5, since both aggregate the same authored-write events), plus two shared primitives
both cross-event signals need without restating: `horizon` for the `signal_horizon_days` maturity
rule, and `sessions` for linked-session scope and coverage.

| Signal | Module | Entry point |
|---|---|---|
| 1. writes per session; zero-write rate | `writes` | `writes_per_session` |
| 2. dedup offered → resolved | `dedup` | `dedup_resolution` |
| 3. amend after surface | `repair` | `amend_after_surface` |
| 4. retire count | `retirement` | `retire_count` |
| 5. write size distribution | `writes` | `write_size_distribution` |
| 6. version-conflict / no-receipt rate | `contention` | `conflict_rate` |

No reporting UI, no formatting, no export format — `build-plan.md`'s M8 fence keeps this package to
SQL plus the typed results a caller aggregates or displays however it needs to.
"""

from zikaron.core.signals.contention import ConflictRate, conflict_rate
from zikaron.core.signals.dedup import DedupOutcome, DedupResolution, dedup_resolution
from zikaron.core.signals.repair import RepairCounts, amend_after_surface
from zikaron.core.signals.retirement import RetireCount, retire_count
from zikaron.core.signals.sessions import LinkCoverage, link_coverage, linked_session_ids
from zikaron.core.signals.writes import (
    SessionWrites,
    WriteSizeDistribution,
    WritesPerSession,
    write_size_distribution,
    writes_per_session,
)

__all__ = [
    "ConflictRate",
    "DedupOutcome",
    "DedupResolution",
    "LinkCoverage",
    "RepairCounts",
    "RetireCount",
    "SessionWrites",
    "WriteSizeDistribution",
    "WritesPerSession",
    "amend_after_surface",
    "conflict_rate",
    "dedup_resolution",
    "link_coverage",
    "linked_session_ids",
    "retire_count",
    "write_size_distribution",
    "writes_per_session",
]
