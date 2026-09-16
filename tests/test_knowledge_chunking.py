"""`zikaron.core.knowledge.chunking` — line-aware, verbatim, budget-respecting chunk planning.

The three properties the module promises are asserted directly rather than implied: chunks hold
whole lines verbatim, they partition the file's lines, and what is embedded fits the model.
"""

from dataclasses import dataclass
from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.fake_encoder import FakeEncoder
from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.indexing.chunking import PREFIX_SEPARATOR
from zikaron.core.knowledge.chunking import FileChunkPlan, plan_file_chunks, split_lines

_PATH: Final = "docs/runbook.md"

#: Every character `str.splitlines` treats as a line break and this chunker does not. Written as
#: code points rather than as literals because two of them are invisible, and an invisible character
#: in a test fixture is one nobody can review.
_PYTHON_LINE_BOUNDARIES: Final = tuple(
    chr(code) for code in (0x0B, 0x0C, 0x0D, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029)
)


def _plan(
    text: str,
    *,
    path: str = _PATH,
    encoder: FakeEncoder | None = None,
    chunk_max_tokens: int = 450,
) -> FileChunkPlan:
    return plan_file_chunks(
        path=path,
        text=text,
        encoder=encoder if encoder is not None else FakeEncoder(),
        chunk_max_tokens=chunk_max_tokens,
    )


def _rejoined(plan: FileChunkPlan) -> str:
    return "".join(chunk.text for chunk in plan.chunks)


# ---------------------------------------------------------------------------
# split_lines
# ---------------------------------------------------------------------------


def test_an_empty_file_has_no_lines() -> None:
    assert split_lines("") == ()


def test_each_line_keeps_its_own_terminator() -> None:
    assert split_lines("alpha\nbeta\n") == ("alpha\n", "beta\n")


def test_a_file_not_ending_in_a_newline_keeps_its_last_line_unterminated() -> None:
    """The one file shape most likely to be quoted back, and the one a chunker that appends a
    terminator would disagree with the file about by exactly one byte."""
    assert split_lines("alpha\nbeta") == ("alpha\n", "beta")


def test_a_blank_line_is_a_line() -> None:
    assert split_lines("\n\n") == ("\n", "\n")


def test_a_carriage_return_stays_inside_its_line() -> None:
    """A CRLF file needs no special case: splitting on `\\n` alone leaves the `\\r` where it was,
    which is what keeps the stored text byte-identical to the file."""
    assert split_lines("alpha\r\nbeta\r\n") == ("alpha\r\n", "beta\r\n")


@pytest.mark.parametrize(
    "character",
    _PYTHON_LINE_BOUNDARIES,
    ids=["vt", "ff", "cr", "fs", "gs", "rs", "nel", "ls", "ps"],
)
def test_the_nine_characters_python_would_break_on_are_not_line_ends(character: str) -> None:
    """`str.splitlines` breaks on all nine. A file carrying any of them would then have every later
    line number shifted away from what git, an editor and the agent's own file reader count."""
    assert len(f"a{character}b".splitlines()) > 1
    assert split_lines(f"a{character}b") == (f"a{character}b",)


# ---------------------------------------------------------------------------
# The partition property
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.text(alphabet=st.characters(blacklist_characters="\n"), max_size=12), max_size=25),
    st.booleans(),
)
def test_chunks_concatenate_back_to_the_file_exactly(lines: list[str], trailing: bool) -> None:
    """Nothing is lost and nothing is duplicated, whatever the packing did — the property that
    makes a stored chunk a copy of the file rather than a rendering of it."""
    text = "\n".join(lines) + ("\n" if trailing and lines else "")
    plan = _plan(text, chunk_max_tokens=3)
    assert _rejoined(plan) == text


@settings(max_examples=200, deadline=None)
@given(
    st.lists(st.sampled_from(["one two three", "", "four", "five six"]), max_size=25),
    st.integers(min_value=1, max_value=6),
)
def test_line_ranges_are_contiguous_and_cover_every_line(
    lines: list[str], chunk_max_tokens: int
) -> None:
    text = "".join(f"{line}\n" for line in lines)
    plan = _plan(text, chunk_max_tokens=chunk_max_tokens)
    expected_line = 1
    for chunk in plan.chunks:
        assert chunk.start_line == expected_line
        assert chunk.end_line >= chunk.start_line
        expected_line = chunk.end_line + 1
    assert expected_line - 1 == len(split_lines(text))


