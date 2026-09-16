"""The gate measures what it claims to measure, checked against the tree rather than a memory.

**A package nobody names in a `--cov` flag reports nothing at all, rather than reporting zero**, so
its absence from the gate is invisible in a green run and in the coverage table alike. That is not a
hypothetical: `zikaron/knowledge` — the command that creates and builds corpora — shipped a whole
milestone with no floor over it, and the same class of omission had already been caught once before
in the same flags. Both times the fix was to add the flag; this is the fix that makes the next one
fail loudly instead.

The floor itself is checked the same way, against the sentence in `design/coding-standards.md` that
states it, because a ratchet documented in one place and enforced in another is two numbers free to
disagree.
"""

import re
import tomllib
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parent.parent
_PACKAGE_ROOT: Final = _ROOT / "zikaron"
_CHECK_SCRIPT: Final = _ROOT / "check.sh"
_STANDARDS: Final = _ROOT / "design" / "coding-standards.md"

#: A `--cov=zikaron/<package>` flag as `check.sh` spells it.
_COV_FLAG: Final = re.compile(r"--cov=zikaron/([A-Za-z_]+)")

#: The floor as `coding-standards.md` states it, in the one sentence that states it.
_STATED_FLOOR: Final = re.compile(r"The floor is \*\*(\d+)%\*\*")


def _packages() -> set[str]:
    """Every importable package directly under `zikaron/`, from the tree itself."""
    return {
        entry.name
        for entry in _PACKAGE_ROOT.iterdir()
        if entry.is_dir() and (entry / "__init__.py").is_file()
    }


def test_the_gate_measures_every_package_in_the_tree() -> None:
    measured = set(_COV_FLAG.findall(_CHECK_SCRIPT.read_text(encoding="utf-8")))
    assert measured == _packages()


def test_the_discovery_can_actually_see_a_package() -> None:
    """The oracle above is only worth its assertion if it finds packages by looking. This shows it
    finding one — otherwise a discovery that silently returned nothing would make the test pass by
    comparing two empty sets."""
    assert "knowledge" in _packages()
    assert "core" in _packages()


def test_the_configured_floor_is_the_one_the_standards_state() -> None:
    stated = _STATED_FLOOR.search(_STANDARDS.read_text(encoding="utf-8"))
    assert stated is not None, "coding-standards.md no longer states the coverage floor"
    configured = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert configured["tool"]["coverage"]["report"]["fail_under"] == int(stated.group(1))
