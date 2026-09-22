"""`README.md`'s configuration table, checked against the keys it describes.

**This is the third and fourth copy of one set of facts**, and the ones nobody edits.
`zikaron/core/config/keys.py` declares the bounds, `design/schema.md` restates them for the design
record — guarded by `test_config_keys.py` — and `README.md` restates them again for a reader who
will never open either. Measured when that third copy was finally read against the first: two
penalties documented as accepting `0.0` that the code refuses outright, and five keys whose Range
column was an em dash beside a real enforced range. Every one of those would have cost a user a
service that refuses to start, with the README saying the value was fine.

**Numeric rows only.** The string and free-text rows describe their ranges in prose a reader needs
rather than in a notation, so they are listed by name and asserted to be *absent* from the numeric
set instead — which still fails loudly if one of them ever gains real bounds.
"""

import re
from pathlib import Path
from typing import Final

import pytest

from tests.design_tables import EN_DASH
from zikaron.core.config.keys import (
    CONFIG_KEYS_BY_NAME,
    ConfigBounds,
    FloatBounds,
    IntBounds,
    StoreCoupling,
)

README: Final = Path(__file__).resolve().parent.parent / "README.md"
HEADING: Final = "### Everything that is tweakable"

#: The section the worked `config.toml` lives in, and where the example test below slices from.
#: **It is not `HEADING`**: the example block sits *above* that subheading, so anchoring the example
#: on the same string the table uses would have found no block at all and the test would have failed
#: on its own assertion rather than on a defect. Stated because a sweep round proposed exactly that
#: fix, reasoning from the file's other tests without reading the README's order — a suggested
#: replacement is a claim like any other.
EXAMPLE_SECTION: Final = "## Configuration"
COLUMNS: Final = ("Section", "Key", "Default", "Range", "What it does")

#: The keys whose Range cell is deliberately prose. Each is a string key with no numeric bound, so
#: a notation would be worse than the sentence. **Written out rather than derived from the code**,
#: because deriving it would make the exemption follow whatever the code does and guard nothing —
#: a key that gained a numeric range would quietly leave the set and take its README row with it.
#: The test below reconciles this literal against the code, which is the half that bites.
PROSE_RANGE_KEYS: Final = frozenset({"embed_model", "embed_prefix_query"})

#: Imported rather than redeclared: `test_config_keys.py` parses the same notation out of
#: `design/schema.md`, and a second copy of the character would let the two guards disagree about
#: what a range separator is — the two-sites failure this corpus keeps recording.
_AT_LEAST: Final = "≥"


def _table_rows() -> list[dict[str, str]]:
    """The one table under `HEADING`, as a list of column-name → cell-text dicts."""
    lines = README.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(HEADING)
    except ValueError:  # pragma: no cover - the heading is asserted to exist below
        raise AssertionError(f"README.md has no {HEADING!r} section") from None
    rows: list[dict[str, str]] = []
    header: tuple[str, ...] | None = None
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if header is None:
            header = cells
            continue
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(dict(zip(header, cells, strict=True)))
    assert header == COLUMNS, f"README config table columns are {header}, expected {COLUMNS}"
    return rows


def _bare(cell: str) -> str:
    """A cell's text with the backticks and bold markers the table uses for emphasis removed."""
    return cell.replace("`", "").replace("**", "").strip()


def _expected_range(bounds: ConfigBounds) -> str:
    """How this README table writes the range a key actually enforces.

    One function rather than a parser, because the table is written for a reader: generating the
    expected string and comparing it is what makes an *unwritten* convention impossible, where a
    tolerant parser would accept three spellings of one bound and guard none of them.
    """
    if isinstance(bounds, IntBounds):
        if bounds.maximum is None:
            return f"{_AT_LEAST} {bounds.minimum}"
        return f"{bounds.minimum}{EN_DASH}{bounds.maximum}"
    if isinstance(bounds, FloatBounds):
        low = f"{bounds.minimum}" if bounds.minimum_inclusive else f">{bounds.minimum}"
        high = f"{bounds.maximum}" if bounds.maximum_inclusive else f"<{bounds.maximum}"
        return f"{low}{EN_DASH}{high}"
    raise AssertionError(f"no README notation defined for {bounds!r}")


