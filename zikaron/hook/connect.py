"""The hook's own single-attempt connect-or-start sequence.

`architecture.md` §Lifecycle's five-step start-if-absent sequence is normative, and
`zikaron.service.lifecycle.connect_start_if_absent` already implements it — but that module also
imports `zikaron.service.context` and `zikaron.service.server` for its unrelated `idle_self_stop`
function, which pulls `aiosqlite`, `sqlite-vec` and `fastembed`'s own dependency chain into any
process that imports the module at all, whichever function it actually calls (verified directly:
`import zikaron.service.lifecycle` adds `aiosqlite`, `numpy` and `sqlite_vec` to `sys.modules`).
Importing it here would violate this package's own stdlib-only contract before a single request
is ever sent, so this module re-implements the same five steps rather than importing that one —
including the `flock`: two racing callers can each observe the socket absent at the same instant,
and without a lock serializing the vet-and-clear-stale-socket-and-spawn sequence, one caller can
unlink a socket the *other* has just bound and is already live on, forcing a second, redundant
service to start against a store the first is already correctly serving.

**This reimplementation differs from the one it mirrors in two ways that matter here.** First,
no *second outer attempt* after this one's own five-step sequence fails.
`lifecycle.py`'s own sequence is that whole five-step race-safe procedure and runs to
completion or raises — there is no looping inside it to narrow — but
`zikaron.mcp.connection.ServiceConnection` wraps a call to it in an outer retry (`_MAX_ATTEMPTS =
2`) for a long-running process that can afford to try the sequence a second time when an
already-established connection turns out to be dead. The hook has no equivalent connection to
have gone stale — every invocation is a fresh, single-shot process — and a user's message is
waiting on it, so this module runs the five-step sequence exactly once: one connect, one lock, one
recheck, one possible spawn, one poll to one deadline, then whatever the outcome is. A failure
here is handed straight to the caller's degraded-mode path rather than retried, which is what
keeps a slow or wedged service from costing the user two deadlines instead of one.

Second, what ends a wait. Here it is the caller's deadline, for the lock as well as the poll;
`lifecycle.py` blocks on the lock and polls to a fixed deadline of its own. Both end the poll early
when the process they spawned fails — an exit because another service holds the store is not a
failure, and that service is waited for instead. A user waits on every second of this one, so
another client's start is not waited out past the deadline any more than its own, and a service
the poll was queued behind is not called a start once it has stalled.

Reuses `zikaron.service.paths` and `zikaron.service.security` directly: both were verified to
import cleanly with no non-stdlib package added to `sys.modules`, so borrowing their path
derivation and filesystem-vetting logic does not compromise this package's own contract, and it
keeps the *safety* rules — never unlink an unvetted socket, never trust a hostile runtime
directory — identical to the ones `zikaron-service` and `zikaron-mcp` already enforce, rather than
a third, independently-written copy of the same two checks that could drift from the other two.
"""

import errno
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from zikaron.hook import rpc
from zikaron.service import paths, security

_POLL_INTERVAL_SECONDS = 0.05
_CONNECT_TIMEOUT_SECONDS = 0.3

#: What a spawned service exits with when another already holds its store: that one is serving or
#: starting the store, so a poll that sees it goes on looking. A child normally waits longer than a
#: push's whole deadline before it exits that way, which is why a queued push is decided at its
#: deadline by `_raise_if_queued_behind_a_stalled_start` and not by this. Restated rather than
#: imported from `zikaron.service.ownership`, which would bring `asyncio` into a process that runs
#: once per message (~27 ms measured here); a guard test holds the two equal.
_ANOTHER_SERVICE_EXIT_STATUS = os.EX_TEMPFAIL

#: How long another service holding the store may go without a sign of life, not shutting down,
#: before a push queued behind it stops calling the wait a start. A serving service renews that
#: sign on every idle poll, so only a holder that has stopped polling gets this old — a start that
#: never reached its first poll, or a service whose loop is stuck. One that has gone this long has
#: stalled — the operator has to hear about it — while a start that legitimately runs longer, a
#: first run fetching its model over a slow link, costs every message after that minute an alarm
#: until it binds, rather than going unreported forever.
_STALLED_START_SECONDS = 60.0

