"""`zikaron.service.server` — request dispatch, error mapping, and response framing.

Default tier: exercises `_handle_line`/`_dispatch_request` directly against a real store (real
SQLite, `FakeEncoder`) with no socket at all, since a `StreamReader`/`StreamWriter` pair is not
what these tests are about — `test_service_lifecycle_integration.py` covers the real transport.
`health`'s own JSON-serialization roundtrip lives here specifically because it is what caught a
real defect (`HealthStatus` is a `slots=True` dataclass, so `.__dict__` does not exist): a unit
test that actually serializes the response, rather than merely calling `dispatch.health` and
inspecting the Python object, is what a diligent reviewer of this exact bug would ask for.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from tests.fake_encoder import FakeEncoder, unit_at
from tests.service_fixtures import open_context
from zikaron.core.errors import ErrorCode
from zikaron.core.events import ClientKind
from zikaron.core.indexing.chunking import PREFIX_SEPARATOR
from zikaron.service import rpc, server
from zikaron.service.context import ServiceContext


def _line(method: str, params: dict[str, object], request_id: int = 1) -> bytes:
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    return (json.dumps(request) + "\n").encode("utf-8")


async def _response_json(ctx: ServiceContext, line: bytes) -> dict[str, object]:
    """`server._handle_line`, asserting a real response line came back — every request built by
    `_line` carries an `id`, so `None` here would itself be the defect under test."""
    response_line = await server._handle_line(ctx, line)
    assert response_line is not None
    parsed = json.loads(response_line)
    assert isinstance(parsed, dict)
    return parsed


async def test_shut_down_returns_promptly_even_with_an_idle_client_still_connected(
    tmp_path: Path,
) -> None:
    """`asyncio.Server.wait_closed()` explicitly waits until every accepted connection is
    dropped, not merely until new ones stop being accepted — measured directly against this
    project's own pinned Python 3.12.3 before writing this fix: a standalone repro server with
    one accepted-but-idle connection left a bare `close()`/`wait_closed()` pair still pending
    after a 3 s timeout. A client that finishes a request and keeps its socket open is the
    documented norm (`architecture.md`: "the client adopts the returned label and reuses it for
    its process lifetime"), so this is not an edge case — it is what every real, long-lived
    `zikaron-mcp` connection looks like from the service's own point of view.

    A deliberate, narrow exception to this file's own stated real-socket-free convention: a real
    `asyncio.start_unix_server`/`asyncio.open_unix_connection` pair is the only way to reproduce
    the actual `wait_closed()` hang this test defends against — `_handle_line`'s in-process
    dispatch has no notion of an accepted transport at all. `asyncio.wait_for` bounds the whole
    assertion so a genuine regression fails this test in a few seconds rather than hanging the
    whole suite indefinitely.

    Sends one real request and reads its real response before ever calling `shut_down` — not
    merely opening the connection and immediately proceeding, which would race the event loop's
    own scheduling of the server-side accept callback and could pass with the connection not yet
    actually registered as "accepted" on either the fixed or the broken code, defending nothing.
    Confirmed by direct measurement: a first draft of this test without the request/response
    round trip passed even with `RunningServer.close_all_connections` temporarily removed from
    `shut_down`, precisely because of this race — the version below is what actually
    distinguishes the two.
    """
    async with open_context(tmp_path) as ctx:
        sock_path = tmp_path / "server.sock"
        running = await server.serve(ctx, str(sock_path))

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(_line("health", {}))
        await writer.drain()
        response_line = await reader.readline()
        assert json.loads(response_line)["result"]["ready"] is True

        # The connection stays open here — deliberately never closed by this test — which is
        # exactly the state `shut_down` must not depend on the peer ending on its own.
        try:
            await asyncio.wait_for(running.shut_down(), timeout=5.0)
        finally:
            writer.close()


async def test_shut_down_survives_a_connection_accepted_but_not_yet_self_registered(
    tmp_path: Path,
) -> None:
    """The narrower, more dangerous window the previous test's own request/response round trip
    cannot reach: a connection already **accepted** — meaning `asyncio.Server`'s own private
    `_active_count` (the exact quantity `wait_closed()` waits on) already reflects it — but whose
    handler task has not yet run far enough to reach `serve`'s own `connections.add(...)` line, so
    `RunningServer._connections` is still empty. Measured directly with a standalone script before
    writing the fix this test defends: reaching that line reliably took **three** bare
    `asyncio.sleep(0)` event-loop turns after the transport itself was already attached — not one,
    and not a number worth hardcoding as a sleep duration, which is exactly why this test builds
    the window directly with a real `asyncio.Server` and an intentionally empty `RunningServer.
    _connections`, rather than trying to time a real accept precisely (a sleep-based version of
    this test would be nondeterministic by construction: too short and it would not reliably land
    inside the window on a slower machine, too long and it would not be defending anything a
    request/response round trip did not already cover).

    A real client genuinely connects and is genuinely accepted — `server._active_count` reflects
    it — but `RunningServer` here is constructed with an empty `_connections` set on purpose, the
    exact state `close_all_connections` must still resolve from correctly by polling `_active_
    count` itself rather than assuming its own tracking set is already complete.
    """
    sock_path = tmp_path / "bare_server.sock"
    registration_gate = asyncio.Event()
    handler_started = asyncio.Event()

    async def _on_connect(reader: asyncio.StreamReader, _writer: asyncio.StreamWriter) -> None:
        # Holds this handler task suspended *before* it would register itself, deterministically
        # reproducing the accepted-but-not-yet-self-registered window — real production code
        # registers on its very first line with no `await` before it at all, so this artificial
        # gate is what a real handler's own multi-turn task-creation delay looks like from
        # `close_all_connections`'s point of view, without depending on how many turns that
        # actually takes on any given Python patch release. `handler_started` is set *before*
        # awaiting the gate specifically so the test below can wait for a real, observable fact
        # ("this task has begun running and is now blocked on the gate") rather than merely
        # yielding once and hoping that was enough turns for the task to have started at all —
        # a single bare `await asyncio.sleep(0)` can pass its own following assertion vacuously
        # if the handler task simply had not been scheduled yet, which proves nothing about
        # whether `shut_down` is genuinely blocked on this connection specifically.
        handler_started.set()
        await registration_gate.wait()
        connection = asyncio.current_task()
        assert connection is not None
        running._connections.add(connection)
        await reader.readline()

    bare_server = await asyncio.start_unix_server(_on_connect, path=str(sock_path))
    running = server.RunningServer(server=bare_server)

    _reader, writer = await asyncio.open_unix_connection(str(sock_path))
    try:
        # The client's own `open_unix_connection` returning says nothing about whether the
        # *server* side has processed the accept yet — that is a separate, asynchronous step —
        # so this polls for the one fact the test actually needs (the transport is attached) via
        # a real condition rather than assuming it is already true immediately after connecting.
        # This loop is not the thing under test — `close_all_connections` below is — so bounding
        # it generously and failing loudly if it is never met keeps this test itself honest about
        # what it is and is not measuring.
        for _ in range(1000):
            if bare_server._active_count > 0:  # type: ignore[attr-defined]
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("the server side never attached the accepted transport")
        assert len(running._connections) == 0, (
            "the handler task must not have reached its own registration line yet, or this test "
            "is not actually building the window it claims to"
        )

        shutdown_started = asyncio.Event()

        async def _shut_down_and_signal_started() -> None:
            # Set as this coroutine's very first synchronous action, before delegating to the
            # real `shut_down()` — proves the *task* wrapping this call has genuinely begun
            # running, which `handler_started` alone cannot: that event is set from a completely
            # different task (the gated connection handler), and nothing stops it from having
            # been set well before `shut_down_task` below is even created, in which case waiting
            # on it afterward would return immediately regardless of whether `shut_down_task`
            # itself has run a single line yet. Confirmed directly this is a real, not merely
            # theoretical, gap: the polling loop above yields repeatedly, and the gated handler
            # can reach `handler_started.set()` during any of those yields, well before this
            # function is ever called.
            shutdown_started.set()
            await running.shut_down()

        shut_down_task = asyncio.create_task(_shut_down_and_signal_started())
        # Waits for the *shutdown task itself* to confirm it has started running — not merely
        # that the gated connection handler has started, which is a different task with no
        # ordering guarantee relative to this one. This is what makes the assertion below
        # discriminating rather than vacuous: without this wait, `shut_down_task.done()` being
        # `False` could equally mean "genuinely blocked, having already begun draining" or "has
        # simply not been scheduled to run at all yet," and only the first of those is the
        # property this test claims to defend. `handler_started` remains useful and is still
        # awaited afterward, since the gate itself is only meaningful once the handler has
        # actually reached it — but it cannot, on its own, synchronize a *different* task
        # created afterward.
        await asyncio.wait_for(shutdown_started.wait(), timeout=5.0)
        await asyncio.wait_for(handler_started.wait(), timeout=5.0)
        assert not shut_down_task.done(), (
            "shut_down() returned before the gated connection ever registered or was released — "
            "it cannot have genuinely waited for _active_count to reach zero"
        )

        registration_gate.set()
        await asyncio.wait_for(shut_down_task, timeout=5.0)
    finally:
        writer.close()


async def test_close_all_connections_raises_loudly_rather_than_hanging_inside_gather(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`close_all_connections`'s deadline used to be checked only *after* its `await gather(...)`
    returned, and even the bounded successor (`asyncio.wait_for(gather(...), timeout=remaining)`)
    turned out not to be a genuine hard deadline either — `wait_for`'s own docstring says plainly
    that "if the task suppresses the cancellation and returns a value instead, that value is
    returned," and `gather(..., return_exceptions=True)` does exactly that for a child that keeps
    swallowing `CancelledError`, so a handler resisting *every* cancellation (not merely one) left
    `wait_for` itself waiting forever for the `gather` future it was meant to bound — confirmed
    directly with a standalone script before rewriting the production code to use `asyncio.wait`
    instead, which is documented plainly not to raise on timeout at all and hands control back to
    the caller's own deadline check regardless of whether the underlying tasks ever finish
    cancelling. This test's handler suppresses cancellation behind a **separately releasable**
    gate — not a fixed count — specifically so it distinguishes a real deadline from the
    second-cancellation escape hatch a fixed "swallow exactly once" handler would give a merely
    `wait_for`-wrapped fix an accidental way to pass through (the timeout's own cancellation of an
    outer future supplies exactly one more cancellation to an inner task, which a
    "swallow-exactly-once" handler would then let through, making the earlier, insufficient fix
    look correct for the wrong reason). `_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS` is monkeypatched
    to a small value so this test itself stays fast rather than needing to wait out the real 5 s
    production deadline."""
    monkeypatch.setattr(server, "_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS", 0.3)

    sock_path = tmp_path / "cancellation_resistant.sock"
    release_gate = asyncio.Event()

    async def _on_connect(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connection = asyncio.current_task()
        assert connection is not None
        running._connections.add(connection)
        try:
            while not release_gate.is_set():
                try:
                    # A plain `asyncio.sleep` is what reliably delivers `CancelledError` back to
                    # this `try` on cancellation — confirmed directly: an earlier draft of this
                    # test tried to reproduce the same resistance around `reader.readline()`
                    # instead, and found that cancelling a task suspended there can instead
                    # surface as `readline()` returning an ordinary (empty) result rather than
                    # raising, which is a genuinely different asyncio behaviour from what this
                    # test needs to construct on purpose.
                    await asyncio.sleep(10.0)
                except asyncio.CancelledError:
                    # Deliberately suppresses *every* cancellation until the test's own cleanup
                    # releases the gate — the scenario `close_all_connections` must genuinely
                    # bound by its own deadline rather than by hoping the handler eventually
                    # gives up.
                    continue
        finally:
            # Confirmed directly this matters, not merely for tidiness: the earlier draft of
            # this test never closed `writer` at all, and the handler task finishing normally
            # (once the gate opens) left the underlying transport itself still open, since
            # nothing had ever told it to close — the transport, not the task, is what `_active_
            # count` actually counts, and the test hung waiting for `bare_server.wait_closed()`
            # as a direct result. Mirrors `_handle_connection`'s own `finally: writer.close()`.
            writer.close()

    bare_server = await asyncio.start_unix_server(_on_connect, path=str(sock_path))
    running = server.RunningServer(server=bare_server)

    _reader, writer = await asyncio.open_unix_connection(str(sock_path))
    try:
        for _ in range(1000):
            if running._connections:
                break
            await asyncio.sleep(0)
        else:
            raise AssertionError("the handler task never registered itself")

        with pytest.raises(TimeoutError, match="responded to cancellation"):
            await asyncio.wait_for(running.close_all_connections(), timeout=5.0)
    finally:
        writer.close()
        # The handler resists cancellation until the gate is released — release it now, then
        # cancel one more time so it actually exits, rather than outliving this test.
        release_gate.set()
        for connection in list(running._connections):
            connection.cancel()
        await asyncio.gather(*list(running._connections), return_exceptions=True)
        bare_server.close()
        await bare_server.wait_closed()


async def test_health_response_is_valid_json_and_carries_no_session_id(tmp_path: Path) -> None:
    """`health` takes no envelope and echoes no `session_id` — `architecture.md`'s one exemption
    from the resolution preamble, and the exact case whose `.__dict__` bug this test would have
    caught before the real socket ever ran. `pid` in the response is **this process's own**
    `os.getpid()` — never anything a request can supply, per `architecture.md`'s
    `{ready, store_path, store_id, embed_model, embed_dim, schema_version, pid}` — so a request
    naming `pid` in its own params (as this one deliberately does) must have no effect on it."""
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(ctx, _line("health", {"pid": 4242}))
        result = parsed["result"]
        assert isinstance(result, dict)
        assert result["ready"] is True
        assert result["pid"] == os.getpid()
        assert "session_id" not in result


async def test_a_successful_call_echoes_the_resolved_session_id(tmp_path: Path) -> None:
    """`session_id` is a **sibling** of `result` — `client: {session_id}` in the response
    envelope, not merged into whatever shape `result` itself takes, since some methods'
    `result` is a bare list (`search`) with no key to add one to."""
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": _client("s1")})
        )
        client = parsed["client"]
        assert isinstance(client, dict)
        assert client["session_id"] == "s1"
        result = parsed["result"]
        assert isinstance(result, dict)
        assert "session_id" not in result


async def test_a_bootstrap_call_gets_a_minted_session_id_back(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": _client(None)})
        )
        client = parsed["client"]
        assert isinstance(client, dict)
        session_id = client["session_id"]
        assert isinstance(session_id, str)
        assert session_id.startswith("zk-")


async def test_search_returns_a_bare_list_with_the_label_still_attached(tmp_path: Path) -> None:
    """`memory_search`'s documented shape is a bare list — `[{uuid, gist, ...}, ...]`, no
    wrapping key — which is exactly why `session_id` cannot be merged into `result`: a list has
    no key to add one to, and this is the one method in this test file whose `result` is not an
    object at all."""
    async with open_context(tmp_path) as ctx:
        await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": _client("s1")})
        )
        parsed = await _response_json(
            ctx, _line("memory_search", {"query": "g", "client": _client("s1")})
        )
        assert isinstance(parsed["result"], list)
        client = parsed["client"]
        assert isinstance(client, dict)
        assert client["session_id"] == "s1"


