"""`zikaron.harness.spec` against `design/harness.md` §"The table", read from the document itself.

The drift this guards is not two copies of a constant disagreeing — it is the design being revised
while the code stays put. So the design document is the input, not a second transcription of it,
which is the arrangement `coding-standards.md` §2 requires for anything the design states as a
table.

**Every extractor here fails closed.** A cell this file cannot parse raises rather than being
skipped, because a reader that quietly returned nothing for a row it did not understand would turn
the whole guard into a test that passes unconditionally. That is the same rule `design_tables.py`
holds itself to, restated for the cell-level extraction this table needs: its cells carry prose and
section references around the value, so "the whole cell is the value" — which most design tables
can assume — does not hold here.
"""

import re

import pytest

from tests.design_tables import table_with_columns
from zikaron.core.indexing.chunking import utf16_units
from zikaron.harness import detect
from zikaron.harness import spec as spec_module
from zikaron.harness.spec import (
    CHANNELS,
    CLAUDE_CODE,
    KIRO,
    SPECS,
    TRIGGERS,
    Harness,
    HarnessSpec,
    HookEvent,
    OutputChannel,
    channel_for,
    event_for,
)

_DOCUMENT = "harness.md"
_HEADING = "## The table"
_COLUMNS = ("Fact", "**kiro-cli**", "**Claude Code**")

_BACKTICKED = re.compile(r"`([^`]+)`")
_SECTION_REFERENCE = re.compile(r"§[0-9a-z]+")
_NUMBER = re.compile(r"\d[\d,]*")

#: Cell texts that state a value is not applicable to a harness at all, rather than naming one.
_ABSENT_MARKERS = ("absent", "none", "n/a")

#: The one unit every injection budget is stated in.
_BUDGET_UNIT = "characters"


@pytest.fixture(scope="module")
def rows() -> dict[str, dict[str, str]]:
    """The design table keyed by its own `Fact` column.

    A duplicated fact name raises rather than letting one row silently shadow another — the same
    fail-closed posture the parser itself takes for a repeated heading.
    """
    table = table_with_columns(_DOCUMENT, _HEADING, _COLUMNS)
    keyed: dict[str, dict[str, str]] = {}
    for row in table:
        fact = row["Fact"]
        if fact in keyed:
            message = f"{_DOCUMENT} states the fact {fact!r} twice"
            raise AssertionError(message)
        keyed[fact] = row
    return keyed


def _cell(rows: dict[str, dict[str, str]], fact: str, spec: HarnessSpec) -> str:
    """One harness's cell for one fact, by the column that harness owns."""
    if fact not in rows:
        message = f"{_DOCUMENT} no longer states the fact {fact!r}"
        raise AssertionError(message)
    column = "**kiro-cli**" if spec is KIRO else "**Claude Code**"
    return rows[fact][column]


def _leading_bold(cell: str) -> str:
    """The first `**bolded**` word in `cell`, lowercased.

    This table's cells carry prose after their value, so the answer is extracted rather than the
    cell read whole — and a cell with no bolded word raises rather than returning something
    falsy, since a guard that quietly read nothing would pass unconditionally.
    """
    match = re.search(r"\*\*([A-Za-z]+)\*\*", cell)
    if match is None:
        message = f"cell states no bolded answer: {cell!r}"
        raise ValueError(message)
    return match.group(1).lower()


def _identifier(cell: str) -> str | None:
    """The first backticked identifier in `cell`, or `None` if the cell says the value is absent.

    Cells in this table carry prose and section references around their value — an alias note, a
    second trigger name, a measurement reference — so the identifier is extracted rather than the
    cell being read whole. A cell that neither names an identifier nor states absence raises: it
    means the design changed shape and this guard can no longer read it.
    """
    match = _BACKTICKED.search(cell)
    if match is not None:
        return match.group(1)
    if any(marker in cell.lower() for marker in _ABSENT_MARKERS):
        return None
    message = f"cannot read an identifier or an absence from {cell!r}"
    raise AssertionError(message)


