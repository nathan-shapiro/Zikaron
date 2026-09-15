"""M19 spike A: the two SQLite mechanisms design/knowledge-index.md asserts from documentation.

Consumers: §8.4 (the encoder-mismatch repair drops `chunks`, `chunks_fts` and `chunks_vec` and
recreates the vector table AT A NEW DIMENSION in a single transaction) and §3.2 (external-content
FTS5 does not observe deletes on its content table, so rows must be removed explicitly, and
querying such an index "returns garbage rather than an error").

    .venv/bin/python spikes/spike_vec0_fts5_ddl.py

Prints one line per question with a PASS/FAIL/NOTE verdict. No product code is imported.
"""

import os
import sqlite3
import struct
import sys
import tempfile

import sqlite_vec

DIM_OLD, DIM_NEW = 4, 6
results: list[tuple[str, str, str]] = []


def record(verdict: str, question: str, detail: str) -> None:
    results.append((verdict, question, detail))
    print(f"  [{verdict:<4}] {question}\n         {detail}")


def vec(xs: list[float]) -> bytes:
    return struct.pack(f"{len(xs)}f", *xs)


def connect(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path)
    c.enable_load_extension(True)
    c.load_extension(sqlite_vec.loadable_path())
    c.enable_load_extension(False)
    return c


def build(path: str, dim: int = DIM_OLD) -> sqlite3.Connection:
    """A miniature of §3.2: chunks + external-content FTS5 + vec0, three rows."""
    c = connect(path)
    c.executescript(f"""
        CREATE TABLE chunks(id INTEGER PRIMARY KEY, path TEXT NOT NULL, text TEXT NOT NULL);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(path, text, content='chunks', content_rowid='id');
        CREATE VIRTUAL TABLE chunks_vec USING vec0(chunk_id INTEGER PRIMARY KEY,
                                                   embedding float[{dim}]);
    """)
    rows = [
        (1, "a.md", "reciprocal rank fusion explained here"),
        (2, "b.md", "the encoder mismatch repair drops derived tables"),
        (3, "c.md", "sparse checkout listing is not the file set"),
    ]
    for i, p, t in rows:
        c.execute("INSERT INTO chunks(id, path, text) VALUES (?,?,?)", (i, p, t))
        c.execute("INSERT INTO chunks_fts(rowid, path, text) VALUES (?,?,?)", (i, p, t))
        c.execute(
            "INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?,?)",
            (i, vec([float(i)] + [0.0] * (dim - 1))),
        )
    c.commit()
    return c


def ic(c: sqlite3.Connection, arg: int | None = 1) -> str:
    """FTS5's own integrity-check. Argument 1 additionally compares index against content.

    `arg=None` issues the bare form -- the one an implementer reaches for first, and the one
    trap 4 exists to warn about, so every corpus is checked against it rather than against an
    assumed equivalence to argument 0.
    """
    sql = (
        "INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')"
        if arg is None
        else f"INSERT INTO chunks_fts(chunks_fts, rank) VALUES('integrity-check', {arg})"
    )
    try:
        c.execute(sql)
        return "OK"
    except sqlite3.Error as e:
        return f"{type(e).__name__}: {e}"


def vec_dim(c: sqlite3.Connection, table: str = "chunks_vec") -> int | None:
    """vec0 records its declared dimension in its own shadow/introspection tables."""
    sql = c.execute(
        "SELECT sql FROM sqlite_master WHERE name=? AND type='table'", (table,)
    ).fetchone()
    if not sql:
        return None
    body = sql[0]
    return int(body[body.index("float[") + 6 : body.index("]", body.index("float["))])


# --------------------------------------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="zk-spike-a-")
print(f"sqlite {sqlite3.sqlite_version}, sqlite-vec {sqlite_vec.loadable_path().split('/')[-1]}")
print(f"python sqlite3 module {sqlite3.version}, scratch {tmp}\n")

# ======================================================================================
print("A1-A4. vec0 DDL inside a transaction")

# A1: does the drop-and-recreate work at all, with Python's DEFAULT isolation_level?
p = os.path.join(tmp, "a1.db")
c = build(p)
c.execute("BEGIN")
c.executescript  # noqa: B018 - documented below; executescript would COMMIT first
for stmt in (
    "DELETE FROM chunks_fts",  # DML first, see A5 for why this one is wrong
    "DROP TABLE chunks_fts",
    "DROP TABLE chunks_vec",
    "DELETE FROM chunks",
    "CREATE VIRTUAL TABLE chunks_fts USING fts5(path, text, content='chunks', content_rowid='id')",
    f"CREATE VIRTUAL TABLE chunks_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{DIM_NEW}])",
):
    c.execute(stmt)
