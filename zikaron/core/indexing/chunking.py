"""The chunking preflight: prose in, the exact set of chunks that will be embedded out.

`design/indexing.md` §"Chunk construction" is normative and this module is its mechanism. Every
function here is **pure** — no store, no connection, no clock — which is what lets the preflight
run before any transaction opens and lets its determinism be asserted by running it twice.

The one rejection it raises is `bounds`, which is rung 1 of both validation ladders
(`architecture.md` §"Validation precedence") and so is correctly decided before existence,
version or receipt. Everything else it can raise is `index_failed`: the arithmetic left no room
for content, or the assembled sequence overran the model's cap, both of which are configuration
or model problems rather than anything wrong with the caller's prose.
"""

import re
from dataclasses import dataclass
from typing import Final

from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing.encoder import Encoder

#: One blank line — a newline, any run of whitespace, another newline — is the paragraph
#: boundary `indexing.md` step 3 splits on. `\s` covers the whitespace *and* further newlines, so
#: a run of several blank lines is one boundary rather than several empty paragraphs.
_PARAGRAPH_BREAK: Final = re.compile(r"\n\s*\n")

#: The separator between a chunk's prepended prefix and its own content (`indexing.md` step 7).
#: The prefix is a memory's gist here and an indexed file's path in the knowledge index; the
#: separator is the same character in both, so it is stated once — two copies of one byte is how a
#: budget computed in one place comes to describe a sequence assembled in another.
PREFIX_SEPARATOR: Final = "\n"

#: What the budget arithmetic charges for `PREFIX_SEPARATOR`, per `indexing.md`: one token, even
#: though a bare newline is whitespace that BGE's WordPiece pre-tokenizer discards and so
#: measures zero. The error is then one token of unused budget instead of one token of overflow,
#: and the assembled-sequence assertion stays a bug-catcher rather than becoming the mechanism
#: that discovers a future model whose separator does tokenize.
SEPARATOR_TOKENS: Final = 1

#: The gist's hard character bound, and the only bound here that is a fixed constant rather than
#: configuration.
#:
#: **It exists because tokens bound neither characters nor bytes.** The deployed WordPiece
#: tokenizer maps anything outside its vocabulary to a single `[UNK]`, so an unbroken
#: 4,000-character run counts as one token and 256 emoji count as 256 — a gist can satisfy every
#: token bound the write path states and still be arbitrarily long. Without a second bound in a
#: unit that actually constrains size, no claim about the injected block fitting a harness's
#: injection budget is provable, and the failure it guards against is a block silently truncated
#: mid-memory.
#:
#: **Fixed rather than configurable, deliberately**: an output cap cannot be proven against a limit
#: an operator can raise, so making this a config key would defeat the only reason it exists.
#:
#: **Counted in UTF-16 code units, the same unit the injection budgets were measured to use.** The
#: earlier pin used text where a code point and a UTF-16 unit coincide and so could not separate
#: them; the astral rerun did (`research/claude-code-dogfood-checkpoint.md` §3), and UTF-16 units
#: is the answer. So this is the *correct* count, not a conservative one. Counting code points here
#: while the budget counted units would leave the two halves of one argument in different units, and
#: the worst case — five gists of astral characters — would exceed the budget it is supposed to
#: prove.
#:
#: **The number, and what it buys.** A five-row injected block's fixed framing measures 1,309
#: units, so five gists at this bound come to 6,429 — 64% of the smallest injection budget any
#: supported harness states. UTF-8 needs at most three bytes per UTF-16 unit (a
#: Basic-Multilingual-Plane character is one unit and at most three bytes; an astral character is
#: two units and four bytes), so the same block is at most 19,287 bytes against the largest
#: byte-denominated budget, 29% of it. The framing is preamble prose and moves when that prose does,
#: so every figure in this paragraph is recomputed rather than carried.
#:
#: **The trade it makes.** Measured across prose styles at 3.89 to 6.55 characters per token, this
#: binds above roughly 156 tokens of plain English: comfortably clear of the default gist token
#: bound of 64 (worst case 363 characters), and genuinely the binding constraint near the top of
#: that key's range. Admitting prose at the highest configurable token bound would need ~1,584
#: characters per gist, which puts the same block at 92% of budget — a rejection naming the count
#: is the better failure than a block that fits by luck.
GIST_MAX_CHARACTERS: Final = 1024


