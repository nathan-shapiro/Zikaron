"""When retrieval misses, what did it miss — the document, or the passage inside it?

The headroom measurement established that reordering the candidate pool can recover at most a
sixth of queries, while a third find nothing relevant at any depth. That larger share is a
retrieval failure rather than a ranking one, and it has at least three different causes wanting
three different fixes:

- the right **document** is retrieved but the answering passage is not, because the passage was cut
  into a chunk that is mostly about something else, or split across two chunks — a chunking problem;
- the right document is **never retrieved at all** — an embedding or query-construction problem;
- the answering passage is retrieved, but the oracle names a *different* chunk of the same section
  as truth — an artifact of the oracle rather than a defect in the product.

The three are distinguished by asking, for every query, whether the truth chunk's **file** and its
**section** appear in the ranking even where the truth chunk itself does not.

Usage:

    .venv/bin/python experiments/m26_miss_diagnosis.py <workspace> <kb-name> [per-family]
"""

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from uuid import UUID

import aiosqlite

# Both scripts live in `experiments/`, which the interpreter puts on the path for the one it runs.
import m25_fusion_sweep as m25

from zikaron.core.config.resolution import resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge.database import KnowledgeDatabase

DEPTHS = (5, 20, 50, m25.MAX_DEPTH)


def classify(
    ranking: list[int],
    truth: frozenset[int],
    same_section: frozenset[int],
    paths: dict[int, str],
    truth_paths: set[str],
    *,
    at: int,
) -> str:
    """What this query's outcome at depth `at` is evidence of."""
    window = ranking[:at]
    if any(cid in truth for cid in window):
        return "truth chunk found"
    if any(cid in same_section for cid in window):
        return "same section, different chunk"
    if any(paths.get(cid) in truth_paths for cid in window):
        return "right file, wrong section"
    return "right file never retrieved"


async def main() -> int:
    if len(sys.argv) < 3:  # noqa: PLR2004 — workspace and knowledge-base name
        print(__doc__)
        return 2
    workspace = Path(sys.argv[1]).resolve()
    store_dir = workspace / ".zikaron"
    kb_name = sys.argv[2].lower()
    per_family = int(sys.argv[3]) if len(sys.argv) > 3 else m25.DEFAULT_PER_FAMILY  # noqa: PLR2004

    config = resolve(workspace / "system.toml", workspace / "project.toml")
    async with aiosqlite.connect(store_dir / "memory.db") as memory:
        found = await memory.execute_fetchall(
            "SELECT id FROM knowledge_bases WHERE name = ?", (kb_name,)
        )
    if not found:
        print(f"no knowledge base named {kb_name!r} in {store_dir}")
        return 2

    encoder = await asyncio.to_thread(FastEmbedEncoder.load, config.get_str("embed_model"))
    knowledge = await KnowledgeDatabase.open(store_dir, UUID(str(found[0][0])))
    try:
        db = knowledge.connection
        chunks = await m25.load_chunks(db)
        paths = {c.chunk_id: c.path for c in chunks}
        instrument = m25.Instrument()
        queries = m25.build_queries(chunks, per_family, instrument)
        fetched = await m25.fetch_all(db, queries, encoder, config)
    finally:
        await knowledge.close()

    rrf_k, depth, weight = m25.SHIPPED
    outcomes: dict[int, Counter[str]] = {at: Counter() for at in DEPTHS}
    # How far a truth chunk sits from the nearest retrieved chunk of its own file, in chunk
    # positions: 0 means the file was found and the exact chunk with it, 1 means the neighbouring
    # chunk was returned instead. A tight distribution here says the answer is being cut in half.
    neighbour_distance: Counter[int] = Counter()

    for item in fetched:
        if item.query.family != "heading":
            continue
        ranking = m25.fuse(item, rrf_k=rrf_k, depth=depth, weight=weight)
        truth = item.query.truth
        truth_paths = {paths[cid] for cid in truth if cid in paths}
        same_section = item.query.same_title_bodies | item.query.excluded
        for at in DEPTHS:
            outcomes[at][
                classify(ranking, truth, same_section, paths, truth_paths, at=at)
            ] += 1
        retrieved_same_file = [
            cid for cid in ranking[:20] if paths.get(cid) in truth_paths
        ]
        if retrieved_same_file and not (truth & set(ranking[:20])):
            nearest = min(abs(cid - t) for cid in retrieved_same_file for t in truth)
            neighbour_distance[min(nearest, 10)] += 1

    total = sum(outcomes[DEPTHS[0]].values())
    report = {
        "family": "heading",
        "queries": total,
        "outcomes": {
            f"top{at}": {k: round(v / total, 4) for k, v in sorted(outcomes[at].items())}
            for at in DEPTHS
        },
        "chunk_id_distance_to_nearest_same_file_hit_in_top20": dict(
            sorted(neighbour_distance.items())
        ),
    }
    print(json.dumps(report, indent=2))

    print("\n=== where retrieval actually fails (heading, n=%d) ===" % total, file=sys.stderr)
    for at in DEPTHS:
        row = "  ".join(f"{k}: {v / total:.3f}" for k, v in sorted(outcomes[at].items()))
        print(f"top{at:<4} {row}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
