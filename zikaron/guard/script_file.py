"""Row 6 of `design/edit-guards.md` §3.2: a scratch script, run — and the guard's one file read.

A shell or row-4 interpreter whose **script operand** is scratch (§3.3) has that script judged as
if it were the scanned body of a heredoc fed to the same word: an interpreter's text for row 4's
write calls, a shell's for every row, line by line. **The text** is the body a row-5 `cat`/`tee`
heredoc wrote to that path earlier in the same unit, or else the file itself, read once.

| Command (`cwd` `/home/u/proj`) | Row 6 |
|---|---|
| `cat > /tmp/fix.py <<'EOF'` / `open('f','w')` / `EOF` / `python3 /tmp/fix.py` | denies: `f` |
| `python3 "$TMPDIR/fix.py"` | judges the file, if one is there |
| `cd /tmp/w && bash rewrite.sh` | judges `/tmp/w/rewrite.sh` |
| `python fix.py` · `python3 -m fix /tmp/x` · `bash -c '…' /tmp/fix.sh` | no scratch operand |

The judged script starts from the run's directory and no bindings — its process inherits the one
and none of the command's unexported variables — and inside its text row 6 reads no file.

>>> from zikaron.guard.decision import decide
>>> staged = "cat > /tmp/fix.py <<'EOF'\\nopen('f','w')\\nEOF\\npython3 /tmp/fix.py"
>>> match = decide(staged, Location(cwd="/home/u/proj")).match
>>> match.form.name, match.word, match.authored_paths
('SCRATCH_SCRIPT', 'python3', ('/home/u/proj/f',))
"""

import enum
import os
import stat
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from zikaron.guard.forms import Form, FormMatch, Target, script_targets
from zikaron.guard.grammar import Pipeline, SimpleCommand, Token
from zikaron.guard.heredoc import Unit, delimit
from zikaron.guard.lexer import executed_text
from zikaron.guard.literal_text import literal_targets
from zikaron.guard.position import command_name, command_words
from zikaron.guard.programs import is_python, is_shell
from zikaron.guard.redirects import find_redirects
from zikaron.guard.scratch import Location

#: The most row 6 reads: 256 KiB.
MAXIMUM_BYTES: Final = 256 * 1024

#: Reads the script file at a path, or answers `None`.
Reader = Callable[[str], str | None]
#: Every match in a shell script's text, judged from a location as a scanned body is.
ShellJudge = Callable[[Unit, Location], list[FormMatch]]

_PYTHON_TAKES_NEXT: Final = frozenset({"--check-hash-based-pycs"})
_NODE_TAKES_NEXT: Final = frozenset({
    "-r", "--require", "--import", "--loader", "--experimental-loader", "--input-type", "-C",
    "--conditions",
})  # fmt: skip
_NODE_NO_FILE: Final = frozenset({"-e", "-p", "--eval", "--print"})
_SHELL_TAKES_NEXT: Final = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})


class _Option(enum.Enum):
    """What one option token means for finding the operand after it."""

    ALONE = "alone"
    TAKES_NEXT = "takes the next token"
    NO_FILE = "no script file"


def script_operand(simple: SimpleCommand, word: int) -> Token | None:
    """The script file the shell or interpreter at token `word` runs, or `None` when it runs none.

    >>> from zikaron.guard.chars import Char, Kind
    >>> from zikaron.guard.grammar import parse
    >>> def operand(command: str) -> str | None:
    ...     (pipeline,) = parse([Char(c, Kind.CODE) for c in command])
    ...     found = script_operand(pipeline[0], 0)
    ...     return None if found is None else found.raw
    >>> [operand(c) for c in ("python3 -u -X utf8 f.py", "python3 -Werror f.py", "bash -o x f")]
    ['f.py', 'f.py', 'f']
    >>> [operand(c) for c in ("python3 -um m", "node -e x f.js", "bash -ec x f", "python3 - f")]
    [None, None, None, None]
    >>> operand("bash -- -f"), operand("node --require r f.js > out"), operand("node +x")
    ('-f', 'f.js', '+x')
    >>> operand("bash <(x)"), operand("bash <(x) f")
    (None, 'f')
    """
    name = command_name(simple.tokens[word])
    arguments = simple.tokens[word + 1 :]
    redirects = find_redirects(arguments).tokens
    tokens = iter(
        token for index, token in enumerate(arguments) if index not in redirects and token.is_word
    )
    for token in tokens:
        if not _is_option(token, name):
            return token
        if token.unquoted == "--":
            return next(tokens, None)
        option = _option(name, token.unquoted)
        if option is _Option.NO_FILE:
            return None
        if option is _Option.TAKES_NEXT:
            next(tokens, None)
    return None


def _is_option(token: Token, name: str) -> bool:
    prefixes = ("-", "+") if is_shell(name) else ("-",)
    return token.starts_unquoted and token.unquoted.startswith(prefixes)


