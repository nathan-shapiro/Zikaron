"""Signal 3 — amend after surface: does D11's repair loop ever fire?

`schema.md` §"D30's six signals, as queries", row 3: the unit is the **`(session_id, memory_uuid)`
pair** on both sides, not a qualifying `amend` call and not a distinct memory — a memory surfaced
in two linked sessions is two repair opportunities, a memory
surfaced five times in one session is one, and two amends on it in one session are one. The
denominator is every distinct pair with a `kind='surface'` row **within a linked session**; the
numerator is the subset also followed by an `amend` on that uuid in that session, where "followed
by" is `event.id > ` the pair's **earliest** `surface` row and `at ≤` that surface's own
`signal_horizon_days` deadline. A pair still inside its deadline with no such `amend` is **pending**
and excluded from the rate rather than counted as unrepaired.

**This is D11's `amend` arm only.** A surfaced memory the agent repaired by `retire` instead is
legitimate under D11 and D16 and is counted by `signals.retirement`, not here — so this rate is a
floor on repair, never a full measure of it, and the two signals are meant to be read together.

Restricted to linked sessions for the same reason as signal 1: `surface` comes from `zikaron-hook`
and `amend` from `zikaron-mcp`, so an unlinked session's `amend` calls would never be found by this
join and the session would look like a surface with no repair when the two clients simply minted
different labels. Link coverage is reported alongside.

**Why the deadline test is Python, not SQL.** SQLite's own `datetime()` function reformats an
ISO-8601-with-offset string into a space-separated, offset-free, sub-second-truncated one — measured
directly against this store's own `timestamp()` output — so a value it computes is no longer
string-comparable with a value `datetime.fromisoformat(...).isoformat()` produces, and a comparison
mixing the two formats can be silently wrong at exactly the boundary this signal exists to get
right.
Every other deadline comparison in this codebase (`consolidation.runs.Run.has_lapsed`) is Python for
the identical reason, so SQL here is used only to find candidate rows and their timestamps; the
comparison against the deadline is `signals.horizon.has_passed`, in Python, on values this store's
own clock produced.
"""

from dataclasses import dataclass

import aiosqlite

from zikaron.core.events import EventKind
from zikaron.core.signals.horizon import has_passed
from zikaron.core.signals.sessions import LinkCoverage, link_coverage, linked_session_ids

# One row per (session_id, memory_uuid) pair surfaced within a linked session: the earliest
# `surface` row's own `id` (what "followed by" means) and `at` (what the deadline is measured
# from), plus the earliest **qualifying-by-id** `amend`'s `at` if one exists at all — "qualifying
# by id" here means only `a.id > earliest_id`, deliberately not yet bounded by the deadline, since
# that bound is a Python comparison against a value this query cannot compute in its own format.
# `earliest_amend_at` is `NULL` exactly when no `amend` on that uuid in that session follows the
# earliest surface by id at all, which is the pending/not-amended case this function must still
# tell apart by comparing `now` to the pair's own deadline.
_SURFACED_PAIRS = """
SELECT
    s.session_id,
    s.memory_uuid,
    MIN(s.id) AS earliest_surface_id,
    (SELECT at FROM event
      WHERE kind = ? AND session_id = s.session_id AND memory_uuid = s.memory_uuid
      ORDER BY id LIMIT 1) AS earliest_surface_at,
    (SELECT MIN(a.at) FROM event AS a
      WHERE a.kind = ?
        AND a.session_id = s.session_id
        AND a.memory_uuid = s.memory_uuid
        AND a.id > MIN(s.id)) AS earliest_qualifying_amend_at
FROM event AS s
WHERE s.kind = ?
  AND s.session_id IN ({placeholders})
  AND s.memory_uuid IS NOT NULL
GROUP BY s.session_id, s.memory_uuid
"""
#: `a.id > MIN(s.id)` above, not `>=`: `event.id` is one unconditional `PRIMARY KEY` shared by
#: every kind (`store/ddl.py`), so no `amend` row can ever share an id with the `surface` row
#: `MIN(s.id)` names, and the two comparisons are equivalent under any reachable state. `>` is
#: kept because it states the intended relation ("strictly after"), not because `>=` would behave
#: differently — no fixture can distinguish them, which is worth recording so a reviewer does not
#: go looking for the fixture that should exist and cannot.


@dataclass(frozen=True, slots=True)
class RepairCounts:
    """The three matured/pending classes, the horizon used, plus link coverage.

    `n_amended` and `n_not_amended` are both permanent once counted; `n_pending` is excluded from
    the rate for the reason `signals.horizon` states — a pair created moments ago must not look
    identical to one genuinely ignored. `signal_horizon_days` travels with the result for the same
    reason `dedup.DedupResolution` carries it: the same counts under two horizons are two
    different estimands, not a re-run of one, and `schema.md` requires both cross-event queries to
    report the horizon they used alongside the rate.
    """

    n_amended: int
    n_not_amended: int
    n_pending: int
    signal_horizon_days: int
    link: LinkCoverage

    @property
    def n_matured(self) -> int:
        return self.n_amended + self.n_not_amended

    @property
    def amend_after_surface_rate(self) -> float | None:
        """`n_amended / n_matured`, or `None` over an empty denominator.

        Bounded in `[0, 1]` by construction: `n_amended` is one of exactly two terms summing to
        `n_matured`, so it can never exceed the sum it is drawn from.
        """
        if self.n_matured == 0:
            return None
        return self.n_amended / self.n_matured


async def amend_after_surface(
    db: aiosqlite.Connection, *, now: str, signal_horizon_days: int
) -> RepairCounts:
    """Classify every (linked session, surfaced memory) pair as amended, not-amended, or pending.

    One SQL statement finds, per pair, the earliest surface's own timestamp and — if any exists at
    all — the earliest `amend` that follows it **by `id`**, with no deadline bound applied in SQL.
    Classification then applies the deadline in Python: an `amend` exists but landed after the
    deadline is **not** "amended" (`at ≤ deadline` is part of the numerator condition, not a filter
    on when this query happens to run), so that pair is reclassified exactly as if no amend had ever
    been found, using the same `has_passed` test a pair with no amend at all would use.
    """
    linked = await linked_session_ids(db)
    n_amended = n_not_amended = n_pending = 0
    if linked:
        placeholders = ", ".join("?" for _ in linked)
        sql = _SURFACED_PAIRS.format(placeholders=placeholders)
        rows = await db.execute_fetchall(
            sql,
            (
                EventKind.SURFACE.value,
                EventKind.AMEND.value,
                EventKind.SURFACE.value,
                *linked,
            ),
        )
        for (
            _session_id,
            _memory_uuid,
            _earliest_surface_id,
            surface_at,
            qualifying_amend_at,
        ) in rows:
            amended_within_deadline = qualifying_amend_at is not None and not has_passed(
                str(surface_at),
                now=str(qualifying_amend_at),
                signal_horizon_days=signal_horizon_days,
            )
            if amended_within_deadline:
                n_amended += 1
            elif has_passed(str(surface_at), now=now, signal_horizon_days=signal_horizon_days):
                n_not_amended += 1
            else:
                n_pending += 1
    return RepairCounts(
        n_amended=n_amended,
        n_not_amended=n_not_amended,
        n_pending=n_pending,
        signal_horizon_days=signal_horizon_days,
        link=await link_coverage(db),
    )
