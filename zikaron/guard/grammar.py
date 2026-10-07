"""Simple commands and pipelines: the part of shell grammar `design/edit-guards.md` §3.1 parses.

A **simple command** runs from a command position to the next unquoted `|`, `||`, `&&`, `;`, `&`,
`)` or newline; its tokens split on whitespace, and a quoted string is one token. A **pipeline**
is the simple commands joined by `|`. Nothing more of shell grammar is parsed (§7).

Three constructs are kept whole or marked rather than parsed further:

- `$(…)` closing on its own line is **one token** of the enclosing command, and its contents are
  parsed as pipelines of their own — so `echo $(date) > f` keeps its sink. One that does not
  close on its line leaves a boundary token: the words after it are in command position *and*
  stay in the enclosing simple command.
- `(` and a standalone `{` leave a boundary token too; they open a command position.
- `>(…)`/`<(…)` is one process-substitution token, or, unclosed, opens one.

>>> from zikaron.guard.chars import Char, Kind
>>> stream = [Char(c, Kind.CODE) for c in "cat f|sed -n 1p; echo $(date) > g"]
>>> [[[t.raw for t in command.tokens] for command in pipe] for pipe in parse(stream)]
[[['cat', 'f'], ['sed', '-n', '1p']], [['date']], [['echo', '$(date)', '>', 'g']]]
"""

import enum
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from zikaron.guard.chars import Char, Kind


class Boundary(enum.Enum):
    """A construct that opens a command position inside a simple command."""

    SUBSHELL = "("
    GROUP = "{"
    #: A `$(` whose `)` is not on its line.
    SUBSTITUTION = "$("


class ProcessSubstitution(enum.Enum):
    """A token beginning `>(` or `<(`."""

    #: Its `)` closes inside the token.
    WHOLE = "whole"
    #: Its `)` lies outside it, or nowhere.
    OPEN = "open"


@dataclass(frozen=True, slots=True)
class Token:
    """One word of a simple command, or a boundary standing between two of its words."""

    chars: tuple[Char, ...] = ()
    boundary: Boundary | None = None
    process_substitution: ProcessSubstitution | None = None

    @property
    def raw(self) -> str:
        """The word as written, quotes included."""
        if self.boundary is not None:
            return self.boundary.value
        return "".join(char.text for char in self.chars)

    @property
    def unquoted(self) -> str:
        """The word with its quote delimiters removed."""
        if self.boundary is not None:
            return self.boundary.value
        return "".join(char.text for char in self.chars if char.kind is not Kind.QUOTE)

    @property
    def starts_unquoted(self) -> bool:
        """Whether the word's first character is code — the only way it can be an operator."""
        return bool(self.chars) and self.chars[0].kind is Kind.CODE

    @property
    def is_word(self) -> bool:
        """Neither a boundary nor a process substitution."""
        return self.boundary is None and self.process_substitution is None

    @property
    def has_here_text(self) -> bool:
        """Whether the word opens a heredoc body or begins `<<` — a heredoc or a here-string."""
        if any(char.heredoc is not None for char in self.chars):
            return True
        return self.starts_unquoted and self.raw.startswith("<<")

    @property
    def heredoc_scripts(self) -> tuple[str, ...]:
        """The scripts of the executed heredoc bodies this word opens."""
        return tuple(
            char.heredoc.script
            for char in self.chars
            if char.heredoc is not None and char.heredoc.script is not None
        )

    @property
    def heredoc_texts(self) -> tuple[str, ...]:
        """The bodies this word opens, as written, data or scanned."""
        return tuple(char.heredoc.text for char in self.chars if char.heredoc is not None)


@dataclass(frozen=True, slots=True)
class SimpleCommand:
    """A simple command's tokens, the indices at which a command position begins, and whether it
    runs inside a same-line `$(…)` — a subshell, whose variables and directory do not outlive it."""

    tokens: tuple[Token, ...]
    positions: frozenset[int]
    in_substitution: bool = False


#: The simple commands joined by `|`, bounded by `;`, `&&`, `||`, `&`, `)` or a line end.
Pipeline = tuple[SimpleCommand, ...]


def parse(chars: Sequence[Char], *, in_substitution: bool = False) -> list[Pipeline]:
    """Every pipeline in an annotated stream, in the order its last simple command ends — so a
    same-line `$(…)`'s own pipelines come before the one that encloses them."""
    parser = _Parser(chars, in_substitution=in_substitution)
    parser.run()
    return parser.pipelines


def same_line_close(
    chars: Sequence[Char], start: int, *, stop_at_blank: bool = False
) -> int | None:
    """The index of the code `)` closing a `(` just before `start`, if it is on the same line.

    With `stop_at_blank`, unquoted whitespace before it also means "no close" — how a process
    substitution containing whitespace is read (§3.1).
    """
    depth = 1
    for index in range(start, len(chars)):
        char = chars[index]
        if char.text == "\n":
            return None
        if char.kind is not Kind.CODE:
            continue
        if stop_at_blank and char.text in " \t":
            return None
        if char.text == "(":
            depth += 1
        elif char.text == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


