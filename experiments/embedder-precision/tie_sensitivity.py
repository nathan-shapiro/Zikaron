#!/usr/bin/env python
"""EXPLORATORY: do insertion-order RRF ties *cause* the hybrid to absorb bge-large's dense gain?

Round 2 observed that bge-large beats bge-small dense-only but not inside the RRF hybrid, and
offered "rrf() breaks exact ties by insertion order, which favours the BM25 arm" as the mechanism.
Review round-2 BLOCKER 3 correctly objected that tie PREVALENCE is not evidence of tie CAUSATION,
and asked for an arm-order swap or an explicit tie-break sensitivity run. This is that run.

Declared as **exploratory** under PREREGISTRATION.md section 7 and PREREGISTRATION-R3.md R3.5, and
it MAY NOT SUPPORT A DECISION. The decision rule was fixed before the numbers existed (R3.5):

    Insertion-order ties may be described as the CAUSE of the vanishing dense gain only if the
    `large_vs_small_hybrid` useful_hit@5 contrast reaches the section 5.1 adoption threshold -
    point >= +0.05 with a 95 % CI excluding 0 - under at least ONE of the three alternative tie
    rules. Otherwise ties are a design defect of unquantified consequence and the mechanism is
    NOT established.

FOUR TIE RULES, everything else held fixed (same arms, k=60, depth 50, blind set, graded labels):
  bm25_first      canonical round-2 behaviour: BM25 passed first, Python stable sort
  dense_first     dense passed first, so insertion order favours dense instead
  tiebreak_dense  explicit deterministic tie-break on the dense arm's own rank
  tiebreak_bm25   explicit deterministic tie-break on the BM25 arm's own rank

SECOND, NON-TIE DIAGNOSTIC (also exploratory). For the queries where bge-large's dense arm puts a
primary in the top 5 and bge-small's does not, how many of those primaries were ALREADY in the BM25
arm's top 5 - so fusion had nothing to add - versus how many the fusion LOST? This tests the
alternative mechanism (unweighted RRF over two arms is dominated by arm agreement) without
appealing to ties at all.

Usage: .venv/bin/python tie_sensitivity.py
Out:   results/tie_sensitivity.json
"""
import json
import pathlib
import sys
import time

import evalkit as EK
import retrieval as R
import retrieval2 as R2
from embcache import EmbedCache

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "tie_sensitivity.json"
DB_PATH = HERE / "index_tie.db"          # separate file so index_v2.db state is untouched
DEPTH = 50
TAGS = ["bge-small-prefix", "bge-large-prefix", "nomic"]

# config -> (bm25 table, bm25 weights, dense tag)
HYBRIDS = {
    "H_small_prefix": ("fx_text", (1, 1), "bge-small-prefix"),
    "H_large":        ("fx_text", (1, 1), "bge-large-prefix"),
    "H_nomic":        ("fx_text", (1, 1), "nomic"),
    "H_tok_w3":       ("fx_tok_dup", (1, 1, 3), "bge-small-prefix"),
}

RULES = {
    "bm25_first":     dict(order=("bm25", "dense"), tiebreak="insertion"),
    "dense_first":    dict(order=("dense", "bm25"), tiebreak="insertion"),
    "tiebreak_dense": dict(order=("bm25", "dense"), tiebreak="by:dense"),
    "tiebreak_bm25":  dict(order=("bm25", "dense"), tiebreak="by:bm25"),
}

CONTRASTS = [("large_vs_small_hybrid", "H_large", "H_small_prefix"),
             ("nomic_vs_small_hybrid", "H_nomic", "H_small_prefix")]


def build(db, mems):
    R2.build_lexical_factorial(db, mems, verbose=False)
    from fastembed import TextEmbedding
    caches = {}
    for tag in TAGS:
        model, qpre, ppre = R.MODELS[tag]
        cache = EmbedCache(model, TextEmbedding(model_name=model))
        dv = cache.embed([ppre + R.doc_text(m, "gist_content") for m in mems])
        table = f"vec_{tag.replace('-', '_')}"
        db.executescript(f"""
            drop table if exists {table};
            create virtual table {table} using vec0(rowid integer primary key,
                                                    emb float[{dv.shape[1]}]);""")
        for i, v in enumerate(dv, start=1):
            db.execute(f"insert into {table}(rowid, emb) values (?,?)", (i, v.tobytes()))
        db.commit()
        caches[tag] = (cache, qpre)
    return caches


