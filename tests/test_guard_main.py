"""`zikaron-guard`'s dispatch, its override output, its tool filters and its fail-open rule, on
both harnesses.

`design/guards.md` §3.4 (the override withdraws the deny and grants nothing), §5 (the tool
sets are the spec field's matchers), §6 (every failure is an allow, silently) and §9 (the
platform the self-match rule reads is the process's own). Under kiro a deny is exit 2 with the
reason on stderr, and nothing else reaches the model (`design/harness.md` §"The table").
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from zikaron.guard import decision, main, messages
from zikaron.guard.forms import FormMatch
from zikaron.guard.scratch import Location
from zikaron.harness.spec import CLAUDE_CODE, KIRO, GuardHook, Guards, HarnessSpec


def _guards(spec: HarnessSpec) -> Guards:
    assert spec.guards is not None
    return spec.guards


GUARDS: Final = _guards(CLAUDE_CODE)
KIRO_GUARDS: Final = _guards(KIRO)
DENIED = "sed -i 's/a/b/' f"
SELF_MATCHING = "pkill -f month_monitor.py"
OVERRIDDEN = f"{DENIED} #ZIKARON-FORCE #Reason: regenerate golden file"


def _pre_tool_use(command: object = DENIED, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": "/home/u/proj",
        "tool_input": {"command": command},
    }
    payload.update(overrides)
    return payload


def _kiro_pre_tool_use(command: object = DENIED) -> dict[str, object]:
    """The shell tool's payload as kiro sends it (`research/kiro-v3-probe.md` §32)."""
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "sess_x",
        "tool_name": "execute_bash",
        "cwd": "/home/u/proj",
        "tool_input": {
            "command": command,
            "description": "d",
            "cwd": None,
            "run_in_background": False,
            "timeout": None,
        },
    }


def _envelope(payload: object, spec: HarnessSpec = CLAUDE_CODE) -> dict[str, object] | None:
    output = main.respond(json.dumps(payload), tmpdir=None, platform="linux", spec=spec)
    if output is None:
        return None
    assert (output.stderr, output.exit_code) == ("", 0)
    envelope = json.loads(output.stdout)["hookSpecificOutput"]
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
    denied = decision.decide(DENIED, Location("/home/u/proj"), platform="linux")
    assert isinstance(denied, decision.Deny)
    assert isinstance(denied.match, FormMatch)
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
@pytest.mark.parametrize("command", [DENIED, SELF_MATCHING])
def test_pre_tool_use_judges_only_bash_and_monitor(tool: object, command: str) -> None:
    assert _envelope(_pre_tool_use(command, tool_name=tool)) is None


@pytest.mark.parametrize("command", [DENIED, SELF_MATCHING])
def test_a_monitor_command_is_judged_by_both_rules(command: str) -> None:
    envelope = _envelope(_pre_tool_use(command, tool_name="Monitor"))
    assert envelope is not None
    assert envelope["permissionDecision"] == "deny"


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
    assert GUARDS.reread is not None
    assert GUARDS.command.tools == frozenset({"Bash", "Monitor"})
    assert GUARDS.reread.tools == frozenset({"Edit", "MultiEdit", "NotebookEdit", "Write"})
    widened = GUARDS._replace(command=GuardHook("PreToolUse", "Bash|Grep"))
    spec = CLAUDE_CODE._replace(guards=widened)
    assert _envelope(_pre_tool_use(tool_name="Grep"), spec=spec) is not None


@pytest.mark.parametrize(
    "hook", [hook for hook in (GUARDS.command, GUARDS.reread) if hook is not None]
)
def test_each_matcher_is_a_bar_joined_list_of_bare_tool_names(hook: GuardHook) -> None:
    assert all(name.isalpha() and name[0].isupper() for name in hook.matcher.split("|"))


def test_a_harness_without_guards_produces_nothing() -> None:
    assert _envelope(_pre_tool_use(), spec=CLAUDE_CODE._replace(guards=None)) is None


