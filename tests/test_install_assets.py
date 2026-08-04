"""The shipped artefacts, checked against the design and against the code they must agree with.

Every test here exists because the artefact it guards is *prose or JSON that nothing else executes*:
a wrong model id, a tool name that does not exist, or a missing prohibition would all install
cleanly, validate cleanly, and only be discovered by a consolidation run behaving oddly.
"""

import json
import re
import shlex
from pathlib import Path

import pytest
from fastmcp import Client

from tests.design_tables import literal, table_with_columns
from zikaron.hook.limits import MAX_OUTPUT_SIZE, TIMEOUT_MS
from zikaron.hook.write_policy import WRITE_POLICY_PROMPT
from zikaron.install.assets import CONSOLIDATOR_PROMPT, SKILL_MARKDOWN, SKILL_NAME
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    MCP_SERVER_NAME,
    TOOL_SELECTOR,
    Commands,
    HookFormat,
    consolidator_agent_config,
    hooks_array,
    hooks_object,
    mcp_servers_value,
)
from zikaron.install.main import DEFAULT_MODEL
from zikaron.mcp.server import build_server

_DISTRIBUTION_HEADING = "### The consolidator's model is a shipped config field, not a `meta` key"
_MODEL_TABLE_COLUMNS = ("Setting", "Location", "Type", "v0 default", "Rule")
_MS_PER_SECOND = 1000

_COMMANDS = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))


def _design_model_default() -> str:
    table = table_with_columns("architecture.md", _DISTRIBUTION_HEADING, _MODEL_TABLE_COLUMNS)
    rows = [row for row in table if "consolidator model" in row["Setting"]]
    assert len(rows) == 1
    return literal(rows[0]["v0 default"])


class TestTheModelDefaultComesFromTheDesign:
    def test_the_shipped_default_is_the_one_the_design_states(self) -> None:
        """Read out of `architecture.md` at test time rather than compared against a second copy
        typed here, so revising the design's own table is what fails this — not only editing code.
        """
        assert _design_model_default() == DEFAULT_MODEL

    def test_the_written_config_states_the_model_explicitly(self) -> None:
        """The no-silent-inheritance rule: an omitted `model` means the consolidator runs whatever
        the user's own session runs, and the one variable being held fixed stops being ours.
        """
        config = consolidator_agent_config(_COMMANDS, model=DEFAULT_MODEL)
        assert config["model"] == DEFAULT_MODEL


class TestTheConsolidatorConfigMatchesTheToolSurfaceInCode:
    def test_the_allowlist_covers_the_whole_server_so_every_tool_is_pre_approved(self) -> None:
        """A subagent has nobody to answer a permission prompt, so an available-but-not-allowed tool
        is one that fails at the moment it is needed."""
        config = consolidator_agent_config(_COMMANDS, model=DEFAULT_MODEL)
        assert config["tools"] == [f"@{MCP_SERVER_NAME}"]
        assert config["allowedTools"] == [f"@{MCP_SERVER_NAME}"]

    def test_it_grants_no_filesystem_or_shell_tool(self) -> None:
        config = consolidator_agent_config(_COMMANDS, model=DEFAULT_MODEL)
        tools = config["tools"]
        allowed = config["allowedTools"]
        assert isinstance(tools, list)
        assert isinstance(allowed, list)
        granted = {*tools, *allowed}
        assert granted.isdisjoint({"read", "write", "shell", "grep", "glob", "code", "@builtin"})

    def test_it_declares_no_hooks(self) -> None:
        """Its session must not fire the push hook — it has no `search` to spend a result on — and
        must not print the write policy, which is already in its own system prompt."""
        assert "hooks" not in consolidator_agent_config(_COMMANDS, model=DEFAULT_MODEL)

    def test_it_runs_the_mcp_server_in_consolidator_mode(self) -> None:
        config = consolidator_agent_config(_COMMANDS, model=DEFAULT_MODEL)
        servers = config["mcpServers"]
        assert isinstance(servers, dict)
        assert servers[MCP_SERVER_NAME] == {
            "command": str(_COMMANDS.mcp),
            "args": ["--mode", "consolidator"],
        }

    async def test_every_tool_the_prompt_instructs_is_one_the_server_registers(
        self, tmp_path: Path
    ) -> None:
        """The prompt names its tools in prose, and prose cannot be type-checked. Asserted against
        the tools a real consolidator server actually registers — not against a list typed here —
        so a rename in code fails this instead of surfacing as a tool call with no handler, mid-run,
        with a lease held.

        Set equality in both directions on purpose: a tool named in the prompt that does not exist
        is a broken instruction, and a tool that exists but is never mentioned is a capability the
        model has no reason to know it has.
        """
        mcp = build_server("consolidator", cwd=tmp_path)
        async with Client(mcp) as client:
            registered = {tool.name for tool in await client.list_tools()}
        assert set(re.findall(r"zikaron_[a-z_]+", CONSOLIDATOR_PROMPT)) == registered

    def test_the_prompt_never_names_a_tool_the_consolidator_cannot_reach(self) -> None:
        """`search` and `fetch` are not registered on a consolidator process at all, so naming
        either would instruct a call whose absence is structural."""
        assert "zikaron_search" not in CONSOLIDATOR_PROMPT
        assert "zikaron_fetch" not in CONSOLIDATOR_PROMPT


