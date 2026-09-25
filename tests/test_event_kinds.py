"""The event vocabulary, checked against `design/schema.md` §"The `event` log, per kind".

The section states a kind's detail shape in its own row, except for the two stop reasons, whose
value sets it gives in a second table. Both are read here, so neither can drift alone.
"""

import re

import pytest

from tests.design_tables import (
    literal,
    parse_fenced_code,
    parse_field_values,
    parse_name_lists,
    parse_payload,
    section_lines,
    sql_statements,
    table_with_columns,
)
from zikaron.core.consolidation import runs
from zikaron.core.consolidation.runs import RunStatus
from zikaron.core.errors import ErrorCode
from zikaron.core.events import (
    EVENT_SPECS,
    AmendDetail,
    ArmTermination,
    AuthoredSize,
    ClientKind,
    ConsolidateRunDetail,
    DedupOfferedDetail,
    Demotion,
    DetailField,
    DiscardDetail,
    EventDetail,
    EventKind,
    EventSpec,
    FetchDetail,
    GroupRef,
    GroupServedDetail,
    MergeDetail,
    MergeRole,
    NoReceiptDetail,
    PromoteDetail,
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
                "preamble_digest": "0123456789ab",
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
        preamble_digest="0123456789ab",
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
        EventKind.DEDUP_OFFERED: DedupOfferedDetail(created_uuid="u1", cosine=0.9, rank=1),
        EventKind.MERGE: MergeDetail(
            group=GroupRef(group_id="g1", run_id="r1"),
            role=MergeRole.ABSORBED,
            from_version=1,
            to_version=2,
            n_absorbed=2,
            size=AuthoredSize.none_authored(),
        ),
        EventKind.PROMOTE: PromoteDetail(
            group=GroupRef(group_id="g1", run_id="r1"),
            role=PromoteRole.FLIPPED,
            form=PromoteForm.IN_PLACE,
            from_version=1,
            to_version=2,
            n_absorbed=1,
            size=AuthoredSize(token_count=10, gist_tokens=3, n_chunks=1, truncated=False),
        ),
        EventKind.DISCARD: DiscardDetail(
            group=GroupRef(group_id="g1", run_id="r1"),
            reason="superseded by the pinned version",
            from_version=1,
            to_version=2,
            n_absorbed=1,
        ),
        EventKind.GROUP_SERVED: GroupServedDetail(
            group=GroupRef(group_id="g1", run_id="r1"),
            role=ServeRole.MEMBER,
            version_served=3,
            serve_count=1,
        ),
        EventKind.CONSOLIDATE_RUN: ConsolidateRunDetail(
            run_id="r1", phase=RunPhase.PLANNED, n_groups=2, n_members=5, n_deferred=0
        ),
    }
    for kind, detail in built.items():
        assert detail.kind is kind
        payload = detail.as_detail()
        assert tuple(payload) == EVENT_SPECS[kind].field_names, kind
        EVENT_SPECS[kind].validate(payload)


def _value_types_by_name() -> dict[str, EventKind]:
    """Every `EventDetail` subclass's declared kind, keyed by class name.

    Keyed by name rather than collected as a list, because `@dataclass(slots=True)` cannot add
    `__slots__` to an existing class and so **returns a new one**: the class the `class` statement
    created stays registered in `EventDetail.__subclasses__()` beside its slotted replacement, and
    every subclass therefore appears twice. Counting the raw list would report every kind as
    duplicated; keying by `__qualname__`, which both copies share, leaves exactly one entry per
    declared type — which is what makes "two types claim one kind" a checkable statement.
    """
    return {
        subclass.__qualname__: subclass.kind
        for subclass in EventDetail.__subclasses__()
        if hasattr(subclass, "kind")
    }


