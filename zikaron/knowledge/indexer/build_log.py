"""The `knowledge_build` event: what one corpus build cost, and how it ended.

`schema.md` §"What is instrumented, what is not, and why" is normative. A build is the most
expensive operation this product performs and it is the one event no client emits: the indexer opens
`memory.db` directly, so it has no envelope to take a label from and mints its own `session_id` and
`op_id` on the rule every other writer follows — one unit of work, one `op_id`.

**No row write is ever the reason a build reports failure.** A non-contention failure of either
write goes to stderr and the build's own outcome stands: status 0 on the success path, and on the
failure path the *original* exception is what the caller re-raises, so `refused: a build is already
running …` stays that rather than becoming a chained driver error. The build's outcome is the
answer; the row is the audit. That is the same trade the access log takes — losing an audit row is a
measurement gap, corrupting a caller's answer is not — applied to both writers rather than one.

**This writer waits where the access log refuses to, and the asymmetry is the point.** `call`
declines to wait because a caller is holding a response; a build has no latency budget — it has just
spent minutes — and this row is the only record of those minutes. So the write takes its
connection's ordinary `busy_timeout` and swallows contention only after it: the row is dropped by
continuous contention for that whole budget, not by the service happening to be mid-write.
"""

import sys
import time
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import aiosqlite

from zikaron.core.errors import ZikaronError
from zikaron.core.events import (
    BUILD_FAILED_WIRE_NAME,
    MS_PER_SECOND,
    ClientKind,
    EventOrigin,
    KnowledgeBuildDetail,
)
from zikaron.core.knowledge.errors import KnowledgeError
from zikaron.core.knowledge.scan import ScanResult
from zikaron.core.records.memory import log_event
from zikaron.core.store.transactions import in_one_transaction, is_contention, propagate
from zikaron.knowledge.indexer import detach
from zikaron.service.envelope import mint_op_id, mint_session_id

#: The `schema_version` whose `event` `CHECK` first admits this kind. A build against a store below
#: it writes nothing and says nothing: a direct run never migrates (D37), so an unmigrated store is
#: an ordinary state for one rather than a failure to report.
FIRST_SCHEMA_VERSION: Final = 3


def _wire_name(error: BaseException) -> str:
    """The name this failure is recorded under, fixed per exception class.

    A `KnowledgeError` records its own, so one condition keeps one name wherever it appears; a
    `ZikaronError` records its code's, since a build raises those itself and they are not
    "unexpected"; anything else — a driver error, an `OSError`, an exception no layer named —
    records `build_failed`. `internal_error` is deliberately not reused for that remainder: it is a
    wire code, and a build answers no wire.
    """
    if isinstance(error, KnowledgeError):
        return error.wire_name
    if isinstance(error, ZikaronError):
        return error.code.wire_name
    return BUILD_FAILED_WIRE_NAME


@dataclass(frozen=True, slots=True)
class BuildLog:
    """One build's own event row, written on the connection the build already holds.

    Constructed only once a registry `id` is in hand, which is what makes `knowledge_base_id`
    non-null and mean what it says: a refusal reaching no id has no corpus whose cost it is, and a
    row keyed by nothing joins to nothing.
    """

    _connection: aiosqlite.Connection
    _origin: EventOrigin
    _knowledge_base_id: UUID
    _full: bool
    _schema_version: int
    _started: float

    @classmethod
    def opened(
        cls,
        connection: aiosqlite.Connection,
        *,
        knowledge_base_id: UUID,
        full: bool,
        schema_version: int,
        started: float,
    ) -> "BuildLog":
        """Begin recording a build that has bound its corpus, minting this build's own label.

        `started` is the caller's own `time.perf_counter()` reading, taken before the corpus was
        resolved, because `duration_ms` spans the whole build **including the model load**: that is
        the elapsed cost somebody actually paid, and the load is not constant across a cold and a
        warm cache.
        """
        return cls(
            _connection=connection,
            _origin=EventOrigin(
                session_id=mint_session_id(),
                client_kind=ClientKind.INDEXER,
                op_id=mint_op_id(),
            ),
            _knowledge_base_id=knowledge_base_id,
            _full=full,
            _schema_version=schema_version,
            _started=started,
        )

    async def succeeded(self, result: ScanResult) -> None:
        """Record a build that completed, from the scan it left behind.

        **No failure of the row *write* reaches the caller**, which is not the same as never
        raising: the payload is built here, outside `_write`'s guard. `main.build` places this call
        after its own `try`/`except` for exactly that reason — inside it, a failure here would be
        recorded as a *failed build* that in fact completed.
        """
        await self._write(
            KnowledgeBuildDetail(
                knowledge_base_id=str(self._knowledge_base_id),
                spawned_by_op_id=detach.spawned_by_op_id(),
                full=self._full,
                rebuilt=result.rebuilt_identity is not None,
                ok=True,
                error_code=None,
                duration_ms=self._elapsed_ms(),
                files_indexed=result.counters.files_indexed,
            )
        )

    async def failed(self, error: BaseException) -> None:
        """Record a build that did not complete. No failure of the row write reaches the caller.

        Called from inside the catch that exists to record somebody else's failure, so the guard is
        `_write`'s and the caller re-raises the **original** exception rather than this row's.

        `rebuilt` and `files_indexed` are null rather than zero: both are read off the result
        `scan.run` returns only on completion, so a build refused before the scan and one that died
        inside it alike have no corpus to count and no settled answer to whether it rebuilt. `0`
        means a completed scan indexed nothing, which is why neither defaults.
        """
        await self._write(
            KnowledgeBuildDetail(
                knowledge_base_id=str(self._knowledge_base_id),
                spawned_by_op_id=detach.spawned_by_op_id(),
                full=self._full,
                rebuilt=None,
                ok=False,
                error_code=_wire_name(error),
                duration_ms=self._elapsed_ms(),
                files_indexed=None,
            )
        )

    def _elapsed_ms(self) -> float:
        return (time.perf_counter() - self._started) * MS_PER_SECOND

    async def _write(self, detail: KnowledgeBuildDetail) -> None:
        """Attempt the row, reporting a failure to stderr rather than raising it.

        A **fresh** `in_one_transaction` with no read left open on this connection: a stale WAL
        snapshot turns the attempt into an immediate `SQLITE_BUSY_SNAPSHOT`, which `is_contention`
        swallows, leaving no trace of why.
        """
        if self._schema_version < FIRST_SCHEMA_VERSION:
            return

        async def _insert(db: aiosqlite.Connection) -> None:
            await log_event(db, ctx=self._origin, detail=detail, memory_uuid=None)

        try:
            await in_one_transaction(self._connection, _insert, failure=propagate)
        except aiosqlite.Error as error:
            if not is_contention(error):
                _report(f"could not record this build: {error}")
        except Exception as error:
            _report(f"could not record this build: {error}")


def _report(message: str) -> None:
    """Say one line about a row that was not written, on the stream a foreground build prints to.

    Never a raise: this writer exists to record somebody else's outcome, and an exception escaping
    it would replace the very outcome it was recording. Detached, all three streams are `DEVNULL`,
    so this reaches a person only in the foreground — which is where a build is re-run to find out
    why.
    """
    print(message, file=sys.stderr)
