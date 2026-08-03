"""Every tool description carries the decision mechanics `architecture.md` requires sitting in
context at the point of decision (D30), asserted directly against the generated `tools/list`
description text rather than only against the source docstring — a description is what a calling
model actually sees, and the two can diverge if a future edit changes one without the other.
"""

from pathlib import Path

import pytest
from fastmcp import Client

from zikaron.mcp.server import build_server


async def _description_of(mode: str, tool_name: str, tmp_path: Path) -> str:
    mcp = build_server(mode, cwd=tmp_path)  # type: ignore[arg-type]
    async with Client(mcp) as client:
        tools = await client.list_tools()
    (tool,) = [tool for tool in tools if tool.name == tool_name]
    description = tool.description
    assert isinstance(description, str)
    return description


@pytest.mark.parametrize(
    "required_phrase",
    [
        "may not\nequal `uuid` itself",
        "create a cycle",
        "may not already be retired outright",
    ],
)
async def test_zikaron_retire_describes_the_supersession_graph_rules(
    tmp_path: Path, required_phrase: str
) -> None:
    """`architecture.md` §"zikaron_retire": `superseded_by` must satisfy schema.md invariant 6 —
    "no self-edge, no cycle, target not already retired-outright" — and a model that does not know
    these rules in advance would only discover them by trying an illegal edge and reading the
    rejection; stating them in the tool's own description lets it avoid an avoidable one."""
    description = await _description_of("primary", "zikaron_retire", tmp_path)
    assert required_phrase in description


@pytest.mark.parametrize(
    "required_phrase",
    [
        "1-based",
        "including this delivery",
        "excludes",
    ],
)
async def test_zikaron_next_group_describes_shard_serve_count_and_remaining_groups(
    tmp_path: Path, required_phrase: str
) -> None:
    """`architecture.md` §"zikaron_next_group": `shard` is 1-based, `serve_count` includes the
    current delivery, and `remaining_groups` excludes the group just delivered — each of the
    three is easy to get backwards without being told, and a consolidator that assumed 0-based
    sharding or an inclusive `remaining_groups` would misjudge whether it is looking at a re-serve
    or the last group of a run."""
    description = await _description_of("consolidator", "zikaron_next_group", tmp_path)
    assert required_phrase in description
