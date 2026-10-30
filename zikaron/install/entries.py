"""The JSON Zikaron adds to a harness configuration: hook entries, the MCP server, and the
definitions of the agents Zikaron ships.

`architecture.md` §"The install contract" is normative.

Dicts are the return type here and that is deliberate rather than a lapse from
`coding-standards.md` §2's types-not-dicts rule: these functions *are* the serialization boundary —
their output goes straight to `json.dump` into a file whose schema belongs to the harness, not to
us.
The typed values live on the input side (`Commands`, `HarnessSpec`), which is where a mistake would
otherwise be silent.
"""

import copy
import os
import shlex
import sysconfig
from pathlib import Path
from typing import Final, NamedTuple

from zikaron.guard.arguments import harness_arguments
from zikaron.guard.limits import TIMEOUT_SECONDS as GUARD_TIMEOUT_SECONDS
from zikaron.harness.spec import CLAUDE_CODE, KIRO, Harness, HarnessSpec, SearchReminder
from zikaron.hook.components import Components
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS
from zikaron.install.assets import (
    CLAUDE_CODE_FILE_READING,
    KIRO_FILE_READING,
    consolidator_prompt,
    identity_vocabulary,
)
from zikaron.install.code_knowledge import (
    CLAUDE_CODE_ORCHESTRATOR_PROMPT,
    CLAUDE_CODE_PLANNER_COMMAND,
    CLAUDE_CODE_SPAWN_INSTRUCTION,
    DOCUMENTER_AGENT_NAME,
    DOCUMENTER_DESCRIPTION,
    DOCUMENTER_EFFORT,
    DOCUMENTER_PROMPT,
    KIRO_ORCHESTRATOR_DESCRIPTION,
    KIRO_ORCHESTRATOR_PROMPT,
    KIRO_PLANNER_COMMAND,
    ORCHESTRATOR_AGENT_NAME,
    ORCHESTRATOR_DESCRIPTION,
    ORCHESTRATOR_EFFORT,
    orchestrator_prompt,
    with_write_policy,
)
from zikaron.install.code_knowledge import KIRO_SPAWN_INSTRUCTION as KIRO_DOCUMENTER_SPAWN
from zikaron.mcp.tool_names import CONSOLIDATOR_TOOLS, PRIMARY_TOOLS
from zikaron.service import paths

#: The `mcpServers` key, and therefore the `@zikaron` selector. One declaration, because the name
#: appears in places that must agree — the server map, `tools`, the `mcp` rule's `match`, and a
#: universal profile's `allowedTools` — and a mismatch in `tools` silently produces an agent with no
#: Zikaron tools at all (measured; see `TOOL_SELECTOR`).
MCP_SERVER_NAME: Final = "zikaron"

#: How an agent config selects this server's tools. **Configuring `mcpServers` is not sufficient**,
#: which was measured rather than inferred: an agent carrying the server entry and a `tools` list
#: that did not name it reported its available tools as `code, dummy, execute_bash, fs_read,
#: fs_write, glob, grep, todo_list, use_subagent` — the whole memory surface absent, with no warning
#: anywhere. `tools` selects; `mcpServers` only configures.
TOOL_SELECTOR: Final = f"@{MCP_SERVER_NAME}"

#: The consolidator's own config file name, and hence its agent name (kiro derives one from the
#: other). Named in `architecture.md`'s distribution table, so it is not ours to vary.
CONSOLIDATOR_AGENT_NAME: Final = "zikaron-consolidator"

_HOOK_SCRIPT: Final = "zikaron-hook"
_MCP_SCRIPT: Final = "zikaron-mcp"
_GUARD_SCRIPT: Final = "zikaron-guard"

#: The memory store's two kiro trigger names, **read from the seam rather than spelled again**. A
#: second copy here would drift: the harness-table drift guard covers spec↔design and nothing
#: covers spec↔installer, so a trigger renamed in the spec would move the *hook* (whose tests read
#: the spec) while the *installer* kept writing the old name — an installed config naming a trigger
#: the hook does not recognize, which fails as no output and exit 0.
KIRO_TRIGGERS: Final = (KIRO.spawn_trigger, KIRO.prompt_trigger)

