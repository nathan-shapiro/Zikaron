"""Probe: what a long request, a killed service and a frozen service do to other clients."""

import asyncio
import os
import signal
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from contextlib import closing
from pathlib import Path

from zikaron.mcp.connection import ServiceConnection

PROJ = Path(sys.argv[1])
SRC = (
    Path(sys.argv[2]) / ".zikaron/memory.db"
    if len(sys.argv) > 2
    else Path.home() / "zikaron-m34-replay/replay/.zikaron/memory.db"
)
PHASE_D_SECONDS = 20.0


def copy_store() -> None:
    (PROJ / ".zikaron").mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
    d = sqlite3.connect(PROJ / ".zikaron/memory.db")
    s.backup(d)
    d.close()
    s.close()


def service_pid() -> int | None:
    out = subprocess.run(
        ["pgrep", "-f", f"service.main .* {PROJ}/.zikaron"], capture_output=True, text=True
    ).stdout.split()
    return int(out[0]) if out else None


async def call(conn: ServiceConnection, method: str, params: dict, kind: str = "mcp") -> str:
    t = time.monotonic()
    try:
        r = await conn.request(method, params, envelope=conn.envelope(kind=kind))
        tag = "err:" + str(r["error"].get("message"))[:60] if "error" in r else "ok"
    except Exception as e:  # noqa: BLE001
        tag = f"{type(e).__name__}: {str(e)[:90]}"
    return f"{time.monotonic() - t:6.2f}s {method:20s} {tag}"


def _last_event_id() -> int:
    with closing(sqlite3.connect(f"file:{PROJ}/.zikaron/memory.db?mode=ro", uri=True)) as db:
        return int(db.execute("SELECT coalesce(max(id), 0) FROM event").fetchone()[0])


def _logged_refusals(since: int) -> Counter[tuple[str, str]]:
    """The access log's view of the same phase: rows past `since`, by method and outcome."""
    with closing(sqlite3.connect(f"file:{PROJ}/.zikaron/memory.db?mode=ro", uri=True)) as db:
        rows = db.execute(
            "SELECT json_extract(detail, '$.method'), coalesce(json_extract(detail, "
            "'$.error_code'), 'ok') FROM event WHERE kind = 'call' AND id > ?",
            (since,),
        ).fetchall()
    return Counter((str(method), str(code)) for method, code in rows)


async def _answer(conn: ServiceConnection, method: str, params: dict, kind: str = "mcp") -> dict:
    return await conn.request(method, params, envelope=conn.envelope(kind=kind))


async def phase_d(primary: ServiceConnection, consolidator: ServiceConnection) -> None:
    """`next_group` and `apply_merge` against concurrent `search` and `surface`.

    The traffic the read retry exists for, which a plan alone no longer produces. Counted from the
    responses the probe receives, per method; the access log's count is printed beside it as its
    undercount, since a read refused at a held lock drops its own `call` row.
    """
    print("\n== D: serves and merges against concurrent reads ==")
    since = _last_event_id()
    received: Counter[tuple[str, str]] = Counter()
    stop = asyncio.Event()

    async def consolidate() -> None:
        while not stop.is_set():
            served = await _answer(consolidator, "memory_next_group", {}, kind="consolidator")
            result = served.get("result", {})
            if not isinstance(result, dict) or "group_id" not in result:
                break
            members = [
                {"uuid": row["uuid"], "expected_version": row["expected_version"]}
                for row in result["journal_entries"]
            ]
            anchor = result.get("anchor")
            if anchor:
                verb, params = "memory_apply_merge", {
                    "group_id": result["group_id"],
                    "target": {"uuid": anchor["uuid"], "expected_version": anchor["expected_version"]},
                    "gist": anchor["gist"],
                    "content": anchor["content"],
                    "absorb": members,
                }
            else:
                verb, params = "memory_apply_discard", {
                    "group_id": result["group_id"],
                    "absorb": members,
                    "reason": "probe",
                }
            answered = await _answer(consolidator, verb, params, kind="consolidator")
            received[(verb, _outcome(answered))] += 1

    async def read(method: str, key: str) -> None:
        # A connection of its own: one client connection's requests are answered in order, so
        # readers sharing one would never overlap each other or the consolidator.
        reader = ServiceConnection(PROJ)
        while not stop.is_set():
            answered = await _answer(reader, method, {key: "timestamps ticks drift"})
            received[(method, _outcome(answered))] += 1

    del primary
    writer = asyncio.create_task(consolidate())
    readers = [
        asyncio.create_task(read(method, key))
        for method, key in (("memory_search", "query"), ("memory_surface", "prompt")) * 2
    ]
    await asyncio.sleep(PHASE_D_SECONDS)
    stop.set()
    await asyncio.gather(writer, *readers, return_exceptions=True)
    print("  received:", dict(sorted(received.items())))
    print("  logged:  ", dict(sorted(_logged_refusals(since).items())))


def _outcome(answered: dict) -> str:
    error = answered.get("error")
    return "ok" if error is None else str(error.get("code"))


async def main() -> None:
    copy_store()
    primary = ServiceConnection(PROJ)
    consolidator = ServiceConnection(PROJ)
    print("warm:", await call(primary, "memory_search", {"query": "timestamps"}))
    print("pid", service_pid())

    print("\n== A: plan_groups (10 s client timeout) with a second client searching ==")
    plan = asyncio.create_task(call(consolidator, "memory_plan_groups", {}, kind="consolidator"))
    for _ in range(8):
        await asyncio.sleep(2)
        print("  concurrent:", await call(primary, "memory_search", {"query": "ticks"}))
    print("  plan:", await plan)
    for _ in range(3):
        print("  after:", await call(primary, "memory_search", {"query": "ticks"}))
        print(
            "  after (consolidator conn):",
            await call(consolidator, "memory_next_group", {}, kind="consolidator"),
        )

    await phase_d(primary, consolidator)

    print("\n== B: service killed under a held connection ==")
    os.kill(service_pid() or 0, signal.SIGTERM)
    await asyncio.sleep(2)
    for _ in range(3):
        print("  ", await call(primary, "memory_search", {"query": "ticks"}))
    print("  new pid", service_pid())

    print("\n== C: service frozen 15 s (SIGSTOP), then resumed ==")
    pid = service_pid() or 0
    os.kill(pid, signal.SIGSTOP)
    for _ in range(2):
        print("  frozen:", await call(primary, "memory_search", {"query": "ticks"}))
    os.kill(pid, signal.SIGCONT)
    await asyncio.sleep(1)
    for _ in range(3):
        print("  resumed:", await call(primary, "memory_search", {"query": "ticks"}))
    os.kill(service_pid() or 0, signal.SIGTERM)


asyncio.run(main())
