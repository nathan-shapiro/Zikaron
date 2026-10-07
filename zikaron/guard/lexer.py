"""Strings, comments and continuations: `design/edit-guards.md` §3.1 steps 2 and 3.

One left-to-right pass over a unit's lines, where **the first thing met decides**:

- a quote that pairs on its line is a one-line string;
- a `#` at a line start or after whitespace, outside any string, is the line's comment;
- an unpaired quote met first opens a **multi-line string**, which takes the rest of the line —
  `#` and all — and runs to the first unescaped quote of its kind on a later line.

Then step 3 joins a line that ends in an unescaped `\\`, or — its comment removed — in an
unquoted `|`, `||` or `&&`, to the next: the newline becomes a token break and nothing else.

>>> from zikaron.guard.heredoc import delimit
>>> letter = dict(zip(Kind, "CSQMJ", strict=True))  # code, string, quote, comment, join
>>> def kinds(*lines: str) -> str:
...     return "".join(letter[c.kind] for c in annotate(delimit(lines)))
>>> kinds("a 'b' # c")
'CCQSQCMMM'
>>> kinds('echo "a', '#b" x')
'CCCCCQSSSSQCC'
>>> kinds("a |", "b")
'CCCJC'
"""

from dataclasses import replace

from zikaron.guard.chars import Char, Heredoc, Kind
from zikaron.guard.heredoc import Body, Unit
from zikaron.guard.quoting import closing_quote


def annotate(unit: Unit) -> tuple[Char, ...]:
    """The unit's lines as one stream, newline-separated, each character with its reading.

    The first `<` of each body's opener carries that body; an executed body's script is its own
    stream, comments removed, so row 4 searches what the interpreter will run.
    """
    chars: list[Char] = []
    open_quote = ""
    for index, line in enumerate(unit.lines):
        row, open_quote = _annotate_line(line, open_quote)
        for opening in unit.openings[index]:
            body = opening.body
            heredoc = Heredoc(_script(body), "\n".join(body.lines))
            row[opening.column] = replace(row[opening.column], heredoc=heredoc)
        chars.extend(row)
        if index < len(unit.lines) - 1:
            newline = Char("\n", Kind.STRING, open_quote) if open_quote else Char("\n", Kind.CODE)
            chars.append(newline)
    _join_continuations(chars)
    return tuple(chars)


def _script(body: Body) -> str | None:
    return None if body.unit is None else executed_text(body.unit)


def executed_text(unit: Unit) -> str:
    """A unit's text as row 4 searches what an interpreter runs: its comments removed.

    >>> from zikaron.guard.heredoc import delimit
    >>> executed_text(delimit(["x = 1  # open('f','w')", "open('g','w')"]))
    "x = 1  \\nopen('g','w')"
    """
    return "".join(char.text for char in annotate(unit) if char.kind is not Kind.COMMENT)


def _annotate_line(text: str, open_quote: str) -> tuple[list[Char], str]:
    """One line, entered inside a multi-line string when `open_quote` is set. Returns the line's
    characters and the quote still open at its end."""
    row: list[Char] = []
    index = 0
    if open_quote:
        close = closing_quote(text, 0, open_quote)
        if close is None:
            return [Char(c, Kind.STRING, open_quote) for c in text], open_quote
        row += [Char(c, Kind.STRING, open_quote) for c in text[:close]]
        row.append(Char(text[close], Kind.QUOTE, open_quote))
        index = close + 1
        open_quote = ""
    while index < len(text):
        character = text[index]
        if character == "\\" and text[index + 1 : index + 2] in ("'", '"'):
            # Outside a string, `\"` and `\'` open nothing (§7, "parsed as stated").
            row += [Char(character, Kind.CODE), Char(text[index + 1], Kind.CODE)]
            index += 2
        elif character in "'\"":
            index, open_quote = _string(text, index, row)
        elif character == "#" and (index == 0 or text[index - 1] in " \t"):
            row += [Char(c, Kind.COMMENT) for c in text[index:]]
            index = len(text)
        else:
            row.append(Char(character, Kind.CODE))
            index += 1
    return row, open_quote


def _string(text: str, index: int, row: list[Char]) -> tuple[int, str]:
    """Append the string opened at `index`; return where reading resumes and the quote left open
    when it does not close on this line."""
    quote = text[index]
    row.append(Char(quote, Kind.QUOTE, quote))
    close = closing_quote(text, index + 1, quote)
    if close is None:
        row += [Char(c, Kind.STRING, quote) for c in text[index + 1 :]]
        return len(text), quote
    row += [Char(c, Kind.STRING, quote) for c in text[index + 1 : close]]
    row.append(Char(text[close], Kind.QUOTE, quote))
    return close + 1, ""


def _join_continuations(chars: list[Char]) -> None:
    """Step 3, in place: every code newline that continues its line becomes a join."""
    for index, char in enumerate(chars):
        if not char.is_code("\n"):
            continue
        backslashes = 0
        while index - backslashes - 1 >= 0 and chars[index - backslashes - 1].is_code("\\"):
            backslashes += 1
        if backslashes % 2 == 1:
            chars[index - 1] = replace(chars[index - 1], kind=Kind.JOIN)
            chars[index] = replace(char, kind=Kind.JOIN)
        elif _ends_in_pipe_or_and(chars, index):
            chars[index] = replace(char, kind=Kind.JOIN)


def _ends_in_pipe_or_and(chars: list[Char], newline: int) -> bool:
    """Whether the line ending at `newline`, its comment and trailing blanks skipped, ends in an
    unquoted `|` (so also `||`) or `&&`."""
    last = newline - 1
    while (
        last >= 0
        and chars[last].text != "\n"
        and (chars[last].kind is Kind.COMMENT or chars[last].text in " \t")
    ):
        last -= 1
    if last < 0:
        return False
    if chars[last].is_code("|"):
        return True
    return chars[last].is_code("&") and last >= 1 and chars[last - 1].text == "&"
