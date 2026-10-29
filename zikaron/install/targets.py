"""The one place a harness difference is allowed to take a different **shape** rather than a
different value.

`design/harness.md` §"The installer's two targets" is normative. Everywhere else in Zikaron — both
thin clients — a harness difference is data in `zikaron.harness.spec`, because forking doubles every
future change to the two components the design keeps deliberately thin. The installer cannot be
written that way, and the reason is structural rather than a concession: kiro's artefacts are
**one** file whose path the *user* supplies, and Claude Code's are files at paths the *project*
fixes. That is not two values of one parameter.

**The split this module has to keep honest.** A *value* that differs (a session variable, a trigger
name, an injection budget, the consolidator's model default) is a `HarnessSpec` field with a row in
`harness.md` §"The table" and a drift-guard test. A *shape* that differs (which files exist, how
each is merged) is a method here. A value that migrates into a method is the seam failing, and the
symptom is a literal in this file that also appears in `spec.py`.

What does **not** vary lives in `main.py` and `writer.py` and is called by both implementations:
preflight order, the check-everything-then-write-everything split, collision policy, backup
discipline, atomic replacement.
"""

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from zikaron.harness.spec import CLAUDE_CODE, KIRO, Harness, HarnessSpec
from zikaron.hook.components import Components
from zikaron.install import agent_scan, settings_hooks
from zikaron.install import harness as harness_cli
from zikaron.install.assets import (
    CLAUDE_CODE_SPAWN_INSTRUCTION,
    KIRO_SPAWN_INSTRUCTION,
    SKILL_NAME,
    identity_vocabulary,
    skill_markdown,
)
from zikaron.install.code_knowledge import (
    DOCUMENT_SKILL_NAME,
    DOCUMENTER_AGENT_NAME,
    KIRO_ARGUMENTS_SOURCE,
    KIRO_PLANNER_COMMAND,
    ORCHESTRATOR_AGENT_NAME,
    document_code_skill,
    launch_skill,
)
from zikaron.install.code_knowledge import (
    KIRO_SPAWN_INSTRUCTION as KIRO_DOCUMENTER_SPAWN,
)
from zikaron.install.entries import (
    CONSOLIDATOR_AGENT_NAME,
    MCP_SERVER_NAME,
    TOOL_SELECTOR,
    claude_hooks_value,
    claude_mcp_servers_value,
    claude_tool_vocabulary,
    consolidator_agent_config,
    consolidator_agent_markdown,
    documenter_agent_config,
    documenter_agent_markdown,
    hooks_array,
    mcp_servers_value,
    orchestrator_agent_markdown,
    primary_rules,
)
from zikaron.install.harness import InstallError
from zikaron.install.kiro_merge import plan_kiro_merge
from zikaron.install.ownership import merged_server, refuse_conflicting
from zikaron.install.writer import (
    MergePlan,
    Plan,
    ShippedFile,
    Targets,
    guard_backup_path,
)

_JSON_INDENT = 2

#: What may be written into `model:` in YAML frontmatter.
#:
#: **The first character must be alphanumeric, and that is the load-bearing half.** In YAML a `[`
#: only opens a flow sequence at the *start* of a scalar, so `sonnet[1m]` is a plain string while
#: `[1m]` is a one-element list — the same class of silent meaning-change as an embedded colon, and
#: the reason the anchor is not simply `[A-Za-z0-9._\[\]-]+`.
#:
#: **Brackets are permitted because they were measured, not assumed.** An earlier revision refused
#: them and its comment claimed "every id and alias either harness serves satisfies it" — an
#: unmeasured universal. Probing it refuted it: a subagent whose frontmatter said
#: `model: sonnet[1m]` **spawned normally** (`research/claude-code-installer-probe.md` §11), so the
#: long-context alias form is a legitimate value the installer was rejecting.
_MODEL_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\[\]-]*")

#: The settings key that pre-approves project-scoped MCP servers. Written under the same
#: `--no-trust-tools` flag that governs kiro's permission rules, because it answers the same
#: question: does this install trust its own tools, or make the user approve them one at a time.
_ENABLED_SERVERS_KEY: Final = "enabledMcpjsonServers"

#: Claude Code's permission key. **Distinct from `_ENABLED_SERVERS_KEY`, and the two are easy to
#: conflate**: that key governs whether a project-scoped server *loads*, while this one governs
#: whether each tool *call* is approved. Writing only the first leaves every
#: `zikaron_memory_remember` behind an approval prompt — the per-write friction `writer._selecting`
#: calls worse than not asking at all, installed silently and with nothing saying so.
_PERMISSIONS_KEY: Final = "permissions"
_ALLOW_KEY: Final = "allow"

