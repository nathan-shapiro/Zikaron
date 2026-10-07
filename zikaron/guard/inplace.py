"""Rows 1 to 3 of `design/edit-guards.md` §3.2 — in-place editors — and their targets (§3.3).

| Row | Command word | Matches on a token |
|---|---|---|
| 1 | `sed`, `gsed` | `--in-place[=…]`, or `-<c>*[iI]…` with every `<c>` in `nrEsuz` |
| 2 | `perl` | `-<c>*i…` with every `<c>` in `pnlaws`, or `0` and its octal digits |
| 2 | `ruby` | `-<c>*i…` with every `<c>` in `pnlaw` |
| 3 | `awk`, `gawk` | `-i inplace`, `-iinplace`, `--include=inplace`, `--include inplace` |

**The targets** are the words after the command word that are not flags, not redirect tokens and
not a flag's argument — minus the first, which is the script, unless a script-carrying flag
(`-e`, `-f`, their long forms, perl's `-E`) supplied it.

>>> from zikaron.guard.chars import Char, Kind
>>> from zikaron.guard.grammar import parse
>>> def targets(family: Family, command: str) -> list[str]:
...     (pipeline,) = parse([Char(c, Kind.CODE) for c in command])
...     return in_place_targets(family, pipeline[0].tokens[1:])
>>> targets(Family.SED, "sed -i s/a/b/ /tmp/x")
['/tmp/x']
>>> targets(Family.SED, "sed -i '' -e s/a/b/ -e s/c/d/ f g 2> log")
['f', 'g']
>>> targets(Family.PERL, "perl -0777pi -e s/a/b/ f")
['f']
"""

import enum
import re
from collections.abc import Sequence
from typing import Final

from zikaron.guard.grammar import Token
from zikaron.guard.redirects import find_redirects


class Family(enum.Enum):
    """Whose flag grammar an in-place editor's command word follows."""

    SED = "sed"
    PERL = "perl"
    RUBY = "ruby"
    AWK = "awk"


_SED: Final = re.compile(r"-[nrEsuz]*[iI]")
_PERL: Final = re.compile(r"-(?:[pnlaws]|0[0-7]*+)*+i")
_RUBY: Final = re.compile(r"-[pnlaw]*i")
#: An in-place token carrying no suffix, after which BSD sed's empty suffix argument may follow.
_BARE_IN_PLACE: Final = re.compile(r"-[nrEsuz]*[iI]|-(?:[pnlaws]|0[0-7]*+)*+i")
_EMPTY_QUOTED: Final = frozenset({"''", '""'})

#: The flags that take a separate argument without supplying the script, per family.
_ARGUMENT_FLAGS: Final[dict[Family, frozenset[str]]] = {
    Family.AWK: frozenset({"-i", "--include", "-v", "-F"}),
    Family.SED: frozenset({"-l", "--line-length"}),
    Family.PERL: frozenset({"-I", "-M"}),
    Family.RUBY: frozenset({"-I", "-r"}),
}


def family_of(name: str) -> Family | None:
    """The in-place editor family a command name belongs to, or `None`.

    >>> [family_of(n) for n in ("gsed", "perl", "gawk", "sedx")]
    [<Family.SED: 'sed'>, <Family.PERL: 'perl'>, <Family.AWK: 'awk'>, None]
    """
    if re.fullmatch(r"g?sed", name):
        return Family.SED
    if re.fullmatch(r"g?awk", name):
        return Family.AWK
    return {"perl": Family.PERL, "ruby": Family.RUBY}.get(name)


def edits_in_place(family: Family, arguments: Sequence[Token]) -> bool:
    """Whether the arguments after a family's command word carry its in-place flag."""
    words = [token.unquoted for token in arguments]
    if family is Family.AWK:
        return any(
            word in ("-iinplace", "--include=inplace")
            or (word in ("-i", "--include") and words[index + 1 : index + 2] == ["inplace"])
            for index, word in enumerate(words)
        )
    return any(_is_in_place_flag(family, word) for word in words)


def _is_in_place_flag(family: Family, word: str) -> bool:
    if family is Family.SED:
        return bool(_SED.match(word)) or word == "--in-place" or word.startswith("--in-place=")
    if family is Family.PERL:
        return bool(_PERL.match(word))
    if family is Family.RUBY:
        return bool(_RUBY.match(word))
    return False


def in_place_targets(family: Family, arguments: Sequence[Token]) -> list[str]:
    """The targets among the arguments after the command word, as written."""
    redirect = find_redirects(arguments).tokens
    candidates: list[str] = []
    script_given = False
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if index in redirect or not token.is_word:
            index += 1
        elif token.starts_unquoted and token.unquoted.startswith("-"):
            consumed, carries_script = _flag(family, token.unquoted, arguments[index + 1 :])
            script_given = script_given or carries_script
            index += 1 + consumed
        else:
            candidates.append(token.raw)
            index += 1
    return candidates if script_given else candidates[1:]


def _flag(family: Family, flag: str, rest: Sequence[Token]) -> tuple[int, bool]:
    """How many following words a flag consumes, and whether it supplies the script.

    >>> _flag(Family.SED, "-ne", ()), _flag(Family.SED, "-E", ()), _flag(Family.PERL, "-E", ())
    ((1, True), (0, False), (1, True))
    >>> _flag(Family.SED, "-e's/a/b/'", ()), _flag(Family.SED, "--file=s.sed", ())
    ((0, True), (0, True))
    """
    if _is_in_place_flag(family, flag):
        suffix_follows = bool(_BARE_IN_PLACE.fullmatch(flag)) and bool(rest)
        return (1 if suffix_follows and rest[0].raw in _EMPTY_QUOTED else 0), False
    letters = "efE" if family is Family.PERL else "ef"
    if flag in ("--expression", "--file"):
        return 1, True
    if flag.startswith(("--expression=", "--file=")):
        return 0, True
    if re.match(rf"-[{letters}].", flag, re.DOTALL):
        return 0, True
    if re.fullmatch(rf"-[A-Za-z0-9]*[{letters}]", flag):
        return 1, True
    return (1 if flag in _ARGUMENT_FLAGS[family] else 0), False
