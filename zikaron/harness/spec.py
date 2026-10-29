"""`design/harness.md` §"The table", as data.

One `HarnessSpec` per supported harness, and every harness-varying value either a field on it or
derived from those fields. A test reads the design document itself and asserts this table against
it, so an edit on either side fails rather than drifting — the arrangement `coding-standards.md` §2
requires for anything the design states as a table.

**The trigger vocabulary is derived from the specs rather than written a second time**, as the
union of both specs' own trigger fields: a name either is some harness's stated trigger or is not a
trigger at all, and there is no third place for the two to disagree.
"""

import enum
import os
from pathlib import Path
from typing import Final, NamedTuple


class Harness(enum.Enum):
    """The supported harnesses. A closed set: detection returns one of these and never `None`,
    since kiro is the fallback rather than a third "unknown" state.
    """

    KIRO = "kiro"
    CLAUDE_CODE = "claude-code"


class HookEvent(enum.Enum):
    """What a hook invocation *means*, independent of which harness's trigger name delivered it.

    Trigger names normalize onto the members below, each name to the one member it means. `SPAWN`
    and `PROMPT` exist under both harnesses; `SUBAGENT_START` and `SEARCH` arrive only under Claude
    Code, whose payload carries the `agent_type` that makes a per-agent rule expressible at all.

    `SubagentStop` is deliberately absent. It has no work to do: the only path that wanted it
    existed to record which concrete model a consolidation run used, and that is unnecessary
    because the harness refuses an unknown model id at spawn, so the configured id can simply be
    trusted. Its absence is what keeps the `event` log's own rule — pushes come from the hook,
    writes from the MCP client — true, since the hook has no write path at all.
    """

    SPAWN = "spawn"
    PROMPT = "prompt"
    SUBAGENT_START = "subagent_start"
    #: A search of the project's files has run (`design/code-knowledge.md` §6).
    SEARCH = "search"


class OutputChannel(enum.Enum):
    """How a hook's output reaches a model. **The two are not interchangeable per event**, which is
    measured rather than assumed: plain exit-0 stdout from a `SubagentStart` hook reaches nobody —
    not the subagent, not the parent — while the same text under
    `hookSpecificOutput.additionalContext` reaches the subagent verbatim and stays invisible to the
    parent, which is the isolation write-policy delivery wants.
    """

    STDOUT = "stdout"
    ADDITIONAL_CONTEXT = "additional_context"


class GuardHook(NamedTuple):
    """One guard hook group: its trigger and its matcher (`design/guards.md` §5).

    The matcher is a `|`-joined list of bare tool names, never a regex, because the guard reads the
    tools it judges by splitting it — so widening a matcher widens what the guard judges, and the
    tool names live once.
    """

    trigger: str
    matcher: str

    @property
    def tools(self) -> frozenset[str]:
        """The tool names the matcher selects."""
        return frozenset(self.matcher.split("|"))


class Guards(NamedTuple):
    """The two guard hook groups: the command hook, which carries the find-replace guard and the
    self-match rule, and the re-read nudge."""

    command: GuardHook
    reread: GuardHook


class SearchArm(NamedTuple):
    """One kind of search the reminder follows: the tools its matcher names, and the `if` filter
    each of its handlers carries, one handler per filter."""

    matcher: str
    filters: tuple[str, ...]

    @property
    def tools(self) -> frozenset[str]:
        """The tool names the matcher selects."""
        return frozenset(self.matcher.split("|"))


class SearchReminder(NamedTuple):
    """The reminder's hook (`design/code-knowledge.md` §6): its trigger and its two arms — `files`,
    the search tools whose `path` is what they searched, and `shell`, whose `command` is read for a
    search command. Installed as one group whose matcher joins both arms'."""

    trigger: str
    files: SearchArm
    shell: SearchArm

    @property
    def matcher(self) -> str:
        """The one group's matcher."""
        return f"{self.files.matcher}|{self.shell.matcher}"


