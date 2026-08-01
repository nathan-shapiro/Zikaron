#!/usr/bin/env python
"""Sweep driver. Builds indexes, runs every configuration, writes results/sweep.json.

Usage:
  .venv/bin/python sweep.py                 # everything
  .venv/bin/python sweep.py --only 4p 6     # named configs only (indexes still built as needed)

METRIC DEFINITIONS (stated here so the report and the code cannot drift apart):

  recall@5      For each query, |gold retrieved in top 5| / |gold|. Every query in this
                dataset has exactly one gold, so this is also success@5 / hit-rate@5.
  precision@5   |gold retrieved in top 5| / 5. With one gold per query the CEILING IS 0.200.
                Reported because the brief asks for it, but recall@5 is the informative one.
  MRR@10        Mean of 1/rank of the first gold within the top 10, else 0.
  hnd           Hard-negative displacement rate: fraction of queries WITH a hard negative
                where at least one hard negative outranks the gold. This is the headline for
                category 1. Lower is better. It is computed over the FULL ranking, not the
                top 5, so a query whose gold is at 40 and hard negative at 39 still counts as
                displaced - that is deliberate, it measures the ranker's ordering preference
                rather than being confounded with recall.
  hnd_top5      Stricter and more operational: fraction where a hard negative appears in the
                top 5 AND outranks the gold. This is what the user actually sees under D12.

Determinism: no sampling anywhere; fastembed ONNX inference is deterministic on fixed input;
SEED is set for numpy only to make any future sampling reproducible.
"""
import argparse
import json
import pathlib
import statistics
import sys
import time
from collections import defaultdict

import numpy as np

import retrieval as R

SEED = 20260731
np.random.seed(SEED)

HERE = pathlib.Path(__file__).parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

# --------------------------------------------------------------------------- configs
# Each config is (name, description, callable(db, query_text, qvecs) -> ranking)
# qvecs is a dict tag -> query vector, precomputed once per query for all models.

CONFIGS = [
    ("1_bm25", "BM25 alone (FTS5, gist+content)"),
    ("2_small_noprefix", "bge-small dense alone, NO prefix (incumbent's exact behaviour)"),
    ("3_small_prefix", "bge-small dense alone, WITH BGE query prefix"),
    ("4_rrf_small_noprefix", "RRF(BM25, bge-small no-prefix) - incumbent as built"),
    ("4p_rrf_small_prefix", "RRF(BM25, bge-small with prefix) - incumbent as documented"),
    ("5_rrf_tokens_small", "RRF(BM25 over +tokens column w=3, bge-small prefix)"),
    ("6_rrf_bm25_large", "RRF(BM25, bge-large prefix) - the scale-only control"),
    ("7_rrf_bm25_nomic", "RRF(BM25, nomic-embed-text-v1.5) - tokenizer/context change"),
    ("8_best_plus_reranker", "best RRF config + bge-reranker-base over top 50"),
]

DENSE_TAGS = ["bge-small", "bge-small-prefix", "bge-large-prefix", "nomic"]


def rank_for(cfg: str, db, qtext: str, qvecs: dict) -> list:
    if cfg == "1_bm25":
        return R.bm25(db, qtext)
    if cfg == "2_small_noprefix":
        return R.dense(db, qvecs["bge-small"], "bge-small")
    if cfg == "3_small_prefix":
        return R.dense(db, qvecs["bge-small-prefix"], "bge-small-prefix")
    if cfg == "4_rrf_small_noprefix":
        return R.rrf(R.bm25(db, qtext), R.dense(db, qvecs["bge-small"], "bge-small"))
    if cfg == "4p_rrf_small_prefix":
        return R.rrf(R.bm25(db, qtext),
                     R.dense(db, qvecs["bge-small-prefix"], "bge-small-prefix"))
    if cfg == "5_rrf_tokens_small":
        return R.rrf(R.bm25(db, qtext, use_tokens=True),
                     R.dense(db, qvecs["bge-small-prefix"], "bge-small-prefix"))
    if cfg == "6_rrf_bm25_large":
        return R.rrf(R.bm25(db, qtext),
                     R.dense(db, qvecs["bge-large-prefix"], "bge-large-prefix"))
    if cfg == "7_rrf_bm25_nomic":
        return R.rrf(R.bm25(db, qtext), R.dense(db, qvecs["nomic"], "nomic"))
    raise KeyError(cfg)


