"""Whether a file is text: the name deny-list, the sniff, and the attribute predicate.

The deny-list is read back out of `knowledge-index.md` rather than transcribed twice, since it is
a list the design states and the likelier drift is the design moving while the code stays put.
"""

import re

import pytest

from tests.design_tables import section_lines
from zikaron.core.knowledge import text
from zikaron.core.knowledge.counters import SkipReason

_DOCUMENT = "knowledge-index.md"
_HEADING = "### 4.2 Text detection"
_BACKTICKED = re.compile(r"`([^`]+)`")
#: The two deny-list bullets name their group in single-asterisk italics; every other bullet in
#: this section opens in bold. Matching the one and not the other is what keeps this reading the
#: list rather than every code span in the section.
_GROUP_BULLET = re.compile(r"- \*(?!\*)")


def _design_endings() -> set[str]:
    """Every name ending the design's two deny-list bullets give.

    Read from the bullets that introduce each group rather than from the whole section, because
    the section quotes plenty of other code spans — attribute names, commands, column names — and
    a match over all of them would assert something much weaker than the list.
    """
    lines = section_lines(_DOCUMENT, _HEADING)
    found: set[str] = set()
    collecting = False
    for line in lines:
        if _GROUP_BULLET.match(line.lstrip()):
            collecting = True
        elif not line.startswith("  "):
            collecting = False
        if collecting:
            found.update(_BACKTICKED.findall(line))
    # The design spells the lock-file group as a glob; the code matches the same thing as the
    # ending that glob describes, which is the form a name test can use.
    return {ending.removeprefix("*") for ending in found}


class TestTheDenyList:
    def test_it_is_exactly_what_the_design_lists(self) -> None:
        assert set(text.DENIED_ENDINGS) == _design_endings()

    def test_the_two_groups_are_disjoint_and_make_up_the_whole(self) -> None:
        """They are separate for separate reasons — one group is text nobody wants, the other is
        binary that would otherwise be read in full on every scan — and an entry in both would
        make the reason for its presence unknowable."""
        assert not set(text.DENIED_TEXT_ENDINGS) & set(text.DENIED_BINARY_ENDINGS)
        assert set(text.DENIED_ENDINGS) == set(text.DENIED_TEXT_ENDINGS) | set(
            text.DENIED_BINARY_ENDINGS
        )

    @pytest.mark.parametrize(
        "name", ["bundle.min.js", "site.min.css", "poetry.lock", "package-lock.json", "logo.PNG"]
    )
    def test_a_denied_name_is_refused(self, name: str) -> None:
        assert text.extension_denied(name)

    @pytest.mark.parametrize("name", ["app.js", "site.css", "package.json", "notes.md", "Makefile"])
    def test_an_ordinary_name_is_admitted(self, name: str) -> None:
        assert not text.extension_denied(name)

    def test_the_compound_endings_do_not_deny_their_plain_forms(self) -> None:
        """A suffix test would see `.js`, `.css` and `.json` here and deny every script,
        stylesheet and JSON document there is."""
        assert not text.extension_denied("min.js.backup")
        assert not text.extension_denied("lock.json")


class TestTheSniff:
    def test_ordinary_text_decodes_and_comes_back_whole(self) -> None:
        detected = text.sniff(b"hello\nworld\n")
        assert isinstance(detected, text.DecodedText)
        assert detected.text == "hello\nworld\n"

    def test_a_byte_order_mark_is_stripped_from_the_decoded_text(self) -> None:
        detected = text.sniff(b"\xef\xbb\xbfhello")
        assert isinstance(detected, text.DecodedText)
        assert detected.text == "hello"

    def test_a_nul_in_the_first_prefix_is_binary(self) -> None:
        detected = text.sniff(b"MZ\x00\x00rest")
        assert detected == text.NotText(SkipReason.BINARY)

    def test_a_nul_past_the_prefix_is_not_what_the_sniff_looks_at(self) -> None:
        """The prefix test is a cheap reject rather than the authority: what settles the question
        is the whole-file decode below, and a NUL is valid UTF-8."""
        detected = text.sniff(b"a" * text.SNIFF_PREFIX_BYTES + b"\x00")
        assert isinstance(detected, text.DecodedText)

    def test_invalid_utf8_anywhere_is_a_decode_error(self) -> None:
        """Whole-file rather than the sniffed prefix: a file whose tail is invalid would otherwise
        be mangled from the first bad byte onward."""
        detected = text.sniff(b"a" * text.SNIFF_PREFIX_BYTES + b"\xff\xfe")
        assert detected == text.NotText(SkipReason.DECODE_ERROR)

    def test_an_empty_file_is_text(self) -> None:
        assert text.sniff(b"") == text.DecodedText("")


class TestTheAttributePredicate:
    @pytest.mark.parametrize(
        ("answers", "excluded"),
        [
            ({"binary": "set", "text": "unset"}, True),
            ({"binary": "unspecified", "text": "unset"}, True),
            ({"binary": "unspecified", "text": "auto"}, False),
            ({"binary": "unspecified", "text": "set"}, False),
            ({"binary": "unspecified", "text": "unspecified"}, False),
            ({}, False),
        ],
    )
    def test_the_five_answer_shapes_git_gives(
        self, answers: dict[str, str], excluded: bool
    ) -> None:
        """`text=auto` is the case that matters most: it is the line GitHub's own guidance
        recommends as a repository's first, and the predicate an implementer infers from "exclude
        unless text is set" would exclude every file in such a repository."""
        assert text.excluded_by_attributes(answers) is excluded

    def test_an_arbitrary_attribute_value_admits(self) -> None:
        """The answer is not a boolean — a value-carrying attribute yields whatever string it was
        given — and anything other than the two exclusion shapes admits."""
        assert not text.excluded_by_attributes({"binary": "unspecified", "text": "lf"})
