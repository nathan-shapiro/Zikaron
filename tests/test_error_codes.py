"""The error contract, checked against the error table in `design/architecture.md` §Errors."""

import re

import pytest

from tests.design_tables import (
    MINUS_SIGN,
    ParsedField,
    literal,
    number,
    parse_payload,
    section_lines,
    table_with_columns,
)
from zikaron.core.errors import (
    APPLICATION_CODE_MAX,
    APPLICATION_CODE_MIN,
    ERROR_SPECS,
    INACTIVE_ROW_STATES,
    BadConfigSource,
    BadMergeTargetReason,
    ErrorCode,
    ErrorSpec,
    IndexStage,
    PayloadField,
    RowState,
    ZikaronError,
)

DOCUMENT = "architecture.md"
HEADING = "## Errors"
COLUMNS = ("Code", "Name", "Raised when", "`data`")

# The design states the claimed application range as one bold pair, e.g. **-32099...-32000**.
_BOLD_RANGE = re.compile(rf"\*\*({MINUS_SIGN}?\d+)\u2026({MINUS_SIGN}?\d+)\*\*")


@pytest.fixture(scope="module")
def design_rows() -> list[dict[str, str]]:
    return table_with_columns(DOCUMENT, HEADING, COLUMNS)


def test_codes_and_names_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    expected = [(number(row["Code"]), literal(row["Name"])) for row in design_rows]
    actual = [(int(code), code.wire_name) for code in ErrorCode]
    assert actual == expected


def test_every_code_has_exactly_one_spec() -> None:
    assert set(ERROR_SPECS) == set(ErrorCode)
    assert all(spec.message for spec in ERROR_SPECS.values())


def test_payload_field_names_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    for row in design_rows:
        code = ErrorCode(number(row["Code"]))
        stated = tuple(field.name for field in parse_payload(row["`data`"]))
        assert ERROR_SPECS[code].field_names == stated, code.wire_name


def test_payload_value_sets_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    """A field whose value the design constrains must carry that constraint here as well.

    A design that started allowing null for a payload field would fail here rather than pass:
    nothing in this contract models a nullable payload field, so the guard refuses the case
    instead of dropping it.
    """
    for row in design_rows:
        code = ErrorCode(number(row["Code"]))
        declared = {field.name: field for field in ERROR_SPECS[code].data_fields}
        for stated in parse_payload(row["`data`"]):
            assert not stated.nullable, f"{code.wire_name}.{stated.name} nullable, not modelled"
            assert declared[stated.name].values == stated.values, f"{code.wire_name}.{stated.name}"


def test_the_closed_sets_are_enums_carrying_exactly_the_designs_values(
    design_rows: list[dict[str, str]],
) -> None:
    """Every multi-valued set is an enum, so no later call site can spell one of its members."""
    stated: dict[str, ParsedField] = {
        f"{literal(row['Name'])}.{field.name}": field
        for row in design_rows
        for field in parse_payload(row["`data`"])
        if len(field.values) > 1
    }
    assert set(stated) == {
        "bad_config.source",
        "bad_merge_target.reason",
        "inactive_row.state",
        "index_failed.stage",
    }
    assert stated["bad_config.source"].values == tuple(BadConfigSource)
    assert stated["bad_merge_target.reason"].values == tuple(BadMergeTargetReason)
    assert stated["inactive_row.state"].values == INACTIVE_ROW_STATES
    assert stated["index_failed.stage"].values == tuple(IndexStage)


def test_every_code_lies_in_the_range_the_design_claims() -> None:
    """The design states its band; the codes must be inside the band it states, not ours."""
    prose = "\n".join(section_lines(DOCUMENT, HEADING))
    claimed = [
        (int(low.replace(MINUS_SIGN, "-")), int(high.replace(MINUS_SIGN, "-")))
        for low, high in _BOLD_RANGE.findall(prose)
    ]
    assert (APPLICATION_CODE_MIN, APPLICATION_CODE_MAX) in claimed
    assert all(APPLICATION_CODE_MIN <= code <= APPLICATION_CODE_MAX for code in ErrorCode)


def test_only_bad_config_may_omit_a_payload_field() -> None:
    """Which fields are optional is stated in the design's prose, not in its `{...}` notation.

    `bad_config` reports a store value, a file value or a derived path, and only the file case
    has a file to name. Every other payload is complete or the raise site is wrong, so the
    transcription below is deliberately exhaustive rather than a spot check.
    """
    optional = {
        f"{code.wire_name}.{field.name}"
        for code, spec in ERROR_SPECS.items()
        for field in spec.data_fields
        if not field.required
    }
    assert optional == {"bad_config.file"}


def test_payload_keys_follow_the_declared_order_whatever_order_they_arrive_in() -> None:
    forwards = ZikaronError(ErrorCode.BAD_SUPERSESSION, uuid="a", target="b", reason="cycle")
    backwards = ZikaronError(ErrorCode.BAD_SUPERSESSION, reason="cycle", target="b", uuid="a")
    assert list(forwards.data) == ["uuid", "target", "reason"]
    assert list(backwards.data) == list(forwards.data)
    assert dict(backwards.data) == dict(forwards.data)