class HarnessSpec(NamedTuple):
    """Everything that varies between harnesses, for one harness.

    A `NamedTuple` rather than a frozen dataclass purely for import cost (see the package
    docstring); it is immutable and typed either way.
    """

    harness: Harness
    marker_variable: str | None
    session_variable: str
    #: Whether the session variable reaches hooks and the agent's shell but no MCP server, so that
    #: the hook relays its session's label to the MCP client through the agent server both share
    #: (`design/harness.md` §"The session relay").
    session_variable_misses_mcp_server: bool
    spawn_trigger: str
    prompt_trigger: str
    subagent_start_trigger: str | None
    #: The characters a hook's output may run to before the harness cuts it, counted as UTF-16
    #: code units.
    injection_budget: int
    #: What opens every hook command, before the quoted hook path.
    hook_command_prefix: str
    consolidator_model: str
    #: The code documenter's default model.
    documenter_model: str
    harness_binary: str
    #: The variable naming the directory this harness considers "the project", or `None` where the
    #: harness exports none. Read by `store_scope_dir` below; see its docstring for why.
    project_dir_variable: str | None
    #: Whether this harness's consolidator subagent can be granted a tool that reads a file, and
    #: therefore whether an over-large tool result may be written to one instead of returned.
    #:
    #: One field for both, deliberately, because they are one capability and the mismatches are
    #: what hurt: granting the tool without spilling widens the consolidator's reach for nothing,
    #: and spilling without granting it hands the model a path it cannot open, which is the same
    #: stall this was built to end. Where this is false the client returns every payload inline,
    #: the consolidator config gains no tool, and its prompt gains no text about files.
    consolidator_can_read_files: bool
    #: The guards' triggers and matchers, or `None` where the guards are not offered — which is
    #: what the installer's refusal of them reads.
    guards: Guards | None
    #: The search reminder's hook, or `None` where a tool event's output has no documented path to
    #: the model, in which case a memory install writes no such hook.
    search_reminder: SearchReminder | None
    #: The documenter's whole grant: reading, searching and writing files, spelled as this harness
    #: names its own tools. The only place either harness's file tools are named, so the
    #: documenter's prompt can say *read* and *write* and stay true on both
    #: (`design/code-knowledge.md` §5.4).
    file_tools: tuple[str, ...]

    def exceeds_injection_budget(self, text: str) -> bool:
        """Whether `text` is larger than this harness will actually inject.

        Characters are counted as **UTF-16 code units**, not as `len(text)`. The two agree for
        every character in the Basic Multilingual Plane and differ by a factor of two for astral
        ones. Claude Code was **measured** to count units: 6,000 astral code points, 12,000 units,
        are cut under its 10,000 cap while 4,600 arrive whole
        (`research/claude-code-dogfood-checkpoint.md` §3), so `len(text)` would pass a block the
        harness then cuts. Which of the two kiro counts is unmeasured, and units bound either.

        `surrogatepass` keeps this total. A lone surrogate is legal in a Python string decoded from
        JSON and would otherwise raise out of a bound check whose callers treat it as a plain
        predicate.
        """
        measured = len(text.encode("utf-16-le", errors="surrogatepass")) // 2
        return measured > self.injection_budget

    def store_scope_dir(self, fallback: Path) -> Path:
        """The directory D17 scopes a store to — **the one function both clients must call**.

        The defect this exists to end was two implementations of one decision. `zikaron-hook` keyed
        the store on the harness-supplied payload `cwd`, which under Claude Code follows the
        agent's own `cd`; `zikaron-mcp` keyed it on `Path.cwd()` of a process spawned once at
        session start, which never moves. They agreed only while nobody changed directory, and
        diverged silently when anyone did: push read a freshly-created empty store while pull kept
        answering from the real one, and nothing anywhere said so. Measured on one live session:
        **39 cwd transitions**, a store created under a log directory, and 20 pushes in another
        session returning nothing across two hours
        (`research/claude-code-dogfood-checkpoint.md` §"Store scoping").

        Two rungs, deliberately the same shape as the session-label ladder: read this harness's own
        project variable, and fall back to `fallback` when the harness exports none or the value is
        unusable. Claude Code's variable is measured present in **both** clients' processes — the
        hook's, and all six MCP server starts in `spikes/claude-code-harness/mcp.log` — which is
        what the agreement property actually rests on, since one client reading it and the other
        not would reproduce the split this exists to close.

        **The fallback is not a degraded mode for kiro** — kiro exports no such variable (measured:
        six `KIRO_*` names across 270 probe records, none spatial) and appears not to need one,
        because its shell restores the working directory rather than persisting it. That last
        clause is an operator observation plus twelve days and ~8,000 events producing no stray
        store; it is **not measured**, and `tests/test_harness_store_scope.py` pins the dependency
        at the point where it would have to change. Kiro's rung is exactly its behaviour before this
        function existed.

        **Refusing a value is narrower than it sounds, and the nesting case is not covered by it.**
        A value that does not name an existing absolute directory is refused in favour of
        `fallback`. But the case `design/harness.md` §"The nesting limit" documents — a process
        tree inheriting an enclosing Claude Code session's variables — inherits a directory that
        *does* exist, so `is_dir()` passes and **this function adopts it**. That is a regression
        this change introduces, stated rather than hidden: before it, a nested kiro session's MCP
        client keyed the correct *inner* store through `Path.cwd()`; now, having misdetected the
        harness from the inherited marker, it reads and writes the **enclosing project's** store —
        its `remember` landing in the outer store and its `search` answering from the outer
        project's lore. The hook side is partly guarded by the misdetection tripwire; the MCP write
        path is not. The root cause is misdetection, and the remedy `detect.py` records
        repairs the **hook only** — it turns on the hook's own payload `session_id`, which an MCP
        client does not have — so the MCP half has a named cost and no named repair. This
        function is deliberately not the place to invent one.

        **When a value *is* refused, the clients diverge again**, because they fall back to
        different inputs — the hook to the harness's wandering payload `cwd`, the MCP client to its
        fixed spawn cwd, `zikaron knowledge` to whichever directory the command was typed in. So
        the refusal is safe for the store's *location* and not for the clients' *agreement*, in
        exactly the pathological case (a deleted project directory, a container boundary) where
        nobody is watching.
        """
        return self.named_project_dir() or fallback

    def named_project_dir(self) -> Path | None:
        """This harness's exported project directory, or `None` where there is no usable one.

        One predicate rather than two, so a caller that needs to know *whether the variable
        answered* cannot disagree with `store_scope_dir` about it — comparing the resolved
        directory against the fallback is not that question, since a variable naming exactly the
        fallback answers while looking as though it did not.
        """
        if self.project_dir_variable is None:
            return None
        named = os.environ.get(self.project_dir_variable)
        if not named:
            return None
        candidate = Path(named)
        # Absolute as well as existing: a *relative* value would be resolved against each
        # client's own process cwd, which is precisely the pair of different directories this
        # function exists to collapse. The harness sets an absolute path; this costs one call.
        return candidate if candidate.is_absolute() and candidate.is_dir() else None


