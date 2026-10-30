"""The guards' prompt texts are memory-reviewer's wording, verbatim (`design/guards.md` §5).

`reviews/m37-edit-guards-review.md` §"Prompt texts" is where Claude Code's wording was written,
`reviews/m38-selfmatch-guard-review.md` §"Prompt texts" for the self-match rule's deny, and
`reviews/m41-2-review.md` §"Prompt texts — kiro" for kiro's. Each subsection holds its texts in
fenced blocks, which this test reads and compares with the texts each harness ships — so a template
edited without the review file, or the reverse, fails.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from zikaron.guard import messages
from zikaron.guard.forms import Form, FormMatch, Target
from zikaron.guard.selfmatch import Platform, SelfMatch
from zikaron.guard.start_text import guard_start_text
from zikaron.harness.spec import CLAUDE_CODE, KIRO, HarnessSpec, ToolIds
from zikaron.hook.write_policy import SUBAGENT_WRITE_POLICY_PROMPT, WRITE_POLICY_PROMPT

REVIEWS: Final = Path(__file__).resolve().parent.parent / "reviews"
REVIEW: Final = REVIEWS / "m37-edit-guards-review.md"
SELF_MATCH_REVIEW: Final = REVIEWS / "m38-selfmatch-guard-review.md"
KIRO_REVIEW: Final = REVIEWS / "m41-2-review.md"
ACKNOWLEDGED: Final = "#ZIKARON-FORCE accepted by Zikaron's find-replace guard"
GUARD_START_TEXT: Final = guard_start_text(CLAUDE_CODE)

#: A spec whose tools and name are no harness's, so a text that renders one of kiro's or Claude
#: Code's names under it wrote that name as a literal.
_STRANGER: Final = KIRO._replace(
    prose_name="Stranger", tool_ids=ToolIds("open_it", "patch_it", "put_it", "run_it")
)


def _prompt_texts(review: Path) -> tuple[dict[str, list[str]], list[str]]:
    """Each `### ` subsection of `review`'s §"Prompt texts", mapped to its fenced blocks in order,
    and the section's lines outside every fence. Headings are read outside fences only: the start
    text itself opens with a `## ` line."""
    blocks: dict[str, list[str]] = {}
    prose: list[str] = []
    in_section = False
    subsection: list[str] | None = None
    fence: list[str] | None = None
    for line in review.read_text(encoding="utf-8").splitlines():
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


TEXTS, SECTION_PROSE = _prompt_texts(REVIEW)
SELF_MATCH_TEXTS, _ = _prompt_texts(SELF_MATCH_REVIEW)
KIRO_TEXTS, KIRO_SECTION_PROSE = _prompt_texts(KIRO_REVIEW)


def _blocks(prefix: str, texts: dict[str, list[str]] = TEXTS) -> list[str]:
    (heading,) = [heading for heading in texts if heading.startswith(prefix)]
    return texts[heading]


def _with(template: str, spec: HarnessSpec) -> str:
    return messages.with_harness(template, spec)


def _unacknowledged(template: str) -> str:
    """A find-replace deny as a harness that acknowledges no override renders it."""
    return f"{_with(template, KIRO)} {messages.UNACKNOWLEDGED_CLAUSE}"


def test_the_self_match_deny_and_its_fixes_are_the_reviewers() -> None:
    template, linux, darwin = _blocks("1.", SELF_MATCH_TEXTS)
    assert template == _with(messages.SELF_MATCH_TEMPLATE, CLAUDE_CODE)
    assert {Platform.LINUX: linux, Platform.DARWIN: darwin} == messages.SELF_MATCH_FIXES


def test_kiros_self_match_deny_and_its_fixes_are_the_reviewers() -> None:
    template, linux, darwin = _blocks("4.", KIRO_TEXTS)
    assert template == _with(messages.SELF_MATCH_TEMPLATE, KIRO)
    assert {Platform.LINUX: linux, Platform.DARWIN: darwin} == messages.SELF_MATCH_FIXES


@pytest.mark.parametrize(
    ("spec", "texts"), [(CLAUDE_CODE, TEXTS), (KIRO, KIRO_TEXTS)], ids=["claude-code", "kiro"]
)
def test_the_start_text_is_the_reviewers(spec: HarnessSpec, texts: dict[str, list[str]]) -> None:
    assert _blocks("1.", texts)[0] == guard_start_text(spec)


def test_the_start_text_asks_for_the_re_read_only_where_a_reminder_follows_an_edit() -> None:
    """kiro has no re-read hook, since no post-tool output reaches its model."""
    sentence = "After each edit, a reminder from this project's hooks"
    assert sentence in " ".join(guard_start_text(CLAUDE_CODE).split())
    assert sentence not in " ".join(guard_start_text(KIRO).split())
    assert "re-read" not in guard_start_text(KIRO)


def test_the_deny_message_its_no_target_clause_and_its_placement_clause_are_the_reviewers() -> None:
    template, no_target, placement = _blocks("2.")
    assert template == _with(messages.DENY_TEMPLATE, CLAUDE_CODE)
    assert no_target == f"it names {messages.NO_TARGET}"
    assert placement == messages.PLACEMENT_CLAUSE


def test_kiros_deny_message_its_no_target_clause_and_its_placement_clause_are_the_reviewers() -> (
    None
):
    template, no_target, placement = _blocks("2.", KIRO_TEXTS)
    assert template == _unacknowledged(messages.DENY_TEMPLATE)
    assert no_target == f"it names {messages.NO_TARGET}"
    assert placement == messages.PLACEMENT_CLAUSE


def test_the_invalid_marker_message_is_the_reviewers() -> None:
    assert _blocks("3.")[0] == _with(messages.INVALID_MARKER_TEMPLATE, CLAUDE_CODE)
    assert _blocks("3.", KIRO_TEXTS)[0] == _unacknowledged(messages.INVALID_MARKER_TEMPLATE)


def test_the_acknowledgement_is_the_reviewers() -> None:
    assert _blocks("4.")[0] == _with(messages.ACKNOWLEDGEMENT_TEMPLATE, CLAUDE_CODE)
    assert messages.acknowledgement("bulk fix", ()).startswith(ACKNOWLEDGED)


def test_the_nudge_is_the_reviewers() -> None:
    with_ranges, without = _blocks("5.")
    assert with_ranges == messages.NUDGE_WITH_RANGES_TEMPLATE
    assert without == messages.NUDGE_TEMPLATE


@pytest.mark.parametrize("prose", [SECTION_PROSE, KIRO_SECTION_PROSE], ids=["claude-code", "kiro"])
def test_the_form_labels_are_the_reviewers(prose: list[str]) -> None:
    labels = dict(re.findall(r"^\| (\d) \| `([^`]+)` \|$", "\n".join(prose), re.MULTILINE))
    assert {Form(int(row)): label for row, label in labels.items()} == messages.FORM_LABELS


class TestTheReReadAskOnTheDeny:
    """Where an accepted override is not acknowledged, the find-replace guard's denies carry the
    re-read the acknowledgement asks for elsewhere; the self-match deny edits nothing."""

    _MATCH: Final = FormMatch(Form.SED_IN_PLACE, "sed", (Target("/home/u/proj/f", False),))
    _SELF: Final = SelfMatch(word="pkill", platform=Platform.LINUX, excerpt="pkill -f x")

    @pytest.mark.parametrize("invalid_marker", [False, True])
    def test_kiros_find_replace_denies_end_with_it(self, invalid_marker: bool) -> None:
        kiro = messages.deny_message(
            self._MATCH, invalid_marker=invalid_marker, marker_in_content=False, spec=KIRO
        )
        claude = messages.deny_message(
            self._MATCH, invalid_marker=invalid_marker, marker_in_content=False, spec=CLAUDE_CODE
        )
        assert kiro.endswith(messages.UNACKNOWLEDGED_CLAUSE)
        assert messages.UNACKNOWLEDGED_CLAUSE not in claude

    def test_the_placement_clause_follows_it(self) -> None:
        kiro = messages.deny_message(
            self._MATCH, invalid_marker=False, marker_in_content=True, spec=KIRO
        )
        assert kiro.endswith(f"{messages.UNACKNOWLEDGED_CLAUSE} {messages.PLACEMENT_CLAUSE}")

    def test_the_self_match_deny_does_not_carry_it(self) -> None:
        kiro = messages.deny_message(
            self._SELF, invalid_marker=False, marker_in_content=False, spec=KIRO
        )
        assert messages.UNACKNOWLEDGED_CLAUSE not in kiro
        assert "because kiro-cli runs each command inside a shell" in kiro


class TestEveryTextNamesItsToolsFromTheSpec:
    """A kiro or Claude Code name written as a literal in a template shows when the template is
    rendered for a harness whose names are neither's."""

    _THEIR_NAMES: Final = (
        *KIRO.tool_ids,
        *CLAUDE_CODE.tool_ids,
        KIRO.prose_name,
        CLAUDE_CODE.prose_name,
    )

    @pytest.mark.parametrize(
        "template",
        [
            messages.DENY_TEMPLATE,
            messages.INVALID_MARKER_TEMPLATE,
            messages.SELF_MATCH_TEMPLATE,
            messages.ACKNOWLEDGEMENT_TEMPLATE,
            messages.UNACKNOWLEDGED_CLAUSE,
        ],
    )
    def test_a_message(self, template: str) -> None:
        rendered = _with(template, _STRANGER)
        for name in self._THEIR_NAMES:
            assert not re.search(rf"\b{re.escape(name)}\b", rendered), name

    @pytest.mark.parametrize("harness", [KIRO, CLAUDE_CODE], ids=["kiro", "claude-code"])
    def test_the_start_text(self, harness: HarnessSpec) -> None:
        rendered = guard_start_text(_STRANGER._replace(harness=harness.harness))
        for name in self._THEIR_NAMES:
            assert not re.search(rf"\b{re.escape(name)}\b", rendered), name
        for name in _STRANGER.tool_ids:
            assert name in rendered


