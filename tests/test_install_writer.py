"""`zikaron.install.writer`: what lands on disk, and what is refused.

`architecture.md` §"The install contract" is normative. The interesting behaviour here is all
*refusal*: this is the one part of Zikaron that writes files a user owns, so every test below is
either "it did not clobber that" or "it said what it changed".
"""

import errno
import json
import os
import shlex
from pathlib import Path

import pytest

from zikaron.hook.limits import TIMEOUT_MS
from zikaron.install.assets import SKILL_MARKDOWN
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    MCP_SERVER_NAME,
    TOOL_SELECTOR,
    Commands,
    HookFormat,
)
from zikaron.install.harness import InstallError
from zikaron.install.writer import (
    Plan,
    Report,
    Targets,
    commit_merge,
    plan_merge,
    write_shipped_files,
)


def merge_agent_config(path: Path, plan: Plan, report: Report) -> None:
    """Plan and commit in one call, which is what every merge test below is asserting about.

    The two are separate in production so `main.py` can run every refusal before writing anything; a
    test that only cares about the merged result should not have to restate that ordering, and
    `tests/test_install_main.py` is where the ordering itself is asserted.
    """
    commit_merge(plan_merge(path, plan), report)


_COMMANDS = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))
_OTHER_COMMANDS = Commands(
    hook=Path("/elsewhere/bin/zikaron-hook"), mcp=Path("/elsewhere/bin/zikaron-mcp")
)


def _plan(
    project: Path,
    *,
    force: bool = False,
    fmt: HookFormat = HookFormat.OBJECT,
    trust_tools: bool = True,
) -> Plan:
    return Plan(
        targets=Targets(project=project),
        commands=_COMMANDS,
        model="a-model",
        hook_format=fmt,
        force=force,
        trust_tools=trust_tools,
    )


def _write_agent(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


class TestWritingTheShippedFiles:
    def test_it_creates_both_files_and_their_directories(self, tmp_path: Path) -> None:
        report = Report()
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
        targets = Targets(project=tmp_path)
        assert targets.consolidator_config.is_file()
        assert targets.skill_file.is_file()
        assert set(report.created) == {targets.consolidator_config, targets.skill_file}

    def test_the_written_config_is_json_carrying_the_planned_model(self, tmp_path: Path) -> None:
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, Report())
        written = json.loads(Targets(project=tmp_path).consolidator_config.read_text())
        assert written["model"] == "a-model"

    def test_an_existing_file_is_kept_not_overwritten(self, tmp_path: Path) -> None:
        """The case that matters: an operator has edited the shipped prompt, and a re-run must not
        silently discard the edit. The fixture names *this* install's own command, because a config
        naming another one is the separate, deliberately different case below."""
        targets = Targets(project=tmp_path)
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, Report())
        edited = json.loads(targets.consolidator_config.read_text())
        edited["prompt"] = "mine, edited"
        targets.consolidator_config.write_text(json.dumps(edited))
        report = Report()
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
        assert json.loads(targets.consolidator_config.read_text())["prompt"] == "mine, edited"
        assert report.skipped == [targets.consolidator_config, targets.skill_file]

    def test_force_replaces_an_existing_file(self, tmp_path: Path) -> None:
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        targets.consolidator_config.write_text('{"name": "mine, edited"}')
        write_shipped_files(_plan(tmp_path, force=True), SKILL_MARKDOWN, Report())
        assert json.loads(targets.consolidator_config.read_text())["model"] == "a-model"

    def test_a_symlink_at_the_target_is_treated_as_existing_rather_than_followed(
        self, tmp_path: Path
    ) -> None:
        """Following it would write our JSON through the link into whatever it points at."""
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        elsewhere = tmp_path / "somebody-elses-file"
        elsewhere.write_text("untouched")
        targets.consolidator_config.symlink_to(elsewhere)
        report = Report()
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
        assert elsewhere.read_text() == "untouched"
        assert report.skipped == [targets.consolidator_config]

    def test_force_through_a_symlink_replaces_the_link_not_its_target(self, tmp_path: Path) -> None:
        """`--force` means "replace the file I named", never "write into wherever it points"."""
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        elsewhere = tmp_path / "somebody-elses-file"
        elsewhere.write_text("untouched")
        targets.consolidator_config.symlink_to(elsewhere)
        write_shipped_files(_plan(tmp_path, force=True), SKILL_MARKDOWN, Report())
        assert elsewhere.read_text() == "untouched"
        assert not targets.consolidator_config.is_symlink()
        assert json.loads(targets.consolidator_config.read_text())["model"] == "a-model"


