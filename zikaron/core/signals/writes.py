"""Signals 1 and 5 — writes per session and the zero-write rate; the write size distribution.

**Signal 1.** `schema.md` §"D30's six signals, as queries", row 1: per `session_id`,
`count(kind='remember')` and `count(kind='amend')` reported separately and summed, over a
denominator of `count(DISTINCT session_id)` restricted to **linked** sessions (`signals.sessions`) —
every session the service saw through both clients, whether or not it wrote. A linked session with a
`surface_call` and no `remember`/`amend` is a zero-write session; an unlinked one is excluded rather
than counted as zero-write, because an unlinked *writing* session would otherwise be miscounted as
one — the exact failure `write-policy.md` §3 names as the one to engineer against, since it biases
the rate in the direction that would confirm the under-writing prior this signal exists to test.

Reports **both halves of D11's loop from the write side**: `remember` volume alone answers "is the
agent recording at all", and the retire signal (`signals.retirement`) answers the repair half this
one does not — a session with plenty of `remember` and no `amend` is not yet evidence that repair
never fires, since a surfaced memory repaired by outright `retire` is legitimate under D11 and D16
and belongs to a different signal.

**Signal 5**, kept in this module rather than a separate one: both signals aggregate the same
authored-write events (`remember`, `amend`, and the authoring rows of `merge`/`promote`), and a
write's size is one further fact about the same write population signal 1 already counts — not a
fact about a different event population.
"""

from dataclasses import dataclass

import aiosqlite

from zikaron.core.events import EventKind
from zikaron.core.signals.sessions import LinkCoverage, link_coverage, linked_session_ids

_PER_SESSION_COUNTS = """
SELECT session_id,
       SUM(CASE WHEN kind = ? THEN 1 ELSE 0 END) AS n_remember,
       SUM(CASE WHEN kind = ? THEN 1 ELSE 0 END) AS n_amend
FROM event
WHERE session_id IN ({placeholders})
  AND kind IN (?, ?)
GROUP BY session_id
"""
#: The two `AS` labels above are documentation, not a wire the row is read through:
#: `writes_per_session` below unpacks each row positionally (`session_id, n_remember, n_amend`),
#: so which count is `n_remember` is decided by which `?` value binds to the first `CASE WHEN` at
#: parameter-construction time, never by the label text. Stated here because that makes the label
#: itself unable to cause or catch a defect, which a mutation on it would otherwise look like.


@dataclass(frozen=True, slots=True)
class SessionWrites:
    """One linked session's write counts. A session absent from the per-session query made
    neither call, so both counts are `0` for it — the zero-write case this signal exists to find."""

    session_id: str
    n_remember: int
    n_amend: int

    @property
    def n_writes(self) -> int:
        """`remember` and `amend` summed, per the design's "reported separately and summed"."""
        return self.n_remember + self.n_amend

    @property
    def wrote_nothing(self) -> bool:
        return self.n_writes == 0


@dataclass(frozen=True, slots=True)
class WritesPerSession:
    """The full signal: every linked session's write counts, plus the coverage the cross-client
    join depends on.

    `n_linked_sessions` is the rate's own denominator, restated on the type rather than left to be
    recomputed from `len(sessions)` — `sessions` already omits nothing, so the two do agree, but a
    caller reading only this field should not have to know that to trust it names the denominator.
    """

    sessions: tuple[SessionWrites, ...]
    link: LinkCoverage

    @property
    def n_linked_sessions(self) -> int:
        return len(self.sessions)

    @property
    def n_zero_write_sessions(self) -> int:
        return sum(1 for session in self.sessions if session.wrote_nothing)

    @property
    def zero_write_rate(self) -> float | None:
        """`n_zero_write_sessions / n_linked_sessions`, or `None` over an empty denominator.

        Bounded in `[0, 1]` by construction: the numerator counts a subset of the exact rows the
        denominator counts (a session cannot be zero-write and also outside `sessions`, since every
        linked session appears in `sessions` whether or not it wrote), so it can never exceed the
        denominator it is drawn from.
        """
        if self.n_linked_sessions == 0:
            return None
        return self.n_zero_write_sessions / self.n_linked_sessions

    @property
    def total_remember(self) -> int:
        return sum(session.n_remember for session in self.sessions)

    @property
    def total_amend(self) -> int:
        return sum(session.n_amend for session in self.sessions)


