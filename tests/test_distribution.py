"""What the published artefacts contain, checked by building them.

**This is the one place the publication sweep's conclusions could be quietly undone.**
`test_publication_hygiene.py` asserts that nothing under `zikaron/` carries a machine-local path,
which holds because the evidence directories are outside the package. That argument is only as good
as those directories staying out of the distribution — and what keeps them out is setuptools'
defaults, which no file in this repository states and any future `MANIFEST.in` could reverse.

**Built rather than reasoned about.** `packages.find` restricting the wheel to `zikaron*` is easy to
read and says nothing about the sdist, which has its own inclusion rules. The only honest check is
to build both and look.

**`--no-isolation`, so the build uses this virtualenv's own pinned `setuptools` and reaches no
network.** With isolation, `build` creates a fresh environment and downloads the backend, which
would make a hermetic suite depend on PyPI being up.
"""

import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from tests.test_publication_hygiene import _FORBIDDEN_LITERALS

_ROOT: Final = Path(__file__).resolve().parent.parent

#: Directories that exist to hold evidence and must never be installed. `research/` and `spikes/`
#: quote machine-local paths by design, `.kiro/` is one machine's real installed output, and the
#: `FINDINGS` files quote the strings the sweep counts.
_MUST_NOT_SHIP: Final = ("research", "reviews", "experiments", "spikes", ".kiro", "design")

_MUST_NOT_SHIP_FILES: Final = ("FINDINGS.md", "FINDINGS-archive.md", "CLAUDE.md")


def test_the_build_backend_is_installed_at_the_version_the_backend_pin_names() -> None:
    """Two statements of one version, and the failure of the second is a build that cannot run.

    `build --no-isolation` resolves `[build-system] requires` against the running environment, so
    the `dev` extra must carry the same pin. Neither `uv venv --seed` nor `python -m venv` seeds
    setuptools on 3.12+, so "it works here" is a fact about one machine until this holds.
    """
    declared = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    (backend,) = declared["build-system"]["requires"]
    assert backend in declared["project"]["optional-dependencies"]["dev"], (
        f"the dev extra does not pin {backend}, so `build --no-isolation` has no backend to use"
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The sdist and the wheel this tree produces, built once for the module.

    **Built from a copy, not from the live tree.** The sdist step rewrites `zikaron.egg-info/` at
    the project root, which is the one directory `check-matrix.sh` already identifies as the race
    between concurrent editable installs — and under `--parallel` three interpreters reach this
    fixture at about the same moment. The copy keeps the evidence directories, since their absence
    from the artefacts is the thing under test.
    """
    source = tmp_path_factory.mktemp("source") / "tree"
    shutil.copytree(
        _ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv*",
            "build",
            "dist",
            "*.egg-info",
            ".zikaron",
            "__pycache__",
            ".mypy_cache",
        ),
    )
    out = tmp_path_factory.mktemp("dist")
    completed = subprocess.run(  # noqa: S603 — a fixed, test-constructed interpreter path.
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(out), str(source)],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    (sdist,) = out.glob("*.tar.gz")
    (wheel,) = out.glob("*.whl")
    return sdist, wheel


def _sdist_names(sdist: Path) -> Iterator[str]:
    with tarfile.open(sdist) as archive:
        for name in archive.getnames():
            # Every sdist member sits under one `<name>-<version>/` root; the paths that matter are
            # the ones below it.
            yield name.partition("/")[2]


def _wheel_names(wheel: Path) -> Iterator[str]:
    with zipfile.ZipFile(wheel) as archive:
        yield from archive.namelist()


@pytest.mark.parametrize("directory", _MUST_NOT_SHIP)
def test_no_evidence_directory_reaches_either_artefact(
    built: tuple[Path, Path], directory: str
) -> None:
    sdist, wheel = built
    for label, names in (("sdist", _sdist_names(sdist)), ("wheel", _wheel_names(wheel))):
        offenders = [name for name in names if name.startswith(f"{directory}/")]
        assert not offenders, f"{label} ships {directory}/: {offenders[:5]}"


@pytest.mark.parametrize("filename", _MUST_NOT_SHIP_FILES)
def test_no_working_document_reaches_either_artefact(
    built: tuple[Path, Path], filename: str
) -> None:
    """`FINDINGS.md` and `CLAUDE.md` quote the machine-local strings the sweep counts, so they are
    the working record rather than documentation of the product."""
    sdist, wheel = built
    for label, names in (("sdist", _sdist_names(sdist)), ("wheel", _wheel_names(wheel))):
        assert filename not in set(names), f"{label} ships {filename}"


def test_the_artefacts_carry_the_package_and_its_marker(built: tuple[Path, Path]) -> None:
    """The oracle above passes trivially over an empty archive, which is how a build that produced
    nothing useful would look identical to a clean one."""
    _sdist, wheel = built
    names = set(_wheel_names(wheel))
    assert "zikaron/cli/main.py" in names
    assert "zikaron/doctor/checks.py" in names
    assert "zikaron/py.typed" in names


def test_the_wheel_declares_every_console_script(built: tuple[Path, Path]) -> None:
    """The front door has to survive packaging, and an entry point is metadata rather than code —
    nothing that imports the package would notice its absence."""
    _sdist, wheel = built
    with zipfile.ZipFile(wheel) as archive:
        (entry_points,) = [n for n in archive.namelist() if n.endswith("entry_points.txt")]
        declared = archive.read(entry_points).decode()
    for script in ("zikaron =", "zikaron-hook =", "zikaron-mcp ="):
        assert script in declared, f"{script.rstrip(' =')} is not in the built wheel"


def test_nothing_published_names_this_machine(built: tuple[Path, Path]) -> None:
    """The publication guarantee, stated over what is actually published.

    **`test_publication_hygiene.py` scans `zikaron/` and the sdist ships more than that** — `tests/`
    travels with it, and that file's own docstring records that it deliberately does not scan
    `tests/`. So the guarantee everyone reasons about had a gap exactly the size of the difference.
    Reading the built archives closes it by construction: whatever setuptools decides to include is
    what gets scanned, so a future `MANIFEST.in` cannot widen the distribution past the guard.

    The patterns are imported rather than restated, because two copies of a forbidden-string list
    is how one of them goes stale.
    """
    sdist, wheel = built
    offenders = []
    with tarfile.open(sdist) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            assert handle is not None
            text = handle.read().decode("utf-8", errors="replace")
            offenders += [f"sdist:{member.name}" for p in _FORBIDDEN_LITERALS if p.search(text)]
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            text = archive.read(name).decode("utf-8", errors="replace")
            offenders += [f"wheel:{name}" for p in _FORBIDDEN_LITERALS if p.search(text)]
    assert not offenders, f"the published artefacts carry machine-local strings: {offenders[:10]}"


def test_the_licence_ships(built: tuple[Path, Path]) -> None:
    """`license-files` is what puts it in the wheel's metadata directory; MIT requires the text to
    travel with the distribution."""
    _sdist, wheel = built
    assert any(name.endswith("licenses/LICENSE") for name in _wheel_names(wheel))
