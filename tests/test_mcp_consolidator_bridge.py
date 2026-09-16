"""The `memory_plan_groups` lazy-takeover bridge (`zikaron.mcp.consolidator._PlanBridge`) — the
exact three-state machine `build-plan.md`'s M10 done-when states, tested at its own transitions and
through the real `zikaron_memory_next_group` tool end to end.

Every test constructs a fake `request` that records which RPC methods were called, in order, and
returns a scripted response per call — the same shape `ServiceConnection.request` itself returns
(a parsed JSON-RPC response object), so these tests exercise `_PlanBridge`/`_call` exactly as they
run against a real connection, with only the socket itself faked out.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from fastmcp import Client

from zikaron.mcp.connection import ServiceConnection
from zikaron.mcp.consolidator import _PlanBridge
from zikaron.mcp.errors import ServiceRejectionError, TransportFailureError
from zikaron.mcp.server import build_server

_STORE_BUSY = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32020, "message": "store busy"}}
_INDEX_FAILED = {
    "jsonrpc": "2.0",
    "id": 1,
    "error": {"code": -32021, "message": "index maintenance failed"},
}
_PLAN_OK = {"jsonrpc": "2.0", "id": 1, "result": {"run_id": "r1", "status": "active"}}


def _scripted(
    responses: dict[str, list[dict[str, object]]], calls: list[str]
) -> Callable[..., object]:
    """A fake `ServiceConnection.request` that pops the next scripted response for `method` off
    `responses[method]` each time it is called, and appends `method` to `calls` in call order —
    so a test can assert both *what* was returned and *how many times*, and *in what order*, each
    method was actually reached.
    """

    async def fake_request(
        _self: ServiceConnection,
        method: str,
        _params: dict[str, object],
        *,
        envelope: object,  # noqa: ARG001 — keyword-only name must match `ServiceConnection.request`'s.
    ) -> dict[str, object]:
        calls.append(method)
        queue = responses.get(method, [])
        if not queue:
            raise AssertionError(f"no scripted response left for {method!r}; calls so far: {calls}")
        return queue.pop(0)

    return fake_request


async def test_unplanned_calls_plan_groups_before_the_first_forwarded_next_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake = _scripted(
        {
            "memory_plan_groups": [_PLAN_OK],
            "memory_next_group": [{"jsonrpc": "2.0", "id": 1, "result": {"done": True}}],
        },
        calls,
    )
    monkeypatch.setattr(ServiceConnection, "request", fake)
    connection = ServiceConnection(Path("/nonexistent"))
    bridge = _PlanBridge()

    await bridge.ensure_planned(connection)

    assert calls == ["memory_plan_groups"]


async def test_ready_forwards_without_calling_plan_groups_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake = _scripted({"memory_plan_groups": [_PLAN_OK]}, calls)
    monkeypatch.setattr(ServiceConnection, "request", fake)
    connection = ServiceConnection(Path("/nonexistent"))
    bridge = _PlanBridge()

    await bridge.ensure_planned(connection)
    assert calls == ["memory_plan_groups"]

    await bridge.ensure_planned(connection)
    await bridge.ensure_planned(connection)
    assert calls == ["memory_plan_groups"], (
        "a READY bridge must never call plan_groups a second time"
    )


async def test_store_busy_leaves_the_bridge_unplanned_so_a_retry_replans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`architecture.md`'s exact awkward transition, named in M10's own done-when: a first
    `plan_groups` answering `store_busy` leaves the client `unplanned` so the retry plans and
    serves — no `next_group` reaching the service in between, and exactly one takeover eventually
    committed."""
    calls: list[str] = []
    fake = _scripted({"memory_plan_groups": [_STORE_BUSY, _PLAN_OK]}, calls)
    monkeypatch.setattr(ServiceConnection, "request", fake)
    connection = ServiceConnection(Path("/nonexistent"))
    bridge = _PlanBridge()

    with pytest.raises(ServiceRejectionError) as excinfo:
        await bridge.ensure_planned(connection)
    assert excinfo.value.code == -32020
    assert calls == ["memory_plan_groups"], "store_busy must not itself call next_group"

    # The retry: a fresh forwarded next_group calls ensure_planned again, and this time succeeds.
    await bridge.ensure_planned(connection)
    assert calls == ["memory_plan_groups", "memory_plan_groups"]


async def test_a_non_busy_failure_becomes_failed_and_is_never_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    fake = _scripted({"memory_plan_groups": [_INDEX_FAILED, _PLAN_OK]}, calls)
    monkeypatch.setattr(ServiceConnection, "request", fake)
    connection = ServiceConnection(Path("/nonexistent"))
    bridge = _PlanBridge()

    with pytest.raises(ServiceRejectionError) as excinfo:
        await bridge.ensure_planned(connection)
    assert excinfo.value.code == -32021
    assert calls == ["memory_plan_groups"]

    # FAILED is terminal: every later call re-raises the same recorded failure without calling
    # plan_groups again, even though a second, successful response is scripted and waiting.
    for _ in range(3):
        with pytest.raises(ServiceRejectionError) as excinfo:
            await bridge.ensure_planned(connection)
        assert excinfo.value.code == -32021
    assert calls == ["memory_plan_groups"], "FAILED must never call plan_groups a second time"