#: The permission rule that lets an agent call this server's tools without asking. Under kiro's V3
#: engine a call no rule allows asks, and a headless run refuses every ask.
_MCP_RULE: Final[dict[str, object]] = {
    "capability": "mcp",
    "match": [f"{MCP_SERVER_NAME}/*"],
    "effect": "allow",
}

#: The rule that lets the primary agent load a skill without asking. Loading one runs nothing, and
#: `kiro-cli agent upgrade` derives exactly this rule from a V2 profile.
_SKILL_RULE: Final[dict[str, object]] = {"capability": "skill", "effect": "allow"}

#: The documenter's file grant, as rules: it reads its source and writes its document.
_FILE_RULES: Final[tuple[dict[str, object], ...]] = (
    {"capability": "fs_read", "effect": "allow"},
    {"capability": "fs_write", "effect": "allow"},
)

#: The orchestrator's grant, as rules: it reads the consolidator's config, runs the planner and
#: spawns documenters.
_ORCHESTRATOR_RULES: Final[tuple[dict[str, object], ...]] = (
    {"capability": "fs_read", "effect": "allow"},
    {"capability": "shell", "effect": "allow"},
    {"capability": "subagent", "effect": "allow"},
)

#: Where the consolidator's MCP client writes an over-large result under kiro, as a path rule names
#: it: the store lies under the scope directory, which under kiro is the directory kiro was launched
#: from, and that is what a rule's `./` names (`research/kiro-v3-probe.md` §25, §47).
_SPILL_RULE_PATH: Final = f"./{paths.spill_dir(paths.store_dir(Path())).as_posix()}/**"

#: The consolidator's read: allowed in the spill directory, and refused everywhere else. The deny is
#: what confines it, since a subagent's own allow rule grants nothing beyond the session's
#: (`research/kiro-v3-probe.md` §52, §53, §55).
_SPILL_READ_RULES: Final[tuple[dict[str, object], ...]] = (
    {"capability": "fs_read", "match": [_SPILL_RULE_PATH], "effect": "allow"},
    {"capability": "fs_read", "exclude": [_SPILL_RULE_PATH], "effect": "deny"},
)


def mcp_rule() -> dict[str, object]:
    """A fresh copy of the rule allowing every Zikaron tool."""
    return copy.deepcopy(_MCP_RULE)


def primary_rules() -> list[dict[str, object]]:
    """The rules a user's own agent profile gains: Zikaron's tools, then loading a skill."""
    return [mcp_rule(), copy.deepcopy(_SKILL_RULE)]


#: Shared by both harnesses' consolidator definitions, which is why it is a constant rather than a
#: literal inside either builder: it is the text a harness reads to decide the agent is relevant,
#: and two copies would let one harness's install drift into describing a different agent. It
#: states what D32 is about, no reach into search or fetch, and not the whole grant: the file read
#: the spill needs is disclosed in the grant itself and in the spill guidance that bounds it.
_CONSOLIDATOR_DESCRIPTION: Final = (
    "Consolidates Zikaron's memory journal into long-term records. Spawned by the "
    "zikaron-consolidate skill; carries the four consolidation verbs and no way to search or "
    "fetch memory."
)

#: Claude Code's start, prompt and subagent triggers, derived from the seam for the reason above.
#: `SubagentStart` has no kiro counterpart and is not optional: the write-policy-per-subagent path
#: sits behind it. Leaving it out would leave that path dead with nothing failing — no error, no
#: log line, just subagents that never see the policy. The `is not None` filter is a type narrowing
#: and not a real branch: this tuple is Claude Code's, and Claude Code has each of them.
_CLAUDE_TRIGGERS: Final = tuple(
    trigger
    for trigger in (
        CLAUDE_CODE.spawn_trigger,
        CLAUDE_CODE.prompt_trigger,
        CLAUDE_CODE.subagent_start_trigger,
    )
    if trigger is not None
)

