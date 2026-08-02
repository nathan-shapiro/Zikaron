"""Query construction on both arms, for both kinds of query — `retrieval.md` §"Query construction".

Two claims are load-bearing here and both are about what the code must *not* do. The lexical
constructor must never hand FTS5 an expression it can reject, because a syntax error on the push
path would send every user message to the degraded path; and the dense preflight must never let an
over-length query reach the model unannounced, because BGE truncates silently and the whole point of
the write-side preflight is that no truncation anywhere is silent.

The FTS5 assertions run against a real `memory_fts` table, since "this expression is accepted and
matches non-adjacently" is a claim about SQLite rather than about our string handling.
`pytest.raises` around the *unquoted* forms is what makes the quoting rule's value observable
instead of asserted.
"""

import re
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests import retrieval_fixtures as fx
from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.retrieval import query
from zikaron.core.retrieval.query import QueryOrigin

_MAX_TERMS: Final = 64
_PREFIX: Final = "Represent this sentence for searching relevant passages: "

#: A legal `embed_prefix_query` that does **not** end in whitespace, which is what lets the prefix
#: fuse with the query's first token. Only the shipped default ends in a space; the key is a
#: free-form string.
_UNSPACED_PREFIX: Final = "P:"

#: A colon inside a whitespace run rather than at its end — the shape `_FusingEncoder` charges three
#: tokens for, standing in for a sub-word split across a fused prefix boundary.
_FUSED_SPLIT: Final = re.compile(r":\S")

#: The two documents every FTS assertion below runs against. The first is the design's own
#: counterexample — two terms present but far apart — and the second has them adjacent, which is
#: what makes the phrase-versus-terms difference visible rather than asserted.
_SPLIT = ("split terms", "foo appears here and bar appears much later")
_JOINED = ("joined", "foo.bar(baz) inline")


def test_terms_are_maximal_alphanumeric_runs() -> None:
    """`foo.bar(baz)` is three terms, which is what makes a dotted identifier retrievable at all."""
    assert set(query.lexical_terms("foo.bar(baz)", max_terms=_MAX_TERMS)) == {"foo", "bar", "baz"}


def test_every_non_alphanumeric_character_is_a_boundary() -> None:
    terms = query.lexical_terms("PGHOST=db-1.internal:5432", max_terms=_MAX_TERMS)
    assert set(terms) == {"PGHOST", "db", "1", "internal", "5432"}


def test_unicode_alphanumerics_are_kept_together() -> None:
    """`str.isalnum()` is the boundary rule, so an accented letter is an ordinary term character
    rather than a boundary — the case `retrieval.md` checked against `fts5vocab`. The order is the
    length rule below, not the input order: `naïve` is the longer term."""
    assert query.lexical_terms("café naïve", max_terms=_MAX_TERMS) == ("naïve", "café")


def test_a_fragment_with_no_alphanumeric_produces_no_term() -> None:
    assert query.lexical_terms("... --- !!!", max_terms=_MAX_TERMS) == ()


def test_pure_punctuation_skips_the_lexical_arm_rather_than_matching_everything() -> None:
    built = query.lexical_query("?!?", max_terms=_MAX_TERMS)
    assert built.skipped
    assert built.expression is None
    assert built.terms == ()


def test_terms_are_deduplicated_on_first_occurrence() -> None:
    assert query.lexical_terms("proto proto codegen", max_terms=_MAX_TERMS) == ("codegen", "proto")


def test_deduplication_does_not_fold_case_because_folding_is_fts5s() -> None:
    """Two casings spend two slots, deliberately: a second folding rule here is the silent
    divergence the quoted-literal design exists to avoid, and the cost is a slot, never a match."""
    assert query.lexical_terms("PGHOST pghost", max_terms=_MAX_TERMS) == ("PGHOST", "pghost")


