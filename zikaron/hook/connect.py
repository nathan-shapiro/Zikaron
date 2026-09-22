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

**This reimplementation is narrower than the one it mirrors in exactly one direction, and
nowhere else**: no *second outer attempt* after this one's own five-step sequence fails.
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

from zikaron.service import paths, security

#: How long this single attempt waits, in total, for a freshly spawned server to answer a genuine
#: `health()` — not merely accept a connection. `push.py`'s own internal deadline
#: (`architecture.md`: "enforce an internal deadline of ~2 s") is the budget for the *whole*
#: `userPromptSubmit` hook, connect-through-print included, so this value must leave room for the
#: request and response after it. Set well under that: a cold spawn racing this deadline and
#: losing is exactly the case that must degrade (log to `hook.log`, relay on stdout) rather than
#: make the user wait for the `timeout_ms` kiro enforces on the whole hook command — 10 s on this
#: harness, and stated explicitly in the shipped entry (`architecture.md` §"The install contract").
HEALTH_POLL_DEADLINE_SECONDS = 1.2
_HEALTH_POLL_INTERVAL_SECONDS = 0.05
_CONNECT_TIMEOUT_SECONDS = 0.3

#: `architecture.md`: "`ECONNREFUSED` on an existing socket file is the signature of a service
#: that died without cleaning up — unlink and respawn rather than reporting an error," and
#: `ENOENT` is the plainer case of a socket that was never created. Mirrors
#: `zikaron.service.lifecycle._ABSENT_SERVER_ERRNOS` exactly, restated here rather than imported
#: since importing that module at all is what this file exists to avoid.
_ABSENT_SERVER_ERRNOS = frozenset({errno.ENOENT, errno.ECONNREFUSED})


class HookTransportError(Exception):
    """No server became reachable within the deadline.

    `push.py` catches this alongside every other failure kind and logs it to `hook.log` plus a
    stdout relay, per `architecture.md`'s "Degraded modes". `StoreIdentityError` is the one
    subclass of this that names a more specific reason — a reachable server that answered, but
    disagreed about which store it was serving — kept as a subclass rather than a sibling
    exception so a caller that only wants "did this single attempt succeed" can still catch this
    one base type, while a caller that wants to log the design's own `-32030 store_identity`
    code specifically can check for the subclass first.
    """


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
    """`health()`'s result, exactly as `push.py`'s identity check needs it."""

    store_path: str
    store_id: str


def connect_once(
    sock_path: Path, *, store_db_path: Path, store_id: str | None, server_command: Sequence[str]
) -> socket.socket:
    """One pass through start-if-absent, implementing `architecture.md`'s full five-step
    sequence exactly: connect; on absence, take the `flock`, connect again (another client may
    have won the race while this one reached the lock), and only then vet-and-spawn-and-poll;
    verify identity; return a connected socket.

    **This is one outer attempt with an internal lock, not two outer attempts.** The design's own
    lock exists to prevent exactly this race: two hooks (or a hook racing `zikaron-mcp`'s own
    start-if-absent) can both observe the socket absent, and without serialization the second one
    can vet-and-unlink the *first* one's now-live socket — the first server's own file, not a
    stale leftover — before spawning a second server
    at the identical path. `architecture.md`'s own five steps are one race-safe *unit*: connect,
    lock, recheck, spawn-if-still-absent, release. Nothing here retries that whole unit a second
    time if it still fails after the lock is released; the "single attempt" property is about not
    looping the five-step unit, not about omitting a step inside it.

    Returns:
        A connected, unverified-timeout socket — `push.py` sets its own request timeout before
        using it, since this socket's timeout is still whatever `_CONNECT_TIMEOUT_SECONDS` left it
        at.

    Raises:
        HookTransportError: no server became reachable before the deadline, or a reachable one's
            `health()` disagreed with `store_db_path`/`store_id`.
        OSError: a filesystem or vetting failure distinct from "the server is absent" —
            `zikaron.service.security.ensure_runtime_dir`'s own `ZikaronError` on a hostile runtime
            directory propagates as itself, since this single attempt has no fallback path to
            degrade *through* a runtime directory it does not trust.
    """
    sock, health = _connect_or_start_under_lock(sock_path, server_command=server_command)
    _verify_identity(health, store_db_path=store_db_path, store_id=store_id, sock=sock)
    return sock


