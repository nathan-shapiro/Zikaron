"""Does SQLite's busy_timeout cover a deferred transaction's read-to-write upgrade? (WAL mode)

Run: .venv/bin/python spikes/sqlite_deferred_upgrade_busy.py
Read by: research/build-transaction-upgrade-race.md
"""

import os
import sqlite3
import tempfile
import threading
import time

path = os.path.join(tempfile.mkdtemp(), "p.db")
setup = sqlite3.connect(path, isolation_level=None)
setup.execute("PRAGMA journal_mode=WAL")
setup.execute("CREATE TABLE t(x)")
setup.close()


def trial(first_statement: str) -> str:
    holder = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    holder.execute("BEGIN IMMEDIATE")
    threading.Timer(0.3, lambda: holder.execute("ROLLBACK")).start()
    build = sqlite3.connect(path, isolation_level=None, timeout=5.0)
    t0 = time.monotonic()
    try:
        build.execute(first_statement)
        build.execute("SELECT count(*) FROM t").fetchall()
        build.execute("INSERT INTO t VALUES (1)")
        build.execute("COMMIT")
        result = "committed"
    except sqlite3.OperationalError as e:
        result = f"{e} (extended code {e.sqlite_errorcode})"
        build.execute("ROLLBACK")
    elapsed = time.monotonic() - t0
    time.sleep(0.4)
    holder.close()
    build.close()
    return f"{first_statement:16} -> {result} after {elapsed:.3f}s (write lock held 0.300s; busy_timeout 5s)"


print("sqlite", sqlite3.sqlite_version)
print(trial("BEGIN"))
print(trial("BEGIN IMMEDIATE"))
