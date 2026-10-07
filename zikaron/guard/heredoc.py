"""Heredoc bodies: where each begins and ends, and whether anything executes it.

`design/edit-guards.md` §3.1 step 1 and §3.2 "Heredoc bodies" are normative. Bodies are delimited
**before** anything else is read, so a quote inside a body can never close a string opened
outside it. Each body is then one of two things:

- **scanned**, when the opener's pipeline has a shell or interpreter as a command word — its
  lines are a command of their own, delimited again here and judged as any other line;
- **data** otherwise — never looked inside, so a PR body or a staged script cannot be denied for
  what it says, until row 6 runs that script and judges the body as its text.

So `bash <<'EOF'`, `cat <<'EOF' | bash` and `python3 -c "$(cat <<'EOF'` open scanned bodies,
while `cat > /tmp/fix.sh <<'EOF'` and `gh pr create --body "$(cat <<'EOF'` open data.

A body begins after the opener's line *and the lines that line continues onto* — by a trailing
`\\`, `|`, `&&` or `||` — and ends at the line equal to its delimiter (leading tabs stripped
under `<<-`). Two openers on one line take their bodies in turn.

>>> unit = delimit(["bash <<'EOF'", "sed -i x f", "EOF", "cat > g <<X", "y", "X"])
>>> unit.lines
("bash <<'EOF'", 'cat > g <<X')
>>> [(body.lines, body.is_scanned) for body in unit.bodies]
[(('sed -i x f',), True), (('y',), False)]
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple

from zikaron.guard.chars import Char, Heredoc, Kind
from zikaron.guard.grammar import parse
from zikaron.guard.position import command_name, command_words
from zikaron.guard.programs import executes_text
from zikaron.guard.quoting import comment_start, is_within, paired_quotes

#: `<<` or `<<-`, never `<<<` — a here-string opens no body.
_OPENER: Final = re.compile(r"(?<!<)<<(-?)(?!<)")
#: An unquoted delimiter word, without the leading backslash that quotes it.
_BARE_DELIMITER: Final = re.compile(r"\\?([^\s;|&()<>'\"]+)")


@dataclass(frozen=True, slots=True)
class Body:
    """A heredoc body's lines. `unit` holds them delimited again when the body is scanned."""

    lines: tuple[str, ...]
    unit: "Unit | None"

    @property
    def is_scanned(self) -> bool:
        return self.unit is not None


@dataclass(frozen=True, slots=True)
class Opening:
    """A `<<` that opens a body, at `column` of its line."""

    column: int
    body: Body


@dataclass(frozen=True, slots=True)
class Unit:
    """The lines of a command outside its heredoc bodies, each with the bodies it opens."""

    lines: tuple[str, ...]
    openings: tuple[tuple[Opening, ...], ...]

    @property
    def bodies(self) -> tuple[Body, ...]:
        return tuple(opening.body for line in self.openings for opening in line)


class _Opener(NamedTuple):
    column: int
    strips_tabs: bool
    delimiter: str


def delimit(lines: Sequence[str]) -> Unit:
    """Split `lines` into the command's own lines and its bodies, recursively for scanned ones."""
    own: list[str] = []
    openings: list[tuple[Opening, ...]] = []
    index = 0
    while index < len(lines):
        group = _logical_line(lines, index)
        position = group[-1] + 1
        found: dict[int, list[Opening]] = {}
        for offset, line_index in enumerate(group):
            for opener in _openers(lines[line_index])[0]:
                end = _delimiter_line(lines, position, opener)
                body_lines = tuple(lines[position:end])
                executed = _is_executed(lines, group, offset, opener.column)
                body = Body(body_lines, delimit(body_lines) if executed else None)
                found.setdefault(offset, []).append(Opening(opener.column, body))
                position = end + 1
        for offset, line_index in enumerate(group):
            own.append(lines[line_index])
            openings.append(tuple(found.get(offset, ())))
        index = position
    return Unit(tuple(own), tuple(openings))


