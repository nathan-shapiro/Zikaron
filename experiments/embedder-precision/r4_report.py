#!/usr/bin/env python
"""Round 4: apply PREREGISTRATION-R4.md to the results, in the order it declares.

1. Every configuration shared with round 3 must reproduce bit-identically (R4.6). If one does not,
   stop: nothing about a candidate is read until that is explained.
2. R4.3's quality gate, per candidate, on `blind|d50|r4_<arm>_vs_small_hybrid`.
3. R4.4's reported contrasts and, if present, the identifier and latency facts.

    ../../.venv/bin/python r4_report.py
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent / "results"
CANDIDATES = {"granite30": "granite-30m", "e5small": "e5-small", "granite125": "granite-125m"}
IGNORED = {"wall_seconds", "ties"}


def _strip(result: dict) -> dict:
    return {k: v for k, v in result.items() if k not in IGNORED}


def main() -> int:
    r3 = json.loads((HERE / "eval_v2.json").read_text())
    r4 = json.loads((HERE / "eval_r4.json").read_text())

    moved = [k for k, v in r3["results"].items() if _strip(v) != _strip(r4["results"].get(k, {}))]
    moved += [k for k, v in r3["contrasts"].items() if v != r4["contrasts"].get(k)]
    if moved:
        print("STOP: round-3 figures moved:", moved[:10], f"({len(moved)} total)")
        return 1
    print(f"R4.6: {len(r3['results'])} results and {len(r3['contrasts'])} contrasts from round 3 "
          f"reproduce bit-identically\n")

    lat = HERE / "latency_r4.json"
    ratios = {}
    if lat.exists():
        for tag, m in json.loads(lat.read_text())["models"].items():
            ratios[tag] = m["warm_ratio_to_incumbent_median"]

    base = r4["results"]["blind|d50|H_small_prefix"]["by_category"]
    print("R4.3 DECIDING — H_<candidate> − H_small_prefix, blind set, depth 50, useful_recall@5")
    for sfx, tag in CANDIDATES.items():
        c = r4["contrasts"][f"blind|d50|r4_{sfx}_vs_small_hybrid"]["useful_hit5"]
        cats = r4["results"][f"blind|d50|H_{sfx}"]["by_category"]
        gains = [k for k in cats if cats[k]["useful_hit5"] > base[k]["useful_hit5"]]
        ratio = ratios.get(tag)
        need = 0.05 if ratio is None or ratio <= 3 else 0.08 if ratio <= 10 else 0.12
        passed = c["excludes_zero"] and c["point"] >= need and len(gains) >= 2
        print(f"  {tag:14s} {c['point']:+.4f} CI {c['ci95']} up {c['changed_up']} down "
              f"{c['changed_down']}  categories gaining: {len(gains)} {gains}  "
              f"cost ratio {ratio}  need {need:+.2f}  -> {'PASS' if passed else 'fail'}")

    print("\nR4.4 reported — useful_recall@5 and mrr@10, blind set, depth 50")
    for key in sorted(k for k in r4["contrasts"] if k.startswith("blind|d50|r4_")):
        c = r4["contrasts"][key]
        u, m = c["useful_hit5"], c["mrr10"]
        print(f"  {key.split('|')[2]:30s} recall {u['point']:+.4f} {u['ci95']}   "
              f"mrr {m['point']:+.4f} {m['ci95']}")

    print("\nAbsolute, blind set, depth 50")
    for cfg in ["D_small_prefix", "D_small_fp32", "D_granite30", "D_e5small", "D_granite125",
                "H_small_prefix", "H_small_fp32", "H_granite30", "H_e5small", "H_granite125"]:
        a = r4["results"][f"blind|d50|{cfg}"]["ALL"]
        print(f"  {cfg:16s} useful_recall@5 {a['useful_hit5']:.4f}  mrr@10 {a['mrr10']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
