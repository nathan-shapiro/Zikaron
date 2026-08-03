"""`zikaron.hook.connect.connect_once`: the lock-protected race between two concurrent callers.

`architecture.md` §"Start-if-absent, without a thundering herd" is normative — the `flock`
around vet-and-clear-stale-socket-and-spawn exists specifically to prevent two racing clients
from both observing the socket absent and one of them unlinking the *other's* now-live socket
before spawning a second server. This test proves the lock actually closes that race, against
real threads calling the real function concurrently — not merely that the sequential unit tests
in `test_hook_connect.py` still pass, which they would even without the lock, since none of them
exercise genuine concurrency.

Round-2 review (`reviews/m11-hook-client-review.md`, finding 1) found round 1's version of this
file asserted only that both callers received a socket — true whether or not the lock exists,
since a lock-free race can also converge on one winner binding while the loser's own bind fails
and it falls through to connecting to the winner. Every test below now makes the spawned
server itself append evidence of having been invoked *before* it attempts anything else, so
"exactly one spawn happened" is checked directly against that record rather than inferred from
the outcome — and the second test now forces a genuine interleaving *deterministically*, via a
monkeypatch-based synchronization point rather than a fixed `time.sleep` delay: an intermediate
version of this test used a sleep to approximate the race and was found, on direct
experimentation, to pass identically whether the lock was present or removed — for reasons that
took direct measurement to characterize at all, which is exactly the tell that a fixed delay was
never actually pinning the mechanism it was meant to exercise. No test in this file relies on a
guessed sleep duration for correctness; every wait is either a bounded `Event.wait`/`join`
timeout (a safety net against a genuine hang, not a race-timing assumption) or a real subprocess
simulating startup latency inside the spawned server script itself.
"""

import fcntl
import json
import os
import signal
import socket
import sys
import threading
import unittest.mock
from pathlib import Path
from typing import Final

import pytest

from zikaron.hook.connect import connect_once

pytestmark = pytest.mark.integration

#: A script that, before doing anything else, appends its own pid and start time to a marker
#: file (so the test can count real spawn attempts regardless of whether the bind that follows
#: succeeds), then binds the socket after a small delay and answers `health()` repeatedly.
_LONG_RUNNING_SERVER_SCRIPT: Final = """
import json
import socket
import sys
import time

sock_path, delay_ms, store_path, store_id, marker_path = sys.argv[1:6]
with open(marker_path, "a", encoding="utf-8") as marker:
    marker.write(f"{__import__('os').getpid()} {time.monotonic()}\\n")
time.sleep(int(delay_ms) / 1000)
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
try:
    server.bind(sock_path)
except OSError:
    # Lost the race to bind — another spawn (or a pre-existing server) got there first. Exit
    # without serving; the marker line above already recorded that this process was spawned at
    # all, which is what the test's spawn count actually needs.
    raise SystemExit(0) from None
server.listen(4)
server.settimeout(5.0)
while True:
    try:
        connection, _ = server.accept()
    except socket.timeout:
        break
    with connection:
        buffer = b""
        while not buffer.endswith(b"\\n"):
            chunk = connection.recv(4096)
            if not chunk:
                break
            buffer += chunk
        if not buffer:
            continue
        request = json.loads(buffer.decode("utf-8"))
        response = {
            "jsonrpc": "2.0",
            "id": request.get("id", 1),
            "result": {"ready": True, "store_path": store_path, "store_id": store_id},
        }
        connection.sendall((json.dumps(response) + "\\n").encode("utf-8"))
"""


@pytest.fixture
def long_running_server_script(tmp_path: Path) -> Path:
    script = tmp_path / "long_running_server.py"
    script.write_text(_LONG_RUNNING_SERVER_SCRIPT, encoding="utf-8")
    return script


class _ThreadResults:
    """A plain, lock-protected append-only list of `connect_once` outcomes from concurrent
    caller threads — factored out because every test in this file appends to one under a lock
    from more than one thread, and inlining the lock at each call site was pushing the more
    elaborate races past this project's own statement-count lint threshold for no benefit to
    clarity."""

    def __init__(self) -> None:
        self._items: list[socket.socket | BaseException] = []
        self._lock = threading.Lock()

    def record(self, outcome: socket.socket | BaseException) -> None:
        with self._lock:
            self._items.append(outcome)

    @property
    def errors(self) -> list[BaseException]:
        return [item for item in self._items if isinstance(item, BaseException)]

    @property
    def sockets(self) -> list[socket.socket]:
        return [item for item in self._items if isinstance(item, socket.socket)]

    def __len__(self) -> int:
        return len(self._items)


