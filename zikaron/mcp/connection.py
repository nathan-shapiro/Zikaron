"""A lazy, reconnecting handle to `zikaron-service`, held for the life of one MCP server process.

`architecture.md` §Lifecycle states the client's obligation precisely: "a client can connect just
as the service decides to exit, and its request then fails. Clients retry once through the full
start-if-absent sequence before falling back." This module is that obligation, and nothing more —
it opens no connection until something asks for one (M10's own done-when: "the client provably
makes no service call until the model calls a tool"), and every later request reuses the same
socket rather than reopening it per call, which is what lets one process serve many tool calls
without repeating the ~101 ms cold start-if-absent cost every time.

`service.lifecycle.connect_start_if_absent` already implements the six-step sequence — vet,
connect, `flock`, connect again, spawn-and-poll if still dead, verify identity — exactly as this
client needs it, and is reused unmodified rather than copied: a second implementation of that
sequence is a second place for the race conditions it was written to survive to disagree with the
first.
"""

import asyncio
import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path

from zikaron.core.config.resolution import (
    EffectiveConfig,
    default_system_config_path,
    project_config_path,
    resolve,
)
from zikaron.core.store.store import Store
from zikaron.service import paths
from zikaron.service.envelope import ClientEnvelope
from zikaron.service.lifecycle import connect_start_if_absent, default_server_command

#: How many times a request already in flight against a connection this module believed was live
#: may be retried, once, through a fresh `connect_start_if_absent` — `architecture.md`'s own
#: number, stated as "retry once," not "retry until it works." A second failure after that retry
#: is a genuine problem (the store itself is unreachable, not merely a service that happened to
#: exit between two requests) and propagates rather than looping.
_MAX_ATTEMPTS = 2

#: `connect_start_if_absent` hands back a socket whose timeout is still set to `lifecycle.py`'s
#: own `_CONNECT_TIMEOUT_SECONDS` (1.0 s) — correct for *establishing* the connection, wrong for
#: every ordinary request afterward: `zikaron/core/store/ddl.py`'s `PRAGMA busy_timeout = 5000`
#: means a genuinely contended write may legitimately take up to 5 s to resolve (into either a
#: success or a `store_busy` response, per `architecture.md`'s own error table), and every
#: primary/consolidator RPC method is a single such transaction with no other unbounded step. A
#: request timeout left at 1 s would cut that wait off first, misreporting a slow-but-successful
#: (or a slow-but-honestly-`store_busy`) response as `AmbiguousMutationError` instead. Comfortably
#: above the 5 s ceiling, with margin for ordinary scheduling jitter, rather than exactly at it.
_REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class StoreLocation:
    """Where this process's store lives, resolved once from the process's own working directory —
    D17's "literally the current working directory," computed here rather than trusted from an
    argument, since an MCP server process has no caller supplying it one the way `zikaron-service`
    itself is handed `sock_path`/`store_dir` on its own argv.
    """

    store_dir: Path
    sock_path: Path

    @classmethod
    def resolve(cls, cwd: Path) -> "StoreLocation":
        store_dir = paths.store_dir(cwd)
        resolved_store_dir = store_dir.resolve()
        runtime_dir = paths.runtime_dir(
            xdg_runtime_dir=os.environ.get("XDG_RUNTIME_DIR"), uid=os.getuid()
        )
        sock_path = paths.socket_path(runtime_dir, resolved_store_dir)
        return cls(store_dir=store_dir, sock_path=sock_path)