def _quantity(cell: str) -> int:
    """The single number a budget cell states, in the one unit every budget is stated in.

    Section references are stripped first: `(§5, §7a)` contains digits that are not the quantity,
    and a naive scan would read one of them. Anything other than exactly one number, or a cell
    that does not name the unit, raises rather than picking a candidate, since guessing which digits
    were meant is the failure mode this whole file exists to prevent.
    """
    prose = _SECTION_REFERENCE.sub("", cell)
    numbers = _NUMBER.findall(prose)
    if len(numbers) != 1 or _BUDGET_UNIT not in prose.lower():
        message = f"expected exactly one number, in {_BUDGET_UNIT}, in {cell!r}; found {numbers}"
        raise AssertionError(message)
    return int(numbers[0].replace(",", ""))


class TestTheCodeTableMatchesTheDesignTable:
    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_marker_variable(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Marker variable (detection)", spec)) == spec.marker_variable

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_session_variable(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Session variable", spec)) == spec.session_variable

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_project_dir_variable(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """D17's store scope, which is the one row where absence is itself the measurement.

        Kiro's cell must read as *absent* rather than naming something: there is no such variable,
        and a future row that quietly named one would repoint every kiro store.
        """
        cell = _cell(rows, "Project-directory variable (D17 store scope)", spec)
        assert _identifier(cell) == spec.project_dir_variable

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_spawn_trigger(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Spawn trigger", spec)) == spec.spawn_trigger

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_prompt_trigger(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Prompt trigger", spec)) == spec.prompt_trigger

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_subagent_start_trigger(
        self, rows: dict[str, dict[str, str]], spec: HarnessSpec
    ) -> None:
        assert _identifier(_cell(rows, "Subagent triggers", spec)) == spec.subagent_start_trigger

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_consolidator_reads_files(
        self, rows: dict[str, dict[str, str]], spec: HarnessSpec
    ) -> None:
        """Whether this harness's consolidator may be handed a file, and therefore whether an
        over-large result is written to one.

        One field for two consequences — the tool grant and the spill — so a design that flipped
        one cell without the other would put a consolidator with no file-reading tool in front of a
        path it cannot open, which is the stall the spill exists to end, rebuilt from the other
        side.
        """
        cell = _cell(rows, "Consolidator reads files", spec)
        answer = _leading_bold(cell)
        if answer not in {"yes", "no"}:
            message = f"cell does not open with **yes** or **no**: {cell!r}"
            raise ValueError(message)
        assert (answer == "yes") == spec.consolidator_can_read_files

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_documenter_tool_grant(
        self, rows: dict[str, dict[str, str]], spec: HarnessSpec
    ) -> None:
        """The documenter's grant, the only place a file tool is named for it: the cell's leading
        backticked names, in order, are exactly the spec's."""
        cell = _cell(rows, "Documenter tool grant (`file_tools`)", spec)
        named = tuple(_BACKTICKED.findall(cell))[: len(spec.file_tools)]
        assert named == spec.file_tools

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_guard_hooks(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """The guards' triggers and matchers, the re-read hook's only where there is one, or that
        the harness offers no guards at all — which is what the installer's refusal of them
        reads."""
        cell = _cell(rows, "Guard hooks (`guards`)", spec)
        if spec.guards is None:
            assert _identifier(cell) is None
            return
        hooks = spec.guards
        expected = (
            hooks.command.trigger,
            hooks.command.matcher,
            *(() if hooks.reread is None else (hooks.reread.trigger, hooks.reread.matcher)),
        )
        assert tuple(_BACKTICKED.findall(cell))[: len(expected)] == expected
        if hooks.reread is None:
            assert "no re-read hook" in cell

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_guard_deny(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """How a deny reaches the model: the exit status and channel the guard answers with."""
        assert spec.guards is not None
        cell = _cell(rows, "Guard deny (`guards.deny`)", spec)
        assert _leading_bold(cell) == spec.guards.deny.value

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_spill_location(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """Where the consolidator's client writes an over-large result, which decides whether its
        own path rules can name the file."""
        cell = _cell(rows, "Spill file location (`spill_location`)", spec)
        assert _leading_bold(cell) == spec.spill_location.value

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_tool_ids(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """The tools a shipped text names, as the model sees them, in the field's order."""
        cell = _cell(rows, "Tool ids the model sees (`tool_ids`)", spec)
        assert tuple(_BACKTICKED.findall(cell))[: len(spec.tool_ids)] == tuple(spec.tool_ids)

    def test_each_harness_is_named_in_prose_as_its_column_is_headed(self) -> None:
        """The name a shipped text gives the harness, such as the self-match deny's."""
        assert f"**{KIRO.prose_name}**" == _COLUMNS[1]
        assert f"**{CLAUDE_CODE.prose_name}**" == _COLUMNS[2]

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_search_reminder(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """The reminder's trigger, each arm's matcher and filters in order, or that the harness has
        no reminder — which is what a memory install's absent entry reads."""
        cell = _cell(rows, "Search reminder (`search_reminder`)", spec)
        reminder = spec.search_reminder
        if reminder is None:
            assert _identifier(cell) is None
            return
        expected = (
            reminder.trigger,
            reminder.files.matcher,
            *reminder.files.filters,
            reminder.shell.matcher,
            *reminder.shell.filters,
        )
        assert tuple(_BACKTICKED.findall(cell))[: len(expected)] == expected

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_harness_binary(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """What the installer looks for on `PATH` before writing anything.

        A *value*, so it lives on the spec with a row here — the installer's refusal is one shared
        rule parameterized by it, not two implementations. Getting it wrong is not a crash: it is an
        install that refuses on a machine where the harness is present, or writes on one where it
        is not.
        """
        assert _identifier(_cell(rows, "Harness binary", spec)) == spec.harness_binary

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_consolidator_model(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """The installer's default, read from the row that states it.

        A *value* that differs per harness, so it lives on the spec with a row here rather than in
        `zikaron/install/targets.py` — which is where the shapes go. The two spellings are not
        interchangeable and the reason is asymmetric: kiro's must be a concrete id because the
        install-time `--list-models` check compares against ids, and Claude Code's may be an alias
        because that harness refuses an unknown id at spawn instead of substituting one.
        """
        assert _identifier(_cell(rows, "Shipped consolidator `model`", spec)) == (
            spec.consolidator_model
        )

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_documenter_model(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Shipped documenter `model`", spec)) == (
            spec.documenter_model
        )

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_orchestrator_model(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Shipped orchestrator `model`", spec)) == (
            spec.orchestrator_model
        )

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_injection_budget(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _quantity(_cell(rows, "Injection budget", spec)) == spec.injection_budget

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_session_variable_reach(
        self, rows: dict[str, dict[str, str]], spec: HarnessSpec
    ) -> None:
        """Whether the session variable misses the MCP server, which is what makes the hook relay
        the label to the MCP client: a cell opening **hooks** says the server is not among what it
        reaches, **both** that it is."""
        cell = _cell(rows, "Session variable reaches", spec)
        answer = _leading_bold(cell)
        if answer not in {"hooks", "both"}:
            message = f"cell does not open with **hooks** or **both**: {cell!r}"
            raise ValueError(message)
        assert (answer == "hooks") == spec.session_variable_misses_mcp_server

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_hook_command_prefix(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        """What opens every hook command: the backticked word the cell opens with, or nothing where
        the cell opens with `none`."""
        cell = _cell(rows, "Hook `command`", spec)
        opening = _BACKTICKED.match(cell)
        if opening is None and not cell.lower().startswith("none"):
            message = f"cell opens with neither a backticked prefix nor `none`: {cell!r}"
            raise ValueError(message)
        prefix = "" if opening is None else f"{opening.group(1)} "
        assert prefix == spec.hook_command_prefix

    def test_spawn_and_prompt_go_out_on_stdout_under_both_harnesses(
        self, rows: dict[str, dict[str, str]]
    ) -> None:
        for harness_spec in SPECS.values():
            assert "stdout" in _cell(rows, "Output channel, spawn/prompt", harness_spec).lower()
        assert channel_for(HookEvent.SPAWN) is OutputChannel.STDOUT
        assert channel_for(HookEvent.PROMPT) is OutputChannel.STDOUT

    def test_the_subagent_channel_is_structured_only_where_the_trigger_exists(
        self, rows: dict[str, dict[str, str]]
    ) -> None:
        """The row the code deliberately does not carry per-harness, checked against the document
        anyway: the design states one harness has no subagent channel at all, which is exactly why
        `CHANNELS` is keyed by event rather than by `(harness, event)`.
        """
        kiro_cell = _cell(rows, "Output channel, subagent", KIRO).lower()
        claude_cell = _cell(rows, "Output channel, subagent", CLAUDE_CODE)
        assert any(marker in kiro_cell for marker in _ABSENT_MARKERS)
        assert "additionalContext" in claude_cell
        assert KIRO.subagent_start_trigger is None
        assert CHANNELS[HookEvent.SUBAGENT_START] is OutputChannel.ADDITIONAL_CONTEXT

    def test_the_search_reminder_goes_out_on_the_tool_events_structured_channel(
        self, rows: dict[str, dict[str, str]]
    ) -> None:
        """A tool event's plain stdout goes to the debug log alone
        (`research/claude-code-tool-hook-probe.md`); `additionalContext` reaches the agent, measured
        with a nonce in the main session and a subagent alike (`research/m40-4-hook-probes.md`)."""
        kiro_cell = _cell(rows, "Output channel, tool event", KIRO).lower()
        assert any(marker in kiro_cell for marker in _ABSENT_MARKERS)
        assert "additionalContext" in _cell(rows, "Output channel, tool event", CLAUDE_CODE)
        assert KIRO.search_reminder is None
        assert channel_for(HookEvent.SEARCH) is OutputChannel.ADDITIONAL_CONTEXT


class TestTheTableIsInternallyConsistent:
    def test_every_declared_harness_has_a_spec(self) -> None:
        for harness, spec in SPECS.items():
            assert spec.harness is harness

    def test_the_trigger_vocabulary_is_the_union_of_both_harnesses_own_triggers(self) -> None:
        """Derived, not written twice — so a rename in a spec moves the vocabulary with it."""
        expected = {
            KIRO.spawn_trigger: HookEvent.SPAWN,
            CLAUDE_CODE.spawn_trigger: HookEvent.SPAWN,
            KIRO.prompt_trigger: HookEvent.PROMPT,
            CLAUDE_CODE.prompt_trigger: HookEvent.PROMPT,
            CLAUDE_CODE.subagent_start_trigger: HookEvent.SUBAGENT_START,
        }
        assert CLAUDE_CODE.search_reminder is not None
        expected[CLAUDE_CODE.search_reminder.trigger] = HookEvent.SEARCH
        assert expected == TRIGGERS

    def test_each_harnesss_own_trigger_names_resolve_to_the_events_they_mean(self) -> None:
        for spec in SPECS.values():
            assert event_for(spec.spawn_trigger) is HookEvent.SPAWN
            assert event_for(spec.prompt_trigger) is HookEvent.PROMPT
            if spec.subagent_start_trigger is not None:
                assert event_for(spec.subagent_start_trigger) is HookEvent.SUBAGENT_START
            if spec.search_reminder is not None:
                assert event_for(spec.search_reminder.trigger) is HookEvent.SEARCH

    def test_every_event_has_a_channel(self) -> None:
        """A new event with no channel would emit nothing at all, silently, which is the failure
        the subagent trigger already demonstrated once.
        """
        for event in HookEvent:
            assert channel_for(event) in set(OutputChannel)

    @pytest.mark.parametrize(
        "unknown",
        ["", "postToolUse", "SessionEnd", "SubagentStop", "agentSpawn", "userPromptSubmit"],
    )
    def test_an_unrecognised_trigger_name_resolves_to_nothing(self, unknown: str) -> None:
        """kiro's camelCase names among them: its V3 payload names the event in PascalCase even for
        an entry configured with one (`research/kiro-v3-probe.md` §3), so the hook needs no
        synonyms.

        `SubagentStop` among them, deliberately: it is a real trigger one harness sends and this
        hook has no work for, and the hook having no write path at all depends on it staying out of
        the vocabulary rather than merely being unhandled downstream.
        """
        assert event_for(unknown) is None

    @pytest.mark.parametrize("malformed", [None, 42, [], {}])
    def test_a_non_string_trigger_resolves_to_nothing_rather_than_raising(
        self, malformed: object
    ) -> None:
        """The payload is untrusted JSON: a missing or malformed `hook_event_name` is not a trigger
        this hook implements, which is the same answer as an unknown name and not a crash.
        """
        assert event_for(malformed) is None


class TestTheTableFailsClosedOnAMalformedEntry:
    """Both guards below raise at construction rather than resolving silently. They exercise private
    functions deliberately: the whole value of a fail-closed guard is what it does on input that
    cannot reach it through the public table, so there is no public call that can trigger either.
    """

    def test_a_trigger_name_meaning_two_different_events_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A name claimed by two harnesses for *different* events is a genuine ambiguity rather
        than the synonym the shared vocabulary is built on, and resolving it to whichever spec was
        declared last would silently route one harness's trigger to the other's handler.
        """
        collision = KIRO._replace(prompt_trigger=KIRO.spawn_trigger)
        monkeypatch.setattr(spec_module, "SPECS", {Harness.KIRO: collision})
        with pytest.raises(ValueError, match="two different events"):
            spec_module._trigger_vocabulary()

    @pytest.mark.parametrize(
        "unmarked_count",
        [0, 2],
        ids=["no-fallback-harness", "two-fallback-harnesses"],
    )
    def test_the_fallback_requires_exactly_one_unmarked_harness(
        self, monkeypatch: pytest.MonkeyPatch, unmarked_count: int
    ) -> None:
        """None would leave detection undefined when no marker is set; two would leave it ambiguous.
        Either is a table that cannot be read, so it raises rather than picking.
        """
        marked = CLAUDE_CODE
        unmarked = KIRO._replace(marker_variable=None)
        specs = {Harness.CLAUDE_CODE: marked} if unmarked_count == 0 else {}
        if unmarked_count == 2:
            specs = {
                Harness.KIRO: unmarked,
                Harness.CLAUDE_CODE: CLAUDE_CODE._replace(marker_variable=None),
            }
        monkeypatch.setattr(detect, "SPECS", specs)
        with pytest.raises(ValueError, match="exactly one harness"):
            detect._fallback_harness()


class TestInjectionBudgetMeasurement:
    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_a_budget_does_not_measure_bytes(self, spec: HarnessSpec) -> None:
        """kiro's cut was measured in characters too (`research/kiro-v3-probe.md` §21)."""
        multi_byte = "—" * spec.injection_budget
        assert len(multi_byte.encode("utf-8")) > spec.injection_budget
        assert not spec.exceeds_injection_budget(multi_byte)

    def test_astral_characters_count_two_against_a_character_budget(self) -> None:
        """The **measured** reading, pinned so it cannot be quietly relaxed to `len()`.

        The budget was first pinned with text from the Basic Multilingual Plane, where a code point
        and a UTF-16 code unit are the same thing, so it could not say which was counted. The
        astral rerun settled it (`research/claude-code-dogfood-checkpoint.md` §3): 6,000 astral code
        points — 12,000 units — truncate under the 10,000 cap while 4,600 survive. So counting
        units is **correct**, and a `len()`-based count would be *wrong* rather than merely less
        safe. Half the budget in astral characters is exactly at it; one more is over.
        """
        astral = "\U00010348"
        assert len(astral) == 1, "one code point, but two UTF-16 code units"
        exactly_at = astral * (CLAUDE_CODE.injection_budget // 2)
        assert not CLAUDE_CODE.exceeds_injection_budget(exactly_at)
        assert CLAUDE_CODE.exceeds_injection_budget(exactly_at + astral)

    def test_the_seam_and_the_write_path_count_characters_identically(self) -> None:
        """The two halves of one argument must use one unit, or the write-path bound stops proving
        anything about the injection budget.

        They are separate implementations by necessity — the seam is the hook's stdlib-only module
        and may not import `core` — so the agreement is guarded rather than assumed. The budget is
        exercised through its public predicate at the exact boundary the shared count implies.
        """
        for filler in ("a", "—", "漢", "\U00010348", "\ud800"):
            units_each = utf16_units(filler)
            at_the_budget = filler * (CLAUDE_CODE.injection_budget // units_each)
            assert utf16_units(at_the_budget) == CLAUDE_CODE.injection_budget, filler
            assert not CLAUDE_CODE.exceeds_injection_budget(at_the_budget), filler
            assert CLAUDE_CODE.exceeds_injection_budget(at_the_budget + filler), filler

    def test_the_conservative_count_never_under_reports_against_code_points(self) -> None:
        """Stated as the general property rather than one fixture: whatever the text, the measure
        used is at least the code-point count, so a budget that holds here holds under the other
        reading too.
        """
        for text in ("plain ascii", "— em dashes —", "\U0001f600 emoji \U00010348", ""):
            assert len(text.encode("utf-16-le")) // 2 >= len(text)

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_the_bound_is_exclusive_at_exactly_the_budget(self, spec: HarnessSpec) -> None:
        """One unit over and exactly at, since a fixture merely "large" passes either way."""
        assert not spec.exceeds_injection_budget("x" * spec.injection_budget)
        assert spec.exceeds_injection_budget("x" * (spec.injection_budget + 1))
