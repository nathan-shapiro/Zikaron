"""`zikaron.install.targets`: two harnesses, one installer, and the seam between them.

`design/harness.md` §"The installer's two targets" is normative. Three kinds of test live here and
they are not interchangeable:

- **A regression guard** that kiro's artefacts are byte-for-byte what the writer emitted when the
  fixture was last taken. The risk in changing a shared writer is that it quietly moves a working
  harness's output, and "we did not mean to" is not evidence. So the fixture is a snapshot, not a
  restatement of intent: it is **re-rendered through the installer's own functions** whenever the
  shipped text is deliberately changed, and its whole job is to make every *other* change red.
- **Format tests** that each Claude Code artefact parses as the thing the harness will try to read
  it as — including a real YAML parse of frontmatter the installer produces by string formatting.
- **Refusal tests**, which are the same discipline `test_install_main.py` applies to kiro, run
  against the new target: nothing is written when a refusal fires.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from zikaron.harness.spec import CLAUDE_CODE, KIRO
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS, TIMEOUT_MS
from zikaron.hook.write_policy import SUBAGENT_WRITE_POLICY_PROMPT
from zikaron.install import harness
from zikaron.install.assets import (
    CLAUDE_CODE_SPAWN_INSTRUCTION,
    KIRO_SPAWN_INSTRUCTION,
    identity_vocabulary,
    render,
    skill_markdown,
)
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    MCP_SERVER_NAME,
    Commands,
    HookFormat,
    claude_tool_vocabulary,
    consolidator_agent_config,
    hooks_array,
    hooks_object,
    mcp_servers_value,
)
from zikaron.install.harness import InstallError
from zikaron.install.main import main
from zikaron.install.targets import KiroTarget
from zikaron.install.writer import Plan
from zikaron.mcp.tool_names import ALL_TOOLS, CONSOLIDATOR_TOOLS, PRIMARY_TOOLS

_GOLDEN = Path(__file__).parent / "fixtures" / "kiro_artefacts.json"

_FIXTURE_COMMANDS = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))

#: Captured before the autouse fixture below replaces it, so the one test that must use the *real*
#: console-script paths can put them back. Everything else wants the fake: where pip put the scripts
#: is a fact about the environment, not behaviour under test.
_REAL_COMMANDS = Commands.from_this_interpreter

#: Captured before the autouse fixture answers it, so the one test that must consult the real
#: `PATH` can put it back.
_REAL_BINARY_IS_AVAILABLE = harness.binary_is_available


@pytest.fixture(autouse=True)
def installed_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Commands:
    """Console scripts that exist on disk, since a missing command is its own refusal."""
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
    """No real harness binary in the unit tier: these tests are about the installer's decisions.

    **Presence is pinned to true**, not left to the machine. Both harnesses' binaries happen to be
    installed on the workstation this was written on, so an unpinned check would pass here and
    refuse everything in a container — a suite whose result depends on what is on `PATH` is not
    testing the code. Tests that are *about* absence override this fixture explicitly.
    """
    monkeypatch.setattr(
        harness, "available_model_ids", lambda: frozenset({KIRO.consolidator_model})
    )
    monkeypatch.setattr(harness, "validate_agent_config", lambda _path: None)
    monkeypatch.setattr(harness, "binary_is_available", lambda _name: True)


@pytest.fixture(autouse=True)
def _no_inherited_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CLAUDECODE` is set in the environment that runs this suite when it runs under Claude Code.

    Left alone, harness resolution would read the *test runner's* harness and the refusal tests
    below would silently stop testing a refusal — passing for a reason that has nothing to do with
    the code. Cleared here so every test states its own evidence.
    """
    monkeypatch.delenv("CLAUDECODE", raising=False)


def _project(tmp_path: Path, *, dotdirs: tuple[str, ...] = ()) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    for name in dotdirs:
        (project / name).mkdir(exist_ok=True)
    return project


def _claude_paths(project: Path) -> dict[str, Path]:
    return {
        "settings": project / ".claude" / "settings.local.json",
        "mcp": project / ".mcp.json",
        "agent": project / ".claude" / "agents" / f"{CONSOLIDATOR_AGENT_NAME}.md",
        "skill": project / ".claude" / "skills" / "zikaron-consolidate" / "SKILL.md",
    }


