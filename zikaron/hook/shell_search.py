"""Which paths the searches in a shell command covered, for the search reminder.

`design/code-knowledge.md` §6 is normative. A search is a simple command whose word, in command
position as `design/guards.md` §3.1 finds one, is `grep`, `egrep`, `fgrep` or `rg`, or `git` whose
subcommand is `grep`; its operands are read as the guard reads `grep`'s, each program with the
options of its own that take an argument. Read by the guard's own parser, so a command means one
thing to both hooks.

With no path, a recursive `grep`, an `rg` and a `git grep` search the working directory, while any
other `grep`, and an `rg` after a `|`, reads its input and searches nothing. One whose paths come
from elsewhere — a stand-in among its operands, or run by `xargs` — searches nothing either. A
relative path is taken against the working directory the payload names, a leading `~` expanded; a
`cd` earlier in the same command is not followed.
"""

import os
from collections.abc import Iterator, Sequence
from itertools import takewhile
from pathlib import Path, PurePosixPath
from typing import Final

from zikaron.guard.grammar import SimpleCommand, Token, parse
from zikaron.guard.grep_filter import LONG_SKIPPED, Grep, read_grep
from zikaron.guard.heredoc import delimit
from zikaron.guard.lexer import annotate
from zikaron.guard.position import command_name, command_words
from zikaron.guard.redirects import arguments

GREPS: Final = frozenset({"grep", "egrep", "fgrep"})
RIPGREP: Final = "rg"
GIT: Final = "git"
_GIT_GREP: Final = "grep"

#: `rg`'s option that lists the files it would search: every operand is a path, none a pattern.
_RG_LISTS_FILES: Final = "--files"

#: `rg`'s short options that take an argument, `-e` and `-f` aside, which it reads as `grep` does.
RG_SKIPPED: Final = frozenset("ABCmgtTjMrEd")
#: `rg`'s long options that take an argument, unless written with `=value`.
RG_LONG_SKIPPED: Final = frozenset(
    {
        "--after-context",
        "--before-context",
        "--context",
        "--context-separator",
        "--color",
        "--colors",
        "--dfa-size-limit",
        "--encoding",
        "--engine",
        "--field-context-separator",
        "--field-match-separator",
        "--glob",
        "--hostname-bin",
        "--hyperlink-format",
        "--iglob",
        "--ignore-file",
        "--max-columns",
        "--max-count",
        "--max-depth",
        "--max-filesize",
        "--path-separator",
        "--pre",
        "--pre-glob",
        "--regex-size-limit",
        "--replace",
        "--sort",
        "--sortr",
        "--threads",
        "--type",
        "--type-add",
        "--type-clear",
        "--type-not",
    }
)
#: `git grep`'s long options that take an argument beyond `grep`'s own.
GIT_GREP_LONG_SKIPPED: Final = LONG_SKIPPED | {"--max-depth", "--threads"}

#: `git`'s own options before its subcommand that take an argument: `-C` moves the directory the
#: subcommand runs in, and `-c` sets a configuration value.
_GIT_MOVES: Final = "-C"
_GIT_SETS: Final = "-c"

#: How a pathspec names the repository's top, read as the project's directory.
_TOP_PATHSPEC: Final = ":/"
_MAGIC: Final = ":"
#: What separates a `git grep`'s revisions from its pathspecs.
_SEPARATOR: Final = "--"
#: The characters that make a pathspec component a glob.
_GLOB: Final = frozenset("*?[")

#: Operands that stand for paths named elsewhere rather than naming one.
_STAND_IN: Final = "{}"
_TERMINATORS: Final = frozenset({"+", ";", "-"})

#: A program that hands the command it runs paths read from its input, so a search it runs names
#: none of its own.
_SUPPLIES_PATHS: Final = frozenset({"xargs"})


def searched_paths(command: str, *, cwd: str, top: str) -> tuple[str, ...]:
    """Every path the searches in `command` covered, absolute and normalized; empty when it ran no
    search. `cwd` is the directory the command ran in, and `top` the project's."""
    found: list[str] = []
    for pipeline in parse(annotate(delimit(command.split("\n")))):
        for index, simple in enumerate(pipeline):
            for word in command_words(simple):
                if not _run_by_a_supplier(simple, word):
                    found.extend(_searched(simple, word, after_pipe=index > 0, cwd=cwd, top=top))
    return tuple(found)


