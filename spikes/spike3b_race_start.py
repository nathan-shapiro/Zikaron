"""
M0 spike 3b — two clients racing start-if-absent under flock.

Launches two client processes at (as close as achievable) the same moment
against a cold store, and confirms:
  - exactly one server process ends up spawned (no duplicate spawns, no
    thundering herd)
  - both clients successfully connect and get a valid health() response
  - both report the SAME pid in health(), proving they talk to the same
    server instance rather than two racing ones

Throwaway per build-plan.md's M0 fence.
"""

import multiprocessing
import os
import time

from spike3_client import _send_request, connect_start_if_absent

SOCK_PATH = "/tmp/zikaron_spike3.sock"
DB_PATH = "/tmp/zikaron_spike3.db"
LOCK_PATH = SOCK_PATH + ".lock"
LOG_PATH = "/tmp/zikaron_spike3_server.log"


def _client_worker(label: str, barrier: multiprocessing.Barrier, result_queue: multiprocessing.Queue) -> None:
    barrier.wait()  # release both processes at (as close as possible to) the same instant
    t0 = time.monotonic()
    sock, health = connect_start_if_absent(idle_timeout_s=5.0, log_path=LOG_PATH, label=label)
    resp = _send_request(sock, "echo", {"value": label, "client": {"session_id": label}}, req_id=1)
    elapsed = time.monotonic() - t0
    sock.close()
    result_queue.put(
        {
            "label": label,
            "elapsed_s": elapsed,
            "health_pid": health.get("pid"),
            "echo_ok": resp.get("result", {}).get("echo") == label,
        }
    )


def main() -> None:
    for p in (SOCK_PATH, LOCK_PATH, DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm", LOG_PATH):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    barrier = multiprocessing.Barrier(2)
    result_queue: multiprocessing.Queue = multiprocessing.Queue()

    p1 = multiprocessing.Process(target=_client_worker, args=("racer-A", barrier, result_queue))
    p2 = multiprocessing.Process(target=_client_worker, args=("racer-B", barrier, result_queue))
    p1.start()
    p2.start()
    p1.join(timeout=10)
    p2.join(timeout=10)

    results = [result_queue.get() for _ in range(2)]
    print("\n=== Race results ===")
    for r in results:
        print(r)

    pids = {r["health_pid"] for r in results}
    print(f"\nDistinct server pids seen by the two racers: {pids}")
    print(f"Both racers converged on ONE server instance: {len(pids) == 1}")
    print(f"Both echo calls succeeded: {all(r['echo_ok'] for r in results)}")

    time.sleep(6.0)  # let the idle monitor fire so the log is complete
    print("\n=== Server log ===")
    with open(LOG_PATH) as f:
        print(f.read())


if __name__ == "__main__":
    main()
