import sqlite3, tempfile, os, sqlite_vec
tmp = tempfile.mkdtemp()
def make_kb(fname, tbl, rows):
    p = os.path.join(tmp, fname); c = sqlite3.connect(p)
    c.execute(f"CREATE VIRTUAL TABLE {tbl} USING fts5(path, body)")
    for i,(path,body) in enumerate(rows):
        c.execute(f"INSERT INTO {tbl}(rowid,path,body) VALUES (?,?,?)",(i+1,path,body))
    c.commit(); c.close(); return p

# 'fusion' RARE in kb_a (1/200), COMMON in kb_b (100/200). Identical matching sentence in both.
SENT = "reciprocal rank fusion explained here"
a = make_kb("a.db","chunks_a", [("hit.md",SENT)] + [(f"f{i}.md","unrelated filler text") for i in range(199)])
b = make_kb("b.db","chunks_b", [(f"h{i}.md",SENT) for i in range(100)] + [(f"g{i}.md","unrelated filler text") for i in range(100)])

m = sqlite3.connect(":memory:")
m.execute("ATTACH DATABASE ? AS kba",(a,)); m.execute("ATTACH DATABASE ? AS kbb",(b,))

print("A. UNION across attached FTS5 when table names are UNIQUE per KB:")
try:
    r = m.execute("""
      SELECT 'kba' src, path, bm25(chunks_a) s FROM kba.chunks_a WHERE chunks_a MATCH 'fusion'
      UNION ALL
      SELECT 'kbb', path, bm25(chunks_b) FROM kbb.chunks_b WHERE chunks_b MATCH 'fusion'
      ORDER BY s LIMIT 5""").fetchall()
    for src,p,s in r: print(f"   {src}  {p:<9} bm25={s:.5f}")
    print("   -> WORKS")
except Exception as e:
    print("   FAILED:", type(e).__name__, e)

print("\nB. Is BM25 comparable across corpora? Identical matching text, different corpus stats:")
for schema,tbl in (("kba","chunks_a"),("kbb","chunks_b")):
    n = m.execute(f"SELECT count(*) FROM {schema}.{tbl}").fetchone()[0]
    hits = m.execute(f"SELECT count(*) FROM {schema}.{tbl} WHERE {tbl} MATCH 'fusion'").fetchone()[0]
    s = m.execute(f"SELECT bm25({tbl}) FROM {schema}.{tbl} WHERE {tbl} MATCH 'fusion' ORDER BY 1 LIMIT 1").fetchone()[0]
    print(f"   {schema}: corpus={n:>3}  matching={hits:>3}  best bm25={s:>9.5f}")
print("\n   Both rows contain the SAME sentence. Any difference is corpus statistics, not relevance.")
