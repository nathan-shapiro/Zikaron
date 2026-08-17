"""`zikaron.mcp.server.build_server` — tool-set separation is structural, not a filter.

Every test here uses `fastmcp.Client(mcp)` for an in-memory connection with no subprocess and no
real socket, per `coding-standards.md` §4's own testing convention for this framework
(`research/fastmcp-api-shape.md` §6) — these tests are about which tools exist on a `FastMCP`
instance and whether calling one reaches the network, not about the transport FastMCP itself uses.
"""

from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from zikaron.mcp.connection import ServiceConnection
from zikaron.mcp.server import build_server
from zikaron.mcp.tool_names import CONSOLIDATOR_TOOLS, PRIMARY_TOOLS

#: Read from `zikaron.mcp.tool_names` rather than restated here, and that is the point of the
#: module: the installer now spells these names into shipped prose, because Claude Code addresses a
#: tool as `mcp__<server>__<tool>` and the model sees that string verbatim. A second hand-kept list
#: whose drift produced a *prompt naming a tool that does not exist* would fail nowhere — a model
#: that cannot find a tool improvises. These two assertions are what make the declaration true: they
#: compare it against the tools the real servers actually register.
_PRIMARY_TOOL_NAMES = PRIMARY_TOOLS
_CONSOLIDATOR_TOOL_NAMES = CONSOLIDATOR_TOOLS


async def test_primary_mode_exposes_exactly_five_tools(tmp_path: Path) -> None:
    mcp = build_server("primary", cwd=tmp_path)
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == _PRIMARY_TOOL_NAMES


async def test_consolidator_mode_exposes_exactly_four_tools(tmp_path: Path) -> None:
    mcp = build_server("consolidator", cwd=tmp_path)
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == _CONSOLIDATOR_TOOL_NAMES


async def test_a_consolidator_config_provably_cannot_reach_search_or_fetch(
    tmp_path: Path,
) -> None:
    """`architecture.md`'s exact done-when phrase. "Provably" means structural absence, not a
    denied call: the consolidator's `FastMCP` instance never had `zikaron_search`/`zikaron_fetch`
    decorated onto it at all (`server.py`'s own docstring), so they are not merely refused —
    `tools/list` cannot name them and `tools/call` has no handler to dispatch to, which this test
    checks from both directions rather than only the enumeration one."""
    mcp = build_server("consolidator", cwd=tmp_path)
    async with Client(mcp) as client:
        tool_names = {tool.name for tool in await client.list_tools()}
        assert "zikaron_search" not in tool_names
        assert "zikaron_fetch" not in tool_names
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("zikaron_search", {"query": "anything"})
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool("zikaron_fetch", {"uuids": ["x"]})


async def test_a_primary_config_has_no_consolidator_tools_either(tmp_path: Path) -> None:
    """The structural absence runs both directions — D32's two tool sets are disjoint, not one
    set with a "primary" subset and a "consolidator" superset."""
    mcp = build_server("primary", cwd=tmp_path)
    async with Client(mcp) as client:
        tool_names = {tool.name for tool in await client.list_tools()}
    assert tool_names.isdisjoint(_CONSOLIDATOR_TOOL_NAMES)


async def test_building_either_server_makes_no_service_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M10's own done-when: "the client provably makes no service call until the model calls a
    tool, so a spawn that does nothing takes no lock." `build_server` constructs a
    `ServiceConnection`, but `ServiceConnection.__init__` only resolves paths — it must never
    reach the service by any path, and this test proves that by failing every seam a constructor
    could reach the service through, not only `.request()` itself: patching `.request()` alone
    would still pass for a hypothetical `ServiceConnection.__init__` that called
    `connect_start_if_absent` or opened the store directly, bypassing `.request()` entirely and
    still violating the property this test is named for.
    """

    async def _fail_if_called(
        _self: object,
        method: str,
        _params: dict[str, object],
        *,
        envelope: object,  # noqa: ARG001 — keyword-only name must match `ServiceConnection.request`'s.
    ) -> object:
        raise AssertionError(
            f"ServiceConnection.request({method!r}, ...) was called merely by building the "
            "server — no tool was invoked"
        )

    def _fail_if_store_opened(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Store.open was called merely by building the server")

    def _fail_if_connection_attempted(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("connect_start_if_absent was called merely by building the server")

    monkeypatch.setattr(ServiceConnection, "request", _fail_if_called)
    monkeypatch.setattr("zikaron.mcp.connection.Store.open", _fail_if_store_opened)
    monkeypatch.setattr(
        "zikaron.mcp.connection.connect_start_if_absent", _fail_if_connection_attempted
    )

    build_server("primary", cwd=tmp_path)
    build_server("consolidator", cwd=tmp_path)
    # No assertion beyond "this did not raise": if either `build_server` call, or the
    # `register_*_tools` calls it makes, had reached any of the three patched seams for any
    # reason, the version above would have raised already.


async def test_listing_tools_makes_no_service_call_either(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`tools/list` returns each tool's already-computed schema (name, description, parameters —
    all derived from the decorated function's own signature and docstring at decoration time), not
    anything a call to the service could produce, so listing must be exactly as lazy as building —
    checked against the same three seams the sibling test above uses, for the identical reason.
    """

    async def _fail_if_called(
        _self: object,
        method: str,
        _params: dict[str, object],
        *,
        envelope: object,  # noqa: ARG001 — keyword-only name must match `ServiceConnection.request`'s.
    ) -> object:
        raise AssertionError(f"ServiceConnection.request({method!r}, ...) was called by tools/list")

    def _fail_if_store_opened(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Store.open was called by tools/list")

    def _fail_if_connection_attempted(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("connect_start_if_absent was called by tools/list")

    monkeypatch.setattr(ServiceConnection, "request", _fail_if_called)
    monkeypatch.setattr("zikaron.mcp.connection.Store.open", _fail_if_store_opened)
    monkeypatch.setattr(
        "zikaron.mcp.connection.connect_start_if_absent", _fail_if_connection_attempted
    )

    mcp = build_server("primary", cwd=tmp_path)
    async with Client(mcp) as client:
        await client.list_tools()
