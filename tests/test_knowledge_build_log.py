"""The `knowledge_build` event: what a build records, and what it refuses to let the row cost it.

`design/schema.md` §"What is instrumented, what is not, and why" is normative. A build is the most
expensive operation the product performs and the one event no client emits, so two properties carry
this module and they pull in opposite directions:

- **the row exists for every outcome a build's own code reaches**, success or refusal, because the
  question it answers is what building this corpus has cost over time and a failed build is part of
  that history;
- **no row write is ever the reason a build reports failure**, on either path, because the build's
  outcome is the answer and the row is the audit.

**Default tier with a stubbed `build_settings`.** The real one loads `FastEmbedEncoder`, which is a
second of CPU per test and proves nothing about the log; the decisions a build reports are tested
against the deterministic encoder in `zikaron.core.knowledge`'s own suites.
"""

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import build_settings, config_for, corpus_root, write_meta
from zikaron.core.clock import timestamp
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.events import (
    BUILD_FAILED_WIRE_NAME,
    MS_PER_SECOND,
    ClientKind,
    EventKind,
)
from zikaron.core.knowledge import lifecycle, registry, scan
from zikaron.core.knowledge import meta as knowledge_meta
from zikaron.core.knowledge import paths as knowledge_paths
from zikaron.core.knowledge.errors import (
    CorpusRootMissingError,
    IndexerBusyError,
    UnknownKnowledgeBaseError,
)
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.store import ddl
from zikaron.core.store.connection import open_connection
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.knowledge import scope
from zikaron.knowledge.indexer import build_log, detach
from zikaron.knowledge.indexer import main as indexer_main

#: The `op_id` a spawning verb would have put in the child's environment.
_SPAWNING_OP_ID = "op-that-asked"


@pytest.fixture(autouse=True)
def _deterministic_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the real model load, which every build in this file would otherwise pay."""

    async def _settings(config: object, *, full: bool = False) -> object:
        return build_settings(config, encoder=FakeEncoder(), full=full)  # type: ignore[arg-type]

    monkeypatch.setattr(indexer_main, "build_settings", _settings)


@pytest.fixture(autouse=True)
def _no_inherited_attribution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test with no spawning `op_id` in the environment.

    A developer's shell that happened to export it would otherwise attribute every build here to
    that value, which is the failure `detach.spawn`'s per-spawn copy exists to prevent.
    """
    monkeypatch.delenv(detach.SPAWNED_BY_OP_ID_VARIABLE, raising=False)


def _project(tmp_path: Path, *, register: bool = True) -> Path:
    """A store with one corpus registered over a real directory, without the CLI.

    Registered through `core.knowledge.lifecycle` rather than through a management verb, which would
    start a real service and spawn a real build of its own.
    """
    config = config_for(tmp_path)
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
    corpus_root(tmp_path)

    async def _create() -> None:
        async with await Store.create(tmp_path / ".zikaron", config, embedder) as store:
            if register:
                await lifecycle.add(
                    tmp_path / ".zikaron",
                    store.connection,
                    config,
                    lifecycle.AddRequest(
                        name="docs",
                        root=tmp_path / "docs",
                        description="architecture records",
                        git_mode=GitMode.OFF,
                    ),
                )

    asyncio.run(_create())
    return tmp_path


def _build(project: Path, *, name: str = "docs", full: bool = False) -> int:
    """Run one build in-process, exactly as the command's own entry point does."""

    async def _run() -> int:
        async with scope.open_store(project) as store:
            return await indexer_main.build(store, name=name, full=full)

    return asyncio.run(_run())


def _rows(project: Path, kind: EventKind = EventKind.KNOWLEDGE_BUILD) -> list[dict[str, object]]:
    """Every event of `kind`, with its envelope columns folded in beside the detail's own keys."""
    with closing(sqlite3.connect(project / ".zikaron" / "memory.db")) as connection:
        found = connection.execute(
            "SELECT client_kind, session_id, op_id, detail FROM event WHERE kind = ? ORDER BY id",
            (kind.value,),
        ).fetchall()
    return [
        {"client_kind": client, "session_id": session, "op_id": op, **json.loads(detail)}
        for client, session, op, detail in found
    ]


