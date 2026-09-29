"""Which of a project's Claude Code subagents cannot see Zikaron's tools, and why that is reported.

An explicit `tools:` list in a Claude Code subagent's frontmatter **overrides** the project-wide MCP
registration the Claude Code target otherwise relies on. Such an agent sees no Zikaron verb while
every artefact the install writes is still correct, so the symptom is a store that stays empty with
nothing anywhere saying why. `design/harness.md` §"What the install reports rather than enforces" is
normative.

**Detection only, never an edit.** A user's allowlist is a deliberate grant — the one that cost an
hour to diagnose excluded `Task` and every `mcp__*` — and an installer that widens it so its own
tools become reachable is making a security-adjacent decision on the user's behalf. That is the same
reasoning Zikaron applies in reverse when it keeps the consolidator's own grant narrow.

**This is the first thing the installer reads rather than writes, and the parsing rule is
load-bearing.** `install/assets.py` emits frontmatter needing no assumption about which YAML
features a harness's parser supports, and this package carries no YAML dependency at all. Reading a
third party's file inverts that, against files the harness accepts and a strict parser would not: an
agent's prose body follows the frontmatter and is not YAML. A mis-parse fails in the two directions
that cost the most — naming an agent that is fine, or staying silent about the one that is broken,
which is the diagnosis this scan exists to shorten.

**The accepted grammar, so a wrong name is diagnosable from the agent file rather than from here.**
A `tools:` key at column zero, with or without a space before its colon, carrying either a
comma-separated value on the same line, a bracketed flow sequence closed on that line, or a `-`
block list below it. Entries may be quoted and may carry a trailing `#` comment. **Two spellings
YAML accepts are not read, and both fail by naming an agent that is fine**: a block scalar
(`tools: >-` or `|` with the entries indented beneath), and a flow sequence whose bracket closes on
a later line. Neither is a plausible way to write a tools list, and the cost of getting one wrong is
a name to check rather than a silence.
"""

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from zikaron.install.entries import CONSOLIDATOR_AGENT_NAME, MCP_SERVER_NAME

#: The line that opens and closes a frontmatter block.
_FENCE: Final = "---"

#: The frontmatter key whose presence overrides project-wide inheritance.
_TOOLS_KEY: Final = "tools"

#: What opens a YAML comment. Stripped from the `tools:` line and from each list entry, because a
#: trailing comment left in place matches neither form of the grant and names an agent that is fine.
_COMMENT: Final = "#"

#: A byte-order mark, which several editors write and which would otherwise make a file that *does*
#: open with a fence read as having none — the scan then going silent about it. Spelled as an escape
#: because the character itself is invisible in every editor that would show this line.
_BOM: Final = chr(0xFEFF)

#: What a `tools:` entry must be to reach Zikaron's own server: **equality, or the `__` prefix,
#: never a bare prefix.** The consolidator's server is `zikaron-consolidator`, so `mcp__zikaron` is
#: a prefix of `mcp__zikaron-consolidator__…` — a `startswith` test would pass an agent that can
#: reach only the consolidator while still being unable to see a single memory verb.
GRANT: Final = f"mcp__{MCP_SERVER_NAME}"
_GRANT_PREFIX: Final = f"{GRANT}__"

#: The one agent the installer writes itself, matched on the filename derived from its own constant.
#: Its narrow grant is D32 working, so a scan that did not skip it would name Zikaron's own artefact
#: as unable to see Zikaron, on every install. Every **other** agent holding only the consolidator's
#: grant is still named: that grant belongs to the consolidator alone.
_SHIPPED_AGENT_FILENAME: Final = f"{CONSOLIDATOR_AGENT_NAME}.md"


def agents_directory(project: Path) -> Path:
    """Where `blind_agents` looks, for a caller that needs to name it in a report.

    The project's own directory alone. A **user-level** agent under `~/.claude/agents/` takes the
    same frontmatter and is usable in any project, and is deliberately out of scope: it sits outside
    a scan of the project's own directory. Said so the next diagnosis does not re-derive it.
    """
    return project / ".claude" / "agents"


def blind_agents(project: Path) -> tuple[str, ...] | None:
    """Each agent whose `tools:` list cannot reach Zikaron's server, as a project-relative path.

    Paths rather than names, because a path is what the reader has to open to change the grant, and
    an agent's frontmatter `name:` need not match its filename.

    Returns:
        The agents, sorted, possibly empty — or **`None` when there is no directory to scan**, which
        is a different answer from *nobody was named*: a report whose row is absent says the
        question was not asked, and one saying `none` says it was asked and answered.
    """
    directory = agents_directory(project)
    if not directory.is_dir():
        return None
    named = [
        str(path.relative_to(project))
        for path in sorted(directory.glob("*.md"))
        if path.name != _SHIPPED_AGENT_FILENAME and _is_blind(path)
    ]
    return tuple(named)


