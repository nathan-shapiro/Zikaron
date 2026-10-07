"""`design/edit-guards.md` §8, the find-replace rule's test table, as commands and expectations.

§8 is the one place the rule table's rows are listed, so the parametrised test reads it rather
than holding a second copy. Each row's `Command` cell holds one or more items separated by ` · `;
an item is one or more backticked spans, each a line of one command, separated by ` / `. A few
items are written as prose that names a neighbour ("the same ending `f`"); each such phrasing is
recognised here explicitly, and **any prose not recognised raises**, so a new row cannot be
skipped silently.

The `Expected` cell starts with the decision — *deny*, *silent* or *ack* — and may add what the
message says: which marker message, the placement clause, and what the deny names.

§8.1, row 6's file reads, adds a first column naming the files each row's `$TMPDIR` holds, in the
forms its preamble lists; `file_cases` reads it, and any form not listed there raises.
"""

import enum
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tests.design_tables import DesignTableError, table_with_columns

DOCUMENT: Final = "edit-guards.md"
HEADING: Final = "## 8. The test table's seed"
FILE_READS_HEADING: Final = "### 8.1 Row 6's file reads"

#: §8's payload: a `cwd` that is not scratch, `$TMPDIR` unset, no `scratchpad_dir`.
CWD: Final = "/home/u/proj"
#: The one row that says a relative target resolves under `/tmp/` is judged here.
SCRATCH_CWD: Final = "/tmp/w"  # noqa: S108 — a payload value, never touched

_SPAN: Final = re.compile(r"``\s?(.+?)\s?``|`([^`]*)`")
_EACH_INSIDE: Final = ' — each inside `python3 -c "…"`'
_INLINE_PYTHON: Final = '`python3 -c "…"`'


@dataclass(frozen=True)
class Case:
    """One item of §8: the command, the `cwd` it is judged under, and the raw `Expected` cell."""

    row: int
    item: str
    command: str
    expected: str
    cwd: str = CWD

    @property
    def id(self) -> str:
        return f"row{self.row}:{self.command[:60]}"


@dataclass(frozen=True)
class Expected:
    """What an `Expected` cell asserts."""

    decision: str
    invalid_marker: bool
    placement: bool
    named: tuple[str, ...]
    named_form: str | None
    names_no_literal: bool
    names_authored: bool

    @classmethod
    def of(cls, cell: str, command: str) -> "Expected":
        named = tuple(re.findall(r"naming `([^`]+)`", cell))
        no_literal = "naming no literal" in cell or "naming nothing" in cell
        per_item = _per_item_naming(cell, command)
        if per_item is not None:
            named, no_literal = per_item
        word = re.match(r"\*?(\w+)", cell)
        if word is None:
            raise DesignTableError(f"§8 Expected cell names no decision: {cell!r}")
        form = re.search(r"naming the `(\w+)` form", cell)
        return cls(
            decision=word.group(1).lower(),
            invalid_marker="invalid" in cell,
            placement="placement" in cell,
            named=named,
            named_form=form.group(1) if form else None,
            names_no_literal=no_literal,
            names_authored="naming the authored target" in cell,
        )


def cases() -> list[Case]:
    """Every item of every row of §8, in order."""
    found: list[Case] = []
    previous_row: list[str] = []
    rows = table_with_columns(DOCUMENT, HEADING, ("Command", "Expected"))
    for number, row in enumerate(rows, start=1):
        cell = row["Command"]
        each_inside = cell.endswith(_EACH_INSIDE)
        if each_inside:
            cell = cell[: -len(_EACH_INSIDE)]
        this_row: list[str] = []
        for item in _items(cell):
            command, cwd = _command(item, this_row, previous_row)
            if each_inside:
                command = _inside_python(command)
            found.append(Case(number, item, command, row["Expected"], cwd))
            this_row.append(command)
        previous_row = this_row
    return found


def _items(cell: str) -> list[str]:
    """A cell's ` · `-separated items, never splitting inside backticks."""
    items: list[str] = []
    current: list[str] = []
    inside = False
    index = 0
    while index < len(cell):
        if cell[index] == "`":
            inside = not inside
        if not inside and cell.startswith(" · ", index):
            items.append("".join(current).strip())
            current = []
            index += len(" · ")
            continue
        current.append(cell[index])
        index += 1
    items.append("".join(current).strip())
    return items


def _pieces(item: str) -> tuple[list[str], str]:
    """An item's backticked spans, and the prose between them."""
    spans: list[str] = []
    prose: list[str] = []
    position = 0
    for match in _SPAN.finditer(item):
        prose.append(item[position : match.start()])
        spans.append(match.group(1) if match.group(1) is not None else match.group(2))
        position = match.end()
    prose.append(item[position:])
    return spans, " ".join(part.strip() for part in prose).strip()


def _inside_python(snippet: str) -> str:
    return f"python3 -c '{snippet}'" if '"' in snippet else f'python3 -c "{snippet}"'


def _command(item: str, this_row: list[str], previous_row: list[str]) -> tuple[str, str]:
    """The literal command an item stands for, and the `cwd` it is judged under."""
    if item.startswith("a relative target that"):
        return "sed -i 's/a/b/' x", SCRATCH_CWD
    spans, prose = _pieces(item)
    command = _from_neighbour(item, spans, prose, this_row, previous_row)
    if command is None:
        command = _abbreviated(item, spans, prose)
    if command is not None:
        return command, CWD
    leftover = re.sub(r"/|\ba line quoting\b|\ba line\b", " ", prose.replace("*probe*:", ""))
    if leftover.strip():
        raise DesignTableError(f"§8 item {item!r} carries prose this reader does not know")
    return "\n".join(spans), CWD