async def writes_per_session(db: aiosqlite.Connection) -> WritesPerSession:
    """Every linked session's `remember`/`amend` counts, with link coverage.

    A linked session that made no `remember` and no `amend` call is absent from the SQL result
    (`GROUP BY` produces no row for a group with nothing to group), so it is added back explicitly
    with both counts `0` — the join must not silently drop the case this whole signal is for.
    """
    linked = await linked_session_ids(db)
    counted: dict[str, SessionWrites] = {}
    if linked:
        placeholders = ", ".join("?" for _ in linked)
        sql = _PER_SESSION_COUNTS.format(placeholders=placeholders)
        params = (
            EventKind.REMEMBER.value,
            EventKind.AMEND.value,
            *linked,
            EventKind.REMEMBER.value,
            EventKind.AMEND.value,
        )
        rows = await db.execute_fetchall(sql, params)
        for session_id, n_remember, n_amend in rows:
            counted[str(session_id)] = SessionWrites(
                session_id=str(session_id), n_remember=int(n_remember), n_amend=int(n_amend)
            )
    sessions = tuple(
        counted.get(session_id, SessionWrites(session_id=session_id, n_remember=0, n_amend=0))
        for session_id in sorted(linked)
    )
    return WritesPerSession(sessions=sessions, link=await link_coverage(db))


# ---------------------------------------------------------------------------
# Signal 5 — write size distribution
# ---------------------------------------------------------------------------
#
# Kept in this module rather than a separate one: both signals aggregate the same authored-write
# events (`remember`, `amend`, and the authoring rows of `merge`/`promote`), and a write's size is
# one further fact about the same write count 1 already found — not a fact about a different event
# population.

_AUTHORED_SIZES = """
SELECT id, json_extract(detail, '$.token_count') AS token_count
FROM event
WHERE kind IN (?, ?)
UNION ALL
SELECT id, json_extract(detail, '$.token_count') AS token_count
FROM event
WHERE kind = ? AND json_extract(detail, '$.role') = 'target'
UNION ALL
SELECT id, json_extract(detail, '$.token_count') AS token_count
FROM event
WHERE kind = ? AND json_extract(detail, '$.role') IN ('created', 'flipped')
ORDER BY id
"""


@dataclass(frozen=True, slots=True)
class WriteSizeDistribution:
    """`token_count` from every write that authored prose, in `event.id` order.

    A distribution, not a rate (`schema.md`: "n/a (a distribution, not a rate)"), so this carries
    the raw values rather than a summary statistic — histogramming, percentiles or a mean are a
    caller's choice, and baking one in would answer a question about the shape of the data with a
    single number chosen before the shape was known. Ordered by the underlying `event.id` (the
    query's own `ORDER BY`, applied over the whole three-branch `UNION`) so two reads of one store
    return byte-identical results, matching every other signal's own determinism guarantee rather
    than leaving `UNION ALL`'s branch order to be assumed.
    """

    values: tuple[int, ...]


async def write_size_distribution(db: aiosqlite.Connection) -> WriteSizeDistribution:
    """`token_count` from every write that authored prose: `remember`, `amend`, a merge's `target`
    row, and a promotion's `created`/`flipped` row.

    An absorbed `merge` row and every non-`created`/`flipped` `promote` row authored no prose, so
    the design states their `token_count` as null (`schema.md`'s nullability table) rather than
    absent — filtering by `role` here is what a query over `token_count IS NOT NULL` would do
    implicitly, made explicit because the role is the actual reason those rows are excluded, not an
    incidental correlate of it.
    """
    rows = await db.execute_fetchall(
        _AUTHORED_SIZES,
        (
            EventKind.REMEMBER.value,
            EventKind.AMEND.value,
            EventKind.MERGE.value,
            EventKind.PROMOTE.value,
        ),
    )
    return WriteSizeDistribution(values=tuple(int(token_count) for _id, token_count in rows))