#: Said whenever a Claude Code install completes, because the failure it warns about is silent and
#: total: a project-scoped server that has not been approved simply does not load, and the agent
#: then has no Zikaron tools with nothing anywhere saying why.
_APPROVAL_NOTE: Final = (
    "Claude Code asks for approval twice over, and a default install answers both: "
    f"`{_ENABLED_SERVERS_KEY}` for whether a project-scoped `.mcp.json` server **loads** at all, "
    "and "
    f"`{_PERMISSIONS_KEY}.{_ALLOW_KEY}` for whether each tool **call** goes through without a "
    "prompt. Both were measured to work in an interactive session — no load prompt, and no "
    "per-call prompt across six writes and eight reads — but nothing in the shipped software can "
    "check either one, because a headless run approves everything "
    "(`research/claude-code-installer-probe.md` §8). So if Zikaron's tools are "
    "absent, check `/mcp` for a server pending approval before looking anywhere else — and if they "
    "are present but every write interrupts you, it is the second key that did not take."
)

#: Said for the same reason as `_APPROVAL_NOTE`, about a gate that install-time config deliberately
#: does **not** answer. Measured in an operator-driven session: the consolidator's first `Read` of a
#: spilled payload raises a prompt, and the harness offers to allow that directory for the session.
#:
#: A `permissions.allow` entry for the runtime directory was considered and **rejected**. `Read` is
#: grantable but not scopable in subagent frontmatter, so this prompt is the one place D32's
#: widening becomes a check an operator answers rather than prose; the harness's own session-scoped
#: option is narrower than anything an installed settings entry could express; D10 makes
#: consolidation operator-invoked, so there is no unattended run for it to stall; and on a mature
#: store spilling is the *majority* path, so a permanent entry would have the widened grant
#: exercised silently on essentially every consolidation forever. What the note buys is that the
#: prompt arrives expected rather than mid-run and unexplained.
_SPILL_READ_NOTE: Final = (
    "A group too large for this harness to deliver is written to a file and the consolidator is "
    "given its path, so the first time a consolidation meets such a group — routine on a mature "
    "store, possibly never on a small one — Claude Code will ask whether it may read from the "
    "runtime directory (`$XDG_RUNTIME_DIR/zikaron`, or `/tmp/zikaron-<uid>` where that variable "
    "is unset). That prompt is expected, **recurs in each new session** because the grant it "
    "offers is session-scoped, and is deliberately not answered by this install: choose the "
    "option allowing that directory for the session. A file-reading tool cannot be restricted to "
    "one path in subagent config, so this prompt is the only point at which that grant is put to "
    "you as a question."
)

#: The exposure D32 cannot mechanically prevent here, reported rather than passed over in silence.
_EXPOSURE_NOTE: Final = (
    "Your primary agent can see the four consolidation verbs "
    f"(`mcp__{CONSOLIDATOR_AGENT_NAME}__*`) as well as its own tools. That is not a "
    "misconfiguration and it cannot be fixed here: a server must be registered session-wide to be "
    "reachable by any subagent at all, and `permissions.deny` is global — denying a verb "
    "unregisters it and the consolidator subagent is then refused at spawn with zero tools. Under "
    "kiro the two tool sets are mechanically separate; here that half of the design is "
    "prompt-only, and an unauthorized consolidation costs tokens and possibly a poorly-judged "
    "long-term record."
)


def _blind_agents_note(blind: Sequence[str]) -> str:
    """The line naming each subagent whose own `tools:` list cannot reach Zikaron.

    Conditioned on there being any, like the grant notes above: an unconditional line would say
    nothing on almost every install and train its reader to skip the one that matters.

    The form it advises is the one `research/claude-code-installer-probe.md` §7 measured — a
    whole-server wildcard in subagent frontmatter grants that server's tools and excludes others,
    in the block form this installer already ships for its own agent. The residual is only that it
    was measured for `zikaron-consolidator` rather than `zikaron`: the same mechanism, a different
    server name. `mcp__zikaron-consolidator` is never suggested — that grant belongs to the
    consolidator alone.
    """
    listed = ", ".join(blind)
    return (
        f"These subagents set their own `tools:` list, which **overrides** the project-wide "
        f"`.mcp.json` registration this install just wrote, so Zikaron's verbs are absent from "
        f"them: {listed}. Nothing here changes them — your allowlist is a deliberate grant. To "
        f"give one of them the memory tools, add `{agent_scan.GRANT}` to its `tools:`, which is "
        f"the same whole-server form Zikaron's own consolidator agent uses."
    )


