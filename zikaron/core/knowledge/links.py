"""What a document's front matter says it describes: the link reader, and the link as it is stored.

`knowledge-index.md` §7.7 is normative, and its grammar is what this implements. A document opts
in by opening with a `---` block carrying `zikaron-source` and `zikaron-source-blob`; nothing else
about a file's structure is read. The grammar is strict on purpose, since widening it later breaks
no document and narrowing it would.

**One reader, over text, for every caller.** The build reads the text it decoded, and the migration
and search's fallback read the stored chunks' concatenation, which is that same text exactly — so
the three cannot disagree about what one file declares.

**A declaration that is not well-formed is reported, not dropped.** A link that looks absent reads
as a document that needs no checking, which is the one wrong answer the field exists to prevent.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

#: How far into a document its front matter may reach: the closing `---`, its terminator included,
#: must fall within this many characters. Part of what a document's writer relies on, so a
#: constant rather than configuration.
LINK_PREFIX_CHARS: Final = 4096

#: The longest source path a declaration may carry — macOS's `PATH_MAX`, the smaller of the two
#: supported platforms', so a longer one could name no file on the stricter of them.
LINK_PATH_MAX_CHARS: Final = 1024

SOURCE_KEY: Final = "zikaron-source"
SOURCE_BLOB_KEY: Final = "zikaron-source-blob"

_DELIMITER: Final = "---"

#: Git's object ids: 40 hexadecimal digits for SHA-1, 64 where the object format is SHA-256.
_BLOB: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class SourceLink:
    """A well-formed declaration: the source's path relative to the Zikaron root, and its hash."""

    path: str
    blob: str


@dataclass(frozen=True, slots=True)
class MalformedLink:
    """A file that declares a link and gets it wrong — one key without the other, a key twice, a
    block that never closes within `LINK_PREFIX_CHARS`, or a value out of its grammar."""


#: What a file that declares a link declares.
type DeclaredLink = SourceLink | MalformedLink


@dataclass(frozen=True, slots=True)
class LinkRecord:
    """What one version of a file declares, beside the `content_hash` of the bytes it was read
    from: the four link columns of a `files` row.

    Trusted only while `read_from` equals the row's own `content_hash`; otherwise the link is read
    again from the stored chunks.
    """

    read_from: str
    declared: DeclaredLink | None

    def columns(self) -> tuple[str, int, str | None, str | None]:
        """`link_read_from`, `link_declared`, `source_path` and `source_blob`, in that order."""
        source = self.declared if isinstance(self.declared, SourceLink) else None
        return (
            self.read_from,
            0 if self.declared is None else 1,
            None if source is None else source.path,
            None if source is None else source.blob,
        )


def declared_from_columns(
    declared: object, source_path: object, source_blob: object
) -> DeclaredLink | None:
    """The declaration a row's last three link columns record, as `LinkRecord.columns` wrote it."""
    if not declared:
        return None
    if isinstance(source_path, str) and isinstance(source_blob, str):
        return SourceLink(path=source_path, blob=source_blob)
    return MalformedLink()


def _lines(text: str) -> Iterator[tuple[str, bool]]:
    """Every line starting within the prefix, with one trailing `\\r` removed, and whether it ends
    there.

    Split on `\\n` alone, as the chunker splits. A line ends within the prefix when its terminator
    does, or when it is the text's last line and the text ends there.
    """
    start = 0
    while start < len(text) and start < LINK_PREFIX_CHARS:
        newline = text.find("\n", start, LINK_PREFIX_CHARS)
        if newline == -1:
            ends = len(text) <= LINK_PREFIX_CHARS
            line = text[start:] if ends else text[start:LINK_PREFIX_CHARS]
            yield line.removesuffix("\r"), ends
            return
        yield text[start:newline].removesuffix("\r"), True
        start = newline + 1


def key_and_value(line: str) -> tuple[str, str] | None:
    """A front-matter line's key and value by §7.7's grammar, or `None` for a line with no `:`."""
    key, colon, value = line.partition(":")
    if not colon:
        return None
    value = value.strip()
    if len(value) > 1 and value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return key.strip(), value


def _well_formed(paths: list[str], blobs: list[str]) -> DeclaredLink:
    if len(paths) != 1 or len(blobs) != 1:
        return MalformedLink()
    (path,), (blob,) = paths, blobs
    if (
        not path
        or path.startswith("/")
        or "\0" in path
        or len(path) > LINK_PATH_MAX_CHARS
        or _BLOB.fullmatch(blob) is None
    ):
        return MalformedLink()
    return SourceLink(path=path, blob=blob)


def read_link(text: str) -> DeclaredLink | None:
    """What `text`'s front matter declares, or `None` where it declares no link.

    Total: every text has exactly one of the three answers.

    Args:
        text: a file's decoded text, any byte-order mark already removed — or its stored chunks'
            concatenation, which is the same characters.
    """
    lines = _lines(text)
    first = next(lines, None)
    if first is None or first != (_DELIMITER, True):
        return None
    paths: list[str] = []
    blobs: list[str] = []
    for line, ends in lines:
        if line == _DELIMITER and ends:
            if not paths and not blobs:
                return None
            return _well_formed(paths, blobs)
        parsed = key_and_value(line)
        if parsed is None:
            continue
        key, value = parsed
        if key == SOURCE_KEY:
            paths.append(value)
        elif key == SOURCE_BLOB_KEY:
            blobs.append(value)
    # The block never closed within the prefix: whatever it carried is a declaration gone wrong.
    return MalformedLink() if paths or blobs else None
