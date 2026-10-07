"""`--components`: the memory store, the edit guards, or both (`design/edit-guards.md` §5).

`design/build-plan.md` §M37 names the axes: the prior state of `settings.local.json`, the
selection, the mode, the harness and the other flags. The plane of prior state against selection
is walked whole against one model of what §5 says the result is — an install touches only its own
selection, never removes another's, and the shared start entries carry the union — and the other
axes are walked where they change something.

The settings file is parsed JSON, so its helpers are typed `Any` rather than restating the
harness's schema here.
"""

import json
import shlex
from pathlib import Path
from typing import Any

import pytest

from zikaron.guard.limits import TIMEOUT_SECONDS
from zikaron.harness.spec import CLAUDE_CODE, EditGuards
from zikaron.hook.components import Components
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS
from zikaron.install import harness
from zikaron.install.entries import Commands, claude_hooks_value
from zikaron.install.main import main


def _edit_guards() -> EditGuards:
    guards = CLAUDE_CODE.edit_guards
    assert guards is not None
    return guards


GUARDS = _edit_guards()
START_TRIGGERS = ("SessionStart", "SubagentStart")
USER_PRE_TOOL_USE = {"matcher": "Bash", "hooks": [{"type": "command", "command": "/u/lint.sh"}]}
USER_POST_TOOL_USE = {"hooks": [{"type": "command", "command": "/u/format.sh"}]}


@pytest.fixture(autouse=True)
def commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Commands:
    scripts = tmp_path / "venv bin"
    scripts.mkdir()
    installed = Commands(hook=scripts / "zikaron-hook", mcp=scripts / "zikaron-mcp")
    for path in (installed.hook, installed.mcp, installed.guard):
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    monkeypatch.setattr(Commands, "from_this_interpreter", classmethod(lambda _cls: installed))
    monkeypatch.setattr(harness, "binary_is_available", lambda _name: True)
    monkeypatch.setattr(harness, "available_model_ids", frozenset)
    monkeypatch.setattr(harness, "validate_agent_config", lambda _path: None)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return installed


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".claude").mkdir(parents=True)
    return root


def _install(project: Path, *flags: str) -> int:
    return main(["--project", str(project), "--harness", "claude-code", *flags])


def _settings(project: Path) -> dict[str, Any]:
    loaded = json.loads((project / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _hooks(project: Path) -> dict[str, Any]:
    hooks = _settings(project)["hooks"]
    assert isinstance(hooks, dict)
    return hooks


def _commands_of(groups: list[Any]) -> list[str]:
    return [entry["command"] for group in groups for entry in group["hooks"]]


def _tree(project: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(project)): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


PRIORS = [None, Components.MEMORY, Components.GUARDS, Components.BOTH]


@pytest.mark.parametrize("prior", PRIORS, ids=lambda p: f"over-{p.value if p else 'nothing'}")
@pytest.mark.parametrize("selection", list(Components), ids=lambda s: s.value)
def test_the_result_is_the_union_of_what_was_there_and_what_is_installed(
    project: Path, commands: Commands, prior: Components | None, selection: Components
) -> None:
    if prior is not None:
        assert _install(project, "--components", prior.value) == 0
    assert _install(project, "--components", selection.value) == 0
    installed = selection if prior is None else prior.union(selection)
    hooks = _hooks(project)
    expected_triggers = {
        *START_TRIGGERS,
        *(["UserPromptSubmit"] if installed.memory else []),
        *([GUARDS.find_replace.trigger, GUARDS.reread.trigger] if installed.guards else []),
    }
    assert set(hooks) == expected_triggers
    start = " ".join((shlex.quote(str(commands.hook)), *installed.arguments))
    for trigger in START_TRIGGERS:
        assert _commands_of(hooks[trigger]) == [start]
    settings = _settings(project)
    assert ("enabledMcpjsonServers" in settings) is installed.memory
    assert ("permissions" in settings) is installed.memory
    assert (project / ".mcp.json").exists() is installed.memory
    consolidator = project / ".claude" / "agents" / "zikaron-consolidator.md"
    assert consolidator.exists() is installed.memory


def test_without_the_flag_an_install_writes_what_memory_writes(tmp_path: Path) -> None:
    plain, selected = tmp_path / "plain", tmp_path / "selected"
    for root in (plain, selected):
        (root / ".claude").mkdir(parents=True)
    assert _install(plain) == 0
    assert _install(selected, "--components", "memory") == 0
    assert _tree(plain) == _tree(selected)


def test_a_memory_start_entry_is_the_command_alone() -> None:
    commands = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))
    entry = {
        "hooks": [
            {
                "type": "command",
                "command": "/venv/bin/zikaron-hook",
                "timeout": HOOK_TIMEOUT_SECONDS,
            }
        ]
    }
    assert claude_hooks_value(commands) == {
        "SessionStart": [entry],
        "UserPromptSubmit": [entry],
        "SubagentStart": [entry],
    }


