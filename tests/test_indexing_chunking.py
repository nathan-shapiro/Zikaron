"""The chunking preflight, against `design/indexing.md` §"Chunk construction" and §Storage.

Every test here is over a pure function — no store, no connection — so the determinism the design
requires is asserted directly rather than inferred: `plan_chunks` is called twice on the same input
and the two results are compared as whole objects.

The `FakeEncoder`'s whitespace tokenizer is what makes the budgets hand-computable — "seven words,
budget five, so two chunks" is a statement about the packing rule. Fidelity to the real WordPiece
vocabulary is the integration tier's job, in `test_indexing_integration.py`.
"""

import re
from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.design_tables import document_lines, table_with_columns
from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing.chunking import (
    GIST_MAX_CHARACTERS,
    PREFIX_SEPARATOR,
    SEPARATOR_TOKENS,
    ChunkPlan,
    paragraphs,
    plan_chunks,
    utf16_units,
)

DESIGN_DOCUMENT: Final = "indexing.md"

_GIST: Final = "protobuf codegen fails silently on staging"


def _plan(
    content: str,
    *,
    gist: str = _GIST,
    encoder: FakeEncoder | None = None,
    chunk_max_tokens: int = 450,
    gist_max_tokens: int = 64,
) -> ChunkPlan:
    return plan_chunks(
        gist=gist,
        content=content,
        encoder=encoder if encoder is not None else FakeEncoder(),
        chunk_max_tokens=chunk_max_tokens,
        gist_max_tokens=gist_max_tokens,
    )


def _words(count: int, *, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))


# ---------------------------------------------------------------------------
# The common case, and the budget arithmetic behind it
# ---------------------------------------------------------------------------


def test_a_short_memory_yields_exactly_one_chunk() -> None:
    """`indexing.md`: "for the common short memory this yields exactly one chunk"."""
    plan = _plan("the proto compiler version drifts from the pinned one")
    assert plan.n_chunks == 1
    assert plan.chunks[0].part_index == 0
    assert plan.chunks[0].truncated is False
    assert plan.truncated is False


def test_part_index_is_zero_based_and_contiguous() -> None:
    plan = _plan(
        "\n\n".join(_words(4, prefix=f"p{part}w") for part in range(5)), chunk_max_tokens=4
    )
    assert [chunk.part_index for chunk in plan.chunks] == list(range(plan.n_chunks))
    assert plan.n_chunks == 5


def test_the_effective_budget_is_the_smaller_of_the_config_and_the_models_room() -> None:
    """`content_budget = cap - specials - gist - separator`, then `min` with `chunk_max_tokens`."""
    encoder = FakeEncoder()
    gist = _words(10)
    plan = _plan("one paragraph", gist=gist, encoder=encoder, chunk_max_tokens=450)
    room = encoder.max_sequence_tokens - encoder.n_special_tokens - 10 - SEPARATOR_TOKENS
    assert plan.gist_tokens == 10
    assert plan.effective_budget == min(450, room)
    assert plan.effective_budget == 450, "the config bound is what binds at a 10-token gist"


def test_a_long_gist_makes_the_models_cap_bind_instead_of_the_config() -> None:
    encoder = FakeEncoder(max_sequence_tokens=64)
    plan = _plan(
        "a b c", gist=_words(20), encoder=encoder, chunk_max_tokens=450, gist_max_tokens=64
    )
    assert plan.effective_budget == 64 - 2 - 20 - SEPARATOR_TOKENS


def test_the_designs_stated_floor_follows_from_this_modules_own_constants() -> None:
    """The design states the floor as a number; this recomputes it from the code's constants.

    A two-way guard: the design's `445` moving, or `SEPARATOR_TOKENS` moving, fails here. The four
    inputs are the ones the design's own sentence names — a 512 cap, 2 specials, the 64-token gist
    ceiling, one separator.
    """
    prose = "\n".join(document_lines(DESIGN_DOCUMENT))
    stated = re.findall(r"the floor is (\d+)", prose)
    assert len(stated) == 1, "the design must state its floor exactly once"
    assert int(stated[0]) == 512 - 2 - 64 - SEPARATOR_TOKENS


# ---------------------------------------------------------------------------
# Paragraph-greedy packing, no overlap
# ---------------------------------------------------------------------------


def test_paragraphs_split_on_blank_lines_and_are_stripped() -> None:
    assert paragraphs("first\n\nsecond") == ("first", "second")
    assert paragraphs("first\n   \n\n  second  ") == ("first", "second")
    assert paragraphs("one line\nstill one paragraph") == ("one line\nstill one paragraph",)