def test_a_fixed_value_is_supplied_rather_than_asked_for() -> None:
    error = ZikaronError(ErrorCode.NO_READ_RECEIPT, uuids=["a", "b"])
    assert dict(error.data) == {
        "uuids": ["a", "b"],
        "hint": "re-read it through fetch or next_group",
    }
    version = ZikaronError(ErrorCode.SCHEMA_INCOMPATIBLE, found=2)
    assert dict(version.data) == {"found": 2, "supported": 1}


def test_a_fixed_value_may_be_passed_but_not_changed() -> None:
    assert ZikaronError(ErrorCode.SCHEMA_INCOMPATIBLE, found=2, supported=1).data["supported"] == 1
    with pytest.raises(ValueError, match="is not one of"):
        ZikaronError(ErrorCode.SCHEMA_INCOMPATIBLE, found=2, supported=2)


def test_a_closed_value_must_match_the_type_it_serializes_as() -> None:
    """`true` and `1.0` are not the integer 1 on the wire, however they compare in Python."""
    with pytest.raises(ValueError, match="is not one of"):
        ZikaronError(ErrorCode.SCHEMA_INCOMPATIBLE, found=2, supported=True)
    with pytest.raises(ValueError, match="is not one of"):
        ZikaronError(ErrorCode.SCHEMA_INCOMPATIBLE, found=2, supported=1.0)


def test_a_non_scalar_where_a_closed_set_is_declared_is_refused() -> None:
    with pytest.raises(ValueError, match=r"bad_config\.source"):
        ZikaronError(ErrorCode.BAD_CONFIG, source=["meta"], key="k", value="v", expected="int >= 1")


def test_a_value_outside_a_closed_set_is_refused() -> None:
    with pytest.raises(ValueError, match=r"bad_config\.source"):
        ZikaronError(
            ErrorCode.BAD_CONFIG,
            source="environment",
            key="rrf_k",
            value="0",
            expected="int >= 1",
        )


def test_inactive_row_state_excludes_live_and_accepts_the_other_two_row_states() -> None:
    """`live` means `active=1`, and `inactive_row` fires only on a row already `active=0` — a
    raise site that named `live` would itself be the bug this payload exists to catch."""
    assert RowState.LIVE not in INACTIVE_ROW_STATES
    assert set(INACTIVE_ROW_STATES) == {RowState.SUPERSEDED, RowState.RETIRED}
    for state in INACTIVE_ROW_STATES:
        error = ZikaronError(ErrorCode.INACTIVE_ROW, uuid="a", state=state)
        assert error.data["state"] == state
    with pytest.raises(ValueError, match=r"inactive_row\.state"):
        ZikaronError(ErrorCode.INACTIVE_ROW, uuid="a", state=RowState.LIVE)


def test_a_closed_set_accepts_its_enum_member_and_its_plain_string() -> None:
    from_enum = ZikaronError(
        ErrorCode.BAD_MERGE_TARGET,
        group_id="g",
        uuid="u",
        reason=BadMergeTargetReason.NOT_AUTHORIZED,
    )
    from_string = ZikaronError(
        ErrorCode.BAD_MERGE_TARGET, group_id="g", uuid="u", reason="not_authorized"
    )
    assert from_enum.data["reason"] == from_string.data["reason"]


def test_an_optional_field_may_be_omitted() -> None:
    error = ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.META,
        key="embed_dim",
        value="0",
        expected="int >= 1",
    )
    assert "file" not in error.data
    assert list(error.data) == ["source", "key", "value", "expected"]


def test_a_missing_required_field_is_a_programming_error() -> None:
    with pytest.raises(TypeError, match="missing=\\['state'\\]"):
        ZikaronError(ErrorCode.INACTIVE_ROW, uuid="a")


def test_a_field_the_code_does_not_carry_is_a_programming_error() -> None:
    with pytest.raises(TypeError, match="unknown=\\['gist'\\]"):
        ZikaronError(ErrorCode.NOT_FOUND, uuid="a", gist="leaked")


def test_the_exception_text_names_the_code() -> None:
    error = ZikaronError(ErrorCode.STORE_BUSY, verb="amend")
    assert (
        str(error)
        == "store_busy: the store was locked; the call did not proceed and may be retried"
    )
    assert error.code is ErrorCode.STORE_BUSY
    assert error.message == ERROR_SPECS[ErrorCode.STORE_BUSY].message


def test_a_spec_cannot_declare_one_field_twice() -> None:
    with pytest.raises(ValueError, match="declares a field twice"):
        ErrorSpec("nonsense", (PayloadField("uuid"), PayloadField("uuid")))


def test_only_a_single_valued_field_counts_as_a_constant() -> None:
    assert PayloadField("hint", values=("re-read it through fetch or next_group",)).is_constant
    assert not PayloadField("source", values=("meta", "file")).is_constant
    assert not PayloadField("uuid").is_constant
