#!/usr/bin/env python
"""Twin duel: isolate IDENTIFIER discrimination from TOPICAL retrieval.

Why this exists. In the full sweep, a near-miss query like "constructing WidgetV2 from our old
dict payloads" can be answered correctly *without the model resolving the identifier at all*,
because the WidgetV2 memory is also the one that talks about dict payloads and constructors.
Topic alone is enough. A low displacement rate in the sweep therefore does NOT prove the
embedder can tell V1 from V2 - it may only prove the surrounding prose differs.

This script removes that confound by restricting the contest to the twin pair and by stripping
the query down. Three probes per near-miss pair, per model:

  full   - the real session-opening query vs {gold, hard_neg}. Baseline; topic available.
  bare   - the DISCRIMINATING TOKEN ALONE as the query (e.g. just "WidgetV2"). No topic signal
           whatsoever. If a model is at chance here it is blind to the identifier, full stop.
  neutral- the token embedded in a topic-free carrier sentence ("Tell me about WidgetV2."),
           which is a fairer bare probe because single tokens are out of distribution for a
           sentence embedder.

Metric: duel win rate = fraction of pairs where cos(q, gold) > cos(q, hard_neg). 0.5 is chance.
Also reports the mean cosine MARGIN, because a model can win the duel by a margin so small
that any competing signal in a real ranking will overturn it.

Usage: .venv/bin/python twin_duel.py
Out:   results/twin_duel.json
"""
import json
import pathlib
import statistics

import numpy as np
from fastembed import TextEmbedding

import retrieval as R

HERE = pathlib.Path(__file__).parent
OUT = HERE / "results" / "twin_duel.json"

# The token that is the ONLY legitimate basis for choosing between the twins, per query.
DISCRIMINATOR = {
    "q-c1-01": "WidgetV1", "q-c1-02": "WidgetV2",
    "q-c1-03": "v2.3.1", "q-c1-04": "v2.3.10",
    "q-c1-05": "conftest.py", "q-c1-06": "conf_test.py",
    "q-c1-07": "AUTH_TOKEN", "q-c1-08": "AUTH_TOKEN_V2",
    "q-c1-09": "build.gradle", "q-c1-10": "build.gradle.kts",
    "q-c1-11": "user_id", "q-c1-12": "userId",
    "q-c1-13": "--no-cache", "q-c1-14": "--no-cache-dir",
    "q-c1-15": "staging", "q-c1-16": "staging-2",
    "q-c1-17": "retry_backoff", "q-c1-18": "retry_backoff_ms",
    "q-c1-19": "parse_date", "q-c1-20": "parse_datetime",
    "q-c1-21": "org.example.core.Config", "q-c1-22": "org.example.config.Core",
    "q-c1-23": "DATABASE_URL", "q-c1-24": "DATABASE_URL_RO",
    "q-c1-25": "30 seconds", "q-c1-26": "300 seconds",
    "q-c1-27": "migration 0042", "q-c1-28": "migration 0042_1",
}


def norm(v):
    return v / np.linalg.norm(v)


def main() -> int:
    doc = R.load_dataset()
    by_uuid = {m["uuid"]: m for m in doc["memories"]}
    pairs = [q for q in doc["queries"]
             if q["cat"] == "near_miss" and q["hard_neg"] and q["qid"] in DISCRIMINATOR]

    out = {}
    for tag in ["bge-small", "bge-small-prefix", "bge-large-prefix", "nomic"]:
        model, qpre, ppre = R.MODELS[tag]
        emb = TextEmbedding(model_name=model)

        # passages: gist+content for both twins
        docs, dmap = [], {}
        for q in pairs:
            for u in q["gold"] + q["hard_neg"]:
                if u not in dmap:
                    dmap[u] = len(docs)
                    docs.append(ppre + R.doc_text(by_uuid[u]))
        dv = np.array(list(emb.embed(docs)), dtype=np.float32)
        dv = np.array([norm(v) for v in dv])

        probes = {
            "full": [qpre + q["text"] for q in pairs],
            "bare": [qpre + DISCRIMINATOR[q["qid"]] for q in pairs],
            "neutral": [qpre + f"Tell me about {DISCRIMINATOR[q['qid']]}." for q in pairs],
        }
        res = {}
        for pname, texts in probes.items():
            qv = np.array(list(emb.embed(texts)), dtype=np.float32)
            qv = np.array([norm(v) for v in qv])
            wins, margins, detail = [], [], []
            for i, q in enumerate(pairs):
                sg = float(qv[i] @ dv[dmap[q["gold"][0]]])
                sh = float(qv[i] @ dv[dmap[q["hard_neg"][0]]])
                wins.append(sg > sh)
                margins.append(sg - sh)
                detail.append(dict(qid=q["qid"], token=DISCRIMINATOR[q["qid"]],
                                   cos_gold=round(sg, 4), cos_hard_neg=round(sh, 4),
                                   margin=round(sg - sh, 4), win=bool(sg > sh)))
            res[pname] = dict(
                n=len(pairs),
                win_rate=round(statistics.mean(wins), 4),
                mean_margin=round(statistics.mean(margins), 4),
                median_margin=round(statistics.median(margins), 4),
                mean_abs_margin=round(statistics.mean(abs(m) for m in margins), 4),
                mean_cos_gold=round(statistics.mean(d["cos_gold"] for d in detail), 4),
                mean_cos_hard_neg=round(statistics.mean(d["cos_hard_neg"] for d in detail), 4),
                detail=detail,
            )
            print(f"{tag:18} {pname:8} win_rate={res[pname]['win_rate']:.3f} "
                  f"mean_margin={res[pname]['mean_margin']:+.4f} "
                  f"cos_gold={res[pname]['mean_cos_gold']:.3f} "
                  f"cos_hn={res[pname]['mean_cos_hard_neg']:.3f}", flush=True)
        out[tag] = dict(model=model, probes=res)

    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
