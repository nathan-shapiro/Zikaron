"""The design readers themselves.

Everything else in this suite trusts these readers, so their failure mode matters more than
their success. Two ways they could betray it: returning nothing for a document they could not
understand, which makes every drift guard pass unconditionally; or returning something
*plausible* for an ambiguous one, which leaves the suite checking a table nobody is maintaining.
Both are tested here, on literal input rather than on the real corpus, so the malformed cases are
hermetic and the real documents stay untouched.
"""

import pytest

from tests.design_tables import (
    DesignTableError,
    literal,
    number,
    parse_block_quote,
    parse_couplings,
    parse_field_values,
    parse_name_lists,
    parse_payload,
    parse_section,
    parse_tables,
    parse_toml,
    section_lines,
    table_with_columns,
    tables,
)


def lines(text: str) -> list[str]:
    return text.strip("\n").splitlines()


TABLE = lines(
    """
## Codes

| Code | Name |
|---|---|
| -1 | `alpha` |
| -2 | `beta` |
"""
)


def test_a_section_yields_its_own_lines_only() -> None:
    body = parse_section(lines("## A\nfirst\n## B\nsecond"), "## A")
    assert body == ["first"]


def test_a_deeper_heading_stays_inside_the_section() -> None:
    body = parse_section(lines("## A\n### A1\nnested\n## B\nsecond"), "## A")
    assert body == ["### A1", "nested"]


def test_a_missing_heading_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="no heading"):
        parse_section(lines("## A\nfirst"), "## B")


def test_a_heading_repeated_with_only_deeper_ones_between_is_an_error() -> None:
    """The two sections would otherwise be concatenated and read as one."""
    with pytest.raises(DesignTableError, match="more than once"):
        parse_section(lines("## A\nfirst\n### A1\nx\n## A\nsecond"), "## A")


def test_a_heading_repeated_later_in_the_document_is_an_error() -> None:
    """A revised section beside the one it revises must not silently read as the stale copy."""
    with pytest.raises(DesignTableError, match="more than once"):
        parse_section(lines("## A\nfirst\n## B\nx\n## A\nsecond"), "## A")


def test_a_heading_inside_a_fence_is_text() -> None:
    body = parse_section(lines("## A\n```toml\n# not a heading\n```\nafter\n## B"), "## A")
    assert body == ["```toml", "# not a heading", "```", "after"]


def test_a_table_is_keyed_by_its_column_headings() -> None:
    (table,) = parse_tables(TABLE)
    assert table == [{"Code": "-1", "Name": "`alpha`"}, {"Code": "-2", "Name": "`beta`"}]


def test_two_tables_in_one_section_are_kept_apart() -> None:
    found = parse_tables(lines("| A |\n|---|\n| 1 |\n\ntext\n\n| B |\n|---|\n| 2 |"))
    assert found == [[{"A": "1"}], [{"B": "2"}]]


def test_a_table_with_no_rows_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="no rows"):
        parse_tables(lines("| A |\n|---|"))


def test_a_blank_column_name_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="blank column name"):
        parse_tables(lines("| A | |\n|---|---|\n| 1 | 2 |"))


def test_a_repeated_column_name_is_an_error() -> None:
    """Keying rows by heading would silently drop one of two columns of the same name."""
    with pytest.raises(DesignTableError, match="repeats a column name"):
        parse_tables(lines("| A | A |\n|---|---|\n| 1 | 2 |"))


def test_a_delimiter_of_the_wrong_width_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="delimiter has"):
        parse_tables(lines("| A | B |\n|---|\n| 1 | 2 |"))


def test_a_missing_delimiter_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="not a delimiter"):
        parse_tables(lines("| A |\n| 1 |\n| 2 |"))


def test_a_short_row_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="row has 1 cells"):
        parse_tables(lines("| A | B |\n|---|---|\n| 1 |"))


def test_an_escaped_pipe_stays_inside_its_cell() -> None:
    (table,) = parse_tables(lines("| A | B |\n|---|---|\n| x \\| y | z |"))
    assert table == [{"A": "x | y", "B": "z"}]


def test_toml_that_nests_too_deep_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="nests deeper"):
        parse_toml(lines("```toml\n[a.b]\nc = 1\n```"))


def test_a_second_toml_sample_is_an_error_even_when_the_first_still_agrees() -> None:
    """The stale-read case: reading the first block would agree with the code and be wrong.

    A revised sample added beside the one it revises is the way a defaults guard goes on passing
    while the design has moved. The first block below is what the code holds; the second is not.
    """
    section = lines("```toml\n[a]\nb = 60\n```\n\nprose\n\n```toml\n[a]\nb = 30\n```")
    assert parse_toml(lines("```toml\n[a]\nb = 60\n```")) == {"a": {"b": 60}}
    with pytest.raises(DesignTableError, match="2 fenced toml blocks"):
        parse_toml(section)


