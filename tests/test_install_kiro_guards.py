"""The guards under kiro: the entries a selection writes into a kiro profile, and how a merge tells
one selection's entries from the other's (`design/guards.md` §5, `design/build-plan.md` §M41-2
item 7).

A selection owns the entries it writes: the memory store's two `zikaron-hook` entries, and the
guards' start entry, `zikaron-hook --components guards`, and their `zikaron-guard --harness kiro` on
the shell tool. An install replaces its own selection's entries and keeps the other's, and
recognizes an entry by its program's file name and its arguments, so another venv's is found.
"""

import json
import shlex
from pathlib import Path
from typing import Any, Final

import pytest

from zikaron.guard.limits import TIMEOUT_SECONDS as GUARD_TIMEOUT_SECONDS
from zikaron.guard.start_text import guard_start_text
from zikaron.harness.spec import KIRO
from zikaron.hook.components import Components
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS
from zikaron.hook.write_policy import WRITE_POLICY_PROMPT
from zikaron.install import harness
from zikaron.install.entries import Commands, hooks_array
from zikaron.install.main import main

_MEMORY_NAMES: Final = ("zikaron-SessionStart", "zikaron-UserPromptSubmit")
_GUARD_NAMES: Final = ("zikaron-guards-SessionStart", "zikaron-guards-PreToolUse")


def _scripts(directory: Path) -> Commands:
    directory.mkdir(parents=True, exist_ok=True)
    installed = Commands(hook=directory / "zikaron-hook", mcp=directory / "zikaron-mcp")
    for path in (installed.hook, installed.mcp, installed.guard):
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    return installed


@pytest.fixture(autouse=True)
def commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Commands:
    installed = _scripts(tmp_path / "venv bin")
    monkeypatch.setattr(Commands, "from_this_interpreter", classmethod(lambda _cls: installed))
    monkeypatch.setattr(harness, "binary_is_available", lambda _name: True)
    monkeypatch.setattr(harness, "installed_version", lambda: harness.MINIMUM_VERSION)
    shipped = frozenset({KIRO.consolidator_model, KIRO.documenter_model, KIRO.orchestrator_model})
    monkeypatch.setattr(harness, "available_model_ids", lambda: shipped)
    monkeypatch.setattr(harness, "validate_agent_config", lambda _path: None)
    return installed


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".kiro").mkdir(parents=True)
    return root


@pytest.fixture
def profile(project: Path) -> Path:
    path = project / "mine.json"
    path.write_text(json.dumps({"name": "mine", "permissions": {"rules": []}}), encoding="utf-8")
    return path


def _install(project: Path, *flags: str) -> int:
    return main(["--project", str(project), "--harness", "kiro", *flags])