def main() -> int:
    doc = R.load_dataset()
    mems = doc["memories"]
    row_of = {m["uuid"]: i for i, m in enumerate(mems, start=1)}
    labels = EK.load_labels()
    rows = EK.load_blind()

    if DB_PATH.exists():
        DB_PATH.unlink()
    db = R.connect(DB_PATH)
    t0 = time.perf_counter()
    caches = build(db, mems)
    print(f"[index] built in {time.perf_counter()-t0:.1f}s", flush=True)

    qv = {}
    for tag in TAGS:
        cache, qpre = caches[tag]
        vecs = cache.embed([qpre + r["text"] for r in rows])
        for r, v in zip(rows, vecs):
            qv.setdefault(r["query_id"], {})[tag] = v
        cache.flush()

    # cache the raw arms once per query so tie rules are compared on IDENTICAL inputs
    arms = {}
    for r in rows:
        for tbl, w in {("fx_text", (1, 1)), ("fx_tok_dup", (1, 1, 3))}:
            arms[(r["query_id"], tbl)] = R2.bm25_tab(db, tbl, r["text"], w, DEPTH)
        for tag in TAGS:
            arms[(r["query_id"], tag)] = R2.dense_tab(db, qv[r["query_id"]][tag], tag, DEPTH)

    out = dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        status="EXPLORATORY - PREREGISTRATION section 7 / R3.5. May not support a decision.",
        decision_rule=("ties may be called the CAUSE only if large_vs_small_hybrid useful_hit5 "
                       "reaches point >= +0.05 with CI excluding 0 under at least one alternative "
                       "tie rule"),
        depth=DEPTH, rrf_k=R.RRF_K, n_queries=len(rows), rules=list(RULES),
        per_rule={}, contrasts={}, verdict={},
    )

    scored = {}           # (rule, cfg) -> rows
    for rule, spec in RULES.items():
        for cfg, (tbl, _w, tag) in HYBRIDS.items():
            got = []
            for r in rows:
                a = {"bm25": arms[(r["query_id"], tbl)], "dense": arms[(r["query_id"], tag)]}
                ranked = R2.rrf_tiebreak([(n, a[n]) for n in spec["order"]],
                                         tiebreak=spec["tiebreak"])
                order = [i for i, _ in ranked]
                s = EK.score_query(order, labels[r["stub_id"]], row_of)
                s.update(query_id=r["query_id"], stub_id=r["stub_id"],
                         variant_style=r["variant_style"], trap_category=r["trap_category"],
                         intent=r["intent"])
                got.append(s)
            scored[(rule, cfg)] = got
            out["per_rule"].setdefault(rule, {})[cfg] = EK.aggregate(got)

    for rule in RULES:
        for cname, a, b in CONTRASTS:
            out["contrasts"][f"{rule}|{cname}"] = {
                m: EK.paired_bootstrap(scored[(rule, a)], scored[(rule, b)], m)
                for m in ["useful_hit5", "mrr10"]}

    # ---- the declared decision rule, evaluated mechanically rather than by eye
    verdict = {}
    for cname, _a, _b in CONTRASTS:
        base = out["contrasts"][f"bm25_first|{cname}"]["useful_hit5"]
        alts = {}
        for rule in RULES:
            if rule == "bm25_first":
                continue
            c = out["contrasts"][f"{rule}|{cname}"]["useful_hit5"]
            alts[rule] = dict(point=c["point"], ci95=c["ci95"],
                              reaches_adoption_threshold=bool(
                                  c["point"] is not None and c["point"] >= 0.05
                                  and c["excludes_zero"]))
        verdict[cname] = dict(
            canonical=dict(point=base["point"], ci95=base["ci95"]),
            alternatives=alts,
            any_alternative_reaches_threshold=any(v["reaches_adoption_threshold"]
                                                  for v in alts.values()),
            max_movement_from_canonical=round(
                max(abs((v["point"] or 0) - (base["point"] or 0)) for v in alts.values()), 4),
        )
    out["verdict"] = verdict

    # ---- non-tie decomposition: where does the dense gain go?
    dsmall = {}
    dlarge = {}
    bm25only = {}
    for r in rows:
        for tag, sink in (("bge-small-prefix", dsmall), ("bge-large-prefix", dlarge)):
            order = [i for i, _ in arms[(r["query_id"], tag)]]
            sink[r["query_id"]] = EK.score_query(order, labels[r["stub_id"]], row_of)
        order = [i for i, _ in arms[(r["query_id"], "fx_text")]]
        bm25only[r["query_id"]] = EK.score_query(order, labels[r["stub_id"]], row_of)

    hyb_small = {s["query_id"]: s for s in scored[("bm25_first", "H_small_prefix")]}
    hyb_large = {s["query_id"]: s for s in scored[("bm25_first", "H_large")]}

    gain_q = [q for q in dsmall if dlarge[q]["useful_hit5"] > dsmall[q]["useful_hit5"]]
    loss_q = [q for q in dsmall if dlarge[q]["useful_hit5"] < dsmall[q]["useful_hit5"]]

    # Per-query ranks for the dense-gain queries, so "fusion pulled it back out of the top 5" is
    # a shown quantity rather than an assertion.
    def rank_in(arm_key, q, stub):
        prim = {row_of[u] for u in labels[stub]["primary"] if u in row_of}
        for i, (rid, _s) in enumerate(arms[(q, arm_key)], start=1):
            if rid in prim:
                return i
        return None

    detail = []
    for q in sorted(gain_q):
        stub = q.rsplit("-v", 1)[0]
        detail.append(dict(
            query_id=q,
            primary_rank_dense_large=rank_in("bge-large-prefix", q, stub),
            primary_rank_dense_small=rank_in("bge-small-prefix", q, stub),
            primary_rank_bm25=rank_in("fx_text", q, stub),
            primary_rank_fused_large=hyb_large[q]["primary_rank"],
            primary_rank_fused_small=hyb_small[q]["primary_rank"],
            hybrid_large_hit=bool(hyb_large[q]["useful_hit5"]),
            hybrid_small_hit=bool(hyb_small[q]["useful_hit5"]),
        ))

    # Three mutually exclusive fates for a dense-only gain, once fused. Round-2's single
    # "survived / lost" split conflated the last two, which overstates fusion's damage: a query
    # the small HYBRID already answers via its lexical arm never had a gain available to lose.
    fate = dict(
        no_gain_available_small_hybrid_already_hit=sum(
            1 for q in gain_q if hyb_small[q]["useful_hit5"] > 0),
        differential_gain_preserved=sum(
            1 for q in gain_q
            if hyb_large[q]["useful_hit5"] > 0 and hyb_small[q]["useful_hit5"] == 0),
        gain_destroyed_missed_by_both_hybrids=sum(
            1 for q in gain_q
            if hyb_large[q]["useful_hit5"] == 0 and hyb_small[q]["useful_hit5"] == 0),
    )

    # The alternative mechanism, quantified: with two unweighted arms, a document present in BOTH
    # arms' returned lists gets two reciprocal-rank contributions and a document present in only
    # one gets one. So the fused top 5 is dominated by ARM AGREEMENT, and a dense-only improvement
    # has to beat that. Count how many H_large fused top-5 slots are held by agreed documents.
    agree_slots = both = 0
    inter_sizes, union_sizes = [], []
    for r in rows:
        q = r["query_id"]
        bset = {rid for rid, _ in arms[(q, "fx_text")]}
        dset = {rid for rid, _ in arms[(q, "bge-large-prefix")]}
        inter_sizes.append(len(bset & dset))
        union_sizes.append(len(bset | dset))
        ranked = R2.rrf_tiebreak([("bm25", arms[(q, "fx_text")]),
                                 ("dense", arms[(q, "bge-large-prefix")])], tiebreak="insertion")
        for rid, _s in ranked[:5]:
            agree_slots += 1
            if rid in bset and rid in dset:
                both += 1
    mean_inter = sum(inter_sizes) / len(inter_sizes)
    mean_union = sum(union_sizes) / len(union_sizes)
    dec = dict(
        status="EXPLORATORY",
        n_dense_gain_queries=len(gain_q),
        n_dense_loss_queries=len(loss_q),
        dense_gain_already_in_bm25_top5=sum(1 for q in gain_q if bm25only[q]["useful_hit5"] > 0),
        dense_gain_not_in_bm25_top5=sum(1 for q in gain_q if bm25only[q]["useful_hit5"] == 0),
        fate_of_dense_gains=fate,
        hybrid_net_change=round(
            sum(hyb_large[q]["useful_hit5"] - hyb_small[q]["useful_hit5"] for q in dsmall)
            / len(dsmall), 4),
        fused_top5_slots=agree_slots,
        fused_top5_slots_in_both_arms=both,
        frac_fused_top5_agreed=round(both / agree_slots, 4) if agree_slots else None,
        # Is "all top-5 slots agreed" trivial? Only if the two arms return nearly the same set.
        # These make that checkable: the intersection is a minority of the union, so it is not.
        mean_arm_intersection_size=round(mean_inter, 1),
        mean_arm_union_size=round(mean_union, 1),
        frac_union_in_intersection=round(mean_inter / mean_union, 4),
        per_query=detail,
    )
    out["dense_gain_decomposition"] = dec

    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print("\n--- useful_hit5 by tie rule -------------------------------------------------")
    for rule in RULES:
        line = "  ".join(f"{c}={out['per_rule'][rule][c]['useful_hit5']:.4f}" for c in HYBRIDS)
        print(f"{rule:16} {line}")
    print("\n--- large_vs_small_hybrid useful_hit5 by tie rule ---------------------------")
    for rule in RULES:
        c = out["contrasts"][f"{rule}|large_vs_small_hybrid"]["useful_hit5"]
        print(f"{rule:16} {c['point']:+.4f} CI={c['ci95']} up={c['changed_up']} "
              f"down={c['changed_down']}")
    v = out["verdict"]["large_vs_small_hybrid"]
    print(f"\nany alternative rule reaching the +0.05/CI adoption threshold: "
          f"{v['any_alternative_reaches_threshold']}   "
          f"max movement from canonical: {v['max_movement_from_canonical']}")
    print(f"\ndense-gain queries: {dec['n_dense_gain_queries']} "
          f"(already in BM25 top5: {dec['dense_gain_already_in_bm25_top5']}, "
          f"not: {dec['dense_gain_not_in_bm25_top5']})")
    print(f"fate: {dec['fate_of_dense_gains']}")
    print(f"fused top-5 slots held by docs in BOTH arms' candidates: "
          f"{dec['fused_top5_slots_in_both_arms']}/{dec['fused_top5_slots']} "
          f"({dec['frac_fused_top5_agreed']})")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
