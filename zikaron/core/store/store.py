"""Schema creation, open/close, and the checks each of those two paths is required to run.

`schema.md` §"Creating the dense index" fixes creation's order because `vec0` fixes a column's
width forever at `CREATE` time: validate the effective `embed_dim`, check the configured
embedder's actual output width against it, *then* create tables — in that order, so a
mismatched model name never produces a store whose every future write fails at insert time
pointing at the wrong culprit. Open re-validates `meta` on every call, per the same document's
"validation happens twice" rule, and refuses to proceed through a `reindexing` sentinel left by
a process that died mid-reindex, or through a `schema_version` this build does not support.
"""

import re
import uuid
from pathlib import Path
from types import TracebackType
from typing import Final, Self
from urllib.parse import quote

import aiosqlite
import sqlite_vec

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.store import ddl, meta, permissions
from zikaron.core.store.embedder import Embedder

#: The schema version every table and invariant in this build implements. Sourced from nowhere
#: else: `zikaron.core.errors.ERROR_SPECS[ErrorCode.SCHEMA_INCOMPATIBLE]`'s payload fixes
#: `supported` to the same integer, and a test asserts the two agree rather than one restating
#: the other: one declaration, checked from two directions, rather than two that agree today.
SUPPORTED_SCHEMA_VERSION: Final = 1

_DB_FILENAME: Final = "memory.db"

#: `vec0` has no introspection function for a column's declared width; the only place it is
#: recorded is the literal `CREATE VIRTUAL TABLE` text `sqlite_master` stores verbatim. Matched
#: as the **whole** value, not a substring search — `sqlite_master.sql` holds exactly one
#: statement per row, so a genuine `vec0` table's row is entirely this shape and nothing else,
#: and searching for the shape *inside* an arbitrary string would accept a table that merely
#: quotes the phrase as data (a `CHECK` constraint's string literal, for instance) without ever
#: being `vec0` at all. `fullmatch` after collapsing whitespace is what makes "the entire
#: recorded statement is this shape" the actual test, rather than "this shape occurs somewhere
#: in the recorded statement."
_VEC0_WIDTH_PATTERN: Final = re.compile(
    r"CREATE\s+VIRTUAL\s+TABLE\s+memory_vec\s+USING\s+vec0\s*\(\s*embedding\s+float\[(\d+)\]\s*\)",
    re.IGNORECASE,
)


async def _physical_vec0_width(db: aiosqlite.Connection) -> int:
    """The width `memory_vec.embedding` was actually created at, read back from its own DDL.

    `meta.embed_dim` records what the store's `meta` row *says* the width is; this reads what
    the column *is*, so invariant 11's check on open cannot be satisfied by a `meta` row that
    agrees with the effective config while the physical column disagrees with both — nor by an
    object merely *named* `memory_vec` that is not a `vec0` virtual table at all. Matching the
    *whole* recorded statement, not searching for the shape somewhere inside it, is what rules
    that second case out: a table whose `CHECK` constraint merely quotes the expected phrase as
    string data would satisfy a substring search without being `vec0` at all, since the phrase
    would then simply be present somewhere in a longer string that is not, as a whole, that
    statement.
    """
    rows = await db.execute_fetchall("SELECT sql FROM sqlite_master WHERE name = 'memory_vec'")
    matches = list(rows)
    if len(matches) != 1:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.META,
            key="memory_vec",
            value=f"{len(matches)} matching tables",
            expected="exactly one memory_vec table",
        )
    (sql,) = matches[0]
    collapsed = re.sub(r"\s+", " ", str(sql)).strip()
    found = _VEC0_WIDTH_PATTERN.fullmatch(collapsed)
    if found is None:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.META,
            key="memory_vec",
            value=str(sql),
            expected="CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[<n>])",
        )
    return int(found.group(1))


async def _read_meta_table(db: aiosqlite.Connection) -> dict[str, str]:
    """Every `meta` row's text value, or an empty mapping if `meta` itself does not exist.

    `existing_only=True` on `_open_connection` stops `Store.open` from *creating* a missing
    store, but it does nothing about an existing `memory.db` whose `meta` table is itself
    absent — dropped by hand, or left behind by a process that failed between creating the
    file and running its DDL. That case must still fail at the Zikaron boundary as
    `bad_config`, not as a raw `sqlite3.OperationalError` bubbling straight out of a driver
    call. Returning an empty mapping rather than raising here reuses `parse_and_validate`'s own
    existing "first required key found missing" reporting — a store with no `meta` table is a
    store missing all five required keys, which is exactly true, and reporting it that way
    costs no second error path.
    """
    try:
        rows = await db.execute_fetchall("SELECT key, value FROM meta")
    except aiosqlite.Error:
        return {}
    return {str(key): str(value) for key, value in rows}


