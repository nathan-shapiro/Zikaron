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
from zikaron.core.retrieval.block import PREAMBLE
from zikaron.harness.spec import KIRO
from zikaron.hook.limits import MAX_OUTPUT_SIZE, TIMEOUT_MS
from zikaron.hook.write_policy import WRITE_POLICY_PROMPT
from zikaron.install.assets import (
    CONSOLIDATOR_PROMPT,
    KIRO_SPAWN_INSTRUCTION,
    SKILL_NAME,
    identity_vocabulary,
    skill_markdown,
)
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
from zikaron.mcp.server import build_server

_DISTRIBUTION_HEADING = "### The consolidator's model is a shipped config field, not a `meta` key"
_MODEL_TABLE_COLUMNS = ("Setting", "Location", "Type", "v0 default", "Rule")
_MS_PER_SECOND = 1000

_COMMANDS = Commands(hook=Path("/venv/bin/zikaron-hook"), mcp=Path("/venv/bin/zikaron-mcp"))

#: Kiro's rendering of the skill: the identity tool vocabulary, so every name is spelled exactly as
#: the shipped prose writes it. Every assertion below that was written against the old module-level
#: constant is an assertion about *this* text, and it must stay byte-identical to what M12 shipped —
#: `TestKiroArtefactsAreUnchanged` in `tests/test_install_targets.py` is what holds that.
_KIRO_SKILL = skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION)


def _flat(text: str) -> str:
    """`text` with every run of whitespace collapsed to one space.

    Every prose assertion below goes through this. The shipped texts are hard-wrapped, so a clause
    that spans a line break is invisible to a plain substring test — and rewrapping a paragraph,
    which
    happens whenever one is edited, would otherwise silently disarm the guard that defends it.
    """
    return re.sub(r"\s+", " ", text)


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
        assert _design_model_default() == KIRO.consolidator_model

    def test_the_written_config_states_the_model_explicitly(self) -> None:
        """The no-silent-inheritance rule: an omitted `model` means the consolidator runs whatever
        the user's own session runs, and the one variable being held fixed stops being ours.
        """
        config = consolidator_agent_config(_COMMANDS, model=KIRO.consolidator_model)
        assert config["model"] == KIRO.consolidator_model


class TestTheConsolidatorConfigMatchesTheToolSurfaceInCode:
    def test_the_allowlist_covers_the_whole_server_so_every_tool_is_pre_approved(self) -> None:
        """A subagent has nobody to answer a permission prompt, so an available-but-not-allowed tool
        is one that fails at the moment it is needed."""
        config = consolidator_agent_config(_COMMANDS, model=KIRO.consolidator_model)
        assert config["tools"] == [f"@{MCP_SERVER_NAME}"]
        assert config["allowedTools"] == [f"@{MCP_SERVER_NAME}"]

    def test_it_grants_no_filesystem_or_shell_tool(self) -> None:
        config = consolidator_agent_config(_COMMANDS, model=KIRO.consolidator_model)
        tools = config["tools"]
        allowed = config["allowedTools"]
        assert isinstance(tools, list)
        assert isinstance(allowed, list)
        granted = {*tools, *allowed}
        assert granted.isdisjoint({"read", "write", "shell", "grep", "glob", "code", "@builtin"})

    def test_it_declares_no_hooks(self) -> None:
        """Its session must not fire the push hook — it has no `search` to spend a result on — and
        must not print the write policy, which is already in its own system prompt."""
        assert "hooks" not in consolidator_agent_config(_COMMANDS, model=KIRO.consolidator_model)

    def test_it_runs_the_mcp_server_in_consolidator_mode(self) -> None:
        config = consolidator_agent_config(_COMMANDS, model=KIRO.consolidator_model)
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
        assert "zikaron_search" not in _flat(CONSOLIDATOR_PROMPT)
        assert "zikaron_fetch" not in _flat(CONSOLIDATOR_PROMPT)


