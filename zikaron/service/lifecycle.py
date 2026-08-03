"""Idle self-stop, and the start-if-absent sequence every client of this service runs.

`architecture.md` §Lifecycle is normative for both halves. Idle self-stop is server-side: a
background task that polls the store's own activity clock and exits the process when it has been
idle past `idle_timeout` with nothing in flight, unlinking the socket first so no client mistakes
a dead server for a live one. Start-if-absent is client-side, and lives here rather than in a
future `mcp`/`hook` package because M9's own integration tests are the first thing that needs to
exercise the exact race conditions `architecture.md` names — connect, `flock`, connect again,
vet-and-unlink-stale, spawn detached, poll `health()` — and M10/M11 reuse this unmodified rather
than each writing their own copy of a six-step sequence that must agree on every step.
"""

import asyncio
import errno
import fcntl
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.service import security
from zikaron.service.context import ServiceContext
from zikaron.service.server import RunningServer

#: `architecture.md` §Lifecycle: "a background task polls every 30 s."
IDLE_POLL_INTERVAL_SECONDS = 30.0

#: How long start-if-absent waits for a freshly spawned server to answer `health()` before giving
#: up. Generous relative to the ~101 ms cold-start figure `research/spike-results.md` measured, to
#: absorb slower CI/container environments without becoming a source of flaky tests.
_HEALTH_POLL_DEADLINE_SECONDS = 10.0
_HEALTH_POLL_INTERVAL_SECONDS = 0.05
_CONNECT_TIMEOUT_SECONDS = 1.0

#: The two `OSError` codes `architecture.md` names as the signature of "nobody is listening" —
#: either the socket file has never existed (`ENOENT`) or it exists but no process has it bound
#: (`ECONNREFUSED`, the exact shape a service that died without cleaning up leaves behind). Any
#: *other* `OSError` — `EACCES`, `ECONNRESET`, a permissions problem on the socket file itself —
#: is not "absent," and treating it as a reason to spawn a second server would paper over a real
#: failure this sequence has no business recovering from silently.
_ABSENT_SERVER_ERRNOS = frozenset({errno.ENOENT, errno.ECONNREFUSED})


def _is_absent_server(error: OSError) -> bool:
    return error.errno in _ABSENT_SERVER_ERRNOS


async def idle_self_stop(
    ctx: ServiceContext, server: RunningServer, sock_path: Path, *, original_store_inode: int
) -> None:
    """Poll until the store is idle past `idle_timeout` with nothing in flight, or until the
    store this process has open is no longer the one currently on disk at its own path — then
    stop, for whichever reason fired first.

    Runs as a background task for the life of the process; cancel it to shut down without
    triggering either exit condition, as `main.py`'s signal handler does. Unlinks `sock_path`
    **before** closing the server, so no client's `connect()` can ever observe a socket file this
    process is about to stop listening on without also finding it gone — a window there would be
    exactly the "connect exactly as the server exits" race `architecture.md` requires the *client*
    to survive, and closing that window here is strictly better than relying only on the client's
    retry.

    `server.shut_down()` — not a bare `server.server.close(); await server.server.wait_closed()`
    — because a client that finished a request and kept its connection open (the documented norm:
    `architecture.md` "the client adopts the returned label and reuses it for its process
    lifetime") makes `wait_closed()` alone block forever, measured directly against this
    project's own pinned Python 3.12.3: `wait_closed()` explicitly waits until all accepted
    connections are dropped, not merely until new ones stop being accepted. `RunningServer.
    shut_down` closes every tracked connection first, which is what makes this actually return.

    **`original_store_inode` is a required parameter, captured by the caller, not by this
    function.** `main.py` reads it from `ctx.store.opened_inode` — a field `Store.open`/`Store.
    create` set immediately after their own `aiosqlite.connect()` returned, with no `await` in
    between (`zikaron.core.store.store._open_connection`'s own docstring has the full reasoning
    for this capture point, including the narrow, human-authorized gap it deliberately accepts
    rather than a materially larger VFS-level integration).

    The check itself compares the *current* path's inode against `original_store_inode` — a
    `memory.db` deleted and recreated at the identical path afterward gets a different inode at
    that path immediately, while this process's own connection keeps its own file descriptor
    bound to the original inode regardless — confirmed directly, not only reasoned about
    SQLite's own fd semantics (`architecture.md` §"Idle self-stop", which also has the further
    measurement that a real operation on that connection can still genuinely fail afterward,
    rather than silently and successfully serving stale data forever — either outcome is exactly
    "this connection is no longer the one to keep going", which is what this poll stops rather
    than waits out). The file being briefly *absent* (deleted, nothing recreated yet) is treated
    identically to a changed inode: either way, this process's own open store is not the one
    currently on disk at its path, which is the condition this check exists to catch, not
    specifically "was it replaced by another file."
    """
    idle_timeout = ctx.config.get_int("idle_timeout")
    while True:
        await asyncio.sleep(IDLE_POLL_INTERVAL_SECONDS)
        if ctx.activity.may_stop(idle_timeout=idle_timeout) or _store_path_now_differs(
            ctx.store.path, from_inode=original_store_inode
        ):
            sock_path.unlink(missing_ok=True)
            await server.shut_down()
            return