class HarnessTarget(ABC):
    """How one harness's artefacts are serialized and merged.

    Deliberately narrow. Every method answers "what does *this* harness need on disk"; none of them
    decides *whether* to write, in what order, or what to do on a collision — those are one
    implementation in `main.py` and `writer.py` and stay that way.
    """

    #: The harness this target installs for, and the spec its values come from.
    spec: HarnessSpec

    @property
    def name(self) -> str:
        """The `--harness` value that selects this target."""
        return str(self.spec.harness.value)

    @property
    @abstractmethod
    def accepts_agent_flag(self) -> bool:
        """Whether `--agent` means anything here.

        Kiro merges into a config the user names; Claude Code's merge targets are fixed project
        paths. Passing `--agent` to a target that has no use for it is **refused** rather than
        ignored, because ignoring it would silently discard the one instruction the user gave about
        where their configuration lives.
        """

    @property
    @abstractmethod
    def ships_orchestrator(self) -> bool:
        """Whether a memory install writes the code orchestrator the documentation skill has the
        session spawn.

        Where it does not, the session that invokes the skill runs its loop itself, so
        `--orchestrator-model` is refused there rather than ignored, and no orchestrator's model is
        checked.
        """

    @abstractmethod
    def shipped_files(self, plan: Plan) -> tuple[ShippedFile, ...]:
        """The artefacts this install owns outright, path and exact content."""

    @abstractmethod
    def plan_merges(self, plan: Plan, agent: Path | None) -> tuple[MergePlan, ...]:
        """Every merge this install would perform, checked and not yet written.

        Raises:
            InstallError: any refusal. Nothing has been written when one is raised — that ordering
                is the contract's, and it is why this returns a value instead of writing.
        """

    @abstractmethod
    def fragment(self, plan: Plan) -> str:
        """What `--print-only` shows instead of merging: the entries, and the caveats."""

    def refuse_absent_harness(self) -> None:
        """Refuse when the harness that would *read* these artefacts is not on this machine.

        **One rule for both harnesses, parameterized by a seam value** — `harness_binary` — rather
        than two implementations, because the argument does not vary: an install writes files whose
        only reader is that binary, and writing them where it does not exist produces exit 0, no
        Zikaron tools, and nothing anywhere saying why. That is the same working-looking-inert
        outcome `_resolve_harness` refuses to *guess* its way into, and refusing one while
        permitting the other was an inconsistency rather than a design.

        It was also, before this existed, an accident of implementation: kiro refused an absent
        binary only as a **side effect** of its model check, so the message talked about model
        validation rather than about the harness being missing, and Claude Code — which needs no
        model check — did not refuse at all.

        **Presence, not health.** A binary that is installed but unauthenticated still means the
        harness is here and will read these files; whether the user can currently talk to it is a
        different problem with a different remedy.

        Raises:
            InstallError: the harness binary is not on `PATH`.
        """
        if harness_cli.binary_is_available(self.spec.harness_binary):
            return
        raise InstallError(
            f"{self.spec.harness_binary} is not on PATH, so nothing on this machine would read "
            f"what a --harness {self.name} install writes. The hook and MCP entries name that "
            "binary's own mechanisms, and installing them where it is absent exits 0 and leaves no "
            "Zikaron tools at all. Install the harness first, or use --print-only to see exactly "
            "what would be written."
        )

    @abstractmethod
    def refuse_unknown_model(self, model: str) -> None:
        """Refuse a model id this harness would not serve as asked.

        Raises:
            InstallError: the id is not one this harness accepts.
        """

    @abstractmethod
    def refuse_unsupported_version(self) -> None:
        """Refuse a release of this harness older than the one Zikaron supports.

        Raises:
            InstallError: the harness is older than its floor, or names no version this can read.
        """

    def notes(self, plan: Plan) -> list[str]:
        """Anything true of this harness that the user should be told after a successful install."""
        del plan
        return []

    def complaints_about(self, paths: list[Path]) -> list[str]:
        """Whatever the harness itself dislikes about the files we just wrote.

        A **report**, never a refusal — the install has already happened by the time this is called,
        and telling the user what the harness objects to is more useful than an exception that
        leaves them guessing which file it meant. Empty by default: only kiro ships a config
        validator to ask.
        """
        del paths
        return []


