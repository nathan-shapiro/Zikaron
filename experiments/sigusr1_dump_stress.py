"""Signal a real service with `SIGUSR1` repeatedly and count how often the process dies.

    .venv/bin/python experiments/sigusr1_dump_stress.py [runs] [signals_per_run]

Defaults to 60 runs of 5 signals. Each run spawns the service exactly as a client does, against one
store created up front, and sends its signals as soon as the socket accepts — while the open path's
model load can still be running Python on its own thread. Each signal after the first waits for the
previous dump to land, so a death is attributable to the signal that preceded it. Prints each death
with its return code (`-11` is `SIGSEGV`, `-10` is `SIGUSR1`'s default disposition) and a summary
line with the dump count, which should equal runs × signals when nothing died.

`research/sigusr1-dump-crash.md` records what this measured.
"""

import asyncio
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_service_lifecycle_integration import (  # noqa: E402
    MODEL,
    _create_store,
    _spawn_server,
    _wait_for_accepting_socket,
)
from zikaron.core.indexing.encoder import FastEmbedEncoder  # noqa: E402
from zikaron.service.paths import service_log_path  # noqa: E402

_DUMP_HEADER = "Current thread"
_DUMP_DEADLINE_SECONDS = 10.0


def _dumps(store_dir: Path) -> int:
    return service_log_path(store_dir).read_text(errors="replace").count(_DUMP_HEADER)


async def main(runs: int, signals_per_run: int) -> None:
    os.environ.setdefault("XDG_RUNTIME_DIR", tempfile.mkdtemp(prefix="zkrt-"))
    encoder = FastEmbedEncoder.load(MODEL)
    store_dir = Path(tempfile.mkdtemp(prefix="zkst-")) / ".zikaron"
    store_dir.mkdir()
    await _create_store(store_dir, encoder)
    deaths: list[tuple[int, int]] = []
    for run in range(runs):
        sock = Path(tempfile.mkdtemp(prefix="zk-", dir="/tmp")) / "s.sock"
        process = _spawn_server(sock, store_dir)
        try:
            _wait_for_accepting_socket(sock, deadline_seconds=15.0)
            for _ in range(signals_per_run):
                before = _dumps(store_dir)
                os.kill(process.pid, signal.SIGUSR1)
                deadline = time.monotonic() + _DUMP_DEADLINE_SECONDS
                while _dumps(store_dir) <= before and process.poll() is None:
                    if time.monotonic() > deadline:
                        break
                    time.sleep(0.02)
                time.sleep(0.05)
                if process.poll() is not None:
                    break
            returncode = process.poll()
            if returncode is not None:
                deaths.append((run, returncode))
                print(f"run {run}: died, return code {returncode}", flush=True)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
    print(
        f"runs={runs} signals_per_run={signals_per_run} deaths={len(deaths)} "
        f"dumps={_dumps(store_dir)} log={service_log_path(store_dir)}"
    )


if __name__ == "__main__":
    asyncio.run(
        main(
            int(sys.argv[1]) if len(sys.argv) > 1 else 60,
            int(sys.argv[2]) if len(sys.argv) > 2 else 5,
        )
    )
