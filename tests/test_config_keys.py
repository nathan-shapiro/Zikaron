"""The configuration schema, checked against `design/schema.md` §"Configuration keys".

Two facts are read from `design/architecture.md` instead, because that is where the design
states them: which keys are coupled to what the store already contains, and how severely.
"""

from enum import Enum, IntEnum, StrEnum

import pytest

from tests.design_tables import (
    EN_DASH,
    couplings,
    literal,
    table_with_columns,
    toml_block,
)
from zikaron.core.config.keys import (
    CONFIG_KEYS,
    CONFIG_KEYS_BY_NAME,
    ConfigBounds,
    ConfigKey,
    ConfigSection,
    ConfigUnit,
    FloatBounds,
    IntBounds,
    StoreCoupling,
    StringBounds,
    _index_by_name,
)

DOCUMENT = "schema.md"
HEADING = "## Configuration keys"
COLUMNS = ("Section", "Key", "Type", "Range", "Default", "Notes")
COUPLING_DOCUMENT = "architecture.md"
COUPLING_HEADING = "### What the file cannot change *silently*: the store-coupled keys"

_UNCONSTRAINED = {"\u2014", "\u2013", "-"}
_AT_LEAST = "\u2265"


@pytest.fixture(scope="module")
def design_rows() -> list[dict[str, str]]:
    return table_with_columns(DOCUMENT, HEADING, COLUMNS)


@pytest.fixture(scope="module")
def design_sample() -> dict[str, dict[str, object]]:
    return toml_block(DOCUMENT, HEADING)


def _expected_bounds(type_cell: str, range_cell: str) -> ConfigBounds:
    """Turn the design's type and range columns into the bounds they describe.

    Every form the design actually uses is handled and anything else raises, so a new notation
    has to be read by a person rather than being quietly approximated by the nearest match.
    """
    declared = literal(type_cell)
    text = literal(range_cell)
    if declared.endswith("string"):
        if text != "non-empty" and text not in _UNCONSTRAINED:
            raise AssertionError(f"unrecognized string range {text!r}")
        return StringBounds(non_empty=text == "non-empty")
    if declared.endswith("float"):
        low, high = (part.strip() for part in text[1:-1].split(","))
        return FloatBounds(
            float(low),
            float(high),
            minimum_inclusive=text.startswith("["),
            maximum_inclusive=text.endswith("]"),
        )
    if not declared.endswith("int"):
        raise AssertionError(f"unrecognized type {declared!r}")
    if text.startswith(_AT_LEAST):
        return IntBounds(int(text.removeprefix(_AT_LEAST)))
    if EN_DASH not in text:
        raise AssertionError(f"unrecognized int range {text!r}")
    low, high = text.split(EN_DASH)
    return IntBounds(int(low), int(high))


def _expected_unit(type_cell: str, name: str) -> ConfigUnit:
    """The unit the design gives a key, from its type column or, failing that, its own name."""
    declared = literal(type_cell)
    if "seconds" in declared:
        return ConfigUnit.SECONDS
    if "bytes" in declared:
        return ConfigUnit.BYTES
    if name.endswith("_days"):
        return ConfigUnit.DAYS
    return ConfigUnit.NONE


def test_sections_and_names_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    expected = [(literal(row["Section"]), literal(row["Key"])) for row in design_rows]
    actual = [(key.section.value, key.name) for key in CONFIG_KEYS]
    assert actual == expected


def test_every_section_the_design_uses_is_a_declared_section(
    design_rows: list[dict[str, str]],
) -> None:
    used = {literal(row["Section"]) for row in design_rows}
    assert used == {section.value for section in ConfigSection}


def test_types_and_ranges_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    for row, key in zip(design_rows, CONFIG_KEYS, strict=True):
        assert key.bounds == _expected_bounds(row["Type"], row["Range"]), key.toml_path


def test_units_match_the_design_table(design_rows: list[dict[str, str]]) -> None:
    for row, key in zip(design_rows, CONFIG_KEYS, strict=True):
        assert key.unit == _expected_unit(row["Type"], key.name), key.toml_path


def test_defaults_match_the_design_sample(design_sample: dict[str, dict[str, object]]) -> None:
    """The sample file is the design's own statement of every default, in its own syntax."""
    flattened = {
        (section, name): value
        for section, keys in design_sample.items()
        for name, value in keys.items()
    }
    actual = {(key.section.value, key.name): key.default for key in CONFIG_KEYS}
    assert actual == flattened
    for key in CONFIG_KEYS:
        sampled = flattened[key.section.value, key.name]
        assert type(sampled) is key.value_type, key.toml_path


def test_the_designs_two_statements_of_each_default_agree(
    design_rows: list[dict[str, str]],
    design_sample: dict[str, dict[str, object]],
) -> None:
    """The table quotes each default and so does the sample file; they must not disagree.

    `embed_prefix_query` is the one key whose table cell describes its default instead of
    quoting it, precisely because the value ends in a space that a table cell would swallow.
    """
    for row in design_rows:
        name = literal(row["Key"])
        sampled = design_sample[literal(row["Section"])][name]
        cell = literal(row["Default"])
        if name == "embed_prefix_query":
            assert "trailing space" in row["Default"]
            continue
        if isinstance(sampled, float):
            assert float(cell) == sampled, name
        elif isinstance(sampled, int):
            assert int(cell) == sampled, name
        else:
            assert cell == sampled, name


