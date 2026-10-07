"""Row 4's write calls, and each one's target, in a script as the interpreter sees it.

`design/edit-guards.md` §3.2 "Row 4's write calls" lists the patterns; §3.3 "Row 4" says which
expression of each is its target, how names are bound, and how a target is judged
(`zikaron.guard.expression`). Each pattern allows `\\?` before a quote, so an escaped `\\"w\\"` is
seen.

| Write call | Its target |
|---|---|
| `open(…, 'w')` — a write mode after a comma, module prefix or not | the first argument |
| `<receiver>.open('w')` — a write mode first, receiver no path-first module | the receiver |
| `.write_text(`, `.write_bytes(` | the receiver |
| node's `writeFile(`, `appendFile(`, their `Sync`s, `createWriteStream(` | the first argument |
| `fileinput.input(…, inplace=True)` and `FileInput(…)` | the first argument |

>>> write_targets("print(open('x').read())") is None
True
>>> write_targets("p = Path('CLAUDE.md'); q = p; q.write_text(s); open('/tmp/x', 'w')")
[Named(path='CLAUDE.md'), Named(path='/tmp/x')]
>>> write_targets("with tempfile.TemporaryDirectory() as d: open(f'{d}/x', 'w')")
[Scratch()]
>>> write_targets("open(sys.argv[1], 'w')")
[None]
"""

import enum
import re
from typing import Final, NamedTuple

from zikaron.guard.expression import Judge, Judged, Scratch, Source, is_scratch_call

_QUOTE: Final = r"\\?['\"]"
_MODE: Final = r"(w|a|x|r[bt]?\+)[bt+]*(?:[:|]\w+)?"
_NAME: Final = r"[A-Za-z_]\w*"


class TargetIs(enum.Enum):
    """Which expression of a write call is its target."""

    FIRST_ARGUMENT = "first argument"
    RECEIVER = "receiver"


class Shape(enum.Enum):
    """How a pattern's match locates its call's `(` and its target expression."""

    #: A bare `open(`, matched from its `o`.
    OPEN = "open"
    #: A function whose first argument is a path, matched from its name.
    FUNCTION = "function"
    #: A receiver's mode-first `.open(`, matched from the receiver.
    RECEIVER_OPEN = "receiver open"
    #: A path method, matched from its `.`.
    METHOD = "method"

    @property
    def target(self) -> TargetIs:
        if self in (Shape.OPEN, Shape.FUNCTION):
            return TargetIs.FIRST_ARGUMENT
        return TargetIs.RECEIVER


class WritePattern(NamedTuple):
    pattern: re.Pattern[str]
    shape: Shape


WRITE_PATTERNS: Final = (
    WritePattern(
        re.compile(
            r"(?<!\w)open\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*,\s*(?:mode\s*=\s*)?"
            + _QUOTE
            + _MODE
            + _QUOTE
        ),
        Shape.OPEN,
    ),
    WritePattern(
        re.compile(r"(?:(?<![\w.])\w+|\))\.open\(\s*(?:mode\s*=\s*)?" + _QUOTE + _MODE + _QUOTE),
        Shape.RECEIVER_OPEN,
    ),
    WritePattern(re.compile(r"\.write_text\("), Shape.METHOD),
    WritePattern(re.compile(r"\.write_bytes\("), Shape.METHOD),
    WritePattern(
        re.compile(r"(?:write|append)File(?:Sync)?\(|createWriteStream\("), Shape.FUNCTION
    ),
    WritePattern(
        re.compile(
            r"(?:fileinput\.)?(?:input|FileInput)\((?:[^()]|\([^()]*\))*inplace\s*=\s*(?:True|1)\b"
        ),
        Shape.FUNCTION,
    ),
)

#: Receiver words whose `open(` takes a path first, so a mode-first `.open(` on them is a read of
#: a file named like a mode — `io.open('w')`.
PATH_FIRST_MODULES: Final = frozenset(
    {"io", "codecs", "gzip", "bz2", "lzma", "tarfile", "wave", "aifc", "fsspec", "smart_open", "fs"}
)

_BINDING: Final = re.compile(rf"\s*(?:(?:const|let|var)\s+)?({_NAME})\s*(?::[^=]*)?=(?!=)\s*")
_WITH: Final = re.compile(r"\s*with\s+")
_WITH_ITEM: Final = re.compile(rf"(.*)\s+as\s+({_NAME})\s*$", re.DOTALL)


class WriteCall(NamedTuple):
    """A write call: which expression is its target, and where — the call's `(` for a first
    argument, the method's `.` for a receiver."""

    target: TargetIs
    anchor: int