def test_an_unclosed_toml_fence_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="never closed"):
        parse_toml(lines("```toml\n[a]\nb = 1"))


def test_a_bare_toml_key_outside_a_section_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="not a section"):
        parse_toml(lines("```toml\na = 1\n```"))


def test_an_empty_toml_block_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="toml block is empty"):
        parse_toml(lines("```toml\n# nothing\n```"))


def test_a_section_with_no_toml_block_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="0 fenced toml blocks"):
        parse_toml(lines("prose only"))


def test_a_toml_block_keeps_a_trailing_space_inside_a_string() -> None:
    parsed = parse_toml(lines('```toml\n[a]\nb = "x: "\n```'))
    assert parsed == {"a": {"b": "x: "}}


def test_a_cell_holding_a_literal_is_unwrapped() -> None:
    assert literal(" `not_found` ") == "not_found"
    assert literal(" **64** ") == "64"
    assert number(" \u221232000 ") == -32000


def test_a_payload_group_ignores_the_prose_that_follows_it() -> None:
    cell = "`{group_id, uuids}` \u2014 **uuids only**; no state, {not, a, payload}"
    assert [field.name for field in parse_payload(cell)] == ["group_id", "uuids"]


def test_a_stated_value_set_is_read_off_the_field() -> None:
    (role, count) = parse_payload("{role:'target'|'absorbed', n}")
    assert (role.name, role.values, role.nullable) == ("role", ("target", "absorbed"), False)
    assert (count.name, count.values) == ("n", ())


def test_null_among_the_values_is_recorded_separately() -> None:
    (field,) = parse_payload("{demotion:'superseded'|'retired'|null}")
    assert field.values == ("superseded", "retired")
    assert field.nullable


def test_an_unquoted_number_is_a_value_of_its_own_type() -> None:
    (_, supported) = parse_payload("{found, supported: 1}")
    assert supported.values == (1,)


def test_an_illustrated_shape_is_not_mistaken_for_a_value() -> None:
    (field,) = parse_payload("{current: [{...}]}")
    assert field.values == ()


def test_a_set_stated_beside_the_group_is_read_too() -> None:
    fields = parse_payload("`{uuid, reason}` with `reason \u2208 not_authorized | not_targetable`")
    assert fields[1].values == ("not_authorized", "not_targetable")


def test_a_set_stated_for_a_field_outside_the_group_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="constrained but not in the payload"):
        parse_payload("`{uuid}` with `state \u2208 live | retired`")


def test_a_cell_with_no_payload_group_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="no payload group"):
        parse_payload("NULL")


def test_an_unbalanced_payload_group_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="unbalanced brackets"):
        parse_payload("{group_id, uuids")


def test_a_crossed_payload_group_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="crossed brackets"):
        parse_payload("{uuids: [a}]")


def test_a_value_table_continues_under_a_blank_name() -> None:
    table = [
        {"Field": "`a`", "Values": "`'one'`"},
        {"Field": "", "Values": "`'two'`"},
        {"Field": "`b`", "Values": "`'one'` | `'two'`"},
    ]
    assert parse_field_values(table, "Field", "Values") == {
        "a": ("one", "two"),
        "b": ("one", "two"),
    }


def test_a_value_row_before_any_field_name_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="precedes any field name"):
        parse_field_values([{"Field": "", "Values": "`'one'`"}], "Field", "Values")


def test_a_stray_opening_fence_cannot_hide_a_later_duplicate_heading() -> None:
    """The stale-read case: everything before the stray fence parses, so nothing looks wrong.

    Without refusing the unterminated fence, the second `## A` is invisible and the first — which
    is exactly what the code already agrees with — is returned as though it were the only one.
    """
    hidden = lines("## A\nfirst\n## B\n```\n## A\nsecond")
    with pytest.raises(DesignTableError, match="never closed"):
        parse_section(hidden, "## A")


def test_couplings_that_classify_one_key_twice_are_an_error() -> None:
    """The first bullet agrees with the code, so document order would resolve the clash away."""
    section = lines("- **Hard — `k`.** one\n- **Soft — `k`.** two")
    with pytest.raises(DesignTableError, match="more than one bullet"):
        parse_couplings(section)


def test_couplings_without_bullets_are_an_error() -> None:
    with pytest.raises(DesignTableError, match="no store-coupling"):
        parse_couplings(lines("prose with no bullets"))


def test_a_field_constrained_twice_beside_its_group_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="constrained twice in one cell"):
        parse_payload("`{reason}` with `reason \u2208 a | b` and `reason \u2208 c | d`")


def test_a_field_constrained_both_inside_and_beside_its_group_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="in and beside the group"):
        parse_payload("`{reason:'a'|'b'}` with `reason \u2208 c | d`")


