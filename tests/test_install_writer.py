"""`zikaron.install.writer` and `zikaron.install.kiro_merge`: what lands on disk, and what is
refused.

`architecture.md` §"The install contract" is normative, and `design/harness.md` §"The installer's
two targets" for the profile shapes kiro's V3 engine reads. The interesting behavior here is all
*refusal*: this is the one part of Zikaron that writes files a user owns, so every test below is
either "it did not clobber that" or "it said what it changed".
"""

import errno
import json
import os
import re
import shlex
from pathlib import Path
from typing import Final

import pytest

from zikaron.code_knowledge.main import DEFAULT_DOCUMENTS
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS
from zikaron.install.code_knowledge import DOCUMENTER_AGENT_NAME
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    MCP_SERVER_NAME,
    TOOL_SELECTOR,
    Commands,
    hooks_array,
)
from zikaron.install.harness import InstallError
from zikaron.install.kiro_merge import DOCUMENTS_DIRECTORY, plan_kiro_merge
from zikaron.install.targets import KiroTarget
from zikaron.install.writer import (
    Plan,
    Report,
    Targets,
    commit_merge,
    write_shipped_files,
)


def merge_agent_config(path: Path, plan: Plan, report: Report) -> None:
    """Plan and commit in one call, which is what every merge test below is asserting about.

    The two are separate in production so `main.py` can run every refusal before writing anything; a
    test that only cares about the merged result should not have to restate that ordering, and
    `tests/test_install_main.py` is where the ordering itself is asserted.
    """
    commit_merge(plan_kiro_merge(path, plan, Targets(project=plan.project)), report)


def write_kiro_files(plan: Plan, report: Report) -> None:
    """Kiro's shipped files, through the same target the installer uses.

    The content is asked of the target rather than restated, so these tests keep asserting about
    what an install actually writes rather than about a fixture that happens to resemble it.
    """
    write_shipped_files(KiroTarget().shipped_files(plan), plan, report)


_COMMANDS = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))

#: The agents the install adds to a populated crew, and the skills it declares, in its order.
_OURS = (CONSOLIDATOR_AGENT_NAME, DOCUMENTER_AGENT_NAME)
_SKILLS = (
    "skill://.kiro/skills/zikaron-consolidate/SKILL.md",
    "skill://.kiro/skills/zikaron-document-code/SKILL.md",
)
_OTHER_COMMANDS = Commands(
    hook=Path("/elsewhere/bin/zikaron-hook"), mcp=Path("/elsewhere/bin/zikaron-mcp")
)

#: The two rules a default merge adds to a profile's `permissions.rules`, spelled as
#: `kiro-cli agent upgrade` derives them from a V2 profile (`research/kiro-v3-probe.md` §2).
_MCP_RULE: Final[dict[str, object]] = {
    "capability": "mcp",
    "match": [f"{MCP_SERVER_NAME}/*"],
    "effect": "allow",
}
_SKILL_RULE: Final[dict[str, object]] = {"capability": "skill", "effect": "allow"}

#: The profile `kiro-cli agent create made` writes on 2.35.1 (`research/kiro-v3-probe.md` §22).
_AGENT_CREATE_PROFILE: Final[dict[str, object]] = {
    "name": "made",
    "description": "",
    "prompt": None,
    "mcpServers": {},
    "tools": ["*"],
    "toolAliases": {},
    "allowedTools": [],
    "resources": [],
    "toolsSettings": {},
    "includeMcpJson": True,
    "model": None,
    "permissions": {"rules": [{"capability": "fs_read", "match": ["./**"], "effect": "allow"}]},
    "kiroUpgrade": {
        "revision": 2,
        "fingerprint": "sha256:a491e259057c3401142cdb4355e2c5f8503003bce444a444fe1ffe204c5d33bd",
        "source": "sha256:aaf30cb0d6d67d98141d4bb0bd1cbebee05128584714ec0d5149e275bb2b15c1",
    },
}


def _plan(project: Path, *, force: bool = False, trust_tools: bool = True) -> Plan:
    return Plan(
        project=project,
        commands=_COMMANDS,
        consolidator_model="a-model",
        documenter_model="a-model",
        orchestrator_model="a-model",
        force=force,
        trust_tools=trust_tools,
    )


def _universal(**fields: object) -> dict[str, object]:
    """A profile carrying both engines' fields, `permissions` and `allowedTools`, as
    `kiro-cli agent create` writes one."""
    return {"name": "mine", "permissions": {"rules": []}, "allowedTools": [], **fields}