@pytest.mark.parametrize(
    "text",
    [
        messages.DENY_TEMPLATE,
        messages.INVALID_MARKER_TEMPLATE,
        messages.PLACEMENT_CLAUSE,
        messages.ACKNOWLEDGEMENT_TEMPLATE,
        messages.NUDGE_WITH_RANGES_TEMPLATE,
        messages.NUDGE_TEMPLATE,
        messages.SELF_MATCH_TEMPLATE,
        messages.UNACKNOWLEDGED_CLAUSE,
        *messages.SELF_MATCH_FIXES.values(),
    ],
)
def test_each_hook_message_is_one_ascii_line(text: str) -> None:
    assert text.isascii()
    assert "\n" not in text


def test_the_self_match_texts_hold_no_brace_but_their_placeholders() -> None:
    """`str.format` fills them, and the excerpt it fills in may hold any character; the harness's
    name is filled first."""
    expected = {"word", "excerpt", "fix", "harness"}
    assert set(re.findall(r"\{(\w*)\}", messages.SELF_MATCH_TEMPLATE)) == expected
    stripped = re.sub(r"\{(word|excerpt|fix|harness)\}", "", messages.SELF_MATCH_TEMPLATE)
    for text in (stripped, *messages.SELF_MATCH_FIXES.values()):
        assert "{" not in text
        assert "}" not in text


@pytest.mark.parametrize("spec", [CLAUDE_CODE, KIRO], ids=["claude-code", "kiro"])
def test_the_start_text_never_mentions_the_override(spec: HarnessSpec) -> None:
    assert "ZIKARON-FORCE" not in guard_start_text(spec)
    assert "Reason" not in guard_start_text(spec)


@pytest.mark.parametrize("policy", [WRITE_POLICY_PROMPT, SUBAGENT_WRITE_POLICY_PROMPT])
def test_the_policy_and_the_start_text_together_fit_the_injection_budget(policy: str) -> None:
    assert not CLAUDE_CODE.exceeds_injection_budget(f"{policy}\n\n{GUARD_START_TEXT}")


def test_the_nudge_template_is_the_length_the_design_states() -> None:
    template = messages.NUDGE_WITH_RANGES_TEMPLATE
    fixed = len(template) - len("{path}") - len("{ranges}")
    assert fixed == 218