#: kiro-cli's V3 engine, as `research/kiro-v3-probe.md` measured it on 2.35.1.
KIRO: Final = HarnessSpec(
    harness=Harness.KIRO,
    marker_variable=None,
    session_variable="KIRO_SESSION_ID",
    session_variable_misses_mcp_server=True,
    spawn_trigger="SessionStart",
    prompt_trigger="UserPromptSubmit",
    # No hook fires for a subagent session at all, so a subagent has no trigger of its own here.
    subagent_start_trigger=None,
    # The cut is the harness's own; neither spelling of an entry's size field moves it.
    injection_budget=3_000,
    # `exec` makes the agent server the hook's parent, as it is the MCP server's, which is what the
    # session relay is keyed on.
    hook_command_prefix="exec ",
    # Pinned to a concrete id: an id this harness does not recognize is documented to be replaced
    # by its default with no more than a warning, so the installer validates membership against
    # `chat --list-models` — a check an alias would fail, since that command lists ids.
    consolidator_model="claude-sonnet-5",
    documenter_model="claude-sonnet-5",
    harness_binary="kiro-cli",
    # Measured, not assumed: of the six `KIRO_*` variables across 270 hook and MCP server records,
    # none names a workspace or project directory.
    project_dir_variable=None,
    # What this harness does with an over-large MCP result is **unmeasured**. Rather than invent a
    # remedy for behaviour nobody has observed, every payload is returned inline here exactly as
    # before, and the consolidator keeps the four verbs and nothing else.
    consolidator_can_read_files=False,
    # Not offered: a `PostToolUse` hook's output was measured not to reach the model.
    guards=None,
    search_reminder=None,
    file_tools=("read", "grep", "glob", "write"),
)