def _write_agent(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


class TestWritingTheShippedFiles:
    def test_it_creates_every_file_and_its_directories(self, tmp_path: Path) -> None:
        report = Report()
        write_kiro_files(_plan(tmp_path), report)
        targets = Targets(project=tmp_path)
        shipped = {
            targets.consolidator_config,
            targets.skill_file,
            targets.documenter_config,
            targets.document_skill_file,
        }
        assert all(path.is_file() for path in shipped)
        assert set(report.created) == shipped

    def test_the_written_config_is_json_carrying_the_planned_model(self, tmp_path: Path) -> None:
        write_kiro_files(_plan(tmp_path), Report())
        written = json.loads(Targets(project=tmp_path).consolidator_config.read_text())
        assert written["model"] == "a-model"

    def test_a_file_already_holding_what_we_ship_is_kept_untouched(self, tmp_path: Path) -> None:
        """The ordinary re-run, and the only case that is now "kept": the bytes on disk already are
        the bytes this install ships."""
        targets = Targets(project=tmp_path)
        write_kiro_files(_plan(tmp_path), Report())
        report = Report()
        write_kiro_files(_plan(tmp_path), report)
        assert report.skipped == [
            targets.consolidator_config,
            targets.skill_file,
            targets.documenter_config,
            targets.document_skill_file,
        ]
        assert report.replaced == []

    def test_a_hand_edited_file_is_backed_up_and_refreshed(self, tmp_path: Path) -> None:
        """**A deliberate reversal.** This test previously asserted the opposite — that an
        operator's edit to a shipped file survives a re-run — and that rule is what made the
        installer keep an *older version's* consolidator prompt on every upgrade and report it
        cheerfully as "already there". Content is the only evidence the installer has, and "an older
        Zikaron wrote this" and "a human edited this" are the same observation to it.

        So the trade was made the other way, and it is a trade rather than a strict improvement:
        a stale prompt is silent, routine (every upgrade) and actively misleading, while a clobbered
        edit is loud, backed up before it is touched, and reported. The supported way to vary
        shipped prose remains an override file — `architecture.md` §"The install contract" makes
        that argument for the write policy — not editing an installed artefact.

        The residual cost, stated because nothing else states it: `.bak` is first-wins, so a
        *second* hand edit is not preserved.
        """
        targets = Targets(project=tmp_path)
        write_kiro_files(_plan(tmp_path), Report())
        edited = json.loads(targets.consolidator_config.read_text())
        edited["prompt"] = "mine, edited"
        targets.consolidator_config.write_text(json.dumps(edited))
        report = Report()
        write_kiro_files(_plan(tmp_path), report)
        assert json.loads(targets.consolidator_config.read_text())["prompt"] != "mine, edited"
        assert report.replaced == [targets.consolidator_config]
        assert (
            json.loads((tmp_path / ".kiro/agents/zikaron-consolidator.json.bak").read_text())[
                "prompt"
            ]
            == "mine, edited"
        )

    def test_force_replaces_an_existing_file(self, tmp_path: Path) -> None:
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        targets.consolidator_config.write_text('{"name": "mine, edited"}')
        write_kiro_files(_plan(tmp_path, force=True), Report())
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
        write_kiro_files(_plan(tmp_path), report)
        assert elsewhere.read_text() == "untouched"
        assert report.skipped == [targets.consolidator_config]

    def test_force_through_a_symlink_replaces_the_link_not_its_target(self, tmp_path: Path) -> None:
        """`--force` means "replace the file I named", never "write into wherever it points"."""
        targets = Targets(project=tmp_path)
        targets.consolidator_config.parent.mkdir(parents=True)
        elsewhere = tmp_path / "somebody-elses-file"
        elsewhere.write_text("untouched")
        targets.consolidator_config.symlink_to(elsewhere)
        write_kiro_files(_plan(tmp_path, force=True), Report())
        assert elsewhere.read_text() == "untouched"
        assert not targets.consolidator_config.is_symlink()
        assert json.loads(targets.consolidator_config.read_text())["model"] == "a-model"


class TestAV2OnlyProfileIsRefused:
    """V3 skips a profile with a V2 trust field and no `permissions` for its default agent
    (`research/kiro-v3-probe.md` §1), so installing into one would install into a profile nothing
    loads. Converting the user's trust settings is `kiro-cli agent upgrade`'s job, and the refusal
    names it."""

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"name": "mine", "allowedTools": ["read"]}, id="allowedTools"),
            pytest.param({"name": "mine", "allowedTools": []}, id="an empty allowedTools"),
            pytest.param(
                {"name": "mine", "toolsSettings": {"shell": {"allowedCommands": ["ls"]}}},
                id="toolsSettings",
            ),
        ],
    )
    def test_it_is_refused_naming_the_upgrade_command(
        self, tmp_path: Path, document: dict[str, object]
    ) -> None:
        config = tmp_path / "agents" / "mine.json"
        _write_agent(config, document)
        before = config.read_text()
        upgrade = re.escape(f"kiro-cli agent upgrade {config.parent}")
        with pytest.raises(InstallError, match=upgrade):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before
        assert not config.with_name("mine.json.bak").exists()

    def test_an_empty_tools_settings_is_no_trust_field(self, tmp_path: Path) -> None:
        """`kiro-cli agent create` writes `"toolsSettings": {}`, and the upgrader calls a profile
        with no trust field universal, so counting `{}` would refuse a profile nothing converts."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "toolsSettings": {}})
        merge_agent_config(config, _plan(tmp_path), Report())
        written = json.loads(config.read_text())
        assert written["toolsSettings"] == {}
        assert written["permissions"] == {"rules": [_MCP_RULE, _SKILL_RULE]}


class TestHooksAreWrittenInTheArrayForm:
    def test_a_profile_with_no_hooks_gains_both_array_entries(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["hooks"] == hooks_array(_COMMANDS)

    def test_a_second_install_replaces_rather_than_duplicates(self, tmp_path: Path) -> None:
        """Two entries on one trigger would inject two blocks per user message."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["hooks"] == hooks_array(_COMMANDS)

    def test_a_users_own_array_entry_is_kept_beside_ours(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "git-status",
                        "trigger": "SessionStart",
                        "action": {"type": "command", "command": "git status"},
                    }
                ],
            },
        )
        merge_agent_config(config, _plan(tmp_path), Report())
        hooks = json.loads(config.read_text())["hooks"]
        assert [entry["name"] for entry in hooks] == [
            "git-status",
            "zikaron-SessionStart",
            "zikaron-UserPromptSubmit",
        ]

    def test_it_adds_the_primary_mcp_server_and_keeps_the_users_own(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "mcpServers": {"git": {"command": "mcp-server-git"}}})
        merge_agent_config(config, _plan(tmp_path), Report())
        servers = json.loads(config.read_text())["mcpServers"]
        assert set(servers) == {"git", MCP_SERVER_NAME}
        assert servers[MCP_SERVER_NAME]["args"] == ["--mode", "primary"]


