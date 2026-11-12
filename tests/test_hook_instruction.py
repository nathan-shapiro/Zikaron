"""`zikaron.hook.instruction`: an agent's latest instruction, read from the end of its transcript.

`design/harness.md` §"Agent teams" is normative. The fixtures are the probe runs' record shapes
(`tests/transcript_records.py`); each case is one the brief names, and the two that must not push
the instruction before them are pinned to yield `Unread`.
"""

import json
from pathlib import Path

import pytest

from tests import transcript_records as records
from zikaron.harness.spec import CLAUDE_CODE
from zikaron.hook.instruction import Unread, latest


def _latest(path: Path, *, main_shaped: bool = False) -> str | Unread | None:
    assert CLAUDE_CODE.instruction_push is not None
    return latest(path, CLAUDE_CODE.instruction_push, main_shaped=main_shaped)


def test_an_ordinary_subagents_prompt_before_its_first_tool_call(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user("Find where the gate is defined."),
            records.attachment(),
            records.assistant(records.thinking()),
            records.assistant(records.text()),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "Find where the gate is defined."


def test_the_tail_a_responses_first_call_reads_yields_its_instruction(tmp_path: Path) -> None:
    """The shape 51 of the live runs' 53 agent `PreToolUse` hooks saw: the response is not yet
    written, and the request records after the instruction carry no instruction."""
    path = records.write(
        tmp_path / "t.jsonl", records.at_first_call(records.message("Run the probe."))
    )
    assert _latest(path) == "Run the probe."


def test_an_in_process_teammates_first_message_is_its_body(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user(records.message("Run the probe.", summary="Spawn mate-1")),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "Run the probe."


def test_a_later_message_and_not_the_one_before_it(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user(records.message("First.")),
            records.assistant(records.tool_use()),
            records.user([records.tool_result()]),
            records.assistant(records.text()),
            records.user(records.message("Second.")),
            records.attachment(),
            records.assistant(records.thinking()),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "Second."


def test_two_messages_delivered_in_one_turn_are_one_instruction(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.assistant(records.text()),
            records.user(records.message("Second.")),
            records.user(records.message("Third.")),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "Second.\n\nThird."


def test_two_messages_in_one_record_are_one_instruction(tmp_path: Path) -> None:
    """Two sent in quick succession to an idle teammate arrive as one record, measured."""
    both = records.message("Second.") + "\n\n" + records.message("Third.")
    path = records.write(
        tmp_path / "t.jsonl",
        [records.assistant(records.text()), *records.at_first_call(both)],
    )
    assert _latest(path) == "Second.\n\nThird."


@pytest.mark.parametrize(
    "after",
    [
        "",
        "\n\nThis is a shutdown request. To approve it, call SendMessage with exactly this input.",
    ],
    ids=["alone", "followed-by-its-instructions"],
)
def test_a_shutdown_request_is_no_instruction(tmp_path: Path, after: str) -> None:
    """Measured, the request is its JSON line followed by prose on how to answer it."""
    request = json.dumps({"type": "shutdown_request", "requestId": "r", "from": "team-lead"})
    path = records.write(
        tmp_path / "t.jsonl",
        [records.user(records.message(request + after)), records.assistant(records.tool_use())],
    )
    assert _latest(path) is None


def test_an_arrow_in_a_messages_summary_stays_out_of_its_body(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user(records.message("Run it.", summary="step a -> b")),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "Run it."


def test_a_body_on_the_tags_own_line_is_unread(tmp_path: Path) -> None:
    inline = f'{records.MESSAGE_OPENING} teammate_id="team-lead">Run it.</teammate-message>'
    path = records.write(tmp_path / "t.jsonl", [records.user(inline)])
    assert _latest(path) is Unread.UNWRAPPED


@pytest.mark.parametrize("flag", ["isMeta", "isCompactSummary"])
def test_a_record_the_harness_flags_as_its_own_is_passed_over(tmp_path: Path, flag: str) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user("The task."),
            records.user("<local-command-caveat>placeholder", **{flag: True}),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "The task."


def test_a_skill_expansion_is_passed_over(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user("The task."),
            records.user([records.text("skill body")], isMeta=True),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "The task."


@pytest.mark.parametrize("closing", [True, False], ids=["as-measured", "closing-absent"])
def test_a_resumed_subagents_next_prompt_is_its_body(tmp_path: Path, closing: bool) -> None:
    """The record the harness flags as its own is the instruction here, and the earlier prompt
    is not pushed again."""
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user("The first task."),
            records.assistant(records.tool_use()),
            records.user([records.tool_result()]),
            records.assistant(records.text()),
            records.resumed("The second task.", closing=closing),
            records.attachment(),
            records.assistant(records.thinking()),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "The second task."


def test_a_resume_record_of_another_wording_is_unread(tmp_path: Path) -> None:
    resume = records.resumed("The second task.")
    resume["message"] = {"role": "user", "content": "The coordinator says:\nThe second task."}
    path = records.write(
        tmp_path / "t.jsonl",
        [records.user("The first task."), resume, records.assistant(records.tool_use())],
    )
    assert _latest(path) is Unread.UNWRAPPED


def test_a_text_record_after_the_instruction_is_unread(tmp_path: Path) -> None:
    """An instruction of a shape never measured must not push the one before it."""
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user("The first task."),
            records.assistant(records.text()),
            records.user([records.text("A second prompt in blocks.")]),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) is Unread.TEXT_AFTER


def test_a_tool_result_after_the_instruction_is_unread(tmp_path: Path) -> None:
    """The turn is past its first tool call, so this call is not the one the marker was set for."""
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user(records.message("The task.")),
            records.assistant(records.tool_use()),
            records.user([records.tool_result()]),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) is Unread.RESULT_AFTER


def test_a_transcript_cut_mid_record_is_unread(tmp_path: Path) -> None:
    path = records.write(tmp_path / "t.jsonl", [records.user("The task.")])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "assistant", "message": {"con')
    assert _latest(path) is Unread.MALFORMED


def test_a_user_record_without_content_is_unread(tmp_path: Path) -> None:
    path = records.write(tmp_path / "t.jsonl", [{"type": "user", "message": {"role": "user"}}])
    assert _latest(path) is Unread.MALFORMED


def test_a_message_that_never_closes_is_unread(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [records.user(f'{records.MESSAGE_OPENING} teammate_id="team-lead">\nNo end.')],
    )
    assert _latest(path) is Unread.UNWRAPPED


def test_a_missing_transcript_is_unread(tmp_path: Path) -> None:
    assert _latest(tmp_path / "absent.jsonl") is Unread.MISSING


def test_an_empty_transcript_holds_nothing(tmp_path: Path) -> None:
    assert _latest(records.write(tmp_path / "t.jsonl", [])) is None


def test_a_tmux_teammates_own_transcript_is_served(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.attachment(),
            records.user(records.message("Run the probe.")),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path, main_shaped=True) == "Run the probe."


def test_a_main_session_is_never_served_whatever_its_last_record_says(tmp_path: Path) -> None:
    """The lead receives teammates' messages as these records too; its prompts are the prompt
    hook's, and messages to it are not pushed on."""
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user("A prompt the operator typed."),
            records.assistant(records.text()),
            records.user(records.message("A report.", sender="mate-1")),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path, main_shaped=True) is None


def test_the_instruction_is_found_across_read_blocks(tmp_path: Path) -> None:
    """The transcript is read backward in blocks; one far larger than a block still yields the
    instruction at its end, whole."""
    earlier = [records.user("Old."), records.assistant(records.text("x" * 2_000))] * 100
    body = "y" * 70_000
    path = records.write(
        tmp_path / "t.jsonl",
        [*earlier, records.user(body), records.assistant(records.tool_use())],
    )
    assert path.stat().st_size > 3 * 65_536
    assert _latest(path) == body


def test_an_earlier_turns_tool_result_ends_the_instruction(tmp_path: Path) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.user("Old."),
            records.user([records.tool_result()]),
            records.user(records.message("New.")),
            records.assistant(records.tool_use()),
        ],
    )
    assert _latest(path) == "New."


def test_a_record_of_neither_text_nor_a_tool_result_is_passed_over(tmp_path: Path) -> None:
    image: dict[str, object] = {"type": "image", "source": {"type": "base64", "data": ""}}
    path = records.write(
        tmp_path / "t.jsonl",
        [records.user("The task."), records.user([image]), records.assistant(records.tool_use())],
    )
    assert _latest(path) == "The task."


def test_a_session_whose_first_instruction_comes_after_its_own_records_is_a_teammate(
    tmp_path: Path,
) -> None:
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.attachment(),
            records.user("<local-command-caveat>placeholder", isMeta=True),
            records.user([records.tool_result()]),
            records.user(records.message("Run the probe.")),
            records.assistant(records.tool_use()),
        ],
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
    assert _latest(path, main_shaped=True) == "Run the probe."


def test_the_same_transcript_reads_byte_identically_twice(tmp_path: Path) -> None:
    """`coding-standards.md` §4: the reader is the one new step on the push path, the service's
    half being the prompt path's own."""
    path = records.write(
        tmp_path / "t.jsonl",
        [
            records.assistant(records.text()),
            records.user(records.message("Second.")),
            records.user(records.message("Third.")),
            records.assistant(records.tool_use()),
        ],
    )
    first, second = _latest(path), _latest(path)
    assert isinstance(first, str)
    assert first.encode() == str(second).encode()


def test_a_session_with_no_instruction_at_all_is_not_served(tmp_path: Path) -> None:
    path = records.write(tmp_path / "t.jsonl", [records.attachment()])
    assert _latest(path, main_shaped=True) is None
