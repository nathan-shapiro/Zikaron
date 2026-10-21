"""A build is under way from its spawn, not from its lock, and the service answers accordingly.

`knowledge-index.md` §8.4 is normative, and invariant 19 is what these hold. A build loads its model
before it takes its corpus's lock, so the service remembers the process it last spawned per corpus
and the corpus's `last_scan_started_at` as the spawning call read it: while that process is alive
and the mark has not moved, `refresh` and `add` answer `already_indexing` and `remove` refuses.

No build runs. The spawn is replaced by a recorder whose processes the test starts alive or exited,
and a build reaching its lock is stood for by writing the rows it writes.
"""

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.knowledge_fixtures import DEAD_PID, StubProcess, corpus_root, write_meta
from tests.service_fixtures import envelope, open_context
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import lock, meta, registry
from zikaron.core.knowledge import paths as knowledge_paths
from zikaron.knowledge.indexer import detach
from zikaron.service import dispatch_knowledge
from zikaron.service.context import ServiceContext
from zikaron.service.spawned_builds import SpawnedBuilds

_MARK = "2026-10-13T12:00:00+00:00"


@dataclass(slots=True)
class _Spawns:
    """Every build asked for, and the handle each was given: alive unless a test says otherwise."""

    processes: list[StubProcess] = field(default_factory=list)
    alive: bool = True
    pid: int = DEAD_PID

    def spawn(self, name: str, **_options: object) -> StubProcess:
        del name
        process = StubProcess(pid=self.pid, returncode=None if self.alive else 0)
        self.processes.append(process)
        return process


@pytest.fixture(autouse=True)
def spawns(monkeypatch: pytest.MonkeyPatch) -> _Spawns:
    recorded = _Spawns()
    monkeypatch.setattr(detach, "spawn", recorded.spawn)
    return recorded


async def _call(ctx: ServiceContext, method: str, params: dict[str, object]) -> dict[str, object]:
    result = await dispatch_knowledge.KNOWLEDGE_METHODS[method].handler(
        ctx.store.connection, ctx, envelope(), params
    )
    payload = result.as_json()
    assert isinstance(payload, dict)
    return payload


def _only(payload: dict[str, object]) -> dict[str, object]:
    bases = payload["knowledge_bases"]
    assert isinstance(bases, list)
    (one,) = bases
    assert isinstance(one, dict)
    return one


async def _add(ctx: ServiceContext, tmp_path: Path, name: str = "docs") -> dict[str, object]:
    params: dict[str, object] = {
        "name": name,
        "path": str(corpus_root(tmp_path, name)),
        "description": "d",
    }
    return _only(await _call(ctx, "knowledge_add", params))


async def _refresh(ctx: ServiceContext, name: str = "docs") -> dict[str, object]:
    return _only(await _call(ctx, "knowledge_refresh", {"name": name}))


async def _database_of(ctx: ServiceContext, name: str) -> Path:
    registered = await registry.require(ctx.store.connection, name)
    return knowledge_paths.knowledge_db_path(ctx.store_directory, registered.id)


async def _take_the_lock(ctx: ServiceContext, name: str = "docs", *, pid: int) -> None:
    """What a build writes as it takes its lock: the lock rows and a fresh scan mark."""
    await write_meta(
        await _database_of(ctx, name),
        **{
            meta.LAST_SCAN_STARTED_AT_KEY: _MARK,
            meta.LOCK_PID_KEY: str(pid),
            meta.LOCK_HOST_KEY: lock.this_host(),
            meta.LOCK_STARTED_AT_KEY: _MARK,
        },
    )


