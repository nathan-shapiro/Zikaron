#!/usr/bin/env python
"""Latency harness. Measures, never estimates.

Four numbers per model:
  warm_embed        single-query embed latency in-process, p50 / p95 / p99, after warmup.
                    Batch size 1 on purpose: the push hook embeds exactly one query.
  warm_e2e          full retrieval path warm: embed query + FTS5 BM25 + vec0 KNN + RRF fuse.
  cold_process      whole-process wall time from `python -c` through interpreter start,
                    imports, model load, embed one query, query the DB, print. This is the
                    number that decides whether the userPromptSubmit hook can be a plain
                    subprocess or must talk to a persistent daemon.
  footprint         on-disk bytes of the model's directory in the fastembed cache.

Usage:  .venv/bin/python latency.py [--reps 60] [--cold-reps 3]
Out:    results/latency.json
"""
import argparse
import json
import os
import pathlib
import shutil
import statistics
import subprocess
import sys
import time

import numpy as np

import retrieval as R

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "latency.json"
PY = str(HERE / ".venv" / "bin" / "python")

CACHE_DIRS = [pathlib.Path("/tmp/fastembed_cache"),
              pathlib.Path(os.environ.get("FASTEMBED_CACHE_PATH", "/nonexistent")),
              pathlib.Path.home() / ".cache" / "fastembed",
              pathlib.Path.home() / ".cache" / "huggingface" / "hub"]

QUERY = "Working on constructing WidgetV2 from our old dict payloads this morning."

COLD_SNIPPET = r"""
import sys, sqlite3, json, numpy as np, sqlite_vec
from fastembed import TextEmbedding
tag, model, qpre = sys.argv[1], sys.argv[2], sys.argv[3]
db = sqlite3.connect(sys.argv[4]); db.enable_load_extension(True)
sqlite_vec.load(db); db.enable_load_extension(False)
emb = TextEmbedding(model_name=model)
v = next(iter(emb.embed([qpre + sys.argv[5]])))
v = (np.array(v, dtype=np.float32)); v /= np.linalg.norm(v)
t = "vec_" + tag.replace("-", "_")
rows = db.execute(f"select rowid, distance from {t} where emb match ? and k=5 order by distance",
                  (v.tobytes(),)).fetchall()
print("COLD_OK", len(rows))
"""


