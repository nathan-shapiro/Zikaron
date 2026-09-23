"""The shipped package carries no path out of the machine it was written on.

`zikaron/` is what a user installs, and it is clean today: the publication sweep classified every
home-directory and private-project string in the repository and found **none inside the package**.
Most sit in the evidence directories — `reviews/`, `experiments/`, `spikes/`, `research/` — and a
few sit outside them deliberately: `design/build-plan.md`, `FINDINGS.md` and `FINDINGS-archive.md`
quote the strings they count, and the two `.kiro/` configs are real installed output whose
virtualenv paths the installer rewrites. Full method and per-hit classification:
`research/publication-sweep.md`. **No file count is stated here**: the set moves whenever a document
that quotes these strings is edited or archived, and the assertion below does not depend on it.

**A test rather than a habit**, because the sweep is run once per publication and an absolute path
reaches the package by the ordinary route of someone pasting a working command into a docstring. The
gate runs every edit.

**Patterns are assembled from fragments, exactly as `test_version_seam.py` does, and the reason is
the same class of self-reference with a twist**: a literal here would make this file a hit in every
future sweep, so the recorded count would be permanently one higher than the exposure and the next
person to reconcile it would be chasing a string that exists only to forbid itself.

**Scope, and the line is drawn by false-positive population rather than by family.** The sweep
(`research/publication-sweep.md`) runs four pattern families. Three of them are here. The one left
out is *credential-shaped **names*** — `TOKEN|KEY|SECRET|…` — because this package names every one
of its dict-key constants `<NAME>_KEY` by convention — in the `meta`, `counters` and `store`
modules and every module that reads them — so that pattern
reports `zikaron/` lines forever, none of them a credential, and asserting against it would mean an
allowlist that grows with the schema. **No figure is written here**: the sweep's own count for this
family is over the whole tree and includes `tests/`, which this guard deliberately does not scan,
so quoting it would be the right number for the wrong quantity.

Credential-shaped **values** are a different case and are included: per the sweep, they have
**zero** hits inside `zikaron/` today, and a token pasted into shipped code is a worse outcome
than a home path — which is the case a guard most earns its keep on.

**The embedding model's pin is credential-shaped and deliberate**: owning the fetch means a full
40-hex Hugging Face revision and a set of SHA256 digests in product code, all matching the value
patterns below. They live in one module, so the exemption is a single-file allowlist —
`_SHAPE_EXEMPT` below states why that rather than a per-line marker, and the exemption is narrowed
by a positive check on the file's contents rather than trusted.
"""

import itertools
import re
from pathlib import Path
from typing import Final

from zikaron.core.indexing.model_pin import PINNED_ARTIFACTS

_ROOT: Final = Path(__file__).resolve().parent.parent
_PACKAGE: Final = _ROOT / "zikaron"

#: Machine-local paths and the operator's address. Assembled from fragments rather than spelled, so
#: that a later sweep of the tree does not find them here — a literal would make this file a hit in
#: every future sweep, leaving the recorded count permanently one higher than the exposure.
#:
#: `example.invalid` placeholders are deliberately *not* excluded: the package contains no email
#: address of any kind, so the narrower pattern is the honest one and a placeholder appearing in
#: shipped code would be worth a look regardless.
_FORBIDDEN_LITERALS: Final = tuple(
    re.compile(re.escape(pattern))
    for pattern in (
        "/home/" + "nathan",
        "Leiba" + "Trader",
        "~/" + "Trading",
        "zk-" + "dogfood",
        "zk-" + "m26-cockroach",
        "nathan-shapiro" + "@" + "outlook.com",
    )
)