class KiroTarget(HarnessTarget):
    """kiro-cli on its V3 agent engine: shipped files under `.kiro/`, and one merge into a
    user-named agent profile (`kiro_merge.py`)."""

    spec = KIRO

    @property
    def accepts_agent_flag(self) -> bool:
        return True

    @property
    def ships_orchestrator(self) -> bool:
        return False

    def shipped_files(self, plan: Plan) -> tuple[ShippedFile, ...]:
        targets = Targets(project=plan.project)
        config = consolidator_agent_config(plan.commands, model=plan.consolidator_model)
        return (
            ShippedFile(
                targets.consolidator_config, json.dumps(config, indent=_JSON_INDENT) + "\n"
            ),
            ShippedFile(
                targets.skill_file,
                skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION),
            ),
            ShippedFile(
                targets.documenter_config,
                json.dumps(
                    documenter_agent_config(plan.commands, model=plan.documenter_model),
                    indent=_JSON_INDENT,
                )
                + "\n",
            ),
            ShippedFile(
                targets.document_skill_file,
                document_code_skill(
                    identity_vocabulary(),
                    spawn_instruction=KIRO_DOCUMENTER_SPAWN,
                    planner_command=KIRO_PLANNER_COMMAND,
                    arguments_source=KIRO_ARGUMENTS_SOURCE,
                ),
            ),
        )

    def plan_merges(self, plan: Plan, agent: Path | None) -> tuple[MergePlan, ...]:
        if agent is None:
            return ()
        return (plan_kiro_merge(agent, plan, Targets(project=plan.project)),)

    def fragment(self, plan: Plan) -> str:
        entries: dict[str, object] = {
            "hooks": hooks_array(plan.commands),
            "mcpServers": mcp_servers_value(plan.commands, mode="primary"),
        }
        if plan.trust_tools:
            entries["permissions"] = {"rules": primary_rules()}
        caveats = [
            f"`{TOOL_SELECTOR}` must be in that agent's `tools`, unless `tools` holds `*`, or "
            "Zikaron's tools are simply absent — `mcpServers` configures the server and `tools` "
            "selects from it.",
            "Add the `permissions.rules` entries to the agent's own rules, or every Zikaron tool "
            "call asks for approval and neither skill loads headless."
            if plan.trust_tools
            else "--no-trust-tools leaves out the two rules a default install writes, so every "
            "Zikaron tool call asks for approval and neither skill loads headless.",
            "The agent also needs `subagent` in its `tools` and a "
            '`{"capability": "subagent", "effect": "allow"}` rule for the '
            f"{SKILL_NAME} and {DOCUMENT_SKILL_NAME} skills to spawn their agents, and `shell` "
            f"with its rule for {DOCUMENT_SKILL_NAME} to run its planner.",
        ]
        return (
            "Add these to the agent config you actually use (or re-run with --agent <path> to have "
            "them merged in, with a backup):\n\n"
            + json.dumps(entries, indent=_JSON_INDENT)
            + "\n\n"
            + "\n".join(f"- {caveat}" for caveat in caveats)
        )

    def refuse_unsupported_version(self) -> None:
        """Refuse a kiro-cli older than the floor, whose V3 engine this was never run against."""
        found = harness_cli.installed_version()
        if found >= harness_cli.MINIMUM_VERSION:
            return
        raise InstallError(
            f"kiro-cli {_dotted(found)} is older than {_dotted(harness_cli.MINIMUM_VERSION)}, the "
            "oldest release whose V3 agent engine Zikaron supports. Upgrade kiro-cli and re-run."
        )

    def notes(self, plan: Plan) -> list[str]:
        del plan
        return [
            "Zikaron runs on kiro's V3 agent engine: the default from kiro-cli 3.0, and `--v3` on "
            "2.35. Under V2 the consolidator's and the documenter's first tool call asks for "
            "permission, with nobody to answer it.",
            "kiro starts a session's first turn without waiting for its MCP servers, and "
            "`zikaron-mcp` takes about two seconds to start, so a headless run "
            "(`kiro-cli chat --no-interactive`) needs `--require-mcp-startup` or its first turn "
            "has no Zikaron tools. The flag does not make an interactive session wait, even one "
            "given its first prompt on the command line.",
        ]

    def refuse_unknown_model(self, model: str) -> None:
        """`architecture.md`'s no-silent-fallback rule, enforced where a config is about to be
        written.

        The check is *membership*, not a regex or a prefix: the harness answers with an exact set,
        and kiro documents an unknown id as replaced by its default, with a warning at most, which
        leaves two consolidation runs incomparable while both look healthy.
        """
        available = harness_cli.available_model_ids()
        if model in available:
            return
        raise InstallError(
            f"{model!r} is not a model this harness offers. `kiro-cli agent validate` would accept "
            "it silently and the harness would run its default instead, so it is refused here. "
            f"Available: {', '.join(sorted(available))}"
        )

    def complaints_about(self, paths: list[Path]) -> list[str]:
        """`kiro-cli agent validate`'s own text about any JSON we wrote, if it has any.

        Its diagnostics name the offending field, so they are relayed rather than replaced with
        "invalid". This catches a schema mistake in what we just wrote; the model check above
        catches the one thing this command provably does not.
        """
        complaints: list[str] = []
        for path in paths:
            if path.suffix != ".json":
                continue
            complaint = harness_cli.validate_agent_config(path)
            if complaint is not None:
                complaints.append(f"{path}: `kiro-cli agent validate` says: {complaint}")
        return complaints


