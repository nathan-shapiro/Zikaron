"""The re-read nudge, `design/edit-guards.md` §4, through the hook's I/O."""

import json

import pytest

from zikaron.guard import messages
from zikaron.guard.main import respond

PATH = "/home/u/proj/design/x.md"
PATCH = [{"oldStart": 10, "oldLines": 3, "newStart": 10, "newLines": 4, "lines": []}]


def _nudge(tool: str, tool_input: dict[str, object], **result: object) -> str | None:
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "cwd": "/home/u/proj",
        "tool_input": tool_input,
        **result,
    }
    output = respond(json.dumps(payload), tmpdir=None)
    if output is None:
        return None
    envelope = json.loads(output)["hookSpecificOutput"]
    assert envelope["hookEventName"] == "PostToolUse"
    assert set(envelope) == {"hookEventName", "additionalContext"}
    context = envelope["additionalContext"]
    assert isinstance(context, str)
    return context


@pytest.mark.parametrize("field", ["tool_response", "tool_output"])
def test_line_ranges_come_from_the_structured_patch_in_either_result_field(field: str) -> None:
    patch = [*PATCH, {"newStart": 40, "newLines": 1}]
    nudge = _nudge("Edit", {"file_path": PATH}, **{field: {"structuredPatch": patch}})
    assert nudge == messages.NUDGE_WITH_RANGES_TEMPLATE.format(path=PATH, ranges="10-13, 40")


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"tool_response": {}},
        {"tool_response": {"structuredPatch": []}},
        {"tool_response": {"structuredPatch": "10-13"}},
        {"tool_response": {"structuredPatch": [{"newStart": 1}]}},
        {"tool_response": {"structuredPatch": [{"newStart": True, "newLines": 1}]}},
        {"tool_response": {"structuredPatch": [*PATCH, "hunk"]}},
    ],
)
def test_no_recognised_patch_omits_the_ranges_never_guesses(result: dict[str, object]) -> None:
    assert _nudge("Edit", {"file_path": PATH}, **result) == messages.NUDGE_TEMPLATE.format(
        path=PATH
    )


def test_notebook_edit_names_its_notebook_path() -> None:
    nudge = _nudge("NotebookEdit", {"notebook_path": "/home/u/proj/n.ipynb"})
    assert nudge == messages.NUDGE_TEMPLATE.format(path="/home/u/proj/n.ipynb")


def test_a_write_that_creates_a_file_gets_no_nudge() -> None:
    assert _nudge("Write", {"file_path": PATH}, tool_response={"type": "create"}) is None


@pytest.mark.parametrize("result", [{"tool_response": {"type": "update"}}, {}])
def test_a_write_that_overwrites_or_says_nothing_gets_a_nudge(result: dict[str, object]) -> None:
    assert _nudge("Write", {"file_path": PATH}, **result) is not None


@pytest.mark.parametrize(
    "path",
    ["/tmp/probe.py", "/var/tmp/x", "/private/tmp/x"],  # noqa: S108 — payload values, never opened
)
def test_a_scratch_path_gets_no_nudge(path: str) -> None:
    assert _nudge("Edit", {"file_path": path}, tool_response={"structuredPatch": PATCH}) is None


@pytest.mark.parametrize("tool_input", [{}, {"file_path": ""}, {"file_path": 3}])
def test_an_edit_naming_no_path_gets_no_nudge(tool_input: dict[str, object]) -> None:
    assert _nudge("MultiEdit", tool_input) is None
