"""A pattern handed to `pgrep` or `grep`: whether its text is known, and how `re` reads it.

`design/guards.md` §9.1 and §9.2. A pattern is **literal** when its token carries no `$` or backtick
outside single quotes, so what the program receives is what the command shows; any other pattern
is not judged, since what it will hold is not in the text — except, for `pgrep` and `pkill`, a
variable the command binds, which `selfmatch` reads as its value.

>>> from zikaron.guard.heredoc import delimit
>>> from zikaron.guard.grammar import parse
>>> from zikaron.guard.lexer import annotate
>>> (pipeline,) = parse(annotate(delimit(["pkill -f '$x' \\"$y\\" z$"])))
>>> [literal_text(token) for token in pipeline[0].tokens[2:]]
['$x', None, None]
>>> compiled("pgrep(", ignore_case=False) is None
True
"""

import re
import warnings

from zikaron.guard.chars import Kind
from zikaron.guard.grammar import Token

_EXPANSIONS = frozenset("$`")


def literal_text(token: Token) -> str | None:
    """The token's text as the program receives it, or `None` when an expansion decides that."""
    for char in token.chars:
        quoted = char.kind is Kind.STRING and char.quote == "'"
        if char.text in _EXPANSIONS and not quoted:
            return None
    return token.unquoted


def compiled(pattern: str, *, ignore_case: bool) -> re.Pattern[str] | None:
    """`pattern` compiled by `re`, or `None` where `re` cannot compile it.

    Warnings are ignored: `re` warns on a POSIX class such as `[[:alpha:]]`, and under a filter
    that turns warnings into errors the same command would otherwise decide differently.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error:
            return None
