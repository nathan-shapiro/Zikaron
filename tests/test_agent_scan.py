"""Which Claude Code subagents the install and `doctor` name as unable to see Zikaron.

`design/harness.md` §"What the install reports rather than enforces" is normative. The case cost an
hour to diagnose in a real project: everything Zikaron writes was correct — schema 2, a warm
service, ten `surface_call` events proving the hook pushed, twelve tools registered against the
right scope — and the store held zero memories, because one subagent's frontmatter set its own
`tools:` list and an explicit list **overrides** the project-wide MCP registration.

**Every direction is a fixture here, because a mis-parse fails in the two directions that cost the
most**: naming an agent that is fine, or staying silent about the one that is broken.
"""

from pathlib import Path

import pytest

from zikaron.install import agent_scan
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    MCP_SERVER_NAME,
    Commands,
    consolidator_agent_markdown,
)

_COMMANDS = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))

#: Spelled by code point rather than written into the literals below, where it is invisible. Stated
#: here rather than imported from the module, so these cases drive the byte an editor writes instead
#: of whatever the module believes it is.
_BOM = chr(0xFEFF)


def _agent(project: Path, name: str, body: str) -> Path:
    directory = agent_scan.agents_directory(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    return path


def _relative(project: Path, name: str) -> str:
    return str(agent_scan.agents_directory(project).relative_to(project) / f"{name}.md")


#: The shape found in the field: an allowlist authored before Zikaron existed, naming ordinary tools
#: and no `mcp__*` at all — so the agent cannot see a single memory verb and nothing said so.
_BLIND_BLOCK_LIST = """---
name: income-quant
description: Maintains the dividend model's persistent state files.
tools:
  - Read
  - Write
  - Bash
---

You are the income quant.
"""


@pytest.mark.parametrize(
    ("body", "named"),
    [
        pytest.param(_BLIND_BLOCK_LIST, True, id="a block list with no mcp entry"),
        pytest.param(
            "---\ntools: Read, Write, Bash\n---\n\nprose\n",
            True,
            id="the inline spelling of the same list",
        ),
        pytest.param(
            "---\ntools: [Read, Write, Bash]\n---\n\nprose\n",
            True,
            id="the flow-sequence spelling of the same list",
        ),
        pytest.param(
            f"---\ntools:\n  - Read\n  - mcp__{CONSOLIDATOR_AGENT_NAME}\n---\n\nprose\n",
            True,
            id="only the consolidator's grant, which is a prefix of nothing it can use",
        ),
        pytest.param(
            f"---\ntools: Read, mcp__{CONSOLIDATOR_AGENT_NAME}__memory_next_group\n---\n\nprose\n",
            True,
            id="only a consolidator tool, which `startswith` would have passed",
        ),
        pytest.param(
            f"---\ntools:\n  - Read\n  - mcp__{MCP_SERVER_NAME}\n---\n\nprose\n",
            False,
            id="the whole-server grant, as a block list",
        ),
        pytest.param(
            f"---\ntools: Read, mcp__{MCP_SERVER_NAME}\n---\n\nprose\n",
            False,
            id="the whole-server grant, inline",
        ),
        pytest.param(
            f"---\ntools: [Read, mcp__{MCP_SERVER_NAME}]\n---\n\nprose\n",
            False,
            id="the whole-server grant, as a flow sequence",
        ),
        pytest.param(
            f"---\ntools:\n  - mcp__{MCP_SERVER_NAME}__memory_remember\n---\n\nprose\n",
            False,
            id="one memory verb, which the `__` prefix admits",
        ),
        pytest.param(
            f'---\ntools:\n  - "mcp__{MCP_SERVER_NAME}"\n---\n\nprose\n',
            False,
            id="the grant in quotes, which YAML permits",
        ),
        pytest.param(
            f"---\ntools:\n  - Read\n  not-a-list-item\n  - mcp__{MCP_SERVER_NAME}\n---\n\nprose\n",
            False,
            id="an indented line that is not a list item, which must neither grant nor terminate",
        ),
        pytest.param(
            "---\nname: inheriting\ndescription: sets no tools list\n---\n\nprose\n",
            False,
            id="no tools key at all, so nothing overrides the registration",
        ),
        pytest.param(
            "# An agent with no frontmatter\n\ntools:\n  - Read\n\n---\n\nprose\n",
            False,
            id="a file opening with no fence, whose body is prose rather than YAML",
        ),
        pytest.param(
            "---\nname: nested\nmcp:\n  tools:\n    - Read\n---\n\nprose\n",
            False,
            id="a `tools:` nested under another key, which is not this one",
        ),
        pytest.param(
            "---\ntools:\nmodel: sonnet\n---\n\nprose\n",
            True,
            id="a tools key with no entries, which grants nothing at all",
        ),
        pytest.param(
            "---\ntools: []\n---\n\nprose\n",
            True,
            id="the same, spelled as an empty flow sequence",
        ),
        # Four spellings Claude Code accepts that a careless parser names blind, each in the
        # false-positive direction this module's docstring calls the expensive one.
        pytest.param(
            f"---\ntools:  # what it may use\n  - Read\n  - mcp__{MCP_SERVER_NAME}\n---\n\nprose\n",
            False,
            id="a comment on the tools line, with the list below it",
        ),
        pytest.param(
            f"---\ntools:\n  - Read\n  - mcp__{MCP_SERVER_NAME}  # the verbs\n---\n\nprose\n",
            False,
            id="a comment after the entry that carries the grant",
        ),
        pytest.param(
            f'---\ntools: "Read, mcp__{MCP_SERVER_NAME}"\n---\n\nprose\n',
            False,
            id="the whole inline value quoted, which YAML permits",
        ),
        pytest.param(
            f"---\ntools:\n  - Read\n# a note at column zero\n  - mcp__{MCP_SERVER_NAME}\n---\n"
            "\nprose\n",
            False,
            id="a column-zero comment inside the list, which must not truncate it",
        ),
        pytest.param(
            f"---\ntools :\n  - mcp__{MCP_SERVER_NAME}\n---\n\nprose\n",
            False,
            id="a space before the colon, which YAML accepts and a scan must not read as no list",
        ),
        pytest.param(
            "---\ntools :\n  - Read\n---\n\nprose\n",
            True,
            id="the same spacing with a blind list, so the key is still recognised",
        ),
        pytest.param(
            f"{_BOM}---\ntools:\n  - mcp__{MCP_SERVER_NAME}\n---\n\nprose\n",
            False,
            id="a byte-order mark before the fence, which several editors write",
        ),
        pytest.param(
            f"{_BOM}---\ntools:\n  - Read\n---\n\nprose\n",
            True,
            id="the same file with a blind list, so the BOM does not silence the scan",
        ),
    ],
)
def test_which_agents_are_named(tmp_path: Path, body: str, named: bool) -> None:
    _agent(tmp_path, "subject", body)
    assert agent_scan.blind_agents(tmp_path) == ((_relative(tmp_path, "subject"),) if named else ())


def test_the_installer_s_own_agent_is_skipped(tmp_path: Path) -> None:
    """Its narrow grant is D32 working, so a scan that did not skip it would name Zikaron's own
    artefact as unable to see Zikaron — on every install, in the false-positive direction.

    **Rendered through the installer's own function rather than hand-typed**, per `CLAUDE.md`
    §Harness: a transcription would keep passing on the day the shipped frontmatter changed shape.
    """
    shipped = consolidator_agent_markdown(_COMMANDS, model="sonnet")
    _agent(tmp_path, CONSOLIDATOR_AGENT_NAME, shipped)
    assert agent_scan.blind_agents(tmp_path) == ()


def test_another_agent_holding_only_the_consolidator_s_grant_is_still_named(tmp_path: Path) -> None:
    """The skip is by filename, not by content: that grant belongs to the consolidator alone."""
    shipped = consolidator_agent_markdown(_COMMANDS, model="sonnet")
    _agent(tmp_path, "impostor", shipped)
    assert agent_scan.blind_agents(tmp_path) == (_relative(tmp_path, "impostor"),)


def test_no_agents_directory_is_a_different_answer_from_nobody_named(tmp_path: Path) -> None:
    """`None` against `()`: a report whose row is absent says the question was not asked, and one
    saying `none` says it was asked and answered."""
    assert agent_scan.blind_agents(tmp_path) is None
    agent_scan.agents_directory(tmp_path).mkdir(parents=True)
    assert agent_scan.blind_agents(tmp_path) == ()


def test_every_named_agent_is_reported_and_the_order_is_stable(tmp_path: Path) -> None:
    """Sorted, because an install that named the same three agents in a different order each run
    would read as something having changed."""
    for name in ("charlie", "alpha", "bravo"):
        _agent(tmp_path, name, _BLIND_BLOCK_LIST)
    assert agent_scan.blind_agents(tmp_path) == tuple(
        _relative(tmp_path, name) for name in ("alpha", "bravo", "charlie")
    )


def test_an_unreadable_agent_file_is_not_reported_as_blind(tmp_path: Path) -> None:
    """This is an advisory line inside a command whose work is already done: undecodable bytes in
    somebody else's agent file are not something to fail an install over, nor evidence either."""
    _agent(tmp_path, "sound", f"---\ntools: mcp__{MCP_SERVER_NAME}\n---\n\nprose\n")
    (agent_scan.agents_directory(tmp_path) / "binary.md").write_bytes(
        b"---\ntools: \xff\xfe\n---\n"
    )
    assert agent_scan.blind_agents(tmp_path) == ()


def test_a_frontmatter_block_that_is_never_closed_is_still_read(tmp_path: Path) -> None:
    """The file claims frontmatter, and there is no closing fence to tell the block from the body.

    Read to the end rather than treated as having none, because the alternative is silence about an
    agent whose grant may well exclude everything — the more expensive of the two mistakes here.
    """
    _agent(tmp_path, "unterminated", "---\nname: unterminated\ntools:\n  - Read\n\nprose\n")
    assert agent_scan.blind_agents(tmp_path) == (_relative(tmp_path, "unterminated"),)


def test_the_grant_the_advice_names_is_the_one_the_predicate_accepts(tmp_path: Path) -> None:
    """One constant for what is checked and what is advised. Two spellings would let the install
    tell a user to add an entry its own scan does not accept."""
    _agent(tmp_path, "subject", f"---\ntools: {agent_scan.GRANT}\n---\n\nprose\n")
    assert agent_scan.blind_agents(tmp_path) == ()
    assert f"mcp__{MCP_SERVER_NAME}" == agent_scan.GRANT