class TestTheThreeSharedProhibitions:
    """Both texts must carry them, because the consolidator never sees the injected write policy.

    Asserted as a property of each text rather than as one being a copy of the other: the audiences
    differ, so the wording should too, and a copy test would force them to converge or be deleted.
    """

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_prohibits_recording_secrets(self, text: str) -> None:
        assert "Never record a secret" in text

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_asks_for_observations_rather_than_orders(self, text: str) -> None:
        assert "--force" in text, "both texts use the same worked example of an order"

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_states_what_a_gist_is_for(self, text: str) -> None:
        assert "PGHOST" in text, "both texts use the same worked example of a cue-shaped gist"


class TestTheSkillFile:
    def test_the_frontmatter_name_matches_the_directory_it_installs_into(self) -> None:
        """kiro derives one from the other, so a mismatch is a skill that never loads."""
        assert f"\nname: {SKILL_NAME}\n" in SKILL_MARKDOWN

    def test_the_description_is_one_physical_line(self) -> None:
        """A single-line plain scalar needs no assumption about which YAML features the harness's
        frontmatter parser supports — the reason it is assembled from fragments in code.
        """
        lines = SKILL_MARKDOWN.split("\n")
        described = [line for line in lines if line.startswith("description:")]
        assert len(described) == 1
        assert lines[lines.index(described[0]) + 1] == "---"

    def test_the_frontmatter_is_closed_before_the_body(self) -> None:
        assert SKILL_MARKDOWN.startswith("---\n")
        assert SKILL_MARKDOWN.split("---\n")[2].lstrip().startswith("#")

    def test_it_names_the_agent_the_skill_spawns(self) -> None:
        assert CONSOLIDATOR_AGENT_NAME in SKILL_MARKDOWN

    def test_it_tells_the_reader_that_reinvoking_recovers_a_stuck_run(self) -> None:
        """The takeover is the one user-facing recovery path in the whole system, and this file is
        the only place a user encounters it."""
        assert "takes the run over" in SKILL_MARKDOWN


