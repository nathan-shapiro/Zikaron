#!/usr/bin/env python
"""True cost of the extracted-`tokens` column (review MAJOR 7).

Round 1 quoted only `wall_seconds_all_queries` (0.119 s either way) and called the cost
"negligible". That excluded extraction, index creation, database growth and write/amend
maintenance - i.e. all the costs the column actually has, since it is a WRITE-side feature.

Measured here, on the real substrate:
  * **regex extraction time** per memory, alone (p50/p95).
  * **insert p50/p95** for a full memory write transaction, with and without the tokens path.
    One transaction per memory, because that is what a Zikaron write is - not a bulk load.
  * **amend p50/p95**, because D6/D11 make amendment a hot-path operation. FTS5 has no in-place
    update, so an amend is delete + reinsert.
  * **on-disk bytes**, per table and per FTS shadow table via `dbstat` where available, plus the
    honest fallback of whole-file size on two separately built databases.

Usage: .venv/bin/python tokens_cost.py [--trials 3]
Out:   results/tokens_cost.json

NOISE WARNING, learned the hard way. These timings are dominated by `fsync`, not by the extra
work, and they move ~30 % between runs on an otherwise idle box: a first run gave insert p50
2.055 ms baseline, a second gave 1.596 ms. Absolute figures are therefore not quotable to three
digits. What IS stable is the paired DELTA within a single trial, since both databases are built
back-to-back under the same conditions - so the script runs the whole pair several times and
reports the per-trial deltas and their median.
"""
import argparse
import json
import pathlib
import sqlite3
import statistics
import sys
import time

import retrieval as R
import retrieval2 as R2

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "tokens_cost.json"
REPS = 5


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1))))
    return xs[i]


def ms(x):
    return round(x * 1000, 4)


def have_dbstat(db) -> bool:
    try:
        db.execute("select * from dbstat limit 1").fetchone()
        return True
    except sqlite3.OperationalError:
        return False