async def test_a_zikaron_error_echoes_the_resolved_session_id_too(tmp_path: Path) -> None:
    """`architecture.md`: "a client that bootstraps into a failing first call still learns its
    label" — the label belongs in the response *envelope*, the same top-level `client.session_id`
    sibling a success uses, never spliced into the error's own declared `data` shape (`not_found`
    is `{uuid}`; nothing in the error table names `session_id` as one of its fields).

    Sends a genuine **bootstrap** envelope (`session_id=None`), not an already-labeled one — the
    docstring's own claim is specifically about a client that has *not yet* learned a label at
    all, and a test that supplies `_client("s1")` proves only that an already-labeled client keeps
    its label through an error, never that a freshly *minted* label survives one."""
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(
            ctx,
            _line(
                "memory_amend",
                {
                    "uuid": "no-such-uuid",
                    "version": 1,
                    "gist": "g",
                    "content": "c",
                    "client": _client(None),
                },
            ),
        )
        client = parsed["client"]
        assert isinstance(client, dict)
        session_id = client["session_id"]
        assert isinstance(session_id, str)
        assert session_id.startswith("zk-")
        error = parsed["error"]
        assert isinstance(error, dict)
        assert error["code"] == ErrorCode.NOT_FOUND
        data = error["data"]
        assert isinstance(data, dict)
        assert "session_id" not in data