#: The two start triggers, whose shared entry carries the `--components` selection.
CLAUDE_START_TRIGGERS: Final = (_CLAUDE_TRIGGERS[0], _CLAUDE_TRIGGERS[2])

#: The guards' hook groups on each harness, read from the seam for the same reason: Claude Code's
#: command hook and re-read nudge, and kiro's command hook. The filters are type narrowings, since
#: both harnesses offer the guards.
_CLAUDE_GUARD_HOOKS: Final = tuple(
    hook
    for guards in (CLAUDE_CODE.guards,)
    if guards is not None
    for hook in (guards.command, guards.reread)
    if hook is not None
)
_KIRO_GUARD_HOOKS: Final = tuple(
    hook
    for guards in (KIRO.guards,)
    if guards is not None
    for hook in (guards.command, guards.reread)
    if hook is not None
)

#: The search reminder's hook, read from the seam the same way, with the same narrowing.
_CLAUDE_REMINDERS: Final = tuple(
    reminder for reminder in (CLAUDE_CODE.search_reminder,) if reminder is not None
)


class Commands(NamedTuple):
    """The absolute command paths the shipped entries name.

    Resolved from the running interpreter rather than accepted as strings, so an install cannot
    write a `command` pointing at an interpreter that does not have Zikaron in it — which would fail
    at hook time, in a subprocess whose stderr the harness does not surface.
    """

    hook: Path
    mcp: Path

    @property
    def guard(self) -> Path:
        """`zikaron-guard`, beside `zikaron-hook`: every console script lands in one directory."""
        return self.hook.with_name(_GUARD_SCRIPT)

    @classmethod
    def from_this_interpreter(cls) -> "Commands":
        """`<venv>/bin/zikaron-hook` and `<venv>/bin/zikaron-mcp` for the interpreter running this.

        `sysconfig.get_path("scripts")` is the same directory `pip install` put the console scripts
        in, so this resolves correctly under a venv, a `--user` install or a system install without
        needing to know which of the three it is.
        """
        scripts = Path(sysconfig.get_path("scripts"))
        return cls(hook=scripts / _HOOK_SCRIPT, mcp=scripts / _MCP_SCRIPT)

    def missing(self, components: Components = Components.MEMORY) -> tuple[Path, ...]:
        """Whichever of the scripts `components` needs is not an executable file, in path order.

        `zikaron-hook` is needed by every selection, since the start entries carry the guards'
        start text too; `zikaron-mcp` by the memory store, `zikaron-guard` by the guards.

        Checked rather than assumed because the failure is otherwise invisible until a hook fires:
        installing from a source checkout without `pip install` leaves them absent, and a hook whose
        `command` does not exist produces no output on the one channel the harness reads.

        **Executability, not merely existence.** A console script that exists without the execute
        bit — a file copied out of a wheel by hand, an install onto a filesystem mounted
        `noexec` — fails at exactly the moment this check exists to protect, and `is_file()` alone
        would pass it.
        """
        needed = (
            self.hook,
            *([self.mcp] if components.memory else []),
            *([self.guard] if components.guards else []),
        )
        return tuple(path for path in needed if not (path.is_file() and os.access(path, os.X_OK)))