def test_each_guard_entry_states_its_timeout_and_its_matcher(
    project: Path, commands: Commands
) -> None:
    assert _install(project, "--components", "guards") == 0
    hooks = _hooks(project)
    for hook in GUARDS:
        (group,) = hooks[hook.trigger]
        assert group["matcher"] == hook.matcher
        assert group["hooks"] == [
            {
                "type": "command",
                "command": shlex.quote(str(commands.guard)),
                "timeout": TIMEOUT_SECONDS,
            }
        ]


def test_the_guard_timeout_is_the_one_the_design_states() -> None:
    design = (Path(__file__).resolve().parent.parent / "design" / "edit-guards.md").read_text(
        encoding="utf-8"
    )
    assert f"**Each guard entry states its `timeout`: {TIMEOUT_SECONDS} s**" in design


def test_a_guards_only_install_writes_only_hooks(project: Path) -> None:
    assert _install(project, "--components", "guards") == 0
    assert set(_settings(project)) == {"hooks"}
    assert sorted(_tree(project)) == [".claude/settings.local.json"]


def test_guards_over_memory_leave_the_approvals_byte_identical(project: Path) -> None:
    assert _install(project) == 0
    before = _settings(project)
    assert _install(project, "--components", "guards") == 0
    after = _settings(project)
    for key in ("enabledMcpjsonServers", "permissions"):
        assert json.dumps(after[key]) == json.dumps(before[key])
    assert _hooks(project)["UserPromptSubmit"] == before["hooks"]["UserPromptSubmit"]


def test_memory_over_guards_leaves_the_guard_groups_byte_identical(project: Path) -> None:
    assert _install(project, "--components", "guards") == 0
    before = _hooks(project)
    assert _install(project) == 0
    after = _hooks(project)
    for hook in GUARDS:
        assert json.dumps(after[hook.trigger]) == json.dumps(before[hook.trigger])


@pytest.mark.parametrize("selection", ["guards", "both"])
def test_a_users_own_tool_hooks_survive_with_or_without_our_matcher(
    project: Path, selection: str
) -> None:
    path = project / ".claude" / "settings.local.json"
    path.write_text(
        json.dumps(
            {"hooks": {"PreToolUse": [USER_PRE_TOOL_USE], "PostToolUse": [USER_POST_TOOL_USE]}}
        )
    )
    assert _install(project, "--components", selection) == 0
    hooks = _hooks(project)
    assert hooks["PreToolUse"][0] == USER_PRE_TOOL_USE
    assert hooks["PostToolUse"][0] == USER_POST_TOOL_USE
    assert len(hooks["PreToolUse"]) == len(hooks["PostToolUse"]) == 2


def test_an_older_memory_install_is_upgraded_on_the_start_entries_only(
    project: Path, commands: Commands
) -> None:
    older = {"hooks": [{"type": "command", "command": str(commands.hook), "timeout": 30}]}
    path = project / ".claude" / "settings.local.json"
    path.write_text(
        json.dumps(
            {"hooks": {t: [older] for t in ("SessionStart", "UserPromptSubmit", "SubagentStart")}}
        )
    )
    assert _install(project, "--components", "guards") == 0
    hooks = _hooks(project)
    assert hooks["UserPromptSubmit"] == [older]
    for trigger in START_TRIGGERS:
        (group,) = hooks[trigger]
        assert group["hooks"][0]["timeout"] == HOOK_TIMEOUT_SECONDS
        assert group["hooks"][0]["command"].endswith("--components both")


def test_an_unquoted_path_from_before_quoting_is_replaced_not_duplicated(
    project: Path, commands: Commands
) -> None:
    unquoted = {"hooks": [{"type": "command", "command": str(commands.hook), "timeout": 10}]}
    assert " " in str(commands.hook)
    path = project / ".claude" / "settings.local.json"
    path.write_text(json.dumps({"hooks": {"SessionStart": [unquoted]}}))
    assert _install(project) == 0
    assert _commands_of(_hooks(project)["SessionStart"]) == [shlex.quote(str(commands.hook))]


def test_a_users_command_the_shell_cannot_split_is_kept_as_theirs(project: Path) -> None:
    unsplittable = {"hooks": [{"type": "command", "command": 'echo "unterminated'}]}
    path = project / ".claude" / "settings.local.json"
    path.write_text(json.dumps({"hooks": {"SessionStart": [unsplittable]}}))
    assert _install(project, "--components", "guards") == 0
    assert _hooks(project)["SessionStart"][0] == unsplittable


