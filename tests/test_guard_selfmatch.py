"""The self-match rule's data against `design/guards.md` §9.1 and §9.2, and its option grammar.

§9.1's platform table, its signal list and §9.2's `grep` options are each stated once in the
design and once as data in `zikaron.guard`; the first tests hold the two equal. The rest judge
commands directly, one property of §9.1 or §9.2 each, which its name states.
"""

import re
import warnings
from typing import Final

import pytest

from tests.design_tables import section_lines, table_with_columns
from tests.guard_table import DOCUMENT
from zikaron.guard.grep_filter import DIALECTS, LONG_SKIPPED, SKIPPED, Dialect
from zikaron.guard.heredoc import delimit
from zikaron.guard.selfmatch import GRAMMARS, SIGNAL_NAMES, Platform, SelfMatch, first_self_match

WHAT_IS_JUDGED: Final = "### 9.1 What is judged"
THE_DECISION: Final = "### 9.2 The decision"
_SPAN: Final = re.compile(r"`([^`]+)`")


def _judge(command: str, platform: str = "linux") -> SelfMatch | None:
    return first_self_match(delimit(command.split("\n")), command, platform)


def _text(heading: str) -> str:
    """A section's prose with its line breaks and indentation collapsed to single spaces."""
    return re.sub(r"\s+", " ", " ".join(section_lines(DOCUMENT, heading)))


def _options(cell: str) -> tuple[set[str], set[str]]:
    """The short option letters and the long options a cell's backticked spans name."""
    words = [word for span in _SPAN.findall(cell) for word in span.split()]
    return (
        {word[1:] for word in words if re.fullmatch(r"-[A-Za-z]", word)},
        {word for word in words if word.startswith("--")},
    )


PLATFORM_ROWS = table_with_columns(
    DOCUMENT,
    WHAT_IS_JUDGED,
    ("`sys.platform`", "The rule applies when", "Never when", "Options taking an argument"),
)


def _row(platform: Platform) -> dict[str, str]:
    (row,) = [
        row for row in PLATFORM_ROWS if row["`sys.platform`"].startswith(f"`{platform.value}`")
    ]
    return row


@pytest.mark.parametrize("platform", list(Platform), ids=lambda p: p.value)
def test_each_platforms_grammar_is_its_row_of_the_table(platform: Platform) -> None:
    grammar, row = GRAMMARS[platform], _row(platform)
    for column, letters in (
        ("The rule applies when", grammar.applies),
        ("Never when", grammar.never),
    ):
        short, long = _options(row[column])
        assert short == letters, column
        assert long == {name for name, letter in grammar.long_names.items() if letter in letters}
    short, long = _options(row["Options taking an argument"])
    assert short == grammar.with_argument
    assert long == grammar.long_with_argument


def test_every_other_platform_is_the_tables_last_row_and_is_silent() -> None:
    assert len(PLATFORM_ROWS) == len(Platform) + 1
    last = PLATFORM_ROWS[-1]
    assert (last["`sys.platform`"], last["The rule applies when"]) == ("anything else", "never")
    for other in ("win32", "cygwin", "freebsd14", "linux2", ""):
        assert _judge("pkill -f month_monitor.py", other) is None


def test_each_long_option_outside_the_table_is_paired_with_its_letter_in_section_9() -> None:
    text = _text(WHAT_IS_JUDGED) + _text(THE_DECISION)
    for platform in Platform:
        grammar = GRAMMARS[platform]
        for name, letter in grammar.long_names.items():
            if letter not in grammar.applies | grammar.never:
                assert f"`-{letter}`/`{name}`" in text


def test_the_signal_names_are_the_designs_list() -> None:
    text = _text(WHAT_IS_JUDGED)
    (listed,) = [span for span in _SPAN.findall(text) if span.startswith("HUP ")]
    assert tuple(listed.split()) == SIGNAL_NAMES
    assert "`RTMIN+<n>`/`RTMAX-<n>`" in text


def test_the_grep_options_are_the_designs() -> None:
    text = _text(THE_DECISION)
    spans = _SPAN.findall(text)
    (short,) = [span for span in spans if span.startswith("-A ")]
    (long,) = [span for span in spans if span.startswith("--max-count ")]
    assert set(short.replace("-", "").split()) == SKIPPED
    assert set(long.split()) == LONG_SKIPPED
    assert "unless `-E` or `-P` (read as `-E`) or `-F` says otherwise" in text
    assert DIALECTS == {"E": Dialect.EXTENDED, "P": Dialect.EXTENDED, "F": Dialect.FIXED}


#: Each platform's options that make the rule apply, as one leading cluster.
APPLIES: Final = {Platform.LINUX: "-f", Platform.DARWIN: "-af"}