#: `architecture.md`: "`ECONNREFUSED` on an existing socket file is the signature of a service
#: that died without cleaning up — unlink and respawn rather than reporting an error," and
#: `ENOENT` is the plainer case of a socket that was never created. Mirrors
#: `zikaron.service.lifecycle._ABSENT_SERVER_ERRNOS` exactly, restated here rather than imported
#: since importing that module at all is what this file exists to avoid.
_ABSENT_SERVER_ERRNOS = frozenset({errno.ENOENT, errno.ECONNREFUSED})


class HookTransportError(Exception):
    """No server became reachable: nothing answered, the one spawned here exited first, or the
    start this attempt was queued behind has stalled.

    Its two subclasses name more specific reasons — a spawned service still starting, and a
    reachable one serving a different store — and stay subclasses so a caller that only asks
    whether this single attempt succeeded can catch this one base type.
    """


class ServiceStartingError(HookTransportError):
    """A start was still running at the poll deadline: the service this attempt spawned had not
    yet answered `health()`, or another client still held the start-if-absent lock, which it
    holds only while it starts one. A start that is slow, not one that failed — a spawned process
    that exits before answering raises the plain `HookTransportError` instead.

    `waited_on` says which: `lock` or `poll`.
    """

    def __init__(self, message: str, *, waited_on: Literal["lock", "poll"]) -> None:
        self.waited_on = waited_on
        super().__init__(message)


class StoreIdentityError(HookTransportError):
    """A reachable server's `health()` disagreed with this client's own resolved
    `store_db_path`/`store_id` — `architecture.md`'s `-32030 store_identity`, §"Store identity is
    verified, not assumed". Carries the two values the design's own error payload names
    (`{expected, actual}`) so a caller can log them rather than only a formatted message string.
    """

    def __init__(self, *, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"store_identity: expected={expected} actual={actual}")


@dataclass(frozen=True, slots=True)
class Health:
    """`health()`'s result, as this client uses it: the store's identity, and whether the service
    is still loading its model and how long it has had its store open. A service too old to report
    the last two is read as loaded, with no uptime."""

    store_path: str
    store_id: str
    model_loaded: bool = True
    uptime_seconds: float | None = None

    def still_loading_within(self, seconds: float) -> bool:
        """Whether this service is still starting: loading its model, its store open under
        `seconds`. One still loading after longer has stalled, and is not a start."""
        return (
            not self.model_loaded
            and self.uptime_seconds is not None
            and self.uptime_seconds < seconds
        )


@dataclass(frozen=True, slots=True)
class Connection:
    """What `connect_once` hands back: a connected socket whose service's identity is verified.

    `cold_start` is true when nothing answered this attempt's first connect — whether this attempt
    then spawned the service or a racing client did while this one waited for the lock. `health`
    is what the service answered, read once over `sock`.
    `sock`'s timeout is whatever `_health` left of `_CONNECT_TIMEOUT_SECONDS`; the caller sets its
    own before a request.
    """

    sock: socket.socket
    cold_start: bool
    health: Health


def connect_once(
    sock_path: Path,
    *,
    store_db_path: Path,
    store_id: str | None,
    server_command: Sequence[str],
    poll_deadline: float,
) -> Connection:
    """One pass through `architecture.md`'s start-if-absent sequence: connect; on absence, take
    the `flock` and connect again, since another client may have started the service while this
    one waited for it; only then vet, spawn and poll; verify identity.

    **One outer attempt with an internal lock, not two outer attempts.** Without the lock, two
    hooks — or a hook and `zikaron-mcp` — can both see the socket absent, and the second can
    vet-and-unlink the first one's now-live socket before spawning a second server at the same
    path. Nothing here retries the sequence once it has failed.

    Args:
        poll_deadline: the `time.monotonic()` instant this attempt stops waiting — for the lock,
            and for a service it spawned. The caller's, because both waits spend its budget.

    Raises:
        ServiceStartingError: a start was still running at `poll_deadline` — this attempt's, or
            the one another client holds the lock for.
        HookTransportError: no server became reachable — the one spawned here exited first, or
            was queued behind a stalled start — or a reachable one's `health()` disagreed with
            `store_db_path`/`store_id`.
        OSError: a filesystem or vetting failure distinct from "the server is absent".
        ZikaronError: `security.ensure_runtime_dir` refused the runtime directory. It propagates
            as itself: there is no fallback to degrade through a directory this attempt does not
            trust.
    """
    security.ensure_runtime_dir(sock_path.parent, uid=security.current_uid())
    sock = _try_connect(sock_path)
    cold_start = sock is None
    if sock is None:
        sock, health = _start_under_lock(
            sock_path, server_command=server_command, poll_deadline=poll_deadline
        )
    else:
        health = _health_or_close(sock)
    _verify_identity(health, store_db_path=store_db_path, store_id=store_id, sock=sock)
    return Connection(sock=sock, cold_start=cold_start, health=health)


