"""The two row-state re-checks a serve and the ladder both run, evaluated by SQLite's own clause.

`architecture.md` names them as one condition each, and names them **twice** on purpose: a member
that fails the first at serve time is recorded `disposition='vacated'`, and a member that fails it
at call time is *vacated in fact and not yet recorded*, which is why rung 6 answers `not_in_group`
rather than inventing a code. Those two sites must apply the identical predicate or the second
would reject rows the first would have delivered.

**So the predicate is not re-expressed here.** The clause comes from
`eligibility.CONSUMER_FILTERS` — `tier='journal' AND active=1` for a member, `tier='long_term' AND
active=1` for a merge target — and is evaluated by SQLite against the row. A Python mirror
(`row.tier is Tier.JOURNAL and row.active`) would read better and would be a second statement of a
rule the design gives exactly one home, silently surviving a change to that table. This is the same
choice the query constructor makes when it hands quoted terms to FTS5's own tokenizer instead of
reimplementing `unicode61`.

The cost is one indexed `EXISTS` per row on a manually-invoked, rare path, inside a transaction the
caller already holds.
"""

from typing import Final

import aiosqlite

from zikaron.core.retrieval.eligibility import MEMORY_ALIAS, Consumer, narrowing

#: The two consumers whose filters double as these state conditions. Named so the mapping from
#: "what is being checked" to "whose filter says so" is written once rather than at each call site.
_MEMBER: Final = Consumer.ORPHAN
_TARGET: Final = Consumer.CONSOLIDATION


async def _satisfies(db: aiosqlite.Connection, *, uuid: str, consumer: Consumer) -> bool:
    """Whether the row named by `uuid` satisfies `consumer`'s own narrowing filter, right now.

    Raises:
        KeyError: the consumer states no narrowing filter, so there is nothing to check and a caller
            asking has confused "no filter" with "admits nothing". Only `surface` and `search` are
            in that position and neither has a row-state condition to re-check.
    """
    clause = narrowing(consumer)
    if clause is None:
        raise KeyError(f"{consumer} states no narrowing filter, so there is nothing to re-check")
    sql = (
        "SELECT EXISTS (SELECT 1 FROM memory "  # noqa: S608 — the clause is a source-level constant from the filter table; the uuid is bound.
        f"{MEMORY_ALIAS} WHERE {MEMORY_ALIAS}.uuid = ? AND {clause})"
    )
    rows = await db.execute_fetchall(sql, (uuid,))
    return bool(next(iter(rows))[0])


async def is_deliverable_member(db: aiosqlite.Connection, uuid: str) -> bool:
    """Whether this row is still an unconsolidated journal row, i.e. still a deliverable member.

    A row that fails this has left the journal by another path between plan and call — a primary
    agent retired it, or promoted it. Nothing was lost and it blocks no completion; it is simply not
    something a consolidator may act on.
    """
    return await _satisfies(db, uuid=uuid, consumer=_MEMBER)


async def is_targetable(db: aiosqlite.Connection, uuid: str) -> bool:
    """Whether this row is still an active long-term record, i.e. still a legal `merge` target.

    A merge never rewrites a historical row: `superseded_by` is immutable once set, so a retired row
    given fresh prose would be neither the current record nor a faithful historical one.
    """
    return await _satisfies(db, uuid=uuid, consumer=_TARGET)
