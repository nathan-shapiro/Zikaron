"""What the four search counters cost a search, in milliseconds.

Run it:

    .venv/bin/python experiments/m24_counter_write_cost.py

A search of one corpus now ends in a small write transaction — four `UPDATE`s in `meta` — where it
used to end in nothing. That is a write on the latency path §6.1 exists to protect, so the size of
it is a number rather than an intuition. Two figures are taken: the write against an idle database,
which is the ordinary case, and the write against a database whose writer lock is held, which is
the case the timeout is dropped to zero for.

The comparison to hold it against is this project's own: a knowledge search measured at **16-17 ms**
including the query embedding, and opening one corpus at **p50 1.32 ms**. Both were taken on a
machine that was not idle, and so is this.
"""

import asyncio
import statistics
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from zikaron.core.config.resolution import resolve
from zikaron.core.knowledge import ddl, lifecycle
from zikaron.core.knowledge.counters import SearchTally, record_search
from zikaron.core.store.connection import open_connection
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store

_ROUNDS = 50


async def _timed(connection: object, rounds: int) -> list[float]:
    samples: list[float] = []
    for index in range(rounds):
        started = time.perf_counter()
        await record_search(connection, SearchTally(results=index % 6, stale=index % 3))  # type: ignore[arg-type]
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def _report(label: str, samples: list[float]) -> None:
    print(
        f"{label:<28}p50 {statistics.median(samples):6.3f} ms   "
        f"min {min(samples):6.3f}   max {max(samples):6.3f}   n={len(samples)}"
    )


async def _run() -> None:
    with TemporaryDirectory() as scratch:
        root = Path(scratch)
        corpus = root / "docs"
        corpus.mkdir()
        (corpus / "a.md").write_text("a line\n", encoding="utf-8")
        config = resolve(root / "system.toml", root / "project.toml")
        store_dir = root / ".zikaron"
        embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
        async with await Store.create(store_dir, config, embedder) as store:
            created = await lifecycle.add(
                store_dir,
                store.connection,
                config,
                lifecycle.AddRequest(
                    name="docs", root=corpus, description="a corpus", home=root / "not-home"
                ),
            )
        connection, _inode = await open_connection(
            created.database_path, pragmas=ddl.PRAGMAS, existing_only=True
        )
        holder, _held = await open_connection(
            created.database_path, pragmas=ddl.PRAGMAS, existing_only=True
        )
        try:
            _report("idle database", await _timed(connection, _ROUNDS))
            await holder.execute("BEGIN IMMEDIATE")
            await holder.execute("INSERT INTO meta (key, value) VALUES ('held', '1')")
            _report("writer lock held", await _timed(connection, _ROUNDS))
            await holder.rollback()
        finally:
            await holder.close()
            await connection.close()


if __name__ == "__main__":
    asyncio.run(_run())
