"""`design/harness.md` §"The table", as data.

One `HarnessSpec` per supported harness, and every harness-varying value either a field on it or
derived from those fields. A test reads the design document itself and asserts this table against
it, so an edit on either side fails rather than drifting — the arrangement `coding-standards.md` §2
requires for anything the design states as a table.

**The trigger vocabulary is derived from the specs rather than written a second time.** Kiro's array
hook format accepts PascalCase trigger names generally, and `SessionStart` as an alias for
`agentSpawn`, so the two harnesses' names are one vocabulary with synonyms rather than two
languages. Building the map as the union of both specs' own trigger fields makes that structural: a
name either is some harness's stated trigger or is not a trigger at all, and there is no third place
for the two to disagree.
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

    Trigger names normalize many-to-three. `SPAWN` and `PROMPT` exist under both harnesses;
    `SUBAGENT_START` arrives only under Claude Code, whose payload carries the `agent_type` that
    makes a per-agent rule expressible at all.

    `SubagentStop` is deliberately absent. It has no work to do: the only path that wanted it
    existed to record which concrete model a consolidation run used, and that is unnecessary
    because the harness refuses an unknown model id at spawn, so the configured id can simply be
    trusted. Its absence is what keeps the `event` log's own rule — pushes come from the hook,
    writes from the MCP client — true, since the hook has no write path at all.
    """

    SPAWN = "spawn"
    PROMPT = "prompt"
    SUBAGENT_START = "subagent_start"


class OutputChannel(enum.Enum):
    """How a hook's output reaches a model. **The two are not interchangeable per event**, which is
    measured rather than assumed: plain exit-0 stdout from a `SubagentStart` hook reaches nobody —
    not the subagent, not the parent — while the same text under
    `hookSpecificOutput.additionalContext` reaches the subagent verbatim and stays invisible to the
    parent, which is the isolation write-policy delivery wants.
    """

    STDOUT = "stdout"
    ADDITIONAL_CONTEXT = "additional_context"


class BudgetUnit(enum.Enum):
    """What an injection budget counts. The distinction is load-bearing and was pinned by
    experiment rather than inferred: an ASCII bisection cannot tell bytes from characters, and
    ~9,000 characters of a 3-byte-per-character script plus its ASCII markers — 27,016 bytes —
    arrived whole under a 10,000-*character* cap.

    **Which kind of character is now measured: UTF-16 code units**
    (`research/claude-code-dogfood-checkpoint.md` §3). The earlier experiment could not settle it,
    because the text it used lies in the Basic Multilingual Plane, where one code point is also
    exactly one UTF-16 code unit. The astral rerun separates all three candidates: 6,000 astral code
    points — 12,000 UTF-16 units — **truncate** under the 10,000 cap, while 4,600 (9,200 units)
    arrive whole. So a `len()`-based count is **wrong**, not merely less conservative: it would pass
    a block the harness then truncates.

    **The member is still named `CHARACTERS`, and that name is now known to be the ambiguous word.**
    Renaming it is the honest fix and was deliberately not done inside a checkpoint milestone; note
    that `tests/test_harness_table.py` parses the design table's budget cell for one number and one
    unit word, so a unit whose name contains a digit needs that parser taught first.
    """

    BYTES = "bytes"
    CHARACTERS = "characters"


class HarnessSpec(NamedTuple):
    """Everything that varies between harnesses, for one harness.

    A `NamedTuple` rather than a frozen dataclass purely for import cost (see the package
    docstring); it is immutable and typed either way.
    """

    harness: Harness
    marker_variable: str | None
    session_variable: str
    spawn_trigger: str
    prompt_trigger: str
    subagent_start_trigger: str | None
    fires_hooks_for_subagent_sessions: bool
    injection_budget: int
    budget_unit: BudgetUnit
    consolidator_model: str
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

    def exceeds_injection_budget(self, text: str) -> bool:
        """Whether `text` is larger than this harness will actually inject.

        Measures in **this harness's own unit**. Comparing a byte length against a
        character-denominated cap under-reports by up to the encoding's expansion factor, and
        comparing a character length against a byte-denominated cap over-reports by the same — so
        the unit travels with the number rather than being assumed by the caller.

        Characters are counted as **UTF-16 code units**, not as `len(text)`. The two agree for
        every character in the Basic Multilingual Plane and differ by a factor of two for astral
        ones — and UTF-16 units are what a character-denominated harness was **measured** to count
        (`research/claude-code-dogfood-checkpoint.md` §3; see `BudgetUnit`). This is therefore the
        correct count rather than a conservative one: `len(text)` would pass 6,000 astral characters
        against a 10,000 cap that truncates them.

        `surrogatepass` on both branches keeps this total. A lone surrogate is legal in a Python
        string decoded from JSON and would otherwise raise out of a bound check whose callers treat
        it as a plain predicate.
        """
        if self.budget_unit is BudgetUnit.BYTES:
            measured = len(text.encode("utf-8", errors="surrogatepass"))
        else:
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
        17 `KIRO_*` names across 42 probe records, none spatial) and appears not to need one,
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


