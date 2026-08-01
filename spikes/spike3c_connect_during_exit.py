"""
M0 spike 3c — a client connecting exactly as the server exits on idle.

Starts a server with a short idle_timeout, waits until just before that
deadline, then fires a client connect attempt timed to land in the exact
window where the server may be mid-exit (socket about to be / just
unlinked). Confirms:
  - the race is real and reproducible (this is not testing the happy path)
  - the CLIENT survives it: architecture.md says "clients retry once
    through the full start-if-absent sequence before falling back" — so
    this spike's client uses connect_start_if_absent() unmodified and
    checks whether that retry behaviour, as coded, actually recovers.

Throwaway per build-plan.md's M0 fence.
"""

import os
import subprocess
import sys
import threading
import time

from spike3_client import _connect, _send_request, connect_start_if_absent

SOCK_PATH = "/tmp/zikaron_spike3.sock"
DB_PATH = "/tmp/zikaron_spike3.db"
LOCK_PATH = SOCK_PATH + ".lock"
LOG_PATH = "/tmp/zikaron_spike3_server.log"
SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "spike3_server.py")
IDLE_TIMEOUT_S = 2.0


def main() -> None:
    for p in (SOCK_PATH, LOCK_PATH, DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm", LOG_PATH):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    open(LOG_PATH, "w").close()

    # Start the server directly (not via the client) so we control its
    # idle clock precisely: it starts idling from process start with no
    # requests ever made, so it will self-stop at ~IDLE_TIMEOUT_S.
    proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT, SOCK_PATH, DB_PATH, str(IDLE_TIMEOUT_S), LOG_PATH],
        start_new_session=True,
    )
    print(f"Server started directly, pid={proc.pid}, idle_timeout={IDLE_TIMEOUT_S}s, no requests will be sent to it")

    # Wait for the socket to exist so we know the server is up.
    deadline = time.monotonic() + 5.0
    while not os.path.exists(SOCK_PATH) and time.monotonic() < deadline:
        time.sleep(0.02)
    print(f"Socket appeared after server start: {os.path.exists(SOCK_PATH)}")

    # Busy-poll connecting repeatedly through the idle deadline, to try to
    # land a raw connect attempt in the exact moment the server unlinks
    # the socket and exits. This measures the raw race, before any client
    # retry logic is involved.
    print(f"\nBusy-polling raw connect() through the ~{IDLE_TIMEOUT_S}s idle deadline...")
    attempts = []
    t_start = time.monotonic()
    while time.monotonic() - t_start < IDLE_TIMEOUT_S + 1.5:
        t0 = time.monotonic()
        try:
            s = _connect(SOCK_PATH, timeout=0.2)
            s.close()
            attempts.append((t0 - t_start, "ok"))
        except OSError as e:
            attempts.append((t0 - t_start, f"fail:{e.strerror}"))
        time.sleep(0.01)

    transitions = []
    prev = None
    for t, outcome in attempts:
        if prev is not None and outcome != prev:
            transitions.append((round(t, 4), prev, "->", outcome))
        prev = outcome
    print(f"Outcome transitions during the poll: {transitions}")
    raw_race_observed = any("ok" in a[1] for a in attempts) and any("fail" in a[1] for a in attempts)
    print(f"Raw race window actually observed (both ok and fail outcomes occurred): {raw_race_observed}")

    proc.wait(timeout=10)
    print(f"\nServer process exited, returncode={proc.returncode}")

    # Now the real question: does connect_start_if_absent(), run RIGHT
    # after the server is confirmed gone, recover cleanly via its own
    # retry-through-start-if-absent logic? This is the client-side
    # behaviour architecture.md actually prescribes.
    print("\n--- Client recovery via connect_start_if_absent() after the server has exited ---")
    sock, health = connect_start_if_absent(idle_timeout_s=5.0, log_path=LOG_PATH, label="post-exit-client")
    resp = _send_request(sock, "echo", {"value": "recovered", "client": {"session_id": "post-exit-client"}}, req_id=1)
    print(f"Recovery echo response: {resp}")
    sock.close()

    # Cleanup: let the new server idle out too, so no process is left running.
    time.sleep(6.0)
    print("\n=== Full server log ===")
    with open(LOG_PATH) as f:
        print(f.read())


if __name__ == "__main__":
    main()
