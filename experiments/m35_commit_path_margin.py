"""M35: how long the commit path takes, from the service's last deadline check to the hook's `recv`.

`architecture.md` §"A push the agent never saw is never recorded as shown": a `surface` answers
`deadline_passed` past its caller's deadline less `dispatch.DEADLINE_MARGIN_MS`. The margin has to
cover the path from the check before `COMMIT` passing — the `COMMIT` and its WAL `fsync`, the
worker-to-loop handoff, the `call` row attempt, encoding, the socket, the hook's wake — because a
commit whose answer lands after the hook gave up is a push recorded as shown that nobody saw.

**Measured, not assumed, and under the host's real load.** A real spawned service on a copy of a real
store; the hook's own client code (`connect_once`, `surface_once`) sending pushes one at a time; the
service stamping `time.time()` as its last check passes (`m35_margin_site/sitecustomize.py`), and the
client stamping `time.time()` as `recv` returns. Both ends share the machine's realtime clock, so the
difference is the path. Pushes are sequential, so the i-th stamp belongs to the i-th push.

    .venv/bin/python experiments/m35_commit_path_margin.py <scratch-dir> [pushes] [source-store-dir]

Prints the distribution in milliseconds and the percentile the constant is set from.
"""

import os
import sqlite3
import statistics
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "experiments" / "m35_margin_site"
DEFAULT_SOURCE = Path.home() / "zikaron-m34-replay" / "replay" / ".zikaron"
PROMPTS = (
    "the tick timestamps collide",
    "why did the consolidation run stall",
    "how do I run the integration tests",
    "what broke the proto codegen",
    "the lease expired mid run",
)


def _copy_store(source: Path, project: Path) -> None:
    (project / ".zikaron").mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(f"file:{source / 'memory.db'}?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(project / ".zikaron" / "memory.db")) as dst,
    ):
        src.backup(dst)


def _measure(project: Path, pushes: int, stamps: Path) -> list[float]:
    """Run in a child interpreter, so the service it spawns inherits the instrumentation."""
    script = f"""
import time
from pathlib import Path
from zikaron.hook import connect, envelope, rpc
from zikaron.service import paths
store_dir = paths.store_dir(Path({str(project)!r}))
sock_path = connect.resolve_sock_path(store_dir)
command = connect.default_server_command(sock_path, store_dir)
prompts = {PROMPTS!r}
for index in range({pushes} + 3):
    sock = connect.connect_once(
        sock_path,
        store_db_path=paths.store_db_path(store_dir),
        store_id=None,
        server_command=command,
    )
    try:
        sock.settimeout(30)
        rpc.surface_once(
            sock,
            prompt=prompts[index % len(prompts)],
            limit=5,
            envelope=envelope.build_envelope(session_id="margin-probe", pid=1),
            deadline_at_ms=int((time.time() + 4.0) * 1000),
        )
        print(f"{{time.time():.6f}}", flush=True)
    finally:
        sock.close()
"""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(SITE), os.environ.get("PYTHONPATH", "")]),
        "ZIKARON_MARGIN_STAMPS": str(stamps),
    }
    answered = subprocess.run(  # noqa: S603 — a fixed argv this harness builds.
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    checked = stamps.read_text(encoding="utf-8").split()
    # The first three pushes warm the model and the pool; they are not the steady state.
    pairs = list(zip(checked, answered, strict=True))[3:]
    return [(float(received) - float(check)) * 1000 for check, received in pairs]


def _stop_service(project: Path) -> None:
    subprocess.run(  # noqa: S603, S607 — a fixed argv this harness builds.
        ["pkill", "-f", f"service.main .* {project}/.zikaron"], check=False
    )


def main() -> None:
    project = Path(sys.argv[1]).resolve()
    pushes = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    source = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_SOURCE
    _copy_store(source, project)
    stamps = project / "stamps.txt"
    stamps.unlink(missing_ok=True)
    started = time.monotonic()
    try:
        samples = _measure(project, pushes, stamps)
    finally:
        _stop_service(project)
    ordered = sorted(samples)

    def percentile(fraction: float) -> float:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    print(f"pushes measured: {len(samples)} in {time.monotonic() - started:.1f}s")
    print(f"load average:    {os.getloadavg()}")
    print(f"median:          {statistics.median(samples):.2f} ms")
    for fraction in (0.9, 0.99, 0.999):
        print(f"{f'p{fraction * 100:g}:':<17}{percentile(fraction):.2f} ms")
    print(f"max:             {ordered[-1]:.2f} ms")


if __name__ == "__main__":
    main()