# --------------------------------------------------------------------------- metrics

def evaluate(rankings: dict, doc: dict) -> dict:
    """rankings: qid -> [rowid,...] best-first. Returns metrics overall and per category."""
    by_uuid_row = {}
    per_q = {}
    for q in doc["queries"]:
        order = rankings[q["qid"]]
        gold_rows = {ROW_OF[u] for u in q["gold"]}
        hn_rows = {ROW_OF[u] for u in q["hard_neg"]}
        top5, top10 = order[:5], order[:10]
        rec5 = len(gold_rows & set(top5)) / len(gold_rows)
        prec5 = len(gold_rows & set(top5)) / 5.0
        mrr = 0.0
        for i, r in enumerate(top10, start=1):
            if r in gold_rows:
                mrr = 1.0 / i
                break
        pos = {r: i for i, r in enumerate(order)}
        gold_pos = min((pos[r] for r in gold_rows if r in pos), default=10**6)
        hn_pos = min((pos[r] for r in hn_rows if r in pos), default=10**6)
        displaced = bool(hn_rows) and hn_pos < gold_pos
        displaced5 = displaced and hn_pos < 5
        per_q[q["qid"]] = dict(cat=q["cat"], rec5=rec5, prec5=prec5, mrr=mrr,
                               gold_rank=gold_pos + 1 if gold_pos < 10**6 else None,
                               hn_rank=hn_pos + 1 if hn_pos < 10**6 else None,
                               has_hn=bool(hn_rows), displaced=displaced,
                               displaced5=displaced5)

    def agg(rows):
        hn = [r for r in rows if r["has_hn"]]
        return dict(
            n=len(rows),
            recall_at_5=round(statistics.mean(r["rec5"] for r in rows), 4),
            precision_at_5=round(statistics.mean(r["prec5"] for r in rows), 4),
            mrr_at_10=round(statistics.mean(r["mrr"] for r in rows), 4),
            n_with_hn=len(hn),
            hnd=round(statistics.mean(r["displaced"] for r in hn), 4) if hn else None,
            hnd_top5=round(statistics.mean(r["displaced5"] for r in hn), 4) if hn else None,
        )

    rows = list(per_q.values())
    out = {"ALL": agg(rows)}
    per_cat = defaultdict(list)
    for r in rows:
        per_cat[r["cat"]].append(r)
    for c, rs in per_cat.items():
        out[c] = agg(rs)
    return dict(summary=out, per_query=per_q)


# --------------------------------------------------------------------------- main

