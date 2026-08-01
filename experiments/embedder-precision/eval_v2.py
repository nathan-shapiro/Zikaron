#!/usr/bin/env python
"""Round-2 evaluation driver.

Runs 18 configurations over TWO query sets and TWO ranking depths, scores them with the graded
relevance labels from `stubs_v2.json`, and computes the paired cluster-bootstrap contrasts that
`PREREGISTRATION.md` section 5 declared in advance.

Query sets
  blind  `queries_blind.json`  192 prompts / 64 stubs, authored without reading the memories.
                               THE PRIMARY SET. Every decision comes from here.
  dev    `dataset.json`        the 64 v1 queries, same author as the memories. DEVELOPMENT ONLY.
                               Scored against the same graded labels, so the dev-vs-blind
                               difference is the **v1-development versus v2-blind query-set gap**.
                               That gap is DESCRIPTIVE (PREREGISTRATION-R3.md R3.3): the two sets
                               differ in author AND in register, length, detail and deliberate
                               underspecification, so it does NOT isolate an authorship effect and
                               supports no decision.

Depths
  50   the operational pipeline (round-1's FUSE_DEPTH). top-5 metrics from here.
  187  the whole corpus. The ONLY depth at which a full-ranking displacement claim is legitimate
       (review MAJOR 13). RRF scores depend on depth, so both are run rather than assumed equal.

Configuration families
  L_*  lexical only - the factorial ablation of BLOCKER 5, with no dense arm to confound it
  D_*  dense only   - includes bge-large and nomic, which round 1 never tested unfused (MAJOR 8)
  H_*  hybrid RRF   - the deployable shapes

Usage
  .venv/bin/python eval_v2.py                    # everything -> results/eval_v2.json
  .venv/bin/python eval_v2.py --sets blind       # skip the dev set
  .venv/bin/python eval_v2.py --depths 50
"""
import argparse
import json
import pathlib
import sys
import time
from collections import defaultdict

import numpy as np

import evalkit as EK
import retrieval as R
import retrieval2 as R2
from embcache import EmbedCache

HERE = pathlib.Path(__file__).parent
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)
DB_PATH = HERE / "index_v2.db"

DENSE_TAGS = ["bge-small", "bge-small-prefix", "bge-large-prefix", "nomic"]

# name -> (family, description). The planned set; PREREGISTRATION section 7 forbids adding
# unplanned contrasts without labelling them exploratory.
CONFIGS = [
    # ---- lexical factorial: the four things round-1 config 5 changed, separated
    ("L_A_unicode61",     "L", "BM25 (gist,content) unicode61 - baseline tokenizer"),
    ("L_B_tokchar",       "L", "BM25 (gist,content) tokenchars '_-./' - TOKENIZER ONLY"),
    ("L_C_tok_w0",        "L", "BM25 (gist,content,tokens_dup) tokenchars, tokens weight 0"),
    ("L_D_tok_w1",        "L", "BM25 (gist,content,tokens_dup) tokenchars, tokens weight 1"),
    ("L_E_tok_w3",        "L", "BM25 (gist,content,tokens_dup) tokenchars, tokens weight 3"),
    ("L_F_tok_w3_nodup",  "L", "as L_E but whole tokens emitted ONCE - no TF boost"),
    ("L_G_split",         "L", "COMPOSITE: RRF(BM25 unicode61 gist+content, BM25 tokenchars "
                               "tokens-only) - adds tokens index + a second arm + RRF at once"),
    # ---- dense only
    ("D_small_noprefix",  "D", "bge-small dense alone, no prefix"),
    ("D_small_prefix",    "D", "bge-small dense alone, BGE query prefix"),
    ("D_large_prefix",    "D", "bge-large dense alone, BGE query prefix - MAJOR 8 control"),
    ("D_nomic",           "D", "nomic-embed-text-v1.5 dense alone - MAJOR 8 control"),
    # ---- hybrids
    ("H_small_noprefix",  "H", "RRF(L_A, bge-small no prefix) - round-1 config 4"),
    ("H_small_prefix",    "H", "RRF(L_A, bge-small prefix) - round-1 config 4p, the baseline"),
    ("H_tokchar_notok",   "H", "RRF(L_B, bge-small prefix) - tokenizer change only, in hybrid"),
    ("H_tok_w3",          "H", "RRF(L_E, bge-small prefix) - round-1 config 5"),
    ("H_tok_w3_nodup",    "H", "RRF(L_F, bge-small prefix) - config 5 minus the TF boost"),
    ("H_large",           "H", "RRF(L_A, bge-large prefix) - round-1 config 6"),
    ("H_nomic",           "H", "RRF(L_A, nomic) - round-1 config 7"),
]