async def test_a_malformed_envelope_gets_no_session_id_since_none_was_resolved(
    tmp_path: Path,
) -> None:
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": {"kind": "mcp"}})
        )
        assert "client" not in parsed
        error = parsed["error"]
        assert isinstance(error, dict)
        assert error["code"] == ErrorCode.BOUNDS
        data = error.get("data", {})
        assert isinstance(data, dict)
        assert "session_id" not in data


async def test_an_unhandled_handler_exception_still_echoes_the_resolved_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one `encode_error` call site in `_compute_response_line` no test had exercised at
    all: a genuine, unexpected exception from a handler (not a `ZikaronError`), reaching `_
    compute_response_line`'s own `except Exception:` fallback. Correct by inspection since round
    9's error-envelope fix — the call site passes `session_id=envelope.session_id` exactly like
    the other two — but "correct by inspection" is not the same claim as "guarded by a test," and
    a future edit to this specific call site could silently drop the keyword with nothing here to
    catch it. `_METHODS` is monkeypatched at the one entry `remember` resolves to, rather than
    forcing a real `core` function to raise, since the point is to exercise this server-level
    fallback specifically, independent of which real handler happened to be involved."""
    async with open_context(tmp_path) as ctx:

        async def _handler_raises_unexpectedly(
            _db: object, _ctx: object, _envelope: object, _params: object
        ) -> object:
            raise RuntimeError("a genuine bug in a handler, deliberately, for this test")

        monkeypatch.setitem(server._METHODS, "memory_remember", _handler_raises_unexpectedly)

        parsed = await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": _client("s1")})
        )
        client = parsed["client"]
        assert isinstance(client, dict)
        assert client["session_id"] == "s1"
        error = parsed["error"]
        assert isinstance(error, dict)
        assert error["code"] == rpc.ProtocolErrorCode.INTERNAL_ERROR
        assert "data" not in error or "session_id" not in error.get("data", {})


async def test_fetch_returns_the_documented_record_shape_and_reports_missing_uuids(
    tmp_path: Path,
) -> None:
    """`fetch` was the one primary-agent method with **no** service-level test at all — found by
    enabling the coverage floor on `zikaron/service` (which had been silently excluded since M1,
    when `core` was the only package), and worth closing rather than noting because an unasserted
    wire shape is exactly the class of defect a wrong RPC method name is: reachable only by a real
    client sending the real method name, invisible to a test that calls a Python handler function
    directly instead.

    Asserts the exact twelve-field record shape `architecture.md` §`zikaron_memory_fetch` states,
    as a set
    rather than by spot-checking a few keys, so a field silently added or dropped fails here; and
    asserts an unknown uuid is reported in `missing` rather than failing the batch, which the same
    section states explicitly ("a partial answer is more useful than none")."""
    async with open_context(tmp_path) as ctx:
        written = await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": _client("s1")})
        )
        result = written["result"]
        assert isinstance(result, dict)
        uuid = result["uuid"]

        parsed = await _response_json(
            ctx, _line("memory_fetch", {"uuids": [uuid, "no-such-uuid"], "client": _client("s1")})
        )
        fetched = parsed["result"]
        assert isinstance(fetched, dict)

        records = fetched["records"]
        assert isinstance(records, list)
        assert len(records) == 1, "the unknown uuid must not produce a record"
        record = records[0]
        assert isinstance(record, dict)
        assert set(record) == {
            "uuid",
            "gist",
            "content",
            "version",
            "tier",
            "active",
            "state",
            "superseded_by",
            "superseded_by_latest",
            "superseded_by_latest_state",
            "created_at",
            "updated_at",
        }
        assert record["uuid"] == uuid
        assert fetched["missing"] == ["no-such-uuid"]


async def test_an_unknown_method_is_a_protocol_level_error(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(ctx, _line("no_such_method", {"client": _client("s1")}))
        error = parsed["error"]
        assert isinstance(error, dict)
        assert error["code"] == rpc.ProtocolErrorCode.METHOD_NOT_FOUND


async def test_envelope_resolution_precedes_the_method_lookup(tmp_path: Path) -> None:
    """A malformed envelope is reported as the envelope failure, never as `method_not_found` —
    resolution is rung 0 of the preamble and runs before the method name is even looked up, so an
    unknown method paired with a bad envelope must not silently prefer the "friendlier" of the two
    possible rejections."""
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(ctx, _line("no_such_method", {"client": {"kind": "mcp"}}))
        error = parsed["error"]
        assert isinstance(error, dict)
        assert error["code"] == ErrorCode.BOUNDS


async def test_an_unknown_method_with_a_well_formed_envelope_still_echoes_the_label(
    tmp_path: Path,
) -> None:
    """A method that does not exist is checked **after** resolution, so a caller that sent a
    well-formed envelope still learns its label — `architecture.md`'s "on success and on every
    error alike" names no exception for "the method turned out not to exist," and the label is
    the same top-level `client.session_id` sibling a success uses, not a field spliced into
    `METHOD_NOT_FOUND`'s own `data`."""
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(ctx, _line("no_such_method", {"client": _client("s1")}))
        client = parsed["client"]
        assert isinstance(client, dict)
        assert client["session_id"] == "s1"
        error = parsed["error"]
        assert isinstance(error, dict)
        assert error["code"] == rpc.ProtocolErrorCode.METHOD_NOT_FOUND


