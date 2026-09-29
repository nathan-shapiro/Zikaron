"""Re-derive M33's two figures against the largest real store, through the shipped migration.

    .venv/bin/python spikes/m33_schema_three_and_call_volume.py [store.db]

Defaults to `~/Trading/LeibaTrader/.zikaron/memory.db`. Snapshots it with `VACUUM INTO` — never
`cp`, which copies the main file without its WAL — and leaves the original untouched.

Two questions, one snapshot:

1. **What the 2→3 step costs, and whether the result is sound.** Run through
   `core.store.migration.migrate` rather than through a re-implementation of it, so the figure is
   the one production pays. `spikes/m31_check_widening.py` compared the two *routes* and is left
   alone; this measures the route that was chosen.
2. **What `call` does to §"Retention"'s growth figure.** That figure predates the kind, so it is
   re-derived rather than scaled: the row count comes from the store's own distinct `op_id`s, and
   the bytes per row are measured by inserting them and watching the file, indexes included.

**The op_id count is a floor on the calls, and deliberately so.** A `call` row is written per
dispatched RPC, and the eight knowledge verbs emitted nothing before this milestone — so their
calls left no `op_id` behind and cannot be counted here at all. A project that uses the knowledge
index writes more `call` rows than this predicts.

Throwaway rather than a test: it needs a real store under the operator's home, which no test may
open, and the answers are recorded in `research/` rather than asserted.
"""

import asyncio
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiosqlite  # noqa: E402

from zikaron.core.store import migration  # noqa: E402

#: How many synthetic `call` rows to insert when measuring bytes per row. Large enough that the
#: file's own page granularity is a small share of the answer.
_SAMPLE_ROWS = 20_000

_EVENT_INDEXES = (
    "CREATE INDEX idx_event_kind_at ON event(kind, at)",
    "CREATE INDEX idx_event_session ON event(session_id)",
    "CREATE INDEX idx_event_session_kind ON event(session_id, client_kind)",
    "CREATE INDEX idx_event_op ON event(op_id)",
    "CREATE INDEX idx_event_uuid_at ON event(memory_uuid, at)",
)

#: A `call` detail of the shape the seam writes, at a plausible length: a long method name, a
#: refusal, and a duration with the precision `time.perf_counter` produces.
_SAMPLE_DETAIL = (
    '{"method": "memory_apply_promote", "ok": false, "error_code": "version_conflict", '
    '"duration_ms": 12.384512999999998}'
)


def snapshot(source: Path, into: Path) -> None:
    db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        db.execute("VACUUM INTO ?", (str(into),))
    finally:
        db.close()


async def migrate_snapshot(path: Path) -> tuple[float, int, str]:
    """Run the shipped 2→3 step. Returns (milliseconds, version reached, integrity_check)."""
    db = await aiosqlite.connect(path)
    try:
        await db.execute("PRAGMA journal_mode = WAL")
        rows = list(await db.execute_fetchall("SELECT value FROM meta WHERE key='schema_version'"))
        started = time.perf_counter()
        reached = await migration.migrate(db, from_version=int(rows[0][0]))
        elapsed = (time.perf_counter() - started) * 1000
        checked = list(await db.execute_fetchall("PRAGMA integrity_check"))
        return elapsed, reached, str(checked[0][0])
    finally:
        await db.close()


def bytes_per_call_row(path: Path) -> tuple[float, int]:
    """Insert `_SAMPLE_ROWS` `call` rows and return (bytes per row, rows the store already held).

    Measured as the file's growth after a `VACUUM`, so the answer is the live cost of the row plus
    its five indexes rather than whatever free pages the store happened to be carrying.
    """
    db = sqlite3.connect(path)
    try:
        held = int(db.execute("SELECT count(*) FROM event").fetchone()[0])
        db.execute("VACUUM")
        before = path.stat().st_size
        db.execute("BEGIN IMMEDIATE")
        db.executemany(
            "INSERT INTO event (at, session_id, client_kind, op_id, kind, memory_uuid, detail) "
            "VALUES (?, ?, ?, ?, 'call', NULL, ?)",
            [
                (
                    f"2026-09-28T12:00:{index % 60:02d}.000000+00:00",
                    f"zk-{index:032x}",
                    "mcp",
                    f"{index:032x}",
                    _SAMPLE_DETAIL,
                )
                for index in range(_SAMPLE_ROWS)
            ],
        )
        db.commit()
        db.execute("VACUUM")
        after = path.stat().st_size
    finally:
        db.close()
    return (after - before) / _SAMPLE_ROWS, held


def per_day(path: Path) -> tuple[int, int, float]:
    """(distinct op_ids, events, days spanned) from the store's own log."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ops = int(db.execute("SELECT count(DISTINCT op_id) FROM event").fetchone()[0])
        events = int(db.execute("SELECT count(*) FROM event").fetchone()[0])
        first, last = db.execute("SELECT min(at), max(at) FROM event").fetchone()
        spanned = (
            sqlite3.connect(":memory:")
            .execute("SELECT julianday(?) - julianday(?)", (last, first))
            .fetchone()[0]
        )
    finally:
        db.close()
    return ops, events, float(spanned)


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
        ops, events, days = per_day(base)
        print(f"snapshot {base.stat().st_size} bytes, {events} events, {ops} op_ids, {days:.1f} days")

        elapsed, reached, integrity = asyncio.run(migrate_snapshot(base))
        print(f"\n2->3 migration    {elapsed:7.1f} ms   reached={reached}  integrity={integrity}")
        assert _EVENT_INDEXES  # the rebuild recreates these; listed so a loss is visible below
        surviving = sqlite3.connect(base).execute(
            "SELECT count(*) FROM sqlite_master WHERE type='index' AND tbl_name='event' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        print(f"                  indexes surviving: {surviving} of {len(_EVENT_INDEXES)}")

        per_row, held = bytes_per_call_row(base)
        calls_per_day = ops / days
        print(f"\ncall row          {per_row:7.1f} bytes live, indexes included")
        print(f"op_ids per day    {calls_per_day:7.1f}  (a floor: knowledge verbs left none)")
        print(f"events per day    {events / days:7.1f}  over {held} rows held")
        print(f"\ncall adds         {per_row * calls_per_day * 365 / 1e6:7.1f} MB/year at that rate")
        print(f"                  {100 * ops / events:7.1f}% more rows than the log already holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
