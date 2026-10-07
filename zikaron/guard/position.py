"""Command position: which words of a simple command are commands (`design/edit-guards.md` §3.1).

A form's command word counts only in command position. A position opens at the start of a simple
command, after a boundary (`(`, a standalone `{`, an unclosed `$(`), and after `find`'s `-exec`
or `-execdir`. From there, leading `NAME=value` assignments, the shell keywords and the wrappers
below are skipped, each wrapper with its `-`-prefixed flags and the separate argument of the flags
that take one.

It also reads the two things a simple command changes for the commands after it (§3.3): the
variables an assignment-only command binds, and the directory a `cd` moves to.

>>> from zikaron.guard.chars import Char, Kind
>>> from zikaron.guard.grammar import parse
>>> def words(command: str) -> list[str]:
...     (pipeline,) = parse([Char(c, Kind.CODE) for c in command])
...     return [command_name(pipeline[0].tokens[k]) for k in command_words(pipeline[0])]
>>> words("LC_ALL=C timeout -s KILL 60 /usr/bin/sed -i x f")
['sed']
>>> words("find . -exec sed -i x {} +")
['find', 'sed']
>>> words('grep -rn "sed -i" tests/')
['grep']
"""

import re
from collections.abc import Sequence
from typing import Final

from zikaron.guard.grammar import SimpleCommand, Token

KEYWORDS: Final = frozenset({"if", "while", "until", "do", "then", "else", "elif"})

#: The wrappers a command word may stand behind, each with its own flags.
WRAPPERS: Final = frozenset(
    {
        "sudo",
        "env",
        "xargs",
        "time",
        "timeout",
        "nice",
        "nohup",
        "command",
        "exec",
        "busybox",
        "npx",
    }
)

#: The two-word wrappers, each the runner's name followed by `run`.
RUNNERS: Final = frozenset({"uv", "poetry", "pdm", "pipenv"})

#: The flags that consume the next word, per wrapper. Only a bare flag consumes: `-I{}` carries
#: its argument attached.
ARGUMENT_FLAGS: Final[dict[str, frozenset[str]]] = {
    "xargs": frozenset({"-I", "-n", "-L", "-P", "-d", "-s", "-E", "--max-args", "--max-procs"}),
    "nice": frozenset({"-n"}),
    "sudo": frozenset({"-u", "-g", "--user", "--group"}),
    "env": frozenset({"-u"}),
    "timeout": frozenset({"-s", "-k", "--signal", "--kill-after"}),
    "uv run": frozenset({"--with", "--python", "-p"}),
}

_ASSIGNMENT: Final = re.compile(r"[A-Za-z_]\w*=.*", re.DOTALL)
_PATH_PREFIX: Final = re.compile(r"^(?:\S*/)?")


def base_name(word: str) -> str:
    """A word without its leading `\\` (the alias-skipping spelling) or its path prefix.

    >>> base_name("\\\\sed"), base_name("/usr/bin/env"), base_name(".venv/bin/python")
    ('sed', 'env', 'python')
    """
    return _PATH_PREFIX.sub("", word.lstrip("\\"))


def command_name(token: Token) -> str:
    """The name a command word is compared under: unquoted, without its path prefix."""
    return base_name(token.unquoted)


def command_words(command: SimpleCommand) -> list[int]:
    """The indices of the command words in `command`, ascending."""
    starts = set(command.positions)
    starts.update(
        index + 1
        for index, token in enumerate(command.tokens)
        if token.boundary is None and token.unquoted in ("-exec", "-execdir")
    )
    found = {_skip_prefix(command.tokens, start) for start in starts}
    return sorted(index for index in found if index is not None and index < len(command.tokens))


def bound_variables(command: SimpleCommand) -> tuple[tuple[str, str], ...]:
    """The `(name, value)` pairs a simple command made only of `NAME=value` words binds for the
    commands after it; none for any other command — a prefix assignment (`S=x cmd`) binds only
    `cmd`'s environment, and its own words were expanded before it took effect.

    >>> from zikaron.guard.chars import Char, Kind
    >>> from zikaron.guard.grammar import parse
    >>> [bound_variables(p[0]) for p in parse([Char(c, Kind.CODE) for c in "S=/tmp/x D=a; S=b ls"])]
    [(('S', '/tmp/x'), ('D', 'a')), ()]
    """
    words = [token.unquoted for token in command.tokens]
    if not words or not all(
        token.is_word and _ASSIGNMENT.fullmatch(word)
        for token, word in zip(command.tokens, words, strict=True)
    ):
        return ()
    return tuple((name, value) for name, _, value in (word.partition("=") for word in words))


def changed_directory(command: SimpleCommand) -> str | None:
    """The directory a simple command that is exactly `cd DIR` moves to, as written; `None` for any
    other command, and for `cd -` or a `~` path, whose directory the rules cannot know.

    >>> from zikaron.guard.chars import Char, Kind
    >>> from zikaron.guard.grammar import parse
    >>> pipelines = parse([Char(c, Kind.CODE) for c in "cd /tmp/x; cd; cd -"])
    >>> [changed_directory(pipeline[0]) for pipeline in pipelines]
    ['/tmp/x', None, None]
    """
    match [token.raw if token.is_word else None for token in command.tokens]:
        case ["cd", str(directory)] if directory != "-" and not directory.startswith("~"):
            return directory
        case _:
            return None


def _skip_prefix(tokens: Sequence[Token], index: int) -> int | None:
    """The command word a position at `index` reaches, or `None` when a boundary or the end of the
    command comes first."""
    while index < len(tokens):
        token = tokens[index]
        if token.boundary is not None:
            return None
        name = base_name(token.unquoted)
        if _ASSIGNMENT.fullmatch(token.unquoted) or name in KEYWORDS:
            index += 1
            continue
        wrapper = _wrapper_at(tokens, index, name)
        if wrapper is None:
            return index
        index = _skip_wrapper(tokens, index + len(wrapper.split()), wrapper)
    return None


def _wrapper_at(tokens: Sequence[Token], index: int, name: str) -> str | None:
    """The wrapper starting at `index` — `uv run` spelled as its two words — or `None`."""
    if name in RUNNERS and index + 1 < len(tokens) and tokens[index + 1].unquoted == "run":
        return f"{name} run"
    return name if name in WRAPPERS else None


def _skip_wrapper(tokens: Sequence[Token], index: int, wrapper: str) -> int:
    """Past a wrapper's flags, each argument-taking flag's argument, and `timeout`'s duration —
    the one word after its flags, whatever it is."""
    takes_argument = ARGUMENT_FLAGS.get(wrapper, frozenset())
    while index < len(tokens) and tokens[index].boundary is None:
        flag = tokens[index].unquoted
        if not flag.startswith("-"):
            break
        index += 2 if flag in takes_argument else 1
    if wrapper == "timeout" and index < len(tokens):
        index += 1
    return index
