"""Creating and opening one knowledge base's database.

The same two paths `Store` has, and the same contract — validate on creation, re-validate on
every open — with one difference that is the reason a knowledge base can be created at all
without paying for a model load: **`embed_dim` is taken from configuration and never checked
against a loaded encoder.**

That is a real trade rather than an oversight. `Store.create` loads the configured embedder and
compares its actual output width before creating a table `vec0` will fix forever, so a typo'd
model name is refused with no database on disk. Here the same typo produces a knowledge base whose
first embedding write fails — recovered by the encoder-mismatch repair, which has to exist anyway
because configuration can change under a knowledge base that is already built. What is bought is
that creating a corpus costs no `fastembed` import and no model load on the caller's critical
path, which is a cost measured at roughly a second and deliberately moved off it.
"""

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, Self
from uuid import UUID

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import ddl, meta, paths
from zikaron.core.store import permissions
from zikaron.core.store.connection import open_connection
from zikaron.core.store.transactions import in_one_transaction


def _schema_too_new(found: int) -> ZikaronError:
    return ZikaronError(
        ErrorCode.SCHEMA_INCOMPATIBLE, found=found, supported=meta.SUPPORTED_SCHEMA_VERSION
    )


def _propagate(_error: aiosqlite.Error) -> None:
    """Name a driver failure during schema creation as itself.

    No wire code describes "creating a knowledge base's tables failed" — `index_failed` speaks of
    index maintenance on the memory store — so the driver's own error is the honest answer, and
    whichever lifecycle verb was running reports it.
    """


@dataclass(frozen=True, slots=True)
class NewKnowledgeBase:
    """What a caller has to say to define a corpus, independent of how they said it.

    One type rather than a long parameter list, because two surfaces construct exactly this — a
    command's parsed arguments and a tool call's validated payload — and a parameter list would
    let the two drift into accepting different things.

    Everything here is already validated by the time one exists: `name` is normalized, `root` is
    resolved, and `max_file_bytes` is either in range or absent.
    """

    name: str
    root: Path
    description: str
    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    git_mode: meta.GitMode = meta.GitMode.TRACKED
    max_file_bytes: int | None = None


def seed_identity(
    kb_id: UUID, spec: NewKnowledgeBase, config: EffectiveConfig
) -> meta.KnowledgeMeta:
    """The `meta` a fresh knowledge base is created with, seeded from configuration.

    Every per-knowledge-base setting is persisted at creation rather than read from configuration
    later. A setting accepted and not persisted would be silently undone by the next build, which
    would re-walk under the global default and change the corpus the caller defined.

    `root` is stored already resolved, because a relative path would name different directories
    from different working directories and the value has to outlive the call.

    Args:
        kb_id: the id the registry generated.
        spec: the validated definition. Its `name` is stored as a breadcrumb only — the registry
            owns the authoritative one.
        config: the effective configuration to seed the tuning keys from.
    """
    configured_cap = config.get_int("knowledge_max_file_bytes")
    return meta.KnowledgeMeta(
        schema_version=meta.SUPPORTED_SCHEMA_VERSION,
        id=kb_id,
        name_breadcrumb=spec.name,
        root_path=str(spec.root),
        include_globs=spec.include_globs,
        exclude_globs=spec.exclude_globs,
        git_mode=spec.git_mode,
        embed_model=config.get_str("embed_model"),
        embed_dim=config.get_int("embed_dim"),
        chunk_max_tokens=config.get_int("chunk_max_tokens"),
        rrf_k=config.get_int("rrf_k"),
        fusion_depth=config.get_int("fusion_depth"),
        max_file_bytes=spec.max_file_bytes if spec.max_file_bytes is not None else configured_cap,
    )