def _read_marker_lines(marker_path: Path) -> list[tuple[int, float]]:
    """Every `(pid, monotonic_start_time)` pair a spawned server recorded, in file order — the
    file may not exist at all if nothing was ever spawned."""
    if not marker_path.exists():
        return []
    lines = marker_path.read_text(encoding="utf-8").splitlines()
    parsed: list[tuple[int, float]] = []
    for line in lines:
        pid_text, time_text = line.split()
        parsed.append((int(pid_text), float(time_text)))
    return parsed


def _reap_marker_pids(marker_path: Path) -> None:
    """Best-effort SIGTERM + reap for every pid a marker file recorded — the delayed script in
    `_LONG_RUNNING_SERVER_SCRIPT` stays alive until its own 5-second `accept()` timeout if it won
    the bind, and this test should not depend on that timeout to keep the process table clean."""
    for pid, _started_at in _read_marker_lines(marker_path):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            # Not this test process's own child (spawned via `subprocess.Popen` inside
            # `connect_once`, so it *is* a direct child in every case this file constructs —
            # kept as a defensive fallback rather than a silent pass, since a `ChildProcessError`
            # here would mean the reap genuinely could not be confirmed).
            continue


def _race_connect_once(
    sock_path: Path,
    *,
    store_db_path: Path,
    store_id: str,
    server_command: list[str],
    thread_count: int,
) -> list[socket.socket | BaseException]:
    """Call `connect_once` from `thread_count` concurrent threads with identical arguments, and
    return every thread's outcome — a real socket or the exception it raised — in the order the
    threads happened to finish, not the order they started."""
    results: list[socket.socket | BaseException] = []
    results_lock = threading.Lock()

    def _one_caller() -> None:
        try:
            sock = connect_once(
                sock_path,
                store_db_path=store_db_path,
                store_id=store_id,
                server_command=server_command,
            )
        except BaseException as error:  # captured for the assertion below, not swallowed.
            with results_lock:
                results.append(error)
        else:
            with results_lock:
                results.append(sock)

    threads = [threading.Thread(target=_one_caller) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10.0)
    return results


def test_two_concurrent_callers_race_to_start_exactly_one_service(
    tmp_path: Path, long_running_server_script: Path
) -> None:
    """The exact race `architecture.md`'s lock exists to close: both callers observe the socket
    absent and call `connect_once` at effectively the same instant (forced via a `threading.
    Barrier` so neither can win by simply going first), and the lock must ensure only one spawn
    command ever runs — proven directly by counting the marker lines the spawned script itself
    writes before it does anything else, not merely by both calls eventually succeeding, which a
    lock-free implementation could also produce if the loser's failed bind fell through to
    connecting to the winner.
    """
    sock_path = tmp_path / "test.sock"
    store_db_path = tmp_path / "memory.db"
    marker_path = tmp_path / "spawned.marker"
    command = [
        sys.executable,
        str(long_running_server_script),
        str(sock_path),
        "100",  # bind 100ms after spawn, so both callers are well inside the lock together first
        str(store_db_path),
        "the-store-id",
        str(marker_path),
    ]

    barrier = threading.Barrier(2)
    results: list[socket.socket | BaseException] = []
    results_lock = threading.Lock()

    def _one_caller() -> None:
        barrier.wait(timeout=10.0)
        try:
            sock = connect_once(
                sock_path,
                store_db_path=store_db_path,
                store_id="the-store-id",
                server_command=command,
            )
        except BaseException as error:
            with results_lock:
                results.append(error)
        else:
            with results_lock:
                results.append(sock)

    threads = [threading.Thread(target=_one_caller) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10.0)

        errors = [r for r in results if isinstance(r, BaseException)]
        assert not errors, f"unexpected failures: {errors}"
        sockets = [r for r in results if isinstance(r, socket.socket)]
        assert len(sockets) == 2
        for sock in sockets:
            sock.close()

        spawns = _read_marker_lines(marker_path)
        assert len(spawns) == 1, (
            f"expected exactly one spawn under the lock, marker file recorded {len(spawns)}: "
            f"{spawns}"
        )
    finally:
        _reap_marker_pids(marker_path)