async def _read_store_identity(store_dir: Path) -> str | None:
    """This store's own `meta.store_id`, if it already exists — `None` if `memory.db` is not
    there yet.

    `connect_start_if_absent`'s identity check compares `health()`'s report against a value the
    *client* resolved for itself (`lifecycle.py`: "a client cannot verify identity against a fact
    it never read for itself"), so this client needs `meta.store_id` before it can call that
    function at all, on every call after the very first — exactly the pattern
    `test_service_lifecycle_integration.py` establishes for a test client, reused here for the
    real one. Opening and immediately closing costs one extra round trip through SQLite's own open
    path, but it is the only source of this value that does not require trusting an
    unauthenticated peer's self-report before checking it.

    Both `db_path.exists()` and `resolve_effective_config` run through `asyncio.to_thread` below,
    not directly: the first is a blocking `stat`, the second reaches `config.resolution.
    _read_layer`'s own blocking `Path.read_bytes()` for both config layers — either one run
    synchronously here would hold the same event loop `ServiceConnection.request`'s own blocking
    socket calls are already careful to run off of, for the identical reason `architecture.md`'s
    RPC section states for those.

    **A store this client has never seen before is not an error here.** `memory.db` not existing
    yet is the ordinary state of a project `zikaron-service` has never started against
    (`architecture.md` §"First run"), and `zikaron-service` is what creates it on its own first
    startup — this function only checks whether the *file* is there, never opens a connection
    itself when it is not, and returns `None` for `connect_start_if_absent` to treat as "no prior
    identity to verify against yet."

    Raises:
        ZikaronError: whatever `Store.open` raises for a store that **does** exist but fails to
            open — most commonly `REINDEXING` or `SCHEMA_INCOMPATIBLE`, or `BAD_CONFIG` for a
            corrupt `meta`. A tool handler that calls this lets any such error propagate as a
            normal FastMCP tool error: there is no client-side action that would repair it, and
            `zikaron-service` faces the identical failure on its own startup for the identical
            reason.
    """
    db_path = store_dir / "memory.db"
    exists = await asyncio.to_thread(db_path.exists)
    if not exists:
        return None
    config = await asyncio.to_thread(resolve_effective_config, store_dir)
    store = await Store.open(store_dir, config)
    try:
        return store.meta.store_id
    finally:
        await store.close()


def resolve_effective_config(store_dir: Path) -> EffectiveConfig:
    """The two-layer config this process's store was configured with — the same two paths
    `zikaron-service`'s own `main.py` resolves from an identical `store_dir`, so a client and the
    service it talks to can never disagree about which files back the effective configuration.
    """
    return resolve(
        default_system_config_path(os.environ.get("XDG_CONFIG_HOME"), Path.home()),
        project_config_path(store_dir),
    )


def _harness_session_id() -> str | None:
    """`KIRO_SESSION_ID` from this process's own environment, or `None` if it is absent **or**
    intrudes on the service's reserved `zk-` namespace.

    `architecture.md`'s client contract, stated plainly for exactly this case: "a client that
    finds a `zk-`-prefixed value in `KIRO_SESSION_ID` must treat it as absent — send the bootstrap
    form and adopt a fresh service-minted label." The `zk-` prefix is how the service tells its
    own minted labels apart from a harness's, and that distinction is only truthful if every
    client honours it rather than forwarding whatever the environment happens to hold.
    """
    value = os.environ.get("KIRO_SESSION_ID")
    if value is not None and value.startswith("zk-"):
        return None
    return value


