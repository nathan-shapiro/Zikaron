"""Does the first retrieval stage leave a reranker anything to do?

A reranker reorders a candidate set that hybrid fusion has already chosen. It can therefore only
help where fusion **found** the right passage and **mis-ordered** it. If the answer is at rank 1
whenever it is present at all, a reranker is theatre; if the answer is routinely at rank 8 of a
pool of 20, a reranker is exactly the instrument for it.

This is measurable directly, and the arithmetic is tight enough to be a ceiling rather than an
estimate:

- **The floor is `hit@5` post-cap**, which is what a caller receives today.
- **The ceiling is `hit@N` pre-cap**, for the `N` a reranker would rescore. A perfect reranker puts
  truth at rank 1 of its rescored window, where the per-file cap cannot evict it, so every query
  whose truth is inside the window becomes a post-cap hit and no query outside it can.
- **The difference is the entire headroom** available to any reranker at that `N`, no matter how
  good the model.

So a small gap kills the within-corpus stage before any model is loaded or any relevance label is
written, and a large gap is the precondition that makes the rest of the milestone worth running.

`M25`'s heading exclusions are applied throughout, via its own `fuse`: the chunk physically holding
a heading line, and the heading chunks of identically-titled sections elsewhere, both contain the
query verbatim and neither is truth.

Usage:

    .venv/bin/python experiments/m26_headroom.py <workspace> <kb-name> [per-family]
"""

import asyncio
import json
import statistics
import sys
from pathlib import Path
from uuid import UUID

import aiosqlite

# Both scripts live in `experiments/`, which the interpreter puts on the path for the one it runs.
import m25_fusion_sweep as m25

from zikaron.core.config.resolution import resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge.database import KnowledgeDatabase

#: Where truth is looked for. The first entries describe what a caller sees; the later ones are the
#: windows a reranker could plausibly rescore, and `MAX_DEPTH` is the whole fused pool.
DEPTHS = (1, 3, 5, 10, 20, 30, 50, 100, 200, m25.MAX_DEPTH)

#: The windows a reranker might be given, for the headroom table. Costed at roughly 52 ms per
#: candidate per corpus, so the largest is stated to show the shape rather than to be proposed.
WINDOWS = (10, 20, 50)


def rank_of(ranking: list[int], truth: frozenset[int]) -> int | None:
    """Where truth first appears, counting from 1, or `None` if it is not in the pool at all."""
    for position, chunk_id in enumerate(ranking, start=1):
        if chunk_id in truth:
            return position
    return None


def summarise(family: str, rows: list[dict[str, object]]) -> dict[str, object]:
    """One family's hit curve, its post-cap floor, and the headroom each window would offer."""
    n = len(rows)
    hits = {depth: sum(int(row[f"hit@{depth}"]) for row in rows) / n for depth in DEPTHS}
    capped_hit5 = sum(int(row["hit@5_capped"]) for row in rows) / n
    found = [int(row["rank"]) for row in rows if row["rank"] is not None]
    return {
        "family": family,
        "queries": n,
        "hit_at": hits,
        "hit5_capped": capped_hit5,
        "truth_in_pool": len(found) / n,
        "rank_when_found": {
            "median": statistics.median(found) if found else None,
            "mean": statistics.fmean(found) if found else None,
            "p90": sorted(found)[min(len(found) - 1, int(0.9 * len(found)))] if found else None,
        },
        # The whole point of the run: what a perfect reranker over this window could add to what a
        # caller receives today. Negative is impossible by construction and would mean the cap is
        # evicting truth that fusion had already placed in the top five.
        "headroom": {
            window: round(hits[window] - capped_hit5, 4)
            for window in WINDOWS
            if window in hits
        },
    }


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
    by_family: dict[str, list[dict[str, object]]] = {}
    for item in fetched:
        ranking = m25.fuse(item, rrf_k=rrf_k, depth=depth, weight=weight)
        truth = item.query.truth
        row: dict[str, object] = {
            "rank": rank_of(ranking, truth),
            "hit@5_capped": m25.hit_at(
                m25.capped(ranking, paths, limit=m25.LIMIT_PER_KB), truth, at=m25.LIMIT_PER_KB
            ),
        }
        for probe in DEPTHS:
            row[f"hit@{probe}"] = m25.hit_at(ranking, truth, at=probe)
        by_family.setdefault(item.query.family, []).append(row)

    report = {
        "shipped_cell": {"rrf_k": rrf_k, "fusion_depth": depth, "dense_weight": weight},
        "chunks": len(chunks),
        "limit_per_kb": m25.LIMIT_PER_KB,
        "max_chunks_per_file": m25.MAX_CHUNKS_PER_FILE,
        "families": [summarise(family, rows) for family, rows in sorted(by_family.items())],
    }
    print(json.dumps(report, indent=2))

    print("\n=== headroom: what a perfect reranker over a window could add to hit@5 ===", file=sys.stderr)
    for family in report["families"]:
        bars = "  ".join(f"N={w}: +{gain:.4f}" for w, gain in family["headroom"].items())
        print(
            f"{family['family']:<12} hit5_capped {family['hit5_capped']:.4f}   {bars}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
