"""`zikaron-hook --components`: the start text by selection (`design/edit-guards.md` §5).

No flag is the memory hook exactly as it was. `guards` emits only the guard start text and makes
no service connection; `both` emits the write policy, then the guard start text. The consolidator,
whose system prompt is its whole instruction, gets nothing under any selection.
"""

import io
import json
import sys

import pytest

from zikaron.guard.start_text import GUARD_START_TEXT
from zikaron.hook import main as main_module
from zikaron.hook import push, spawn_warm, subagent_policy
from zikaron.hook.components import Components
from zikaron.hook.write_policy import SUBAGENT_WRITE_POLICY_PROMPT, WRITE_POLICY_PROMPT

SPAWN: dict[str, object] = {
    "hook_event_name": "SessionStart",
    "cwd": "/home/u/proj",
    "session_id": "s",
}
SUBAGENT: dict[str, object] = {
    "hook_event_name": "SubagentStart",
    "cwd": "/home/u/proj",
    "agent_type": "Explore",
}
CONSOLIDATOR: dict[str, object] = {
    **SUBAGENT,
    "agent_type": subagent_policy.CONSOLIDATOR_AGENT_TYPE,
}
PROMPT: dict[str, object] = {
    "hook_event_name": "UserPromptSubmit",
    "cwd": "/home/u/proj",
    "prompt": "hello",
}


@pytest.fixture(autouse=True)
def service_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every call that would reach the service or spawn a process, and answer it."""
    calls: list[str] = []

    def spawn(**_: object) -> str:
        calls.append("spawn_warm")
        return WRITE_POLICY_PROMPT

    def push_run(**_: object) -> str:
        calls.append("push")
        return "PUSHED"

    monkeypatch.setattr(spawn_warm, "run", spawn)
    monkeypatch.setattr(push, "run", push_run)
    return calls


def _emit(
    payload: dict[str, object],
    arguments: list[str],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    monkeypatch.setattr(sys, "argv", ["zikaron-hook", *arguments])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit):
        main_module.main()
    return capsys.readouterr().out


def _subagent_context(output: str) -> str:
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    assert isinstance(context, str)
    return context


def test_no_flag_emits_exactly_the_write_policy_on_session_start(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _emit(SPAWN, [], capsys, monkeypatch) == WRITE_POLICY_PROMPT


def test_no_flag_emits_exactly_the_subagent_policy_on_subagent_start(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _emit(SUBAGENT, [], capsys, monkeypatch)
    assert _subagent_context(output) == SUBAGENT_WRITE_POLICY_PROMPT


def test_guards_emit_only_the_guard_start_text_and_reach_no_service(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, service_calls: list[str]
) -> None:
    flag = ["--components", "guards"]
    assert _emit(SPAWN, flag, capsys, monkeypatch) == GUARD_START_TEXT
    assert _subagent_context(_emit(SUBAGENT, flag, capsys, monkeypatch)) == GUARD_START_TEXT
    assert _emit(PROMPT, flag, capsys, monkeypatch) == ""
    assert service_calls == []


def test_both_emit_the_policy_then_the_guard_start_text(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    flag = ["--components", "both"]
    spawn = _emit(SPAWN, flag, capsys, monkeypatch)
    assert spawn == f"{WRITE_POLICY_PROMPT}\n\n{GUARD_START_TEXT}"
    subagent = _subagent_context(_emit(SUBAGENT, flag, capsys, monkeypatch))
    assert subagent == f"{SUBAGENT_WRITE_POLICY_PROMPT}\n\n{GUARD_START_TEXT}"
    assert _emit(PROMPT, flag, capsys, monkeypatch) == "PUSHED"


@pytest.mark.parametrize("flag", [[], ["--components", "guards"], ["--components", "both"]])
def test_the_consolidator_gets_no_start_text_under_any_selection(
    flag: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _emit(CONSOLIDATOR, flag, capsys, monkeypatch) == ""


def test_a_subagent_session_spawn_with_both_still_gets_the_guard_text(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spawn_warm, "run", lambda **_: None)
    assert _emit(SPAWN, ["--components", "both"], capsys, monkeypatch) == GUARD_START_TEXT


def test_the_guard_start_text_carries_no_override_syntax() -> None:
    assert "#ZIKARON-FORCE" not in GUARD_START_TEXT


@pytest.mark.parametrize(
    "arguments",
    [[], ["--components"], ["--components", "all"], ["--components", "guards", "x"], ["guards"]],
)
def test_a_flag_that_does_not_read_cleanly_is_the_memory_hook(arguments: list[str]) -> None:
    assert Components.from_arguments(arguments) is Components.MEMORY


@pytest.mark.parametrize("selection", list(Components))
def test_a_selections_arguments_read_back_as_that_selection(selection: Components) -> None:
    assert Components.from_arguments(list(selection.arguments)) is selection


@pytest.mark.parametrize(
    ("one", "other", "union"),
    [
        (Components.MEMORY, Components.MEMORY, Components.MEMORY),
        (Components.GUARDS, Components.GUARDS, Components.GUARDS),
        (Components.MEMORY, Components.GUARDS, Components.BOTH),
        (Components.GUARDS, Components.MEMORY, Components.BOTH),
        (Components.BOTH, Components.MEMORY, Components.BOTH),
        (Components.GUARDS, Components.BOTH, Components.BOTH),
    ],
)
def test_the_union_carries_both_selections_products(
    one: Components, other: Components, union: Components
) -> None:
    assert one.union(other) is union
