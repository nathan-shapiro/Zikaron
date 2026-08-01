#!/usr/bin/env python
"""Graded-relevance metrics and cluster-bootstrap uncertainty. Shared by every round-2 driver.

METRIC DEFINITIONS (authoritative; PREREGISTRATION.md section 4 declared these before any
round-2 result was computed).

Labels come from `stubs_v2.json`, which grades every bearing memory:
  primary             - the record that answers the prompt. >=1 per stub, 3 stubs have two.
  also_useful         - a record a user would be glad to also see. Not a failure under D12's
                        five-slot budget, so it is NOT counted as a distractor.
  harmful_if_applied  - a record whose *application* would misdirect. The real trap.

Per query, over a ranking of rowids best-first:
  useful_hit@5        1 if any `primary` is in the top 5. THE HEADLINE.
  harmful_exposure@5  1 if any `harmful_if_applied` is in the top 5. Reported separately from
                      useful_hit; the two are never netted against each other.
  harmful_disp@5      1 if a harmful record is in the top 5 AND ranks above every primary. The
                      PRIMARY displacement measure (review MAJOR 13: hnd over a 50-candidate
                      union was never a full-corpus ranking).
  harmful_disp_full   1 if a harmful record outranks every primary anywhere in the ranking
                      supplied. Only meaningful when the caller ranked the WHOLE corpus; the
                      driver records `rank_depth` so the report cannot quote this as full-corpus
                      when it was not.
  mrr@10              1/rank of the first primary in the top 10, else 0.
  relevant_recall@5   |(primary u also_useful) n top5| / |primary u also_useful|. Secondary.

Uncertainty: the STUB is the resampling unit, not the query, because the three phrasing variants
of one stub are the same information need. Paired cluster bootstrap: resample stubs with
replacement, apply the SAME resample to both arms of a contrast, take percentile intervals of the
difference. 10 000 resamples, seed fixed.
"""
import json
import pathlib
import statistics
from collections import defaultdict

import numpy as np

HERE = pathlib.Path(__file__).parent
BOOT_N = 10000
BOOT_SEED = 20260801


# --------------------------------------------------------------------------- label loading

def load_labels() -> dict:
    """stub_id -> dict(primary, also_useful, harmful, intent, trap_category)."""
    stubs = json.loads((HERE / "stubs_v2.json").read_text())["stubs"]
    out = {}
    for s in stubs:
        by = defaultdict(list)
        for r in s["relevant_memory_uuids"]:
            by[r["grade"]].append(r["uuid"])
        out[s["stub_id"]] = dict(
            primary=by["primary"], also_useful=by["also_useful"],
            harmful=by["harmful_if_applied"],
            confusable=list(s.get("confusable_uuids", [])),
            intent=s["intent"], trap_category=s["trap_category"],
            identifiers=s.get("identifiers_involved", []))
    return out


def load_blind() -> list:
    """The PRIMARY eval set: 192 prompts authored without reading the memory prose."""
    return json.loads((HERE / "queries_blind.json").read_text())["queries"]


def load_dev(dataset: dict) -> list:
    """The DEVELOPMENT set: the 64 v1 queries, same shape as blind rows so metrics are identical.

    v1 qid == v2 stub_id, so the v1 queries can be scored against the SAME graded labels. That
    makes the dev-vs-blind difference computable on a fixed label set - but it does NOT make it an
    isolated authorship contrast. The two sets differ in author AND in register, length, detail and
    deliberate underspecification (39/192 blind rows withhold a cue on purpose). See
    PREREGISTRATION-R3.md R3.3: the quantity is the v1-development versus v2-blind QUERY-SET GAP,
    it is descriptive, and it supports no decision.
    """
    return [dict(query_id=q["qid"] + "-dev", stub_id=q["qid"], variant=0,
                 text=q["text"], variant_style="v1_self_authored", underspecified=False,
                 trap_category=q["cat"], intent="current_action")
            for q in dataset["queries"]]


# --------------------------------------------------------------------------- per-query scoring