def _registry_id(project: Path) -> str:
    async def _read() -> str:
        async with scope.open_store(project) as store:
            await registry.ensure(store.connection)
            return str((await registry.require(store.connection, "docs")).id)

    return asyncio.run(_read())


class TestWhatACompletedBuildRecords:
    def test_it_records_the_corpus_the_work_and_the_cost(self, tmp_path: Path) -> None:
        """Keyed by the registry **`id`**, never the name: `knowledge_rename` exists, and a cost
        history keyed by a renameable field breaks at the rename."""
        project = _project(tmp_path)
        assert _build(project) == 0
        (row,) = _rows(project)
        assert row["knowledge_base_id"] == _registry_id(project)
        assert row["ok"] is True
        assert row["error_code"] is None
        assert row["full"] is False
        assert row["rebuilt"] is False
        assert row["files_indexed"] == 1
        assert isinstance(row["duration_ms"], float)

    def test_it_is_the_one_event_no_client_emits(self, tmp_path: Path) -> None:
        """A build has no envelope to take a label from, so it mints its own — and files itself
        under a `client_kind` no request may carry, which keeps the linkage signals honest."""
        project = _project(tmp_path)
        _build(project)
        (row,) = _rows(project)
        assert row["client_kind"] == ClientKind.INDEXER.value
        assert str(row["session_id"]).startswith("zk-")
        assert row["op_id"]

    def test_the_flag_asked_for_and_the_rebuild_that_happened_are_separate_fields(
        self, tmp_path: Path
    ) -> None:
        """An identity change reindexes the whole corpus at `full=false`, so a history grouped by
        `full` alone files those minutes under "incremental"."""
        project = _project(tmp_path)
        _build(project)
        _rewrite_recorded_model(project)
        _build(project)
        first, second = _rows(project)
        assert (first["full"], first["rebuilt"]) == (False, False)
        assert (second["full"], second["rebuilt"]) == (False, True)

    def test_the_count_is_the_corpus_left_behind_rather_than_what_this_build_wrote(
        self, tmp_path: Path
    ) -> None:
        """`counters.py`'s own reading, so a no-change rescan reports what the full build before it
        did rather than zero."""
        project = _project(tmp_path)
        _build(project)
        _build(project)
        first, second = _rows(project)
        assert first["files_indexed"] == second["files_indexed"] == 1


def _rewrite_recorded_model(project: Path) -> None:
    """Move the model the corpus claims, so the next build rebuilds at the new identity."""
    databases = sorted((project / ".zikaron" / "knowledge").glob("*.db"))
    with closing(sqlite3.connect(databases[0])) as connection:
        connection.execute("UPDATE meta SET value = 'some-other-model' WHERE key = 'embed_model'")
        connection.commit()


class TestAttribution:
    def test_a_spawning_op_id_in_the_environment_is_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without this edge nothing joins a build's cost to its requester: the build mints a label
        of its own, and only the spawning `call` row knows whether an agent or a person asked."""
        monkeypatch.setenv(detach.SPAWNED_BY_OP_ID_VARIABLE, _SPAWNING_OP_ID)
        project = _project(tmp_path)
        _build(project)
        (row,) = _rows(project)
        assert row["spawned_by_op_id"] == _SPAWNING_OP_ID

    def test_a_foreground_run_records_no_attribution(self, tmp_path: Path) -> None:
        """Null rather than invented. A re-run of a printed `foreground_command` never carries the
        token, because it travels outside the argv — which is what keeps that printed command the
        one that reproduces the build."""
        project = _project(tmp_path)
        _build(project)
        (row,) = _rows(project)
        assert row["spawned_by_op_id"] is None

    def test_a_second_spawn_without_a_token_is_not_attributed_to_the_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A **per-spawn copy** of the environment, never an assignment into this process's own.

        A long-lived service spawning many builds would otherwise attribute every later one to the
        first caller, and the row would look complete while being wrong. The copy also **omits** the
        variable when none is passed, rather than inheriting one.
        """
        spawned: list[dict[str, str] | None] = []

        def _record(argv: list[str], **keywords: object) -> object:
            del argv
            environment = keywords.get("env")
            assert environment is None or isinstance(environment, dict)
            spawned.append(environment)
            raise _SpawnStoppedError

        monkeypatch.setattr(subprocess, "Popen", _record)
        for token in (_SPAWNING_OP_ID, None):
            with pytest.raises(_SpawnStoppedError):
                detach.spawn("docs", project=tmp_path, spawned_by_op_id=token)

        first, second = spawned
        assert first is not None
        assert second is not None
        assert first[detach.SPAWNED_BY_OP_ID_VARIABLE] == _SPAWNING_OP_ID
        assert detach.SPAWNED_BY_OP_ID_VARIABLE not in second
        assert detach.SPAWNED_BY_OP_ID_VARIABLE not in os.environ


