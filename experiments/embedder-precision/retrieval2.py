#!/usr/bin/env python
"""Round-2 retrieval additions. Imports round-1 `retrieval` and does NOT modify it.

Why a second module: `PREREGISTRATION.md` records sha256 hashes of the round-1 code so a future
session can prove the round-1 results were not produced by different code than what is on disk.
Editing `retrieval.py` would invalidate that record. Everything new lives here.

What is new:

1. **A factorial set of FTS5 tables** so the four things round-1 config 5 changed at once can be
   separated (review BLOCKER 5):
     fx_text          unicode61,   (gist, content)                 - the baseline tokenizer
     fx_tokchar       tokenchars,  (gist, content)                 - tokenizer change ONLY
     fx_tok_dup       tokenchars,  (gist, content, tokens)         - tokens WITH dup emission
     fx_tok_nodup     tokenchars,  (gist, content, tokens)         - tokens WITHOUT dup emission
     fx_tokonly       tokenchars,  (tokens)                        - extracted field alone,
                                                                     so custom tokenization can be
                                                                     confined to it
   FTS5 cannot give one table two tokenizers, so "custom tokenization confined to the extracted
   field" has to be two tables fused, not one table. That is `fx_text` + `fx_tokonly`.

2. **`extract_variant`** - the same frozen regex set from `identifiers.py`, with whole-token
   duplicate emission as an explicit switch. `assert_extract_parity()` proves the dup=True path
   is byte-identical to the frozen `identifiers.extract`, so the factor is isolated and the
   extractor under test is unchanged.

3. **`rrf_counted`** - RRF that also reports how often two documents finish on exactly equal fused
   scores, and therefore how often order is decided by Python's stable-sort insertion order, which
   favours whichever arm was passed first (review MAJOR 8). Two distinct quantities are tracked and
   named separately after review round-2 BLOCKER 3: the per-query BOOLEAN "any tie inside the top
   five", and the mean COUNT of tied adjacent pairs inside the top five. Round 2 computed the
   second and labelled it the first.

3b. **`rrf_tiebreak`** - the same fusion with an explicit, declared tie-handling rule instead of
   insertion order, so the round-3 exploratory diagnostic (`tie_sensitivity.py`) can test whether
   tie handling is what erased the dense arm's advantage, rather than inferring it from prevalence.

4. **Depth as a parameter** everywhere, so a displacement diagnostic can be run over the whole
   corpus instead of over a 50-candidate union (review MAJOR 13).
"""
import re
import sqlite3

import numpy as np

import identifiers
import retrieval as R

TOKENIZE_TEXT = R.TOKENIZE_TEXT           # "unicode61"
TOKENIZE_TOK = R.TOKENIZE_TOK             # "unicode61 tokenchars '_-./'"

FTS_TABLES = {
    # name          -> (tokenizer, columns)
    "fx_text":      (TOKENIZE_TEXT, ("gist", "content")),
    "fx_tokchar":   (TOKENIZE_TOK,  ("gist", "content")),
    "fx_tok_dup":   (TOKENIZE_TOK,  ("gist", "content", "tokens")),
    "fx_tok_nodup": (TOKENIZE_TOK,  ("gist", "content", "tokens")),
    "fx_tokonly":   (TOKENIZE_TOK,  ("tokens",)),
}


# --------------------------------------------------------------- frozen extractor, dup as a switch

def extract_variant(text: str, dup: bool = True) -> list:
    """Identical to identifiers.extract when dup=True; emits each whole form once when dup=False.

    The regex set, the punctuation policy and the decomposition are taken verbatim from the
    frozen identifiers.py. Only the emission multiplicity changes.
    """
    whole, parts = [], []
    for pat in identifiers.RE_PATTERNS:
        for m in pat.finditer(text):
            tok = m.group(0)
            low = tok.lower().strip("-./")
            if len(low) >= 2:
                whole.append(low)
            for p in identifiers.SPLIT.split(low):
                if p:
                    parts.append(p)
            for p in identifiers.CAMEL.findall(tok):
                if len(p) > 1:
                    parts.append(p.lower())
    out = list(whole)
    if dup:
        out += list(whole)
    seen = set()
    for t in parts:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def extract_variant_str(text: str, dup: bool = True) -> str:
    return " ".join(extract_variant(text, dup=dup))


