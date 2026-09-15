"""Whether a candidate file is text, and what to call it when it is not.

Three tests, applied in increasing order of cost, and each of them exists because the one before it
cannot answer the question cheaply enough:

1. **A name-ending deny-list**, at walk time. A string comparison, and it carries most of the load:
   a binary file that reaches the sniff is read in full on **every** scan for as long as it stays in
   the tree, because a file that was never indexed has no stored hash for change detection to clear
   it against.
2. **The sniff** — no NUL byte in the first 8 KiB, and the whole file decodes as UTF-8. Whole-file
   rather than the sniffed prefix: a file whose tail is invalid UTF-8 would otherwise either raise
   or be silently mangled from the first bad byte onward.
3. **The repository's own declaration**, from `.gitattributes`, which excludes a file the sniff
   would have admitted.

The deny-list is not a correctness mechanism and is not treated as one: the sniff remains the
authority for anything not on it, so a mis-extensioned text file is still indexed.

**The precedence between the sniff and the attributes is one-directional.** An attribute may
exclude a file the sniff admits; no attribute forces a file the sniff rejects back in. The sniff
protects a reader from bytes it cannot decode, and no declaration makes invalid UTF-8 decodable.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from zikaron.core.knowledge.counters import SkipReason

#: How much of a file the NUL test looks at. A prefix rather than the whole file because the test
#: is a cheap reject: anything binary enough to matter carries a NUL early, and the whole-file
#: decode below is what actually settles the question.
SNIFF_PREFIX_BYTES: Final = 8192

#: Text, and worthless to index. The NUL test admits every one of these, so nothing downstream
#: would reject them: generated, minified or machine-authored files whose content answers no
#: question anyone would ask a corpus.
DENIED_TEXT_ENDINGS: Final[tuple[str, ...]] = (
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
    "-lock.json",
    ".po",
    ".mo",
)

#: Binary, which the sniff would reject anyway — but only after reading the file. Denying these by
#: name is what keeps a repository's images and wheels off the read-every-scan path.
DENIED_BINARY_ENDINGS: Final[tuple[str, ...]] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".zip",
    ".gz",
    ".tar",
    ".whl",
    ".so",
    ".dylib",
    ".dll",
    ".o",
    ".a",
    ".class",
    ".jar",
    ".pyc",
    ".wasm",
    ".db",
    ".sqlite",
    ".mp4",
    ".mp3",
    ".wav",
)

#: Both groups, as the walk applies them. Name *endings* rather than suffixes, because three
#: entries are compound (`.min.js`, `.min.css`, `-lock.json`) and a suffix test would see only
#: `.js`, `.css` and `.json` — which would deny every script, stylesheet and JSON document there
#: is.
DENIED_ENDINGS: Final[tuple[str, ...]] = (*DENIED_TEXT_ENDINGS, *DENIED_BINARY_ENDINGS)

#: The `.gitattributes` attributes that decide whether the repository calls a file binary.
BINARY_ATTRIBUTE: Final = "binary"
TEXT_ATTRIBUTE: Final = "text"
ATTRIBUTES: Final[tuple[str, ...]] = (BINARY_ATTRIBUTE, TEXT_ATTRIBUTE)

#: The attribute values that exclude. Everything else admits — including `unspecified`, `set`, and
#: any other string a value-carrying attribute produces.
_ATTRIBUTE_SET: Final = "set"
_ATTRIBUTE_UNSET: Final = "unset"


@dataclass(frozen=True, slots=True)
class DecodedText:
    """A file that is text, with the decoded content the sniff had to produce anyway."""

    text: str


@dataclass(frozen=True, slots=True)
class NotText:
    """A file that is not text, and which of the two reasons it failed on."""

    reason: SkipReason


#: What the sniff answers. The decoded text travels with the verdict because producing it *is* the
#: whole-file test — decoding twice to avoid returning it would pay the same cost again.
type Detection = DecodedText | NotText


def extension_denied(name: str) -> bool:
    """Whether this file name ends the way something not worth indexing ends.

    Matched case-insensitively, because `.PNG` is as much an image as `.png` and this list is a
    heuristic rather than an identity. Path *matching* elsewhere stays byte-exact, which is a
    different question about a different value.
    """
    lowered = name.lower()
    return any(lowered.endswith(ending) for ending in DENIED_ENDINGS)


def sniff(raw: bytes) -> Detection:
    """Whether `raw` is text, and its decoded content when it is.

    Args:
        raw: the file's bytes exactly as read. A BOM is stripped here and nowhere earlier — the
            content hash is taken over these bytes, so two files differing only by a BOM are
            correctly different files.
    """
    if b"\x00" in raw[:SNIFF_PREFIX_BYTES]:
        return NotText(SkipReason.BINARY)
    try:
        return DecodedText(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        return NotText(SkipReason.DECODE_ERROR)


def excluded_by_attributes(answers: Mapping[str, str]) -> bool:
    """Whether the repository's own attributes say this file is not text.

    **Exclude iff `binary` is `set` or `text` is `unset`.** Everything else admits, and the
    exactness matters because the attribute result is not a boolean: it is `set`, `unset`,
    `unspecified`, or an arbitrary string. `text=auto` — the line GitHub's own guidance recommends
    as a repository's first — answers `auto`, so the predicate an implementer infers from "exclude
    unless `text` is set" would exclude **every file in an ordinary repository**, returning an
    empty corpus with a skip count equal to the file count and nothing raising.

    The `binary` half is belt-and-braces: the `binary` macro expands to `-diff -merge -text`, so
    `text` answering `unset` is already sufficient for every file marked that way.

    Args:
        answers: this path's answer per attribute, keyed by attribute name. A missing attribute is
            read as `unspecified`, which admits — the same answer git gives for a path no rule
            mentions.
    """
    return (
        answers.get(BINARY_ATTRIBUTE) == _ATTRIBUTE_SET
        or answers.get(TEXT_ATTRIBUTE) == _ATTRIBUTE_UNSET
    )
