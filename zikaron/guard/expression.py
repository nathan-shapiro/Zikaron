"""Row 4's target expressions: what a write call in an inline script writes to.

`design/edit-guards.md` §3.3, "Row 4", is normative. Each write call has one **target
expression** — the first argument of `open(` and its kin, the receiver of `.write_text(` and its
kin — and **its head decides**. The head is the expression's first operand, before any
`.name`/`.name(…)` chain; the six steps are tried in order:

| Step | Head | Yields | Example → yields |
|---|---|---|---|
| 1 | a scratch call, on the whole operand | scratch | `tempfile.mkdtemp()` → scratch |
| 2 | a string literal | the literal | `'/tmp/x'` → `/tmp/x` |
| 3 | `Path('…')` and its `/ '…'` chain | the literals, joined | `Path('d') / 'x'` → `d/x` |
| 4 | a name | its binding | `out`, bound by `out = 'f'` → `f` |
| 5 | a path function: `str(`, `os.path.join(` … | its first argument | `str(Path('f'))` → `f` |
| 6 | a head with a chain after it | the head's, unless the chain reads | `p.parent` → `p`'s |

Anything else yields **nothing**, and a write whose target yields nothing is denied naming no
target. **Whatever leads governs**: `Path('research') / src.name` names `research` whatever `src`
holds.

>>> judge = Judge(Source(""), {"out": Named("research/x.md")})
>>> judge.target_of("Path('design') / 'x.md'"), judge.target_of("tempfile.mkdtemp()")
(Named(path='design/x.md'), Scratch())
>>> judge.target_of("out.with_suffix('.json')"), judge.target_of("out.stem")
(Named(path='research/x.md'), None)
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

_NAME: Final = r"[A-Za-z_]\w*"
_LINK: Final = re.compile(rf"\.({_NAME})")
_LITERAL_START: Final = re.compile(r"(?<![\w])([rRbBfFuU]{0,2})(['\"`])")
_SCRATCH_CALL: Final = re.compile(
    r"(?:\w+\.)*tempfile\."
    r"|(?:mkdtemp|mkstemp|mktemp|gettempdir|TemporaryFile|NamedTemporaryFile"
    r"|SpooledTemporaryFile|TemporaryDirectory)\("
    r"|(?:[\w.]*\.)?(?:environ\[\s*['\"]TMPDIR['\"]\s*\]"
    r"|environ\.get\(\s*['\"]TMPDIR['\"]|getenv\(\s*['\"]TMPDIR['\"])"
    r"|process\.env\.TMPDIR\b"
)
_NODE_TMPDIR: Final = re.compile(r"\btmpdir\(\)$")
_LEADING_SPAN: Final = re.compile(r"\$?\{([^}]*)\}")
_CALL_HEAD: Final = re.compile(rf"({_NAME}(?:\.{_NAME})*)\(")
_PATH_CONSTRUCTOR: Final = re.compile(r"(?:pathlib\.)?Path")
_WRITE_MODE_CALL: Final = re.compile(r"\(\s*(?:mode\s*=\s*)?['\"](w|a|x|r[bt]?\+)")

#: Step 5's path functions: their first argument is judged in their place.
PATH_FUNCTIONS: Final = frozenset(
    {
        "str",
        "Path",
        "pathlib.Path",
        "os.path.join",
        "os.path.abspath",
        "os.path.expanduser",
        "os.path.realpath",
        "os.path.dirname",
        "os.fspath",
        "path.join",
        "path.resolve",
    }
)
#: The path functions whose several leading literals join with `/`.
_JOINERS: Final = frozenset({"os.path.join", "path.join"})

#: Step 6: a chain containing one of these reads a file or takes a name component, so it yields
#: nothing — as does a `.open(` with no write mode.
CHAIN_STOPS: Final = frozenset(
    {
        "read_text",
        "read_bytes",
        "read",
        "readlines",
        "exists",
        "is_file",
        "is_dir",
        "stat",
        "iterdir",
        "glob",
        "rglob",
        "stem",
        "name",
        "suffix",
        "parts",
    }
)


@dataclass(frozen=True, slots=True)
class Named:
    """A target expression naming a path, as its literal text — relative or absolute."""

    path: str


@dataclass(frozen=True, slots=True)
class Scratch:
    """A target expression headed by a scratch call: scratch, whatever it names."""


#: What a target expression yields; `None` is nothing.
Judged = Named | Scratch


def is_scratch_call(operand: str) -> bool:
    """Step 1's test, on an operand's text.

    >>> [is_scratch_call(o) for o in ("tempfile.gettempdir()", "os.tmpdir()", "mktemp_x(")]
    [True, True, False]
    """
    operand = operand.strip()
    return bool(_SCRATCH_CALL.match(operand) or _NODE_TMPDIR.search(operand))


@dataclass(frozen=True, slots=True)
class Literal:
    """A string literal: where it starts (its prefix included) and ends, and its contents."""

    start: int
    end: int
    content: str


class Source:
    """A script's text, its string literals, and a copy with every literal masked as `_` so that
    brackets, commas and names inside strings are never read as code."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.literals = {literal.start: literal for literal in _literals(text)}
        masked = list(text)
        for literal in self.literals.values():
            for index in range(literal.start, literal.end):
                if masked[index] != "\n":
                    masked[index] = "_"
        self.masked = "".join(masked)

    def close_of(self, opening: int) -> int | None:
        """The bracket closing the one at `opening`."""
        depth = 0
        for index in range(opening, len(self.masked)):
            if self.masked[index] in "([{":
                depth += 1
            elif self.masked[index] in ")]}":
                depth -= 1
                if depth == 0:
                    return index
        return None

    def open_of(self, closing: int) -> int | None:
        """The bracket opening the one at `closing`."""
        depth = 0
        for index in range(closing, -1, -1):
            if self.masked[index] in ")]}":
                depth += 1
            elif self.masked[index] in "([{":
                depth -= 1
                if depth == 0:
                    return index
        return None

    def arguments(self, opening: int) -> list[tuple[int, int]]:
        """The `(start, end)` of each top-level argument of the call whose `(` is at `opening`."""
        close = self.close_of(opening)
        if close is None:
            return []
        found: list[tuple[int, int]] = []
        depth = 0
        start = opening + 1
        for index in range(opening + 1, close):
            character = self.masked[index]
            if character in "([{":
                depth += 1
            elif character in ")]}":
                depth -= 1
            elif character == "," and depth == 0:
                found.append((start, index))
                start = index + 1
        if self.text[start:close].strip() or found:
            found.append((start, close))
        return found

    def trim(self, start: int, end: int) -> tuple[int, int]:
        while start < end and self.text[start].isspace():
            start += 1
        while end > start and self.text[end - 1].isspace():
            end -= 1
        return start, end

    def whole_literal(self, start: int, end: int) -> Literal | None:
        """The literal spanning exactly `start:end`, whitespace trimmed."""
        start, end = self.trim(start, end)
        literal = self.literals.get(start)
        return literal if literal is not None and literal.end == end else None

    def closing(self, opening: int, end: int) -> int:
        """The bracket closing the one at `opening`, or `end` when none does before `end`."""
        close = self.close_of(opening)
        return close if close is not None and close < end else end

    def operand_end(self, start: int, end: int) -> int:
        """Where the operand at `start` ends: a name, a call or a parenthesised group, with its
        chain. `start` itself when there is no operand there."""
        if self.masked[start : start + 1] == "(":
            close = self.closing(start, end)
            if close == end:
                return start
            index = close + 1
        else:
            name = re.match(_NAME, self.masked[start:end])
            if name is None:
                return start
            index = start + name.end()
        for _, after in self._chain(index, end):
            index = after
        return index

    def _chain(self, index: int, end: int) -> Iterator[tuple[str | None, int]]:
        """The links of the chain starting at `index` — `.name`, a call's `(…)`, a subscript's
        `[…]` — each as its name (`None` for a bracketed one) and the index after it. The chain
        stops at anything else, or at a bracket that does not close before `end`."""
        while index < end:
            if self.masked[index] in "([":
                close = self.closing(index, end)
                if close == end:
                    return
                index = close + 1
                yield None, index
                continue
            link = _LINK.match(self.masked, index, end)
            if link is None:
                return
            index = link.end()
            yield link.group(1), index

    def slash_literals(self, start: int, end: int) -> list[str]:
        """The literals of a `/ '…' / '…'` chain from `start`, up to the first non-literal."""
        found: list[str] = []
        index = start
        while True:
            slash = re.match(r"\s*/\s*", self.text[index:end])
            literal = self.literals.get(index + slash.end()) if slash else None
            if slash is None or literal is None:
                return found
            found.append(literal.content)
            index = literal.end

    def chain_yields(self, start: int, end: int) -> bool:
        """Step 6: `False` when the chain in `start:end` contains a read, a name component, or a
        `.open(` with no write mode."""
        for name, after in self._chain(start, end):
            if name is not None and name in CHAIN_STOPS:
                return False
            is_call = self.masked[after:end].startswith("(")
            if name == "open" and is_call and not _WRITE_MODE_CALL.match(self.text, after):
                return False
        return True


