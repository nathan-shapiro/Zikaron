"""The names of the tools each mode registers, as data.

D32's two tool sets, in one place that is neither a server module nor a test. It exists because
**the installer now has to spell these names in shipped prose**: Claude Code addresses an MCP tool
as `mcp__<server>__<tool>` and the model sees that string verbatim
(`research/claude-code-installer-probe.md` §6), so the consolidator prompt and the skill body cannot
carry bare names under that harness. A second hand-maintained list of tool names is exactly the
drift this corpus keeps paying for — a name that stops matching produces a model told to call a tool
that does not exist, which improvises rather than failing — so the lists live here and
`tests/test_mcp_server.py` asserts them against the tools the **real** servers actually register.

Stdlib-only and import-cheap by construction (it imports nothing at all), because `zikaron.install`
reads it and the MCP server modules it describes pull in `fastmcp`.
"""

from typing import Final

#: The tools `register_primary_tools` decorates onto a `--mode primary` server: D32's five memory
#: verbs, plus knowledge search. Search over indexed documents is a primary-agent tool and nothing
#: else — the consolidator has no use for a corpus of files, and keeping it out of that mode is the
#: same structural guarantee the five memory verbs already rely on.
PRIMARY_TOOLS: Final = frozenset(
    {
        "zikaron_search",
        "zikaron_fetch",
        "zikaron_remember",
        "zikaron_amend",
        "zikaron_retire",
        "zikaron_knowledge_search",
    }
)

#: The four tools `register_consolidator_tools` decorates onto a `--mode consolidator` server.
#: Never registered in a primary process at all, which is the seam D7's claim rests on.
CONSOLIDATOR_TOOLS: Final = frozenset(
    {
        "zikaron_next_group",
        "zikaron_merge",
        "zikaron_promote",
        "zikaron_discard",
    }
)

#: Every tool name Zikaron ships. Which *server* owns each is deliberately **not** here:
#: server names belong to `zikaron.install.entries`, which already declares them for the
#: `mcpServers` map, and repeating them here would be the same drift this module exists to prevent.
ALL_TOOLS: Final = PRIMARY_TOOLS | CONSOLIDATOR_TOOLS
