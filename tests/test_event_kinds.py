"""The event vocabulary, checked against `design/schema.md` §"The `event` log, per kind".

The section states a kind's detail shape in its own row, except for the two stop reasons, whose
value sets it gives in a second table. Both are read here, so neither can drift alone.
"""

import pytest

from tests.design_tables import (
    literal,
    parse_field_values,
    parse_name_lists,
    parse_payload,
    table_with_columns,
)
from zikaron.core.errors import ErrorCode
from zikaron.core.events import (
    EVENT_SPECS,
    Demotion,
    DetailField,
    EventKind,
    EventSpec,
    MergeRole,
    PromoteForm,
    PromoteRole,
    RunPhase,
    ServeRole,
    StopReason,
)

DOCUMENT = "schema.md"
HEADING = "## The `event` log, per kind"
KIND_COLUMNS = ("`kind`", "Cardinality", "`memory_uuid`", "`detail`")
STOP_REASON_COLUMNS = ("Field", "Values", "Meaning")
NULLABLE_COLUMN = "`detail` fields that may be null"
NULLABLE_COLUMNS = ("`kind`", NULLABLE_COLUMN, "Why")


@pytest.fixture(scope="module")
def design_rows() -> list[dict[str, str]]:
    return table_with_columns(DOCUMENT, HEADING, KIND_COLUMNS)


@pytest.fixture(scope="module")
def design_stop_reasons() -> dict[str, tuple[str, ...]]:
    table = table_with_columns(DOCUMENT, HEADING, STOP_REASON_COLUMNS)
    return parse_field_values(table, "Field", "Values")


@pytest.fixture(scope="module")
def design_nullable() -> dict[str, tuple[str, ...]]:
    table = table_with_columns(DOCUMENT, HEADING, NULLABLE_COLUMNS)
    return parse_name_lists(table, "`kind`", NULLABLE_COLUMN)


def test_kinds_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    expected = [literal(row["`kind`"]) for row in design_rows]
    assert [kind.value for kind in EventKind] == expected


def test_every_kind_has_exactly_one_spec() -> None:
    assert set(EVENT_SPECS) == set(EventKind)


def test_which_kinds_name_a_memory_matches_the_design_table(
    design_rows: list[dict[str, str]],
) -> None:
    """The design writes `NULL` for a per-call kind and describes the uuid for a per-row kind."""
    for row in design_rows:
        kind = EventKind(literal(row["`kind`"]))
        names_memory = row["`memory_uuid`"].strip() != "NULL"
        assert EVENT_SPECS[kind].names_memory is names_memory, kind.value


def test_detail_field_names_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    for row in design_rows:
        kind = EventKind(literal(row["`kind`"]))
        stated = tuple(field.name for field in parse_payload(row["`detail`"]))
        assert EVENT_SPECS[kind].field_names == stated, kind.value


def test_detail_value_sets_match_the_design_table(
    design_rows: list[dict[str, str]],
    design_stop_reasons: dict[str, tuple[str, ...]],
) -> None:
    """Both places the design states a detail value set are checked against the one declaration.

    A stop reason's values live in the second table, so a kind's own row must not also state them
    — two statements of one set is the drift this guard exists to prevent, not a redundancy to
    tolerate.
    """
    for row in design_rows:
        kind = EventKind(literal(row["`kind`"]))
        declared = {field.name: field for field in EVENT_SPECS[kind].detail_fields}
        for stated in parse_payload(row["`detail`"]):
            if stated.name in design_stop_reasons:
                assert not stated.values, f"{kind.value}.{stated.name} stated in two places"
                expected = design_stop_reasons[stated.name]
            else:
                expected = tuple(str(value) for value in stated.values)
            assert declared[stated.name].values == expected, f"{kind.value}.{stated.name}"


def test_nullable_detail_fields_match_the_design_table(
    design_rows: list[dict[str, str]],
    design_nullable: dict[str, tuple[str, ...]],
) -> None:
    """Nullability is a contract: a signal that joins on a field has to know what null means.

    A kind absent from the design's nullability table has no field this document states may be
    null, which is not the same as one whose fields cannot be null — so the code says exactly what
    the design says and nothing more.
    """
    for row in design_rows:
        kind = EventKind(literal(row["`kind`"]))
        expected = set(design_nullable.get(kind.value, ()))
        actual = {field.name for field in EVENT_SPECS[kind].detail_fields if field.nullable}
        assert actual == expected, kind.value


def test_the_nullability_table_names_only_fields_its_kind_carries(
    design_rows: list[dict[str, str]],
    design_nullable: dict[str, tuple[str, ...]],
) -> None:
    carried = {
        literal(row["`kind`"]): {field.name for field in parse_payload(row["`detail`"])}
        for row in design_rows
    }
    assert set(design_nullable) <= set(carried)
    for kind, names in design_nullable.items():
        assert set(names) <= carried[kind], kind


def test_a_null_written_into_a_value_set_is_also_in_the_nullability_table(
    design_rows: list[dict[str, str]],
    design_nullable: dict[str, tuple[str, ...]],
) -> None:
    """The design states some nulls in two forms, and the two must not disagree."""
    for row in design_rows:
        kind = literal(row["`kind`"])
        inline = {field.name for field in parse_payload(row["`detail`"]) if field.nullable}
        assert inline <= set(design_nullable.get(kind, ())), kind


def test_the_stop_reason_table_covers_exactly_the_two_arms(
    design_stop_reasons: dict[str, tuple[str, ...]],
) -> None:
    assert set(design_stop_reasons) == {"dense_stop_reason", "lexical_stop_reason"}
    assert design_stop_reasons["dense_stop_reason"] == tuple(StopReason)
    assert set(design_stop_reasons["lexical_stop_reason"]) < set(StopReason)


def test_the_closed_sets_are_enums_carrying_exactly_the_designs_values(
    design_rows: list[dict[str, str]],
) -> None:
    """Every closed detail set is an enum, so no later writer can spell one of its members."""
    stated = {
        f"{literal(row['`kind`'])}.{field.name}": field.values
        for row in design_rows
        for field in parse_payload(row["`detail`"])
        if field.values
    }
    assert stated == {
        "surface.demotion": tuple(Demotion),
        "merge.role": tuple(MergeRole),
        "promote.role": tuple(PromoteRole),
        "promote.form": tuple(PromoteForm),
        "group_served.role": tuple(ServeRole),
        "consolidate_run.phase": tuple(RunPhase),
    }


def test_no_kind_declares_a_field_twice() -> None:
    with pytest.raises(ValueError, match="declares a field twice"):
        EventSpec(names_memory=True, detail_fields=(DetailField("v"), DetailField("v")))


def test_a_kind_serializes_as_its_own_name() -> None:
    """Kinds are written to a text column, so the enum member must be usable as the value."""
    assert f"{EventKind.CONSOLIDATE_RUN}" == "consolidate_run"
    assert EventKind("consolidate_run") is EventKind.CONSOLIDATE_RUN


def test_the_missing_receipt_event_and_error_are_spelled_differently_on_purpose() -> None:
    """Two vocabularies name one situation, and neither spelling may be tidied into the other.

    The event kind and the error code are separate contracts — one is a durable row a signal
    counts, the other is a number on the wire — and each is checked against its own design table.
    They are pinned against each other here because the resemblance invites a helpful rename that
    would silently break whichever side was not being looked at.
    """
    assert EventKind.NO_RECEIPT.value == "no_receipt"
    assert ErrorCode.NO_READ_RECEIPT.wire_name == "no_read_receipt"
