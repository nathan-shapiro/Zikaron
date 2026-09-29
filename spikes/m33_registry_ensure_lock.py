"""Does a no-op `CREATE TABLE IF NOT EXISTS` ask for the write lock?

Run: `.venv/bin/python spikes/m33_registry_ensure_lock.py`

The question arose from a test: `schema.md` §"`call` is an access log" claims the five read-only
knowledge verbs make the access log's row their call's first and only `memory.db` write, on the
strength of `registry.ensure_table`'s recorded measurement that the no-op `CREATE` "takes no write
lock at all". A held-lock test on `knowledge_list` failed at `store_unavailable` instead.

What this measures, against a real store with a second connection holding the write lock:

1. the statement on the connection the service itself holds
2. the same statement on a connection opened fresh against the same file
3. the `sqlite_master` read that replaced it

`(1)` waits out `busy_timeout` and fails; `(2)` and `(3)` return at once. Throwaway rather than a
test: it needs a five-second wait to say anything, which is not a cost the gate should pay per run.
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.service_fixtures import open_context  # noqa: E402
from zikaron.core.knowledge import registry  # noqa: E402
from zikaron.core.store import ddl  # noqa: E402
from zikaron.core.store.connection import open_connection  # noqa: E402


async def _timed(label: str, work: object) -> None:
    started = time.perf_counter()
    try:
        await work  # type: ignore[misc]
        print(f"{label:<44} OK        in {time.perf_counter() - started:.3f}s")
    except Exception as error:  # noqa: BLE001 — the outcome under measurement.
        print(f"{label:<44} {error} after {time.perf_counter() - started:.3f}s")


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        async with open_context(Path(tmp)) as ctx:
            held = ctx.store.connection
            await registry.ensure(held)
            holder, _inode = await open_connection(
                ctx.store.path, pragmas=ddl.PRAGMAS, existing_only=True
            )
            await holder.execute("BEGIN IMMEDIATE")
            await holder.execute("INSERT INTO meta (key, value) VALUES ('held', '1')")

            fresh, _inode = await open_connection(
                ctx.store.path, pragmas=ddl.PRAGMAS, existing_only=True
            )
            await _timed("the store's own connection, CREATE", held.execute(registry.CREATE_TABLE))
            await _timed("a fresh connection, CREATE", fresh.execute(registry.CREATE_TABLE))
            await _timed(
                "the store's own connection, schema read",
                held.execute_fetchall(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (registry.TABLE_NAME,),
                ),
            )
            await fresh.close()
            await holder.rollback()
            await holder.close()


if __name__ == "__main__":
    asyncio.run(main())