def test_a_caller_that_finds_the_socket_absent_but_loses_the_lock_never_spawns(
    tmp_path: Path, long_running_server_script: Path
) -> None:
    """A caller must not spawn at all if, by the time it acquires the lock, a *different* caller
    has already bound a live socket under it — the connect-again-under-the-lock recheck
    `architecture.md`'s 5-step sequence names. Constructed as a genuine, deterministic race
    rather than a sleep-based one (round 1's version of this test pre-started a server before
    either caller began, which lets both take the warm fast path without ever reaching the
    lock/spawn branch at all — passing identically with the lock removed; a since-discarded
    intermediate version used `time.sleep` to approximate the interleaving, and a second
    since-discarded version delayed the *unlocked* pre-check rather than the lock acquisition
    itself, which cannot distinguish "the lock serialized us" from "the other caller simply
    finished first anyway" — both were found, on direct experimentation, to pass identically
    whether the lock was present or removed, which is the exact tell that neither was actually
    pinning the mechanism).

    The seam this version delays is the lock acquisition itself (`fcntl.flock(lock_fd,
    fcntl.LOCK_EX)`, patched on the shared `fcntl` module itself — `connect.py`'s own call site
    resolves `fcntl.flock` dynamically at call time, so patching the module's attribute affects
    that resolution without needing to reach into `connect`'s own namespace for it), gated to
    caller B's own thread only. With the real lock present, this reproduces exactly what the
    OS-level `flock` already does — caller B blocks until caller A's own lock is released, by
    which point caller A's socket is definitely live, so caller B's own recheck must find it.
    With the lock's `LOCK_EX` call removed or replaced by anything that does not actually block
    (the mutation this test is designed to catch), this patched wrapper is simply never reached
    at all, so caller B proceeds straight into the vet-and-spawn branch while caller A may still
    be mid-bind — exercising the real unguarded race rather than a race that happens to resolve
    safely regardless of the lock's presence.
    """
    sock_path = tmp_path / "test.sock"
    store_db_path = tmp_path / "memory.db"
    marker_path = tmp_path / "spawned.marker"
    caller_a_command = [
        sys.executable,
        str(long_running_server_script),
        str(sock_path),
        "0",
        str(store_db_path),
        "the-store-id",
        str(marker_path),
    ]
    # A command that fails loudly and distinctively if it is ever actually invoked — caller B
    # must never reach this, since it must find caller A's socket already live under the lock.
    caller_b_poison_command = [sys.executable, "-c", "raise SystemExit(97)"]

    results = _ThreadResults()
    caller_b_reached_its_lock_acquisition = threading.Event()
    release_caller_b = threading.Event()
    real_flock = fcntl.flock
    thread_b = threading.Thread(target=lambda: None)  # placeholder, replaced below.

    def _caller_a() -> None:
        try:
            sock = connect_once(
                sock_path,
                store_db_path=store_db_path,
                store_id="the-store-id",
                server_command=caller_a_command,
            )
        except BaseException as error:
            results.record(error)
            return
        results.record(sock)
        # Caller A has now completed its own sequence, which for the winner means a real, live,
        # bound socket exists at `sock_path` — the deterministic condition caller B's own release
        # below waits for.
        release_caller_b.set()

    def _flock_delayed_only_for_caller_bs_lock_acquisition(fd: int, operation: int) -> None:
        # `unittest.mock.patch.object` replaces `fcntl.flock` at module scope, so this wrapper is
        # what *every* call goes through, including caller A's own release (`LOCK_UN`) and its
        # own acquisition. Gating the delay on both thread identity *and* the specific `LOCK_EX`
        # operation is what keeps every other call passing straight through — delaying caller A's
        # own `LOCK_UN` release, for instance, would prevent it from ever reaching the release
        # this test depends on, another self-deadlock shape found while building this test.
        if threading.current_thread() is thread_b and operation == fcntl.LOCK_EX:
            caller_b_reached_its_lock_acquisition.set()
            release_caller_b.wait(timeout=10.0)
        real_flock(fd, operation)

    def _caller_b() -> None:
        with unittest.mock.patch.object(
            fcntl, "flock", side_effect=_flock_delayed_only_for_caller_bs_lock_acquisition
        ):
            try:
                sock = connect_once(
                    sock_path,
                    store_db_path=store_db_path,
                    store_id="the-store-id",
                    server_command=caller_b_poison_command,
                )
            except BaseException as error:
                results.record(error)
            else:
                results.record(sock)

    thread_a = threading.Thread(target=_caller_a)
    thread_b = threading.Thread(target=_caller_b)
    try:
        # Caller B starts first and is held right before its own lock acquisition until caller
        # A — started only once that hold is confirmed — has genuinely finished. This is what
        # makes the interleaving deterministic rather than merely likely: caller B cannot possibly
        # proceed past acquiring the lock until this test says so.
        thread_b.start()
        assert caller_b_reached_its_lock_acquisition.wait(timeout=10.0), (
            "caller B never reached its own lock acquisition"
        )
        thread_a.start()
        thread_a.join(timeout=10.0)
        thread_b.join(timeout=10.0)

        assert not results.errors, f"unexpected failures: {results.errors}"
        assert len(results.sockets) == 2, f"expected both callers to connect, got {len(results)}"
        for sock in results.sockets:
            sock.close()

        spawns = _read_marker_lines(marker_path)
        assert len(spawns) == 1, (
            f"expected exactly one spawn (caller A's), marker file recorded {len(spawns)}: {spawns}"
        )
    finally:
        release_caller_b.set()  # in case an assertion above failed before caller A could set it.
        _reap_marker_pids(marker_path)