c.commit()
record(
    "PASS" if vec_dim(c) == DIM_NEW else "FAIL",
    "A1  drop + recreate vec0 at a new dimension inside one explicit transaction",
    f"declared dimension after commit = {vec_dim(c)} (was {DIM_OLD}, wanted {DIM_NEW})",
)
c.close()

# A2: does it survive a reopen?
c = connect(p)
try:
    c.execute("INSERT INTO chunks(id,path,text) VALUES (9,'x','y')")
    c.execute("INSERT INTO chunks_vec(chunk_id, embedding) VALUES (9,?)", (vec([1.0] * DIM_NEW),))
    c.commit()
    new_ok = True
    new_err = ""
except sqlite3.Error as e:
    new_ok, new_err = False, f"{type(e).__name__}: {e}"
try:
    c.execute("INSERT INTO chunks_vec(chunk_id, embedding) VALUES (10,?)", (vec([1.0] * DIM_OLD),))
    old_rejected, old_err = False, "accepted an OLD-dimension vector"
except sqlite3.Error as e:
    old_rejected, old_err = True, f"{type(e).__name__}: {e}"
c.rollback()
record(
    "PASS" if (new_ok and old_rejected and vec_dim(c) == DIM_NEW) else "FAIL",
    "A2  the new dimension survives a close/reopen and is enforced",
    f"dim={vec_dim(c)}; new-dim insert ok={new_ok}{new_err}; old-dim rejected={old_rejected} ({old_err})",
)
c.close()

# A3: does a FAILURE mid-repair roll back cleanly -- old tables, old dimension, old rows?
p = os.path.join(tmp, "a3.db")
c = build(p)
before = c.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
c.execute("BEGIN")
c.execute("DROP TABLE chunks_fts")
c.execute("DROP TABLE chunks_vec")
c.execute("DELETE FROM chunks")
c.execute(
    f"CREATE VIRTUAL TABLE chunks_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{DIM_NEW}])"
)
try:  # the simulated failure: the indexer dies / the next statement is bad
    c.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(path, text, content='chunks', tokenize='no-such-tokenizer')")
    raise AssertionError("expected the bad tokenizer to fail")
except sqlite3.Error:
    c.rollback()
after = c.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
fts_back = c.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'fusion'").fetchone()[0]
record(
    "PASS" if (after == before == 3 and vec_dim(c) == DIM_OLD and fts_back == 1) else "FAIL",
    "A3  ROLLBACK after dropping and recreating restores the pre-repair state",
    f"chunks_vec rows {before} -> {after}; dimension back to {vec_dim(c)}; FTS query returns {fts_back} row(s)",
)
c.close()

# A4: the trap -- Python's legacy transaction control does NOT open a transaction for DDL.
p = os.path.join(tmp, "a4.db")
c = build(p)  # default isolation_level="" (legacy), no explicit BEGIN
c.execute("DROP TABLE chunks_vec")
c.rollback()
survived = "chunks_vec" in {
    r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
}
record(
    "NOTE" if not survived else "PASS",
    "A4  DROP TABLE with NO explicit BEGIN, under python sqlite3's default isolation_level",
    "ROLLBACK did NOT restore the table -- the DDL ran in autocommit"
    if not survived
    else "the DDL joined an implicit transaction and rolled back",
)
c.close()

# A4b: same statement, after a DML statement has opened the implicit transaction.
p = os.path.join(tmp, "a4b.db")
c = build(p)
c.execute("DELETE FROM chunks WHERE id=3")  # legacy mode opens a transaction for DML
c.execute("DROP TABLE chunks_vec")
c.rollback()
survived_b = "chunks_vec" in {
    r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
}
record(
    "NOTE",
    "A4b DROP TABLE after a DML statement has opened the implicit transaction",
    f"chunks_vec survived the ROLLBACK: {survived_b}",
)
c.close()

# A4c: executescript() -- the natural way to write a multi-statement repair.
p = os.path.join(tmp, "a4c.db")
c = build(p)
c.execute("BEGIN")
c.execute("DELETE FROM chunks WHERE id=3")
c.executescript("DROP TABLE chunks_vec;")
try:
    c.rollback()
except sqlite3.Error:
    pass
rows_left = c.execute("SELECT count(*) FROM chunks").fetchone()[0]
record(
    "NOTE",
    "A4c executescript() inside an explicit transaction",
    f"chunks rows after ROLLBACK: {rows_left} of 3 -- executescript COMMITs any open transaction first"
    if rows_left < 3
    else f"chunks rows after ROLLBACK: {rows_left} of 3 -- the transaction survived",
)
c.close()

