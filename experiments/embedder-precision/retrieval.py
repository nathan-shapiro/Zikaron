#!/usr/bin/env python
"""Index building and retrieval arms. SQLite + FTS5 + sqlite-vec, exactly the Zikaron stack.

Three retrieval arms:
  bm25(field_set)  - FTS5 BM25 over either {gist, content} or {gist, content, tokens}
  dense(model)     - sqlite-vec vec0 KNN over cosine-normalised embeddings
  rrf(a, b, k=60)  - reciprocal rank fusion, fixed k, no per-config tuning

Two FTS tables are built with DIFFERENT tokenizers on purpose:
  fts_text   - default unicode61. What the incumbent design would use.
  fts_tok    - unicode61 with tokenchars '_-./' so extracted identifiers survive whole.
               Must match identifiers.py; see the GOTCHA note there.

Embeddings are stored per model in their own vec0 table, and the model id + dimension are
recorded in a `vectors_meta` row. That is the Open-question-5 hygiene rule (a same-dimension
model swap is otherwise a silent correctness failure) implemented rather than argued about.
"""
import json
import pathlib
import sqlite3

import numpy as np
import sqlite_vec

from identifiers import extract_str

HERE = pathlib.Path(__file__).parent
DB_PATH = HERE / "index.db"
RRF_K = 60          # fixed for every configuration, never tuned per config
FUSE_DEPTH = 50     # candidates taken from each arm before fusion; also the reranker's window

# fastembed model name -> (query prefix, passage prefix)
MODELS = {
    "bge-small": ("BAAI/bge-small-en-v1.5", "", ""),
    "bge-small-prefix": ("BAAI/bge-small-en-v1.5",
                         "Represent this sentence for searching relevant passages: ", ""),
    "bge-large-prefix": ("BAAI/bge-large-en-v1.5",
                         "Represent this sentence for searching relevant passages: ", ""),
    "nomic": ("nomic-ai/nomic-embed-text-v1.5", "search_query: ", "search_document: "),
}

TOKENIZE_TEXT = "unicode61"
TOKENIZE_TOK = "unicode61 tokenchars '_-./'"


def connect(path=DB_PATH) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def doc_text(m: dict, mode: str = "gist_content") -> str:
    """What gets embedded / indexed for a memory."""
    if mode == "gist_only":
        return m["gist"]
    if mode == "content_only":
        return m["content"]
    return m["gist"] + "\n" + m["content"]


def build_lexical(db: sqlite3.Connection, memories: list) -> None:
    db.executescript(f"""
        drop table if exists mem;
        drop table if exists fts_text;
        drop table if exists fts_tok;
        create table mem(rowid integer primary key, uuid text, key text, cat text,
                         gist text, content text, tokens text);
        create virtual table fts_text using fts5(gist, content, tokenize="{TOKENIZE_TEXT}");
        create virtual table fts_tok  using fts5(gist, content, tokens,
                                                tokenize="{TOKENIZE_TOK}");
    """)
    for i, m in enumerate(memories, start=1):
        tok = extract_str(m["gist"] + " " + m["content"])
        db.execute("insert into mem(rowid, uuid, key, cat, gist, content, tokens)"
                   " values (?,?,?,?,?,?,?)",
                   (i, m["uuid"], m["key"], m["cat"], m["gist"], m["content"], tok))
        db.execute("insert into fts_text(rowid, gist, content) values (?,?,?)",
                   (i, m["gist"], m["content"]))
        db.execute("insert into fts_tok(rowid, gist, content, tokens) values (?,?,?,?)",
                   (i, m["gist"], m["content"], tok))
    db.commit()


def build_dense(db: sqlite3.Connection, memories: list, tag: str, embedder,
                passage_prefix: str, dim: int, mode: str = "gist_content") -> None:
    table = f"vec_{tag.replace('-', '_')}"
    db.executescript(f"""
        drop table if exists {table};
        create virtual table {table} using vec0(rowid integer primary key, emb float[{dim}]);
        create table if not exists vectors_meta(tag text primary key, model text, dim int,
                                                embed_mode text);
    """)
    texts = [passage_prefix + doc_text(m, mode) for m in memories]
    vecs = np.array(list(embedder.embed(texts)), dtype=np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    for i, v in enumerate(vecs, start=1):
        db.execute(f"insert into {table}(rowid, emb) values (?,?)", (i, v.tobytes()))
    db.execute("insert or replace into vectors_meta values (?,?,?,?)",
               (tag, MODELS[tag][0] if tag in MODELS else tag, dim, mode))
    db.commit()


# --------------------------------------------------------------------------- arms

def _fts_query(text: str, tokenchars: bool) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms."""
    import re
    pat = r"[A-Za-z0-9_\-./]+" if tokenchars else r"[A-Za-z0-9]+"
    terms = [t for t in re.findall(pat, text.lower()) if len(t) > 1]
    terms = [t.strip("-./") for t in terms]
    terms = [t for t in terms if len(t) > 1]
    if not terms:
        return '"zzzznomatch"'
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))


def bm25(db, query: str, limit=FUSE_DEPTH, use_tokens=False, weights=None) -> list:
    """Return [(rowid, score)] best-first. weights = per-column BM25 weights."""
    if use_tokens:
        w = weights or (1.0, 1.0, 3.0)   # tokens column weighted higher
        q = _fts_query(query, tokenchars=True)
        # bm25() returns a negative number, more-negative = better; negate for best-first.
        sql = (f"select rowid, -bm25(fts_tok, {w[0]}, {w[1]}, {w[2]}) as s from fts_tok "
               f"where fts_tok match ? order by s desc limit ?")
    else:
        w = weights or (1.0, 1.0)
        q = _fts_query(query, tokenchars=False)
        sql = (f"select rowid, -bm25(fts_text, {w[0]}, {w[1]}) as s from fts_text "
               f"where fts_text match ? order by s desc limit ?")
    try:
        return [(r, s) for r, s in db.execute(sql, (q, limit))]
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"FTS query failed for {query!r}: {e}") from e


def dense(db, qvec: np.ndarray, tag: str, limit=FUSE_DEPTH) -> list:
    table = f"vec_{tag.replace('-', '_')}"
    rows = db.execute(
        f"select rowid, distance from {table} where emb match ? and k = ? order by distance",
        (qvec.astype(np.float32).tobytes(), limit)).fetchall()
    return [(r, -d) for r, d in rows]


def rrf(*rankings, k=RRF_K) -> list:
    """Reciprocal rank fusion. rankings are lists of (rowid, score) best-first."""
    acc = {}
    for ranking in rankings:
        for rank, (rowid, _) in enumerate(ranking, start=1):
            acc[rowid] = acc.get(rowid, 0.0) + 1.0 / (k + rank)
    return sorted(acc.items(), key=lambda kv: -kv[1])


def load_dataset() -> dict:
    return json.loads((HERE / "dataset.json").read_text())
