"""M19 spike C: which quantity orders the groups, on a real three-KB corpus.

Consumer: design/knowledge-index.md §7.2, which orders groups by **best dense cosine** and records
(§16 open question 2) that this is blind to a group whose top result is a pure lexical hit -- the
code-knowledge case. The alternative it names but does not adopt is **best fused contribution**.
This is a code-shape question rather than a parameter question: the fusion parameters are `meta`
keys and can be swept later, but which quantity orders the groups is a branch in the ranking path.

    .venv/bin/python spikes/spike_group_ordering.py

Three real corpora, mechanically-generated queries, mechanical ground truth. Dense scoring is exact
cosine in numpy rather than through `vec0` -- vec0 brute-forces, so the ordering is identical and
the storage layer is not what is under test here. The lexical arm is real FTS5 with real `bm25()`.
No product code is imported; `lexical_query`'s OR-of-quoted-terms construction is reimplemented
below and cross-checked against `zikaron/core/retrieval/query.py` by eye.
"""

import math
import os
import random
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict

import numpy as np
from fastembed import TextEmbedding

MODEL = "BAAI/bge-small-en-v1.5"  # D20
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # config default
RRF_K, FUSION_DEPTH = 60, 50  # config defaults
GROUP_SIZE, PER_FILE_CAP = 5, 2  # §7.3
CHUNK_WORDS = 350  # spike-grade stand-in for §4.3's token budget
CHUNK_CAP_PER_KB = 600
MAX_TERMS = 32
SEED = 19

AMAZONQ = os.path.expanduser("~/amazon-q-developer-cli")


# ======================================================================================
# Corpora
# ======================================================================================
def files_under(root: str, suffixes: tuple[str, ...], skip: tuple[str, ...] = ()) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("target", "__pycache__")]
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            if fn.endswith(suffixes) and not any(s in p for s in skip):
                out.append(p)
    return sorted(out)


CORPORA = {
    "zikaron_code": files_under("zikaron", (".py",)),
    "amazonq_code": files_under(os.path.join(AMAZONQ, "crates/chat-cli/src"), (".rs",)),
    "amazonq_docs": files_under(os.path.join(AMAZONQ, "docs"), (".md",))
    + files_under(AMAZONQ, (".md",), skip=("crates/", "docs/")),
}
for name, paths in CORPORA.items():
    if not paths:
        print(f"corpus {name} is empty -- is {AMAZONQ} present?", file=sys.stderr)
        raise SystemExit(2)


def chunk_file(path: str, root: str) -> list[tuple[str, str]]:
    try:
        text = open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, OSError):
        return []
    rel = os.path.relpath(path, root)
    out, buf, count = [], [], 0
    for line in text.splitlines():
        buf.append(line)
        count += len(line.split())
        if count >= CHUNK_WORDS:
            out.append((rel, "\n".join(buf)))
            buf, count = [], 0
    if buf and any(line.strip() for line in buf):
        out.append((rel, "\n".join(buf)))
    return out


rng = random.Random(SEED)
kbs: dict[str, list[tuple[str, str]]] = {}
for name, paths in CORPORA.items():
    root = "zikaron" if name == "zikaron_code" else AMAZONQ
    chunks: list[tuple[str, str]] = []
    for p in paths:
        chunks.extend(chunk_file(p, root))
        if len(chunks) >= CHUNK_CAP_PER_KB:
            break
    kbs[name] = chunks[:CHUNK_CAP_PER_KB]

print(f"model {MODEL}, seed {SEED}")
for name, chunks in kbs.items():
    files = len({p for p, _ in chunks})
    words = sum(len(t.split()) for _, t in chunks)
    print(f"  {name:<14} {len(chunks):>4} chunks from {files:>3} files, {words:>7,} words")

# ======================================================================================
# Index: FTS5 per KB, dense vectors in memory
# ======================================================================================
CACHE = "/tmp/zk-spike-c-embeddings.npz"
print("\nembedding (bge-small, CPU) …", end="", flush=True)
embedder = TextEmbedding(MODEL)
cached = {}
if os.path.exists(CACHE):
    loaded = np.load(CACHE)
    if all(f"{n}" in loaded and loaded[n].shape[0] == len(kbs[n]) for n in kbs):
        cached = {n: loaded[n] for n in kbs}
        print(" (document vectors from cache)", end="")