def utf16_units(text: str) -> int:
    """How many UTF-16 code units `text` occupies — the unit a character budget was measured to
    count (`research/claude-code-dogfood-checkpoint.md` §3).

    One per Basic-Multilingual-Plane character and two per astral character, so it never
    under-reports against a code-point count. `surrogatepass` keeps the function total: a lone
    surrogate is legal in a Python string decoded from JSON and would otherwise raise here rather
    than being counted as the one unit it occupies.

    Deliberately duplicated by `zikaron.harness.spec.HarnessSpec.exceeds_injection_budget` rather
    than shared: that module is the hook's stdlib-only seam and may not import from `core` at any
    price. A test asserts the two agree, which is the arrangement this codebase already uses for
    every other copy it cannot avoid.
    """
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


#: The separator paragraphs are rejoined with when several share one chunk. Blank-line-separated,
#: because that is what the author wrote and what the boundary detection above reads back.
_PARAGRAPH_JOIN: Final = "\n\n"


@dataclass(frozen=True, slots=True)
class Chunk:
    """One chunk of a memory's content, as it will be stored and embedded.

    `text` is a verbatim slice of `content` — never the assembled, gist-prepended sequence, which
    is `embedded_text` below and is not stored anywhere. `token_count` counts `text` alone, per
    `indexing.md` §Storage: the chunk's own slice of content, excluding the gist, the separator
    and the special tokens.
    """

    part_index: int
    text: str
    token_count: int
    truncated: bool

    def embedded_text(self, gist: str) -> str:
        """The sequence actually embedded: the gist, one separator, then this chunk's content.

        Gist-prepending is what keeps a chunk from being an orphan — "run `make clean` first" with
        nothing saying what it concerns — and it is why the budget is computed against the
        assembled sequence rather than against content alone.
        """
        return f"{gist}{PREFIX_SEPARATOR}{self.text}"


@dataclass(frozen=True, slots=True)
class ChunkPlan:
    """Everything the write path needs from the preflight, and everything its events report.

    `content_tokens` is the memory's own size — `memory.token_count` and the `remember`/`amend`
    event's `detail.token_count`, which count `content` and not the gist, since `gist_tokens` is
    a sibling field that would otherwise double-count it.

    The gist itself is deliberately **not** a field here: it belongs to the `Rewrite` this plan was
    built from, and a second copy of it beside the chunks would be a second thing to keep in step.
    Both methods that need it take it as an argument instead.
    """

    gist_tokens: int
    content_tokens: int
    effective_budget: int
    chunks: tuple[Chunk, ...]

    @property
    def n_chunks(self) -> int:
        """How many chunks this plan holds. Always at least one — invariant 12."""
        return len(self.chunks)

    @property
    def truncated(self) -> bool:
        """Whether any chunk came from a hard-split paragraph — the `truncated` canary per write.

        Never inferred from the embedder, which reports no truncation at all; this is set by the
        preflight's own hard-split step and by nothing else.
        """
        return any(chunk.truncated for chunk in self.chunks)

    def embedded_texts(self, gist: str) -> tuple[str, ...]:
        """Every chunk's assembled sequence, in `part_index` order — the embedder's input."""
        return tuple(chunk.embedded_text(gist) for chunk in self.chunks)


def _reject_bounds(field: str, limit: int, actual: int) -> ZikaronError:
    return ZikaronError(ErrorCode.BOUNDS, field=field, limit=limit, actual=actual)


def _non_whitespace_length(text: str) -> int:
    """How many non-whitespace characters `text` holds — the quantity "non-empty" bounds.

    A count rather than a boolean so the `bounds` payload can report an `actual` against a
    `limit` of 1, in the same numeric shape as the gist-length rejection beside it.
    """
    return len("".join(text.split()))


def paragraphs(content: str) -> tuple[str, ...]:
    """`content` split on blank lines, each stripped, with empties dropped.

    Deterministic for one input, which is the whole basis of the chunk-boundary determinism the
    build plan requires: this is the only place a boundary is decided from the text itself rather
    than from a token count.
    """
    parts = (part.strip() for part in _PARAGRAPH_BREAK.split(content))
    return tuple(part for part in parts if part)