class TestARefreshWhileASpawnedBuildLoads:
    async def test_invariant_19_it_answers_already_indexing_and_spawns_nothing(
        self, tmp_path: Path, spawns: _Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            assert (await _add(ctx, tmp_path))["outcome"] == "started"
            entry = await _refresh(ctx)
        assert entry["outcome"] == "already_indexing"
        assert len(spawns.processes) == 1
        assert entry["lock"] is None
        assert entry["last_scan_started_at"] is None

    async def test_the_reason_names_the_process_add_spawned(self, tmp_path: Path) -> None:
        """The pid is what a person stops when a build never reaches its lock, so a plain
        `refresh` hands it over rather than a destructive call made in order to be refused."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            entry = await _refresh(ctx)
        assert f"pid {DEAD_PID} on {lock.this_host()}" in str(entry["reason"])

    async def test_beside_a_crashed_builds_lock_it_carries_that_lock_as_dead(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(
                await _database_of(ctx, "docs"),
                **{
                    meta.LOCK_PID_KEY: str(DEAD_PID),
                    meta.LOCK_HOST_KEY: lock.this_host(),
                    meta.LOCK_STARTED_AT_KEY: _MARK,
                },
            )
            entry = await _refresh(ctx)
        assert entry["outcome"] == "already_indexing"
        held = entry["lock"]
        assert isinstance(held, dict)
        assert held["live"] is False

    async def test_once_the_build_holds_its_lock_the_lock_answers(
        self, tmp_path: Path, spawns: _Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await _take_the_lock(ctx, pid=os.getpid())
            entry = await _refresh(ctx)
        assert entry["outcome"] == "already_indexing"
        held = entry["lock"]
        assert isinstance(held, dict)
        assert held["live"] is True
        assert entry["last_scan_started_at"] == _MARK
        assert len(spawns.processes) == 1

    async def test_a_build_that_released_its_lock_and_is_still_exiting_does_not_stop_one(
        self, tmp_path: Path, spawns: _Spawns
    ) -> None:
        """Liveness alone would be too wide: a build tears down after its lock goes, and a refresh
        landing then asked for a build that is not running."""
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(await _database_of(ctx, "docs"), last_scan_started_at=_MARK)
            entry = await _refresh(ctx)
        assert spawns.processes[0].poll() is None, "the first build is still exiting"
        assert entry["outcome"] == "started"
        assert len(spawns.processes) == 2
        assert entry["last_scan_started_at"] == _MARK

    async def test_a_dead_process_is_seen_as_dead_whatever_its_pid(
        self, tmp_path: Path, spawns: _Spawns
    ) -> None:
        """The handle has answered; the pid it was spawned under is this test's own, which any
        probe of the number would find alive."""
        spawns.pid = os.getpid()
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            spawns.processes[0].returncode = 0
            spawns.alive = False
            assert (await _refresh(ctx))["outcome"] == "started"
            removed = await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": True})
        assert removed["removed"] is True
        assert len(spawns.processes) == 2

    async def test_two_dispatched_together_spawn_one_build(
        self, tmp_path: Path, spawns: _Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            spawns.alive = False
            await _add(ctx, tmp_path)
            spawns.alive = True
            first, second = await asyncio.gather(_refresh(ctx), _refresh(ctx))
        outcomes = sorted(str(entry["outcome"]) for entry in (first, second))
        assert outcomes == ["already_indexing", "started"]
        assert len(spawns.processes) == 2

    async def test_a_rename_between_the_spawn_and_the_refresh_changes_nothing(
        self, tmp_path: Path, spawns: _Spawns
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await _call(ctx, "knowledge_rename", {"name": "docs", "new_name": "notes"})
            assert (await _refresh(ctx, "notes"))["outcome"] == "already_indexing"
            with pytest.raises(ZikaronError) as refused:
                await _call(ctx, "knowledge_remove", {"name": "notes", "confirm": True})
        assert refused.value.code is ErrorCode.KNOWLEDGE_BASE_BUSY
        assert len(spawns.processes) == 1


class TestARemovalWhileASpawnedBuildLoads:
    async def test_it_is_refused_busy_naming_the_spawned_process(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            with pytest.raises(ZikaronError) as refused:
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": True})
            still_there = await _database_of(ctx, "docs")
        assert refused.value.code is ErrorCode.KNOWLEDGE_BASE_BUSY
        assert refused.value.data["name"] == "docs"
        assert f"pid {DEAD_PID}" in str(refused.value.data["holder"])
        assert still_there.is_file()

    async def test_the_unconfirmed_preview_is_unchanged(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            with pytest.raises(ZikaronError) as refused:
                await _call(ctx, "knowledge_remove", {"name": "docs", "confirm": False})
        assert refused.value.code is ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED


class TestEveryBuildEntryCarriesTheMarkItsCallRead:
    async def test_a_corpus_never_scanned_carries_null(
        self, tmp_path: Path, spawns: _Spawns
    ) -> None:
        spawns.alive = False
        async with open_context(tmp_path) as ctx:
            entry = await _add(ctx, tmp_path)
        assert entry["last_scan_started_at"] is None
        assert "lock" not in entry, "only an already_indexing entry carries the lock"

    async def test_a_scanned_corpus_carries_its_mark(self, tmp_path: Path, spawns: _Spawns) -> None:
        spawns.alive = False
        async with open_context(tmp_path) as ctx:
            await _add(ctx, tmp_path)
            await write_meta(await _database_of(ctx, "docs"), last_scan_started_at=_MARK)
            entry = await _refresh(ctx)
        assert entry["outcome"] == "started"
        assert entry["last_scan_started_at"] == _MARK


class TestTheTable:
    def test_an_alive_build_with_an_unmoved_mark_is_loading(self) -> None:
        table = SpawnedBuilds()
        kb_id = uuid.uuid4()
        table.record(kb_id, StubProcess(returncode=None), mark=None)
        holder = table.loading(kb_id, mark=None)
        assert holder is not None
        assert holder.pid == DEAD_PID
        assert holder.host == lock.this_host()

    def test_a_moved_mark_drops_the_entry_for_good(self) -> None:
        table = SpawnedBuilds()
        kb_id = uuid.uuid4()
        table.record(kb_id, StubProcess(returncode=None), mark=None)
        assert table.loading(kb_id, mark=_MARK) is None
        assert table.loading(kb_id, mark=None) is None, "dropped, not merely answered"
        assert len(table) == 0

    def test_every_spawn_forgets_the_builds_that_have_exited(self) -> None:
        table = SpawnedBuilds()
        exited = StubProcess(returncode=None)
        table.record(uuid.uuid4(), exited, mark=None)
        exited.returncode = 0
        running = uuid.uuid4()
        table.record(running, StubProcess(returncode=None), mark=None)
        assert len(table) == 1
        assert table.loading(running, mark=None) is not None
