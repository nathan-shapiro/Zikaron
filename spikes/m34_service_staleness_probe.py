"""Probe: what a long request, a killed service and a frozen service do to other clients."""

import asyncio
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from zikaron.mcp.connection import ServiceConnection

SRC = Path.home() / "zikaron-m34-replay/replay/.zikaron/memory.db"
PROJ = Path(sys.argv[1])


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
