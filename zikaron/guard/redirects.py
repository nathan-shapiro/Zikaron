"""Sinks and redirect tokens (`design/guards.md` §3.1).

A **sink** writes a file: an unquoted `>` or `>>` with its target in the next token, or glued to
it. A **redirect token** is any token that is part of a redirection — a sink and its target,
`<…`, `>&…`, `&>…`, a digit followed by `>` or `<`, and the word after a bare operator of those.
Redirect tokens are never targets of rows 1 to 3 nor of `tee`, nor operands of `pgrep`, `pkill` or
§9.2's `grep` (`arguments`).

| Command | Sinks | Redirect tokens |
|---|---|---|
| `echo x > f` | `f` | `>`, `f` |
| `echo x >>f` | `f` | `>>f` |
| `sed … f 2> log` | — | `2>`, `log` |
| `echo x >&2` · `echo x > >(cat)` | — | `>&2` · `>` |

>>> from zikaron.guard.chars import Char, Kind
>>> from zikaron.guard.grammar import parse
>>> def of(command: str) -> Redirects:
...     (pipeline,) = parse([Char(c, Kind.CODE) for c in command])
...     return find_redirects(pipeline[0].tokens)
>>> of("echo x >>f 2> log")
Redirects(sinks=('f',), tokens=frozenset({2, 3, 4}))
"""

import re
from collections.abc import Sequence
from typing import Final, NamedTuple

from zikaron.guard.grammar import ProcessSubstitution, Token

_GLUED_SINK: Final = re.compile(r">>?[^>&(|]")
_DIGIT_REDIRECT: Final = re.compile(r"\d+[<>]")
_BARE_DIGIT_REDIRECT: Final = re.compile(r"\d+(>>?|<|>&)")
_REDIRECT_STARTS: Final = ("<", ">&", "&>")
#: The bare operators whose target is the next word.
_BARE_OPERATORS: Final = frozenset({"&>", "&>>", "<", "<<", "<<-", "<<<", ">&"})


class Redirects(NamedTuple):
    """A simple command's sink targets, as written, and the indices of its redirect tokens."""

    sinks: tuple[str, ...]
    tokens: frozenset[int]


def find_redirects(tokens: Sequence[Token]) -> Redirects:
    """The sinks and redirect tokens among `tokens`."""
    sinks: list[str] = []
    redirect: set[int] = set()
    for index, token in enumerate(tokens):
        if token.boundary is not None or not token.starts_unquoted:
            continue
        if token.process_substitution is ProcessSubstitution.OPEN:
            # Its `)` ends this simple command, so "every token up to that `)`" is the rest.
            redirect.update(range(index, len(tokens)))
            continue
        if token.process_substitution is not None:
            continue
        raw = token.raw
        if raw in (">", ">>"):
            redirect.add(index)
            target = tokens[index + 1] if index + 1 < len(tokens) else None
            if target is not None and target.is_word:
                sinks.append(target.raw)
                redirect.add(index + 1)
        elif _GLUED_SINK.match(raw):
            sinks.append(raw.lstrip(">"))
            redirect.add(index)
        elif raw.startswith(_REDIRECT_STARTS) or _DIGIT_REDIRECT.match(raw):
            redirect.add(index)
            if raw in _BARE_OPERATORS or _BARE_DIGIT_REDIRECT.fullmatch(raw):
                redirect.add(index + 1)
    return Redirects(tuple(sinks), frozenset(redirect))


def arguments(tokens: Sequence[Token], word: int) -> tuple[Token, ...]:
    """The tokens after the command word at index `word`, its redirect tokens left out — what
    the program itself is handed (§9.1).

    >>> from zikaron.guard.chars import Char, Kind
    >>> from zikaron.guard.grammar import parse
    >>> (pipeline,) = parse([Char(c, Kind.CODE) for c in "pgrep -f 2>/dev/null > out x"])
    >>> [token.raw for token in arguments(pipeline[0].tokens, 0)]
    ['-f', 'x']
    """
    redirect = find_redirects(tokens).tokens
    return tuple(
        token for index, token in enumerate(tokens) if index > word and index not in redirect
    )
