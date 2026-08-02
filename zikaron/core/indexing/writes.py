"""The two indexed write verbs: `remember` and `amend`, each one transaction.

This is where invariant 2 becomes real. Every logical mutation that touches indexed prose is
**exactly one** SQLite transaction covering the `memory` row, the `version` bump, explicit
`memory_fts` maintenance, `memory_chunk` + `memory_vec` maintenance, any `read_receipt` change,
and its `event` rows. A service killed mid-write therefore leaves either the old state or the new
one, never prose with a stale dense index.

**Two verbs, not three.** `retire` (`records.memory`) writes `active`, `superseded_by`, `version`
and `updated_at`; none of those is an indexed column, `memory_fts` indexes `gist` and `content`
only, and D16 leaves chunks and vectors exactly where they are so a superseded row stays
retrievable. It has nothing for this layer to add, which is a property of the verb rather than an
omission — `indexing.md` §"Implementation constraints" states it so nobody adds a third verb to
make the set look symmetrical.

**What happens outside the transaction, and why.** `prepare` runs the chunking preflight and the
embedding before `BEGIN`. The preflight reads nothing from the store and raises only `bounds`, which
is rung 1 of the validation ladder and precedes existence, version and receipt anyway; the embedding
is outside because a cold model load costs hundreds of milliseconds and holding SQLite's single
write lock across it would make every concurrent writer's `busy_timeout` a function of model-load
time. Nothing is staged before `BEGIN`, so failing there loses nothing.

The cost of that choice, stated rather than hidden: an `amend` that will be rejected as
`version_conflict` has already paid for its embedding, because authorization happens inside the
transaction and the embedding deliberately does not. The alternative trades a wasted single-digit
millisecond inference on a rejected call for the write lock being held across a possibly
three-orders-of-magnitude-longer model load on every call, which is the worse side of the trade.

**The seam for the layer above.** `remember_within_transaction` and `amend_within_transaction`
assume an already-open transaction and neither commit nor roll back, exactly as `records.memory`'s
row-level cores do. The tool-facing write path composes them: D15's dedup search has to run in the
*same* transaction as the `remember` it reports on, since it queries the vectors that transaction
just wrote.
"""

import contextlib
import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Final, Self

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.errors import BadConfigSource, ErrorCode, IndexStage, ZikaronError
from zikaron.core.events import EventKind
from zikaron.core.indexing import chunking, lexical, vectors
from zikaron.core.indexing.chunking import ChunkPlan
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.indexing.vectors import IndexIdentity
from zikaron.core.records import memory
from zikaron.core.records.memory import CallParams, Memory, Rewrite
from zikaron.core.store.store import Store

#: One verb's work inside an already-open transaction. Named so `_in_one_transaction` can own the
#: `BEGIN`/commit decision for both verbs without either one repeating it.
type _Work[T] = Callable[[aiosqlite.Connection], Awaitable[T]]


@dataclass(frozen=True, slots=True)
class IndexingContext:
    """Everything an indexed write needs that is constant for the life of one store handle.

    The split between the fields is the dual-homed rule in `schema.md`: `identity` records what the
    *existing* index was built with and is `meta`'s to state, while `chunk_max_tokens` and
    `gist_max_tokens` govern **new** writes and are the config file's.

    Self-validating, so every write inward may assume the encoder matches the index it is writing
    into. Without that check a store created with one model could be written by another of the same
    width, and the only trace would be `memory_chunk.embed_model` rows quietly disagreeing about
    what the vectors beside them mean — which is exactly the silent `vec0` corruption D20 exists to
    prevent, arriving through the write path instead of through a config edit.

    Raises:
        ZikaronError: `BAD_CONFIG` (`source='meta'`) if the encoder's reported model name or width
            disagrees with what the store recorded.
    """

    encoder: Encoder
    chunk_max_tokens: int
    gist_max_tokens: int
    identity: IndexIdentity

    def __post_init__(self) -> None:
        encoder = self.encoder
        if (
            encoder.model_name != self.identity.embed_model
            or encoder.dim != self.identity.embed_dim
        ):
            raise ZikaronError(
                ErrorCode.BAD_CONFIG,
                source=BadConfigSource.META,
                key="embed_model/embed_dim",
                value=f"{encoder.model_name}/{encoder.dim}",
                expected=f"{self.identity.embed_model}/{self.identity.embed_dim} (what this "
                "store's existing index was built with — an encoder that disagrees would write "
                "vectors labelled with a model that did not produce them)",
            )

    @classmethod
    def for_store(cls, store: Store, config: EffectiveConfig, encoder: Encoder) -> Self:
        """Bundle one store's recorded index identity with the config that governs new writes."""
        return cls(
            encoder=encoder,
            chunk_max_tokens=config.get_int("chunk_max_tokens"),
            gist_max_tokens=config.get_int("gist_max_tokens"),
            identity=IndexIdentity(
                embed_model=store.meta.embed_model, embed_dim=store.meta.embed_dim
            ),
        )