def assert_extract_parity(texts) -> int:
    """Prove extract_variant(dup=True) reproduces the frozen extractor exactly."""
    n = 0
    for t in texts:
        a = identifiers.extract(t)
        b = extract_variant(t, dup=True)
        if a != b:
            raise AssertionError(f"extract parity broken on {t[:80]!r}")
        n += 1
    return n


# --------------------------------------------------------------------------- index construction

def build_lexical_factorial(db: sqlite3.Connection, memories: list, verbose=False) -> dict:
    """Build mem table + all five FTS variants. Returns per-table row counts."""
    parity = assert_extract_parity([m["gist"] + " " + m["content"] for m in memories])

    ddl = ["drop table if exists mem2",
           "create table mem2(rowid integer primary key, uuid text, key text, cat text,"
           " gist text, content text, tok_dup text, tok_nodup text)"]
    for name, (tokz, cols) in FTS_TABLES.items():
        ddl.append(f"drop table if exists {name}")
        ddl.append(f"create virtual table {name} using fts5({', '.join(cols)},"
                   f' tokenize="{tokz}")')
    db.executescript(";\n".join(ddl) + ";")

    for i, m in enumerate(memories, start=1):
        raw = m["gist"] + " " + m["content"]
        td = extract_variant_str(raw, dup=True)
        tn = extract_variant_str(raw, dup=False)
        db.execute("insert into mem2 values (?,?,?,?,?,?,?,?)",
                   (i, m["uuid"], m["key"], m["cat"], m["gist"], m["content"], td, tn))
        db.execute("insert into fx_text(rowid, gist, content) values (?,?,?)",
                   (i, m["gist"], m["content"]))
        db.execute("insert into fx_tokchar(rowid, gist, content) values (?,?,?)",
                   (i, m["gist"], m["content"]))
        db.execute("insert into fx_tok_dup(rowid, gist, content, tokens) values (?,?,?,?)",
                   (i, m["gist"], m["content"], td))
        db.execute("insert into fx_tok_nodup(rowid, gist, content, tokens) values (?,?,?,?)",
                   (i, m["gist"], m["content"], tn))
        db.execute("insert into fx_tokonly(rowid, tokens) values (?,?)", (i, td))
    db.commit()
    counts = {t: db.execute(f"select count(*) from {t}").fetchone()[0] for t in FTS_TABLES}
    counts["extract_parity_checked"] = parity
    if verbose:
        print("[fx] " + " ".join(f"{k}={v}" for k, v in counts.items()), flush=True)
    return counts


# --------------------------------------------------------------------------- arms

def bm25_tab(db, table: str, query: str, weights, limit: int) -> list:
    """BM25 over an arbitrary FTS variant. weights must match the table's column count."""
    tokz, cols = FTS_TABLES[table]
    tokenchars = tokz != TOKENIZE_TEXT
    q = R._fts_query(query, tokenchars=tokenchars)
    assert len(weights) == len(cols), f"{table} has {len(cols)} cols, got {len(weights)} weights"
    wl = ", ".join(str(float(w)) for w in weights)
    sql = (f"select rowid, -bm25({table}, {wl}) as s from {table} "
           f"where {table} match ? order by s desc limit ?")
    try:
        return [(r, s) for r, s in db.execute(sql, (q, limit))]
    except sqlite3.OperationalError as e:
        raise RuntimeError(f"FTS query failed on {table} for {query!r}: {e}") from e


def dense_tab(db, qvec: np.ndarray, tag: str, limit: int) -> list:
    return R.dense(db, qvec, tag, limit=limit)


TIE_STATS = {"fusions": 0, "tied_adjacent_pairs": 0, "ranked_items": 0,
             "fusions_with_tie": 0, "tied_adjacent_pairs_in_top5": 0,
             "fusions_with_tie_in_top5": 0}


