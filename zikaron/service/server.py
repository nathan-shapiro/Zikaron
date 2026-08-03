"""The asyncio UDS server: one connection loop, dispatching each line and framing its response.

`architecture.md` §RPC: `asyncio.start_unix_server`, newline-delimited JSON-RPC 2.0. Every method
except `health()` runs the resolution preamble (`envelope.py`) before dispatch, and every request —
success or error — echoes the resolved `client.session_id` in its response, per
`architecture.md`: "a client that bootstraps into a failing first call still learns its label."

**Concurrency note.** Handling one connection's requests sequentially — reading, dispatching and
replying to one line before reading the next — is a property of this server's per-connection loop,
not of the store: `aiosqlite` already runs every blocking SQLite call off the event loop
(`coding-standards.md` §6), so two *different* connections' requests interleave freely, and two
writers genuinely contend through `busy_timeout` rather than through anything this server adds. A
non-negative `in_flight` counter is what `lifecycle.py`'s idle self-stop depends on, and it is
correct precisely because `ActivityTracker.begin_request`/`end_request` bracket the *whole*
dispatch, including the case where dispatch raises.
"""

import asyncio
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from zikaron.core.errors import ZikaronError
from zikaron.service import dispatch, rpc
from zikaron.service.context import ServiceContext
from zikaron.service.dispatch_consolidation import CONSOLIDATOR_METHODS
from zikaron.service.envelope import ResolvedEnvelope, parse_envelope, resolve
from zikaron.service.params import Handler
from zikaron.service.rpc import ProtocolErrorCode, RequestParseError, RpcRequest

_METHODS: Mapping[str, Handler] = {**dispatch.PRIMARY_METHODS, **CONSOLIDATOR_METHODS}

_READ_LIMIT = 1 << 20  # 1 MiB per line — generous for any request this surface takes.

#: How long `RunningServer.close_all_connections` polls for a connection's handler task to reach
#: its own registration line before giving up and raising loudly — generous relative to the three
#: bare `asyncio.sleep(0)` turns measured directly as sufficient in practice, so a slower CI
#: environment or a future Python patch release adding one more scheduling hop does not turn into
#: a flaky test, while a genuinely stuck handler (never responding to cancellation at all) still
#: fails loudly rather than hanging the whole shutdown path forever.
_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS = 5.0


class ShutdownTimeoutError(TimeoutError):
    """Graceful shutdown's own deadline expired — the one condition the operator-directed hard
    process-exit fallback (`main._force_exit_after_shutdown_timeout`) is authorized to act on.

    A subclass of the built-in `TimeoutError` rather than a bare one, and raised *only* from the
    three graceful-shutdown deadline exits (`RunningServer.close_all_connections`'s two branches,
    and `RunningServer.shut_down`'s bounded `wait_closed()`), because `main`'s fallback must fire
    on exactly this condition and nothing else: an ordinary `TimeoutError` can reach that boundary
    from anywhere — a startup step, a lifecycle task, a dependency's own internal timeout, a store
    close — and none of those prove *this* deadline expired or warrant bypassing the normal,
    diagnosable failure path with an un-catchable `os._exit`.
    """


_LOGGER = logging.getLogger("zikaron.service")


def _resolved_envelope(params: dict[str, object]) -> ResolvedEnvelope:
    envelope = parse_envelope(params.get("client"))
    return resolve(envelope)


async def _dispatch_request(ctx: ServiceContext, request: RpcRequest) -> str | None:
    """One parsed request, all the way to its response line.

    `_compute_response_line`'s own two `except` clauses map every `ZikaronError` and every
    unexpected handler exception to an encoded error line, so an ordinary request practically
    never causes this function itself to raise — but it is not an absolute guarantee: a failure
    in `health`'s own dispatch, in envelope resolution, in response encoding, or in
    `ctx.activity`'s own bookkeeping is outside that inner mapping, and `_handle_line`'s own outer
    `except Exception` exists specifically as the server-boundary fallback for exactly that case,
    answering a bare `INTERNAL_ERROR` for a genuinely unexpected failure this function could not
    itself account for.

    Returns `None` for a genuine JSON-RPC notification (`request.has_id` false), which gets no
    response at all; every other request gets exactly one line, success or error. Computed once,
    at the very end, rather than checked at each of this function's several return points: the
    notification rule is "suppress whatever this call would have answered," not a separate
    decision at every site that could produce an answer.

    `ctx.activity.begin_request()`/`end_request()` bracket **this whole function**, not only the
    branch that finds a matching handler — `architecture.md` §"Idle self-stop": "`last_activity`
    is refreshed when each request completes," with no exception named for `health`, a malformed
    envelope, or an unknown method. A repeated `health()` poll is exactly what a client's own
    start-if-absent sequence does while waiting for the service to become ready, and idle
    self-stop must not be able to fire while that is happening.
    """
    ctx.activity.begin_request()
    try:
        line = await _compute_response_line(ctx, request)
    finally:
        ctx.activity.end_request()
    return line if request.has_id else None