class TestTheSharedRulesAreInBothTexts:
    """Both texts must carry them, because the consolidator never sees the injected write policy.

    Asserted as a property of each text rather than as one being a copy of the other: the audiences
    differ, so the wording should too, and a copy test would force them to converge or be deleted.

    **Each assertion names the operative clause, not a worked example's token.** Earlier versions
    checked that `--force` and `PGHOST` appeared — tokens that survive the deletion or inversion of
    the very instruction they illustrate, so the test would have stayed green while the rule went
    away.
    """

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_prohibits_recording_secrets(self, text: str) -> None:
        assert "Never record a secret" in _flat(text)
        assert "plaintext on disk" in _flat(text), "the reason travels with the rule"

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_asks_for_observations_rather_than_orders(self, text: str) -> None:
        assert "less context than" in _flat(text), "the rule's reason must travel with it"
        assert "--force" in _flat(text), "and the worked example that makes it concrete"

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_states_what_a_gist_is_for(self, text: str) -> None:
        assert "whether to read further" in _flat(text)
        assert "Lead with the observable symptom" in _flat(text)

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_bounds_a_gist_with_a_number_an_agent_can_act_on(self, text: str) -> None:
        """ "Keep it short" left an agent to discover the bound by losing a call, and one did."""
        assert "20 to 25 words" in _flat(text)
        assert "64 tokens" in _flat(text)

    @pytest.mark.parametrize("text", [WRITE_POLICY_PROMPT, CONSOLIDATOR_PROMPT])
    def test_it_requires_an_expiring_claim_to_carry_its_condition_in_the_gist(
        self, text: str
    ) -> None:
        """The fourth shared rule, and the one the consolidator was missing: it rewrites gists
        during
        a merge, so it can strip a condition the write policy required — recreating the measured
        failure where an expired prohibition was recalled as a permanent one.
        """
        flat = _flat(text)
        assert "permanent rule" in flat
        assert "until a fix lands" in flat, "both illustrate the condition concretely"
        assert "gist" in flat


class TestTheRulesEachTextCarriesAlone:
    def test_only_the_policy_tells_the_primary_agent_when_to_search(self) -> None:
        """The consolidator has no search tool, so a recall rule there would name a capability it
        does not have."""
        assert "Look things up before you spend time" in _flat(WRITE_POLICY_PROMPT)
        assert "Look things up" not in _flat(CONSOLIDATOR_PROMPT)

    @pytest.mark.parametrize(
        "occasion",
        [
            "Something surprised you",
            "You are about to propose",
            "You are about to say an approach will not work",
            "You are about to rename, move or delete",
        ],
    )
    def test_the_policy_names_recall_occasions_the_agent_can_detect(self, occasion: str) -> None:
        """Each trigger has to be an event, not a self-assessment.

        The rule this replaced said to search "whenever you are about to spend real effort", which
        requires noticing that effort is coming — a judgement the agent using this store reported
        making badly mid-task, because effort feels like progress. These four are things it can
        observe itself doing.
        """
        assert occasion in _flat(WRITE_POLICY_PROMPT)

    def test_the_policy_disarms_the_effort_judgement_rather_than_only_replacing_it(self) -> None:
        """Naming events is not enough alone: the old category reads as permission to defer until
        the effort feels big, so the reason it fails is stated beside the events."""
        assert "effort feels like progress" in _flat(WRITE_POLICY_PROMPT)

    def test_the_policy_requires_a_proposal_to_state_what_recall_returned(self) -> None:
        """A claim that has to carry its own search cannot be satisfied by not searching, and
        "found nothing relevant" is spelled out so silence is not a way to comply."""
        flat = _flat(WRITE_POLICY_PROMPT)
        assert "say what you searched for and what came back" in flat
        assert "found nothing relevant" in flat

    def test_both_the_policy_and_the_block_say_the_selection_stops_covering_the_task(self) -> None:
        """The sufficiency illusion is created by the block, once per message, so the block is where
        it has to be answered — the policy is read once per session and then competes with every
        push after it. Asserted of both, since either alone leaves a gap.
        """
        assert "not for the problem as you understand" in _flat(WRITE_POLICY_PROMPT)
        assert "Once you reframe the problem the selection no longer follows" in _flat(PREAMBLE)
        assert "no new one arrives" in _flat(PREAMBLE)

    def test_only_a_record_whose_claim_is_untrue_is_ever_called_stale(self) -> None:
        """Two different unreliabilities, and one word was doing both jobs.

        The policy's repair rule uses "stale" for a memory whose claim is no longer true, which the
        agent is asked to amend. The first draft of the recall rule then called the *injected gists*
        stale once the problem was reframed — but reframing does not make a record untrue, it makes
        the selection incomplete, and telling an agent otherwise invites an amend on prose that was
        correct. The word is reserved for the repair sense, and the recall text puts the
        unreliability on the choice of which records were shown.
        """
        assert "stale" not in PREAMBLE
        assert WRITE_POLICY_PROMPT.count("stale") == 1, "only the repair rule may use the word"

    def test_the_policy_says_a_memory_is_evidence_rather_than_a_ruling(self) -> None:
        """Without this, telling an agent to consult memory while planning makes a stale claim more
        consequential rather than less."""
        flat = _flat(WRITE_POLICY_PROMPT)
        assert "not a ruling about what must happen now" in flat
        assert "what to re-check, not which option to drop" in flat

    def test_only_the_consolidator_is_told_to_write_one_verb_at_a_time(self) -> None:
        flat = _flat(CONSOLIDATOR_PROMPT)
        assert "one at a time" in flat
        assert "not guaranteed to run in the order" in flat
        assert "one at a time" not in _flat(WRITE_POLICY_PROMPT)

    def test_the_consolidator_prefers_splitting_over_a_table_of_contents(self) -> None:
        flat = _flat(CONSOLIDATOR_PROMPT)
        assert "probably not one finding" in flat
        assert "table of contents" in flat

    def test_the_split_rule_accepts_a_situation_and_not_only_a_symptom(self) -> None:
        """A build procedure or a settled convention has a sharp situation and no symptom; the
        narrower wording would have biased the store toward failure records only."""
        assert "one observable symptom or situation" in _flat(CONSOLIDATOR_PROMPT)