def hooks_array(
    commands: Commands, components: Components = Components.MEMORY
) -> list[dict[str, object]]:
    """Kiro's `hooks` entries for one selection, the memory store's before the guards': a flat
    list carrying its own `trigger` per entry, which is V3's form.

    The memory store's two point at `zikaron-hook`, which dispatches on `hook_event_name` from its
    own stdin payload (`zikaron/hook/main.py`). The guards have a start entry of their own,
    `zikaron-hook --components guards`, because kiro cuts each hook's output at its budget and the
    policy and the guard start text together would not fit one (`design/guards.md` §5); and
    `zikaron-guard`, told it is kiro's, on the shell tool. No entry carries a size field: kiro cuts
    a hook's output at its own limit whatever an entry says (`design/harness.md` §"Injection
    budgets").
    """
    hook = hook_command_string(commands.hook, KIRO)
    entries: list[dict[str, object]] = []
    if components.memory:
        entries.extend(
            _kiro_entry(f"zikaron-{trigger}", trigger, hook, HOOK_TIMEOUT_SECONDS)
            for trigger in KIRO_TRIGGERS
        )
    if components.guards:
        start = KIRO.spawn_trigger
        guards_start = " ".join((hook, *Components.GUARDS.arguments))
        entries.append(
            _kiro_entry(f"zikaron-guards-{start}", start, guards_start, HOOK_TIMEOUT_SECONDS)
        )
        guard = " ".join(
            (hook_command_string(commands.guard, KIRO), *harness_arguments(Harness.KIRO))
        )
        for group in _KIRO_GUARD_HOOKS:
            entry = _kiro_entry(
                f"zikaron-guards-{group.trigger}", group.trigger, guard, GUARD_TIMEOUT_SECONDS
            )
            entries.append({**entry, "matcher": group.matcher})
    return entries


def _kiro_entry(name: str, trigger: str, command: str, timeout: int) -> dict[str, object]:
    return {
        "name": name,
        "trigger": trigger,
        "action": {"type": "command", "command": command},
        "timeout": timeout,
    }


def hook_command_string(hook_command: Path, spec: HarnessSpec) -> str:
    """The `command` string for a hook entry: the harness's prefix, then the executable path,
    **shell-quoted**.

    Measured, not inferred: this field is run through a shell. An unquoted
    `/home/me/My Projects/.venv/bin/zikaron-hook` produced
    `/bin/bash: line 1: /home/me/My: No such file or directory` and exit 127 from the real harness,
    with the hook contributing nothing — no write policy on spawn, no memories on a prompt — while
    the install itself had exited 0, because the path *is* an executable file and every preflight
    passed.
    A single-quoted path was then measured to run correctly.

    So a project or venv directory containing a space is enough to break the whole install, with no
    attacker and nothing exotic. `shlex.quote` is applied here rather than at each call site so
    every entry is quoted by construction.

    `mcpServers`' own `command` is deliberately **not** quoted: that field takes a program and a
    separate `args` array, which is exec-style rather than shell-style, and quoting it would make
    the harness look for a file whose name contains the quotes.
    """
    return spec.hook_command_prefix + shlex.quote(str(hook_command))


#: The `.mcp.json` key that exempts one server from Claude Code's deferred tool loading.
#:
#: **Without it a description arrives late, per verb, or not at all.** Claude Code defers MCP tools
#: when the tool list is crowded: they are listed by *name* with schemas unloaded, and a description
#: comes only when the agent loads that verb — which a production transcript shows it doing one verb
#: at a time, just before first use. The write-time rules M32 and M33 put in
#: `zikaron_memory_remember`'s description ride that channel
#: (`design/harness.md` §"MCP tools may arrive deferred").
#:
#: **Per-server, which is why it is the installer's to write** rather than a setting asking the user
#: to turn deferral off project-wide. That section states the alternative and why it was rejected.
ALWAYS_LOAD_KEY: Final = "alwaysLoad"

#: The fields of a `.mcp.json` server entry that say **which install** wrote it: an absolute
#: interpreter path and the `--mode`. Anything else is a key this installer adds and may add more
#: of, so a merge compares only these — see `ownership.refuse_conflicting`.
MCP_OWNERSHIP_FIELDS: Final = ("command", "args")


def server_entry(commands: Commands, *, mode: str, always_load: bool = False) -> dict[str, object]:
    """One server entry. The single declaration of an entry's shape, so no caller rebuilds it."""
    entry: dict[str, object] = {"command": str(commands.mcp), "args": ["--mode", mode]}
    if always_load:
        entry[ALWAYS_LOAD_KEY] = True
    return entry


