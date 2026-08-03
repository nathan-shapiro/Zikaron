"""`build_server(mode)`: one `FastMCP` instance, with exactly the tool set `mode` names.

`architecture.md` §"a consolidator config provably cannot reach `search` or `fetch`" is the whole
reason this module exists as a separate seam rather than one function that decorates all nine
tools and hides five of them: `register_primary_tools`/`register_consolidator_tools` are only ever
called one at a time, per process, so the tools the other mode owns are never decorated onto this
process's `FastMCP` instance at all — not merely hidden from `tools/list`, absent from it, and
absent from what `tools/call` can dispatch to, regardless of what a model asks for. This is
Approach A from `research/fastmcp-api-shape.md` §3: read the mode before constructing any tool,
decorate only the relevant functions, rather than registering all nine and filtering.

Constructing a `ServiceConnection` here costs nothing beyond resolving paths — it opens no socket
(`connection.py`'s own contract) — so building the server for either mode makes no RPC call, and
neither does anything else in this module: the tools' own bodies are the only code that ever calls
`ServiceConnection.request`, and those bodies run only on an actual `tools/call`.
"""

from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from zikaron.mcp.connection import ServiceConnection
from zikaron.mcp.consolidator import register_consolidator_tools
from zikaron.mcp.primary import register_primary_tools

#: The two agent configs D32 names, and the only two values `build_server` accepts — a third
#: string would be a caller bug, not a mode this project has ever specified, so it is rejected
#: rather than silently defaulted to either real one.
Mode = Literal["primary", "consolidator"]


def build_server(mode: Mode, *, cwd: Path) -> FastMCP:
    """One `FastMCP` instance for `mode`, its tools decorated and nothing else done yet — no
    connection opened, no RPC made.

    Args:
        mode: `"primary"` registers the five primary-agent tools; `"consolidator"` registers the
            four consolidator tools plus the `plan_groups` bridge in front of `next_group`.
        cwd: this process's own working directory, D17's scope key — resolved once here and
            handed to the one `ServiceConnection` this process holds for its whole lifetime.
    """
    mcp = FastMCP(name=f"zikaron-{mode}")
    connection = ServiceConnection(cwd)
    if mode == "primary":
        register_primary_tools(mcp, connection)
    else:
        register_consolidator_tools(mcp, connection)
    return mcp