class ServiceConnection:
    """One live socket to `zikaron-service`, opened lazily and reconnected once on death — and
    the one process-lifetime session label every request through it carries.

    `architecture.md`: "the client adopts the returned label and reuses it for its process
    lifetime." A fresh `client_envelope()` call per request that re-read `KIRO_SESSION_ID` every
    time would be correct only under `harness` resolution (the environment variable does not
    change mid-process); under `minted` resolution — no `KIRO_SESSION_ID` at all, the common case
    for a client that is not a genuine kiro-spawned process, and reachable even under one if the
    variable were ever absent — every call would instead bootstrap with `session_id: null` and the
    service would mint a **new** `zk-<uuid4>` label each time, silently breaking every
    receipt/ownership check that assumes one session speaks with one label: a consolidator's own
    successful `plan_groups`, owned by `(session_id, pid)`, would then be followed by a
    `next_group` under a *different* `session_id` and see its own run as foreign. This class holds
    the resolved label once it is known, so every request after the first that establishes it uses
    the identical value.

    **Every `request()` call runs under one `asyncio.Lock`, for a second reason beyond ordinary
    mutual exclusion of the socket itself.** FastMCP dispatches each `tools/call` as its own task
    on one event loop, and every `await` inside the obtain-socket-send-receive-adopt sequence is a
    point where a concurrently-running call can resume. Without the lock, two concurrent *first*
    calls through this connection could both observe no held socket and both establish one (the
    loser's leaked and overwritten), or both build a bootstrap envelope before either response is
    adopted — splitting one process's own receipts and writes across two different service-minted
    labels, exactly the failure this class exists to prevent in the *sequential* case. The lock
    makes the whole round trip atomic instead.
    """

    def __init__(self, cwd: Path) -> None:
        self._location = StoreLocation.resolve(cwd)
        self._sock: socket.socket | None = None
        self._session_id: str | None = _harness_session_id()
        # Every `request()` call runs its whole body — obtain-or-establish a socket, send,
        # receive, adopt the label — under this one lock, never partially: two `tools/call`
        # dispatches can otherwise run concurrently on FastMCP's own event loop, and each `await`
        # inside that sequence (`_read_store_identity` opening the store, `connect_start_if_absent`
        # itself) is a point where the other task can resume. Without serialization here, two
        # concurrent first calls could both observe no held socket and both establish one — the
        # loser's socket then leaked and overwritten — or both build a bootstrap envelope before
        # either response is adopted, splitting one process's own receipts and writes across two
        # different service-minted labels. The lock makes the whole round trip atomic with
        # respect to every other call through this same connection.
        self._lock = asyncio.Lock()

    def envelope(self, *, kind: str) -> ClientEnvelope:
        """This process's own `client` envelope for one request: the adopted session label (if
        any is known yet), this process's own pid, and no `op_id` — the service mints one per
        call when a client sends none (`envelope.resolve`), so there is nothing for this client to
        generate or track across requests.

        `kind` is supplied by the caller rather than fixed on this class, since one process serves
        exactly one mode's own tool set but the same connection type serves both — `"mcp"` for the
        primary agent's process, `"consolidator"` for the consolidator's.

        Called by a tool handler *before* `request()`, so the label it carries can be stale by the
        time `request()` actually acquires its own lock and sends — `request()` re-reads
        `self._session_id` fresh under that lock rather than trusting this envelope's own copy,
        which is what keeps a label adopted by a concurrently-running call from being silently
        overwritten by an older bootstrap envelope built before that adoption happened.
        """
        return ClientEnvelope(session_id=self._session_id, kind=kind, pid=os.getpid(), op_id=None)

    async def request(
        self, method: str, params: dict[str, object], *, envelope: ClientEnvelope
    ) -> dict[str, object]:
        """Send one JSON-RPC request, reconnecting once if the held connection turned out to be
        dead *before this request was sent*, and return the parsed response line — a success
        (`{"result": ...}`) or an error (`{"error": {"code", "message", "data"?}}`) object,
        whichever the service sent.

        `envelope` is a parameter rather than built internally, so a caller may attach `kind`
        before this method runs; the label it carries, however, is re-read from this connection's
        own `_session_id` the instant this method's lock is acquired — never trusted as given —
        which is what §"the client adopts the returned label" is actually enforced by, and what
        keeps two concurrent calls from splitting one process's writes across two labels (see
        `__init__`'s own docstring on why the whole method runs under one lock). The response's
        own `client.session_id` (present on every success **and every error alike**, per
        `architecture.md`) is read and adopted before returning or raising, so every later call —
        including one already waiting on this same lock — sees it.

        **The retry only ever re-sends a request with zero bytes actually transmitted.**
        `architecture.md` states "retry once" for the case its own example names — "a client can
        connect just as the service decides to exit" — which is a failure discovered before any
        byte of *this* call's request left the socket. A failure discovered after even one byte
        was accepted is a genuinely different case the design does not yet answer: `sendall`'s own
        documentation states plainly that once it raises, "it's impossible to tell how much data
        has been sent" — so a naive read of "did `sendall` raise" cannot tell "nothing was sent"
        from "most of it was, and the service may already be running it" apart. `_send_request`
        therefore tracks progress itself with a manual send loop rather than trusting `sendall`,
        and raises a distinguishable `_ZeroProgressSendError` only for the zero-bytes case.
        Any positive progress, or any failure discovered while reading the response, means the
        service may already have received, processed and **committed** the request with only the
        response lost — retrying it would then risk a second `remember` (a duplicate row), a
        second `amend` at a version the first attempt already bumped (a spurious conflict, not a
        duplicate), or a second consolidator write racing its own first attempt. `op_id`
        correlates *audit rows* after the fact; it is not a live idempotency check the service
        performs before executing a write. So this method **never retries past the first byte
        actually sent**: `_MAX_ATTEMPTS` only bounds attempts that fail with zero progress, and
        every other failure instead raises `AmbiguousMutationError` immediately, naming the
        genuine uncertainty rather than silently resolving it in either direction.

        Raises:
            ZikaronError: whatever `_read_store_identity`/`connect_start_if_absent` raise while
                establishing a connection — a missing or unhealthy store, a `store_identity`
                mismatch, or the underlying transport never becoming reachable before the
                deadline, reported as a plain `ConnectionError` from `connect_start_if_absent`
                itself and left unwrapped, since this module has no more specific diagnosis to add
                to it than the sequence that raised it already gives.
            AmbiguousMutationError: the request was sent successfully but no response could be
                read — the outcome of `method` on the service is genuinely unknown, and this is
                never retried automatically for the reason above.
        """
        async with self._lock:
            current_envelope = ClientEnvelope(
                session_id=self._session_id,
                kind=envelope.kind,
                pid=envelope.pid,
                op_id=envelope.op_id,
            )
            last_error: Exception | None = None
            for _attempt in range(_MAX_ATTEMPTS):
                sock = await self._connected_socket()
                try:
                    # `asyncio.to_thread`, not a bare synchronous call: `_send_request`/
                    # `_read_response` block on the raw socket, and calling either directly here
                    # would hold the single-threaded event loop for as long as the service takes
                    # to answer — including the full `PRAGMA busy_timeout = 5000` window a
                    # contended write may legitimately need — starving every other coroutine on
                    # this same loop for that entire wait. Measured directly: an earlier version
                    # of this method called both synchronously, and a concurrent `asyncio.sleep`
                    # in another task on the same loop was starved for the whole blocking wait
                    # rather than resuming on schedule — the exact self-inflicted-deadlock shape
                    # `coding-standards.md` §6 already documents for the service's own SQL calls,
                    # reproduced here on the client side instead.
                    #
                    # **Cancelling this `await` does not stop the worker thread underneath it.**
                    # `asyncio.to_thread` has no mechanism to interrupt a thread already inside a
                    # blocking syscall — cancellation only unwinds the *awaiting coroutine*, so a
                    # cancelled tool call would otherwise release `self._lock` (the `async with`
                    # above exits during cancellation unwind) while the orphaned worker thread is
                    # still reading or writing `sock` in the background. A later call could then
                    # acquire the lock and use the *same* socket object the orphaned thread is
                    # still touching — two send loops interleaving bytes on the wire, or an
                    # orphaned read silently stealing the later call's own response. Detaching the
                    # socket from `self._sock` on cancellation, before re-raising, is what
                    # prevents *that* specific collision: no later call can ever be handed this
                    # exact socket object again, because nothing still names it. Closing it here
                    # is not relied on to promptly wake the orphaned worker's own blocked
                    # `send`/`recv` — on Linux, closing a descriptor from another thread is not a
                    # reliable interrupt for a syscall already blocked on it, and the orphaned
                    # call may not observe anything until data arrives, the peer closes, or its
                    # own `_REQUEST_TIMEOUT_SECONDS` elapses. What bounds the orphaned worker is
                    # that timeout, not this `close()` — the close only guarantees detachment.
                    try:
                        await asyncio.to_thread(
                            _send_request, sock, method, params, envelope=current_envelope
                        )
                    except asyncio.CancelledError:
                        self._sock = None
                        sock.close()
                        raise
                except _ZeroProgressSendError as error:
                    # Zero bytes of this exact request were accepted by the socket before it
                    # failed — nothing was necessarily delivered, so the held socket is dead and
                    # must not be reused, but retrying through a fresh connection is safe: this
                    # exact call has not yet reached the service in any form.
                    sock.close()
                    self._sock = None
                    last_error = error.cause
                    continue
                except (OSError, ConnectionError) as error:
                    # Some bytes of this request were accepted by the socket before the send
                    # itself failed, or the connection died while reading the response after a
                    # *complete* send succeeded. Either way, whether the service received, ran
                    # and committed the request before this failure is now unknown — this is
                    # deliberately not retried, for the reason this method's own docstring gives.
                    sock.close()
                    self._sock = None
                    raise AmbiguousMutationError(method, error) from error
                try:
                    try:
                        response = await asyncio.to_thread(_read_response, sock)
                    except asyncio.CancelledError:
                        # Identical reasoning to the send-side handler above: the read worker
                        # thread survives this coroutine's own cancellation, so the socket it is
                        # still reading from must be detached and closed here too.
                        self._sock = None
                        sock.close()
                        raise
                except (OSError, ConnectionError) as error:
                    sock.close()
                    self._sock = None
                    raise AmbiguousMutationError(method, error) from error
                self._adopt_label_from(response)
                return response
            if last_error is None:
                # Unreachable with `_MAX_ATTEMPTS >= 1`: the loop above raises and reassigns
                # `last_error` on every non-returning path, so falling through it at all means at
                # least one attempt failed. Raised rather than asserted so the guarantee holds
                # even when the interpreter runs with assertions stripped (`python -O`).
                raise RuntimeError("connect retry loop exited with no attempt recorded")
            raise last_error

    def _adopt_label_from(self, response: dict[str, object]) -> None:
        """Read `client.session_id` off a response and hold it for every later request, exactly
        as `architecture.md` step 4/5 of resolution require — on a success **and** on an
        application-level error alike, since the service returns the envelope either way and a
        client that only adopted from success responses would re-bootstrap after every rejected
        first call.
        """
        client_field = response.get("client")
        if not isinstance(client_field, dict):
            return
        session_id = client_field.get("session_id")
        if isinstance(session_id, str):
            self._session_id = session_id

    async def _connected_socket(self) -> socket.socket:
        """The held socket if one is open, else a freshly established one via the full
        start-if-absent sequence — reusing `service.lifecycle` unmodified rather than copying it.

        `connect_start_if_absent` is itself a **blocking** function by its own documented design
        — correct for the short-lived, single-connection-attempt processes `lifecycle.py` was
        originally written to serve, wrong for `zikaron-mcp`: this class holds one connection
        across many tool calls in one long-running process, so a blocking call anywhere inside
        it risks starving the same event loop every other coroutine on this process runs on for
        as long as start-if-absent takes (up to its own ~10 s health-poll deadline). Run through
        `asyncio.to_thread` for the identical reason `request()`'s own send/receive calls are.

        **Run as an explicit `asyncio.Task`, not a bare `await`, so a cancellation of *this*
        coroutine does not discard whatever the underlying thread eventually returns.**
        `asyncio.to_thread`'s own worker thread keeps running a blocking call to completion
        however its awaiting coroutine is treated — cancelling the `await` only unwinds this
        coroutine, and a bare `await asyncio.to_thread(connect_start_if_absent, ...)` that was
        cancelled mid-flight would let that thread's eventual return value (a real, connected —
        and possibly newly-spawned-service-owning — socket) simply vanish, held by nothing,
        closed by nothing. Wrapping the call in its own `asyncio.Task` and shielding it from this
        coroutine's own cancellation lets the underlying operation finish exactly as it would have
        anyway (it cannot actually be stopped early regardless), while giving this method a
        handle to close whatever the task eventually returns if this coroutine itself was
        cancelled before the task finished.

        Resets the socket's own timeout before returning it: `connect_start_if_absent` hands one
        back still set to its own short connect-phase deadline
        (`lifecycle._CONNECT_TIMEOUT_SECONDS`), which is correct for establishing the connection
        and wrong for every request this connection serves afterward — see
        `_REQUEST_TIMEOUT_SECONDS`'s own docstring for why.
        """
        if self._sock is not None:
            return self._sock
        store_db_path = self._location.store_dir / "memory.db"
        store_id = await _read_store_identity(self._location.store_dir)
        connect_task = asyncio.ensure_future(
            asyncio.to_thread(
                connect_start_if_absent,
                self._location.sock_path,
                store_db_path=store_db_path,
                store_id=store_id,
                server_command=default_server_command(
                    self._location.sock_path, self._location.store_dir
                ),
            )
        )
        try:
            sock, _health = await asyncio.shield(connect_task)
        except asyncio.CancelledError:
            # This coroutine was cancelled, not the underlying thread — `connect_task` keeps
            # running regardless, per this method's own docstring, so its eventual result must
            # still be collected and closed rather than left to leak. The retry is itself
            # shielded, and in a loop: a *second* cancellation arriving while this cleanup is
            # itself awaiting `connect_task` would otherwise hit the identical problem one level
            # down — an unshielded retry-await cancelled again would abandon `connect_task` a
            # second time with nothing left to notice when it eventually finishes. Looping on a
            # freshly shielded await for as many cancellations as arrive is what keeps this
            # cleanup itself cancellation-safe rather than only correct for exactly one.
            while True:
                try:
                    sock, _health = await asyncio.shield(connect_task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    # The connection attempt itself failed (or `connect_task` was independently
                    # cancelled by something other than this method) after this coroutine gave up
                    # on it — nothing was established, so there is nothing to close, and the
                    # original cancellation is still what this method owes its own caller.
                    raise asyncio.CancelledError from None
                else:
                    break
            sock.close()
            raise
        sock.settimeout(_REQUEST_TIMEOUT_SECONDS)
        self._sock = sock
        return sock

    def close(self) -> None:
        """Close the held socket, if one is open. Safe to call whether or not a connection was
        ever established — a tool process that exits having never made a call has nothing to
        close, and closing twice is a no-op rather than an error."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None


class AmbiguousMutationError(Exception):
    """`method` was sent, but no response could be read — whether the service received, ran and
    committed it is genuinely unknown, and `ServiceConnection.request` never retries this case
    automatically (its own docstring states the exact scenario this exists to name rather than
    silently resolve).
    """

    def __init__(self, method: str, cause: Exception) -> None:
        self.method = method
        self.cause = cause
        super().__init__(
            f"{method}: request was sent but no response was received — its outcome on the "
            f"service is unknown ({cause})"
        )


class _ZeroProgressSendError(Exception):
    """`_send_request` failed with **zero** bytes of this request accepted by the socket —
    `socket.sendall`'s own documented limit ("if an error occurs, it's impossible to tell how
    much data has been sent") is why this is tracked explicitly with a manual send loop rather
    than inferred from `sendall` raising: a request whose `sendall` call raised after
    successfully writing some prefix of the bytes may still have been received and acted on by
    the service, indistinguishable on the wire from a fully-sent request whose response was lost.
    Only the zero-progress case this exception names is safe for `ServiceConnection.request` to
    retry through a fresh connection.
    """

    def __init__(self, cause: OSError) -> None:
        self.cause = cause
        super().__init__(str(cause))


def _send_request(
    sock: socket.socket, method: str, params: dict[str, object], *, envelope: ClientEnvelope
) -> None:
    """The request half of one round trip: frame and write one line, matching `service.rpc`'s own
    newline-delimited JSON-RPC 2.0 exactly. Split from reading the response — see `_read_response`
    and `ServiceConnection.request`'s own docstring — so a caller can distinguish "this call's
    bytes never left the socket" from "they did, and only the answer is missing," which decides
    whether retrying is safe.

    Uses a manual `sock.send()` loop rather than `socket.sendall`, specifically to track how many
    bytes were actually accepted before any failure: `sendall`'s own documentation is explicit
    that this is unknowable once it has raised, which would make a request that failed after
    partially transmitting indistinguishable from one that failed transmitting nothing at all —
    exactly the ambiguity `_ZeroProgressSendError` exists to rule out rather than assume
    away. A failure after positive progress propagates as a bare `OSError`, which
    `ServiceConnection.request` treats identically to a response-read failure (ambiguous, never
    retried); a failure with zero bytes sent is wrapped in `_ZeroProgressSendError`, the one
    case safe to retry. **The loop also terminates explicitly on `send()` returning `0`** with a
    non-empty remaining payload, rather than calling `send()` again unconditionally: a `0` return
    signals no forward progress on this connection, and this function runs synchronously inside
    `ServiceConnection.request`'s own `asyncio.Lock` — an unbounded loop here would block the
    entire event loop, not merely this one coroutine, so a stuck connection must fail rather than
    spin.

    Builds the request object directly rather than through `service.rpc`: that module's whole
    surface is response framing (`encode_result`/`encode_error`), because nothing on the service
    side ever sends a *request* — this is the one place in the codebase that does, and it has no
    service-side counterpart to share the encoding with.
    """
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **params,
            "client": {
                "session_id": envelope.session_id,
                "kind": envelope.kind,
                "pid": envelope.pid,
                "op_id": envelope.op_id,
            },
        },
    }
    payload = (json.dumps(request) + "\n").encode("utf-8")
    sent_so_far = 0
    while sent_so_far < len(payload):
        try:
            sent_this_call = sock.send(payload[sent_so_far:])
        except OSError as error:
            if sent_so_far == 0:
                raise _ZeroProgressSendError(error) from error
            raise
        if sent_this_call == 0:
            # `send()` returning 0 with a non-empty remaining payload signals no forward
            # progress on this connection — treated as a broken connection rather than retried
            # in a loop, since retrying an unchanged call with the identical remaining bytes has
            # no reason to succeed where the first attempt did not, and this function runs
            # synchronously inside `ServiceConnection.request`'s own `asyncio.Lock`: a loop that
            # never terminates here would block every other call through this connection, and the
            # event loop thread itself, rather than merely this one coroutine.
            stuck = ConnectionError("send() returned 0 with data remaining — connection is stuck")
            if sent_so_far == 0:
                raise _ZeroProgressSendError(stuck) from stuck
            raise stuck
        sent_so_far += sent_this_call


def _read_response(sock: socket.socket) -> dict[str, object]:
    """The response half of one round trip: read one newline-terminated line and parse it."""
    buffer = b""
    while not buffer.endswith(b"\n"):
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed before a full response was read")
        buffer += chunk
    parsed = json.loads(buffer.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ConnectionError(f"response was not a JSON object: {parsed!r}")
    return parsed
