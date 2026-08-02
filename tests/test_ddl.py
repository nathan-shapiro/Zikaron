"""The schema DDL, checked statement-by-statement against `design/schema.md` §Tables.

The design states the whole schema as one fenced SQL block rather than a markdown table, so this
guard reads that fence and splits it into statements the same way `ddl.py` does, then compares
the two statement lists directly — an edit to either side that adds, removes or reorders a
statement fails a test here, which is what makes "the DDL matches the design" a checked claim.
"""

import re

import pytest

from tests.design_tables import (
    DesignTableError,
    normalize_sql,
    parse_fenced_code,
    section_lines,
    sql_statements,
)
from zikaron.core.store.ddl import FIXED_STATEMENTS, PRAGMAS, memory_vec_statement

DOCUMENT = "schema.md"
HEADING = "## Tables"

_EMBED_DIM_TEMPLATE = re.compile(r"<embed_dim>")


@pytest.fixture(scope="module")
def design_statements() -> list[str]:
    fenced = parse_fenced_code(section_lines(DOCUMENT, HEADING), "sql")
    return sql_statements(fenced)


def _split_pragmas_and_ddl(statements: list[str]) -> tuple[list[str], list[str]]:
    pragmas = [statement for statement in statements if statement.upper().startswith("PRAGMA")]
    rest = [statement for statement in statements if not statement.upper().startswith("PRAGMA")]
    return pragmas, rest


def test_the_three_pragmas_match_the_design_exactly(design_statements: list[str]) -> None:
    design_pragmas, _ = _split_pragmas_and_ddl(design_statements)
    assert [normalize_sql(p) for p in PRAGMAS] == design_pragmas


def test_every_fixed_statement_appears_in_the_design_in_the_same_order(
    design_statements: list[str],
) -> None:
    """`memory_vec`'s statement is a template in the design and is checked separately below —
    every other statement is compared verbatim, in the design's own order, since the DDL's
    foreign keys make execution order load-bearing rather than cosmetic."""
    _, design_ddl = _split_pragmas_and_ddl(design_statements)
    design_without_vec_table = [
        statement for statement in design_ddl if "memory_vec" not in statement
    ]
    assert [normalize_sql(s) for s in FIXED_STATEMENTS] == design_without_vec_table


def test_the_design_states_exactly_one_memory_vec_template_statement(
    design_statements: list[str],
) -> None:
    _, design_ddl = _split_pragmas_and_ddl(design_statements)
    vec_statements = [statement for statement in design_ddl if "memory_vec" in statement]
    assert len(vec_statements) == 1
    assert _EMBED_DIM_TEMPLATE.search(vec_statements[0])


def test_memory_vec_statement_substitutes_the_designs_template_exactly(
    design_statements: list[str],
) -> None:
    _, design_ddl = _split_pragmas_and_ddl(design_statements)
    (template,) = [statement for statement in design_ddl if "memory_vec" in statement]
    expected = _EMBED_DIM_TEMPLATE.sub("384", template)
    assert normalize_sql(memory_vec_statement(384)) == expected


@pytest.mark.parametrize("embed_dim", [1, 8, 384, 768, 4096])
def test_memory_vec_statement_accepts_any_width_at_least_one(embed_dim: int) -> None:
    statement = memory_vec_statement(embed_dim)
    assert f"float[{embed_dim}]" in statement
    assert "CREATE VIRTUAL TABLE memory_vec USING vec0" in statement


@pytest.mark.parametrize("embed_dim", [0, -1, -384])
def test_memory_vec_statement_refuses_a_width_below_one(embed_dim: int) -> None:
    with pytest.raises(ValueError, match="embed_dim must be"):
        memory_vec_statement(embed_dim)


def test_fixed_statements_create_every_table_the_design_names_except_memory_vec(
    design_statements: list[str],
) -> None:
    """A coarser check than the statement-for-statement comparison above: every table name the
    design's `CREATE TABLE`/`CREATE VIRTUAL TABLE` statements introduce must appear somewhere in
    `FIXED_STATEMENTS`, so a table silently dropped from one list but not the other cannot pass
    by the two lists merely being the same length."""
    table_name = re.compile(r"CREATE (?:VIRTUAL )?TABLE (\w+)")
    _, design_ddl = _split_pragmas_and_ddl(design_statements)
    design_tables = {
        match.group(1) for statement in design_ddl for match in table_name.finditer(statement)
    }
    coded_tables = {
        match.group(1) for statement in FIXED_STATEMENTS for match in table_name.finditer(statement)
    }
    assert coded_tables == design_tables - {"memory_vec"}


