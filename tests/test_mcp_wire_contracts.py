"""Every primary and consolidator tool sends the exact wire method, params and `client.kind`
`architecture.md` states — checked directly against a recording fake `ServiceConnection.request`,
via the real tool through `fastmcp.Client`, rather than only against the module's own internal
helper functions.
"""

import json
from pathlib import Path
from typing import NamedTuple

import pytest
from fastmcp import Client
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError

from zikaron.core.knowledge.groups import Group, SearchResponse, response_bytes
from zikaron.core.knowledge.search import Result
from zikaron.core.knowledge.state import KnowledgeState
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

    mcp = build_server(mode, scope_dir=tmp_path)
    return Client(mcp), calls


_SUCCESS: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

#: Any corpus root, for a case that is about what a tool *sends* rather than about what is on disk:
#: the service is faked out here, so nothing ever resolves this.
_A_PATH = "/corpus/docs"


class _ToolCase(NamedTuple):
    tool_name: str
    tool_args: dict[str, object]
    expected_method: str
    expected_params: dict[str, object]


@pytest.mark.parametrize(
    "case",
    [
        _ToolCase(
            "zikaron_memory_search",
            {"query": "q", "limit": 3, "include_retired": True},
            "memory_search",
            {"query": "q", "limit": 3, "include_retired": True},
        ),
        _ToolCase(
            "zikaron_memory_fetch",
            {"uuids": ["a", "b"]},
            "memory_fetch",
            {"uuids": ["a", "b"]},
        ),
        _ToolCase(
            "zikaron_memory_remember",
            {"gist": "g", "content": "c"},
            "memory_remember",
            {"gist": "g", "content": "c"},
        ),
        _ToolCase(
            "zikaron_memory_amend",
            {"uuid": "u1", "version": 2, "gist": "g", "content": "c"},
            "memory_amend",
            {"uuid": "u1", "version": 2, "gist": "g", "content": "c"},
        ),
        _ToolCase(
            "zikaron_memory_retire",
            {"uuid": "u1", "version": 2, "superseded_by": "u2"},
            "memory_retire",
            {"uuid": "u1", "version": 2, "superseded_by": "u2"},
        ),
        _ToolCase(
            "zikaron_knowledge_search",
            {"query": "q", "knowledge_bases": ["docs"], "limit_per_kb": 7},
            "knowledge_search",
            {"query": "q", "knowledge_bases": ["docs"], "limit_per_kb": 7},
        ),
        _ToolCase(
            "zikaron_knowledge_search",
            {"query": "q"},
            "knowledge_search",
            {"query": "q", "knowledge_bases": None, "limit_per_kb": 5},
        ),
        _ToolCase("zikaron_knowledge_list", {}, "knowledge_list", {}),
        _ToolCase(
            "zikaron_knowledge_status",
            {"knowledge_base": "docs"},
            "knowledge_status",
            {"knowledge_base": "docs"},
        ),
        _ToolCase("zikaron_knowledge_status", {}, "knowledge_status", {"knowledge_base": None}),
        _ToolCase(
            "zikaron_knowledge_add",
            {
                "name": "docs",
                "path": _A_PATH,
                "description": "a corpus",
                "include": ["*.md"],
                "exclude": ["draft/*"],
                "git_mode": "all",
                "max_file_bytes": 4096,
            },
            "knowledge_add",
            {
                "name": "docs",
                "path": _A_PATH,
                "description": "a corpus",
                "include": ["*.md"],
                "exclude": ["draft/*"],
                "git_mode": "all",
                "max_file_bytes": 4096,
            },
        ),
        _ToolCase(
            "zikaron_knowledge_add",
            {"name": "docs", "path": _A_PATH, "description": "a corpus"},
            "knowledge_add",
            {
                "name": "docs",
                "path": _A_PATH,
                "description": "a corpus",
                "include": None,
                "exclude": None,
                "git_mode": "tracked",
                "max_file_bytes": None,
            },
        ),
        _ToolCase(
            "zikaron_knowledge_remove",
            {"name": "docs", "confirm": True},
            "knowledge_remove",
            {"name": "docs", "confirm": True},
        ),
        _ToolCase(
            "zikaron_knowledge_rename",
            {"name": "docs", "new_name": "design"},
            "knowledge_rename",
            {"name": "docs", "new_name": "design"},
        ),
        _ToolCase(
            "zikaron_knowledge_refresh",
            {"name": "docs", "full": True},
            "knowledge_refresh",
            {"name": "docs", "full": True},
        ),
        _ToolCase(
            "zikaron_knowledge_refresh",
            {},
            "knowledge_refresh",
            {"name": None, "full": False},
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
            "zikaron_memory_merge",
            {
                "group_id": "g1",
                "target": {"uuid": "t1", "expected_version": 1},
                "gist": "g",
                "content": "c",
                "absorb": [{"uuid": "a1", "expected_version": 1}],
            },
            "memory_apply_merge",
            {
                "group_id": "g1",
                "target": {"uuid": "t1", "expected_version": 1},
                "gist": "g",
                "content": "c",
                "absorb": [{"uuid": "a1", "expected_version": 1}],
            },
        ),
        _ToolCase(
            "zikaron_memory_promote",
            {"group_id": "g1", "gist": "g", "content": "c", "absorb": []},
            "memory_apply_promote",
            {"group_id": "g1", "gist": "g", "content": "c", "absorb": []},
        ),
        _ToolCase(
            "zikaron_memory_discard",
            {"group_id": "g1", "absorb": [], "reason": "not useful"},
            "memory_apply_discard",
            {"group_id": "g1", "absorb": [], "reason": "not useful"},
        ),
    ],
)
async def test_each_consolidator_write_tool_sends_its_exact_apply_prefixed_wire_method(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: _ToolCase
) -> None:
    """`dispatch_consolidation.py`'s own docstring names the exact defect this test rules out: a
    client sending `memory_merge`/`memory_promote`/`memory_discard` — the tool's own name minus its
    `zikaron_` prefix, which is how every other wire method is spelled — rather than the actual
    `memory_apply_merge`/`memory_apply_promote`/`memory_apply_discard`
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
    write_calls = [call for call in calls if call[0] != "memory_plan_groups"]
    assert len(write_calls) == 1
    method, params, kind = write_calls[0]
    assert method == case.expected_method
    assert params == case.expected_params
    assert kind == "consolidator"


async def test_the_knowledge_response_cap_is_denominated_as_the_transport_delivers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap exists to stop a result being truncated at the harness without anything saying so,
    so what it counts has to be the same quantity the measured threshold counted.

    **Two facts, and the second is the trap.** Our accounting bounds the payload the transport
    delivers as text — asserted below, and non-zero, so a delivery carrying nothing cannot pass this
    by arithmetic. And the transport *also* sends that payload again as structured content, which
    is pinned here because it is the fact that invites the wrong conclusion: charging the cap twice
    for it would halve the answer, since the threshold the cap sits under was itself measured
    through this same duplication and recorded in single-counted payload size.
    """
    payload = SearchResponse(
        groups=(
            Group(
                knowledge_base="docs",
                description="design records",
                state=KnowledgeState.OK,
                files_remaining=None,
                results=tuple(
                    Result(
                        path=f"design/{index}.md",
                        start_line=1,
                        end_line=4,
                        snippet="a paragraph of prose with some length to it\n" * 4,
                        truncated=False,
                        score=0.5,
                        stale=False,
                    )
                    for index in range(5)
                ),
            ),
        ),
        groups_dropped=False,
    )
    response: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "result": payload.payload()}
    client, _calls = await _client_for("primary", tmp_path, monkeypatch, response)
    async with client:
        delivered = await client.call_tool("zikaron_knowledge_search", {"query": "anything"})
    as_text = sum(
        len(block.text.encode("utf-8")) for block in delivered.content if hasattr(block, "text")
    )
    assert as_text > 0
    assert as_text <= response_bytes(payload)
    # The duplication itself, pinned rather than described: the same payload again, as structured
    # content, which is what a reader has to know before deciding what the cap should count. Pinned
    # as equality rather than as presence, because what matters is that the second copy carries the
    # whole answer — a transport that shipped a stub or a summary here would leave the cap counting
    # a quantity nobody receives. Compared through a serialization round trip, which is the form
    # both copies cross the wire in: the payload's tuples arrive as lists.
    #
    # The `{"result": ...}` wrapper is the transport's rather than ours, and it is the detail that
    # settles the denomination. A tool that does not declare a structured return shape has its
    # answer wrapped under that single key; these tools do not declare one, so this is the same
    # shape taken by the probe whose measurements the cap's threshold comes from — which is why the
    # threshold and the cap describe one quantity, and why counting this copy would count it twice.
    assert delivered.structured_content == {"result": json.loads(json.dumps(payload.payload()))}


@pytest.mark.parametrize(
    ("tool_name", "tool_args"),
    [
        ("zikaron_memory_search", {"query": "anything"}),
        ("zikaron_knowledge_search", {"query": "anything"}),
    ],
)
async def test_a_primary_tool_reports_a_transport_failure_as_a_tool_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    tool_args: dict[str, object],
) -> None:
    """A service that cannot be reached must arrive at the model as a tool error carrying what went
    wrong — not as an opaque internal failure, which is what an uncaught exception from the socket
    layer would be. The message is checked as well as the type, because the type alone would pass
    for a handler that swallowed the cause."""

    async def _refuse(
        _self: ServiceConnection,
        _method: str,
        _params: dict[str, object],
        *,
        envelope: object,  # noqa: ARG001 — the keyword is the caller's, so the name cannot move.
    ) -> dict[str, object]:
        raise OSError("the socket is gone")

    monkeypatch.setattr(ServiceConnection, "envelope", lambda _self, *, kind: _FakeEnvelope(kind))
    monkeypatch.setattr(ServiceConnection, "request", _refuse)
    mcp = build_server("primary", scope_dir=tmp_path)
    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="the socket is gone"):
            await client.call_tool(tool_name, tool_args)