def _connect_or_start_under_lock(
    sock_path: Path, *, server_command: Sequence[str]
) -> tuple[socket.socket, Health]:
    """Steps 1 through 5 of `architecture.md`'s start-if-absent sequence, exactly: an unlocked
    connect first (the ordinary warm case never needs the lock at all), then — only on absence —
    the lock, a second connect under it, and the spawn-if-still-absent-and-poll branch, releasing
    the lock on every exit path.
    """
    security.ensure_runtime_dir(sock_path.parent, uid=security.current_uid())
    sock = _try_connect(sock_path)
    if sock is not None:
        # Already listening (the ordinary warm case): no lock needed at all, since nothing is
        # about to be spawned or unlinked. This connection has never been asked `health()` yet,
        # so one call is genuinely needed here.
        try:
            health = _health(sock)
        except BaseException:
            sock.close()
            raise
        return sock, health

    lock_path = paths.lock_path(sock_path)
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Step 3: "another client may have won and already started it" — recheck under the lock
        # before touching the socket file at all, so a live socket the other client just bound is
        # never mistaken for a stale one.
        sock = _try_connect(sock_path)
        if sock is not None:
            try:
                health = _health(sock)
            except BaseException:
                sock.close()
                raise
            return sock, health
        _vet_and_clear_stale_socket(sock_path)
        _spawn_detached(server_command)
        # `_poll_until_reachable` already confirmed readiness with its own `health()` call before
        # returning — a **second** call over the identical connection would ask a server that
        # answers one request per connection (the real `zikaron-service`'s own JSON-RPC loop
        # answers many, but nothing in this function's own contract may assume a peer's request
        # count) for a response it has no obligation to send twice. `_poll_until_reachable`
        # therefore hands back the `Health` it already has, not merely the socket.
        return _poll_until_reachable(sock_path)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


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


def _spawn_detached(server_command: Sequence[str]) -> None:
    """Start the service, detached, and forget it — this single attempt does not wait on the
    child beyond polling its socket, and does not reap it: a short-lived hook process exits long
    before the spawned service's own eventual idle self-stop, so there is no zombie-avoidance
    reason for this process to hold a `Popen` handle the way `zikaron.service.lifecycle`'s own
    reaping thread exists for a *long-running* spawning client. Whatever process this hook's own
    parent (kiro) reaps this child under is outside this function's concern once the fork
    succeeds.
    """
    subprocess.Popen(  # noqa: S603 — `server_command` is caller-supplied, the fixed argv this
        # process's own caller decided to spawn, never built from request data.
        list(server_command),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _poll_until_reachable(sock_path: Path) -> tuple[socket.socket, Health]:
    """Poll for a genuine `health()` response, not merely a successful connect, until
    `HEALTH_POLL_DEADLINE_SECONDS` elapses.

    Mirrors `zikaron.service.lifecycle._poll_until_reachable`'s own reasoning exactly: a freshly
    spawned process can accept a connection before it is able to answer anything, so a poll that
    stopped at `connect()` would hand the caller a socket the service is not yet serving on.
    Answering `health()` is the readiness signal because it is the first thing that requires the
    store to be open.

    It does **not** mean the model is loaded. The service binds while a deferred load is still
    running, deliberately, so a `health()` answer bounds the wait for the *store* and not for the
    first embedding — the request after it may still block on the model.

    Returns:
        The connected socket and the `Health` this function's own poll attempt already read from
        it — the caller must not call `_health` a second time over this identical connection, since
        a peer that answers one request per accepted connection would have nothing left to answer
        with.

    Raises:
        HookTransportError: the deadline elapsed with no genuine `health()` response.
    """
    deadline = time.monotonic() + HEALTH_POLL_DEADLINE_SECONDS
    while time.monotonic() < deadline:
        sock = _try_connect(sock_path)
        if sock is None:
            time.sleep(_HEALTH_POLL_INTERVAL_SECONDS)
            continue
        try:
            health = _health(sock)
        except (OSError, ConnectionError, KeyError, ValueError, TypeError):
            sock.close()
            time.sleep(_HEALTH_POLL_INTERVAL_SECONDS)
            continue
        else:
            return sock, health
    raise HookTransportError(f"no server became reachable at {sock_path} before the deadline")


def _health(sock: socket.socket) -> Health:
    """Send `health()` and parse its result, requiring a genuine JSON boolean `true` for `ready`
    — mirrors `zikaron.service.lifecycle._health`'s own reasoning for rejecting a merely-truthy
    value rather than coercing one.

    Raises:
        OSError: the socket failed during send or receive.
        ConnectionError: the connection closed before a full line arrived, or the response was
            not the expected shape.
        KeyError: a required field (`store_path`, `store_id`, `ready`) was absent from the result.
        ValueError, TypeError: the response was not valid JSON, or `ready` was present but not the
            JSON boolean `true`.
    """
    request = {"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}
    sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
    buffer = b""
    while not buffer.endswith(b"\n"):
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
    return Health(store_path=str(result["store_path"]), store_id=str(result["store_id"]))


def default_server_command(sock_path: Path, store_dir: Path) -> list[str]:
    """The argv `zikaron.service.main` expects — identical shape to
    `zikaron.service.lifecycle.default_server_command`, restated rather than imported for the same
    reason every other reuse in this module is direct rather than through `lifecycle.py`.
    """
    return [sys.executable, "-m", "zikaron.service.main", str(sock_path), str(store_dir)]


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
    """
    resolved_store_dir = store_dir.resolve()
    runtime_dir = paths.runtime_dir(
        xdg_runtime_dir=os.environ.get("XDG_RUNTIME_DIR"), uid=os.getuid()
    )
    return paths.socket_path(runtime_dir, resolved_store_dir)