def test_part_index_counts_from_zero_without_gaps() -> None:
    plan = _plan("one two three four\nfive six seven eight\nnine ten\n", chunk_max_tokens=4)
    assert [chunk.part_index for chunk in plan.chunks] == list(range(plan.n_chunks))


def test_a_chunks_text_is_exactly_the_lines_its_range_names() -> None:
    text = "alpha\nbeta\ngamma\ndelta\n"
    plan = _plan(text, chunk_max_tokens=2)
    lines = split_lines(text)
    for chunk in plan.chunks:
        assert chunk.text == "".join(lines[chunk.start_line - 1 : chunk.end_line])


def test_an_empty_file_produces_no_chunks() -> None:
    plan = _plan("")
    assert plan.chunks == ()
    assert plan.n_chunks == 0


def test_a_file_of_only_blank_lines_produces_one_blank_chunk() -> None:
    """Stated rather than special-cased: dropping it would make the partition property conditional,
    and a blank chunk costs one row where a conditional property costs an argument every later
    reader has to reconstruct."""
    plan = _plan("\n\n\n")
    assert _rejoined(plan) == "\n\n\n"
    assert plan.n_chunks == 1


# ---------------------------------------------------------------------------
# Packing
# ---------------------------------------------------------------------------


def test_a_whole_short_file_is_one_chunk() -> None:
    plan = _plan("alpha beta\n\ngamma\n")
    assert plan.n_chunks == 1
    assert plan.chunks[0].start_line == 1
    assert plan.chunks[0].end_line == 3


def test_a_break_falls_after_a_blank_run_when_the_budget_allows() -> None:
    """Paragraphs are what packing prefers: the blank line stays with the paragraph above it, so a
    reader sees the break where they would have put it."""
    plan = _plan("one two\n\nthree four\n", chunk_max_tokens=2)
    assert [(chunk.start_line, chunk.end_line) for chunk in plan.chunks] == [(1, 2), (3, 3)]
    assert plan.chunks[0].text == "one two\n\n"


def test_a_paragraph_too_large_for_one_chunk_breaks_at_line_boundaries() -> None:
    text = "one two\nthree four\nfive six\n"
    plan = _plan(text, chunk_max_tokens=3)
    assert [(chunk.start_line, chunk.end_line) for chunk in plan.chunks] == [(1, 1), (2, 2), (3, 3)]
    assert _rejoined(plan) == text


def test_an_over_large_paragraph_flushes_what_was_already_pending() -> None:
    """The paragraph that will not fit does not drag the chunk before it along: that one is emitted
    first, so a break never lands in the middle of a paragraph that fitted perfectly well."""
    text = "tiny\n\none two three four five\n"
    plan = _plan(text, chunk_max_tokens=3)
    assert plan.chunks[0].text == "tiny\n\n"
    assert _rejoined(plan) == text


def test_packing_is_deterministic() -> None:
    text = "alpha beta\ngamma delta\n\nepsilon\nzeta eta theta\n"
    first = _plan(text, chunk_max_tokens=4)
    second = _plan(text, chunk_max_tokens=4)
    assert [(c.part_index, c.start_line, c.end_line, c.text) for c in first.chunks] == [
        (c.part_index, c.start_line, c.end_line, c.text) for c in second.chunks
    ]


# ---------------------------------------------------------------------------
# The over-long line
# ---------------------------------------------------------------------------


def test_an_over_long_line_is_stored_whole_and_embedded_from_its_head() -> None:
    line = " ".join(f"w{index}" for index in range(30))
    plan = _plan(f"{line}\n", chunk_max_tokens=5)
    (chunk,) = plan.chunks
    assert chunk.text == f"{line}\n"
    assert chunk.head_only is True
    assert chunk.embedded_body == " ".join(f"w{index}" for index in range(5))
    assert plan.head_only_chunks == 1


def test_an_over_long_line_keeps_its_own_line_number() -> None:
    line = " ".join(f"w{index}" for index in range(30))
    plan = _plan(f"first\n{line}\nlast\n", chunk_max_tokens=5)
    over_long = next(chunk for chunk in plan.chunks if chunk.head_only)
    assert (over_long.start_line, over_long.end_line) == (2, 2)


def test_an_ordinary_chunk_embeds_its_whole_text() -> None:
    plan = _plan("alpha beta\n")
    (chunk,) = plan.chunks
    assert chunk.head_only is False
    assert chunk.embedded_body == chunk.text