class ClaudeCodeTarget(HarnessTarget):
    """Claude Code: the shipped Markdown artefacts — three agents and two skills — and two merges
    into fixed project files."""

    spec = CLAUDE_CODE

    @property
    def accepts_agent_flag(self) -> bool:
        return False

    @property
    def ships_orchestrator(self) -> bool:
        return True

    def _settings(self, project: Path) -> Path:
        """`.claude/settings.local.json`, never `settings.json`.

        The `command` strings written here are absolute venv paths — machine-local by construction,
        for the reason `architecture.md` §"The install contract" gives about console scripts — and
        `settings.json` is the shared, checked-in layer. Writing machine-local paths into a file the
        user commits would break every other clone of the repository.
        """
        return project / ".claude" / "settings.local.json"

    def _mcp_config(self, project: Path) -> Path:
        return claude_mcp_config(project)

    def shipped_files(self, plan: Plan) -> tuple[ShippedFile, ...]:
        """The consolidator, the documenter, the code orchestrator the documentation skill has the
        session spawn, and the two skills, which only the memory store ships."""
        if not plan.components.memory:
            return ()
        project = plan.project
        return (
            ShippedFile(
                project / ".claude" / "agents" / f"{CONSOLIDATOR_AGENT_NAME}.md",
                consolidator_agent_markdown(plan.commands, model=plan.consolidator_model),
            ),
            ShippedFile(
                project / ".claude" / "skills" / SKILL_NAME / "SKILL.md",
                skill_markdown(claude_tool_vocabulary(), CLAUDE_CODE_SPAWN_INSTRUCTION),
            ),
            ShippedFile(
                project / ".claude" / "agents" / f"{DOCUMENTER_AGENT_NAME}.md",
                documenter_agent_markdown(model=plan.documenter_model),
            ),
            ShippedFile(
                project / ".claude" / "agents" / f"{ORCHESTRATOR_AGENT_NAME}.md",
                orchestrator_agent_markdown(model=plan.orchestrator_model),
            ),
            ShippedFile(
                project / ".claude" / "skills" / DOCUMENT_SKILL_NAME / "SKILL.md",
                launch_skill(claude_tool_vocabulary()),
            ),
        )

    def plan_merges(self, plan: Plan, agent: Path | None) -> tuple[MergePlan, ...]:
        del agent  # refused upstream by `accepts_agent_flag`; never reaches here.
        if not plan.components.memory:
            return (self._plan_settings(plan),)
        return (self._plan_settings(plan), self._plan_mcp(plan))

    def _plan_settings(self, plan: Plan) -> MergePlan:
        """This selection's hook groups, and for the memory store the approvals, merged into the
        settings file.

        **The user's own hooks on our triggers survive**, which is not a nicety: `SessionStart` and
        `UserPromptSubmit` are ordinary triggers a person may already be using, and this file is one
        they edit by hand. So the merge replaces *our* groups within each trigger's list and leaves
        every other group exactly where it was — the same rule kiro's `_merged_hooks_object`
        applies, for the same reason.

        **An install touches only its own selection** (`design/guards.md` §5): triggers it does
        not write are copied verbatim, and so is the other selection's group on a trigger both
        write, so guards over a memory install keep every memory hook, and the reverse. The start
        entries both selections share take the union of what they carry and what is being
        installed. `settings_hooks` holds the rule.
        """
        path = self._settings(plan.project)
        _guard_backup_path_if_present(path)
        document = _load_json_object_or_empty(path)
        hooks = settings_hooks.merge(_hook_groups_by_trigger(document, path), plan=plan, path=path)
        merged = dict(document)
        merged["hooks"] = hooks.hooks
        notes = list(hooks.notes)
        if plan.components.memory:
            notes.extend(_merge_approvals(document, merged, plan=plan, path=path))
        return MergePlan(
            path=path, document=merged, notes=tuple(notes), unchanged=merged == document
        )

    def _plan_mcp(self, plan: Plan) -> MergePlan:
        """Both servers into `.mcp.json`, **merged per key** rather than replaced.

        A difference outside `MCP_OWNERSHIP_FIELDS` is an upgrade rather than a conflict, so nothing
        refuses on it — and replacing the entry wholesale would therefore delete a key the *user*
        put on Zikaron's own entry, silently. Merging keeps it, and `ownership.merged_server`
        reports what it kept, added and overwrote, since not refusing must not mean not saying.

        **`--force` replaces the entry whole**, which is what it is for: it takes over an entry
        another install owns, and merging there would carry that install's keys forward. **It does
        so whether or not ownership differs** — the flag has one meaning on both merged files, and
        on a clone-mate's committed `.mcp.json` a whole replacement is what keeps a stranger's `env`
        out of a server this install registers for the whole session. So the flag can drop a key
        from *this* install's own entry too, on a run passed for something else entirely, which is
        what the note covers.
        """
        path = self._mcp_config(plan.project)
        _guard_backup_path_if_present(path)
        document = _load_json_object_or_empty(path)
        servers = claude_mcp_servers_value(plan.commands)
        existing = document.get("mcpServers")
        _refuse_unmergeable_shape(existing, dict, path=path, key="mcpServers")
        refuse_conflicting(existing, servers, path=path, key="mcpServers", force=plan.force)
        current: dict[str, object] = existing if isinstance(existing, dict) else {}
        merged_servers: dict[str, object] = dict(current)
        notes: list[str] = []
        for name, entry in servers.items():
            merged_servers[name], entry_notes = merged_server(
                current.get(name),
                entry,
                name=name,
                force=plan.force,
                registered_for="for the whole session",
            )
            notes.extend(entry_notes)
        merged = dict(document)
        merged["mcpServers"] = merged_servers
        return MergePlan(
            path=path, document=merged, notes=tuple(notes), unchanged=merged == document
        )

    def fragment(self, plan: Plan) -> str:
        # Built with this run's own flags rather than with the defaults, so the preview is a preview
        # of *this* install: showing `enabledMcpjsonServers` beside `--no-trust-tools` would promise
        # something the real run would withhold — and the start entries' selection is the union
        # the real run would write, read from the file as it stands.
        start = self._previewed_start_selection(plan)
        previewed: dict[str, object] = {
            "hooks": claude_hooks_value(plan.commands, plan.components, start=start)
        }
        if not plan.components.memory:
            settings = json.dumps(previewed, indent=_JSON_INDENT)
            return f"Add these to {self._settings(plan.project)}:\n\n{settings}"
        if plan.trust_tools:
            previewed[_ENABLED_SERVERS_KEY] = sorted(_ZIKARON_SERVERS)
        previewed[_PERMISSIONS_KEY] = _merged_permissions(
            {}, trust_tools=plan.trust_tools, path=self._settings(plan.project)
        )[0]
        settings = json.dumps(previewed, indent=_JSON_INDENT)
        mcp = json.dumps(
            {"mcpServers": claude_mcp_servers_value(plan.commands)}, indent=_JSON_INDENT
        )
        # The three advisory notes are deliberately *not* appended here, unlike the caveats kiro's
        # fragment carries. `notes()` below returns them and every caller extends with it, so a copy
        # here printed each one twice under `--print-only` — the one path that appends the fragment
        # and the notes. Kiro is unaffected because its fragment's caveats are config-shape advice
        # its `notes()` does not repeat, which is the arrangement this now matches.
        return (
            f"Add these to {self._settings(plan.project)}:\n\n{settings}\n\n"
            f"and these to {self._mcp_config(plan.project)}:\n\n{mcp}"
        )

    def _previewed_start_selection(self, plan: Plan) -> Components:
        """The start entries' selection an install would write over the settings file as it
        stands, or this run's own where the file cannot be read: a preview refuses nothing it does
        not have to, and the real run reports the file's problem."""
        path = self._settings(plan.project)
        try:
            by_trigger = _hook_groups_by_trigger(_load_json_object_or_empty(path), path)
        except InstallError:
            return plan.components
        return settings_hooks.start_selection(by_trigger, plan)

    def refuse_unsupported_version(self) -> None:
        """No release floor: nothing an install writes here depends on one Claude Code release."""

    def refuse_unknown_model(self, model: str) -> None:
        """Refuse a model id that cannot be written into YAML frontmatter as given.

        **There is no *availability* check here, and that is measured rather than assumed.**

        Claude Code refuses an unrecognised model id at spawn, loudly, before any turn executes
        (`research/claude-code-harness-probe.md` §7d) — the opposite of kiro's silent substitution,
        which is the *sole* reason the `--list-models` membership check exists at all. The harness
        enforces no-silent-fallback itself, so a check here would add a dependency on a command
        Claude Code does not offer in order to re-derive a guarantee it already gives.

        **What is checked is the id's *shape*.** This value is interpolated into YAML frontmatter by
        string formatting, so `--model "a: b"` changes what the document *means* and a value with an
        embedded newline injects a frontmatter key — both of which parse as valid YAML, so nothing
        downstream complains. The harness eventually refuses the mangled model at spawn, by which
        time the artefact has been claiming things the user never asked for. Every real id and alias
        satisfies the pattern.

        Raises:
            InstallError: the id is not a plain single-line token.
        """
        if _MODEL_ID.fullmatch(model) is not None:
            return
        raise InstallError(
            f"{model!r} cannot be written into YAML frontmatter as given. An agent's "
            "`model:` must be a plain id or alias — letters, digits, dots, hyphens, underscores — "
            "because a value carrying a colon or a newline would silently change what that file "
            "means rather than fail."
        )

    def notes(self, plan: Plan) -> list[str]:
        """The memory store's notes; the guards have none to give."""
        if not plan.components.memory:
            return []
        notes = [_APPROVAL_NOTE, _SPILL_READ_NOTE, _EXPOSURE_NOTE]
        blind = agent_scan.blind_agents(plan.project)
        if blind:
            notes.append(_blind_agents_note(blind))
        return notes