def test_the_cap_keeps_the_longest_terms() -> None:
    """In prose about code the long tokens are the identifiers, error strings and paths; the terms
    the cap drops are short common words BM25 would have scored near zero anyway."""
    assert query.lexical_terms("a bb MaxRetryError ccc", max_terms=2) == ("MaxRetryError", "ccc")


def test_the_cap_breaks_length_ties_on_first_occurrence() -> None:
    assert query.lexical_terms("bbb aaa ccc", max_terms=2) == ("bbb", "aaa")


def test_terms_are_joined_in_selection_order() -> None:
    """Longest-first, ties by first occurrence — one ordering rule for both the cap and the join,
    so the emitted expression is byte-identical across runs and the cap is legible in the text."""
    built = query.lexical_query("a bb ccc", max_terms=_MAX_TERMS)
    assert built.expression == '"ccc" OR "bb" OR "a"'


def test_construction_is_deterministic() -> None:
    text = "make proto exits 0 but emits nothing when protoc is older than 3.21"
    assert query.lexical_query(text, max_terms=8) == query.lexical_query(text, max_terms=8)


def test_internal_lexical_text_is_gist_then_content() -> None:
    assert query.internal_lexical_text("g", "c") == "g\nc"


async def _match(db: aiosqlite.Connection, expression: str) -> list[str]:
    rows = await db.execute_fetchall(
        "SELECT m.gist FROM memory_fts JOIN memory m ON m.rowid = memory_fts.rowid "
        "WHERE memory_fts MATCH ? ORDER BY m.gist",
        (expression,),
    )
    return [str(row[0]) for row in rows]


async def _two_documents(harness: fx.Harness) -> None:
    for gist, content in (_SPLIT, _JOINED):
        await harness.write(gist=gist, content=content)


@pytest.mark.parametrize("raw", ["foo.bar(baz)", "OR", 'say "hi', "-x"])
async def test_the_raw_forms_the_quoting_rule_exists_for_are_genuinely_rejected(
    tmp_path: Path, raw: str
) -> None:
    """Not a hypothetical: each of these raises `fts5: syntax error`, which on the push path would
    mean no memories at all for that user message.

    The four are the design's own list — a parenthesis, a bare boolean, an unbalanced quote, a
    leading hyphen. Note what is *not* here: `say "hi"`, with the quote closed, is perfectly legal
    FTS5 (an implicit AND of a token and a phrase), so listing it would have asserted a rejection
    that does not happen and taught a future reader the wrong rule.
    """
    async with fx.harness(tmp_path) as harness:
        await _two_documents(harness)
        with pytest.raises(aiosqlite.OperationalError):
            await _match(harness.store.connection, raw)


async def test_the_constructed_expression_is_accepted_and_matches_non_adjacently(
    tmp_path: Path,
) -> None:
    """The counterexample that killed the whole-fragment phrase form.

    Both forms are run against the same two documents, and the difference is the whole point: the
    quoted **phrase** `"foo bar baz"` matches only the document whose tokens are adjacent, silently
    losing the one where `foo` and `bar` are far apart, while term-level `OR` finds both. That lost
    document is the query shape this store exists to serve — a dotted identifier, a path, an error
    string — so the phrase form's precision is not worth its recall.
    """
    async with fx.harness(tmp_path) as harness:
        await _two_documents(harness)
        db = harness.store.connection
        built = query.lexical_query("foo.bar(baz)", max_terms=_MAX_TERMS)
        assert built.expression is not None

        assert await _match(db, built.expression) == ["joined", "split terms"]
        assert await _match(db, '"foo bar baz"') == ["joined"]


async def test_a_quoted_operator_is_matched_as_a_word(tmp_path: Path) -> None:
    """Quoting is what neutralizes operators: FTS5 applies the table's own tokenizer to a string
    literal's contents, so a bare `OR` becomes the word "or" rather than a boolean."""
    async with fx.harness(tmp_path) as harness:
        await _two_documents(harness)
        built = query.lexical_query("OR", max_terms=_MAX_TERMS)
        assert built.expression == '"OR"'
        assert await _match(harness.store.connection, built.expression) == []


