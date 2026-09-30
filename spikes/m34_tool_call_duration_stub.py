"""Stub MCP server for measuring how long a harness lets one tool call run (M34).

Its one tool sleeps `seconds` and logs start and end to `stub.log` beside this file. The log shows
the server slept; that the harness waited is shown only by the tool's own result reaching the model,
so read both. Measured 2026-09-29: a 330 s call completed under both Claude Code 2.1.280 and
kiro-cli, and each model's reply carried `slept 330.1s` (`design/harness.md`, row "MCP tool-call
duration"). Re-derive:

    claude -p "Call mcp__stub__sleep_for once with seconds=330 and reply with its result" \
        --mcp-config mcp.json --strict-mcp-config --allowedTools mcp__stub__sleep_for
    kiro-cli chat --agent stubprobe --trust-all-tools --no-interactive "<the same request>"

with `mcp.json` / `.kiro/agents/stubprobe.json` naming this file as the `stub` server.
"""
import asyncio, time, sys
from pathlib import Path
from fastmcp import FastMCP
LOG = Path(__file__).with_name("stub.log")
mcp = FastMCP("stub")
@mcp.tool
async def sleep_for(seconds: int) -> str:
    """Sleep for `seconds` seconds, then return how long it actually slept."""
    t = time.monotonic()
    with LOG.open("a") as f: f.write(f"{time.time():.0f} start {seconds}\n")
    await asyncio.sleep(seconds)
    with LOG.open("a") as f: f.write(f"{time.time():.0f} end {time.monotonic()-t:.1f}\n")
    return f"slept {time.monotonic()-t:.1f}s"
mcp.run()