def mcp_servers_value(commands: Commands, *, mode: str) -> dict[str, object]:
    """The `mcpServers` entry for one mode: `primary` for a user's own agent, `consolidator` for
    ours. **No `alwaysLoad`** — the key is Claude Code's `.mcp.json` vocabulary and kiro's agent
    config has no such field; nothing is known to defer there either."""
    return {MCP_SERVER_NAME: server_entry(commands, mode=mode)}


def claude_tool_vocabulary() -> dict[str, str]:
    """Bare tool name → the `mcp__<server>__<tool>` form Claude Code serves and shows the model.

    Built from the two tool sets and the two server names rather than listed, so a tool added to
    `zikaron.mcp.tool_names` is covered here automatically and a *renamed* one fails
    `assets._guard_known_tools` loudly instead of shipping a name nothing serves.
    """
    return {
        **{name: f"mcp__{MCP_SERVER_NAME}__{name}" for name in PRIMARY_TOOLS},
        **{name: f"mcp__{CONSOLIDATOR_AGENT_NAME}__{name}" for name in CONSOLIDATOR_TOOLS},
    }


def claude_hooks_value(
    commands: Commands,
    components: Components = Components.MEMORY,
    *,
    start: Components | None = None,
) -> dict[str, list[dict[str, object]]]:
    """The `hooks` value for `.claude/settings.local.json` for one selection: its groups per
    trigger, the memory store's before the guards' on a trigger both write.

    Every selection writes the two start triggers, whose `zikaron-hook` command carries `start` —
    the selection those entries emit start text for, `components` unless the caller widens it to a
    union with what is already installed (`design/guards.md` §5). The memory store adds the
    prompt trigger and the search reminder's group (`design/code-knowledge.md` §6); the guards add
    their two groups, each with its matcher.

    The doubled nesting is the harness's own and was confirmed by running it: an event maps to a
    list of *groups*, each carrying an optional `matcher` and its own inner `hooks` list
    (`research/claude-code-installer-probe.md` §1). The start and prompt groups carry no `matcher`
    — `UserPromptSubmit` accepts none at all, and the start triggers must fire for every session
    and every subagent, which is what omitting it means.

    `timeout` is **seconds** here, measured rather than assumed. `command` is a shell command line,
    measured (`research/claude-code-hook-command-shell-probe.md`), so the path is shell-quoted: an
    unquoted path containing a space does not run at all.
    """
    start_selection = components if start is None else start
    start_group = _claude_group(commands.hook, start_selection.arguments, HOOK_TIMEOUT_SECONDS)
    groups: dict[str, list[dict[str, object]]] = {}
    for trigger in _CLAUDE_TRIGGERS:
        if trigger in CLAUDE_START_TRIGGERS:
            groups[trigger] = [start_group]
        elif components.memory:
            groups[trigger] = [_claude_group(commands.hook, (), HOOK_TIMEOUT_SECONDS)]
    for reminder in _CLAUDE_REMINDERS if components.memory else ():
        groups.setdefault(reminder.trigger, []).append(_reminder_group(commands.hook, reminder))
    for hook in _CLAUDE_GUARD_HOOKS if components.guards else ():
        guard = _claude_group(commands.guard, (), GUARD_TIMEOUT_SECONDS)
        groups.setdefault(hook.trigger, []).append({"matcher": hook.matcher, **guard})
    return groups


def _claude_group(script: Path, arguments: tuple[str, ...], timeout: int) -> dict[str, object]:
    command = " ".join((hook_command_string(script, CLAUDE_CODE), *arguments))
    return {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}


def _reminder_group(script: Path, reminder: SearchReminder) -> dict[str, object]:
    """The reminder's one group: both arms' tools in its matcher, and a handler per `if` filter,
    each a string, since a list of them is never matched (`research/m40-4-hook-probes.md`)."""
    command = hook_command_string(script, CLAUDE_CODE)
    return {
        "matcher": reminder.matcher,
        "hooks": [
            {
                "type": "command",
                "if": condition,
                "command": command,
                "timeout": HOOK_TIMEOUT_SECONDS,
            }
            for condition in (*reminder.files.filters, *reminder.shell.filters)
        ],
    }


