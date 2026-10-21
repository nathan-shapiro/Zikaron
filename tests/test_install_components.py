"""`--components`: the memory store, the guards, or both (`design/guards.md` §5).

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
from zikaron.harness.spec import CLAUDE_CODE, Guards, SearchReminder
from zikaron.hook.components import Components
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS
from zikaron.install import harness
from zikaron.install.entries import Commands, claude_hooks_value
from zikaron.install.main import main


def _guards() -> Guards:
    guards = CLAUDE_CODE.guards
    assert guards is not None
    return guards


def _reminder() -> SearchReminder:
    reminder = CLAUDE_CODE.search_reminder
    assert reminder is not None
    return reminder


GUARDS = _guards()
REMINDER = _reminder()
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


def _scripts_of(groups: list[Any]) -> list[str]:
    """Each group's one Zikaron script, by name, in the order the groups stand."""
    return [Path(shlex.split(group["hooks"][0]["command"])[0]).name for group in groups]


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
        *(["UserPromptSubmit", REMINDER.trigger] if installed.memory else []),
        *([GUARDS.command.trigger, GUARDS.reread.trigger] if installed.guards else []),
    }
    assert set(hooks) == expected_triggers
    start = " ".join((shlex.quote(str(commands.hook)), *installed.arguments))
    for trigger in START_TRIGGERS:
        assert _commands_of(hooks[trigger]) == [start]
    shared = sorted(_scripts_of(hooks.get(REMINDER.trigger, [])))
    assert shared == sorted(
        [*(["zikaron-hook"] if installed.memory else []), *(["zikaron-guard"] * installed.guards)]
    )
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
    reminder = {
        "matcher": "Grep|Glob|Bash",
        "hooks": [
            {
                "type": "command",
                "if": condition,
                "command": "/venv/bin/zikaron-hook",
                "timeout": HOOK_TIMEOUT_SECONDS,
            }
            for condition in ("Grep", "Glob", "Bash(*grep *)", "Bash(rg *)")
        ],
    }
    assert claude_hooks_value(commands) == {
        "SessionStart": [entry],
        "UserPromptSubmit": [entry],
        "SubagentStart": [entry],
        "PostToolUse": [reminder],
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
    design = (Path(__file__).resolve().parent.parent / "design" / "guards.md").read_text(
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
        assert json.dumps(after[hook.trigger][0]) == json.dumps(before[hook.trigger][0])


@pytest.mark.parametrize("selection", ["memory", "guards", "both"])
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
    installed = Components(selection)
    assert hooks["PreToolUse"][0] == USER_PRE_TOOL_USE
    assert hooks["PostToolUse"][0] == USER_POST_TOOL_USE
    assert len(hooks["PreToolUse"]) == 1 + installed.guards
    assert len(hooks["PostToolUse"]) == 1 + installed.memory + installed.guards


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


@pytest.mark.parametrize("selection", ["guards", "both"])
def test_an_older_bash_only_guard_group_is_replaced_by_the_widened_matcher(
    project: Path, commands: Commands, selection: str
) -> None:
    command = shlex.quote(str(commands.guard))
    older = {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": command, "timeout": TIMEOUT_SECONDS}],
    }
    path = project / ".claude" / "settings.local.json"
    path.write_text(json.dumps({"hooks": {"PreToolUse": [older]}}))
    assert _install(project, "--components", selection) == 0
    (group,) = _hooks(project)[GUARDS.command.trigger]
    assert group == {**older, "matcher": GUARDS.command.matcher}
    assert GUARDS.command.tools == frozenset({"Bash", "Monitor"})


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
    assert "ships no agent" in capsys.readouterr().err
    assert _tree(project) == {}
    assert _install(project, "--components", "both", "--model", "opus") == 0
    for agent in ("zikaron-consolidator", "zikaron-documenter", "zikaron-code-orchestrator"):
        definition = project / ".claude" / "agents" / f"{agent}.md"
        assert "model: opus" in definition.read_text(encoding="utf-8")


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


def _write_settings(project: Path, document: dict[str, Any]) -> None:
    (project / ".claude" / "settings.local.json").write_text(json.dumps(document))


class TestTheSharedPostToolUseTrigger:
    """Both selections write the reminder's trigger: the memory store its search reminder, the
    guards their re-read nudge. A group belongs to the selection whose program it runs
    (`design/guards.md` §5), and ownership is membership, not list equality."""

    def _shared(self, project: Path) -> list[Any]:
        groups = _hooks(project)[REMINDER.trigger]
        assert isinstance(groups, list)
        return groups

    def _ours(self, project: Path) -> dict[str, Any]:
        (group,) = [g for g in self._shared(project) if _scripts_of([g]) == ["zikaron-hook"]]
        assert isinstance(group, dict)
        return group

    @pytest.mark.parametrize("force", [False, True], ids=["plain", "forced"])
    @pytest.mark.parametrize(
        ("first", "second"), [("guards", "memory"), ("memory", "guards"), ("both", "both")]
    )
    def test_each_selection_keeps_the_other_s_group(
        self,
        project: Path,
        capsys: pytest.CaptureFixture[str],
        first: str,
        second: str,
        force: bool,
    ) -> None:
        """The other selection's group is copied, not replaced, so no note reports it."""
        assert _install(project, "--components", first) == 0
        capsys.readouterr()
        assert _install(project, "--components", second, *(["--force"] * force)) == 0
        assert sorted(_scripts_of(self._shared(project))) == ["zikaron-guard", "zikaron-hook"]
        out = capsys.readouterr().out
        assert "--force replaced Zikaron's hook" not in out
        assert "differed from what this install writes" not in out

    @pytest.mark.parametrize(
        ("first", "then"),
        [("memory", "memory"), ("both", "both"), ("both", "memory"), ("both", "guards")],
    )
    def test_a_rerun_that_changes_nothing_writes_nothing(
        self, project: Path, first: str, then: str
    ) -> None:
        assert _install(project, "--components", first) == 0
        before = _tree(project)
        assert _install(project, "--components", then) == 0
        assert _tree(project) == before
        assert not (project / ".claude" / "settings.local.json.bak").exists()

    @pytest.mark.parametrize("change", ["fewer", "more"])
    def test_our_group_with_another_set_of_handlers_is_rewritten_and_reported(
        self, project: Path, capsys: pytest.CaptureFixture[str], change: str
    ) -> None:
        assert _install(project) == 0
        settings = _settings(project)
        (group,) = settings["hooks"][REMINDER.trigger]
        handlers = group["hooks"]
        group["hooks"] = handlers[:-1] if change == "fewer" else [*handlers, handlers[0]]
        _write_settings(project, settings)
        capsys.readouterr()
        assert _install(project) == 0
        assert self._ours(project) == claude_hooks_value(_commands())[REMINDER.trigger][0]
        assert "differed from what this install writes" in capsys.readouterr().out

    def test_our_group_beside_a_user_s_command_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _install(project) == 0
        settings = _settings(project)
        settings["hooks"][REMINDER.trigger][0]["hooks"].append(
            {"type": "command", "command": "/u/mine.sh"}
        )
        _write_settings(project, settings)
        capsys.readouterr()
        assert _install(project) == 1
        assert REMINDER.trigger in capsys.readouterr().err

    def test_under_force_it_is_replaced_and_the_user_s_command_reported(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _install(project) == 0
        settings = _settings(project)
        settings["hooks"][REMINDER.trigger][0]["hooks"].append(
            {"type": "command", "command": "/u/mine.sh"}
        )
        _write_settings(project, settings)
        capsys.readouterr()
        assert _install(project, "--force") == 0
        assert "/u/mine.sh" not in json.dumps(self._shared(project))
        assert "dropping /u/mine.sh" in capsys.readouterr().out

    def test_another_install_s_group_of_this_selection_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        theirs = _another_installs(claude_hooks_value(_commands())[REMINDER.trigger][0])
        _write_settings(project, {"hooks": {REMINDER.trigger: [theirs]}})
        assert _install(project) == 1
        assert "/other/venv/bin/zikaron-hook" in capsys.readouterr().err

    def test_another_install_s_group_of_this_selection_is_replaced_under_force(
        self, project: Path
    ) -> None:
        theirs = _another_installs(claude_hooks_value(_commands())[REMINDER.trigger][0])
        _write_settings(project, {"hooks": {REMINDER.trigger: [theirs]}})
        assert _install(project, "--force") == 0
        assert "/other/venv" not in json.dumps(self._shared(project))

    def test_another_install_s_group_of_the_other_selection_is_copied_verbatim(
        self, project: Path
    ) -> None:
        """An install touches only its own selection, whoever installed the other."""
        nudge = {
            "matcher": GUARDS.reread.matcher,
            "hooks": [{"type": "command", "command": "/other/venv/bin/zikaron-guard"}],
        }
        _write_settings(project, {"hooks": {GUARDS.reread.trigger: [nudge]}})
        assert _install(project) == 0
        assert self._shared(project)[0] == nudge
        assert _scripts_of(self._shared(project)) == ["zikaron-guard", "zikaron-hook"]


def _commands() -> Commands:
    return Commands.from_this_interpreter()


def _another_installs(group: dict[str, Any]) -> dict[str, Any]:
    """`group` as another install at another path would have written it."""
    return {
        **group,
        "hooks": [
            {**handler, "command": "/other/venv/bin/zikaron-hook"} for handler in group["hooks"]
        ],
    }