class TestUnderKiro:
    """A deny is exit 2 with its reason on stderr and nothing on stdout; nothing printed on exit 0
    reaches the model, so an accepted override says nothing (`research/kiro-v3-probe.md` §33,
    §34)."""

    @staticmethod
    def _respond(payload: object) -> main.HookOutput | None:
        return main.respond(json.dumps(payload), tmpdir=None, platform="linux", spec=KIRO)

    def test_a_real_shape_shell_payload_is_judged_and_denied_on_stderr(self) -> None:
        output = self._respond(_kiro_pre_tool_use())
        assert output is not None
        assert (output.stdout, output.exit_code) == ("", 2)
        assert output.stderr.startswith("Zikaron's find-replace guard refused this command:")
        assert "edited with read_file then str_replace, or with fs_write" in output.stderr
        assert output.stderr.endswith(messages.UNACKNOWLEDGED_CLAUSE)

    def test_the_self_match_deny_names_kiro_and_goes_out_on_stderr(self) -> None:
        output = self._respond(_kiro_pre_tool_use(SELF_MATCHING))
        assert output is not None
        assert output.exit_code == 2
        assert "because kiro-cli runs each command inside a shell" in output.stderr

    def test_an_accepted_override_prints_nothing(self) -> None:
        assert self._respond(_kiro_pre_tool_use(OVERRIDDEN)) is None

    def test_the_shell_tool_is_matched_by_its_id(self) -> None:
        """The payload names the tool `execute_bash`; a matcher written as the selector `shell`
        would match no payload, and the guard would judge nothing."""
        assert KIRO_GUARDS.command.tools == frozenset({"execute_bash"})
        assert self._respond({**_kiro_pre_tool_use(), "tool_name": "shell"}) is None
        assert self._respond({**_kiro_pre_tool_use(), "tool_name": "Bash"}) is None

    def test_a_post_tool_payload_produces_nothing_since_there_is_no_re_read_hook(self) -> None:
        assert KIRO_GUARDS.reread is None
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "str_replace",
            "cwd": "/home/u/proj",
            "tool_input": {"path": "/home/u/proj/a.md"},
        }
        assert self._respond(payload) is None

    def test_tool_input_cwd_is_not_read(self) -> None:
        """Judged against the payload's `cwd`, since `tool_input.cwd` was never seen set."""
        payload = _kiro_pre_tool_use()
        tool_input = payload["tool_input"]
        assert isinstance(tool_input, dict)
        tool_input["cwd"] = "/tmp"  # noqa: S108 — payload text, never opened
        output = self._respond(payload)
        assert output is not None
        assert "it names `/home/u/proj/f`" in output.stderr


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
    stdin: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *arguments: str,
    status: int = 0,
) -> str:
    """`main` with `arguments` on its command line; what it wrote to stdout, its exit status
    asserted. Anything on stderr is asserted absent where the status is 0."""
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    monkeypatch.setattr("sys.argv", ["zikaron-guard", *arguments])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == status
    captured = capsys.readouterr()
    if status == 0:
        assert captured.err == ""
        return captured.out
    assert captured.out == ""
    return captured.err