def claude_mcp_servers_value(commands: Commands) -> dict[str, object]:
    """Both servers, for `.mcp.json`.

    Two entries rather than kiro's one, and not a stylistic difference: a server must be registered
    **session-wide** to be reachable by any subagent at all, so the consolidator's server cannot
    live inside the consolidator's own definition the way it does under kiro. That is the same fact
    that makes D32's other half unenforceable here, reported by the installer rather than hidden.

    **Both carry `alwaysLoad`, and it stays on the consolidator even though nothing needs it
    today — operator decision 2026-09-29, a defensive default rather than a reading of the
    measurement.** `design/harness.md` §"MCP tools may arrive deferred" carries the measurement and
    why it is not grounds to drop the key.
    """
    return {
        MCP_SERVER_NAME: server_entry(commands, mode="primary", always_load=True),
        CONSOLIDATOR_AGENT_NAME: server_entry(commands, mode="consolidator", always_load=True),
    }


def consolidator_agent_markdown(commands: Commands, *, model: str) -> str:
    """The whole `.claude/agents/zikaron-consolidator.md` — YAML frontmatter, prompt as body.

    Three things differ from kiro's JSON and each is measured rather than translated:

    - **`tools` is a whole-server wildcard**, not the four verbs by name. An unrecognised tool name
      in frontmatter refuses the spawn outright with "would be spawned with zero tools"
      (`claude-code-harness-probe.md` §6), so an explicit list is a second declaration of a fact
      `mcp/consolidator.py` owns whose drift mode is a consolidator that will not start. The
      wildcard was measured to grant that server's tools and to **exclude** the primary server's
      `search`/`fetch` (`installer-probe` §7), which is the whole of what D7 needs.
    - **No `mcpServers` block.** A frontmatter `mcpServers:` key is silently ignored (probe §6);
      registration is session-wide in `.mcp.json` or it does not happen.
    - **The model may be an alias**, because this harness refuses an unknown id loudly at spawn
      rather than substituting its default. `harness.md` §"The consolidator's model".
    - **`Read` is granted from the one seam field that also decides whether the client writes an
      over-large result to a file at all.** One field for both, because the mismatches are what
      hurt: the tool without the file widens this agent's reach for nothing, and the file without
      the tool hands it a path it cannot open. The prompt's two fills follow the same field, so a
      config and a prompt can never disagree about which tools exist.

    It widens D32, which withholds retrieval so that "code picks the candidates" is enforced
    mechanically rather than by prose, and here the widening is bounded by prose alone: this
    harness has no per-subagent path rule, so `Read` is grantable but not scopable. A `PreToolUse`
    hook in this agent's own frontmatter is the mechanical version if that ever needs to be more
    than a convention.

    `commands` is unused and stays in the signature deliberately: it keeps this builder's shape
    identical to `consolidator_agent_config`'s, so the two targets call one interface, and the fact
    that Claude Code needs no per-agent server registration is visible as an *unused argument* here
    rather than as an asymmetry the caller has to know about.
    """
    del commands
    frontmatter = "\n".join(
        (
            "---",
            f"name: {CONSOLIDATOR_AGENT_NAME}",
            f"description: {_CONSOLIDATOR_DESCRIPTION}",
            f"model: {model}",
            "tools:",
            f"  - mcp__{CONSOLIDATOR_AGENT_NAME}",
            *(["  - Read"] if CLAUDE_CODE.consolidator_can_read_files else []),
            "---",
        )
    )
    body = consolidator_prompt(
        claude_tool_vocabulary(),
        file_reading=CLAUDE_CODE_FILE_READING.naming(CLAUDE_CODE.tool_ids.read)
        if CLAUDE_CODE.consolidator_can_read_files
        else None,
    )
    return f"{frontmatter}\n\n{body}\n"