def _option_cases() -> list[tuple[Platform, str, bool]]:
    """(platform, option letter, takes an argument) for every ASCII letter not in `never`."""
    return [
        (platform, letter, letter in GRAMMARS[platform].with_argument)
        for platform in Platform
        for letter in sorted(set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        if letter not in GRAMMARS[platform].never
    ]


@pytest.mark.parametrize(
    ("platform", "letter", "takes_argument"),
    _option_cases(),
    ids=lambda value: value.value if isinstance(value, Platform) else str(value),
)
def test_an_option_consumes_an_argument_exactly_when_the_table_says(
    platform: Platform, letter: str, takes_argument: bool
) -> None:
    """Alone and as the last of a cluster: an option that takes an argument consumes
    `month_monitor.py`, leaving a pattern that matches nothing; any other leaves it the pattern.
    With an argument attached (`-dzzz`), the option consumes no further token, so
    `month_monitor.py` stays the pattern whatever the letter, `z` taking none on either platform.
    """
    applies = APPLIES[platform]
    alone = f"pgrep {applies} -{letter} month_monitor.py '[z]zz'"
    clustered = f"pgrep {applies}{letter} month_monitor.py '[z]zz'"
    for command in (alone, clustered):
        assert (_judge(command, platform.value) is None) is takes_argument, command
    attached = f"pgrep {applies} -{letter}zzz month_monitor.py"
    assert _judge(attached, platform.value) is not None, attached


@pytest.mark.parametrize("name", sorted(GRAMMARS[Platform.LINUX].long_with_argument))
def test_a_long_option_consumes_its_argument_unless_written_with_a_value(name: str) -> None:
    assert _judge(f"pgrep -f {name} month_monitor.py '[z]zz'") is None
    assert _judge(f"pgrep -f {name}=x month_monitor.py") is not None


@pytest.mark.parametrize(
    "letter",
    sorted({letter for grammar in GRAMMARS.values() for letter in grammar.never | grammar.applies}),
)
def test_no_option_letter_is_read_as_a_signal(letter: str) -> None:
    """`pkill -A -f …` is `-A`, an option; were it read as a signal, the call would deny."""
    for platform in Platform:
        never = letter in GRAMMARS[platform].never
        command = f"pkill -{letter} {APPLIES[platform]} month_monitor.py"
        assert (_judge(command, platform.value) is None) is never, command


@pytest.mark.parametrize("name", SIGNAL_NAMES)
def test_each_signal_is_one_token_in_any_case_with_or_without_sig(name: str) -> None:
    for spelling in (name, name.lower(), f"SIG{name}", f"sig{name.lower()}"):
        assert _judge(f"pkill -{spelling} -f month_monitor.py") is not None, spelling
        assert _judge(f"pkill -f -{spelling} month_monitor.py") is not None, spelling


@pytest.mark.parametrize("signal", ["-9", "-15", "-RTMIN+3", "-rtmax-2"])
def test_a_numbered_signal_is_one_token(signal: str) -> None:
    assert _judge(f"pkill {signal} -f month_monitor.py") is not None


def test_a_signal_is_read_only_for_pkill() -> None:
    """`pgrep -int` is `-i -n -t`, and `-t` consumes the pattern."""
    assert _judge("pgrep -f -int month_monitor.py") is None
    assert _judge("pkill -f -int month_monitor.py") is not None


@pytest.mark.parametrize(
    "command",
    [
        "pgrep -f -- -month_monitor.py",
        "pgrep -f -",
        "pgrep --list-name -f month_monitor.py",
        "! ! pgrep -f month_monitor.py",
        "! sudo -u nathan pkill -f month_monitor.py",
        "pgrep -f 'MONTH_MONITOR' # month_monitor",
    ],
)
def test_a_call_the_rule_reads_through_denies(command: str) -> None:
    assert _judge(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "pgrep -f",
        "pgrep -f >(cat)",
        "!",
        "! ;",
        "pgrep -f '[M]ONTH_MONITOR' # month_monitor, without -i",
    ],
)
def test_a_call_with_nothing_to_match_is_silent(command: str) -> None:
    assert _judge(command) is None


def test_ignore_case_reads_both_spellings() -> None:
    assert _judge("pgrep --ignore-case -f '[M]ONTH' && echo month") is not None
    assert _judge("pgrep -if '[M]ONTH' && echo month") is not None


def test_a_bound_variable_is_read_as_the_last_value_bound_before_the_call() -> None:
    """The excerpt then shows the assignment, where the value occurs in the command's text."""
    found = _judge('P=$1; P=month_monitor.py; pkill -f "$P"')
    assert found is not None
    assert found.excerpt.startswith("P=$1; P=month_monitor.py")
    assert _judge('pkill -f "$P"; P=month_monitor.py') is None
    assert _judge('P=month_monitor.py; P="$1"; pkill -f "$P"') is None


