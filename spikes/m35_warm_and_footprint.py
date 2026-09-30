"""Probe: a warm `memory_search`'s time, and what the service holds once its read pool is full.

    python spikes/m35_warm_and_footprint.py <scratch-project-dir> <seeded-project-dir>

Run once per tree under comparison, from a directory outside the repository so `-m` resolves the
interpreter's own installed package. Reports the median and p90 of 50 sequential warm searches,
then the service's resident memory and open file descriptors after eight concurrent searches have
had the chance to open every pool connection.
"""

import asyncio
import os
import sqlite3
import statistics
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from zikaron.mcp.connection import ServiceConnection

PROJ = Path(sys.argv[1])
SRC = Path(sys.argv[2]) / ".zikaron" / "memory.db"


def copy_store() -> None:
    (PROJ / ".zikaron").mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(PROJ / ".zikaron" / "memory.db")) as copy,
    ):
        source.backup(copy)


def service_pid() -> int:
    found = subprocess.run(
        ["pgrep", "-f", f"service.main .* {PROJ}/.zikaron"], capture_output=True, text=True
    ).stdout.split()
    return int(found[0])


def footprint(pid: int) -> tuple[str, int]:
    status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    rss = next(line.split(":", 1)[1].strip() for line in status.splitlines() if line.startswith("VmRSS"))
    return rss, len(os.listdir(f"/proc/{pid}/fd"))


async def search(conn: ServiceConnection) -> float:
    started = time.monotonic()
    await conn.request(
        "memory_search", {"query": "timestamps ticks drift"}, envelope=conn.envelope(kind="mcp")
    )
    return (time.monotonic() - started) * 1000


async def main() -> None:
    copy_store()
    primary = ServiceConnection(PROJ)
    for _ in range(3):
        await search(primary)
    samples = sorted([await search(primary) for _ in range(50)])
    print(f"warm search: median {statistics.median(samples):.1f} ms, p90 {samples[44]:.1f} ms")
    pid = service_pid()
    print("footprint before a concurrent burst: rss %s, fds %d" % footprint(pid))
    readers = [ServiceConnection(PROJ) for _ in range(8)]
    await asyncio.gather(*(search(reader) for reader in readers))
    print("footprint after a concurrent burst:  rss %s, fds %d" % footprint(pid))
    os.kill(pid, 15)


asyncio.run(main())