class _SpawnStoppedError(Exception):
    """Raised in place of starting a child, so a spawn's arguments are recorded and nothing runs."""


class TestWhichFailuresGetARow:
    def test_a_refusal_before_an_id_is_bound_writes_nothing(self, tmp_path: Path) -> None:
        """The rule is **positional**, not by class: `require` runs outside the `try`, so nothing
        raised before it returns has a corpus whose cost it is, and a row keyed by nothing joins to
        nothing.

        **The refusal is asserted, not only the absent row.** On a store no knowledge verb has
        touched, a `require` hoisted above `registry.ensure` would fail with *no such table* — which
        also writes no row, so the no-row half alone is satisfied by the crash too.
        """
        project = _project(tmp_path, register=False)
        with pytest.raises(UnknownKnowledgeBaseError):
            _build(project, name="nothing-by-that-name")
        assert _rows(project) == []

    def test_a_refusal_after_the_id_is_bound_records_that_class_s_name(
        self, tmp_path: Path
    ) -> None:
        """A child re-establishes every refusal for itself — the service's check and the build are
        not one transaction — so `prepare` can refuse inside a process that started. That is a build
        with a row: one condition, one name, wherever it appears."""
        project = _project(tmp_path)
        (project / "docs").rename(project / "docs-moved")
        with pytest.raises(CorpusRootMissingError):
            _build(project)
        (row,) = _rows(project)
        assert row["ok"] is False
        assert row["error_code"] == CorpusRootMissingError.wire_name
        assert row["files_indexed"] is None
        assert row["rebuilt"] is None

    def test_a_busy_corpus_records_the_name_the_wire_would_have_used(self, tmp_path: Path) -> None:
        """An agent's `refresh` racing an operator's foreground run is the ordinary way here.

        The name is the `ErrorCode`'s, held equal by test, so a query cannot tell a refused build
        apart from a refused call by the spelling.
        """
        project = _project(tmp_path)
        _hold_the_lock(project)
        with pytest.raises(IndexerBusyError):
            _build(project)
        (row,) = _rows(project)
        assert row["error_code"] == ErrorCode.KNOWLEDGE_BASE_BUSY.wire_name

    def test_a_zikaron_error_from_inside_the_scan_records_its_code_s_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The embed stage, which is the case whose omission would have crashed a build inside the
        write that records its failure: were `index_failed` outside the declared value set,
        `EventSpec.validate` would raise there and the one failure worth recording would be lost."""
        project = _project(tmp_path)

        async def _explode(*_args: object, **_keywords: object) -> object:
            raise ZikaronError(ErrorCode.INDEX_FAILED, stage="embed")

        monkeypatch.setattr(scan, "run", _explode)
        with pytest.raises(ZikaronError):
            _build(project)
        (row,) = _rows(project)
        assert row["ok"] is False
        assert row["error_code"] == ErrorCode.INDEX_FAILED.wire_name
        assert row["files_indexed"] is None

    def test_a_failure_no_layer_named_records_the_remainder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`build_failed` rather than `internal_error`: that one names a wire code, and a build
        answers no wire."""
        project = _project(tmp_path)

        async def _explode(*_args: object, **_keywords: object) -> object:
            raise RuntimeError("a driver error, an OSError, an exception no layer named")

        monkeypatch.setattr(scan, "run", _explode)
        with pytest.raises(RuntimeError):
            _build(project)
        (row,) = _rows(project)
        assert row["error_code"] == BUILD_FAILED_WIRE_NAME


