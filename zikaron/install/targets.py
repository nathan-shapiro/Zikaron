"""The one place a harness difference is allowed to take a different **shape** rather than a
different value.

`design/harness.md` §"The installer's two targets" is normative. Everywhere else in Zikaron — both
thin clients — a harness difference is data in `zikaron.harness.spec`, because forking doubles every
future change to the two components the design keeps deliberately thin. The installer cannot be
written that way, and the reason is structural rather than a concession: kiro's artefacts are
**one** file whose path the *user* supplies, and Claude Code's are **four** files at paths the
*project* fixes. That is not two values of one parameter.

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
from pathlib import Path
from typing import Final

from zikaron.harness.spec import CLAUDE_CODE, KIRO, Harness, HarnessSpec
from zikaron.install import harness as harness_cli
from zikaron.install.assets import (
    CLAUDE_CODE_SPAWN_INSTRUCTION,
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
    claude_hooks_value,
    claude_mcp_servers_value,
    claude_tool_vocabulary,
    consolidator_agent_config,
    consolidator_agent_markdown,
    hooks_value,
    mcp_servers_value,
)
from zikaron.install.harness import InstallError
from zikaron.install.writer import (
    ARRAY_FORMAT_OUTPUT_CAP_NOTE,
    MergePlan,
    Plan,
    ShippedFile,
    Targets,
    guard_backup_path,
    plan_kiro_merge,
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
#: unmeasured universal, which a review caught and this corpus's own rule forbids. Probing it
#: refuted it: a subagent whose frontmatter said `model: sonnet[1m]` **spawned normally**
#: (`research/claude-code-installer-probe.md` §11), so the long-context alias form is a legitimate
#: value the installer was rejecting.
_MODEL_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\[\]-]*")

#: The settings key that pre-approves project-scoped MCP servers. Written under the same
#: `--no-trust-tools` flag that governs kiro's `allowedTools`, because it answers the same question:
#: does this install trust its own tools, or make the user approve them one at a time.
_ENABLED_SERVERS_KEY: Final = "enabledMcpjsonServers"

#: Claude Code's permission key. **Distinct from `_ENABLED_SERVERS_KEY`, and a review caught the
#: install conflating them**: that key governs whether a project-scoped server *loads*, while this
#: one governs whether each tool *call* is approved. Writing only the first left every
#: `zikaron_remember` behind an approval prompt — the per-write friction `writer._selecting` calls
#: worse than not asking at all, installed silently on the harness we are migrating to.
_PERMISSIONS_KEY: Final = "permissions"
_ALLOW_KEY: Final = "allow"

#: Said whenever a Claude Code install completes, because the failure it warns about is silent and
#: total: a project-scoped server that has not been approved simply does not load, and the agent
#: then has no memory tools with nothing anywhere saying why.
_APPROVAL_NOTE: Final = (
    "Claude Code asks for approval twice over, and a default install answers both: "
    f"`{_ENABLED_SERVERS_KEY}` for whether a project-scoped `.mcp.json` server **loads** at all, "
    "and "
    f"`{_PERMISSIONS_KEY}.{_ALLOW_KEY}` for whether each tool **call** goes through without a "
    "prompt. That either key has the effect intended is documented rather than measured "
    "(`research/claude-code-installer-probe.md` §8: a headless run approves everything, so the "
    "property cannot be observed without an interactive session). So if the memory tools are "
    "absent, check `/mcp` for a server pending approval before looking anywhere else — and if they "
    "are present but every write interrupts you, it is the second key that did not take."
)

#: The exposure D32 cannot mechanically prevent here, reported rather than passed over in silence —
#: the same reflex M12 applied to the array format's inherited `max_output_size`.
_EXPOSURE_NOTE: Final = (
    "Your primary agent can see the four consolidation verbs "
    f"(`mcp__{CONSOLIDATOR_AGENT_NAME}__*`) as well as its own five tools. That is not a "
    "misconfiguration and it cannot be fixed here: a server must be registered session-wide to be "
    "reachable by any subagent at all, and `permissions.deny` is global — denying a verb "
    "unregisters it and the consolidator subagent is then refused at spawn with zero tools. Under "
    "kiro the two tool sets are mechanically separate; here that half of the design is "
    "prompt-only, and an unauthorized consolidation costs tokens and possibly a poorly-judged "
    "long-term record."
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
        memory tools, and nothing anywhere saying why. That is the same working-looking-inert
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
            "memory tools at all. Install the harness first, or use --print-only to see exactly "
            "what would be written."
        )

    @abstractmethod
    def refuse_unknown_model(self, model: str) -> None:
        """Refuse a model id this harness would not serve as asked.

        Raises:
            InstallError: the id is not one this harness accepts.
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
    """kiro-cli: two shipped files under `.kiro/`, and one merge into a user-named agent config.

    Byte-for-byte what M12 shipped. That is asserted by a regression guard rather than hoped for:
    this milestone's whole risk is that generalising the writer quietly changes the working
    harness's output, and "we did not mean to" is not evidence.
    """

    spec = KIRO

    @property
    def accepts_agent_flag(self) -> bool:
        return True

    def shipped_files(self, plan: Plan) -> tuple[ShippedFile, ...]:
        targets = Targets(project=plan.project)
        config = consolidator_agent_config(plan.commands, model=plan.model)
        return (
            ShippedFile(
                targets.consolidator_config, json.dumps(config, indent=_JSON_INDENT) + "\n"
            ),
            ShippedFile(
                targets.skill_file,
                skill_markdown(identity_vocabulary(), KIRO_SPAWN_INSTRUCTION),
            ),
        )

    def plan_merges(self, plan: Plan, agent: Path | None) -> tuple[MergePlan, ...]:
        if agent is None:
            return ()
        return (plan_kiro_merge(agent, plan, Targets(project=plan.project)),)

    def fragment(self, plan: Plan) -> str:
        entries = json.dumps(
            {
                "hooks": hooks_value(plan.commands, plan.hook_format),
                "mcpServers": mcp_servers_value(plan.commands, mode="primary"),
            },
            indent=_JSON_INDENT,
        )
        caveats = [
            f"`{TOOL_SELECTOR}` must be in that agent's `tools`, or the memory tools are simply "
            "absent — `mcpServers` configures the server and `tools` selects from it. Put it in "
            "`allowedTools` as well, or every memory write will interrupt you for approval.",
            "The agent also needs `subagent` among its `tools` for the zikaron-consolidate skill "
            "to spawn the consolidator.",
        ]
        if plan.hook_format is HookFormat.ARRAY:
            caveats.append(ARRAY_FORMAT_OUTPUT_CAP_NOTE)
        return (
            "Add these to the agent config you actually use (or re-run with --agent <path> to have "
            "them merged in, with a backup):\n\n"
            + entries
            + "\n\n"
            + "\n".join(f"- {caveat}" for caveat in caveats)
        )

    def refuse_unknown_model(self, model: str) -> None:
        """`architecture.md`'s no-silent-fallback rule, enforced where a config is about to be
        written.

        The check is *membership*, not a regex or a prefix: the harness answers with an exact set,
        and accepting anything outside it would install a config whose model the harness silently
        replaces with its own default — leaving two consolidation runs incomparable while both look
        healthy.
        """
        available = harness_cli.available_model_ids()
        if model in available:
            return
        raise InstallError(
            f"{model!r} is not a model this harness offers. `kiro-cli agent validate` would accept "
            "it silently and the harness would fall back to its default, so it is refused here "
            f"instead. Available: {', '.join(sorted(available))}"
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
    """Claude Code: two shipped Markdown/JSON artefacts, and two merges into fixed project files."""

    spec = CLAUDE_CODE

    @property
    def accepts_agent_flag(self) -> bool:
        return False

    def _settings(self, project: Path) -> Path:
        """`.claude/settings.local.json`, never `settings.json`.

        The `command` strings written here are absolute venv paths — machine-local by construction,
        for the reason `architecture.md` §"The install contract" gives about console scripts — and
        `settings.json` is the shared, checked-in layer. Writing machine-local paths into a file the
        user commits would break every other clone of the repository.
        """
        return project / ".claude" / "settings.local.json"

    def _mcp_config(self, project: Path) -> Path:
        return project / ".mcp.json"

    def shipped_files(self, plan: Plan) -> tuple[ShippedFile, ...]:
        project = plan.project
        return (
            ShippedFile(
                project / ".claude" / "agents" / f"{CONSOLIDATOR_AGENT_NAME}.md",
                consolidator_agent_markdown(plan.commands, model=plan.model),
            ),
            ShippedFile(
                project / ".claude" / "skills" / SKILL_NAME / "SKILL.md",
                skill_markdown(claude_tool_vocabulary(), CLAUDE_CODE_SPAWN_INSTRUCTION),
            ),
        )

    def plan_merges(self, plan: Plan, agent: Path | None) -> tuple[MergePlan, ...]:
        del agent  # refused upstream by `accepts_agent_flag`; never reaches here.
        return (self._plan_settings(plan), self._plan_mcp(plan))

    def _plan_settings(self, plan: Plan) -> MergePlan:
        """Hook entries, and optionally the server pre-approval, merged into the settings file.

        **The user's own hooks on our triggers survive**, which is not a nicety: `SessionStart` and
        `UserPromptSubmit` are ordinary triggers a person may already be using, and this file is one
        they edit by hand. So the merge replaces *our* group within each trigger's list and leaves
        every other group exactly where it was — the same rule kiro's `_merged_hooks_object`
        applies, for the same reason. An earlier version of this method assigned the whole trigger
        key, which would have deleted a user's own hook and, worse, refused the install first on
        the grounds that it "differed".
        """
        path = self._settings(plan.project)
        _guard_backup_path_if_present(path)
        document = _load_json_object_or_empty(path)
        existing = document.get("hooks")
        _refuse_unmergeable_shape(existing, dict, path=path, key="hooks")
        by_trigger: dict[str, list[object]] = {}
        for key, value in (existing or {}).items() if isinstance(existing, dict) else ():
            _refuse_unmergeable_shape(value, list, path=path, key=f"hooks.{key}")
            by_trigger[key] = list(value)
        ours = claude_hooks_value(plan.commands)
        _refuse_differing_hook_groups(by_trigger, ours, plan=plan, path=path)

        merged = dict(document)
        merged["hooks"] = {
            **{key: value for key, value in by_trigger.items() if key not in ours},
            **{
                trigger: [
                    *(
                        group
                        for group in by_trigger.get(trigger, [])
                        if not _is_a_zikaron_hook_group(group, plan.commands)
                    ),
                    *groups,
                ]
                for trigger, groups in ours.items()
            },
        }
        notes: list[str] = []
        listed = document.get(_ENABLED_SERVERS_KEY)
        _refuse_unmergeable_shape(listed, list, path=path, key=_ENABLED_SERVERS_KEY)
        if plan.trust_tools:
            merged[_ENABLED_SERVERS_KEY] = _with_servers(listed)
        elif not _ZIKARON_SERVERS.issubset(_strings_in(listed)):
            # **Conditioned on absence, which a review caught.** The merge never *removes* an
            # entry, so a `--no-trust-tools` re-run over a previously-trusting install leaves both
            # grants in the file — and an unconditional note would then assert the opposite of what
            # the file now says. `plan_kiro_merge` already guards its equivalent note this way.
            notes.append(
                f"`{_ENABLED_SERVERS_KEY}` was **not** written (--no-trust-tools), so you will be "
                "asked to approve both Zikaron servers before any memory tool loads."
            )
        merged[_PERMISSIONS_KEY], allow_notes = _merged_permissions(
            document, trust_tools=plan.trust_tools, path=path
        )
        notes.extend(allow_notes)
        return MergePlan(path=path, document=merged, notes=tuple(notes))

    def _plan_mcp(self, plan: Plan) -> MergePlan:
        """Both servers merged into `.mcp.json`."""
        path = self._mcp_config(plan.project)
        _guard_backup_path_if_present(path)
        document = _load_json_object_or_empty(path)
        servers = claude_mcp_servers_value(plan.commands)
        existing = document.get("mcpServers")
        _refuse_unmergeable_shape(existing, dict, path=path, key="mcpServers")
        _refuse_conflicting(existing, servers, path=path, key="mcpServers", force=plan.force)
        merged = dict(document)
        merged["mcpServers"] = {
            **(existing if isinstance(existing, dict) else {}),
            **servers,
        }
        return MergePlan(path=path, document=merged, notes=())

    def fragment(self, plan: Plan) -> str:
        # Built with this run's own flags rather than with the defaults, so the preview is a preview
        # of *this* install: showing `enabledMcpjsonServers` beside `--no-trust-tools` would promise
        # something the real run would withhold.
        previewed: dict[str, object] = {"hooks": claude_hooks_value(plan.commands)}
        if plan.trust_tools:
            previewed[_ENABLED_SERVERS_KEY] = sorted(_ZIKARON_SERVERS)
        previewed[_PERMISSIONS_KEY] = _merged_permissions(
            {}, trust_tools=plan.trust_tools, path=self._settings(plan.project)
        )[0]
        settings = json.dumps(previewed, indent=_JSON_INDENT)
        mcp = json.dumps(
            {"mcpServers": claude_mcp_servers_value(plan.commands)}, indent=_JSON_INDENT
        )
        return (
            f"Add these to {self._settings(plan.project)}:\n\n{settings}\n\n"
            f"and these to {self._mcp_config(plan.project)}:\n\n{mcp}\n\n"
            f"- {_APPROVAL_NOTE}\n- {_EXPOSURE_NOTE}"
        )

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
            f"{model!r} cannot be written into YAML frontmatter as given. The consolidator's "
            "`model:` must be a plain id or alias — letters, digits, dots, hyphens, underscores — "
            "because a value carrying a colon or a newline would silently change what that file "
            "means rather than fail."
        )

    def notes(self, plan: Plan) -> list[str]:
        del plan
        return [_APPROVAL_NOTE, _EXPOSURE_NOTE]