async def _load_sqlite_vec(db: aiosqlite.Connection) -> None:
    """Load the `sqlite-vec` extension on this connection, through `aiosqlite`'s own method.

    `aiosqlite.Connection.load_extension` is the sanctioned path: the wrapped `sqlite3`
    connection lives on `aiosqlite`'s own dedicated worker thread, so reaching into it directly
    to call `sqlite_vec.load()` raises from the caller's thread instead.
    """
    await db.enable_load_extension(True)
    try:
        await db.load_extension(sqlite_vec.loadable_path())
    finally:
        await db.enable_load_extension(False)


async def _open_connection(db_path: Path, *, existing_only: bool = False) -> aiosqlite.Connection:
    """Open `db_path` through `aiosqlite`, with the extension and pragmas every connection needs.

    Never bare `sqlite3`: a handler that called it directly could hold the single-threaded event
    loop for as long as SQLite's own `busy_timeout` retries, which is a genuine, previously
    reproduced self-inflicted deadlock (`design/coding-standards.md` §6) rather than a style
    concern. `aiosqlite` closes that structurally by running the connection on its own thread.

    A failure loading the extension or applying a pragma closes the connection before
    propagating: `aiosqlite.connect` succeeding is not this function succeeding, and a caller
    that only wraps its *own* work in `try`/`except` would otherwise be handed nothing to close
    when the failure happened here instead.

    Args:
        existing_only: when `True`, refuse to create `db_path` if it is absent, via SQLite's
            own `mode=rw` URI option — `Store.open` sets this, because an "open" that silently
            creates an empty database on a missing store is a mutation this operation must not
            perform, and would otherwise leave that empty file at the ambient process umask
            rather than `0600` (`restrictive_umask` only wraps `Store.create`'s connection).
            `Store.create` leaves this `False`, since creating the file is exactly its job.

    Raises:
        ZikaronError: `BAD_CONFIG` if `existing_only` is set and `db_path` does not already
            exist as an openable SQLite database, naming what was expected.
    """
    if existing_only:
        uri = f"file:{quote(str(db_path))}?mode=rw"
        try:
            db = await aiosqlite.connect(uri, uri=True)
        except aiosqlite.Error as error:
            raise ZikaronError(
                ErrorCode.BAD_CONFIG,
                source=BadConfigSource.FILE,
                key="store_dir",
                value=str(db_path),
                expected="an existing, openable memory.db — this store has not been created",
            ) from error
    else:
        db = await aiosqlite.connect(db_path)
    try:
        await _load_sqlite_vec(db)
        for pragma in ddl.PRAGMAS:
            await db.execute(pragma)
    except BaseException:
        await db.close()
        raise
    return db


def _dimension_mismatch(
    config: EffectiveConfig, embed_dim: int, embedder: Embedder
) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        file=str(config.source_of("embed_dim") or "<default>"),
        key="embedding.embed_dim",
        value=str(embed_dim),
        expected=f"the configured embedder ({embedder.model_name}) actually emits "
        f"{embedder.dim}-dimensional vectors",
    )


def _model_name_mismatch(config: EffectiveConfig, embedder: Embedder) -> ZikaronError:
    configured = config.get_str("embed_model")
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        file=str(config.source_of("embed_model") or "<default>"),
        key="embedding.embed_model",
        value=configured,
        expected=f"the embedder passed to create() reports model_name={embedder.model_name!r}, "
        "which must match the configured embed_model — meta seeds from this call's embedder, "
        "not from the config text alone",
    )


def _reindexing_in_progress(since: str) -> ZikaronError:
    return ZikaronError(ErrorCode.REINDEXING, since=since)


def _schema_too_new(found: int) -> ZikaronError:
    return ZikaronError(
        ErrorCode.SCHEMA_INCOMPATIBLE, found=found, supported=SUPPORTED_SCHEMA_VERSION
    )