def consolidator_agent_config(commands: Commands, *, model: str) -> dict[str, object]:
    """The whole `zikaron-consolidator.json`.

    Every field is a decision `architecture.md` §"The install contract" states, and four are worth
    re-reading here because their absence would be invisible:

    - `tools` is `@zikaron` and `read` — and `@zikaron` has to be there at all, since `mcpServers`
      configures a server while `tools` is what selects its tools. No `write` or `shell`: the
      design's claim is that *code* selects the candidates.
    - `read` is for a spilled result, and its rules confine it there: one allows reading the spill
      directory, and a deny excluding that directory refuses every other read and the searches,
      since a subagent's own allow rule grants nothing beyond the session's
      (`research/kiro-v3-probe.md` §52, §53, §55). A consolidator that can read the repository can
      wander outside the group it was handed.
    - `permissions.rules` allows the server's tools, because an available-but-not-allowed tool
      asks, and headless V3 refuses every ask. Under a session, a spawned agent may do what the
      session's rules allow, less what any rule in the chain denies, so its own allow rules decide
      only where it runs as a session of its own (`design/harness.md` §Subagents). It carries no V2
      trust field, so V3 reads it as a profile of its own engine.
    - there is **no** `hooks` key: a subagent's own hooks never fire, and its policy is this prompt.
    """
    return {
        "name": CONSOLIDATOR_AGENT_NAME,
        "description": _CONSOLIDATOR_DESCRIPTION,
        "model": model,
        "prompt": consolidator_prompt(
            identity_vocabulary(),
            file_reading=KIRO_FILE_READING.naming(KIRO.tool_ids.read)
            if KIRO.consolidator_can_read_files
            else None,
        ),
        "tools": sorted([TOOL_SELECTOR, *(["read"] if KIRO.consolidator_can_read_files else [])]),
        "permissions": {
            "rules": [
                mcp_rule(),
                *(copy.deepcopy(_SPILL_READ_RULES) if KIRO.consolidator_can_read_files else ()),
            ]
        },
        "mcpServers": mcp_servers_value(commands, mode="consolidator"),
    }


def documenter_agent_markdown(*, model: str) -> str:
    """The whole `.claude/agents/zikaron-documenter.md`: frontmatter, then the prompt as body.

    Its `tools:` is this harness's file tools and the primary server (`design/code-knowledge.md`
    §5.4) — no shell, no spawn tool — and its effort is fixed at `DOCUMENTER_EFFORT`.
    """
    definition = _ClaudeAgent(
        name=DOCUMENTER_AGENT_NAME,
        description=DOCUMENTER_DESCRIPTION,
        effort=DOCUMENTER_EFFORT,
        tools=(*CLAUDE_CODE.file_tools, f"mcp__{MCP_SERVER_NAME}"),
        prompt=DOCUMENTER_PROMPT,
    )
    return definition.markdown(model=model)


def orchestrator_agent_markdown(*, model: str) -> str:
    """The whole `.claude/agents/zikaron-code-orchestrator.md`, the agent the code documentation
    skill has the session spawn, its prompt followed by the loop (`design/code-knowledge.md` §5.2,
    §5.4).

    Its grant spawns, runs the planner, reads `.mcp.json` and reaches the primary server, and holds
    none of the editing tools: the planner removes and moves documents and the documenters write
    them. `Bash` could write a file, and the prompt is what says it does not.
    `Agent(zikaron-documenter)` would narrow nothing, since a subagent's definition ignores the type
    list. It runs in the background whatever its spawner asks, and its effort is fixed at
    `ORCHESTRATOR_EFFORT`.
    """
    definition = _ClaudeAgent(
        name=ORCHESTRATOR_AGENT_NAME,
        description=ORCHESTRATOR_DESCRIPTION,
        effort=ORCHESTRATOR_EFFORT,
        tools=("Agent", "Bash", "Read", f"mcp__{MCP_SERVER_NAME}"),
        prompt=orchestrator_prompt(
            claude_tool_vocabulary(),
            own_prompt=CLAUDE_CODE_ORCHESTRATOR_PROMPT,
            spawn_instruction=CLAUDE_CODE_SPAWN_INSTRUCTION,
            planner_command=CLAUDE_CODE_PLANNER_COMMAND,
        ),
        background=True,
    )
    return definition.markdown(model=model)


