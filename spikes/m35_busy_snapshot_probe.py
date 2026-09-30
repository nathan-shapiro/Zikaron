"""A deferred transaction that reads, then writes, is refused at once if another connection commits
in between — `busy_timeout` never runs. `BEGIN IMMEDIATE` takes the write lock up front and waits.

This is `test_rename_and_remove_reach_a_real_service`'s CI failure (run 36657562917): `rename` is
`BEGIN` → `ensure_table`/`require` reads → `UPDATE`, and the indexer writes its `knowledge_build`
row after releasing the corpus lock, which is what `refresh --wait` watches.

    python3 spikes/m35_busy_snapshot_probe.py <scratch-dir>
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
    path = Path(sys.argv[1]) / "snapshot.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)
    setup = _connect(path)
    setup.execute("CREATE TABLE kb (id INTEGER, name TEXT)")
    setup.execute("CREATE TABLE event (x INTEGER)")
    setup.execute("INSERT INTO kb VALUES (1, 'docs')")
    for begin in ("BEGIN", "BEGIN IMMEDIATE"):
        service, indexer = _connect(path), _connect(path)
        started = time.perf_counter()
        service.execute(begin)
        service.execute("SELECT name FROM kb").fetchall()
        writer = threading.Thread(target=lambda: indexer.execute("INSERT INTO event VALUES (1)"))
        writer.start()
        writer.join(0.3)
        try:
            service.execute("UPDATE kb SET name = 'renamed'")
            service.execute("COMMIT")
            print(f"{begin}: committed")
        except sqlite3.OperationalError as error:
            elapsed = time.perf_counter() - started
            print(f"{begin}: {error.sqlite_errorname} after {elapsed:.3f} s")
            service.execute("ROLLBACK")
        writer.join()


if __name__ == "__main__":
    main()
