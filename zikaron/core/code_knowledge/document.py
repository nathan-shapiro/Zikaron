"""A per-source-file document as the planner reads it: its link, title, role line and headings.

`design/code-knowledge.md` §4 fixes the format and §3.4 what of it is read. The link is K14's,
through K14's own reader (`zikaron.core.knowledge.links`), so the planner and a search cannot
disagree about what a document declares. Lines are split as that reader splits them, on `\\n`
alone with one trailing `\\r` removed.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from zikaron.core.knowledge.links import (
    SOURCE_BLOB_KEY,
    SOURCE_KEY,
    DeclaredLink,
    MalformedLink,
    SourceLink,
    key_and_value,
    read_link,
)

#: The four `##` headings every document carries, in the order §4 gives them.
SECTION_HEADINGS: Final[tuple[str, ...]] = ("Purpose", "Declarations", "Behavior", "Dependencies")

_DELIMITER: Final = "---"
_HEADING_PREFIX: Final = "## "


class Defect(StrEnum):
    """Why a document that declares a link is `invalid` for the source its location derives."""

    MALFORMED_LINK = "malformed_link"
    WRONG_SOURCE = "wrong_source"
    NO_TITLE = "no_title"
    NO_ROLE_LINE = "no_role_line"
    MISSING_HEADING = "missing_heading"


def front_matter(source: str, blob: str) -> str:
    """The block a document describing `source` at hash `blob` opens with, exactly."""
    return f"{_DELIMITER}\n{SOURCE_KEY}: {source}\n{SOURCE_BLOB_KEY}: {blob}\n{_DELIMITER}\n"


def title(source: str) -> str:
    """The title line of the document describing `source`."""
    return f"# `{source}`"


def lines_of(text: str) -> list[str]:
    """`text`'s lines, split on `\\n` alone, each with one trailing `\\r` removed."""
    return [line.removesuffix("\r") for line in text.split("\n")]


def block_end(lines: list[str]) -> int | None:
    """The index of the line closing an opening `---` block, or `None` where there is none."""
    if not lines or lines[0] != _DELIMITER:
        return None
    for index in range(1, len(lines)):
        if lines[index] == _DELIMITER:
            return index
    return None


def title_index(lines: list[str], start: int) -> int | None:
    """The index of the title line — the first non-blank line from `start` — or `None`."""
    for index in range(start, len(lines)):
        if lines[index].strip():
            return index
    return None


def is_heading(line: str) -> bool:
    """Whether `line` is a `##` heading — exactly two marks and a space."""
    return line.startswith(_HEADING_PREFIX)


def heading_text(line: str) -> str:
    """A `##` heading's text."""
    return line[len(_HEADING_PREFIX) :].rstrip()


@dataclass(frozen=True, slots=True)
class Document:
    """What the planner reads from one document's text."""

    link: DeclaredLink | None
    title: str | None
    role: str
    headings: frozenset[str]

    @classmethod
    def parse(cls, text: str) -> "Document":
        """Read `text`, a document's decoded text with any byte-order mark removed."""
        link = read_link(text)
        lines = lines_of(text)
        end = block_end(lines)
        found = title_index(lines, 0 if end is None else end + 1)
        if found is None:
            return cls(link=link, title=None, role="", headings=frozenset())
        role: list[str] = []
        headings: set[str] = set()
        for line in lines[found + 1 :]:
            if is_heading(line):
                headings.add(heading_text(line))
            elif not headings and line.strip():
                role.append(line.strip())
        return cls(
            link=link,
            title=lines[found].rstrip(),
            role=" ".join(role),
            headings=frozenset(headings),
        )

    def defect(self, source: str) -> Defect | None:
        """Why this document is not a well-formed description of `source`, or `None` if it is.

        Its blob is not compared: a wrong blob makes a document `stale`, which is a different
        class with the same remedy.
        """
        if isinstance(self.link, MalformedLink):
            return Defect.MALFORMED_LINK
        if self.link is None or self.link.path != source:
            return Defect.WRONG_SOURCE
        if self.title != title(source):
            return Defect.NO_TITLE
        if not self.role:
            return Defect.NO_ROLE_LINE
        if not self.headings.issuperset(SECTION_HEADINGS):
            return Defect.MISSING_HEADING
        return None

    @property
    def movable(self) -> bool:
        """Whether this document is a well-formed description of the source it declares, so that
        rewriting its link and title to another path describes that path's bytes exactly."""
        return isinstance(self.link, SourceLink) and self.defect(self.link.path) is None


def relinked(text: str, source: str) -> str:
    """`text` with its `zikaron-source` line and its title naming `source`, and nothing else
    changed — each line's own `\\r`, where it has one, kept.

    `text` must parse to a `movable` document, which is what guarantees both lines exist.
    """
    raw = text.split("\n")
    lines = lines_of(text)
    end = block_end(lines)
    if end is None:
        raise ValueError("relinked needs a document whose front matter closes")
    for index in range(1, end):
        parsed = key_and_value(lines[index])
        if parsed is not None and parsed[0] == SOURCE_KEY:
            raw[index] = _keeping_return(raw[index], f"{SOURCE_KEY}: {source}")
    found = title_index(lines, end + 1)
    if found is None:
        raise ValueError("relinked needs a document with a title")
    raw[found] = _keeping_return(raw[found], title(source))
    return "\n".join(raw)


def _keeping_return(original: str, replacement: str) -> str:
    return f"{replacement}\r" if original.endswith("\r") else replacement