async def test_case_folding_happens_on_both_sides_by_fts5s_own_code(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        await _two_documents(harness)
        built = query.lexical_query("FOO", max_terms=_MAX_TERMS)
        assert built.expression is not None
        assert await _match(harness.store.connection, built.expression) == [
            "joined",
            "split terms",
        ]


def test_a_short_query_is_embedded_whole() -> None:
    encoder = FakeEncoder()
    external = query.external_query(
        "why does the proto step fail", encoder=encoder, prefix=_PREFIX, max_terms=_MAX_TERMS
    )
    assert not external.query_truncated
    assert external.query_tokens == 6
    assert external.prepared.origin is QueryOrigin.EXTERNAL
    assert encoder.embedded == [(f"{_PREFIX}why does the proto step fail",)]


def test_query_tokens_counts_the_query_alone_and_excludes_the_prefix() -> None:
    """Recorded so the number means the same thing on a store configured with an empty prefix; the
    prefix is already charged against the budget on the other side of the subtraction."""
    encoder = FakeEncoder()
    text = "one two three"
    with_prefix = query.external_query(text, encoder=encoder, prefix=_PREFIX, max_terms=_MAX_TERMS)
    without = query.external_query(text, encoder=encoder, prefix="", max_terms=_MAX_TERMS)
    assert with_prefix.query_tokens == without.query_tokens == 3


def test_an_over_budget_query_keeps_its_head_and_records_the_truncation() -> None:
    """Truncated rather than refused — the asymmetry with the write side is deliberate, since
    refusing a user's prompt would mean refusing to retrieve at all — and never silently."""
    encoder = FakeEncoder(max_sequence_tokens=10, n_special_tokens=2)
    text = " ".join(f"w{index}" for index in range(20))
    external = query.external_query(text, encoder=encoder, prefix="", max_terms=_MAX_TERMS)
    assert external.query_truncated
    assert external.query_tokens == 20
    assert encoder.embedded == [("w0 w1 w2 w3 w4 w5 w6 w7",)]


def test_the_prefix_is_charged_against_the_budget() -> None:
    """Two tokens of prefix take two tokens off what the query may keep, which is the whole reason
    the budget is `cap - specials - prefix` rather than `cap - specials`."""
    encoder = FakeEncoder(max_sequence_tokens=10, n_special_tokens=2)
    text = " ".join(f"w{index}" for index in range(20))
    query.external_query(text, encoder=encoder, prefix="two tokens ", max_terms=_MAX_TERMS)
    assert encoder.embedded == [("two tokens w0 w1 w2 w3 w4 w5",)]


def test_the_lexical_arm_still_sees_the_whole_query_when_the_dense_side_is_truncated() -> None:
    """The measured mitigation for head-truncation: an identifier past the dense cutoff stays
    retrievable through BM25, because the two arms overflow differently."""
    encoder = FakeEncoder(max_sequence_tokens=5, n_special_tokens=2)
    external = query.external_query(
        "aa bb cc MaxRetryError", encoder=encoder, prefix="", max_terms=_MAX_TERMS
    )
    assert external.query_truncated
    assert encoder.embedded == [("aa bb cc",)]
    assert "MaxRetryError" in (external.prepared.lexical.expression or "")


class _FusingEncoder(FakeEncoder):
    """A tokenizer on which a fused prefix boundary costs *more* than the two parts did apart.

    One whitespace run is one token, except a run with a colon inside it — rather than at its end —
    costs three, standing in for the sub-word split a real WordPiece performs when a merged string
    is not in its vocabulary. So `"P:"` is one token and `"w0"` is one, while `"P:w0"` is three.

    That is the property under test, not any particular tokenizer's behaviour: a real tokenizer
    re-tokenizes across a join, so the pieces of `prefix + query` are not the pieces of `prefix`
    plus the pieces of `query`, and the count can move either way. Only the shipped default prefix
    ends in whitespace, and `embed_prefix_query` is a free-form config string, so a prefix that
    fuses is a legal configuration rather than a hypothetical one.
    """

    def count_tokens(self, text: str) -> int:
        return sum(3 if _FUSED_SPLIT.search(run) else 1 for run in text.split())


def test_a_prefix_that_fuses_with_the_query_cannot_hide_a_truncation() -> None:
    """The blocker this preflight exists for, in the one configuration that reaches it.

    Budget arithmetic alone says this query fits exactly: `cap - specials - count(prefix)` is 4 and
    the query is 4 tokens. But the assembled string costs one token more than the two parts, so
    embedding it unchanged would hand the model a sequence one token over its cap — which BGE
    truncates silently, with `query_truncated` recording `false`. Counting what is actually sent is
    what catches it.
    """
    encoder = _FusingEncoder(max_sequence_tokens=7, n_special_tokens=2)
    text = "w0 w1 w2 w3"
    assert encoder.count_tokens(_UNSPACED_PREFIX) + encoder.count_tokens(text) == 5
    assert encoder.count_tokens(_UNSPACED_PREFIX + text) == 6

    external = query.external_query(
        text, encoder=encoder, prefix=_UNSPACED_PREFIX, max_terms=_MAX_TERMS
    )

    assert external.query_truncated
    assert external.query_tokens == 4
    (embedded,) = encoder.embedded[-1]
    assert encoder.count_tokens(embedded) + encoder.n_special_tokens <= 7


def test_a_fused_boundary_also_shrinks_an_already_truncated_head() -> None:
    """The other half: a query long enough to be truncated by the budget must still have its *head*
    checked against the cap, since the fused boundary applies to whatever head is kept."""
    encoder = _FusingEncoder(max_sequence_tokens=7, n_special_tokens=2)
    text = " ".join(f"w{index}" for index in range(20))

    external = query.external_query(
        text, encoder=encoder, prefix=_UNSPACED_PREFIX, max_terms=_MAX_TERMS
    )

    assert external.query_truncated
    assert external.query_tokens == 20
    (embedded,) = encoder.embedded[-1]
    assert encoder.count_tokens(embedded) + encoder.n_special_tokens <= 7
    assert embedded.startswith(_UNSPACED_PREFIX)


def test_a_query_that_fits_whole_is_not_reported_as_truncated() -> None:
    """`query_truncated` means what it says, so a query that fits is left exactly as it came —
    leading and trailing punctuation included. Slicing it to token boundaries would report a
    truncation that did not happen, which is the same false record in the opposite direction."""
    encoder = FakeEncoder()
    text = "  why does the proto step fail?  "
    external = query.external_query(text, encoder=encoder, prefix=_PREFIX, max_terms=_MAX_TERMS)
    assert not external.query_truncated
    assert encoder.embedded == [(f"{_PREFIX}{text}",)]


def test_a_prefix_leaving_no_room_once_fused_is_a_named_configuration_error() -> None:
    """Reachable only by configuration, and reported as one rather than as a query silently reduced
    to the prefix alone: with the fused boundary, even a one-token query overruns this cap."""
    encoder = _FusingEncoder(max_sequence_tokens=4, n_special_tokens=2)
    with pytest.raises(ZikaronError) as raised:
        query.external_query(
            "w0 w1", encoder=encoder, prefix=_UNSPACED_PREFIX, max_terms=_MAX_TERMS
        )
    assert raised.value.code is ErrorCode.BAD_CONFIG
    assert raised.value.data["key"] == "embedding.embed_prefix_query"


def test_a_prefix_longer_than_the_model_cap_is_a_named_configuration_error() -> None:
    """Reachable only by misconfiguration, and reported as one: a prefix leaving no room for the
    query means the store cannot be read, which is a `bad_config` naming the key to change."""
    encoder = FakeEncoder(max_sequence_tokens=3, n_special_tokens=2)
    with pytest.raises(ZikaronError) as raised:
        query.external_query("q", encoder=encoder, prefix="a b c", max_terms=_MAX_TERMS)
    assert raised.value.code is ErrorCode.BAD_CONFIG
    assert raised.value.data["key"] == "embedding.embed_prefix_query"


class _DisagreeingEncoder(FakeEncoder):
    """A tokenizer whose count and spans disagree — the failure that loses a query's tail silently.

    Well-formed spans that are merely *short*: ordered, in range, non-overlapping, and covering only
    the first token. Every later check still passes, and the head kept is not the head counted.
    """

    def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:
        return super().token_char_spans(text)[:1]


def test_a_tokenizer_whose_count_and_spans_disagree_is_refused() -> None:
    encoder = _DisagreeingEncoder(max_sequence_tokens=5, n_special_tokens=2)
    with pytest.raises(ZikaronError) as raised:
        query.external_query("a b c d e f g", encoder=encoder, prefix="", max_terms=_MAX_TERMS)
    assert raised.value.code is ErrorCode.BAD_CONFIG
    assert raised.value.data["key"] == "embedding.embed_model"


async def test_an_internal_query_reuses_the_stored_first_chunk_vector(tmp_path: Path) -> None:
    """No second embed call, no truncation risk, and the same vector every time — which is what
    makes planning a pure function of the store rather than of a second inference."""
    async with fx.harness(tmp_path) as harness:
        gist, content = "pinned deps", "urllib3 must stay on 1.26.x for the vendored client"
        uuid = await harness.write(gist=gist, content=content)
        harness.encoder.embedded.clear()

        internal = await query.internal_query(
            harness.store.connection, memory_uuid=uuid, max_terms=_MAX_TERMS
        )

        assert harness.encoder.embedded == []
        assert internal.origin is QueryOrigin.INTERNAL
        assert internal.vector == fx.query_vector_for(gist, content)


async def test_an_internal_querys_lexical_side_is_its_own_gist_and_content(tmp_path: Path) -> None:
    """The identical constructor an external query uses, called on stored prose — one rule, not two.
    The cap does real work here, because a memory has far more terms than a prompt."""
    async with fx.harness(tmp_path) as harness:
        uuid = await harness.write(gist="alpha", content="beta gamma")
        internal = await query.internal_query(
            harness.store.connection, memory_uuid=uuid, max_terms=2
        )
        assert internal.lexical.terms == ("alpha", "gamma")


async def test_an_internal_query_for_an_unknown_uuid_is_not_found(tmp_path: Path) -> None:
    async with fx.harness(tmp_path) as harness:
        with pytest.raises(ZikaronError) as raised:
            await query.internal_query(
                harness.store.connection, memory_uuid="nope", max_terms=_MAX_TERMS
            )
        assert raised.value.code is ErrorCode.NOT_FOUND


async def test_an_internal_query_for_a_row_with_no_chunks_is_reported_not_papered_over(
    tmp_path: Path,
) -> None:
    """Invariant 12 makes this impossible for a row with content, so it is reported rather than
    quietly repaired with a second embed call the internal path is specified not to make."""
    async with fx.harness(tmp_path) as harness:
        uuid = await harness.write(gist="g", content="c")
        await harness.store.connection.execute("DELETE FROM memory_vec")
        await harness.store.connection.execute(
            "DELETE FROM memory_chunk WHERE memory_uuid = ?", (uuid,)
        )
        await harness.store.connection.commit()
        with pytest.raises(ZikaronError) as raised:
            await query.internal_query(
                harness.store.connection, memory_uuid=uuid, max_terms=_MAX_TERMS
            )
        assert raised.value.code is ErrorCode.NOT_FOUND