@pytest.fixture(scope="module")
def golden() -> dict[str, object]:
    """Kiro's artefacts as they stand, captured by running the code that produces them.

    Module-scoped and free-standing rather than a class-scoped method, which pytest deprecates.
    """
    loaded = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _frontmatter(path: Path) -> dict[str, object]:
    """The YAML frontmatter of a Markdown artefact, parsed by something that did not write it."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "frontmatter must open on the very first line"
    _, raw, _body = text.split("---\n", 2)
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict)
    return parsed


class TestKiroArtefactsChangeOnlyWhenSomebodyMeansThemTo:
    """Byte-for-byte, against a captured snapshot of what this code produces.

    **What it catches is drift nobody intended**, and the failure it was written for is real:
    everything kiro ships travels through a `HarnessTarget` and a prose renderer, both written
    while looking at the Claude Code case — which is exactly the condition under which a working
    harness's output shifts by a character nobody notices. It caught one: the kiro spawn
    instruction gained a line break purely from how a constant was wrapped in the source.

    **What it cannot catch is a change made on purpose**, because the remedy for a deliberate one
    is to re-capture the snapshot, and a re-captured snapshot agrees with the code by
    construction. The snapshot was first taken from a commit that predated the renderer, which made
    it independent evidence; renaming every tool to carry its subsystem changed three of its six
    entries deliberately, and re-taking it spent that independence. It is worth saying which guard
    remains: this pins that kiro's shipped prose does not move *by accident*, and nothing here
    pins that a deliberate move was correct.

    **Re-capturing is the remedy for a deliberate change, and it is done one entry at a time.**
    Compare every entry by *value* first and rewrite only what actually moved, preserving the
    file's `ensure_ascii` style: a reformatted snapshot hides which entry changed, which is the one
    thing this fixture exists to show.
    """

    def test_the_consolidator_config_is_identical(self, golden: dict[str, object]) -> None:
        assert (
            consolidator_agent_config(_FIXTURE_COMMANDS, model="a-model")
            == golden["consolidator_agent_config"]
        )

    def test_the_bytes_the_target_would_write_are_identical(
        self, tmp_path: Path, golden: dict[str, object]
    ) -> None:
        """**The parsed-dict comparison above is not enough**: the fixture
        was even captured with `sort_keys=True`, so key order is provably not what it pins, while
        the bytes on disk come from `KiroTarget.shipped_files`' own `json.dumps(..., indent=2)` plus
        a trailing newline. A change to the indent, the newline, or a move to sorted keys would ship
        different bytes to every existing install — each re-run then reporting "differed …
        rewritten" — and pass that test.

        Intent 2 says byte-for-byte, so this asserts the string `shipped_files` actually returns.
        """
        plan = Plan(
            project=tmp_path,
            commands=_FIXTURE_COMMANDS,
            model="a-model",
            hook_format=HookFormat.OBJECT,
            force=False,
            trust_tools=True,
        )
        by_name = {
            shipped.path.name: shipped.content for shipped in KiroTarget().shipped_files(plan)
        }
        assert by_name[f"{CONSOLIDATOR_AGENT_NAME}.json"] == golden["consolidator_config_bytes"]
        assert by_name["SKILL.md"] == golden["skill_markdown"]

    def test_the_skill_is_identical(self, golden: dict[str, object]) -> None:
        rendered = skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION)
        assert rendered == golden["skill_markdown"]

    def test_both_hook_formats_are_identical(self, golden: dict[str, object]) -> None:
        assert hooks_object(_FIXTURE_COMMANDS) == golden["hooks_object"]
        assert hooks_array(_FIXTURE_COMMANDS) == golden["hooks_array"]

    def test_the_mcp_server_entry_is_identical(self, golden: dict[str, object]) -> None:
        assert mcp_servers_value(_FIXTURE_COMMANDS, mode="primary") == golden["mcp_servers"]


class TestHarnessResolution:
    """`--harness auto` refuses rather than guessing, which is the point of it.

    `harness.detect.current_harness` answers a *different* question — "which harness am I running
    under" — and falls back to kiro when the marker is absent, because kiro exports none. Inheriting
    that here would write kiro artefacts into a Claude Code project from a plain terminal and exit
    0: a working-looking install with no Zikaron tools anywhere.
    """

    def test_explicit_beats_every_kind_of_evidence(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".kiro",))
        assert main(["--project", str(project), "--harness", CLAUDE_CODE.harness.value]) == 0
        assert _claude_paths(project)["mcp"].is_file()

    def test_auto_reads_a_lone_claude_directory(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        assert _claude_paths(project)["mcp"].is_file()

    def test_auto_reads_a_lone_kiro_directory(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".kiro",))
        assert main(["--project", str(project)]) == 0
        assert (project / ".kiro" / "agents" / f"{CONSOLIDATOR_AGENT_NAME}.json").is_file()

    def test_auto_refuses_when_both_are_present(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path, dotdirs=(".kiro", ".claude"))
        assert main(["--project", str(project)]) == 1
        error = capsys.readouterr().err
        assert "both .kiro/ and .claude/" in error
        assert not _claude_paths(project)["mcp"].exists()

    def test_auto_refuses_when_nothing_says(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path)
        assert main(["--project", str(project)]) == 1
        assert "neither .kiro/ nor .claude/" in capsys.readouterr().err

    def test_the_refusal_names_both_values_a_user_could_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A refusal a user cannot act on is a worse outcome than the guess it replaced."""
        main(["--project", str(_project(tmp_path))])
        error = capsys.readouterr().err
        assert f"--harness {KIRO.harness.value}" in error
        assert f"--harness {CLAUDE_CODE.harness.value}" in error

    def test_the_environment_marker_decides_only_when_the_project_does_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Project evidence outranks the marker: the install is *for* the project, not for the
        terminal it was launched from."""
        monkeypatch.setenv("CLAUDECODE", "1")
        bare = _project(tmp_path / "bare")
        assert main(["--project", str(bare)]) == 0
        assert _claude_paths(bare)["mcp"].is_file()

        kiro_project = _project(tmp_path / "kiro", dotdirs=(".kiro",))
        assert main(["--project", str(kiro_project)]) == 0
        assert not _claude_paths(kiro_project)["mcp"].exists()


class TestTheAgentFlagIsKiroOnly:
    def test_it_is_refused_rather_than_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Ignoring it would discard the one instruction the user gave about their config."""
        project = _project(tmp_path, dotdirs=(".claude",))
        config = project / "agent.json"
        config.write_text("{}", encoding="utf-8")
        assert main(["--project", str(project), "--agent", str(config)]) == 1
        error = capsys.readouterr().err
        assert "--agent has no meaning" in error
        assert ".mcp.json" in error

    def test_nothing_is_written_when_it_is_refused(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        config = project / "agent.json"
        config.write_text("{}", encoding="utf-8")
        main(["--project", str(project), "--agent", str(config)])
        assert not _claude_paths(project)["agent"].exists()
        assert not _claude_paths(project)["mcp"].exists()


class TestACleanClaudeCodeInstall:
    @pytest.fixture
    def installed(self, tmp_path: Path) -> Path:
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        return project

    def test_it_writes_exactly_the_four_artefacts(self, installed: Path) -> None:
        for name, path in _claude_paths(installed).items():
            assert path.is_file(), name

    def test_the_settings_file_is_json_and_carries_all_three_triggers(
        self, installed: Path
    ) -> None:
        """Three, not two. `SubagentStart` has no kiro counterpart and is not optional: it carries
        the write-policy-per-subagent path behind it, and registering only kiro's two triggers
        would leave that path dead with nothing anywhere failing."""
        document = json.loads(_claude_paths(installed)["settings"].read_text(encoding="utf-8"))
        assert set(document["hooks"]) == {"SessionStart", "UserPromptSubmit", "SubagentStart"}

    def test_the_mcp_file_is_json_and_registers_both_modes(self, installed: Path) -> None:
        """Two servers, session-wide. A server must be registered session-wide to be reachable by
        any subagent at all, so the consolidator's cannot live inside the consolidator's own
        definition the way it does under kiro."""
        servers = json.loads(_claude_paths(installed)["mcp"].read_text(encoding="utf-8"))
        assert set(servers["mcpServers"]) == {MCP_SERVER_NAME, CONSOLIDATOR_AGENT_NAME}
        assert servers["mcpServers"][MCP_SERVER_NAME]["args"] == ["--mode", "primary"]
        assert servers["mcpServers"][CONSOLIDATOR_AGENT_NAME]["args"] == ["--mode", "consolidator"]

    def test_both_markdown_artefacts_have_frontmatter_that_actually_parses(
        self, installed: Path
    ) -> None:
        """Parsed with PyYAML, which did not write it. The installer emits this frontmatter by
        string formatting, so an unquoted `: ` appearing in a description would silently produce a
        *different* YAML document rather than an invalid one — and the harness would read a mangled
        agent instead of refusing a broken file."""
        paths = _claude_paths(installed)
        assert _frontmatter(paths["agent"])["name"] == CONSOLIDATOR_AGENT_NAME
        assert _frontmatter(paths["skill"])["name"] == "zikaron-consolidate"

    def test_the_consolidator_is_granted_the_whole_server_and_read_and_nothing_else(
        self, installed: Path
    ) -> None:
        """A whole-server wildcard, measured to grant that server's tools and exclude the primary
        server's `search`/`fetch` (`claude-code-installer-probe.md` §7). Preferred over four
        explicit names because an unrecognised name in frontmatter refuses the spawn outright.

        `Read` joins it because this harness caps a tool result and an over-large group is written
        to a file instead — the consolidator needs a way to open it. Asserted as an exact list
        rather than a membership check: the point of this test is what is *absent*, and a
        containment assertion would pass against a config that had quietly gained `Bash`."""
        tools = _frontmatter(_claude_paths(installed)["agent"])["tools"]
        assert tools == [f"mcp__{CONSOLIDATOR_AGENT_NAME}", "Read"]

    def test_the_model_is_this_harnesss_own_default(self, installed: Path) -> None:
        assert _frontmatter(_claude_paths(installed)["agent"])["model"] == (
            CLAUDE_CODE.consolidator_model
        )

    def test_the_agent_body_is_the_consolidator_prompt(self, installed: Path) -> None:
        body = _claude_paths(installed)["agent"].read_text(encoding="utf-8").split("---\n", 2)[2]
        assert "You are **zikaron-consolidator**" in body

    def test_it_reports_the_approval_step_and_the_exposure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Both are things the installer cannot fix and must therefore not pass over in silence:
        an unapproved server loads nothing at all, and the primary agent's reach into the four
        consolidation verbs is D32's other half going prompt-only."""
        main(["--project", str(_project(tmp_path, dotdirs=(".claude",)))])
        printed = capsys.readouterr().out
        assert "approval" in printed
        assert "enabledMcpjsonServers" in printed
        assert "four consolidation verbs" in printed

    def test_it_pre_approves_both_the_loading_and_the_calling(self, tmp_path: Path) -> None:
        """**Two different keys, and conflating them is the defect this guards.**
        `enabledMcpjsonServers` decides whether a project-scoped server *loads*;
        `permissions.allow` decides whether each *call* goes through without a prompt. Writing only
        the first left every `zikaron_memory_remember` behind an approval prompt — the per-write
        friction the design calls worse than not asking at all."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        document = json.loads(_claude_paths(project)["settings"].read_text(encoding="utf-8"))
        assert sorted(document["enabledMcpjsonServers"]) == [
            MCP_SERVER_NAME,
            CONSOLIDATOR_AGENT_NAME,
        ]
        assert sorted(document["permissions"]["allow"]) == [
            f"mcp__{MCP_SERVER_NAME}",
            f"mcp__{CONSOLIDATOR_AGENT_NAME}",
        ]

    def test_no_trust_tools_withholds_both_keys_for_your_own_tools(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project), "--no-trust-tools"]) == 0
        document = json.loads(_claude_paths(project)["settings"].read_text(encoding="utf-8"))
        assert "enabledMcpjsonServers" not in document
        assert f"mcp__{MCP_SERVER_NAME}" not in document["permissions"]["allow"]

    def test_no_trust_tools_still_allows_the_consolidators_own_server(self, tmp_path: Path) -> None:
        """Not an oversight and not a loophole: a subagent has nobody to answer a permission prompt,
        so an unapproved tool there does not ask — it fails at the moment consolidation needs it.
        `--no-trust-tools` is a statement about *your* writes, not about whether consolidation can
        run at all, which is exactly the asymmetry kiro's always-trusted consolidator config has."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project), "--no-trust-tools"]) == 0
        document = json.loads(_claude_paths(project)["settings"].read_text(encoding="utf-8"))
        assert document["permissions"]["allow"] == [f"mcp__{CONSOLIDATOR_AGENT_NAME}"]


class TestTheHookTimeoutUnit:
    """One budget, three spellings, and the mistake that must stay unreachable.

    Kiro's `timeout_ms` carries 10000; Claude Code's `timeout` is **seconds** (measured,
    `claude-code-installer-probe.md` §2). Copying the integer across installs a 10,000-second
    budget — nearly three hours in which a wedged hook blocks every user message, with the harness
    doing exactly as told and nothing reporting a problem.
    """

    def test_claude_entries_state_seconds(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        main(["--project", str(project)])
        document = json.loads(_claude_paths(project)["settings"].read_text(encoding="utf-8"))
        for groups in document["hooks"].values():
            for group in groups:
                for entry in group["hooks"]:
                    assert entry["timeout"] == HOOK_TIMEOUT_SECONDS

    def test_no_claude_entry_ever_carries_a_millisecond_figure(self, tmp_path: Path) -> None:
        """The tripwire, stated as the shape of the bug rather than as the value: any timeout at or
        above kiro's millisecond figure is a unit error, whatever the canonical seconds value later
        becomes."""
        project = _project(tmp_path, dotdirs=(".claude",))
        main(["--project", str(project)])
        raw = _claude_paths(project)["settings"].read_text(encoding="utf-8")
        document = json.loads(raw)
        timeouts = [
            entry["timeout"]
            for groups in document["hooks"].values()
            for group in groups
            for entry in group["hooks"]
        ]
        assert timeouts
        assert all(value < TIMEOUT_MS for value in timeouts)

    def test_the_two_kiro_formats_state_one_budget_in_their_own_units(self) -> None:
        """Derived from one constant rather than converted from each other, so neither can drift
        into the other's unit."""
        assert hooks_object(_FIXTURE_COMMANDS)["agentSpawn"][0]["timeout_ms"] == TIMEOUT_MS
        assert hooks_array(_FIXTURE_COMMANDS)[0]["timeout"] == HOOK_TIMEOUT_SECONDS
        assert TIMEOUT_MS == HOOK_TIMEOUT_SECONDS * 1000


class TestToolNamesInShippedProse:
    """Claude Code shows the model `mcp__<server>__<tool>` verbatim (`installer-probe` §6), so a
    bare name in shipped prose names a tool that does not exist — and a model told to call a tool
    it cannot find improvises rather than failing."""

    def test_every_tool_is_qualified_by_its_owning_server(self) -> None:
        vocabulary = claude_tool_vocabulary()
        assert set(vocabulary) == ALL_TOOLS
        for name in PRIMARY_TOOLS:
            assert vocabulary[name] == f"mcp__{MCP_SERVER_NAME}__{name}"
        for name in CONSOLIDATOR_TOOLS:
            assert vocabulary[name] == f"mcp__{CONSOLIDATOR_AGENT_NAME}__{name}"

    def test_no_bare_tool_name_survives_into_a_claude_artefact(self, tmp_path: Path) -> None:
        """The property, asserted over the shipped text rather than over the substitution table:
        a rewrite that covered the table and missed a call site would pass the test above."""
        project = _project(tmp_path, dotdirs=(".claude",))
        main(["--project", str(project)])
        for key in ("agent", "skill"):
            text = _claude_paths(project)[key].read_text(encoding="utf-8")
            for name in ALL_TOOLS:
                bare = [
                    line for line in text.splitlines() if name in line and f"__{name}" not in line
                ]
                assert not bare, f"{key} names {name} unqualified: {bare}"

    def test_kiro_prose_keeps_the_bare_names(self) -> None:
        """The identity vocabulary is what makes kiro's artefacts carry the shipped constants
        exactly as written, rather than a rendering of them."""
        skill = skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION)
        assert "zikaron_memory_next_group" in skill
        assert "mcp__" not in skill

    def test_a_tool_the_vocabulary_does_not_know_raises_at_build_time(self) -> None:
        """The whole reason to render rather than duplicate. An unknown token passing through
        untouched would reintroduce exactly the drift this mechanism removes, silently."""
        with pytest.raises(ValueError, match="zikaron_not_a_tool"):
            render("call `zikaron_not_a_tool` now", identity_vocabulary())

    def test_the_claude_spawn_instruction_does_not_name_a_spawning_tool(self) -> None:
        """Deliberate. The tool's name varies by build — `Agent` in one, `Task` documented in
        another — and no probe pinned which a given install offers, while a bare "spawn the <name>
        subagent" instruction was measured to work. Naming the wrong tool would send the model
        hunting for something that is not there."""
        assert "subagent_type: zikaron-consolidator" in CLAUDE_CODE_SPAWN_INSTRUCTION
        assert "`Task`" not in CLAUDE_CODE_SPAWN_INSTRUCTION
        assert "`Agent`" not in CLAUDE_CODE_SPAWN_INSTRUCTION


class TestSameInstallOlderVersion:
    """The defect this class exists to pin: staleness was "names a *different install's*
    interpreter", which caught a cloned repository and missed the case an installer actually meets
    — *same install, older version*. Upgrading Zikaron and re-running left the previous version's
    consolidator prompt in place, reported cheerfully as "already there".
    """

    @pytest.mark.parametrize("harness_name", [KIRO.harness.value, CLAUDE_CODE.harness.value])
    def test_an_unchanged_re_run_keeps_every_shipped_file(
        self, tmp_path: Path, harness_name: str
    ) -> None:
        project = _project(tmp_path)
        assert main(["--project", str(project), "--harness", harness_name]) == 0
        before = {
            p: p.read_bytes() for p in project.rglob("*") if p.is_file() and p.suffix != ".bak"
        }
        assert main(["--project", str(project), "--harness", harness_name]) == 0
        after = {
            p: p.read_bytes() for p in project.rglob("*") if p.is_file() and p.suffix != ".bak"
        }
        assert after == before, "a re-run changed an artefact it should have recognised as current"

    @pytest.mark.parametrize("harness_name", [KIRO.harness.value, CLAUDE_CODE.harness.value])
    def test_a_stale_shipped_file_is_backed_up_rewritten_and_reported(
        self, tmp_path: Path, harness_name: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Stands in for the upgrade: the bytes on disk are not the bytes this install ships, which
        is the only thing the installer can actually observe about a version it no longer has."""
        project = _project(tmp_path)
        main(["--project", str(project), "--harness", harness_name])
        skill = next(project.rglob("SKILL.md"))
        skill.write_text("# an older Zikaron wrote this\n", encoding="utf-8")
        capsys.readouterr()

        assert main(["--project", str(project), "--harness", harness_name]) == 0
        printed = capsys.readouterr().out
        assert "differed from what this install ships" in printed
        assert skill.with_name("SKILL.md.bak").read_text(encoding="utf-8").startswith("# an older")
        assert "Consolidate project memory" in skill.read_text(encoding="utf-8")

    def test_a_hand_edit_is_preserved_in_the_backup_before_it_is_replaced(
        self, tmp_path: Path
    ) -> None:
        """The one behaviour change, and why it is safe: nothing is replaced without `<name>.bak`
        existing first."""
        project = _project(tmp_path)
        main(["--project", str(project), "--harness", CLAUDE_CODE.harness.value])
        agent = _claude_paths(project)["agent"]
        agent.write_text("mine\n", encoding="utf-8")
        main(["--project", str(project), "--harness", CLAUDE_CODE.harness.value])
        assert agent.with_name(agent.name + ".bak").read_text(encoding="utf-8") == "mine\n"


class TestClaudeCodeRefusals:
    """The same discipline `test_install_main.py` holds kiro to: a refusal writes nothing."""

    def test_a_conflicting_server_entry_is_refused_and_names_the_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Another install owns it, and its absolute paths may point at a venv this one knows
        nothing about. Overwriting silently would hide that the user has two installs.

        The *hook* half of this rule is exercised in
        `TestTheSettingsMergeLeavesTheUsersOwnHooksAlone`, where it belongs: a hook conflict is only
        a conflict when the entry is **Zikaron's**, and an earlier version of this test used an
        unrelated command — which the merge now correctly preserves rather than refuses.
        """
        project = _project(tmp_path, dotdirs=(".claude",))
        mcp = _claude_paths(project)["mcp"]
        mcp.write_text(
            json.dumps(
                {"mcpServers": {MCP_SERVER_NAME: {"command": "/other/venv/bin/zikaron-mcp"}}}
            ),
            encoding="utf-8",
        )
        assert main(["--project", str(project)]) == 1
        error = capsys.readouterr().err
        assert "--force" in error
        assert MCP_SERVER_NAME in error
        assert not _claude_paths(project)["agent"].exists()

    def test_force_replaces_a_conflicting_server_entry(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        mcp = _claude_paths(project)["mcp"]
        mcp.write_text(
            json.dumps(
                {"mcpServers": {MCP_SERVER_NAME: {"command": "/other/venv/bin/zikaron-mcp"}}}
            ),
            encoding="utf-8",
        )
        assert main(["--project", str(project), "--force"]) == 0
        servers = json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]
        assert servers[MCP_SERVER_NAME]["command"] != "/other/venv/bin/zikaron-mcp"

    def test_an_unrelated_server_survives_the_merge(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        mcp = _claude_paths(project)["mcp"]
        mcp.write_text(
            json.dumps({"mcpServers": {"theirs": {"command": "/usr/bin/their-server"}}}),
            encoding="utf-8",
        )
        assert main(["--project", str(project)]) == 0
        servers = json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]
        assert servers["theirs"] == {"command": "/usr/bin/their-server"}

    def test_a_users_own_settings_survive_the_merge(self, tmp_path: Path) -> None:
        """The merge target belongs to the user. A key this install does not write is not even
        inspected, and one it *does* write is added to rather than replaced."""
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.write_text(
            json.dumps({"env": {"MINE": "1"}, "permissions": {"allow": ["Bash(ls)"]}}),
            encoding="utf-8",
        )
        assert main(["--project", str(project)]) == 0
        document = json.loads(settings.read_text(encoding="utf-8"))
        assert document["env"] == {"MINE": "1"}, "a key we never touch is untouched"
        assert document["permissions"]["allow"][0] == "Bash(ls)", "theirs stays, and stays first"
        assert f"mcp__{MCP_SERVER_NAME}" in document["permissions"]["allow"]
        assert "hooks" in document

    def test_an_existing_settings_file_is_backed_up_before_it_is_merged(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.write_text(json.dumps({"permissions": {}}), encoding="utf-8")
        main(["--project", str(project)])
        assert json.loads(settings.with_name(settings.name + ".bak").read_text()) == {
            "permissions": {}
        }

    def test_a_fresh_project_is_not_asked_for_a_backup_it_cannot_have(self, tmp_path: Path) -> None:
        """A backup is a copy of the user's prior state, and there is none. Kiro never reaches this
        branch — `--agent` must name an existing file — but Claude Code's merge targets are fixed
        project paths a fresh project simply does not have."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        assert not _claude_paths(project)["mcp"].with_name(".mcp.json.bak").exists()

    def test_a_malformed_settings_file_is_refused_rather_than_overwritten(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.write_text("{not json", encoding="utf-8")
        assert main(["--project", str(project)]) == 1
        assert "not valid JSON" in capsys.readouterr().err
        assert settings.read_text(encoding="utf-8") == "{not json"

    @pytest.mark.parametrize(
        ("harness_name", "shipped"),
        [
            pytest.param(
                CLAUDE_CODE.harness.value,
                Path(".claude/agents/zikaron-consolidator.md"),
                id="claude-code",
            ),
            pytest.param(
                KIRO.harness.value,
                Path(".kiro/agents/zikaron-consolidator.json"),
                id="kiro",
            ),
        ],
    )
    def test_a_directory_where_a_shipped_file_belongs_is_refused(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        harness_name: str,
        shipped: Path,
    ) -> None:
        """The brief asks for the collision behaviour to be exercised *identically* against both
        targets, so this one is parametrized rather than written twice: the guard is shared code and
        the only thing that varies is which path it is pointed at."""
        project = _project(tmp_path)
        (project / shipped).mkdir(parents=True)
        assert main(["--project", str(project), "--harness", harness_name]) == 1
        assert "not a regular file" in capsys.readouterr().err
        assert not (project / shipped).is_file()


class TestPrintOnly:
    """Made explicit, where under kiro it was an accident of omitting `--agent`."""

    @pytest.mark.parametrize("harness_name", [KIRO.harness.value, CLAUDE_CODE.harness.value])
    def test_it_writes_nothing_at_all(self, tmp_path: Path, harness_name: str) -> None:
        project = _project(tmp_path)
        assert main(["--project", str(project), "--harness", harness_name, "--print-only"]) == 0
        assert not any(path.is_file() for path in project.rglob("*"))

    def test_an_unvalidatable_model_becomes_a_note_rather_than_a_refusal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A preview refuses nothing it does not have to. The model check asks a *remote* harness
        whether an id exists, and the fragment neither contains the model nor mentions it — so a
        hard refusal here would block a preview in order to validate something the preview does not
        show. That is not hypothetical: on a machine whose `kiro-cli` auth has lapsed, this was the
        difference between `--print-only` working and not.
        """
        monkeypatch.setattr(
            harness,
            "available_model_ids",
            lambda: (_ for _ in ()).throw(InstallError("kiro-cli is not reachable")),
        )
        project = _project(tmp_path)
        assert (
            main(["--project", str(project), "--harness", KIRO.harness.value, "--print-only"]) == 0
        )
        printed = capsys.readouterr().out
        assert "a real install would refuse here" in printed
        assert "kiro-cli is not reachable" in printed

    def test_it_lists_the_files_an_install_would_also_write(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The help text promises "exactly what an install would add", and the fragment shows only
        the merge entries — so the two shipped files were invisible in a preview of an install that
        writes them."""
        project = _project(tmp_path)
        main(["--project", str(project), "--harness", CLAUDE_CODE.harness.value, "--print-only"])
        printed = capsys.readouterr().out
        assert "would also write" in printed
        assert f"{CONSOLIDATOR_AGENT_NAME}.md" in printed
        assert "SKILL.md" in printed

    def test_it_shows_both_claude_files_by_name(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        project = _project(tmp_path)
        main(
            [
                "--project",
                str(project),
                "--harness",
                CLAUDE_CODE.harness.value,
                "--print-only",
            ]
        )
        printed = capsys.readouterr().out
        assert "settings.local.json" in printed
        assert ".mcp.json" in printed
        assert "SubagentStart" in printed


class TestTheSettingsMergeLeavesTheUsersOwnHooksAlone:
    """`SessionStart` and `UserPromptSubmit` are ordinary triggers a person may already be using,
    and `settings.local.json` is a file they edit by hand — this repository's own carries a curated
    `permissions.allow` block. So the merge replaces *Zikaron's* group within a trigger's list and
    nothing else. Caught during the build: the first version assigned the whole trigger key, which
    would have deleted a user's hook and refused the install first for good measure.
    """

    def _settings_with(self, project: Path, document: dict[str, object]) -> Path:
        settings = _claude_paths(project)["settings"]
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps(document), encoding="utf-8")
        return settings

    def test_an_unrelated_hook_on_our_own_trigger_survives(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        theirs = {"hooks": [{"type": "command", "command": "/usr/local/bin/their-notifier"}]}
        settings = self._settings_with(project, {"hooks": {"SessionStart": [theirs]}})

        assert main(["--project", str(project)]) == 0
        groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
        assert theirs in groups
        assert len(groups) == 2

    def test_a_hook_on_a_trigger_we_do_not_touch_survives(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        theirs = {"hooks": [{"type": "command", "command": "/usr/local/bin/their-linter"}]}
        settings = self._settings_with(project, {"hooks": {"PostToolUse": [theirs]}})

        assert main(["--project", str(project)]) == 0
        assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"] == [theirs]

    def test_another_installs_hook_is_recognised_and_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Matched on the command's file name rather than its full path, which is the whole point:
        a group naming another venv's `zikaron-hook` is a *different install*, and leaving it in
        place would have two interpreters firing into one store."""
        project = _project(tmp_path, dotdirs=(".claude",))
        stale = {
            "hooks": [{"type": "command", "command": "/other/venv/bin/zikaron-hook", "timeout": 10}]
        }
        settings = self._settings_with(project, {"hooks": {"SessionStart": [stale]}})

        assert main(["--project", str(project)]) == 1
        assert "SessionStart" in capsys.readouterr().err
        assert json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SessionStart"] == [stale]

    def test_the_refusal_names_what_differs_not_only_where(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        installed_commands: Commands,
    ) -> None:
        """Kiro's `_describe_difference` names the offending fields, and its docstring gives the
        reason: naming only the location leaves a user unable to tell **their own edit** from a
        Zikaron version change, and so unable to decide whether `--force` is the right answer. The
        settings refusal named only the trigger, which is the asymmetry this covers.

        This fixture is the harder half — *our own* command with a changed `timeout`, which the
        command comparison cannot distinguish and which the message must therefore describe.
        """
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.parent.mkdir(parents=True, exist_ok=True)
        hooked = str(installed_commands.hook)
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": hooked, "timeout": 999}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        assert main(["--project", str(project)]) == 1
        error = capsys.readouterr().err
        assert "SessionStart" in error
        assert "the entry differs" in error

    def test_force_replaces_another_installs_hook_without_duplicating_it(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        stale = {
            "hooks": [{"type": "command", "command": "/other/venv/bin/zikaron-hook", "timeout": 10}]
        }
        settings = self._settings_with(project, {"hooks": {"SessionStart": [stale]}})

        assert main(["--project", str(project), "--force"]) == 0
        groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
        assert groups != [stale]
        assert len(groups) == 1, "the stale group is replaced, not accompanied"

    def test_re_running_an_identical_install_does_not_accumulate_groups(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        main(["--project", str(project)])
        main(["--project", str(project)])
        document = json.loads(_claude_paths(project)["settings"].read_text(encoding="utf-8"))
        for trigger, groups in document["hooks"].items():
            assert len(groups) == 1, trigger


class TestShapesAMergeTargetCanLegitimatelyBeIn:
    """`.claude/settings.local.json` and `.mcp.json` are files people edit, and a half-written one
    is ordinary rather than exotic. Each shape here is either read the way the harness reads it or
    refused — never silently discarded, which on a *write* path is data loss with a reassuring
    shape.
    """

    def test_an_empty_settings_file_is_read_as_an_empty_object(self, tmp_path: Path) -> None:
        """How an editor leaves a config someone started and abandoned. Refusing it would block an
        install over a file with nothing in it to lose."""
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("   \n", encoding="utf-8")
        assert main(["--project", str(project)]) == 0
        assert "hooks" in json.loads(settings.read_text(encoding="utf-8"))

    def test_a_json_array_where_an_object_belongs_is_refused(self, tmp_path: Path) -> None:
        """There is nothing to merge into, and guessing would discard whatever it is."""
        project = _project(tmp_path, dotdirs=(".claude",))
        mcp = _claude_paths(project)["mcp"]
        mcp.write_text("[1, 2, 3]", encoding="utf-8")
        assert main(["--project", str(project)]) == 1
        assert mcp.read_text(encoding="utf-8") == "[1, 2, 3]"

    @pytest.mark.parametrize(
        "group",
        [
            pytest.param("not-a-group", id="a bare string where a group belongs"),
            pytest.param({"hooks": "not-a-list"}, id="a group whose hooks are not a list"),
            pytest.param({"matcher": "*"}, id="a group with no hooks at all"),
        ],
    )
    def test_a_malformed_group_on_our_trigger_is_left_alone_rather_than_read_as_ours(
        self, tmp_path: Path, group: object
    ) -> None:
        """None of these is recognisable as a Zikaron entry, so none is refused and none is
        rewritten — it is the user's, whatever it is, and it survives beside our own."""
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"hooks": {"SessionStart": [group]}}), encoding="utf-8")
        assert main(["--project", str(project)]) == 0
        groups = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["SessionStart"]
        assert group in groups
        assert len(groups) == 2


@pytest.mark.integration
class TestAgainstTheRealShippedCommands:
    """The brief's done-when says "driven through the real shipped commands", and everywhere else in
    this file those are faked.

    Under kiro that clause is `tests/test_install_e2e.py`'s job and needs a live authenticated
    `kiro-cli`. Under Claude Code nothing external is needed at all — there is no model check — so
    the real thing is reachable here: this installs with the console scripts `pip install -e .`
    actually produced, and asserts the artefacts name paths that exist and can be executed. A hook
    whose `command` does not exist produces no output on the one channel the harness reads, and
    fails in a subprocess whose stderr nobody surfaces.
    """

    @pytest.fixture(autouse=True)
    def _real_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Commands, "from_this_interpreter", _REAL_COMMANDS)

    def test_every_installed_command_path_exists_and_is_executable(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        paths = _claude_paths(project)

        servers = json.loads(paths["mcp"].read_text(encoding="utf-8"))["mcpServers"]
        commanded = [Path(server["command"]) for server in servers.values()]
        document = json.loads(paths["settings"].read_text(encoding="utf-8"))
        commanded += [
            Path(str(entry["command"]))
            for groups in document["hooks"].values()
            for group in groups
            for entry in group["hooks"]
        ]

        assert len(commanded) == 5, "two servers and three hooks"
        for path in commanded:
            assert path.is_absolute(), path
            assert path.is_file(), path
            assert os.access(path, os.X_OK), path


class TestAWrongShapedKeyIsRefusedRatherThanReplaced:
    """Defensive filtering on a *write* path is data loss with a reassuring shape.

    The same rule and the same reasoning as `writer.py`'s `TestShapesThatWouldBeSilentlyDropped` for
    kiro. Each value below is something a person put in a file they hand-edit; this code cannot know
    what they meant by it, so it refuses instead of writing over it. Found by re-reading the merge
    against that existing rule rather than by a failing test — the first version of both merges
    treated a wrong-shaped value as absent.
    """

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            pytest.param("hooks", ["not", "an", "object"], id="hooks as an array"),
            pytest.param("hooks", "off", id="hooks as a string"),
            pytest.param("enabledMcpjsonServers", "zikaron", id="server list as a string"),
        ],
    )
    def test_a_settings_key_of_the_wrong_kind_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str, value: object
    ) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps({key: value})
        settings.write_text(original, encoding="utf-8")
        assert main(["--project", str(project)]) == 1
        assert key in capsys.readouterr().err
        assert settings.read_text(encoding="utf-8") == original

    def test_a_trigger_whose_groups_are_not_an_array_is_refused(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"hooks": {"SessionStart": {"a": 1}}}), encoding="utf-8")
        with_error = main(["--project", str(project)])
        assert with_error == 1

    def test_mcp_servers_of_the_wrong_kind_is_refused(self, tmp_path: Path) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        mcp = _claude_paths(project)["mcp"]
        original = json.dumps({"mcpServers": ["zikaron"]})
        mcp.write_text(original, encoding="utf-8")
        assert main(["--project", str(project)]) == 1
        assert mcp.read_text(encoding="utf-8") == original