def _hold_the_lock(project: Path) -> None:
    """Plant a lock naming this process, so the next build refuses as busy.

    Written into the corpus's own `meta` rather than taken through `lock.acquire`, on
    `knowledge_fixtures.write_meta`'s reasoning: what is under test is the reader, and there is no
    build here to write the rows for real. This process's own pid is what makes the holder
    unmistakably live, which is the reading `builds.plan` refuses on.
    """

    async def _plant() -> None:
        async with scope.open_store(project) as store:
            registered = await registry.require(store.connection, "docs")
            await write_meta(
                knowledge_paths.knowledge_db_path(store.directory, registered.id),
                **{
                    knowledge_meta.LOCK_PID_KEY: str(os.getpid()),
                    knowledge_meta.LOCK_HOST_KEY: socket.gethostname(),
                    knowledge_meta.LOCK_STARTED_AT_KEY: timestamp(),
                },
            )

    asyncio.run(_plant())


class TestWhatTheRowMayNotCost:
    def test_a_store_below_schema_three_attempts_no_write_and_raises_nothing(
        self, tmp_path: Path
    ) -> None:
        """A direct build never migrates (D37), so an unmigrated store is an **ordinary state** for
        one rather than a failure to print — which is why the build decides from the version it was
        handed rather than writing a row and catching the `CHECK`."""
        project = _project(tmp_path)
        _set_schema_version(project, build_log.FIRST_SCHEMA_VERSION - 1)
        assert _build(project) == 0
        assert _rows(project) == []

    def test_a_row_write_that_fails_after_a_completed_scan_leaves_the_build_reported_as_built(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Status 0, the report intact, and **one line on stderr**, so a silent swallow fails here.

        Attempted after the report and after the `try`/`except`: inside it, a non-contention failure
        of the success write would enter the failure catch, write a *second* row saying `ok=false`
        for a build that completed, and re-raise.
        """
        project = _project(tmp_path)
        _break_the_row_write(monkeypatch)
        assert _build(project) == 0
        captured = capsys.readouterr()
        assert "built     'docs'" in captured.out
        assert captured.err.strip().count("\n") == 0
        assert "could not record this build" in captured.err
        assert _rows(project) == []

    def test_a_driver_error_that_is_not_contention_is_reported_like_any_other_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The driver arm, which no test driving real contention reaches.

        A build polls for the write lock for its whole budget rather than dropping its row, so
        contention *resolves* instead of raising. What has to be told apart from it is the driver
        failure that will not resolve: a lock means the row lands on a later build, a `disk I/O
        error` means the store is failing, and swallowing the second as though it were the first is
        the one outcome that leaves no trace of why.
        """
        project = _project(tmp_path)

        async def _explode(*_args: object, **_keywords: object) -> object:
            raise aiosqlite.OperationalError("disk I/O error")

        monkeypatch.setattr(build_log, "log_event", _explode)
        assert _build(project) == 0
        captured = capsys.readouterr()
        assert "could not record this build" in captured.err
        assert "disk I/O error" in captured.err
        assert _rows(project) == []

    def test_a_contention_error_is_swallowed_rather_than_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other side of the arm above, and the reason it tests the result code not the message.

        A lock means the row will land on a later build and there is nothing for the operator to do,
        so reporting it would train them to ignore the line that matters. The code is **injected**
        here rather than reproduced: the real route is a lock held past the connection's whole
        budget, and waiting that out would test the transaction helper instead of this arm.
        """
        project = _project(tmp_path)

        class _Locked(aiosqlite.OperationalError):
            """What the driver raises on a lock: the result code, not the message, is the signal."""

            sqlite_errorcode = sqlite3.SQLITE_BUSY

        async def _explode(*_args: object, **_keywords: object) -> object:
            raise _Locked("database is locked")

        monkeypatch.setattr(build_log, "log_event", _explode)
        assert _build(project) == 0
        assert "could not record this build" not in capsys.readouterr().err
        assert _rows(project) == []

    def test_a_success_payload_that_cannot_be_built_changes_nothing_about_the_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The completion callback runs inside `scan.run`'s `try`, so its guard must be whole.

        A failure building the success payload must not reach the scan's failure path — which would
        record a completed build `ok=false` and exit 1 — and must not be attempted again after the
        lock's release, which is the ordering the callback exists for. So: status 0, no row at all,
        and no second attempt.

        Driven through the payload construction itself rather than a shared dependency, which would
        break the failure payload too and leave the two outcomes indistinguishable.
        """
        project = _project(tmp_path)

        def _explode(_self: object, _result: object) -> object:
            raise RuntimeError("the success payload could not be built")

        monkeypatch.setattr(build_log.BuildLog, "_completed", _explode)
        assert _build(project) == 0
        assert _rows(project) == [], "a completed build must not be recorded as a failed one"

    def test_a_row_write_that_fails_on_the_failure_path_leaves_the_refusal_as_the_outcome(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The **original** exception is re-raised, not the row's, so `scope.execute` still renders
        `refused:` rather than a chained driver error over a build that was refused for a reason its
        caller can act on."""
        project = _project(tmp_path)
        (project / "docs").rename(project / "docs-moved")
        _break_the_row_write(monkeypatch)

        status = scope.execute(
            lambda: _one_build(project), printer=lambda line: print(line, file=sys.stderr)
        )
        captured = capsys.readouterr()
        assert status == 1
        assert "refused: " in captured.err
        assert "could not record this build" in captured.err
        assert _rows(project) == []

    def test_a_row_attempted_under_a_held_lock_lands_once_the_lock_releases(
        self, tmp_path: Path
    ) -> None:
        """**A build waits where the access log refuses to, and the asymmetry is the point.** `call`
        declines because a caller is holding a response; a build has just spent minutes and that row
        is the only record of them, so it polls for the write lock for the primitive's whole budget,
        `ddl.BUSY_TIMEOUT_MS`."""
        project = _project(tmp_path)
        started = time.perf_counter()
        asyncio.run(_build_against_a_briefly_held_lock(project))
        elapsed = time.perf_counter() - started
        (row,) = _rows(project)
        assert row["ok"] is True
        assert elapsed < ddl.BUSY_TIMEOUT_MS / MS_PER_SECOND, (
            f"it gave up rather than waiting: {elapsed:.3f}s"
        )


async def _build_against_a_briefly_held_lock(project: Path) -> None:
    """Hold `memory.db`'s write lock, release it while the build runs, and let the row land."""
    async with scope.open_store(project) as store:
        holder, _inode = await open_connection(
            store.directory / "memory.db", pragmas=ddl.PRAGMAS, existing_only=True
        )
        try:
            await holder.execute("BEGIN IMMEDIATE")
            await holder.execute("INSERT INTO meta (key, value) VALUES ('held', '1')")
            releasing = asyncio.create_task(_release_after(holder, 0.2))
            await indexer_main.build(store, name="docs")
            await releasing
        finally:
            await holder.close()


async def _release_after(holder: aiosqlite.Connection, seconds: float) -> None:
    await asyncio.sleep(seconds)
    await holder.rollback()


async def _one_build(project: Path) -> int:
    async with scope.open_store(project) as store:
        return await indexer_main.build(store, name="docs")


def _break_the_row_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the row write fail for a reason that is not contention, which is not swallowed."""

    async def _explode(*_args: object, **_keywords: object) -> object:
        raise OSError("the disk is full")

    monkeypatch.setattr(build_log, "log_event", _explode)


def _set_schema_version(project: Path, version: int) -> None:
    with closing(sqlite3.connect(project / ".zikaron" / "memory.db")) as connection:
        connection.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),)
        )
        connection.commit()
