"""The guards' prompt texts are memory-reviewer's wording, verbatim (`design/edit-guards.md` §5).

`reviews/m37-edit-guards-review.md` §"Prompt texts" is where that wording was written. Each of its
subsections holds the text in its first fenced block, which this test reads and compares with the
constant that ships it — so a constant edited without the review file, or the reverse, fails.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from zikaron.guard import messages
from zikaron.guard.forms import Form
from zikaron.guard.start_text import GUARD_START_TEXT
from zikaron.harness.spec import CLAUDE_CODE
from zikaron.hook.write_policy import SUBAGENT_WRITE_POLICY_PROMPT, WRITE_POLICY_PROMPT

REVIEW: Final = Path(__file__).resolve().parent.parent / "reviews" / "m37-edit-guards-review.md"
ACKNOWLEDGED: Final = "#ZIKARON-FORCE accepted by Zikaron's find-replace guard"


def _prompt_texts() -> tuple[dict[str, list[str]], list[str]]:
    """Each `### ` subsection of §"Prompt texts", mapped to its fenced blocks in order, and the
    section's lines outside every fence. Headings are read outside fences only: the start text
    itself opens with a `## ` line."""
    blocks: dict[str, list[str]] = {}
    prose: list[str] = []
    in_section = False
    subsection: list[str] | None = None
    fence: list[str] | None = None
    for line in REVIEW.read_text(encoding="utf-8").splitlines():
        if fence is not None:
            if line == "```":
                if subsection is not None:
                    subsection.append("\n".join(fence))
                fence = None
            else:
                fence.append(line)
        elif line.startswith("```"):
            fence = []
        elif line.startswith("## "):
            in_section = line.startswith("## Prompt texts")
            subsection = None
        elif in_section and line.startswith("### "):
            subsection = blocks.setdefault(line.removeprefix("### ").strip(), [])
        elif in_section:
            prose.append(line)
    return blocks, prose


TEXTS, SECTION_PROSE = _prompt_texts()


def _blocks(prefix: str) -> list[str]:
    (heading,) = [heading for heading in TEXTS if heading.startswith(prefix)]
    return TEXTS[heading]


def test_the_start_text_is_the_reviewers() -> None:
    assert _blocks("1.")[0] == GUARD_START_TEXT


def test_the_deny_message_its_no_target_clause_and_its_placement_clause_are_the_reviewers() -> None:
    template, no_target, placement = _blocks("2.")
    assert template == messages.DENY_TEMPLATE
    assert no_target == f"it names {messages.NO_TARGET}"
    assert placement == messages.PLACEMENT_CLAUSE


def test_the_invalid_marker_message_is_the_reviewers() -> None:
    assert _blocks("3.")[0] == messages.INVALID_MARKER_TEMPLATE


def test_the_acknowledgement_is_the_reviewers() -> None:
    assert _blocks("4.")[0] == messages.ACKNOWLEDGEMENT_TEMPLATE
    assert messages.acknowledgement("bulk fix", ()).startswith(ACKNOWLEDGED)


def test_the_nudge_is_the_reviewers() -> None:
    with_ranges, without = _blocks("5.")
    assert with_ranges == messages.NUDGE_WITH_RANGES_TEMPLATE
    assert without == messages.NUDGE_TEMPLATE


def test_the_form_labels_are_the_reviewers() -> None:
    labels = dict(re.findall(r"^\| (\d) \| `([^`]+)` \|$", "\n".join(SECTION_PROSE), re.MULTILINE))
    assert {Form(int(row)): label for row, label in labels.items()} == messages.FORM_LABELS


@pytest.mark.parametrize(
    "text",
    [
        messages.DENY_TEMPLATE,
        messages.INVALID_MARKER_TEMPLATE,
        messages.PLACEMENT_CLAUSE,
        messages.ACKNOWLEDGEMENT_TEMPLATE,
        messages.NUDGE_WITH_RANGES_TEMPLATE,
        messages.NUDGE_TEMPLATE,
    ],
)
def test_each_hook_message_is_one_ascii_line(text: str) -> None:
    assert text.isascii()
    assert "\n" not in text


def test_the_start_text_never_mentions_the_override() -> None:
    assert "ZIKARON-FORCE" not in GUARD_START_TEXT
    assert "Reason" not in GUARD_START_TEXT


@pytest.mark.parametrize("policy", [WRITE_POLICY_PROMPT, SUBAGENT_WRITE_POLICY_PROMPT])
def test_the_policy_and_the_start_text_together_fit_the_injection_budget(policy: str) -> None:
    assert not CLAUDE_CODE.exceeds_injection_budget(f"{policy}\n\n{GUARD_START_TEXT}")


def test_the_nudge_template_is_the_length_the_design_states() -> None:
    template = messages.NUDGE_WITH_RANGES_TEMPLATE
    fixed = len(template) - len("{path}") - len("{ranges}")
    assert fixed == 218
