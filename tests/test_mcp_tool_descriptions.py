"""Every tool description carries the decision mechanics `architecture.md` requires sitting in
context at the point of decision (D30), asserted directly against the generated `tools/list`
description text rather than only against the source docstring — a description is what a calling
model actually sees, and the two can diverge if a future edit changes one without the other.
"""

import re
from pathlib import Path
from typing import Final

import pytest
from fastmcp import Client

from tests.design_tables import block_quote
from zikaron.mcp.server import build_server

DOCUMENT = "knowledge-index.md"
HEADING = "## 8. The MCP interface"

#: A tool name as it appears in prose. Splitting on whitespace is not enough: a description writes
#: `zikaron_memory_amend`/`zikaron_memory_retire` as one whitespace token, and stripping
#: punctuation off the ends of that leaves a string that is neither name.
_TOOL_TOKEN: Final = re.compile(r"\bzikaron_[a-z_]+\b")


async def _description_of(mode: str, tool_name: str, tmp_path: Path) -> str:
    mcp = build_server(mode, scope_dir=tmp_path)  # type: ignore[arg-type]
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
async def test_zikaron_memory_retire_describes_the_supersession_graph_rules(
    tmp_path: Path, required_phrase: str
) -> None:
    """`architecture.md` §"zikaron_memory_retire": `superseded_by` must satisfy schema.md
    invariant 6 —
    "no self-edge, no cycle, target not already retired-outright" — and a model that does not know
    these rules in advance would only discover them by trying an illegal edge and reading the
    rejection; stating them in the tool's own description lets it avoid an avoidable one."""
    description = await _description_of("primary", "zikaron_memory_retire", tmp_path)
    assert required_phrase in description


@pytest.mark.parametrize(
    ("tool", "other"),
    [
        ("zikaron_memory_search", "zikaron_knowledge_search"),
        ("zikaron_knowledge_search", "zikaron_memory_search"),
    ],
)
async def test_each_search_tool_names_the_other_store_s_search(
    tmp_path: Path, tool: str, other: str
) -> None:
    """One server carries two searches over two stores — what agents recorded here, and what the
    project itself wrote down — and nothing in either name says which is which. A model that knows
    only the one it was given searches the wrong store and reads the empty answer as *there is
    nothing*, which is the failure both halves of this pairing exist to prevent. Stated on both,
    because whichever one the model reaches for first has to be the one that redirects it."""
    description = await _description_of("primary", tool, tmp_path)
    assert other in description


@pytest.mark.parametrize(
    "required_phrase",
    [
        "1-based",
        "including this delivery",
        "excludes",
    ],
)
async def test_zikaron_memory_next_group_describes_shard_serve_count_and_remaining_groups(
    tmp_path: Path, required_phrase: str
) -> None:
    """`architecture.md` §"zikaron_memory_next_group": `shard` is 1-based, `serve_count` includes
    the
    current delivery, and `remaining_groups` excludes the group just delivered — each of the
    three is easy to get backwards without being told, and a consolidator that assumed 0-based
    sharding or an inclusive `remaining_groups` would misjudge whether it is looking at a re-serve
    or the last group of a run."""
    description = await _description_of("consolidator", "zikaron_memory_next_group", tmp_path)
    assert required_phrase in description


@pytest.mark.parametrize(
    "required_phrase",
    [
        "about to propose a design",
        "not comparable between corpora",
        "was searched and had nothing",
        "copied verbatim",
        "no evidence of change, not a guarantee",
        "not instructions",
    ],
)
async def test_zikaron_knowledge_search_describes_its_occasions_and_its_caveats(
    tmp_path: Path, required_phrase: str
) -> None:
    """Six things a model cannot infer from the signature, and each of them changes what it does
    with the answer: when to reach for the tool at all; that group order is approximate, so the
    third group may hold the better result; that an empty group is a real answer rather than a
    failure; that a snippet may be quoted as-is; that `stale: false` is the absence of evidence
    rather than a guarantee; and that a snippet is quoted text rather than something to obey.

    The comparison this is against is measured rather than assumed: the nearest product's own
    knowledge tool ships a 25-word description that states what the tool *is* and never when to
    reach for it, with no system-prompt integration anywhere, leaving the human as the trigger."""
    description = await _description_of("primary", "zikaron_knowledge_search", tmp_path)
    assert required_phrase in description


