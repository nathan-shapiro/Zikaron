"""Query construction: a prompt is not an FTS5 expression, and it is not always under 512 tokens.

`retrieval.md` §"Query construction" is normative. Two failures live here, one per arm, and both
were underspecified until that section was written:

- **Lexical.** A raw prompt is not a safe `MATCH` expression — a quote, a parenthesis or a bare
  `OR` changes the query's meaning or raises `fts5: syntax error`, and a syntax error on the push
  path would send every user message to the degraded path. The rule splits on boundaries only and
  hands each fragment to FTS5 **as a quoted string literal**, so FTS5's own tokenizer does the case
  folding and diacritic stripping. Reimplementing `unicode61` was the alternative and it is a
  silent-divergence bug in the one component that must agree with the index.
- **Dense.** A long prompt, or consolidation's group-gist concatenation, can exceed the model's
  512-token input, and BGE truncates silently. So the read side gets the same preflight the write
  side has — through the same tokenizer — and resolves it the other way: it **truncates and records
  it**, because a write can be handed back to an agent that still holds its text while refusing a
  user's prompt would mean refusing to retrieve at all.

`retrieval.md` §"Two kinds of query" then makes both rules serve two callers. An **external** query
is text from outside the store; an **internal** query is a memory querying other memories, whose
dense side is its own stored first-chunk embedding and whose lexical side is its own `gist +
content` through the identical constructor. One rule called on stored prose instead of on a prompt,
never a second rule.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import aiosqlite

from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.indexing.vectors import serialize

#: What separates the two prose fields of an internal query's lexical side. Any non-alphanumeric
#: character would do — the constructor keeps only alphanumeric runs — so the choice is legibility.
_INTERNAL_JOIN: Final = "\n"


class QueryOrigin(StrEnum):
    """Where a query's dense vector came from, which decides whether a cosine may be read off it.

    An `INTERNAL` query reuses a stored first-chunk embedding, which the write path L2-normalized,
    so `cos = 1 - d^2/2` over `vec0`'s distance is exact and the three cosine cutoffs mean what
    they say. An `EXTERNAL` query's vector is whatever the embedder returned for the prompt and is
    deliberately **not** renormalized: ordering by distance to unit documents is monotone in cosine
    for any fixed query vector, so the ranking is unaffected, and no external query is ever
    thresholded — all three cutoffs are `s(X -> Y)` between two stored memories. Carrying the origin
    is what keeps that from being a fact somebody has to remember: a cosine is offered only where it
    is exact.
    """

    EXTERNAL = "external"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class LexicalQuery:
    """One query's lexical side: the terms selected, and the expression bound into `MATCH`.

    `expression` is `None` when no term survived, which is `retrieval.md`'s `lexical_skipped`: a
    prompt of pure punctuation runs dense-only rather than raising or matching everything.
    """

    terms: tuple[str, ...]
    expression: str | None

    @property
    def skipped(self) -> bool:
        """Whether the lexical arm has nothing to run — zero surviving terms."""
        return self.expression is None


@dataclass(frozen=True, slots=True)
class PreparedQuery:
    """Everything the retrieval algorithm needs of a query, whichever kind produced it.

    The algorithm is identical for both kinds (`retrieval.md` §"Two kinds of query"), so this is
    the seam: construction differs, retrieval does not.
    """

    origin: QueryOrigin
    vector: bytes
    lexical: LexicalQuery


@dataclass(frozen=True, slots=True)
class ExternalQuery:
    """A prepared external query plus the two facts only its dense preflight can report.

    `query_tokens` is the pre-truncation token count of the query text **alone**, excluding the BGE
    prefix — the prefix is charged against the budget on the other side of the subtraction, so
    counting it here would double it and make the recorded number disagree with the same field on a
    store configured with an empty prefix. Both fields go on the `search`/`surface_call` event.
    """

    prepared: PreparedQuery
    query_tokens: int
    query_truncated: bool


def _quote(term: str) -> str:
    """One term as an FTS5 string literal.

    Quoting is what neutralizes operators — a quoted `OR` is the word "or", a quoted `-x` is "x" —
    and, more importantly, what hands the term's *contents* to the table's own tokenizer, so case
    folding and diacritic stripping happen on both sides by the same code. The internal-quote
    doubling `retrieval.md` step 3 requires is unconditional rather than guarded: a term is a run of
    alphanumerics and so cannot contain a quote today, and an unconditional `replace` costs nothing
    while a conditional one would be a branch nothing can reach.
    """
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def _alphanumeric_runs(text: str) -> list[str]:
    """Every maximal run of Unicode alphanumerics in `text`, in order.

    `str.isalnum()` per character rather than a tokenizer of our own: `retrieval.md` bounds the
    residual risk of this being *our* boundary rule rather than SQLite's to one term missing one
    match — checked against `fts5vocab` on nine technical strings with zero disagreements — which is
    a strictly smaller exposure than reproducing `unicode61`'s folding tables.
    """
    runs: list[str] = []
    current: list[str] = []
    for character in text:
        if character.isalnum():
            current.append(character)
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return runs


def lexical_terms(text: str, *, max_terms: int) -> tuple[str, ...]:
    """The terms `text` contributes to a lexical query, in the order they will be joined.

    Deduplicated on the exact string, then sorted **longest-first with ties broken by first
    occurrence**, then cut to `max_terms`. Longest-first is the right truncation for this corpus
    rather than an arbitrary one: in prose about code the long tokens are the identifiers, error
    strings and paths, while the terms it drops are short common words BM25 would have scored near
    zero anyway.

    Deduplication compares the text as written, and deliberately does not fold case: folding is
    FTS5's, on both sides, and a second folding rule here is exactly the silent divergence the
    quoted-literal design avoids. Two differently-cased occurrences of one word therefore spend two
    of the `max_terms` slots, which costs a slot and cannot cost correctness.
    """
    seen: dict[str, int] = {}
    for index, run in enumerate(_alphanumeric_runs(text)):
        seen.setdefault(run, index)
    ranked = sorted(seen.items(), key=lambda pair: (-len(pair[0]), pair[1]))
    return tuple(term for term, _ in ranked[:max_terms])


def lexical_query(text: str, *, max_terms: int) -> LexicalQuery:
    """`text` as an FTS5 `MATCH` expression, or a skipped arm if it yields no term.

    The expression is `OR` over quoted terms, in selection order, and is always **bound as a
    parameter** rather than formatted into SQL text. BM25 already ranks a document matching several
    terms above one matching a single term, so `OR` loses nothing a phrase would gain — while a
    phrase would require adjacency and so would silently drop every non-adjacent match on dotted
    identifiers, paths and error strings, which is precisely the query shape this store serves.
    """
    terms = lexical_terms(text, max_terms=max_terms)
    expression = " OR ".join(_quote(term) for term in terms) if terms else None
    return LexicalQuery(terms=terms, expression=expression)


def internal_lexical_text(gist: str, content: str) -> str:
    """The prose an internal query's lexical side is built from: the memory's own `gist + content`.

    A function rather than a call-site concatenation because the 64-term cap does real work here —
    a memory has far more terms than a prompt does — so which text the cap is applied to is part of
    the contract rather than an incidental detail of one caller.
    """
    return f"{gist}{_INTERNAL_JOIN}{content}"


def _prefix_too_long(prefix_tokens: int, cap: int) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        file="<effective config>",
        key="embedding.embed_prefix_query",
        value=f"{prefix_tokens} tokens",
        expected=f"a prefix leaving at least one token of the model's {cap}-token input for the "
        "query itself — a longer prefix leaves no query to embed, so the store cannot be read",
    )


def _inconsistent_tokenizer(model_name: str) -> ZikaronError:
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        file="<embedding artifact>",
        key="embedding.embed_model",
        value=model_name,
        expected="a tokenizer whose token count and token spans agree — they disagree, so the "
        "head kept here would not be the head that was counted",
    )


def _prefix_leaves_no_query_token(prefix_tokens: int, cap: int) -> ZikaronError:
    """`bad_config` for a prefix beside which not even this query's first token fits.

    Distinct from `_prefix_too_long` only in how it was discovered: that one is arithmetic on the
    two counts, this one is what the assembled sequence turned out to cost once the boundary between
    them was tokenized. The claim is deliberately about *this* query rather than about every query,
    because the boundary's cost depends on the text either side of it and a different first token
    could fuse more cheaply. Same key, same remedy, both reachable only by configuration.
    """
    return ZikaronError(
        ErrorCode.BAD_CONFIG,
        source=BadConfigSource.FILE,
        file="<effective config>",
        key="embedding.embed_prefix_query",
        value=f"{prefix_tokens} tokens",
        expected="a prefix beside which this query's first token still fits once the two are "
        f"tokenized together — assembled with even one of its tokens the sequence exceeds the "
        f"model's {cap}-token input",
    )


def assembled_tokens(prefix: str, kept: str, *, encoder: Encoder) -> int:
    """How many tokens the model will actually see for `prefix + kept`, special tokens included.

    Counted on the **concatenation**, never as the sum of the two pieces' counts. A tokenizer
    re-tokenizes across a join, so neither count bounds the other: with the shipped prefix, which
    ends in whitespace, the pre-tokenizer splits at the boundary and the two agree — but
    `embed_prefix_query` is a free-form string, and a prefix without a trailing boundary fuses with
    the query's first token and can produce *more* pieces than the two counts predicted. Trusting
    the sum would then report a short prompt as untruncated while the model quietly dropped its
    tail, which is the single failure this preflight exists to prevent.
    """
    return encoder.count_tokens(f"{prefix}{kept}") + encoder.n_special_tokens


def _fit_to_cap(text: str, *, prefix: str, budget: int, encoder: Encoder) -> str:
    """The nominal-budget head of `text`, shrunk until its **assembled** sequence fits the cap.

    Called only once the whole text is known not to fit. The budget subtraction chooses the first
    candidate; this is what settles it, by counting `prefix + head` as one string at each step
    rather than adding the two pieces' counts. Each step drops one query token, so the loop
    terminates, and its floor is one token: a prefix beside which not even this query's first token
    fits is a configuration error rather than a query silently reduced to the prefix alone.

    Not "the longest head that fits", and the distinction is worth stating because retokenization at
    the boundary can *reduce* a count as well as raise it — so a head one token past the nominal
    budget could in principle fit. The search deliberately does not look there: `retrieval.md` sets
    the budget as what the query may keep, and going above it to reclaim a token the boundary
    happened to absorb would make the kept length depend on the prefix in a way no field records.

    Raises:
        ZikaronError: `BAD_CONFIG` naming `embedding.embed_prefix_query` if not even this query's
            first token fits beside the prefix.
    """
    for tokens in range(min(budget, encoder.count_tokens(text)), 0, -1):
        kept = _head(text, tokens=tokens, encoder=encoder)
        if assembled_tokens(prefix, kept, encoder=encoder) <= encoder.max_sequence_tokens:
            return kept
    raise _prefix_leaves_no_query_token(encoder.count_tokens(prefix), encoder.max_sequence_tokens)


def _head(text: str, *, tokens: int, encoder: Encoder) -> str:
    """The first `tokens` tokens of `text`, sliced on token boundaries.

    Head rather than tail for one stated reason and one measured mitigation: the head carries the
    topic and the earliest-named identifiers, and it is the same direction the write-side hard split
    takes, so there is one rule rather than two; and the lexical arm still sees the whole prompt, so
    an identifier past the dense cutoff stays retrievable through BM25.

    The spans are counted against the count that decided a truncation was needed, for the same
    reason the write-side hard split does it: a well-formed but *short* span list would keep fewer
    tokens than intended and record a number describing text that was never embedded, with nothing
    later able to notice.

    Raises:
        ZikaronError: `BAD_CONFIG` naming `embedding.embed_model` if the artifact's token count and
            token spans disagree.
    """
    spans = encoder.token_char_spans(text)
    if len(spans) != encoder.count_tokens(text):
        raise _inconsistent_tokenizer(encoder.model_name)
    window = spans[:tokens]
    return text[window[0][0] : window[-1][1]]


def external_query(text: str, *, encoder: Encoder, prefix: str, max_terms: int) -> ExternalQuery:
    """Build both arms of a query from text outside the store, embedding it under the token budget.

    The dense side is embedded through the deployed artifact with D20's BGE query-instruction
    prefix; the lexical side is the term constructor above, over the **whole** text whether or not
    the dense side had to be truncated.

    Blocking work — one embedding call — so a caller on an event loop is responsible for keeping
    this off it, exactly as the write path's `embed_chunks` is.

    Args:
        text: the query as the caller received it: a user prompt, an agent's `search` string, or
            consolidation's group-gist concatenation.
        encoder: the deployed artifact. Its tokenizer counts, and its model embeds.
        prefix: `embed_prefix_query`. Query-side only, per BGE's asymmetric convention; the empty
            string disables it.
        max_terms: `fts_query_max_terms`.

    Raises:
        ZikaronError: `BAD_CONFIG` if the configured prefix leaves no room for the query — either by
            the budget arithmetic or once the two are tokenized as one string — or if the artifact's
            token count and token spans disagree.
    """
    cap = encoder.max_sequence_tokens
    budget = cap - encoder.n_special_tokens - encoder.count_tokens(prefix)
    if budget < 1:
        raise _prefix_too_long(encoder.count_tokens(prefix), cap)

    query_tokens = encoder.count_tokens(text)
    # The assembled sequence is counted first, so the common path pays one tokenizer call and the
    # search below runs only when the input genuinely overflows. Checking it this way also keeps
    # `query_truncated` exact: `_head` slices from the first token's start to the last token's end,
    # so calling it on a query that already fits would drop leading or trailing punctuation and
    # report a truncation that did not happen.
    fits_whole = assembled_tokens(prefix, text, encoder=encoder) <= cap
    kept = text if fits_whole else _fit_to_cap(text, prefix=prefix, budget=budget, encoder=encoder)
    (vector,) = encoder.embed([f"{prefix}{kept}"])
    return ExternalQuery(
        prepared=PreparedQuery(
            origin=QueryOrigin.EXTERNAL,
            vector=serialize(vector),
            lexical=lexical_query(text, max_terms=max_terms),
        ),
        query_tokens=query_tokens,
        # What was dropped, not what the budget subtraction predicted would be dropped: the two
        # differ exactly when the prefix boundary retokenizes, which is the case this preflight now
        # settles by counting the assembled string instead of the sum of its parts.
        query_truncated=kept != text,
    )


async def internal_query(
    db: aiosqlite.Connection, *, memory_uuid: str, max_terms: int
) -> PreparedQuery:
    """Build both arms of one memory's query against the others, reading no model at all.

    The dense side is the memory's **stored first-chunk embedding** (`part_index = 0`): it already
    exists, it is already normalized, it cannot overflow the model's input because the write-side
    preflight proved it fits, and reusing it is what makes planning a pure function of the store
    rather than of a second inference. The lexical side is the memory's own `gist + content` through
    the identical constructor an external query uses, where the 64-term cap does real work.

    Assumes the caller's own open transaction: an internal query's whole point is to run inside the
    write or planning transaction that produced the row it is querying from.

    Raises:
        ZikaronError: `NOT_FOUND` if `memory_uuid` names no row, or names one with no `part_index=0`
            chunk. Invariant 12 makes the second impossible for a row with content, so it is
            reported rather than papered over with a second embed call.
    """
    rows = await db.execute_fetchall(
        "SELECT m.gist, m.content, v.embedding "
        "FROM memory m "
        "JOIN memory_chunk c ON c.memory_uuid = m.uuid AND c.part_index = 0 "
        "JOIN memory_vec v ON v.rowid = c.chunk_id "
        "WHERE m.uuid = ?",
        (memory_uuid,),
    )
    found = list(rows)
    if not found:
        raise ZikaronError(ErrorCode.NOT_FOUND, uuid=memory_uuid)
    gist, content, embedding = found[0]
    return PreparedQuery(
        origin=QueryOrigin.INTERNAL,
        vector=bytes(embedding),
        lexical=lexical_query(internal_lexical_text(str(gist), str(content)), max_terms=max_terms),
    )