# ======================================================================================
print("\nA5-A9. External-content FTS5 when the content rows are gone")

p = os.path.join(tmp, "a5.db")
c = build(p)

# A5: does FTS observe a delete on its content table?
c.execute("DELETE FROM chunks WHERE id=1")
c.commit()
still = c.execute("SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'fusion'").fetchall()
record(
    "PASS" if still else "FAIL",
    "A5  FTS5 does NOT observe a delete on its external content table",
    f"MATCH 'fusion' still returns rowid(s) {[r[0] for r in still]} after the content row was deleted",
)

# A6: what does the orphaned index return -- error, or values?
try:
    row = c.execute(
        "SELECT rowid, path, text FROM chunks_fts WHERE chunks_fts MATCH 'fusion'"
    ).fetchone()
    record("NOTE", "A6  selecting COLUMNS of an orphaned FTS5 row", f"returned {row!r} (no error)")
except sqlite3.Error as e:
    record("NOTE", "A6  selecting COLUMNS of an orphaned FTS5 row", f"{type(e).__name__}: {e}")

for fn, label in (
    ("bm25(chunks_fts)", "A7  bm25() over an orphaned row"),
    ("snippet(chunks_fts, 1, '[', ']', '...', 8)", "A8  snippet() over an orphaned row"),
    ("highlight(chunks_fts, 1, '[', ']')", "A8b highlight() over an orphaned row"),
):
    try:
        v = c.execute(
            f"SELECT {fn} FROM chunks_fts WHERE chunks_fts MATCH 'fusion'"
        ).fetchone()[0]
        record("NOTE", label, f"returned {v!r} (no error)")
    except sqlite3.Error as e:
        record("NOTE", label, f"{type(e).__name__}: {e}")

# A9: does FTS5's own integrity-check see the orphan?
for arg, label in (
    (None, "A9  FTS5 integrity-check, no argument"),
    (0, "A9b FTS5 integrity-check, argument 0 (index internals only)"),
    (1, "A9c FTS5 integrity-check, argument 1 (also compare against content)"),
):
    sql = (
        "INSERT INTO chunks_fts(chunks_fts) VALUES('integrity-check')"
        if arg is None
        else f"INSERT INTO chunks_fts(chunks_fts, rank) VALUES('integrity-check', {arg})"
    )
    try:
        c.execute(sql)
        record("NOTE", label, "reported OK -- the orphan is INVISIBLE to it")
    except sqlite3.Error as e:
        record("NOTE", label, f"{type(e).__name__}: {e}")
c.close()

# ======================================================================================
print("\nA10-A12. The explicit deletion §4.6 must perform, and its ordering constraint")

p = os.path.join(tmp, "a10.db")
c = build(p)
# The documented incantation: supply the ORIGINAL column values with the 'delete' command.
orig = c.execute("SELECT path, text FROM chunks WHERE id=1").fetchone()
c.execute("INSERT INTO chunks_fts(chunks_fts, rowid, path, text) VALUES('delete', 1, ?, ?)", orig)
c.execute("DELETE FROM chunks WHERE id=1")
c.execute("DELETE FROM chunks_vec WHERE chunk_id=1")
c.commit()
gone = c.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'fusion'").fetchone()[0]
ic10 = ic(c, 1)
record(
    "PASS" if gone == 0 and ic10 == "OK" else "FAIL",
    "A10 'delete' with the original column values, then delete the content row",
    f"MATCH now returns {gone} row(s); integrity-check 1: {ic10}",
)

# A11: the ordering constraint -- what if you delete the content row FIRST?
c.execute("DELETE FROM chunks WHERE id=2")
try:
    c.execute("INSERT INTO chunks_fts(chunks_fts, rowid, path, text) VALUES('delete', 2, NULL, NULL)")
    c.commit()
    left = c.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'mismatch'").fetchone()[0]
    record(
        "NOTE",
        "A11 'delete' with WRONG values (content row already gone, so NULLs)",
        f"accepted; MATCH 'mismatch' still returns {left} row(s); "
        f"integrity-check 0: {ic(c, 0)}; integrity-check 1: {ic(c, 1)}",
    )
except sqlite3.Error as e:
    record("NOTE", "A11 'delete' with WRONG values", f"{type(e).__name__}: {e}")