# Declared contrasts: (name, arm_a, arm_b, what it isolates)
CONTRASTS = [
    ("prefix_dense",       "D_small_prefix", "D_small_noprefix", "BGE query prefix, dense alone"),
    ("prefix_hybrid",      "H_small_prefix", "H_small_noprefix", "BGE query prefix, in hybrid"),
    ("large_vs_small_dense", "D_large_prefix", "D_small_prefix", "capacity, dense-only (MAJOR 8)"),
    ("nomic_vs_small_dense", "D_nomic", "D_small_prefix", "nomic, dense-only (MAJOR 8)"),
    ("large_vs_small_hybrid", "H_large", "H_small_prefix", "capacity, deployed pipeline"),
    ("nomic_vs_small_hybrid", "H_nomic", "H_small_prefix", "nomic, deployed pipeline"),
    ("tokenizer_only",     "L_B_tokchar", "L_A_unicode61", "tokenchars alone, no tokens field"),
    ("tokens_w0_vs_tokenizer", "L_C_tok_w0", "L_B_tokchar", "field present at weight 0"),
    ("tokens_w1_vs_tokenizer", "L_D_tok_w1", "L_B_tokchar", "field at weight 1"),
    ("tokens_w3_vs_tokenizer", "L_E_tok_w3", "L_B_tokchar", "ISOLATED tokens effect (BLOCKER 5)"),
    ("dup_emission",       "L_E_tok_w3", "L_F_tok_w3_nodup", "duplicate whole-token TF boost"),
    ("split_index_composite", "L_G_split", "L_A_unicode61",
     "COMPOSITE, isolates nothing: simultaneously adds the tokens index, a second retrieval arm, "
     "RRF rank normalisation and insertion-order tie behaviour (review r2 BLOCKER 4)"),
    ("tokens_w3_vs_baseline", "L_E_tok_w3", "L_A_unicode61", "round-1's CONFOUNDED comparison"),
    ("tokens_hybrid_isolated", "H_tok_w3", "H_tokchar_notok", "isolated tokens effect, in hybrid"),
    ("tokens_hybrid_confounded", "H_tok_w3", "H_small_prefix", "round-1 config 5 vs 4p"),
]


# Which dense models each config needs, so --only can skip loading models it will not use.
DENSE_TAGS_FOR = {
    "D_small_noprefix": {"bge-small"}, "D_small_prefix": {"bge-small-prefix"},
    "D_large_prefix": {"bge-large-prefix"}, "D_nomic": {"nomic"},
    "H_small_noprefix": {"bge-small"}, "H_small_prefix": {"bge-small-prefix"},
    "H_tokchar_notok": {"bge-small-prefix"}, "H_tok_w3": {"bge-small-prefix"},
    "H_tok_w3_nodup": {"bge-small-prefix"}, "H_large": {"bge-large-prefix"},
    "H_nomic": {"nomic"},
}


