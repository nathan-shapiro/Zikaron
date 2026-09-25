"""`research/injected-prose-log.md` decodes `surface_call.detail.preamble_digest`.

The log is only worth keeping if the live constants are findable in it and superseded ones stay put,
so these assert that — plus that exactly one entry claims to be live — and nothing else about the
prose around the entries.
"""

import re
from hashlib import sha256
from pathlib import Path
from typing import Final

from zikaron.core.retrieval.block import FRAMING, PREAMBLE_DIGEST

LOG: Final = Path(__file__).resolve().parent.parent / "research" / "injected-prose-log.md"
_ENTRY: Final = re.compile(r"^## `([0-9a-f]{12})`", re.M)
_FENCE: Final = re.compile(r"^```\n(.*?)\n```$", re.M | re.S)


def _entries() -> dict[str, str]:
    """Each entry's digest mapped to the framing recorded under it."""
    text = LOG.read_text()
    headings = list(_ENTRY.finditer(text))
    bounds = [m.start() for m in headings] + [len(text)]
    out = {}
    for index, heading in enumerate(headings):
        fence = _FENCE.search(text, heading.end(), bounds[index + 1])
        assert fence is not None, f"entry {heading.group(1)} records no text"
        out[heading.group(1)] = fence.group(1)
    return out


def test_the_live_framing_has_an_entry_reproducing_it() -> None:
    entries = _entries()
    assert PREAMBLE_DIGEST in entries, (
        f"the framing this build renders digests to {PREAMBLE_DIGEST}, which {LOG.name} does not "
        "record: add an entry before changing the text, or a stored row cannot be decoded"
    )
    assert entries[PREAMBLE_DIGEST] == FRAMING


def test_every_entry_is_named_by_the_digest_of_the_text_it_records() -> None:
    for digest, framing in _entries().items():
        assert sha256(framing.encode()).hexdigest()[:12] == digest


def test_the_log_records_more_than_one_reader_would_need_to_find_in_git() -> None:
    assert _entries(), f"{LOG.name} records no framing at all"


def test_exactly_the_live_framing_is_headed_live() -> None:
    """Adding an entry without closing the previous one leaves two texts claiming to be live."""
    live = re.findall(r"^## `([0-9a-f]{12})` — live\b", LOG.read_text(), re.M)
    assert live == [PREAMBLE_DIGEST], (
        "exactly one entry may be headed `live`, and it must be the framing this build renders; "
        "close the previous entry with its end date when adding a new one"
    )


#: Framings that rows on a real store carry, or fall back to. Removing one orphans those rows, so a
#: digest joins this set when its text is retired and never leaves it.
_DECODES_STORED_ROWS: Final = frozenset({"77fffb2fb3bf", "879a14704ab1", "1ad616ed80fa"})


def test_no_entry_a_stored_row_needs_has_been_removed() -> None:
    """The log is append-only in the one direction that matters: editing an entry in place rather
    than adding one keeps the digests consistent and every other assertion green, while the text a
    stored row needs disappears."""
    assert _entries().keys() >= _DECODES_STORED_ROWS