def test_the_embedded_sequence_is_the_path_then_the_separator_then_the_body() -> None:
    plan = _plan("alpha beta\n")
    (chunk,) = plan.chunks
    assert chunk.embedded_text(_PATH) == f"{_PATH}{PREFIX_SEPARATOR}{chunk.text}"
    assert plan.prefix == _PATH
    assert plan.embedded_texts() == (chunk.embedded_text(_PATH),)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def test_the_budget_is_the_smaller_of_the_corpus_setting_and_what_the_model_leaves() -> None:
    encoder = FakeEncoder(max_sequence_tokens=20, n_special_tokens=2)
    plan = plan_file_chunks(path="a b c", text="x\n", encoder=encoder, chunk_max_tokens=450)
    assert plan.effective_budget == 20 - 2 - 3 - 1


def test_the_corpus_setting_binds_when_it_is_the_smaller() -> None:
    assert _plan("x\n", chunk_max_tokens=7).effective_budget == 7


def test_a_path_too_long_to_leave_room_for_content_is_shortened_not_refused() -> None:
    """A deep enough path used to make a file permanently unindexable: every build died on it, in
    the same place, with nothing in any report naming the file or saying why, and the only remedy
    an exclude glob nobody had a pointer toward. The prefix is an address rather than content, so
    the prefix is what yields."""
    encoder = FakeEncoder(max_sequence_tokens=8, n_special_tokens=2)
    plan = plan_file_chunks(
        path="a b c d e f g h", text="content\n", encoder=encoder, chunk_max_tokens=450
    )
    assert plan.prefix == "a b c d"
    assert plan.effective_budget == 1
    assert plan.chunks[0].text == "content\n"
    assert plan.embedded_texts() == (f"a b c d{PREFIX_SEPARATOR}content\n",)


def test_a_path_that_fits_is_used_whole() -> None:
    assert _plan("alpha\n").prefix == _PATH


def test_a_model_with_no_room_for_content_at_all_is_refused() -> None:
    """Nothing about the file: a configured model whose whole input is its special tokens and a
    separator can embed nothing at all, so this is the one budget failure left and what it names is
    a model rather than a path."""
    encoder = FakeEncoder(max_sequence_tokens=3, n_special_tokens=2)
    with pytest.raises(ZikaronError) as excinfo:
        plan_file_chunks(path="a", text="x\n", encoder=encoder, chunk_max_tokens=450)
    assert excinfo.value.code is ErrorCode.INDEX_FAILED
    assert excinfo.value.data["stage"] == IndexStage.BUDGET


@dataclass
class _JoinMergingEncoder(FakeEncoder):
    """An encoder whose token count for several lines is not the sum of its count for each.

    The packer's running sum assumes joining at a line terminator merges no tokens, which is true of
    the deployed tokenizer and measured. This is what happens if that ever stops being true: the
    post-condition recount catches it, rather than a sequence reaching the model over-length.
    """

    def count_tokens(self, text: str) -> int:
        lines = [line for line in text.split("\n") if line]
        return 1 if len(lines) <= 1 else 100


def test_a_plan_whose_chunks_do_not_fit_their_own_budget_is_refused() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        _plan("one\ntwo\nthree\n", encoder=_JoinMergingEncoder(), chunk_max_tokens=4)
    assert excinfo.value.code is ErrorCode.INDEX_FAILED
    assert excinfo.value.data["stage"] == IndexStage.ASSEMBLY


@dataclass
class _PrefixFusingEncoder(FakeEncoder):
    """An encoder for which the path prefix costs far more once it is joined to the body.

    The body fits the budget on its own and the assembled sequence does not, which is the exact
    failure counting the two pieces separately would miss.
    """

    def count_tokens(self, text: str) -> int:
        """Expensive only for the *exact* sequence the plan emits: path, separator, then body.

        The trigger is deliberately this narrow. An earlier version fired on any text containing
        the separator anywhere and beginning with the path — which a body ending in a newline
        satisfies whether or not the separator was ever placed between the two, so the check passed
        against an assembly that counted `path + body` with the separator dropped. A fake that
        cannot tell the emitted string from a near-miss cannot guard the one property this test is
        named for.
        """
        counted = len(text.split())
        return counted * 1000 if text.startswith(f"{_PATH}{PREFIX_SEPARATOR}") else counted


def test_a_plan_whose_assembled_sequence_overruns_the_model_is_refused() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        _plan("alpha beta\n", encoder=_PrefixFusingEncoder(), chunk_max_tokens=4)
    assert excinfo.value.code is ErrorCode.INDEX_FAILED
    assert excinfo.value.data["stage"] == IndexStage.ASSEMBLY
