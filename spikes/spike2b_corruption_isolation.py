"""
Isolate spike 2's corruption finding in a minimal repro, separate from the
rest of the script's state, to confirm it is not an artifact of prior
statements in that run.
"""

import sqlite3


def main() -> None:
    con = sqlite3.connect(":memory:")
    con.execute("""
        CREATE TABLE memory (
            rowid INTEGER PRIMARY KEY,
            uuid TEXT NOT NULL UNIQUE,
            gist TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            gist, content,
            content='memory',
            content_rowid='rowid'
        )
    """)
    con.execute(
        "INSERT INTO memory (rowid, uuid, gist, content) VALUES (1, 'u1', 'g1', 'c1')"
    )
    con.execute(
        "INSERT INTO memory_fts (rowid, gist, content) VALUES (1, 'g1', 'c1')"
    )
    con.commit()

    print("Row present. Now delete ONLY the content table row (no memory_fts maintenance):")
    con.execute("DELETE FROM memory WHERE rowid = 1")
    con.commit()
    print("DELETE FROM memory succeeded and committed with no error.")

    print("Querying memory_fts now (this is what triggers the failure downstream)...")
    try:
        rows = con.execute(
            "SELECT rowid, gist FROM memory_fts WHERE memory_fts MATCH '\"c1\"'"
        ).fetchall()
        print(f"Query succeeded: {rows}")
    except sqlite3.DatabaseError as e:
        print(f"Query RAISED: {type(e).__name__}: {e}")

    # Also try the bare, non-MATCH select that spike 2 used
    try:
        rows2 = con.execute("SELECT rowid FROM memory_fts WHERE rowid = 1").fetchall()
        print(f"Bare select succeeded: {rows2}")
    except sqlite3.DatabaseError as e:
        print(f"Bare select RAISED: {type(e).__name__}: {e}")

    con.close()


if __name__ == "__main__":
    main()
