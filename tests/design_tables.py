"""Read the normative tables straight out of the design documents.

Several things in the code are transcriptions of tables in `design/`. Checking one against a
second hand-written copy would only prove the two copies agree, and would say nothing about the
likelier drift: the design being revised while the code stays put. So the tests read the design
documents themselves. An edit on either side then fails a test, which is the only arrangement
where "the code matches the design" is a claim rather than a hope.

Everything here fails closed. A reader that returned an empty result for a document it could not
understand would turn every drift guard into a test that passes unconditionally, and one that
returned a *plausible* result for an ambiguous document would be worse still — the suite would
go on checking a table nobody was looking at any more. So ambiguity raises: a heading that
occurs twice, a table with repeated or blank column names, a delimiter row that does not match
its header, a payload group whose brackets cross.

The parsing functions take text and the reading functions take a document name, so a malformed
input can be tested without a malformed document on disk.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DESIGN_DIR: Final = Path(__file__).resolve().parent.parent / "design"

MINUS_SIGN: Final = "\u2212"
EN_DASH: Final = "\u2013"

_FENCE: Final = "```"
_UNESCAPED_PIPE: Final = re.compile(r"(?<!\\)\|")
_DELIMITER_CELL: Final = re.compile(r"^:?-{3,}:?$")
_QUOTED: Final = re.compile(r"^'([^']*)'$")
_CLOSER_FOR: Final = {"{": "}", "[": "]"}

type Row = dict[str, str]
type Table = list[Row]


class DesignTableError(Exception):
    """The design document does not hold what a test expected to read from it."""


@dataclass(frozen=True)
class ParsedField:
    """One field of a payload or detail object, as the design writes it.

    `values` is the closed set stated after the field's name — strings where the design quotes
    them and integers where it does not — and is empty when the design states no set, either
    because the value is open or because it is illustrated rather than enumerated. `nullable`
    records that `null` was one of the stated alternatives.
    """

    name: str
    values: tuple[str | int, ...] = ()
    nullable: bool = False


# ---------------------------------------------------------------------------
# Parsing: text in, structure out
# ---------------------------------------------------------------------------


def _heading_depth(line: str) -> int:
    return len(line) - len(line.lstrip("#"))


def _structural_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Every heading that is structure rather than fenced text, as `(line index, text)`.

    An unterminated fence is refused rather than treated as running to the end of the document.
    One stray opening fence would otherwise swallow every heading after it — including a second
    copy of the heading a reader is looking for — while the content before it went on parsing
    perfectly, which is the shape of failure that hides itself.
    """
    headings: list[tuple[int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.startswith(_FENCE):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("#"):
            headings.append((index, line.strip()))
    if in_fence:
        raise DesignTableError("a fence is opened and never closed")
    return headings


def parse_section(lines: list[str], heading: str) -> list[str]:
    """The lines under `heading`, ending at the next heading of the same or shallower depth.

    `heading` is the whole markdown heading including its hashes, matched exactly. Headings
    inside fenced code blocks are text rather than structure and are ignored.

    A heading that occurs more than once anywhere in the document is an error rather than a
    choice of the first. A revised section added beside the one it revises is exactly the case
    that would otherwise leave every guard downstream checking the stale copy, and the ambiguity
    is not something a reader of the failure should have to guess at.
    """
    depth = _heading_depth(heading)
    headings = _structural_headings(lines)
    starts = [index for index, text in headings if text == heading]
    if not starts:
        raise DesignTableError(f"no heading {heading!r}")
    if len(starts) > 1:
        raise DesignTableError(f"heading {heading!r} occurs more than once, at lines {starts}")
    start = starts[0]
    end = next(
        (index for index, text in headings if index > start and _heading_depth(text) <= depth),
        len(lines),
    )
    return lines[start + 1 : end]


def _split_row(line: str) -> list[str]:
    cells = [cell.strip().replace("\\|", "|") for cell in _UNESCAPED_PIPE.split(line.strip())]
    if cells and cells[0] == "":
        cells.pop(0)
    if cells and cells[-1] == "":
        cells.pop()
    return cells


def parse_tables(section: list[str]) -> list[Table]:
    """Every markdown table in a section, each as one dict per row keyed by column heading."""
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    in_fence = False
    for line in section:
        if line.startswith(_FENCE):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.lstrip().startswith("|"):
            current.append(_split_row(line))
            continue
        if current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return [_as_table(block) for block in blocks]


def _as_table(block: list[list[str]]) -> Table:
    if len(block) < 3:
        raise DesignTableError(f"table has {len(block)} lines, so it has no rows")
    header, delimiter = block[0], block[1]
    if any(cell == "" for cell in header):
        raise DesignTableError(f"table has a blank column name: {header}")
    if len(set(header)) != len(header):
        raise DesignTableError(f"table repeats a column name: {header}")
    if len(delimiter) != len(header):
        raise DesignTableError(f"delimiter has {len(delimiter)} cells for {len(header)} columns")
    if not all(_DELIMITER_CELL.match(cell) for cell in delimiter):
        raise DesignTableError(f"second table line is not a delimiter: {delimiter}")
    rows: Table = []
    for row in block[2:]:
        if len(row) != len(header):
            raise DesignTableError(f"row has {len(row)} cells for {len(header)} columns: {row}")
        rows.append(dict(zip(header, row, strict=True)))
    return rows


def parse_toml(section: list[str]) -> dict[str, dict[str, object]]:
    """The one fenced TOML block in a section, parsed into sections of scalar keys.

    Exactly one, not the first of several: a revised sample added beside the one it revises would
    otherwise leave every default checked against the stale copy, silently and indefinitely.

    A top-level scalar or a third level of nesting is refused rather than flattened, since the
    configuration format is exactly two levels deep and a sample that had drifted from that would
    otherwise be read as though it had not.
    """
    blocks: list[list[str]] = []
    collecting: list[str] | None = None
    for line in section:
        if line.startswith(_FENCE):
            if collecting is not None:
                blocks.append(collecting)
                collecting = None
            elif line.strip().removeprefix(_FENCE).strip() == "toml":
                collecting = []
            continue
        if collecting is not None:
            collecting.append(line)
    if collecting is not None:
        raise DesignTableError("a toml fence is opened and never closed")
    if len(blocks) != 1:
        raise DesignTableError(f"{len(blocks)} fenced toml blocks, expected one")
    parsed = tomllib.loads("\n".join(blocks[0]))
    if not parsed:
        raise DesignTableError("toml block is empty")
    sections: dict[str, dict[str, object]] = {}
    for name, value in parsed.items():
        if not isinstance(value, dict):
            raise DesignTableError(f"top-level key {name!r} is not a section")
        for inner, deeper in value.items():
            if isinstance(deeper, dict):
                raise DesignTableError(f"{name}.{inner} nests deeper than a section")
        sections[name] = dict(value)
    return sections


def literal(cell: str) -> str:
    """A table cell that holds one literal, with the markdown around it removed."""
    return cell.strip().strip("*").strip("`").strip()


def number(cell: str) -> int:
    """A table cell holding one integer, written with the typographic minus sign or without."""
    return int(literal(cell).replace(MINUS_SIGN, "-"))


def _matching_bracket(text: str, start: int) -> int:
    expected: list[str] = []
    for position in range(start, len(text)):
        char = text[position]
        if char in _CLOSER_FOR:
            expected.append(_CLOSER_FOR[char])
        elif char in ("}", "]"):
            if not expected:
                raise DesignTableError(f"unbalanced brackets in {text!r}")
            if expected.pop() != char:
                raise DesignTableError(f"crossed brackets in {text!r}")
            if not expected:
                return position
    raise DesignTableError(f"unbalanced brackets in {text!r}")


def _top_level_commas(inner: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in inner:
        if char in _CLOSER_FOR:
            depth += 1
        elif char in ("}", "]"):
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _parse_alternatives(name: str, stated: str) -> ParsedField:
    if not stated.strip():
        return ParsedField(name)
    values: list[str | int] = []
    nullable = False
    for alternative in stated.split("|"):
        stated_value = literal(alternative)
        if stated_value == "null":
            nullable = True
            continue
        quoted = _QUOTED.match(stated_value)
        if quoted is not None:
            values.append(quoted.group(1))
        elif stated_value.lstrip("-").isdigit():
            values.append(int(stated_value))
        else:
            # An illustration rather than an enumeration, as in `[{...}]`. The field's value is
            # open, and pretending the illustration were the one legal value would be worse
            # than recording that the design does not constrain it.
            return ParsedField(name)
    return ParsedField(name, tuple(values), nullable)


_STATED_SET: Final = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)\s*\u2208\s*([^`]+)`")


def parse_payload(cell: str) -> tuple[ParsedField, ...]:
    """The fields of the first `{...}` group in a cell, in the order the design writes them.

    A cell may state a field's closed set two ways — inside the group after a colon, or beside
    it as `name in a | b` — and both are read, because a set stated the second way constrains
    the payload every bit as much as one stated the first way. Remaining prose is commentary.
    """
    if "{" not in cell:
        raise DesignTableError(f"no payload group in {cell!r}")
    start = cell.index("{")
    inner = cell[start + 1 : _matching_bracket(cell, start)]
    fields = [
        _parse_alternatives(literal(part.split(":")[0]), part.partition(":")[2])
        for part in _top_level_commas(inner)
        if part.strip()
    ]
    if not fields:
        raise DesignTableError(f"empty payload group in {cell!r}")
    return tuple(_with_stated_sets(fields, cell))


def _with_stated_sets(fields: list[ParsedField], cell: str) -> list[ParsedField]:
    stated: dict[str, tuple[str, ...]] = {}
    for name, alternatives in _STATED_SET.findall(cell):
        if name in stated:
            raise DesignTableError(f"{name!r} constrained twice in one cell: {cell!r}")
        stated[name] = tuple(
            value for value in (literal(part) for part in alternatives.split("|")) if value
        )
    known = {field.name for field in fields}
    unknown = set(stated) - known
    if unknown:
        raise DesignTableError(f"{sorted(unknown)} constrained but not in the payload: {cell!r}")
    for field in fields:
        if field.name in stated and field.values:
            raise DesignTableError(f"{field.name!r} constrained twice, in and beside the group")
    return [
        ParsedField(field.name, stated[field.name], field.nullable)
        if field.name in stated
        else field
        for field in fields
    ]


def parse_field_values(
    table: Table, field_column: str, values_column: str
) -> dict[str, tuple[str, ...]]:
    """Collect a two-column field-to-values table, whose rows continue under a blank name."""
    collected: dict[str, list[str]] = {}
    current: str | None = None
    for row in table:
        name = literal(row[field_column])
        if name:
            current = name
            collected.setdefault(current, [])
        if current is None:
            raise DesignTableError(f"a value row precedes any field name: {row}")
        for alternative in row[values_column].split("|"):
            stated_value = literal(alternative).strip("'")
            if stated_value:
                collected[current].append(stated_value)
    if not collected:
        raise DesignTableError("no field values in table")
    return {name: tuple(values) for name, values in collected.items()}


def parse_name_lists(
    table: Table, key_column: str, names_column: str
) -> dict[str, tuple[str, ...]]:
    """A table mapping one key to a comma-separated list of names, one row per key.

    A key appearing twice is refused: two rows for one key would either contradict each other or
    mean the list is split, and reading only one of them is how half a rule goes missing.
    """
    collected: dict[str, tuple[str, ...]] = {}
    for row in table:
        key = literal(row[key_column])
        if not key:
            raise DesignTableError(f"a row has no key: {row}")
        if key in collected:
            raise DesignTableError(f"{key!r} appears in two rows")
        names = tuple(
            name for name in (literal(part) for part in row[names_column].split(",")) if name
        )
        if not names:
            raise DesignTableError(f"{key!r} lists no names")
        collected[key] = names
    if not collected:
        raise DesignTableError("no rows in table")
    return collected


def parse_couplings(section: list[str]) -> dict[str, str]:
    """Map each store-coupled key name to the severity its own bullet gives it.

    A name classified by two bullets is refused rather than resolved by document order: the two
    bullets are what disagree, and choosing between them is not a reader's job.
    """
    bullet = re.compile(r"^-\s+\*\*(Hard|Soft)\s*[\u2014-]\s*(.+?)\.\*\*")
    couplings: dict[str, str] = {}
    for line in section:
        match = bullet.match(line.strip())
        if match is None:
            continue
        severity = match.group(1).lower()
        for name in re.findall(r"`([^`]+)`", match.group(2)):
            if name in couplings:
                raise DesignTableError(f"{name!r} is classified by more than one bullet")
            couplings[name] = severity
    if not couplings:
        raise DesignTableError("no store-coupling bullets")
    return couplings


# ---------------------------------------------------------------------------
# Reading: a document name in, parsed structure out
# ---------------------------------------------------------------------------


def document_lines(document: str) -> list[str]:
    """Every line of a design document."""
    path = DESIGN_DIR / document
    if not path.is_file():
        raise DesignTableError(f"no design document at {path}")
    return path.read_text(encoding="utf-8").splitlines()


def _located(document: str, heading: str, error: DesignTableError) -> DesignTableError:
    return DesignTableError(f"{document} / {heading}: {error}")


def section_lines(document: str, heading: str) -> list[str]:
    """The lines of one section of a design document."""
    try:
        return parse_section(document_lines(document), heading)
    except DesignTableError as error:
        raise _located(document, heading, error) from error


def tables(document: str, heading: str) -> list[Table]:
    """Every table in one section of a design document."""
    try:
        found = parse_tables(section_lines(document, heading))
    except DesignTableError as error:
        raise _located(document, heading, error) from error
    if not found:
        raise DesignTableError(f"{document} / {heading}: found no table")
    return found


def table_with_columns(document: str, heading: str, columns: tuple[str, ...]) -> Table:
    """The one table in a section whose column headings are exactly `columns`.

    Tables are found by what they are rather than by where they sit, so inserting another table
    into a section cannot silently redirect a guard, and renaming a normative column fails
    loudly instead of matching something adjacent.
    """
    matches = [table for table in tables(document, heading) if tuple(table[0]) == columns]
    if len(matches) != 1:
        found = [tuple(table[0]) for table in tables(document, heading)]
        raise DesignTableError(
            f"{document} / {heading}: {len(matches)} tables with columns {columns}, found {found}"
        )
    return matches[0]


def toml_block(document: str, heading: str) -> dict[str, dict[str, object]]:
    """The fenced TOML sample in one section of a design document."""
    try:
        return parse_toml(section_lines(document, heading))
    except DesignTableError as error:
        raise _located(document, heading, error) from error


def couplings(document: str, heading: str) -> dict[str, str]:
    """The store-coupling severities stated in one section of a design document."""
    try:
        return parse_couplings(section_lines(document, heading))
    except DesignTableError as error:
        raise _located(document, heading, error) from error