CLAUDE_CODE: Final = HarnessSpec(
    harness=Harness.CLAUDE_CODE,
    marker_variable="CLAUDECODE",
    session_variable="CLAUDE_CODE_SESSION_ID",
    session_variable_misses_mcp_server=False,
    spawn_trigger="SessionStart",
    prompt_trigger="UserPromptSubmit",
    subagent_start_trigger="SubagentStart",
    injection_budget=10_000,
    hook_command_prefix="",
    # An alias, and safely so: this harness refuses an unknown id loudly at spawn, so both rules
    # `architecture.md` §"The consolidator's model" states are satisfied — the field is present
    # explicitly, and the harness serves exactly what was asked for. A *pinned* default would rot
    # instead: an install a year from now would ship last year's id, and once that id retires the
    # consolidator fails at spawn. Experiments pin; the shipped default does not have to.
    consolidator_model="sonnet",
    documenter_model="haiku",
    harness_binary="claude",
    project_dir_variable="CLAUDE_PROJECT_DIR",
    # Measured: an over-large result is replaced wholesale by an error notice, and the harness's
    # own spill file is one line of JSON that `Read` cannot paginate. A file this project writes
    # can be paginated, so the capability is real — `research/claude-code-mcp-result-truncation.md`.
    consolidator_can_read_files=True,
    guards=Guards(
        command=GuardHook(trigger="PreToolUse", matcher="Bash|Monitor"),
        reread=GuardHook(trigger="PostToolUse", matcher="Edit|MultiEdit|NotebookEdit|Write"),
    ),
    # As measured: an `if` is a string, one per handler — a list is never matched — and a leading
    # wildcard reaches `egrep`, `fgrep` and both spellings of `git grep`
    # (`research/m40-4-hook-probes.md`).
    search_reminder=SearchReminder(
        trigger="PostToolUse",
        files=SearchArm(matcher="Grep|Glob", filters=("Grep", "Glob")),
        shell=SearchArm(matcher="Bash", filters=("Bash(*grep *)", "Bash(rg *)")),
    ),
    file_tools=("Read", "Grep", "Glob", "Write", "Edit"),
)

SPECS: Final[dict[Harness, HarnessSpec]] = {
    Harness.KIRO: KIRO,
    Harness.CLAUDE_CODE: CLAUDE_CODE,
}


def _trigger_vocabulary() -> dict[str, HookEvent]:
    """Every trigger name any supported harness sends, mapped to what it means.

    Derived from the specs so the two cannot disagree — see the module docstring. A name claimed by
    two harnesses for *different* events would be a genuine ambiguity rather than a synonym, so it
    raises here at import rather than resolving silently to whichever spec was declared last.
    """
    vocabulary: dict[str, HookEvent] = {}
    for spec in SPECS.values():
        reminder = spec.search_reminder
        named = (
            (spec.spawn_trigger, HookEvent.SPAWN),
            (spec.prompt_trigger, HookEvent.PROMPT),
            (spec.subagent_start_trigger, HookEvent.SUBAGENT_START),
            (None if reminder is None else reminder.trigger, HookEvent.SEARCH),
        )
        for trigger, event in named:
            if trigger is None:
                continue
            if vocabulary.get(trigger, event) is not event:
                message = f"trigger {trigger!r} means two different events"
                raise ValueError(message)
            vocabulary[trigger] = event
    return vocabulary


TRIGGERS: Final[dict[str, HookEvent]] = _trigger_vocabulary()

#: Which channel each event's output must go out on. A function of the event alone, not of the
#: harness: the only harness variation is which events a harness produces at all, so a per-harness
#: column here would carry only unreachable cells and no information.
CHANNELS: Final[dict[HookEvent, OutputChannel]] = {
    HookEvent.SPAWN: OutputChannel.STDOUT,
    HookEvent.PROMPT: OutputChannel.STDOUT,
    HookEvent.SUBAGENT_START: OutputChannel.ADDITIONAL_CONTEXT,
    HookEvent.SEARCH: OutputChannel.ADDITIONAL_CONTEXT,
}


def event_for(trigger: object) -> HookEvent | None:
    """What `trigger` means, or `None` if no supported harness sends that name.

    `trigger` is typed `object` because it arrives as untrusted JSON from a harness's own stdin
    delivery: a value that is absent, or present but not a string, is simply not a trigger this
    hook implements, which is the same answer as an unrecognised name and not a failure of
    anything this module owns.
    """
    if not isinstance(trigger, str):
        return None
    return TRIGGERS.get(trigger)


def channel_for(event: HookEvent) -> OutputChannel:
    """The output channel `event`'s text must be written on."""
    return CHANNELS[event]