async def test_a_transport_failure_during_plan_groups_becomes_failed_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_request_that_drops(
        _self: ServiceConnection,
        method: str,
        _params: dict[str, object],
        *,
        envelope: object,  # noqa: ARG001 — keyword-only name must match `ServiceConnection.request`'s.
    ) -> dict[str, object]:
        calls.append(method)
        raise ConnectionError("service died mid-request")

    monkeypatch.setattr(ServiceConnection, "request", fake_request_that_drops)
    connection = ServiceConnection(Path("/nonexistent"))
    bridge = _PlanBridge()

    with pytest.raises(TransportFailureError):
        await bridge.ensure_planned(connection)
    assert calls == ["memory_plan_groups"]

    with pytest.raises(TransportFailureError):
        await bridge.ensure_planned(connection)
    assert calls == ["memory_plan_groups"], "FAILED from a transport failure must also never retry"


async def test_end_to_end_through_the_real_tool_plan_groups_precedes_the_first_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bridge exercised through the actual `zikaron_memory_next_group` tool, via an in-memory
    `fastmcp.Client` — proving the wiring in `register_consolidator_tools` calls
    `bridge.ensure_planned` before forwarding, not merely that `_PlanBridge` itself is correct in
    isolation."""
    calls: list[str] = []
    fake = _scripted(
        {
            "memory_plan_groups": [_PLAN_OK],
            "memory_next_group": [{"jsonrpc": "2.0", "id": 1, "result": {"done": True}}],
        },
        calls,
    )
    monkeypatch.setattr(ServiceConnection, "request", fake)

    mcp = build_server("consolidator", scope_dir=tmp_path)
    async with Client(mcp) as client:
        result = await client.call_tool("zikaron_memory_next_group", {})

    assert calls == ["memory_plan_groups", "memory_next_group"]
    assert result.data == {"done": True}


async def test_end_to_end_a_second_next_group_does_not_replan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    fake = _scripted(
        {
            "memory_plan_groups": [_PLAN_OK],
            "memory_next_group": [
                {"jsonrpc": "2.0", "id": 1, "result": {"done": True}},
                {"jsonrpc": "2.0", "id": 1, "result": {"done": True}},
            ],
        },
        calls,
    )
    monkeypatch.setattr(ServiceConnection, "request", fake)

    mcp = build_server("consolidator", scope_dir=tmp_path)
    async with Client(mcp) as client:
        await client.call_tool("zikaron_memory_next_group", {})
        await client.call_tool("zikaron_memory_next_group", {})

    assert calls == ["memory_plan_groups", "memory_next_group", "memory_next_group"]


async def test_cancelling_during_plan_groups_moves_to_failed_never_back_to_unplanned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact ambiguity `plan_groups`' own service RPC creates under cancellation: the service
    may have already committed a successful takeover before the cancellation reached this client,
    and there is no way from here to tell that case apart from one where nothing happened yet.
    Leaving the bridge `UNPLANNED` in either case would let a retry risk a **second** successful
    takeover from one process — the exact bound `architecture.md`'s "at most one successful
    takeover per client process" exists to enforce — so cancellation must move straight to the
    terminal `FAILED` state, never back to a retryable one.
    """
    response_may_be_delivered = asyncio.Event()

    async def fake_request_that_hangs_on_the_response(
        _self: ServiceConnection,
        method: str,
        _params: dict[str, object],
        *,
        envelope: object,  # noqa: ARG001
    ) -> dict[str, object]:
        assert method == "memory_plan_groups"
        # Models the exact scenario the docstring above names: the request has already reached
        # the service and, for all this client can tell, may already have committed — only the
        # *response* has not arrived yet, and this coroutine is about to be cancelled while
        # waiting for it.
        await response_may_be_delivered.wait()
        return _PLAN_OK

    monkeypatch.setattr(ServiceConnection, "request", fake_request_that_hangs_on_the_response)
    connection = ServiceConnection(Path("/nonexistent"))
    bridge = _PlanBridge()

    task = asyncio.create_task(bridge.ensure_planned(connection))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # A second, separate `next_group` forwarding must not attempt another `plan_groups` — it must
    # find the bridge already `FAILED` and re-raise the recorded failure immediately.
    with pytest.raises(TransportFailureError):
        await bridge.ensure_planned(connection)

    # Release the never-cancelled underlying fake, so it does not linger as a running task after
    # this test ends.
    response_may_be_delivered.set()
