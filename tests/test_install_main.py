"""`python -m zikaron.install`: the order of its checks, and what it prints.

The load-bearing property is **nothing is written until every check has passed**. A half-installed
project whose consolidator names a model the harness will silently substitute is exactly the outcome
the model check exists to prevent, so a test that only asserted the error message would miss the
point entirely — every refusal test below also asserts the filesystem is untouched.
"""

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from zikaron.harness.spec import KIRO
from zikaron.install import harness
from zikaron.install.entries import MCP_SERVER_NAME, TOOL_SELECTOR, Commands, HookFormat
from zikaron.install.main import main
from zikaron.install.writer import Targets

_MODELS = frozenset({KIRO.consolidator_model, "claude-haiku-4.5"})


def _kiro_install(argv: list[str]) -> int:
    """`main` with the harness stated, which every test in this file assumes.

    Stated rather than left to `--harness auto`, and the reason is the behaviour under test
    elsewhere: `auto` **refuses** on a directory carrying neither `.kiro/` nor `.claude/`, which is
    exactly what a `tmp_path` project is. Passing it here would make every test in this file assert
    the resolution rule instead of the thing it is about; `tests/test_install_targets.py` asserts
    the resolution rule once, deliberately.
    """
    return main(["--harness", KIRO.harness.value, *argv])