#: Both `.mcp.json` keys this install writes. Derived from the two names `entries.py` already owns
#: rather than re-listed, so a rename moves the pre-approval with the registration.
_ZIKARON_SERVERS: Final = frozenset({MCP_SERVER_NAME, CONSOLIDATOR_AGENT_NAME})

TARGETS: Final[dict[Harness, HarnessTarget]] = {
    Harness.KIRO: KiroTarget(),
    Harness.CLAUDE_CODE: ClaudeCodeTarget(),
}


def claude_mcp_config(project: Path) -> Path:
    """Where a Claude Code install registers both servers; `doctor` reads the same path."""
    return project / ".mcp.json"


def target_for(harness: Harness) -> HarnessTarget:
    """The installer adapter for `harness`."""
    return TARGETS[harness]


def _guard_backup_path_if_present(path: Path) -> None:
    """Run the backup-path check **at plan time**, when the target exists.

    `plan_kiro_merge`'s docstring gives the reason: the backup is the
    last thing a merge does and the shipped files are written before it, so leaving the check where
    it happens means a blocked `<file>.bak` is discovered only after the artefacts have landed — the
    half-install the plan/commit split exists to prevent. Omitting it here has a concrete symptom:
    a **directory** at `.mcp.json.bak` produces two written files, one merged file, and *then*
    "install refused". The same condition is re-tested at commit; a check and a use are
    two moments and this one is cheap.

    Raises:
        InstallError: something is at `<path>.bak` and it is not a regular file.
    """
    if path.exists() or path.is_symlink():
        guard_backup_path(path)


