"""Fixtures the retrieval tests share: a real store, real indexes, and a predictable query vector.

Default tier throughout, unmarked: a store on `tmp_path` with real SQLite, real FTS5 and the real
`sqlite-vec` extension is hermetic, deterministic and fast (`coding-standards.md` §4), and both arms
are claims about what those two indexes return, so neither can be checked against a stand-in.

**The store is held with `async with`**, which is the rule for every holder of one and not a test
convenience: the connection's worker thread is non-daemon, so a handle nobody closes keeps its
process alive at exit. `tests/conftest.py` turns a forgotten one into a failure rather than a hang.

Rows are written through the **real** write path — `indexing.writes.remember` — so every chunk,
vector and FTS posting a test retrieves is one the production code produced, and retirement goes
through the real verb, receipt and all. Two facts the write path cannot set are written directly
instead, each for a stated reason: `tier`, because the verb that flips it is M7's, and `created_at`,
because no verb ever sets it and the recency tiebreak needs distinct, ordered values that a
same-millisecond write burst does not produce.
"""

import json
import struct
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tests.fake_encoder import FakeEncoder, vector_for
from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.indexing import writes
from zikaron.core.indexing.chunking import PREFIX_SEPARATOR
from zikaron.core.indexing.writes import IndexedCall, IndexingContext
from zikaron.core.records import memory as records
from zikaron.core.records.memory import CallParams, Rewrite
from zikaron.core.retrieval.reads import ReadCall
from zikaron.core.retrieval.retrieve import RetrievalSettings
from zikaron.core.store.store import Store

MAX_DEPTH: Final = 32


def config(tmp_path: Path, overrides: str = "") -> EffectiveConfig:
    """The effective config for a store under `tmp_path`, optionally amended by TOML text.

    Overrides go through the real two-layer resolution rather than through a hand-built
    `EffectiveConfig`, so a test that lowers `fusion_depth` is also asserting that the key is
    settable the way an operator would set it.
    """
    project = tmp_path / "project.toml"
    project.write_text(overrides, encoding="utf-8")
    return resolve(tmp_path / "system.toml", project)


def ctx(session_id: str = "s1", client_kind: str = "mcp", op_id: str = "op1") -> CallParams:
    return CallParams(
        session_id=session_id, client_kind=client_kind, op_id=op_id, max_depth=MAX_DEPTH
    )


