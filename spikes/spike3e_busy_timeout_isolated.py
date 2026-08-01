"""
Isolate spike 3d's surprising finding — busy_timeout=5000 apparently NOT
absorbing a 0.5s BEGIN IMMEDIATE hold — from the asyncio server entirely,
using two real OS threads and two real sqlite3 connections directly
against a file-backed db. This removes the event loop as a variable.
"""

import os
import sqlite3
import threading
import time

DB_PATH = "/tmp/zikaron_spike3d_isolated.db"


def setup() -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except FileNotFoundError:
            pass
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, n INTEGER)")
    con.execute("INSERT INTO counter (id, n) VALUES (1, 0)")
    con.close()


results = {}


def writer(label: str, hold_s: float, start_barrier: threading.Barrier) -> None:
    con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=5.0)
    con.execute("PRAGMA busy_timeout = 5000")
    start_barrier.wait()
    t0 = time.monotonic()
    try:
        con.execute("BEGIN IMMEDIATE")
        t_acquired = time.monotonic() - t0
        time.sleep(hold_s)
        con.execute("UPDATE counter SET n = n + 1 WHERE id = 1")
        con.execute("COMMIT")
        elapsed = time.monotonic() - t0
        (n,) = con.execute("SELECT n FROM counter WHERE id = 1").fetchone()
        results[label] = {"outcome": "ok", "t_acquired": round(t_acquired, 4), "elapsed": round(elapsed, 4), "n": n}
    except sqlite3.OperationalError as e:
        elapsed = time.monotonic() - t0
        results[label] = {"outcome": "error", "error": str(e), "elapsed": round(elapsed, 4)}
    finally:
        con.close()


def main() -> None:
    setup()
    barrier = threading.Barrier(2)
    t1 = threading.Thread(target=writer, args=("A", 0.5, barrier))
    t2 = threading.Thread(target=writer, args=("B", 0.5, barrier))
    t1.start()
    time.sleep(0.02)  # bias A to acquire BEGIN IMMEDIATE first, deterministically
    t2.start()
    t1.join()
    t2.join()

    print("Two real threads, two real sqlite3 connections, timeout=5.0 (Python driver-level) "
          "AND PRAGMA busy_timeout=5000 (SQLite-level), each holding BEGIN IMMEDIATE for 0.5s:")
    for label, r in results.items():
        print(f"  {label}: {r}")


if __name__ == "__main__":
    main()
