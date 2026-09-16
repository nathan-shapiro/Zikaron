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


def parse_fenced_code(section: list[str], language: str) -> str:
    """The one fence tagged ` ```{language} ` in a section, with its opening/closing lines cut.

    Exactly one, for the same reason `parse_toml` insists on exactly one TOML fence: a second
    block added beside the one it revises would otherwise leave every guard reading whichever
    one happens to be first, silently and indefinitely. A fence tagged with a different language,
    or untagged, does not count — this function is for finding a specific normative block, not
    every fence in the section.
    """
    blocks: list[list[str]] = []
    collecting: list[str] | None = None
    matched = False
    for line in section:
        if line.startswith(_FENCE):
            if collecting is not None:
                if matched:
                    blocks.append(collecting)
                collecting = None
                matched = False
            else:
                collecting = []
                matched = line.strip().removeprefix(_FENCE).strip() == language
            continue
        if collecting is not None and matched:
            collecting.append(line)
    if collecting is not None:
        raise DesignTableError(f"a {language} fence is opened and never closed")
    if len(blocks) != 1:
        raise DesignTableError(f"{len(blocks)} fenced {language} blocks, expected one")
    return "\n".join(blocks[0])


def parse_block_quote(section: list[str], opening: str) -> str:
    """The one block quote in a section whose first line starts with `opening`, unquoted.

    Anchored on its opening words rather than assumed to be the section's only quote: a section
    long enough to be worth guarding usually holds more than one, and a parser that silently took
    the first would keep passing while pointed at the wrong block. Exactly one must match, so a
    second quote opening the same way is an error rather than a coin toss.

    Fenced content is masked, as every other reader here masks it, and for a reason this corpus
    supplies: withdrawn text is kept rather than deleted, so a historical copy of a quote can
    legitimately sit in a fence beside the live one. Reading through fences would let that copy
    satisfy the exactly-one rule if the live quote were ever removed, and a guard would then compare
    a shipped artifact against an archive while still passing.

    Returns the quote with its `> ` markers stripped and its lines joined, which is the form a
    prose block is compared in — the wrapping is the document's, not the text's.
    """
    blocks: list[list[str]] = []
    collecting: list[str] | None = None
    in_fence = False
    for line in [*section, ""]:
        fence = line.startswith(_FENCE)
        if not fence and not in_fence and line.startswith(">"):
            unquoted = line[1:].removeprefix(" ")
            if collecting is None:
                collecting = [unquoted]
            else:
                collecting.append(unquoted)
            continue
        # A fence boundary closes an open quote as any other non-quoted line does. Skipping it
        # instead would let an *empty* fence between two quote runs join them into one block —
        # nothing separates them once both fence lines are passed over — which is a quote this
        # document does not contain, reported under an opening it does.
        if fence:
            in_fence = not in_fence
        if collecting is not None:
            if collecting[0].startswith(opening):
                blocks.append(collecting)
            collecting = None
    if len(blocks) != 1:
        raise DesignTableError(f"{len(blocks)} block quotes open with {opening!r}, expected one")
    return "\n".join(blocks[0])


def _strip_sql_comments(sql: str) -> str:
    """Remove every `--` line comment, respecting single-quoted strings a comment marker could
    sit inside — none of `schema.md`'s DDL does that, but a splitter that assumed it does is
    exactly the kind of assumption that stops being true on the next design edit.
    """
    out: list[str] = []
    in_string = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'":
            in_string = not in_string
            out.append(char)
            index += 1
        elif not in_string and sql[index : index + 2] == "--":
            newline = sql.find("\n", index)
            index = len(sql) if newline == -1 else newline
        else:
            out.append(char)
            index += 1
    return "".join(out)