def rrf_counted(*rankings, k=R.RRF_K, count=True) -> list:
    """RRF, plus accounting for exact-score ties resolved by insertion order.

    A tie means two documents finished on bit-identical fused scores, so their relative order is
    decided by Python's stable sort, i.e. by which arm happened to be passed first. With
    unweighted RRF over two arms, ties are structural: a doc at rank i in arm A and a doc at rank
    i in arm B, each absent from the other arm, both score 1/(k+i).

    TWO DIFFERENT QUANTITIES, kept separate after review round-2 BLOCKER 3 caught them being
    conflated:
      * `tied_adjacent_pairs_in_top5` counts tied ADJACENT PAIRS inside the top five. A query with
        two adjacent ties contributes 2. Summed over queries and divided by the query count this
        is a mean-pairs-per-query, NOT a fraction of queries, and calling it one was the bug.
      * `fusions_with_tie_in_top5` is a per-fusion BOOLEAN: did this query have any tie inside its
        top five at all. This is the quantity the report needs, because the operational question
        is "for how many queries is an injected slot decided by insertion order".
    """
    acc = {}
    for ranking in rankings:
        for rank, (rowid, _s) in enumerate(ranking, start=1):
            acc[rowid] = acc.get(rowid, 0.0) + 1.0 / (k + rank)
    order = sorted(acc.items(), key=lambda kv: -kv[1])
    if count:
        TIE_STATS["fusions"] += 1
        TIE_STATS["ranked_items"] += len(order)
        tied = sum(1 for a, b in zip(order, order[1:]) if a[1] == b[1])
        TIE_STATS["tied_adjacent_pairs"] += tied
        TIE_STATS["fusions_with_tie"] += 1 if tied else 0
        # Adjacent pairs wholly inside the top five: positions (0,1) (1,2) (2,3) (3,4).
        t5 = sum(1 for a, b in zip(order[:5], order[1:5]) if a[1] == b[1])
        TIE_STATS["tied_adjacent_pairs_in_top5"] += t5
        TIE_STATS["fusions_with_tie_in_top5"] += 1 if t5 else 0
    return order


def rrf_tiebreak(rankings: list, k=R.RRF_K, tiebreak: str = "insertion") -> list:
    """RRF with an EXPLICIT, declared tie-handling rule. Exploratory diagnostic only (R3.5).

    `rankings` is a list of (name, ranking) pairs, in the order they are fused. Fused scores are
    identical to `rrf_counted` for the same arms in the same order; only the resolution of exact
    ties differs.

      insertion  Python's stable sort on -score. Ties keep first-seen order, i.e. the order of
                 `rankings`. This is what the deployed code does, and it is what makes arm order
                 matter.
      by:<name>  ties broken by the named arm's own rank (better rank wins); documents absent
                 from that arm sort last within the tie group. A deterministic, declared rule
                 that does not depend on which arm was passed first.
    """
    acc, seen = {}, {}
    for i, (name, ranking) in enumerate(rankings):
        for rank, (rowid, _s) in enumerate(ranking, start=1):
            acc[rowid] = acc.get(rowid, 0.0) + 1.0 / (k + rank)
            seen.setdefault(rowid, {})[name] = rank
    if tiebreak == "insertion":
        return sorted(acc.items(), key=lambda kv: -kv[1])
    if not tiebreak.startswith("by:"):
        raise ValueError(f"unknown tiebreak {tiebreak!r}")
    arm = tiebreak[3:]
    if arm not in {n for n, _ in rankings}:
        raise ValueError(f"tiebreak arm {arm!r} not among {[n for n, _ in rankings]}")
    BIG = 10 ** 9
    return sorted(acc.items(), key=lambda kv: (-kv[1], seen[kv[0]].get(arm, BIG)))


def reset_ties():
    for key in TIE_STATS:
        TIE_STATS[key] = 0


def tie_report() -> dict:
    """Tie accounting. Key names say exactly which quantity each one is (review r2 BLOCKER 3)."""
    t = dict(TIE_STATS)
    f = t["fusions"]
    t["mean_tied_adjacent_pairs_per_query"] = round(t["tied_adjacent_pairs"] / f, 3) if f else None
    t["frac_queries_with_any_tie"] = round(t["fusions_with_tie"] / f, 4) if f else None
    # The per-query BOOLEAN. This is the operationally meaningful one.
    t["frac_queries_with_any_tie_inside_top5"] = (
        round(t["fusions_with_tie_in_top5"] / f, 4) if f else None)
    # The mean PAIR COUNT inside the top five. Round 2 divided this by the query count and
    # mislabelled the result as a fraction of queries.
    t["mean_tied_adjacent_pairs_in_top5_per_query"] = (
        round(t["tied_adjacent_pairs_in_top5"] / f, 4) if f else None)
    return t


# --------------------------------------------------------------------------- index size accounting

def table_bytes(db, name: str) -> int:
    """Bytes occupied by every shadow table of an FTS5 virtual table (or a plain table)."""
    try:
        rows = db.execute(
            "select sum(pgsize) from dbstat where name = ? or name like ? escape '\\'",
            (name, name.replace("_", "\\_") + "\\_%")).fetchone()
        return int(rows[0] or 0)
    except sqlite3.OperationalError:
        return -1
