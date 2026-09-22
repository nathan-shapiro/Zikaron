"""Read receipts: what makes D26's read-before-write mechanical rather than trusted.

`schema.md` invariant 9 is normative. A receipt is keyed on `(session_id, client_kind,
memory_uuid, version)` — never on the process alone, because a subagent's MCP client and its
parent's hook share one `session_id`, so scoping to the session alone would let a consolidator's
serve license a primary agent's amend it never itself fetched. Minting is an idempotent upsert,
because a re-served consolidation group delivers the same rows at the same versions to the same
session and a plain insert would violate the primary key. Spending never deletes a receipt — the
version bump that revokes every *other* receipt for a row (invariant 9's own revocation rule) is
`memory.py`'s job, since it touches every receipt for a uuid rather than one row's read of it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import aiosqlite

from zikaron.core.errors import ErrorCode, ZikaronError


class ReceiptSource(StrEnum):
    """The four sources `read_receipt.source` may name, exactly as `schema.md`'s `CHECK` states
    them: `fetch`, `next_group`'s serve, a rejected write's conflict payload, or the caller's own
    successful write.
    """

    FETCH = "fetch"
    GROUP = "group"
    CONFLICT = "conflict"
    OWN_WRITE = "own_write"


#: Every legal value of `read_receipt.source`, in `schema.md`'s own DDL order — checked against
#: the table's `CHECK` constraint by `tests/test_ddl.py`'s drift guard, not restated here.
RECEIPT_SOURCES: Final = tuple(ReceiptSource)


@dataclass(frozen=True, slots=True)
class ReadReceipt:
    """One row of `read_receipt`: a licence to write `memory_uuid` at exactly `version`.

    Constructing one does not mint it — `mint` does that, against the store. This type is the
    typed shape a caller reads a minted receipt back as, per `coding-standards.md` §2's "types,
    not dicts" rule.
    """

    session_id: str
    client_kind: str
    memory_uuid: str
    version: int
    at: str
    source: ReceiptSource


@dataclass(frozen=True, slots=True)
class ReceiptKey:
    """`read_receipt`'s primary key, exactly: `(session_id, client_kind, memory_uuid, version)`.

    A separate type from `ReadReceipt` rather than reusing it with `at`/`source` ignored: every
    function in this module that looks a receipt up needs only the key, never the row's other two
    columns, and a caller holding a full `ReadReceipt` when it means only the key would invite
    reading `at`/`source` off a value that was never minted. Bundling the four key columns is also
    what keeps `mint`/`spend`/`revoke_on_version_bump` under `PLR0913`'s argument-count style
    bound — the four genuinely form one unit, since they are exactly the table's own key.
    """

    session_id: str
    client_kind: str
    memory_uuid: str
    version: int


async def mint(
    db: aiosqlite.Connection, *, key: ReceiptKey, at: str, source: ReceiptSource
) -> None:
    """Upsert one `read_receipt` row, refreshing `at` and `source` on a repeat mint.

    The upsert is invariant 9's own requirement, not a convenience: a group re-served to the same
    session at the same version must not violate `read_receipt`'s primary key, and the design
    states the refresh explicitly ("refreshes `at` and `source`") rather than leaving a repeat
    mint a no-op.

    Callers pass an already-open connection and do not commit here: minting is one statement
    inside whichever caller's transaction — `fetch`, a conflict, or a successful write — mints
    it, per invariant 10's "the event commits with its mutation" rule extended to receipts.
    """
    await db.execute(
        """
        INSERT INTO read_receipt (session_id, client_kind, memory_uuid, version, at, source)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (session_id, client_kind, memory_uuid, version)
        DO UPDATE SET at = excluded.at, source = excluded.source
        """,
        (key.session_id, key.client_kind, key.memory_uuid, key.version, at, source.value),
    )


async def spend(db: aiosqlite.Connection, *, key: ReceiptKey) -> bool:
    """Whether a matching receipt exists, without consuming it.

    Named `spend` rather than `check` because the caller's own transaction is what makes holding
    the receipt meaningful here: by the time this returns, the same transaction is about to bump
    `version`, which revokes every receipt for this uuid **except** the one the write mints for
    itself (invariant 9) — so the receipt this call found is, in effect, used up by the write that
    follows it, even though this function deletes nothing. A receipt is never deleted by *reading*
    it; only a version bump prunes the table.
    """
    rows = await db.execute_fetchall(
        """
        SELECT 1 FROM read_receipt
        WHERE session_id = ? AND client_kind = ? AND memory_uuid = ? AND version = ?
        """,
        (key.session_id, key.client_kind, key.memory_uuid, key.version),
    )
    return len(list(rows)) > 0


async def revoke_on_version_bump(db: aiosqlite.Connection, *, keep: ReceiptKey) -> None:
    """Delete every receipt for `keep.memory_uuid` except the writer's own, freshly minted one.

    Invariant 9: "On a version bump of uuid U, every receipt for U is deleted except the one
    minted for the writer at the new version." The writer's own receipt is identified by all
    three of its key columns, not by version alone — two different clients of one session could
    otherwise both survive a bump that only one of them earned, which is exactly the leak
    `client_kind` was added to the key to close.

    Call this **after** minting the writer's own-write receipt at the new version, since deleting
    first and minting second would, for one statement's duration, be indistinguishable from a
    caller that deleted every receipt and simply forgot to mint one back.
    """
    await db.execute(
        """
        DELETE FROM read_receipt
        WHERE memory_uuid = ?
          AND NOT (session_id = ? AND client_kind = ? AND version = ?)
        """,
        (keep.memory_uuid, keep.session_id, keep.client_kind, keep.version),
    )


def require_all(uuids_with_receipt: Sequence[str], *, uuids: Sequence[str]) -> None:
    """Raise `no_read_receipt` naming every uuid in `uuids` missing a receipt.

    `schema.md` invariant 9's precedence note — "the version check runs before the receipt
    check" — is enforced by call order at each raise site, not by this function: this is purely
    the payload assembly for the rung once a caller has already decided it is time to run it, and
    architecture.md's ladders say the per-row steps are evaluated across **all** named rows
    before any is rejected, so every missing uuid is named in one call rather than the first.

    Args:
        uuids_with_receipt: the subset of `uuids` a matching receipt was found for, in any order.
        uuids: every uuid the caller's write is about to mutate.
    """
    held = set(uuids_with_receipt)
    missing = [uuid for uuid in uuids if uuid not in held]
    if missing:
        raise ZikaronError(
            ErrorCode.NO_READ_RECEIPT, uuids=missing, hint="re-read it through fetch or next_group"
        )
