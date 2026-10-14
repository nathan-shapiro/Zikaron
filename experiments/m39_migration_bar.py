"""M39's preregistered bar on the corpus migration's write-lock hold (`knowledge-index.md` §7.7.1).

    .venv/bin/python experiments/m39_migration_bar.py [rows] [copies] [--real <corpus.db>]

**The bar**: p95 of the migration's write-lock hold at most 1 s, over at least 20 migrations each
of a fresh copy, on a schema-1 corpus of at least 7,000 `files` rows with chunks to match. A build
of the previous version may be waiting on that lock under a 5 s `busy_timeout`, so a longer hold can
end it; a miss moves the backfill out of the step (§7.7.1 says how).

**What is timed is `migration.migrate`, which is one `BEGIN IMMEDIATE` transaction**: from the
`BEGIN` that takes the lock to the `COMMIT` that releases it, with no other connection contending,
so nothing but the step's own work is inside the figure.

**The corpus is synthetic and built to the row count**, since the per-row read, parse and update is
the term that scales: `files` rows with three chunks each of about 1,500 characters, the length the
chunker's budget produces, and a third of the files opening with a linked front-matter block — the
case that reads past the first chunk. Built once, at schema 1, by the real schema with `files`
rebuilt to schema 1's columns, then copied fresh for every run.

`--real` migrates a copy of a live corpus database as well, taken with `Connection.backup` so the
copy is consistent while its owner keeps serving; it is reported beside the measurement, not as it.
"""

import asyncio
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Final

from zikaron.core.config.resolution import resolve
from zikaron.core.knowledge import ddl, migration
from zikaron.core.knowledge.database import KnowledgeDatabase, NewKnowledgeBase, seed_identity
from zikaron.core.knowledge.links import LINK_PREFIX_CHARS
from zikaron.core.store.connection import open_connection

_BAR_SECONDS: Final = 1.0
_CHUNKS_PER_FILE: Final = 3
_CHUNK_CHARS: Final = 1500
_BLOB: Final = "0123456789abcdef0123456789abcdef01234567"

#: `files` as schema 1 created it.
_V1_FILES: Final = """
CREATE TABLE files (
  path            TEXT    PRIMARY KEY,
  size            INTEGER NOT NULL,
  content_hash    TEXT    NOT NULL,
  git_blob_hash   TEXT,
  chunk_count     INTEGER NOT NULL,
  indexed_at      TEXT    NOT NULL,
  CHECK (length(path) > 0),
  CHECK (size >= 0),
  CHECK (chunk_count >= 0)
)
"""


async def _created(directory: Path) -> Path:
    config = resolve(directory / "system.toml", directory / "project.toml")
    spec = NewKnowledgeBase(name="bar", root=directory, description="the migration bar")
    identity = seed_identity(uuid.uuid4(), spec, config)
    async with await KnowledgeDatabase.create(directory / ".zikaron", identity) as created:
        return created.path


def _fill_at_schema_one(db_path: Path, rows: int) -> None:
    filler = ("lorem ipsum dolor sit amet " * 80)[: _CHUNK_CHARS - 1] + "\n"
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("DROP TABLE files")
        db.execute(_V1_FILES)
        db.execute(
            "DELETE FROM meta WHERE key IN ('results_linked', 'results_source_changed', "
            "'results_source_missing', 'results_source_unverifiable')"
        )
        db.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
        chunk_rows = []
        file_rows = []
        for index in range(rows):
            path = f"docs/{index:06d}.md"
            texts = [filler] * _CHUNKS_PER_FILE
            if index % 3 == 0:
                front = (
                    f"---\nzikaron-source: src/{index:06d}.py\nzikaron-source-blob: {_BLOB}\n---\n"
                )
                texts[0] = front + filler[len(front) :]
            file_rows.append(
                (
                    path,
                    _CHUNK_CHARS * _CHUNKS_PER_FILE,
                    f"{index:040x}",
                    None,
                    _CHUNKS_PER_FILE,
                    "2026-10-13T00:00:00+00:00",
                )
            )
            chunk_rows.extend(
                (path, part, part * 10 + 1, part * 10 + 10, text) for part, text in enumerate(texts)
            )
        db.executemany("INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)", file_rows)
        db.executemany(
            "INSERT INTO chunks (path, part_index, start_line, end_line, text) "
            "VALUES (?, ?, ?, ?, ?)",
            chunk_rows,
        )
        db.commit()
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


async def _timed_migration(db_path: Path) -> float:
    db, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)
    try:
        started = time.perf_counter()
        moved = await migration.migrate(db)
        elapsed = time.perf_counter() - started
    finally:
        await db.close()
    if not moved:
        raise RuntimeError(f"{db_path} was not at schema 1")
    return elapsed


def _backup(source: Path, target: Path) -> None:
    with (
        closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as live,
        closing(sqlite3.connect(target)) as copy,
    ):
        live.backup(copy)


async def _measure(rows: int, copies: int, real: Path | None) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch)
        template = await _created(directory)
        _fill_at_schema_one(template, rows)
        holds = []
        for run in range(copies):
            copy = directory / f"copy-{run}.db"
            shutil.copyfile(template, copy)
            holds.append(await _timed_migration(copy))
            copy.unlink()
        holds.sort()
        p95 = holds[max(0, round(0.95 * len(holds)) - 1)]
        print(f"load average   {os.getloadavg()}")
        print(f"rows           {rows} ({_CHUNKS_PER_FILE} chunks each, a third linked)")
        print(f"migrations     {copies}, each of a fresh copy")
        print(f"hold p50       {statistics.median(holds):.3f} s")
        print(
            f"hold p95       {p95:.3f} s   (bar {_BAR_SECONDS:.1f} s: "
            f"{'met' if p95 <= _BAR_SECONDS else 'MISSED'})"
        )
        print(f"hold max       {holds[-1]:.3f} s")
        print(f"per row p95    {p95 / rows * 1e6:.1f} µs")
        print(f"prefix bound   {LINK_PREFIX_CHARS} characters")
        if real is not None:
            copy = directory / "real.db"
            _backup(real, copy)
            with closing(sqlite3.connect(copy)) as db:
                ((count,),) = db.execute("SELECT count(*) FROM files").fetchall()
            print(f"real corpus    {count} rows: hold {await _timed_migration(copy):.3f} s")


def main() -> int:
    arguments = sys.argv[1:]
    real = None
    if "--real" in arguments:
        at = arguments.index("--real")
        real = Path(arguments[at + 1])
        del arguments[at : at + 2]
    rows = int(arguments[0]) if arguments else 7000
    copies = int(arguments[1]) if len(arguments) > 1 else 20
    asyncio.run(_measure(rows, copies, real))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
