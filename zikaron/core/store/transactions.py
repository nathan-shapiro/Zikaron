"""How a transaction ends, in one place, for every layer that opens one.

`schema.md` invariant 2 makes "exactly one SQLite transaction" a property of every logical
mutation, and `retrieval.md` makes it a property of a read too, because a probe and the
`chunk_count` it is compared against have to see one snapshot. Every layer therefore needs the
same three things — `BEGIN`, the work, and a finalization that leaves the connection out of a
transaction whatever happened — and the third is where the difficulty is: a `COMMIT` can fail, a
failed `COMMIT` can leave the transaction open, and a `ROLLBACK` can fail too. A second copy of
that ladder is precisely how a write already reported as failed comes to be committed by whatever
runs next, so there is one.

This sits in `store/` because everything here is a property of SQLite rather than of records,
indexing or retrieval: which result codes mean *locked*, and what has to be true of a connection
when a caller lets go of it.

**What varies between callers is only how a driver-level failure is named**, so that is the one
parameter: a function from the driver's exception to the wire error it should become, or to `None`
for a failure that has no Zikaron code and should propagate as itself. `architecture.md` §Errors
fixes both halves — a write names contention `store_busy` and everything else `index_failed`,
while a read names contention and propagates the rest, since `index_failed`'s contract speaks of
index maintenance and a rolled-back write.
"""

import contextlib
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Final, NoReturn

import aiosqlite

from zikaron.core.errors import ErrorCode, ZikaronError

#: One caller's work inside an already-open transaction.
type Work[T] = Callable[[aiosqlite.Connection], Awaitable[T]]

#: How a caller names a driver-level failure: the wire error it becomes, or `None` to propagate
#: the driver's own exception because no Zikaron code describes it.
type FailureMap = Callable[[aiosqlite.Error], Exception | None]

#: The SQLite **primary** result codes that mean *the store was locked, try again* rather than
#: *the operation failed*. `store_busy` is the one error the design tells a caller it may retry,
#: so collapsing contention into anything terminal would take a retryable answer and make it look
#: final. Primary codes rather than names, because SQLite reports *extended* results — a WAL
#: reader whose snapshot went stale before it tried to write gets `SQLITE_BUSY_SNAPSHOT`, which is
#: contention by every meaning that matters and matches no exact-name test for `SQLITE_BUSY`.
_CONTENTION: Final = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})

#: SQLite packs an extended result as the primary code in its low byte plus a subcode above it.
_PRIMARY_RESULT_MASK: Final = 0xFF

#: The two codes invariant 10's rejection carve-out applies to: a rejected call that still commits
#: its audit event and, for a version conflict, the receipt for the record it returned. Every other
#: `ZikaronError` a mutation can raise has written nothing at the point it raises, so it rolls back
#: the ordinary way.
_CARVE_OUT_CODES: Final = (ErrorCode.VERSION_CONFLICT, ErrorCode.NO_READ_RECEIPT)


def is_contention(error: aiosqlite.Error) -> bool:
    """Whether this driver failure means the store was locked rather than the work failed.

    Read off the exception's own SQLite result code rather than its message text: the message is
    prose that varies between builds, while the code is the contract SQLite itself publishes. An
    exception carrying no result code — one constructed rather than raised by the driver — is not
    contention by definition.
    """
    code = getattr(error, "sqlite_errorcode", None)
    return isinstance(code, int) and (code & _PRIMARY_RESULT_MASK) in _CONTENTION


async def commit_or_roll_back(db: aiosqlite.Connection, error: BaseException | None) -> None:
    """Commit on success or on a carve-out rejection; roll back on anything else.

    This is the one place that decides which of invariant 10's two outcomes applies, and it belongs
    to the transaction-*owning* caller — never to a neutral `<verb>_within_transaction` core that
    something else may have composed into a wider transaction. Only the owner structurally knows
    that authorization ran with nothing else staged ahead of it, which is what makes committing a
    rejection safe; a neutral core cannot see what its caller staged before calling it, so it must
    never touch the transaction on any path.

    The decision is made from the raised error's own **code**, not from where it was raised: a
    `version_conflict` or `no_read_receipt` has deliberately written an audit event, and for the
    conflict a receipt for the record it returned, so those two commit while the domain mutation
    they rejected does not exist to commit.
    """
    if error is None or (isinstance(error, ZikaronError) and error.code in _CARVE_OUT_CODES):
        await db.commit()
    else:
        await db.rollback()


def _raise_mapped(error: aiosqlite.Error, failure: FailureMap) -> NoReturn:
    """Raise the wire error this driver failure maps to, or re-raise the driver's own.

    Annotated `NoReturn` because it is what lets the callers below be written without a trailing
    `raise` that can never run: the type checker knows the branch terminates here, so there is no
    unreachable statement to keep honest.
    """
    mapped = failure(error)
    if mapped is None:
        raise error
    raise mapped from error


async def finalize(
    db: aiosqlite.Connection, error: BaseException | None, *, failure: FailureMap
) -> None:
    """Commit or roll back per invariant 10, leaving the connection out of a transaction either way.

    Two obligations, and the second is the one easy to miss. A `COMMIT` that fails means the write
    did not happen, so it must be reported rather than merely logged — and it can leave the
    transaction *open*, with every staged row still visible on this connection. Reporting the
    failure without also rolling back would leave a write already announced as failed sitting there
    to be committed by whatever runs next, and would make the following call's `BEGIN` fail as a
    nested one. So a failed finalization always attempts the rollback before raising.

    **If that rollback also fails, the connection is closed.** At that point the transaction state
    could not be repaired, so every later use of this connection risks committing the very write
    this call has just reported as failed — a durable, silent wrong answer. Closing it makes the
    next use of it fail loudly instead, which is the trade this whole layer is built on: one noisy
    failure in preference to one quiet corruption. It does mean disrupting another holder of a
    connection this function only borrows, and that is accepted rather than overlooked — the holder
    gets an error it can act on, where the alternative is a memory the store claims not to have.

    When this fires while another error is already propagating, the raise replaces it and keeps it
    as the new error's context: the transaction's own outcome is the more useful answer, and
    preserving only the first fault would leave the caller told nothing about the work's fate.
    """
    try:
        await commit_or_roll_back(db, error)
    except aiosqlite.Error as caught:
        # Unconditional, because rolling back a connection that holds no transaction is a no-op and
        # asking first would only add a branch that means nothing.
        try:
            await db.rollback()
        except aiosqlite.Error:
            with contextlib.suppress(Exception):
                await db.close()
        _raise_mapped(caught, failure)


async def in_one_transaction[T](
    db: aiosqlite.Connection, work: Work[T], *, failure: FailureMap
) -> T:
    """Run `work` inside one transaction, then commit or roll back per invariant 10.

    Every driver-level failure goes through `failure`, and all three places one can occur are
    covered: opening the transaction, the work itself, and finalizing. A raw `sqlite3` exception
    escaping *unnamed* would leave whoever serializes the response with no code to send — which is
    why `failure` returning `None` has to be a deliberate choice by that caller rather than the
    default.

    A `ZikaronError` raised by `work` passes through untouched, so a rejection keeps its own code —
    and, for invariant 10's two carve-out codes, its committed audit trail.
    """
    try:
        await db.execute("BEGIN")
    except aiosqlite.Error as caught:
        _raise_mapped(caught, failure)
    error: BaseException | None = None
    try:
        result = await work(db)
    except aiosqlite.Error as caught:
        error = caught
        _raise_mapped(caught, failure)
    except BaseException as caught:
        error = caught
        raise
    finally:
        await finalize(db, error, failure=failure)
    return result