def test_adjacent_paragraphs_merge_while_they_fit_and_break_when_they_do_not() -> None:
    content = "\n\n".join(["a1 a2", "b1 b2", "c1 c2"])
    plan = _plan(content, chunk_max_tokens=4)
    assert [chunk.text for chunk in plan.chunks] == ["a1 a2\n\nb1 b2", "c1 c2"]
    assert [chunk.token_count for chunk in plan.chunks] == [4, 2]


def test_no_chunk_overlaps_its_neighbour() -> None:
    """D28 rejects overlap outright: near-duplicate chunks both retrieve, and the push path has
    only five slots to spend."""
    content = "\n\n".join(_words(3, prefix=f"p{part}w") for part in range(4))
    plan = _plan(content, chunk_max_tokens=3)
    seen: list[str] = []
    for chunk in plan.chunks:
        seen.extend(chunk.text.split())
    assert len(seen) == len(set(seen)), "a token appears in two chunks"


def test_the_gist_is_prepended_to_every_chunk_with_one_separator() -> None:
    plan = _plan("\n\n".join(["a1 a2", "b1 b2"]), chunk_max_tokens=2)
    assert plan.n_chunks == 2
    for chunk in plan.chunks:
        assembled = chunk.embedded_text(_GIST)
        assert assembled == f"{_GIST}{PREFIX_SEPARATOR}{chunk.text}"
    assert plan.embedded_texts(_GIST) == tuple(chunk.embedded_text(_GIST) for chunk in plan.chunks)


# ---------------------------------------------------------------------------
# The hard split and its canary
# ---------------------------------------------------------------------------


def test_an_oversized_paragraph_is_hard_split_and_every_piece_is_flagged_truncated() -> None:
    plan = _plan(_words(7), chunk_max_tokens=3)
    assert [chunk.text for chunk in plan.chunks] == ["w0 w1 w2", "w3 w4 w5", "w6"]
    assert all(chunk.truncated for chunk in plan.chunks)
    assert plan.truncated is True


def test_a_hard_split_paragraph_does_not_absorb_the_paragraph_after_it() -> None:
    """The packer restarts empty after a hard split, so `truncated` keeps a per-chunk meaning."""
    plan = _plan(f"{_words(4)}\n\nafter", chunk_max_tokens=3)
    assert [(chunk.text, chunk.truncated) for chunk in plan.chunks] == [
        ("w0 w1 w2", True),
        ("w3", True),
        ("after", False),
    ]


def test_truncated_is_false_for_a_memory_the_budget_never_cut() -> None:
    plan = _plan("\n\n".join(["a1 a2", "b1 b2 b3"]), chunk_max_tokens=3)
    assert plan.n_chunks == 2
    assert plan.truncated is False


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_chunk_boundaries_are_identical_across_two_runs_on_one_input() -> None:
    """`coding-standards.md` §4: determinism gets asserted, not assumed."""
    content = "\n\n".join([_words(9), "short one", _words(5, prefix="x")])
    first = _plan(content, chunk_max_tokens=4)
    second = _plan(content, chunk_max_tokens=4)
    assert first == second
    assert [chunk.text for chunk in first.chunks] == [chunk.text for chunk in second.chunks]


# ---------------------------------------------------------------------------
# Sizes reported
# ---------------------------------------------------------------------------


def test_content_tokens_counts_content_alone_and_gist_tokens_counts_the_gist() -> None:
    """`indexing.md` §Storage: the two are siblings, so neither includes the other."""
    plan = _plan(_words(12), gist=_words(3))
    assert plan.gist_tokens == 3
    assert plan.content_tokens == 12


def test_chunk_token_counts_sum_to_the_content_count_when_only_blank_lines_were_dropped() -> None:
    """Per-chunk `token_count` is the chunk's own slice, so the slices account for the content."""
    plan = _plan(
        "\n\n".join([_words(4), _words(4, prefix="x"), _words(4, prefix="y")]), chunk_max_tokens=4
    )
    assert plan.n_chunks == 3
    assert sum(chunk.token_count for chunk in plan.chunks) == plan.content_tokens


# ---------------------------------------------------------------------------
# The one bound that rejects a write, and the two index_failed stages
# ---------------------------------------------------------------------------


