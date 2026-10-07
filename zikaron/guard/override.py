"""The override: `#ZIKARON-FORCE #Reason: <at least two words>` (`design/edit-guards.md` §3.4).

It is examined only after a form matched with a target that is not scratch. It lives in a shell
**comment** on a line of the command that is not a heredoc body, matched against that comment —
so a marker inside a body or a quoted string is content, never an override. The reason is invalid
when fewer than two words remain after every `<…>` span is removed.

| The command's comment, or where its marker is | State |
|---|---|
| `#ZIKARON-FORCE #Reason: regenerate golden` · `… #Reason: fix <12> now` | valid |
| `#ZIKARON-FORCE` · `… #Reason: golden` · `… #Reason: <few words>` · `f#ZIKARON-FORCE` | invalid |
| the marker only inside a heredoc body or a quoted string | absent, marker in content |

>>> from zikaron.guard.heredoc import delimit
>>> from zikaron.guard.lexer import annotate
>>> def state(command: str) -> Override:
...     return read_override(annotate(delimit(command.split("\\n"))), command)
>>> state("sed -i x f #ZIKARON-FORCE #Reason: 'golden file'")
Override(state=<State.VALID: 'valid'>, reason="'golden file'", marker_in_content=False)
>>> state("sed -i x f#ZIKARON-FORCE #Reason: a b").state
<State.INVALID: 'invalid'>
>>> state("echo 'x #ZIKARON-FORCE #Reason: two words' >> f")
Override(state=<State.ABSENT: 'absent'>, reason=None, marker_in_content=True)
"""

import enum
import re
from collections.abc import Sequence
from typing import Final, NamedTuple

from zikaron.guard.chars import Char, Kind

MARKER: Final = "#ZIKARON-FORCE"
_REASON_LABEL: Final = "#Reason:"
_OVERRIDE: Final = re.compile(r"(^|\s)#ZIKARON-FORCE[ \t]+#Reason:[ \t]*\S+[ \t]+\S+")
_PLACEHOLDER: Final = re.compile(r"<[^>]*>")
#: The fewest words a reason may have once its `<…>` spans are removed.
_REASON_WORDS: Final = 2


class State(enum.Enum):
    VALID = "valid"
    #: The marker stands outside every body and string, and no comment carries a valid override.
    INVALID = "invalid"
    ABSENT = "absent"


class Override(NamedTuple):
    state: State
    #: A valid override's reason: the text after `#Reason:` to the end of its line, trimmed.
    reason: str | None
    #: Whether, absent an override, the marker appeared inside a heredoc body or a quoted string.
    marker_in_content: bool


def read_override(chars: Sequence[Char], command: str) -> Override:
    """The override state of `command`, from the annotated stream of its own lines."""
    for comment in _comments(chars):
        for match in _OVERRIDE.finditer(comment):
            reason = comment[comment.index(_REASON_LABEL, match.start()) + len(_REASON_LABEL) :]
            if len(_PLACEHOLDER.sub(" ", reason).split()) >= _REASON_WORDS:
                return Override(State.VALID, reason.strip(), marker_in_content=False)
    outside_strings = "".join(
        "\0" if char.kind in (Kind.STRING, Kind.QUOTE) else char.text for char in chars
    )
    if MARKER in outside_strings:
        return Override(State.INVALID, None, marker_in_content=False)
    return Override(State.ABSENT, None, marker_in_content=MARKER in command)


def _comments(chars: Sequence[Char]) -> list[str]:
    """Each line's comment text."""
    comments: list[str] = []
    current: list[str] = []
    for char in chars:
        if char.kind is Kind.COMMENT:
            current.append(char.text)
        elif char.text == "\n":
            if current:
                comments.append("".join(current))
            current = []
    if current:
        comments.append("".join(current))
    return comments
