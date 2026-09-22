"""Start-if-absent under two racing clients, connect-as-server-exits,
a stale socket file, and a refused foreign-store handshake — every one of them against a real
subprocess speaking real Unix-domain-socket JSON-RPC.

Integration tier throughout: every test here spawns `python -m zikaron.service.main` as a real
detached process and speaks to it over a real socket, which is exactly what the `integration`
marker exists for (`coding-standards.md` §4) — a real store on `tmp_path` stays in the *default*
tier, but a real subprocess and a real socket do not.

`FastEmbedEncoder.load` runs once, module-scoped, for the same reason `test_indexing_integration.py`
loads it once: the load is the expensive part, not the store creation each test does with it.

**Every server pid this module ever learns of is eventually reaped, even one this module never
held a `Popen` for.** `connect_start_if_absent`'s whole contract is that its caller never gets a
handle to what it may spawn — a real client only ever asks the OS to start one — so an indirectly
spawned server is known only through the socket, via `health()`. `_kill_and_reap_server_at` kills
and reaps by that discovered pid directly, and registers the pid in `_KNOWN_SERVER_PIDS` the
instant it learns it, *before* attempting anything else — so if the socket stops answering between
that registration and the kill attempt, an autouse fixture
(`_sweep_known_server_pids_after_every_test`) force-kills and reaps whatever is left in the
registry after every test, rather than the guarantee depending on the socket staying reachable
through to cleanup. `_running_server`'s own explicitly-held `Popen` is additionally waited on
directly, unconditionally, in its own `finally` — the one case this module both spawned and holds
a durable handle for.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Final

import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.store.store import Store
from zikaron.service import security
from zikaron.service.lifecycle import connect_start_if_absent

pytestmark = pytest.mark.integration

MODEL: Final = "BAAI/bge-small-en-v1.5"

#: Generous relative to spike 3's measured ~101 ms cold start, to absorb slower CI environments.
_SPAWN_DEADLINE_SECONDS = 15.0


@pytest.fixture(scope="module")
def encoder() -> FastEmbedEncoder:
    return FastEmbedEncoder.load(MODEL)


@pytest.fixture(autouse=True)
def _sweep_known_server_pids_after_every_test() -> Iterator[None]:
    """Force-kill and reap anything left in `_KNOWN_SERVER_PIDS` once a test finishes.

    `_kill_and_reap_server_at`'s own cleanup can fail to reach a pid it already knew about — the
    socket stops answering *after* an earlier successful `health()` call but *before* that
    function's own kill attempt runs — and an indirectly-spawned server has no held `Popen` for
    any per-test cleanup to fall back on the way `_running_server`'s explicit child does. This is
    the backstop: whatever pid this module ever learned of and never confirmed reaped is killed
    and waited on here, every test, so a hung indirect child cannot silently outlive the test that
    spawned it and contend with a later test for the same socket path or file descriptors.
    """
    yield
    stragglers = list(_KNOWN_SERVER_PIDS)
    for pid in stragglers:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        # `TimeoutError` is suppressed here specifically, unlike every other reap site in this
        # module: this fixture runs after *every* test, so a straggler that still would not die
        # must not fail whichever test happens to run next by raising out of its own setup — the
        # primary "fail loudly on a stuck reap" guarantee lives in `_running_server`'s own
        # unconditional `process.wait()`, which raises for the test that actually caused the leak.
        # The pid is discarded from the registry only on a *confirmed* reap: a pid this attempt
        # could not confirm stays registered, so the very next test's own sweep retries it rather
        # than this fixture quietly asserting "eventually reaped" about a pid it never actually
        # saw exit.
        try:
            _reap(pid, deadline_seconds=5.0)
        except TimeoutError:
            continue
        _KNOWN_SERVER_PIDS.discard(pid)


def _config(store_dir: Path) -> EffectiveConfig:
    return resolve(store_dir / "system.toml", store_dir / "config.toml")


async def _create_store(store_dir: Path, encoder: FastEmbedEncoder) -> str:
    """Create a real store at `store_dir`, then close it, returning its `store_id`.

    The subprocess opens the store itself; this only needs `meta.store_id` up front, since
    `connect_start_if_absent`'s identity check requires the *client's own* resolved value to
    compare `health()`'s report against — a client cannot verify identity against a fact it never
    read for itself.
    """
    async with await Store.create(store_dir, _config(store_dir.parent), encoder) as store:
        return store.meta.store_id


def _server_command(sock_path: Path, store_dir: Path) -> list[str]:
    return [sys.executable, "-m", "zikaron.service.main", str(sock_path), str(store_dir)]


def _send(
    sock: socket.socket, method: str, params: dict[str, object], request_id: int = 1
) -> dict[str, object]:
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
    buffer = b""
    while not buffer.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed before a full response was read")
        buffer += chunk
    parsed = json.loads(buffer.decode("utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _wait_for_socket(sock_path: Path, *, deadline_seconds: float) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if sock_path.exists():
            return
        time.sleep(0.02)
    raise TimeoutError(f"{sock_path} never appeared")


def _wait_for_accepting_socket(sock_path: Path, *, deadline_seconds: float) -> None:
    """Wait until the socket **accepts a connection**, not until its file exists.

    **The two are different and the difference is a real flake.** `bind()` creates the path and
    `listen()` follows it, so between them the file exists and a `connect()` gets
    `ECONNREFUSED` — measured, as a gate failure at load ~7 in
    `test_client_retries_through_start_if_absent_when_the_server_exits_mid_connect`, which then
    passed 5 of 5 in isolation. `_wait_for_socket` is waiting on the *start* of the readiness
    window, which is the same observation recorded for the signal-handler race
    in the other direction.

    **`_wait_for_socket` is deliberately left alone rather than changed to this.** Its other caller
    is the test asserting a `SIGTERM` arriving *as soon as the socket appears* still unlinks it,
    and for that one the gap between appearing and being ready "is precisely what must not exist" —
    waiting for acceptance there would hide the defect the test exists to catch. One helper per
    question, because the two questions genuinely differ.
    """
    deadline = time.monotonic() + deadline_seconds
    last: OSError | None = None
    while time.monotonic() < deadline:
        if sock_path.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(1.0)
                probe.connect(str(sock_path))
            except OSError as error:  # not listening yet, or gone again
                last = error
            else:
                return
            finally:
                probe.close()
        time.sleep(0.02)
    raise TimeoutError(f"{sock_path} never accepted a connection (last error: {last})")


def _wait_for_pid_file(pid_file: Path, *, deadline_seconds: float) -> int | None:
    """The pid a fake test server wrote to `pid_file` immediately after binding, or `None` if it
    never appeared before the deadline — tolerant rather than raising, since this is a cleanup
    path and a fake process that never even started (for some unrelated reason) leaves nothing
    for this function to find, which is not itself a new failure to report."""
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if pid_file.exists():
            return int(pid_file.read_text())
        time.sleep(0.02)
    return None


def _kill_and_reap_from_pid_file(pid_file: Path) -> None:
    """Cleanup for a fake server whose pid is known only through a pid file, never through a
    successful `health()` exchange — the health-readiness regression tests below deliberately
    exercise `connect_start_if_absent` failing *before* it ever completes a health handshake, so
    `_kill_and_reap_server_at`'s own connect-and-ask-`health()` approach cannot discover a pid on
    exactly the path these tests exist to defend.

    Registered in `_KNOWN_SERVER_PIDS` *before* the kill/reap attempt, and discarded only once
    `_reap` actually confirms completion — mirroring `_kill_and_reap_server_at`'s own established
    pattern. A `TimeoutError` here must not silently drop the pid off the session-wide sweep's
    radar: if this attempt's own reap genuinely fails, the sweep fixture is the only remaining
    backstop, and it can only retry a pid it already knows about.
    """
    pid = _wait_for_pid_file(pid_file, deadline_seconds=_SPAWN_DEADLINE_SECONDS)
    if pid is None:
        return
    _KNOWN_SERVER_PIDS.add(pid)
    with suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    with suppress(TimeoutError):
        _reap(pid, deadline_seconds=5.0)
        _KNOWN_SERVER_PIDS.discard(pid)


def _runtime_dir(tmp_path: Path) -> Path:
    """A socket directory `security.ensure_runtime_dir` will actually accept: exactly `0700`,
    created fresh by this fixture rather than reusing `tmp_path` itself — whose own mode is
    pytest's to decide, not this module's, and both `main.run` and the client's own
    `connect_start_if_absent` vet whatever directory the socket sits in before using it."""
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    return runtime


def _spawn_server(sock_path: Path, store_dir: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603 - a fixed, test-controlled argv, not external input.
        _server_command(sock_path, store_dir),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


#: Every pid this module has ever discovered running a server, across every test in this session
#: — the register-as-you-learn-it half of the reaping guarantee. `_kill_and_reap_server_at`'s own
#: cleanup can fail to reach a pid it already knew about (the socket stops answering *after* an
#: earlier successful `health()` call but *before* cleanup runs), and for an indirectly-spawned
#: server there is no held `Popen` to fall back on the way `_running_server`'s explicit child has
#: — this registry is what lets a session-scoped sweep force-kill anything still alive that this
#: module ever learned the pid of, rather than the guarantee depending on the socket staying
#: reachable through to cleanup.
_KNOWN_SERVER_PIDS: set[int] = set()


def _kill_and_reap_server_at(sock_path: Path) -> None:
    """Kill and reap whatever process is actually listening at `sock_path` right now, by asking it.

    Every test below either holds a `Popen` for the server it explicitly spawned, or causes
    `connect_start_if_absent` to spawn a **new** one via `asyncio.to_thread` — a plain thread of
    *this same process*, not a subprocess, so that spawn is just as much a direct child of pytest
    as an explicit `Popen` is, and reaping it needs the identical mechanism. `os.waitpid` works
    for a pid this process is the real parent of whether or not anything still holds the `Popen`
    object that spawned it — confirmed directly (dropping the `Popen` immediately after spawning
    and reaping purely by pid still succeeds) — which is what lets one function reap either case:
    connect, ask `health()` for the pid it is actually running as, `SIGKILL` that pid directly —
    never `Popen.pid`, which after a respawn names a process that no longer exists — and
    `waitpid` it to completion, since a `kill()` with no `wait()` leaves a genuine zombie
    (`State: Z` in `/proc/<pid>/status`, measured directly) rather than merely a slow-to-notice
    absence.

    A discovered pid is added to `_KNOWN_SERVER_PIDS` the instant `health()` reports it —
    *before* this function attempts anything else — so a server that answers once and then stops
    responding before this function's own kill attempt is still covered by the session-scoped
    sweep (`_kill_all_known_server_pids`) even though this particular call cannot reach it.
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(str(sock_path))
        try:
            result = _send(sock, "health", {})["result"]
            assert isinstance(result, dict)
            pid = int(result["pid"])
        finally:
            sock.close()
    except OSError:
        return  # Nothing reachable at this path — nothing to kill.
    _KNOWN_SERVER_PIDS.add(pid)
    with suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    _reap(pid, deadline_seconds=5.0)
    _KNOWN_SERVER_PIDS.discard(pid)


