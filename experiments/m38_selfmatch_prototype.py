"""The self-match rule's prototype, the one `research/m38-selfmatch-replay.md`'s counts came from.

`design/build-plan.md` §M38 item 6: kept as it was when the brief was approved, so that
`experiments/m38_selfmatch_replay.py` can judge every command with it and with the shipped
`zikaron.guard.selfmatch` in one pass, and list each command on which they disagree. It reads
`linux` only. A `pgrep`/`pkill` in command position, parsed by the find-replace guard's own §3.1
grammar, with `-f` and neither `-x`, `-A` nor `-v`, carries a literal pattern; the rule denies when
that pattern, compiled by Python's `re`, searches the command's own text — unless a `pgrep -a`'s
pipeline continues into a `grep -v` whose own pattern searches that text too, which removes the
shell's line from what is printed.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from zikaron.guard.chars import Kind
from zikaron.guard.grammar import Pipeline, SimpleCommand, Token, parse
from zikaron.guard.heredoc import Unit, delimit
from zikaron.guard.lexer import annotate
from zikaron.guard.position import command_name, command_words

_PROCESS_WORDS = frozenset({"pgrep", "pkill"})
#: procps-ng 4.0.4's options that take an argument, short and long.
_SHORT_WITH_ARG = frozenset("dgGPstuUFrOq")
_LONG_WITH_ARG = frozenset(
    {
        "--delimiter", "--pgroup", "--group", "--parent", "--session", "--terminal", "--euid",
        "--uid", "--pidfile", "--runstates", "--ns", "--nslist", "--signal", "--older", "--cgroup",
        "--queue",
    }
)  # fmt: skip
#: `design/guards.md` §9.1: a signal is `-<digits>` or `-[SIG]<NAME>` from a fixed list, in
#: any case, so `-A` stays an option and `-ABRT` and `-int` are signals.
_SIGNAL_NAMES = (
    "HUP", "INT", "QUIT", "ILL", "TRAP", "ABRT", "IOT", "EMT", "BUS", "FPE", "KILL", "USR1", "SEGV",
    "USR2", "PIPE", "ALRM", "TERM", "STKFLT", "CHLD", "CONT", "STOP", "TSTP", "TTIN", "TTOU", "URG",
    "XCPU", "XFSZ", "VTALRM", "PROF", "WINCH", "IO", "POLL", "INFO", "PWR", "SYS", "RTMIN", "RTMAX",
)  # fmt: skip
_SIGNAL = re.compile(
    r"-(?:\d+|(?:SIG)?(?:" + "|".join(_SIGNAL_NAMES) + r"|RTMIN\+\d+|RTMAX-\d+))$", re.IGNORECASE
)
#: A `$(` that opens, after optional wrappers, a `pgrep`/`pkill` — read inside double quotes,
#: where §3.1 keeps the whole string one token and so neither rule sees it (§9.4).
_QUOTED_SUBSTITUTION = re.compile(
    r"\$\(\s*(?:(?:sudo|timeout\s+\S+|nice|env|command)\s+)*p(?:grep|kill)\b([^)]*)"
)
_FULL = re.compile(r"(?:^|\s)(?:-[a-zA-Z]*f[a-zA-Z]*|--full)(?:\s|$)")


@dataclass(frozen=True, slots=True)
class Call:
    """One `pgrep`/`pkill` in command position."""

    name: str
    full: bool
    exempt_flag: str | None
    lists_full: bool
    pattern: str | None
    #: The pattern's token as written, quotes included.
    raw: str


@dataclass(frozen=True, slots=True)
class Verdict:
    call: Call
    #: `deny`, `silent: <why>`.
    outcome: str
    where: str = ""


def read_call(name: str, arguments: Sequence[Token]) -> Call:
    full = lists_full = False
    exempt: str | None = None
    skip = False
    pattern: str | None = None
    raw = ""
    ended = False
    for token in arguments:
        if not token.is_word:
            break
        text = token.unquoted
        if skip:
            skip = False
            continue
        if not ended and text == "--":
            ended = True
            continue
        if not ended and text.startswith("--"):
            option = text.split("=", 1)[0]
            full |= option == "--full"
            lists_full |= option == "--list-full"
            if option in ("--exact", "--ignore-ancestors", "--inverse"):
                exempt = exempt or option
            skip = option in _LONG_WITH_ARG and "=" not in text
            continue
        if not ended and text.startswith("-") and len(text) > 1:
            if name == "pkill" and _SIGNAL.match(text):
                continue
            for index, letter in enumerate(text[1:]):
                if letter in _SHORT_WITH_ARG:
                    skip = index == len(text) - 2
                    break
                full |= letter == "f"
                lists_full |= letter == "a"
                if letter in "xAv":
                    exempt = exempt or f"-{letter}"
            continue
        pattern, raw = text, token.raw
        break
    return Call(name, full, exempt, lists_full, pattern, raw)


def judge(command: str) -> list[Verdict]:
    verdicts: list[Verdict] = []
    for pipeline in _pipelines(delimit(command.split("\n"))):
        for index, simple in enumerate(pipeline):
            for word in command_words(simple):
                at = word
                name = command_name(simple.tokens[at])
                if name == "!" and at + 1 < len(simple.tokens):
                    at += 1
                    name = command_name(simple.tokens[at])
                if name not in _PROCESS_WORDS:
                    continue
                call = read_call(name, simple.tokens[at + 1 :])
                verdicts.append(_verdict(call, command, pipeline, index))
    return verdicts


def _verdict(call: Call, command: str, pipeline: Pipeline, index: int) -> Verdict:
    silenced = _silenced(call)
    if silenced is not None or call.pattern is None:
        return Verdict(call, f"silent: {silenced}")
    try:
        found = re.search(call.pattern, command)
    except re.error:
        return Verdict(call, "silent: re.error")
    if found is None:
        return Verdict(call, "silent: no self-match")
    if call.name == "pgrep" and call.lists_full and _filtered(pipeline[index + 1 :], command):
        return Verdict(call, "silent: grep -v removes the shell's line")
    start = max(0, found.start() - 20)
    return Verdict(call, "deny", command[start : found.end() + 20])


def _silenced(call: Call) -> str | None:
    """Why the call is not judged on its pattern at all, or `None` when it is."""
    if not call.full:
        return "no -f"
    if call.exempt_flag is not None:
        return call.exempt_flag
    if call.pattern is None:
        return "no pattern"
    if not call.raw.startswith("'") and ("$" in call.raw or "`" in call.raw):
        return "pattern not literal"
    return None


def _filtered(rest: Sequence[SimpleCommand], command: str) -> bool:
    for simple in rest:
        for word in command_words(simple):
            if command_name(simple.tokens[word]) != "grep":
                continue
            grep = _read_grep(simple.tokens[word + 1 :])
            if not grep.invert or grep.from_file:
                continue
            flags = re.IGNORECASE if grep.ignore_case else 0
            for pattern in grep.patterns:
                if pattern is None:
                    continue
                try:
                    if re.search(_to_python(pattern, grep.dialect), command, flags):
                        return True
                except re.error:
                    continue
    return False


@dataclass(slots=True)
class _Grep:
    #: Each pattern's text, or `None` for one that is not literal (§9.2).
    patterns: list[str | None]
    invert: bool = False
    ignore_case: bool = False
    dialect: str = "basic"
    #: Patterns come from a file, which is not read, so this `grep` exempts nothing.
    from_file: bool = False


def _literal(token: Token) -> str | None:
    if not token.raw.startswith("'") and ("$" in token.raw or "`" in token.raw):
        return None
    return token.unquoted


#: `grep` options consuming an argument (§9.2): a pattern, a file of patterns, or anything else.
_GREP_PATTERN, _GREP_FILE, _GREP_SKIP = "e", "f", frozenset("ABCmdD")
_GREP_LONG_SKIP = frozenset(
    {
        "--max-count", "--context", "--after-context", "--before-context", "--include",
        "--exclude", "--exclude-dir", "--label", "--devices", "--directories", "--binary-files",
    }
)  # fmt: skip


def _read_grep(arguments: Sequence[Token]) -> _Grep:
    grep = _Grep([])
    pending: str | None = None
    pattern_option = False
    for token in arguments:
        if not token.is_word:
            break
        text = token.unquoted
        if pending is not None:
            if pending == _GREP_PATTERN:
                grep.patterns.append(_literal(token))
            pending = None
            continue
        if text.startswith("--"):
            grep.invert |= text == "--invert-match"
            grep.ignore_case |= text == "--ignore-case"
            if text.startswith("--regexp="):
                grep.patterns.append(text.split("=", 1)[1])
                pattern_option = True
            elif text == "--regexp":
                pending, pattern_option = _GREP_PATTERN, True
            elif text.startswith("--file"):
                grep.from_file = pattern_option = True
                if text == "--file":
                    pending = _GREP_FILE
            elif text in _GREP_LONG_SKIP:
                pending = "skip"
            continue
        if text.startswith("-") and len(text) > 1:
            pending, pattern_option = _read_grep_cluster(text[1:], grep, pattern_option)
            continue
        if not pattern_option:
            grep.patterns.append(_literal(token))
            pattern_option = True
    return grep


def _read_grep_cluster(letters: str, grep: _Grep, pattern_option: bool) -> tuple[str | None, bool]:
    """One `-xyz` cluster: what the next token is for, if anything, and whether a pattern option
    has now been seen."""
    for index, letter in enumerate(letters):
        rest = letters[index + 1 :]
        if letter == _GREP_PATTERN:
            if rest:
                grep.patterns.append(rest)
                return None, True
            return _GREP_PATTERN, True
        if letter == _GREP_FILE:
            grep.from_file = True
            return (None if rest else _GREP_FILE), True
        if letter in _GREP_SKIP:
            return (None if rest else letter), pattern_option
        grep.invert |= letter == "v"
        grep.ignore_case |= letter == "i"
        if letter in "EP":
            grep.dialect = "extended"
        elif letter == "F":
            grep.dialect = "fixed"
    return None, pattern_option


def _to_python(pattern: str, dialect: str) -> str:
    if dialect == "fixed":
        return re.escape(pattern)
    if dialect == "extended":
        return pattern
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern) and pattern[index + 1] in "|(){}+?":
            out.append(pattern[index + 1])
            index += 2
            continue
        out.append("\\" + char if char in "|(){}+?" else char)
        index += 1
    return "".join(out)


def quoted_substitution(command: str) -> bool:
    """Whether a `pgrep -f`/`pkill -f` stands inside a double-quoted `$(…)`, which §9 does not
    read (§9.4)."""
    for unit in _units(delimit(command.split("\n"))):
        chars = annotate(unit)
        text = "".join(char.text for char in chars)
        for found in _QUOTED_SUBSTITUTION.finditer(text):
            first = chars[found.start()]
            if first.kind is Kind.STRING and first.quote == '"' and _FULL.search(found.group(1)):
                return True
    return False


def _units(unit: Unit) -> Iterator[Unit]:
    yield unit
    for body in unit.bodies:
        if body.unit is not None:
            yield from _units(body.unit)


def _pipelines(unit: Unit) -> Iterator[Pipeline]:
    yield from parse(annotate(unit))
    for body in unit.bodies:
        if body.unit is not None:
            yield from _pipelines(body.unit)