def test_every_kind_has_exactly_one_typed_value() -> None:
    """No kind may be logged without a typed value, and none is left without one.

    This test began life asserting the *complement* — which kinds deliberately had no producer yet,
    because a dataclass nothing constructs is dead code. Every kind now has both, so the assertion
    inverts: the set difference is empty in **both** directions. Left as a test rather than deleted,
    because the property it defends is the one that made the earlier form safe. A new `EventKind`
    added without its value type fails here, and `log_event` takes an `EventDetail` so there is no
    dict-shaped way to write one anyway; a value type declaring a `kind` no longer in `EventKind`
    fails here too.
    """
    typed = _value_types_by_name()
    assert set(typed.values()) == set(EventKind)
    assert len(typed) == len(set(typed.values())), f"two value types claim one kind: {typed}"


_CLIENT_KIND_CHECK = re.compile(r"client_kind TEXT NOT NULL CHECK \(client_kind IN \(([^)]*)\)\)")


def _create_statement(prefix: str) -> str:
    """One `CREATE TABLE` statement from `schema.md`'s DDL block, normalized, read at test time.

    Located by name rather than by position, and required to be **unique**: a second copy of one
    table anywhere in that block — a revision added beside the old one — would otherwise be read as
    whichever came first, which is the stale-read failure this family of guards exists to prevent.
    """
    ddl = parse_fenced_code(section_lines(DOCUMENT, "## Tables"), "sql")
    found = [statement for statement in sql_statements(ddl) if statement.startswith(prefix)]
    assert len(found) == 1, f"{len(found)} statements matching {prefix!r} in {DOCUMENT} §Tables"
    return found[0]


def test_client_kinds_match_the_event_table_check_constraint() -> None:
    """`ClientKind` is a value set the schema states, so it is read from the schema.

    Read from `event.client_kind`'s `CHECK` rather than transcribed beside it, for the reason every
    drift guard here exists: a hand-typed second copy catches a code edit and is blind to a design
    edit, which is the likelier direction. `read_receipt.client_kind` carries the same vocabulary
    and deliberately declares no `CHECK` of its own — it is half of that table's primary key, and
    the schema's comment says so — so there is one statement of the set and this reads it.
    """
    match = _CLIENT_KIND_CHECK.search(_create_statement("CREATE TABLE event ("))
    assert match is not None, "event.client_kind's CHECK constraint was not found"
    stated = tuple(value.strip().strip("'") for value in match.group(1).split(","))
    assert tuple(kind.value for kind in ClientKind) == stated


_RUN_STATUS_CHECK = re.compile(r"status TEXT NOT NULL CHECK \(status IN \(([^)]*)\)\)")


def test_run_statuses_match_the_consolidation_run_check_constraint() -> None:
    """`RunStatus` is a value set the schema states, so it is read from the schema.

    `RunPhase` was already guarded — the `consolidate_run` detail table states its members, and the
    test above compares them — while `RunStatus` was not, even though the two are deliberately kept
    1:1 by `runs._CLOSING_PHASE`. A status added to the DDL without its enum member, or the
    reverse, would have surfaced as a `CHECK` violation on the first store that tried to write it.
    """
    statement = _create_statement("CREATE TABLE consolidation_run (")
    match = _RUN_STATUS_CHECK.search(statement)
    assert match is not None, "consolidation_run.status's CHECK constraint was not found"
    stated = tuple(value.strip().strip("'") for value in match.group(1).split(","))
    assert tuple(status.value for status in RunStatus) == stated


def test_every_terminal_run_status_has_a_phase_to_record_it() -> None:
    """`runs.close` maps a terminal status onto the `consolidate_run` phase that records it, and
    looks it up with `[]` — so a status added without a phase raises `KeyError` at the one call
    site that closes a run, on whichever path first reaches it.

    Asserted as an exhaustive set equality rather than a spot check: the mapping must cover
    **every** status except `ACTIVE`, which is not a close, and must invent none. That keeps the
    two vocabularies 1:1 by test rather than by the convention of having written them out together.
    """
    assert set(runs._CLOSING_PHASE) == set(RunStatus) - {RunStatus.ACTIVE}
    assert {phase.value for phase in runs._CLOSING_PHASE.values()} <= {
        phase.value for phase in RunPhase
    }