@pytest.fixture(scope="module")
def rows() -> dict[str, dict[str, str]]:
    parsed = _table_rows()
    assert parsed, "README config table is empty"
    return {_bare(row["Key"]): row for row in parsed}


def test_every_documented_key_exists(rows: dict[str, dict[str, str]]) -> None:
    """A row naming a key the code does not have sends a reader to edit nothing."""
    unknown = sorted(set(rows) - set(CONFIG_KEYS_BY_NAME))
    assert not unknown, f"README documents keys that do not exist: {unknown}"


def test_every_key_is_documented(rows: dict[str, dict[str, str]]) -> None:
    """A key absent from the table is a knob only the source reveals."""
    missing = sorted(set(CONFIG_KEYS_BY_NAME) - set(rows))
    assert not missing, f"README documents no row for: {missing}"


def test_every_numeric_range_matches_the_bounds_the_code_enforces(
    rows: dict[str, dict[str, str]],
) -> None:
    """The failure this file exists for: a range a user can read and the service will refuse.

    Checked for every numeric key at once rather than one assertion per key, so the report names
    the whole drifted set instead of stopping at the first.
    """
    wrong: list[str] = []
    for name, row in rows.items():
        if name in PROSE_RANGE_KEYS:
            continue
        expected = _expected_range(CONFIG_KEYS_BY_NAME[name].bounds)
        if _bare(row["Range"]) != expected:
            wrong.append(f"{name}: README says {_bare(row['Range'])!r}, code enforces {expected!r}")
    assert not wrong, "README ranges disagree with the code:\n" + "\n".join(wrong)


def test_every_documented_default_is_the_default_the_code_ships(
    rows: dict[str, dict[str, str]],
) -> None:
    """A default is the other half a reader acts on, and it drifts the same way a range does.

    Prose-range rows describe their default in words (`a retrieval instruction`) for the same
    reason their range is prose, so they are exempt here too.
    """
    wrong: list[str] = []
    for name, row in rows.items():
        if name in PROSE_RANGE_KEYS:
            continue
        shipped = CONFIG_KEYS_BY_NAME[name].default
        documented = _bare(row["Default"])
        if documented != str(shipped):
            wrong.append(f"{name}: README says {documented!r}, code ships {shipped!r}")
    assert not wrong, "README defaults disagree with the code:\n" + "\n".join(wrong)


def test_the_prose_range_exemption_is_exactly_the_keys_with_no_numeric_bounds() -> None:
    """The exemption is not a hiding place, in either direction.

    A key that gains a numeric range must lose its exemption and have that range written into the
    README; a key that loses one must gain the sentence. Reconciling the literal above against the
    code catches both, where a derived set would silently follow whichever way the code moved —
    the shape of every drift this file was written after.
    """
    without_numeric_bounds = {
        name
        for name, key in CONFIG_KEYS_BY_NAME.items()
        if not isinstance(key.bounds, IntBounds | FloatBounds)
    }
    assert without_numeric_bounds == PROSE_RANGE_KEYS, (
        f"the exempt set is {sorted(PROSE_RANGE_KEYS)} but the keys with no numeric bound are "
        f"{sorted(without_numeric_bounds)}; README's Range column must follow"
    )


def test_the_section_column_names_each_key_s_real_section(
    rows: dict[str, dict[str, str]],
) -> None:
    """A key filed under the wrong section is un-findable in the file a user actually edits."""
    wrong: list[str] = []
    for name, row in rows.items():
        section = CONFIG_KEYS_BY_NAME[name].section.value
        if _bare(row["Section"]) != section:
            wrong.append(f"{name}: README says {_bare(row['Section'])!r}, code says {section!r}")
    assert not wrong, "README sections disagree with the code:\n" + "\n".join(wrong)