class TestMergingIntoAnObjectFormatConfig:
    def test_it_adds_both_triggers_and_keeps_the_users_own_hook(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": {"agentSpawn": [{"command": "git status"}]}})
        merge_agent_config(config, _plan(tmp_path), Report())
        hooks = json.loads(config.read_text())["hooks"]
        assert [entry["command"] for entry in hooks["agentSpawn"]] == [
            "git status",
            str(_COMMANDS.hook),
        ]
        assert len(hooks["userPromptSubmit"]) == 1

    def test_a_second_install_replaces_rather_than_duplicates(self, tmp_path: Path) -> None:
        """Two entries on one trigger would inject two blocks per user message."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        hooks = json.loads(config.read_text())["hooks"]
        assert len(hooks["agentSpawn"]) == 1
        assert len(hooks["userPromptSubmit"]) == 1

    def test_an_entry_from_another_interpreter_is_refused_without_force(
        self, tmp_path: Path
    ) -> None:
        """A stale hook command is a previous install from a different venv, and it is refused for
        the same reason a stale server entry is: silently replacing it would hide that the user has
        two installs, and leaving it would install a second hook that fails on every message.
        """
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": {
                    "userPromptSubmit": [{"command": shlex.quote(str(_OTHER_COMMANDS.hook))}]
                },
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError, match="differ from what this install would write"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before
        assert not (tmp_path / "mine.json.bak").exists()

    def test_an_entry_from_another_interpreter_is_replaced_under_force(
        self, tmp_path: Path
    ) -> None:
        """Matched on the command's file name, which is why a different absolute path is still
        recognized as ours and replaced rather than left beside this install's own entry."""
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": {
                    "userPromptSubmit": [{"command": shlex.quote(str(_OTHER_COMMANDS.hook))}]
                },
            },
        )
        merge_agent_config(config, _plan(tmp_path, force=True), Report())
        entries = json.loads(config.read_text())["hooks"]["userPromptSubmit"]
        assert [entry["command"] for entry in entries] == [shlex.quote(str(_COMMANDS.hook))]

    def test_it_adds_the_primary_mcp_server_and_keeps_the_users_own(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "mcpServers": {"git": {"command": "mcp-server-git"}}})
        merge_agent_config(config, _plan(tmp_path), Report())
        servers = json.loads(config.read_text())["mcpServers"]
        assert set(servers) == {"git", MCP_SERVER_NAME}
        assert servers[MCP_SERVER_NAME]["args"] == ["--mode", "primary"]

    def test_a_config_with_no_hooks_key_gets_the_requested_format(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path, fmt=HookFormat.ARRAY), Report())
        assert isinstance(json.loads(config.read_text())["hooks"], list)