def _reap(pid: int, *, deadline_seconds: float) -> None:
    """`os.waitpid(pid, 0)`, but bounded: a pid this process is not actually the parent of (an
    already-reaped one, or one this test never spawned at all) raises `ChildProcessError`, which
    is the ordinary case for a pid `_kill_and_reap_server_at` already fully cleaned up on an
    earlier call within the same test — not every caller of this function is the first to see a
    given pid die. Bounded via `os.WNOHANG` polling rather than a blocking wait with no timeout,
    and **raises on that bound** rather than silently returning: a cleanup helper that reports
    success on a timeout is indistinguishable from one that actually reaped, which is exactly the
    shape of bug this project's own coding standards ask every reader to be suspicious of — a
    guard that returns a *plausible* answer instead of failing loudly when it could not confirm
    one.

    Raises:
        TimeoutError: `pid` was not reaped before `deadline_seconds` elapsed.
    """
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return  # Not this process's child (already reaped, or never was) — nothing to do.
        if reaped_pid == pid:
            return
        time.sleep(0.02)
    raise TimeoutError(f"pid {pid} was not reaped within {deadline_seconds}s")


@asynccontextmanager
async def _running_server(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> AsyncIterator[tuple[Path, Path, str, subprocess.Popen[bytes]]]:
    """A real store, a real spawned service already listening on a real socket.

    Yields `(sock_path, store_dir, store_id, process)`. Cleanup asks whatever is actually
    listening at `sock_path` to identify itself and reaps *that* pid
    (`_kill_and_reap_server_at`, never `process.pid` directly — several tests below deliberately
    kill the original server and cause `connect_start_if_absent` to spawn a second one), then
    unconditionally kills and waits on the `Popen` this function itself holds regardless of
    whether the first step succeeded: neither step is optional, since a genuinely stuck child
    must fail the test loudly (`process.wait`'s own `TimeoutExpired`, left unsuppressed) rather
    than have this function's own cleanup silently report success on a timeout.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    store_id = await _create_store(store_dir, encoder)
    sock_path = _runtime_dir(tmp_path) / "server.sock"
    process = _spawn_server(sock_path, store_dir)
    try:
        _wait_for_accepting_socket(sock_path, deadline_seconds=_SPAWN_DEADLINE_SECONDS)
        yield sock_path, store_dir, store_id, process
    finally:
        try:
            _kill_and_reap_server_at(sock_path)
        finally:
            # Unconditional fallback, not a second competing reap: if the socket was never
            # reachable at all (a startup failure) or `_reap`'s own deadline was exceeded, the
            # process above raises rather than silently returning — a cleanup helper that reports
            # success on a timeout is indistinguishable from one that actually cleaned up. This
            # `finally` guarantees the one handle this function itself holds is dealt with either
            # way: `process.kill()` on an already-dead pid is a no-op past `ProcessLookupError`,
            # and `process.wait()` is unconditional so a genuinely stuck child still fails the
            # test loudly via `TimeoutExpired` rather than leaking silently past it.
            with suppress(ProcessLookupError):
                process.kill()
            process.wait(timeout=5.0)


# ---------------------------------------------------------------------------
# A bare connect is not a health-ready server
# ---------------------------------------------------------------------------


def _fake_server_script(
    tmp_path: Path, *, refused_attempts: int, pid_file: Path, ready_false_attempts: int = 0
) -> Path:
    """A tiny script that binds `sys.argv[1]` immediately, accepts connections immediately, but
    silently closes the first `refused_attempts` of them without ever writing a response —
    everything a would-be caller can observe during those attempts is a live, connected socket
    that never completes a real handshake, which is exactly the state `_poll_until_reachable`
    must not treat as "the service is ready" for. Counted by **connection attempts**, not
    wall-clock time, so the test is deterministic regardless of machine speed: the script does not
    need to race a timer against `_poll_until_reachable`'s own retry interval, it only needs to
    count.

    After `refused_attempts` is exhausted, the next `ready_false_attempts` connections receive a
    **structurally valid** response — matching identity, real JSON, no missing field — whose
    `ready` is the literal JSON boolean `false`. This is a different failure shape than a refused
    attempt on purpose: a refused connection gives `_health` nothing to parse at all, while this
    gives it something that parses correctly and would have been wrongly accepted as readiness by
    a naive `bool(result["ready"])` coercion, since a JSON `false` decodes to Python's `False` and
    `bool(False)` is `False` — so that specific bug would not actually be caught by a `false`
    response alone; `ready_false_attempts` exists to defend the *fixed* code's behavior going
    forward (require the literal `True`, not merely coerce), by asserting the caller keeps polling
    rather than stopping on the first structurally-valid-but-not-ready answer.

    Writes its own pid to `pid_file` immediately after binding, before accepting anything — this
    is deliberately independent of the health handshake this whole test exists to exercise:
    registering for cleanup by *reading a successful health response* would fail on exactly the
    regression path the test is meant to survive (a `connect_start_if_absent` that returns from a
    bare connect and then fails its own first `health()` call never reaches a response to read a
    pid from at all), so the caller reads this file to learn the pid *before* ever calling
    `connect_start_if_absent`.

    Written to a real file rather than passed as `python -c ...`, since the socket path, the
    pid-file path, and the two attempt counts all have to be baked in as literal argv-free
    constants for `_server_command`'s own fixed two-argument shape (`sock_path`, `store_dir`) to
    keep working unmodified as the argv `connect_start_if_absent` spawns — this script ignores its
    own `store_dir` argument entirely.
    """
    script = tmp_path / "fake_slow_server.py"
    script.write_text(
        f"""
import json
import os
import socket
import sys

sock_path = sys.argv[1]
refused_attempts = {refused_attempts}
ready_false_attempts = {ready_false_attempts}
attempt = 0
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(sock_path)
server.listen(5)
with open({str(pid_file)!r}, "w") as pid_out:
    pid_out.write(str(os.getpid()))

def _handle(conn):
    global attempt
    conn.settimeout(2.0)
    while True:
        buf = b""
        while not buf.endswith(b"\\n"):
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk
        request = json.loads(buf.decode())
        attempt += 1
        if attempt <= refused_attempts:
            # Accept the connection, read the request, then simply close with no response —
            # the exact "connected but not ready" state a bare-connect poll cannot distinguish
            # from success.
            conn.close()
            return
        response = {{
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {{
                "ready": attempt > refused_attempts + ready_false_attempts,
                "store_path": "/fake/memory.db",
                "store_id": "fake-store-id",
                "embed_model": "fake",
                "embed_dim": 1,
                "schema_version": 1,
                "pid": os.getpid(),
            }},
        }}
        conn.sendall((json.dumps(response) + "\\n").encode())
        # Deliberately does NOT close here: once past the refusal count, the connection stays
        # open for further requests on the same socket, which is what a genuinely ready server
        # does and what the "answers more than once" half of the regression test needs.

while True:
    conn, _ = server.accept()
    _handle(conn)
"""
    )
    return script


def _fake_server_command(script: Path, sock_path: Path, store_dir: Path) -> list[str]:
    return [sys.executable, str(script), str(sock_path), str(store_dir)]


async def test_a_connected_but_not_yet_health_ready_server_is_not_treated_as_started(
    tmp_path: Path,
) -> None:
    """`architecture.md` states spawning and polling `health()` as one step, with releasing the
    lock as the next, separate one — a process that *accepts a connection* well before it can
    actually answer `health()` (simulated here directly, without paying for a real store or a
    real model load) must not be mistaken for a ready service. If `_poll_until_reachable` treated
    a bare connect as success, this test's `connect_start_if_absent` would return a socket whose
    very first real request either times out or gets nothing back — this asserts it instead
    outlasts several silently-dropped attempts and returns a socket that genuinely answers, more
    than once.

    The fake server's own `accept()` loop runs forever until killed — there is no path on which
    it exits on its own — so this test's cleanup is in an unconditional `finally` around the
    entire `connect_start_if_absent` call, not only around the success path: a failure in that
    call (this fix regressing, or any other bug) must not be able to leak a permanently-running
    fake process for the rest of the test session.
    """
    sock_path = _runtime_dir(tmp_path) / "server.sock"
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    pid_file = tmp_path / "fake_server.pid"
    script = _fake_server_script(tmp_path, refused_attempts=3, pid_file=pid_file)

    sock = None
    try:
        sock, health = await asyncio.to_thread(
            connect_start_if_absent,
            sock_path,
            store_db_path=Path("/fake/memory.db"),
            store_id="fake-store-id",
            server_command=_fake_server_command(script, sock_path, store_dir),
        )
        assert health.ready is True
        assert health.store_id == "fake-store-id"
        # The returned socket must genuinely answer more than once — this proves
        # `connect_start_if_absent` handed back a socket to a server still accepting further
        # requests on the same connection, not merely one that happened to answer its very first
        # real exchange and would fail a second.
        second_response = _send(sock, "health", {})
        second_result = second_response["result"]
        assert isinstance(second_result, dict)
        assert second_result["ready"] is True
    finally:
        if sock is not None:
            sock.close()
        # Reaped from the pid file, not from a successful health response: the whole point of
        # this test is that `connect_start_if_absent` might raise having *never* completed a
        # health exchange if this fix regressed, and that is exactly the case cleanup must still
        # be able to reap. The pid file is written before the fake even starts accepting
        # connections, so `_wait_for_socket`-style polling for it here (rather than assuming it
        # is already there) is what makes this robust to a `connect_start_if_absent` that failed
        # very early, before the fake process itself had time to finish binding and writing it.
        _kill_and_reap_from_pid_file(pid_file)
        _kill_and_reap_server_at(sock_path)


async def test_a_structurally_valid_but_not_ready_health_response_is_not_treated_as_started(
    tmp_path: Path,
) -> None:
    """A response that parses correctly and carries a genuine, present `ready` field set to the
    JSON boolean `false` is a different failure shape than a refused connection with no response
    at all, and it is the one a naive `bool(result["ready"])` coercion would have silently
    accepted: `bool(False)` is `False`, so a literal `false` is not actually the case that specific
    bug got wrong — this test instead defends the *fixed* code's behavior going forward, that
    `_health` requires the literal `True` rather than merely truthiness. `ready_false_attempts=2`
    on top of `refused_attempts=3` means the fake answers twice with a structurally perfect but
    not-ready response before ever answering `true` — `_poll_until_reachable` must survive both
    kinds of non-readiness in the same run. This test sends only the literal `false`; it does not
    exercise a truthy-but-non-boolean value (a string, say) that `bool(...)` would have also
    wrongly accepted and `is True` correctly still refuses — that distinction is true of the fixed
    code by construction (`is True` accepts nothing but the literal boolean), but is not itself
    independently proven by a fixture that never sends such a value."""
    sock_path = _runtime_dir(tmp_path) / "server.sock"
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    pid_file = tmp_path / "fake_server.pid"
    script = _fake_server_script(
        tmp_path, refused_attempts=3, ready_false_attempts=2, pid_file=pid_file
    )

    sock = None
    try:
        sock, health = await asyncio.to_thread(
            connect_start_if_absent,
            sock_path,
            store_db_path=Path("/fake/memory.db"),
            store_id="fake-store-id",
            server_command=_fake_server_command(script, sock_path, store_dir),
        )
        assert health.ready is True
        assert health.store_id == "fake-store-id"
    finally:
        if sock is not None:
            sock.close()
        _kill_and_reap_from_pid_file(pid_file)
        _kill_and_reap_server_at(sock_path)


# ---------------------------------------------------------------------------
# Done-when 1: start-if-absent under two racing clients
# ---------------------------------------------------------------------------


async def test_two_clients_racing_a_cold_store_converge_on_one_server(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """Neither client has ever connected; both run `connect_start_if_absent` against the same
    socket path at (as close as achievable) the same instant. `architecture.md`'s sequence —
    connect, `flock`, connect again, spawn-if-still-dead — must converge on exactly one server
    process, per spike 3's own measurement of the identical race."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    store_id = await _create_store(store_dir, encoder)
    sock_path = _runtime_dir(tmp_path) / "server.sock"
    db_path = store_dir / "memory.db"

    def _connect_and_report_server_pid() -> int:
        """Runs in a worker thread: `connect_start_if_absent` is a blocking call by design, and
        two racers only genuinely contend for the lock if both are actually blocking, not merely
        `await`-ing on the same event loop."""
        sock, _health = connect_start_if_absent(
            sock_path,
            store_db_path=db_path,
            store_id=store_id,
            server_command=_server_command(sock_path, store_dir),
        )
        try:
            response = _send(sock, "health", {})
            result = response["result"]
            assert isinstance(result, dict)
            pid = int(result["pid"])
            # Registered the instant it is known, exactly as `_kill_and_reap_server_at` does —
            # this is precisely the case that helper's own cleanup-time `health()` call can miss
            # if the server becomes unreachable between this operation and that later cleanup, so
            # the registration cannot wait for that second, separate call to happen.
            _KNOWN_SERVER_PIDS.add(pid)
            return pid
        finally:
            sock.close()

    try:
        first_pid, second_pid = await asyncio.gather(
            asyncio.to_thread(_connect_and_report_server_pid),
            asyncio.to_thread(_connect_and_report_server_pid),
        )
        assert first_pid == second_pid, "two racers spawned two different server processes"
    finally:
        _kill_and_reap_server_at(sock_path)


# ---------------------------------------------------------------------------
# Done-when 2: a client connecting exactly as the server exits
# ---------------------------------------------------------------------------


async def test_client_retries_through_start_if_absent_when_the_server_exits_mid_connect(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """Connect while the server is genuinely alive, kill it, and observe the *in-flight*
    request fail — then confirm a fresh `connect_start_if_absent` recovers by respawning.

    This is the actual race `architecture.md` names ("a client can connect just as the service
    decides to exit, and its request then fails… `zikaron-mcp` retries once through the full
    start-if-absent sequence"), and it differs from the stale-socket scenario below in exactly
    the part that matters: here, a request is genuinely *in flight* against a server that then
    disappears out from under it, rather than the client only ever discovering an already-dead
    socket file.
    """
    async with _running_server(tmp_path, encoder) as (sock_path, store_dir, store_id, process):
        live_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        live_sock.settimeout(2.0)
        live_sock.connect(str(sock_path))

        process.kill()
        process.wait(timeout=5.0)

        with pytest.raises(BrokenPipeError):
            # The connection this client held is now against a process that no longer exists —
            # exactly "a client can connect just as the service decides to exit, and its request
            # then fails," simulated by a kill rather than by winning the real idle-exit race,
            # which the test below covers from the *server's* side.
            _send(live_sock, "health", {})
        live_sock.close()

        db_path = store_dir / "memory.db"
        sock, health = await asyncio.to_thread(
            connect_start_if_absent,
            sock_path,
            store_db_path=db_path,
            store_id=store_id,
            server_command=_server_command(sock_path, store_dir),
        )
        try:
            assert health.store_path == str(db_path)
            response = _send(sock, "health", {})
            result = response["result"]
            assert isinstance(result, dict)
            assert result["ready"] is True
        finally:
            sock.close()


# ---------------------------------------------------------------------------
# Done-when 3: a stale socket file
# ---------------------------------------------------------------------------


async def test_start_if_absent_clears_a_stale_socket_left_by_a_killed_server(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """A hard-killed process (`SIGKILL`, no cleanup at all) leaves a socket file that is still,
    structurally, a real uid-owned socket — the only shape `_vet_and_clear_stale_socket` is
    willing to unlink. This asserts both halves: the file is genuinely vettable as stale, and
    start-if-absent actually recovers through it rather than refusing to touch it — with no live
    connection ever made against the dead server, unlike the connecting-mid-exit scenario above."""
    async with _running_server(tmp_path, encoder) as (sock_path, store_dir, store_id, process):
        process.kill()
        process.wait(timeout=5.0)
        assert sock_path.exists()
        assert security.vet_socket_for_unlink(sock_path, uid=os.getuid()) is True

        db_path = store_dir / "memory.db"
        sock, health = await asyncio.to_thread(
            connect_start_if_absent,
            sock_path,
            store_db_path=db_path,
            store_id=store_id,
            server_command=_server_command(sock_path, store_dir),
        )
        try:
            assert health.ready is True
        finally:
            sock.close()


# ---------------------------------------------------------------------------
# Done-when 4: a refused foreign-store handshake
# ---------------------------------------------------------------------------


async def test_a_client_resolving_a_different_store_refuses_the_handshake(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """`architecture.md`: "a mismatch is not a retry: the client... treats the socket as
    foreign." A second store's client, pointed at the first store's live socket, must raise
    `STORE_IDENTITY` rather than proceeding — the whole reason `health()`'s handshake verifies
    **both** `store_path` and `store_id` rather than the path alone."""
    async with _running_server(tmp_path, encoder) as (sock_path, _store_dir, _store_id, _process):
        foreign_store_dir = tmp_path / "other" / ".zikaron"
        foreign_store_dir.mkdir(parents=True)
        foreign_store_id = await _create_store(foreign_store_dir, encoder)
        foreign_db_path = foreign_store_dir / "memory.db"

        with pytest.raises(ZikaronError) as excinfo:
            await asyncio.to_thread(
                connect_start_if_absent,
                sock_path,
                store_db_path=foreign_db_path,
                store_id=foreign_store_id,
                server_command=_server_command(sock_path, foreign_store_dir),
            )
        assert excinfo.value.code is ErrorCode.STORE_IDENTITY
        assert foreign_store_id in str(excinfo.value.data["expected"])


async def test_a_client_resolving_the_same_path_but_a_different_store_id_is_still_refused(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """The load-bearing case a path-only check would miss entirely: a store deleted and
    recreated at the identical path gets a fresh `store_id` (`Store.create` mints a new UUID
    every time), so `store_path` alone cannot distinguish "the store I resolved" from "a store
    that happens to live at the same path now." """
    async with _running_server(tmp_path, encoder) as (
        sock_path,
        store_dir,
        _stale_store_id,
        _process,
    ):
        db_path = store_dir / "memory.db"
        fabricated_store_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(ZikaronError) as excinfo:
            await asyncio.to_thread(
                connect_start_if_absent,
                sock_path,
                store_db_path=db_path,
                store_id=fabricated_store_id,
                server_command=_server_command(sock_path, store_dir),
            )
        assert excinfo.value.code is ErrorCode.STORE_IDENTITY


# ---------------------------------------------------------------------------
# Startup failures are diagnosable from service.log
# ---------------------------------------------------------------------------


async def test_a_config_failure_at_startup_is_logged_before_the_process_exits(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """The log is configured **before** config resolution runs, specifically so a malformed
    config file — which fails before `ServiceContext.assemble` ever opens the store — leaves a
    diagnosable trace rather than an unhandled traceback swallowed by the detached child's
    `/dev/null` stderr. The client-observable half of this (the spawn never becomes reachable) is
    already the design's own contract for every startup failure (`architecture.md` §"Degraded
    modes": `health()` never ready); what this asserts is the operator-observable half."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    (store_dir / "config.toml").write_text(
        "[retrieval]\nrrf_k = not valid toml\n", encoding="utf-8"
    )
    await _create_store(store_dir, encoder)
    sock_path = _runtime_dir(tmp_path) / "server.sock"
    process = _spawn_server(sock_path, store_dir)
    try:
        process.wait(timeout=10.0)
        assert process.returncode != 0
        log_text = (store_dir / "service.log").read_text(encoding="utf-8")
        assert "failed to start" in log_text
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)


async def test_a_store_open_failure_at_startup_is_also_logged(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """The startup `try` in `main.run()` wraps both config resolution *and*
    `ServiceContext.assemble()` — this asserts the second half specifically, with a real
    `reindexing` sentinel left behind by a (simulated) process that died mid-reindex, which fails
    inside `Store.open` itself rather than during config parsing. A fix that moved `assemble()`
    outside the `try` would pass the config-failure test above and still fail this one."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    await _create_store(store_dir, encoder)
    async with await Store.open(store_dir, _config(store_dir)) as store:
        await store.connection.execute(
            "INSERT INTO meta (key, value) VALUES ('reindexing', '2026-01-01T00:00:00+00:00')"
        )
        await store.connection.commit()

    sock_path = _runtime_dir(tmp_path) / "server.sock"
    process = _spawn_server(sock_path, store_dir)
    try:
        process.wait(timeout=10.0)
        assert process.returncode != 0
        log_text = (store_dir / "service.log").read_text(encoding="utf-8")
        assert "failed to start" in log_text
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)


# ---------------------------------------------------------------------------
# Idle self-stop and clean signal shutdown, end to end
# ---------------------------------------------------------------------------


async def test_a_signal_arriving_as_soon_as_the_socket_appears_still_unlinks_it(
    tmp_path: Path, encoder: FastEmbedEncoder
) -> None:
    """A real process, signalled at the earliest moment anything outside it can act — the instant
    the socket file appears — and the socket must be gone when it exits.

    **Renamed from `test_idle_self_stop_unlinks_the_socket_before_the_process_exits`, which named a
    path it never took**: `idle_timeout`'s minimum is 60 seconds, so this has always terminated by
    signal, as its own body said. The old name also hid what made it flaky. Signalling here races
    whatever `run()` still has to do after `serve()` publishes the socket, and until the handlers
    were moved ahead of the bind the default `SIGTERM` disposition won that race under load and
    left the file behind. That ordering is asserted directly, in-process, by
    `test_service_main.py::test_the_signal_handlers_are_installed_before_the_socket_is_bound`;
    what this test adds is that a real spawned process, with a real model load and a real store
    open behind it, honours the same guarantee end to end.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    # The shortest legal `idle_timeout` (60 s, `schema.md`'s declared minimum), written so the idle
    # path sits as near this test as it legally can and still cannot fire inside the 5 s wait below
    # — which is why the signal is the only exit this exercises.
    (store_dir / "config.toml").write_text("[service]\nidle_timeout = 60\n", encoding="utf-8")
    await _create_store(store_dir, encoder)
    sock_path = _runtime_dir(tmp_path) / "server.sock"
    process = _spawn_server(sock_path, store_dir)
    try:
        _wait_for_socket(sock_path, deadline_seconds=_SPAWN_DEADLINE_SECONDS)
        # Signalled with no settling pause on purpose: the gap between the socket appearing and
        # the process being ready to handle a signal is precisely what must not exist, so a sleep
        # here would hide the defect this test is for rather than stabilise it.
        process.terminate()
        process.wait(timeout=5.0)
        assert not sock_path.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