@dataclass(frozen=True, slots=True)
class IndexedCall:
    """The two things every indexed write holds constant: who is calling, and what the index is.

    `ctx` is the RPC call's own identity — session, client kind, `op_id`, and the supersession
    walk's depth cap — and `index` is the store's index settings, which outlive the call. They are
    bundled because *every* verb here needs both and neither changes partway through one call, the
    same reason `CallParams` itself bundles its four; keeping them apart would put six parameters on
    every entry point and invite a call site that passed an encoder from one store and a context
    from another.
    """

    ctx: CallParams
    index: IndexingContext


@dataclass(frozen=True, slots=True)
class PreparedIndex:
    """One memory's prose, its chunk plan and its embedded vectors — everything but the writing.

    Produced by `prepare` and consumed by whichever verb writes it. Holding the three together is
    what keeps them from being computed from different inputs: the vectors are of *these* chunks,
    and the chunks are of *this* prose.
    """

    rewrite: Rewrite
    plan: ChunkPlan
    vectors: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class IndexedWrite:
    """What an indexed write returns: the row as stored, and the plan its index was built from.

    The plan is returned rather than discarded because it holds the numbers the verb's own event
    reports — `gist_tokens`, `n_chunks`, `truncated` — and a caller reporting them to an agent (or
    a test asserting them) would otherwise have to recompute what this call already knows.
    """

    memory: Memory
    plan: ChunkPlan


async def prepare(rewrite: Rewrite, *, index: IndexingContext) -> PreparedIndex:
    """Run the chunking preflight and embed every chunk, before any transaction opens.

    Raises:
        ZikaronError: `BOUNDS` if the gist or content is empty or the gist is over
            `gist_max_tokens`; `INDEX_FAILED` if the token arithmetic leaves no room for content,
            an assembled sequence overran the model's cap, or the embedder failed or returned the
            wrong shape.
    """
    plan = chunking.plan_chunks(
        gist=rewrite.gist,
        content=rewrite.content,
        encoder=index.encoder,
        chunk_max_tokens=index.chunk_max_tokens,
        gist_max_tokens=index.gist_max_tokens,
    )
    embedded = await vectors.embed_chunks(
        plan, gist=rewrite.gist, encoder=index.encoder, embed_dim=index.identity.embed_dim
    )
    return PreparedIndex(rewrite=rewrite, plan=plan, vectors=embedded)


def _document(row: Memory) -> lexical.Document:
    """One `memory` row's prose as `memory_fts` holds it."""
    return lexical.Document(gist=row.gist, content=row.content)


async def _rowid_of(db: aiosqlite.Connection, uuid: str) -> int:
    """The `memory` row's own rowid, which is `memory_fts`'s only link to it.

    `Memory` deliberately does not carry it — invariant 14 makes `uuid` the only handle ever
    exposed, and a rowid on a value object handed outward would be an invitation to use it as one.
    So it is read here, at the one place that needs it, and never returned.
    """
    rows = await db.execute_fetchall("SELECT rowid FROM memory WHERE uuid = ?", (uuid,))
    found = list(rows)
    if not found:
        raise ZikaronError(ErrorCode.NOT_FOUND, uuid=uuid)
    return int(found[0][0])


async def _record_size(db: aiosqlite.Connection, *, uuid: str, token_count: int) -> None:
    """Write `memory.token_count` — the row's current content size, in tokens.

    A statement of this layer's own rather than part of the row insert or update, because the number
    comes from the tokenizer and the row-level layer deliberately has none: the same reason
    `remember`/`amend` events are emitted here and not there. Counted over `content` alone,
    excluding the gist, since `gist_tokens` is a sibling field of the same event and a `token_count`
    that included the gist would double-count it.
    """
    await db.execute("UPDATE memory SET token_count = ? WHERE uuid = ?", (token_count, uuid))


async def _write_index(
    db: aiosqlite.Connection, *, row: Memory, prepared: PreparedIndex, index: IndexingContext
) -> Memory:
    """Write the dense index and the row's size, for a row whose prose is already current.

    Shared by both verbs because the work is identical once the prose is in place; what differs is
    only what had to be removed first, which each verb does for itself.

    Returns:
        `row` with `token_count` as this call just set it. Not re-read from the store: the update
        above is one explicit integer column, so a second `SELECT` would only be reading back a
        value this transaction wrote from a literal it still holds.
    """
    await vectors.insert_chunks(
        db,
        memory_uuid=row.uuid,
        plan=prepared.plan,
        vectors=prepared.vectors,
        identity=index.identity,
    )
    await _record_size(db, uuid=row.uuid, token_count=prepared.plan.content_tokens)
    return replace(row, token_count=prepared.plan.content_tokens)