class TestTheToolSelector:
    """`@zikaron` in `tools`, without which the whole install does nothing.

    Measured, not assumed: an agent with the `mcpServers` entry and a `tools` list that did not name
    the server reported no `zikaron_*` tools at all.
    """

    def test_it_is_added_when_absent(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": ["read", "subagent"]})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["tools"] == ["read", "subagent", TOOL_SELECTOR]

    def test_it_is_added_to_a_config_with_no_tools_key(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["tools"] == [TOOL_SELECTOR]

    def test_a_second_install_does_not_add_it_twice(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": ["read"]})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["tools"] == ["read", TOOL_SELECTOR]

    def test_allowed_tools_gets_it_too_by_default(self, tmp_path: Path) -> None:
        """Without this, every memory write interrupts the user for approval — which pushes against
        the write policy the store depends on and trains them to click through prompts.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "allowedTools": ["read"]})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["allowedTools"] == ["read", TOOL_SELECTOR]

    def test_allowed_tools_is_left_alone_when_the_prompts_are_wanted(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "allowedTools": ["read"]})
        report = Report()
        merge_agent_config(config, _plan(tmp_path, trust_tools=False), report)
        assert json.loads(config.read_text())["allowedTools"] == ["read"]
        assert any("--no-trust-tools" in note for note in report.notes)

    def test_a_second_install_does_not_add_it_to_allowed_tools_twice(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["allowedTools"] == [TOOL_SELECTOR]

    def test_a_non_array_allowed_tools_is_refused_rather_than_replaced(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "allowedTools": "read"})
        before = config.read_text()
        with pytest.raises(InstallError, match="`allowedTools` value that is not an array"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestTheConsolidatorIsAddedToTheCrew:
    """Without this the consolidation skill cannot run at all — found in real use, not in review.

    The skill spawns `zikaron-consolidator` through the `subagent` tool, and
    `toolsSettings.crew.availableAgents` gates which agents that tool may spawn.

    The two lists are **not** symmetric, which is what makes this easy to get wrong: an absent or
    empty `availableAgents` means *every* agent is available, so adding one entry there would narrow
    the config rather than widen it. `trustedAgents` grants nothing when empty, so adding to it can
    only widen.
    """

    def test_a_populated_available_list_gains_the_consolidator(self, tmp_path: Path) -> None:
        """The reported bug, exactly: three of the user's own agents listed, ours missing."""
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "toolsSettings": {
                    "crew": {
                        "availableAgents": ["helper-a", "helper-b"],
                        "trustedAgents": ["helper-a"],
                    }
                },
            },
        )
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == ["helper-a", "helper-b", CONSOLIDATOR_AGENT_NAME]
        assert crew["trustedAgents"] == ["helper-a", CONSOLIDATOR_AGENT_NAME]
        assert any("availableAgents" in note for note in report.notes)

    def test_an_absent_available_list_is_left_alone_rather_than_narrowed(
        self, tmp_path: Path
    ) -> None:
        """The trap. An absent list means every agent is available; writing one entry into it would
        restrict the config to the consolidator alone and silently break every other subagent the
        user has. Trust is still granted, because that only widens.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert "availableAgents" not in crew
        assert crew["trustedAgents"] == [CONSOLIDATOR_AGENT_NAME]
        assert any("every* agent" in note or "every agent" in note for note in report.notes)

    def test_an_empty_available_list_is_treated_the_same_as_an_absent_one(
        self, tmp_path: Path
    ) -> None:
        """`[]` and absent mean the same thing to the harness, so they must mean the same here — a
        fixture with a populated list cannot tell these two branches apart."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "toolsSettings": {"crew": {"availableAgents": []}}})
        merge_agent_config(config, _plan(tmp_path), Report())
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == []
        assert crew["trustedAgents"] == [CONSOLIDATOR_AGENT_NAME]

    def test_the_agent_crew_alias_is_updated_in_place(self, tmp_path: Path) -> None:
        """`agent_crew` is a documented alias for the same block. Writing a second `crew` key beside
        it would leave two blocks whose relationship the harness does not define.
        """
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {"name": "mine", "toolsSettings": {"agent_crew": {"availableAgents": ["helper-a"]}}},
        )
        merge_agent_config(config, _plan(tmp_path), Report())
        settings = json.loads(config.read_text())["toolsSettings"]
        assert "crew" not in settings
        assert settings["agent_crew"]["availableAgents"] == ["helper-a", CONSOLIDATOR_AGENT_NAME]

    def test_other_tools_settings_survive(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "toolsSettings": {
                    "write": {"allowedPaths": ["src/**"]},
                    "crew": {"availableAgents": ["helper-a"]},
                },
            },
        )
        merge_agent_config(config, _plan(tmp_path), Report())
        settings = json.loads(config.read_text())["toolsSettings"]
        assert settings["write"] == {"allowedPaths": ["src/**"]}

    def test_a_second_install_does_not_duplicate_either_entry(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config, {"name": "mine", "toolsSettings": {"crew": {"availableAgents": ["helper-a"]}}}
        )
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == ["helper-a", CONSOLIDATOR_AGENT_NAME]
        assert crew["trustedAgents"] == [CONSOLIDATOR_AGENT_NAME]

    def test_no_tools_settings_block_is_invented_when_nothing_is_trusted(
        self, tmp_path: Path
    ) -> None:
        """With `--no-trust-tools` and no existing crew there is nothing to add, so a config that
        had no `toolsSettings` should not grow an empty one."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        report = Report()
        merge_agent_config(config, _plan(tmp_path, trust_tools=False), report)
        assert "toolsSettings" not in json.loads(config.read_text())
        assert any("trustedAgents" in note for note in report.notes)

    def test_a_populated_available_list_is_still_extended_without_trust(
        self, tmp_path: Path
    ) -> None:
        """`--no-trust-tools` is about approval prompts, not availability: the skill still has to be
        able to spawn the consolidator at all."""
        config = tmp_path / "mine.json"
        _write_agent(
            config, {"name": "mine", "toolsSettings": {"crew": {"availableAgents": ["helper-a"]}}}
        )
        merge_agent_config(config, _plan(tmp_path, trust_tools=False), Report())
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == ["helper-a", CONSOLIDATOR_AGENT_NAME]
        assert "trustedAgents" not in crew


class TestTheSkillIsDeclaredWhenDeclaringItMatters:
    """Skills reach an agent through `resources`, but also arrive by inheritance without one.

    That makes this latent rather than broken — the opposite of the crew list — so the rule is to
    add the entry only where a config's own explicit declarations decide, and to say so otherwise.
    """

    def test_a_config_with_no_resources_is_left_alone_with_a_note(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert "resources" not in json.loads(config.read_text())
        assert any("inherited by default" in note for note in report.notes)

    def test_a_glob_that_already_covers_the_skill_is_not_duplicated(self, tmp_path: Path) -> None:
        """The common case in this repo's own configs: a `**` glob over every workspace skill."""
        config = tmp_path / "mine.json"
        declared = ["file://NOTES.md", "skill://.kiro/skills/**/SKILL.md"]
        _write_agent(config, {"name": "mine", "resources": declared})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["resources"] == declared

    def test_explicit_resources_that_miss_the_skill_gain_it(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "resources": ["file://NOTES.md"]})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert json.loads(config.read_text())["resources"] == [
            "file://NOTES.md",
            "skill://.kiro/skills/zikaron-consolidate/SKILL.md",
        ]
        assert any("`resources`" in note for note in report.notes)

    def test_a_second_install_does_not_add_it_twice(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "resources": []})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["resources"] == [
            "skill://.kiro/skills/zikaron-consolidate/SKILL.md"
        ]

    def test_a_resources_value_that_is_not_an_array_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "resources": "file://NOTES.md"})
        before = config.read_text()
        with pytest.raises(InstallError, match="`resources` value that is not an array"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestACrewBlockThisCannotMergeIntoIsRefused:
    def test_both_crew_spellings_at_once_is_refused(self, tmp_path: Path) -> None:
        """They are documented as aliases for one block, so a config carrying both has no defined
        meaning — and picking one silently would ignore whatever the user put in the other.
        """
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "toolsSettings": {
                    "crew": {"availableAgents": ["helper-a"]},
                    "agent_crew": {"availableAgents": ["helper-b"]},
                },
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError, match=r"both `toolsSettings\.crew` and"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    @pytest.mark.parametrize(
        ("settings", "expected"),
        [
            pytest.param(
                "not an object", "`toolsSettings` value that is not an object", id="settings"
            ),
            pytest.param(
                {"crew": []}, "`toolsSettings.crew` value that is not an object", id="crew"
            ),
            pytest.param(
                {"crew": {"availableAgents": "helper-a"}},
                "availableAgents",
                id="availableAgents",
            ),
            pytest.param(
                {"agent_crew": {"trustedAgents": 7}},
                "trustedAgents",
                id="trustedAgents via the alias",
            ),
        ],
    )
    def test_it_refuses_and_changes_nothing(
        self, tmp_path: Path, settings: object, expected: str
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "toolsSettings": settings})
        before = config.read_text()
        with pytest.raises(InstallError, match=expected):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestAConfigWithSomethingUnexpectedInIt:
    def test_a_hooks_value_that_is_neither_shape_is_refused_rather_than_replaced(
        self, tmp_path: Path
    ) -> None:
        """It is data the user put there and this code cannot tell what they meant by it, so
        dropping it to make room for our two entries would destroy something to install something.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": "not a hooks value"})
        before = config.read_text()
        with pytest.raises(InstallError, match="neither an object nor an array"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    def test_an_mcp_servers_value_that_is_not_an_object_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "mcpServers": ["not an object"]})
        with pytest.raises(InstallError, match="not an object"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_a_hook_entry_that_is_not_an_object_is_left_alone_rather_than_crashing(
        self, tmp_path: Path
    ) -> None:
        """The harness would reject this config, but we read it before the harness does — and the
        useful behaviour is to add our entry and leave the oddity for the harness to complain about,
        not to raise on a file we were only asked to merge into.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": {"agentSpawn": ["not an object"]}})
        merge_agent_config(config, _plan(tmp_path), Report())
        entries = json.loads(config.read_text())["hooks"]["agentSpawn"]
        assert entries[0] == "not an object"
        assert entries[1]["command"] == str(_COMMANDS.hook)


