"""A quotation attributed to a design document appears in that document.

**This class has produced a finding in three separate sweep rounds and nothing mechanical watched
it.** The corpus's answer was a rule — *where a comment quotes another artefact to justify a
decision, grep the quotation* — which depends on somebody remembering. What was found by
remembering:

- `core/store/permissions.py` quoted `architecture.md` §"Filesystem security" requiring the store's
  resolved parent to be *"the cwd"*, after D17's amendment had replaced that with *"the scope
  directory"* — then glossed the word the amendment removed.
- `tests/test_write_tools.py` credited `architecture.md` with a conflict promise that is
  `build-plan.md` §M6's wording.
- `mcp/connection.py`, a **shipped** module, quoted `architecture.md` as *"Clients retry once…"*
  where the source says *"`zikaron-mcp` retries once"* and its next sentence is *"The hook does
  not"* — a single-subject rule broadened into a universal one the source explicitly refuses.

The last is the shape worth the guard: a misquotation that is *plausible*, that reads as
authoritative, and whose error is a widening no reader would question.

**What it compares.** For every `` `<name>.md` `` followed closely by a quoted run, the quoted text
must occur in that document. Both sides are normalised the same way — emphasis markers and
backticks stripped, comment and blockquote continuation markers dropped, wrapped lines joined,
whitespace collapsed — because the corpus wraps prose freely and a raw comparison reports
differences that are only line breaks.

*Measured on the shipped pattern: **0** failures as written, **14** with the decoration strip
disabled, **23** case-sensitive, **51** with no normalisation at all — every one of those an
emphasis marker, a wrapped line or a sentence-initial capital rather than a real misquotation. That
is the difference between a guard and a guard somebody switches off, the same lesson `_flat` and
the Markdown guard's code-span strip each record independently.*

*A figure of "18" stood here and matched no variant, because it was measured against a pattern two
revisions earlier. **Every number in this docstring is a property of the pattern below it**, so a
change to that pattern invalidates them all; re-derive rather than trust, which is one short
script.*

**Stated scope, which is narrower than the class, because a guard that overstates its reach is the
defect this suite has produced five times.** Only quotations of five or more words, adjacent to an
`.md` reference, in `zikaron/` and `tests/`, are reachable. A paraphrase with no quotation marks is
invisible; so is a quotation whose attribution sits further away than the window. The guard says a
quoted run is real, not that every attribution in the corpus is.
"""

import re
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent

#: A markdown filename in backticks, a short introducer ending in a **colon**, then a quoted run.
#:
#: **The colon is the whole of the precision, and it was measured rather than chosen.** A colon
#: introducer is how this corpus presents text as the document's own words; without it, a quoted
#: phrase is usually being *integrated* into the citing sentence, with its case adjusted and small
#: words dropped to fit — which is ordinary English and not a defect.
#:
#: *Measured both ways, under the comparison this file actually ships. As shipped, **59 pairs and
#: 0 failures**. Dropping the colon for any 90-character window gives **144 pairs and 13 failures**
#: — and **44** against a case-*sensitive* comparison, the difference being adjustments like
#: `Enforce an internal deadline of ~2 s` quoted as "enforce an internal deadline of 2 s", which
#: `_comparable`'s folding already absorbs. A round proposed the narrow form with its own
#: measurement attached; I widened it without re-measuring and produced a guard that fails on a
#: correct tree. **Widening a measured design makes it an unmeasured one.***
#:
#: *The two halves of that sentence were, for a while, **not measured the same way**: the cost of
#: dropping the colon was quoted case-sensitively while the file ships case-folding, so it charged
#: the colon for failures the folding already prevents. The honest cost is the smaller one, and the
#: colon still earns its place at it. **"Measured both ways" has to mean the same way twice.***
#:
#: *And the figure written here immediately after that lesson was itself stale within the hour —
#: "40 pairs, 40 verifying", present tense, on a tree measuring 46 and then 59 as the pattern
#: gained the section-name form. **A pair count is a property of the pattern, not of the corpus.***
#:
#: **The window forbids another `.md`**, which is not fussiness: without it the pattern binds a
#: quote to the *nearest preceding* filename rather than its own, and reported
#: `zikaron/service/serialize.py` as misquoting `architecture.md` when the line reads
#: `` `coding-standards.md` §2: "…" `` and quotes it correctly — the previous line happened to
#: mention `architecture.md`. **A guard that attributes the quotation to the wrong document
#: produces a finding that is wrong in the same way as the defect it hunts.**
#:
#: **An optional `§"…"` section name sits between the filename and the introducer**, because
#: a backticked filename, then a section name in the `§"…"` form, then a colon and the quotation
#: is this corpus's commonest attribution shape and the window
#: forbids `"`. Without it every such pair was invisible — **13 of them**, measured, including the
#: very example this file's docstring opens with (`permissions.py`) and one **live** miss in
#: `service/lifecycle.py`, which substituted "it" for a path inside quotation marks after a colon.
#: *A guard whose first documented example is outside its own reach is the stated-scope defect
#: this suite keeps producing, met one more time in the file written to close a different one.*
ATTRIBUTION: Final = re.compile(
    r"`(?P<document>[A-Za-z0-9._/-]+\.md)`"
    r"(?P<section>\s*§\s*[\"“][^\"”]*[\"”])?"
    r"(?P<between>(?:(?!\.md)[^\"“]){0,60}?:\s*)"
    r"[\"“](?P<quote>[^\"”]{25,})[\"”]"
)