def _start_under_lock(
    sock_path: Path, *, server_command: Sequence[str], poll_deadline: float
) -> tuple[socket.socket, Health]:
    """The sequence's locked half, releasing the lock on every exit path."""
    lock_fd = os.open(str(paths.lock_path(sock_path)), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_by(lock_fd, deadline=poll_deadline)
        # Recheck before touching the socket file at all, so a live socket another client bound
        # while this one waited is never mistaken for a stale one.
        sock = _try_connect(sock_path)
        if sock is not None:
            return sock, _health_or_close(sock)
        _vet_and_clear_stale_socket(sock_path)
        child = _spawn_detached(server_command)
        return _poll_until_reachable(sock_path, deadline=poll_deadline, child=child)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _lock_by(lock_fd: int, *, deadline: float) -> None:
    """Take the start-if-absent lock, waiting for it until `deadline` and no longer.

    Another client holds the lock only while it starts the service, through a poll of its own that
    can outlast this one's whole budget, so a blocking wait would leave the harness to kill this
    process — which records nothing. That poll ends at once on a start that has failed, so a lock
    still held at the deadline is a start still running.

    Raises:
        ServiceStartingError: the lock was still held at `deadline`.
    """
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise ServiceStartingError(
                    "another client is still starting the service", waited_on="lock"
                ) from None
            time.sleep(_POLL_INTERVAL_SECONDS)
        else:
            return


def _health_or_close(sock: socket.socket) -> Health:
    try:
        return _health(sock)
    except BaseException:
        sock.close()
        raise


def _verify_identity(
    health: Health, *, store_db_path: Path, store_id: str | None, sock: socket.socket
) -> None:
    """`architecture.md`'s handshake: `store_path` always, `store_id` whenever this client has an
    independent one to compare against. `None` covers this client's own permanent case — every
    invocation is a fresh, single-shot process with no independent id to have read, never merely
    "this store does not exist on disk yet" — per §"Store identity is verified, not assumed"'s
    own hook exception.
    """
    if store_db_path != Path(health.store_path):
        sock.close()
        raise StoreIdentityError(expected=str(store_db_path), actual=health.store_path)
    if store_id is not None and store_id != health.store_id:
        sock.close()
        raise StoreIdentityError(expected=store_id, actual=health.store_id)


def _try_connect(sock_path: Path) -> socket.socket | None:
    """A bare connection attempt: the socket on success, `None` if nobody is listening yet.

    Any `OSError` *other* than the absent-server signature propagates rather than being folded
    into `None` — an `EACCES` or a permissions problem on the socket file itself is not "nobody is
    listening," and treating it as a reason to spawn a second server here would paper over a real
    failure this single attempt has no business recovering from silently.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(_CONNECT_TIMEOUT_SECONDS)
    try:
        sock.connect(str(sock_path))
    except OSError as error:
        sock.close()
        if error.errno in _ABSENT_SERVER_ERRNOS:
            return None
        raise
    return sock


def _vet_and_clear_stale_socket(sock_path: Path) -> None:
    """Unlink `sock_path` if, and only if, it is a real socket this uid owns.

    `architecture.md`: "never unlink a socket you have not vetted" — identical rule and identical
    helper (`zikaron.service.security.vet_socket_for_unlink`) to the one `zikaron.service.lifecycle`
    already enforces, so a stale-socket decision made here agrees with the one the service and the
    MCP client would have made in this function's place.
    """
    if security.vet_socket_for_unlink(sock_path, uid=security.current_uid()):
        sock_path.unlink()


def _spawn_detached(server_command: Sequence[str]) -> subprocess.Popen[bytes]:
    """Start the service in a session of its own, and hand back its handle so the poll can see it
    exit. Nothing waits on it beyond that: the service outlives this process by design.
    """
    return subprocess.Popen(  # noqa: S603 — `server_command` is caller-supplied, the fixed argv
        # this process's own caller decided to spawn, never built from request data.
        list(server_command),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _poll_until_reachable(
    sock_path: Path, *, deadline: float, child: subprocess.Popen[bytes]
) -> tuple[socket.socket, Health]:
    """Poll for a genuine `health()` answer, not merely a connect, until `deadline` — and stop at
    once if `child` exits, because a service that cannot start would otherwise cost every message
    the whole deadline. A child that exits because another service holds the store is the
    exception: that service is the one to wait for, so the poll goes on.

    A freshly spawned process can accept a connection before it can answer anything, so a poll
    that stopped at `connect()` would hand the caller a socket the service is not yet serving on.
    Answering `health()` is the readiness signal because it is the first thing that requires the
    store to be open.

    It does **not** mean the model is loaded. The service binds while a deferred load is still
    running, deliberately, so a `health()` answer bounds the wait for the *store* and not for the
    first embedding — the request after it may still block on the model.

    Returns:
        The socket and the `Health` already read from it. The caller must not ask `health()` again
        over this connection: a peer that answers one request per connection has nothing left.

    Raises:
        HookTransportError: `child` failed — exited, for any reason but another service holding
            the store, without anything answering — or, at `deadline`, it was still queued behind
            another service's start that has stalled.
        ServiceStartingError: `deadline` passed with a start still running.
    """
    while True:
        sock = _try_connect(sock_path)
        if sock is not None:
            try:
                health = _health(sock)
            except (OSError, ConnectionError, KeyError, ValueError, TypeError):
                sock.close()
            else:
                return sock, health
        exit_status = child.poll()
        if exit_status is not None and exit_status != _ANOTHER_SERVICE_EXIT_STATUS:
            raise HookTransportError(f"the service spawned for {sock_path} exited before answering")
        if time.monotonic() >= deadline:
            _raise_if_queued_behind_a_stalled_start(sock_path, child_pid=child.pid)
            raise ServiceStartingError(
                f"the service spawned for {sock_path} is still starting", waited_on="poll"
            )
        time.sleep(_POLL_INTERVAL_SECONDS)


def _raise_if_queued_behind_a_stalled_start(sock_path: Path, *, child_pid: int) -> None:
    """Refuse to call this wait a start when it is a queue behind one that has stalled.

    A child that finds the store held waits for its holder, so a start that never binds would
    otherwise turn every later message's push into one more calm `starting`. The holder names
    itself in the service lock file, whose mtime is its last sign of life — stamped when it took
    the store and renewed on every idle poll — and clears its name as its shutdown begins; one
    still named, alive, not this push's own child, and silent past `_STALLED_START_SECONDS` has
    stalled.

    Raises:
        HookTransportError: this push's start is queued behind a stalled one.
    """
    lock = paths.service_lock_path(sock_path)
    try:
        named = lock.read_text(encoding="ascii").strip()
        held_for = time.time() - lock.stat().st_mtime
    except (OSError, UnicodeDecodeError):
        return
    if not named.isdigit() or int(named) == child_pid or held_for <= _STALLED_START_SECONDS:
        return
    try:
        os.kill(int(named), 0)
    except ProcessLookupError:
        return
    except PermissionError:
        pass  # Alive, under another uid.
    raise HookTransportError(
        f"another service holding the store at {sock_path} has shown no life for {held_for:.0f} s"
    )


def _health(sock: socket.socket) -> Health:
    """Send `health()` and parse its result, requiring a genuine JSON boolean `true` for `ready`
    — mirrors `zikaron.service.lifecycle._health`'s own reasoning for rejecting a merely-truthy
    value rather than coercing one.

    The whole exchange gets `_CONNECT_TIMEOUT_SECONDS`, not each socket call, so how far a connect
    can run past its caller's deadline is bounded.

    Raises:
        OSError: the socket failed during send or receive — `TimeoutError` when the exchange
            outlasted `_CONNECT_TIMEOUT_SECONDS`.
        ConnectionError: the connection closed before a full line arrived, or the response was
            not the expected shape.
        KeyError: a required field (`store_path`, `store_id`, `ready`) was absent from the result.
        ValueError, TypeError: the response was not valid JSON, or `ready` was present but not the
            JSON boolean `true`.
    """
    request = {"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}
    answer_by = time.monotonic() + _CONNECT_TIMEOUT_SECONDS
    rpc.time_out_at(sock, answer_by)
    sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
    buffer = b""
    while not buffer.endswith(b"\n"):
        rpc.time_out_at(sock, answer_by)
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed before a full response was read")
        buffer += chunk
    parsed = json.loads(buffer.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ConnectionError(f"response was not a JSON object: {parsed!r}")
    result = parsed.get("result")
    if not isinstance(result, dict):
        raise ConnectionError(f"health() did not return a result: {parsed!r}")
    ready = result["ready"]
    if ready is not True:
        raise ConnectionError(f"health() reported ready={ready!r}, not the JSON boolean true")
    model_loaded = result.get("model_loaded", True)
    uptime = result.get("uptime_seconds")
    return Health(
        store_path=str(result["store_path"]),
        store_id=str(result["store_id"]),
        model_loaded=model_loaded is not False,
        uptime_seconds=(
            float(uptime)
            if isinstance(uptime, int | float) and not isinstance(uptime, bool)
            else None
        ),
    )


def default_server_command(sock_path: Path, store_dir: Path) -> list[str]:
    """The argv `zikaron.service.main` expects — identical shape to
    `zikaron.service.lifecycle.default_server_command`, restated rather than imported for the same
    reason every other reuse in this module is direct rather than through `lifecycle.py`.
    """
    return [sys.executable, "-P", "-m", "zikaron.service.main", str(sock_path), str(store_dir)]


def resolve_sock_path(store_dir: Path) -> Path:
    """Where this store's socket lives — `zikaron.service.paths`' own derivation, reused
    directly since that module was verified to import with no non-stdlib dependency.

    **This module deliberately has no function reading `meta.store_id` from an existing store,
    and `connect_once`'s own identity check stays path-only, on every connection this client ever
    makes.** `architecture.md` §"Store identity is verified, not assumed" states this as the
    hook's own permanent, documented exception to the ordinary rule that a later connection has a
    real `store_id` to compare against: every `userPromptSubmit` is a fresh, single-shot process
    with no connection of its own from a previous invocation to have learned anything from, and
    the only way to get a `store_id` to compare against would be to read it directly from
    `memory.db` — precisely the store access §"Degraded modes" forbids unconditionally ("the hook
    is never a reader of the store, under any failure"). Two alternatives were considered and
    rejected on that same rule: reading `meta.store_id` directly with bare `sqlite3` (measured to
    violate the no-store-access invariant this whole package exists to hold), and a small sidecar
    file this client would write and read itself to remember an id across invocations (found to be
    circular — whatever a later call would compare against was itself written by an earlier call
    to the same, possibly-now-stale service, so a service that has gone stale without restarting
    reports the identical value both times and the sidecar never disagrees with itself).

    **Path-only comparison is not, on its own, a complete identity check** — it cannot by
    construction distinguish a correctly-running service from one still serving a store that was
    deleted and recreated at the identical path, since the path being compared never changed
    either way. That gap is closed on the *service* side instead: `architecture.md` §"Idle
    self-stop" has the service's own 30 s poll also detect the store it has open no longer being
    the one currently on disk at its own path, and stop rather than keep serving it — the only
    side with an independent way to notice, since it can `stat` the path without opening the file
    it already holds. Given that, path-only is the correct, sufficient check for this client:
    the one case it cannot resolve on its own resolves itself within one more poll cycle either
    way, with no fallback read attempted here in the meantime.

    Raises:
        ZikaronError: `paths.socket_path`'s own `BAD_CONFIG` when the derived path will not fit
            `sun_path`.
    """
    resolved_store_dir = store_dir.resolve()
    runtime_dir = paths.runtime_dir(
        xdg_runtime_dir=os.environ.get("XDG_RUNTIME_DIR"), uid=os.getuid()
    )
    return paths.socket_path(runtime_dir, resolved_store_dir, platform=sys.platform)