def find_write_calls(text: str) -> dict[int, WriteCall]:
    """Every write call in `text`, keyed by the position of its `(`. Where two patterns find the
    same call, the first in `WRITE_PATTERNS` wins."""
    calls: dict[int, WriteCall] = {}
    for pattern, shape in WRITE_PATTERNS:
        for match in pattern.finditer(text):
            found = _locate(text, match, shape)
            if found is not None:
                calls.setdefault(*found)
    return calls


def _locate(text: str, match: re.Match[str], shape: Shape) -> tuple[int, WriteCall] | None:
    """The call's `(` and its `WriteCall`, or `None` for a receiver `.open(` on a path-first
    module."""
    if shape is Shape.OPEN:
        paren = match.start() + len("open")
        return paren, WriteCall(shape.target, paren)
    if shape is Shape.METHOD:
        return match.end() - 1, WriteCall(shape.target, match.start())
    if shape is Shape.RECEIVER_OPEN:
        receiver = re.match(r"(\w+)\.open", match.group(0))
        if receiver is not None and receiver.group(1) in PATH_FIRST_MODULES:
            return None
        dot = text.index(".open(", match.start())
        return dot + len(".open"), WriteCall(shape.target, dot)
    paren = text.index("(", match.start())
    return paren, WriteCall(shape.target, paren)


def write_targets(script: str) -> list[Judged | None] | None:
    """Each write call's target in `script`, in order — `None` for a target expression that
    yields nothing — or `None` when the script has no write call at all."""
    calls = find_write_calls(script)
    if not calls:
        return None
    judge = Judge(Source(script))
    targets: list[Judged | None] = []
    for start, end in _statements(judge.source):
        _bind_with(judge, start, end)
        for paren in sorted(paren for paren in calls if start <= paren < end):
            call = calls[paren]
            if call.target is TargetIs.FIRST_ARGUMENT:
                targets.append(judge.first_argument(call.anchor))
            else:
                targets.append(judge.receiver(call.anchor))
        _bind_assignment(judge, start, end)
    return targets


def _statements(source: Source) -> list[tuple[int, int]]:
    """A statement runs to a `;` or newline outside string literals and unclosed brackets."""
    statements: list[tuple[int, int]] = []
    start = 0
    depth = 0
    for index, character in enumerate(source.masked):
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth = max(0, depth - 1)
        elif character in ";\n" and depth == 0:
            statements.append((start, index))
            start = index + 1
    statements.append((start, len(source.masked)))
    return statements


def _bind_assignment(judge: Judge, start: int, end: int) -> None:
    """`name = <expr>` — after an optional `const`/`let`/`var`, with an optional `: type` — binds
    `name` to what `<expr>` yields; a later binding of the same name replaces the earlier."""
    binding = _BINDING.match(judge.source.text[start:end])
    if binding is None:
        return
    value = judge.target(start + binding.end(), end)
    if value is None:
        judge.bindings.pop(binding.group(1), None)
    else:
        judge.bindings[binding.group(1)] = value


def _bind_with(judge: Judge, start: int, end: int) -> None:
    """`with <expr> as name` binds `name` as scratch where `<expr>`'s head is a scratch call, and
    unbinds it otherwise — so `with open('CLAUDE.md') as src` never makes `src` a target. The items
    may be enclosed in `(…)` and span lines."""
    source = judge.source
    opener = _WITH.match(source.masked[start:end])
    if opener is None:
        return
    for item_start, item_end in _with_items(source, start + opener.end(), end):
        item = _WITH_ITEM.match(source.text[item_start:item_end])
        if item is None:
            continue
        head_start, head_end = source.trim(item_start, item_start + item.end(1))
        operand = source.text[head_start : source.operand_end(head_start, head_end)]
        if is_scratch_call(operand):
            judge.bindings[item.group(2)] = Scratch()
        else:
            judge.bindings.pop(item.group(2), None)


def _with_items(source: Source, start: int, statement_end: int) -> list[tuple[int, int]]:
    """The `(start, end)` of each item of a `with` beginning at `start`."""
    end = statement_end
    if source.masked[start : start + 1] == "(":
        close = source.close_of(start)
        if close is not None and re.match(r"\s*:", source.masked[close + 1 : statement_end]):
            start, end = start + 1, close
    items: list[tuple[int, int]] = []
    depth = 0
    for index in range(start, end):
        character = source.masked[index]
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif depth == 0 and character in ",:":
            items.append((start, index))
            start = index + 1
            if character == ":":
                break
    if end != statement_end:
        items.append((start, end))
    return items