@pytest.mark.integration
class TestTheInstalledConfigDrivesTheRealHook:
    """The glue nothing else covers: settings file → command string → real subprocess → dispatch.

    Every other test here drives `main()` in-process with a fake `Commands`, so all of them would
    still pass if the installed config named a trigger `zikaron/hook/main.py` does not recognise —
    which fails as **no output and exit 0**, the silent shape this whole project is organised
    against, and nothing else in this file covers it.

    `SubagentStart` is the one exercised, and it is the right one for three reasons: it is the entry
    with **no kiro counterpart**, so no existing test could have caught it; its output channel
    differs from the other two, so a channel mistake shows up here and nowhere else; and its handler
    makes **no RPC at all** — the policy is a constant with a file override — so this needs no
    service, no store, no model, and no network.

    The other two triggers reach a live service by design, so those are checked elsewhere.
    **This** path was additionally observed end to end in a real session
    (`research/claude-code-installer-probe.md` §9) — a measurement of this same trigger, not of the
    other two, which have not run.
    """

    @pytest.fixture(autouse=True)
    def _real_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Commands, "from_this_interpreter", _REAL_COMMANDS)

    def _installed_hook_command(self, project: Path, trigger: str) -> str:
        document = json.loads(_claude_paths(project)["settings"].read_text(encoding="utf-8"))
        groups = document["hooks"][trigger]
        assert len(groups) == 1
        entries = groups[0]["hooks"]
        assert len(entries) == 1
        command = entries[0]["command"]
        assert isinstance(command, str)
        return command

    def _run(self, command: str, payload: dict[str, object], project: Path) -> str:
        completed = subprocess.run(  # noqa: S603 — the command is one this test just installed.
            [command],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            cwd=project,
            env={**os.environ, "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "sess-under-test"},
        )
        assert completed.returncode == 0, "a hook must always exit 0"
        return completed.stdout

    def test_the_installed_subagent_hook_delivers_the_policy_on_the_structured_channel(
        self, tmp_path: Path
    ) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        command = self._installed_hook_command(project, "SubagentStart")

        stdout = self._run(
            command,
            {
                "hook_event_name": "SubagentStart",
                "cwd": str(project),
                "session_id": "sess-under-test",
                "agent_id": "a-1",
                "agent_type": "some-other-agent",
            },
            project,
        )

        envelope = json.loads(stdout)
        assert envelope["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
        # The subagent variant, not the main-agent one: the text that reaches an agent the push
        # never serves must not open by describing a block it will never be sent.
        assert envelope["hookSpecificOutput"]["additionalContext"] == SUBAGENT_WRITE_POLICY_PROMPT

    def test_the_installed_subagent_hook_says_nothing_to_the_consolidator(
        self, tmp_path: Path
    ) -> None:
        """D32's own exclusion, through the real binary: the consolidator's policy is its own system
        prompt, and a second copy would spend the subagent's budget saying it again."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        command = self._installed_hook_command(project, "SubagentStart")

        stdout = self._run(
            command,
            {
                "hook_event_name": "SubagentStart",
                "cwd": str(project),
                "session_id": "sess-under-test",
                "agent_id": "a-2",
                "agent_type": CONSOLIDATOR_AGENT_NAME,
            },
            project,
        )
        assert stdout == ""


class TestTheseFixesAreWatchedFailing:
    """Each fix below landed without a test, and every one of them could
    be reverted today with the suite green.

    The rule is *trust a guard only after watching it fail*, and its sharpest instance here was a
    `--model` fix written as a docstring over an unchanged method body: the gate stayed green
    because nothing exercised it. These tests exist so the next revert is loud.
    """

    def test_a_model_id_that_would_change_the_frontmatters_meaning_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`model: a: b` is *valid YAML* and means something else, so nothing downstream complains.
        The harness refuses the mangled model eventually, at spawn — by which time the artefact has
        been claiming things the user never asked for."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project), "--model", "a: b"]) == 1
        assert "YAML frontmatter" in capsys.readouterr().err
        assert not _claude_paths(project)["agent"].exists()

    @pytest.mark.parametrize("good", ["sonnet", "claude-sonnet-5", "sonnet[1m]", "a.b_c-1"])
    def test_a_legitimate_alias_is_accepted_including_the_bracketed_form(
        self, tmp_path: Path, good: str
    ) -> None:
        """`sonnet[1m]` is measured to spawn (`installer-probe` §11), so refusing it would block a
        real value. Safe because `[` only opens a YAML flow sequence at the *start* of a scalar,
        which the pattern's alphanumeric anchor forbids."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project), "--model", good]) == 0
        assert _frontmatter(_claude_paths(project)["agent"])["model"] == good

    @pytest.mark.parametrize("bad", ["a: b", "sonnet\nfoo: bar", "", "has space", "[1m]"])
    def test_no_malformed_model_reaches_the_artefact(self, tmp_path: Path, bad: str) -> None:
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project), "--model", bad]) == 1
        assert not any(path.is_file() for path in (project / ".claude").rglob("*.md"))

    @pytest.mark.parametrize("target", ["settings", "mcp"])
    def test_a_blocked_backup_path_refuses_before_anything_is_written(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], target: str
    ) -> None:
        """The backup is the *last* thing a merge does and the shipped
        files are written before it, so without a plan-time check the refusal arrives after four
        writes — a half-install, which is the outcome the plan/commit split exists to prevent."""
        project = _project(tmp_path, dotdirs=(".claude",))
        path = _claude_paths(project)[target]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        (path.parent / (path.name + ".bak")).mkdir()

        assert main(["--project", str(project)]) == 1
        assert "cannot be backed up" in capsys.readouterr().err
        assert not _claude_paths(project)["agent"].exists()
        assert not _claude_paths(project)["skill"].exists()

    def test_force_backs_a_differing_shipped_file_up_before_replacing_it(
        self, tmp_path: Path
    ) -> None:
        """`--force` is the flag the merge-conflict refusals *instruct* users to pass, so it arrives
        alongside an unrelated conflict rather than only when someone means "discard my edits". It
        replaced without any backup at all."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        agent = _claude_paths(project)["agent"]
        agent.write_text("mine\n", encoding="utf-8")

        assert main(["--project", str(project), "--force"]) == 0
        assert agent.read_text(encoding="utf-8") != "mine\n"
        assert agent.with_name(agent.name + ".bak").read_text(encoding="utf-8") == "mine\n"

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            pytest.param("permissions", ["allow"], id="permissions as an array"),
            pytest.param("permissions", {"allow": "everything"}, id="allow as a string"),
        ],
    )
    def test_a_wrong_shaped_permissions_key_is_refused(
        self, tmp_path: Path, key: str, value: object
    ) -> None:
        """The two shapes an earlier parametrize did not reach, so the error path through
        `_merged_permissions` was unexercised."""
        project = _project(tmp_path, dotdirs=(".claude",))
        settings = _claude_paths(project)["settings"]
        settings.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps({key: value})
        settings.write_text(original, encoding="utf-8")
        assert main(["--project", str(project)]) == 1
        assert settings.read_text(encoding="utf-8") == original

    def test_a_live_marker_beside_a_lone_kiro_directory_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Project evidence still wins — but a lone `.kiro/` in a project opened from a Claude Code
        session is a real configuration, since this corpus's own migration advice is to *keep*
        `.kiro/`. Installing for kiro there is right and silent was not."""
        monkeypatch.setenv("CLAUDECODE", "1")
        project = _project(tmp_path, dotdirs=(".kiro",))
        assert main(["--project", str(project)]) == 0
        printed = capsys.readouterr().out
        assert "CLAUDECODE is set" in printed
        assert f"--harness {CLAUDE_CODE.harness.value}" in printed

    def test_a_re_run_with_no_trust_tools_does_not_claim_it_withheld_what_is_still_there(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The merge never *removes* a grant, so after a default install both are in the file. An
        unconditional note would then assert the opposite of what the file says."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        capsys.readouterr()

        assert main(["--project", str(project), "--no-trust-tools"]) == 0
        printed = capsys.readouterr().out
        document = json.loads(_claude_paths(project)["settings"].read_text(encoding="utf-8"))
        assert f"mcp__{MCP_SERVER_NAME}" in document["permissions"]["allow"], "still granted"
        assert "enabledMcpjsonServers" in document, "still enabled"
        assert "was **not** written" not in printed
        assert "was **not** added" not in printed


class TestInstallingFromAPlainShellWithNoHarnessPresent:
    """The primary invocation, and for a long time an untested one.

    A person installs Zikaron by running a program — from a terminal, over ssh, in a container —
    and usually **not** from inside a harness session. Nothing about that path may require a harness
    to be *running*, and for Claude Code nothing may require a harness to be *installed* either.

    Two properties are separable and both matter. Harness **resolution** must work with no marker in
    the environment, which it does because `_resolve_harness` reads the project first — the
    resolution cases are covered in `TestHarnessResolution`, and this suite's `conftest` clears
    every marker for every test, so they are all already pure-shell tests in that respect. What was
    *not* covered is the **binary** dependency, because the autouse fixture patches
    `available_model_ids` for every test and so hides whether a given path would have called it.
    """

    @pytest.fixture
    def nothing_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A machine with neither harness installed."""
        monkeypatch.setattr(harness, "binary_is_available", lambda _name: False)

    @pytest.mark.parametrize(
        ("harness_name", "binary"),
        [
            pytest.param(KIRO.harness.value, KIRO.harness_binary, id="kiro"),
            pytest.param(CLAUDE_CODE.harness.value, CLAUDE_CODE.harness_binary, id="claude-code"),
        ],
    )
    @pytest.mark.usefixtures("nothing_on_path")
    def test_an_install_is_refused_when_its_own_harness_is_not_here(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        harness_name: str,
        binary: str,
    ) -> None:
        """**One rule, both harnesses**, and the symmetry is the point rather than a tidiness.

        An install writes files whose only reader is that harness's binary. Writing them where it
        does not exist gives exit 0, no Zikaron tools, and nothing saying why — the same
        working-looking-inert outcome `_resolve_harness` refuses to *guess* its way into. Permitting
        it for one harness while refusing it for the other was an inconsistency, and it existed only
        because kiro's refusal was a side effect of its model check while Claude Code has no model
        check to have a side effect.
        """
        project = _project(tmp_path)
        assert main(["--project", str(project), "--harness", harness_name]) == 1
        error = capsys.readouterr().err
        assert binary in error
        assert not any(path.is_file() for path in project.rglob("*"))

    @pytest.mark.parametrize("harness_name", [KIRO.harness.value, CLAUDE_CODE.harness.value])
    @pytest.mark.usefixtures("nothing_on_path")
    def test_print_only_still_previews_with_no_harness_installed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], harness_name: str
    ) -> None:
        """The escape hatch, and the reason the refusal above needs no `--force`. Provisioning a
        machine before its harness is a real thing to want; `--print-only` shows exactly what to
        write, refuses nothing, and writes nothing."""
        project = _project(tmp_path)
        assert main(["--project", str(project), "--harness", harness_name, "--print-only"]) == 0
        printed = capsys.readouterr().out
        assert "a real install would refuse here" in printed
        assert not any(path.is_file() for path in project.rglob("*"))

    def test_a_claude_code_install_asks_no_kiro_binary_anything(self, tmp_path: Path) -> None:
        """The asymmetry that *is* real and stays: Claude Code refuses an unknown model itself, at
        spawn, so the installer has nothing to ask a binary — and must not ask one. Every kiro entry
        point raises here, and the install must not touch any of them."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        for name, path in _claude_paths(project).items():
            assert path.is_file(), name

    def test_a_claude_code_install_reports_nothing_from_a_harness_it_does_not_use(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`complaints_about` is kiro's validator, and a Claude Code install must not surface its
        opinion — the artefacts are not files it can read."""
        project = _project(tmp_path, dotdirs=(".claude",))
        main(["--project", str(project)])
        assert "kiro-cli" not in capsys.readouterr().out

    def test_resolution_needs_no_harness_process_only_the_project(self, tmp_path: Path) -> None:
        """`harness.detect.current_harness()` answers `KIRO` in a plain shell, because kiro exports
        no marker and absence *is* its signal. The installer must never inherit that answer: from a
        plain shell, a Claude-Code project resolves to Claude Code on the strength of the project
        alone."""
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        assert _claude_paths(project)["mcp"].is_file()


@pytest.mark.integration_claude
class TestAgainstTheRealClaudeBinary:
    """The one thing about Claude Code a stub cannot establish: that the name we look for is right.

    Kiro's counterpart (`test_install_harness.py::TestAgainstTheRealBinary`) makes the argument this
    tier rests on — *"a parser checked only against fixtures is checked against my own belief about
    the format"* — and the same applies to a binary name. Every other test in this file answers
    `binary_is_available` for itself, which is correct (a suite whose result depends on what is on
    `PATH` is not testing the code) and which means **nothing anywhere would notice if the name were
    wrong**. An install would then refuse on every machine, including the ones where Claude Code is
    installed, for a reason no test could see.

    Out of the default run because it depends on this machine, not on this repository.
    """

    def test_the_name_the_seam_carries_is_a_binary_that_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """**Fails rather than skips when the binary is absent**, and consults the real `PATH`.

        Both halves were wrong on the first attempt. The module's autouse
        fixture pins `binary_is_available` to `True` for every test in this file, so asserting it
        here asserted the stub back to itself; and the `shutil.which` skip meant a *wrong*
        `harness_binary` made both tests skip and the whole tier exit 0. A tier that goes green on
        the one error it exists to catch is worse than no tier.

        Absence is a legitimate failure here because this tier is **only ever run by explicit
        request** — `pytest -m integration_claude` on a machine without Claude Code is a mistake
        about the machine, and the message says so rather than making the reader guess which of the
        two causes they hit.
        """
        monkeypatch.setattr(harness, "binary_is_available", _REAL_BINARY_IS_AVAILABLE)
        name = CLAUDE_CODE.harness_binary
        assert harness.binary_is_available(name), (
            f"{name!r} is not on PATH. Either this machine has no Claude Code — in which case "
            "do not run `-m integration_claude` here — or `HarnessSpec.harness_binary` names the "
            "wrong binary, in which case every install on every machine refuses and no other test "
            "can see it."
        )

    def test_an_install_is_not_refused_when_the_real_binary_is_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End to end through the *real* `shutil.which`, with the autouse answer removed.

        The stubbed tests prove the refusal fires when the binary is absent; only this one proves it
        does **not** fire when it is present — the half a stub returning `True` cannot distinguish
        from a check that was never reached.
        """
        monkeypatch.setattr(harness, "binary_is_available", _REAL_BINARY_IS_AVAILABLE)
        assert shutil.which(CLAUDE_CODE.harness_binary) is not None, (
            f"{CLAUDE_CODE.harness_binary!r} is not on PATH — see the sibling test's message. "
            "Failing rather than skipping, so no test in this tier reports success for a machine "
            "that cannot run it."
        )
        project = _project(tmp_path, dotdirs=(".claude",))
        assert main(["--project", str(project)]) == 0
        assert _claude_paths(project)["mcp"].is_file()
