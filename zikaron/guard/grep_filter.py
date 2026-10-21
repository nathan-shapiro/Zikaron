"""The self-match rule's one exemption: a `grep -v` that drops the shell's line (`design/guards.md`
§9.2).

On `linux`, `pgrep -a` prints each process's command line, the calling shell's on one line, so a
later `grep -v` in the same pipeline removes that line whenever its own pattern searches the
command's text. Only what is read counts: a pattern that is not literal, that `re` cannot compile,
or that comes from a file (`-f`) exempts nothing.

| Filter after `pgrep -af month_monitor.py` | Drops the shell's line |
|---|---|
| `grep -v grep` · `grep -vE 'pgrep\\|grep'` · `grep -v -e pgrep -e grep` · `grep -vi GREP` | yes |
| `grep -v $$` · `grep -v -f /tmp/pats` · `grep -c pytest` · `grep -v -m 1 '[z]zz'` | no |

>>> from zikaron.guard.heredoc import delimit
>>> from zikaron.guard.grammar import parse
>>> from zikaron.guard.lexer import annotate
>>> def drops(command: str) -> bool:
...     (pipeline,) = parse(annotate(delimit([command])))
...     return drops_shell_line(pipeline[1:], command)
>>> drops("pgrep -af m | grep -v grep"), drops("pgrep -af m | grep -v $$")
(True, False)
"""

import enum
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from zikaron.guard.grammar import SimpleCommand, Token
from zikaron.guard.patterns import compiled, literal_text
from zikaron.guard.position import command_name, command_words
from zikaron.guard.redirects import arguments


class Dialect(enum.Enum):
    """How `grep` reads a pattern."""

    BASIC = "basic"
    EXTENDED = "extended"
    FIXED = "fixed"


#: The options that choose the dialect; `-P` is read as `-E`.
DIALECTS: Final = {"E": Dialect.EXTENDED, "P": Dialect.EXTENDED, "F": Dialect.FIXED}
#: Short options that take an argument which is neither a pattern nor a file of them.
SKIPPED: Final = frozenset("ABCmdD")
#: Long options that take such an argument, unless written with `=value`.
LONG_SKIPPED: Final = frozenset(
    {
        "--max-count",
        "--context",
        "--after-context",
        "--before-context",
        "--include",
        "--exclude",
        "--exclude-dir",
        "--label",
        "--devices",
        "--directories",
        "--binary-files",
    }
)
_PATTERN, _PATTERN_FILE, _INVERT, _IGNORE_CASE = "e", "f", "v", "i"
_RECURSIVE: Final = frozenset("rR")
#: What ends the options: every token after it is an operand.
_END_OF_OPTIONS: Final = "--"
#: The long options read, each with the short option it spells.
_LONG: Final = {
    "--regexp": _PATTERN,
    "--file": _PATTERN_FILE,
    "--invert-match": _INVERT,
    "--ignore-case": _IGNORE_CASE,
    "--recursive": "r",
    "--dereference-recursive": "R",
}
#: What a basic expression escapes to make special, and what an extended one has special unescaped.
_BASIC_SPECIALS: Final = frozenset("|(){}+?")


@dataclass(slots=True)
class Grep:
    """One `grep`'s reading: each pattern's text, `None` for one that is not literal, and every
    operand as written."""

    patterns: list[str | None] = field(default_factory=list)
    letters: set[str] = field(default_factory=set)
    dialect: Dialect = Dialect.BASIC
    operands: list[str] = field(default_factory=list)

    @property
    def drops_matches(self) -> bool:
        """Inverted, with every pattern read from the command."""
        return _INVERT in self.letters and _PATTERN_FILE not in self.letters

    @property
    def paths(self) -> list[str]:
        """The operands naming what to search: all of them when an `-e` or `-f` named the
        patterns, else all but the first, which is the pattern."""
        if self.letters & {_PATTERN, _PATTERN_FILE}:
            return self.operands
        return self.operands[1:]

    @property
    def recursive(self) -> bool:
        """Whether it descends into directories, which with no path means the working one."""
        return bool(self.letters & _RECURSIVE)

    @property
    def names_a_pattern(self) -> bool:
        """Whether anything was given to search for: an operand, or an `-e` or `-f`. Without one
        the command prints its usage or its version and searches nothing."""
        return bool(self.operands) or bool(self.letters & {_PATTERN, _PATTERN_FILE})


