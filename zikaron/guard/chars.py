"""The annotated character: every later stage of the find-replace rule reads one of these.

`design/edit-guards.md` §3.1 parses a command in four steps. After steps 1 to 3 each character of a
line outside a data heredoc body carries what the shell would make of it — code, inside a string,
a quote delimiter, comment, or a line join — and step 4 tokenises that stream. Keeping the reading
on the character, rather than re-deriving it per stage, is what keeps every stage agreeing about
where a string ends.

For `echo "a b" # c`, the kinds are::

    echo "a b" # c
    CCCCCQSSSQCMMM      C code, Q quote, S string, M comment
"""

import enum
from dataclasses import dataclass


class Kind(enum.Enum):
    """What the shell makes of one character (§3.1 steps 2 and 3)."""

    CODE = "code"
    #: Inside a quoted string, one-line or multi-line.
    STRING = "string"
    #: The `'` or `"` that opens or closes a string.
    QUOTE = "quote"
    #: From the line's unquoted `#` to its end.
    COMMENT = "comment"
    #: A line continuation's backslash or newline: it separates tokens and nothing else.
    JOIN = "join"


@dataclass(frozen=True, slots=True)
class Heredoc:
    """The body a `<<` opens.

    `script` is the body's text with its comments removed when something executes it (a scanned
    body, row 4's), and `None` when the body is data. `text` is the body's lines as written, data
    or not — what a row-5 `cat` or `tee` writes to a file, and so what row 6 reads when that file
    is run.
    """

    script: str | None
    text: str = ""


@dataclass(frozen=True, slots=True)
class Char:
    """One character and its reading."""

    text: str
    kind: Kind
    #: The quote enclosing a `STRING` or delimited by a `QUOTE`; empty otherwise.
    quote: str = ""
    #: Set on the first `<` of a `<<` that opens a heredoc body.
    heredoc: Heredoc | None = None

    def is_code(self, text: str) -> bool:
        """Whether this is the unquoted, uncommented character `text`."""
        return self.kind is Kind.CODE and self.text == text