class TestAnObjectFormatHooks:
    """V3 reads object-format `hooks` only as compatibility input, and a key is either an object or
    an array, so Zikaron's array entries cannot sit beside an object-format entry of the user's."""

    def test_one_holding_only_our_entries_is_rewritten_as_array_entries(
        self, tmp_path: Path
    ) -> None:
        """A pre-V3 install as it wrote itself: camelCase triggers, the command alone, and the two
        V2 limit fields."""
        old = {"command": shlex.quote(str(_COMMANDS.hook)), "timeout_ms": 10000}
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": {
                    "agentSpawn": [{**old, "max_output_size": 65536}],
                    "userPromptSubmit": [{**old, "max_output_size": 65536}],
                },
            },
        )
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert json.loads(config.read_text())["hooks"] == hooks_array(_COMMANDS)
        assert any("rewritten from the object form into the array form" in n for n in report.notes)

    def test_one_holding_a_users_entry_is_refused_showing_it_in_the_array_form(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "agents" / "mine.json"
        entry = {"command": "git status", "matcher": "fs_write", "timeout_ms": 1500}
        _write_agent(config, {"name": "mine", "hooks": {"agentSpawn": [entry]}})
        before = config.read_text()
        with pytest.raises(InstallError, match="in the object form") as raised:
            merge_agent_config(config, _plan(tmp_path), Report())
        converted = {
            "name": "agentSpawn-0",
            "trigger": "SessionStart",
            "matcher": "fs_write",
            "action": {"type": "command", "command": "git status"},
            "timeout": 2,
        }
        assert json.dumps([converted]) in str(raised.value)
        assert config.read_text() == before
        assert not config.with_name("mine.json.bak").exists()

    def test_an_empty_object_is_rewritten_with_no_note(self, tmp_path: Path) -> None:
        """Nothing of Zikaron's was there to rewrite, so the install says nothing about it."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": {}})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert json.loads(config.read_text())["hooks"] == hooks_array(_COMMANDS)
        assert not any("rewritten from the object form" in note for note in report.notes)

    @pytest.mark.parametrize(
        "theirs",
        [{"timeout_ms": 1500}, {"command": "'unbalanced quote"}],
        ids=["no command", "unbalanced quotes"],
    )
    def test_an_entry_whose_command_is_no_program_is_the_users(
        self, tmp_path: Path, theirs: dict[str, object]
    ) -> None:
        """Neither names an executable, so neither can be Zikaron's, and the object form is refused
        rather than the entry dropped."""
        config = tmp_path / "agents" / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": {"userPromptSubmit": [theirs]}})
        with pytest.raises(InstallError, match="in the object form"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_the_refusal_names_the_upgrader_only_for_a_profile_it_would_convert(
        self, tmp_path: Path
    ) -> None:
        """The upgrader converts the hooks of a profile without `permissions` and leaves one that
        has them untouched, as out of sync (`research/kiro-v3-probe.md` §19)."""
        hooks = {"stop": [{"command": "git status"}]}
        bare = tmp_path / "bare" / "mine.json"
        _write_agent(bare, {"name": "mine", "hooks": hooks})
        with pytest.raises(InstallError) as without_permissions:
            merge_agent_config(bare, _plan(tmp_path), Report())
        assert f"`kiro-cli agent upgrade {bare.parent}` converts it" in str(
            without_permissions.value
        )

        permitted = tmp_path / "permitted" / "mine.json"
        _write_agent(permitted, {"name": "mine", "permissions": {"rules": []}, "hooks": hooks})
        with pytest.raises(InstallError) as with_permissions:
            merge_agent_config(permitted, _plan(tmp_path), Report())
        assert "Rewrite `hooks` in that form" in str(with_permissions.value)
        assert "kiro-cli agent upgrade" not in str(with_permissions.value)

    def test_an_entry_that_is_not_an_object_is_refused_rather_than_crashing(
        self, tmp_path: Path
    ) -> None:
        """It is the user's, so it is refused like any other entry of theirs, and quoted as it
        stands since it has no array form."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": {"agentSpawn": ["not an object"]}})
        with pytest.raises(InstallError, match=re.escape('yours read: ["not an object"]')):
            merge_agent_config(config, _plan(tmp_path), Report())

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
        assert json.loads(config.read_text())["hooks"] == hooks_array(_COMMANDS)


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

    def test_a_tools_list_selecting_every_tool_gains_nothing_and_says_nothing(
        self, tmp_path: Path
    ) -> None:
        """`*` already selects Zikaron's tools, so adding `@zikaron` beside it, or a note saying it
        was added, would only be noise."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": ["*"]})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert json.loads(config.read_text())["tools"] == ["*"]
        assert not any(f"`{TOOL_SELECTOR}` to" in note for note in report.notes)

    def test_a_non_array_allowed_tools_is_refused_rather_than_replaced(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "allowedTools": "read"})
        before = config.read_text()
        with pytest.raises(InstallError, match="`allowedTools` value that is not an array"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestTheV2HalfOfAUniversalProfile:
    """kiro documents that the TUI rebuilds an out-of-sync profile's V3 fields from its V2 ones, so
    a universal profile's `allowedTools` gains `@zikaron` beside the `mcp` rule, and a rebuild
    should regenerate the rule. A profile with no V2 half has nothing to feed."""

    def test_a_universal_profile_gains_the_selector_in_allowed_tools(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, _universal(allowedTools=["read"]))
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["allowedTools"] == ["read", TOOL_SELECTOR]

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"name": "mine", "permissions": {"rules": []}}, id="permissions"),
            pytest.param({"name": "mine"}, id="no trust field"),
        ],
    )
    def test_a_v3_only_profile_gains_no_allowed_tools(
        self, tmp_path: Path, document: dict[str, object]
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, document)
        merge_agent_config(config, _plan(tmp_path), Report())
        assert "allowedTools" not in json.loads(config.read_text())

    def test_allowed_tools_is_left_alone_when_the_prompts_are_wanted(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, _universal(allowedTools=["read"]))
        merge_agent_config(config, _plan(tmp_path, trust_tools=False), Report())
        assert json.loads(config.read_text())["allowedTools"] == ["read"]

    def test_a_second_install_does_not_add_it_to_allowed_tools_twice(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, _universal())
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["allowedTools"] == [TOOL_SELECTOR]


class TestThePermissionRules:
    """Under V3 a call no rule allows asks, and a headless run refuses every ask. So a default merge
    writes the `mcp` rule over Zikaron's tools, and the `skill` rule, without which neither skill
    loads headless (`research/kiro-v3-probe.md` §24). Asserted on `plan_kiro_merge`'s document, the
    one place both are decided."""

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"name": "mine"}, id="V3-only"),
            pytest.param(_universal(), id="universal"),
        ],
    )
    def test_both_rules_are_written_by_default(
        self, tmp_path: Path, document: dict[str, object]
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, document)
        merge = plan_kiro_merge(config, _plan(tmp_path), Targets(project=tmp_path))
        assert merge.document["permissions"] == {"rules": [_MCP_RULE, _SKILL_RULE]}

    def test_the_users_own_rules_and_fields_are_kept_ahead_of_ours(self, tmp_path: Path) -> None:
        mine = {"capability": "fs_read", "match": ["./**"], "effect": "allow"}
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "permissions": {"rules": [mine], "note": "kept"}})
        merge = plan_kiro_merge(config, _plan(tmp_path), Targets(project=tmp_path))
        assert merge.document["permissions"] == {
            "rules": [mine, _MCP_RULE, _SKILL_RULE],
            "note": "kept",
        }

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param({"name": "mine"}, id="V3-only"),
            pytest.param(_universal(), id="universal"),
        ],
    )
    def test_neither_is_written_under_no_trust_tools_and_the_note_names_both(
        self, tmp_path: Path, document: dict[str, object]
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, document)
        merge = plan_kiro_merge(
            config, _plan(tmp_path, trust_tools=False), Targets(project=tmp_path)
        )
        assert merge.document.get("permissions") == document.get("permissions")
        (note,) = [note for note in merge.notes if "--no-trust-tools" in note]
        assert "two rules" in note
        assert "`mcp` over `zikaron/*`" in note
        assert "`skill`" in note

    def test_a_re_install_over_equal_rules_adds_neither_again(self, tmp_path: Path) -> None:
        """The upgrader derives both rules from a V2 profile, so a profile it converted already
        carries them, in its own order."""
        config = tmp_path / "mine.json"
        rules = [_SKILL_RULE, {"capability": "fs_read", "effect": "allow"}, _MCP_RULE]
        _write_agent(config, {"name": "mine", "permissions": {"rules": rules}})
        merge = plan_kiro_merge(config, _plan(tmp_path), Targets(project=tmp_path))
        assert merge.document["permissions"] == {"rules": rules}

    def test_a_second_install_adds_neither_twice(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["permissions"] == {"rules": [_MCP_RULE, _SKILL_RULE]}


class TestAProfileKiroCliAgentCreateWrote:
    """The common first install: a profile `kiro-cli agent create` wrote, named straight away with
    `--agent`. It is universal, and its `tools` holds `*`."""

    def _merged(self, tmp_path: Path) -> tuple[dict[str, object], tuple[str, ...]]:
        config = tmp_path / "made.json"
        _write_agent(config, _AGENT_CREATE_PROFILE)
        merge = plan_kiro_merge(config, _plan(tmp_path), Targets(project=tmp_path))
        return merge.document, merge.notes

    def test_its_tools_gain_no_selector_and_no_note_about_one(self, tmp_path: Path) -> None:
        document, notes = self._merged(tmp_path)
        assert document["tools"] == ["*"]
        assert not any(f"`{TOOL_SELECTOR}` to" in note for note in notes)

    def test_it_gains_the_selector_in_allowed_tools_and_both_rules(self, tmp_path: Path) -> None:
        document, _notes = self._merged(tmp_path)
        assert document["allowedTools"] == [TOOL_SELECTOR]
        assert document["permissions"] == {
            "rules": [
                {"capability": "fs_read", "match": ["./**"], "effect": "allow"},
                _MCP_RULE,
                _SKILL_RULE,
            ]
        }
        assert document["toolsSettings"] == {}

    def test_it_is_reported_as_out_of_sync_with_its_grant_in_both_halves(
        self, tmp_path: Path
    ) -> None:
        _document, notes = self._merged(tmp_path)
        (note,) = [note for note in notes if "out of sync" in note]
        assert "Zikaron's grant is in both" in note
        assert "`kiro-cli agent create`" in note, "an agent-created profile carries `kiroUpgrade`"

    def test_a_v3_only_upgraded_profile_is_told_what_a_rebuild_would_drop(
        self, tmp_path: Path
    ) -> None:
        """Its V2 fields carry nothing of Zikaron's, so a rebuild from them would lose the rule."""
        config = tmp_path / "mine.json"
        upgrade = _AGENT_CREATE_PROFILE["kiroUpgrade"]
        _write_agent(config, {"name": "mine", "permissions": {"rules": []}, "kiroUpgrade": upgrade})
        merge = plan_kiro_merge(config, _plan(tmp_path), Targets(project=tmp_path))
        (note,) = [note for note in merge.notes if "out of sync" in note]
        assert "carry none of Zikaron's grant" in note


