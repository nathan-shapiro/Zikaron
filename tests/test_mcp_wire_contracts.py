"""Every primary and consolidator tool sends the exact wire method, params and `client.kind`
`architecture.md` states — checked directly against a recording fake `ServiceConnection.request`,
via the real tool through `fastmcp.Client`, rather than only against the module's own internal
helper functions.
"""

from pathlib import Path
from typing import NamedTuple

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport

from zikaron.mcp.connection import ServiceConnection
from zikaron.mcp.server import Mode, build_server


class _FakeEnvelope:
    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.session_id: str | None = None
        self.pid = 1
        self.op_id: str | None = None


async def _client_for(
    mode: Mode, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict[str, object]
) -> tuple[Client[FastMCPTransport], list[tuple[str, dict[str, object], str]]]:
    calls: list[tuple[str, dict[str, object], str]] = []

    def fake_envelope(_self: ServiceConnection, *, kind: str) -> _FakeEnvelope:
        return _FakeEnvelope(kind)

    async def fake_request(
        _self: ServiceConnection, method: str, params: dict[str, object], *, envelope: _FakeEnvelope
    ) -> dict[str, object]:
        calls.append((method, dict(params), envelope.kind))
        return response

    monkeypatch.setattr(ServiceConnection, "envelope", fake_envelope)
    monkeypatch.setattr(ServiceConnection, "request", fake_request)

    mcp = build_server(mode, cwd=tmp_path)
    return Client(mcp), calls


_SUCCESS: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}


class _ToolCase(NamedTuple):
    tool_name: str
    tool_args: dict[str, object]
    expected_method: str
    expected_params: dict[str, object]


@pytest.mark.parametrize(
    "case",
    [
        _ToolCase(
            "zikaron_search",
            {"query": "q", "limit": 3, "include_retired": True},
            "search",
            {"query": "q", "limit": 3, "include_retired": True},
        ),
        _ToolCase("zikaron_fetch", {"uuids": ["a", "b"]}, "fetch", {"uuids": ["a", "b"]}),
        _ToolCase(
            "zikaron_remember",
            {"gist": "g", "content": "c"},
            "remember",
            {"gist": "g", "content": "c"},
        ),
        _ToolCase(
            "zikaron_amend",
            {"uuid": "u1", "version": 2, "gist": "g", "content": "c"},
            "amend",
            {"uuid": "u1", "version": 2, "gist": "g", "content": "c"},
        ),
        _ToolCase(
            "zikaron_retire",
            {"uuid": "u1", "version": 2, "superseded_by": "u2"},
            "retire",
            {"uuid": "u1", "version": 2, "superseded_by": "u2"},
        ),
    ],
)
async def test_each_primary_tool_sends_its_exact_wire_method_and_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: _ToolCase
) -> None:
    client, calls = await _client_for("primary", tmp_path, monkeypatch, _SUCCESS)
    async with client:
        await client.call_tool(case.tool_name, case.tool_args)
    assert len(calls) == 1
    method, params, kind = calls[0]
    assert method == case.expected_method
    assert params == case.expected_params
    assert kind == "mcp"


@pytest.mark.parametrize(
    "case",
    [
        _ToolCase(
            "zikaron_merge",
            {
                "group_id": "g1",
                "target": {"uuid": "t1", "expected_version": 1},
                "gist": "g",
                "content": "c",
                "absorb": [{"uuid": "a1", "expected_version": 1}],
            },
            "apply_merge",
            {
                "group_id": "g1",
                "target": {"uuid": "t1", "expected_version": 1},
                "gist": "g",
                "content": "c",
                "absorb": [{"uuid": "a1", "expected_version": 1}],
            },
        ),
        _ToolCase(
            "zikaron_promote",
            {"group_id": "g1", "gist": "g", "content": "c", "absorb": []},
            "apply_promote",
            {"group_id": "g1", "gist": "g", "content": "c", "absorb": []},
        ),
        _ToolCase(
            "zikaron_discard",
            {"group_id": "g1", "absorb": [], "reason": "not useful"},
            "apply_discard",
            {"group_id": "g1", "absorb": [], "reason": "not useful"},
        ),
    ],
)
async def test_each_consolidator_write_tool_sends_its_exact_apply_prefixed_wire_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: _ToolCase
) -> None:
    """`dispatch_consolidation.py`'s own docstring names the exact defect this test rules out: a
    client sending bare `merge`/`promote`/`discard` (the verb name used elsewhere in the design's
    own prose) rather than the actual wire method `apply_merge`/`apply_promote`/`apply_discard`
    would receive `METHOD_NOT_FOUND` from a real service, invisible to any test that only calls
    this module's Python functions directly rather than going through the wire params it builds.
    """
    plan_response: dict[str, object] = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"run_id": "r1", "status": "active"},
    }
    client, calls = await _client_for("consolidator", tmp_path, monkeypatch, plan_response)
    async with client:
        # Force the bridge to READY first — every consolidator tool below is a write verb, none
        # of which the bridge gates, but starting from a clean, known state keeps this
        # parametrized test's own call count assertion exact regardless of tool ordering.
        await client.call_tool(case.tool_name, case.tool_args)
    write_calls = [call for call in calls if call[0] != "plan_groups"]
    assert len(write_calls) == 1
    method, params, kind = write_calls[0]
    assert method == case.expected_method
    assert params == case.expected_params
    assert kind == "consolidator"