def test_a_socket_already_bound_before_the_race_starts_is_never_unlinked(
    tmp_path: Path,
) -> None:
    """A server already genuinely listening (bound and serving) before either `connect_once`
    call starts: **neither** caller should ever reach the vet-and-unlink-and-spawn branch at all
    — both must simply connect to the one real, live socket, and the socket's own original inode
    must survive, never unlinked-then-recreated by a caller that (incorrectly) treated an
    existing live socket as stale. `server_command` here is a command that would fail loudly if
    it ever actually ran, so a spawn happening at all fails this test rather than merely going
    undetected.
    """
    sock_path = tmp_path / "test.sock"
    store_db_path = tmp_path / "memory.db"

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(4)
    server.settimeout(5.0)
    original_inode = sock_path.stat().st_ino
    stop = threading.Event()

    def _serve() -> None:
        while not stop.is_set():
            try:
                connection, _ = server.accept()
            except TimeoutError:
                continue
            with connection:
                buffer = b""
                while not buffer.endswith(b"\n"):
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    buffer += chunk
                if not buffer:
                    continue
                request = json.loads(buffer.decode("utf-8"))
                response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id", 1),
                    "result": {
                        "ready": True,
                        "store_path": str(store_db_path),
                        "store_id": "already-running",
                    },
                }
                connection.sendall((json.dumps(response) + "\n").encode("utf-8"))

    server_thread = threading.Thread(target=_serve, daemon=True)
    server_thread.start()
    try:
        results = _race_connect_once(
            sock_path,
            store_db_path=store_db_path,
            store_id="already-running",
            server_command=[sys.executable, "-c", "raise SystemExit(1)"],
            thread_count=2,
        )

        assert len(results) == 2
        for result in results:
            assert isinstance(result, socket.socket), f"unexpected failure: {result}"
            result.close()
        assert sock_path.exists(), "the pre-existing socket must never be unlinked"
        assert sock_path.stat().st_ino == original_inode, (
            "the pre-existing socket's own inode must survive — a different inode at the same "
            "path means it was unlinked and a new one bound in its place"
        )
    finally:
        # `stop.set()` alone is not enough to make `_serve`'s own blocking `accept()` return
        # promptly — its `settimeout(5.0)` is what actually bounds the wait, and closing the
        # socket out from under a thread still blocked inside `accept()` is a race of its own
        # (an "Errno 9: Bad file descriptor" from the accept call, harmless here since this
        # thread is daemonized and about to end regardless, but worth avoiding rather than
        # leaving an unhandled-thread-exception warning in every run). Setting the stop flag and
        # then waiting out the thread's own timeout before closing gives it the chance to exit
        # cleanly through its own loop condition first.
        stop.set()
        server_thread.join(timeout=6.0)
        server.close()