async def test_a_notification_gets_no_response_line_at_all(tmp_path: Path) -> None:
    """The `id` key absent entirely is a genuine JSON-RPC notification — no line back, success or
    error alike, which is standard JSON-RPC 2.0 behaviour rather than a Zikaron-specific rule.

    The envelope is deliberately **well-formed** here: a notification whose own envelope is
    malformed would be suppressed for that reason alone, without ever proving that a
    *successful* dispatch is what gets suppressed — this asserts the handler actually ran (the
    memory is really in the store afterward) and only the response line was withheld."""
    async with open_context(tmp_path) as ctx:
        notification = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "memory_remember",
                    "params": {"gist": "g", "content": "c", "client": _client("s1")},
                }
            ).encode("utf-8")
            + b"\n"
        )
        response_line = await server._handle_line(ctx, notification)
        assert response_line is None

        rows = list(
            await ctx.store.connection.execute_fetchall("SELECT gist FROM memory WHERE gist = 'g'")
        )
        assert len(rows) == 1, "the notification's own handler must still have run"


async def test_a_notification_whose_params_fail_shape_validation_still_gets_no_response(
    tmp_path: Path,
) -> None:
    """`RequestParseError` itself must respect `has_id`, not only `_dispatch_request`'s own
    exceptions — a well-formed notification (no `id` key) whose `params` is not an object fails
    inside `parse_request`, before an `RpcRequest` ever exists, and that failure must be
    suppressed exactly as a later, method-level rejection of the same notification would be."""
    async with open_context(tmp_path) as ctx:
        malformed_notification = (
            json.dumps(
                {"jsonrpc": "2.0", "method": "memory_remember", "params": "not-an-object"}
            ).encode("utf-8")
            + b"\n"
        )
        response_line = await server._handle_line(ctx, malformed_notification)
        assert response_line is None