class TestTheCrewOfAUniversalProfile:
    """The skills spawn the consolidator and the documenter, and
    `toolsSettings.crew.availableAgents` gates which agents may be spawned. Fed on a universal
    profile for the reason `allowedTools` is: the upgrader converts `toolsSettings` into rules, so a
    rebuild of the V3 half reads it.

    The list is a restriction: an absent or empty `availableAgents` means *every* agent is
    available, so adding one entry there would narrow the config rather than widen it.
    """

    def test_a_populated_available_list_gains_both_agents(self, tmp_path: Path) -> None:
        """The reported bug, exactly: the user's own agents listed, ours missing."""
        config = tmp_path / "mine.json"
        crew = {"availableAgents": ["helper-a", "helper-b"], "trustedAgents": ["helper-a"]}
        _write_agent(config, _universal(toolsSettings={"crew": crew}))
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        merged = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert merged["availableAgents"] == ["helper-a", "helper-b", *_OURS]
        assert merged["trustedAgents"] == ["helper-a"], "spawn trust is a separate grant, not ours"
        for agent in _OURS:
            assert any(agent in note and "availableAgents" in note for note in report.notes)

    def test_a_v3_only_profiles_tools_settings_is_left_untouched(self, tmp_path: Path) -> None:
        """Whether V3 reads `toolsSettings` at all is a conflict in kiro's own documentation, and a
        V3-only profile has no V2 half for a rebuild to read."""
        config = tmp_path / "mine.json"
        settings = {"crew": {"availableAgents": ["helper-a"]}}
        _write_agent(
            config, {"name": "mine", "permissions": {"rules": []}, "toolsSettings": settings}
        )
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert json.loads(config.read_text())["toolsSettings"] == settings
        assert not any("availableAgents" in note for note in report.notes)

    def test_an_absent_available_list_is_left_alone_rather_than_narrowed(
        self, tmp_path: Path
    ) -> None:
        """The trap. An absent list means every agent is available; writing one entry into it would
        restrict the config to Zikaron's agents alone and silently break every other subagent the
        user has. Nothing is added at all in that case, so no `toolsSettings` block appears either.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, _universal())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert "toolsSettings" not in json.loads(config.read_text())

    def test_an_empty_available_list_is_treated_the_same_as_an_absent_one(
        self, tmp_path: Path
    ) -> None:
        """`[]` and absent mean the same thing to the harness, so they must mean the same here — a
        fixture with a populated list cannot tell these two branches apart."""
        config = tmp_path / "mine.json"
        _write_agent(config, _universal(toolsSettings={"crew": {"availableAgents": []}}))
        merge_agent_config(config, _plan(tmp_path), Report())
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == []
        assert "trustedAgents" not in crew

    def test_the_agent_crew_alias_is_updated_in_place(self, tmp_path: Path) -> None:
        """`agent_crew` is a documented alias for the same block. Writing a second `crew` key beside
        it would leave two blocks whose relationship the harness does not define.
        """
        config = tmp_path / "mine.json"
        _write_agent(
            config, _universal(toolsSettings={"agent_crew": {"availableAgents": ["helper-a"]}})
        )
        merge_agent_config(config, _plan(tmp_path), Report())
        settings = json.loads(config.read_text())["toolsSettings"]
        assert "crew" not in settings
        assert settings["agent_crew"]["availableAgents"] == ["helper-a", *_OURS]

    def test_other_tools_settings_survive(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            _universal(
                toolsSettings={
                    "write": {"allowedPaths": ["src/**"]},
                    "crew": {"availableAgents": ["helper-a"]},
                }
            ),
        )
        merge_agent_config(config, _plan(tmp_path), Report())
        settings = json.loads(config.read_text())["toolsSettings"]
        assert settings["write"] == {"allowedPaths": ["src/**"]}

    def test_a_second_install_does_not_duplicate_the_entry(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, _universal(toolsSettings={"crew": {"availableAgents": ["helper-a"]}}))
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == ["helper-a", *_OURS]

    def test_an_agent_already_listed_is_not_added_again(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        crew = {"availableAgents": ["helper-a", CONSOLIDATOR_AGENT_NAME]}
        _write_agent(config, _universal(toolsSettings={"crew": crew}))
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        merged = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert merged["availableAgents"] == ["helper-a", *_OURS]
        added = [note for note in report.notes if note.startswith("Added `zikaron-")]
        assert added == [next(note for note in added if DOCUMENTER_AGENT_NAME in note)]

    def test_an_existing_trusted_agents_list_is_never_touched(self, tmp_path: Path) -> None:
        """Spawn trust is a wider grant than Zikaron's tools — its own model invocation and four
        mutation verbs — so it stays the user's decision even under `--force`."""
        config = tmp_path / "mine.json"
        crew = {"availableAgents": ["a"], "trustedAgents": ["a"]}
        _write_agent(config, _universal(toolsSettings={"crew": crew}))
        merge_agent_config(config, _plan(tmp_path, force=True), Report())
        assert json.loads(config.read_text())["toolsSettings"]["crew"]["trustedAgents"] == ["a"]

    def test_the_alias_with_no_available_list_is_left_alone(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, _universal(toolsSettings={"agent_crew": {}}))
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["toolsSettings"] == {"agent_crew": {}}

    def test_a_populated_available_list_is_still_extended_without_trust(
        self, tmp_path: Path
    ) -> None:
        """`--no-trust-tools` is about approval prompts, not availability: the skill still has to be
        able to spawn the consolidator at all."""
        config = tmp_path / "mine.json"
        _write_agent(config, _universal(toolsSettings={"crew": {"availableAgents": ["helper-a"]}}))
        merge_agent_config(config, _plan(tmp_path, trust_tools=False), Report())
        crew = json.loads(config.read_text())["toolsSettings"]["crew"]
        assert crew["availableAgents"] == ["helper-a", *_OURS]
        assert "trustedAgents" not in crew


