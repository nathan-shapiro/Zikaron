"""Exactly one `knowledge_build` row per build, landed before the corpus lock is released.

`schema.md` §"What is instrumented, what is not, and why" is normative. `refresh --wait` watches the
lock, so a row written after the release was not there when `--wait` returned; and a second write
site would record every build twice, doubling what `experiments/m33_call_log_queries.py` sums as
its cost. So `scan.run` hands the outcome to a completion callback while it still holds the lock,
and the build's own two sites write only for a refusal before the lock was taken.

Each test reads the rows at the moment of the release — from a separate connection, as `--wait`'s
reader would — as well as at the end.
"""

import asyncio
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import write_meta
from tests.test_knowledge_build_log import (  # noqa: F401 — two autouse fixtures ride along.
    _build,
    _deterministic_encoder,
    _no_inherited_attribution,
    _project,
    _registry_id,
    _rows,
)
from zikaron.core.knowledge import disposal, lock, reporting, scan
from zikaron.core.knowledge import meta as knowledge_meta
from zikaron.core.knowledge import paths as knowledge_paths
from zikaron.core.knowledge.errors import IndexerBusyError


def _rows_at_release(project: Path, monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count the `knowledge_build` rows each time the scan is about to release the corpus lock."""
    counted: list[int] = []
    real = scan._release

    async def counting(db: aiosqlite.Connection) -> None:
        with closing(sqlite3.connect(project / ".zikaron" / "memory.db")) as reader:
            (count,) = reader.execute(
                "SELECT count(*) FROM event WHERE kind = 'knowledge_build'"
            ).fetchone()
        counted.append(int(count))
        await real(db)

    monkeypatch.setattr(scan, "_release", counting)
    return counted


def _lock_rows(project: Path) -> list[str]:
    db_path = knowledge_paths.knowledge_db_path(
        project / ".zikaron", knowledge_meta.parse_id(_registry_id(project))
    )
    with closing(sqlite3.connect(db_path)) as reader:
        rows = reader.execute(
            "SELECT key FROM meta WHERE key IN (?, ?, ?)", tuple(lock.LOCK_KEYS)
        ).fetchall()
    return [str(key) for (key,) in rows]


def test_a_completed_build_has_its_one_row_before_the_lock_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    counted = _rows_at_release(project, monkeypatch)
    assert _build(project) == 0
    assert counted == [1]
    (row,) = _rows(project)
    assert row["ok"] is True


def test_a_build_that_fails_holding_the_lock_has_its_one_row_before_the_lock_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    counted = _rows_at_release(project, monkeypatch)

    async def failing(*_args: object, **_keywords: object) -> int:
        raise RuntimeError("the index phase failed")

    monkeypatch.setattr(disposal, "run", failing)
    with pytest.raises(RuntimeError):
        _build(project)
    assert counted == [1]
    (row,) = _rows(project)
    assert row["ok"] is False
    assert row["error_code"] == "build_failed"


def test_a_refusal_before_the_lock_writes_its_one_row_after_the_refusal(tmp_path: Path) -> None:
    project = _project(tmp_path)
    db_path = knowledge_paths.knowledge_db_path(
        project / ".zikaron", knowledge_meta.parse_id(_registry_id(project))
    )
    asyncio.run(
        write_meta(
            db_path,
            **{
                knowledge_meta.LOCK_PID_KEY: str(os.getpid()),
                knowledge_meta.LOCK_HOST_KEY: lock.this_host(),
                knowledge_meta.LOCK_STARTED_AT_KEY: "earlier",
            },
        )
    )
    with pytest.raises(IndexerBusyError):
        _build(project)
    (row,) = _rows(project)
    assert row["error_code"] == "knowledge_base_busy"


def test_a_build_cancelled_mid_scan_leaves_no_row_and_no_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancellation must not wait out the write-lock budget to record its own death."""
    project = _project(tmp_path)

    async def cancelled(*_args: object, **_keywords: object) -> int:
        raise asyncio.CancelledError

    monkeypatch.setattr(disposal, "run", cancelled)
    with pytest.raises(asyncio.CancelledError):
        _build(project)
    assert _rows(project) == []
    assert _lock_rows(project) == []


def test_a_failure_after_the_scan_returned_exits_one_over_the_rows_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The row describes the scan, which committed; the exit status reports what failed after the
    release. Never a second row after the release."""
    project = _project(tmp_path)
    finished = False
    real_run = scan.run
    real_observe = reporting.observe

    async def run(*args: object, **keywords: object) -> object:
        nonlocal finished
        result = await real_run(*args, **keywords)  # type: ignore[arg-type]
        finished = True
        return result

    async def observe(*args: object, **keywords: object) -> object:
        if finished:
            raise RuntimeError("the report's own read failed")
        return await real_observe(*args, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr(scan, "run", run)
    monkeypatch.setattr(reporting, "observe", observe)
    with pytest.raises(RuntimeError):
        _build(project)
    (row,) = _rows(project)
    assert row["ok"] is True