def test_another_installs_guard_group_is_refused_without_force_and_replaced_with_it(
    project: Path, commands: Commands
) -> None:
    theirs = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "/elsewhere/bin/zikaron-guard", "timeout": 10}],
    }
    path = project / ".claude" / "settings.local.json"
    path.write_text(json.dumps({"hooks": {"PreToolUse": [theirs]}}))
    before = path.read_bytes()
    assert _install(project, "--components", "guards") == 1
    assert path.read_bytes() == before
    assert _install(project, "--components", "guards", "--force") == 0
    assert _commands_of(_hooks(project)["PreToolUse"]) == [shlex.quote(str(commands.guard))]


@pytest.mark.parametrize("selection", list(Components), ids=lambda s: s.value)
def test_print_only_writes_nothing_and_shows_the_selections_groups(
    project: Path, commands: Commands, selection: Components, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _install(project, "--components", selection.value, "--print-only") == 0
    assert _tree(project) == {}
    printed = capsys.readouterr().out
    assert (shlex.quote(str(commands.guard)) in printed) is selection.guards
    assert ("enabledMcpjsonServers" in printed) is selection.memory


@pytest.mark.parametrize(
    ("prior", "selection"),
    [(Components.MEMORY, Components.GUARDS), (Components.GUARDS, Components.MEMORY)],
)
def test_print_only_previews_the_start_union_the_install_would_write(
    project: Path,
    commands: Commands,
    prior: Components,
    selection: Components,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _install(project, "--components", prior.value) == 0
    before = _tree(project)
    capsys.readouterr()
    assert _install(project, "--components", selection.value, "--print-only") == 0
    assert _tree(project) == before
    both = " ".join((shlex.quote(str(commands.hook)), *Components.BOTH.arguments))
    assert json.dumps(both) in capsys.readouterr().out


def test_print_only_over_an_unreadable_settings_file_previews_this_runs_selection(
    project: Path, commands: Commands, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / ".claude" / "settings.local.json").write_text("{not json")
    assert _install(project, "--components", "guards", "--print-only") == 0
    guards = " ".join((shlex.quote(str(commands.hook)), *Components.GUARDS.arguments))
    assert json.dumps(guards) in capsys.readouterr().out


@pytest.mark.parametrize("selection", ["guards", "both"])
def test_kiro_refuses_the_guards_before_writing_anything(
    tmp_path: Path, selection: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "kiro-project"
    (root / ".kiro").mkdir(parents=True)
    status = main(["--project", str(root), "--harness", "kiro", "--components", selection])
    assert status == 1
    assert "does not offer" in capsys.readouterr().err
    assert _tree(root) == {}


def test_model_is_refused_under_guards_and_accepted_under_both(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _install(project, "--components", "guards", "--model", "opus") == 1
    assert "ships no consolidator" in capsys.readouterr().err
    assert _tree(project) == {}
    assert _install(project, "--components", "both", "--model", "opus") == 0
    consolidator = project / ".claude" / "agents" / "zikaron-consolidator.md"
    assert "model: opus" in consolidator.read_text(encoding="utf-8")


def test_no_trust_tools_is_a_no_op_under_guards(tmp_path: Path) -> None:
    trusting, untrusting = tmp_path / "a", tmp_path / "b"
    for root in (trusting, untrusting):
        (root / ".claude").mkdir(parents=True)
    assert _install(trusting, "--components", "guards") == 0
    assert _install(untrusting, "--components", "guards", "--no-trust-tools") == 0
    assert _tree(trusting) == _tree(untrusting)


def test_a_guards_only_install_reports_none_of_the_memory_notes(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _install(project, "--components", "guards") == 0
    printed = capsys.readouterr().out
    assert "enabledMcpjsonServers" not in printed
    assert "consolidat" not in printed


@pytest.mark.parametrize(
    ("selection", "needed"),
    [
        (Components.MEMORY, ("zikaron-hook", "zikaron-mcp")),
        (Components.GUARDS, ("zikaron-hook", "zikaron-guard")),
        (Components.BOTH, ("zikaron-hook", "zikaron-mcp", "zikaron-guard")),
    ],
)
def test_missing_checks_only_the_scripts_the_selection_needs(
    tmp_path: Path, selection: Components, needed: tuple[str, ...]
) -> None:
    absent = Commands(hook=tmp_path / "zikaron-hook", mcp=tmp_path / "zikaron-mcp")
    assert tuple(path.name for path in absent.missing(selection)) == needed