def _embed_settings_disagree(
    current: meta.StoreMeta, configured_model: str, configured_dim: int
) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.META,
        key="embed_model/embed_dim",
        value=f"{configured_model}/{configured_dim}",
        expected=f"{current.embed_model}/{current.embed_dim} (the values this store was "
        "created with — invariant 11 requires a forced reindex, never a silent continue, "
        "on disagreement)",
    )


def _physical_width_disagrees(recorded_dim: int, physical_width: int) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.META,
        key="embed_dim",
        value=str(recorded_dim),
        expected=f"{physical_width} (the width memory_vec's own column was actually created "
        "at — meta.embed_dim must agree with the physical column, not only with the config, "
        "or a corrupted meta row could silently outlive the vec0 table it describes)",
    )


class Store:
    """An open connection to one Zikaron store, plus the `meta` it was opened with.

    Construct only through `create` or `open`, never directly: both classmethods run the
    validation their path requires before a `Store` exists to hand back, so holding one is
    holding a store already known to satisfy invariants 1, 3 and 11 for this open.
    """

    def __init__(
        self, db: aiosqlite.Connection, db_path: Path, current_meta: meta.StoreMeta
    ) -> None:
        self._db: Final = db
        self.path: Final = db_path
        self.meta: Final = current_meta

    @property
    def connection(self) -> aiosqlite.Connection:
        """The underlying `aiosqlite` connection, for a caller that needs to run its own SQL.

        Exposed rather than wrapped with per-statement methods: this module owns schema creation
        and the open path, and no record behaviour lives here for a method to wrap.
        """
        return self._db

    async def close(self) -> None:
        """Close the underlying connection. Safe to call once; not idempotent."""
        await self._db.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    @classmethod
    async def create(cls, store_dir: Path, config: EffectiveConfig, embedder: Embedder) -> Self:
        """Create a fresh store at `store_dir/memory.db`, or raise before touching any table.

        Order is the contract, not an implementation choice (`schema.md` §"Creating the dense
        index"): the effective `embed_dim` is validated, then the embedder's *actual* reported
        width is checked against it, and only once both hold does any `CREATE` statement run.
        A mismatch is `bad_config` naming both values, with **no database file yet on disk** —
        `store_dir` is created, but `memory.db` is opened only after the check passes, so a
        typo'd model name never produces a store to clean up.

        Args:
            store_dir: the `.zikaron` directory this store lives in. Created at `0700` if
                absent; tightened to it if it exists wider.
            config: the effective configuration to seed `meta` from. Its `embed_dim` and
                `embed_model` become this store's dual-homed `meta` values, authoritative from
                this point on.
            embedder: the configured embedder. Consulted only for `.dim` and `.model_name` —
                creation embeds nothing.

        Raises:
            ZikaronError: `BAD_CONFIG`, naming `embed_dim` and the embedder's actual width, if
                the effective config's `embed_dim` does not equal what `embedder.dim` reports;
                or naming `embed_model`, if `embedder.model_name` disagrees with the configured
                `embed_model` — the config states which model to seed `meta` with, and the
                embedder that actually produced the width check must be that model, not merely
                one of the right dimension.
        """
        embed_dim = config.get_int("embed_dim")
        embed_model = config.get_str("embed_model")
        if embedder.dim != embed_dim:
            raise _dimension_mismatch(config, embed_dim, embedder)
        if embedder.model_name != embed_model:
            raise _model_name_mismatch(config, embedder)

        permissions.ensure_store_dir(store_dir)
        db_path = store_dir / _DB_FILENAME
        chunk_max_tokens = config.get_int("chunk_max_tokens")

        # A pre-existing `memory.db` — left behind by an earlier failed attempt, or widened by
        # an operator's own `chmod` — must be tightened before anything fallible runs, not only
        # after this call succeeds. `enforce_store_file_mode` after a successful create closes
        # the gap for files *this* call creates; it says nothing about a file that was already
        # here and wide before this call started, and a failure partway through must not leave
        # that file exactly as wide as it found it.
        for name in (_DB_FILENAME, _DB_FILENAME + "-wal", _DB_FILENAME + "-shm"):
            permissions.enforce_store_file_mode(store_dir / name)

        with permissions.restrictive_umask():
            db = await _open_connection(db_path)
            try:
                defaults = await cls._create_tables_and_meta(
                    db, embed_dim, embed_model, chunk_max_tokens
                )
            except BaseException:
                await db.close()
                raise

        for name in (_DB_FILENAME, _DB_FILENAME + "-wal", _DB_FILENAME + "-shm"):
            permissions.enforce_store_file_mode(store_dir / name)

        current_meta = meta.parse_and_validate(defaults)
        return cls(db, db_path, current_meta)

    @staticmethod
    async def _create_tables_and_meta(
        db: aiosqlite.Connection, embed_dim: int, embed_model: str, chunk_max_tokens: int
    ) -> dict[str, str]:
        """Run every `CREATE` statement plus the `meta` defaults insert, in one transaction.

        Split out of `create` so that method's own control flow stays about ordering and error
        handling, while this one is purely "what SQL runs" — the two concerns `TRY301` otherwise
        conflates by wanting every raise abstracted out of a `try` block that has no raise of
        its own to abstract.
        """
        await db.execute("BEGIN")
        for statement in ddl.FIXED_STATEMENTS:
            await db.execute(statement)
        await db.execute(ddl.memory_vec_statement(embed_dim))
        store_id = str(uuid.uuid4())
        defaults = dict(
            meta.defaults_at_creation(
                schema_version=SUPPORTED_SCHEMA_VERSION,
                store_id=store_id,
                embed_model=embed_model,
                embed_dim=embed_dim,
                chunk_max_tokens=chunk_max_tokens,
            )
        )
        for key, value in defaults.items():
            await db.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, value))
        await db.commit()
        return defaults

    @classmethod
    async def open(cls, store_dir: Path, config: EffectiveConfig) -> Self:
        """Open an existing store at `store_dir/memory.db`, validating on every call.

        Runs, in order: permission enforcement and the symlink refusal (tightening a store left
        wider than `0700`/`0600` by an older build or an operator's own `chmod`), the
        `reindexing` sentinel check (invariant 3 — a process that died mid-reindex must not be
        read through), all five required `meta` keys (`schema.md`'s "validation happens
        twice"), the `schema_version` gate, invariant 11's physical `memory_vec` width check
        (against `meta`, not only against the config — `meta` can drift from the table it
        describes even when it agrees with the file), and finally invariant 11's
        `embed_model`/`embed_dim` comparison against the effective config.

        Args:
            store_dir: the `.zikaron` directory holding `memory.db`.
            config: the effective configuration this open is running under, compared against
                `meta`'s dual-homed values rather than trusted silently.

        Raises:
            ZikaronError: `BAD_CONFIG` if `store_dir` is a symlink; `REINDEXING` if the sentinel
                is present; `BAD_CONFIG` (`source='meta'`) if a required key is missing,
                unparseable, or out of range, if the physical `memory_vec` column's width
                disagrees with `meta.embed_dim`, or if `embed_model`/`embed_dim` disagrees with
                the effective config (invariant 11); `SCHEMA_INCOMPATIBLE` if
                `meta.schema_version` exceeds `SUPPORTED_SCHEMA_VERSION`.
        """
        permissions.enforce_existing_store_permissions(store_dir)
        db_path = store_dir / _DB_FILENAME
        db = await _open_connection(db_path, existing_only=True)
        try:
            current_meta = await cls._validate_on_open(db, config)
        except BaseException:
            await db.close()
            raise
        return cls(db, db_path, current_meta)

    @staticmethod
    async def _validate_on_open(
        db: aiosqlite.Connection, config: EffectiveConfig
    ) -> meta.StoreMeta:
        """Every check `open` must run before handing back a `Store`, in the required order."""
        raw = await _read_meta_table(db)

        since = raw.get(meta.REINDEXING_KEY)
        if since is not None:
            raise _reindexing_in_progress(since)

        current_meta = meta.parse_and_validate(raw)

        if current_meta.schema_version > SUPPORTED_SCHEMA_VERSION:
            raise _schema_too_new(current_meta.schema_version)

        physical_width = await _physical_vec0_width(db)
        if physical_width != current_meta.embed_dim:
            raise _physical_width_disagrees(current_meta.embed_dim, physical_width)

        configured_model = config.get_str("embed_model")
        configured_dim = config.get_int("embed_dim")
        if current_meta.embed_model != configured_model or current_meta.embed_dim != configured_dim:
            raise _embed_settings_disagree(current_meta, configured_model, configured_dim)

        return current_meta