def _store_path_now_differs(store_path: Path, *, from_inode: int) -> bool:
    """Whether `store_path` currently resolves to a different file than `from_inode` names.

    Only `FileNotFoundError` is folded into "yes, differs" alongside a genuine inode mismatch —
    the store being briefly absent (deleted, nothing recreated yet) is, like a changed inode,
    "this process's own open store is not the one currently on disk at its path." Any *other*
    `OSError` (`PermissionError`, `EIO`, a transient filesystem hiccup on an otherwise-untouched
    path) is **not** treated as a replacement: it propagates, so a caller polling on a fixed
    interval sees a genuine, unexpected stat failure rather than an unconditional, potentially
    wrong shutdown decision made on its behalf. This mirrors `architecture.md` §"Idle self-stop",
    which names only absence or a changed inode as the replacement signal.
    """
    try:
        return store_path.stat().st_ino != from_inode
    except FileNotFoundError:
        return True


def _connect(sock_path: Path, *, timeout: float) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(sock_path))
    except BaseException:
        sock.close()
        raise
    return sock


def _send_request(sock: socket.socket, method: str, params: dict[str, object]) -> dict[str, object]:
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
    buffer = b""
    while not buffer.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed before a full response was read")
        buffer += chunk
    parsed = json.loads(buffer.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ConnectionError("response was not a JSON object")
    return parsed


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """`health()`'s result, as the client needs it to verify store identity before its first
    real request — the fields named in `architecture.md`'s handshake."""

    ready: bool
    store_path: str
    store_id: str


def _health(sock: socket.socket) -> HealthCheck:
    """`health()`'s result, requiring a genuine JSON boolean `true` for `ready` — not merely a
    truthy value. `bool(result["ready"])` would have accepted the JSON string `"false"` (a
    non-empty string is truthy in Python) as readiness, and would have accepted a real `false`
    the same way every other truthy-but-wrong value is accepted: this function's whole job is to
    distinguish "the process is ready" from "the process answered but is not ready yet," and a
    JSON boolean is the one shape `architecture.md`'s handshake actually specifies for the field,
    so this rejects anything else rather than coercing it into an answer. Every caller already
    treats this function raising the same way it treats a connection failure — `_poll_until_
    reachable`'s spawn-branch loop keeps polling, and `connect_start_if_absent`'s bare-connect
    branches close the socket and propagate — so raising here rather than merely returning
    `ready=False` is what makes those existing reactions the deciding path instead of a value a
    caller could still fail to check.
    """
    response = _send_request(sock, "health", {})
    result = response.get("result")
    if not isinstance(result, dict):
        raise ConnectionError(f"health() did not return a result: {response!r}")
    ready = result["ready"]
    if ready is not True:
        raise ConnectionError(f"health() reported ready={ready!r}, not the JSON boolean true")
    return HealthCheck(
        ready=True,
        store_path=str(result["store_path"]),
        store_id=str(result["store_id"]),
    )


def _spawn_detached(server_command: Sequence[str]) -> None:
    process = subprocess.Popen(  # noqa: S603 — `server_command` is caller-supplied and not built
        # from untrusted request data; it is the fixed argv this process's own caller decided to
        # spawn.
        list(server_command),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # `start_new_session=True` gives the child its own session and process group — it has no
    # controlling terminal and is not in this process's own process group — but it does **not**
    # reparent the child to `init`; that requires a double-fork, which this does not do. This
    # process remains the child's real OS-level parent for as long as *this* process lives, which
    # matters here specifically because the real clients this sequence serves (`zikaron-mcp`,
    # `zikaron-hook`) are themselves long-lived relative to the service's own idle-timeout
    # lifecycle: if the service later self-stops while the client that started it is still
    # running, dropping the `Popen` with no further action leaves a genuine zombie the instant the
    # service exits — measured directly, not assumed: a child that exits on its own with its
    # `Popen` handle already discarded and never `wait()`-ed on shows `State: Z` in
    # `/proc/<pid>/status` for as long as the parent keeps running. A daemon thread that blocks on
    # `wait()` reaps it without making this function itself block, and being a daemon thread means
    # it does not keep the *client* process alive past whatever else it was doing.
    threading.Thread(target=process.wait, daemon=True).start()


def connect_start_if_absent(
    sock_path: Path, *, store_db_path: Path, store_id: str | None, server_command: Sequence[str]
) -> tuple[socket.socket, HealthCheck]:
    """`architecture.md`'s six-step sequence, exactly: vet the runtime directory, connect,
    `flock`, connect again, vet and spawn if still dead, release the lock, verify identity.

    The runtime directory is vetted **before the very first connect attempt**, not only before
    spawning — `architecture.md` §"Filesystem security": "reject, never repair, a hostile runtime
    path... before creating or using it." A socket already reachable through a hostile directory
    would otherwise let this sequence connect straight through it without ever vetting anything,
    on exactly the common path where a server already answers and nothing about this call ever
    reaches the spawn branch that used to be the only place the check ran.

    Blocking, deliberately: every thin client this sequence serves (M9's own tests today, M10/M11
    later) is a short-lived process making one connection attempt, not an event loop — spawning an
    `asyncio` runtime merely to run a `connect()` and a `flock` would cost more than either
    operation saves.

    Args:
        sock_path: where the socket should be, once the sequence completes.
        store_db_path: this client's own resolved `memory.db` path, checked against `health()`'s
            `store_path` at the very end.
        store_id: this client's own resolved `meta.store_id`, when it has one to check — a path
            alone cannot rule out a store that was deleted and recreated at the identical path
            with a different identity, which is why `architecture.md` requires both checked
            wherever a caller *can* supply an id. **`None` means "this caller has no independent
            store id to compare against,"** which covers two distinct cases, not only one: the
            ordinary bootstrap case (the store does not exist on disk yet, so there is nothing to
            have read — `zikaron-service`'s own first startup is what mints one, §"First run" in
            `architecture.md`), and `zikaron-hook`'s own **permanent** case (every invocation is a
            fresh, single-shot process with no connection of its own from an earlier call to have
            learned an id from, and reading one directly from `memory.db` would violate the no
            store-access invariant that client holds — §"Store identity is verified, not assumed"
            names this exception explicitly). A caller passing `None` in either case is trusting
            whichever identity this call's *own* connection reports, which is sound specifically
            because that identity comes from a connection this exact call either found already
            listening or itself spawned and waited on synchronously — never from a value merely
            asserted by an unrelated, previously-established connection. Whatever gap a purely
            path-only check leaves for the permanent case is closed on the *service* side instead
            (§"Idle self-stop"'s own inode-drift self-stop), not by strengthening this argument.
            `store_db_path` is still compared unconditionally either way, since that value is
            computable from `sock_path` alone with nothing to open.
        server_command: the argv to spawn if no server answers — the caller's own choice of
            interpreter and entry point, since this module has no opinion about how the service is
            packaged.

    Returns:
        `(sock, health)` — a connected socket and the identity it reported, checked against
        `store_db_path` unconditionally and against `store_id` whenever one was given.

    Raises:
        ZikaronError: `STORE_IDENTITY` — a server answered, but `store_db_path` disagreed, or
            `store_id` was given and disagreed — exactly `architecture.md`'s `{expected, actual}`
            payload shape for that code.
        ConnectionError: no server became reachable before the deadline.
    """
    sock, already_confirmed_health = _try_connect_twice_under_lock(
        sock_path, server_command=server_command
    )
    try:
        health = already_confirmed_health if already_confirmed_health is not None else _health(sock)
    except BaseException:
        # The spawn branch's own `HealthCheck` is always already confirmed — this only runs for
        # the two bare-connect branches, where a previously reachable server could still close or
        # malform its response during this handshake. `sock` was never handed to any inner
        # consumer that would have closed it, so closing it here is this function's job.
        sock.close()
        raise
    if store_id is None:
        if store_db_path != Path(health.store_path):
            sock.close()
            raise ZikaronError(
                ErrorCode.STORE_IDENTITY, expected=str(store_db_path), actual=health.store_path
            )
        return sock, health
    expected = f"{store_db_path}#{store_id}"
    actual = f"{health.store_path}#{health.store_id}"
    if expected != actual:
        sock.close()
        raise ZikaronError(ErrorCode.STORE_IDENTITY, expected=expected, actual=actual)
    return sock, health


def _try_connect_twice_under_lock(
    sock_path: Path, *, server_command: Sequence[str]
) -> tuple[socket.socket, HealthCheck | None]:
    """Connect, `flock`, connect again, vet-and-spawn-and-poll-`health()` if still dead.

    Returns a `HealthCheck` alongside the socket only for the branch that actually spawned a new
    process — the one case this function itself must confirm readiness before releasing the lock,
    per `architecture.md`'s "spawn... then poll `health()`... release the lock" ordering. The two
    "already connected" branches (steps 1 and 3: a bare reachability check for "another client
    may have won and already started it") return `None` for the health check, since
    `connect_start_if_absent`'s own step 6 — verify identity from `health()`, after the lock — is
    unconditional and runs for every branch anyway; only the spawn branch needs this function to
    have confirmed health *before* releasing the lock, since it is the one branch where "the
    process exists" and "the process is ready" can genuinely disagree for as long as
    `ServiceContext.assemble()`'s own model load takes.
    """
    security.ensure_runtime_dir(sock_path.parent, uid=security.current_uid())
    try:
        return _connect(sock_path, timeout=_CONNECT_TIMEOUT_SECONDS), None
    except OSError as error:
        if not _is_absent_server(error):
            raise
        # ENOENT (never served) or ECONNREFUSED (a dead server's stale socket) — either way, the
        # sequence below is what recovers. Any other OSError propagates: it is not "absent," and
        # treating it as a reason to spawn a second server would paper over a real failure.

    lock_fd = os.open(str(sock_path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            return _connect(sock_path, timeout=_CONNECT_TIMEOUT_SECONDS), None
        except OSError as error:
            if not _is_absent_server(error):
                raise
            # Still dead once the lock was acquired — nobody else won the race either.
        _vet_and_clear_stale_socket(sock_path)
        _spawn_detached(server_command)
        return _poll_until_reachable(sock_path)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _vet_and_clear_stale_socket(sock_path: Path) -> None:
    """Unlink `sock_path` if, and only if, it is a real socket this uid owns.

    `architecture.md`: "never unlink a socket you have not vetted." A path that fails the check —
    present but not a socket, or owned by someone else — is left alone rather than removed, since
    removing it would be exactly the local symlink-attack shape the design refuses to perform.
    """
    if security.vet_socket_for_unlink(sock_path, uid=security.current_uid()):
        sock_path.unlink()


def _poll_until_reachable(sock_path: Path) -> tuple[socket.socket, HealthCheck]:
    """Poll until a **genuine `health()` response** comes back, not merely a connected socket.

    `architecture.md` §Lifecycle states this precisely as one step, "spawn... then poll
    `health()` until a deadline," with "release the lock" as the *next*, separate step — a bare
    TCP-style connect succeeding is not the condition either sentence names. A freshly spawned
    process can accept a connection well before it has finished `ServiceContext.assemble()`'s own
    slow model load, or it can accept one and then crash mid-handshake; polling only for the
    connect to succeed would release the lock the instant either of those transient, misleading
    states occurs, exactly the premature-release failure this function exists to rule out. Each
    failed attempt's own socket is closed before the next is opened, so a slow or half-answered
    connection does not accumulate open file descriptors across the polling loop.
    """
    deadline = time.monotonic() + _HEALTH_POLL_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        try:
            sock = _connect(sock_path, timeout=_CONNECT_TIMEOUT_SECONDS)
        except OSError:
            time.sleep(_HEALTH_POLL_INTERVAL_SECONDS)
            continue
        try:
            return sock, _health(sock)
        except (OSError, ConnectionError, KeyError, ValueError):
            # Connected, but the process is not yet answering `health()` correctly — still
            # starting up, or it accepted the connection and then died. Close this attempt's
            # socket and keep polling rather than treating a connect alone as success.
            sock.close()
            time.sleep(_HEALTH_POLL_INTERVAL_SECONDS)
    raise ConnectionError(f"no server became reachable at {sock_path} before the deadline")


def default_server_command(sock_path: Path, store_dir: Path) -> list[str]:
    """The argv `main.py` expects: this interpreter, the service module, the socket and store."""
    return [sys.executable, "-m", "zikaron.service.main", str(sock_path), str(store_dir)]