def _refuse_unmergeable_shape(value: object, expected: type, *, path: Path, key: str) -> None:
    """Refuse a key we merge into whose value is not the shape it must be.

    **Not defensive filtering, deliberately.** Treating a wrong-shaped value as absent and writing
    ours over it is data loss wearing a reassuring shape — `writer.py`'s
    `_guard_mergeable_shapes` makes the same argument for kiro, and its tests are named
    `TestShapesThatWouldBeSilentlyDropped`. Whatever the user put there, this code cannot know what
    they meant by it, and a settings file is a thing people hand-edit.

    Absence is fine and is not this function's business: a key that is not there is exactly what a
    fresh project has.

    Raises:
        InstallError: the key is present and is the wrong kind of thing.
    """
    if value is None or isinstance(value, expected):
        return
    raise InstallError(
        f"{path} has {key} as {type(value).__name__}, which this cannot merge into — it must be "
        f"{'an object' if expected is dict else 'an array'}. Whatever is there was put there "
        "deliberately, so it is refused rather than replaced. Move it aside and re-run."
    )


def _hook_groups_by_trigger(document: dict[str, object], path: Path) -> dict[str, list[object]]:
    """The settings file's hook groups, per trigger.

    Raises:
        InstallError: `hooks`, or a trigger's value under it, is the wrong shape.
    """
    existing = document.get("hooks")
    _refuse_unmergeable_shape(existing, dict, path=path, key="hooks")
    by_trigger: dict[str, list[object]] = {}
    for key, value in (existing or {}).items() if isinstance(existing, dict) else ():
        _refuse_unmergeable_shape(value, list, path=path, key=f"hooks.{key}")
        by_trigger[key] = list(value)
    return by_trigger


def _merge_approvals(
    document: dict[str, object], merged: dict[str, object], *, plan: Plan, path: Path
) -> list[str]:
    """The memory store's two approval keys into `merged`, and what saying so needs.

    Raises:
        InstallError: either key is present and is the wrong shape.
    """
    notes: list[str] = []
    listed = document.get(_ENABLED_SERVERS_KEY)
    _refuse_unmergeable_shape(listed, list, path=path, key=_ENABLED_SERVERS_KEY)
    if plan.trust_tools:
        merged[_ENABLED_SERVERS_KEY] = _with_servers(listed)
    elif not _ZIKARON_SERVERS.issubset(_strings_in(listed)):
        # **Conditioned on absence.** The merge never *removes* an
        # entry, so a `--no-trust-tools` re-run over a previously-trusting install leaves both
        # grants in the file — and an unconditional note would then assert the opposite of what
        # the file now says. `plan_kiro_merge` already guards its equivalent note this way.
        notes.append(
            f"`{_ENABLED_SERVERS_KEY}` was **not** written (--no-trust-tools), so you will be "
            "asked to approve both Zikaron servers before any Zikaron tool loads."
        )
    merged[_PERMISSIONS_KEY], allow_notes = _merged_permissions(
        document, trust_tools=plan.trust_tools, path=path
    )
    notes.extend(allow_notes)
    return notes


