"""Sinks and redirect tokens (`design/edit-guards.md` §3.1).

A **sink** writes a file: an unquoted `>` or `>>` with its target in the next token, or glued to
it. A **redirect token** is any token that is part of a redirection — a sink and its target,
`<…`, `>&…`, `&>…`, a digit followed by `>` or `<`, and the word after a bare operator of those.
Redirect tokens are never targets of rows 1 to 3 nor of `tee`.

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