dense: dict[str, np.ndarray] = {}
conns: dict[str, sqlite3.Connection] = {}
for name, chunks in kbs.items():
    # K6: the path prefix is prepended AT EMBED TIME and never stored.
    docs = [f"{path}\n\n{text}" for path, text in chunks]
    dense[name] = cached.get(name)
    if dense[name] is None:
        dense[name] = np.array(list(embedder.embed(docs)), dtype=np.float32)
        dense[name] /= np.linalg.norm(dense[name], axis=1, keepdims=True)
    c = sqlite3.connect(":memory:")
    c.execute("CREATE VIRTUAL TABLE fts USING fts5(path, text)")
    c.executemany(
        "INSERT INTO fts(rowid, path, text) VALUES (?,?,?)",
        [(i, p, t) for i, (p, t) in enumerate(chunks)],
    )
    conns[name] = c
    print(".", end="", flush=True)
if not cached:
    np.savez(CACHE, **dense)
print(" done")

QUERY_VECTORS: dict[str, np.ndarray] = {}


def query_vector(query: str) -> np.ndarray:
    if query not in QUERY_VECTORS:
        v = np.array(list(embedder.embed([QUERY_PREFIX + query]))[0], dtype=np.float32)
        QUERY_VECTORS[query] = v / np.linalg.norm(v)
    return QUERY_VECTORS[query]


# ======================================================================================
# Query construction -- mirrors zikaron/core/retrieval/query.py
# ======================================================================================
def lexical_expression(text: str) -> str | None:
    runs = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    seen: dict[str, int] = {}
    for i, run in enumerate(runs):
        seen.setdefault(run, i)
    ranked = sorted(seen.items(), key=lambda kv: (-len(kv[0]), kv[1]))[:MAX_TERMS]
    terms = [t for t, _ in ranked]
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms) if terms else None


def arms(kb: str, query: str) -> tuple[dict[int, int], dict[int, int], dict[int, float]]:
    """(dense ranks, lexical ranks, cosine by chunk id) for one KB, both arms cut to FUSION_DEPTH."""
    sims = dense[kb] @ query_vector(query)
    order = np.argsort(-sims)[:FUSION_DEPTH]
    dense_ranks = {int(i): r + 1 for r, i in enumerate(order)}
    cosines = {int(i): float(sims[i]) for i in order}
    lex_ranks: dict[int, int] = {}
    expr = lexical_expression(query)
    if expr:
        rows = conns[kb].execute(
            "SELECT rowid FROM fts WHERE fts MATCH ? ORDER BY bm25(fts) LIMIT ?",
            (expr, FUSION_DEPTH),
        ).fetchall()
        lex_ranks = {int(r[0]): i + 1 for i, r in enumerate(rows)}
    return dense_ranks, lex_ranks, cosines


def group_for(kb: str, query: str):
    """The KB's group: fused top chunks under §7.3's per-file cap, with both ordering signals."""
    dense_ranks, lex_ranks, cosines = arms(kb, query)
    fused = {
        cid: sum(1.0 / (RRF_K + r) for r in (dense_ranks.get(cid), lex_ranks.get(cid)) if r)
        for cid in set(dense_ranks) | set(lex_ranks)
    }
    per_file: Counter[str] = Counter()
    group = []
    for cid, score in sorted(fused.items(), key=lambda kv: -kv[1]):
        path = kbs[kb][cid][0]
        if per_file[path] >= PER_FILE_CAP:
            continue
        per_file[path] += 1
        group.append((cid, score, cosines.get(cid), cid in lex_ranks, cid in dense_ranks))
        if len(group) == GROUP_SIZE:
            break
    if not group:
        return None
    dense_found = [c for _, _, c, _, _ in group if c is not None]
    best_cosine = max(dense_found, default=-1.0)
    lexical_only_top = group[0][2] is None
    return {
        "kb": kb,
        "cosine": best_cosine,
        "fused": max(s for _, s, _, _, _ in group),
        "lexical_only_top": lexical_only_top,
        "top_path": kbs[kb][group[0][0]][0],
        "both_arms_top": group[0][3] and group[0][4],
        "had_lexical": bool(lex_ranks),
        # A group with NO dense-found member is the only shape whose ordering key §8.3's explicit
        # `chunks_vec` lookup could change: a lexical-only chunk sits outside the dense top-`depth`,
        # so its cosine cannot exceed any dense-found member's. Counted rather than assumed.
        "no_dense_member": not dense_found,
    }


# ======================================================================================
# Query sets -- mechanically generated, mechanical ground truth
# ======================================================================================
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{7,}")
occurrences: dict[str, Counter[str]] = {name: Counter() for name in kbs}
for name, chunks in kbs.items():
    for _, text in chunks:
        occurrences[name].update(IDENT.findall(text))

unique_to: dict[str, list[str]] = defaultdict(list)
for name, counts in occurrences.items():
    others = [o for o in kbs if o != name]
    for token, n in counts.items():
        if n >= 3 and all(occurrences[o][token] == 0 for o in others):
            unique_to[name].append(token)