#: Continuation markers that begin a wrapped line inside a docstring, a `#:` comment or a
#: blockquote, plus the emphasis and code markers the corpus uses inside quotations.
_CONTINUATION: Final = re.compile(r"\s*\n\s*(?:#:|#|>)?[ \t]*")
_DECORATION: Final = re.compile(r"[*`~]")

#: Quotations kept deliberately in their wrong form, because the text naming a defect has to keep
#: naming it. Keyed by citing file so an exemption cannot spread: the same rule
#: `test_design_pointers_resolve.py` arrived at after its own exemption list leaked across files.
#: **Empty, and that is a measured state rather than an oversight.** Three entries sat here on the
#: day this file was written and **all three were dead**, verified by replacing the set with
#: `frozenset()` and watching the suite stay green:
#:
#: - `connection.py`'s "Clients retry once" — dead twice over. The module was corrected, so the old
#:   wording survives only inside an editorial note with no adjacent filename-and-colon; and
#:   `_comparable` case-folds, so a fragment beginning with a capital could never match anyway.
#: - `permissions.py`'s "resolved parent to be the cwd" — its citation carries a `§"…"` section
#:   name, which the pattern could not then reach, so that file yielded no pair at all.
#: - `install/harness.py`'s "catches a schema mistake…" — it quotes *its own docstring*, not a
#:   markdown file, so no attribution pair exists.
#:
#: **This reproduced, verbatim, the defect its sibling records.** `test_design_pointers_resolve.py`
#: had two exemptions "dead the day they were written", removed them, and wrote down why — and this
#: file copied that constant's name and its keyed-by-citing-file rule while leaving behind the
#: liveness test that catches it. The test is below now. *Copying a mechanism without copying the
#: check that keeps it honest is how a lesson gets cited and not learned.*
QUOTED_AS_EVIDENCE: Final = frozenset[tuple[str, str]]()


def _joined(text: str) -> str:
    """One line, wraps and continuation markers collapsed — **decorations kept**.

    `ATTRIBUTION` matches a backticked filename, so the text it scans must still have its
    backticks. *The first version of this file flattened and stripped in one function and then ran
    the pattern over the stripped text: the backticks the pattern requires had already been
    removed, so it matched **zero** pairs across the whole tree and passed green. A guard written
    against "stated scope exceeds reachable scope" with a reachable scope of nothing — which is
    why the reach is now measured in a test below rather than asserted in this docstring.*
    """
    return re.sub(r"[ \t]+", " ", _CONTINUATION.sub(" ", text)).strip()


def _comparable(text: str) -> str:
    """`_joined`, decorations dropped and **case-folded** — the form the two sides compare in.

    **Case-folding is not laxity, it is what the corpus does.** A sentence-initial capital adjusted
    to sit mid-sentence is universal English practice, and every one of these is a *correct*
    quotation: `architecture.md`'s "**A** background task polls every 30 s" cited as "a background
    task polls every 30 s". Measured: case-sensitive comparison reports **23** failures on this
    tree, and swapping the case of the first character alone makes all twenty-three match — so the
    characterisation is exact, not approximate. *The figure read "16 … all sixteen" while the
    module docstring above said 23, four lines of measurement apart in one file.*

    **It does not weaken what the guard is for.** The finding it was built after — "Clients retry
    once" where the source says "`zikaron-mcp` retries once" — is a different *word*, and survives
    folding untouched. The guard catches substituted words, not substituted letters.
    """
    return re.sub(r"[ \t]+", " ", _DECORATION.sub("", _joined(text))).strip().casefold()