def test_a_name_list_table_maps_each_key_to_its_names() -> None:
    table = [
        {"kind": "`surface`", "fields": "`demotion`"},
        {"kind": "`merge`", "fields": "`token_count`, `truncated`"},
    ]
    assert parse_name_lists(table, "kind", "fields") == {
        "surface": ("demotion",),
        "merge": ("token_count", "truncated"),
    }


def test_a_name_list_table_that_repeats_a_key_is_an_error() -> None:
    """Two rows for one key either contradict or split it, and reading one loses half the rule."""
    table = [{"k": "`a`", "f": "`x`"}, {"k": "`a`", "f": "`y`"}]
    with pytest.raises(DesignTableError, match="two rows"):
        parse_name_lists(table, "k", "f")


def test_a_name_list_row_with_no_key_or_no_names_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="has no key"):
        parse_name_lists([{"k": "", "f": "`x`"}], "k", "f")
    with pytest.raises(DesignTableError, match="lists no names"):
        parse_name_lists([{"k": "`a`", "f": ""}], "k", "f")


def test_a_reader_names_the_document_and_heading_it_failed_on() -> None:
    with pytest.raises(DesignTableError, match=r"schema\.md / ## No Such Section"):
        section_lines("schema.md", "## No Such Section")


def test_a_missing_document_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="no design document"):
        section_lines("no-such-document.md", "## Errors")


def test_a_section_with_no_table_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="found no table"):
        tables("coding-standards.md", "## 1. Structure")


def test_a_table_is_found_by_its_columns_rather_than_its_position() -> None:
    """The event section carries several tables, so position would be an accident of drafting."""
    stop_reasons = table_with_columns(
        "schema.md", "## The `event` log, per kind", ("Field", "Values", "Meaning")
    )
    assert any("stop_reason" in row["Field"] for row in stop_reasons)


def test_columns_that_match_no_table_are_an_error() -> None:
    with pytest.raises(DesignTableError, match="0 tables with columns"):
        table_with_columns("architecture.md", "## Errors", ("Code", "Name"))


QUOTES = lines(
    """
## A

> first quote
> second line

between

> other quote
> tail
"""
)


def test_a_block_quote_is_found_by_the_words_it_opens_with() -> None:
    assert parse_block_quote(QUOTES, "first quote") == "first quote\nsecond line"
    assert parse_block_quote(QUOTES, "other quote") == "other quote\ntail"


def test_a_quote_marker_with_no_space_after_it_is_still_a_quote() -> None:
    """Markdown allows `>text`, and a parser that required `> ` would silently see a shorter
    quote — which is the failure this module exists to prevent, since the guard would keep
    passing against whatever fragment it did find."""
    assert parse_block_quote(lines("## A\n>bare\n> spaced"), "bare") == "bare\nspaced"


def test_a_quote_running_to_the_end_of_a_section_is_closed() -> None:
    """A section whose last line is quoted has no following blank to close on, so the block is
    collected on the way out rather than discarded."""
    assert parse_block_quote(lines("## A\nprose\n> last thing"), "last thing") == "last thing"


def test_a_quote_inside_a_fence_is_not_a_quote() -> None:
    """This corpus keeps withdrawn text rather than deleting it, so a fenced historical copy of a
    quote can sit beside the live one. Reading through the fence would let the copy satisfy the
    exactly-one rule if the live quote were ever removed, leaving a guard comparing a shipped
    artifact against an archive — and still passing."""
    section = lines("## A\n```\n> same words\n```\n\n> same words live\n")
    assert parse_block_quote(section, "same words") == "same words live"


def test_two_quotes_inside_fences_leave_nothing_to_find() -> None:
    """The other half of the same property: masking has to remove them, not merely deprioritize
    them, or the error would report a count drawn from archived text."""
    with pytest.raises(DesignTableError, match="0 block quotes"):
        parse_block_quote(lines("## A\n```\n> gone\n```\n```\n> gone\n```\n"), "gone")


def test_a_fence_between_two_quotes_does_not_join_them() -> None:
    """A fence boundary ends a quote, so two runs separated only by an empty fence stay two.
    Passing over fence lines without closing the open run would splice them into a block the
    document does not contain, reported under an opening that it does."""
    section = lines("## A\n> live quote\n```\n```\n> second run\n")
    assert parse_block_quote(section, "live quote") == "live quote"
    assert parse_block_quote(section, "second run") == "second run"


def test_an_opening_that_matches_no_quote_is_an_error() -> None:
    with pytest.raises(DesignTableError, match="0 block quotes"):
        parse_block_quote(QUOTES, "third quote")


def test_an_opening_that_matches_two_quotes_is_an_error() -> None:
    """Ambiguity is refused rather than resolved by position: a second quote opening the same way
    is exactly the case where taking the first would leave a guard pointed at the wrong block."""
    with pytest.raises(DesignTableError, match="2 block quotes"):
        parse_block_quote(lines("## A\n> same\n\ntext\n\n> same\n"), "same")
