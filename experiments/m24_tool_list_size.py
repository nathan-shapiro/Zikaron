"""How big the primary server's `tools/list` answer is, per tool and in total.

Run it:

    .venv/bin/python experiments/m24_tool_list_size.py

**What this measures and what it does not.** It measures the bytes this project puts on the wire
when a harness asks what tools exist — every name, description and input schema, serialized the way
the transport serializes them. It does **not** measure what a harness does with them: whether they
arrive whole, whether a description is truncated on the way into a model's context, and whether a
model can find a tool it was never shown are all facts about the harness, and the only honest way
to establish them is a session with a real one.

Why it is worth taking anyway: the primary server grew from six tools to twelve, and the question
"is that a size anything is likely to cut" is answerable in a number rather than an intuition. The
comparable figure this project has already measured is the **tool-result** delivery threshold —
roughly 29,923 tokens delivered, refused past it, in single-counted payload bytes
(`research/claude-code-mcp-result-truncation.md`). That is a different channel from a tool list,
so it bounds nothing here; it is the nearest order of magnitude this corpus has.
"""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastmcp import Client

from zikaron.mcp.server import Mode, build_server


async def _measure(mode: Mode, scope: Path) -> list[tuple[str, int, int]]:
    """Every tool on one server, as `(name, description bytes, whole-entry bytes)`."""
    mcp = build_server(mode, scope_dir=scope)
    async with Client(mcp) as client:
        tools = await client.list_tools()
    measured: list[tuple[str, int, int]] = []
    for tool in sorted(tools, key=lambda one: one.name):
        entry = {
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.inputSchema,
        }
        whole = len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
        measured.append((tool.name, len((tool.description or "").encode("utf-8")), whole))
    return measured


async def _report() -> None:
    with TemporaryDirectory() as scope:
        for mode in ("primary", "consolidator"):
            measured = await _measure(mode, Path(scope))  # type: ignore[arg-type]
            print(f"\n{mode}: {len(measured)} tools")
            print(f"{'tool':<34}{'description':>12}{'whole entry':>14}")
            for name, description, whole in measured:
                print(f"{name:<34}{description:>12}{whole:>14}")
            print(
                f"{'TOTAL':<34}{sum(one[1] for one in measured):>12}"
                f"{sum(one[2] for one in measured):>14}"
            )


if __name__ == "__main__":
    asyncio.run(_report())