def _size_detail(plan: ChunkPlan) -> dict[str, object]:
    """The four size fields `remember` and `amend` both report, from the plan that produced them.

    One function because the two events state the same four in the same way, and a second
    transcription of them is how one verb's `truncated` comes to mean something the other's does
    not.
    """
    return {
        "token_count": plan.content_tokens,
        "gist_tokens": plan.gist_tokens,
        "n_chunks": plan.n_chunks,
        "truncated": plan.truncated,
    }


async def remember_within_transaction(
    db: aiosqlite.Connection, *, prepared: PreparedIndex, call: IndexedCall
) -> IndexedWrite:
    """`remember`'s work, assuming the caller already holds an open transaction.

    Neither commits nor rolls back — the caller owns that decision, through
    `records.memory.commit_or_roll_back`, for the reasons that function's own docstring gives.

    Mints the `own_write` receipt the tool surface promises: the agent authored this prose, so it
    may amend the row without fetching it back. Nothing is revoked alongside it, because a uuid that
    did not exist a moment ago has no other receipts.
    """
    created = await memory.create_within_transaction(
        db,
        gist=prepared.rewrite.gist,
        content=prepared.rewrite.content,
        session_id=call.ctx.session_id,
    )
    rowid = await _rowid_of(db, created.uuid)
    await lexical.insert(db, rowid=rowid, document=_document(created))
    stored = await _write_index(db, row=created, prepared=prepared, index=call.index)
    await memory.mint_own_write_receipt(db, uuid=stored.uuid, version=stored.version, ctx=call.ctx)
    await memory.log_event(
        db,
        ctx=call.ctx,
        kind=EventKind.REMEMBER,
        memory_uuid=stored.uuid,
        detail={"version": stored.version, **_size_detail(prepared.plan)},
    )
    return IndexedWrite(memory=stored, plan=prepared.plan)


async def amend_within_transaction(
    db: aiosqlite.Connection,
    *,
    uuid: str,
    version: int,
    prepared: PreparedIndex,
    call: IndexedCall,
) -> IndexedWrite:
    """`amend`'s work, assuming the caller already holds an open transaction.

    Neither commits nor rolls back, on any path — including the rejection paths, where invariant
    10's carve-out means the audit event and the conflict receipt survive while the mutation does
    not. Only the transaction's owner may decide that, and only `commit_or_roll_back` decides it.

    The order inside is the contract, not a preference. Authorization runs **first**, before any
    index work is staged: a `version_conflict` commits its own audit event and receipt, so index
    work staged ahead of the version check would be durably committed by a *rejected* amend. That is
    why the lexical resync names the pre-write values it removes instead of letting FTS5 read them
    out of the content table, which would have forced it to run before the row update — see
    `lexical.remove`.
    """
    before, after = await memory.amend_within_transaction(
        db, uuid=uuid, version=version, rewrite=prepared.rewrite, ctx=call.ctx
    )
    rowid = await _rowid_of(db, uuid)
    await lexical.resync(db, rowid=rowid, before=_document(before), after=_document(after))
    await vectors.delete_chunks(db, memory_uuid=uuid)
    stored = await _write_index(db, row=after, prepared=prepared, index=call.index)
    await memory.log_event(
        db,
        ctx=call.ctx,
        kind=EventKind.AMEND,
        memory_uuid=uuid,
        detail={
            "from_version": before.version,
            "to_version": after.version,
            **_size_detail(prepared.plan),
        },
    )
    return IndexedWrite(memory=stored, plan=prepared.plan)


#: The SQLite **primary** result codes that mean *the store was locked, try again* rather than *the
#: write failed*. `store_busy` is the one error the design tells a caller it may retry, so
#: collapsing contention into `index_failed` would take a retryable answer and make it look
#: terminal. Primary codes rather than names, because SQLite reports *extended* results — a WAL
#: reader whose snapshot went stale before it tried to write gets `SQLITE_BUSY_SNAPSHOT`, which is
#: contention by every meaning that matters and matches no exact-name test for `SQLITE_BUSY`.
_CONTENTION: Final = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})

#: SQLite packs an extended result as the primary code in its low byte plus a subcode above it.
_PRIMARY_RESULT_MASK: Final = 0xFF


