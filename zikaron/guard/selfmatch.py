"""The self-match rule: a `pgrep -f`/`pkill -f` whose pattern matches its own command
(`design/guards.md` §9).

Claude Code runs a command inside a shell whose command line carries the command's text, so where
the platform's `pgrep` can match its own ancestors, a pattern that searches that text matches the
shell: `pkill` kills it, and `pgrep` always finds it. **The test is that search**, the pattern
compiled by `re` and run over the command as received, so nothing here decides which spellings
are safe. `pgrep` and `pkill` are read in command position (§3.1), on the command's own lines and
in every scanned heredoc body, and this rule alone also reads past a `!`. A pattern that is a
variable the command binds is read as the bound value.

| Command | `linux` | `darwin` |
|---|---|---|
| `pkill -f month_monitor.py` | deny | silent: ancestors are excluded |
| `P=month_monitor.py; pkill -f "$P"` | deny: the bound value is the pattern | silent |
| `pkill -f '[m]onth_monitor.py'` | silent: the bracket does not match its own spelling | silent |
| `pgrep -A -f month_monitor.py` | silent: `-A` excludes the ancestors | silent |
| `pgrep -af month_monitor.py` | deny | deny: `-a` includes the ancestors |
| `pgrep -af month_monitor.py \\| grep -v grep` | silent: the filter drops the shell's line | deny |

>>> from zikaron.guard.heredoc import delimit
>>> def judge(command: str, platform: str = "linux") -> SelfMatch | None:
...     return first_self_match(delimit(command.split("\\n")), command, platform)
>>> found = judge("cd /s && until ! timeout 5 pgrep -f day_panel.py >/dev/null; do sleep 15; done")
>>> found.word, found.platform, found.excerpt
('pgrep', <Platform.LINUX: 'linux'>, ' timeout 5 pgrep -f day_panel.py >/dev/null; do slee')
>>> judge("pkill -f month_monitor.py", "darwin") is None, judge("pkill -f x", "win32") is None
(True, True)
"""

import enum
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from zikaron.guard.grammar import Pipeline, Token, parse
from zikaron.guard.grep_filter import drops_shell_line
from zikaron.guard.heredoc import Unit
from zikaron.guard.lexer import annotate
from zikaron.guard.patterns import compiled, literal_text
from zikaron.guard.position import bound_variables, command_name, command_word_at, command_words
from zikaron.guard.redirects import arguments

#: The values a unit's assignments bound so far: a name's literal value, or `None` where the last
#: value bound to it is not literal (§9.1).
Bindings = dict[str, str | None]


class Platform(enum.Enum):
    """A platform whose `pgrep` the rule reads, named as `sys.platform` names it."""

    LINUX = "linux"
    DARWIN = "darwin"


@dataclass(frozen=True, slots=True)
class Grammar:
    """How one platform's `pgrep` and `pkill` read their options: one row of §9.1's table."""

    #: The options that must all be given for the rule to apply.
    applies: frozenset[str]
    #: Options any one of which means the call cannot match its shell.
    never: frozenset[str]
    with_argument: frozenset[str]
    #: Long options, each with the short option it spells.
    long_names: Mapping[str, str]
    #: Long options that take an argument, unless written with `=value`.
    long_with_argument: frozenset[str]
    #: The option that makes `pgrep` print each command line, so that a `grep -v` can drop the
    #: shell's (§9.2); `None` where that exemption does not apply.
    lists_command_lines: str | None


GRAMMARS: Final[Mapping[Platform, Grammar]] = {
    Platform.LINUX: Grammar(
        applies=frozenset("f"),
        never=frozenset("xAv"),
        with_argument=frozenset("dgGOPstuUFrq"),
        long_names={
            "--full": "f",
            "--exact": "x",
            "--ignore-ancestors": "A",
            "--inverse": "v",
            "--list-full": "a",
            "--ignore-case": "i",
        },
        long_with_argument=frozenset(
            {
                "--delimiter",
                "--pgroup",
                "--group",
                "--older",
                "--parent",
                "--session",
                "--signal",
                "--terminal",
                "--euid",
                "--uid",
                "--pidfile",
                "--runstates",
                "--cgroup",
                "--ns",
                "--nslist",
                "--queue",
            }
        ),
        lists_command_lines="a",
    ),
    Platform.DARWIN: Grammar(
        applies=frozenset("fa"),
        never=frozenset("xv"),
        with_argument=frozenset("FGPUcdgtu"),
        long_names={},
        long_with_argument=frozenset(),
        lists_command_lines=None,
    ),
}

#: The signal names `pkill` takes as `-NAME` or `-SIGNAME`, on either platform.
SIGNAL_NAMES: Final = (
    "HUP", "INT", "QUIT", "ILL", "TRAP", "ABRT", "IOT", "EMT", "BUS", "FPE", "KILL", "USR1", "SEGV",
    "USR2", "PIPE", "ALRM", "TERM", "STKFLT", "CHLD", "CONT", "STOP", "TSTP", "TTIN", "TTOU", "URG",
    "XCPU", "XFSZ", "VTALRM", "PROF", "WINCH", "IO", "POLL", "INFO", "PWR", "SYS", "RTMIN", "RTMAX",
)  # fmt: skip
_SIGNAL: Final = re.compile(
    r"-(?:\d+|(?:SIG)?(?:" + "|".join(SIGNAL_NAMES) + r"|RTMIN\+\d+|RTMAX-\d+))", re.IGNORECASE
)
_PGREP, _PKILL = "pgrep", "pkill"
_NEGATION: Final = "!"
_IGNORE_CASE: Final = "i"
#: A pattern token that is one variable and nothing else: `$NAME` or `${NAME}`, bare or in double
#: quotes.
_VARIABLE: Final = re.compile(r'(?P<quote>"?)\$(?:(?P<name>\w+)|\{(?P<braced>\w+)\})(?P=quote)')
#: How many characters of the command a deny shows on each side of the match.
_CONTEXT: Final = 20


