"""
M0 spike 3a — warm round-trip latency, once the server is already up.

Measures many sequential echo() calls over an already-connected socket to
get a warm per-request latency figure, separate from cold start-if-absent
cost (spike3_client.py's cold path) and from the multi-process race
scenarios (spike3b/spike3c).
"""

import statistics
import time

from spike3_client import _send_request, connect_start_if_absent

N = 200


def main() -> None:
    sock, health = connect_start_if_absent(idle_timeout_s=30.0, label="warm-bench")
    print(f"health: {health}")

    # discard the first call (includes any residual connection setup cost)
    _send_request(sock, "echo", {"value": 0, "client": {"session_id": "warm-bench"}}, req_id=1)

    latencies_ms = []
    for i in range(N):
        t0 = time.perf_counter()
        resp = _send_request(sock, "echo", {"value": i, "client": {"session_id": "warm-bench"}}, req_id=i + 2)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
        assert resp["result"]["echo"] == i

    sock.close()

    latencies_ms.sort()
    print(f"\nWarm round-trip over {N} sequential echo() calls (already-connected socket):")
    print(f"  min   = {latencies_ms[0]:.4f} ms")
    print(f"  p50   = {statistics.median(latencies_ms):.4f} ms")
    print(f"  p95   = {latencies_ms[int(N * 0.95)]:.4f} ms")
    print(f"  p99   = {latencies_ms[int(N * 0.99)]:.4f} ms")
    print(f"  max   = {latencies_ms[-1]:.4f} ms")
    print(f"  mean  = {statistics.mean(latencies_ms):.4f} ms")


if __name__ == "__main__":
    main()
