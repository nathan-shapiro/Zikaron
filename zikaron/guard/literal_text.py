"""Row 5 of `design/edit-guards.md` §3.2: literal text written into a file.

| Command word | Matches when | Targets |
|---|---|---|
| `echo`, `printf` | its simple command has a sink | each sink's target |
| `cat` | it has a sink, and a token beginning `<<` or opening a heredoc | each sink's target |
| `tee` | it is fed by literal text (below) | its non-flag words, and any sink's target |

`tee` is **fed by literal text** when its own simple command has a `<<` or `<<<`, or when walking
back along the pipeline over filters reaches a simple command that opens a heredoc, carries a
`<<<`, or is `echo`/`printf`. A shell or interpreter stops the walk: what reaches `tee` is then
that program's output, which this rule leaves alone.

**Row 5 never looks inside a heredoc body for its sink** — the sink must be on the opener's line —
so a PR body's `>` and `->` are never sinks.

>>> from zikaron.guard.chars import Char, Kind
>>> from zikaron.guard.grammar import parse
>>> def targets(command: str) -> list[list[str]]:
...     (pipeline,) = parse([Char(c, Kind.CODE) for c in command])
...     return [literal_targets(pipeline, i, 0) for i in range(len(pipeline))]
>>> targets("printf '%s' x >> f")
[['f']]
>>> targets("echo x | grep x | tee /tmp/x f")
[[], [], ['/tmp/x', 'f']]
>>> targets("python3 - <<<x | tee out.txt")
[[], []]
"""

from typing import Final

from zikaron.guard.grammar import Pipeline
from zikaron.guard.position import command_name, command_words
from zikaron.guard.programs import executes_text
from zikaron.guard.redirects import find_redirects

WORDS: Final = frozenset({"cat", "echo", "printf", "tee"})
_PRINTERS: Final = frozenset({"echo", "printf"})


def literal_targets(pipeline: Pipeline, command: int, word: int) -> list[str]:
    """The targets of row 5 for the command word at token `word` of the pipeline's `command`-th
    simple command, as written — empty when the form does not match."""
    simple = pipeline[command]
    name = command_name(simple.tokens[word])
    arguments = simple.tokens[word + 1 :]
    redirects = find_redirects(arguments)
    if name in _PRINTERS:
        return list(redirects.sinks)
    if name == "cat":
        here_text = any(token.has_here_text for token in arguments)
        return list(redirects.sinks) if redirects.sinks and here_text else []
    if name != "tee" or not _fed_literal_text(pipeline, command, word):
        return []
    own = [
        token.raw
        for index, token in enumerate(arguments)
        if index not in redirects.tokens
        and token.is_word
        and not (token.starts_unquoted and token.unquoted.startswith("-"))
    ]
    return own + list(redirects.sinks)


def _fed_literal_text(pipeline: Pipeline, command: int, word: int) -> bool:
    if any(token.has_here_text for token in pipeline[command].tokens[word + 1 :]):
        return True
    for earlier in reversed(pipeline[:command]):
        names = [command_name(earlier.tokens[k]) for k in command_words(earlier)]
        if any(executes_text(name) for name in names):
            return False
        if _PRINTERS.intersection(names) or any(token.has_here_text for token in earlier.tokens):
            return True
    return False