def _from_neighbour(
    item: str, spans: list[str], prose: str, this_row: list[str], previous_row: list[str]
) -> str | None:
    """An item written as a change to another item of this row or the row before."""
    if item.startswith("the same ending"):
        return "\n".join([*previous_row[-1].split("\n")[:-1], "f"])
    if item.startswith("the same five-line"):
        return previous_row[0].replace("Path('CLAUDE.md')", "Path('/tmp/x')")
    if item.startswith("the same with"):
        return "\n".join([*previous_row[0].split("\n")[:-1], spans[0]])
    if prose.endswith("(same body)"):
        return "\n".join([spans[0], *this_row[-1].split("\n")[1:]])
    return None


def _abbreviated(item: str, spans: list[str], prose: str) -> str | None:
    """An item written as a fragment: a Python snippet, or the tail of the sed probe command."""
    if prose.endswith("inside") and item.endswith(_INLINE_PYTHON):
        return _inside_python(spans[0])
    if spans and spans[0].startswith("… #ZIKARON-FORCE"):
        return "sed -i 's/a/b/' f" + spans[0][1:]
    if spans and spans[0].startswith("… #Reason:"):
        return "sed -i 's/a/b/' f #ZIKARON-FORCE" + spans[0][1:]
    return None


def _per_item_naming(cell: str, command: str) -> tuple[tuple[str, ...], bool] | None:
    """A cell like "the triple-quoted row names `f`, … and the others name no literal": what this
    item names, or that it names no literal."""
    if "the others name no literal" not in cell:
        return None
    for selector, name in re.findall(r"the (.+?) row names `([^`]+)`", cell):
        chosen = (
            '"""' in command if selector == "triple-quoted" else selector.strip("` ") in command
        )
        if chosen:
            return (name,), False
    return (), True


class FileKind(enum.Enum):
    """The forms §8.1's preamble lets a row's file take."""

    TEXT = "text"
    SYMLINK = "symlink"
    FIFO = "fifo"
    DIRECTORY = "directory"
    SIZED = "sized"
    UNDECODABLE = "undecodable"


@dataclass(frozen=True)
class ScratchFile:
    """One file a §8.1 row puts in `$TMPDIR` before its command is judged."""

    name: str
    kind: FileKind
    #: The text, the symlink's target name, or nothing.
    text: str = ""
    #: For `SIZED`: the file's exact length in bytes.
    size: int = 0

    def create(self, directory: Path) -> None:
        path = directory / self.name
        if self.kind is FileKind.TEXT:
            path.write_text(self.text + "\n", encoding="utf-8")
        elif self.kind is FileKind.SYMLINK:
            path.symlink_to(directory / self.text)
        elif self.kind is FileKind.FIFO:
            os.mkfifo(path)
        elif self.kind is FileKind.DIRECTORY:
            path.mkdir()
        elif self.kind is FileKind.SIZED:
            path.write_bytes(_padded(self.text, self.size))
        else:
            path.write_bytes(b"\xff" + self.text.encode() + b"\n")


@dataclass(frozen=True)
class FileCase:
    """One item of §8.1: the files, the command and the raw `Expected` cell."""

    row: int
    files: tuple[ScratchFile, ...]
    command: str
    expected: str
    cwd: str = CWD

    @property
    def id(self) -> str:
        return f"row8.1-{self.row}:{self.command[:60]}"


def file_cases() -> list[FileCase]:
    """Every item of every row of §8.1, in order."""
    found: list[FileCase] = []
    rows = table_with_columns(
        DOCUMENT, FILE_READS_HEADING, ("Files in `$TMPDIR`", "Command", "Expected")
    )
    for number, row in enumerate(rows, start=1):
        files = tuple(_scratch_file(item) for item in _items(row["Files in `$TMPDIR`"]))
        for item in _items(row["Command"]):
            spans, prose = _pieces(item)
            if prose.replace("/", "").strip():
                raise DesignTableError(f"§8.1 command {item!r} carries prose")
            found.append(FileCase(number, files, "\n".join(spans), row["Expected"]))
    return found


_FILE: Final = re.compile(r"`(?P<name>[^`]+)`: (?P<what>.+)")
_SIZED: Final = re.compile(r"(?P<size>\d+) bytes ending in `(?P<text>.+)`")


def _scratch_file(item: str) -> ScratchFile:
    match = _FILE.fullmatch(item)
    if match is None:
        raise DesignTableError(f"§8.1 file {item!r} is in no form the preamble lists")
    name, what = match.group("name"), match.group("what")
    fixed = {"a FIFO": FileKind.FIFO, "a directory": FileKind.DIRECTORY}
    if what in fixed:
        return ScratchFile(name, fixed[what])
    if (sized := _SIZED.fullmatch(what)) is not None:
        return ScratchFile(name, FileKind.SIZED, sized.group("text"), int(sized.group("size")))
    shapes = (
        (r"a symlink to `(.+)`", FileKind.SYMLINK),
        (r"the byte `0xFF` followed by `(.+)`", FileKind.UNDECODABLE),
        (r"`(.+)`", FileKind.TEXT),
    )
    for pattern, kind in shapes:
        if (shaped := re.fullmatch(pattern, what)) is not None:
            return ScratchFile(name, kind, shaped.group(1))
    raise DesignTableError(f"§8.1 file {item!r} is in no form the preamble lists")


def _padded(text: str, size: int) -> bytes:
    """`size` bytes ending in `text`: `#` comment lines of 80 bytes, then a shorter one, first."""
    tail = text.encode()
    room = size - len(tail)
    lines = b"#" * 79 + b"\n"
    filler = lines * (room // len(lines))
    rest = room - len(filler)
    if rest:
        filler += b"#" * (rest - 1) + b"\n"
    return filler + tail