identifier_queries = []
for name in kbs:
    pool = sorted(unique_to[name])
    identifier_queries += [(t, name) for t in rng.sample(pool, min(8, len(pool)))]

SENTENCE = re.compile(r"(?<=[.!?])\s+")
unique_any = {t for name in kbs for t in unique_to[name]}
prose_queries = []
for name, chunks in kbs.items():
    pool = []
    for _, text in chunks:
        for sentence in SENTENCE.split(re.sub(r"\s+", " ", text)):
            words = sentence.split()
            if 12 <= len(words) <= 35 and sum(c.isalpha() for c in sentence) > 0.6 * len(sentence):
                # Mask every token unique to this KB: the lexical giveaway is removed on purpose.
                masked = " ".join(w for w in words if not any(t in w for t in unique_any))
                if len(masked.split()) >= 10:
                    pool.append(masked)
    prose_queries += [(q, name) for q in rng.sample(pool, min(8, len(pool)))]

wrapped_queries = [(f"what does {t} do and where is it used", kb) for t, kb in identifier_queries]

FAMILIES = {
    "identifier (bare)": identifier_queries,
    "identifier (in prose)": wrapped_queries,
    "prose (unique tokens masked)": prose_queries,
}
for label, qs in FAMILIES.items():
    print(f"  {label:<30} {len(qs)} queries")


# ======================================================================================
# Run
# ======================================================================================
ORDERINGS = {
    "cosine": lambda g: (-g["cosine"],),
    "fused": lambda g: (-g["fused"],),
    "fused+cosine": lambda g: (-g["fused"], -g["cosine"]),  # fused, ties broken by cosine
}


def rank_of(truth: str, groups: list[dict], ordering: str) -> int:
    ordered = sorted(groups, key=ORDERINGS[ordering])
    return next(i + 1 for i, g in enumerate(ordered) if g["kb"] == truth)


def mcnemar(rows: list[dict], a: str, b: str) -> str:
    """Paired comparison of two orderings' top-1 hits: discordant counts and an exact p."""
    only_a = sum(r[f"rank:{a}"] == 1 and r[f"rank:{b}"] != 1 for r in rows)
    only_b = sum(r[f"rank:{b}"] == 1 and r[f"rank:{a}"] != 1 for r in rows)
    n = only_a + only_b
    k = min(only_a, only_b)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n) if n else 1.0
    return f"{a} only {only_a}, {b} only {only_b}, {n} discordant, two-sided exact p={p:.3f}"


def ties_at_top(groups: list[dict], key: str) -> int:
    best = max(g[key] for g in groups)
    return sum(1 for g in groups if g[key] == best)


def evaluate(depth: int) -> dict[str, list[dict]]:
    """Run every family at one `fusion_depth`, returning the per-family rows."""
    global FUSION_DEPTH
    FUSION_DEPTH = depth
    out = {}
    for label, queries in FAMILIES.items():
        rows = []
        for query, truth in queries:
            groups = [g for g in (group_for(kb, query) for kb in kbs) if g]
            if not groups:
                continue
            rows.append(
                {
                    "truth": truth,
                    **{f"rank:{o}": rank_of(truth, groups, o) for o in ORDERINGS},
                    "lex_only": next(g["lexical_only_top"] for g in groups if g["kb"] == truth),
                    "any_lex_only": sum(g["lexical_only_top"] for g in groups),
                    "no_dense": sum(g["no_dense_member"] for g in groups),
                    "fused_ties": ties_at_top(groups, "fused"),
                    "cos_ties": ties_at_top(groups, "cosine"),
                }
            )
        out[label] = rows
    return out


print("\n" + "=" * 92)
print("Sensitivity to `fusion_depth`, which is what controls how deep the lexical arm can reach")
print("past the dense arm. These KBs are 41-494 chunks; §16 estimates a real KB at ~22,800, where")
print("depth 50 is 0.2% of the corpus rather than 11%. Lower depths approximate that ratio.\n")
print(f"  {'depth':>5}  {'cosine':>6}  {'fused':>6}  {'f+cos':>6}  {'true-KB lex-only':>16}  "
      f"{'any-KB lex-only':>15}  {'fused ties':>10}  {'cos ties':>8}  {'0-dense groups':>14}")
for depth in (50, 20, 10, 5, 3):
    rows = [r for fam in evaluate(depth).values() for r in fam]
    print(
        f"  {depth:>5}  {sum(r['rank:cosine'] == 1 for r in rows) / len(rows):>6.2f}"
        f"  {sum(r['rank:fused'] == 1 for r in rows) / len(rows):>6.2f}"
        f"  {sum(r['rank:fused+cosine'] == 1 for r in rows) / len(rows):>6.2f}"
        f"  {sum(r['lex_only'] for r in rows):>11}/{len(rows):<4}"
        f"  {sum(r['any_lex_only'] for r in rows):>9}/{len(rows) * 3:<5}"
        f"  {sum(r['fused_ties'] > 1 for r in rows):>6}/{len(rows):<3}"
        f"  {sum(r['cos_ties'] > 1 for r in rows):>4}/{len(rows):<3}"
        f"  {sum(r['no_dense'] for r in rows):>9}/{len(rows) * 3:<4}"
    )