def _openers(line: str) -> tuple[list[_Opener], str]:
    """The openers on a raw line that are outside its paired quotes, and the line with each
    opener's own quoted delimiter neutralised — so `<<'EOF'` pairs no quote of its own while
    `echo "x <<'EOF' y"` still reads as one string.

    >>> [o.delimiter for o in _openers('''bash -c "$(cat <<"EOF"''')[0]]
    ['EOF']
    >>> _openers('''echo "x <<'EOF' y"''')[0]
    []
    """
    found: list[_Opener] = []
    neutral = list(line)
    for match in _OPENER.finditer(line):
        start = match.end()
        while start < len(line) and line[start] in " \t":
            start += 1
        if start >= len(line):
            continue
        if line[start] in "'\"":
            close = line.find(line[start], start + 1)
            if close < 0:
                continue
            delimiter = line[start + 1 : close]
            neutral[start] = neutral[close] = "_"
        else:
            bare = _BARE_DELIMITER.match(line, start)
            if bare is None:
                continue
            delimiter = bare.group(1)
        found.append(_Opener(match.start(), match.group(1) == "-", delimiter))
    neutralised = "".join(neutral)
    spans = paired_quotes(neutralised)
    return [opener for opener in found if not is_within(spans, opener.column)], neutralised


def _code_before_comment(line: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    """A raw line up to its comment, with the neutralised line's paired quotes."""
    neutralised = _openers(line)[1]
    spans = paired_quotes(neutralised)
    cut = comment_start(neutralised, spans)
    return (neutralised if cut is None else neutralised[:cut]), spans


def _continues(line: str) -> bool:
    """Whether the shell reads the next line as part of this one: the line, its comment removed,
    ending in an odd run of backslashes, or in `|`, `||` or `&&` — a `\\` that ends a comment
    continues nothing.

    >>> _continues("cat <<'EOF' |"), _continues("echo a \\\\"), _continues("cat <<'EOF' # x \\\\")
    (True, True, False)
    """
    code = _code_before_comment(line)[0]
    trailing = len(code) - len(code.rstrip("\\"))
    if trailing % 2 == 1:
        return True
    return code.rstrip().endswith(("|", "&&"))


def _logical_line(lines: Sequence[str], index: int) -> list[int]:
    group = [index]
    while _continues(lines[group[-1]]) and group[-1] + 1 < len(lines):
        group.append(group[-1] + 1)
    return group


def _delimiter_line(lines: Sequence[str], start: int, opener: _Opener) -> int:
    """The index of the body's delimiter line, or `len(lines)` when nothing closes it."""
    index = start
    while index < len(lines):
        line = lines[index].lstrip("\t") if opener.strips_tabs else lines[index]
        if line == opener.delimiter:
            return index
        index += 1
    return index


def _is_executed(lines: Sequence[str], group: Sequence[int], offset: int, column: int) -> bool:
    """Whether the opener at `column` of the group's `offset`-th line is in a pipeline that has a
    shell or interpreter as a command word. The lines are read as step 1 reads them: quotes pair
    on their own line, comments are dropped, and the group's lines are joined."""
    probe = Heredoc(script=None)
    chars: list[Char] = []
    for position, line_index in enumerate(group):
        code, spans = _code_before_comment(lines[line_index])
        for index, text in enumerate(code):
            mark = probe if (position, index) == (offset, column) else None
            chars.append(Char(text, _raw_kind(spans, index), heredoc=mark))
        if position < len(group) - 1:
            if chars and chars[-1].is_code("\\"):
                chars[-1] = Char("\\", Kind.JOIN)
            chars.append(Char("\n", Kind.JOIN))
    for pipeline in parse(chars):
        tokens = [token for command in pipeline for token in command.tokens]
        if not any(char.heredoc is probe for token in tokens for char in token.chars):
            continue
        for command in pipeline:
            if any(executes_text(command_name(command.tokens[k])) for k in command_words(command)):
                return True
    return False


def _raw_kind(spans: Sequence[tuple[int, int]], index: int) -> Kind:
    if any(index in span for span in spans):
        return Kind.QUOTE
    return Kind.STRING if is_within(spans, index) else Kind.CODE
