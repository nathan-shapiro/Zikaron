#!/usr/bin/env python
"""How many real corpora a knowledge search can answer for before the byte cap sheds results.

The cap is enforced against `groups.response_bytes`, which counts the encoded payload **once**.
That denomination is the whole point of this harness: an earlier reading of the same question was
taken while the cap charged for both copies the transport delivers, so its numbers were roughly
double and its conclusion — that three corpora already trip the cap — was an artifact of the
accounting rather than a fact about the answer. Everything printed here is in single-counted
payload bytes, the unit `RESPONSE_MAX_BYTES` is written in.

What it measures, over corpora of this repository's own real text:

1. `response_bytes` and `groups_dropped` for a search across the first *n* corpora, for every *n*,
   so where shedding begins is observed rather than extrapolated.
2. The size of one serialized result, which is what lets a reader predict the crossing for a
   different `limit_per_kb` or snippet cap without rebuilding anything.

Run:  .venv/bin/python experiments/m22_response_cap.py [<query>]

Every corpus is built in a throwaway store under a temporary directory, which is removed
afterwards. Nothing is written to this repository. Building is the slow part — real embedding over
a few megabytes of text — and it runs once per corpus.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zikaron.core.config.resolution import resolve  # noqa: E402
from zikaron.core.indexing.encoder import FastEmbedEncoder  # noqa: E402
from zikaron.core.knowledge import groups, lifecycle  # noqa: E402
from zikaron.core.knowledge.meta import GitMode  # noqa: E402
from zikaron.core.store.embedder import FakeEmbedder  # noqa: E402
from zikaron.core.store.store import Store  # noqa: E402
from zikaron.knowledge.indexer.main import build_settings  # noqa: E402

#: Real trees from this repository, in the order the corpora are added. The first two are the pair
#: the superseded reading was taken over, so its numbers and these are about the same text.
CORPORA = ("design", "reviews", "research", "zikaron/core", ".claude")

#: `off` rather than `tracked`, matching what the superseded reading was taken under: several of
#: these trees hold files that are real corpus content and not yet committed, and a corpus that
#: silently omits them measures something other than the tree it names.
GIT_MODE = GitMode.OFF

#: Vocabulary present in every one of those trees, so no group is empty for want of a hit — an
#: empty group serializes to almost nothing and would understate the crossing point.
DEFAULT_QUERY = "how is a chunk written to the index and what happens when the write fails"

#: What a caller gets when it does not ask, which is the value the crossing point is a fact about.
LIMIT_PER_KB = 5


def _name_of(tree: str) -> str:
    """A knowledge-base name for one tree, since a name may not carry a path separator."""
    return tree.replace("/", "-")


async def _build(store_dir, store, config, trees):
    """Register and build every corpus, timing each build."""
    build = await build_settings(config)
    repository = Path(__file__).resolve().parent.parent
    report = []
    for tree in trees:
        await lifecycle.add(
            store_dir,
            store.connection,
            config,
            lifecycle.AddRequest(
                name=_name_of(tree),
                root=repository / tree,
                description=f"{tree} as it stands in this repository",
                git_mode=GIT_MODE,
            ),
        )
        started = time.monotonic()
        refreshed = await lifecycle.refresh(
            store_dir, store.connection, config, name=_name_of(tree), build=build
        )
        counters = refreshed.result.counters
        report.append(
            {
                "knowledge_base": _name_of(tree),
                "seconds": round(time.monotonic() - started, 1),
                "files_indexed": counters.files_indexed,
                "bytes_indexed": counters.bytes_indexed,
            }
        )
        print(f"built {report[-1]}", flush=True)
    return report


async def _measure(store_dir, store, config, trees, query):
    """Search the first *n* corpora, for every *n*, and report what the cap did."""
    encoder = await asyncio.to_thread(FastEmbedEncoder.load, config.get_str("embed_model"))
    rows = []
    for count in range(1, len(trees) + 1):
        response = await groups.search_all(
            store_dir,
            store.connection,
            config,
            groups.SearchRequest(
                text=query, limit_per_kb=LIMIT_PER_KB, names=[_name_of(t) for t in trees[:count]]
            ),
            encoder=encoder,
        )
        # Measured off the response's own payload rather than by re-serializing each result, so
        # what is counted here is the same object the cap was applied to.
        payload = response.payload()
        sizes = [
            len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            for group in payload["groups"]
            for result in group.get("results", ())
        ]
        rows.append(
            {
                "corpora": count,
                "response_bytes": groups.response_bytes(response),
                "groups_dropped": response.groups_dropped,
                "results_served": len(sizes),
                "result_bytes_min": min(sizes, default=0),
                "result_bytes_median": sorted(sizes)[len(sizes) // 2] if sizes else 0,
                "result_bytes_max": max(sizes, default=0),
            }
        )
        print(f"searched {rows[-1]}", flush=True)
    return rows


async def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    workspace = Path(tempfile.mkdtemp(prefix="zikaron-m22-cap-"))
    try:
        config = resolve(workspace / "system.toml", workspace / "project.toml")
        store_dir = workspace / ".zikaron"
        # The store's own embedder never runs here: a knowledge search embeds its query with the
        # encoder passed to `search_all`, and no memory is written. A real one would only add a
        # model load to a harness that already pays for one.
        embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
        async with await Store.create(store_dir, config, embedder) as store:
            builds = await _build(store_dir, store, config, CORPORA)
            searches = await _measure(store_dir, store, config, CORPORA, query)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    print(
        json.dumps(
            {
                # Recorded rather than asserted: a timing quoted without the load it was taken
                # under is an upper bound wearing the clothes of a measurement.
                "load_average_1m": round(os.getloadavg()[0], 2),
                "cpu_count": os.cpu_count(),
                "denomination": "single-counted payload bytes, as groups.response_bytes counts",
                "git_mode": GIT_MODE.value,
                "limit_per_kb": LIMIT_PER_KB,
                "snippet_max_chars": config.get_int("knowledge_snippet_max_chars"),
                "response_max_bytes": groups.RESPONSE_MAX_BYTES,
                "query": query,
                "builds": builds,
                "searches": searches,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