FUSION_DEPTH = 50

print("\n" + "=" * 92)
summary = {}
for label, queries in FAMILIES.items():
    rows = []
    for query, truth in queries:
        groups = [g for g in (group_for(kb, query) for kb in kbs) if g]
        if not groups:
            continue
        rows.append(
            {
                "query": query,
                "truth": truth,
                **{f"rank:{o}": rank_of(truth, groups, o) for o in ORDERINGS},
                "fused_ties": ties_at_top(groups, "fused"),
                "cos_ties": ties_at_top(groups, "cosine"),
                "fused_levels": len({round(g["fused"], 9) for g in groups}),
                "fused_spread": max(g["fused"] for g in groups) - min(g["fused"] for g in groups),
                "cos_spread": max(g["cosine"] for g in groups) - min(g["cosine"] for g in groups),
                "lex_only": next(g["lexical_only_top"] for g in groups if g["kb"] == truth),
                "both_arms": next(g["both_arms_top"] for g in groups if g["kb"] == truth),
                "groups_both_arms": sum(g["both_arms_top"] for g in groups),
                "groups_with_lexical": sum(g["had_lexical"] for g in groups),
                "n_groups": len(groups),
            }
        )
    summary[label] = rows
    print(f"\n{label}   n={len(rows)}")
    for o in ORDERINGS:
        top1 = sum(r[f"rank:{o}"] == 1 for r in rows) / len(rows)
        mrr = statistics.mean(1 / r[f"rank:{o}"] for r in rows)
        print(f"  ordering by {o:<13} top-1 {top1:.2f}   MRR {mrr:.3f}")
    print(
        f"  ties at the top: fused {sum(r['fused_ties'] > 1 for r in rows)}/{len(rows)} queries,"
        f"  cosine {sum(r['cos_ties'] > 1 for r in rows)}/{len(rows)}"
    )
    print(
        f"  distinct fused values across {rows[0]['n_groups']} groups: "
        f"median {statistics.median(r['fused_levels'] for r in rows):.0f};"
        f"  median spread  fused {statistics.median(r['fused_spread'] for r in rows):.5f}"
        f"  cosine {statistics.median(r['cos_spread'] for r in rows):.5f}"
    )
    print(
        f"  true KB's top chunk was lexical-only: {sum(r['lex_only'] for r in rows)}/{len(rows)};"
        f"  found by BOTH arms: {sum(r['both_arms'] for r in rows)}/{len(rows)}"
    )
    print(
        f"  SATURATION: of {rows[0]['n_groups']} groups per query, a median of "
        f"{statistics.median(r['groups_both_arms'] for r in rows):.0f} had a top chunk found by BOTH"
        f" arms, and {statistics.median(r['groups_with_lexical'] for r in rows):.0f} had any lexical"
        " match at all"
    )
    print(f"  PAIRED: {mcnemar(rows, 'cosine', 'fused')}")
    flips = [r for r in rows if (r["rank:cosine"] == 1) != (r["rank:fused"] == 1)]
    for r in flips[:6]:
        direction = "FUSED wins " if r["rank:fused"] == 1 else "COSINE wins"
        print(
            f"    {direction}: truth={r['truth']:<13} cos={r['rank:cosine']} fused={r['rank:fused']}"
            f" fused+cos={r['rank:fused+cosine']}  {r['query'][:52]!r}"
        )
    if len(flips) > 6:
        print(f"    … {len(flips) - 6} more disagreements")

print("\n" + "=" * 92)
print("Aggregate over all families:")
allrows = [r for rows in summary.values() for r in rows]
print(f"  n={len(allrows)}")
for o in ORDERINGS:
    top1 = sum(r[f"rank:{o}"] == 1 for r in allrows) / len(allrows)
    mrr = statistics.mean(1 / r[f"rank:{o}"] for r in allrows)
    print(f"    {o:<13} top-1 {top1:.2f}   MRR {mrr:.3f}")
print(f"  PAIRED: {mcnemar(allrows, 'cosine', 'fused')}")
print(f"  PAIRED: {mcnemar(allrows, 'cosine', 'fused+cosine')}")
print(
    f"  the mechanism §7.2 names — the true KB's best chunk being a LEXICAL-ONLY hit — occurred"
    f" {sum(r['lex_only'] for r in allrows)}/{len(allrows)} times"
)
