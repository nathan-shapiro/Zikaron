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
    AmendDetail,
    ArmTermination,
    Demotion,
    DetailField,
    EventDetail,
    EventKind,
    EventSpec,
    FetchDetail,
    MergeRole,
    NoReceiptDetail,
    PromoteForm,
    PromoteRole,
    QueryShape,
    RememberDetail,
    RetireDetail,
    RunPhase,
    ServeRole,
    StopReason,
    SurfaceCallDetail,
    SurfaceDetail,
    VersionConflictDetail,
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


def test_a_detail_missing_a_declared_key_is_refused() -> None:
    """`EVENT_SPECS` is enforced where the payload is serialized, not only compared in tests.

    Defence in depth rather than the first line of it: every producer now builds a typed
    `EventDetail`, so a misspelled or missing *field* fails at type-check time. What this catches is
    what a type cannot — a value type Python does not enforce at runtime, a grouping spliced into
    the wrong order, and a payload assembled as a mapping by anything that reaches
    `EventSpec.validate` directly. The check runs for every kind, including the six whose producers
    do not exist yet, so it is binding on writers this suite has not been written against.
    """
    with pytest.raises(ValueError, match="are not"):
        EVENT_SPECS[EventKind.FETCH].validate({"version": 1})


def test_a_detail_with_an_extra_key_is_refused() -> None:
    with pytest.raises(ValueError, match="are not"):
        EVENT_SPECS[EventKind.FETCH].validate({"version": 1, "found": True, "extra": 0})


def test_a_detail_whose_keys_are_out_of_order_is_refused() -> None:
    """The order is part of the contract, so two implementations of one kind produce the same
    payload rather than merely equivalent ones."""
    with pytest.raises(ValueError, match="in that order"):
        EVENT_SPECS[EventKind.FETCH].validate({"found": True, "version": 1})


def test_a_closed_set_field_cannot_hold_an_invented_member() -> None:
    detail = {"rank": 1, "fused_score": 0.5, "demoted": True, "demotion": "vanished"}
    with pytest.raises(ValueError, match="not one of"):
        EVENT_SPECS[EventKind.SURFACE].validate(detail)


def test_a_nullable_closed_set_field_accepts_null_and_its_own_members() -> None:
    for demotion in (None, Demotion.SUPERSEDED, "retired"):
        EVENT_SPECS[EventKind.SURFACE].validate(
            {"rank": 1, "fused_score": 0.5, "demoted": demotion is not None, "demotion": demotion}
        )


def test_an_enum_member_and_its_plain_value_are_interchangeable() -> None:
    """They serialize identically, so a producer holding the enum and one holding the string are the
    same writer as far as the log is concerned."""
    for stop in (StopReason.PROBE_CAP_HIT, "probe_cap_hit"):
        EVENT_SPECS[EventKind.SURFACE_CALL].validate(
            {
                "prompt_chars": 10,
                "limit": 5,
                "fusion_depth": 50,
                "dense_depth_reached": 3,
                "dense_stop_reason": stop,
                "lexical_depth_reached": None,
                "lexical_stop_reason": None,
                "query_tokens": 4,
                "query_truncated": False,
                "lexical_skipped": True,
                "n_returned": 3,
                "n_demoted": 0,
            }
        )


def test_a_typed_detail_serializes_to_the_contracts_flat_key_order() -> None:
    """The grouped fields are spliced in place, so the payload is flat and in the declared order.

    Grouping `ArmTermination` and `QueryShape` is what keeps the seven fields `search` and
    `surface_call` share from being transcribed once per kind; this is the assertion that the
    grouping costs nothing on the wire.
    """
    detail = SurfaceCallDetail(
        prompt_chars=12,
        limit=5,
        fusion_depth=50,
        arms=ArmTermination(
            dense_depth_reached=3,
            dense_stop_reason=StopReason.INDEX_EXHAUSTED,
            lexical_depth_reached=None,
            lexical_stop_reason=None,
        ),
        query=QueryShape(query_tokens=4, query_truncated=False, lexical_skipped=True),
        n_returned=3,
        n_demoted=1,
    )
    payload = detail.as_detail()
    assert tuple(payload) == EVENT_SPECS[EventKind.SURFACE_CALL].field_names
    assert payload["dense_stop_reason"] is StopReason.INDEX_EXHAUSTED
    assert payload["lexical_depth_reached"] is None
    EVENT_SPECS[detail.kind].validate(payload)


def test_every_typed_detail_matches_its_kinds_declared_fields() -> None:
    """One assertion covering every value type: the fields it serializes are exactly its kind's.

    Written as a sweep rather than one test per kind because the failure it guards against is a
    field added to a payload without being added to the contract, which is a mistake nobody makes
    for the kind they are looking at.
    """
    built: dict[EventKind, EventDetail] = {
        EventKind.SURFACE: SurfaceDetail(
            rank=1, fused_score=0.5, demoted=True, demotion=Demotion.SUPERSEDED
        ),
        EventKind.FETCH: FetchDetail(version=1, found=True),
        EventKind.REMEMBER: RememberDetail(
            version=1, token_count=10, gist_tokens=3, n_chunks=1, truncated=False
        ),
        EventKind.AMEND: AmendDetail(
            from_version=1,
            to_version=2,
            token_count=10,
            gist_tokens=3,
            n_chunks=1,
            truncated=False,
        ),
        EventKind.RETIRE: RetireDetail(from_version=1, to_version=2, superseded_by=None),
        EventKind.VERSION_CONFLICT: VersionConflictDetail(
            verb="amend", expected_version=1, actual_version=2
        ),
        EventKind.NO_RECEIPT: NoReceiptDetail(verb="amend", version_presented=1),
    }
    for kind, detail in built.items():
        assert detail.kind is kind
        payload = detail.as_detail()
        assert tuple(payload) == EVENT_SPECS[kind].field_names, kind
        EVENT_SPECS[kind].validate(payload)


def test_the_kinds_with_no_producer_yet_have_no_value_type() -> None:
    """The six consolidation kinds are deliberately untyped **because nothing writes them yet**.

    A dataclass nothing constructs is dead code, so the milestone that ships those verbs adds its
    value type in the same change — and it cannot forget, since `log_event` takes an `EventDetail`
    and there is no dict-shaped way in. Asserted rather than left as a comment so that adding one of
    these producers without its type, or adding a type without its producer, is visible here.
    """
    typed = {
        subclass.kind for subclass in EventDetail.__subclasses__() if hasattr(subclass, "kind")
    }
    assert set(EventKind) - typed == {
        EventKind.MERGE,
        EventKind.PROMOTE,
        EventKind.DISCARD,
        EventKind.DEDUP_OFFERED,
        EventKind.GROUP_SERVED,
        EventKind.CONSOLIDATE_RUN,
    }
