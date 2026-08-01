"""
M0 spike 3 — the UDS JSON-RPC transport, client side.

Implements architecture.md's exact start-if-absent sequence:
  1. Try to connect.
  2. On ENOENT or ECONNREFUSED, take an exclusive flock on <sock>.lock.
  3. Try to connect again (another client may have won and started it).
  4. Still dead: unlink stale socket if present, spawn the service
     detached, then poll health() until a deadline.
  5. Release the lock.
  6. Verify store_id / store_path from health() before the first real
     request.

Throwaway per build-plan.md's M0 fence.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import socket
import subprocess
import sys
import time

SOCK_PATH = "/tmp/zikaron_spike3.sock"
DB_PATH = "/tmp/zikaron_spike3.db"
LOCK_PATH = SOCK_PATH + ".lock"
SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "spike3_server.py")
PYTHON = sys.executable


class RpcError(Exception):
    pass


def _connect(sock_path: str, timeout: float = 1.0) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(sock_path)
    return s


def _send_request(sock: socket.socket, method: str, params: dict | None = None, req_id: int = 1) -> dict:
    req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise RpcError("connection closed before a full response was read")
        buf += chunk
    return json.loads(buf.decode("utf-8"))


def _spawn_detached(idle_timeout_s: float, log_path: str) -> subprocess.Popen:
    return subprocess.Popen(
        [PYTHON, SERVER_SCRIPT, SOCK_PATH, DB_PATH, str(idle_timeout_s), log_path],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def connect_start_if_absent(
    idle_timeout_s: float = 3.0,
    log_path: str = "/tmp/zikaron_spike3_server.log",
    label: str = "",
) -> tuple[socket.socket, dict]:
    """Returns (connected socket, health() result). Times the whole sequence."""
    t0 = time.monotonic()

    def _log(msg: str) -> None:
        print(f"[{label}] t={time.monotonic() - t0:.4f}s {msg}")

    # 1. Try to connect.
    try:
        sock = _connect(SOCK_PATH)
        _log("connected on first try (server already warm)")
    except OSError as e:
        if e.errno not in (errno.ENOENT, errno.ECONNREFUSED):
            raise
        _log(f"first connect failed ({errno.errorcode.get(e.errno, e.errno)}) — taking flock")

        # 2. Exclusive flock on <sock>.lock.
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _log("flock acquired")
        try:
            # 3. Try to connect again — another client may have won.
            try:
                sock = _connect(SOCK_PATH)
                _log("connected after acquiring flock (another client won the race)")
            except OSError as e2:
                if e2.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                    raise
                # 4. Still dead: unlink stale socket, spawn detached, poll health().
                if os.path.exists(SOCK_PATH):
                    _log("unlinking stale socket")
                    os.unlink(SOCK_PATH)
                _log("spawning detached server")
                _spawn_detached(idle_timeout_s, log_path)

                deadline = time.monotonic() + 5.0
                sock = None
                while time.monotonic() < deadline:
                    try:
                        sock = _connect(SOCK_PATH, timeout=0.5)
                        break
                    except OSError:
                        time.sleep(0.05)
                if sock is None:
                    raise RpcError("server did not become reachable before deadline")
                _log("connected after spawning + polling")
        finally:
            # 5. Release the lock.
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            _log("flock released")

    # 6. Verify store_id / store_path from health() before the first real request.
    health = _send_request(sock, "health", req_id=0)
    _log(f"health() -> {health.get('result')}")
    return sock, health.get("result", {})


if __name__ == "__main__":
    # Simple manual smoke test when run directly.
    sock, health = connect_start_if_absent(label="manual")
    resp = _send_request(sock, "echo", {"value": "hello", "client": {"session_id": None}}, req_id=1)
    print("echo response:", resp)
    sock.close()