def _searched_files() -> list[Path]:
    """Every Python file whose prose may cite a design document."""
    found = [path for root in ("zikaron", "tests") for path in (REPO / root).rglob("*.py")]
    return [path for path in found if path.is_file() and path != Path(__file__)]


def _documents() -> dict[str, str]:
    """Every markdown document by bare name and by path, flattened once."""
    ignored = {".git", ".venv", ".venv-matrix"}
    bodies: dict[str, str] = {}
    for path in sorted(REPO.rglob("*.md")):
        if any(part.startswith(tuple(ignored)) for part in path.parts):
            continue
        flat = _comparable(path.read_text(encoding="utf-8"))
        bodies.setdefault(path.name, "")
        bodies[path.name] += " " + flat
        bodies[path.relative_to(REPO).as_posix()] = flat
    return bodies


def test_every_quotation_attributed_to_a_design_document_is_in_it() -> None:
    """The quoted words are the document's words, or the quotation marks are unearned.

    Reported as a set rather than one assertion per file: a misquotation is rarely alone, because
    the same sentence tends to get copied, and stopping at the first hides its siblings.
    """
    documents = _documents()
    broken: list[str] = []
    for path in _searched_files():
        relative = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in ATTRIBUTION.finditer(_joined(text)):
            document, quote = match["document"], _comparable(match["quote"]).strip(" .,;:—-")
            if len(quote.split()) < 5:
                continue
            if any(
                quote.startswith(fragment) or fragment in quote
                for citing, fragment in QUOTED_AS_EVIDENCE
                if citing == relative
            ):
                continue
            body = documents.get(document)
            if body is None:
                continue
            # Ellipsis joins two separated runs; each side must stand on its own.
            runs = [run.strip() for run in re.split(r"…|\.\.\.", quote) if len(run.strip()) > 12]
            missing = [run for run in runs if run not in body]
            if missing:
                broken.append(f'{relative}: {document} does not contain "{missing[0][:70]}"')
    assert not broken, (
        "quotations attributed to a document that does not contain them:\n" + "\n".join(broken)
    )


def test_every_evidence_exemption_still_exempts_something() -> None:
    """An exemption that fires nothing is a hole nobody is watching.

    **Written after all three of this file's original exemptions were found dead**, two of them
    unreachable on the day they were added. The sibling guard learned this and carries the same
    assertion; this file copied the constant and not the check.

    An empty set passes, which is the honest reading: no exemption is claimed, so none can rot.
    """
    documents = _documents()
    fired: set[tuple[str, str]] = set()
    for path in _searched_files():
        relative = path.relative_to(REPO).as_posix()
        for match in ATTRIBUTION.finditer(_joined(path.read_text(encoding="utf-8"))):
            quote = _comparable(match["quote"]).strip(" .,;:—-")
            if len(quote.split()) < 5 or documents.get(match["document"]) is None:
                continue
            fired |= {
                (citing, fragment)
                for citing, fragment in QUOTED_AS_EVIDENCE
                if citing == relative and fragment in quote
            }
    assert fired == set(QUOTED_AS_EVIDENCE), (
        f"exemptions that no longer exempt anything: {sorted(set(QUOTED_AS_EVIDENCE) - fired)} — "
        "either the quotation was fixed, or the pattern cannot reach the file that carries it"
    )


def test_this_guard_actually_reaches_the_quotations_it_claims_to_check() -> None:
    """A guard that matches nothing passes, and this one did.

    **Measured, not asserted.** The first version of this file flattened the citing text *and*
    stripped its backticks, then ran a pattern requiring backticks over the result: **zero pairs
    matched across the whole tree, and the suite went green.** A guard written to close the
    stated-scope-exceeds-reachable-scope class with a reachable scope of nothing.

    So reach is a test. The floor is deliberately well under what the tree holds today — it exists
    to catch the pattern silently matching nothing, not to pin a count that every edit moves.
    """
    documents = _documents()
    reached = sum(
        1
        for path in _searched_files()
        for match in ATTRIBUTION.finditer(_joined(path.read_text(encoding="utf-8")))
        if documents.get(match["document"]) is not None
    )
    assert reached >= 20, (
        f"this guard matches {reached} attribution pairs before the five-word filter; it matched "
        "dozens when written, so a collapse to near zero means the pattern has stopped seeing its "
        "subject rather than that the corpus stopped quoting"
    )