def _option(name: str, text: str) -> _Option:
    if text == "-":
        return _Option.NO_FILE
    if is_python(name):
        return _python_option(text)
    if is_shell(name):
        return _shell_option(text)
    if text in _NODE_NO_FILE:
        return _Option.NO_FILE
    return _Option.TAKES_NEXT if text in _NODE_TAKES_NEXT else _Option.ALONE


def _python_option(text: str) -> _Option:
    """A Python option, a short-flag cluster read letter by letter: `W` or `X` takes the rest of
    the token, or the next one when it is last; `m` or `c` means no script file.

    >>> options = ("--check-hash-based-pycs", "--version", "-u", "-uc", "-Wd", "-uW")
    >>> [_python_option(o).name for o in options]
    ['TAKES_NEXT', 'ALONE', 'ALONE', 'NO_FILE', 'ALONE', 'TAKES_NEXT']
    """
    if text in _PYTHON_TAKES_NEXT:
        return _Option.TAKES_NEXT
    if text.startswith("--"):
        return _Option.ALONE
    for index, letter in enumerate(text[1:], start=1):
        if letter in "mc":
            return _Option.NO_FILE
        if letter in "WX":
            return _Option.TAKES_NEXT if index == len(text) - 1 else _Option.ALONE
    return _Option.ALONE


def _shell_option(text: str) -> _Option:
    """A shell option: a cluster holding `c` (an inline script) or `s` (stdin) means no file."""
    if text in _SHELL_TAKES_NEXT:
        return _Option.TAKES_NEXT
    if not text.startswith("--") and ("c" in text or "s" in text):
        return _Option.NO_FILE
    return _Option.ALONE


def staged_texts(pipeline: Pipeline, location: Location) -> dict[str, str]:
    """The heredoc bodies a row-5 `cat` or `tee` in `pipeline` writes, by where each goes: a
    `cat`'s own heredoc, or the latest heredoc feeding a `tee` — its own, or one before it in the
    pipeline, as row 5's walk back finds it."""
    staged: dict[str, str] = {}
    for index, simple in enumerate(pipeline):
        for word in command_words(simple):
            name = command_name(simple.tokens[word])
            if name not in ("cat", "tee"):
                continue
            fed = pipeline[: index + 1] if name == "tee" else (simple,)
            bodies = [text for each in fed for token in each.tokens for text in token.heredoc_texts]
            if not bodies:
                continue
            for raw in literal_targets(pipeline, index, word):
                staged[_key(raw, location)] = bodies[-1]
    return staged


def read_script(path: str) -> str | None:
    """The text of the regular file at `path`, read once, or `None`: for a missing file, a symlink,
    anything not a regular file, one over `MAXIMUM_BYTES`, or any error. It never blocks, so a
    FIFO cannot hang the hook."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size > MAXIMUM_BYTES:
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(MAXIMUM_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    return None if len(data) > MAXIMUM_BYTES else data.decode("utf-8", errors="replace")


@dataclass(frozen=True, slots=True)
class ScriptRuns:
    """Row 6's judge over one unit: the bodies staged so far, how a file is read — `None` inside a
    script's own text, which reads none — and how a shell's text is judged."""

    staged: dict[str, str]
    read: Reader | None
    judge_shell: ShellJudge

    def __call__(
        self, pipeline: Pipeline, command: int, word: int, name: str, location: Location
    ) -> FormMatch | None:
        operand = script_operand(pipeline[command], word)
        if operand is None or not location.is_scratch(operand.raw):
            return None
        text = self._text(operand.raw, location)
        if text is None:
            return None
        unit = delimit(text.split("\n"))
        start = location.in_child()
        if is_shell(name):
            targets = _shell_targets(self.judge_shell(unit, start))
        else:
            targets = script_targets(executed_text(unit), start)
        return None if targets is None else FormMatch(Form.SCRATCH_SCRIPT, name, targets)

    def _text(self, raw: str, location: Location) -> str | None:
        staged = self.staged.get(_key(raw, location))
        if staged is not None or self.read is None:
            return staged
        path = location.file_path(raw)
        return None if path is None else self.read(path)


def _shell_targets(matches: Sequence[FormMatch]) -> tuple[Target, ...] | None:
    """A shell script's targets: every matched row's, a row naming none counting as a target that
    is not exempt; `None` when no row matched."""
    return tuple(_each_target(matches)) if matches else None


def _each_target(matches: Sequence[FormMatch]) -> Iterator[Target]:
    for match in matches:
        yield from match.targets or (Target(None, is_scratch=False),)


def _key(raw: str, location: Location) -> str:
    """Where a staging and a run meet: the file's path where the rules can locate one, else the
    resolved spelling, so `$TMPDIR/x` still meets itself on a machine with no `$TMPDIR`."""
    return location.file_path(raw) or location.resolve(raw)
