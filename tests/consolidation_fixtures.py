"""Fixtures the consolidation tests share: a real store, controlled cosines, and a consolidator
call.

Default tier, unmarked, for the reason `coding-standards.md` §4 gives: a store on `tmp_path` with
real SQLite, real FTS5 and the real `sqlite-vec` extension is hermetic, deterministic and fast, and
every claim here is a claim about what those indexes and those tables actually hold.

**Cosines are planned, not hoped for.** `write` registers an exact unit vector for the row's own
first chunk, at an angle the caller chooses, so `s(X → Y)` between two fixture rows is `cos(a - b)`
and a test can put a pair deliberately on either side of `anchor_cutoff` or `orphan_edge_cutoff`.
Hashed vectors of unrelated prose are near-orthogonal in 384 dimensions, so without this every pair
scores near zero and one cutoff cannot separate the pairs a graph test needs separated.

**`created_at` is written explicitly wherever order matters.** No verb sets it, and group order is
`(created_at, uuid)` — so a fixture that let a same-millisecond write burst assign it would be
testing the uuid tiebreak by accident rather than the order by design.
"""

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tests.fake_encoder import FakeEncoder, unit_at
from tests.retrieval_fixtures import Harness, ctx, harness
from zikaron.core.consolidation.context import ConsolidationCall, ConsolidationSettings
from zikaron.core.consolidation.groups import Disposition, GroupStatus
from zikaron.core.consolidation.runs import RunStatus
from zikaron.core.events import ClientKind
from zikaron.core.indexing import writes
from zikaron.core.indexing.chunking import GIST_SEPARATOR
from zikaron.core.indexing.writes import IndexedCall, IndexingContext
from zikaron.core.records import memory as records
from zikaron.core.records.memory import CallParams, Rewrite, Tier
from zikaron.core.retrieval.retrieve import RetrievalSettings

#: The consolidator's own session and process, distinct from the primary agent's so that a test
# which
#: forgets to pass one is visibly using the wrong client rather than accidentally correct.
CONSOLIDATOR_SESSION: Final = "consolidator-session"
CONSOLIDATOR_PID: Final = 4242
AGENT_SESSION: Final = "agent-session"

#: A `created_at` per fixture row, ISO-8601 in UTC and one minute apart, so group order is decided
# by
#: the timestamps a test wrote rather than by how fast the writes happened to run.
_MINUTE: Final = "2026-08-02T09:{:02d}:00+00:00"


def created_at(minute: int) -> str:
    """A distinct, ordered `created_at` for fixture row `minute`."""
    return _MINUTE.format(minute)


def consolidator_ctx(*, op_id: str = "op1", session_id: str = CONSOLIDATOR_SESSION) -> CallParams:
    """A `CallParams` for the consolidator: `client_kind='consolidator'`, as its receipts
    require."""
    return ctx(session_id=session_id, client_kind=ClientKind.CONSOLIDATOR.value, op_id=op_id)