def _merged_permissions(
    document: dict[str, object], *, trust_tools: bool, path: Path
) -> tuple[dict[str, object], list[str]]:
    """`permissions` with Zikaron's tools pre-approved, and whatever else was there left alone.

    **The consolidator's server is allowed unconditionally**: a subagent has no user to answer a
    permission prompt, so a tool that is available but not allowed is a tool that hangs or fails at
    the moment the consolidator needs it. `--no-trust-tools` is a statement about *your* writes,
    not about whether consolidation can run at all.

    The primary server follows `--no-trust-tools`, which reproduces kiro's asymmetry exactly.

    **Server-level wildcards rather than one entry per tool name**, matching the consolidator's
    frontmatter grant for the same reason: there is no second list to drift from
    `mcp/tool_names.py`. No count is written here — a wildcard exists precisely so nobody
    maintains one.

    That these entries actually remove the per-call prompt is **measured**, interactively
    (`research/claude-code-dogfood-checkpoint.md` §1; `design/harness.md` §"Three approval gates"):
    no per-call prompt across six writes and eight reads. **The install still states the approval
    step in its output anyway**, and the reason survives the measurement rather than being retired
    by it — no install-time or headless check can verify the effect, because a headless run
    approves everything, so nothing in the shipped software can notice the day a key stops
    working. `enabledMcpjsonServers` ships on the same standing, measured in the same session.

    Raises:
        InstallError: `permissions` or `permissions.allow` is present and is the wrong shape.
    """
    existing = document.get(_PERMISSIONS_KEY)
    _refuse_unmergeable_shape(existing, dict, path=path, key=_PERMISSIONS_KEY)
    permissions: dict[str, object] = dict(existing) if isinstance(existing, dict) else {}
    allowed = permissions.get(_ALLOW_KEY)
    _refuse_unmergeable_shape(allowed, list, path=path, key=f"{_PERMISSIONS_KEY}.{_ALLOW_KEY}")
    listed: list[object] = list(allowed) if isinstance(allowed, list) else []

    wanted = {f"mcp__{CONSOLIDATOR_AGENT_NAME}"}
    if trust_tools:
        wanted.add(f"mcp__{MCP_SERVER_NAME}")
    present = _strings_in(allowed)
    permissions[_ALLOW_KEY] = [*listed, *sorted(wanted - present)]

    notes: list[str] = []
    if not trust_tools and f"mcp__{MCP_SERVER_NAME}" not in present:
        # Absence-conditioned for the same reason as the note above: nothing here removes a grant a
        # previous default install added, so saying it was withheld would be false on a re-run.
        notes.append(
            f"`mcp__{MCP_SERVER_NAME}` was **not** added to `permissions.allow` "
            "(--no-trust-tools), so every Zikaron tool call asks your approval. The consolidator's "
            "own server is allowed regardless: a subagent has nobody to answer a prompt, so an "
            "unapproved tool there fails at the moment consolidation needs it."
        )
    return permissions, notes


def _strings_in(value: object) -> set[str]:
    """Every string in `value`, if it is a list at all. Typed against `object` because both callers
    are reading a document the user wrote."""
    if not isinstance(value, list):
        return set()
    return {entry for entry in value if isinstance(entry, str)}


def _with_servers(existing: object) -> list[object]:
    """`existing` plus both Zikaron servers, order-stably and without duplicates.

    Order-stable because this rewrites a list the user may have curated, and reordering it in a
    diff for no reason is a change they have to read.
    """
    listed: list[object] = list(existing) if isinstance(existing, list) else []
    return [*listed, *sorted(_ZIKARON_SERVERS - _strings_in(existing))]


def _load_json_object_or_empty(path: Path) -> dict[str, object]:
    """The JSON object at `path`, or an empty one if nothing is there.

    Absence is **normal** here and is the one difference from kiro's `_load_agent_config`, which
    refuses it: kiro's merge target is a file the user named, so its absence is a mistake worth
    reporting, while these two are fixed project paths that a fresh project legitimately lacks.
    Anything *present* and unreadable is still refused — an empty dict for a malformed file would
    silently discard whatever the user had.

    Raises:
        InstallError: the file exists and is not readable, or is not a JSON object.
    """
    if not (path.exists() or path.is_symlink()):
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"could not read {path}: {exc}") from exc
    if not raw.strip():
        # An empty file is how an editor leaves a config someone started and abandoned. Treating it
        # as `{}` is both what the harness does and the only reading that lets an install proceed.
        return {}
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise InstallError(f"{path} is not a JSON object, so there is nothing to merge into")
    return document


def _dotted(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)