def score_query(order: list, lab: dict, row_of: dict) -> dict:
    """order: rowids best-first. lab: label dict for the stub. row_of: uuid -> rowid."""
    prim = {row_of[u] for u in lab["primary"] if u in row_of}
    also = {row_of[u] for u in lab["also_useful"] if u in row_of}
    harm = {row_of[u] for u in lab["harmful"] if u in row_of}
    rel = prim | also
    top5 = order[:5]
    top5s, top10 = set(top5), order[:10]
    pos = {r: i for i, r in enumerate(order)}
    INF = 10 ** 9
    p_pos = min((pos[r] for r in prim if r in pos), default=INF)
    h_pos = min((pos[r] for r in harm if r in pos), default=INF)

    mrr = 0.0
    for i, r in enumerate(top10, start=1):
        if r in prim:
            mrr = 1.0 / i
            break
    return dict(
        useful_hit5=float(bool(prim & top5s)),
        harmful_exposure5=float(bool(harm) and bool(harm & top5s)) if harm else 0.0,
        harmful_disp5=float(bool(harm) and h_pos < 5 and h_pos < p_pos),
        harmful_disp_full=float(bool(harm) and h_pos < p_pos),
        mrr10=mrr,
        relevant_recall5=(len(rel & top5s) / len(rel)) if rel else 0.0,
        n_primary_in_top5=len(prim & top5s),
        n_also_in_top5=len(also & top5s),
        primary_rank=(p_pos + 1) if p_pos < INF else None,
        harmful_rank=(h_pos + 1) if h_pos < INF else None,
        has_harmful=bool(harm),
    )


METRICS = ["useful_hit5", "harmful_exposure5", "harmful_disp5", "mrr10", "relevant_recall5"]
HARM_ONLY = {"harmful_exposure5", "harmful_disp5", "harmful_disp_full"}


def aggregate(rows: list) -> dict:
    """rows: list of dicts from score_query, each carrying stub_id/trap_category/intent."""
    if not rows:
        return {}
    out = {"n_queries": len(rows), "n_stubs": len({r["stub_id"] for r in rows})}
    for m in METRICS + ["harmful_disp_full"]:
        sel = [r for r in rows if (r["has_harmful"] if m in HARM_ONLY else True)]
        out[m] = round(statistics.mean(r[m] for r in sel), 4) if sel else None
        if m in HARM_ONLY:
            out[m + "_n"] = len(sel)
    ranks = [r["primary_rank"] for r in rows if r["primary_rank"]]
    out["median_primary_rank"] = statistics.median(ranks) if ranks else None
    out["frac_primary_unranked"] = round(
        sum(1 for r in rows if r["primary_rank"] is None) / len(rows), 4)
    return out


def breakdown(rows: list, field: str) -> dict:
    g = defaultdict(list)
    for r in rows:
        g[r[field]].append(r)
    return {str(k): aggregate(v) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


# --------------------------------------------------------------------------- cluster bootstrap

def _stub_means(rows_by_stub: dict, metric: str) -> dict:
    """stub -> (sum, count) for a metric, restricted to eligible rows."""
    out = {}
    for stub, rows in rows_by_stub.items():
        sel = [r for r in rows if (r["has_harmful"] if metric in HARM_ONLY else True)]
        out[stub] = (sum(r[metric] for r in sel), len(sel))
    return out


def paired_bootstrap(rows_a: list, rows_b: list, metric: str, n=BOOT_N, seed=BOOT_SEED) -> dict:
    """Paired cluster bootstrap over stubs for mean(a) - mean(b) on `metric`.

    rows_a and rows_b must cover the same queries (same config-independent query set).
    """
    by_a, by_b = defaultdict(list), defaultdict(list)
    for r in rows_a:
        by_a[r["stub_id"]].append(r)
    for r in rows_b:
        by_b[r["stub_id"]].append(r)
    stubs = sorted(set(by_a) & set(by_b))
    sa, sb = _stub_means(by_a, metric), _stub_means(by_b, metric)
    stubs = [s for s in stubs if sa[s][1] > 0 and sb[s][1] > 0]
    if not stubs:
        return dict(metric=metric, n_stubs=0, point=None)

    num_a = np.array([sa[s][0] for s in stubs], dtype=float)
    den_a = np.array([sa[s][1] for s in stubs], dtype=float)
    num_b = np.array([sb[s][0] for s in stubs], dtype=float)
    den_b = np.array([sb[s][1] for s in stubs], dtype=float)
    point = num_a.sum() / den_a.sum() - num_b.sum() / den_b.sum()

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(stubs), size=(n, len(stubs)))
    diffs = (num_a[idx].sum(1) / den_a[idx].sum(1)) - (num_b[idx].sum(1) / den_b[idx].sum(1))
    lo, hi = np.percentile(diffs, [2.5, 97.5])

    # raw changed-query counts: a difference of "+0.03" must always be quotable as k queries.
    ka = {r["query_id"]: r[metric] for r in rows_a}
    kb = {r["query_id"]: r[metric] for r in rows_b}
    common = set(ka) & set(kb)
    up = sum(1 for q in common if ka[q] > kb[q])
    down = sum(1 for q in common if ka[q] < kb[q])
    return dict(metric=metric, n_stubs=len(stubs), n_queries=len(common),
                point=round(float(point), 4),
                ci95=[round(float(lo), 4), round(float(hi), 4)],
                excludes_zero=bool(lo > 0 or hi < 0),
                changed_up=up, changed_down=down,
                p_two_sided_sign=round(float(_sign_p(diffs)), 4))