def _hard_split(paragraph: str, *, budget: int, encoder: Encoder) -> tuple[str, ...]:
    """Cut one over-budget paragraph into `budget`-token pieces, on token boundaries.

    `indexing.md` step 5 is the only place text is cut inside a paragraph, and it cuts on token
    boundaries so no piece ends mid-token — a mid-token cut would hand the model a fragment of a
    word whose embedding means something else entirely.

    Slicing by the tokenizer's own character offsets is what makes the pieces cover the paragraph:
    each piece runs from its first token's start offset to its last token's end offset, so the only
    characters dropped are the whitespace *between* two pieces, which no token claimed.

    **That guarantee is only as good as the spans accounting for every token**, so the spans are
    counted against the count that sent this paragraph here. A span list that is well-formed but
    *short* — ordered, in range, non-overlapping, and covering only the paragraph's first few tokens
    — would produce pieces that silently omit the rest, which is content loss with every later check
    still passing: the emitted pieces are inside their budget, their assembled sequences are inside
    the cap, and nothing else ever looks at the paragraph again. So a disagreement is refused here
    rather than left to a check that cannot see it.

    A token whose span is zero-width claims no characters, so a piece made only of such tokens is
    empty text whose assembled sequence is the gist alone. That loses nothing — there were no
    characters to lose — and needs no guard of its own once the counts agree.

    Raises:
        ZikaronError: `INDEX_FAILED` at stage `assembly` if the encoder's token count and its token
            spans disagree, since the preflight then cannot cut where its own arithmetic says it
            must.
    """
    spans = encoder.token_char_spans(paragraph)
    if len(spans) != encoder.count_tokens(paragraph):
        raise ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.ASSEMBLY)
    pieces: list[str] = []
    for start in range(0, len(spans), budget):
        window = spans[start : start + budget]
        pieces.append(paragraph[window[0][0] : window[-1][1]])
    return tuple(pieces)


def _pack(paragraph_texts: tuple[str, ...], *, budget: int, encoder: Encoder) -> tuple[Chunk, ...]:
    """Greedily merge adjacent paragraphs into chunks of at most `budget` content tokens.

    Greedy and forward-only, so the boundaries are a function of the text alone. A paragraph that
    alone exceeds the budget is hard-split, and its pieces are chunks of their own: the packer
    does **not** go on filling the last piece with the paragraph that follows it. That keeps
    `truncated` meaning exactly "this chunk's text came out of one over-budget paragraph" rather
    than "some of this chunk's text did", which is what makes the canary readable per chunk.

    The candidate's *joined* text is counted rather than the running sum of its parts, because the
    count that matters is the one the model will perform on the text it is actually given.
    """
    chunks: list[Chunk] = []
    pending: list[str] = []

    def emit(text: str, *, truncated: bool) -> None:
        chunks.append(
            Chunk(
                part_index=len(chunks),
                text=text,
                token_count=encoder.count_tokens(text),
                truncated=truncated,
            )
        )

    def flush() -> None:
        if pending:
            emit(_PARAGRAPH_JOIN.join(pending), truncated=False)
            pending.clear()

    for paragraph in paragraph_texts:
        candidate = _PARAGRAPH_JOIN.join([*pending, paragraph])
        if encoder.count_tokens(candidate) <= budget:
            pending.append(paragraph)
            continue
        flush()
        if encoder.count_tokens(paragraph) <= budget:
            pending.append(paragraph)
            continue
        for piece in _hard_split(paragraph, budget=budget, encoder=encoder):
            emit(piece, truncated=True)
    flush()
    return tuple(chunks)


