#!/usr/bin/env python
"""Regenerate every figure quoted in `research/embedder-benchmark-results.md` from the JSON.

The point is drift prevention. A report and its artefacts diverge the moment someone re-runs one
script; this prints the canonical value for each quoted number, labelled with where it appears, so
a future session can check the report in one pass instead of trusting it.

`--assert` additionally checks the values the report states in prose and exits 1 on mismatch. The
expected values are hard-coded here on purpose: they are what the report SAYS, so a mismatch means
either the report is stale or a rerun moved a number, and both need a human decision.

Usage: .venv/bin/python report_figures.py [--assert]
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
R = HERE / "results"


def g(d, *path, default=None):
    for k in path:
        if d is None:
            return default
        d = d.get(k) if isinstance(d, dict) else None
    return d if d is not None else default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assert", dest="do_assert", action="store_true")
    args = ap.parse_args()

    ev = json.loads((R / "eval_v2.json").read_text())
    go = json.loads((R / "eval_v2_gist_only.json").read_text())
    tc = json.loads((R / "twin_counterfactual.json").read_text())
    ex = json.loads((R / "extractor_heldout.json").read_text())
    ck = json.loads((R / "tokens_cost.json").read_text())
    rr = json.loads((R / "rerank_scaling.json").read_text())
    ts = json.loads((R / "tie_sensitivity.json").read_text())

    def blind(cfg, metric, depth=50):
        return g(ev, "results", f"blind|d{depth}|{cfg}", "ALL", metric)

    def contrast(name, metric, depth=50):
        c = g(ev, "contrasts", f"blind|d{depth}|{name}", metric)
        return (c or {}).get("point"), (c or {}).get("ci95"), \
               (c or {}).get("changed_up"), (c or {}).get("changed_down")

    checks = []   # (label, actual, expected_in_report)

    # --- headline
    checks += [
        ("H_small_prefix useful_hit5 (incumbent)", blind("H_small_prefix", "useful_hit5"), 0.9375),
        ("H_large useful_hit5", blind("H_large", "useful_hit5"), 0.9219),
        ("H_nomic useful_hit5 (best deployed)", blind("H_nomic", "useful_hit5"), 0.9479),
        ("D_small_prefix useful_hit5", blind("D_small_prefix", "useful_hit5"), 0.8958),
        ("D_large_prefix useful_hit5", blind("D_large_prefix", "useful_hit5"), 0.9323),
        ("D_large_prefix mrr10", blind("D_large_prefix", "mrr10"), 0.8511),
        ("D_large_prefix harmful_exposure5 (worst)",
         blind("D_large_prefix", "harmful_exposure5"), 0.7083),
        ("L_A_unicode61 useful_hit5 (BM25 only)", blind("L_A_unicode61", "useful_hit5"), 0.8802),
    ]

    # --- declared contrasts quoted in the report
    for name, metric, exp_pt in [
        ("large_vs_small_dense", "mrr10", 0.0705),
        ("large_vs_small_dense", "useful_hit5", 0.0365),
        ("nomic_vs_small_dense", "mrr10", 0.0468),
        ("large_vs_small_hybrid", "useful_hit5", -0.0156),
        ("nomic_vs_small_hybrid", "useful_hit5", 0.0104),
        ("prefix_dense", "useful_hit5", 0.0260),
        ("prefix_hybrid", "useful_hit5", 0.0104),
        ("tokenizer_only", "useful_hit5", -0.0521),
        ("tokens_w3_vs_tokenizer", "useful_hit5", 0.0365),
        ("tokens_w3_vs_tokenizer", "mrr10", 0.0656),
        ("tokens_w1_vs_tokenizer", "mrr10", 0.0600),
        ("dup_emission", "useful_hit5", 0.0),
        ("tokens_w3_vs_baseline", "useful_hit5", -0.0156),
        ("tokens_w3_vs_baseline", "mrr10", 0.0325),
        ("tokens_w3_vs_baseline", "harmful_exposure5", -0.1528),
        ("tokens_hybrid_isolated", "mrr10", 0.0296),
        ("large_vs_small_dense", "harmful_exposure5", 0.1250),
    ]:
        pt, ci, up, dn = contrast(name, metric)
        checks.append((f"contrast {name} / {metric}  CI={ci} up={up} dn={dn}", pt, exp_pt))

    # --- ties. `frac_queries_with_any_tie_inside_top5` is the per-query BOOLEAN; round 2 quoted
    # a mean pair count under that name (review r2 BLOCKER 3). Both are checked so the two can
    # never drift apart again.
    checks += [
        ("any-tie-in-top5 FRACTION OF QUERIES, H_small_prefix",
         g(ev, "results", "blind|d50|H_small_prefix", "ties",
           "frac_queries_with_any_tie_inside_top5"), 0.125),
        ("any-tie-in-top5 FRACTION OF QUERIES, H_large",
         g(ev, "results", "blind|d50|H_large", "ties",
           "frac_queries_with_any_tie_inside_top5"), 0.1562),
        ("any-tie-in-top5 FRACTION OF QUERIES, H_nomic",
         g(ev, "results", "blind|d50|H_nomic", "ties",
           "frac_queries_with_any_tie_inside_top5"), 0.1146),
        ("any-tie-in-top5 FRACTION OF QUERIES, H_tok_w3",
         g(ev, "results", "blind|d50|H_tok_w3", "ties",
           "frac_queries_with_any_tie_inside_top5"), 0.0781),
        ("mean tied ADJACENT PAIRS in top5 per query, H_nomic (differs from the boolean)",
         g(ev, "results", "blind|d50|H_nomic", "ties",
           "mean_tied_adjacent_pairs_in_top5_per_query"), 0.1198),
        ("any-tie-in-top5 FRACTION OF QUERIES, L_G_split (composite)",
         g(ev, "results", "blind|d50|L_G_split", "ties",
           "frac_queries_with_any_tie_inside_top5"), 0.1719),
        ("mean tied ADJACENT PAIRS in top5 per query, L_G_split",
         g(ev, "results", "blind|d50|L_G_split", "ties",
           "mean_tied_adjacent_pairs_in_top5_per_query"), 0.1979),
        ("any tie anywhere, H_small_prefix",
         g(ev, "results", "blind|d50|H_small_prefix", "ties", "frac_queries_with_any_tie"), 1.0),
        ("mean tied adjacent pairs/query, H_small_prefix",
         g(ev, "results", "blind|d50|H_small_prefix", "ties",
           "mean_tied_adjacent_pairs_per_query"), 17.495),
    ]

    # --- tie-handling sensitivity (exploratory, R3.5)
    checks += [
        ("tie rule: canonical large-vs-small useful_hit5",
         g(ts, "contrasts", "bm25_first|large_vs_small_hybrid", "useful_hit5", "point"), -0.0156),
        ("tie rule: dense_first large-vs-small useful_hit5",
         g(ts, "contrasts", "dense_first|large_vs_small_hybrid", "useful_hit5", "point"), -0.0104),
        ("tie rule: tiebreak_dense large-vs-small useful_hit5",
         g(ts, "contrasts", "tiebreak_dense|large_vs_small_hybrid", "useful_hit5", "point"),
         -0.0104),
        ("tie rule: max movement from canonical",
         g(ts, "verdict", "large_vs_small_hybrid", "max_movement_from_canonical"), 0.0052),
        ("tie rule: any alternative reaches adoption threshold",
         g(ts, "verdict", "large_vs_small_hybrid", "any_alternative_reaches_threshold"), False),
        ("dense-gain queries",
         g(ts, "dense_gain_decomposition", "n_dense_gain_queries"), 9),
        ("dense gains where small hybrid already hit",
         g(ts, "dense_gain_decomposition", "fate_of_dense_gains",
           "no_gain_available_small_hybrid_already_hit"), 4),
        ("dense gains preserved in hybrid",
         g(ts, "dense_gain_decomposition", "fate_of_dense_gains",
           "differential_gain_preserved"), 1),
        ("dense gains destroyed by fusion",
         g(ts, "dense_gain_decomposition", "fate_of_dense_gains",
           "gain_destroyed_missed_by_both_hybrids"), 4),
        ("frac fused top-5 slots held by docs in BOTH arms",
         g(ts, "dense_gain_decomposition", "frac_fused_top5_agreed"), 1.0),
        ("mean arm intersection size (shows the above is not trivial)",
         g(ts, "dense_gain_decomposition", "mean_arm_intersection_size"), 21.7),
        ("mean arm union size",
         g(ts, "dense_gain_decomposition", "mean_arm_union_size"), 77.3),
        ("frac of candidate union that is in the intersection",
         g(ts, "dense_gain_decomposition", "frac_union_in_intersection"), 0.2803),
    ]

    # --- v1-development vs v2-blind query-set gap (renamed from "authorship inflation", R3.3)
    gaps = [v["useful_hit5"]["gap"] for v in ev["query_set_gap"]["per_config"].values()
            if v["useful_hit5"]["gap"] is not None]
    checks += [
        ("mean v1-dev minus v2-blind gap, useful_hit5", round(sum(gaps) / len(gaps), 4), 0.0106),
        ("max gap", max(gaps), 0.0573),
        ("min gap", min(gaps), -0.0208),
        ("gap CI, D_small_prefix (largest)",
         g(ev, "query_set_gap", "stub_clustered", "D_small_prefix", "point"), 0.0573),
        ("gap CI, H_small_prefix (incumbent)",
         g(ev, "query_set_gap", "stub_clustered", "H_small_prefix", "point"), 0.0),
        ("gap CI hi, D_small_prefix",
         g(ev, "query_set_gap", "stub_clustered", "D_small_prefix", "ci95")[1], 0.1146),
        ("gap, L_A_unicode61 (blind higher)",
         g(ev, "query_set_gap", "stub_clustered", "L_A_unicode61", "point"), -0.0208),
    ]

    # --- carrier-probe DI, quoted in section 7 prose
    for tag, exp in [("bge-small", 0.1941), ("bge-small-prefix", 0.2096),
                     ("bge-large-prefix", 0.2322), ("nomic", 0.1976)]:
        checks.append((f"DI carrier {tag} ratio-of-means",
                       g(tc, "models", tag, "carrier", "discrimination_index",
                         "ratio_of_means", "point"), exp))
    # --- DI ratio-of-means interval bounds, quoted in the section 7 table
    for tag, lo, hi in [("bge-small", 0.1353, 0.2895), ("bge-small-prefix", 0.1333, 0.2906),
                        ("bge-large-prefix", 0.1727, 0.2936), ("nomic", 0.1432, 0.2768)]:
        ci = g(tc, "models", tag, "bare", "discrimination_index", "ratio_of_means", "ci95")
        checks.append((f"DI bare {tag} RoM CI", tuple(ci or ()), (lo, hi)))

    # --- twin counterfactual. TWO estimands, both checked, so the report cannot quote one and
    # cite the other's number (review r2 BLOCKER 1).
    for tag, exp in [("bge-small", 0.2048), ("bge-small-prefix", 0.2045),
                     ("bge-large-prefix", 0.2331), ("nomic", 0.2087)]:
        checks.append((f"DI bare {tag} RATIO-OF-MEANS (primary)",
                       g(tc, "models", tag, "bare", "discrimination_index",
                         "ratio_of_means", "point"), exp))
    for tag, exp in [("bge-small-prefix", 0.2266), ("bge-large-prefix", 0.2448),
                     ("nomic", 0.2375)]:
        checks.append((f"DI bare {tag} MEAN-BLOCK-RATIO (secondary)",
                       g(tc, "models", tag, "bare", "discrimination_index",
                         "mean_block_ratio", "point"), exp))
    checks += [
        ("identity margin (must be 0), bge-small-prefix bare",
         g(tc, "models", "bge-small-prefix", "bare", "identity", "margin", "point"), 0.0),
        ("exact-control win rate, bge-small-prefix bare",
         g(tc, "models", "bge-small-prefix", "bare", "exact", "win_rate_trials"), 1.0),
        ("near_miss blocks positive, bge-small-prefix bare",
         g(tc, "models", "bge-small-prefix", "bare", "near_miss", "margin", "blocks_positive"), 14),
        ("DI_rom diff large-small (bare) PRIMARY",
         g(tc, "model_comparisons", "bare|bge-large-prefix_vs_bge-small-prefix|DI_rom",
           "point"), 0.0286),
        ("DI_mbr diff large-small (bare) SECONDARY",
         g(tc, "model_comparisons", "bare|bge-large-prefix_vs_bge-small-prefix|DI_mbr",
           "point"), 0.0181),
        ("DI_rom diff nomic-small (bare) PRIMARY",
         g(tc, "model_comparisons", "bare|nomic_vs_bge-small-prefix|DI_rom", "point"), 0.0042),
        ("DI_mbr diff nomic-small (bare) SECONDARY",
         g(tc, "model_comparisons", "bare|nomic_vs_bge-small-prefix|DI_mbr", "point"), 0.0109),
        ("DI_rom large-small meets prereg 0.15 capacity bar",
         g(tc, "model_comparisons", "bare|bge-large-prefix_vs_bge-small-prefix|DI_rom",
           "meets_prereg_capacity_bar"), False),
    ]

    # --- extractor
    checks += [
        ("extractor recall (held out)", g(ex, "summary", "recall"), 0.4186),
        ("extractor precision lenient", g(ex, "summary", "precision_lenient"), 0.5362),
        ("extractor precision strict", g(ex, "summary", "precision_strict"), 0.36),
        ("numeric-prose cases with a false positive",
         g(ex, "summary", "prose_num_cases_with_fp"), "6/7"),
        ("plain-prose cases with a false positive",
         g(ex, "summary", "prose_plain_cases_with_fp"), "0/7"),
        ("held-out collisions", g(ex, "summary", "collisions"), 2),
        ("frozen sha matches preregistration", ex.get("frozen_matches_preregistration"), True),
    ]

    # --- cost
    checks += [
        ("amend p95 median delta ms", g(ck, "median_deltas", "amend_p95_ms"), 0.3941),
        ("amend p50 median delta ms", g(ck, "median_deltas", "amend_p50_ms"), 0.215),
        ("insert p50 median delta ms", g(ck, "median_deltas", "insert_p50_ms"), 0.0607),
        ("database growth pct", g(ck, "median_deltas", "file_pct"), 5.0),
        ("fts shadow growth pct", g(ck, "median_deltas", "fts_pct"), 5.4),
    ]

    # --- reranker
    for key, exp in [("gist_content|50", 6591.5), ("gist_only|5", 183.6),
                     ("gist_only|50", 1907.9)]:
        checks.append((f"rerank p50 {key}", g(rr, "results", key, "p50_ms"), exp))
    checks.append(("rerank points within 200ms budget",
                   rr.get("operating_points_within_budget"), ["gist_only|5"]))

    # --- gist-only comparison
    checks += [
        ("gist_only D_small_prefix useful_hit5",
         g(go, "results", "blind|d50|D_small_prefix", "ALL", "useful_hit5"), 0.7708),
        ("gist_only H_small_prefix useful_hit5",
         g(go, "results", "blind|d50|H_small_prefix", "ALL", "useful_hit5"), 0.8542),
    ]

    bad = 0
    for label, actual, expected in checks:
        ok = actual == expected
        if isinstance(actual, float) and isinstance(expected, float):
            ok = abs(actual - expected) < 5e-4
        if not ok:
            bad += 1
        print(f"{'ok ' if ok else 'DIFF'}  {label:58} actual={actual!r:<22} report={expected!r}")

    print(f"\n{len(checks)} figures checked, {bad} mismatched")
    if bad and args.do_assert:
        print("The report and the artefacts disagree. Fix one of them deliberately.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