#: Both `.mcp.json` keys this install writes. Derived from the two names `entries.py` already owns
#: rather than re-listed, so a rename moves the pre-approval with the registration.
_ZIKARON_SERVERS: Final = frozenset({MCP_SERVER_NAME, CONSOLIDATOR_AGENT_NAME})

TARGETS: Final[dict[Harness, HarnessTarget]] = {
    Harness.KIRO: KiroTarget(),
    Harness.CLAUDE_CODE: ClaudeCodeTarget(),
}


def target_for(harness: Harness) -> HarnessTarget:
    """The installer adapter for `harness`."""
    return TARGETS[harness]


#: Shared by both conflict refusals below. They guard different shapes — a list of hook *groups*
#: matched by command, and a server *map* matched by key — which is why there are two of them; the
#: *explanation* is identical, and a review caught it existing as two hand-maintained copies.
_ANOTHER_INSTALL: Final = (
    "That usually means another Zikaron install owns them, whose paths may point at a venv this "
    "one knows nothing about. Re-run with --force to replace them."
)


def _guard_backup_path_if_present(path: Path) -> None:
    """Run the backup-path check **at plan time**, when the target exists.

    `plan_kiro_merge` has done this since M12 and its docstring gives the reason: the backup is the
    last thing a merge does and the shipped files are written before it, so leaving the check where
    it happens means a blocked `<file>.bak` is discovered only after the artefacts have landed — the
    half-install the plan/commit split exists to prevent. The Claude Code planners omitted it, which
    a review caught: a **directory** at `.mcp.json.bak` produced two written files, one merged file,
    and *then* "install refused". The same condition is re-tested at commit; a check and a use are
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


def _merged_permissions(
    document: dict[str, object], *, trust_tools: bool, path: Path
) -> tuple[dict[str, object], list[str]]:
    """`permissions` with Zikaron's tools pre-approved, and whatever else was there left alone.

    **The consolidator's server is allowed unconditionally**, and that is the same argument
    `architecture.md` §"The install contract" already makes about kiro's `allowedTools`: a subagent
    has no user to answer a permission prompt, so a tool that is available but not allowed is a tool
    that hangs or fails at the moment the consolidator needs it. `--no-trust-tools` is a statement
    about *your* writes, not about whether consolidation can run at all.

    The primary server follows `--no-trust-tools`, which reproduces kiro's asymmetry exactly.

    **Server-level wildcards rather than nine tool names**, matching the consolidator's frontmatter
    grant for the same reason: there is no second list to drift from `mcp/tool_names.py`.

    That these entries actually remove the per-call prompt is **documented, unmeasured** — the same
    standing `enabledMcpjsonServers` already ships on, and for the same reason: a headless run
    approves everything, so the property cannot be observed without an interactive session. M16.

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
            "(--no-trust-tools), so every memory write will ask your approval. The consolidator's "
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