def _driver_failure(error: aiosqlite.Error, *, verb: str) -> ZikaronError:
    """Map a driver-level failure onto the wire contract, contention distinguished from the rest.

    Contention is read off the exception's own SQLite result code rather than its message text: the
    message is prose that varies between builds, while the code is the contract SQLite itself
    publishes. An exception carrying no result code — one constructed rather than raised by the
    driver — is not contention by definition and lands with the general case.
    """
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & _PRIMARY_RESULT_MASK) in _CONTENTION:
        return ZikaronError(ErrorCode.STORE_BUSY, verb=verb)
    return ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.INDEX_WRITE)


async def _finalize(db: aiosqlite.Connection, error: BaseException | None, *, verb: str) -> None:
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
    connection this layer only borrows, and that is accepted rather than overlooked — the holder
    gets an error it can act on, where the alternative is a memory the store claims not to have.

    When this fires while another error is already propagating, the raise replaces it and keeps it
    as the new error's context: the transaction's own outcome is the more useful answer, and
    preserving only the first fault would leave the caller told nothing about the write's fate.
    """
    try:
        await memory.commit_or_roll_back(db, error)
    except aiosqlite.Error as caught:
        mapped = _driver_failure(caught, verb=verb)
        # Unconditional, because rolling back a connection that holds no transaction is a no-op and
        # asking first would only add a branch that means nothing.
        try:
            await db.rollback()
        except aiosqlite.Error:
            with contextlib.suppress(Exception):
                await db.close()
        raise mapped from caught


async def _in_one_transaction[T](db: aiosqlite.Connection, work: _Work[T], *, verb: str) -> T:
    """Run `work` inside one transaction, then commit or roll back per invariant 10.

    Every driver-level failure this verb can hit is mapped, and all three places it can hit one are
    covered: opening the transaction, the work itself, and finalizing. A raw `sqlite3` exception
    escaping would leave whoever serializes the response with no code to send and an operator
    reading a driver traceback out of a JSON-RPC error field.

    A `ZikaronError` passes through untouched, so a rejection keeps its own code — and, for the two
    carve-out codes, its committed audit trail.
    """
    try:
        await db.execute("BEGIN")
    except aiosqlite.Error as caught:
        raise _driver_failure(caught, verb=verb) from caught
    error: BaseException | None = None
    try:
        result = await work(db)
    except aiosqlite.Error as caught:
        error = caught
        raise _driver_failure(caught, verb=verb) from caught
    except BaseException as caught:
        error = caught
        raise
    finally:
        await _finalize(db, error, verb=verb)
    return result


async def remember(
    db: aiosqlite.Connection, *, rewrite: Rewrite, call: IndexedCall
) -> IndexedWrite:
    """Write a new memory and both of its indexes, in one transaction.

    The chunking preflight and the embedding run first, outside the transaction; only the writes are
    inside it.

    Raises:
        ZikaronError: `BOUNDS` if the gist or content is empty or the gist exceeds
            `gist_max_tokens` — refused before anything is written, and refusable precisely because
            the agent still holds its own text and can shorten a gist in the same turn.
            `INDEX_FAILED` if the budget arithmetic, the chunk-budget assertion or the embedder
            failed, or if the store failed while the transaction was being written;
            `STORE_BUSY` if the store was locked, which the caller may retry. Nothing is left
            behind in any of those cases.
    """
    prepared = await prepare(rewrite, index=call.index)

    async def work(connection: aiosqlite.Connection) -> IndexedWrite:
        return await remember_within_transaction(connection, prepared=prepared, call=call)

    return await _in_one_transaction(db, work, verb="remember")


async def amend(
    db: aiosqlite.Connection, *, uuid: str, version: int, rewrite: Rewrite, call: IndexedCall
) -> IndexedWrite:
    """Rewrite a memory's prose and rebuild both of its indexes, in one transaction.

    Raises:
        ZikaronError: `BOUNDS` as `remember`; then the row-level ladder's own rejections —
            `NOT_FOUND`, `VERSION_CONFLICT` (which commits its audit event and mints a receipt at
            the current version), `NO_READ_RECEIPT`, `INACTIVE_ROW`; or `INDEX_FAILED` naming the
            stage, or `STORE_BUSY` under contention, which the caller may retry. In every case the
            prose and both indexes are left exactly as they were.
    """
    prepared = await prepare(rewrite, index=call.index)

    async def work(connection: aiosqlite.Connection) -> IndexedWrite:
        return await amend_within_transaction(
            connection, uuid=uuid, version=version, prepared=prepared, call=call
        )

    return await _in_one_transaction(db, work, verb="amend")
