"""The names of the tools each mode registers, as data.

D32's two tool sets, in one place that is neither a server module nor a test. It exists because
**the installer has to spell these names in shipped prose**: Claude Code addresses an MCP tool
as `mcp__<server>__<tool>` and the model sees that string verbatim
(`research/claude-code-installer-probe.md` §6), so the consolidator prompt and the skill body cannot
carry bare names under that harness. A second hand-maintained list of tool names is exactly the
drift this corpus keeps paying for — a name that stops matching produces a model told to call a tool
that does not exist, which improvises rather than failing — so the lists live here and
`tests/test_mcp_server.py` asserts them against the tools the **real** servers actually register.

**Every name is `zikaron_<subsystem>_<verb>`, and the subsystem segment earns its length.** One
process serves two stores that answer different questions — agent-authored memories, and fragments
of files nobody here authored — and a model choosing between them reads the name before it reads
the description. A bare `zikaron_search` beside `zikaron_knowledge_search` reads as the general
case of the other rather than as a different store, and the resulting call costs a round trip to
return a confidently empty answer about the wrong corpus.

Spelled out in full rather than assembled from a prefix constant, deliberately: these strings are
what a model is shown, what a shipped prompt names, and what a design table is compared against, so
searching the repository for one has to find every place it is written.

Stdlib-only and import-cheap by construction (it imports nothing at all), because `zikaron.install`
reads it and the MCP server modules it describes pull in `fastmcp`.
"""

from typing import Final

#: The tools `register_primary_tools` decorates onto a `--mode primary` server: D32's five memory
#: verbs, plus the knowledge index's search and its six management verbs. Managing corpora is a
#: primary-agent job and nothing else — the consolidator has no use for a corpus of files, and
#: keeping every one of these out of that mode is the same structural guarantee the five memory
#: verbs already rely on.
PRIMARY_TOOLS: Final = frozenset(
    {
        "zikaron_memory_search",
        "zikaron_memory_fetch",
        "zikaron_memory_remember",
        "zikaron_memory_amend",
        "zikaron_memory_retire",
        "zikaron_knowledge_search",
        "zikaron_knowledge_list",
        "zikaron_knowledge_status",
        "zikaron_knowledge_add",
        "zikaron_knowledge_remove",
        "zikaron_knowledge_rename",
        "zikaron_knowledge_refresh",
    }
)

#: The four tools `register_consolidator_tools` decorates onto a `--mode consolidator` server.
#: Never registered in a primary process at all, which is the seam D7's claim rests on. They carry
#: the memory prefix because that is the store they rewrite; the mode a tool runs in is not part of
#: its name, since nothing a model reads tells it which mode it is in.
CONSOLIDATOR_TOOLS: Final = frozenset(
    {
        "zikaron_memory_next_group",
        "zikaron_memory_merge",
        "zikaron_memory_promote",
        "zikaron_memory_discard",
    }
)

#: Every tool name Zikaron ships. Which *server* owns each is deliberately **not** here:
#: server names belong to `zikaron.install.entries`, which already declares them for the
#: `mcpServers` map, and repeating them here would be the same drift this module exists to prevent.
ALL_TOOLS: Final = PRIMARY_TOOLS | CONSOLIDATOR_TOOLS