class TestTheSkillIsAlwaysDeclared:
    """Skills reach an agent through `resources`, and also arrive by inheritance without one.

    The entry is written whenever nothing already covers it, because the one documented
    configuration where inheritance is off would otherwise get a warning instead of a working
    skill — and declaring resources does not disable inheritance, so adding it narrows nothing.
    """

    def test_a_config_with_no_resources_gets_the_skill_declared(self, tmp_path: Path) -> None:
        """Inheritance usually covers the skill, but `chat.disableInheritingDefaultResources` turns
        that off — and a note is not a delivered skill. The entry is additive, since declaring
        resources does not disable inheritance, so it is written either way.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert json.loads(config.read_text())["resources"] == list(_SKILLS)
        assert sum("reachable whether or not" in note for note in report.notes) == len(_SKILLS)

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
        assert json.loads(config.read_text())["resources"] == ["file://NOTES.md", *_SKILLS]
        assert any("`resources`" in note for note in report.notes)

    def test_a_skill_already_declared_is_not_declared_again(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "resources": [_SKILLS[1]]})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["resources"] == [_SKILLS[1], _SKILLS[0]]

    def test_a_second_install_does_not_add_it_twice(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "resources": []})
        merge_agent_config(config, _plan(tmp_path), Report())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["resources"] == list(_SKILLS)

    def test_a_resources_value_that_is_not_an_array_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "resources": "file://NOTES.md"})
        before = config.read_text()
        with pytest.raises(InstallError, match="`resources` value that is not an array"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestACrewBlockThisCannotMergeIntoIsRefused:
    """On a universal profile, the one shape whose crew is merged into."""

    def test_both_crew_spellings_at_once_is_refused(self, tmp_path: Path) -> None:
        """They are documented as aliases for one block, so a config carrying both has no defined
        meaning — and picking one silently would ignore whatever the user put in the other.
        """
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            _universal(
                toolsSettings={
                    "crew": {"availableAgents": ["helper-a"]},
                    "agent_crew": {"availableAgents": ["helper-b"]},
                }
            ),
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
        _write_agent(config, _universal(toolsSettings=settings))
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

    def test_an_array_entry_that_is_not_an_object_is_left_alone_rather_than_crashing(
        self, tmp_path: Path
    ) -> None:
        """The harness would reject this config, but we read it before the harness does — and the
        useful behavior is to add our entries and leave the oddity for the harness to complain
        about, not to raise on a file we were only asked to merge into.
        """
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": ["not an object"]})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["hooks"] == [
            "not an object",
            *hooks_array(_COMMANDS),
        ]


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
        write_kiro_files(_plan(tmp_path), Report())
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
            write_kiro_files(_plan(tmp_path), Report())
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
        merged = json.loads(config.read_text())
        del merged["mcpServers"]
        _write_agent(config, merged)
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert (tmp_path / "mine.json.bak").read_text() == original
        assert report.backed_up == []
        assert any("left as it was" in note for note in report.notes)

    def test_a_merge_that_changes_nothing_backs_up_and_writes_nothing(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine"})
        merge_agent_config(config, _plan(tmp_path), Report())
        (tmp_path / "mine.json.bak").unlink()
        inode, content = config.stat().st_ino, config.read_bytes()
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert (config.stat().st_ino, config.read_bytes()) == (inode, content)
        assert not (tmp_path / "mine.json.bak").exists()
        assert (report.current, report.merged, report.backed_up) == ([config], [], [])


class TestAStaleShippedConfigIsCorrectedRatherThanKept:
    """Two ways a shipped file goes stale, and one predicate covers both.

    A **cloned repository** arrives with these artefacts tracked, carrying another machine's paths:
    kept as-is that is a consolidator that can never start, and reported as "already there" it is a
    confidently stale artefact. An **upgrade** leaves the paths correct and the prose a version
    behind, which the original interpreter-comparison could not see at all. Both are now the same
    observation — the bytes on disk are not the bytes this install ships — so both are backed up,
    rewritten, and reported.
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
        write_kiro_files(_plan(tmp_path), report)
        rewritten = json.loads(targets.consolidator_config.read_text())
        assert rewritten["model"] == "a-model"
        assert report.replaced == [targets.consolidator_config]
        assert (tmp_path / ".kiro/agents/zikaron-consolidator.json.bak").is_file()
        assert any("differed from what this install ships" in note for note in report.notes)

    def test_an_older_versions_config_is_refreshed_rather_than_kept(self, tmp_path: Path) -> None:
        """The case the interpreter check could not see, and the reason it was replaced.

        This config names *this* install's own interpreter — so the old predicate answered "not
        stale" and kept it — while carrying a prompt no current Zikaron would write. That is an
        upgrade, and it is the common one: the paths are right and the prose is a version behind.
        """
        targets = Targets(project=tmp_path)
        write_kiro_files(_plan(tmp_path), Report())
        outdated = json.loads(targets.consolidator_config.read_text())
        outdated["prompt"] = "the prompt an older Zikaron shipped"
        targets.consolidator_config.write_text(json.dumps(outdated))
        report = Report()
        write_kiro_files(_plan(tmp_path), report)
        assert "the prompt an older Zikaron shipped" not in (
            targets.consolidator_config.read_text()
        )
        assert report.replaced == [targets.consolidator_config]

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
        write_kiro_files(_plan(tmp_path), report)
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
            write_kiro_files(_plan(tmp_path), report)
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

    def test_the_skill_file_is_refreshed_too(self, tmp_path: Path) -> None:
        """**A deliberate reversal**, and this one was a plain defect rather than a trade.

        The skill embeds no interpreter path, so the old predicate — "does this name a different
        install" — could never be true of it, and it was written as the constant `False`. The effect
        was that the shipped skill could **never** be refreshed by any re-run: every edit to
        `SKILL.md` between versions reached new installs and no existing one. Content comparison
        covers every shipped file by construction rather than one at a time, which is why the fix is
        a smaller predicate rather than a second special case.
        """
        targets = Targets(project=tmp_path)
        targets.skill_file.parent.mkdir(parents=True)
        targets.skill_file.write_text("my own skill")
        report = Report()
        write_kiro_files(_plan(tmp_path), report)
        assert targets.skill_file.read_text() != "my own skill"
        assert targets.skill_file in report.replaced
        assert targets.skill_file.with_name("SKILL.md.bak").read_text() == "my own skill"


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
        Otherwise an entry called `zikaron-SessionStart` running something else entirely is
        replaced without `--force`, silently.
        """
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "zikaron-SessionStart",
                        "trigger": "SessionStart",
                        "action": {"type": "command", "command": "/usr/bin/something-else"},
                    }
                ],
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError, match="differ from what this install would write"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestATopLevelNullIsAnAbsence:
    """**`null` is how kiro spells *unset*, and it writes it itself** — so a top-level `null` is
    merged into, not refused.

    ~~These guards once refused it, on the reading that `"hooks": null` is something somebody wrote
    rather than a key they omitted.~~ **Reversed on a measurement against the real binary,
    2026-09-24**: `kiro-cli agent create` emits `toolsSettings`, `toolSchema`, `welcomeMessage` and
    `model` as `null`, and `kiro-cli chat --agent <name>` runs that agent normally. The old reading
    made this installer refuse the harness's own default output — the modal input to `--agent` —
    and told the user to repair a file they never hand-wrote. The withdrawal is recorded rather
    than deleted because *nulls are values* is what anyone would propose from the JSON alone.

    **What the guards were protecting is untouched.** They exist to refuse the *silent replacement
    of data*, and `null` carries none: merging over it destroys nothing, exactly as merging into an
    absent key does. A value of the wrong **type** — a string `tools`, an object `hooks` — is still
    refused, and so is a null entry one level down under our own server name, below.
    """

    @pytest.mark.parametrize(
        "key", ["hooks", "tools", "allowedTools", "mcpServers", "resources", "permissions"]
    )
    def test_a_top_level_null_is_merged_into(self, tmp_path: Path, key: str) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "m", key: None})
        merge_agent_config(config, _plan(tmp_path), Report())
        written = json.loads(config.read_text())
        assert written["mcpServers"][MCP_SERVER_NAME]["command"].endswith("zikaron-mcp")
        assert written["hooks"]

    def test_a_null_tools_settings_is_merged_into(self, tmp_path: Path) -> None:
        """The exact shape `kiro-cli agent create` writes, which this refused until it was run."""
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "m", "toolsSettings": None, "model": None})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["mcpServers"][MCP_SERVER_NAME]

    @pytest.mark.parametrize(
        ("document", "expected"),
        [
            pytest.param({"name": "m", "hooks": 7}, "neither an object nor an array", id="hooks"),
            pytest.param({"name": "m", "tools": "all"}, "not an array", id="tools"),
            pytest.param({"name": "m", "mcpServers": []}, "not an object", id="mcpServers"),
            pytest.param(_universal(toolsSettings="x"), "not an object", id="toolsSettings"),
            pytest.param(
                {"name": "m", "permissions": []},
                "`permissions` value that is not an object",
                id="permissions",
            ),
            pytest.param(
                {"name": "m", "permissions": {"rules": {}}},
                r"`permissions\.rules` as dict rather than an array",
                id="permissions.rules",
            ),
        ],
    )
    def test_a_wrong_type_is_still_refused(
        self, tmp_path: Path, document: dict[str, object], expected: str
    ) -> None:
        """The half that stands: this is data the user put there, and a merge would destroy it."""
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
        with pytest.raises(InstallError, match="differ from what this install would write"):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before


class TestOwnershipDecidesARefusal:
    """An entry is refused only when another install owns it: a server entry by its command and
    mode, a hook entry by its command. Any other difference is this install's own entry from an
    earlier version, which is rewritten and reported — refusing it would block every upgrade the day
    an entry gained a field or a timeout moved.
    """

    def test_an_earlier_install_upgrades_without_force_and_says_what_it_changed(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "zikaron-UserPromptSubmit",
                        "trigger": "UserPromptSubmit",
                        "action": {"type": "command", "command": shlex.quote(str(_COMMANDS.hook))},
                        "timeout": 1,
                    }
                ],
                "mcpServers": {
                    MCP_SERVER_NAME: {
                        "command": str(_COMMANDS.mcp),
                        "args": ["--mode", "primary"],
                        "env": {"MINE": "1"},
                    }
                },
            },
        )
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        written = json.loads(config.read_text())
        assert written["hooks"] == hooks_array(_COMMANDS)
        assert written["mcpServers"][MCP_SERVER_NAME]["env"] == {"MINE": "1"}
        notes = "\n".join(report.notes)
        assert "hook on zikaron-UserPromptSubmit differed in `action`, `timeout`" in notes
        assert "`env`" in notes

    def test_an_earlier_array_install_upgrades_without_force(self, tmp_path: Path) -> None:
        """Recognised by its reserved `name`, so a changed `trigger` is a field of our own entry."""
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "zikaron-SessionStart",
                        "trigger": "Stop",
                        "action": {"type": "command", "command": shlex.quote(str(_COMMANDS.hook))},
                        "timeout": HOOK_TIMEOUT_SECONDS,
                    }
                ],
            },
        )
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        hooks = json.loads(config.read_text())["hooks"]
        spawn = [entry for entry in hooks if entry["name"] == "zikaron-SessionStart"]
        assert [entry["trigger"] for entry in spawn] == ["SessionStart"]
        assert any("zikaron-SessionStart" in note and "trigger" in note for note in report.notes)

    def test_our_command_on_a_trigger_this_install_does_not_write_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        """Nothing here replaces it, so it is neither compared nor touched."""
        mine = {
            "name": "my-stop",
            "trigger": "Stop",
            "action": {"type": "command", "command": shlex.quote(str(_COMMANDS.hook))},
            "timeout": 5,
        }
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": [mine]})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["hooks"] == [mine, *hooks_array(_COMMANDS)]

    def test_our_command_on_such_a_trigger_in_the_object_form_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The object form cannot be kept beside array entries, and this install has no entry to
        rewrite it into, so it is the user's to convert."""
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {"name": "mine", "hooks": {"stop": [{"command": shlex.quote(str(_COMMANDS.hook))}]}},
        )
        with pytest.raises(InstallError, match="in the object form"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_an_unnamed_array_entry_running_our_command_is_replaced_not_duplicated(
        self, tmp_path: Path
    ) -> None:
        """Recognised by its command when it carries no reserved `name`; an entry that is not an
        object is the user's, and is kept as it stands."""
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    "a note of the user's",
                    {
                        "name": "renamed-by-hand",
                        "trigger": "UserPromptSubmit",
                        "action": {"type": "command", "command": shlex.quote(str(_COMMANDS.hook))},
                    },
                ],
            },
        )
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        hooks = json.loads(config.read_text())["hooks"]
        assert "a note of the user's" in hooks
        prompt = [h for h in hooks if isinstance(h, dict) and h["trigger"] == "UserPromptSubmit"]
        assert [entry["name"] for entry in prompt] == ["zikaron-UserPromptSubmit"]
        (note,) = [note for note in report.notes if "hook on UserPromptSubmit differed" in note]
        assert "`name`" in note

    def test_an_unhashable_name_or_trigger_is_left_alone_rather_than_crashing(
        self, tmp_path: Path
    ) -> None:
        odd = {"name": ["x"], "trigger": {"y": 1}, "action": {"type": "command", "command": "z"}}
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "hooks": [odd]})
        merge_agent_config(config, _plan(tmp_path), Report())
        assert odd in json.loads(config.read_text())["hooks"]

    def test_an_array_entry_from_another_interpreter_is_refused(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "zikaron-UserPromptSubmit",
                        "trigger": "UserPromptSubmit",
                        "action": {
                            "type": "command",
                            "command": f"exec {shlex.quote(str(_OTHER_COMMANDS.hook))}",
                        },
                    }
                ],
            },
        )
        before = config.read_text()
        with pytest.raises(InstallError, match=str(_OTHER_COMMANDS.hook)):
            merge_agent_config(config, _plan(tmp_path), Report())
        assert config.read_text() == before

    def test_another_installs_exec_entry_is_recognized_by_its_command_and_refused(
        self, tmp_path: Path
    ) -> None:
        """Read past its `exec`, an entry under a name of the user's choosing is still found to run
        a `zikaron-hook`, so a second install is refused rather than left beside this one."""
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "hooks": [
                    {
                        "name": "renamed-by-hand",
                        "trigger": "SessionStart",
                        "action": {
                            "type": "command",
                            "command": f"exec {shlex.quote(str(_OTHER_COMMANDS.hook))}",
                        },
                    }
                ],
            },
        )
        with pytest.raises(InstallError, match="differ from what this install would write"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_a_server_entry_in_another_mode_is_refused_and_names_the_mode(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "mcpServers": {
                    MCP_SERVER_NAME: {
                        "command": str(_COMMANDS.mcp),
                        "args": ["--mode", "consolidator"],
                    }
                },
            },
        )
        with pytest.raises(InstallError, match=r"args is \['--mode', 'consolidator'\]"):
            merge_agent_config(config, _plan(tmp_path), Report())

    def test_force_replaces_a_server_entry_whole_and_names_what_it_dropped(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(
            config,
            {
                "name": "mine",
                "mcpServers": {
                    MCP_SERVER_NAME: {"command": str(_OTHER_COMMANDS.mcp), "env": {"MINE": "1"}}
                },
            },
        )
        report = Report()
        merge_agent_config(config, _plan(tmp_path, force=True), report)
        assert "env" not in json.loads(config.read_text())["mcpServers"][MCP_SERVER_NAME]
        assert any("--force" in note and "`env`" in note for note in report.notes)
        assert not any("`args`" in note for note in report.notes), "a takeover is not announced"

    def test_an_identical_entry_is_not_a_refusal(self, tmp_path: Path) -> None:
        """Re-running the same install must stay safe."""
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
                "hooks": [
                    {
                        "name": "zikaron-UserPromptSubmit",
                        "trigger": "UserPromptSubmit",
                        "action": {"type": "command", "command": str(_COMMANDS.hook)},
                        "timeout": 1,
                    }
                ],
            },
        )
        merge_agent_config(config, _plan(tmp_path, force=True), Report())
        assert json.loads(config.read_text())["hooks"] == hooks_array(_COMMANDS)


