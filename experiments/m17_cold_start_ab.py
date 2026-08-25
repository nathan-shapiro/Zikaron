"""M17's deciding A/B: what a cold service costs before and after the model load was deferred.

Run once per arm, with the tree in the state that arm names, and give each run the same store:

    .venv/bin/python experiments/m17_cold_start_ab.py <label> [runs]

**What "cold" means here, since it is the whole subject.** A cold *process*, not a cold artifact
cache — the production case this exists for is a service that idled out and was respawned by
start-if-absent on a machine where the model files have been on disk for weeks. Each run therefore
kills any live service and unlinks the socket, but never clears the fastembed cache.

**Each arm discards one warm-up run before measuring.** The first spawn after a period of inactivity
pays page-cache misses on the model file that later runs do not, and that cost belongs to neither
arm; measuring it in whichever arm happened to run first would be measuring the order.

Three timings per run, all from the instant the spawn was issued:

- `socket`  — the first successful `connect()`. What the bind itself costs.
- `health`  — the first `health()` answering `ready`. What a client's readiness poll waits for,
              and the deadline the push hook actually enforces.
- `surface` — a real retrieval answered. The whole sequence, and where a deferred load's remaining
              time is paid.

The two deadlines printed alongside are read from the shipped constants rather than restated, so
this cannot drift from what the hook enforces.
"""

import json
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zikaron.hook import connect, push

STORE_DIR = Path("/home/nathan/Zikaron/.zikaron")
QUERY = "how long does the check script take and what does it run"


def _kill_any_service(sock_path: Path) -> None:
    listing = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True).stdout
    for line in listing.splitlines():
        if "service.main" in line and str(sock_path) in line:
            subprocess.run(["kill", line.split()[0]], check=False)
    for _ in range(200):
        if not sock_path.exists():
            break
        time.sleep(0.01)
    sock_path.unlink(missing_ok=True)


def _one_run(sock_path: Path) -> dict[str, float | int]:
    _kill_any_service(sock_path)
    started = time.monotonic()
    subprocess.Popen(
        connect.default_server_command(sock_path, STORE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    at_socket = at_health = None
    sock = None
    while time.monotonic() - started < 30:
        try:
            candidate = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            candidate.settimeout(1.0)
            candidate.connect(str(sock_path))
        except OSError:
            time.sleep(0.005)
            continue
        if at_socket is None:
            at_socket = time.monotonic() - started
        health = {"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}
        candidate.sendall((json.dumps(health) + "\n").encode())
        answer = _read_line(candidate)
        if answer and answer.get("result", {}).get("ready"):
            at_health = time.monotonic() - started
            sock = candidate
            break
        candidate.close()
        time.sleep(0.005)

    if sock is None or at_socket is None or at_health is None:
        raise SystemExit("the service never became ready within 30 s")

    sock.settimeout(30.0)
    sock.sendall(
        (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "surface",
                    "params": {
                        "prompt": QUERY,
                        "limit": 5,
                        "client": {"session_id": "m17-ab", "kind": "hook", "pid": 1},
                    },
                }
            )
            + "\n"
        ).encode()
    )
    answer = _read_line(sock)
    at_surface = time.monotonic() - started
    sock.close()
    if answer is None or "error" in answer:
        raise SystemExit(f"surface failed: {answer}")
    rows = answer["result"]
    rows = rows if isinstance(rows, list) else rows.get("results", [])

    _kill_any_service(sock_path)
    return {
        "socket": at_socket * 1000,
        "health": at_health * 1000,
        "surface": at_surface * 1000,
        "rows": len(rows),
    }


def _read_line(sock: socket.socket) -> dict | None:
    buffer = b""
    while not buffer.endswith(b"\n"):
        try:
            chunk = sock.recv(65536)
        except OSError:
            return None
        if not chunk:
            return None
        buffer += chunk
    parsed = json.loads(buffer)
    return parsed if isinstance(parsed, dict) else None


def main() -> None:
    label = sys.argv[1] if len(sys.argv) > 1 else "unlabelled"
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    sock_path = connect.resolve_sock_path(STORE_DIR)

    load = Path("/proc/loadavg").read_text().split()[0]
    print(f"arm={label}  runs={runs}  store={STORE_DIR}  load1={load}")
    print(f"deadlines: health poll {connect.HEALTH_POLL_DEADLINE_SECONDS * 1000:.0f} ms, "
          f"hook total {push._DEADLINE_SECONDS * 1000:.0f} ms")

    print("warm-up run (discarded) ...", flush=True)
    _one_run(sock_path)

    results = []
    for index in range(runs):
        outcome = _one_run(sock_path)
        results.append(outcome)
        print(
            f"  run {index + 1}: socket {outcome['socket']:7.0f}  health {outcome['health']:7.0f}"
            f"  surface {outcome['surface']:7.0f}  rows {outcome['rows']}",
            flush=True,
        )

    print(f"  load1 after: {Path('/proc/loadavg').read_text().split()[0]}")
    for key in ("socket", "health", "surface"):
        values = [r[key] for r in results]
        print(
            f"{key:>8}: median {statistics.median(values):7.0f} ms   "
            f"min {min(values):7.0f}   max {max(values):7.0f}"
        )
    beat_poll = sum(1 for r in results if r["health"] < connect.HEALTH_POLL_DEADLINE_SECONDS * 1000)
    beat_total = sum(1 for r in results if r["surface"] < push._DEADLINE_SECONDS * 1000)
    print(f"health inside the poll deadline: {beat_poll}/{runs}")
    print(f"surface inside the hook budget:  {beat_total}/{runs}")


if __name__ == "__main__":
    main()
