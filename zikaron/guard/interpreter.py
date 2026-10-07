"""Row 4 of `design/edit-guards.md` §3.2: an interpreter given an inline script — and the script.

The command word is `python[0-9.]*t?`, `pypy[0-9]*`, `node` or `nodejs`. It runs an **inline
script** when one of these feeds it:

- a `-c`, `-e` or `-E` token, or a short-flag cluster ending in `e`/`E` — or `c` for Python —
  bare or glued to its quoted script (`-c'…'`, `-uc`);
- a `<<` anywhere in its pipeline, a heredoc or a here-string;
- an `echo`/`printf` piping into it from the simple command just before.

**The text searched is the script as the interpreter sees it**: the command's own words with their
shell quotes removed — an opening quote becoming a newline and a closing one a space, `\\"`
unescaped — then every executed heredoc body in the pipeline, raw, then the feeding `echo`'s
words. A multi-line string has its Python-style comments dropped first, so a commented-out write
is not seen.

>>> from zikaron.guard.heredoc import delimit
>>> from zikaron.guard.lexer import annotate
>>> from zikaron.guard.grammar import parse
>>> def script(*lines: str) -> str | None:
...     (pipeline, *_) = parse(annotate(delimit(lines)))
...     return inline_script(pipeline, 0, 0)
>>> script('python3 -c "open(\\\\"f\\\\",\\\\"w\\\\")"')
'-c\\n\\nopen("f","w") '
>>> script("python3 tool.py") is None
True
"""

import re
from typing import Final

from zikaron.guard.chars import Kind
from zikaron.guard.grammar import Pipeline, Token
from zikaron.guard.position import command_name, command_words
from zikaron.guard.programs import is_python
from zikaron.guard.quoting import comment_start, paired_quotes

_SCRIPT_FLAGS: Final = frozenset({"-c", "-e", "-E"})
_PRINTERS: Final = frozenset({"echo", "printf"})


def inline_script(pipeline: Pipeline, command: int, word: int) -> str | None:
    """The script the interpreter at token `word` of the pipeline's `command`-th simple command
    runs, or `None` when nothing feeds it one."""
    simple = pipeline[command]
    arguments = simple.tokens[word + 1 :]
    letters = "ceE" if is_python(command_name(simple.tokens[word])) else "eE"
    flagged = any(_is_script_flag(token, letters) for token in arguments)
    tokens = [token for each in pipeline for token in each.tokens]
    here_text = any(token.has_here_text for token in tokens)
    feeder = _feeding_printer(pipeline, command)
    if not (flagged or here_text or feeder is not None):
        return None
    parts = [_as_interpreted(token) for token in arguments if token.boundary is None]
    parts += [script for token in tokens for script in token.heredoc_scripts]
    parts += [_as_interpreted(token) for token in feeder or () if token.boundary is None]
    return "\n".join(parts)


def _is_script_flag(token: Token, letters: str) -> bool:
    if not token.starts_unquoted:
        return False
    if token.unquoted in _SCRIPT_FLAGS:
        return True
    return re.fullmatch(rf"-[A-Za-z0-9]*[{letters}](['\"].*)?", token.raw, re.DOTALL) is not None


def _feeding_printer(pipeline: Pipeline, command: int) -> tuple[Token, ...] | None:
    """The words after the `echo`/`printf` piping into this command, or `None` when the command
    before it in the pipeline is no printer."""
    if command == 0:
        return None
    previous = pipeline[command - 1]
    words = command_words(previous)
    if not any(command_name(previous.tokens[k]) in _PRINTERS for k in words):
        return None
    return previous.tokens[words[0] + 1 :]


def _as_interpreted(token: Token) -> str:
    """A word with its shell quoting removed, as the interpreter receives it.

    >>> from zikaron.guard.heredoc import delimit
    >>> from zikaron.guard.lexer import annotate
    >>> from zikaron.guard.grammar import parse
    >>> (pipeline,) = parse(annotate(delimit(['echo "a\\\\\\\\\\\\"b"'])))
    >>> _as_interpreted(pipeline[0].tokens[1])
    '\\na\\\\"b '
    """
    text: list[str] = []
    opened = False
    previous = ""
    for char in token.chars:
        collapses = (
            char.kind is Kind.STRING
            and char.quote == '"'
            and previous == "\\"
            and char.text in '"\\$`'
        )
        if char.kind is Kind.QUOTE:
            text.append(" " if opened else "\n")
            opened = not opened
        elif collapses:
            text[-1] = char.text
        else:
            text.append(char.text)
        # A backslash that escaped something is spent: it escapes nothing after it.
        previous = char.text if char.kind is Kind.STRING and not collapses else ""
    interpreted = "".join(text)
    spans_lines = any(char.kind is Kind.STRING and char.text == "\n" for char in token.chars)
    return _drop_comments(interpreted) if spans_lines else interpreted


def _drop_comments(script: str) -> str:
    """Each line's Python-style comment removed, its one-line quoted strings paired first.

    >>> _drop_comments("x = '#'  # a\\n# open('f','w')")
    "x = '#'  \\n"
    """
    lines = []
    for line in script.split("\n"):
        cut = comment_start(line, paired_quotes(line))
        lines.append(line if cut is None else line[:cut])
    return "\n".join(lines)