def _is_blind(path: Path) -> bool:
    """Whether this file sets a `tools:` list and no entry in it reaches Zikaron's server.

    An unreadable file is not blind: this scan is an advisory line inside a command whose work is
    already done, and a permission error or undecodable bytes in somebody else's agent file is not
    something to fail an install over.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    block = _frontmatter(text)
    if block is None:
        return False
    granted = _granted_tools(block)
    if granted is None:
        # No `tools:` key, so nothing overrides the project-wide registration and the agent inherits
        # everything. Note what this leaves uncovered: `disallowedTools: mcp__zikaron` beside no
        # `tools:` list is equally blind and is deliberately out of scope.
        return False
    return not _reaches_zikaron(granted)


def _frontmatter(text: str) -> list[str] | None:
    """The block between the first two fences, or `None` when the file opens with no fence.

    **Only when the file opens with one.** A file that does not has no frontmatter at all, so it
    sets no `tools:` and inherits everything; parsing between two horizontal rules in its body would
    be reading prose as YAML.

    A block that opens and is never closed is read to the end of the file. The file claims
    frontmatter, a `tools:` in it is a grant that has to be read, and there is no closing fence to
    tell the block from the body — so the alternative is to stay silent about an agent whose grant
    might well exclude everything, which is the more expensive of the two mistakes here.
    """
    lines = text.lstrip(_BOM).splitlines()
    if not lines or lines[0].strip() != _FENCE:
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FENCE:
            return lines[1:index]
    return lines[1:]


def _granted_tools(block: Sequence[str]) -> tuple[str, ...] | None:
    """Every entry of the block's `tools:` key, or `None` when it sets none.

    The key is recognised **unindented only**, so a `tools:` nested under some other key is not read
    as this one.
    """
    for index, line in enumerate(block):
        key, separator, value = line.partition(":")
        # `rstrip` and not `strip`: YAML accepts `tools :` with a space before the colon, and a scan
        # that missed it would read the file as setting no list at all — the silent direction.
        # Leading whitespace still disqualifies the key, which keeps a nested `tools:` out.
        if separator != ":" or key.rstrip() != _TOOLS_KEY:
            continue
        # The comment is stripped first, so `tools:  # the list` reads as the *empty* inline form
        # and the block list below it is still found. Left in, that comment is a non-empty inline
        # value and the list is never read at all — an agent with a good grant, named blind.
        inline = _without_comment(value)
        return _inline_entries(inline) if inline else _block_entries(block[index + 1 :])
    return None


def _inline_entries(value: str) -> tuple[str, ...]:
    """A comma-separated list, or a YAML flow sequence, as its entries.

    **Unquoted before the brackets are stripped, and the brackets before the split.** Each order is
    load-bearing, and each mistake names an agent that is fine: `tools: "Read, mcp__zikaron"` split
    first yields `mcp__zikaron"` with the quote attached, and `[Read, mcp__zikaron]` split before
    the brackets come off yields `[Read` and `mcp__zikaron]`. Neither matches either form.
    """
    value = _unquoted(value)
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return tuple(entry for entry in (_unquoted(part) for part in value.split(",")) if entry)


def _block_entries(rest: Sequence[str]) -> tuple[str, ...]:
    """A YAML block list's items, ending at the block's next unindented key.

    A comment-only line is skipped rather than ending the list: at column zero it satisfies the
    break test below and would truncate the entries after it, dropping a grant that is there.
    """
    entries: list[str] = []
    for line in rest:
        stripped = line.strip()
        if not stripped or stripped.startswith(_COMMENT):
            continue
        if not line[:1].isspace() and not stripped.startswith("-"):
            break
        if stripped.startswith("-"):
            entries.append(_unquoted(_without_comment(stripped[1:])))
    return tuple(entry for entry in entries if entry)


def _without_comment(value: str) -> str:
    """`value` with a trailing `#` comment removed, and stripped.

    Only a `#` that opens the line or follows whitespace starts a comment, and one inside quotes
    never does. That is YAML's own rule, followed rather than approximated: the looser test — any
    `#` at all — would cut a value in half instead of stripping a comment from it.
    """
    quote: str | None = None
    for index, character in enumerate(value):
        if quote is not None:
            if character == quote:
                quote = None
        elif character in ("'", '"'):
            quote = character
        elif character == _COMMENT and (index == 0 or value[index - 1].isspace()):
            return value[:index].strip()
    return value.strip()


def _unquoted(value: str) -> str:
    """One entry with its surrounding whitespace and any matching quotes removed."""
    stripped = value.strip()
    for quote in ("'", '"'):
        # `stripped != quote` rules out a lone quote character, where the start and end tests both
        # pass on the same one and the slice below would empty the entry.
        if stripped != quote and stripped.startswith(quote) and stripped.endswith(quote):
            return stripped[1:-1].strip()
    return stripped


def _reaches_zikaron(entries: Iterable[str]) -> bool:
    return any(entry == GRANT or entry.startswith(_GRANT_PREFIX) for entry in entries)