def rank_for(cfg: str, db, qtext: str, qvecs: dict, depth: int) -> list:
    B, D, F = R2.bm25_tab, R2.dense_tab, R2.rrf_counted
    if cfg == "L_A_unicode61":
        return B(db, "fx_text", qtext, (1, 1), depth)
    if cfg == "L_B_tokchar":
        return B(db, "fx_tokchar", qtext, (1, 1), depth)
    if cfg == "L_C_tok_w0":
        return B(db, "fx_tok_dup", qtext, (1, 1, 0), depth)
    if cfg == "L_D_tok_w1":
        return B(db, "fx_tok_dup", qtext, (1, 1, 1), depth)
    if cfg == "L_E_tok_w3":
        return B(db, "fx_tok_dup", qtext, (1, 1, 3), depth)
    if cfg == "L_F_tok_w3_nodup":
        return B(db, "fx_tok_nodup", qtext, (1, 1, 3), depth)
    if cfg == "L_G_split":
        return F(B(db, "fx_text", qtext, (1, 1), depth),
                 B(db, "fx_tokonly", qtext, (1,), depth))
    if cfg == "D_small_noprefix":
        return D(db, qvecs["bge-small"], "bge-small", depth)
    if cfg == "D_small_prefix":
        return D(db, qvecs["bge-small-prefix"], "bge-small-prefix", depth)
    if cfg == "D_large_prefix":
        return D(db, qvecs["bge-large-prefix"], "bge-large-prefix", depth)
    if cfg == "D_nomic":
        return D(db, qvecs["nomic"], "nomic", depth)
    if cfg == "H_small_noprefix":
        return F(B(db, "fx_text", qtext, (1, 1), depth),
                 D(db, qvecs["bge-small"], "bge-small", depth))
    if cfg == "H_small_prefix":
        return F(B(db, "fx_text", qtext, (1, 1), depth),
                 D(db, qvecs["bge-small-prefix"], "bge-small-prefix", depth))
    if cfg == "H_tokchar_notok":
        return F(B(db, "fx_tokchar", qtext, (1, 1), depth),
                 D(db, qvecs["bge-small-prefix"], "bge-small-prefix", depth))
    if cfg == "H_tok_w3":
        return F(B(db, "fx_tok_dup", qtext, (1, 1, 3), depth),
                 D(db, qvecs["bge-small-prefix"], "bge-small-prefix", depth))
    if cfg == "H_tok_w3_nodup":
        return F(B(db, "fx_tok_nodup", qtext, (1, 1, 3), depth),
                 D(db, qvecs["bge-small-prefix"], "bge-small-prefix", depth))
    if cfg == "H_large":
        return F(B(db, "fx_text", qtext, (1, 1), depth),
                 D(db, qvecs["bge-large-prefix"], "bge-large-prefix", depth))
    if cfg == "H_nomic":
        return F(B(db, "fx_text", qtext, (1, 1), depth),
                 D(db, qvecs["nomic"], "nomic", depth))
    raise KeyError(cfg)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", nargs="*", default=["blind", "dev"])
    ap.add_argument("--depths", nargs="*", type=int, default=[50, 187])
    ap.add_argument("--only", nargs="*", default=None, help="config name prefixes (smoke tests)")
    ap.add_argument("--embed-mode", default="gist_content",
                    choices=["gist_content", "gist_only", "content_only"],
                    help="what text is embedded for the DENSE arm; lexical always indexes both")
    ap.add_argument("--out", default=str(RESULTS / "eval_v2.json"))
    args = ap.parse_args()
    global CONFIGS, DENSE_TAGS
    if args.only:
        CONFIGS = [c for c in CONFIGS if any(c[0].startswith(p) for p in args.only)]
        needed = set()
        for n, _f, _d in CONFIGS:
            needed |= DENSE_TAGS_FOR.get(n, set())
        DENSE_TAGS = [t for t in DENSE_TAGS if t in needed]

    doc = R.load_dataset()
    mems = doc["memories"]
    row_of = {m["uuid"]: i for i, m in enumerate(mems, start=1)}
    labels = EK.load_labels()

    qsets = {}
    if "blind" in args.sets:
        qsets["blind"] = EK.load_blind()
    if "dev" in args.sets:
        qsets["dev"] = EK.load_dev(doc)

    if DB_PATH.exists():
        DB_PATH.unlink()
    db = R.connect(DB_PATH)
    t0 = time.perf_counter()
    fx_counts = R2.build_lexical_factorial(db, mems, verbose=True)
    print(f"[index] 5 FTS variants in {time.perf_counter()-t0:.1f}s", flush=True)

    from fastembed import TextEmbedding
    caches, qvecs = {}, defaultdict(lambda: defaultdict(dict))
    for tag in DENSE_TAGS:
        model, qpre, ppre = R.MODELS[tag]
        t0 = time.perf_counter()
        cache = EmbedCache(model, TextEmbedding(model_name=model))
        caches[tag] = (cache, qpre, ppre)
        dv = cache.embed([ppre + R.doc_text(m, args.embed_mode) for m in mems])
        dim = dv.shape[1]
        table = f"vec_{tag.replace('-', '_')}"
        db.executescript(f"""
            drop table if exists {table};
            create virtual table {table} using vec0(rowid integer primary key,
                                                    emb float[{dim}]);
            create table if not exists vectors_meta(tag text primary key, model text, dim int,
                                                    embed_mode text);""")
        for i, v in enumerate(dv, start=1):
            db.execute(f"insert into {table}(rowid, emb) values (?,?)", (i, v.tobytes()))
        db.execute("insert or replace into vectors_meta values (?,?,?,?)",
                   (tag, model, dim, args.embed_mode))
        db.commit()
        for sname, rows in qsets.items():
            qv = cache.embed([qpre + r["text"] for r in rows])
            for r, v in zip(rows, qv):
                qvecs[sname][r["query_id"]][tag] = v
        cache.flush()
        print(f"[dense] {tag} dim={dim} {time.perf_counter()-t0:.1f}s "
              f"(cache hits={cache.hits} misses={cache.misses})", flush=True)

    out = dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        n_memories=len(mems), rrf_k=R.RRF_K, embed_mode=args.embed_mode,
        fts_counts=fx_counts,
        query_sets={k: len(v) for k, v in qsets.items()},
        bootstrap=dict(n=EK.BOOT_N, seed=EK.BOOT_SEED, unit="stub"),
        configs={n: d for n, _f, d in CONFIGS},
        results={}, contrasts={}, ties={},
    )

    all_rows = {}   # (set, depth, cfg) -> rows
    for sname, rows in qsets.items():
        for depth in args.depths:
            for cfg, fam, _desc in CONFIGS:
                R2.reset_ties()
                t0 = time.perf_counter()
                scored = []
                for r in rows:
                    order = [i for i, _ in rank_for(cfg, db, r["text"],
                                                    qvecs[sname][r["query_id"]], depth)]
                    s = EK.score_query(order, labels[r["stub_id"]], row_of)
                    s.update(query_id=r["query_id"], stub_id=r["stub_id"],
                             variant_style=r["variant_style"],
                             trap_category=r["trap_category"], intent=r["intent"],
                             underspecified=r.get("underspecified", False),
                             rank_depth=len(order))
                    scored.append(s)
                wall = time.perf_counter() - t0
                key = f"{sname}|d{depth}|{cfg}"
                all_rows[(sname, depth, cfg)] = scored
                res = dict(
                    ALL=EK.aggregate(scored),
                    by_category=EK.breakdown(scored, "trap_category"),
                    by_intent=EK.breakdown(scored, "intent"),
                    by_register=EK.breakdown(scored, "variant_style"),
                    by_underspecified=EK.breakdown(scored, "underspecified"),
                    phrasing_spread={m: EK.phrasing_spread(scored, m)
                                     for m in ["useful_hit5", "mrr10", "harmful_disp5"]},
                    mean_rank_depth=round(
                        sum(s["rank_depth"] for s in scored) / len(scored), 1),
                    wall_seconds=round(wall, 3),
                )
                if fam in ("H", "L") and cfg in ("L_G_split",) or fam == "H":
                    res["ties"] = R2.tie_report()
                out["results"][key] = res
            print(f"[{sname} d{depth}] done", flush=True)

    # ---- declared contrasts, on the primary set at depth 50 (operational) and 187 (diagnostic)
    for sname in qsets:
        for depth in args.depths:
            for cname, a, b, what in CONTRASTS:
                ra, rb = all_rows.get((sname, depth, a)), all_rows.get((sname, depth, b))
                if not ra or not rb:
                    continue
                out["contrasts"][f"{sname}|d{depth}|{cname}"] = dict(
                    isolates=what, arm_a=a, arm_b=b,
                    **{m: EK.paired_bootstrap(ra, rb, m)
                       for m in ["useful_hit5", "mrr10", "harmful_exposure5", "harmful_disp5"]})

    # ---- dev vs blind on the same configs: the v1-development versus v2-blind QUERY-SET GAP.
    # DESCRIPTIVE ONLY (PREREGISTRATION-R3.md R3.3). The two sets differ in author *and* in
    # register, length, detail and deliberate underspecification, so this is a set difference and
    # not an isolated authorship effect. It supports no decision and estimates no general rate.
    if "dev" in qsets and "blind" in qsets:
        gap = {}
        for depth in args.depths:
            for cfg, _f, _d in CONFIGS:
                d = EK.aggregate(all_rows[("dev", depth, cfg)])
                b = EK.aggregate(all_rows[("blind", depth, cfg)])
                gap[f"d{depth}|{cfg}"] = {
                    m: dict(dev=d[m], blind=b[m],
                            gap=(round(d[m] - b[m], 4)
                                 if d[m] is not None and b[m] is not None else None))
                    for m in EK.METRICS}
        out["query_set_gap"] = dict(
            estimand="v1_development_minus_v2_blind_aggregate",
            interpretation=("Descriptive set difference. NOT an authorship effect: author identity "
                            "is inseparable from the register/length/detail/underspecification "
                            "change between the two sets. Supports no decision."),
            per_config=gap,
            # A stub-clustered interval on the same set difference, per R3.3: for each stub, the
            # dev prompt's value minus the mean of that stub's three blind variants.
            stub_clustered=({cfg: EK.set_gap_bootstrap(all_rows[("dev", args.depths[0], cfg)],
                                                       all_rows[("blind", args.depths[0], cfg)],
                                                       "useful_hit5")
                             for cfg, _f, _d in CONFIGS}),
            stub_clustered_metric="useful_hit5",
            stub_clustered_depth=args.depths[0],
        )

    pathlib.Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    # per-query detail in a separate file so the summary stays readable
    # Per-query detail is named after --out, so a smoke run with --out /tmp/... cannot clobber
    # the canonical results/eval_v2_perquery.json. That bit once.
    detail = {f"{s}|d{d}|{c}": v for (s, d, c), v in all_rows.items()}
    outp = pathlib.Path(args.out)
    pq = outp.with_name(outp.stem + "_perquery" + outp.suffix)
    pq.write_text(json.dumps(detail) + "\n")
    print(f"wrote {args.out} and {pq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
