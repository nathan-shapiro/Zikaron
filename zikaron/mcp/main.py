"""The process entry point: parse which mode this process runs as, build its server, and serve.

Invoked as `python -m zikaron.mcp.main --mode {primary|consolidator}` — the exact shape M12's
shipped agent configs (`.kiro/agents/zikaron-consolidator.json` and whichever config carries the
primary agent's own `mcpServers` entry) supply as `command`/`args`, one MCP server process per
agent spawn (`research/kiro-mcp-lifecycle-probe.md`). `--mode` is a required, explicit argument
rather than an environment variable: the two configs already differ in every other field they
carry, and stating the mode where the rest of the invocation is stated keeps the whole command
self-documenting from the config file alone, with nothing to look up in a separate `env` block to
know which tool set a given `mcpServers` entry actually exposes.
"""

import argparse
import sys
from pathlib import Path

from zikaron.mcp.server import Mode, build_server


def _parse_args(argv: list[str]) -> Mode:
    parser = argparse.ArgumentParser(prog="zikaron-mcp")
    parser.add_argument("--mode", required=True, choices=("primary", "consolidator"))
    parsed = parser.parse_args(argv)
    mode: Mode = parsed.mode
    return mode


def main(argv: list[str] | None = None) -> None:
    """Parse `--mode`, build that mode's server, and run it over stdio.

    `FastMCP.run()` defaults to stdio transport, creates its own event loop internally, and
    cannot be called from inside one that is already running
    (`research/fastmcp-api-shape.md` §4) — so this function stays synchronous top to bottom
    rather than being `async def` with an inner `asyncio.run`, and every tool handler's own
    `async def` body runs *inside* the loop `run()` manages, never a separate one this function
    would otherwise need to reconcile with it.

    Building the server here, before `run()` is ever called, makes no RPC call and opens no
    socket — `server.py`'s own contract — so the whole sequence from process start to the first
    `tools/list` response costs exactly the `fastmcp` import plus tool registration, with no
    service dependency at all until a model actually calls one of them.
    """
    mode = _parse_args(sys.argv[1:] if argv is None else argv)
    mcp = build_server(mode, cwd=Path.cwd())
    mcp.run()


if __name__ == "__main__":
    main()