def _document(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _names(path: Path) -> list[str]:
    return [entry["name"] for entry in _document(path)["hooks"]]


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestTheEntries:
    def test_the_guards_write_exactly_their_start_entry_and_their_shell_hook(
        self, commands: Commands
    ) -> None:
        """No `PostToolUse` entry: kiro has no re-read hook, since no post-tool output reaches its
        model."""
        start, shell = hooks_array(commands, Components.GUARDS)
        hook = shlex.quote(str(commands.hook))
        guard = shlex.quote(str(commands.guard))
        assert start == {
            "name": "zikaron-guards-SessionStart",
            "trigger": "SessionStart",
            "action": {"type": "command", "command": f"exec {hook} --components guards"},
            "timeout": HOOK_TIMEOUT_SECONDS,
        }
        assert shell == {
            "name": "zikaron-guards-PreToolUse",
            "trigger": "PreToolUse",
            "action": {"type": "command", "command": f"exec {guard} --harness kiro"},
            "timeout": GUARD_TIMEOUT_SECONDS,
            "matcher": "execute_bash",
        }

    @pytest.mark.parametrize(
        ("selection", "names"),
        [
            (Components.MEMORY, _MEMORY_NAMES),
            (Components.GUARDS, _GUARD_NAMES),
            (Components.BOTH, (*_MEMORY_NAMES, *_GUARD_NAMES)),
        ],
    )
    def test_each_selection_writes_its_own_entries(
        self, commands: Commands, selection: Components, names: tuple[str, ...]
    ) -> None:
        assert tuple(entry["name"] for entry in hooks_array(commands, selection)) == names

    def test_the_shell_hooks_matcher_is_the_tool_id_a_payload_carries(self) -> None:
        """kiro's payload names the shell tool `execute_bash`, which a matcher written as the
        selector `shell` would select by a different word (`research/kiro-v3-probe.md` §32, §48)."""
        assert KIRO.guards is not None
        assert KIRO.guards.command.matcher == KIRO.tool_ids.shell

    def test_each_start_entrys_output_fits_kiros_per_hook_budget(self, commands: Commands) -> None:
        """kiro cuts each hook at its budget, so the policy and the guard start text are printed by
        two entries; printed by one they would not fit (`research/kiro-v3-probe.md` §21, §49)."""
        starts = [
            entry
            for entry in hooks_array(commands, Components.BOTH)
            if entry["trigger"] == KIRO.spawn_trigger
        ]
        assert len(starts) == len(("memory", "guards"))
        for entry in starts:
            action = entry["action"]
            assert isinstance(action, dict)
            selection = Components.from_arguments(shlex.split(action["command"])[2:])
            printed = "\n\n".join(
                [
                    *([WRITE_POLICY_PROMPT] if selection.memory else []),
                    *([guard_start_text(KIRO)] if selection.guards else []),
                ]
            )
            assert not KIRO.exceeds_injection_budget(printed), entry["name"]
        assert KIRO.exceeds_injection_budget(f"{WRITE_POLICY_PROMPT}\n\n{guard_start_text(KIRO)}")


class TestAGuardsOnlyInstall:
    def test_without_an_agent_it_is_refused_and_writes_nothing(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """It would write nothing and exit 0, the inert success an install refuses."""
        assert _install(project, "--components", "guards") == 1
        refusal = capsys.readouterr().err
        assert "--agent" in refusal
        assert "--print-only" in refusal
        assert _tree(project) == {}

    def test_print_only_prints_its_entries_without_an_agent(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _install(project, "--components", "guards", "--print-only") == 0
        printed = capsys.readouterr().out
        assert "zikaron-guards-PreToolUse" in printed
        assert "mcpServers" not in printed
        assert _tree(project) == {}

    def test_it_writes_its_two_entries_into_the_profile_and_nothing_else(
        self, project: Path, profile: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = _document(profile)
        assert _install(project, "--components", "guards", "--agent", str(profile)) == 0
        after = _document(profile)
        assert [entry["name"] for entry in after.pop("hooks")] == list(_GUARD_NAMES)
        assert after == before
        assert sorted(_tree(project)) == ["mine.json", "mine.json.bak"]
        printed = capsys.readouterr().out
        assert "V3 agent engine" not in printed
        assert "`subagent`" not in printed

    def test_it_checks_no_model(
        self, project: Path, profile: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """It ships no agent, so it has no model for kiro's list to refuse."""
        monkeypatch.setattr(harness, "available_model_ids", frozenset)
        assert _install(project, "--components", "guards", "--agent", str(profile)) == 0


class TestOwnershipIsPerSelection:
    @pytest.mark.parametrize("selection", ["memory", "guards", "both"])
    def test_a_re_run_over_its_own_install_writes_nothing(
        self, project: Path, profile: Path, selection: str
    ) -> None:
        assert _install(project, "--components", selection, "--agent", str(profile)) == 0
        before = profile.read_bytes()
        assert _install(project, "--components", selection, "--agent", str(profile)) == 0
        assert profile.read_bytes() == before

    @pytest.mark.parametrize(
        ("first", "second", "kept"),
        [
            ("both", "memory", _GUARD_NAMES),
            ("guards", "memory", _GUARD_NAMES),
            ("both", "guards", _MEMORY_NAMES),
            ("memory", "guards", _MEMORY_NAMES),
        ],
    )
    def test_one_selection_keeps_the_others_entries_untouched(
        self, project: Path, profile: Path, first: str, second: str, kept: tuple[str, ...]
    ) -> None:
        assert _install(project, "--components", first, "--agent", str(profile)) == 0
        others = [entry for entry in _document(profile)["hooks"] if entry["name"] in kept]
        assert _install(project, "--components", second, "--agent", str(profile)) == 0
        after = _document(profile)["hooks"]
        assert [entry for entry in after if entry["name"] in kept] == others
        assert sorted(_names(profile)) == sorted({*_MEMORY_NAMES, *_GUARD_NAMES})

    def test_another_venvs_guard_entries_are_refused_without_force(
        self, tmp_path: Path, project: Path, profile: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Recognized by the program's file name, so a second install from another venv is found
        rather than written beside the first."""
        elsewhere = _scripts(tmp_path / "elsewhere")
        document = _document(profile)
        document["hooks"] = hooks_array(elsewhere, Components.GUARDS)
        profile.write_text(json.dumps(document), encoding="utf-8")
        before = profile.read_bytes()
        assert _install(project, "--components", "guards", "--agent", str(profile)) == 1
        assert "differ from what this install would write" in capsys.readouterr().err
        assert profile.read_bytes() == before
        assert _install(project, "--components", "guards", "--agent", str(profile), "--force") == 0
        assert _names(profile) == list(_GUARD_NAMES)

    def test_another_venvs_entries_of_the_other_selection_are_not_compared(
        self, tmp_path: Path, project: Path, profile: Path
    ) -> None:
        elsewhere = _scripts(tmp_path / "elsewhere")
        document = _document(profile)
        theirs = hooks_array(elsewhere, Components.MEMORY)
        document["hooks"] = theirs
        profile.write_text(json.dumps(document), encoding="utf-8")
        assert _install(project, "--components", "guards", "--agent", str(profile)) == 0
        assert _document(profile)["hooks"][: len(theirs)] == theirs

    def test_an_entry_of_a_selection_found_without_its_name_is_still_that_selections(
        self, project: Path, profile: Path, commands: Commands
    ) -> None:
        """An entry renamed by hand is recognized by its trigger, its program and its arguments, so
        it is replaced rather than left beside the new one."""
        (start, _shell) = hooks_array(commands, Components.GUARDS)
        document = _document(profile)
        document["hooks"] = [{**start, "name": "renamed"}]
        profile.write_text(json.dumps(document), encoding="utf-8")
        assert _install(project, "--components", "guards", "--agent", str(profile)) == 0
        assert _names(profile) == list(_GUARD_NAMES)

    def test_object_form_memory_hooks_are_kept_in_the_array_form_under_a_guards_install(
        self, project: Path, profile: Path, commands: Commands
    ) -> None:
        """An object-format `hooks` holding the memory store's entries, which kiro's upgrader
        leaves in a profile that has `permissions`, is rewritten in the array form, and a guards
        install keeps those entries."""
        document = _document(profile)
        command = f"exec {shlex.quote(str(commands.hook))}"
        document["hooks"] = {"agentSpawn": [{"command": command}]}
        profile.write_text(json.dumps(document), encoding="utf-8")
        assert _install(project, "--components", "guards", "--agent", str(profile)) == 0
        hooks = _document(profile)["hooks"]
        assert isinstance(hooks, list)
        assert hooks[0]["trigger"] == "SessionStart"
        assert hooks[0]["action"]["command"] == command
        assert [entry["name"] for entry in hooks[1:]] == list(_GUARD_NAMES)
