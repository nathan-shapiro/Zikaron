"""Re-derive M31's two figures: what it costs to widen `event.client_kind`'s CHECK.

    .venv/bin/python spikes/m31_check_widening.py [store.db]

Defaults to `~/Trading/LeibaTrader/.zikaron/memory.db`, the largest real store. Snapshots it with
`VACUUM INTO` — never `cp`, which copies the main file without its WAL — and times both routes
against the snapshot, five runs each, leaving the original untouched.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

WIDENED = "('hook', 'mcp', 'consolidator', 'cli')"
NARROW = "('hook', 'mcp', 'consolidator')"

EVENT_INDEXES = (
    "CREATE INDEX idx_event_kind_at ON event(kind, at)",
    "CREATE INDEX idx_event_session ON event(session_id)",
    "CREATE INDEX idx_event_session_kind ON event(session_id, client_kind)",
    "CREATE INDEX idx_event_op ON event(op_id)",
    "CREATE INDEX idx_event_uuid_at ON event(memory_uuid, at)",
)


def snapshot(source: Path, into: Path) -> None:
    db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        db.execute("VACUUM INTO ?", (str(into),))
    finally:
        db.close()


def working_copy(base: Path, name: str) -> Path:
    path = base.parent / name
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    shutil.copy(base, path)
    return path


def rebuild(db: sqlite3.Connection) -> None:
    """SQLite's documented 12-step: new table, copy, drop, rename, recreate the indexes."""
    created = str(db.execute("SELECT sql FROM sqlite_schema WHERE name='event'").fetchone()[0])
    db.execute("BEGIN IMMEDIATE")
    db.execute(created.replace("TABLE event", "TABLE event_new").replace(NARROW, WIDENED))
    db.execute("INSERT INTO event_new SELECT * FROM event")
    db.execute("DROP TABLE event")
    db.execute("ALTER TABLE event_new RENAME TO event")
    for statement in EVENT_INDEXES:
        db.execute(statement)
    db.commit()


def rewrite_schema(db: sqlite3.Connection) -> None:
    """The `PRAGMA writable_schema` route: edit the stored CREATE TABLE text, touch nothing else."""
    created = str(db.execute("SELECT sql FROM sqlite_schema WHERE name='event'").fetchone()[0])
    version = int(db.execute("PRAGMA schema_version").fetchone()[0])
    db.execute("PRAGMA writable_schema=ON")
    db.execute(
        "UPDATE sqlite_schema SET sql=? WHERE type='table' AND name='event'",
        (created.replace(NARROW, WIDENED),),
    )
    db.execute(f"PRAGMA schema_version={version + 1}")
    db.execute("PRAGMA writable_schema=OFF")
    db.commit()


def measure(base: Path, label: str, apply: object, runs: int = 5) -> None:
    elapsed = []
    for index in range(runs):
        path = working_copy(base, f"{label}-{index}.db")
        db = sqlite3.connect(path)
        db.execute("PRAGMA journal_mode=WAL")
        started = time.perf_counter()
        apply(db)  # type: ignore[operator]
        elapsed.append((time.perf_counter() - started) * 1000)
        db.close()
        db = sqlite3.connect(path)
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        rows = db.execute("SELECT count(*) FROM event").fetchone()[0]
        db.execute(
            "INSERT INTO event(at, session_id, client_kind, op_id, kind) "
            "VALUES('t', 's', 'cli', 'o', 'search')"
        )
        refused = False
        try:
            db.execute(
                "INSERT INTO event(at, session_id, client_kind, op_id, kind) "
                "VALUES('t', 's', 'nope', 'o', 'search')"
            )
        except sqlite3.IntegrityError:
            refused = True
        db.close()
        os.unlink(path)
    print(
        f"{label:<16} {min(elapsed):7.1f}–{max(elapsed):.1f} ms   rows={rows}  "
        f"integrity={integrity}  cli_accepted=True  bogus_refused={refused}"
    )


def main() -> int:
    source = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.expanduser("~/Trading/LeibaTrader/.zikaron/memory.db")
    )
    if not source.exists():
        print(f"no store at {source}", file=sys.stderr)
        return 1
    print(f"sqlite {sqlite3.sqlite_version}, source {source}")
    with tempfile.TemporaryDirectory() as scratch:
        base = Path(scratch) / "snapshot.db"
        snapshot(source, base)
        events = sqlite3.connect(base).execute("SELECT count(*) FROM event").fetchone()[0]
        print(f"snapshot {base.stat().st_size} bytes, {events} events\n")
        measure(base, "12-step", rebuild)
        measure(base, "writable_schema", rewrite_schema)
    return 0


if __name__ == "__main__":
    sys.exit(main())