ROW_OF = {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--embed-mode", default="gist_content",
                    choices=["gist_content", "gist_only", "content_only"])
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    doc = R.load_dataset()
    mems = doc["memories"]
    global ROW_OF
    ROW_OF = {m["uuid"]: i for i, m in enumerate(mems, start=1)}

    db = R.connect()
    t0 = time.perf_counter()
    R.build_lexical(db, mems)
    print(f"[index] lexical built in {time.perf_counter()-t0:.1f}s", flush=True)

    from fastembed import TextEmbedding
    embedders, qvecs = {}, defaultdict(dict)
    build_times = {}
    for tag in DENSE_TAGS:
        model, qpre, ppre = R.MODELS[tag]
        t0 = time.perf_counter()
        emb = TextEmbedding(model_name=model)
        dim = len(next(iter(emb.embed(["dimension probe"]))))
        embedders[tag] = (emb, qpre, ppre, dim)
        R.build_dense(db, mems, tag, emb, ppre, dim, mode=args.embed_mode)
        build_times[tag] = round(time.perf_counter() - t0, 1)
        print(f"[index] dense {tag} ({model}, dim {dim}) in {build_times[tag]}s", flush=True)

    # Precompute query vectors once per model.
    for tag, (emb, qpre, _ppre, _dim) in embedders.items():
        texts = [qpre + q["text"] for q in doc["queries"]]
        vs = np.array(list(emb.embed(texts)), dtype=np.float32)
        vs /= np.linalg.norm(vs, axis=1, keepdims=True)
        for q, v in zip(doc["queries"], vs):
            qvecs[q["qid"]][tag] = v

    names = [c[0] for c in CONFIGS]
    if args.only:
        names = [n for n in names if any(n.startswith(o) or o == n for o in args.only)]

    all_results = {}
    stored_rankings = {}
    for name in names:
        if name == "8_best_plus_reranker":
            continue
        t0 = time.perf_counter()
        rk = {}
        for q in doc["queries"]:
            rk[q["qid"]] = [r for r, _ in rank_for(name, db, q["text"], qvecs[q["qid"]])]
        elapsed = time.perf_counter() - t0
        res = evaluate(rk, doc)
        res["wall_seconds_all_queries"] = round(elapsed, 3)
        res["description"] = dict(CONFIGS)[name]
        all_results[name] = res
        stored_rankings[name] = rk
        s = res["summary"]
        print(f"{name:24} R@5={s['ALL']['recall_at_5']:.3f} MRR@10={s['ALL']['mrr_at_10']:.3f} "
              f"hnd={s['ALL']['hnd']} nm_hnd={s['near_miss']['hnd']}", flush=True)

    # ---- config 8: reranker over the best RRF config's top FUSE_DEPTH
    if not args.only or any(o.startswith("8") for o in args.only):
        rrf_names = [n for n in stored_rankings if n.startswith(("4", "5", "6", "7"))]
        if rrf_names:
            best = max(rrf_names,
                       key=lambda n: (all_results[n]["summary"]["ALL"]["recall_at_5"],
                                      all_results[n]["summary"]["ALL"]["mrr_at_10"]))
            print(f"[rerank] best first-stage = {best}", flush=True)
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            ce = TextCrossEncoder(model_name="BAAI/bge-reranker-base")
            texts = {i: R.doc_text(m, args.embed_mode) for i, m in enumerate(mems, start=1)}
            rk, t0 = {}, time.perf_counter()
            for q in doc["queries"]:
                cand = stored_rankings[best][q["qid"]][:R.FUSE_DEPTH]
                scores = list(ce.rerank(q["text"], [texts[r] for r in cand]))
                order = [r for _, r in sorted(zip(scores, cand), key=lambda p: -p[0])]
                rk[q["qid"]] = order + [r for r in stored_rankings[best][q["qid"]]
                                        if r not in set(cand)]
            elapsed = time.perf_counter() - t0
            res = evaluate(rk, doc)
            res["wall_seconds_all_queries"] = round(elapsed, 3)
            res["description"] = (f"{dict(CONFIGS)['8_best_plus_reranker']} "
                                  f"(first stage = {best})")
            res["first_stage"] = best
            all_results["8_best_plus_reranker"] = res
            s = res["summary"]
            print(f"{'8_best_plus_reranker':24} R@5={s['ALL']['recall_at_5']:.3f} "
                  f"MRR@10={s['ALL']['mrr_at_10']:.3f} hnd={s['ALL']['hnd']} "
                  f"nm_hnd={s['near_miss']['hnd']}", flush=True)

    out = pathlib.Path(args.out) if args.out else RESULTS / f"sweep_{args.embed_mode}.json"
    out.write_text(json.dumps(dict(
        seed=SEED, rrf_k=R.RRF_K, fuse_depth=R.FUSE_DEPTH, embed_mode=args.embed_mode,
        n_memories=len(mems), n_queries=len(doc["queries"]),
        index_build_seconds=build_times, configs=all_results), indent=2) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
