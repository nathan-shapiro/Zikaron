"""The find-replace rule against every row of `design/guards.md` §8, through the hook's I/O.

Each item is judged under §8's payload — `cwd` `/home/u/proj`, `$TMPDIR` and `CLAUDE_JOB_DIR`
unset, no `scratchpad_dir`, no file for row 6 to read — and asserted on what the hook emits: the
decision, which marker message, the placement clause, and what the deny names. Both variables are
pinned as well as passed, because on macOS the OS sets `$TMPDIR`, a background job sets
`CLAUDE_JOB_DIR`, and a row judged under the runner's own value would differ by machine; row 6
reads no file, so a row never depends on what the machine running it holds under `/tmp`. §8.1's
items read real files, through the hook's own reader, written first into a fresh directory that
stands as `$TMPDIR`; §8.2's are judged with the job directory unset and set, a row listing files
writing them first into the `tmp` of a fresh directory that stands as the job's.
"""

import json
import re
from pathlib import Path

import pytest

from tests.guard_table import (
    JOB_DIR,
    Case,
    Expected,
    FileCase,
    JobCase,
    cases,
    file_cases,
    job_cases,
)
from zikaron.guard import messages
from zikaron.guard.main import respond
from zikaron.guard.scratch import normalise
from zikaron.guard.script_file import Reader, read_script

CASES = cases()
FILE_CASES = file_cases()
JOB_CASES = job_cases()


@pytest.fixture(autouse=True)
def _no_tmpdir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("CLAUDE_JOB_DIR", raising=False)


def _emit(
    case: Case | FileCase | JobCase,
    *,
    tmpdir: str | None = None,
    job_dir: str | None = None,
    read: Reader | None = None,
) -> dict[str, object] | None:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": case.cwd,
        "tool_input": {"command": case.command},
    }
    output = respond(
        json.dumps(payload), tmpdir=tmpdir, platform="linux", read=read, job_dir=job_dir
    )
    if output is None:
        return None
    envelope = json.loads(output)["hookSpecificOutput"]
    assert isinstance(envelope, dict)
    return envelope


def _decision(envelope: dict[str, object] | None) -> str:
    if envelope is None:
        return "silent"
    if envelope.get("permissionDecision") == "deny":
        return "deny"
    assert "permissionDecision" not in envelope, "an override must withdraw, never grant"
    return "ack"


def _named(reason: str) -> tuple[list[str], bool]:
    """The paths a deny message names, and whether it says it found none."""
    clause = re.search(r"; it names (.*?)\. (?:That is|It carries)", reason)
    assert clause is not None, reason
    if clause.group(1) == messages.NO_TARGET:
        return [], True
    return re.findall(r"`([^`]+)`", clause.group(1)), False


def test_every_section_8_row_yields_items() -> None:
    assert len({case.row for case in CASES}) > 100
    assert all(case.command for case in CASES)


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_section_8_row(case: Case) -> None:
    expected = Expected.of(case.expected, case.command)
    envelope = _emit(case)
    assert _decision(envelope) == expected.decision, case.expected
    if expected.decision == "ack":
        assert envelope is not None
        context = envelope["additionalContext"]
        assert isinstance(context, str)
        assert context.startswith("#ZIKARON-FORCE accepted by Zikaron's find-replace guard")
    if expected.decision != "deny":
        return
    assert envelope is not None
    reason = envelope["permissionDecisionReason"]
    assert isinstance(reason, str)
    _assert_deny_message(case, expected, reason)


def test_section_8_1_has_rows() -> None:
    assert len({case.row for case in FILE_CASES}) > 10


@pytest.mark.parametrize("case", FILE_CASES, ids=[case.id for case in FILE_CASES])
def test_section_8_1_row(case: FileCase, tmp_path: Path) -> None:
    for scratch_file in case.files:
        scratch_file.create(tmp_path)
    expected = Expected.of(case.expected, case.command)
    envelope = _emit(case, tmpdir=str(tmp_path), read=read_script)
    _assert_expected(case, expected, envelope)


def test_section_8_2_has_rows() -> None:
    assert len({case.row for case in JOB_CASES}) > 4
    assert {case.job_dir_set for case in JOB_CASES} == {False, True}


@pytest.mark.parametrize("case", JOB_CASES, ids=[case.id for case in JOB_CASES])
def test_section_8_2_row(case: JobCase, tmp_path: Path) -> None:
    job_dir: str | None = None
    if case.files:
        (tmp_path / "tmp").mkdir()
        for scratch_file in case.files:
            scratch_file.create(tmp_path / "tmp")
        job_dir = str(tmp_path) if case.job_dir_set else None
    elif case.job_dir_set:
        job_dir = JOB_DIR
    expected = Expected.of(case.expected, case.command)
    envelope = _emit(case, job_dir=job_dir, read=read_script if case.files else None)
    _assert_expected(case, expected, envelope)


def _assert_expected(
    case: FileCase | JobCase, expected: Expected, envelope: dict[str, object] | None
) -> None:
    assert _decision(envelope) == expected.decision, case.expected
    if expected.decision == "deny":
        assert envelope is not None
        reason = envelope["permissionDecisionReason"]
        assert isinstance(reason, str)
        _assert_deny_message(case, expected, reason)


def _assert_deny_message(case: Case | FileCase | JobCase, expected: Expected, reason: str) -> None:
    assert ("It carries #ZIKARON-FORCE" in reason) is expected.invalid_marker
    if expected.placement:
        assert messages.PLACEMENT_CLAUSE in reason
    if "#ZIKARON-FORCE" not in case.command:
        assert messages.PLACEMENT_CLAUSE not in reason
    named, none_found = _named(reason)
    for path in expected.named:
        assert normalise(path, case.cwd) in named, reason
    if expected.named_form is not None:
        assert reason.startswith(
            f"Zikaron's find-replace guard refused this command: `{expected.named_form}` "
        )
    if expected.names_no_literal:
        assert none_found, reason
    if expected.names_authored:
        assert any(_built_from_command(path, case) for path in named), reason


def _built_from_command(path: str, case: Case | FileCase | JobCase) -> bool:
    """A named path every one of whose components appears in the command's own text."""
    relative = path.removeprefix(case.cwd + "/")
    return all(part in case.command for part in relative.strip("/").split("/") if part)