async def _compute_response_line(ctx: ServiceContext, request: RpcRequest) -> str:
    """`_dispatch_request`'s actual work, always returning a line — the notification suppression
    and activity bracketing are both the caller's job, so this function's every branch can simply
    answer."""
    if request.method == "health":
        status = dispatch.health(ctx)
        return rpc.encode_result(request.request_id, status.as_json())

    try:
        envelope = _resolved_envelope(request.params)
    except ZikaronError as error:
        # No session_id to echo: a malformed envelope never reached resolution, so there is
        # nothing to attach — the client's own retry will send a better-formed request.
        return rpc.encode_error(
            request.request_id, int(error.code), error.message, dict(error.data)
        )

    handler = _METHODS.get(request.method)
    if handler is None:
        return rpc.encode_error(
            request.request_id,
            ProtocolErrorCode.METHOD_NOT_FOUND,
            f"method not found: {request.method}",
            session_id=envelope.session_id,
        )

    try:
        result = await handler(ctx.store.connection, ctx, envelope, request.params)
        return rpc.encode_result(
            request.request_id, result.as_json(), session_id=envelope.session_id
        )
    except ZikaronError as error:
        return rpc.encode_error(
            request.request_id,
            int(error.code),
            error.message,
            dict(error.data),
            session_id=envelope.session_id,
        )
    except Exception:
        # A genuine bug in a handler, not a `ZikaronError` — logged here, inside the resolved
        # scope, so both the log line and the response carry the label that would otherwise be
        # lost the instant this exception left the `try` above.
        _LOGGER.exception(
            "unhandled exception dispatching %s (session_id=%s)",
            request.method,
            envelope.session_id,
        )
        return rpc.encode_error(
            request.request_id,
            ProtocolErrorCode.INTERNAL_ERROR,
            "internal error handling this request",
            session_id=envelope.session_id,
        )


async def _handle_line(ctx: ServiceContext, line: bytes) -> str | None:
    try:
        request = rpc.parse_request(line.decode("utf-8"))
    except UnicodeDecodeError as error:
        return rpc.encode_error(None, ProtocolErrorCode.PARSE_ERROR, str(error))
    except RequestParseError as error:
        if not error.has_id:
            return None
        return rpc.encode_error(error.request_id, error.code, error.message)
    try:
        return await _dispatch_request(ctx, request)
    except Exception:
        # `_dispatch_request` already catches every exception that can occur inside its own
        # resolved scope; this is defence in depth for a failure *outside* that scope — before
        # `health` or envelope resolution ever ran — which has no label to attach and so answers
        # with the bare protocol-level code rather than inventing one.
        _LOGGER.exception("unhandled exception dispatching %s", request.method)
        if not request.has_id:
            return None
        return rpc.encode_error(
            request.request_id,
            ProtocolErrorCode.INTERNAL_ERROR,
            "internal error handling this request",
        )