# A12: 'delete-all' -- the whole-index clear the repair could use instead of DROP.
p = os.path.join(tmp, "a12.db")
c2 = build(p)
c2.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('delete-all')")
c2.execute("DELETE FROM chunks")
c2.commit()
n = c2.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'fusion OR mismatch OR sparse'").fetchone()[0]
ic3 = ic(c2, 1)
record(
    "PASS" if n == 0 and ic3 == "OK" else "FAIL",
    "A12 'delete-all' clears the index without needing the original values",
    f"MATCH returns {n} row(s); integrity-check 1: {ic3}",
)
c2.close()
c.close()

# A16: the OTHER direction of invariant 3 -- a `chunks` row with NO `chunks_fts` row.
# A9c measured that argument 1 catches an ORPHANED index (FTS rows whose content is gone).
# Invariant 3 also rules out the inverse, and an oracle that sees only one direction would pass
# on half the corpus the invariant exists to exclude.
p = os.path.join(tmp, "a16.db")
c = build(p)
orig = c.execute("SELECT path, text FROM chunks WHERE id=2").fetchone()
c.execute("INSERT INTO chunks_fts(chunks_fts, rowid, path, text) VALUES('delete', 2, ?, ?)", orig)
c.commit()  # content row KEPT; its FTS row removed
still_there = c.execute("SELECT count(*) FROM chunks WHERE id=2").fetchone()[0]
matches = c.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'mismatch'").fetchone()[0]
record(
    "NOTE",
    "A16 integrity-check against a MISSING FTS row (content row present, FTS row deleted)",
    f"chunks row present={still_there}, FTS matches={matches}; "
    f"bare: {ic(c, None)}; integrity-check 0: {ic(c, 0)}; integrity-check 1: {ic(c, 1)}",
)
c.close()

# ======================================================================================
print("\nA13. Does DROP TABLE on vec0 leave shadow tables behind?")
p = os.path.join(tmp, "a13.db")
c = build(p)
shadows_before = sorted(
    r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'chunks_vec%'")
)
c.execute("BEGIN")
c.execute("DROP TABLE chunks_vec")
mid = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'chunks_vec%'"))
c.execute(
    f"CREATE VIRTUAL TABLE chunks_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{DIM_NEW}])"
)
c.commit()
after_names = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE name LIKE 'chunks_vec%'"))
record(
    "PASS" if not mid else "FAIL",
    "A13 DROP TABLE removes vec0's shadow tables, so the recreate does not collide",
    f"{len(shadows_before)} objects before, {len(mid)} between drop and create, {len(after_names)} after",
)
c.close()

# ======================================================================================
print("\nA14. Is there a cascade after all? The documented FTS5 trigger pattern, extended to vec0")
p = os.path.join(tmp, "a14.db")
c = build(p)
c.executescript("""
    CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, path, text) VALUES('delete', old.id, old.path, old.text);
      DELETE FROM chunks_vec WHERE chunk_id = old.id;
    END;
""")
c.execute("BEGIN")
c.execute("DELETE FROM chunks WHERE path='a.md'")
c.commit()
fts_left = c.execute("SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH 'fusion'").fetchone()[0]
vec_left = c.execute("SELECT count(*) FROM chunks_vec WHERE chunk_id=1").fetchone()[0]
ic14 = ic(c, 1)
record(
    "PASS" if fts_left == 0 and vec_left == 0 and ic14 == "OK" else "FAIL",
    "A14 an AFTER DELETE trigger on `chunks` maintains BOTH derived tables",
    f"orphaned FTS rows {fts_left}, orphaned vectors {vec_left}, integrity-check 1: {ic14}",
)
c.close()

# A15: what a trigger costs -- the §8.4 repair drops the tables the trigger writes to.
p = os.path.join(tmp, "a15.db")
c = build(p)
c.executescript("""
    CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
      INSERT INTO chunks_fts(chunks_fts, rowid, path, text) VALUES('delete', old.id, old.path, old.text);
      DELETE FROM chunks_vec WHERE chunk_id = old.id;
    END;
""")
c.execute("BEGIN")
c.execute("DROP TABLE chunks_fts")
c.execute("DROP TABLE chunks_vec")
try:
    c.execute("DELETE FROM chunks")  # the repair's own statement, with the trigger still installed
    outcome = "succeeded -- the trigger silently did nothing"
except sqlite3.Error as e:
    outcome = f"{type(e).__name__}: {e}"
c.rollback()
record("NOTE", "A15 the §8.4 repair's `DELETE FROM chunks` while a sync trigger is installed", outcome)
c.close()

print("\n" + "=" * 90)
fails = [r for r in results if r[0] == "FAIL"]
print(f"{len(results)} questions, {len(fails)} FAIL")
for _, q, d in fails:
    print(f"  FAIL {q}: {d}")
sys.exit(1 if fails else 0)
