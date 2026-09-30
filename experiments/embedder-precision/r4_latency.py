#!/usr/bin/env python
"""Round 4 cost facts (PREREGISTRATION-R4.md R4.3's cost gate and R4.4): warm single-query embed
p50, cold whole-process start to one embedding, and the ONNX file's size — for the incumbent and
every round-4 arm, in one run on one host, so the ratios the gate uses share a machine and a load.

The host is not idle while this runs (operator, 2026-09-30), so absolute milliseconds here are not
comparable with round 1's or with any budget set on an idle machine. What survives load is the
**ratio**, provided every arm sees the same load: so all models stay loaded and each rep times every
model once, round-robin, and the gate reads the median of per-rep ratios to the incumbent. The
1-minute load average is recorded before and after.

    ../../.venv/bin/python r4_latency.py [--reps 60] [--cold-reps 3]
Out: results/latency_r4.json
"""
import argparse
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time

import retrieval as R
from fastembed import TextEmbedding

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "latency_r4.json"
TAGS = ["bge-small-prefix", "bge-small-fp32-prefix", "granite-30m", "e5-small", "granite-125m"]
QUERY = "Working on constructing WidgetV2 from our old dict payloads this morning."

COLD = r"""
import sys, time
t0 = time.perf_counter()
sys.path.insert(0, sys.argv[1])
import custom_models
from fastembed import TextEmbedding
e = TextEmbedding(model_name=sys.argv[2])
next(iter(e.embed([sys.argv[3]])))
print(f"COLD_MS {(time.perf_counter() - t0) * 1000:.1f}")
"""


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def onnx_bytes(model: TextEmbedding) -> int | None:
    path = getattr(model.model, "_model_dir", None)
    if path is None:
        return None
    return sum(f.stat().st_size for f in pathlib.Path(path).rglob("*.onnx"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=60)
    ap.add_argument("--cold-reps", type=int, default=3)
    args = ap.parse_args()
    out = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "query": QUERY, "reps": args.reps, "models": {}}
    out["loadavg_before"] = os.getloadavg()
    loaded = {t: TextEmbedding(model_name=R.MODELS[t][0]) for t in TAGS}
    for t, emb in loaded.items():
        for _ in range(5):
            list(emb.embed([R.MODELS[t][1] + QUERY]))
    ts = {t: [] for t in TAGS}
    for _ in range(args.reps):
        for t, emb in loaded.items():
            t0 = time.perf_counter()
            list(emb.embed([R.MODELS[t][1] + QUERY]))
            ts[t].append((time.perf_counter() - t0) * 1000)
    cold = {t: [] for t in TAGS}
    for _ in range(args.cold_reps):
        for t in TAGS:
            name, qpre, _ = R.MODELS[t]
            r = subprocess.run([sys.executable, "-c", COLD, str(HERE), name, qpre + QUERY],
                               capture_output=True, text=True, check=True)
            cold[t].append(float(r.stdout.split("COLD_MS")[1]))
    out["loadavg_after"] = os.getloadavg()
    base = ts["bge-small-prefix"]
    for t in TAGS:
        out["models"][t] = dict(
            model=R.MODELS[t][0],
            warm_embed_ms=dict(p50=round(pct(ts[t], 50), 2), p95=round(pct(ts[t], 95), 2)),
            warm_ratio_to_incumbent_median=round(
                statistics.median(a / b for a, b in zip(ts[t], base)), 2),
            cold_whole_process_ms=dict(median=round(statistics.median(cold[t]), 1), all=cold[t]),
            cold_ratio_to_incumbent=round(
                statistics.median(cold[t]) / statistics.median(cold["bge-small-prefix"]), 2),
            onnx_bytes=onnx_bytes(loaded[t]))
        print(t, out["models"][t], flush=True)
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