async def read_meta(db: aiosqlite.Connection) -> dict[str, str]:
    """Every `meta` row's text value, or an empty mapping if `meta` itself does not exist.

    Returning an empty mapping rather than raising reuses `parse_and_validate`'s own "first
    required key found missing" reporting: a database with no `meta` table is one missing every
    required key, which is exactly true, and reporting it that way costs no second error path.
    """
    try:
        rows = await db.execute_fetchall("SELECT key, value FROM meta")
    except aiosqlite.Error:
        return {}
    return {str(key): str(value) for key, value in rows}


def encoder_matches_config(current: meta.KnowledgeMeta, config: EffectiveConfig) -> bool:
    """Whether this knowledge base's recorded encoder identity still agrees with configuration.

    The one divergence this store cannot serve around: vectors labelled with a model that did not
    produce them. Every other tuning key is deliberately **not** compared — those are absorbed per
    knowledge base at creation precisely so that changing a global default does not invalidate an
    index that is already built. Same seeding mechanism, opposite policy.
    """
    return current.embed_model == config.get_str(
        "embed_model"
    ) and current.embed_dim == config.get_int("embed_dim")


def _remove_quietly(db_path: Path) -> None:
    """Delete a database this call created, and its journal siblings, ignoring what is not there.

    Best effort on purpose: it runs while another failure is already propagating, and that failure
    is the one worth reporting. A file left behind here is the lesser harm and is visible as an
    orphan.
    """
    for path in permissions.database_files(db_path):
        with contextlib.suppress(OSError):
            path.unlink()


