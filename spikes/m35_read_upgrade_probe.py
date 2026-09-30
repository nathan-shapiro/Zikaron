"""A read that has already read never waits for the write lock: its upgrade is refused at once.

SQLite runs the busy handler for a write-lock request only from a connection with no transaction
open. So `search`/`surface` — both arms and `chunk_count` read, then the event insert — meeting a
*held* write lock get primary `SQLITE_BUSY` immediately, whatever `busy_timeout` says. `BEGIN
IMMEDIATE` asks from no transaction and waits. Measured 2026-09-29: deferred refused in 0.0 s,
immediate committed at 2.03 s when the holder committed at 2 s.

    python3 spikes/m35_read_upgrade_probe.py <scratch-dir>
"""

import sqlite3
import sys
import threading
import time
from pathlib import Path


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


def main() -> None:
    path = Path(sys.argv[1]) / "upgrade.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    setup = _connect(path)
    setup.execute("CREATE TABLE t (x INTEGER)")
    setup.execute("INSERT INTO t VALUES (1)")
    for begin in ("BEGIN", "BEGIN IMMEDIATE"):
        holder, reader = _connect(path), _connect(path)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO t VALUES (2)")
        threading.Timer(2.0, lambda h=holder: h.execute("COMMIT")).start()
        started = time.perf_counter()
        try:
            reader.execute(begin)
            reader.execute("SELECT count(*) FROM t").fetchall()
            reader.execute("INSERT INTO t VALUES (3)")
            reader.execute("COMMIT")
            print(f"{begin}: committed after {time.perf_counter() - started:.2f} s")
        except sqlite3.OperationalError as error:
            elapsed = time.perf_counter() - started
            print(f"{begin}: {error.sqlite_errorname} after {elapsed:.2f} s")
            reader.execute("ROLLBACK")
        time.sleep(2.2)


if __name__ == "__main__":
    main()
