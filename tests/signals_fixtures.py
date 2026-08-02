"""Shared fixtures for `signals` tests: a bare store, and raw `event` row insertion.

Every signal is read-only aggregation over already-committed `event` rows, so these tests build
fixtures by inserting `event` rows directly rather than running `remember`/`amend`/`retire` through
their real verbs — `event` carries no foreign key (`schema.md`'s DDL), so a hermetic row naming a
uuid no `memory` row backs is exactly as legal a fixture as one that does, and building one this way
keeps a signal's test about the signal's own arithmetic rather than about the write path that
produces its inputs.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store

#: A fixed, valid ISO-8601 instant to anchor fixtures on, in exactly `records.memory.timestamp()`'s
#: own format (offset-aware, microseconds, `T` separator) — the format every signal's Python-side
#: deadline comparison assumes, so a fixture using anything else would test a format none of this
#: store's real writers ever produce.
T0 = "2026-01-01T00:00:00.000000+00:00"


def config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


async def open_store(tmp_path: Path) -> Store:
    store_dir = tmp_path / ".zikaron"
    embedder = FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)
    return await Store.create(store_dir, config(tmp_path), embedder)


@dataclass(frozen=True, slots=True)
class Call:
    """The four fields one RPC call holds constant on every `event` row it commits — the fixture
    equivalent of `records.memory.CallParams` plus `at`, minus `max_depth`, which no signal query
    reads. Bundling `at` here too is not a loss of fixture flexibility: every real `event` row one
    call commits shares one instant, since `log_event` reads the clock once per call, so a fixture
    naming two different `at` values for two rows of what is meant to be "one call" would already
    be describing something no real call can produce."""

    at: str
    session_id: str | None
    client_kind: str
    op_id: str


async def insert_event(
    store: Store,
    *,
    call: Call,
    kind: str,
    memory_uuid: str | None,
    detail: dict[str, object] | None = None,
) -> None:
    """One raw `event` row, bypassing `records.memory.log_event` and `EventSpec.validate`.

    Every signal reads `detail` as free-form JSON via `json_extract`, so a fixture states exactly
    the fields one signal's query reads and no more — `EventSpec`'s full, ordered field list is a
    production write-time contract this test helper deliberately does not enforce, since a fixture
    naming three of `merge`'s eleven fields is not thereby an invalid event for a query that reads
    only those three. `detail=None` serializes as an empty object, for a fixture that needs none.
    """
    payload = json.dumps(detail or {})
    await store.connection.execute(
        "INSERT INTO event (at, session_id, client_kind, op_id, kind, memory_uuid, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (call.at, call.session_id, call.client_kind, call.op_id, kind, memory_uuid, payload),
    )
    await store.connection.commit()