# ---------------------------------------------------------------------------
# The parser itself: normalization must remove formatting differences without ever
# collapsing two statements that actually differ. `design_tables.py`'s own docstring names this
# failure shape explicitly — a reader that returns a plausible answer is worse than one that
# returns nothing, because it stops the comparison from ever failing again.
# ---------------------------------------------------------------------------


def test_normalize_sql_is_insensitive_to_line_wrapping_around_parens_and_commas() -> None:
    wrapped = "CHECK (x IN (\n  'a',\n  'b'\n))"
    flat = "CHECK (x IN ('a', 'b'))"
    assert normalize_sql(wrapped) == normalize_sql(flat)


def test_normalize_sql_does_not_collapse_a_changed_enum_value() -> None:
    original = "CHECK (x IN ('a', 'b'))"
    changed = "CHECK (x IN ('a', 'c'))"
    assert normalize_sql(original) != normalize_sql(changed)


def test_normalize_sql_does_not_collapse_a_missing_column() -> None:
    two_columns = "CREATE TABLE t (a INT, b INT)"
    one_column = "CREATE TABLE t (a INT)"
    assert normalize_sql(two_columns) != normalize_sql(one_column)


def test_normalize_sql_does_not_collapse_a_reordered_clause() -> None:
    first = "CREATE TABLE t (a INT, b INT)"
    reordered = "CREATE TABLE t (b INT, a INT)"
    assert normalize_sql(first) != normalize_sql(reordered)


def test_normalize_sql_preserves_whitespace_inside_a_string_literal() -> None:
    """`'a  b'` (two spaces) and `'a b'` (one space) are different string values, and the
    formatting-insensitivity normalize_sql exists for must never reach inside a literal."""
    two_spaces = "CHECK (x = 'a  b')"
    one_space = "CHECK (x = 'a b')"
    assert normalize_sql(two_spaces) != normalize_sql(one_space)
    assert "'a  b'" in normalize_sql(two_spaces)


def test_normalize_sql_preserves_a_paren_inside_a_string_literal() -> None:
    """A literal `(` is part of the string's own bytes, not a structural character — collapsing
    the whitespace beside it the way a real `(` gets collapsed would silently rewrite data."""
    with_paren_space = "CHECK (x = 'a( b')"
    assert "'a( b'" in normalize_sql(with_paren_space)


def test_sql_statements_preserves_a_semicolon_inside_a_string_literal() -> None:
    """A `;` inside a string is part of the value, not a statement terminator — splitting on it
    would cut one statement's literal in half and produce two syntactically broken halves."""
    block = "CREATE TABLE t (a TEXT DEFAULT 'x;y')"
    assert sql_statements(block) == ["CREATE TABLE t (a TEXT DEFAULT 'x;y')"]


def test_sql_statements_preserves_parens_inside_a_string_literal() -> None:
    """A literal containing unbalanced parens must not desynchronize the real depth counter —
    the string `'a('` has one unmatched `(` that names no structure at all."""
    block = "CREATE TABLE t (a TEXT DEFAULT 'a(', b INT)"
    assert sql_statements(block) == ["CREATE TABLE t (a TEXT DEFAULT 'a(', b INT)"]


def test_sql_statements_preserves_a_multiline_string_literals_internal_whitespace() -> None:
    """`DEFAULT 'a\\n  b'` (two leading spaces on the wrapped line) and `DEFAULT 'a\\nb'` (none)
    are different string values — the wrapping-insensitivity this module exists to provide must
    not reach across a line break that sits *inside* an open string."""
    two_spaces = "CREATE TABLE t (a TEXT DEFAULT 'a\n  b')"
    no_spaces = "CREATE TABLE t (a TEXT DEFAULT 'a\nb')"
    assert sql_statements(two_spaces) != sql_statements(no_spaces)
    assert sql_statements(two_spaces) == ["CREATE TABLE t (a TEXT DEFAULT 'a\n  b')"]


