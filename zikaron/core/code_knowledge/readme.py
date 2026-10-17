"""The module README's digest, and whether the README on disk is the one the module needs.

`design/code-knowledge.md` §3.6 is normative. The digest covers every module source's path and
hash, so the README is listed again whenever either moves; it declares no link, since it describes
many sources and K14 links one. It lists no files: each document's role line is its own, and a
search finds the document.
"""

import hashlib
import os
from collections.abc import Iterable, Mapping
from typing import Final

from zikaron.core.code_knowledge.document import (
    block_end,
    heading_text,
    is_heading,
    lines_of,
    title_index,
)
from zikaron.core.code_knowledge.layout import path_order
from zikaron.core.knowledge.links import key_and_value

#: One of the `zikaron-` keys `knowledge-index.md` §7.7 reserves; the indexer ignores it.
MODULE_DIGEST_KEY: Final = "zikaron-module-digest"

#: The heading a README listing its files carries, which the README this build writes does not.
FILES_HEADING: Final = "Files"
_TITLE_PREFIX: Final = "# "


def module_digest(hashes: Mapping[str, str]) -> str:
    """The SHA-256 of every source's path and hash, in path order.

    Each source contributes its path's bytes, a NUL, its hash and a newline: a path cannot contain
    the NUL and a hash cannot contain the newline, so no two sets of sources share an input.
    """
    digest = hashlib.sha256()
    for path in sorted(hashes, key=path_order):
        digest.update(os.fsencode(path) + b"\0" + hashes[path].encode("ascii") + b"\n")
    return digest.hexdigest()


def front_matter(digest: str) -> str:
    """The block the README opens with, exactly."""
    return f"---\n{MODULE_DIGEST_KEY}: {digest}\n---\n"


def is_current(text: str, digest: str) -> bool:
    """Whether a README's text carries `digest`, once, and a title, and lists no files under a
    `## Files` heading."""
    lines = lines_of(text)
    end = block_end(lines)
    if end is None:
        return False
    declared = [
        parsed[1]
        for parsed in map(key_and_value, lines[1:end])
        if parsed is not None and parsed[0] == MODULE_DIGEST_KEY
    ]
    found = title_index(lines, end + 1)
    titled = found is not None and lines[found].startswith(_TITLE_PREFIX)
    body = lines[end + 1 :]
    lists_files = any(is_heading(line) and heading_text(line) == FILES_HEADING for line in body)
    return declared == [digest] and titled and not lists_files


def roles(item_files: Iterable[tuple[str, str]]) -> str:
    """The role list a README is written from: one line per documented file, `source` then role."""
    return "".join(f"- `{source}` — {role}\n" for source, role in item_files)
