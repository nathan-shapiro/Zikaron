"""One module is allowed to know which Python is running. This checks that, by reading the tree.

Two `asyncio` details differ across the Python versions this package supports, and both are read
through `zikaron.service.asyncio_compat`. The value of putting them in one place is entirely in
nothing else doing the same thing somewhere else, and that is not a property any type checker or
ordinary test can see — a second reader of the running version in some other module is perfectly
valid code that passes everything. So it is checked by scanning source text.

**Textual on purpose.** Prose counts: a docstring that still explains the private counter by naming
it is exactly the drift being guarded against, because the next person to read it learns the wrong
place to look. Two consequences follow. The patterns are assembled from fragments rather than
written as literals, so this file does not match itself; and the allowlist is two files, this one
and the module it guards.
"""

import re
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parent.parent
_SEAM: Final = _ROOT / "zikaron" / "service" / "asyncio_compat.py"

#: Assembled rather than spelled, so that scanning this file finds nothing.
#:
#: **Both import styles, because forbidding only the dotted one is an invitation.** `import
#: platform` then `platform.python_version()` is caught by the dotted pattern; `from platform
#: import python_version` then a bare call is not, and it is the more natural thing to write. The
#: same holds for every name under `sys`.
#:
#: **Word-bounded where a boundary exists to find, and deliberately not where it does not.** `_` is
#: a word character, so the pattern for the transport set matches a mention of the attribute while
#: sparing the four test names in this suite that *contain* it and read nothing. For the same
#: reason a trailing boundary after `python_version` would be wrong: it would fail to match
#: `python_version_tuple`, which reads the running version just as surely.
#:
#: **One shape is knowingly not covered**: a parenthesised multi-line `from sys import (` … `)`
#: escapes every pattern here, all of which are line-wise. The linter's import rules keep a short
#: import on one line, so reaching it takes an import list long enough to wrap — narrow enough to
#: name rather than chase, and named here so the next reader does not assume it was missed.
_FORBIDDEN: Final = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bsys\.(" + "version_info|hexversion|version|implementation" + r")\b",
        # `[^#]*` rather than `.*`: a comment mentioning one of these after an innocent import is
        # prose about the subject, not a read of it.
        r"\bfrom sys import\b[^#]*\b(" + "version_info|hexversion|version" + r")\b",
        r"\bplatform\." + "python_version",
        r"\bfrom platform import\b[^#]*" + "python_version",
        # The modules are imported legitimately elsewhere — `sysconfig` for `get_path` — so the
        # functions are what is forbidden, not the imports.
        r"\bsysconfig\.(" + "get_python_version|get_config_var" + r")\b",
        r"\b_" + "active_count" + r"\b",
        r"\b_" + "clients" + r"\b",
    )
)


def _scanned_files() -> list[Path]:
    """Every Python file under the package and its tests, bar the two allowed to match."""
    allowed = {_SEAM.resolve(), Path(__file__).resolve()}
    return sorted(
        path
        for directory in (_ROOT / "zikaron", _ROOT / "tests")
        for path in directory.rglob("*.py")
        if path.resolve() not in allowed
    )


def test_only_the_seam_reads_the_running_python_or_its_private_asyncio_names() -> None:
    offenders = [
        f"{path.relative_to(_ROOT)}:{number}: {line.strip()}"
        for path in _scanned_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for pattern in _FORBIDDEN
        if pattern.search(line)
    ]
    assert not offenders, (
        "version reads and private asyncio names belong only in asyncio_compat:\n"
        + "\n".join(offenders)
    )


def test_the_scan_reaches_the_files_it_claims_to() -> None:
    """The assertion above is worth nothing if the scan finds no files. Two it must reach, and the
    two it must not."""
    scanned = {path.relative_to(_ROOT).as_posix() for path in _scanned_files()}
    assert "zikaron/service/server.py" in scanned
    assert "tests/test_service_server.py" in scanned
    assert "zikaron/service/asyncio_compat.py" not in scanned
    assert "tests/test_version_seam.py" not in scanned


def test_every_forbidden_pattern_can_actually_match_something() -> None:
    """A pattern that matches nothing would make the scan pass by doing nothing, which is how a
    guard quietly stops guarding. Each is shown matching a line written here for the purpose — and,
    because these samples are assembled the same way the patterns are, this file still does not
    match itself."""
    samples = (
        "sys." + "version_info" + "[:2]",
        "from sys import " + "hexversion",
        "platform." + "python_version" + "_tuple()",
        "from platform import " + "python_version",
        "sysconfig." + "get_config_var" + '("py_version_short")',
        "server._" + "active_count",
        "len(server._" + "clients" + ")",
    )
    assert len(samples) == len(_FORBIDDEN)
    for pattern, sample in zip(_FORBIDDEN, samples, strict=True):
        assert pattern.search(sample), f"{pattern.pattern} matched nothing in {sample!r}"


def test_a_word_bounded_pattern_spares_the_test_names_that_merely_contain_clients() -> None:
    """Why the patterns are word-bounded rather than substrings. Four test names in this suite
    contain the second private name and read nothing at all; a substring scan would flag every one,
    and the obvious fix — narrowing to attribute access — would stop the scan seeing prose, which is
    half of what it is for."""
    innocent = "async def test_two" + "_clients" + "_racing_a_cold_store_converge(self) -> None:"
    forbidden = next(
        pattern for pattern in _FORBIDDEN if pattern.pattern.endswith("clients" + r"\b")
    )
    assert not forbidden.search(innocent)
    assert forbidden.search("the `_" + "clients" + "` set")
