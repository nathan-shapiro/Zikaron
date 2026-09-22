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
_MATRIX_SCRIPT: Final = _ROOT / "check-matrix.sh"
_STANDARDS: Final = _ROOT / "design" / "coding-standards.md"
_README: Final = _ROOT / "README.md"

#: A `--cov=zikaron/<package>` flag as `check.sh` spells it.
_COV_FLAG: Final = re.compile(r"--cov=zikaron/([A-Za-z_]+)")

#: The floor as `coding-standards.md` states it, in the one sentence that states it.
_STATED_FLOOR: Final = re.compile(r"The floor is \*\*(\d+)%\*\*")

#: The version list as `check-matrix.sh` spells it, in the one array that drives the loop.
_MATRIX_MINORS: Final = re.compile(r"^minors=\(([^)]*)\)", re.MULTILINE)

#: The tested set as prose states it, in the one sentence each of `coding-standards.md` and
#: `README.md` uses. Both are checked, because a reader picks whichever document they opened.
#:
#: Each version is matched as a dotted pair rather than as a run of digits, dots and commas: the
#: looser form has to be non-greedy to avoid swallowing the sentence's final full stop, and then it
#: stops at the *first* dot instead — parsing "3.12, 3.13, 3.14." as the single version "3", which
#: reads as a plausible list right up to the comparison.
_STATED_TESTED_SET: Final = re.compile(r"[Tt]ested versions: (\d+\.\d+(?:, \d+\.\d+)*)\.")


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


def _matrix_versions() -> list[str]:
    """The versions `check-matrix.sh` actually loops over, read from the script."""
    found = _MATRIX_MINORS.search(_MATRIX_SCRIPT.read_text(encoding="utf-8"))
    assert found is not None, (
        "check-matrix.sh no longer declares its version list as `minors=(...)`"
    )
    return found.group(1).split()


def _stated_versions(document: Path) -> list[str]:
    """The tested set as one document states it in prose."""
    stated = _STATED_TESTED_SET.search(document.read_text(encoding="utf-8"))
    assert stated is not None, f"{document.name} no longer states the tested versions"
    return [part.strip() for part in stated.group(1).split(",")]


def test_the_matrix_runs_exactly_the_versions_the_prose_calls_tested() -> None:
    """Three statements of one list — the script, the standards, the README — and a reader trusts
    whichever they happened to open. Which versions are tested is also what "supported" means, so
    a version quietly dropped from the script would narrow a promise made in two documents."""
    running = _matrix_versions()
    assert running == _stated_versions(_STANDARDS)
    assert running == _stated_versions(_README)


def test_the_version_discovery_can_actually_see_a_version() -> None:
    """Both oracles above compare parsed lists, so two empty parses would agree and pass."""
    assert "3.12" in _matrix_versions()
    assert "3.12" in _stated_versions(_STANDARDS)
    assert "3.12" in _stated_versions(_README)


def test_the_floor_the_standards_state_is_the_one_the_packaging_requires() -> None:
    """`requires-python` and §6's floor sentence are two statements of one number."""
    configured = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert configured["project"]["requires-python"] == ">=3.12"
    assert "`>=3.12`" in _STANDARDS.read_text(encoding="utf-8")


def test_the_project_table_still_holds_the_keys_a_later_table_can_swallow() -> None:
    """Every key after a TOML table header belongs to that header, so a table inserted in the middle
    of `[project]` silently moves everything below it.

    Observed: placing `[project.urls]` under `license-files` absorbed `requires-python` *and*
    `dependencies` into it. The file parsed. The editable install succeeded. The package simply had
    no dependencies and no interpreter floor. The test above would have caught the floor by
    `KeyError`; nothing at all pinned the dependency list, which is the half that would have
    shipped.

    Checked by shape rather than by contents — the four runtime pins are stated in `pyproject.toml`
    with their reasons and this file is not a second copy of them. What is asserted is that they are
    still *in `[project]`*, which is the property an inserted table destroys.
    """
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    for key in ("name", "version", "readme", "license", "requires-python", "dependencies"):
        assert key in project, f"`{key}` has left [project] — a table header was inserted above it"
    assert len(project["dependencies"]) == 4, "the runtime dependency list changed size"
    assert set(project["scripts"]) == {"zikaron-hook", "zikaron-mcp"}