def _literals(text: str) -> list[Literal]:
    """Every string literal, left to right: prefixed (`f`, `r`, `b`, `rb`, `fr`) or not, and
    backtick-delimited for node. A quote that does not close on its line — a backtick's may span
    lines — starts no literal."""
    found: list[Literal] = []
    index = 0
    while (match := _LITERAL_START.search(text, index)) is not None:
        quote = match.group(2)
        close = match.end()
        while close < len(text) and text[close] != quote:
            if text[close] == "\n" and quote != "`":
                break
            close += 2 if text[close] == "\\" else 1
        if close >= len(text) or text[close] != quote:
            index = match.end()
            continue
        found.append(Literal(match.start(), close + 1, text[match.end() : close]))
        index = close + 1
    return found


@dataclass(slots=True)
class Judge:
    """§3.3's rules over one script, holding the names bound so far."""

    source: Source
    bindings: dict[str, Judged] = field(default_factory=dict)

    def target_of(self, expression: str) -> Judged | None:
        """Judge `expression` as a target expression, under this script's bindings."""
        return Judge(Source(expression), self.bindings).target(0, len(expression))

    def target(self, start: int, end: int) -> Judged | None:
        """The target expression in `start:end` of the source."""
        source = self.source
        start, end = source.trim(start, end)
        if start >= end:
            return None
        operand_end = source.operand_end(start, end)
        if source.masked[start] == "(":
            return self._group(start, operand_end)
        operand = source.text[start:operand_end]
        if operand and is_scratch_call(operand):
            return Scratch()
        literal = source.literals.get(start)
        if literal is not None:
            return self._literal_value(literal)
        head_end, head = self._head(start, end, operand_end)
        if head is None or not source.chain_yields(head_end, operand_end):
            return None
        return head

    def _group(self, opening: int, operand_end: int) -> Judged | None:
        """A parenthesised group heading the operand: its contents judged as a target expression,
        then step 6 on any chain after it."""
        close = self.source.close_of(opening)
        if close is None:
            return None
        inner = self.target(opening + 1, close)
        if inner is None or not self.source.chain_yields(close + 1, operand_end):
            return None
        return inner

    def _literal_value(self, literal: Literal) -> Judged:
        """A literal contributes itself, prefix removed and any `{…}` left in place — unless it
        opens with a `{…}` or `${…}` span whose own target expression yields something."""
        span = _LEADING_SPAN.match(literal.content)
        if span is not None:
            led = self.target_of(span.group(1))
            if led is not None:
                return led
        return Named(literal.content)

    def _head(self, start: int, end: int, operand_end: int) -> tuple[int, Judged | None]:
        """Steps 3 to 5 on the head alone. Returns where the head ends — its chain starts there —
        and what it yields."""
        source = self.source
        call = _CALL_HEAD.match(source.masked, start, operand_end)
        callee = call.group(1) if call else ""
        is_path = bool(_PATH_CONSTRUCTOR.fullmatch(callee))
        if call is None or not (is_path or callee in PATH_FUNCTIONS or "." not in callee):
            # A name head; a dotted callee that is no path function is a name and its chain.
            name = re.match(_NAME, source.masked[start:operand_end])
            if name is None:
                return operand_end, None
            return start + name.end(), self.bindings.get(name.group(0))
        opening = call.end() - 1
        # The operand holds this call only because its `(` closes inside it.
        close = source.closing(opening, operand_end)
        return close + 1, self._call_head(callee, opening, close, (operand_end, end))

    def _call_head(
        self, callee: str, opening: int, close: int, bounds: tuple[int, int]
    ) -> Judged | None:
        source = self.source
        arguments = source.arguments(opening)
        if not arguments:
            return None
        if _PATH_CONSTRUCTOR.fullmatch(callee):
            if is_scratch_call(source.text[slice(*source.trim(*arguments[0]))]):
                return Scratch()
            parts = [source.whole_literal(*argument) for argument in arguments]
            if all(part is not None for part in parts):
                operand_end, end = bounds
                chained = (
                    source.slash_literals(operand_end, end) if operand_end == close + 1 else []
                )
                contents = [part.content for part in parts if part is not None]
                return Named("/".join([*contents, *chained]))
        if callee not in PATH_FUNCTIONS:
            return None
        if callee in _JOINERS:
            leading: list[str] = []
            for argument in arguments:
                literal = source.whole_literal(*argument)
                if literal is None:
                    break
                leading.append(literal.content)
            if len(leading) > 1:
                return Named("/".join(leading))
        return self.target(*arguments[0])

    def first_argument(self, opening: int) -> Judged | None:
        """The target of a call taking a path first: its first argument, or a `file=`/`path=`
        keyword. Any other keyword in first place names nothing."""
        source = self.source
        arguments = source.arguments(opening)
        for start, end in arguments:
            keyword = re.match(r"\s*(?:file|path)\s*=(?!=)\s*", source.text[start:end])
            if keyword is not None:
                return self.target(start + keyword.end(), end)
        if not arguments or re.match(rf"\s*{_NAME}\s*=(?!=)", source.text[slice(*arguments[0])]):
            return None
        return self.target(*arguments[0])

    def receiver(self, dot: int) -> Judged | None:
        """The target of a method on a path: the operand before the `.` at `dot` — a name, a
        call or a parenthesised group, with any `.name(…)` chain between."""
        masked = self.source.masked
        start = dot
        while start > 0:
            if masked[start - 1] == ")":
                opening = self.source.open_of(start - 1)
                if opening is None:
                    break
                start = opening
            name = re.search(rf"{_NAME}$", masked[:start])
            if name is None:
                break
            start = name.start()
            if start == 0 or masked[start - 1] != ".":
                break
            start -= 1
        return self.target(start, dot)