async def _handle_connection(
    ctx: ServiceContext, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """One client's whole connection: read a line, dispatch it, write the response, repeat.

    Writes nothing back for a genuine notification (`_handle_line` returning `None`): standard
    JSON-RPC 2.0 behaviour, and distinct from every other outcome, which always produces exactly
    one line.
    """
    try:
        while True:
            line = await reader.readline()
            if not line:
                return
            response = await _handle_line(ctx, line)
            if response is None:
                continue
            writer.write(response.encode("utf-8"))
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        return
    except asyncio.CancelledError:
        # Shutdown closing this connection out from under a client mid-`readline()` — see
        # `RunningServer.close_all_connections`. Not "a genuine bug in a handler": the connection
        # is being torn down on purpose, so this must propagate as an ordinary cancellation
        # rather than being logged as `_handle_line`'s own inner `except Exception` would log an
        # unrelated dispatch failure.
        raise
    finally:
        writer.close()


@dataclass(slots=True)
class RunningServer:
    """`asyncio.Server` plus the one thing it does not track on its own: which connections are
    currently open.

    `asyncio.Server.close()` stops *accepting new* connections; it does nothing to a connection
    already accepted, and `wait_closed()` explicitly documents waiting "until server is closed
    and all connections have been dropped" — so a single client that finishes a request and then
    keeps its socket open (exactly what `architecture.md` §"Both clients resolve the same label"
    describes as the norm: "the client adopts the returned label and reuses it for its process
    lifetime") blocks `wait_closed()` **forever**, on both the idle-self-stop path and the signal
    path, since both call `shut_down()` (`main.py`), which calls the identical `close()`/`wait_
    closed()` pair. Measured directly on this project's own pinned Python 3.12.3 before writing
    this fix: a standalone repro server with one accepted-but-idle connection left `wait_closed()`
    still pending after a 3 s timeout, confirming this is a real hang and not merely a theoretical
    reading of the docstring.

    `_connections` is a `set[asyncio.Task[None]]` — the *handler* task for each accepted
    connection, not merely its `StreamWriter` — because closing only the writer leaves the
    handler still suspended in `reader.readline()`; the transport closing eventually surfaces as
    that read returning empty and the handler's own `return`, but "eventually" is exactly the
    unbounded wait this class exists to make bounded. Cancelling the task directly and awaiting
    it is what makes shutdown deterministic rather than dependent on the handler's own read
    completing on its own schedule.
    """

    server: asyncio.Server
    _connections: set[asyncio.Task[None]] = field(default_factory=set)

    async def close_all_connections(self, deadline: float | None = None) -> None:
        """Cancel every connection's handler task and wait until none remain attached — the one
        step `asyncio.Server` itself has no notion of, and precisely the step that makes
        `close()`/`wait_closed()` afterward resolve promptly rather than wait on a client that may
        never close its end on its own.

        Called only from `shut_down`, **after** `self.server.close()` has already run — which is
        what bounds the loop below: `close()` stops the listener from ever accepting a *new*
        connection, so `self.server._active_count` — the exact private counter `wait_closed()`
        itself waits on — normally only counts *down* from here. **Normally, not provably**: a
        connection already accepted at the raw-fd level before `close()` ran can still attach
        afterwards, because the event loop accepts the fd synchronously and only then schedules the
        separate task that constructs the transport and calls `Server._attach()`. That race is
        deliberately **not** closed here — doing so would mean replacing `asyncio.start_unix_server`
        with a hand-rolled accept loop — and is covered instead by the operator-directed process
        fallback (`design/architecture.md` §"Idle self-stop", `main._force_exit_after_failed_
        graceful_shutdown`). What this loop *does* guarantee is narrower and is the whole of what it
        claims: it drains every attached transport and registered handler it can observe, under its
        own deadline, and raises `ShutdownTimeoutError` rather than waiting indefinitely if it
        cannot.

        `_active_count` is read directly, once per pass, rather than inferred from
        `len(self._connections)`: measured directly against the installed Python 3.12.3 asyncio
        source, a transport's own `_active_count` increments **synchronously** inside its
        constructor (`_SelectorTransport.__init__`'s `self._server._attach()`), while the callback
        that creates this class's own handler task (`StreamReaderProtocol.connection_made`, called
        from a `loop.call_soon` scheduled by that same constructor) reliably needed **three** bare
        `asyncio.sleep(0)` turns to actually run and reach `serve`'s `connections.add(...)` line,
        measured with a standalone script before writing this loop — not one, and not a number
        this code should assume stays fixed across Python patch releases. Polling the private
        counter itself, rather than counting fixed turns or counting entries in `self.
        _connections`, is what makes this robust to that number changing: whatever it is, this
        loop cancels every task that *has* registered on each pass and keeps yielding until the
        server's own count reports nothing further to wait for.

        `self.server._active_count` is a genuinely private attribute — `type: ignore[attr-
        defined]` at every read below is deliberate, not a suppressed real error, since `asyncio.
        Server`'s public surface (`sockets`, `is_serving`, `close`, `wait_closed`, `serve_forever`,
        `start_serving`, `get_loop`) exposes no public equivalent of "how many connections are
        currently attached" — the private counter is read here only as an observation this loop
        polls, never mutated, and the alternative considered and rejected (subclassing `asyncio.
        Server` to override `_attach`) is not reachable at all, since `create_unix_server`
        hard-codes `base_events.Server` with no factory hook for a caller to substitute a subclass
        through any public API.

        Uses `asyncio.wait(..., timeout=remaining)`, never `asyncio.wait_for(gather(...), timeout=
        remaining)` — confirmed the difference matters by direct measurement before choosing this
        one: `wait_for`'s own docstring states plainly that "if the task suppresses the
        cancellation and returns a value instead, that value is returned," and `gather(...,
        return_exceptions=True)` does exactly that for a child that keeps swallowing
        `CancelledError` — so a handler that resists indefinitely (not merely once) leaves `wait_
        for` itself waiting forever for the `gather` future it was meant to bound, never reaching
        this method's own `TimeoutError`. `asyncio.wait` is documented plainly not to raise on
        timeout at all — "Futures that aren't done when the timeout occurs are returned in the
        second set" — handing control straight back to this loop's own deadline check regardless
        of whether the underlying tasks ever finish cancelling, which is what makes the deadline
        genuinely this method's own decision rather than something it merely hopes `wait_for`
        will honour.

        This `ShutdownTimeoutError` is deliberately allowed to propagate rather than being caught
        here: **directed by the human operator** (2026-08-02, in response to round 12's own
        finding 2 — a narrow, low-severity accept-pipeline race inside `asyncio.Server`'s own
        internals that would require replacing `asyncio.start_unix_server` entirely to close
        provably), the graceful path stays exactly as built and stays the *first* thing tried;
        `main.run` catches this one specific type at the point it attempts shutdown and turns it
        into an unconditional `os._exit` there, rather than this method or anything above it
        trying to make the accept-pipeline race provably airtight. It is a dedicated subclass, not
        a bare `TimeoutError`, precisely so that boundary fires on this condition alone — see
        `ShutdownTimeoutError`'s own docstring.
        """
        deadline = (
            time.monotonic() + _SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS
            if deadline is None
            else deadline
        )
        while self.server._active_count > 0:  # type: ignore[attr-defined]
            for connection in list(self._connections):
                connection.cancel()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                active = self.server._active_count  # type: ignore[attr-defined]
                raise ShutdownTimeoutError(
                    f"{active} connection(s) still attached after "
                    f"{_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS}s of shutdown — a handler task never "
                    "reached its own registration line, or never responded to cancellation."
                )
            if self._connections:
                _done, pending = await asyncio.wait(list(self._connections), timeout=remaining)
                if pending:
                    active = self.server._active_count  # type: ignore[attr-defined]
                    raise ShutdownTimeoutError(
                        f"{active} connection(s) still attached after "
                        f"{_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS}s of shutdown — a handler task "
                        "never responded to cancellation."
                    )
            else:
                await asyncio.sleep(0)

    async def shut_down(self) -> None:
        """Stop accepting new connections, close every connection it can observe, then wait for
        the listener itself to release its socket — in that order, since closing connections first
        is what makes the final `wait_closed()` resolve without depending on any client's own
        behaviour.

        **One absolute deadline spans this whole method**, not one per step: `_SHUTDOWN_QUIESCENCE_
        DEADLINE_SECONDS` is the budget for *shutdown*, so it is computed once here and threaded
        into `close_all_connections`, which leaves `wait_closed()` only whatever remains. An
        earlier version restarted a fresh full budget at each step, which meant the single "5 s
        deadline" the operator's directed policy names could in fact take nearly ten seconds before
        the force-exit path ran (`reviews/m9-service-review.md` round 14, finding 2).

        The final `wait_closed()` is bounded rather than awaited unbounded: `close_all_connections`
        above having succeeded makes it *expected* to return immediately, but "expected" is not
        "guaranteed" — the accept-pipeline race the operator explicitly chose not to chase
        (`design/architecture.md` §"Idle self-stop") is one way a transport can attach late enough
        to still be counted here, and an unbounded await at this exact line would produce no
        `ShutdownTimeoutError` for the hard-exit fallback to act on, silently reintroducing the
        very unbounded hang the whole deadline exists to rule out. `asyncio.wait_for` is
        sufficient here, unlike inside `close_all_connections`: there is no task of ours to
        suppress cancellation at this point — `wait_closed()` is the stdlib's own future, which
        does not resist being cancelled.
        """
        deadline = time.monotonic() + _SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS
        self.server.close()
        await self.close_all_connections(deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ShutdownTimeoutError(
                f"no time left within the {_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS}s shutdown "
                "budget to wait for the listener to finish closing."
            )
        try:
            await asyncio.wait_for(self.server.wait_closed(), timeout=remaining)
        except TimeoutError:
            raise ShutdownTimeoutError(
                f"the listener did not finish closing within the "
                f"{_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS}s shutdown budget."
            ) from None


async def serve(ctx: ServiceContext, sock_path: str) -> RunningServer:
    """Start listening on `sock_path`. The caller owns the socket file's own permissions."""
    connections: set[asyncio.Task[None]] = set()

    async def _on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection = asyncio.current_task()
        if connection is None:
            # Unreachable through `asyncio.start_unix_server`'s own documented mechanism, which
            # always invokes this callback as a task — `raise` rather than a bare `assert` both
            # because this project's own lint config forbids the latter (stripped under `-O`) and
            # because narrowing `connection`'s type this way is what lets the type checker accept
            # the untyped-`None`-returning `add_done_callback` call below.
            raise RuntimeError("connection handler running with no enclosing task")
        connections.add(connection)
        connection.add_done_callback(connections.discard)
        await _handle_connection(ctx, reader, writer)

    server = await asyncio.start_unix_server(_on_connect, path=sock_path, limit=_READ_LIMIT)
    return RunningServer(server=server, _connections=connections)