def dir_size(p: pathlib.Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def find_model_dir(model: str):
    slug = model.split("/")[-1].lower()
    org = model.split("/")[0].lower()
    best = None
    for root in CACHE_DIRS:
        if not root.is_dir():
            continue
        for d in root.iterdir():
            n = d.name.lower()
            if slug in n or (org in n and slug.split("-")[0] in n):
                sz = dir_size(d)
                if best is None or sz > best[1]:
                    best = (d, sz)
    return best


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=60)
    ap.add_argument("--cold-reps", type=int, default=3)
    args = ap.parse_args()

    from fastembed import TextEmbedding
    doc = R.load_dataset()
    db = R.connect()
    out = {"host": dict(python=sys.version.split()[0], cpu_count=os.cpu_count()),
           "query": QUERY, "reps": args.reps, "cold_reps": args.cold_reps, "models": {}}

    cold_snippet_path = HERE / "_cold_probe.py"
    cold_snippet_path.write_text(COLD_SNIPPET)

    for tag in ["bge-small", "bge-small-prefix", "bge-large-prefix", "nomic"]:
        model, qpre, _ppre = R.MODELS[tag]
        rec = {"model": model, "query_prefix": qpre}

        emb = TextEmbedding(model_name=model)
        for _ in range(5):                       # warmup
            list(emb.embed([qpre + QUERY]))

        ts = []
        for _ in range(args.reps):
            t0 = time.perf_counter()
            list(emb.embed([qpre + QUERY]))
            ts.append((time.perf_counter() - t0) * 1000)
        rec["warm_embed_ms"] = dict(p50=round(pct(ts, 50), 2), p95=round(pct(ts, 95), 2),
                                    p99=round(pct(ts, 99), 2),
                                    mean=round(statistics.mean(ts), 2),
                                    min=round(min(ts), 2))

        ts = []
        for _ in range(args.reps):
            t0 = time.perf_counter()
            v = np.array(next(iter(emb.embed([qpre + QUERY]))), dtype=np.float32)
            v /= np.linalg.norm(v)
            a = R.bm25(db, QUERY)
            b = R.dense(db, v, tag)
            R.rrf(a, b)[:5]
            ts.append((time.perf_counter() - t0) * 1000)
        rec["warm_e2e_rrf_ms"] = dict(p50=round(pct(ts, 50), 2), p95=round(pct(ts, 95), 2),
                                      mean=round(statistics.mean(ts), 2))

        cold = []
        for _ in range(args.cold_reps):
            t0 = time.perf_counter()
            p = subprocess.run([PY, str(cold_snippet_path), tag, model, qpre,
                                str(R.DB_PATH), QUERY],
                               capture_output=True, text=True)
            dt = (time.perf_counter() - t0) * 1000
            if "COLD_OK" not in p.stdout:
                rec["cold_error"] = (p.stdout + p.stderr)[-600:]
                break
            cold.append(dt)
        if cold:
            rec["cold_process_ms"] = dict(mean=round(statistics.mean(cold), 1),
                                          min=round(min(cold), 1), max=round(max(cold), 1),
                                          runs=[round(c, 1) for c in cold])

        found = find_model_dir(model)
        if found:
            rec["disk"] = dict(path=str(found[0]), bytes=found[1],
                               mb=round(found[1] / 1e6, 1))
        out["models"][tag] = rec
        print(f"{tag:18} embed p50={rec['warm_embed_ms']['p50']:.1f}ms "
              f"p95={rec['warm_embed_ms']['p95']:.1f}ms | e2e p50="
              f"{rec['warm_e2e_rrf_ms']['p50']:.1f}ms | cold="
              f"{rec.get('cold_process_ms', {}).get('mean', 'ERR')}ms | "
              f"disk={rec.get('disk', {}).get('mb', '?')}MB", flush=True)

    # ---- baselines that do not involve an embedder at all
    ts = []
    for _ in range(args.reps):
        t0 = time.perf_counter()
        R.bm25(db, QUERY)[:5]
        ts.append((time.perf_counter() - t0) * 1000)
    out["bm25_only_ms"] = dict(p50=round(pct(ts, 50), 3), p95=round(pct(ts, 95), 3))

    t0 = time.perf_counter()
    p = subprocess.run([PY, "-c",
                        "import sqlite3,sqlite_vec;print('OK')"], capture_output=True, text=True)
    out["cold_interpreter_plus_sqlitevec_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    # ---- reranker cost over 50 pairs, warm
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        ce = TextCrossEncoder(model_name="BAAI/bge-reranker-base")
        mems = doc["memories"][:R.FUSE_DEPTH]
        passages = [R.doc_text(m) for m in mems]
        for _ in range(2):
            list(ce.rerank(QUERY, passages))
        ts = []
        for _ in range(max(5, args.reps // 6)):
            t0 = time.perf_counter()
            list(ce.rerank(QUERY, passages))
            ts.append((time.perf_counter() - t0) * 1000)
        rr = dict(pairs=len(passages), p50=round(pct(ts, 50), 1), p95=round(pct(ts, 95), 1),
                  mean=round(statistics.mean(ts), 1), n=len(ts))
        found = find_model_dir("BAAI/bge-reranker-base")
        if found:
            rr["disk_mb"] = round(found[1] / 1e6, 1)
            rr["disk_path"] = str(found[0])
        out["reranker_bge_reranker_base"] = rr
        print(f"reranker 50 pairs p50={rr['p50']}ms p95={rr['p95']}ms disk={rr.get('disk_mb')}MB")
    except Exception as e:  # noqa: BLE001
        out["reranker_bge_reranker_base"] = {"error": repr(e)}

    total = 0
    for root in CACHE_DIRS:
        if root.is_dir():
            total = max(total, dir_size(root))
    out["fastembed_cache_total_mb"] = round(total / 1e6, 1)
    out["disk_free_gb"] = round(shutil.disk_usage(str(HERE)).free / 1e9, 1)

    OUT.write_text(json.dumps(out, indent=2) + "\n")
    cold_snippet_path.unlink(missing_ok=True)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