class _Parser:
    """One left-to-right pass over a stream; each code character's handler returns where the
    pass continues."""

    def __init__(self, chars: Sequence[Char], *, in_substitution: bool) -> None:
        self.chars = chars
        self.in_substitution = in_substitution
        self.pipelines: list[Pipeline] = []
        self._pipeline: list[SimpleCommand] = []
        self._tokens: list[Token] = []
        self._positions: set[int] = {0}
        self._word: list[Char] = []
        self._substitution: ProcessSubstitution | None = None
        self._handlers: dict[str, Callable[[int], int]] = {
            "\n": self._newline,
            " ": self._blank,
            "\t": self._blank,
            ";": self._semicolon,
            ")": self._close_paren,
            "(": self._open_paren,
            "{": self._brace,
            "$": self._dollar,
            "<": self._angle,
            ">": self._angle,
            "|": self._bar,
            "&": self._ampersand,
        }

    def run(self) -> None:
        index = 0
        while index < len(self.chars):
            char = self.chars[index]
            if char.kind in (Kind.STRING, Kind.QUOTE):
                self._word.append(char)
                index += 1
            elif char.kind is Kind.COMMENT:
                index += 1
            elif char.kind is Kind.JOIN:
                self._flush()
                index += 1
            else:
                index = self._handlers.get(char.text, self._literal)(index)
        self._end(continues_pipeline=False)

    # -- state

    def _code_at(self, index: int, text: str) -> bool:
        return 0 <= index < len(self.chars) and self.chars[index].is_code(text)

    def _flush(self) -> None:
        if self._word:
            self._tokens.append(Token(tuple(self._word), process_substitution=self._substitution))
        self._word = []
        self._substitution = None

    def _end(self, *, continues_pipeline: bool) -> None:
        self._flush()
        self._pipeline.append(
            SimpleCommand(tuple(self._tokens), frozenset(self._positions), self.in_substitution)
        )
        self._tokens = []
        self._positions = {0}
        if not continues_pipeline:
            self.pipelines.append(tuple(self._pipeline))
            self._pipeline = []

    def _open_boundary(self, boundary: Boundary) -> None:
        self._flush()
        self._tokens.append(Token(boundary=boundary))
        self._positions.add(len(self._tokens))

    # -- handlers

    def _literal(self, index: int) -> int:
        self._word.append(self.chars[index])
        return index + 1

    def _blank(self, index: int) -> int:
        self._flush()
        return index + 1

    def _newline(self, index: int) -> int:
        self._end(continues_pipeline=False)
        return index + 1

    _semicolon = _newline
    _close_paren = _newline

    def _open_paren(self, index: int) -> int:
        self._open_boundary(Boundary.SUBSHELL)
        return index + 1

    def _brace(self, index: int) -> int:
        """`{` opens a command position only as a word of its own: `-I{}`, `${VAR}` and `{}` do
        not."""
        following = self.chars[index + 1].text if index + 1 < len(self.chars) else " "
        if self._word or following not in " \t\n":
            return self._literal(index)
        self._open_boundary(Boundary.GROUP)
        return index + 1

    def _dollar(self, index: int) -> int:
        if not self._code_at(index + 1, "("):
            return self._literal(index)
        close = same_line_close(self.chars, index + 2)
        if close is None:
            self._open_boundary(Boundary.SUBSTITUTION)
            return index + 2
        self.pipelines.extend(parse(self.chars[index + 2 : close], in_substitution=True))
        self._word.extend(self.chars[index : close + 1])
        return close + 1

    def _angle(self, index: int) -> int:
        if self._word or not self._code_at(index + 1, "("):
            return self._literal(index)
        close = same_line_close(self.chars, index + 2, stop_at_blank=True)
        if close is None:
            self._word.extend(self.chars[index : index + 2])
            self._substitution = ProcessSubstitution.OPEN
            return index + 2
        self._word.extend(self.chars[index : close + 1])
        self._substitution = ProcessSubstitution.WHOLE
        return close + 1

    def _bar(self, index: int) -> int:
        """`|`, `||`, and bash's `|&` read as `|`. After an unquoted `>` it is the clobber
        redirect `>|`, part of its token."""
        if self._word and self._code_at(index - 1, ">"):
            return self._literal(index)
        if self._code_at(index + 1, "|"):
            self._end(continues_pipeline=False)
            return index + 2
        self._end(continues_pipeline=True)
        return index + 2 if self._code_at(index + 1, "&") else index + 1

    def _ampersand(self, index: int) -> int:
        """`&&` and `&` end a simple command; an `&` beside a `>` is part of a redirect."""
        if self._code_at(index + 1, "&"):
            self._end(continues_pipeline=False)
            return index + 2
        if self._code_at(index - 1, ">") or self._code_at(index + 1, ">"):
            return self._literal(index)
        self._end(continues_pipeline=False)
        return index + 1