def build_variant(path: pathlib.Path, mems: list, with_tokens: bool) -> dict:
    """Build a database with exactly the tables a deployment would have. Time each write."""
    if path.exists():
        path.unlink()
    db = R.connect(path)
    if with_tokens:
        db.executescript(
            'create table mem(rowid integer primary key, uuid text, gist text, content text,'
            ' tokens text);'
            'create virtual table fts using fts5(gist, content, tokens,'
            f' tokenize="{R2.TOKENIZE_TOK}");')
    else:
        db.executescript(
            'create table mem(rowid integer primary key, uuid text, gist text, content text);'
            'create virtual table fts using fts5(gist, content,'
            f' tokenize="{R2.TOKENIZE_TEXT}");')

    insert_ms, extract_ms = [], []
    for rep in range(REPS):
        for i, m in enumerate(mems, start=1):
            rid = rep * 10000 + i
            raw = m["gist"] + " " + m["content"]
            if with_tokens:
                t0 = time.perf_counter()
                tok = R2.extract_variant_str(raw, dup=True)
                extract_ms.append(time.perf_counter() - t0)
            t0 = time.perf_counter()
            if with_tokens:
                db.execute("insert into mem values (?,?,?,?,?)",
                           (rid, m["uuid"] + str(rep), m["gist"], m["content"], tok))
                db.execute("insert into fts(rowid, gist, content, tokens) values (?,?,?,?)",
                           (rid, m["gist"], m["content"], tok))
            else:
                db.execute("insert into mem values (?,?,?,?)",
                           (rid, m["uuid"] + str(rep), m["gist"], m["content"]))
                db.execute("insert into fts(rowid, gist, content) values (?,?,?)",
                           (rid, m["gist"], m["content"]))
            db.commit()
            insert_ms.append(time.perf_counter() - t0)

    # ---- amend: FTS5 has no in-place update, so delete + reinsert, in one transaction
    amend_ms = []
    for rep in range(REPS):
        for i, m in enumerate(mems, start=1):
            rid = i
            new_content = m["content"] + " Amended: the workaround no longer applies."
            raw = m["gist"] + " " + new_content
            t0 = time.perf_counter()
            if with_tokens:
                tok = R2.extract_variant_str(raw, dup=True)
                db.execute("update mem set content=?, tokens=? where rowid=?",
                           (new_content, tok, rid))
                db.execute("delete from fts where rowid=?", (rid,))
                db.execute("insert into fts(rowid, gist, content, tokens) values (?,?,?,?)",
                           (rid, m["gist"], new_content, tok))
            else:
                db.execute("update mem set content=? where rowid=?", (new_content, rid))
                db.execute("delete from fts where rowid=?", (rid,))
                db.execute("insert into fts(rowid, gist, content) values (?,?,?)",
                           (rid, m["gist"], new_content))
            db.commit()
            amend_ms.append(time.perf_counter() - t0)

    db.execute("vacuum")
    sizes = {}
    if have_dbstat(db):
        for t in ("mem", "fts"):
            sizes[t] = R2.table_bytes(db, t)
        rows = db.execute("select name, sum(pgsize) from dbstat group by name").fetchall()
        sizes["_per_object"] = {n: int(b or 0) for n, b in rows}
    page_count = db.execute("pragma page_count").fetchone()[0]
    page_size = db.execute("pragma page_size").fetchone()[0]
    db.close()

    return dict(
        with_tokens=with_tokens, n_writes=len(insert_ms), reps=REPS,
        insert_ms=dict(p50=ms(pct(insert_ms, 50)), p95=ms(pct(insert_ms, 95)),
                       mean=ms(statistics.mean(insert_ms))),
        amend_ms=dict(p50=ms(pct(amend_ms, 50)), p95=ms(pct(amend_ms, 95)),
                      mean=ms(statistics.mean(amend_ms))),
        extract_ms=(dict(p50=ms(pct(extract_ms, 50)), p95=ms(pct(extract_ms, 95)),
                         mean=ms(statistics.mean(extract_ms))) if extract_ms else None),
        file_bytes=path.stat().st_size, page_count=page_count, page_size=page_size,
        table_bytes=sizes,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3,
                    help="how many times to build BOTH databases; deltas are paired within a trial")
    args = ap.parse_args()
    doc = R.load_dataset()
    mems = doc["memories"]

    def d(a, b):
        return round(100.0 * (a - b) / b, 1) if b else None

    trials = []
    for t in range(args.trials):
        base = build_variant(HERE / "cost_base.db", mems, with_tokens=False)
        tok = build_variant(HERE / "cost_tok.db", mems, with_tokens=True)
        trials.append(dict(
            trial=t, baseline=base, with_tokens=tok,
            deltas=dict(
                insert_p50_ms=round(tok["insert_ms"]["p50"] - base["insert_ms"]["p50"], 4),
                insert_p95_ms=round(tok["insert_ms"]["p95"] - base["insert_ms"]["p95"], 4),
                amend_p50_ms=round(tok["amend_ms"]["p50"] - base["amend_ms"]["p50"], 4),
                amend_p95_ms=round(tok["amend_ms"]["p95"] - base["amend_ms"]["p95"], 4),
                insert_p50_pct=d(tok["insert_ms"]["p50"], base["insert_ms"]["p50"]),
                amend_p50_pct=d(tok["amend_ms"]["p50"], base["amend_ms"]["p50"]),
                file_bytes=tok["file_bytes"] - base["file_bytes"],
                file_pct=d(tok["file_bytes"], base["file_bytes"]),
                fts_bytes=(tok["table_bytes"].get("fts", 0) - base["table_bytes"].get("fts", 0)),
                fts_pct=(d(tok["table_bytes"]["fts"], base["table_bytes"]["fts"])
                         if tok["table_bytes"].get("fts") and base["table_bytes"].get("fts")
                         else None),
            )))
        print(f"trial {t}: " + json.dumps(trials[-1]["deltas"]), flush=True)

    keys = list(trials[0]["deltas"])
    median = {k: (round(statistics.median([tr["deltas"][k] for tr in trials]), 4)
                  if all(isinstance(tr["deltas"][k], (int, float)) for tr in trials) else None)
              for k in keys}
    spread = {k: [min(tr["deltas"][k] for tr in trials), max(tr["deltas"][k] for tr in trials)]
              for k in keys if all(isinstance(tr["deltas"][k], (int, float)) for tr in trials)}
    absolutes = {
        "baseline_insert_p50_ms": [tr["baseline"]["insert_ms"]["p50"] for tr in trials],
        "baseline_amend_p50_ms": [tr["baseline"]["amend_ms"]["p50"] for tr in trials],
        "tokens_insert_p50_ms": [tr["with_tokens"]["insert_ms"]["p50"] for tr in trials],
        "tokens_amend_p50_ms": [tr["with_tokens"]["amend_ms"]["p50"] for tr in trials],
        "extract_p50_ms": [tr["with_tokens"]["extract_ms"]["p50"] for tr in trials],
        "extract_p95_ms": [tr["with_tokens"]["extract_ms"]["p95"] for tr in trials],
    }

    # ---- token text volume: how much extra text the column stores
    raw_chars = sum(len(m["gist"]) + len(m["content"]) for m in mems)
    dup_chars = sum(len(R2.extract_variant_str(m["gist"] + " " + m["content"], dup=True))
                    for m in mems)
    nodup_chars = sum(len(R2.extract_variant_str(m["gist"] + " " + m["content"], dup=False))
                      for m in mems)

    # ---- index bytes inside the single factorial database, for a per-variant comparison
    fx = {}
    db2 = R.connect(HERE / "index_v2.db") if (HERE / "index_v2.db").exists() else None
    if db2 is not None and have_dbstat(db2):
        for t in list(R2.FTS_TABLES) + ["mem2"]:
            fx[t] = R2.table_bytes(db2, t)
        db2.close()

    out = dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        n_memories=len(mems), reps_per_memory=REPS, trials=args.trials,
        median_deltas=median, delta_range_across_trials=spread,
        absolute_p50_across_trials=absolutes,
        per_trial=trials,
        token_text_volume=dict(
            source_chars=raw_chars, tokens_dup_chars=dup_chars, tokens_nodup_chars=nodup_chars,
            dup_pct_of_source=round(100.0 * dup_chars / raw_chars, 1),
            nodup_pct_of_source=round(100.0 * nodup_chars / raw_chars, 1)),
        factorial_index_bytes=fx,
        notes=[
            "One commit per memory: a Zikaron write is a transaction, not a bulk load.",
            "Amend is delete+reinsert because FTS5 has no in-place update.",
            "Sizes measured after VACUUM on a freshly built database; they are deterministic.",
            f"{REPS} writes per memory, so each p95 is over {len(mems)*REPS} transactions.",
            "TIMINGS ARE FSYNC-DOMINATED and move ~30% between runs. Quote the paired median "
            "delta and the across-trial range, never a single absolute figure.",
        ],
    )
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print("\nmedian deltas: " + json.dumps(median))
    print("delta range:   " + json.dumps(spread))
    print("token volume:  " + json.dumps(out["token_text_volume"]))
    print(f"wrote {OUT}")
    for p in ("cost_base.db", "cost_tok.db"):
        (HERE / p).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