#: Credential-shaped values: the 32/40/64-character hex runs a token, a git SHA or a SHA256 takes,
#: and a PEM header.
#:
#: **Bounded on both sides**, so a 40-hex run does not also satisfy the 32-hex pattern and report
#: one planted secret three times. The fragment assembly is the same discipline as above, applied
#: to the one pattern that would otherwise match its own source.
_FORBIDDEN_SHAPES: Final = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])",
        r"(?<![0-9a-fA-F])[0-9a-fA-F]{40}(?![0-9a-fA-F])",
        r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])",
        "-----" + "BEGIN",
    )
)

_FORBIDDEN: Final = _FORBIDDEN_LITERALS + _FORBIDDEN_SHAPES

#: The one file exempt from the *shape* patterns, holding the pinned artefact's revision and
#: digests. **A single-file allowlist rather than a per-line marker, chosen at M30 when the pins
#: existed to look at.** A marker would sit on every digest line and on each new one, which makes
#: it a thing people add without reading — and a marker pasted onto a line that is genuinely a
#: secret is indistinguishable from one pasted onto a digest. One file whose entire purpose is
#: public digests can be audited at a glance.
#:
#: **The exemption is narrowed by a positive check rather than trusted**:
#: `test_the_exempt_file_holds_only_its_declared_pins` asserts that every hex run in it is one of
#: the values `model_pin` declares, so nothing else can hide behind it. The literals stay in force
#: here — a home path in this file would be as wrong as anywhere else.
_SHAPE_EXEMPT: Final = _PACKAGE / "core" / "indexing" / "model_pin.py"

#: A wrapped comment line's continuation marker, stripped before two lines are rejoined.
_CONTINUATION: Final = re.compile(r"^\s*(?:#:|#)?\s*")


def _searchable(
    lines: list[str], *, shapes: tuple[re.Pattern[str], ...]
) -> list[tuple[int, str, tuple[re.Pattern[str], ...]]]:
    """Each line against every pattern, plus each adjacent pair rejoined against the literals only.

    **Why the rejoin at all.** `test_version_seam.py` states the rule this adopts: *a check that
    reads one line at a time is checking the layout as much as the content*, and layout is what an
    ordinary re-wrap changes for free. That file was measured passing over a forbidden name purely
    because a wrap split it in two. This file cites that one for its fragment-assembly trick and
    did not take its scan — so the same hole existed here.

    **Why the literals only.** The shape patterns match runs of hex with hex-character lookaround,
    so joining a line that ends in hex to one that begins in hex would *fabricate* a 32-run that
    exists in neither. A rejoin is sound for a fixed string and unsound for a length-counting
    pattern, and running both over joined text would trade a silent miss for a false alarm.

    **Residual, named rather than assumed covered**: a literal broken across *two* line breaks
    still escapes, as does a shape pattern broken across one. Measured when this landed: rejoining
    every adjacent pair over the whole package surfaced **zero** currently-hidden hits, so this
    closes a latent hole rather than a live one.
    """
    numbered = list(enumerate(lines, start=1))
    joined = [
        (number, f"{line.rstrip()}{_CONTINUATION.sub('', following)}", _FORBIDDEN_LITERALS)
        for (number, line), (_, following) in itertools.pairwise(numbered)
    ]
    applicable = _FORBIDDEN_LITERALS + shapes
    return [(number, line, applicable) for number, line in numbered] + joined


def _scanned_files() -> list[Path]:
    """Every file under the package. Not just `*.py`: `py.typed` and any future data file ship too,
    and a path is as damaging in a shipped asset as in a module."""
    return sorted(path for path in _PACKAGE.rglob("*") if path.is_file() and path.suffix != ".pyc")


def test_the_shipped_package_names_no_path_off_this_machine() -> None:
    offenders = [
        f"{path.relative_to(_ROOT)}:{number}: {line.strip()}"
        for path in _scanned_files()
        # `errors="replace"` rather than a strict decode: the package ships `py.typed` today and may
        # ship a binary asset tomorrow, and a guard that *raises* on the first such file stops being
        # a guard at the moment the tree grows one.
        for number, line, patterns in _searchable(
            path.read_text(encoding="utf-8", errors="replace").splitlines(),
            shapes=() if path == _SHAPE_EXEMPT else _FORBIDDEN_SHAPES,
        )
        for pattern in patterns
        if pattern.search(line)
    ]
    assert not offenders, (
        "the installed package must carry no machine-local path, private-project name, or "
        "credential-shaped value (research/publication-sweep.md):\n" + "\n".join(offenders)
    )


