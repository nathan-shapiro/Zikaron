"""Probe: can we cross-rank across per-KB SQLite files via ATTACH?
Measures the attach limit, and whether FTS5 MATCH / bm25() / vec0 KNN work on attached DBs.
"""
import sqlite3, struct, tempfile, os, sqlite_vec

def vec(xs): return struct.pack(f"{len(xs)}f", *xs)

tmp = tempfile.mkdtemp()
def make_kb(name, rows):
    p = os.path.join(tmp, f"{name}.db")
    c = sqlite3.connect(p); c.enable_load_extension(True)
    c.load_extension(sqlite_vec.loadable_path()); c.enable_load_extension(False)
    c.execute("CREATE VIRTUAL TABLE chunks USING fts5(path, body)")
    c.execute("CREATE VIRTUAL TABLE vecs USING vec0(id INTEGER PRIMARY KEY, emb float[4])")
    for i,(path,body,emb) in enumerate(rows):
        c.execute("INSERT INTO chunks(rowid,path,body) VALUES (?,?,?)",(i+1,path,body))
        c.execute("INSERT INTO vecs(id,emb) VALUES (?,?)",(i+1,vec(emb)))
    c.commit(); c.close(); return p

a = make_kb("kb_a", [("src/retrieval.py","hybrid fusion ranking arms",[1,0,0,0]),
                     ("src/store.py","sqlite storage layer",[0,1,0,0])])
b = make_kb("kb_b", [("docs/fusion.md","reciprocal rank fusion explained",[1,0,0,0]),
                     ("docs/intro.md","getting started guide",[0,0,1,0])])

main = sqlite3.connect(":memory:"); main.enable_load_extension(True)
main.load_extension(sqlite_vec.loadable_path()); main.enable_load_extension(False)

print("1. ATTACH limit:", main.execute("SELECT 0").connection.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED)
      if hasattr(main,'getlimit') else "getlimit unavailable")
main.execute("ATTACH DATABASE ? AS kba",(a,)); main.execute("ATTACH DATABASE ? AS kbb",(b,))

print("2. FTS5 MATCH on attached:",
      main.execute("SELECT path FROM kba.chunks WHERE chunks MATCH 'fusion'").fetchall())
print("3. bm25() on attached:",
      [(p, round(s,4)) for p,s in main.execute(
        "SELECT path, bm25(chunks) FROM kba.chunks WHERE chunks MATCH 'ranking' ORDER BY 2").fetchall()])
print("4. vec0 KNN on attached:",
      main.execute("SELECT id, distance FROM kba.vecs WHERE emb MATCH ? AND k=1",(vec([1,0,0,0]),)).fetchall())
try:
    r = main.execute("""
      SELECT 'kba' src, path, bm25(kba.chunks) s FROM kba.chunks WHERE kba.chunks MATCH 'fusion'
      UNION ALL
      SELECT 'kbb', path, bm25(kbb.chunks) FROM kbb.chunks WHERE kbb.chunks MATCH 'fusion'
      ORDER BY s""").fetchall()
    print("5. UNION ALL across two attached FTS5:", [(a_,b_,round(c_,4)) for a_,b_,c_ in r])
except Exception as e:
    print("5. UNION ALL across attached FTS5 FAILED:", type(e).__name__, e)
try:
    r = main.execute("""
      SELECT 'kba' src, id, distance FROM kba.vecs WHERE emb MATCH ? AND k=2
      UNION ALL
      SELECT 'kbb', id, distance FROM kbb.vecs WHERE emb MATCH ? AND k=2
      ORDER BY distance""",(vec([1,0,0,0]),vec([1,0,0,0]))).fetchall()
    print("6. UNION ALL across two attached vec0:", [(x,y,round(z,4)) for x,y,z in r])
except Exception as e:
    print("6. UNION ALL across attached vec0 FAILED:", type(e).__name__, e)

n=2
try:
    while n < 40:
        p = make_kb(f"x{n}", [("p","q",[0,0,0,1])])
        main.execute(f"ATTACH DATABASE ? AS x{n}",(p,)); n+=1
except Exception as e:
    print(f"7. attach failed at db #{n+1}: {type(e).__name__}: {e}")
else:
    print("7. attached 40+ without error")