def _commands_in(group: object) -> list[str]:
    """Every `command` string inside one settings hook group, defensively.

    Shared by the recogniser and the diagnostic so the two cannot disagree about what an entry *is*
    — and typed against `object` throughout because one side of every comparison is a document the
    user wrote.
    """
    if not isinstance(group, dict):
        return []
    entries = group.get("hooks")
    if not isinstance(entries, list):
        return []
    return [
        str(entry["command"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("command"), str)
    ]


def _is_a_zikaron_hook_group(group: object, commands: Commands) -> bool:
    """Whether a settings hook group is one Zikaron installed.

    Matched on the command's **file name**, not its full path, and that is deliberate: a group
    naming `/somewhere-else/venv/bin/zikaron-hook` belongs to a *different* Zikaron install, and
    recognising it is exactly what lets this install replace it rather than leave two hooks firing
    into the same store from two interpreters.
    """
    return any(Path(command).name == commands.hook.name for command in _commands_in(group))


def _refuse_differing_hook_groups(
    by_trigger: dict[str, list[object]],
    ours: dict[str, list[dict[str, object]]],
    *,
    plan: Plan,
    path: Path,
) -> None:
    """Refuse when an existing **Zikaron** hook group is not exactly what this install would write.

    The contract's word is *differs*, and only our own groups are examined — a user's unrelated
    hook on the same trigger is theirs and is never compared, only preserved. A Zikaron group that
    differs means another install owns it, whose absolute path may point at a venv that no longer
    has Zikaron in it; replacing it silently would hide that the user has two installs, and the
    refusal names the trigger so they can tell their own edit from a version change.

    Raises:
        InstallError: a Zikaron group differs and `--force` was not passed.
    """
    if plan.force:
        return
    differing = sorted(
        f"{trigger}: {_describe_group_difference(group, groups)}"
        for trigger, groups in ours.items()
        for group in by_trigger.get(trigger, [])
        if _is_a_zikaron_hook_group(group, plan.commands) and group not in groups
    )
    if not differing:
        return
    raise InstallError(
        f"{path} already carries Zikaron hook entries that differ from what this install would "
        f"write ({'; '.join(differing)}). {_ANOTHER_INSTALL}"
    )


def _describe_group_difference(group: object, expected: list[dict[str, object]]) -> str:
    """What is different about this group, not merely that something is.

    Kiro's `_describe_difference` names the offending fields and its docstring gives the reason:
    naming only the location leaves a user unable to tell **their own edit** from a Zikaron version
    change, and therefore unable to decide whether `--force` is the right answer. The settings
    refusal named only the trigger until a review pointed at that asymmetry.
    """
    commanded = _commands_in(group)
    wanted = [command for one in expected for command in _commands_in(one)]
    if commanded != wanted:
        return f"command is {commanded or 'absent'}, this install writes {wanted}"
    return "same command, but the entry differs (timeout, matcher, or an extra field)"


def _refuse_conflicting(
    existing: object,
    ours: dict[str, object],
    *,
    path: Path,
    key: str,
    force: bool,
) -> None:
    """Refuse when a key we own is already present with different content.

    The same rule kiro's merge applies to an `mcpServers` entry, for the same reason: a Zikaron
    entry that differs from what this install would write means **another install owns it**, whose
    absolute paths may point at a venv that no longer has Zikaron in it. Overwriting silently would
    hide that the user has two installs; the refusal names the entry and the flag that overrides it.

    Only the entries this install writes are compared. Anything else under the same key is the
    user's and is merged around, never inspected.

    Raises:
        InstallError: a Zikaron-owned entry differs and `--force` was not passed.
    """
    if force or not isinstance(existing, dict):
        return
    differing = sorted(
        name for name, value in ours.items() if name in existing and existing[name] != value
    )
    if not differing:
        return
    raise InstallError(
        f"{path} already carries {key} entries that differ from what this install would write "
        f"({', '.join(differing)}). {_ANOTHER_INSTALL}"
    )
