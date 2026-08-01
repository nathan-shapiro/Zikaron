"""
File-backed re-run of spike 2's two loose ends, this time with
isolation_level=None (true autocommit) so explicit BEGIN/COMMIT strings are
unambiguous and don't fight Python's sqlite3 module's own implicit
transaction tracking (default isolation_level='' auto-BEGINs before DML,
which was silently leaving a transaction open across statements in the
previous attempt and made wal_checkpoint/VACUUM fail for a driver reason
unrelated to the design).
"""

import os
import sqlite3

DB_PATH = "/tmp/zikaron_spike2_filebacked.db"


def fresh_db() -> sqlite3.Connection:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except FileNotFoundError:
            pass
    con = sqlite3.connect(DB_PATH, isolation_level=None)  # true autocommit
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def main() -> None:
    print("=== File-backed re-check (autocommit): naive-delete corruption ===")
    con = fresh_db()
    con.execute(
        "CREATE TABLE memory (rowid INTEGER PRIMARY KEY, uuid TEXT, gist TEXT, content TEXT)"
    )
    con.execute(
        "CREATE VIRTUAL TABLE memory_fts USING fts5(gist, content, content='memory', content_rowid='rowid')"
    )
    con.execute("INSERT INTO memory (rowid, uuid, gist, content) VALUES (1, 'u', 'g', 'secretword')")
    con.execute("INSERT INTO memory_fts (rowid, gist, content) VALUES (1, 'g', 'secretword')")
    print(f"in_transaction after setup inserts (autocommit): {con.in_transaction}")

    con.execute("DELETE FROM memory WHERE rowid = 1")  # no FTS5 maintenance — the naive path
    print(f"in_transaction after naive DELETE (autocommit): {con.in_transaction}")

    try:
        rows = con.execute(
            'SELECT rowid FROM memory_fts WHERE memory_fts MATCH \'"secretword"\''
        ).fetchall()
        print(f"MATCH query after naive delete: succeeded, rows={rows}")
    except sqlite3.DatabaseError as e:
        print(f"MATCH query after naive delete RAISED: {type(e).__name__}: {e}")

    try:
        rows2 = con.execute("SELECT rowid, gist FROM memory_fts").fetchall()
        print(f"Bare unfiltered select over memory_fts: succeeded, rows={rows2}")
    except sqlite3.DatabaseError as e:
        print(f"Bare unfiltered select RAISED: {type(e).__name__}: {e}")

    # Run it again, freshly, to see whether the corruption/inconsistency is
    # itself nondeterministic or reliably one or the other under autocommit.
    try:
        rows3 = con.execute(
            'SELECT rowid, gist FROM memory_fts WHERE memory_fts MATCH \'"secretword"\''
        ).fetchall()
        print(f"Repeat MATCH query (2nd call): succeeded, rows={rows3}")
    except sqlite3.DatabaseError as e:
        print(f"Repeat MATCH query (2nd call) RAISED: {type(e).__name__}: {e}")

    con.close()

    print("\n=== File-backed re-check (autocommit): documented erasure + hygiene sequence ===")
    con2 = fresh_db()
    con2.execute(
        "CREATE TABLE memory (rowid INTEGER PRIMARY KEY, uuid TEXT, gist TEXT, content TEXT)"
    )
    con2.execute(
        "CREATE VIRTUAL TABLE memory_fts USING fts5(gist, content, content='memory', content_rowid='rowid')"
    )
    con2.execute("INSERT INTO memory (rowid, uuid, gist, content) VALUES (1, 'u', 'g', 'leaked-secret-abc')")
    con2.execute("INSERT INTO memory_fts (rowid, gist, content) VALUES (1, 'g', 'leaked-secret-abc')")

    con2.execute("BEGIN")
    cur_gist, cur_content = con2.execute("SELECT gist, content FROM memory WHERE rowid = 1").fetchone()
    con2.execute(
        "INSERT INTO memory_fts (memory_fts, rowid, gist, content) VALUES ('delete', ?, ?, ?)",
        (1, cur_gist, cur_content),
    )
    con2.execute("DELETE FROM memory WHERE rowid = 1")
    con2.execute("COMMIT")
    print(f"Documented erasure transaction committed. in_transaction now: {con2.in_transaction}")

    try:
        con2.execute("INSERT INTO memory_fts(memory_fts) VALUES('integrity-check')")
        print("integrity-check: OK")
    except sqlite3.Error as e:
        print(f"integrity-check RAISED: {type(e).__name__}: {e}")
    print(f"in_transaction after integrity-check: {con2.in_transaction}")

    try:
        result = con2.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        print(f"wal_checkpoint(TRUNCATE): OK, result={result}")
    except sqlite3.Error as e:
        print(f"wal_checkpoint(TRUNCATE) RAISED: {type(e).__name__}: {e}")

    try:
        con2.execute("VACUUM")
        print("VACUUM: OK")
    except sqlite3.Error as e:
        print(f"VACUUM RAISED: {type(e).__name__}: {e}")

    con2.close()

    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(DB_PATH + suffix)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