def test_store_coupling_matches_the_design() -> None:
    severities = couplings(COUPLING_DOCUMENT, COUPLING_HEADING)
    expected = {name: StoreCoupling(severity) for name, severity in severities.items()}
    actual = {
        key.name: key.store_coupling
        for key in CONFIG_KEYS
        if key.store_coupling is not StoreCoupling.NONE
    }
    assert actual == expected


def test_key_names_are_unique_across_the_whole_schema() -> None:
    assert len(CONFIG_KEYS_BY_NAME) == len(CONFIG_KEYS)
    assert all(CONFIG_KEYS_BY_NAME[key.name] is key for key in CONFIG_KEYS)


def test_a_key_name_used_in_two_sections_is_refused() -> None:
    clash = ConfigKey(ConfigSection.SERVICE, "rrf_k", IntBounds(1), 60)
    with pytest.raises(ValueError, match="used twice"):
        _index_by_name((*CONFIG_KEYS, clash))


def test_the_query_prefix_keeps_its_trailing_space() -> None:
    """The prefix is concatenated with the query, so the space is part of the value."""
    prefix = CONFIG_KEYS_BY_NAME["embed_prefix_query"].default
    assert isinstance(prefix, str)
    assert prefix.endswith(": ")


def test_toml_path_is_section_then_name() -> None:
    assert CONFIG_KEYS_BY_NAME["rrf_k"].toml_path == "retrieval.rrf_k"


def test_an_int_bound_open_above_accepts_anything_at_or_over_its_minimum() -> None:
    bounds = IntBounds(1)
    assert not bounds.permits(0)
    assert bounds.permits(1)
    assert bounds.permits(10**9)


def test_a_closed_int_bound_rejects_both_ends_outward() -> None:
    bounds = IntBounds(64, 8192)
    assert not bounds.permits(63)
    assert bounds.permits(64)
    assert bounds.permits(8192)
    assert not bounds.permits(8193)


def test_a_float_bounds_ends_are_open_or_closed_independently() -> None:
    half_open = FloatBounds(0.0, 1.0, minimum_inclusive=False, maximum_inclusive=True)
    assert not half_open.permits(0.0)
    assert half_open.permits(1.0)
    closed = FloatBounds(0.0, 1.0, minimum_inclusive=True, maximum_inclusive=True)
    assert closed.permits(0.0)
    assert closed.permits(1.0)
    assert not closed.permits(1.0000001)


def test_a_non_empty_string_bound_rejects_only_the_empty_string() -> None:
    assert not StringBounds(non_empty=True).permits("")
    assert StringBounds(non_empty=True).permits(" ")
    assert StringBounds(non_empty=False).permits("")


def test_acceptance_is_strict_about_type() -> None:
    """A wrong TOML type is a configuration error, so it must not pass as a coercible value."""
    depth = CONFIG_KEYS_BY_NAME["fusion_depth"]
    assert depth.accepts(50)
    assert not depth.accepts(50.0)
    assert not depth.accepts("50")
    # bool subclasses int, so `fusion_depth = true` would otherwise be accepted as 1.
    assert not depth.accepts(True)
    threshold = CONFIG_KEYS_BY_NAME["dedup_threshold"]
    assert threshold.accepts(0.5)
    assert not threshold.accepts(1)
    model = CONFIG_KEYS_BY_NAME["embed_model"]
    assert model.accepts("x")
    assert not model.accepts("")
    assert not model.accepts(1)


def test_acceptance_rejects_a_subclass_carrying_its_own_meaning() -> None:
    """An in-range value of the right base type is still wrong if it is not that plain type."""

    class Depth(IntEnum):
        MEASURED = 50

    class Label(StrEnum):
        MODEL = "BAAI/bge-small-en-v1.5"

    class Fraction(float, Enum):
        HALF = 0.5

    assert not CONFIG_KEYS_BY_NAME["fusion_depth"].accepts(Depth.MEASURED)
    assert not CONFIG_KEYS_BY_NAME["embed_model"].accepts(Label.MODEL)
    assert not CONFIG_KEYS_BY_NAME["dedup_threshold"].accepts(Fraction.HALF)


def test_acceptance_applies_the_range_as_well_as_the_type() -> None:
    depth = CONFIG_KEYS_BY_NAME["fusion_depth"]
    assert not depth.accepts(0)
    assert not depth.accepts(501)


def test_a_default_of_the_wrong_type_is_refused_at_construction() -> None:
    with pytest.raises(TypeError, match="is not int"):
        ConfigKey(ConfigSection.SERVICE, "nonsense", IntBounds(1), "60")


def test_a_default_outside_its_own_range_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="out of range"):
        ConfigKey(ConfigSection.SERVICE, "nonsense", IntBounds(60, 86400), 59)


def test_value_type_comes_from_the_bounds() -> None:
    assert CONFIG_KEYS_BY_NAME["rrf_k"].value_type is int
    assert CONFIG_KEYS_BY_NAME["retired_penalty"].value_type is float
    assert CONFIG_KEYS_BY_NAME["embed_model"].value_type is str