class TestTheShippedEntriesStateBothLimits:
    def test_object_format_entries_state_the_timeout_and_the_output_cap(self) -> None:
        for entries in hooks_object(_COMMANDS).values():
            assert len(entries) == 1
            assert entries[0]["timeout_ms"] == TIMEOUT_MS
            assert entries[0]["max_output_size"] == MAX_OUTPUT_SIZE

    def test_array_format_entries_state_the_timeout_in_seconds(self) -> None:
        """The one place the two formats disagree about a *value* rather than a shape: seconds here,
        milliseconds there. Writing the millisecond number into this field would install a timeout
        of 10000 seconds, which no test of shape alone would notice.
        """
        for entry in hooks_array(_COMMANDS):
            assert entry["timeout"] == TIMEOUT_MS // _MS_PER_SECOND
            assert "timeout_ms" not in entry
            assert "max_output_size" not in entry

    def test_both_formats_register_exactly_the_two_triggers(self) -> None:
        assert set(hooks_object(_COMMANDS)) == {"agentSpawn", "userPromptSubmit"}
        assert {entry["trigger"] for entry in hooks_array(_COMMANDS)} == {
            "agentSpawn",
            "userPromptSubmit",
        }

    def test_the_command_is_shell_quoted_because_the_harness_runs_it_through_a_shell(self) -> None:
        """Measured: an unquoted path with a space produced `/bin/bash: line 1: ... No such file or
        directory` and exit 127 from the real harness, with the hook contributing nothing while the
        install had exited 0. A spaced path is an ordinary project, not an exotic one.
        """
        spaced = Commands(
            hook=Path("/home/me/My Projects/.venv/bin/zikaron-hook"),
            mcp=Path("/home/me/My Projects/.venv/bin/zikaron-mcp"),
        )
        entry = hooks_object(spaced)["agentSpawn"][0]
        assert entry["command"] == "'/home/me/My Projects/.venv/bin/zikaron-hook'"
        assert shlex.split(str(entry["command"])) == [str(spaced.hook)]

    def test_the_mcp_command_is_not_quoted_because_that_field_is_not_shell_source(self) -> None:
        """`mcpServers` takes a program plus a separate `args` array — exec-style. Quoting it would
        make the harness look for a file whose name contains the quotes."""
        spaced = Commands(
            hook=Path("/home/me/My Projects/.venv/bin/zikaron-hook"),
            mcp=Path("/home/me/My Projects/.venv/bin/zikaron-mcp"),
        )
        entry = mcp_servers_value(spaced, mode="primary")[MCP_SERVER_NAME]
        assert isinstance(entry, dict)
        assert entry["command"] == "/home/me/My Projects/.venv/bin/zikaron-mcp"

    def test_both_formats_run_the_same_absolute_command(self) -> None:
        from_object = {
            entry["command"] for entries in hooks_object(_COMMANDS).values() for entry in entries
        }
        from_array = set()
        for entry in hooks_array(_COMMANDS):
            action = entry["action"]
            assert isinstance(action, dict)
            from_array.add(action["command"])
        assert from_object == from_array == {shlex.quote(str(_COMMANDS.hook))}

    def test_the_primary_mcp_entry_names_primary_mode(self) -> None:
        entry = mcp_servers_value(_COMMANDS, mode="primary")[MCP_SERVER_NAME]
        assert entry == {"command": str(_COMMANDS.mcp), "args": ["--mode", "primary"]}

    def test_the_hook_format_enum_covers_exactly_the_two_documented_formats(self) -> None:
        assert {member.value for member in HookFormat} == {"object", "array"}


class TestTheTrackedArtefactsInThisRepository:
    """This repository tracks its own installed copies, for dogfooding. They can therefore drift.

    Compared **modulo the absolute command paths**, which are machine-specific by construction: a
    clone carries whichever venv the last committer had, so an equality test on the whole file would
    fail on every machine but one. Everything else — the model, the prompt, the tool surface, the
    skill's whole text — is generated content and must match.
    """

    @staticmethod
    def _tracked(name: str) -> Path:
        return Path(__file__).resolve().parent.parent / ".kiro" / "agents" / name

    def test_the_tracked_consolidator_config_matches_what_the_installer_generates(self) -> None:
        tracked = self._tracked("zikaron-consolidator.json")
        if not tracked.is_file():
            pytest.skip("this checkout has no tracked consolidator config")
        document = json.loads(tracked.read_text())
        generated = consolidator_agent_config(_COMMANDS, model=DEFAULT_MODEL)
        assert document["mcpServers"][MCP_SERVER_NAME]["args"] == ["--mode", "consolidator"]
        for key in ("name", "description", "model", "prompt", "tools", "allowedTools"):
            assert document[key] == generated[key], f"tracked config has drifted on {key}"

    def test_the_tracked_skill_matches_the_shipped_text(self) -> None:
        skill = Path(__file__).resolve().parent.parent / ".kiro/skills/zikaron-consolidate/SKILL.md"
        if not skill.is_file():
            pytest.skip("this checkout has no tracked skill")
        assert skill.read_text(encoding="utf-8") == SKILL_MARKDOWN

    def test_the_tracked_dogfood_config_selects_the_memory_tools(self) -> None:
        """The measured failure this repository would hit first: an agent whose `tools` omits the
        server reports no memory tools at all."""
        tracked = self._tracked("zikaron-dogfood.json")
        if not tracked.is_file():
            pytest.skip("this checkout has no dogfood config")
        document = json.loads(tracked.read_text())
        assert TOOL_SELECTOR in document["tools"]
        assert "subagent" in document["tools"]
        assert MCP_SERVER_NAME in document["mcpServers"]
        assert set(document["hooks"]) == {"agentSpawn", "userPromptSubmit"}


class TestTheWholeConfigIsSerializable:
    def test_the_consolidator_config_round_trips_through_json(self) -> None:
        """It is written with `json.dumps`, so a value that cannot serialize would fail at install
        time — which is where this catches it instead."""
        config = consolidator_agent_config(_COMMANDS, model=DEFAULT_MODEL)
        assert json.loads(json.dumps(config)) == config