async def test_an_ordinary_request_with_an_explicit_null_id_still_gets_a_response(
    tmp_path: Path,
) -> None:
    """The one case `dict.get("id")` cannot distinguish from a notification on its own — an
    explicit `"id": null` is a real request and must receive `"id": null` back, never be
    suppressed as if the key had been absent."""
    async with open_context(tmp_path) as ctx:
        line = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "method": "memory_remember",
                    "params": {"gist": "g", "content": "c", "client": _client("s1")},
                }
            ).encode("utf-8")
            + b"\n"
        )
        response_line = await server._handle_line(ctx, line)
        assert response_line is not None
        parsed = json.loads(response_line)
        assert parsed["id"] is None
        assert "result" in parsed


async def test_activity_tracker_brackets_a_successful_dispatch(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        assert ctx.activity.in_flight == 0
        await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": _client("s1")})
        )
        assert ctx.activity.in_flight == 0


async def test_activity_tracker_brackets_a_rejected_dispatch_too(tmp_path: Path) -> None:
    """`in_flight` must return to zero even when the handler raises — `dispatch.amend`'s
    `not_found` here — since `main.py`'s idle self-stop depends on this counter never drifting."""
    async with open_context(tmp_path) as ctx:
        await _response_json(
            ctx,
            _line(
                "memory_amend",
                {
                    "uuid": "no-such-uuid",
                    "version": 1,
                    "gist": "g",
                    "content": "c",
                    "client": _client("s1"),
                },
            ),
        )
        assert ctx.activity.in_flight == 0