@dataclass
class _ScanState:
    """The running state a top-level-semicolon scan carries from one line to the next.

    A plain mutable object rather than several closed-over locals, so `_scan_line` can update
    it in place and the caller's loop stays a loop over lines instead of a loop that also has to
    thread four return values back into itself each iteration.

    `remainder_segment_started_in_string` is a separate fact from `in_string`, and conflating
    them is the bug this comment exists to prevent a future edit from reintroducing: `in_string`
    is the quote state *right now*, while this field is whether the text segment that will
    become this line's `remainder` — the part after the most recent reset, whether that reset
    was the top of the line or a semicolon partway through it — began inside a string. A
    semicolon can close a statement and start a new, empty segment in the middle of a line
    whose own *entry* state said "inside a string"; from that point to the end of the line,
    until that segment actually opens a new string of its own, it did not begin inside one, and
    using the line's entry fact there let a trailing empty remainder survive as a spurious
    statement.
    """

    statements: list[str]
    current: list[str]
    depth: int
    in_string: bool
    remainder_segment_started_in_string: bool = False


def _scan_line(state: _ScanState, raw_line: str) -> None:
    """Advance `state` by one line: track quote/paren depth, and close a statement at every
    top-level semicolon this line contains.

    A parenthesis or semicolon inside a single-quoted string is not a structural character and
    must never be counted as one — a literal containing either would otherwise desynchronize
    the depth counter or split a statement in half, which is why quote state is checked before
    anything else on every character.

    Whitespace gets the same care, and a single start-of-line flag is not enough to give it:
    this line's *leading* whitespace is safe to strip only if the scan enters the line outside
    a string, and its *trailing* whitespace is safe to strip only if the scan leaves the line
    outside a string — those are two independent facts, since a line can start outside a
    string, open one partway through, and end still inside it (leading whitespace is
    formatting; trailing whitespace is now part of the literal's value). Deciding stripping for
    the whole line from either fact alone gets one of those two cases wrong.
    """
    entered_in_string = state.in_string
    # A first pass purely to learn the quote state at the END of the line, without yet deciding
    # what to strip — trailing-whitespace safety depends on that end state, which is not known
    # until the whole line has been scanned once.
    trial_in_string = entered_in_string
    for char in raw_line:
        if char == "'":
            trial_in_string = not trial_in_string
    left = 0 if entered_in_string else len(raw_line) - len(raw_line.lstrip())
    right = len(raw_line) if trial_in_string else len(raw_line.rstrip())
    text = raw_line[left : max(left, right)]

    state.remainder_segment_started_in_string = state.in_string
    line_start = 0
    for position, char in enumerate(text):
        if char == "'":
            state.in_string = not state.in_string
        elif state.in_string:
            continue
        elif char == "(":
            state.depth += 1
        elif char == ")":
            state.depth -= 1
            if state.depth < 0:
                raise DesignTableError(f"unbalanced parentheses in SQL block: {raw_line!r}")
        elif char == ";" and state.depth == 0:
            state.current.append(text[line_start : position + 1])
            state.statements.append("\n".join(state.current))
            state.current = []
            state.remainder_segment_started_in_string = state.in_string
            line_start = position + 1
    remainder = text[line_start:]
    # An ordinary remainder that carries nothing is safe to drop. A remainder that is empty but
    # belongs to a segment which STARTED inside a string is different — an entirely blank line
    # sitting inside a multiline literal is itself part of the literal's value (it is the
    # `\n\n` between two non-blank lines), and dropping it here would lose that newline when
    # `"\n".join(state.current)` reconstructs the statement. The check is against
    # `remainder_segment_started_in_string`, not the line's own entry state: a semicolon
    # earlier in this same line can have reset `current` to a fresh, empty segment that never
    # opened a string at all, and using the line's entry fact there would append a spurious
    # empty element to the segment that follows the semicolon, surviving as an extra, empty
    # statement.
    if remainder != "" or state.remainder_segment_started_in_string:
        state.current.append(remainder)