def test_a_gist_over_its_bound_is_rejected_naming_the_limit_and_the_actual_count() -> None:
    """`indexing.md` step 1: the one place a write is refused, and safe to refuse because the agent
    still holds its own text."""
    with pytest.raises(ZikaronError) as raised:
        _plan("content", gist=_words(65), gist_max_tokens=64)
    assert raised.value.code is ErrorCode.BOUNDS
    assert dict(raised.value.data) == {"field": "gist", "limit": 64, "actual": 65}


def test_a_gist_exactly_at_its_bound_is_accepted() -> None:
    plan = _plan("content", gist=_words(64), gist_max_tokens=64)
    assert plan.gist_tokens == 64


def test_a_gist_over_the_character_bound_is_rejected_naming_the_unit_in_the_field() -> None:
    """The bound that exists because tokens constrain neither characters nor bytes. The field name
    carries the unit because the error payload does not: two bounds on `gist` reporting only a
    limit and an actual would be indistinguishable to the agent reading them.
    """
    with pytest.raises(ZikaronError) as raised:
        _plan("content", gist="a" * (GIST_MAX_CHARACTERS + 1), gist_max_tokens=256)
    assert raised.value.code is ErrorCode.BOUNDS
    assert dict(raised.value.data) == {
        "field": "gist.characters",
        "limit": GIST_MAX_CHARACTERS,
        "actual": GIST_MAX_CHARACTERS + 1,
    }


