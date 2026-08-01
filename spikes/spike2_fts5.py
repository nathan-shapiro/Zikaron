"""
M0 spike 2 — FTS5 external-content behaves as design/schema.md assumes.

Exercises build-plan.md's checks:
  1. content='memory' external-content FTS5 table.
  2. The amend sequence: delete-then-insert inside ONE transaction.
  3. The documented erasure sequence — the 'delete' command using current
     values (write-policy.md's secret-erasure transaction, step-for-step).
  4. Confirm a stale term is genuinely unmatchable afterwards, in both cases.

Throwaway per build-plan.md's M0 fence. Print raw findings; no assertions,
no test framework, no production code.
"""

import sqlite3


def main() -> None:
    print("=== Spike 2: FTS5 external-content ===")
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")

    # --- Schema: memory + external-content memory_fts, per schema.md ---
    con.execute("""
        CREATE TABLE memory (
            rowid INTEGER PRIMARY KEY,
            uuid TEXT NOT NULL UNIQUE,
            gist TEXT NOT NULL,
            content TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            version INTEGER NOT NULL DEFAULT 1
        )
    """)
    # external content: content='memory' ties memory_fts's rowid to memory.rowid
    con.execute("""
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            gist, content,
            content='memory',
            content_rowid='rowid'
        )
    """)
    print("memory + memory_fts (content='memory') created")

    # Insert one memory row + its FTS index row (same rowid, both sides)
    con.execute(
        "INSERT INTO memory (rowid, uuid, gist, content) VALUES (1, ?, ?, ?)",
        ("uuid-1", "protobuf gist marker", "the protobuf step fails silently on staging"),
    )
    con.execute(
        "INSERT INTO memory_fts (rowid, gist, content) VALUES (1, ?, ?)",
        ("protobuf gist marker", "the protobuf step fails silently on staging"),
    )
    con.commit()

    def search(term: str) -> list[tuple]:
        # Quote the term: FTS5's unquoted query syntax treats bare '-' as the
        # NOT operator and colons/other punctuation specially, so an
        # unquoted "prod-eu" parses as "prod NOT eu" rather than a literal.
        # retrieval.md's real query construction quotes terms for exactly
        # this reason; matching that here rather than the naive form.
        quoted = '"' + term.replace('"', '""') + '"'
        return con.execute(
            "SELECT rowid, gist FROM memory_fts WHERE memory_fts MATCH ? ORDER BY rank",
            (quoted,),
        ).fetchall()

    print(f"Search 'protobuf' before amend: {search('protobuf')}")
    print(f"Search 'staging' before amend: {search('staging')}")

    # --- The amend sequence: delete-then-insert in ONE transaction ------
    # indexing.md: "explicit memory_fts maintenance" inside the mutation's
    # own transaction. A content='memory' table needs the delete/insert
    # done explicitly — SQLite does not do it automatically on an UPDATE
    # of the content table.
    print("\n--- Amend: rewrite content, replacing 'staging' with 'prod-eu' ---")
    con.execute("BEGIN")
    new_gist = "protobuf gist marker"
    new_content = "the protobuf step fails silently on prod-eu"
    # 1. delete the old FTS row
    con.execute("DELETE FROM memory_fts WHERE rowid = 1")
    # 2. mutate the content table
    con.execute(
        "UPDATE memory SET gist = ?, content = ?, version = version + 1 WHERE rowid = 1",
        (new_gist, new_content),
    )
    # 3. insert the new FTS row, same rowid
    con.execute(
        "INSERT INTO memory_fts (rowid, gist, content) VALUES (1, ?, ?)",
        (new_gist, new_content),
    )
    con.execute("COMMIT")
    print("Amend transaction committed")

    print(f"Search 'protobuf' after amend: {search('protobuf')}  <- should still match, term retained")
    print(f"Search 'staging' after amend: {search('staging')}  <- should be EMPTY, stale term")
    print(f"Search 'prod-eu' after amend: {search('prod-eu')}  <- should match, new term")

    stale_after_amend_gone = search("staging") == []
    print(f"Stale term genuinely unmatchable after amend: {stale_after_amend_gone}")

    # --- The documented erasure sequence ---------------------------------
    # write-policy.md's exact transaction, adapted to this minimal schema
    # (memory_chunk/memory_vec/consolidation_* omitted here since spike 1
    # already covers the vector side and this spike is scoped to FTS5):
    #
    #   BEGIN;
    #   -- read current values first
    #   INSERT INTO memory_fts (memory_fts, rowid, gist, content)
    #     VALUES ('delete', :rowid, :old_gist, :old_content);
    #   DELETE FROM memory WHERE uuid = :u;
    #   COMMIT;
    #   INSERT INTO memory_fts(memory_fts) VALUES('integrity-check');
    #   PRAGMA wal_checkpoint(TRUNCATE);
    #   VACUUM;
    print("\n--- Erasure: the write-policy.md secret-erasure transaction ---")
    print(f"Search 'prod-eu' before erasure: {search('prod-eu')}")

    # First prove the FAILURE MODE the documented sequence exists to avoid,
    # in an isolated connection so it cannot corrupt the connection this
    # spike still needs afterwards. spike2b_corruption_isolation.py has the
    # full isolated repro; this is the same check inline for one paragraph
    # of context.
    naive_con = sqlite3.connect(":memory:")
    naive_con.execute(
        "CREATE TABLE memory (rowid INTEGER PRIMARY KEY, uuid TEXT, gist TEXT, content TEXT)"
    )
    naive_con.execute(
        "CREATE VIRTUAL TABLE memory_fts USING fts5(gist, content, content='memory', content_rowid='rowid')"
    )
    naive_con.execute("INSERT INTO memory (rowid, uuid, gist, content) VALUES (1, 'u', 'g', 'c')")
    naive_con.execute("INSERT INTO memory_fts (rowid, gist, content) VALUES (1, 'g', 'c')")
    naive_con.commit()
    naive_con.execute("DELETE FROM memory WHERE rowid = 1")  # no FTS5 maintenance
    naive_con.commit()
    try:
        naive_con.execute("SELECT rowid FROM memory_fts WHERE memory_fts MATCH '\"c\"'").fetchall()
        print("NAIVE (delete content row only, no FTS5 maintenance): no error raised")
    except sqlite3.DatabaseError as e:
        print(
            f"NAIVE (delete content row only, no FTS5 maintenance) RAISED: "
            f"{type(e).__name__}: {e}  <- this is why write-policy.md's sequence "
            f"maintains memory_fts explicitly on every mutation, erasure included"
        )
    naive_con.close()

    # Now the DOCUMENTED sequence, on a fresh row in the main connection.
    con.execute(
        "INSERT INTO memory (rowid, uuid, gist, content) VALUES (2, ?, ?, ?)",
        ("uuid-2", "gist for erasure demo", "leaked-secret-token-XYZ appears here"),
    )
    con.execute(
        "INSERT INTO memory_fts (rowid, gist, content) VALUES (2, ?, ?)",
        ("gist for erasure demo", "leaked-secret-token-XYZ appears here"),
    )
    con.commit()
    print(f"\nSearch 'leaked-secret-token-XYZ' before proper erasure: {search('leaked-secret-token-XYZ')}")

    con.execute("BEGIN")
    # read current values first (write-policy.md step 1)
    cur_gist, cur_content = con.execute(
        "SELECT gist, content FROM memory WHERE rowid = 2"
    ).fetchone()
    # the documented 'delete' command: pass command + rowid + OLD column
    # values, in the SAME COLUMN ORDER as the table was declared
    # (gist, content) — this is what lets FTS5 remove the exact postings
    # without a full index rebuild, and — per the finding above — what
    # keeps the FTS5 index from being left in a state a later MATCH query
    # cannot survive.
    con.execute(
        "INSERT INTO memory_fts (memory_fts, rowid, gist, content) VALUES ('delete', ?, ?, ?)",
        (2, cur_gist, cur_content),
    )
    con.execute("DELETE FROM memory WHERE rowid = 2")
    con.execute("COMMIT")
    print("Issued the FTS5 'delete' command with current values, then deleted the content row")

    print(f"Search 'leaked-secret-token-XYZ' after proper erasure: {search('leaked-secret-token-XYZ')}")
    fts_row_after = con.execute(
        "SELECT rowid FROM memory_fts WHERE rowid = 2"
    ).fetchall()
    print(f"memory_fts bare select for rowid=2 after proper erasure: {fts_row_after}")
    print("(no DatabaseError raised — the documented sequence leaves the index queryable)")

    # --- integrity-check + wal_checkpoint + vacuum, as write-policy.md's
    # sequence runs them after the transaction commits ---------------------
    print("\n--- Post-erasure hygiene (write-policy.md step 5) ---")
    try:
        con.execute("INSERT INTO memory_fts(memory_fts) VALUES('integrity-check')")
        print("integrity-check: OK, no exception raised")
    except sqlite3.Error as e:
        print(f"integrity-check RAISED: {type(e).__name__}: {e}")
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print("wal_checkpoint(TRUNCATE): OK (no-op on an in-memory db, but call did not error)")
    except sqlite3.Error as e:
        print(f"wal_checkpoint RAISED: {type(e).__name__}: {e}")
    try:
        con.execute("VACUUM")
        print("VACUUM: OK, no exception raised")
    except sqlite3.Error as e:
        print(f"VACUUM RAISED: {type(e).__name__}: {e}")

    con.close()
    print("\n=== Spike 2 done ===")


if __name__ == "__main__":
    main()
