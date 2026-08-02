"""Signal 4 — retire count, split by whether the retirement named a replacement.

`schema.md` §"D30's six signals, as queries", row 4: `count(kind='retire')` split by whether
`detail.superseded_by` is null, over a denominator of `count(kind='remember')` in the same window —
so the ratio reads as retire-per-write. Single-client (`retire` is only ever emitted by
`records.memory.retire`, the primary-agent verb), so no linkage restriction applies.

**Consolidator retirements are already excluded, and not by a filter this module adds.** The
`retire` event kind is emitted by exactly one write path — the agent's own `zikaron_retire` — while
consolidation's own row-removing dispositions are `merge` (absorbing a member) and `discard`
(dropping one as noise), which are different `EventKind`s entirely. "The agent chose to retire"
and "consolidation absorbed a row" were already distinguishable at the kind level before this
signal was written; counting `kind='retire'` is sufficient on its own; it is not this query's job
to re-derive a distinction the event vocabulary already draws.
"""

from dataclasses import dataclass

import aiosqlite

from zikaron.core.events import EventKind

_RETIRE_SPLIT = """
SELECT
    SUM(CASE WHEN json_extract(detail, '$.superseded_by') IS NULL THEN 1 ELSE 0 END),
    SUM(CASE WHEN json_extract(detail, '$.superseded_by') IS NOT NULL THEN 1 ELSE 0 END)
FROM event
WHERE kind = ?
"""

_REMEMBER_COUNT = "SELECT COUNT(*) FROM event WHERE kind = ?"


@dataclass(frozen=True, slots=True)
class RetireCount:
    """The two `retire` splits, and the `remember` count they are read as a ratio against.

    `n_outright` and `n_superseding` are the two matured facts; `n_remember` is the denominator that
    turns either into "retire-per-write" rather than a bare count with no scale.
    """

    n_outright: int
    n_superseding: int
    n_remember: int

    @property
    def n_retire(self) -> int:
        return self.n_outright + self.n_superseding

    @property
    def retire_per_write(self) -> float | None:
        """`n_retire / n_remember`, or `None` over an empty denominator.

        Not bounded to `[0, 1]` by construction, unlike the other five signals: this one is
        deliberately a ratio of two independent write counts rather than a rate over a shared
        population, and the design's own name for it — "retire-per-write" — states as much. A store
        with more retirements than remembers in its window is possible (an old row retired long
        after the session that created it, counted in a window that starts later) and is not itself
        a defect this type should refuse to represent.
        """
        if self.n_remember == 0:
            return None
        return self.n_retire / self.n_remember


async def retire_count(db: aiosqlite.Connection) -> RetireCount:
    """`retire` calls split by `superseded_by`, over the `remember` count in the same window.

    "The same window" is the whole `event` table as of this call — there is no time-bounding
    parameter, matching every other signal in this package, which all report over the store's full
    retained history rather than a caller-chosen slice (`write-policy.md` §"Pruning the event log":
    a manual prune is whole-session and reports its own surviving window separately, rather than
    this query taking a window argument it would then have to apply consistently to both terms).
    """
    outright_rows = list(await db.execute_fetchall(_RETIRE_SPLIT, (EventKind.RETIRE.value,)))
    n_outright, n_superseding = outright_rows[0]
    remember_rows = list(await db.execute_fetchall(_REMEMBER_COUNT, (EventKind.REMEMBER.value,)))
    n_remember = remember_rows[0][0]
    return RetireCount(
        n_outright=int(n_outright or 0),
        n_superseding=int(n_superseding or 0),
        n_remember=int(n_remember),
    )