class TestAProfileTheUpgraderConverted:
    """`kiro-cli agent upgrade` converts a pre-V3 install's object-format entries into array
    entries it names `agentSpawn-0` and `userPromptSubmit-0`, keeping the camelCase triggers and
    adding a `maxOutputSize` (`research/kiro-v3-probe.md` §2). Ownership reads a trigger by meaning
    and a command past `exec`, so an install over that profile rewrites those entries rather than
    running the hook twice per session."""

    @staticmethod
    def _converted() -> dict[str, object]:
        def entry(trigger: str) -> dict[str, object]:
            return {
                "name": f"{trigger}-0",
                "trigger": trigger,
                "action": {"type": "command", "command": f"'{_COMMANDS.hook}'"},
                "timeout": 10,
                "maxOutputSize": 65536,
            }

        return {
            "name": "mine",
            "tools": [TOOL_SELECTOR],
            "allowedTools": [TOOL_SELECTOR],
            "hooks": [entry("agentSpawn"), entry("userPromptSubmit")],
            "mcpServers": {
                MCP_SERVER_NAME: {"command": str(_COMMANDS.mcp), "args": ["--mode", "primary"]}
            },
            "permissions": {
                "rules": [{"capability": "fs_read", "effect": "allow"}, _MCP_RULE, _SKILL_RULE]
            },
            "kiroUpgrade": _AGENT_CREATE_PROFILE["kiroUpgrade"],
        }

    def test_the_install_over_it_writes_one_entry_per_v3_trigger(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, self._converted())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert json.loads(config.read_text())["hooks"] == hooks_array(_COMMANDS)

    def test_a_second_install_over_it_changes_nothing(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, self._converted())
        merge_agent_config(config, _plan(tmp_path), Report())
        assert plan_kiro_merge(config, _plan(tmp_path), Targets(project=tmp_path)).unchanged


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
        with pytest.raises(InstallError, match=rf"command is '{_OTHER_COMMANDS.mcp}'"):
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