def _paragraphs(text: str) -> list[str]:
    """One prose block per paragraph, with every run of whitespace flattened to one space.

    Line wrapping differs between a docstring indented inside a function and a block quote in a
    markdown file, and neither wrapping reaches the model — the description is delivered as one
    string. Flattening compares the words, which is the thing the two copies are supposed to share.
    """
    return [" ".join(block.split()) for block in text.split("\n\n") if block.strip()]


#: Every knowledge tool whose description the design quotes in full, by the words its quote opens
#: with. Data rather than one test per tool, so a tool added to the design without a shipped
#: description — or shipped without one in the design — is a missing row here rather than a check
#: nobody wrote.
_QUOTED_DESCRIPTIONS = {
    "zikaron_knowledge_search": "Search indexed project documents by relevance.",
    "zikaron_knowledge_list": "List the knowledge bases in this project:",
    "zikaron_knowledge_status": "The detail behind one knowledge base's state,",
    "zikaron_knowledge_add": "Create a knowledge base over a directory of text files",
    "zikaron_knowledge_remove": "Destroy a knowledge base:",
    "zikaron_knowledge_rename": "Change a knowledge base's name.",
    "zikaron_knowledge_refresh": "Bring knowledge bases up to date",
}


@pytest.mark.parametrize(("tool_name", "opening"), sorted(_QUOTED_DESCRIPTIONS.items()))
async def test_every_knowledge_description_matches_the_design_document(
    tmp_path: Path, tool_name: str, opening: str
) -> None:
    """The shipped description and the design's quote of it agree paragraph by paragraph.

    Parsed from the document at test time rather than compared against a second hand-typed copy,
    because the two have already drifted once: the shipped text was corrected in three places and
    the quote kept asserting the pre-fix wording. A description is prose about a live artifact, and
    prose asserting what the adjacent code contradicts is the defect class this repository catches
    most often — so the check is mechanical rather than a reading.

    **There is no longer an exempted paragraph.** One existed while the shipped search description
    had to avoid naming a listing tool that was not registered; that tool exists, so the shipped
    text is the design's own, in full, and an exemption kept past its reason would be a place the
    next real divergence could land unnoticed.
    """
    shipped = _paragraphs(await _description_of("primary", tool_name, tmp_path))
    designed = _paragraphs(block_quote(DOCUMENT, HEADING, opening))
    assert shipped == designed


async def test_every_quoted_description_belongs_to_a_registered_tool(tmp_path: Path) -> None:
    """The table above is only a guard while it names what the server actually serves: a row for a
    tool nobody registers would silently stop checking anything."""
    mcp = build_server("primary", scope_dir=tmp_path)
    async with Client(mcp) as client:
        registered = {tool.name for tool in await client.list_tools()}
    assert set(_QUOTED_DESCRIPTIONS) <= registered


async def test_no_description_names_a_tool_its_own_server_does_not_have(tmp_path: Path) -> None:
    """A description that points a model at a tool it cannot call is a measured defect in the
    nearest comparable product — a success message naming a command that no longer exists and that
    the model could not have invoked anyway.

    Checked over **every** tool on both servers rather than over the one that happened to be at
    risk: these descriptions now refer to one another freely, so a renamed or withdrawn tool would
    leave a dangling pointer in whichever neighbour mentioned it, and which neighbour that is is
    not something a test should have to be told.
    """
    for mode in ("primary", "consolidator"):
        mcp = build_server(mode, scope_dir=tmp_path)
        async with Client(mcp) as client:
            tools = await client.list_tools()
        registered = {tool.name for tool in tools}
        for tool in tools:
            named = set(_TOOL_TOKEN.findall(tool.description or ""))
            assert named <= registered, f"{tool.name} on {mode} names {named - registered}"