async def test_a_health_call_refreshes_last_activity(tmp_path: Path) -> None:
    """`architecture.md` §"Idle self-stop": "`last_activity` is refreshed when each request
    completes" — with no exception named for `health`, which is exactly the request a client's
    own start-if-absent sequence repeats while polling for readiness. A repeated `health()` poll
    must not let idle self-stop fire while it is happening."""
    async with open_context(tmp_path) as ctx:
        stale = ctx.activity.last_activity - 1000
        ctx.activity.last_activity = stale
        await _response_json(ctx, _line("health", {}))
        assert ctx.activity.last_activity > stale
        assert ctx.activity.in_flight == 0


async def test_an_unknown_method_refreshes_last_activity(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        stale = ctx.activity.last_activity - 1000
        ctx.activity.last_activity = stale
        await _response_json(ctx, _line("no_such_method", {"client": _client("s1")}))
        assert ctx.activity.last_activity > stale
        assert ctx.activity.in_flight == 0


async def test_a_malformed_envelope_still_refreshes_last_activity(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        stale = ctx.activity.last_activity - 1000
        ctx.activity.last_activity = stale
        await _response_json(
            ctx, _line("memory_remember", {"gist": "g", "content": "c", "client": {"kind": "mcp"}})
        )
        assert ctx.activity.last_activity > stale
        assert ctx.activity.in_flight == 0


async def test_invalid_json_produces_a_parse_error_with_no_id(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        parsed = await _response_json(ctx, b"not json {{{\n")
        error = parsed["error"]
        assert isinstance(error, dict)
        assert error["code"] == rpc.ProtocolErrorCode.PARSE_ERROR
        assert parsed["id"] is None


async def test_apply_discard_is_reachable_by_its_documented_wire_name(tmp_path: Path) -> None:
    """`architecture.md` §"Service RPC surface" names the three consolidator write methods
    `memory_apply_merge`/`memory_apply_promote`/`memory_apply_discard` on the wire — **not** the
    `memory_merge`/`memory_promote`/`memory_discard` that dropping each tool's `zikaron_` prefix
    would give, which is how every other wire method is spelled, and not the bare
    `merge`/`promote`/`discard` the design's own prose uses elsewhere for the underlying
    verb/concept. Every other consolidator test in this repository calls the Python handler
    functions directly (`dispatch_consolidation.consolidator_discard(...)`), which cannot detect a
    mismatch between the dict key `CONSOLIDATOR_METHODS` registers a handler under and the wire
    name a real client would actually send — this test is the one place that mismatch would have
    been caught, going through `server._handle_line`'s own method-name lookup exactly as a real
    socket connection would."""
    async with open_context(tmp_path) as ctx:
        assert isinstance(ctx.encoder, FakeEncoder)
        first, second = await _write_orphan_pair(ctx)
        consolidator = _client("agent-session", pid=4242, kind=ClientKind.CONSOLIDATOR.value)

        served = await _response_json(ctx, _line("memory_next_group", {"client": consolidator}))
        group_id = served["result"]["group_id"]  # type: ignore[index]
        assert isinstance(group_id, str)

        discarded = await _response_json(
            ctx,
            _line(
                "memory_apply_discard",
                {
                    "group_id": group_id,
                    "absorb": [
                        {"uuid": first, "expected_version": 1},
                        {"uuid": second, "expected_version": 1},
                    ],
                    "reason": "duplicate noise",
                    "client": consolidator,
                },
            ),
        )
        result = discarded["result"]
        assert isinstance(result, dict)
        assert result["retired"] == 2
        assert result["group_complete"] is True


async def test_apply_promote_is_reachable_by_its_documented_wire_name(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        assert isinstance(ctx.encoder, FakeEncoder)
        first, second = await _write_orphan_pair(ctx)
        consolidator = _client("agent-session", pid=4242, kind=ClientKind.CONSOLIDATOR.value)

        served = await _response_json(ctx, _line("memory_next_group", {"client": consolidator}))
        group_id = served["result"]["group_id"]  # type: ignore[index]
        assert isinstance(group_id, str)

        promoted = await _response_json(
            ctx,
            _line(
                "memory_apply_promote",
                {
                    "group_id": group_id,
                    "gist": "promoted gist",
                    "content": "promoted content",
                    "absorb": [
                        {"uuid": first, "expected_version": 1},
                        {"uuid": second, "expected_version": 1},
                    ],
                    "client": consolidator,
                },
            ),
        )
        result = promoted["result"]
        assert isinstance(result, dict)
        assert result["group_complete"] is True
        assert result["uuid"] not in (first, second)


async def test_apply_merge_is_reachable_by_its_documented_wire_name(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        assert isinstance(ctx.encoder, FakeEncoder)
        anchor, member = await _write_anchored_pair(ctx)
        consolidator = _client("agent-session", pid=4242, kind=ClientKind.CONSOLIDATOR.value)

        served = await _response_json(ctx, _line("memory_next_group", {"client": consolidator}))
        group_id = served["result"]["group_id"]  # type: ignore[index]
        assert isinstance(group_id, str)

        merged = await _response_json(
            ctx,
            _line(
                "memory_apply_merge",
                {
                    "group_id": group_id,
                    "target": {"uuid": anchor, "expected_version": 1},
                    "gist": "merged gist",
                    "content": "merged content",
                    "absorb": [{"uuid": member, "expected_version": 1}],
                    "client": consolidator,
                },
            ),
        )
        result = merged["result"]
        assert isinstance(result, dict)
        assert result["version"] == 2
        assert result["group_complete"] is True


async def test_plan_groups_is_reachable_by_its_documented_wire_name(tmp_path: Path) -> None:
    """`plan_groups` is itself a reachable RPC per `architecture.md` — the explicit takeover call
    `zikaron-mcp` makes, not only the implicit call `next_group` makes on an absent run — so it
    needs its own wire-level check independent of `next_group`'s indirect coverage above."""
    async with open_context(tmp_path) as ctx:
        assert isinstance(ctx.encoder, FakeEncoder)
        await _write_orphan_pair(ctx)
        consolidator = _client("agent-session", pid=4242, kind=ClientKind.CONSOLIDATOR.value)

        parsed = await _response_json(ctx, _line("memory_plan_groups", {"client": consolidator}))
        result = parsed["result"]
        assert isinstance(result, dict)
        assert "run_id" in result


# Two prose pairs at a 10-degree angle: cosine ~0.985, comfortably above the default
# `orphan_edge_cutoff` (0.65), and each other's only neighbour, so they satisfy `mutual_k`'s
# default of 5 trivially and form one orphan group deterministically — the same fixture shape
# `test_service_dispatch_consolidation.py` uses, kept local rather than imported across test
# files per this project's own convention of self-contained test modules.
_ORPHAN_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_ORPHAN_B = (
    "proto codegen also fails locally",
    "the same compiler drift shows up in the dev container",
)
_ANCHOR = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_MEMBER = ("proto codegen also fails locally", "the same compiler drift shows up in the container")


async def _write_orphan_pair(ctx: ServiceContext) -> tuple[str, str]:
    assert isinstance(ctx.encoder, FakeEncoder)
    agent = _client("agent-session", pid=100, kind="mcp")
    uuids = []
    for gist, content, degrees in ((*_ORPHAN_A, 0.0), (*_ORPHAN_B, 10.0)):
        embedded = f"{gist}{PREFIX_SEPARATOR}{content}"
        ctx.encoder.planned[embedded] = unit_at(degrees, ctx.encoder.dim)
        response = await _response_json(
            ctx, _line("memory_remember", {"gist": gist, "content": content, "client": agent})
        )
        result = response["result"]
        assert isinstance(result, dict)
        uuids.append(result["uuid"])
    assert len(uuids) == 2
    return uuids[0], uuids[1]


async def _write_anchored_pair(ctx: ServiceContext) -> tuple[str, str]:
    """Returns `(anchor_uuid, member_uuid)` — the anchor already `tier='long_term'`, mirroring
    `test_service_dispatch_consolidation.py`'s own fixture of the same name and purpose: `merge`
    only ever accepts a row already in the group's persisted anchor/candidate set, never a fellow
    journal member, so an orphan pair with no long-term row has nothing legal to `merge` into."""
    assert isinstance(ctx.encoder, FakeEncoder)
    agent = _client("agent-session", pid=100, kind="mcp")
    embedded_anchor = f"{_ANCHOR[0]}{PREFIX_SEPARATOR}{_ANCHOR[1]}"
    ctx.encoder.planned[embedded_anchor] = unit_at(0.0, ctx.encoder.dim)
    anchor_response = await _response_json(
        ctx, _line("memory_remember", {"gist": _ANCHOR[0], "content": _ANCHOR[1], "client": agent})
    )
    anchor_result = anchor_response["result"]
    assert isinstance(anchor_result, dict)
    anchor_uuid = anchor_result["uuid"]
    assert isinstance(anchor_uuid, str)
    await ctx.store.connection.execute(
        "UPDATE memory SET tier = 'long_term' WHERE uuid = ?", (anchor_uuid,)
    )
    await ctx.store.connection.commit()

    embedded_member = f"{_MEMBER[0]}{PREFIX_SEPARATOR}{_MEMBER[1]}"
    ctx.encoder.planned[embedded_member] = unit_at(10.0, ctx.encoder.dim)
    member_response = await _response_json(
        ctx, _line("memory_remember", {"gist": _MEMBER[0], "content": _MEMBER[1], "client": agent})
    )
    member_result = member_response["result"]
    assert isinstance(member_result, dict)
    member_uuid = member_result["uuid"]
    assert isinstance(member_uuid, str)
    return anchor_uuid, member_uuid


def _client(session_id: str | None, *, pid: int = 100, kind: str = "mcp") -> dict[str, object]:
    return {"session_id": session_id, "kind": kind, "pid": pid}