@dataclass(frozen=True, slots=True)
class Call:
    """One `pgrep` or `pkill`: the options given, and its pattern — the first operand."""

    word: str
    options: frozenset[str]
    pattern: Token | None


@dataclass(frozen=True, slots=True)
class SelfMatch:
    """A `pgrep`/`pkill` whose pattern matches the command's own text."""

    word: str
    platform: Platform
    #: The matched text, with up to `_CONTEXT` characters of its line on either side.
    excerpt: str


def first_self_match(top: Unit, command: str, platform: str) -> SelfMatch | None:
    """The first `pgrep`/`pkill` in `command`, delimited as `top`, whose pattern matches
    `command` on `platform` — a `sys.platform` value — or `None`."""
    known = next((each for each in Platform if each.value == platform), None)
    if known is None:
        return None
    for unit in top.walk():
        bound: Bindings = {}
        for pipeline in parse(annotate(unit)):
            found = _in_pipeline(pipeline, command, known, bound)
            if found is not None:
                return found
            bound.update(_bindings(pipeline))
    return None


def _bindings(pipeline: Pipeline) -> Iterator[tuple[str, str | None]]:
    """What `pipeline`'s assignment-only commands bind for the pipelines after it, as §3.3 reads a
    binding, each value `None` where its token is not literal. What a same-line `$(…)`'s own
    commands bind is not read, inside it or after it: a subshell's bindings are not tracked, though
    it inherits those made before it."""
    for simple in pipeline:
        pairs = bound_variables(simple)
        if simple.in_substitution or not pairs:
            continue
        for token, (name, value) in zip(simple.tokens, pairs, strict=True):
            yield name, value if literal_text(token) is not None else None


def _in_pipeline(
    pipeline: Pipeline, command: str, platform: Platform, bound: Bindings
) -> SelfMatch | None:
    grammar = GRAMMARS[platform]
    for index, simple in enumerate(pipeline):
        for word in command_words(simple):
            at = _past_negation(simple.tokens, word)
            if at is None or command_name(simple.tokens[at]) not in (_PGREP, _PKILL):
                continue
            call = read_call(command_name(simple.tokens[at]), arguments(simple.tokens, at), grammar)
            found = _search(call, command, grammar, bound)
            if found is None:
                continue
            lists = call.word == _PGREP and grammar.lists_command_lines in call.options
            if lists and drops_shell_line(pipeline[index + 1 :], command):
                continue
            return SelfMatch(call.word, platform, _excerpt(command, found))
    return None


def _past_negation(tokens: Sequence[Token], index: int) -> int | None:
    """The command word after any `!` at `index`, past the wrappers that follow it (§9.1)."""
    current: int | None = index
    while current is not None and command_name(tokens[current]) == _NEGATION:
        current = command_word_at(tokens, current + 1)
    return current


def read_call(word: str, given: Sequence[Token], grammar: Grammar) -> Call:
    """The options and pattern of the arguments `word` is `given`, its redirections already left
    out, as `grammar`'s platform reads them: an option taking an argument consumes the rest of its
    cluster or the next token, `--` ends the options, and `pkill`'s signal is one token wherever it
    stands."""
    options: set[str] = set()
    consumes = ended = False
    for token in given:
        if not token.is_word:
            break
        text = token.unquoted
        if consumes:
            consumes = False
        elif ended or not text.startswith("-") or text == "-":
            return Call(word, frozenset(options), token)
        elif text == "--":
            ended = True
        elif text.startswith("--"):
            name, equals, _ = text.partition("=")
            if name in grammar.long_names:
                options.add(grammar.long_names[name])
            consumes = name in grammar.long_with_argument and not equals
        elif word != _PKILL or _SIGNAL.fullmatch(text) is None:
            consumes = _read_cluster(text[1:], grammar, options)
    return Call(word, frozenset(options), None)


def _read_cluster(letters: str, grammar: Grammar, options: set[str]) -> bool:
    """Read one `-xyz` cluster into `options`; whether it consumes the next token."""
    for index, letter in enumerate(letters):
        if letter in grammar.with_argument:
            return index == len(letters) - 1
        options.add(letter)
    return False


def _search(call: Call, command: str, grammar: Grammar, bound: Bindings) -> re.Match[str] | None:
    """Where `call`'s pattern matches `command`, if the call can match its shell at all."""
    if call.pattern is None or not grammar.applies <= call.options or grammar.never & call.options:
        return None
    text = _pattern_text(call.pattern, bound)
    if text is None:
        return None
    pattern = compiled(text, ignore_case=_IGNORE_CASE in call.options)
    return None if pattern is None else pattern.search(command)


def _pattern_text(token: Token, bound: Bindings) -> str | None:
    """The pattern as `pgrep` receives it: the token's literal text, or the literal value bound to
    the one variable the token is; `None` where that is not known (§9.1)."""
    literal = literal_text(token)
    if literal is not None:
        return literal
    variable = _VARIABLE.fullmatch(token.raw)
    if variable is None:
        return None
    return bound.get(variable["name"] or variable["braced"])


def _excerpt(command: str, found: re.Match[str]) -> str:
    line_start = command.rfind("\n", 0, found.start()) + 1
    line_end = command.find("\n", found.end())
    end = len(command) if line_end < 0 else line_end
    return command[max(line_start, found.start() - _CONTEXT) : min(end, found.end() + _CONTEXT)]