def test_sql_statements_preserves_trailing_whitespace_on_the_line_a_string_opens_on() -> None:
    """The opposite half of the case above: a line that starts *outside* a string, opens one
    partway through, and has trailing whitespace after the quote — that whitespace is inside
    the now-open literal, not a line-wrap artefact, even though the line itself began outside
    any string. Stripping decided from a single start-of-line flag gets exactly this case
    wrong, because the flag says "outside" while the trailing bytes are already "inside"."""
    with_trailing_space = "CREATE TABLE t (a TEXT DEFAULT 'a  \n b')"
    assert sql_statements(with_trailing_space) == ["CREATE TABLE t (a TEXT DEFAULT 'a  \n b')"]


def test_sql_statements_preserves_a_blank_line_inside_a_multiline_string_literal() -> None:
    """A wholly blank line sitting between two non-blank lines of one open string is itself
    part of the literal's value — the `\\n\\n` it represents — and must not be dropped the way
    an ordinary blank line between two statements is."""
    block = "CREATE TABLE t (a TEXT DEFAULT 'a\n\nb')"
    assert sql_statements(block) == ["CREATE TABLE t (a TEXT DEFAULT 'a\n\nb')"]


def test_sql_statements_produces_no_spurious_statement_after_a_mid_line_semicolon() -> None:
    """A single line can both ENTER already inside a string (opened on a previous line) and
    later, on that same line, close it, open and close a second string, and terminate the
    statement with a top-level semicolon — after which nothing else follows on that line. The
    empty text after the semicolon must not survive as a spurious second, empty statement: the
    fact that the LINE entered inside a string says nothing about whether the fresh, empty
    segment that begins immediately after the semicolon did."""
    block = "'a\nb' || 'c';"
    assert sql_statements(block) == ["'a\nb' || 'c'"]


def test_sql_statements_splits_on_a_blank_line_between_statements() -> None:
    block = "CREATE TABLE a (x INT)\n\nCREATE TABLE b (y INT)"
    assert sql_statements(block) == ["CREATE TABLE a (x INT)", "CREATE TABLE b (y INT)"]


def test_sql_statements_splits_on_a_top_level_semicolon_with_no_blank_line() -> None:
    block = "PRAGMA a = 1; PRAGMA b = 2;"
    assert sql_statements(block) == ["PRAGMA a = 1", "PRAGMA b = 2"]


def test_sql_statements_does_not_split_inside_an_open_paren() -> None:
    """A semicolon or blank line genuinely cannot appear here, but the depth counter must not
    treat one hidden inside a multi-line CHECK's own indentation as a split point."""
    block = "CREATE TABLE t (\n  a INT,\n\n  b INT\n)"
    assert sql_statements(block) == ["CREATE TABLE t (a INT, b INT)"]


def test_sql_statements_strips_line_comments() -> None:
    block = "CREATE TABLE t (\n  a INT -- a comment with a ( paren\n)"
    assert sql_statements(block) == ["CREATE TABLE t (a INT)"]


def test_sql_statements_refuses_unbalanced_parentheses() -> None:
    with pytest.raises(DesignTableError, match="unbalanced"):
        sql_statements("CREATE TABLE t (a INT))")


def test_sql_statements_refuses_a_block_ending_still_open() -> None:
    with pytest.raises(DesignTableError, match="unbalanced"):
        sql_statements("CREATE TABLE t (a INT")


def test_parse_fenced_code_refuses_two_blocks_of_the_same_language() -> None:
    section = ["```sql", "SELECT 1", "```", "", "```sql", "SELECT 2", "```"]
    with pytest.raises(DesignTableError, match="2 fenced sql blocks"):
        parse_fenced_code(section, "sql")


def test_parse_fenced_code_refuses_zero_blocks_of_the_requested_language() -> None:
    section = ["```toml", "x = 1", "```"]
    with pytest.raises(DesignTableError, match="0 fenced sql blocks"):
        parse_fenced_code(section, "sql")


def test_parse_fenced_code_ignores_a_block_tagged_with_a_different_language() -> None:
    section = ["```python", "x = 1", "```", "", "```sql", "SELECT 1", "```"]
    assert parse_fenced_code(section, "sql") == "SELECT 1"


def test_parse_fenced_code_refuses_an_unterminated_fence() -> None:
    section = ["```sql", "SELECT 1"]
    with pytest.raises(DesignTableError, match="never closed"):
        parse_fenced_code(section, "sql")