@pytest.mark.parametrize("stdin", ["", "{", "not json", "null", "[1, 2]"])
@pytest.mark.parametrize("arguments", [(), ("--harness", "kiro")], ids=["claude-code", "kiro"])
def test_malformed_stdin_exits_zero_with_no_output(
    stdin: str,
    arguments: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _run_main(stdin, capsys, monkeypatch, *arguments) == ""


@pytest.mark.parametrize(
    ("payload", "arguments"),
    [(_pre_tool_use(), ()), (_kiro_pre_tool_use(), ("--harness", "kiro"))],
    ids=["claude-code", "kiro"],
)
def test_an_exception_inside_a_rule_exits_zero_with_no_output(
    payload: dict[str, object],
    arguments: tuple[str, ...],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under kiro too: exit 2 on a defect would block a call for a reason not the agent's, and
    exit 0 is what kiro gives a crashed hook anyway (`research/kiro-v3-probe.md` §34)."""

    def broken(*_: object) -> decision.Decision:
        raise RuntimeError("a defect in a rule")

    monkeypatch.setattr(main, "decide", broken)
    assert _run_main(json.dumps(payload), capsys, monkeypatch, *arguments) == ""


class TestTheHarnessIsTheCommandLines:
    """The installer knows which harness's file it writes; the environment can lie, since a kiro
    launched from Claude Code inherits `CLAUDECODE` (`design/harness.md` §"The nesting limit")."""

    def test_harness_kiro_denies_on_stderr_whatever_the_environment_says(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert CLAUDE_CODE.marker_variable is not None
        monkeypatch.setenv(CLAUDE_CODE.marker_variable, "1")
        stdin = json.dumps(_kiro_pre_tool_use())
        reason = _run_main(stdin, capsys, monkeypatch, "--harness", "kiro", status=2)
        assert reason.startswith("Zikaron's find-replace guard refused this command:")

    def test_no_argument_is_claude_code_whatever_the_environment_says(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert CLAUDE_CODE.marker_variable is not None
        monkeypatch.delenv(CLAUDE_CODE.marker_variable, raising=False)
        output = _run_main(json.dumps(_pre_tool_use()), capsys, monkeypatch)
        assert json.loads(output)["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_an_accepted_override_under_kiro_exits_zero_saying_nothing(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stdin = json.dumps(_kiro_pre_tool_use(OVERRIDDEN))
        assert _run_main(stdin, capsys, monkeypatch, "--harness", "kiro") == ""


def test_an_exception_inside_the_self_match_rule_exits_zero_with_no_output(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("a defect in the self-match rule")

    monkeypatch.setattr(decision, "first_self_match", broken)
    assert _run_main(json.dumps(_pre_tool_use(SELF_MATCHING)), capsys, monkeypatch) == ""


@pytest.mark.parametrize(("platform", "denied"), [("linux", True), ("darwin", False)])
def test_main_passes_the_processs_own_platform(
    platform: str,
    denied: bool,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    output = _run_main(json.dumps(_pre_tool_use(SELF_MATCHING)), capsys, monkeypatch)
    assert bool(output) is denied


def test_main_writes_the_rules_output_and_exits_zero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("CLAUDE_JOB_DIR", raising=False)
    output = _run_main(json.dumps(_pre_tool_use()), capsys, monkeypatch)
    assert json.loads(output)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_main_reads_tmpdir_from_the_environment(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", "/var/folders/x/T")
    command = "sed -i 's/a/b/' /var/folders/x/T/f"
    assert _run_main(json.dumps(_pre_tool_use(command)), capsys, monkeypatch) == ""


@pytest.mark.parametrize("job_dir", ["/home/u/.claude/jobs/j", "/home/u/.claude/jobs/j/"])
def test_main_reads_a_background_jobs_directory_from_the_environment(
    job_dir: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_JOB_DIR", job_dir)
    command = "sed -i 's/a/b/' /home/u/.claude/jobs/j/tmp/f"
    assert _run_main(json.dumps(_pre_tool_use(command)), capsys, monkeypatch) == ""


class TestTheRealProcess:
    """`main()` in a process of its own, as the console script runs it: stdin in, stdout out,
    exit 0."""

    @staticmethod
    def _run(stdin: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = {k: v for k, v in os.environ.items() if k != "CLAUDE_JOB_DIR"}
        script = "import sys; from zikaron.guard.main import main; main()"
        return subprocess.run(  # noqa: S603 — this interpreter and a fixed script.
            [sys.executable, "-c", script, *arguments],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=environment,
        )

    def test_a_deny_reaches_stdout(self) -> None:
        result = self._run(json.dumps(_pre_tool_use()))
        assert result.returncode == 0
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result.stderr == ""

    def test_under_kiro_a_deny_exits_2_with_the_reason_on_stderr(self) -> None:
        result = self._run(json.dumps(_kiro_pre_tool_use()), "--harness", "kiro")
        assert (result.returncode, result.stdout) == (2, "")
        assert result.stderr.startswith("Zikaron's find-replace guard refused this command:")

    def test_a_self_match_deny_reaches_stdout(self) -> None:
        """`-af` matches its shell on both supported platforms, so this holds on either."""
        result = self._run(json.dumps(_pre_tool_use("pgrep -af month_monitor.py")))
        reason = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        assert (result.returncode, result.stderr) == (0, "")
        assert reason.startswith("Zikaron's self-match rule refused this command")

    @pytest.mark.parametrize("stdin", ["", "not json{{{"])
    def test_malformed_stdin_exits_zero_with_no_output(self, stdin: str) -> None:
        result = self._run(stdin)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")

    def test_the_process_reads_a_scratch_script_it_is_asked_to_run(self, tmp_path: Path) -> None:
        """Row 6's one read is wired at `main`, the hook's I/O edge, and nowhere else."""
        (tmp_path / "fix.py").write_text("open('f', 'w').write('x')\n", encoding="utf-8")
        payload = json.dumps(_pre_tool_use(f"python3 {tmp_path}/fix.py"))
        assert main.respond(payload, tmpdir=None, platform="linux") is None
        result = self._run(payload)
        decision = json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]
        assert (result.returncode, decision) == (0, "deny")


def test_a_scratchpad_the_payload_names_is_scratch() -> None:
    command = "sed -i 's/a/b/' /home/u/pad/f"
    assert _envelope(_pre_tool_use(command)) is not None
    assert _envelope(_pre_tool_use(command, scratchpad_dir="/home/u/pad")) is None