class KnowledgeDatabase:
    """An open connection to one knowledge base, plus the `meta` it was opened with.

    Construct only through `create` or `open`, never directly: both classmethods run the
    validation their path requires before an instance exists to hand back.

    Held with `async with`, or closed in a `finally`. That is a rule about process exit rather
    than tidiness — `aiosqlite` runs each connection on a dedicated **non-daemon** thread, so a
    connection nobody closes keeps its process alive after all its work is done, printing nothing
    while not exiting, with no hook late enough to rescue it.
    """

    def __init__(
        self, db: aiosqlite.Connection, db_path: Path, current_meta: meta.KnowledgeMeta
    ) -> None:
        self._db: Final = db
        self.path: Final = db_path
        self.meta: Final = current_meta

    @property
    def connection(self) -> aiosqlite.Connection:
        """The underlying `aiosqlite` connection, for a caller that needs to run its own SQL."""
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
    async def create(cls, store_dir: Path, identity: meta.KnowledgeMeta) -> Self:
        """Create this knowledge base's database, with the full schema and its `meta` seeded.

        The knowledge directory is created at `0700` and the three database files at `0600`, the
        same modes the memory store uses and for the same reason: a knowledge base holds the text
        of every file it indexed, so it is exactly as sensitive as whatever it was pointed at.

        Args:
            store_dir: the `.zikaron` directory this store lives in.
            identity: the `meta` to seed, already validated by having been constructed.

        Raises:
            FileExistsError: something is already at this path. Not a state to absorb — the path
                is named by a freshly generated uuid4, so a file there is an anomaly worth
                stopping for rather than a knowledge base to adopt.
            ZikaronError: `BAD_CONFIG` if the store directory is reached through a symlink.
        """
        directory = paths.knowledge_dir(store_dir)
        db_path = paths.knowledge_db_path(store_dir, identity.id)
        if db_path.exists():
            raise FileExistsError(f"a knowledge base database already exists at {db_path}")

        await asyncio.to_thread(permissions.ensure_store_dir, directory)

        # Every step from here on either creates the file or runs with it already created, so all
        # of them share one failure handler. Connecting is itself a creating step: SQLite makes the
        # file before anything in this method can fail, and a failure afterwards would otherwise
        # leave a registered knowledge base pointing at an empty database with no `meta` — which
        # reads back as *this index cannot be opened*, the one state that says a rebuild will not
        # help, for a condition a rebuild fixes completely. Removing what this call made collapses
        # every such failure into the absent-database state instead: an empty knowledge base the
        # next build fills in with nobody's involvement.
        #
        # Deleting is safe precisely because of the check above, which has just established the
        # path was empty — so anything there now was made by this call. `db` is bound before the
        # block so the handler can close a connection that was established and then abandoned; the
        # cost of not closing one is not a leaked handle but a non-daemon thread that keeps the
        # whole process alive after its work is done, printing nothing.
        db: aiosqlite.Connection | None = None
        try:
            with permissions.restrictive_umask():
                db, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS)
                await cls._create_tables_and_meta(db, identity, ddl.FIXED_STATEMENTS)
            for path in permissions.database_files(db_path):
                await asyncio.to_thread(permissions.enforce_store_file_mode, path)
        except BaseException:
            if db is not None:
                await db.close()
            await asyncio.to_thread(_remove_quietly, db_path)
            raise

        return cls(db, db_path, identity)

    @staticmethod
    async def _create_tables_and_meta(
        db: aiosqlite.Connection,
        identity: meta.KnowledgeMeta,
        statements: Sequence[str],
    ) -> None:
        """Run every `CREATE` statement plus the `meta` seed, in one transaction.

        Statement by statement through `in_one_transaction`, which issues an explicit `BEGIN`, and
        never as an `executescript`. Both halves matter and both are measured: `sqlite3`'s legacy
        transaction control opens an implicit transaction only before DML, so a `CREATE` issued
        with none open runs in autocommit and a later rollback does not undo it; and
        `executescript` commits any open transaction before running, which dissolves the atomicity
        outright. A half-created knowledge base that survived a failure would be indistinguishable
        from a complete one on every later open.

        `statements` is passed rather than read from the module so the rollback can be exercised
        directly, with the database left in place to be inspected — it cannot be checked through
        `create`, which deletes the file on failure, where a transactional and an autocommitting
        implementation both leave nothing and the assertion says nothing. It has **no default**,
        deliberately: a default naming a module attribute is bound once at import, so the value a
        caller thought it was substituting would never arrive.
        """

        async def _work(connection: aiosqlite.Connection) -> None:
            for statement in statements:
                await connection.execute(statement)
            await connection.execute(ddl.chunks_vec_statement(identity.embed_dim))
            for key, value in meta.defaults_at_creation(identity).items():
                await connection.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?)", (key, value)
                )

        await in_one_transaction(db, _work, failure=_propagate)

    @classmethod
    async def open(cls, store_dir: Path, kb_id: UUID) -> Self:
        """Open an existing knowledge base, validating its `meta` on every call.

        Deliberately takes no configuration to compare against. A knowledge base whose recorded
        encoder identity has diverged from the configured one is **not** a failure to open — it is
        a state a caller reports and a build repairs — and refusing here would deny that caller the
        very fields it needs in order to say so.

        Raises:
            aiosqlite.Error: the database is absent or cannot be opened. Absence is not an error
                to this module's callers — it is an empty knowledge base — so telling the two
                apart is left to them, who know which they are looking at.
            ZikaronError: `BAD_CONFIG` (`source='meta'`) if a required key is missing, unparseable
                or out of range; `SCHEMA_INCOMPATIBLE` if `meta.schema_version` is newer than this
                build supports.
        """
        db_path = paths.knowledge_db_path(store_dir, kb_id)
        db, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)
        try:
            current_meta = await cls._validate_on_open(db)
        except BaseException:
            await db.close()
            raise
        return cls(db, db_path, current_meta)

    @staticmethod
    async def _validate_on_open(db: aiosqlite.Connection) -> meta.KnowledgeMeta:
        """Every check `open` must run before handing back a database, in the required order."""
        raw = await read_meta(db)
        current_meta = meta.parse_and_validate(raw)
        if current_meta.schema_version > meta.SUPPORTED_SCHEMA_VERSION:
            raise _schema_too_new(current_meta.schema_version)
        return current_meta