#: Kiro states `max_output_size` explicitly in every object-format hook entry, so the budget here is
#: the value the installer writes rather than the harness's own 10240-byte default.
KIRO: Final = HarnessSpec(
    harness=Harness.KIRO,
    marker_variable=None,
    session_variable="KIRO_SESSION_ID",
    spawn_trigger="agentSpawn",
    prompt_trigger="userPromptSubmit",
    subagent_start_trigger=None,
    # Kiro has no subagent trigger because it fires the ordinary hooks *for* a subagent session
    # instead. So a payload whose `session_id` differs from the environment's is the routine,
    # expected subagent case here — which is exactly why the tripwire that reads the same
    # divergence as an anomaly must not fire under this harness.
    fires_hooks_for_subagent_sessions=True,
    injection_budget=65_536,
    budget_unit=BudgetUnit.BYTES,
    # Pinned to a concrete id, and it has to be: this harness substitutes its own default for an
    # id it does not recognise, *silently*, so the installer validates membership against
    # `chat --list-models` — a check an alias would fail, since that command lists ids.
    consolidator_model="claude-sonnet-5",
    harness_binary="kiro-cli",
    # Measured, not assumed: the lifecycle probe captured every `KIRO_*` variable across 42
    # records and none names a workspace or project directory.
    project_dir_variable=None,
    # What this harness does with an over-large MCP result is **unmeasured**. Rather than invent a
    # remedy for behaviour nobody has observed, every payload is returned inline here exactly as
    # before, and the consolidator keeps the four verbs and nothing else.
    consolidator_can_read_files=False,
)

#: Claude Code's budget is fixed: there is no configuration field to raise it, so unlike kiro's this
#: number is the harness's own and not something an installer chose.
CLAUDE_CODE: Final = HarnessSpec(
    harness=Harness.CLAUDE_CODE,
    marker_variable="CLAUDECODE",
    session_variable="CLAUDE_CODE_SESSION_ID",
    spawn_trigger="SessionStart",
    prompt_trigger="UserPromptSubmit",
    subagent_start_trigger="SubagentStart",
    # `UserPromptSubmit` does not fire for subagents at all here; a subagent is reached through its
    # own trigger, whose payload carries the agent identity kiro's cannot express. Payload and
    # environment session ids are therefore invariantly equal in any hook this harness fires, which
    # is what makes a divergence meaningful enough to log.
    fires_hooks_for_subagent_sessions=False,
    injection_budget=10_000,
    budget_unit=BudgetUnit.CHARACTERS,
    # An alias, and safely so: this harness refuses an unknown id loudly at spawn, so both rules
    # `architecture.md` §"The consolidator's model" states are satisfied — the field is present
    # explicitly, and the harness serves exactly what was asked for. A *pinned* default would rot
    # instead: an install a year from now would ship last year's id, and once that id retires the
    # consolidator fails at spawn. Experiments pin; the shipped default does not have to.
    consolidator_model="sonnet",
    harness_binary="claude",
    project_dir_variable="CLAUDE_PROJECT_DIR",
    # Measured: an over-large result is replaced wholesale by an error notice, and the harness's
    # own spill file is one line of JSON that `Read` cannot paginate. A file this project writes
    # can be paginated, so the capability is real — `research/claude-code-mcp-result-truncation.md`.
    consolidator_can_read_files=True,
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
        named = (
            (spec.spawn_trigger, HookEvent.SPAWN),
            (spec.prompt_trigger, HookEvent.PROMPT),
            (spec.subagent_start_trigger, HookEvent.SUBAGENT_START),
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
#: harness: the only harness variation is that kiro never produces `SUBAGENT_START` at all, so a
#: per-harness column here would carry one unreachable cell and no information.
CHANNELS: Final[dict[HookEvent, OutputChannel]] = {
    HookEvent.SPAWN: OutputChannel.STDOUT,
    HookEvent.PROMPT: OutputChannel.STDOUT,
    HookEvent.SUBAGENT_START: OutputChannel.ADDITIONAL_CONTEXT,
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
