"""The knowledge index's two schemas, checked against the design documents that state them.

One table lives in `memory.db` and is specified by `schema.md`; the rest live in each knowledge
base's own file and are specified by `knowledge-index.md`. Both are read out of the documents
themselves rather than compared against a second hand-written copy, because the likelier drift is
the design being revised while the code stays put.
"""

import re

import pytest

from tests.design_tables import normalize_sql, parse_fenced_code, section_lines, sql_statements
from zikaron.core.knowledge.ddl import FIXED_STATEMENTS, PRAGMAS, chunks_vec_statement
from zikaron.core.knowledge.registry import CREATE_TABLE
from zikaron.core.store.ddl import FIXED_STATEMENTS as STORE_STATEMENTS

_KB_DOCUMENT = "knowledge-index.md"
_KB_HEADING = "### 3.2 Schema, per KB database"
_REGISTRY_DOCUMENT = "schema.md"
_REGISTRY_HEADING = "## The knowledge-base registry"

_EMBED_DIM_TEMPLATE = re.compile(r"<embed_dim>")


@pytest.fixture(scope="module")
def design_statements() -> list[str]:
    fenced = parse_fenced_code(section_lines(_KB_DOCUMENT, _KB_HEADING), "sql")
    return sql_statements(fenced)


def _split_pragmas_and_ddl(statements: list[str]) -> tuple[list[str], list[str]]:
    pragmas = [statement for statement in statements if statement.upper().startswith("PRAGMA")]
    rest = [statement for statement in statements if not statement.upper().startswith("PRAGMA")]
    return pragmas, rest


def test_the_two_pragmas_match_the_design_exactly(design_statements: list[str]) -> None:
    """Two, not three. `foreign_keys` is absent because this schema declares none, and switching
    it on would promise a cascade none of these tables actually has — so the count is asserted
    here rather than left to whoever reads the tuple."""
    design_pragmas, _ = _split_pragmas_and_ddl(design_statements)
    assert [normalize_sql(pragma) for pragma in PRAGMAS] == design_pragmas
    assert len(PRAGMAS) == 2


def test_every_fixed_statement_appears_in_the_design_in_the_same_order(
    design_statements: list[str],
) -> None:
    """`chunks_vec`'s statement is a template in the design and is checked separately below —
    every other statement is compared verbatim, in the design's own order, because `chunks_fts` is
    external-content against `chunks` and the index follows the table it indexes."""
    _, design_ddl = _split_pragmas_and_ddl(design_statements)
    without_vec = [statement for statement in design_ddl if "chunks_vec" not in statement]
    assert [normalize_sql(statement) for statement in FIXED_STATEMENTS] == without_vec


def test_the_design_states_exactly_one_chunks_vec_template(design_statements: list[str]) -> None:
    _, design_ddl = _split_pragmas_and_ddl(design_statements)
    vec_statements = [statement for statement in design_ddl if "chunks_vec" in statement]
    assert len(vec_statements) == 1
    assert _EMBED_DIM_TEMPLATE.search(vec_statements[0])


def test_chunks_vec_statement_substitutes_the_designs_template_exactly(
    design_statements: list[str],
) -> None:
    _, design_ddl = _split_pragmas_and_ddl(design_statements)
    (template,) = [statement for statement in design_ddl if "chunks_vec" in statement]
    assert normalize_sql(chunks_vec_statement(384)) == _EMBED_DIM_TEMPLATE.sub("384", template)


@pytest.mark.parametrize("embed_dim", [1, 8, 384, 768, 4096])
def test_chunks_vec_statement_accepts_any_width_at_least_one(embed_dim: int) -> None:
    statement = chunks_vec_statement(embed_dim)
    assert f"float[{embed_dim}]" in statement
    assert "CREATE VIRTUAL TABLE chunks_vec USING vec0" in statement


@pytest.mark.parametrize("embed_dim", [0, -1])
def test_chunks_vec_statement_refuses_a_width_below_one(embed_dim: int) -> None:
    with pytest.raises(ValueError, match="embed_dim must be >= 1"):
        chunks_vec_statement(embed_dim)


def test_the_registry_table_matches_schema_md_exactly() -> None:
    """The registry's DDL is stated in `schema.md` rather than in `knowledge-index.md`, because
    it is a table in `memory.db` and that document is the contract for those."""
    fenced = parse_fenced_code(section_lines(_REGISTRY_DOCUMENT, _REGISTRY_HEADING), "sql")
    (design_statement,) = sql_statements(fenced)
    assert normalize_sql(CREATE_TABLE) == design_statement


def test_the_registry_table_is_created_idempotently() -> None:
    """`IF NOT EXISTS` is what lets `memory.db`'s `schema_version` stay where it is: one creation
    site that every store can run, including one created before the table existed. Asserted
    because dropping those three words would silently reintroduce the migration this design
    decided not to need."""
    assert "IF NOT EXISTS" in normalize_sql(CREATE_TABLE).upper()


def test_the_registry_table_is_not_created_by_store_creation() -> None:
    """The other half of the same decision: a second, eager creation path would give two copies of
    one statement room to disagree, and would make the additive change look like a migration."""
    assert not any("knowledge_bases" in statement for statement in STORE_STATEMENTS)