@dataclass(frozen=True, slots=True)
class Consolidator:
    """An open store plus everything a consolidation test does to it and reads back out of it."""

    harness: Harness

    def call(
        self,
        *,
        op_id: str = "op1",
        pid: int = CONSOLIDATOR_PID,
        session_id: str = CONSOLIDATOR_SESSION,
        overrides: dict[str, float] | None = None,
    ) -> ConsolidationCall:
        """A `ConsolidationCall` for this store, optionally with settings a test has bent.

        Settings come from the real two-layer config resolution by default, so a test that lowers a
        cutoff is also asserting the key is settable the way an operator would set it; `overrides`
        exists for the handful of cases where the *type*'s own range is what is under test.
        """
        settings = ConsolidationSettings.from_config(self.harness.config)
        if overrides:
            settings = ConsolidationSettings(
                anchor_cutoff=float(overrides.get("anchor_cutoff", settings.anchor_cutoff)),
                orphan_edge_cutoff=float(
                    overrides.get("orphan_edge_cutoff", settings.orphan_edge_cutoff)
                ),
                mutual_k=int(str(overrides.get("mutual_k", settings.mutual_k))),
                group_max=int(str(overrides.get("group_max", settings.group_max))),
                max_group_serves=int(
                    str(overrides.get("max_group_serves", settings.max_group_serves))
                ),
                run_lease_seconds=int(str(overrides.get("run_lease", settings.run_lease_seconds))),
            )
        return ConsolidationCall(
            ctx=consolidator_ctx(op_id=op_id, session_id=session_id),
            pid=pid,
            settings=settings,
            retrieval=RetrievalSettings.from_config(self.harness.config),
            index=IndexingContext.for_store(
                self.harness.store, self.harness.config, self.harness.encoder
            ),
        )

    @property
    def db(self) -> object:
        """The underlying connection, for a test asserting on stored rows directly."""
        return self.harness.store.connection

    async def write(
        self,
        *,
        gist: str,
        content: str,
        minute: int,
        degrees: float | None = None,
        tier: Tier = Tier.JOURNAL,
    ) -> str:
        """Write one memory through the real indexed path, then fix its order and tier.

        `degrees` registers the exact unit vector the encoder will return for this row's own first
        chunk, which is what makes `s(X → Y)` between two fixture rows equal `cos(a - b)`.
        Registered **before** the write, because the write is what embeds.

        `tier` is set directly after the write for the same reason the retrieval fixtures do it: the
        verb that flips a tier is `promote`, and a planning fixture needs long-term rows to exist
        before any verb has run.
        """
        if degrees is not None:
            embedded = f"{gist}{GIST_SEPARATOR}{content}"
            self.harness.encoder.planned[embedded] = unit_at(degrees, self.harness.encoder.dim)
        uuid = await self.harness.write(
            gist=gist, content=content, call_ctx=ctx(session_id=AGENT_SESSION)
        )
        await self.harness.set_created_at(uuid, created_at(minute))
        if tier is not Tier.JOURNAL:
            await self.harness.set_tier(uuid, tier.value)
        return uuid

    async def amend(self, uuid: str, *, gist: str, content: str) -> None:
        """Amend one row through the real primary-agent path: fetch to earn the receipt, then amend.

        Fetch first for the same reason `retrieval_fixtures.Harness.retire` does: a session with no
        receipt for a row it never touched gets `no_read_receipt` regardless of which version it
        presents, since D26's read-before-write is a receipt fact, not a version-guessing game.
        """
        call = ctx(session_id=AGENT_SESSION)
        found, _ = await records.fetch(self.harness.store.connection, uuids=[uuid], ctx=call)
        await writes.amend(
            self.harness.store.connection,
            uuid=uuid,
            version=found[0].version,
            rewrite=Rewrite(gist=gist, content=content),
            call=IndexedCall(
                ctx=call,
                index=IndexingContext.for_store(
                    self.harness.store, self.harness.config, self.harness.encoder
                ),
            ),
        )

    async def runs(self) -> list[tuple[str, str, int, RunStatus]]:
        """Every run as `(run_id, session_id, pid, status)`, in `started_at` order."""
        rows = await self.harness.store.connection.execute_fetchall(
            "SELECT run_id, session_id, pid, status FROM consolidation_run "
            "ORDER BY started_at, run_id"
        )
        return [
            (str(run_id), str(session_id), int(str(pid)), RunStatus(str(status)))
            for run_id, session_id, pid, status in rows
        ]

    async def groups(self) -> list[tuple[str, str | None, str, int, int, GroupStatus, int]]:
        """Every group as `(group_id, anchor_uuid, order_key, shard_index, shard_count, status,
        serve_count)`, in the order a serve considers them."""
        rows = await self.harness.store.connection.execute_fetchall(
            "SELECT group_id, anchor_uuid, order_key, shard_index, shard_count, status, "
            "serve_count FROM consolidation_group ORDER BY order_key, shard_index"
        )
        return [
            (
                str(group_id),
                None if anchor is None else str(anchor),
                str(order_key),
                int(str(shard_index)),
                int(str(shard_count)),
                GroupStatus(str(status)),
                int(str(serve_count)),
            )
            for group_id, anchor, order_key, shard_index, shard_count, status, serve_count in rows
        ]

    async def member_rows(
        self, group_id: str
    ) -> list[tuple[str, int, int | None, Disposition | None]]:
        """One group's members as `(uuid, version_seen, version_served, disposition)`, group
        order."""
        rows = await self.harness.store.connection.execute_fetchall(
            "SELECT mem.memory_uuid, mem.version_seen, mem.version_served, mem.disposition "
            "FROM consolidation_group_member mem JOIN memory m ON m.uuid = mem.memory_uuid "
            "WHERE mem.group_id = ? ORDER BY m.created_at, mem.memory_uuid",
            (group_id,),
        )
        return [
            (
                str(uuid),
                int(str(version_seen)),
                None if version_served is None else int(str(version_served)),
                None if disposition is None else Disposition(str(disposition)),
            )
            for uuid, version_seen, version_served, disposition in rows
        ]

    async def authorization_rows(self, group_id: str) -> list[tuple[str, str, int, int]]:
        """One group's authorization set as `(uuid, role, version_served, rank)`, by rank."""
        rows = await self.harness.store.connection.execute_fetchall(
            "SELECT memory_uuid, role, version_served, rank FROM consolidation_group_candidate "
            "WHERE group_id = ? ORDER BY rank",
            (group_id,),
        )
        return [
            (str(uuid), str(role), int(str(version)), int(str(rank)))
            for uuid, role, version, rank in rows
        ]

    async def receipts(self) -> list[tuple[str, str, str, int, str]]:
        """Every receipt as `(session_id, client_kind, uuid, version, source)`."""
        rows = await self.harness.store.connection.execute_fetchall(
            "SELECT session_id, client_kind, memory_uuid, version, source FROM read_receipt "
            "ORDER BY session_id, client_kind, memory_uuid, version"
        )
        return [
            (str(session), str(kind), str(uuid), int(str(version)), str(source))
            for session, kind, uuid, version, source in rows
        ]

    async def row(self, uuid: str) -> tuple[str, bool, str | None, int]:
        """One memory's `(tier, active, superseded_by, version)`."""
        rows = await self.harness.store.connection.execute_fetchall(
            "SELECT tier, active, superseded_by, version FROM memory WHERE uuid = ?", (uuid,)
        )
        tier, active, superseded_by, version = next(iter(rows))
        return (
            str(tier),
            bool(active),
            None if superseded_by is None else str(superseded_by),
            int(str(version)),
        )

    async def events(self) -> list[tuple[str, str | None, dict[str, object]]]:
        """Every event as `(kind, memory_uuid, detail)` in `id` order, `detail` parsed."""
        return await self.harness.events()

    async def clear_events(self) -> None:
        """Drop the events the fixture's own writes emitted, so an assertion can state an exact
        list."""
        await self.harness.clear_events()

    async def kinds(self, *, only: Sequence[str] | None = None) -> list[str]:
        """Every event kind in order, optionally restricted to a named set."""
        found = [kind for kind, _, _ in await self.events()]
        return found if only is None else [kind for kind in found if kind in set(only)]

    async def lapse_lease(self, run_id: str) -> None:
        """Move one run's `expires_at` into the past, so its lease has provably lapsed.

        Written directly because nothing in the API can make time pass: the lease is derived from
        `started_at` plus a configured duration, and the alternative — a 60-second minimum lease
        and a sleeping test — trades a fast, exact fixture for a slow, flaky one.
        """
        await self.harness.store.connection.execute(
            "UPDATE consolidation_run SET expires_at = ? WHERE run_id = ?",
            ("2000-01-01T00:00:00+00:00", run_id),
        )
        await self.harness.store.connection.commit()

    async def expires_at(self, run_id: str) -> str:
        rows = await self.harness.store.connection.execute_fetchall(
            "SELECT expires_at FROM consolidation_run WHERE run_id = ?", (run_id,)
        )
        return str(next(iter(rows))[0])

    async def insert_second_active_run(self, *, run_id: str = "second") -> None:
        """Write a second `status='active'` run directly, which invariant 15 forbids.

        The only way to reach that state: `plan_groups` closes every active run before creating
        another, so a test that needs the reader's refusal has to construct the broken store by
        hand.
        """
        await self.harness.store.connection.execute(
            "INSERT INTO consolidation_run "
            "(run_id, session_id, pid, started_at, expires_at, status) "
            "VALUES (?, ?, ?, ?, ?, 'active')",
            (run_id, "other", 1, created_at(0), "2099-01-01T00:00:00+00:00"),
        )
        await self.harness.store.connection.commit()


@asynccontextmanager
async def consolidator(
    tmp_path: Path, *, overrides: str = "", encoder: FakeEncoder | None = None
) -> AsyncIterator[Consolidator]:
    """Create a store under `tmp_path` and close it however the test ends."""
    async with harness(tmp_path, overrides=overrides, encoder=encoder) as open_harness:
        yield Consolidator(harness=open_harness)


def detail_of(
    events: Sequence[tuple[str, str | None, dict[str, object]]], kind: str
) -> list[dict[str, object]]:
    """Every `detail` of one kind, in order — for asserting a payload rather than only a count."""
    return [detail for event_kind, _, detail in events if event_kind == kind]


def dumps(value: object) -> str:
    """Canonical JSON, for a determinism assertion that compares two payloads byte for byte."""
    return json.dumps(value, sort_keys=True, default=str)
