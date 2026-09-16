"""Every tool description carries the decision mechanics `architecture.md` requires sitting in
context at the point of decision (D30), asserted directly against the generated `tools/list`
description text rather than only against the source docstring — a description is what a calling
model actually sees, and the two can diverge if a future edit changes one without the other.
"""

from pathlib import Path

import pytest
from fastmcp import Client

from tests.design_tables import block_quote
from zikaron.mcp.server import build_server

DOCUMENT = "knowledge-index.md"
HEADING = "## 8. The MCP interface"


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


#: The one paragraph the shipped description is licensed to state differently from the design's
#: quote of it: the design tells a caller to list the corpora first, and the tool that would do
#: that is not built yet, so the shipped text says how to search all of them instead.
_LICENSED_SUBSTITUTION = 1


async def test_zikaron_knowledge_search_matches_the_design_document(tmp_path: Path) -> None:
    """The shipped description and the design's quote of it agree paragraph by paragraph, except
    for the one paragraph the design itself licenses a substitution in.

    Parsed from the document at test time rather than compared against a second hand-typed copy,
    because the two have already drifted once: the shipped text was corrected in three places and
    the quote kept asserting the pre-fix wording. A description is prose about a live artifact, and
    prose asserting what the adjacent code contradicts is the defect class this repository catches
    most often — so the check is mechanical rather than a reading.
    """
    shipped = _paragraphs(await _description_of("primary", "zikaron_knowledge_search", tmp_path))
    designed = _paragraphs(
        block_quote(DOCUMENT, HEADING, "Search indexed project documents by relevance.")
    )
    assert len(shipped) == len(designed)
    for index, (one, other) in enumerate(zip(shipped, designed, strict=True)):
        if index == _LICENSED_SUBSTITUTION:
            continue
        assert one == other


@pytest.mark.parametrize(
    "required_phrase",
    [
        "Omit `knowledge_bases` to search every corpus",
        "clamped rather than refused",
    ],
)
async def test_the_substituted_paragraph_still_carries_what_it_substitutes_for(
    tmp_path: Path, required_phrase: str
) -> None:
    """The exempted paragraph is the one place nothing else would notice an edit.

    Two things live only here, and each is load-bearing somewhere else. Telling a caller to omit the
    names is what replaces the instruction to list the corpora first — the tool that would do the
    listing does not exist, so without this sentence a caller has no stated way to discover what it
    can search. And the clamp sentence is the whole justification for not reporting the effective
    limit back on the response: that decision rests on the number being stated where a caller reads
    it before choosing one. Both would otherwise be droppable with nothing going red.
    """
    description = await _description_of("primary", "zikaron_knowledge_search", tmp_path)
    assert required_phrase in _paragraphs(description)[_LICENSED_SUBSTITUTION]


async def test_the_licensed_substitution_is_the_only_paragraph_that_differs(
    tmp_path: Path,
) -> None:
    """The exemption above is narrow, so it is pinned from the other side as well.

    Without this, a substitution paragraph that came to match the document would leave the guard
    exempting a paragraph that needs no exemption — and the next real divergence could land there
    unnoticed. The design's version names the listing tool; the shipped one must not.
    """
    shipped = _paragraphs(await _description_of("primary", "zikaron_knowledge_search", tmp_path))
    designed = _paragraphs(
        block_quote(DOCUMENT, HEADING, "Search indexed project documents by relevance.")
    )
    assert shipped[_LICENSED_SUBSTITUTION] != designed[_LICENSED_SUBSTITUTION]
    assert "zikaron_knowledge_list" in designed[_LICENSED_SUBSTITUTION]


async def test_zikaron_knowledge_search_names_no_tool_this_build_does_not_have(
    tmp_path: Path,
) -> None:
    """A description that points a model at a tool it cannot call is a measured defect in the
    nearest comparable product — a success message naming a command that no longer exists — and
    the management tools this one would naturally refer to do not exist yet."""
    description = await _description_of("primary", "zikaron_knowledge_search", tmp_path)
    mcp = build_server("primary", scope_dir=tmp_path)
    async with Client(mcp) as client:
        registered = {tool.name for tool in await client.list_tools()}
    named = {word.strip("`.,:") for word in description.split() if "zikaron_" in word}
    assert named <= registered
