#!/usr/bin/env python
"""Leakage audit for dataset.json.

Question it answers: is this eval accidentally trivial? If a query shares most of its tokens
with its gold memory, any lexical retriever wins by construction and every downstream number
is inflated.

Reports, overall and per category:
  * jaccard(query, gold)                    - raw overlap
  * containment(query -> gold)              - fraction of query tokens present in gold, which is
                                              the more honest measure for short queries, since
                                              Jaccard is depressed just by the gold being long
  * the SAME two numbers against the hard negative, and the margin between them. This is the
    number that actually matters for category 1: if a query overlaps its hard negative as much
    as its gold, then lexical retrieval cannot separate them and the task is genuinely hard.

Usage: .venv/bin/python leakage_audit.py [--json]
"""
import json
import pathlib
import re
import statistics
import sys
from collections import defaultdict

TOK = re.compile(r"[a-z0-9]+")
HERE = pathlib.Path(__file__).parent


def toks(s: str) -> set:
    return set(TOK.findall(s.lower()))


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0


def containment(q: set, d: set) -> float:
    return len(q & d) / len(q) if q else 0.0


def main() -> int:
    doc = json.loads((HERE / "dataset.json").read_text())
    by_uuid = {m["uuid"]: m for m in doc["memories"]}

    rows = []
    for q in doc["queries"]:
        qt = toks(q["text"])
        g = by_uuid[q["gold"][0]]
        gt_gist = toks(g["gist"])
        gt_full = toks(g["gist"] + " " + g["content"])
        row = dict(qid=q["qid"], cat=q["cat"], n_query_tokens=len(qt),
                   j_gist=jaccard(qt, gt_gist), j_full=jaccard(qt, gt_full),
                   c_gist=containment(qt, gt_gist), c_full=containment(qt, gt_full))
        if q["hard_neg"]:
            h = by_uuid[q["hard_neg"][0]]
            ht_gist = toks(h["gist"])
            ht_full = toks(h["gist"] + " " + h["content"])
            row.update(hn_j_gist=jaccard(qt, ht_gist), hn_j_full=jaccard(qt, ht_full),
                       hn_c_gist=containment(qt, ht_gist), hn_c_full=containment(qt, ht_full))
            row["margin_c_gist"] = row["c_gist"] - row["hn_c_gist"]
            row["margin_c_full"] = row["c_full"] - row["hn_c_full"]
        rows.append(row)

    def agg(subset, field):
        vals = [r[field] for r in subset if field in r]
        if not vals:
            return None
        return dict(n=len(vals), mean=round(statistics.mean(vals), 4),
                    median=round(statistics.median(vals), 4),
                    min=round(min(vals), 4), max=round(max(vals), 4))

    fields = ["j_gist", "j_full", "c_gist", "c_full",
              "hn_c_gist", "hn_c_full", "margin_c_gist", "margin_c_full"]
    groups = {"ALL": rows}
    per_cat = defaultdict(list)
    for r in rows:
        per_cat[r["cat"]].append(r)
    groups.update(per_cat)

    out = {g: {f: agg(rs, f) for f in fields} for g, rs in groups.items()}

    if "--json" in sys.argv:
        print(json.dumps(dict(per_group=out, per_query=rows), indent=2))
        return 0

    hdr = f"{'group':16} {'n':>3}  {'J(q,gist)':>10} {'J(q,full)':>10} {'C(q,gist)':>10} {'C(q,full)':>10}"
    print(hdr)
    print("-" * len(hdr))
    for g in ["ALL", "near_miss", "paraphrase_only", "error_string", "polarity", "over_length"]:
        if g not in out:
            continue
        o = out[g]
        print(f"{g:16} {o['j_gist']['n']:>3}  "
              f"{o['j_gist']['mean']:>10.3f} {o['j_full']['mean']:>10.3f} "
              f"{o['c_gist']['mean']:>10.3f} {o['c_full']['mean']:>10.3f}   (mean)")
        print(f"{'':16} {'':>3}  "
              f"{o['j_gist']['median']:>10.3f} {o['j_full']['median']:>10.3f} "
              f"{o['c_gist']['median']:>10.3f} {o['c_full']['median']:>10.3f}   (median)")

    print()
    print("Hard-negative comparison (containment). margin = gold - hard_neg; near 0 means")
    print("lexical overlap alone cannot separate gold from its confusable twin.")
    hdr2 = f"{'group':16} {'n':>3}  {'C_gold(full)':>13} {'C_hn(full)':>11} {'margin':>8}  {'margin<=0':>9}"
    print(hdr2)
    print("-" * len(hdr2))
    for g in ["ALL", "near_miss", "polarity", "error_string"]:
        if g not in out or out[g]["margin_c_full"] is None:
            continue
        rs = [r for r in groups[g] if "margin_c_full" in r]
        neg = sum(1 for r in rs if r["margin_c_full"] <= 0)
        o = out[g]
        print(f"{g:16} {len(rs):>3}  {o['c_full']['mean']:>13.3f} "
              f"{o['hn_c_full']['mean']:>11.3f} {o['margin_c_full']['mean']:>8.3f}  "
              f"{neg:>4}/{len(rs):<4}")

    print()
    print("Highest-leakage queries by containment against gold gist+content:")
    for r in sorted(rows, key=lambda r: -r["c_full"])[:8]:
        print(f"  {r['c_full']:.3f}  {r['qid']:10} {r['cat']:16} ({r['n_query_tokens']} query tokens)")
    print("Lowest-leakage queries:")
    for r in sorted(rows, key=lambda r: r["c_full"])[:8]:
        print(f"  {r['c_full']:.3f}  {r['qid']:10} {r['cat']:16} ({r['n_query_tokens']} query tokens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
