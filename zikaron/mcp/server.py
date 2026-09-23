"""`build_server(mode)`: one `FastMCP` instance, with exactly the tool set `mode` names.

`architecture.md` §"Consolidator tool surface" — *"'Provably cannot reach' is structural, not a
filter, and the mechanism is where the tool set is decided"* — is the whole reason this module
exists as a separate seam rather than one function that decorates every tool and hides the ones
this mode does not own: `register_primary_tools`/`register_consolidator_tools` are only ever called
one at a time, per process, so the tools the other mode owns are never decorated onto this
process's `FastMCP` instance at all — not merely hidden from `tools/list`, absent from it, and
absent from what `tools/call` can dispatch to, regardless of what a model asks for. This is
Approach A from `research/fastmcp-api-shape.md` §3: read the mode before constructing any tool,
decorate only the relevant functions, rather than registering both sets and filtering.

**The counts are deliberately not written here.** `zikaron.mcp.tool_names` is where each mode's
set is declared, and a number repeated in this docstring is one more thing to keep in step with a
set that grows.

Constructing a `ServiceConnection` here costs nothing beyond resolving paths — it opens no socket
(`connection.py`'s own contract) — so building the server for either mode makes no RPC call, and
neither does anything else in this module: the tools' own bodies are the only code that ever calls
`ServiceConnection.request`, and those bodies run only on an actual `tools/call`.
"""

from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

from zikaron.harness import detect
from zikaron.mcp import spill
from zikaron.mcp.connection import ServiceConnection, resolve_effective_config
from zikaron.mcp.consolidator import register_consolidator_tools
from zikaron.mcp.primary import register_primary_tools
from zikaron.mcp.spill import SpillPolicy
from zikaron.service import paths

#: The two agent configs D32 names, and the only two values `build_server` accepts — a third
#: string would be a caller bug, not a mode this project has ever specified, so it is rejected
#: rather than silently defaulted to either real one.
Mode = Literal["primary", "consolidator"]


def build_server(mode: Mode, *, scope_dir: Path) -> FastMCP:
    """One `FastMCP` instance for `mode`, its tools decorated and nothing else done yet — no
    connection opened, no RPC made.

    Args:
        mode: `"primary"` registers the primary agent's tools — the memory verbs and the whole
            knowledge surface; `"consolidator"` registers the four consolidator tools plus the
            `memory_plan_groups` bridge in front of `memory_next_group`.
        scope_dir: the **already-resolved** store-scope directory (D17) —
            `main.py` resolves it through `HarnessSpec.store_scope_dir` and this hands it to the
            one `ServiceConnection` this process holds for its whole lifetime.

    Raises:
        ZikaronError: `StoreLocation.resolve`'s `BAD_CONFIG` for a runtime directory that leaves
            no room in `sun_path`, in either mode; in consolidator mode also
            `resolve_effective_config`'s, since `_spill_policy` reads both config layers here
            rather than per call. Either stops the server before it serves.
    """
    mcp = FastMCP(name=f"zikaron-{mode}")
    connection = ServiceConnection(scope_dir)
    if mode == "primary":
        register_primary_tools(mcp, connection)
    else:
        spill_policy = _spill_policy(connection)
        # Before serving anything: remove what a previous consolidator left behind. This process's
        # own exit cannot be relied on — a harness terminates its MCP server rather than letting it
        # exit, so cleanup has to be something the *next* start does rather than something the last
        # one promised.
        spill.sweep_stale(spill_policy)
        register_consolidator_tools(mcp, connection, spill_policy=spill_policy)
    return mcp


def _spill_policy(connection: ServiceConnection) -> SpillPolicy:
    """Whether this process may write an over-large result to a file, and above what size.

    Built here rather than inside the consolidator module so that the primary branch above cannot
    acquire one by accident: spilling is a property of the consolidator mode, and the only way to
    obtain a policy is to be on that branch.

    The config read is blocking and deliberately runs here, at build time, before anything is
    served — `build_server`'s contract is that it opens no connection and makes no RPC, which this
    keeps; a local file read is not a round trip. Resolving it per call instead would put a `stat`
    and two file reads on every tool invocation to answer a question whose answer cannot change
    while the process lives (`schema.md`: config is read once, at startup).
    """
    config = resolve_effective_config(connection.location.store_dir)
    return SpillPolicy(
        enabled=detect.current_spec().consolidator_can_read_files,
        threshold_bytes=config.get_int("spill_threshold"),
        directory=connection.location.runtime_dir,
        # The same hash the socket is named for, so one store's spill files are findable among
        # every store's without opening any of them — which is what the erasure procedure needs.
        store_key=paths.socket_hash(connection.location.store_dir.resolve()),
    )
