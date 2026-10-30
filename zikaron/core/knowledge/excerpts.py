"""What a result shows of the chunk it ranks: a snippet when whole, an opening when named.

A snippet is verbatim file content for the line range it reports (K13). An opening is a label: the
file's first chunk past any link front matter, its whitespace collapsed and its length bounded, so a
reader can judge a result it was not shown whole. No markdown is parsed for it (`knowledge-index.md`
§1.1); the only structure read is the front matter the index already owns (K14).
"""

from itertools import accumulate
from typing import Final

from zikaron.core.knowledge import chunking, links

#: The longest opening, in Unicode code points, its closing ellipsis included. Read where the
#: opening is cut rather than bound as a default, so a replay can measure another value.
OPENING_MAX_CHARS: int = 400

_ELLIPSIS: Final = "…"


def cut_to_snippet(text: str, *, start_line: int, max_chars: int) -> tuple[str, int, bool]:
    """A chunk's text as a snippet, with the last line it covers and whether it was cut.

    The governing property is that the snippet is byte-identical to lines `start_line` through the
    returned line of the file, so a caller can read that range and get the same bytes, quote a
    command out of it, or widen it for context. A cut therefore removes **whole lines from the
    end** — the result is fewer lines of the file, never a doctored version of more.

    **The one exception is when not even the chunk's first line fits.** There is then no whole-line
    prefix to return, so the cut lands *inside* that line: the snippet is a prefix of it, `end_line`
    names it, and any further lines of the chunk are outside the snippet entirely — `truncated` is
    all that says so. The alternative is an unbounded string in a bounded response, and nothing
    useful can be done about a forty-kilobyte minified line the text detection admitted.

    Note that this does **not** require the chunk to be one line: a chunk of six lines whose first
    is longer than the cap takes the same path.

    Args:
        text: the chunk's stored text, verbatim. A chunk always holds at least one line.
        start_line: the file line `text` begins at.
        max_chars: `knowledge_snippet_max_chars`, counted in Unicode code points.

    Returns:
        The snippet, the file line it ends at, and whether anything was left out.
    """
    lines = chunking.split_lines(text)
    if len(text) <= max_chars:
        return text, start_line + len(lines) - 1, False
    # How many whole lines fit, counted from the running total rather than by accumulating and
    # breaking: the totals only increase, so counting the ones within the cap *is* the greedy
    # answer — and it has no loop exit that the arithmetic above has already made unreachable.
    fitting = sum(1 for total in accumulate(len(line) for line in lines) if total <= max_chars)
    if fitting == 0:
        return text[:max_chars], start_line, True
    return "".join(lines[:fitting]), start_line + fitting - 1, True


def opening_of(first_chunk: str) -> str:
    """A file's opening, from the text of its first chunk alone.

    The text starts after a link front-matter block where one closes within the chunk's link
    prefix, and at the chunk's first character otherwise. Every run of whitespace becomes one space.
    Past `OPENING_MAX_CHARS` the text is cut at the last space that leaves room for the ellipsis, or
    at the limit where there is none, and the ellipsis closes it.

    Returns:
        The opening, `""` when nothing is left once the front matter and whitespace are gone.
    """
    collapsed = " ".join(first_chunk[links.front_matter_end(first_chunk) :].split())
    if len(collapsed) <= OPENING_MAX_CHARS:
        return collapsed
    room = OPENING_MAX_CHARS - len(_ELLIPSIS)
    space = collapsed.rfind(" ", 0, room + 1)
    kept = collapsed[:space] if space > 0 else collapsed[:room]
    return kept + _ELLIPSIS