def _snapshot(project: Path) -> dict[str, bytes]:
    """Every file under `project` with its bytes — the state a refusal must leave untouched.

    A whole-tree comparison rather than a check on the one file a test is about, because the defect
    these guard against is not a wrong error message: it is the two shipped files landing in a
    project whose merge was then refused.
    """
    return {
        str(path.relative_to(project)): path.read_bytes()
        for path in sorted(project.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(autouse=True)
def _installed_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Commands:
    """A `Commands` pair that exists on disk, since a missing command is its own refusal.

    Patched at `entries.Commands.from_this_interpreter` rather than by manufacturing a venv, because
    what this substitutes is "where pip put the console scripts" — a fact about the environment, not
    behaviour under test.
    """
    scripts = tmp_path / "venv-bin"
    scripts.mkdir()
    commands = Commands(hook=scripts / "zikaron-hook", mcp=scripts / "zikaron-mcp")
    for path in (commands.hook, commands.mcp):
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    monkeypatch.setattr(Commands, "from_this_interpreter", classmethod(lambda _cls: commands))
    return commands


@pytest.fixture(autouse=True)
def _harness_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real `kiro-cli` in the unit tier: these tests are about the command's own decisions."""
    monkeypatch.setattr(harness, "available_model_ids", lambda: _MODELS)
    monkeypatch.setattr(harness, "validate_agent_config", lambda _path: None)
    # Presence is answered too, and pinned rather than left to the machine: an unpinned check makes
    # this file pass on a workstation with kiro installed and refuse everything in a container,
    # which is a suite testing its environment rather than its code.
    monkeypatch.setattr(harness, "binary_is_available", lambda _name: True)


class TestASuccessfulInstall:
    def test_it_exits_zero_and_writes_both_artefacts(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        assert _kiro_install(["--project", str(project)]) == 0
        targets = Targets(project=project)
        assert targets.consolidator_config.is_file()
        assert targets.skill_file.is_file()

    def test_without_an_agent_it_prints_the_fragment_to_paste(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        _kiro_install(["--project", str(project)])
        printed = capsys.readouterr().out
        assert '"mcpServers"' in printed
        assert '"userPromptSubmit"' in printed
        assert "subagent" in printed

    def test_the_printed_fragment_is_valid_json_in_the_requested_format(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Printed for a human to paste into a JSON file, so it has to parse as JSON on its own."""
        project = tmp_path / "project"
        project.mkdir()
        _kiro_install(["--project", str(project), "--format", "array"])
        printed = capsys.readouterr().out
        fragment = json.loads(printed[printed.index("{") : printed.rindex("}") + 1])
        assert isinstance(fragment["hooks"], list)
        assert "10240" in printed, "an array install inherits the default, and is told so"

    def test_with_an_agent_it_merges_instead_of_printing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(json.dumps({"name": "mine", "tools": ["subagent"]}))
        assert _kiro_install(["--project", str(project), "--agent", str(agent)]) == 0
        merged = json.loads(agent.read_text())
        assert MCP_SERVER_NAME in merged["mcpServers"]
        assert TOOL_SELECTOR in merged["tools"]
        assert TOOL_SELECTOR in merged["allowedTools"], "memory writes would prompt every time"
        printed = capsys.readouterr().out
        assert "merged" in printed
        assert "backed up" in printed

    def test_a_second_run_says_what_it_kept_and_how_to_replace_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The output a user actually sees on re-running the installer, which is also the only place
        `--force` is suggested to them."""
        project = tmp_path / "project"
        project.mkdir()
        _kiro_install(["--project", str(project)])
        capsys.readouterr()
        assert _kiro_install(["--project", str(project)]) == 0
        printed = capsys.readouterr().out
        assert "kept" in printed
        assert "--force" in printed

    def test_a_config_from_another_install_is_reported_as_replaced(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """What a cloner of this repository sees: the tracked consolidator config names another
        machine's venv, and the install says it rewrote it rather than reporting success and leaving
        a consolidator that can never start.
        """
        project = tmp_path / "project"
        project.mkdir()
        stale = Targets(project=project).consolidator_config
        stale.parent.mkdir(parents=True)
        stale.write_text(
            json.dumps(
                {
                    "name": "zikaron-consolidator",
                    "mcpServers": {MCP_SERVER_NAME: {"command": "/another/venv/bin/zikaron-mcp"}},
                }
            )
        )
        assert _kiro_install(["--project", str(project)]) == 0
        printed = capsys.readouterr().out
        assert "replaced" in printed
        assert "differed from what this install ships" in printed

    def test_it_adds_the_consolidator_to_a_populated_crew_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The bug found in real use: the skill spawns the consolidator through `subagent`, and a
        config listing its own crew agents and not ours cannot spawn it at all."""
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(
            json.dumps(
                {
                    "name": "mine",
                    "toolsSettings": {"crew": {"availableAgents": ["helper-a"]}},
                }
            )
        )
        assert _kiro_install(["--project", str(project), "--agent", str(agent)]) == 0
        crew = json.loads(agent.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == ["helper-a", "zikaron-consolidator"]
        assert "trustedAgents" not in crew, "spawn trust is a separate grant, left to the user"
        printed = capsys.readouterr().out
        assert "availableAgents" in printed
        assert "ask your permission once" in printed

    def test_no_trust_tools_leaves_the_allowlist_alone_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(json.dumps({"name": "mine", "allowedTools": ["read"]}))
        assert (
            _kiro_install(["--project", str(project), "--agent", str(agent), "--no-trust-tools"])
            == 0
        )
        assert json.loads(agent.read_text())["allowedTools"] == ["read"]
        assert "ask your permission" in capsys.readouterr().out

    def test_the_model_can_be_overridden_for_a_comparison_run(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        assert _kiro_install(["--project", str(project), "--model", "claude-haiku-4.5"]) == 0
        written = json.loads(Targets(project=project).consolidator_config.read_text())
        assert written["model"] == "claude-haiku-4.5"

    def test_the_default_format_is_the_object_one(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(json.dumps({"name": "mine"}))
        _kiro_install(["--project", str(project), "--agent", str(agent)])
        assert isinstance(json.loads(agent.read_text())["hooks"], dict)
        assert HookFormat.OBJECT is HookFormat("object")


class TestTheDocumentedInvocation:
    def test_python_m_zikaron_install_is_runnable(self) -> None:
        """`python -m zikaron.install` is the invocation the install docs give, and it resolves a
        *package* — so it needs `__main__.py` to exist and to reach `main()`. Nothing else in the
        suite would notice that file being deleted, since every other test calls `main()` directly.

        `--help` rather than a real install: this asserts the entry point resolves and parses
        arguments, and the end-to-end tests cover what it does when it runs for real.
        """
        completed = subprocess.run(
            [sys.executable, "-m", "zikaron.install", "--help"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0
        assert "--agent" in completed.stdout
        assert "--model" in completed.stdout


class TestRefusalsHappenBeforeAnythingIsWritten:
    def test_an_unknown_model_is_refused_and_nothing_is_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        assert _kiro_install(["--project", str(project), "--model", "not-a-real-model"]) == 1
        assert not (project / ".kiro").exists()
        assert "not a model this harness offers" in capsys.readouterr().err

    def test_the_refusal_lists_what_is_available(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        _kiro_install(["--project", str(project), "--model", "nope"])
        assert KIRO.consolidator_model in capsys.readouterr().err

    def test_a_missing_console_script_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A hook whose command does not exist fails silently, because the harness does not surface
        a hook's stderr — so an install from a source tree with no `pip install` has to refuse.
        """
        absent = Commands(
            hook=tmp_path / "nowhere" / "zikaron-hook", mcp=tmp_path / "nowhere" / "m"
        )
        monkeypatch.setattr(Commands, "from_this_interpreter", classmethod(lambda _cls: absent))
        project = tmp_path / "project"
        project.mkdir()
        assert _kiro_install(["--project", str(project)]) == 1
        assert not (project / ".kiro").exists()
        assert "not installed for this interpreter" in capsys.readouterr().err

    def test_a_console_script_without_the_execute_bit_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Existing is not the same as runnable: a script copied out of a wheel by hand, or one on
        a filesystem mounted `noexec`, fails at the moment this check exists to protect.
        """
        scripts = tmp_path / "not-executable"
        scripts.mkdir()
        commands = Commands(hook=scripts / "zikaron-hook", mcp=scripts / "zikaron-mcp")
        for path in (commands.hook, commands.mcp):
            path.write_text("#!/bin/sh\n")
            path.chmod(0o644)
        monkeypatch.setattr(Commands, "from_this_interpreter", classmethod(lambda _cls: commands))
        project = tmp_path / "project"
        project.mkdir()
        assert _kiro_install(["--project", str(project)]) == 1
        assert not (project / ".kiro").exists()
        assert "not installed for this interpreter" in capsys.readouterr().err

    def test_a_project_that_is_not_a_directory_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _kiro_install(["--project", str(tmp_path / "does-not-exist")]) == 1
        assert "is not a directory" in capsys.readouterr().err

    def test_an_agent_path_that_does_not_exist_is_refused_before_writing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--agent` merges into a config the user already has; a typo in that path must not leave
        the shipped files installed and the entries silently unmerged."""
        project = tmp_path / "project"
        project.mkdir()
        assert (
            _kiro_install(["--project", str(project), "--agent", str(project / "typo.json")]) == 1
        )
        assert not (project / ".kiro").exists()
        assert "does not exist" in capsys.readouterr().err

    def test_a_missing_harness_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _raise() -> frozenset[str]:
            raise harness.InstallError("kiro-cli is not on PATH.")

        monkeypatch.setattr(harness, "available_model_ids", _raise)
        project = tmp_path / "project"
        project.mkdir()
        assert _kiro_install(["--project", str(project)]) == 1
        assert not (project / ".kiro").exists()
        assert "not on PATH" in capsys.readouterr().err


class TestNothingIsWrittenWhenTheMergeIsRefused:
    """The ordering the install contract states, asserted where it is decided rather than only in
    the writer's own unit tests.

    Each case snapshots the whole project tree and compares it byte-for-byte afterwards, because the
    defect this guards against is not a wrong error message — it is the two shipped files landing
    in a project whose agent config was then refused, leaving a half-install nobody asked for.
    """

    def test_a_malformed_agent_config_leaves_the_project_untouched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text("{not json")
        before = _snapshot(project)
        assert _kiro_install(["--project", str(project), "--agent", str(agent)]) == 1
        assert _snapshot(project) == before
        assert not (project / ".kiro").exists()
        assert "not valid JSON" in capsys.readouterr().err

    def test_a_conflicting_zikaron_entry_leaves_the_project_untouched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(
            json.dumps(
                {
                    "name": "mine",
                    "mcpServers": {MCP_SERVER_NAME: {"command": "/another/venv/bin/zikaron-mcp"}},
                }
            )
        )
        before = _snapshot(project)
        assert _kiro_install(["--project", str(project), "--agent", str(agent)]) == 1
        assert _snapshot(project) == before
        assert "pointing somewhere else" in capsys.readouterr().err

    def test_a_blocked_backup_path_leaves_the_project_untouched(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The refusal that was discovered *after* the shipped files had been written, until the
        backup check moved into the preflight. A directory at `<config>.bak` is the cheapest way to
        force it.
        """
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(json.dumps({"name": "mine"}))
        (project / "mine.json.bak").mkdir()
        before = _snapshot(project)
        assert _kiro_install(["--project", str(project), "--agent", str(agent)]) == 1
        assert _snapshot(project) == before
        assert not (project / ".kiro").exists()
        assert "cannot be backed up" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("document", "expected"),
        [
            pytest.param({"name": "m", "hooks": 5}, "neither an object nor an array", id="hooks"),
            pytest.param(
                {"name": "m", "hooks": {"stop": {"command": "mine"}}},
                "hooks.stop",
                id="nested hooks",
            ),
            pytest.param({"name": "m", "tools": "read"}, "not an array", id="tools"),
            pytest.param(
                {"name": "m", "allowedTools": "read"},
                "`allowedTools` value that is not an array",
                id="allowedTools",
            ),
            pytest.param(
                {"name": "m", "toolsSettings": "nope"},
                "`toolsSettings` value that is not an object",
                id="toolsSettings",
            ),
            pytest.param(
                {"name": "m", "toolsSettings": {"crew": []}},
                "`toolsSettings.crew` value that is not an object",
                id="crew",
            ),
            pytest.param(
                {"name": "m", "toolsSettings": {"crew": {"availableAgents": "a"}}},
                "availableAgents",
                id="availableAgents",
            ),
            pytest.param(
                {
                    "name": "m",
                    "toolsSettings": {"crew": {"a": 1}, "agent_crew": {"b": 2}},
                },
                "both `toolsSettings.crew` and",
                id="both crew spellings",
            ),
            pytest.param(
                {"name": "m", "resources": "file://x"},
                "`resources` value that is not an array",
                id="resources",
            ),
            pytest.param(
                {
                    "name": "m",
                    "hooks": [
                        {
                            "name": "zikaron-agentSpawn",
                            "trigger": "stop",
                            "action": {"type": "command", "command": "/x/zikaron-hook"},
                        }
                    ],
                },
                "differ from what this install would write",
                id="reserved array name",
            ),
        ],
    )
    def test_every_unmergeable_shape_leaves_the_project_untouched(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        document: dict[str, object],
        expected: str,
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(json.dumps(document))
        before = _snapshot(project)
        assert _kiro_install(["--project", str(project), "--agent", str(agent)]) == 1
        assert _snapshot(project) == before
        assert not (project / ".kiro").exists()
        assert expected in capsys.readouterr().err


class TestPathShapesThatWouldOtherwiseLieOrCrash:
    """Predictable filesystem shapes, refused in the preflight rather than discovered mid-write."""

    def test_a_symlinked_agent_config_is_refused_with_its_target_named(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Publishing an atomic rewrite replaces the directory entry, which would sever a config
        managed as a link into a dotfile repository — leaving a new local file and the real one
        untouched and disconnected, with the install reporting success.
        """
        project = tmp_path / "project"
        project.mkdir()
        real = tmp_path / "dotfiles" / "mine.json"
        real.parent.mkdir()
        real.write_text(json.dumps({"name": "mine"}))
        link = project / "mine.json"
        link.symlink_to(real)
        before = real.read_text()
        assert _kiro_install(["--project", str(project), "--agent", str(link)]) == 1
        assert link.is_symlink()
        assert real.read_text() == before
        assert not (project / ".kiro").exists()
        printed = capsys.readouterr().err
        assert "is a symlink" in printed
        assert str(real) in printed

    def test_a_directory_where_the_skill_belongs_is_refused_rather_than_reported_as_kept(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reported as "kept", this exited 0 while no loadable skill existed anywhere."""
        project = tmp_path / "project"
        project.mkdir()
        skill = project / ".kiro" / "skills" / "zikaron-consolidate" / "SKILL.md"
        skill.mkdir(parents=True)
        assert _kiro_install(["--project", str(project)]) == 1
        assert "is not a regular file" in capsys.readouterr().err
        assert not (project / ".kiro" / "agents").exists()

    def test_a_dangling_symlink_at_the_skill_is_refused_rather_than_reported_as_kept(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`Path.exists()` is false for a dangling symlink, so this used to pass the preflight, be
        reported as "kept", and let the install exit 0 with no loadable skill anywhere.
        """
        project = tmp_path / "project"
        project.mkdir()
        skill = project / ".kiro" / "skills" / "zikaron-consolidate" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.symlink_to(project / "nothing-here.md")
        assert _kiro_install(["--project", str(project)]) == 1
        assert "is not a regular file" in capsys.readouterr().err
        assert not (project / ".kiro" / "agents").exists()

    def test_a_dangling_symlink_at_a_skill_ancestor_is_refused_before_anything_is_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        skills = project / ".kiro" / "skills"
        skills.parent.mkdir(parents=True)
        skills.symlink_to(project / "nowhere")
        before = _snapshot(project)
        assert _kiro_install(["--project", str(project)]) == 1
        assert _snapshot(project) == before
        assert "is not a directory" in capsys.readouterr().err

    def test_the_consolidator_config_cannot_be_chosen_as_the_primary_merge_target(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A plausible pick out of an agents directory, and it used to produce a working-looking
        install with consolidation silently broken: the consolidator's own config became a *primary*
        agent while keeping its identity and prompt, so its first `zikaron_next_group` had no tool.
        """
        project = tmp_path / "project"
        project.mkdir()
        _kiro_install(["--project", str(project)])
        consolidator = Targets(project=project).consolidator_config
        before = _snapshot(project)
        capsys.readouterr()
        assert _kiro_install(["--project", str(project), "--agent", str(consolidator)]) == 1
        assert _snapshot(project) == before
        assert "which this install writes itself" in capsys.readouterr().err

    def test_a_file_where_a_skill_directory_belongs_is_refused_before_anything_is_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """This used to write the consolidator config first and then raise `NotADirectoryError` from
        `mkdir(parents=True)` — a traceback and a half-install, from a path shape.
        """
        project = tmp_path / "project"
        project.mkdir()
        skills = project / ".kiro" / "skills"
        skills.parent.mkdir(parents=True)
        skills.write_text("a file where a directory belongs")
        assert _kiro_install(["--project", str(project)]) == 1
        assert "is not a directory" in capsys.readouterr().err
        assert not (project / ".kiro" / "agents").exists()


class TestTheWrittenCommandRunsThroughAShell:
    """The harness executes a hook `command` through `/bin/bash -c` — measured, together with the
    failure that follows: an unquoted path containing a space produced
    `/bin/bash: line 1: /home/me/My: No such file or directory` and exit 127, while the install
    itself
    had exited 0.

    So the assertion that matters is not the shape of the string but that a shell can run it, from a
    directory whose name is ordinary-but-awkward.
    """

    def test_a_scripts_directory_with_spaces_and_metacharacters_still_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scripts = tmp_path / "My Projects (v2)" / "bin"
        scripts.mkdir(parents=True)
        marker = tmp_path / "it-ran.marker"
        hook = scripts / "zikaron-hook"
        hook.write_text(f"#!/bin/sh\ncat >/dev/null\necho ran > {shlex.quote(str(marker))}\n")
        hook.chmod(0o755)
        mcp = scripts / "zikaron-mcp"
        mcp.write_text("#!/bin/sh\nexit 0\n")
        mcp.chmod(0o755)
        monkeypatch.setattr(
            Commands,
            "from_this_interpreter",
            classmethod(lambda _cls: Commands(hook=hook, mcp=mcp)),
        )
        project = tmp_path / "project"
        project.mkdir()
        agent = project / "mine.json"
        agent.write_text(json.dumps({"name": "mine"}))
        assert _kiro_install(["--project", str(project), "--agent", str(agent)]) == 0

        written = json.loads(agent.read_text())["hooks"]["userPromptSubmit"][0]["command"]
        completed = subprocess.run(  # noqa: S602 — a shell is exactly what is under test.
            written,
            shell=True,
            input="{}",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert marker.read_text().strip() == "ran"


class TestTheValidationReport:
    def test_a_complaint_about_what_we_wrote_is_printed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(harness, "validate_agent_config", lambda _path: "unknown field `toolz`")
        project = tmp_path / "project"
        project.mkdir()
        assert _kiro_install(["--project", str(project)]) == 0
        assert "unknown field `toolz`" in capsys.readouterr().out

    def test_only_json_files_are_validated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The skill is markdown; handing it to an agent-config validator would produce a complaint
        that means nothing."""
        asked: list[Path] = []

        def _record(path: Path) -> None:
            asked.append(path)

        monkeypatch.setattr(harness, "validate_agent_config", _record)
        project = tmp_path / "project"
        project.mkdir()
        _kiro_install(["--project", str(project)])
        assert asked == [Targets(project=project).consolidator_config]