class TestMergingIntoAnArrayFormatConfig:
    def test_the_files_own_format_wins_over_the_requested_one(self, tmp_path: Path) -> None:
        """The harness rewrites a config in whichever format it read, so a file carrying both shapes
        has no defined meaning — the requested format cannot be allowed to convert one."""
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "git-status",
                        "trigger": "agentSpawn",
                        "action": {"type": "command", "command": "git status"},
                    }
                ],
            },
        )
        merge_agent_config(config, _plan(tmp_path, fmt=HookFormat.OBJECT), Report())
        hooks = json.loads(config.read_text())["hooks"]
        assert isinstance(hooks, list)
        assert [entry["name"] for entry in hooks] == [
            "git-status",
            "zikaron-agentSpawn",
            "zikaron-userPromptSubmit",
        ]

    def test_a_second_install_replaces_by_name(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": []})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert len(json.loads(config.read_text())["hooks"]) == 2

    def test_it_reports_that_those_entries_have_no_output_cap_field(self, tmp_path: Path) -> None:
        """Stated rather than hidden: the array format documents no `max_output_size`, so those
        entries inherit the harness default and the operator should know which they got."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": []})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert any("max_output_size" in note for note in report.notes)


class TestTheAtomicWrite:
    def test_a_predictable_temporary_symlink_is_neither_followed_nor_clobbered(
        self, tmp_path: Path
    ) -> None:
        """A fixed `<target>.tmp` would be *followed* if it were a symlink, redirecting the content
        a check on the final target had just protected. The scratch file is created exclusively
        under an unpredictable name instead, so a planted `.tmp` is simply irrelevant.
        """
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        outside = tmp_path / "outside.json"
        planted = targets.consolidator_config.with_name(targets.consolidator_config.name + ".tmp")
        planted.symlink_to(outside)
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, Report())
        assert not outside.exists(), "the write followed a planted temporary symlink"
        assert planted.is_symlink(), "the planted link was clobbered rather than ignored"
        assert json.loads(targets.consolidator_config.read_text())["model"] == "a-model"

    def test_a_short_write_is_not_published(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A write to a regular file may legally return short, and ignoring that would rename a
        truncated config over the user's own. Forced by making `os.write` accept one byte at a time
        and then refuse: the loop must raise rather than publish what it managed to write.
        """
        targets = Targets(project=tmp_path)
        calls: list[int] = []
        real_write = os.write

        def _short(descriptor: int, payload: bytes) -> int:
            calls.append(len(payload))
            if len(calls) > 2:
                raise OSError(errno.ENOSPC, "no space left on device")
            return real_write(descriptor, payload[:1])

        monkeypatch.setattr(os, "write", _short)
        with pytest.raises(OSError, match="no space"):
            write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, Report())
        assert not targets.consolidator_config.exists(), "a truncated file was published"
        leftovers = [path.name for path in targets.agents_dir.iterdir()]
        assert leftovers == [], f"scratch files survived: {leftovers}"

    def test_a_short_write_that_completes_across_calls_is_published_whole(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other half: the loop has to keep going, not merely notice. One byte per call, and the
        published file must still be complete and parseable.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        real_write = os.write
        monkeypatch.setattr(
            os, "write", lambda descriptor, payload: real_write(descriptor, payload[:1])
        )
        merge_agent_config(config, _plan(tmp_path), Report())
        assert TOOL_SELECTOR in json.loads(config.read_text())["tools"]
        assert (tmp_path / "mine.json.bak").is_file(), "the backup went through the same loop"

    def test_no_scratch_files_are_left_behind(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert [path.name for path in tmp_path.iterdir() if path.name.endswith(".tmp")] == []

    def test_an_existing_configs_mode_survives_the_replacement(self, tmp_path: Path) -> None:
        """A rename replaces the inode and its mode with it, so a `0644` config must not come back
        `0600` as a side effect of how it was written."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        config.chmod(0o644)
        merge_agent_config(config, _plan(tmp_path), Report())
        assert config.stat().st_mode & 0o777 == 0o644


class TestTheBackup:
    def test_the_first_merge_writes_a_backup(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        original = config.read_text()
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        backup = tmp_path / "mine.json.bak"
        assert backup.read_text() == original
        assert report.backed_up == [backup]

    def test_a_dangling_backup_symlink_is_refused_rather_than_written_through(
        self, tmp_path: Path
    ) -> None:
        """`Path.exists()` is **false** for a dangling symlink and `shutil.copy2` follows one, so a
        naive existence check would write this config's contents to wherever the link points —
        outside the project entirely. It is also not a backup, so the merge is refused.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        before = config.read_text()
        outside = tmp_path / "outside" / "target.json"
        (tmp_path / "mine.json.bak").symlink_to(outside)
        with pytest.raises(InstallError, match="not a regular file"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert not outside.exists(), "the backup followed a dangling symlink out of the project"
        assert config.read_text() == before

    def test_a_second_merge_leaves_the_first_backup_alone(self, tmp_path: Path) -> None:
        """Overwriting it would replace the pristine original with a copy the first install had
        already modified — the one way this command could lose something irrecoverably.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        original = config.read_text()
        merge_agent_config(config, _plan(tmp_path), Report())
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert (tmp_path / "mine.json.bak").read_text() == original
        assert report.backed_up == []
        assert any("left as it was" in note for note in report.notes)


class TestAStaleShippedConfigIsCorrectedRatherThanKept:
    """A cloned repository arrives with these artefacts tracked, carrying another machine's paths.

    Kept as-is that is a consolidator that can never start; reported as "already there" it is a
    confidently stale artefact. So it is backed up and rewritten, and the rewrite is reported.
    """

    def test_a_config_naming_another_install_is_rewritten(self, tmp_path: Path) -> None:
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        targets.consolidator_config.write_text(
            json.dumps(
                {
                    "name": "zikaron-consolidator",
                    "mcpServers": {
                        MCP_SERVER_NAME: {"command": "/some/other/venv/bin/zikaron-mcp"}
                    },
                }
            )
        )
        report = Report()
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
        rewritten = json.loads(targets.consolidator_config.read_text())
        assert rewritten["model"] == "a-model"
        assert report.replaced == [targets.consolidator_config]
        assert (tmp_path / ".kiro/agents/zikaron-consolidator.json.bak").is_file()
        assert any("named a different Zikaron install" in note for note in report.notes)

    def test_a_config_naming_this_install_is_kept(self, tmp_path: Path) -> None:
        """An ordinary re-run: an operator may have edited the prompt, and that must survive."""
        targets = Targets(project=tmp_path)
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, Report())
        edited = json.loads(targets.consolidator_config.read_text())
        edited["prompt"] = "my own consolidator prompt"
        targets.consolidator_config.write_text(json.dumps(edited))
        report = Report()
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
        assert json.loads(targets.consolidator_config.read_text())["prompt"] == (
            "my own consolidator prompt"
        )
        assert report.skipped == [targets.consolidator_config, targets.skill_file]
        assert report.replaced == []

    @pytest.mark.parametrize(
        "existing",
        [
            pytest.param("{not json", id="unparseable"),
            pytest.param("[1, 2, 3]", id="not an object"),
            pytest.param('{"name": "x"}', id="no server entry"),
            pytest.param('{"mcpServers": {"zikaron": "not an object"}}', id="server not an object"),
        ],
    )
    def test_a_config_that_cannot_be_read_as_one_is_also_replaced(
        self, tmp_path: Path, existing: str
    ) -> None:
        """Whatever these are, they are not a consolidator config this install can rely on — and the
        backup means rewriting them loses nothing.
        """
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        targets.consolidator_config.write_text(existing)
        report = Report()
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
        assert json.loads(targets.consolidator_config.read_text())["model"] == "a-model"
        assert report.replaced == [targets.consolidator_config]

    def test_a_config_that_cannot_be_backed_up_is_kept_rather_than_replaced_unbacked(
        self, tmp_path: Path
    ) -> None:
        """Correcting a stale artefact is worth doing, but not at the cost of losing what is there
        with no copy. Keeping a broken config is recoverable; replacing it unbacked is not.
        """
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        targets.consolidator_config.write_text('{"name": "unreadable"}')
        targets.consolidator_config.chmod(0o000)
        try:
            report = Report()
            write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
            assert targets.consolidator_config in report.skipped
            assert report.replaced == []
            assert any("could not be backed up" in note for note in report.notes)
        finally:
            targets.consolidator_config.chmod(0o600)

    def test_a_merge_whose_backup_path_is_blocked_is_refused(self, tmp_path: Path) -> None:
        """The same rule where it matters most: an edit to a file the user owns, with no recoverable
        copy of it, is refused rather than performed.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        (tmp_path / "mine.json.bak").mkdir()
        with pytest.raises(InstallError, match="not a regular file"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_the_skill_file_is_never_rewritten_on_staleness(self, tmp_path: Path) -> None:
        """The skill embeds no path, so it can never be stale in this sense — and an operator's edit
        to it must survive a re-run for that reason."""
        targets = Targets(project=tmp_path)
        targets.skill_file.parent.mkdir(parents=True)
        targets.skill_file.write_text("my own skill")
        report = Report()
        write_shipped_files(_plan(tmp_path), SKILL_MARKDOWN, report)
        assert targets.skill_file.read_text() == "my own skill"
        assert targets.skill_file in report.skipped


class TestShapesThatWouldBeSilentlyDropped:
    """Defensive filtering on a *write* path is data loss with a reassuring shape.

    Each of these values used to be filtered out by the merge and replaced with ours. They are
    things the user put there; this code cannot know what they meant, so it refuses.
    """

    def test_a_trigger_whose_value_is_not_an_array_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": {"stop": {"command": "mine"}}})
        before = config.read_text()
        with pytest.raises(InstallError, match=r"hooks\.stop"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    def test_a_tools_value_that_is_not_an_array_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": "read"})
        before = config.read_text()
        with pytest.raises(InstallError, match="`tools` value that is not an array"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    def test_a_reserved_array_entry_name_running_something_else_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The merge replaces an array entry by its `name`, so the guard must refuse by name too.
        Otherwise an entry called `zikaron-agentSpawn` running something else entirely is replaced
        without `--force`, silently.
        """
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "zikaron-agentSpawn",
                        "trigger": "agentSpawn",
                        "action": {"type": "command", "command": "/usr/bin/something-else"},
                    }
                ],
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError, match="differ from what this install would write"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestExplicitNullsAreValuesRatherThanAbsences:
    """JSON has a fourth scalar, and every one of these guards first read `is not None`.

    `"hooks": null` is something somebody wrote, not a key they omitted — and all three were
    silently replaced, which is exactly what the guards exist to refuse.
    """

    @pytest.mark.parametrize(
        ("document", "expected"),
        [
            pytest.param(
                {"name": "m", "hooks": None}, "neither an object nor an array", id="hooks"
            ),
            pytest.param({"name": "m", "tools": None}, "not an array", id="tools"),
            pytest.param({"name": "m", "mcpServers": None}, "not an object", id="mcpServers"),
        ],
    )
    def test_a_top_level_null_is_refused(
        self, tmp_path: Path, document: dict[str, object], expected: str
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, document)
        before = config.read_text()
        with pytest.raises(InstallError, match=expected):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    def test_a_null_zikaron_server_entry_is_refused_rather_than_replaced(
        self, tmp_path: Path
    ) -> None:
        """One level down, the same mistake: `existing_server is not None` skipped the guard for a
        present-but-null entry, so it was replaced without `--force`."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "m", "mcpServers": {MCP_SERVER_NAME: None}})
        before = config.read_text()
        with pytest.raises(InstallError, match="pointing somewhere else"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestAnEntryThatDiffersInAnyFieldIsRefused:
    """The contract says *differs from what this install would write*, and equality of the command
    alone is not equality of the entry.

    The case that matters is an operator who deliberately set their own `timeout_ms`: silently
    resetting it would discard a choice somebody made, and the refusal names the differing field so
    they can tell their own edit from a Zikaron version change.
    """

    def test_an_object_entry_with_the_current_command_but_a_changed_timeout(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": {"userPromptSubmit": [{"command": str(_COMMANDS.hook), "timeout_ms": 1}]},
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError, match="timeout_ms"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    def test_an_array_entry_with_the_reserved_name_but_a_changed_trigger(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "zikaron-agentSpawn",
                        "trigger": "stop",
                        "action": {"type": "command", "command": shlex.quote(str(_COMMANDS.hook))},
                        "timeout": 10,
                    }
                ],
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError, match="trigger"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    def test_an_identical_entry_is_not_a_refusal(self, tmp_path: Path) -> None:
        """Re-running the same install must stay safe, which is what makes the comparison structural
        rather than merely strict."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())

    def test_force_adopts_this_installs_entries(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": {"userPromptSubmit": [{"command": str(_COMMANDS.hook), "timeout_ms": 1}]},
            },
        )
        merge_agent_config(config, _plan(tmp_path, force=True), Report())
        entries = json.loads(config.read_text())["hooks"]["userPromptSubmit"]
        assert [entry["timeout_ms"] for entry in entries] == [TIMEOUT_MS]


class TestMergeRefusals:
    def test_a_config_wired_to_another_interpreter_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "mcpServers": {
                    MCP_SERVER_NAME: {
                        "command": str(_OTHER_COMMANDS.mcp),
                        "args": ["--mode", "primary"],
                    }
                },
            },
        )
        with pytest.raises(InstallError, match="pointing somewhere else"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_that_refusal_happens_before_anything_is_written(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "mcpServers": {MCP_SERVER_NAME: {"command": "/somewhere/else/zikaron-mcp"}},
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before
        assert not (tmp_path / "mine.json.bak").exists()

    def test_an_identical_existing_entry_is_not_a_refusal(self, tmp_path: Path) -> None:
        """Re-running an install must be safe; only a *different* entry is worth stopping for."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())

    def test_malformed_json_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        config.write_text("{not json")
        with pytest.raises(InstallError, match="not valid JSON"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_a_json_document_that_is_not_an_object_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        config.write_text("[1, 2, 3]")
        with pytest.raises(InstallError, match="not a JSON object"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_an_unreadable_config_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        config.chmod(0o000)
        try:
            with pytest.raises(InstallError, match="could not read"):
                merge_agent_config(config, _plan(tmp_path), Report())
        finally:
            config.chmod(0o600)


class TestTheSubagentToolNote:
    def test_it_says_so_when_the_tool_is_missing(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": ["read"]})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert any("subagent" in note for note in report.notes)

    def test_it_stays_quiet_when_the_tool_is_there(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": ["read", "subagent"]})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert not any("subagent" in note for note in report.notes)