class _ClaudeAgent(NamedTuple):
    """What a code-knowledge agent's Claude Code definition fixes; the model is the install's."""

    name: str
    description: str
    effort: str
    tools: tuple[str, ...]
    prompt: str
    background: bool = False

    def markdown(self, *, model: str) -> str:
        """The definition: YAML frontmatter, then the prompt as body."""
        frontmatter = "\n".join(
            (
                "---",
                f"name: {self.name}",
                f"description: {self.description}",
                f"model: {model}",
                f"effort: {self.effort}",
                *(("background: true",) if self.background else ()),
                "tools:",
                *(f"  - {tool}" for tool in self.tools),
                "---",
            )
        )
        return f"{frontmatter}\n\n{self.prompt}\n"


def documenter_agent_config(commands: Commands, *, model: str) -> dict[str, object]:
    """The whole `.kiro/agents/zikaron-documenter.json`.

    `tools` is the file tools and `@zikaron`, and `permissions.rules` allows reading, writing and
    Zikaron's tools, as the consolidator's allows its own. Spawned, it may do only what the
    session's rules allow, which the install reports rather than grants (`design/harness.md`
    §Subagents), so its own rules decide where it runs as a session of its own. The primary server
    is configured here, since a kiro agent config carries its own `mcpServers`. No `hooks`: a
    subagent's own hooks never fire. Its prompt ends with the write policy, and `effortLevel` sets
    its effort (`research/kiro-v3-probe.md` §39).

    `tools` is sorted: with these selectors in any other order, `kiro-cli agent upgrade` calls the
    profile out of sync, the class kiro documents the TUI answering by a rebuild
    (`research/kiro-v3-probe.md` §26), which no measured launch or reselection triggered (§30).
    """
    return {
        "name": DOCUMENTER_AGENT_NAME,
        "description": DOCUMENTER_DESCRIPTION,
        "model": model,
        "effortLevel": DOCUMENTER_EFFORT,
        "prompt": with_write_policy(DOCUMENTER_PROMPT),
        "tools": sorted([*KIRO.file_tools, TOOL_SELECTOR]),
        "permissions": {"rules": [*copy.deepcopy(_FILE_RULES), mcp_rule()]},
        "mcpServers": mcp_servers_value(commands, mode="primary"),
    }


def orchestrator_agent_config(commands: Commands, *, model: str) -> dict[str, object]:
    """The whole `.kiro/agents/zikaron-code-orchestrator.json`, the agent the code documentation
    skill has the session spawn and wait for, its prompt followed by the loop and the write policy
    (`design/code-knowledge.md` §5.2, §5.4).

    Its `tools` read the consolidator's config, run the planner, spawn documenters and reach the
    primary server, and select no `write`: the planner removes and moves documents and the
    documenters write them. Its rules allow those tools and carry no `fs_write`, since a session
    allowing `fs_write` over the documents directory reaches a documenter through it
    (`research/kiro-v3-probe.md` §54). No `hooks`, for the documenter's reason; `tools` sorted,
    for the same.
    """
    return {
        "name": ORCHESTRATOR_AGENT_NAME,
        "description": KIRO_ORCHESTRATOR_DESCRIPTION,
        "model": model,
        "effortLevel": ORCHESTRATOR_EFFORT,
        "prompt": with_write_policy(
            orchestrator_prompt(
                identity_vocabulary(),
                own_prompt=KIRO_ORCHESTRATOR_PROMPT,
                spawn_instruction=KIRO_DOCUMENTER_SPAWN,
                planner_command=KIRO_PLANNER_COMMAND,
            )
        ),
        "tools": sorted([TOOL_SELECTOR, "read", "shell", "subagent"]),
        "permissions": {"rules": [*copy.deepcopy(_ORCHESTRATOR_RULES), mcp_rule()]},
        "mcpServers": mcp_servers_value(commands, mode="primary"),
    }
