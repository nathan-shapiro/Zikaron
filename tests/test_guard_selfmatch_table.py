"""The self-match rule against every row of `design/guards.md` §9.5, through the hook's I/O.

Each item is judged as §8's are — `cwd` `/home/u/proj`, `$TMPDIR` unset, no file for row 6 to
read — on the row's platform and tool, and asserted on what the hook emits: no output at all for
*silent*, and for a deny, which rule's message, its parts and its appended clauses. The self-match
message is matched against its own template, so the assertions hold whatever its wording is.
"""

import json
import re

import pytest

from tests.guard_table import CWD, SelfMatchCase, SelfMatchExpected, selfmatch_cases
from zikaron.guard import messages
from zikaron.guard.main import respond
from zikaron.guard.selfmatch import Platform

CASES = selfmatch_cases()
FIND_REPLACE_PREFIX = messages.DENY_TEMPLATE.split("{", 1)[0]


def _template_pattern() -> re.Pattern[str]:
    """`SELF_MATCH_TEMPLATE` as a regular expression with one group per placeholder."""
    parts = re.split(r"\{(\w+)\}", messages.SELF_MATCH_TEMPLATE)
    pattern = "".join(
        re.escape(part) if index % 2 == 0 else f"(?P<{part}>.*?)"
        for index, part in enumerate(parts)
    )
    return re.compile(pattern, re.DOTALL)


SELF_MATCH = _template_pattern()


def _emit(case: SelfMatchCase) -> dict[str, object] | None:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": case.tool,
        "cwd": CWD,
        "tool_input": {"command": case.command},
    }
    output = respond(json.dumps(payload), tmpdir=None, platform=case.platform, read=None)
    if output is None:
        return None
    envelope = json.loads(output)["hookSpecificOutput"]
    assert isinstance(envelope, dict)
    return envelope


@pytest.fixture(autouse=True)
def _no_tmpdir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)


def test_section_9_5_yields_items_on_every_platform_and_tool() -> None:
    assert len({case.row for case in CASES}) > 40
    assert {case.platform for case in CASES} == {"linux", "darwin", "win32"}
    assert {case.tool for case in CASES} == {"Bash", "Monitor"}


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_section_9_5_row(case: SelfMatchCase) -> None:
    expected = SelfMatchExpected.of(case.expected)
    envelope = _emit(case)
    if expected.decision == "silent":
        assert envelope is None, case.expected
        return
    assert envelope is not None, case.expected
    assert envelope["permissionDecision"] == "deny"
    reason = envelope["permissionDecisionReason"]
    assert isinstance(reason, str)
    if expected.find_replace:
        assert reason.startswith(FIND_REPLACE_PREFIX)
        return
    body = _without(reason, messages.PLACEMENT_CLAUSE, expected=expected.placement)
    body = _without(body, messages.MARKER_CLAUSE, expected=expected.marker_clause)
    parts = SELF_MATCH.fullmatch(body)
    assert parts is not None, reason
    assert parts["word"] in ("pgrep", "pkill")
    assert parts["word"] in case.command
    assert parts["excerpt"] in case.command
    assert parts["fix"] == messages.SELF_MATCH_FIXES[Platform(case.platform)]


def _without(reason: str, clause: str, *, expected: bool) -> str:
    """`reason` with `clause` removed from its end, asserting it was there exactly when expected."""
    suffix = f" {clause}"
    assert reason.endswith(suffix) is expected, reason
    return reason.removesuffix(suffix)
