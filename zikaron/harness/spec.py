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
    9,016 characters of a 3-byte-per-character script — 27,016 bytes — arrived whole under a
    10,000-*character* cap.

    **`CHARACTERS` is measured conservatively, because the experiment that pinned it could not
    settle which kind of character.** The text it used lies in the Basic Multilingual Plane, where
    one code point is also exactly one UTF-16 code unit — so it separates characters from bytes and
    says nothing about code points versus UTF-16 units. A harness implemented on a runtime whose
    native string length is UTF-16 would count every astral character (emoji among them, which real
    gists do contain) as two where Python's `len` counts one. `exceeds_injection_budget` therefore
    measures UTF-16 code units, which is an upper bound on both readings, so the bound holds
    whichever is true. The experiment that would settle it is a bisection run with an astral
    character, which separates all three candidate units at once.
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

    def exceeds_injection_budget(self, text: str) -> bool:
        """Whether `text` is larger than this harness will actually inject.

        Measures in **this harness's own unit**. Comparing a byte length against a
        character-denominated cap under-reports by up to the encoding's expansion factor, and
        comparing a character length against a byte-denominated cap over-reports by the same — so
        the unit travels with the number rather than being assumed by the caller.

        Characters are counted as **UTF-16 code units**, not as `len(text)`. The two agree for
        every character in the Basic Multilingual Plane and differ by a factor of two for astral
        ones, and which of them a character-denominated harness actually counts is unmeasured (see
        `BudgetUnit`). Counting the larger of the two is what keeps this a bound rather than a
        guess; the cost is rejecting a little early in a corner no ordinary gist reaches.

        `surrogatepass` on both branches keeps this total. A lone surrogate is legal in a Python
        string decoded from JSON and would otherwise raise out of a bound check whose callers treat
        it as a plain predicate.
        """
        if self.budget_unit is BudgetUnit.BYTES:
            measured = len(text.encode("utf-8", errors="surrogatepass"))
        else:
            measured = len(text.encode("utf-16-le", errors="surrogatepass")) // 2
        return measured > self.injection_budget


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
