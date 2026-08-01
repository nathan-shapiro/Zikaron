"""
M0 spike 3d — busy_timeout behaviour with two writers.

Two clients concurrently call slow_write(), which opens its OWN sqlite3
connection per call (busy_timeout=5000, matching schema.md's PRAGMA),
does BEGIN IMMEDIATE, holds the write lock for hold_s, then commits.
Since this spike's server handles requests inside one asyncio event loop
but each slow_write() opens a fresh connection and calls the blocking
sqlite3 API directly, the two calls' file-level lock contention is real:
whichever call's BEGIN IMMEDIATE loses the race blocks the SQLite driver
at the OS level until busy_timeout elapses or the lock frees, which is
exactly the contention design/schema.md's PRAGMA busy_timeout = 5000 is
meant to absorb.

Confirms:
  - both writes eventually succeed (busy_timeout absorbs the contention)
  - the counter ends up incremented exactly twice (no lost update)
  - the SECOND writer's observed wait time is close to the first writer's
    hold_s, evidencing that it was blocked and released rather than
    failing outright
  - what happens when hold_s exceeds busy_timeout (5s): confirm the
    documented store_busy failure actually surfaces rather than hanging
    forever or silently corrupting

Throwaway per build-plan.md's M0 fence.
"""

import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor

from spike3_client import _send_request, connect_start_if_absent

SOCK_PATH = "/tmp/zikaron_spike3.sock"
DB_PATH = "/tmp/zikaron_spike3.db"
LOCK_PATH = SOCK_PATH + ".lock"
LOG_PATH = "/tmp/zikaron_spike3_server.log"


def _fresh_connection() -> socket.socket:
    sock, _health = connect_start_if_absent(idle_timeout_s=15.0, log_path=LOG_PATH, label="writer")
    # The connect_start_if_absent() socket carries a short connect-phase
    # timeout (1.0s / 0.5s per spike3_client._connect) which is too tight
    # for a request that legitimately takes several seconds server-side
    # (hold_s up to 6.0 below, plus busy_timeout's own 5s ceiling on top
    # of that for the contended case). Extend it now that the connection
    # is established — this is a request-lifetime timeout, not a
    # reconnect-attempt timeout, and the two are different concerns.
    sock.settimeout(20.0)
    return sock


def _do_slow_write(label: str, hold_s: float) -> dict:
    sock = _fresh_connection()
    t0 = time.monotonic()
    resp = _send_request(
        sock,
        "slow_write",
        {"hold_s": hold_s, "client": {"session_id": label}},
        req_id=1,
    )
    elapsed = time.monotonic() - t0
    sock.close()
    return {"label": label, "elapsed_s": round(elapsed, 4), "response": resp}


def main() -> None:
    for p in (SOCK_PATH, LOCK_PATH, DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm", LOG_PATH):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    open(LOG_PATH, "w").close()

    print("=== Two concurrent writers, each holding the write lock 0.5s (well under busy_timeout=5000ms) ===")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_do_slow_write, "writer-1", 0.5)
        time.sleep(0.05)  # ensure writer-1's BEGIN IMMEDIATE lands first
        f2 = pool.submit(_do_slow_write, "writer-2", 0.5)
        r1 = f1.result()
        r2 = f2.result()

    print(json.dumps(r1, indent=2))
    print(json.dumps(r2, indent=2))

    ns = []
    for r in (r1, r2):
        result = r["response"].get("result")
        if result:
            ns.append(result["n"])
    print(f"\nCounter values reported by the two writes: {ns}")
    print(f"Counter incremented exactly twice, no lost update: {sorted(ns) == [1, 2] if len(ns) == 2 else False}")

    # The second writer to actually acquire BEGIN IMMEDIATE should show a
    # waited_s close to the first writer's hold_s (~0.5s), evidencing it
    # was blocked at the SQLite level and then proceeded, rather than
    # racing through untouched.
    waits = [r["response"].get("result", {}).get("waited_s") for r in (r1, r2)]
    print(f"waited_s reported by each writer: {waits}")

    print("\n=== One writer holding LONGER than busy_timeout (5000ms): hold_s=6.0 vs a second writer with no wait ===")
    for p in (SOCK_PATH, LOCK_PATH, DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm", LOG_PATH):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    open(LOG_PATH, "w").close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_do_slow_write, "long-holder", 6.0)
        time.sleep(0.2)  # ensure long-holder's BEGIN IMMEDIATE lands first
        f2 = pool.submit(_do_slow_write, "impatient", 0.0)
        r1 = f1.result()
        r2 = f2.result()

    print(json.dumps(r1, indent=2))
    print(json.dumps(r2, indent=2))
    impatient_error = r2["response"].get("error")
    print(f"\nSecond writer's outcome after busy_timeout elapsed: {impatient_error or r2['response'].get('result')}")
    print(f"Second writer waited approximately busy_timeout (5s), not instantly failed or hung forever: {r2['elapsed_s']}")

    time.sleep(16.0)  # let the idle monitor clean up
    print("\n=== Server log ===")
    with open(LOG_PATH) as f:
        print(f.read())


if __name__ == "__main__":
    main()
