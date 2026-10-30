"""What a named result shows of its file: the opening, read from the first chunk alone.

The opening parses no markdown (`knowledge-index.md` §1.1); the one structure it skips is the
link front matter the index already reads, found by the same line reader as `read_link`, so the
two cannot split a block's lines differently.
"""

from pathlib import Path
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zikaron.core.knowledge import excerpts
from zikaron.core.knowledge.links import (
    LINK_PREFIX_CHARS,
    SourceLink,
    front_matter_end,
    read_link,
)

_SHA1: Final = "0123456789abcdef0123456789abcdef01234567"
_LINKED: Final = f"---\nzikaron-source: lib/foo.py\nzikaron-source-blob: {_SHA1}\n---\n"
_BODY: Final = "# `lib/foo.py`\n\nParses the frobnicator's  config.\n\n## Purpose\n"


@pytest.fixture
def limit() -> int:
    return excerpts.OPENING_MAX_CHARS


class TestTheOpening:
    def test_a_linked_document_opens_after_its_front_matter(self) -> None:
        assert excerpts.opening_of(_LINKED + _BODY) == (
            "# `lib/foo.py` Parses the frobnicator's config. ## Purpose"
        )

    def test_an_unlinked_document_opens_at_its_first_character(self) -> None:
        assert excerpts.opening_of(_BODY) == (
            "# `lib/foo.py` Parses the frobnicator's config. ## Purpose"
        )

    def test_front_matter_of_another_kind_is_the_file_s_own_text(self) -> None:
        assert excerpts.opening_of("---\ntitle: a page\n---\nbody\n") == (
            "--- title: a page --- body"
        )

    def test_a_malformed_link_block_within_the_chunk_is_skipped(self) -> None:
        malformed = "---\nzikaron-source: lib/foo.py\n---\nbody text\n"
        assert read_link(malformed) is not None
        assert excerpts.opening_of(malformed) == "body text"

    def test_a_block_that_closes_past_the_prefix_stays_in(self) -> None:
        padding = "".join(f"note: {index}\n" for index in range(LINK_PREFIX_CHARS // 8))
        unclosed = f"---\nzikaron-source: lib/foo.py\n{padding}---\nbody\n"
        opening = excerpts.opening_of(unclosed)
        assert opening.startswith("--- zikaron-source: lib/foo.py note: 0")

    def test_a_block_still_open_at_the_chunk_s_end_stays_in(self) -> None:
        assert excerpts.opening_of("---\nzikaron-source: lib/foo.py\n") == (
            "--- zikaron-source: lib/foo.py"
        )

    def test_nothing_but_front_matter_opens_as_the_empty_string(self) -> None:
        assert excerpts.opening_of(_LINKED + "\n  \n") == ""

    def test_the_cut_falls_on_the_last_space_that_leaves_room(self, limit: int) -> None:
        kept = limit // len("word ")
        opening = excerpts.opening_of(" ".join(["word"] * limit))
        assert opening == " ".join(["word"] * kept) + "…"
        assert len(opening) <= limit

    def test_a_space_just_inside_the_room_is_where_it_cuts(self, limit: int) -> None:
        room = limit - 1
        text = "a" * (room - 1) + " " + "b" * 10
        assert excerpts.opening_of(text) == "a" * (room - 1) + "…"

    def test_a_space_just_past_the_room_is_not_used(self, limit: int) -> None:
        room = limit - 1
        text = "a" * (room + 1) + " " + "b" * 10
        assert excerpts.opening_of(text) == "a" * room + "…"

    def test_with_no_space_the_cut_lands_at_the_limit(self, limit: int) -> None:
        opening = excerpts.opening_of("x" * (limit * 3))
        assert opening == "x" * (limit - 1) + "…"
        assert len(opening) == limit

    def test_a_text_at_the_limit_is_not_cut(self, limit: int) -> None:
        assert excerpts.opening_of("y" * limit) == "y" * limit

    def test_the_limit_is_read_where_the_opening_is_cut(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(excerpts, "OPENING_MAX_CHARS", 10)
        assert excerpts.opening_of("abcdefghijklmnop") == "abcdefghi…"


_LINES: Final = (
    "---",
    "zikaron-source: lib/foo.py",
    f"zikaron-source-blob: {_SHA1}",
    "title: a page",
    "body",
    "",
)


@given(
    st.lists(st.sampled_from(_LINES), max_size=8),
    st.sampled_from(["\n", "\r\n"]),
)
def test_only_a_block_that_declares_a_link_is_skipped(lines: list[str], newline: str) -> None:
    """The opening skips a block exactly where `read_link` reads a declaration from one that
    closed, so the two cannot disagree about which text is the file's own."""
    text = newline.join(lines)
    end = front_matter_end(text)
    declared = read_link(text)
    if end:
        assert declared is not None
        assert text[:end].rstrip("\r\n").endswith("---")
        assert text[:end].count("---") == 2
    if isinstance(declared, SourceLink):
        assert end > 0


def test_the_limit_is_what_the_prose_about_it_says() -> None:
    """Two design sentences state the limit, and it is a number set from a measurement, so a new
    value reaching the code and not the prose is the drift this catches."""
    repo = Path(__file__).resolve().parent.parent
    for relative, phrase in (
        ("design/knowledge-index.md", f"`OPENING_MAX_CHARS` ({excerpts.OPENING_MAX_CHARS} code"),
        ("design/code-knowledge.md", f"an opening of at most {excerpts.OPENING_MAX_CHARS}"),
    ):
        body = " ".join((repo / relative).read_text(encoding="utf-8").split())
        assert phrase in body, relative