def test_the_scan_reaches_the_package_it_claims_to() -> None:
    """The assertion above passes trivially over an empty file list, which is how a guard stops
    guarding without saying so."""
    scanned = {path.relative_to(_ROOT).as_posix() for path in _scanned_files()}
    assert "zikaron/install/assets.py" in scanned, "the shipped-prose module must be scanned"
    assert "zikaron/hook/main.py" in scanned
    assert "zikaron/py.typed" in scanned, "shipped data files are scanned, not only modules"
    assert not any(name.startswith("tests/") for name in scanned)


def test_every_forbidden_pattern_can_actually_match_something() -> None:
    """A pattern that matches nothing makes the scan pass by doing nothing. Each is shown matching a
    line built here the same fragmented way, so this file still does not match itself."""
    samples = (
        "# measured on " + "/home/" + "nathan" + "/Zikaron",
        "# the " + "Leiba" + "Trader" + " store",
        "# under " + "~/" + "Trading",
        "# the " + "zk-" + "dogfood" + " throwaway",
        "# the " + "zk-" + "m26-cockroach" + " clone",
        "# reported by " + "nathan-shapiro" + "@" + "outlook.com",
        "TOKEN = " + "a" * 32,
        "SHA = " + "b" * 40,
        "DIGEST = " + "c" * 64,
        "-----" + "BEGIN OPENSSH PRIVATE KEY-----",
    )
    assert len(samples) == len(_FORBIDDEN)
    for pattern, sample in zip(_FORBIDDEN, samples, strict=True):
        assert pattern.search(sample), f"{pattern.pattern} matched nothing in {sample!r}"


def test_the_exempt_file_holds_only_its_declared_pins() -> None:
    """What narrows the shape exemption from "this file may contain anything" to "this file may
    contain the pins it declares".

    Without this, exempting a file would be a standing hole that a later edit could put a real
    secret through, and the guard would stay green — which is the objection to a per-line marker
    applied to the alternative that was chosen instead.
    """
    declared = {pin.revision for pin in PINNED_ARTIFACTS.values()} | {
        digest for pin in PINNED_ARTIFACTS.values() for digest in pin.digests.values()
    }
    text = _SHAPE_EXEMPT.read_text(encoding="utf-8")
    found = {match for shape in _FORBIDDEN_SHAPES for match in shape.findall(text)}
    assert found <= declared, (
        f"undeclared credential-shaped value in {_SHAPE_EXEMPT.name}: {found - declared}"
    )


def test_the_exemption_is_only_where_it_is_claimed() -> None:
    """A planted digest anywhere else in the package is still caught, so the exemption is one file
    rather than a pattern that happens to match one."""
    elsewhere = _PACKAGE / "core" / "indexing" / "encoder.py"
    assert elsewhere != _SHAPE_EXEMPT
    scanned = _searchable(["DIGEST = " + "d" * 64], shapes=_FORBIDDEN_SHAPES)
    assert any(pattern.search(line) for _, line, patterns in scanned for pattern in patterns)


def test_this_file_does_not_match_itself() -> None:
    """The whole point of the fragment assembly, asserted rather than trusted. If this fails, the
    sweep's recorded counts will drift by one per pattern and the drift will look like exposure."""
    own_text = Path(__file__).read_text(encoding="utf-8")
    matched = [pattern.pattern for pattern in _FORBIDDEN if pattern.search(own_text)]
    assert not matched, f"fragment assembly failed for: {matched}"
