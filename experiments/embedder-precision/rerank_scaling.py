#!/usr/bin/env python
"""How reranker cost scales with candidate count and passage length (review MAJOR 14).

Round 1 measured `bge-reranker-base` at exactly one operating point - 50 unchunked gist+content
pairs - and then wrote a conclusion broad enough to sound like "cross-encoder reranking is
rejected". The review is right that this does not generalise. Rather than argue about it, measure
the two cheapest generalisations the review named: FEWER candidates and GIST-ONLY passages.

Predeclared budget (PREREGISTRATION.md 5.4): p95 <= 200 ms for the whole rerank stage on the push
path, ~20x the measured warm hybrid path.

Usage: .venv/bin/python rerank_scaling.py
Out:   results/rerank_scaling.json

Run it with nothing else competing for CPU; it is a latency measurement.
"""
import json
import os
import pathlib
import statistics
import sys
import time

import retrieval as R

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "rerank_scaling.json"
CANDS = [5, 10, 25, 50]
REPS = 7
QUERY = "the cache warmer path keeps returning stale objects after a write"


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1))))]


def main() -> int:
    doc = R.load_dataset()
    mems = doc["memories"]
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    ce = TextCrossEncoder(model_name="BAAI/bge-reranker-base")

    modes = {
        "gist_content": [R.doc_text(m, "gist_content") for m in mems],
        "gist_only": [R.doc_text(m, "gist_only") for m in mems],
    }
    list(ce.rerank(QUERY, modes["gist_only"][:2]))   # warm up

    out = dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        model="BAAI/bge-reranker-base", cpu_count=os.cpu_count(),
        reps=REPS, budget_p95_ms=200, query=QUERY, results={},
    )
    for mode, texts in modes.items():
        chars = round(statistics.mean(len(t) for t in texts), 1)
        for n in CANDS:
            cand = texts[:n]
            times = []
            for _ in range(REPS):
                t0 = time.perf_counter()
                list(ce.rerank(QUERY, cand))
                times.append((time.perf_counter() - t0) * 1000)
            key = f"{mode}|{n}"
            p50, p95 = pct(times, 50), pct(times, 95)
            out["results"][key] = dict(
                mode=mode, n_pairs=n, mean_passage_chars=chars,
                p50_ms=round(p50, 1), p95_ms=round(p95, 1),
                ms_per_pair=round(p50 / n, 1),
                within_200ms_budget=bool(p95 <= 200),
            )
            print(f"{key:22} p50={p50:8.1f}ms p95={p95:8.1f}ms  {p50/n:6.1f} ms/pair  "
                  f"budget_ok={p95 <= 200}", flush=True)

    ok = [k for k, v in out["results"].items() if v["within_200ms_budget"]]
    out["operating_points_within_budget"] = ok
    out["conclusion_scope"] = (
        "Measured for BAAI/bge-reranker-base on this CPU only. Operating points within the "
        "predeclared 200 ms p95 push-path budget: " + (", ".join(ok) if ok else "none") + ". "
        "Nothing here measures a smaller reranker, a GPU, chunked passages, or the pull path, "
        "where a multi-second cost may well be acceptable.")
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print("\n" + out["conclusion_scope"])
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
