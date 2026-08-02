"""Linked sessions: which `session_id`s the service saw through both clients, and how completely.

`schema.md` §"Linked sessions": a push comes from `zikaron-hook` (`client_kind='hook'`), a write
from `zikaron-mcp` (`client_kind='mcp'`), so any signal joining the two only measures what it claims
to measure when both clients resolved the *same* session label. A session with `hook` events and no
`mcp` events is not evidence of a zero-write session — it may just be a session where the two
clients minted different labels, which the design calls an **unlinked** session precisely so it can
be excluded rather than miscounted. Two of the six signals (writes-per-session/zero-write, and
amend-after-surface) are cross-client for exactly this reason and both report **link coverage**
alongside their own numbers, computed by this module, rather than assuming the ~1.0 the design
expects to hold under kiro.

This module answers only "which sessions" and "how many were linked over how many had any `hook`
event" — the population and coverage fraction every cross-client signal needs before it can restrict
its own numerator and denominator to the linked set. It does not restrict any other table itself;
each signal joins against `linked_session_ids` as its own scope.
"""

from dataclasses import dataclass

import aiosqlite

from zikaron.core.events import ClientKind

_LINKED_SESSION_IDS = """
SELECT DISTINCT hook.session_id
FROM event AS hook
JOIN event AS mcp
  ON mcp.session_id = hook.session_id
 AND mcp.client_kind = ?
WHERE hook.client_kind = ?
  AND hook.session_id IS NOT NULL
"""
#: `DISTINCT` above is defence in depth rather than load-bearing: `linked_session_ids` below
#: rebuilds its result as a `frozenset` regardless, which already dedups. Kept because it costs
#: nothing and documents the query's own intent, and because removing it would make correctness
#: depend on every future caller of this statement routing through that one Python wrapper.

_HOOK_SESSION_COUNT = """
SELECT COUNT(DISTINCT session_id)
FROM event
WHERE client_kind = ?
  AND session_id IS NOT NULL
"""


@dataclass(frozen=True, slots=True)
class LinkCoverage:
    """Linked sessions over sessions with any `hook` event, as every cross-client signal reports it.

    `coverage` is `None` rather than `0.0` when `hook_sessions` is zero, since a fraction with no
    denominator is not zero coverage — it is a store the hook side never touched at all, and the two
    should not be plotted as though they meant the same thing.
    """

    linked_sessions: int
    hook_sessions: int

    def __post_init__(self) -> None:
        if self.linked_sessions > self.hook_sessions:
            raise ValueError(
                f"linked_sessions={self.linked_sessions} exceeds "
                f"hook_sessions={self.hook_sessions}: linked is defined as a subset"
            )

    @property
    def coverage(self) -> float | None:
        """`linked_sessions / hook_sessions`, or `None` if no session ever had a `hook` event."""
        if self.hook_sessions == 0:
            return None
        return self.linked_sessions / self.hook_sessions


async def linked_session_ids(db: aiosqlite.Connection) -> frozenset[str]:
    """Every `session_id` with at least one `hook` event and at least one `mcp` event.

    The scope every cross-client signal restricts itself to. Returned as a set of ids rather than
    joined inline into each caller's own query, so a signal's SQL states its own numerator and
    denominator against `session_id IN (...)` without re-deriving what "linked" means at each site.

    The two bound parameters below are written in the order the statement's two `?` placeholders
    appear (`mcp.client_kind` first, `hook.client_kind` second), but the query itself is symmetric
    in which literal binds to which alias: it asks whether a session has a row of each of the two
    values `{hook, mcp}` somewhere, and a self-join checking that condition cannot distinguish
    "alias `hook` holds `'hook'` and alias `mcp` holds `'mcp'`" from the reverse. Swapping the two
    values here is therefore not a distinguishable defect — stated here because it is exactly the
    kind of change a reviewer might otherwise flag as unverified.
    """
    rows = await db.execute_fetchall(
        _LINKED_SESSION_IDS, (ClientKind.MCP.value, ClientKind.HOOK.value)
    )
    return frozenset(str(row[0]) for row in rows)


async def link_coverage(db: aiosqlite.Connection) -> LinkCoverage:
    """Linked-session count over hook-session count, for reporting beside a cross-client signal.

    Two separate queries rather than one derived from `linked_session_ids`' own length, because the
    denominator — sessions with any `hook` event — is a different population than the numerator's
    join and must be counted on its own rather than inferred from the linked set's size.
    """
    linked = await linked_session_ids(db)
    hook_count_rows = list(await db.execute_fetchall(_HOOK_SESSION_COUNT, (ClientKind.HOOK.value,)))
    hook_sessions = int(hook_count_rows[0][0])
    return LinkCoverage(linked_sessions=len(linked), hook_sessions=hook_sessions)
