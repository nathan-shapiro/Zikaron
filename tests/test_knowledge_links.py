"""What a document's front matter declares, read as `knowledge-index.md` §7.7's grammar says.

The grammar is strict on purpose: widening it later breaks no document and narrowing it would. So
each case below is a line of that grammar, and a declaration that gets it wrong must come back
malformed rather than absent — absent reads as a document that needs no checking.
"""

from typing import Final

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.fake_encoder import FakeEncoder
from zikaron.core.knowledge import chunking, text
from zikaron.core.knowledge.links import (
    LINK_PATH_MAX_CHARS,
    LINK_PREFIX_CHARS,
    MalformedLink,
    SourceLink,
    read_link,
)

_SHA1: Final = "0123456789abcdef0123456789abcdef01234567"
_SHA256: Final = "0123456789abcdef" * 4


def _front(*lines: str, newline: str = "\n") -> str:
    """A document opening with a `---` block holding `lines`, then a body."""
    return newline.join(["---", *lines, "---", "# body"]) + newline


_LINKED: Final = ("zikaron-source: lib/foo.py", f"zikaron-source-blob: {_SHA1}")


@pytest.mark.parametrize(
    ("document", "declared"),
    [
        pytest.param("# no front matter\n", None, id="no-front-matter"),
        pytest.param(_front("title: a page"), None, id="front-matter-without-the-keys"),
        pytest.param(_front(*_LINKED), SourceLink("lib/foo.py", _SHA1), id="unquoted"),
        pytest.param(
            _front('zikaron-source: "lib/foo.py"', f'zikaron-source-blob: "{_SHA1}"'),
            SourceLink("lib/foo.py", _SHA1),
            id="quoted",
        ),
        pytest.param(_front(*_LINKED, newline="\r\n"), SourceLink("lib/foo.py", _SHA1), id="crlf"),
        pytest.param(
            _front("zikaron-source: ../other/lib.py", f"zikaron-source-blob: {_SHA256}"),
            SourceLink("../other/lib.py", _SHA256),
            id="sha256-and-a-dot-dot-path",
        ),
        pytest.param(
            _front("title: kept", *_LINKED, "zikaron-later: ignored"),
            SourceLink("lib/foo.py", _SHA1),
            id="other-keys-and-a-reserved-one",
        ),
        pytest.param(
            _front("Zikaron-Source: lib/foo.py", f"Zikaron-Source-Blob: {_SHA1}"),
            None,
            id="case-differs-so-not-a-key",
        ),
        pytest.param(
            "--- \n" + "\n".join(_LINKED) + "\n---\n", None, id="opening-line-with-whitespace"
        ),
        pytest.param(
            "---\n" + "\n".join(_LINKED) + "\n--- \n", MalformedLink(), id="closing-with-whitespace"
        ),
        pytest.param(_front(_LINKED[0]), MalformedLink(), id="path-without-blob"),
        pytest.param(_front(_LINKED[1]), MalformedLink(), id="blob-without-path"),
        pytest.param(_front(*_LINKED, _LINKED[0]), MalformedLink(), id="a-key-twice"),
        pytest.param("---\n" + "\n".join(_LINKED) + "\n", MalformedLink(), id="never-closes"),
        pytest.param(_front("zikaron-source:", _LINKED[1]), MalformedLink(), id="empty-path"),
        pytest.param(
            _front('zikaron-source: ""', _LINKED[1]), MalformedLink(), id="empty-quoted-path"
        ),
        pytest.param(
            _front("zikaron-source: /abs/foo.py", _LINKED[1]), MalformedLink(), id="absolute"
        ),
        pytest.param(_front("zikaron-source: lib/\0foo.py", _LINKED[1]), MalformedLink(), id="nul"),
        pytest.param(
            _front(_LINKED[0], f"zikaron-source-blob: {_SHA1.upper()}"),
            MalformedLink(),
            id="uppercase-blob",
        ),
        pytest.param(
            _front(_LINKED[0], f"zikaron-source-blob: {_SHA1[:-1]}"),
            MalformedLink(),
            id="short-blob",
        ),
        pytest.param(
            "---\n" + "\n".join(_LINKED) + "\n---",
            SourceLink("lib/foo.py", _SHA1),
            id="closing-line-ends-the-text",
        ),
    ],
)
def test_the_grammar(document: str, declared: SourceLink | MalformedLink | None) -> None:
    assert read_link(document) == declared


def test_a_byte_order_mark_is_gone_before_the_reader_sees_the_text() -> None:
    """The reader is given the text as the indexer decodes it, which is what the chunks hold."""
    detection = text.sniff(("﻿" + _front(*_LINKED, newline="\r\n")).encode("utf-8"))
    assert isinstance(detection, text.DecodedText)
    assert read_link(detection.text) == SourceLink("lib/foo.py", _SHA1)


def _closing_at(terminator_index: int) -> str:
    """A linked block whose closing line's `\\n` sits at `terminator_index` of the text."""
    head = "---\n" + "\n".join(_LINKED) + "\nnote: "
    padding = terminator_index - len(head) - len("\n---")
    return head + "x" * padding + "\n---\n# body\n"


@pytest.mark.parametrize(
    ("terminator_index", "declared"),
    [
        (LINK_PREFIX_CHARS - 1, SourceLink("lib/foo.py", _SHA1)),
        (LINK_PREFIX_CHARS, MalformedLink()),
    ],
    ids=["just-inside", "just-past"],
)
def test_a_block_closing_at_the_bound(
    terminator_index: int, declared: SourceLink | MalformedLink
) -> None:
    document = _closing_at(terminator_index)
    assert document[terminator_index] == "\n"
    assert document[terminator_index - 3 : terminator_index] == "---"
    assert read_link(document) == declared


@pytest.mark.parametrize(
    ("length", "well_formed"),
    [(LINK_PATH_MAX_CHARS, True), (LINK_PATH_MAX_CHARS + 1, False)],
    ids=["just-inside", "just-past"],
)
def test_a_path_at_its_bound(length: int, well_formed: bool) -> None:
    path = "a" * (length - len(".py")) + ".py"
    declared = read_link(_front(f"zikaron-source: {path}", _LINKED[1]))
    assert declared == (SourceLink(path, _SHA1) if well_formed else MalformedLink())


_BLOCKISH: Final = st.lists(
    st.one_of(
        st.sampled_from(["---", "--- ", "\r", "zikaron-source: ", "zikaron-source-blob: ", ": "]),
        st.just(_SHA1),
        st.text(max_size=40),
    ),
    max_size=12,
)


@settings(max_examples=300, deadline=None)
@given(pieces=_BLOCKISH, joiner=st.sampled_from(["\n", "\r\n", ""]))
def test_the_reader_is_total_and_reads_stored_chunks_as_it_reads_the_file(
    pieces: list[str], joiner: str
) -> None:
    """One of the three answers for any text, and the same one for the chunks a build stores,
    joined in order — which is what the migration and search's fallback read."""
    document = joiner.join(pieces)
    declared = read_link(document)
    assert declared is None or isinstance(declared, SourceLink | MalformedLink)
    plan = chunking.plan_file_chunks(
        path="doc.md", text=document, encoder=FakeEncoder(), chunk_max_tokens=8
    )
    assert read_link("".join(chunk.text for chunk in plan.chunks)) == declared
