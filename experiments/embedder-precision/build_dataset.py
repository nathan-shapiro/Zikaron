#!/usr/bin/env python
"""Assemble dataset_src/*.py into a single auditable dataset.json.

Deterministic: uuids are UUID5 over a fixed namespace and the memory's stable authoring key,
so re-running produces byte-identical output and ids are stable across runs.

Usage:  .venv/bin/python build_dataset.py
Output: dataset.json
"""
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from dataset_src import cat1_near_miss, cat2345_traps, distractors_a, distractors_b  # noqa: E402

# Fixed namespace so uuids never change between runs.
NS = uuid.UUID("6f1d2c3e-4a5b-5c6d-8e9f-0a1b2c3d4e5f")

OUT = pathlib.Path(__file__).parent / "dataset.json"


def main() -> int:
    mems = []
    seen = set()
    for mod in (cat1_near_miss, cat2345_traps, distractors_a, distractors_b):
        for m in mod.MEMORIES:
            if m["key"] in seen:
                raise SystemExit(f"duplicate memory key: {m['key']}")
            seen.add(m["key"])
            mems.append(dict(
                uuid=str(uuid.uuid5(NS, m["key"])),
                key=m["key"],
                cat=m["cat"],
                gist=m["gist"].strip(),
                content=m["content"].strip(),
            ))

    by_key = {m["key"]: m["uuid"] for m in mems}

    queries = []
    qseen = set()
    for mod in (cat1_near_miss, cat2345_traps):
        for q in mod.QUERIES:
            if q["qid"] in qseen:
                raise SystemExit(f"duplicate qid: {q['qid']}")
            qseen.add(q["qid"])
            for k in list(q["gold"]) + list(q.get("hard_neg") or []):
                if k not in by_key:
                    raise SystemExit(f"{q['qid']} references unknown memory key {k!r}")
            queries.append(dict(
                qid=q["qid"],
                cat=q["cat"],
                text=q["text"].strip(),
                gold=[by_key[k] for k in q["gold"]],
                gold_keys=list(q["gold"]),
                hard_neg=[by_key[k] for k in (q.get("hard_neg") or [])],
                hard_neg_keys=list(q.get("hard_neg") or []),
            ))

    # Sanity: no distractor is ever gold; every gold memory exists exactly once.
    gold_keys = {k for q in queries for k in q["gold_keys"]}
    cat_of = {m["key"]: m["cat"] for m in mems}
    bad = [k for k in gold_keys if cat_of[k] == "distractor"]
    if bad:
        raise SystemExit(f"distractors used as gold: {bad}")

    doc = dict(
        schema_version=1,
        note=("Synthetic tribal-knowledge retrieval eval for Zikaron. See README.md. "
              "uuid = uuid5(fixed-ns, key) so ids are stable across rebuilds."),
        n_memories=len(mems),
        n_queries=len(queries),
        memories=mems,
        queries=queries,
    )
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

    from collections import Counter
    print(f"wrote {OUT}")
    print(f"memories: {len(mems)}  ->", dict(Counter(m['cat'] for m in mems)))
    print(f"queries:  {len(queries)} ->", dict(Counter(q['cat'] for q in queries)))
    print(f"gold memories referenced: {len(gold_keys)}")
    print(f"queries with >=1 hard negative: {sum(1 for q in queries if q['hard_neg'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