def sql_statements(sql: str) -> list[str]:
    """Split a fenced SQL block into its individual statements, comments and blank lines gone.

    A statement ends at a top-level semicolon **or** a blank line — `schema.md`'s DDL block uses
    both conventions, a semicolon after three one-line `PRAGMA`s and a blank line between the
    longer `CREATE` statements — so both are accepted, and a nesting-depth check refuses to split
    inside an unbalanced parenthesis rather than guessing. Lines are joined with a newline, not a
    forced space, because a design line that wraps immediately after an open paren has no space
    there to begin with; `normalize_sql` below normalizes the newline itself, so two statements
    differing only in how the design wrapped them still compare equal.
    """
    uncommented = _strip_sql_comments(sql)
    state = _ScanState(statements=[], current=[], depth=0, in_string=False)
    for raw_line in uncommented.splitlines():
        stripped = raw_line.strip()
        if stripped == "" and state.depth == 0 and not state.in_string:
            if state.current:
                state.statements.append("\n".join(state.current))
                state.current = []
            continue
        _scan_line(state, raw_line)
    if state.depth != 0:
        raise DesignTableError("SQL block ends with unbalanced parentheses")
    if state.in_string:
        raise DesignTableError("SQL block ends with an unterminated string literal")
    if state.current:
        state.statements.append("\n".join(state.current))
    return [normalize_sql(statement) for statement in state.statements]


def normalize_sql(statement: str) -> str:
    """Collapse whitespace so two statements differing only in *how* the source wrapped their
    lines compare equal, while a real content difference — a changed literal, a missing column,
    a reordered clause — still does not.

    `schema.md` sometimes writes one value per line with a trailing comment, which a plain
    whitespace collapse turns into a space where a flat, uncommented transcription has none —
    `CHECK (source IN (\\n 'fetch', ...` versus `CHECK (source IN ('fetch', ...`. Stripping
    whitespace that sits directly against a paren or before a comma removes exactly that
    formatting difference — but only **outside** a single-quoted string: `'a  b'` and `'a b'`
    are different string values, and `'a( b'` is a different string value from `'a(b'`, so this
    function must never rewrite a byte that sits between two unescaped `'` characters. Exposed
    for a caller comparing a hand-written literal against `sql_statements`'s own output, since
    both sides need the same normalization or a wrapping difference on one side alone would
    look like content drift.
    """
    without_trailing_semicolon = statement.rstrip().removesuffix(";")
    out: list[str] = []
    in_string = False
    index = 0
    length = len(without_trailing_semicolon)
    while index < length:
        char = without_trailing_semicolon[index]
        if char == "'":
            in_string = not in_string
            out.append(char)
            index += 1
        elif in_string:
            out.append(char)
            index += 1
        elif char.isspace():
            end = index
            while end < length and without_trailing_semicolon[end].isspace():
                end += 1
            before = out[-1] if out else ""
            after = without_trailing_semicolon[end] if end < length else ""
            if before not in ("(", "") and after not in (")", ",", ""):
                out.append(" ")
            index = end
        else:
            out.append(char)
            index += 1
    return "".join(out).strip()


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


def fenced_code(document: str, heading: str, language: str) -> str:
    """The one fence tagged ` ```{language} ` in one section of a design document, with its
    opening/closing lines cut — `language=""` for an untagged fence, as `write-policy.md`'s own
    prompt block uses (a bare ` ``` `, no language identifier, since the block is prose to be
    printed verbatim rather than a language a syntax highlighter should format)."""
    try:
        return parse_fenced_code(section_lines(document, heading), language)
    except DesignTableError as error:
        raise _located(document, heading, error) from error


def block_quote(document: str, heading: str, opening: str) -> str:
    """The one block quote in one section of a design document that opens with `opening`."""
    try:
        return parse_block_quote(section_lines(document, heading), opening)
    except DesignTableError as error:
        raise _located(document, heading, error) from error


def couplings(document: str, heading: str) -> dict[str, str]:
    """The store-coupling severities stated in one section of a design document."""
    try:
        return parse_couplings(section_lines(document, heading))
    except DesignTableError as error:
        raise _located(document, heading, error) from error
