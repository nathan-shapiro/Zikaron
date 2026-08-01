"""
M0 spike 1 — sqlite-vec loads and the schema pattern works.

Exercises build-plan.md's four checks:
  1. Load the extension from a venv install.
  2. Create `memory_vec` from the `float[<embed_dim>]` template at a
     NON-384 width, since schema.md's default (384, bge-small) is the one
     width every real measurement already covers — the spike's job is the
     *other* case, since embed_dim is configurable per schema.md.
  3. Confirm explicit-rowid inserts work and that
     `memory_vec.rowid == memory_chunk.chunk_id` supports the join.
  4. Confirm a KNN query returns distances.
  5. Confirm what happens on a dimension mismatch: the error, and whether
     it is detectable before insert.

Throwaway per build-plan.md's M0 fence. Print raw findings; no assertions,
no test framework, no production code.
"""

import sqlite3
import struct

import sqlite_vec

DIM = 8  # non-384 on purpose — schema.md's DDL is a TEMPLATE, not a literal


def serialize(vec: list[float]) -> bytes:
    """Match sqlite-vec's documented raw-bytes input format for float[N]."""
    return struct.pack(f"{len(vec)}f", *vec)


def main() -> None:
    print("=== Spike 1: sqlite-vec ===")
    print(f"sqlite_vec.__version__ = {sqlite_vec.__version__}")

    con = sqlite3.connect(":memory:")

    # --- 1. Load the extension ---------------------------------------
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    (loaded_version,) = con.execute("SELECT vec_version()").fetchone()
    print(f"vec_version() = {loaded_version}  <- extension loaded OK")

    # --- 2. Create memory_vec from the float[<embed_dim>] template ----
    # schema.md: "TEMPLATE, not a literal: <embed_dim> is substituted with
    # the VALIDATED EFFECTIVE embed_dim at creation."
    ddl = f"CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[{DIM}])"
    print(f"DDL: {ddl}")
    con.execute(ddl)
    print(f"memory_vec created at width {DIM} (non-384) — template substitution OK")

    # Companion table standing in for memory_chunk.chunk_id, the join key
    # schema.md declares as an invariant: memory_vec.rowid == memory_chunk.chunk_id
    con.execute("""
        CREATE TABLE memory_chunk (
            chunk_id INTEGER PRIMARY KEY,
            memory_uuid TEXT NOT NULL,
            part_index INTEGER NOT NULL
        )
    """)

    # --- 3. Explicit-rowid insert + the join invariant -----------------
    rows = [
        (1, "uuid-a", 0, [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
        (2, "uuid-a", 1, [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2]),
        (3, "uuid-b", 0, [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    ]
    for chunk_id, uuid, part_index, vec in rows:
        con.execute(
            "INSERT INTO memory_chunk (chunk_id, memory_uuid, part_index) VALUES (?, ?, ?)",
            (chunk_id, uuid, part_index),
        )
        # explicit rowid on the vec0 table, matching memory_chunk.chunk_id
        con.execute(
            "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)",
            (chunk_id, serialize(vec)),
        )
    con.commit()
    print(f"Inserted {len(rows)} rows with explicit rowid = chunk_id")

    join_rows = con.execute("""
        SELECT mc.chunk_id, mc.memory_uuid, mv.rowid
        FROM memory_chunk mc
        JOIN memory_vec mv ON mv.rowid = mc.chunk_id
        ORDER BY mc.chunk_id
    """).fetchall()
    print(f"Join memory_vec.rowid == memory_chunk.chunk_id -> {join_rows}")
    join_ok = all(chunk_id == vec_rowid for chunk_id, _uuid, vec_rowid in join_rows)
    print(f"Join invariant holds: {join_ok}")

    # --- 4. KNN query returns distances ---------------------------------
    query_vec = [0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85]  # near uuid-a's chunk 0
    knn_rows = con.execute(
        """
        SELECT mv.rowid, mc.memory_uuid, mv.distance
        FROM memory_vec mv
        JOIN memory_chunk mc ON mc.chunk_id = mv.rowid
        WHERE mv.embedding MATCH ?
          AND k = 3
        ORDER BY mv.distance
        """,
        (serialize(query_vec),),
    ).fetchall()
    print(f"KNN k=3 results (rowid, uuid, distance): {knn_rows}")
    print(f"Distances returned and numeric: {all(isinstance(d, float) for _, _, d in knn_rows)}")

    # --- 5. Dimension mismatch behaviour --------------------------------
    print("\n--- Dimension mismatch ---")
    wrong_dim_vec = serialize([0.1, 0.2, 0.3])  # 3-d into an 8-d column
    try:
        con.execute(
            "INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)",
            (99, wrong_dim_vec),
        )
        con.commit()
        print("UNEXPECTED: mismatched-dimension insert succeeded with no error")
    except sqlite3.Error as e:
        print(f"Insert raised: {type(e).__name__}: {e}")

    # Is it detectable *before* insert, i.e. without relying on the DB to reject it?
    # sqlite-vec exposes vec_length() precisely for this — check what it reports
    # for the column's declared width vs. what we're about to insert.
    try:
        (declared_len,) = con.execute(
            "SELECT vec_length(embedding) FROM memory_vec LIMIT 1"
        ).fetchone()
        print(f"vec_length() on an existing row reports declared width: {declared_len}")
    except sqlite3.Error as e:
        print(f"vec_length() probe raised: {type(e).__name__}: {e}")

    # Confirm the declared width is also readable from a fresh, empty table
    # via a schema/pragma inspection, which is what a pre-insert check would need.
    schema_row = con.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'memory_vec'"
    ).fetchone()
    print(f"sqlite_master DDL for memory_vec: {schema_row}")

    con.close()
    print("\n=== Spike 1 done ===")


if __name__ == "__main__":
    main()