class TestTheBuiltInGrantNotes:
    """Under V3 a built-in tool takes both a `tools` entry and an allow rule: without the rule kiro
    asks, and a headless run refuses (`research/kiro-v3-probe.md` §11). Granting either is the
    user's decision, so the install says which is missing and grants nothing.

    Asserted on each note's own clause rather than on the tool's bare name, which other notes
    mention too.
    """

    @pytest.mark.parametrize("tool", ["subagent", "shell"])
    @pytest.mark.parametrize(
        ("tools", "rules"),
        [
            pytest.param(["read"], [], id="neither"),
            pytest.param(["read", "subagent", "shell"], [], id="listed without its rule"),
            pytest.param(
                ["read"],
                [
                    {"capability": "subagent", "effect": "allow"},
                    {"capability": "shell", "effect": "allow"},
                ],
                id="a rule but not listed",
            ),
        ],
    )
    def test_it_says_so_unless_the_tool_is_both_listed_and_allowed(
        self, tmp_path: Path, tool: str, tools: list[str], rules: list[dict[str, object]]
    ) -> None:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": tools, "permissions": {"rules": rules}})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert any(f"does not grant the `{tool}` tool" in note for note in report.notes)

    @pytest.mark.parametrize("tool", ["subagent", "shell"])
    @pytest.mark.parametrize(
        "tools",
        [
            pytest.param(["read", "subagent", "shell"], id="listed"),
            pytest.param(["*"], id="every tool"),
        ],
    )
    def test_it_stays_quiet_when_the_tool_is_listed_and_allowed(
        self, tmp_path: Path, tool: str, tools: list[str]
    ) -> None:
        config = tmp_path / "mine.json"
        rules = [
            {"capability": "subagent", "effect": "allow"},
            {"capability": "shell", "effect": "allow"},
        ]
        _write_agent(config, {"name": "mine", "tools": tools, "permissions": {"rules": rules}})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        assert not any(f"does not grant the `{tool}` tool" in note for note in report.notes)

    def test_a_subagent_rule_matching_only_the_consolidator_names_the_documenter(
        self, tmp_path: Path
    ) -> None:
        """The rule `kiro-cli agent upgrade` derives from a V2 profile that trusted the
        consolidator, as this repository's own converted dogfood profile carries."""
        config = tmp_path / "mine.json"
        rule = {"capability": "subagent", "match": ["zikaron-consolidator"], "effect": "allow"}
        tools = ["read", "subagent"]
        _write_agent(config, {"name": "mine", "tools": tools, "permissions": {"rules": [rule]}})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        (note,) = [note for note in report.notes if "`subagent` rules do not match" in note]
        assert "`zikaron-documenter`" in note
        assert "`zikaron-consolidator`" not in note
        assert not any("does not grant the `subagent` tool" in note for note in report.notes)

    def test_a_subagent_rule_matching_both_agents_by_pattern_is_quiet(self, tmp_path: Path) -> None:
        config = tmp_path / "mine.json"
        rule = {"capability": "subagent", "match": ["zikaron-*"], "effect": "allow"}
        tools = ["read", "subagent"]
        _write_agent(config, {"name": "mine", "tools": tools, "permissions": {"rules": [rule]}})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        clauses = ("does not grant the `subagent` tool", "`subagent` rules do not match")
        assert not any(clause in note for note in report.notes for clause in clauses)


