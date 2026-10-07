"""How one line pairs its quotes, and where its comment starts.

This is the reading `design/edit-guards.md` §3.1 step 1 gives a raw line: **a quote counts only
if it pairs on its own line**. Step 1 uses it to decide which `<<` openers are inside a string,
and row 4 (§3.2) uses it again to drop Python comments from a script.

>>> line = '''echo "a # b" 'it' # note'''
>>> spans = paired_quotes(line)
>>> [line[a : b + 1] for a, b in spans]
['"a # b"', "'it'"]
>>> line[comment_start(line, spans) :]
'# note'
"""

from collections.abc import Sequence

#: An inclusive `(open, close)` index pair of one quoted string on a line.
Span = tuple[int, int]


def closing_quote(text: str, start: int, quote: str) -> int | None:
    """The index of the first `quote` at or after `start` that closes a string, or `None`.

    Inside `"…"` a backslash escapes the next character; `'…'` has no escape.

    >>> closing_quote('a\\\\"b"', 0, '"')
    4
    >>> closing_quote("a\\\\'b", 0, "'")
    2
    """
    index = start
    while index < len(text):
        if quote == '"' and text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index
        index += 1
    return None


def paired_quotes(line: str) -> tuple[Span, ...]:
    """The strings that open and close on `line`, left to right.

    A quote with no partner on the line opens nothing here. Outside a string, `\\"` and `\\'`
    open nothing either (§7, "parsed as stated").

    >>> paired_quotes('''echo \\\\"x\\\\" 'y' "z''')
    ((11, 13),)
    """
    spans: list[Span] = []
    index = 0
    while index < len(line):
        if line[index] == "\\" and line[index + 1 : index + 2] in ("'", '"'):
            index += 2
            continue
        if line[index] in "'\"":
            close = closing_quote(line, index + 1, line[index])
            if close is not None:
                spans.append((index, close))
                index = close + 1
                continue
        index += 1
    return tuple(spans)


def is_within(spans: Sequence[Span], index: int) -> bool:
    """Whether `index` falls inside one of `spans`, delimiters included."""
    return any(start <= index <= end for start, end in spans)


def comment_start(line: str, spans: Sequence[Span]) -> int | None:
    """Where the line's comment begins: a `#` at the line start or after a space or tab, outside
    every span. `None` when the line has no comment.

    >>> comment_start("a#b # c", ())
    4
    """
    for index, character in enumerate(line):
        after_blank = index == 0 or line[index - 1] in " \t"
        if character == "#" and after_blank and not is_within(spans, index):
            return index
    return None