def test_the_character_bound_counts_utf16_units_so_astral_characters_cost_two() -> None:
    """The bound and the injection budget must count in one unit, or the bound stops proving
    anything about the budget.

    Half the bound in astral characters is exactly at it; one more is over. A code-point count
    would admit twice as many, and five such gists would then overrun the very budget this bound
    exists to keep the injected block inside.
    """
    astral = "\U00010348"
    assert len(astral) == 1, "one code point, two UTF-16 units"
    exactly_at = astral * (GIST_MAX_CHARACTERS // 2)
    assert _plan("content", gist=exactly_at, gist_max_tokens=256) is not None
    with pytest.raises(ZikaronError) as raised:
        _plan("content", gist=exactly_at + astral, gist_max_tokens=256)
    assert dict(raised.value.data) == {
        "field": "gist.characters",
        "limit": GIST_MAX_CHARACTERS,
        "actual": GIST_MAX_CHARACTERS + 2,
    }


def test_utf16_units_never_under_reports_and_tolerates_a_lone_surrogate() -> None:
    """Total by construction: a lone surrogate is legal in a string decoded from JSON, and a
    counter that raised on one would turn a bound check into an exception at the write path.
    """
    for text in ("", "ascii", "— dashes —", "漢字", "\U00010348", "\ud800"):
        assert utf16_units(text) >= len(text)
    assert utf16_units("\ud800") == 1
    assert utf16_units("\U00010348") == 2


def test_a_gist_exactly_at_the_character_bound_is_accepted() -> None:
    """Inclusive, like every other bound here. One character over and exactly at is what separates
    the two, since a fixture merely "long" passes either way.
    """
    assert _plan("content", gist="a" * GIST_MAX_CHARACTERS, gist_max_tokens=256) is not None


def test_the_character_bound_catches_what_the_token_bound_structurally_cannot() -> None:
    """The whole reason the character bound exists, stated as a test rather than as a comment.

    A tokenizer maps an unbroken run outside its vocabulary to a single unknown token, so an
    arbitrarily long gist can satisfy every token bound the write path states. Without a bound in a
    unit that actually constrains size, no claim about the injected block fitting a harness budget
    is provable at all.
    """
    pathological = "a" * 4000
    encoder = FakeEncoder()
    assert encoder.count_tokens(pathological) <= 256, (
        "the premise: this passes the token bound comfortably"
    )
    with pytest.raises(ZikaronError) as raised:
        _plan("content", gist=pathological, gist_max_tokens=256)
    assert dict(raised.value.data)["field"] == "gist.characters"


def test_characters_are_checked_before_tokens() -> None:
    """A validation-precedence question, and the order is observable so it is behaviour. Characters
    first because it is the cheaper check — no tokenizer — and the more actionable rejection, since
    an agent can count the characters it just wrote and cannot count subword tokens.
    """
    over_both = "word " * 400
    assert len(over_both) > GIST_MAX_CHARACTERS
    with pytest.raises(ZikaronError) as raised:
        _plan("content", gist=over_both, gist_max_tokens=64)
    assert dict(raised.value.data)["field"] == "gist.characters"


def test_the_character_bound_matches_the_number_the_design_states() -> None:
    """Read from `schema.md` §Bounds itself rather than from a second transcription of it, so the
    design being revised while this constant stays put is a failing test rather than a silent
    disagreement about what the write path enforces.

    **This imposes a constraint on the design document, and the failure message is the only place a
    future editor will meet it:** the Value cell must contain exactly one number, so a unit whose
    name contains a digit cannot be written there — spell it in the Why column instead. Failing
    closed on an ambiguous cell is deliberate; picking one of two candidate numbers would let this
    guard go on passing while checking the wrong one.
    """
    rows = table_with_columns("schema.md", "## Bounds", ("Bound", "Value", "Why"))
    stated = [row["Value"] for row in rows if "gist.characters" in row["Bound"]]
    assert len(stated) == 1, "schema.md must state the gist character bound exactly once"
    numbers = re.findall(r"\d[\d,]*", stated[0])
    assert len(numbers) == 1, f"expected exactly one number in {stated[0]!r}, found {numbers}"
    assert int(numbers[0].replace(",", "")) == GIST_MAX_CHARACTERS


def test_emptiness_is_still_checked_before_either_length_bound() -> None:
    """A blank gist reports emptiness rather than a length, which is the more useful of the two
    answers and was the existing order before a second length bound joined it.
    """
    with pytest.raises(ZikaronError) as raised:
        _plan("content", gist="   ")
    assert dict(raised.value.data) == {"field": "gist", "limit": 1, "actual": 0}


@pytest.mark.parametrize("blank", ["", "   ", "\n\t\n"])
def test_empty_prose_is_rejected_as_bounds_on_either_field(blank: str) -> None:
    """`schema.md` §Bounds states non-emptiness for both fields, and this is the layer that can
    refuse before any SQL runs — the table's own CHECK would otherwise surface as an
    `IntegrityError` with no field named."""
    with pytest.raises(ZikaronError) as gist_raised:
        _plan("content", gist=blank)
    assert dict(gist_raised.value.data) == {"field": "gist", "limit": 1, "actual": 0}
    with pytest.raises(ZikaronError) as content_raised:
        _plan(blank)
    assert dict(content_raised.value.data) == {"field": "content", "limit": 1, "actual": 0}


def test_a_model_leaving_no_room_for_content_is_index_failed_at_the_budget_stage() -> None:
    encoder = FakeEncoder(max_sequence_tokens=8)
    with pytest.raises(ZikaronError) as raised:
        _plan("content", gist=_words(6), encoder=encoder, gist_max_tokens=64)
    assert raised.value.code is ErrorCode.INDEX_FAILED
    assert raised.value.data["stage"] == IndexStage.BUDGET


def test_an_assembled_sequence_over_the_cap_is_index_failed_at_the_assembly_stage() -> None:
    """Step 7's assertion. Reached with an encoder whose count of the *assembled* text exceeds what
    its counts of the parts imply — the additivity assumption the assertion exists to not make."""

    class NonAdditiveEncoder(FakeEncoder):
        def count_tokens(self, text: str) -> int:
            counted = super().count_tokens(text)
            return counted * 100 if PREFIX_SEPARATOR in text else counted

    with pytest.raises(ZikaronError) as raised:
        _plan("a b c", encoder=NonAdditiveEncoder())
    assert raised.value.code is ErrorCode.INDEX_FAILED
    assert raised.value.data["stage"] == IndexStage.ASSEMBLY


def test_an_encoder_whose_spans_are_missing_entirely_yields_no_plan_at_all() -> None:
    """A count saying "over budget" with no token spans to cut on is a contradiction, and the answer
    is to refuse rather than to return the paragraph whole and call it a chunk."""

    class SpanlessEncoder(FakeEncoder):
        def count_tokens(self, text: str) -> int:
            return 999 if text else 0

        def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:  # noqa: ARG002
            return ()

    encoder = SpanlessEncoder(max_sequence_tokens=100_000)
    with pytest.raises(ZikaronError) as raised:
        _plan("one paragraph", encoder=encoder, chunk_max_tokens=3, gist_max_tokens=99_999)
    assert raised.value.code is ErrorCode.INDEX_FAILED
    assert raised.value.data["stage"] == IndexStage.ASSEMBLY


def test_spans_covering_only_part_of_a_paragraph_yield_no_plan_at_all() -> None:
    """The dangerous shape of the same disagreement: spans that are well-formed but **short**.

    In range, in order, non-overlapping — and covering only the paragraph's first few tokens. The
    pieces cut from them are inside their budget and their assembled sequences inside the cap, so
    every later check passes while the paragraph's tail is silently absent from the dense index.
    Nothing downstream can notice, because nothing downstream looks at the paragraph again; the
    counts are therefore compared where the cut is made.
    """

    class PrefixSpanEncoder(FakeEncoder):
        """Counts every word but reports spans for only the first half of them."""

        def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:
            full = super().token_char_spans(text)
            return full[: len(full) // 2]

    with pytest.raises(ZikaronError) as raised:
        _plan(_words(8), encoder=PrefixSpanEncoder(), chunk_max_tokens=2)
    assert raised.value.code is ErrorCode.INDEX_FAILED
    assert raised.value.data["stage"] == IndexStage.ASSEMBLY


def test_a_recounted_chunk_over_its_budget_is_refused_even_when_it_fits_the_models_cap() -> None:
    """The post-condition recounts what was emitted rather than trusting the window that cut it.

    A real WordPiece tokenizer can retokenize a slice differently from how it tokenized the
    paragraph the slice came from — a cut that lands inside a word leaves a fragment the vocabulary
    splits its own way — so a window of `budget` tokens can emit a piece that counts more than
    `budget` on its own. Recounting the emitted text is what notices, and a large model cap is used
    here so the assembled-sequence half of the check cannot be what fires.
    """

    class DriftingEncoder(FakeEncoder):
        """Counts one token per word, except for one slice it reports as one token longer."""

        def count_tokens(self, text: str) -> int:
            counted = super().count_tokens(text)
            return counted + 1 if text == "w2 w3" else counted

    encoder = DriftingEncoder(max_sequence_tokens=100_000)
    with pytest.raises(ZikaronError) as raised:
        _plan(_words(4), encoder=encoder, chunk_max_tokens=2, gist_max_tokens=99_999)
    assert raised.value.code is ErrorCode.INDEX_FAILED
    assert raised.value.data["stage"] == IndexStage.ASSEMBLY


# ---------------------------------------------------------------------------
# Properties, over generated prose
# ---------------------------------------------------------------------------

#: Prose assembled from fragments rather than from single characters, so the generated corpus
#: actually contains the structures the packer decides on: blank lines, runs of whitespace,
#: multi-character tokens and punctuation the tokenizer keeps inside a token.
_PROSE = (
    st.lists(
        st.sampled_from(["a", "b", "z9", " ", "\n", "\n\n", "  ", "x_y", "-", ".", "\t"]),
        min_size=1,
        max_size=40,
    )
    .map("".join)
    # Blank content is a `bounds` rejection with a test of its own, so it is filtered out here
    # rather than skipped inside the body: `pytest.skip` in a Hypothesis test skips the *whole*
    # test on the first blank example, which silently retires the property.
    .filter(lambda prose: bool(prose.strip()))
)


@given(content=_PROSE, budget=st.integers(min_value=1, max_value=6))
@settings(max_examples=250, deadline=None)
def test_property_chunking_never_loses_content(content: str, budget: int) -> None:
    """Every non-whitespace character of `content` survives, in order, across the chunks.

    The whole point of chunking rather than truncating: the store keeps the prose. Only whitespace
    may be dropped — blank lines at a paragraph boundary, and the run between two tokens where a
    hard split cut.
    """
    plan = _plan(content, chunk_max_tokens=budget)
    assert "".join("".join(chunk.text.split()) for chunk in plan.chunks) == "".join(content.split())


@given(content=_PROSE, budget=st.integers(min_value=1, max_value=6))
@settings(max_examples=250, deadline=None)
def test_property_every_chunk_fits_the_budget_and_at_least_one_exists(
    content: str, budget: int
) -> None:
    """Invariant 12's structural half — an active memory always has a chunk — plus the bound each
    chunk was cut to. A chunk over budget would be a sequence the model truncates silently."""
    plan = _plan(content, chunk_max_tokens=budget)
    assert plan.n_chunks >= 1
    assert all(chunk.token_count <= plan.effective_budget for chunk in plan.chunks)
    assert all(chunk.token_count >= 1 or not chunk.text for chunk in plan.chunks)


@given(content=_PROSE)
@settings(max_examples=100, deadline=None)
def test_property_the_plan_is_a_pure_function_of_its_inputs(content: str) -> None:
    assert _plan(content, chunk_max_tokens=3) == _plan(content, chunk_max_tokens=3)