class TestTheSkillFile:
    def test_the_frontmatter_name_matches_the_directory_it_installs_into(self) -> None:
        """kiro derives one from the other, so a mismatch is a skill that never loads."""
        assert f"\nname: {SKILL_NAME}\n" in _KIRO_SKILL

    def test_the_description_is_one_physical_line(self) -> None:
        """A single-line plain scalar needs no assumption about which YAML features the harness's
        frontmatter parser supports — the reason it is assembled from fragments in code.
        """
        lines = _KIRO_SKILL.split("\n")
        described = [line for line in lines if line.startswith("description:")]
        assert len(described) == 1
        assert lines[lines.index(described[0]) + 1] == "---"

    def test_the_frontmatter_is_closed_before_the_body(self) -> None:
        assert _KIRO_SKILL.startswith("---\n")
        assert _KIRO_SKILL.split("---\n")[2].lstrip().startswith("#")

    def test_it_names_the_agent_the_skill_spawns(self) -> None:
        assert CONSOLIDATOR_AGENT_NAME in _KIRO_SKILL

    def test_it_tells_the_reader_that_reinvoking_recovers_a_stuck_run(self) -> None:
        """The takeover is the one user-facing recovery path in the whole system, and this file is
        the only place a user encounters it."""
        assert "takes the run over" in _KIRO_SKILL


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
        generated = consolidator_agent_config(_COMMANDS, model=KIRO.consolidator_model)
        assert document["mcpServers"][MCP_SERVER_NAME]["args"] == ["--mode", "consolidator"]
        for key in ("name", "description", "model", "prompt", "tools", "allowedTools"):
            assert document[key] == generated[key], f"tracked config has drifted on {key}"

    def test_the_tracked_skill_matches_the_shipped_text(self) -> None:
        skill = Path(__file__).resolve().parent.parent / ".kiro/skills/zikaron-consolidate/SKILL.md"
        if not skill.is_file():
            pytest.skip("this checkout has no tracked skill")
        assert skill.read_text(encoding="utf-8") == _KIRO_SKILL

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
        config = consolidator_agent_config(_COMMANDS, model=KIRO.consolidator_model)
        assert json.loads(json.dumps(config)) == config