@pytest.mark.parametrize("token", ['"$P"x', '"$P', "'$P'", "\\$P", '"${P}.py"', "$P$P", "${P"])
def test_only_a_token_that_is_one_variable_is_read_as_its_value(token: str) -> None:
    assert _judge(f"P=month_monitor.py; pkill -f {token}") is None


def test_the_excerpt_is_the_match_with_its_own_line_around_it() -> None:
    command = "cd /srv\nfor p in $(pgrep -f month_monitor.py); do\n  kill $p\ndone"
    found = _judge(command)
    assert found is not None
    assert found.excerpt == "for p in $(pgrep -f month_monitor.py); do"
    long_line = "sleep 1; " * 5 + "pkill -f month_monitor.py; echo " + "y" * 40
    found = _judge(long_line)
    assert found is not None
    start = long_line.index("month_monitor.py")
    assert found.excerpt == long_line[start - 20 : start + len("month_monitor.py") + 20]


def test_a_scanned_body_is_judged_and_reported_from_its_own_line() -> None:
    found = _judge("bash <<'EOF'\necho start\npkill -f month_monitor.py\nEOF")
    assert found is not None
    assert found.excerpt == "pkill -f month_monitor.py"


@pytest.mark.parametrize(
    "grep",
    [
        "grep -v grep",
        "grep -v 'pgrep\\|grep'",
        "grep -vE 'pgrep|grep'",
        "grep -vP 'pgrep|grep'",
        "grep -vF pgrep",
        "grep -vF 'pgrep|'",
        "grep -vi GREP",
        "grep --ignore-case --invert-match GREP",
        "grep -v -e '[z]zz' -e pgrep",
        "grep -v -epgrep",
        "grep -v --regexp pgrep",
        "grep -v --regexp=pgrep",
        "grep -v -m 1 grep",
        "grep -v -m1 grep",
        "grep -v --max-count 1 grep",
        "grep -v --max-count=1 grep",
        "grep -v --color=auto grep",
        "grep -v 'a\\\\b\\|grep'",
        "grep -v 'grep('",
        "grep -vF 'x$y'",
        "grep -v $X grep -e grep",
    ],
)
def test_a_grep_v_whose_pattern_searches_the_command_exempts_on_linux_only(grep: str) -> None:
    command = f"pgrep -af month_monitor.py | {grep}"
    assert _judge(command) is None, command
    assert _judge(f"pgrep -f month_monitor.py | {grep}") is not None
    assert _judge(command.replace("pgrep -af", "pgrep -laf"), "darwin") is not None


@pytest.mark.parametrize(
    "grep",
    [
        "grep -v $$",
        "grep -v -e $$",
        "grep -v -e$$",
        "grep -v --regexp=$$",
        'grep -v "$PAT"',
        "grep -v -f /tmp/pats",
        "grep -v -f/tmp/pats grep",
        "grep -v --file /tmp/pats",
        "grep -v --file=/tmp/pats grep",
        "grep -v -e grep -f /tmp/pats",
        "grep -c pytest",
        "grep -v '[z]zz'",
        "grep -vE 'pgrep('",
        "grep -v 'grep\\'",
        "grep -v -e '[z]zz' grep",
        "grep -v <(echo grep)",
        "grep -v $(\nprintf grep\n)",
        "grep -v 2>/dev/null '[z]zz'",
        "grep -v grep -e '[z]zz'",
        "grep -v",
    ],
)
def test_a_grep_that_does_not_drop_the_shells_line_exempts_nothing(grep: str) -> None:
    command = f"pgrep -af month_monitor.py | {grep}"
    assert _judge(command) is not None, command


def test_the_exemption_needs_pgrep_not_pkill() -> None:
    assert _judge("pkill -af month_monitor.py | grep -v grep") is not None


def test_a_pattern_re_cannot_compile_is_silent_and_a_posix_class_compiles() -> None:
    """`re` reads `[[:alpha:]]` as the class `[[:alpha:]` followed by a `]`, which matches the `:]`
    of its own spelling — §9.4's stated false deny, compiled with its warning ignored."""
    assert _judge("pgrep -f '('") is None
    assert _judge("pgrep -f '[[:alpha:]]'") is not None


def test_a_warning_while_compiling_changes_no_decision() -> None:
    """Under a filter that makes every warning an error, the POSIX class `re` warns about decides
    as it does without one, in `pgrep`'s pattern and in `grep`'s."""
    commands = ("pgrep -f '[[:alpha:]]'", "pgrep -af m | grep -v '[[:alpha:]]grep\\|pgrep'")
    expected = [_judge(command) for command in commands]
    re.purge()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert [_judge(command) for command in commands] == expected