def plan_chunks(
    *,
    gist: str,
    content: str,
    encoder: Encoder,
    chunk_max_tokens: int,
    gist_max_tokens: int,
) -> ChunkPlan:
    """Run `indexing.md`'s preflight over one memory's prose.

    Pure: the same arguments produce byte-identical chunks on every call and in every process,
    which is what every claim about deterministic chunk boundaries rests on.

    Args:
        gist: the memory's gist, counted against `gist_max_tokens` and prepended to every chunk.
        content: the memory's content, stored untruncated and split into chunks here.
        encoder: the deployed artifact — its tokenizer does the counting and its special-token
            count and sequence cap set the budget.
        chunk_max_tokens: the configured per-chunk content budget, which binds unless the gist is
            long enough that the model's own cap binds first.
        gist_max_tokens: the one bound that rejects an agent's write.

    Returns:
        A `ChunkPlan` with at least one chunk — invariant 12, which holds because non-empty
        content yields at least one paragraph.

    Raises:
        ZikaronError: `BOUNDS` if `gist` or `content` is empty or whitespace-only, if `gist`
            exceeds `GIST_MAX_CHARACTERS` (reported against field `gist.characters`), or if `gist`
            exceeds `gist_max_tokens` — each naming the limit and the actual count, so the agent
            can shorten its gist in the same turn. The character bound is checked first; a gist
            over both reports characters, which is the unit the agent can act on directly.
            `INDEX_FAILED` at stage `budget` if the model's cap
            leaves no room for content once the gist and separator are charged for, or at stage
            `assembly` if the plan the packing produced does not in fact satisfy its own budget or
            the model's cap, which is a defect in this module rather than something a caller can
            fix by rewriting its prose.
    """
    gist_length = _non_whitespace_length(gist)
    if gist_length == 0:
        raise _reject_bounds("gist", 1, 0)
    content_length = _non_whitespace_length(content)
    if content_length == 0:
        raise _reject_bounds("content", 1, 0)

    # Characters before tokens, for two reasons. It is the cheaper check — no tokenizer — and it is
    # the more actionable rejection, since an agent can count the characters it just wrote and
    # cannot count WordPiece tokens. The field name carries the unit because the error payload does
    # not: two bounds on one field reporting only a limit and an actual would be indistinguishable.
    gist_units = utf16_units(gist)
    if gist_units > GIST_MAX_CHARACTERS:
        raise _reject_bounds("gist.characters", GIST_MAX_CHARACTERS, gist_units)

    gist_tokens = encoder.count_tokens(gist)
    if gist_tokens > gist_max_tokens:
        raise _reject_bounds("gist", gist_max_tokens, gist_tokens)

    content_budget = (
        encoder.max_sequence_tokens - encoder.n_special_tokens - gist_tokens - SEPARATOR_TOKENS
    )
    effective_budget = min(chunk_max_tokens, content_budget)
    if effective_budget < 1:
        raise ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.BUDGET)

    packed = _pack(paragraphs(content), budget=effective_budget, encoder=encoder)
    plan = ChunkPlan(
        gist_tokens=gist_tokens,
        content_tokens=encoder.count_tokens(content),
        effective_budget=effective_budget,
        chunks=packed,
    )
    _assert_plan_is_within_its_budgets(plan, gist=gist, encoder=encoder)
    return plan


def _assert_plan_is_within_its_budgets(plan: ChunkPlan, *, gist: str, encoder: Encoder) -> None:
    """Refuse a plan the packing above did not actually satisfy, on either of its two bounds.

    Two conditions, one raise, because both mean the same thing — the packer produced something it
    claims to have fitted and did not:

    - **Every chunk's own slice is within `effective_budget`.** Checked by *recounting* the emitted
      text rather than by trusting the count that drove the packing, which is what makes this a
      post-condition instead of a restatement. It is also the backstop for a hard split that could
      not cut where the count said it should: returning an over-budget chunk would be a sequence the
      model silently truncates, and silent truncation is the one failure chunking exists to prevent.
    - **Every assembled sequence fits the model's cap, specials included** — `indexing.md` step 7.
      Checked against the assembled text rather than against the sum of its parts, because the
      parts' counts are exactly what an assumption of additivity would be.

    A failure is `index_failed` at the `assembly` stage: not a truncation, and not something the
    caller can fix by rewriting its prose, so the write rolls back rather than being shortened by a
    model that reports nothing.
    """
    for chunk in plan.chunks:
        if chunk.token_count > plan.effective_budget:
            raise ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.ASSEMBLY)
        assembled = encoder.count_tokens(chunk.embedded_text(gist)) + encoder.n_special_tokens
        if assembled > encoder.max_sequence_tokens:
            raise ZikaronError(ErrorCode.INDEX_FAILED, stage=IndexStage.ASSEMBLY)
