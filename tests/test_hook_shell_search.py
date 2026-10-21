"""Which paths a shell command's searches covered (`design/code-knowledge.md` §6)."""

from pathlib import Path

import pytest

from zikaron.hook.shell_search import searched_paths

CWD = "/work/project/sub"
TOP = "/work/project"
HOME = str(Path("~").expanduser())


def _paths(command: str) -> tuple[str, ...]:
    return searched_paths(command, cwd=CWD, top=TOP)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("grep -rn needle src", (f"{CWD}/src",)),
        ("grep -rn needle", (CWD,)),
        ("grep -R needle", (CWD,)),
        ("grep --recursive needle", (CWD,)),
        ("grep --dereference-recursive needle", (CWD,)),
        ("grep needle a.py b.py", (f"{CWD}/a.py", f"{CWD}/b.py")),
        ("grep -e needle src", (f"{CWD}/src",)),
        ("grep -e needle -e hay src lib", (f"{CWD}/src", f"{CWD}/lib")),
        ("grep -f patterns.txt src", (f"{CWD}/src",)),
        ("grep -A 3 needle src", (f"{CWD}/src",)),
        ("grep --include '*.rs' -rn needle src", (f"{CWD}/src",)),
        ("grep --include=*.rs -rn needle src", (f"{CWD}/src",)),
        ("grep -rn -- -needle src", (f"{CWD}/src",)),
        ("grep -e x -- -weird", (f"{CWD}/-weird",)),
        ("grep -rn needle /abs/elsewhere", ("/abs/elsewhere",)),
        ("grep -rn needle ../up", ("/work/project/up",)),
        ("grep -rn needle ~/notes", (f"{HOME}/notes",)),
        ("grep -rn needle 'src/*.py'", (f"{CWD}/src/*.py",)),
        ("egrep -rn needle .", (CWD,)),
        ("fgrep needle a b", (f"{CWD}/a", f"{CWD}/b")),
        ("/usr/bin/grep -rn needle src", (f"{CWD}/src",)),
        ("timeout 5 grep -rn needle src", (f"{CWD}/src",)),
        ("LC_ALL=C grep -rn needle src", (f"{CWD}/src",)),
    ],
)
def test_grep(command: str, expected: tuple[str, ...]) -> None:
    assert _paths(command) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rg needle", (CWD,)),
        ("rg needle src", (f"{CWD}/src",)),
        ("rg -g '*.rs' needle src", (f"{CWD}/src",)),
        ("rg -r REPLACED needle src", (f"{CWD}/src",)),
        ("rg --type rust needle src", (f"{CWD}/src",)),
        ("rg --type=rust needle", (CWD,)),
        ("rg -e needle src lib", (f"{CWD}/src", f"{CWD}/lib")),
        ("rg --files src", (f"{CWD}/src",)),
        ("rg --files -g '*.rs' src lib", (f"{CWD}/src", f"{CWD}/lib")),
        ("rg --files", (CWD,)),
        ("cd src && rg needle", (CWD,)),
        ("ls; rg needle", (CWD,)),
        ("rg -e needle", (CWD,)),
        ("rg -f patterns.txt", (CWD,)),
    ],
)
def test_ripgrep(command: str, expected: tuple[str, ...]) -> None:
    assert _paths(command) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git grep needle", (CWD,)),
        ("git grep -n needle src", (f"{CWD}/src",)),
        ("git grep -n needle -- src", (f"{CWD}/src",)),
        ("git -C lib grep needle", (f"{CWD}/lib",)),
        ("git -C lib grep needle src", (f"{CWD}/lib/src",)),
        ("git -c color.ui=never grep needle", (CWD,)),
        ("git --no-pager grep needle src", (f"{CWD}/src",)),
        ("git grep needle -- :/lib", (f"{TOP}/lib",)),
        ("git grep needle -- :/", (TOP,)),
        ("git grep needle -- ':!vendor'", (CWD,)),
        ("git grep --max-depth 2 needle src", (f"{CWD}/src",)),
        ("git grep needle HEAD main -- src", (f"{CWD}/src",)),
        ("git grep -e needle HEAD -- src lib", (f"{CWD}/src", f"{CWD}/lib")),
        ("git grep needle HEAD --", (CWD,)),
        ("git grep needle HEAD", (f"{CWD}/HEAD",)),
        ("git grep needle -- '*.py'", (CWD,)),
        ("git grep needle -- 'src/*.rs'", (f"{CWD}/src",)),
        ("git grep needle -- 'src/a/**/[ab].py'", (f"{CWD}/src/a",)),
        ("git grep needle -- ':/**/*.py'", (TOP,)),
        ("git grep -- -needle", (CWD,)),
        ("git grep -- -needle src", (f"{CWD}/src",)),
        ("git grep -n -- -needle HEAD -- src", (f"{CWD}/src",)),
    ],
)
def test_git_grep(command: str, expected: tuple[str, ...]) -> None:
    assert _paths(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "ls src",
        "grep needle",
        "git log --oneline | grep fix",
        "cat notes.txt | rg needle",
        "git log",
        "git -C lib status",
        "pgrep -f grep",
        "echo grep -rn needle src",
        "python3 -c 'print(1)'",
        "",
        "find src -exec grep -l needle {} +",
        "find src -exec grep -l needle {} ';'",
        "find src -exec grep -rl needle {} +",
        "find src | xargs -I{} grep needle {}",
        "find src -name '*.py' | xargs grep -rn needle",
        "grep -r needle -",
        "rg --version",
        "rg --help",
        "rg --type-list",
        "git grep --help",
        "grep -r --help",
    ],
    ids=[
        "no search",
        "a grep with neither path nor -r",
        "a pipe filter",
        "an rg after a pipe",
        "git without grep",
        "git -C without grep",
        "pgrep",
        "grep as an argument",
        "an interpreter",
        "empty",
        "find -exec with +",
        "find -exec with ;",
        "find -exec with a recursive grep",
        "xargs -I",
        "xargs with a recursive grep",
        "the input",
        "rg's version",
        "rg's usage",
        "rg's type list",
        "git grep's usage",
        "a recursive grep's usage",
    ],
)
def test_a_command_that_searches_nothing(command: str) -> None:
    assert _paths(command) == ()


def test_a_grep_after_a_heredoc_is_read() -> None:
    command = "cat <<'END' > /dev/null\nhello\nEND\ngrep -rn needle src"
    assert _paths(command) == (f"{CWD}/src",)


def test_a_cd_earlier_in_the_command_is_not_followed() -> None:
    assert _paths("cd src && grep -rn needle .") == (CWD,)


def test_every_search_in_a_compound_command_counts() -> None:
    assert _paths("grep -rn a src; rg b lib") == (f"{CWD}/src", f"{CWD}/lib")