def drops_shell_line(rest: Sequence[SimpleCommand], command: str) -> bool:
    """Whether a `grep` among `rest`, the simple commands after a `pgrep -a` in its pipeline,
    drops the shell's line: an inverted one, one of whose own patterns searches `command`."""
    for simple in rest:
        for word in command_words(simple):
            if command_name(simple.tokens[word]) == "grep":
                grep = read_grep(arguments(simple.tokens, word))
                if grep.drops_matches and _any_searches(grep, command):
                    return True
    return False


def _any_searches(grep: Grep, command: str) -> bool:
    for text in grep.patterns:
        if text is None:
            continue
        pattern = compiled(_as_python(text, grep.dialect), ignore_case=_IGNORE_CASE in grep.letters)
        if pattern is not None and pattern.search(command) is not None:
            return True
    return False


def read_grep(
    given: Sequence[Token],
    *,
    skipped: frozenset[str] = SKIPPED,
    long_skipped: frozenset[str] = LONG_SKIPPED,
) -> Grep:
    """A `grep`'s options and patterns: its first operand, unless an `-e` or `-f` anywhere names
    them, which makes every operand a file. `--` ends the options.

    `skipped` and `long_skipped` are the options that take an argument, `grep`'s by default; a
    program that reads its patterns as `grep` does but takes other options passes its own.
    """
    grep = Grep()
    pending: str | None = None
    literals: list[str | None] = []
    options_ended = False
    for token in given:
        if not token.is_word:
            break
        text = token.unquoted
        if pending is not None:
            if pending == _PATTERN:
                grep.patterns.append(literal_text(token))
            pending = None
        elif not options_ended and text == _END_OF_OPTIONS:
            options_ended = True
        elif not options_ended and text.startswith("--"):
            pending = _read_long(text, token, grep, long_skipped)
        elif not options_ended and text.startswith("-") and len(text) > 1:
            pending = _read_cluster(text[1:], token, grep, skipped)
        else:
            literals.append(literal_text(token))
            grep.operands.append(text)
    if literals and not grep.letters & {_PATTERN, _PATTERN_FILE}:
        grep.patterns.append(literals[0])
    return grep


def _read_long(text: str, token: Token, grep: Grep, long_skipped: frozenset[str]) -> str | None:
    """Read one long option; what the next token is for, if anything."""
    name, equals, _ = text.partition("=")
    letter = _LONG.get(name)
    if letter is not None:
        grep.letters.add(letter)
    if letter == _PATTERN and equals:
        literal = literal_text(token)
        grep.patterns.append(None if literal is None else literal.partition("=")[2])
        return None
    if equals:
        return None
    if letter in (_PATTERN, _PATTERN_FILE) or name in long_skipped:
        return letter or name
    return None


def _read_cluster(letters: str, token: Token, grep: Grep, skipped: frozenset[str]) -> str | None:
    """Read one `-xyz` cluster; what the next token is for, if anything."""
    for index, letter in enumerate(letters):
        attached = letters[index + 1 :]
        if letter == _PATTERN:
            grep.letters.add(letter)
            if not attached:
                return letter
            literal = literal_text(token)
            grep.patterns.append(None if literal is None else attached)
            return None
        if letter == _PATTERN_FILE or letter in skipped:
            grep.letters.add(letter)
            return None if attached else letter
        grep.letters.add(letter)
        grep.dialect = DIALECTS.get(letter, grep.dialect)
    return None


def _as_python(pattern: str, dialect: Dialect) -> str:
    """A `grep` pattern as `re` reads the same expression."""
    if dialect is Dialect.FIXED:
        return re.escape(pattern)
    if dialect is Dialect.EXTENDED:
        return pattern
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            following = pattern[index + 1 : index + 2]
            out.append(following if following in _BASIC_SPECIALS else char + following)
            index += 2
            continue
        out.append("\\" + char if char in _BASIC_SPECIALS else char)
        index += 1
    return "".join(out)
