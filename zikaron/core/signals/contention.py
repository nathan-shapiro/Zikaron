"""Signal 6 — version-conflict and no-receipt rate, over observable receipt-gated mutation calls.

`schema.md` §"D30's six signals, as queries", row 6: `count(DISTINCT op_id)` over
`kind='version_conflict'`, and **separately** over `kind='no_receipt'` — never summed, because a
conflict means "read something stale" and a missing receipt means "wrote without reading", and
collapsing the two into one number would erase the distinction the design states as the whole
reason for reporting them side by side. Both numerators dedup by `op_id` because a single rejected
call can emit several rows of one kind (`schema.md`: "one row per conflicting uuid" / "one row per
uuid lacking a receipt"), and a rate whose two sides use different units is not a rate at all — a
three-row conflicting `merge` naively counted as 3 rows over a 1-call denominator would report 300%.

The denominator is `count(DISTINCT op_id)` over three **disjoint** terms: committed calls of the
five receipt-gated verbs (`amend`, `retire`, `merge`, `promote`, `discard`), plus conflicted calls,
plus no-receipt calls. Disjoint because a call is rejected at the first rung holding any offender,
and the version rung precedes the receipt rung in both ladders (invariant 9), so no call emits both
kinds; and a rejected call commits no mutation, so no call is both committed and rejected.
`remember` is excluded from every term **by construction, not filtered out**: it names no
pre-existing row, so neither ladder rung applies to it and it cannot appear in either numerator —
admitting it into the denominator would divide contention by write volume, which signal 1 already
measures on purpose.
"""

from dataclasses import dataclass

import aiosqlite

from zikaron.core.events import EventKind

#: The five verbs that name a pre-existing row at a version, and so are the only calls a version
#: conflict or a missing receipt can be rejected from. `schema.md`'s own list, transcribed once.
_RECEIPT_GATED_KINDS: tuple[EventKind, ...] = (
    EventKind.AMEND,
    EventKind.RETIRE,
    EventKind.MERGE,
    EventKind.PROMOTE,
    EventKind.DISCARD,
)

_COUNT_DISTINCT_OP_IDS = "SELECT COUNT(DISTINCT op_id) FROM event WHERE kind IN ({placeholders})"


@dataclass(frozen=True, slots=True)
class ConflictRate:
    """Both numerators and the shared denominator, each already a call count via `DISTINCT op_id`.

    `n_version_conflict` and `n_no_receipt` are reported as a pair, never summed — matching the
    design's own instruction not to collapse them.
    """

    n_version_conflict: int
    n_no_receipt: int
    n_committed: int

    def __post_init__(self) -> None:
        if self.n_version_conflict < 0 or self.n_no_receipt < 0 or self.n_committed < 0:
            raise ValueError("call counts must be non-negative")

    @property
    def n_calls(self) -> int:
        """The full denominator: committed plus both rejection populations, which are disjoint by
        the ladder ordering the design states, so this sum double-counts nothing."""
        return self.n_committed + self.n_version_conflict + self.n_no_receipt

    @property
    def version_conflict_rate(self) -> float | None:
        """`n_version_conflict / n_calls`, or `None` over an empty denominator.

        Bounded in `[0, 1]` by construction: `n_version_conflict` is one disjoint term the
        denominator sums, so it can never exceed the sum it is one addend of.
        """
        if self.n_calls == 0:
            return None
        return self.n_version_conflict / self.n_calls

    @property
    def no_receipt_rate(self) -> float | None:
        """`n_no_receipt / n_calls`, or `None` over an empty denominator. Bounded as above."""
        if self.n_calls == 0:
            return None
        return self.n_no_receipt / self.n_calls


async def conflict_rate(db: aiosqlite.Connection) -> ConflictRate:
    """The version-conflict and no-receipt rates over every observable receipt-gated call.

    Three independent `COUNT(DISTINCT op_id)` queries rather than one query with three `CASE`
    branches, because each term counts distinct `op_id`s **within its own `kind` filter** — a call
    that emitted three `version_conflict` rows must count once in that term and the committed term
    must not see it at all, which a single shared `GROUP BY op_id` would make harder to state
    correctly than three separate, disjoint-by-ladder-ordering counts.
    """
    committed_placeholders = ", ".join("?" for _ in _RECEIPT_GATED_KINDS)
    committed_sql = _COUNT_DISTINCT_OP_IDS.format(placeholders=committed_placeholders)
    committed_rows = list(
        await db.execute_fetchall(committed_sql, tuple(kind.value for kind in _RECEIPT_GATED_KINDS))
    )
    conflict_sql = _COUNT_DISTINCT_OP_IDS.format(placeholders="?")
    conflict_rows = list(
        await db.execute_fetchall(conflict_sql, (EventKind.VERSION_CONFLICT.value,))
    )
    no_receipt_rows = list(await db.execute_fetchall(conflict_sql, (EventKind.NO_RECEIPT.value,)))
    return ConflictRate(
        n_version_conflict=int(conflict_rows[0][0]),
        n_no_receipt=int(no_receipt_rows[0][0]),
        n_committed=int(committed_rows[0][0]),
    )