def _run_by_a_supplier(simple: SimpleCommand, word: int) -> bool:
    """Whether the command at `word` is run by one that hands it paths, which the parser passes
    over as a wrapper and so places before it in the same simple command."""
    return any(
        token.is_word and command_name(token) in _SUPPLIES_PATHS for token in simple.tokens[:word]
    )


def _searched(
    simple: SimpleCommand, word: int, *, after_pipe: bool, cwd: str, top: str
) -> Iterator[str]:
    name = command_name(simple.tokens[word])
    given = arguments(simple.tokens, word)
    if name in GREPS:
        grep = read_grep(given)
        if grep.names_a_pattern:
            yield from _paths(grep.paths, cwd=cwd, default=cwd if grep.recursive else None)
    elif name == RIPGREP:
        rg = read_grep(given, skipped=RG_SKIPPED, long_skipped=RG_LONG_SKIPPED)
        listing = any(token.unquoted == _RG_LISTS_FILES for token in given)
        if listing or rg.names_a_pattern:
            written = rg.operands if listing else rg.paths
            yield from _paths(written, cwd=cwd, default=None if after_pipe else cwd)
    elif name == GIT:
        yield from _git_grep(given, cwd=cwd, top=top)


def _git_grep(given: Sequence[Token], *, cwd: str, top: str) -> Iterator[str]:
    """A `git grep`'s paths: its pathspecs, `:/` read as `top` and any other magic one as no path,
    or the directory it ran in when none is left."""
    index = 0
    base = cwd
    while index < len(given) and given[index].unquoted.startswith("-"):
        option = given[index].unquoted
        if option in (_GIT_MOVES, _GIT_SETS) and index + 1 < len(given):
            if option == _GIT_MOVES:
                base = _absolute(given[index + 1].unquoted, cwd=base)
            index += 1
        index += 1
    if index >= len(given) or given[index].unquoted != _GIT_GREP:
        return
    rest = given[index + 1 :]
    grep = read_grep(rest, long_skipped=GIT_GREP_LONG_SKIPPED)
    if not grep.names_a_pattern:
        return
    pathspecs = [
        _literal_prefix(
            str(Path(top) / path.removeprefix(_TOP_PATHSPEC))
            if path.startswith(_TOP_PATHSPEC)
            else path
        )
        for path in _after_revisions(rest, grep)
        if path.startswith(_TOP_PATHSPEC) or not path.startswith(_MAGIC)
    ]
    yield from _paths(pathspecs, cwd=base, default=base)


def _after_revisions(given: Sequence[Token], grep: Grep) -> list[str]:
    """A `git grep`'s written pathspecs: every operand after a `--`, since `git grep <pattern>
    [<rev>…] -- [<pathspec>…]` makes each operand before it but the pattern a revision. Without a
    `--`, nothing lexical tells a revision from a path, and every operand is read as a path.

    A `--` before any pattern only ends the options, as git reads it, so the pattern follows it
    and a second `--` is the one that separates revisions from pathspecs.
    """
    words = list(takewhile(lambda token: token.is_word, given))
    dash = next((i for i, token in enumerate(words) if token.unquoted == _SEPARATOR), None)
    if dash is None:
        return grep.paths
    after = [token.unquoted for token in words[dash + 1 :]]
    if after == grep.operands and len(grep.paths) < len(grep.operands):
        following = after[1:]
        if _SEPARATOR in following:
            return following[following.index(_SEPARATOR) + 1 :]
        return following
    return after


def _literal_prefix(pathspec: str) -> str:
    """A pathspec up to its first component carrying a wildcard, since git's globs cross
    directories: `*.c` searches every directory below, and `src/*.rs` every one below `src`."""
    literal = list(takewhile(lambda part: not _GLOB & set(part), PurePosixPath(pathspec).parts))
    return str(PurePosixPath(*literal)) if literal else "."


def _paths(written: Sequence[str], *, cwd: str, default: str | None) -> Iterator[str]:
    """`written` made absolute, or `default` alone when nothing was written — and nothing at all
    when an operand stands in for paths named elsewhere: `find -exec`'s and `xargs -I`'s `{}`,
    `find`'s `+` and `;`, and `-` for the input."""
    if any(_STAND_IN in path or path in _TERMINATORS for path in written):
        return
    if written:
        yield from (_absolute(path, cwd=cwd) for path in written)
    elif default is not None:
        yield os.path.normpath(default)


def _absolute(path: str, *, cwd: str) -> str:
    return os.path.normpath(Path(cwd) / Path(path).expanduser())
