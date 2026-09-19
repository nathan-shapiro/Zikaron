#!/usr/bin/env python
"""Build the M25 sweep corpus once, into a persistent store the sweep can re-query.

**Why this is a separate command from the sweep.** Every parameter M25 tunes — `rrf_k`,
`fusion_depth`, arm weighting, `limit_per_kb` — is applied at *search* time, so none of them
invalidates an index. The expensive half therefore runs exactly once and the grid re-queries it,
which is what makes a sweep of this size affordable at all: the build is minutes and each further
configuration is arithmetic over two already-ranked lists.

The store is deliberately **not** a temporary directory, unlike `m22_response_cap.py`'s. That
harness measured one number and threw the corpus away; this one is the input to a sweep that will
be re-run as the grid and the oracle change, and rebuilding ~4 MB of prose on every iteration would
make the loop too slow to iterate honestly.

Run:  .venv/bin/python experiments/m25_build_sweep_corpus.py <corpus-root> <store-dir> [name]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zikaron.core.config.resolution import resolve
from zikaron.core.knowledge import lifecycle
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.knowledge.indexer.main import build_settings

#: `off` rather than `tracked`: the corpus is a sparse checkout of somebody else's repository, so
#: what git says about it describes their history rather than this measurement, and `tracked` would
#: additionally make the file set depend on how the checkout was made.
GIT_MODE = GitMode.OFF

#: `<corpus-root> <store-dir>`, with the knowledge base's name optional.
_REQUIRED_ARGS = 3


async def main() -> int:
    if len(sys.argv) < _REQUIRED_ARGS:
        print(__doc__)
        return 2
    corpus_root = Path(sys.argv[1]).resolve()
    workspace = Path(sys.argv[2]).resolve()
    name = sys.argv[3] if len(sys.argv) > _REQUIRED_ARGS else "sweep_corpus"
    if not corpus_root.is_dir():
        print(f"not a directory: {corpus_root}")
        return 2

    workspace.mkdir(parents=True, exist_ok=True)
    config = resolve(workspace / "system.toml", workspace / "project.toml")
    store_dir = workspace / ".zikaron"
    # The store's own embedder never runs: nothing here writes a memory, and a knowledge build
    # embeds through the encoder `build_settings` loads. A real one would only add a model load.
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))

    async with await Store.create(store_dir, config, embedder) as store:
        await lifecycle.add(
            store_dir,
            store.connection,
            config,
            lifecycle.AddRequest(
                name=name,
                root=corpus_root,
                description=f"M25 sweep corpus: {corpus_root}",
                git_mode=GIT_MODE,
            ),
        )
        build = await build_settings(config)
        started = time.monotonic()
        refreshed = await lifecycle.refresh(
            store_dir, store.connection, config, name=name, build=build
        )
        elapsed = time.monotonic() - started
        counters = refreshed.result.counters

    print(
        json.dumps(
            {
                # Recorded rather than asserted: a timing quoted without the load it was taken
                # under is an upper bound wearing the clothes of a measurement.
                "load_average_1m": round(os.getloadavg()[0], 2),
                "cpu_count": os.cpu_count(),
                "corpus_root": str(corpus_root),
                "store_dir": str(store_dir),
                "knowledge_base": name,
                "git_mode": GIT_MODE.value,
                "seconds": round(elapsed, 1),
                "files_indexed": counters.files_indexed,
                "bytes_indexed": counters.bytes_indexed,
                "embed_model": config.get_str("embed_model"),
                "chunk_max_tokens": config.get_int("chunk_max_tokens"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