@dataclass(frozen=True, slots=True)
class Harness:
    """An open store, the config and encoder it was opened with, and what a read test does to it.

    The three travel together because every one of these operations needs at least two of them, and
    a test that had to thread them by hand would be free to write a row with one config and read it
    with another — which is a fixture bug that looks like a retrieval bug.
    """

    store: Store
    encoder: FakeEncoder
    config: EffectiveConfig

    @property
    def db(self) -> object:
        """The underlying connection, for a test asserting on stored rows directly."""
        return self.store.connection

    def read_call(self, *, call_ctx: CallParams | None = None) -> ReadCall:
        return ReadCall(
            ctx=call_ctx if call_ctx is not None else ctx(),
            settings=RetrievalSettings.from_config(self.config),
            encoder=self.encoder,
        )

    async def write(self, *, gist: str, content: str, call_ctx: CallParams | None = None) -> str:
        """Write one memory through the real indexed write path and return its uuid."""
        index = IndexingContext.for_store(self.store, self.config, self.encoder)
        written = await writes.remember(
            self.store.connection,
            rewrite=Rewrite(gist=gist, content=content),
            call=IndexedCall(ctx=call_ctx if call_ctx is not None else ctx(), index=index),
        )
        return written.memory.uuid

    async def retire(
        self,
        uuid: str,
        *,
        superseded_by: str | None = None,
        call_ctx: CallParams | None = None,
    ) -> None:
        """Retire through the real verb: `fetch` to earn the receipt, then `retire`."""
        call = call_ctx if call_ctx is not None else ctx()
        found, _ = await records.fetch(self.store.connection, uuids=[uuid], ctx=call)
        await records.retire(
            self.store.connection,
            uuid=uuid,
            version=found[0].version,
            superseded_by=superseded_by,
            ctx=call,
        )

    async def set_tier(self, uuid: str, tier: str) -> None:
        """Set `tier` directly: the verb that flips it is `promote`, which belongs to M7.

        A read path only reads the column, so what matters is that the value is one the `CHECK`
        accepts — not how it got there.
        """
        await self.store.connection.execute(
            "UPDATE memory SET tier = ? WHERE uuid = ?", (tier, uuid)
        )
        await self.store.connection.commit()

    async def set_created_at(self, uuid: str, created_at: str) -> None:
        """Set `created_at` directly: no verb sets it, and the journal-local recency tiebreak needs
        distinct, ordered values."""
        await self.store.connection.execute(
            "UPDATE memory SET created_at = ? WHERE uuid = ?", (created_at, uuid)
        )
        await self.store.connection.commit()

    async def clear_events(self) -> None:
        """Drop the events the fixture's own writes emitted.

        So a read-path assertion can state the **exact** list of rows one call produced, rather than
        excluding the setup's kinds by name — an exclusion is what lets an unexpected extra event go
        unnoticed, which is the whole thing an event-log assertion is for.
        """
        await self.store.connection.execute("DELETE FROM event")
        await self.store.connection.commit()

    async def events(self) -> list[tuple[str, str | None, dict[str, object]]]:
        """Every event row in `id` order as `(kind, memory_uuid, detail)`, with `detail` parsed.

        Parsed rather than compared as text so an assertion can state the fields, their values **and
        their order** — which `EVENT_SPECS` fixes, so that two implementations of one kind produce
        the same payload rather than merely equivalent ones.
        """
        rows = await self.store.connection.execute_fetchall(
            "SELECT kind, memory_uuid, detail FROM event ORDER BY id"
        )
        return [
            (
                str(kind),
                None if memory_uuid is None else str(memory_uuid),
                dict(json.loads(str(detail))),
            )
            for kind, memory_uuid, detail in rows
        ]

    async def envelopes(self) -> list[tuple[str | None, str, str]]:
        """Every event's `(session_id, client_kind, op_id)` in `id` order: invariant 18's fields."""
        rows = await self.store.connection.execute_fetchall(
            "SELECT session_id, client_kind, op_id FROM event ORDER BY id"
        )
        return [
            (None if session_id is None else str(session_id), str(client_kind), str(op_id))
            for session_id, client_kind, op_id in rows
        ]


@asynccontextmanager
async def harness(
    tmp_path: Path, *, encoder: FakeEncoder | None = None, overrides: str = ""
) -> AsyncIterator[Harness]:
    """Create a store under `tmp_path` and close it however the test ends.

    `async with` rather than a plain factory, because the cleanup has to survive a failing
    assertion: the connection's thread is non-daemon, and skipping the close is what turns a
    one-line test failure into a session that never exits.
    """
    used = encoder if encoder is not None else FakeEncoder()
    effective = config(tmp_path, overrides)
    async with await Store.create(tmp_path / ".zikaron", effective, used) as store:
        yield Harness(store=store, encoder=used, config=effective)


def _unit(vector: Sequence[float]) -> tuple[float, ...]:
    norm = sum(value * value for value in vector) ** 0.5
    return tuple(value / norm for value in vector)


def query_vector_for(gist: str, content: str, *, dim: int = 384) -> bytes:
    """The exact vector `FakeEncoder` stored for the first chunk of this `(gist, content)` pair.

    Handed to the dense arm as a query, it puts that memory at distance 0 and therefore at rank 1,
    which is what makes a dense-arm assertion about *ranks* rather than about hash luck. It assumes
    the content fits one chunk, which every fixture here keeps true.
    """
    embedded = f"{gist}{PREFIX_SEPARATOR}{content}"
    values = _unit(vector_for(embedded, dim))
    return struct.pack(f"<{dim}f", *values)