def _sign_p(diffs: np.ndarray) -> float:
    """Bootstrap two-sided 'p': 2x the smaller tail mass on the wrong side of zero."""
    n = len(diffs)
    below = float((diffs <= 0).sum()) / n
    above = float((diffs >= 0).sum()) / n
    return min(1.0, 2.0 * min(below, above))


def set_gap_bootstrap(rows_dev: list, rows_blind: list, metric: str,
                      n=BOOT_N, seed=BOOT_SEED) -> dict:
    """Stub-clustered interval on a QUERY-SET difference, where the two sets have different sizes.

    `paired_bootstrap` reports changed-query counts by intersecting `query_id`, which is empty
    across query sets (dev ids end `-dev`, blind ids end `-v1/-v2/-v3`) and would silently print
    0 up / 0 down. This variant pairs on the STUB instead: for each stub, the dev prompt's value
    against the MEAN of that stub's three blind variants, then resamples stubs with replacement.

    Interpretation is fixed by PREREGISTRATION-R3.md R3.3: this is an interval on the observed
    v1-development versus v2-blind SET DIFFERENCE. Author identity is not separable from the
    register/length/detail change between the sets, so it is not an authorship effect.
    """
    by_d, by_b = defaultdict(list), defaultdict(list)
    for r in rows_dev:
        by_d[r["stub_id"]].append(r)
    for r in rows_blind:
        by_b[r["stub_id"]].append(r)
    sd, sb = _stub_means(by_d, metric), _stub_means(by_b, metric)
    stubs = [s for s in sorted(set(by_d) & set(by_b)) if sd[s][1] > 0 and sb[s][1] > 0]
    if not stubs:
        return dict(metric=metric, n_stubs=0, point=None)
    vd = np.array([sd[s][0] / sd[s][1] for s in stubs], dtype=float)
    vb = np.array([sb[s][0] / sb[s][1] for s in stubs], dtype=float)
    d = vd - vb
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(n, len(d)))
    lo, hi = np.percentile(d[idx].mean(1), [2.5, 97.5])
    return dict(metric=metric, n_stubs=len(stubs), point=round(float(d.mean()), 4),
                ci95=[round(float(lo), 4), round(float(hi), 4)],
                excludes_zero=bool(lo > 0 or hi < 0),
                stubs_dev_higher=int((d > 0).sum()), stubs_equal=int((d == 0).sum()),
                stubs_blind_higher=int((d < 0).sum()),
                estimand="mean over stubs of (dev value - mean of that stub's 3 blind variants)")


def phrasing_spread(rows: list, metric: str) -> dict:
    """Metric computed per phrasing register, and the spread across them.

    This is the honest replacement for 'we reran it and got the same number'. Inference is
    deterministic, so rerunning changes nothing; changing the phrasing changes a lot.
    """
    by_v = defaultdict(list)
    for r in rows:
        by_v[r["variant_style"]].append(r)
    vals = {}
    for style, rs in by_v.items():
        sel = [r for r in rs if (r["has_harmful"] if metric in HARM_ONLY else True)]
        if sel:
            vals[style] = round(statistics.mean(r[metric] for r in sel), 4)
    if len(vals) < 2:
        return dict(per_register=vals)
    return dict(per_register=vals, min=min(vals.values()), max=max(vals.values()),
                range=round(max(vals.values()) - min(vals.values()), 4))