class TestTheDocumenterParentGrantNote:
    """kiro gives a subagent only what its own rules and its parent's both allow, so the
    documenter's file rules are not enough by themselves: a primary profile without a write rule
    left a spawned documenter asking, and headless writing nothing (`research/kiro-v3-probe.md`
    §28). The install names the missing rules and grants neither."""

    _CLAUSE: Final = "allow rule, and kiro gives a subagent"

    def _notes(self, tmp_path: Path, rules: list[dict[str, object]]) -> list[str]:
        config = tmp_path / "mine.json"
        _write_agent(config, {"name": "mine", "tools": ["*"], "permissions": {"rules": rules}})
        report = Report()
        merge_agent_config(config, _plan(tmp_path), report)
        return [note for note in report.notes if self._CLAUSE in note]

    def test_a_profile_with_neither_rule_is_told_both(self, tmp_path: Path) -> None:
        (note,) = self._notes(tmp_path, [])
        assert "no `fs_read` or `fs_write` allow rule" in note
        assert '"match": ["./**"]' in note
        assert f'"match": ["./{DOCUMENTS_DIRECTORY}/**"]' in note

    def test_a_profile_that_reads_is_told_only_the_write_rule(self, tmp_path: Path) -> None:
        """The read rule is the one `kiro-cli agent create` writes."""
        read: dict[str, object] = {"capability": "fs_read", "match": ["./**"], "effect": "allow"}
        (note,) = self._notes(tmp_path, [read])
        assert "no `fs_write` allow rule" in note
        assert "`fs_read`" not in note
        assert "writing each document" in note
        assert "reading each source" not in note

    def test_a_profile_allowing_both_is_quiet(self, tmp_path: Path) -> None:
        rules: list[dict[str, object]] = [
            {"capability": "fs_read", "effect": "allow"},
            {"capability": "fs_write", "match": ["./docs/**"], "effect": "allow"},
        ]
        assert self._notes(tmp_path, rules) == []

    def test_the_write_rule_is_scoped_to_the_planner_default(self) -> None:
        assert DOCUMENTS_DIRECTORY == DEFAULT_DOCUMENTS