def test_every_store_coupled_key_is_marked_as_one_at_its_real_severity(
    rows: dict[str, dict[str, str]],
) -> None:
    """A key coupled to what is already stored, described as though it were free to change.

    **The failure this was written after.** The table marked `embed_model` and `embed_dim`
    `**Store-coupled**` and left `chunk_max_tokens` unmarked, while `keys.py` gives it
    `StoreCoupling.SOFT` and `design/architecture.md` §"What the file cannot change *silently*: the
    store-coupled keys" names **three** dual-homed keys at **two** severities. The prose above the
    table said "Two keys are store-coupled" — and a sweep round rewrote that very sentence for an
    unrelated defect without re-deriving its count, which is how a corrected sentence keeps a wrong
    number.

    **Severity is asserted, not just the flag**, because the two mean opposite things to a reader:
    a hard change means reindexing and, for the memory store, a service that will not start; a soft
    one means new writes are cut differently and nothing else. Marking both the same way would be a
    guard that passes while the table misleads.

    `test_config_keys.py` already pins `keys.py` against the design document. This pins the third
    copy — the one a user actually reads — against `keys.py`, which is what nothing was doing.
    """
    expected = {
        name: f"**Store-coupled ({key.store_coupling.value.lower()})**"
        for name, key in CONFIG_KEYS_BY_NAME.items()
        if key.store_coupling is not StoreCoupling.NONE
    }
    wrong: list[str] = []
    for name, row in rows.items():
        marker = expected.get(name)
        described = row["What it does"]
        if marker is None:
            if "Store-coupled" in described:
                wrong.append(f"{name}: marked store-coupled, but the code couples it to nothing")
        elif marker not in described:
            wrong.append(f"{name}: README should carry {marker!r}, its cell reads {described!r}")
    assert not wrong, "README store-coupling markers disagree with the code:\n" + "\n".join(wrong)


def test_no_range_cell_is_left_as_an_em_dash(rows: dict[str, dict[str, str]]) -> None:
    """An em dash in a Range column reads as *unbounded* beside a table of populated ones.

    Five rows carried one while the code enforced a real range. The generated-string comparison
    above already catches that; this states the rule on its own so the reason survives.
    """
    dashed = sorted(name for name, row in rows.items() if _bare(row["Range"]) in {"—", "-"})
    assert not dashed, f"Range left as an em dash where a real bound exists: {dashed}"


def test_the_example_toml_block_ships_the_defaults_it_claims() -> None:
    """The **fourth** copy of these values — the one this file's own docstring did not know about.

    `README.md` shows a worked `config.toml` under §Configuration whose comments present each line
    as the shipped default. It sits outside the table every other test here parses, so none of them
    could see it: measured when this was written, **five keys** — `fusion_depth`, `rrf_k`,
    `group_max`, `run_lease`, `idle_timeout` — were stated there and guarded nowhere.

    **The lesson is the one at the top of this file, one recursion deeper.** That docstring says
    "this is the third copy … and the third is the one nobody edits". It was the *fourth*, and the
    unguarded one was the example a reader is most likely to copy verbatim into their own config.
    **Counting the copies of a claim is itself a claim**, and this one was short by one.

    **Anchored to `EXAMPLE_SECTION`, and that is the whole of the second fix here.** The first
    version searched the *entire* README for the first ```toml fence. Correct today, because there
    is exactly one — and silently wrong the moment a `pyproject.toml` or `.mcp.json` snippet is
    added anywhere above it, which would move the guard's subject while it stayed green. Requiring
    **exactly one** block inside the section says so out loud instead.
    """
    text = README.read_text(encoding="utf-8")
    start = text.find(f"\n{EXAMPLE_SECTION}\n")
    assert start != -1, f"README.md no longer has a {EXAMPLE_SECTION!r} section"
    end = text.find("\n## ", start + 1)
    section = text[start : end if end != -1 else len(text)]
    blocks = re.findall(r"```toml\n(.*?)```", section, re.DOTALL)
    assert len(blocks) == 1, (
        f"expected exactly one ```toml block under {EXAMPLE_SECTION!r}, found {len(blocks)}"
    )
    shown = dict(
        re.findall(r"^(\w+)\s*=\s*(\S+)", blocks[0], re.MULTILINE),
    )
    assert shown, "the example config.toml block parsed to no settings"
    wrong = [
        f"{name}: the example shows {value}, the code ships {CONFIG_KEYS_BY_NAME[name].default}"
        for name, value in shown.items()
        if name in CONFIG_KEYS_BY_NAME and value != str(CONFIG_KEYS_BY_NAME[name].default)
    ]
    unknown = sorted(set(shown) - set(CONFIG_KEYS_BY_NAME))
    assert not wrong, "the example config.toml disagrees with the code:\n" + "\n".join(wrong)
    assert not unknown, f"the example config.toml sets keys that do not exist: {unknown}"
