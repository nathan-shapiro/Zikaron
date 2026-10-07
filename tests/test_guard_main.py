"""`zikaron-guard`'s dispatch, its override output, its tool filters and its fail-open rule.

`design/edit-guards.md` §3.4 (the override withdraws the deny and grants nothing), §5 (the tool
sets are the spec field's matchers) and §6 (every failure is an allow, silently).
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from zikaron.guard import decision, main, messages
from zikaron.guard.scratch import Location
from zikaron.harness.spec import CLAUDE_CODE, EditGuards, GuardHook

GUARDS = CLAUDE_CODE.edit_guards
DENIED = "sed -i 's/a/b/' f"


def _pre_tool_use(command: object = DENIED, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": "/home/u/proj",
        "tool_input": {"command": command},
    }
    payload.update(overrides)
    return payload


def _envelope(payload: object, guards: EditGuards | None = GUARDS) -> dict[str, object] | None:
    output = main.respond(json.dumps(payload), tmpdir=None, guards=guards)
    if output is None:
        return None
    envelope = json.loads(output)["hookSpecificOutput"]
    assert isinstance(envelope, dict)
    return envelope


def test_a_deny_carries_the_decision_and_the_message() -> None:
    envelope = _envelope(_pre_tool_use())
    assert envelope is not None
    assert envelope["hookEventName"] == "PreToolUse"
    assert envelope["permissionDecision"] == "deny"
    reason = envelope["permissionDecisionReason"]
    assert isinstance(reason, str)
    assert "`sed` edits a file in place (-i or --in-place); it names `/home/u/proj/f`." in reason


def test_a_valid_override_returns_no_decision_only_the_acknowledgement() -> None:
    envelope = _envelope(_pre_tool_use(f"{DENIED} #ZIKARON-FORCE #Reason: regenerate golden file"))
    denied = decision.decide(DENIED, Location("/home/u/proj"))
    assert isinstance(denied, decision.Deny)
    targets = denied.match.authored_paths
    assert envelope == {
        "hookEventName": "PreToolUse",
        "additionalContext": messages.acknowledgement("regenerate golden file", targets),
    }


def test_the_acknowledgement_names_what_the_command_changes_so_it_can_be_re_read() -> None:
    """§3.4: the re-read the nudge cannot ask after a Bash call is asked by the acknowledgement,
    naming every authored target of every denying form — or the fixed clause where none
    resolves."""
    forms = (
        "sed -i 's/a/b/' f g /tmp/x && echo y > h && echo z > f #ZIKARON-FORCE #Reason: bulk rename"
    )
    changes = "This command changes `/home/u/proj/f`, `/home/u/proj/g`, `/home/u/proj/h`. "
    assert changes in _context(forms)
    assert "/tmp/x" not in _context(forms)  # noqa: S108 — command text, never opened
    staged = (
        "cat > /tmp/fix.py <<'EOF' #ZIKARON-FORCE #Reason: bulk mechanical rename\n"
        "open('f', 'w')\nEOF\npython3 /tmp/fix.py"
    )
    assert "This command changes `/home/u/proj/f`. " in _context(staged)
    unresolved = "python3 -c \"open(sys.argv[1], 'w')\" f #ZIKARON-FORCE #Reason: bulk rename"
    assert messages.NO_TARGET in _context(unresolved)


def _context(command: str) -> str:
    envelope = _envelope(_pre_tool_use(command))
    assert envelope is not None
    context = envelope["additionalContext"]
    assert isinstance(context, str)
    return context


@pytest.mark.parametrize(
    "marker",
    ["#ZIKARON-FORCE", "#ZIKARON-FORCE #Reason: golden", "#ZIKARON-FORCE #Reason: <few words>"],
)
def test_an_invalid_marker_denies_with_the_invalid_marker_message(marker: str) -> None:
    envelope = _envelope(_pre_tool_use(f"{DENIED} {marker}"))
    assert envelope is not None
    reason = envelope["permissionDecisionReason"]
    assert isinstance(reason, str)
    assert "It carries #ZIKARON-FORCE, but no comment in it is a valid override." in reason


def test_a_marker_glued_to_a_word_is_invalid() -> None:
    envelope = _envelope(_pre_tool_use("sed -i 's/a/b/' f#ZIKARON-FORCE #Reason: a b"))
    assert envelope is not None
    assert "It carries #ZIKARON-FORCE" in str(envelope["permissionDecisionReason"])


def test_a_marker_on_a_command_no_form_matches_produces_no_output() -> None:
    assert _envelope(_pre_tool_use("ls #ZIKARON-FORCE #Reason: a b")) is None
    assert _envelope(_pre_tool_use("ls #ZIKARON-FORCE")) is None


@pytest.mark.parametrize("tool", ["Edit", "Write", "Grep", "PowerShell", None])
def test_pre_tool_use_judges_only_bash(tool: object) -> None:
    assert _envelope(_pre_tool_use(tool_name=tool)) is None


@pytest.mark.parametrize("tool", ["Bash", "Read", "Grep", None])
def test_post_tool_use_nudges_only_the_four_edit_tools(tool: object) -> None:
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": tool,
        "cwd": "/home/u/proj",
        "tool_input": {"file_path": "/home/u/proj/a.md"},
    }
    assert _envelope(payload) is None


def test_the_tool_sets_are_the_spec_fields_matchers() -> None:
    assert GUARDS is not None
    assert GUARDS.find_replace.tools == frozenset({"Bash"})
    assert GUARDS.reread.tools == frozenset({"Edit", "MultiEdit", "NotebookEdit", "Write"})
    widened = GUARDS._replace(find_replace=GuardHook("PreToolUse", "Bash|Grep"))
    assert _envelope(_pre_tool_use(tool_name="Grep"), guards=widened) is not None


@pytest.mark.parametrize("hook", [GUARDS.find_replace, GUARDS.reread] if GUARDS else [])
def test_each_matcher_is_a_bar_joined_list_of_bare_tool_names(hook: GuardHook) -> None:
    assert all(name.isalpha() and name[0].isupper() for name in hook.matcher.split("|"))


def test_a_harness_without_guards_produces_nothing() -> None:
    assert _envelope(_pre_tool_use(), guards=None) is None


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "PreToolUse",
        {"hook_event_name": "Stop"},
        {"hook_event_name": None},
        _pre_tool_use(command=None),
        _pre_tool_use(command=["sed", "-i"]),
        _pre_tool_use(cwd=None),
        _pre_tool_use(cwd="relative/dir"),
        _pre_tool_use(tool_input="sed -i 's/a/b/' f"),
        {key: value for key, value in _pre_tool_use().items() if key != "tool_input"},
    ],
)
def test_a_payload_missing_what_the_rule_needs_produces_nothing(payload: object) -> None:
    assert _envelope(payload) is None


def _run_main(
    stdin: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
    return capsys.readouterr().out


@pytest.mark.parametrize("stdin", ["", "{", "not json", "null", "[1, 2]"])
def test_malformed_stdin_exits_zero_with_no_output(
    stdin: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run_main(stdin, capsys, monkeypatch) == ""


def test_an_exception_inside_a_rule_exits_zero_with_no_output(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> decision.Decision:
        raise RuntimeError("a defect in a rule")

    monkeypatch.setattr(main, "decide", broken)
    assert _run_main(json.dumps(_pre_tool_use()), capsys, monkeypatch) == ""


def test_main_writes_the_rules_output_and_exits_zero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    output = _run_main(json.dumps(_pre_tool_use()), capsys, monkeypatch)
    assert json.loads(output)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_main_reads_tmpdir_from_the_environment(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", "/var/folders/x/T")
    command = "sed -i 's/a/b/' /var/folders/x/T/f"
    assert _run_main(json.dumps(_pre_tool_use(command)), capsys, monkeypatch) == ""


class TestTheRealProcess:
    """`main()` in a process of its own, as the console script runs it: stdin in, stdout out,
    exit 0."""

    @staticmethod
    def _run(stdin: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", "from zikaron.guard.main import main; main()"],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_a_deny_reaches_stdout(self) -> None:
        result = self._run(json.dumps(_pre_tool_use()))
        assert result.returncode == 0
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result.stderr == ""

    @pytest.mark.parametrize("stdin", ["", "not json{{{"])
    def test_malformed_stdin_exits_zero_with_no_output(self, stdin: str) -> None:
        result = self._run(stdin)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")

    def test_the_process_reads_a_scratch_script_it_is_asked_to_run(self, tmp_path: Path) -> None:
        """Row 6's one read is wired at `main`, the hook's I/O edge, and nowhere else."""
        (tmp_path / "fix.py").write_text("open('f', 'w').write('x')\n", encoding="utf-8")
        payload = json.dumps(_pre_tool_use(f"python3 {tmp_path}/fix.py"))
        assert main.respond(payload, tmpdir=None) is None
        result = self._run(payload)
        decision = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
        assert (result.returncode, decision) == (0, "deny")


def test_a_scratchpad_the_payload_names_is_scratch() -> None:
    command = "sed -i 's/a/b/' /home/u/pad/f"
    assert _envelope(_pre_tool_use(command)) is not None
    assert _envelope(_pre_tool_use(command, scratchpad_dir="/home/u/pad")) is None
