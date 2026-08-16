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
    BudgetUnit,
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


def _quantity(cell: str) -> tuple[int, str]:
    """The single number and single unit word a budget cell states.

    Section references are stripped first: `(§5, §7a)` contains digits that are not the quantity,
    and a naive scan would read one of them. Anything other than exactly one number and exactly one
    unit word raises rather than picking a candidate, since guessing which digits were meant is the
    failure mode this whole file exists to prevent.
    """
    prose = _SECTION_REFERENCE.sub("", cell)
    numbers = _NUMBER.findall(prose)
    units = [unit.value for unit in BudgetUnit if unit.value in prose.lower()]
    if len(numbers) != 1 or len(units) != 1:
        message = f"expected exactly one number and one unit in {cell!r}, found {numbers}, {units}"
        raise AssertionError(message)
    return int(numbers[0].replace(",", "")), units[0]


class TestTheCodeTableMatchesTheDesignTable:
    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_marker_variable(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Marker variable (detection)", spec)) == spec.marker_variable

    @pytest.mark.parametrize("spec", [KIRO, CLAUDE_CODE], ids=lambda spec: spec.harness.value)
    def test_session_variable(self, rows: dict[str, dict[str, str]], spec: HarnessSpec) -> None:
        assert _identifier(_cell(rows, "Session variable", spec)) == spec.session_variable

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
    def test_injection_budget_value_and_unit(
        self, rows: dict[str, dict[str, str]], spec: HarnessSpec
    ) -> None:
        value, unit = _quantity(_cell(rows, "Injection budget", spec))
        assert value == spec.injection_budget
        assert unit == spec.budget_unit.value

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

    def test_the_harness_firing_hooks_for_subagents_is_the_one_without_a_subagent_trigger(
        self, rows: dict[str, dict[str, str]]
    ) -> None:
        """The field the tripwire's scoping depends on, read from the row that states it. The
        design's own wording for the harness with no subagent trigger is that hooks fire *for*
        subagent sessions instead — which is precisely the property that makes a payload/environment
        divergence routine there and anomalous elsewhere.
        """
        for spec in SPECS.values():
            cell = _cell(rows, "Subagent triggers", spec).lower()
            states_no_trigger = any(marker in cell for marker in _ABSENT_MARKERS)
            assert spec.fires_hooks_for_subagent_sessions == states_no_trigger


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
        assert expected == TRIGGERS

    def test_each_harnesss_own_trigger_names_resolve_to_the_events_they_mean(self) -> None:
        for spec in SPECS.values():
            assert event_for(spec.spawn_trigger) is HookEvent.SPAWN
            assert event_for(spec.prompt_trigger) is HookEvent.PROMPT
            if spec.subagent_start_trigger is not None:
                assert event_for(spec.subagent_start_trigger) is HookEvent.SUBAGENT_START

    def test_the_other_harnesss_spawn_name_is_a_synonym_rather_than_an_unknown_trigger(
        self,
    ) -> None:
        """One vocabulary with synonyms, not two languages: kiro's array hook format accepts
        PascalCase trigger names, so a payload naming the other harness's spawn trigger still means
        spawn. Structural here rather than asserted, since the map is the union of both specs.
        """
        assert event_for(CLAUDE_CODE.spawn_trigger) is HookEvent.SPAWN
        assert event_for(KIRO.spawn_trigger) is HookEvent.SPAWN

    def test_every_event_has_a_channel(self) -> None:
        """A new event with no channel would emit nothing at all, silently, which is the failure
        the subagent trigger already demonstrated once.
        """
        for event in HookEvent:
            assert channel_for(event) in set(OutputChannel)

    @pytest.mark.parametrize("unknown", ["", "postToolUse", "SessionEnd", "SubagentStop"])
    def test_an_unrecognised_trigger_name_resolves_to_nothing(self, unknown: str) -> None:
        """`SubagentStop` among them, deliberately: it is a real trigger one harness sends and this
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
    def test_a_byte_denominated_budget_measures_encoded_length(self) -> None:
        assert KIRO.budget_unit is BudgetUnit.BYTES
        just_over = "—" * (KIRO.injection_budget // 3 + 1)
        assert len(just_over) < KIRO.injection_budget
        assert KIRO.exceeds_injection_budget(just_over)

    def test_a_character_denominated_budget_does_not_measure_bytes(self) -> None:
        assert CLAUDE_CODE.budget_unit is BudgetUnit.CHARACTERS
        multi_byte = "—" * CLAUDE_CODE.injection_budget
        assert len(multi_byte.encode("utf-8")) > CLAUDE_CODE.injection_budget
        assert not CLAUDE_CODE.exceeds_injection_budget(multi_byte)

    def test_astral_characters_count_two_against_a_character_budget(self) -> None:
        """The conservative reading of an unmeasured fact, pinned so it cannot be quietly relaxed.

        A character-denominated budget was pinned with text from the Basic Multilingual Plane,
        where a code point and a UTF-16 code unit are the same thing — so whether such a harness
        counts code points or UTF-16 units is unknown. Astral characters are where the two diverge,
        and counting the larger keeps the budget a bound under either reading. Half the budget in
        astral characters is exactly at it; one more is over.
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

    def test_a_byte_denominated_budget_also_tolerates_a_lone_surrogate(self) -> None:
        """The other branch's totality, which every other surrogate test here misses: they all drive
        the character path, so dropping `surrogatepass` from the UTF-8 branch alone would pass.

        Also pins three UTF-8 bytes per lone surrogate — the figure the three-bytes-per-unit ceiling
        relies on for this character class, and the reason a surrogate cannot smuggle a block past
        the byte budget.
        """
        assert KIRO.budget_unit is BudgetUnit.BYTES
        assert not KIRO.exceeds_injection_budget("\ud800" * 3)
        assert len("\ud800".encode("utf-8", errors="surrogatepass")) == 3

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
