"""
M0 spike 3 — the UDS JSON-RPC transport, server side.

Minimal asyncio UDS server implementing architecture.md's shape:
  - newline-delimited JSON-RPC 2.0
  - health() unlabelled, everything else takes a `client` envelope (ignored
    for this spike's purposes beyond echoing session_id back, since the
    label ladder itself is a separate, already-measured concern — see
    FINDINGS.md's kiro-session-id-probe)
  - idle self-stop: last_activity refreshed per request, background poll,
    exit when idle exceeds idle_timeout AND no requests in flight
  - socket unlinked before the process exits, in both the idle-exit and
    signal-exit paths
  - busy_timeout emulated via a real sqlite3 db so two writers can be
    observed contending

idle_timeout is intentionally SHORT here (spike3_config.IDLE_TIMEOUT_S,
seconds not the real 30 min default) so the idle-exit race is observable
within a spike run rather than requiring a 30-minute wait. This is a
scale-down for observability, not a claim about the production default.

Throwaway per build-plan.md's M0 fence.
"""

import asyncio
import json
import os
import signal
import sqlite3
import sys
import time

SOCK_PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/zikaron_spike3.sock"
DB_PATH = sys.argv[2] if len(sys.argv) > 2 else "/tmp/zikaron_spike3.db"
IDLE_TIMEOUT_S = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0
LOG_PATH = sys.argv[4] if len(sys.argv) > 4 else "/tmp/zikaron_spike3_server.log"

_last_activity = time.monotonic()
_in_flight = 0
_store_id = "spike3-store"
_stop_event: asyncio.Event | None = None


def log(msg: str) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(f"{time.time():.6f} pid={os.getpid()} {msg}\n")


def setup_db() -> None:
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")
    con.execute("CREATE TABLE IF NOT EXISTS counter (id INTEGER PRIMARY KEY, n INTEGER)")
    con.execute("INSERT OR IGNORE INTO counter (id, n) VALUES (1, 0)")
    con.close()


async def handle_request(req: dict) -> dict:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "health":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"store_id": _store_id, "store_path": DB_PATH, "pid": os.getpid()},
        }

    client = params.get("client", {})
    session_id = client.get("session_id") or "zk-spike3-minted"

    if method == "echo":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"echo": params.get("value"), "session_id": session_id},
        }

    if method == "slow_write":
        # Simulates a real write under contention: open a connection with
        # the design's own busy_timeout, BEGIN IMMEDIATE, hold briefly,
        # then commit — so two concurrent callers genuinely contend on the
        # same file-backed db under WAL.
        #
        # The blocking sqlite3 calls run via asyncio.to_thread rather than
        # inline: a bare `con.execute(...)` inside this coroutine is a
        # synchronous C call that freezes the WHOLE single-threaded event
        # loop for as long as SQLite's own busy_timeout keeps retrying —
        # which starves every other coroutine, including the one holding
        # the lock this call is waiting on. An earlier version of this
        # spike ran the calls inline and produced a self-inflicted
        # deadlock: writer B's blocking BEGIN IMMEDIATE froze the loop so
        # writer A's `await asyncio.sleep(hold_s)` could never fire and
        # release the lock, so B's call ran out its own busy_timeout
        # waiting on a release that could never happen. Real contention
        # was never being measured. asyncio.to_thread moves the blocking
        # call to a worker thread, which is what the actual service must
        # do for every store access, not only this spike.
        hold_s = params.get("hold_s", 0.3)

        def _do_write() -> dict:
            con = sqlite3.connect(DB_PATH, isolation_level=None, timeout=5.0)
            con.execute("PRAGMA busy_timeout = 5000")
            t0 = time.monotonic()
            try:
                con.execute("BEGIN IMMEDIATE")
                time.sleep(hold_s)  # hold the write lock — real blocking sleep, off the loop
                con.execute("UPDATE counter SET n = n + 1 WHERE id = 1")
                con.execute("COMMIT")
                waited = time.monotonic() - t0
                (n,) = con.execute("SELECT n FROM counter WHERE id = 1").fetchone()
                return {"ok": True, "n": n, "waited_s": round(waited, 4)}
            except sqlite3.OperationalError as e:
                return {"ok": False, "error": str(e)}
            finally:
                con.close()

        write_result = await asyncio.to_thread(_do_write)
        if write_result["ok"]:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "n": write_result["n"],
                    "waited_s": write_result["waited_s"],
                    "session_id": session_id,
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32001, "message": f"store_busy: {write_result['error']}"},
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    global _last_activity, _in_flight
    peer = writer.get_extra_info("peername")
    log(f"client connected peer={peer}")
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            _in_flight += 1
            _last_activity = time.monotonic()
            try:
                req = json.loads(line.decode("utf-8"))
                log(f"request: {req.get('method')} id={req.get('id')}")
                resp = await handle_request(req)
            except json.JSONDecodeError as e:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
            finally:
                _in_flight -= 1
                _last_activity = time.monotonic()
            writer.write((json.dumps(resp) + "\n").encode("utf-8"))
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()
        log(f"client disconnected peer={peer}")


async def idle_monitor(server: asyncio.base_events.Server) -> None:
    global _stop_event
    while True:
        await asyncio.sleep(0.5)
        idle_for = time.monotonic() - _last_activity
        if idle_for > IDLE_TIMEOUT_S and _in_flight == 0:
            log(f"idle_timeout reached (idle_for={idle_for:.2f}s, in_flight={_in_flight}) — stopping")
            server.close()
            await server.wait_closed()
            cleanup_socket()
            assert _stop_event is not None
            _stop_event.set()
            return


def cleanup_socket() -> None:
    log("unlinking socket before exit")
    try:
        os.unlink(SOCK_PATH)
    except FileNotFoundError:
        pass


async def main() -> None:
    global _stop_event
    _stop_event = asyncio.Event()
    setup_db()
    # start-if-absent vetting: refuse a stale non-socket at the path
    if os.path.exists(SOCK_PATH):
        os.unlink(SOCK_PATH)  # spike scope: the flock-guarded client already vetted this

    server = await asyncio.start_unix_server(handle_client, path=SOCK_PATH)
    os.chmod(SOCK_PATH, 0o600)
    log(f"server listening on {SOCK_PATH}, idle_timeout={IDLE_TIMEOUT_S}s")

    loop = asyncio.get_running_loop()

    def _on_signal() -> None:
        log("signal received — stopping")
        server.close()
        cleanup_socket()
        assert _stop_event is not None
        _stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    monitor_task = asyncio.create_task(idle_monitor(server))
    async with server:
        serve_task = asyncio.create_task(server.serve_forever())
        await _stop_event.wait()
        serve_task.cancel()
        monitor_task.cancel()
        for t in (serve_task, monitor_task):
            try:
                await t
            except asyncio.CancelledError:
                pass
    log("exiting")


if __name__ == "__main__":
    # clear prior log so each run's findings are unambiguous
    open(LOG_PATH, "w").close()
    asyncio.run(main())
