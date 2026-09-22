"""Every `` `<doc>.md` §"…" `` pointer names a section that exists.

`design/coding-standards.md` §5 bans circumstantial provenance in code but **carves out the contract
pointer** — a comment saying *what this code must agree with* — on the argument that section names
are the stable half and that the pointer is load-bearing. That argument only holds while the
pointers resolve, and nothing was checking.

**Measured when this was first run: six broken sites over four distinct pointers, four of the six
in shipped code.** `server.py`, `primary.py` and `consolidator.py` under `zikaron/mcp/` all cited
`architecture.md` §"a consolidator config provably cannot reach `search` or `fetch`", a string that
has never appeared in that document; `zikaron/core/records/__init__.py` cited `indexing.md`
§"Atomicity", a heading that does not exist in a file that does not contain the word; and two more
sat in `research/` and `design/build-plan.md`. Every one read as authoritative and sent a reader
nowhere.

*A round of the sweep that found these reported "four breaks, three in shipped code" and this
docstring copied it. Re-derived from the diff: six and four. **A count arriving inside a finding is
still a claim** — which is a rule this corpus already had, restated here because the file enforcing
mechanical checks is the last place a hand-copied number belongs.*

**Matched against the document's whole text rather than against its headings**, deliberately: this
corpus cites bold lead-ins as often as `##` headings, and a headings-only check would have reddened
dozens of correct pointers and been switched off. The weaker assertion still catches every failure
above, because a string that is not in the file is not in the file.
*~~It still catches every failure.~~ **One shape escapes it and did**: a target that merely
**quotes** the pointer, so the section name is in the file without the section being.
`_defining_text` strips `§"…"` constructs before the comparison, which is the narrowest repair that
closes it without becoming a heading parser.*

`reviews/` is excluded — it is an append-only audit trail quoting what was believed at the time, and
a review round that cited a section later renamed is a record rather than a defect. **That sentence
described nothing for as long as it existed**: the directory was not among the roots walked, so the
exclusion filtered a set that was already empty. It is walked now, and the exclusion is what keeps
its pointers out — **no total is written here**, for the reason this file states thirty lines
below about the corpus's own count: run the pattern over that directory, which is one command.
*A figure did sit here, and in the constant's comment below, and matched no derivation of anything
— not the pointer count, not the unique-pair count, not the pre-fix pattern's count. It was carried
by hand in the file whose subject is that hand-carried counts decay.*
"""

import re
from pathlib import Path
from typing import Final

import pytest

REPO: Final = Path(__file__).resolve().parent.parent

#: `` `foo.md` §"Some section" `` and `` `design/foo.md` §"Some section" `` — this corpus uses both
#: spellings interchangeably, and **the first version of this pattern admitted no `/`**, so every
#: path-prefixed pointer was skipped in silence. **When the hole was found, roughly three in ten
#: pointers carried a prefix and every one of them was invisible to this guard; four were broken,
#: all in normative documents.** *No total is written here. Three were measured on one day — 441,
#: 448 and 457 — and the differences are real edits, not disagreeing instruments: the corpus gains
#: pointers faster than a docstring can record them. The **ratio** is what the lesson needs, and it
#: is the thing that does not move. Re-derive either number by running the pattern; that is one
#: command, and this file briefly carried three different totals for "the corpus", one per
#: paragraph, from not running it.*
#:
#: **That is the same failure as the wrap blindness `_flat` exists for, by a different route**, in
#: a guard whose docstring says "every pointer". The lesson is not about slashes: **a guard that
#: recognises its subject by a pattern is only as complete as the pattern, and a spelling the
#: corpus uses freely is exactly what the author of the pattern forgets.** So the count above is
#: re-derivable rather than asserted — widen the class, run it, and compare.
POINTER: Final = re.compile(r"`([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*\.md)`\s*§\"([^\"]+)\"")

#: A line break plus whatever marker continues the prose on the next line — a `#:` or `#` comment
#: marker, a `>` blockquote marker, or plain indentation. Collapsed to one space before a pointer
#: is compared, so a section name spanning two comment lines still matches the document's prose.
_LINE_BREAK: Final = re.compile(r"\s*\n\s*(?:#:|#|>)?[ \t]*")


def _flat(text: str) -> str:
    """The text as one line, with wraps and their continuation markers collapsed to single spaces.

    **The whole reason this exists**: the first version of this guard matched line by line, so a
    pointer whose closing quote fell on the next line was never examined at all. Re-derived over
    the corpus **as it stood that day: 307 pointers, of which 259 were visible to that check and 48
    were not** — and one of the 48 was genuinely broken, in a *normative* document, citing a
    `FINDINGS.md` section an archive pass had moved. **A guard whose docstring says "every pointer"
    while silently skipping the ones that wrap is worse than no guard**, because it gets quoted as
    coverage.
    """
    return re.sub(r"[ \t]+", " ", _LINE_BREAK.sub(" ", text))


#: A `§"…"` construct anywhere in a target document. Removed before the containment test below, so
#: that a *pointer* naming a section can never be mistaken for the section existing.
_POINTER_CONSTRUCT: Final = re.compile(r'§\s*"[^"]*"')


def _defining_text(body: str) -> str:
    """A document's text with every `§"…"` construct removed — what may *define* a section.

    **The hole this closes, measured 2026-09-22.** A reading note in `FINDINGS-archive.md` pointed
    at `FINDINGS.md` §"Track C" after an archive pass had moved that section into the archive
    itself. The pointer was broken and the guard passed, because `FINDINGS.md` still contained the
    string `§"Track C"` — inside a pointer of its own, aimed back at the archive. **The target
    quoting the pointer is not the target having the section**, and whole-text containment cannot
    tell the two apart.

    Over the corpus that day: **438 pointers, exactly one** resolving only that way. So this costs
    nothing on a correct tree, which is the argument for adding it rather than the argument against
    — the same shape as every other hole this file has had, each of which was also worth nothing
    until the day it was worth a broken pointer in a normative document.

    **It is deliberately blind to *which* document a construct points at.** A section named only by
    an internal `§"…"` self-reference is no more defined than one named by an external pointer, and
    distinguishing them would re-introduce the parsing this test exists to avoid.
    """
    return _POINTER_CONSTRUCT.sub(" ", body)


#: Files whose pointers are history rather than instruction, and must not be repaired.
#:
#: *This tuple did nothing for as long as it existed.* `reviews/` was named here **and left out of
#: the roots `_tracked_files` walks**, so no path under it ever reached the filter, and every
#: pointer in that directory sat outside the scan whatever this said. The exclusion is now real:
#: `reviews` is walked, and this is what keeps its pointers out. **A guard's stated scope and its
#: reachable scope are two different things** — the lesson this file already carried, found a third
#: time, in the very mechanism written to express it.
EXCLUDED_PREFIXES: Final = ("reviews/",)

#: Broken pointers quoted *as findings*, under the withdraw-in-place rule — the text naming what
#: was wrong has to keep naming it.
#:
#: **Keyed by the citing file as well as the target**, which an earlier version was not. Exempting
#: `(document, section)` alone meant that once a dead pointer had been written up, **writing that
#: same dead pointer live anywhere in the corpus was silently allowed** — the exemption list was
#: quietly becoming a list of holes, one per lesson recorded. Naming the file that may quote it
#: keeps the hole one entry wide. The list grows whenever a break is recorded rather than merely
#: fixed, which is the cost of this corpus's own rule that a refuted claim stays on the page.
#: Pointers a file deliberately quotes as evidence of a break, keyed by citing file so an
#: exemption cannot silently cover a second site. Empty: every entry named prose in `FINDINGS.md`
#: that no longer exists. The liveness test below is what keeps it that way — an exemption for a
#: pointer that now resolves is a hole, not a carve-out.
QUOTED_AS_EVIDENCE: Final = frozenset[tuple[str, str, str]]()


def _tracked_files() -> list[Path]:
    """Every file this guard reads, found from the tree rather than from a list.

    A list would be a second thing to maintain, and the failure it invites is a new module whose
    pointers nobody checks — which is how the breaks above survived.

    **The named files at the end are not decoration.** An earlier version of this function declared
    `.sh`, `.yml` and `.toml` in its suffix set over `roots` alone, and reached **zero** `.yml`,
    **zero** `.toml` and two `.sh` — because every such file that actually carries a pointer sits
    at the repository root or under `.github/`, outside every root walked. The suffix list
    advertised a coverage that did not exist, which is the same defect as the pattern above wearing
    a different hat: **a guard's stated scope and its reachable scope are two different things, and
    only the second one guards anything.**
    """
    suffixes = {".md", ".py", ".sh", ".yml", ".toml"}
    roots = (
        "zikaron",
        "tests",
        "design",
        "research",
        "experiments",
        ".claude",
        ".kiro",
        # Walked so that `EXCLUDED_PREFIXES` actually excludes something. It named `reviews/` while
        # this tuple did not reach it, so the filter was dead code and the docstring described a
        # mechanism that never ran.
        "reviews",
    )
    found = [
        path
        for root in roots
        for path in (REPO / root).rglob("*")
        if path.is_file() and path.suffix in suffixes
    ]
    found += [
        REPO / name
        for name in (
            "README.md",
            "CLAUDE.md",
            "FINDINGS.md",
            "FINDINGS-archive.md",
            "check.sh",
            "check-matrix.sh",
            "pyproject.toml",
            ".github/workflows/check.yml",
        )
    ]
    return [path for path in found if path.is_file()]


@pytest.fixture(scope="module")
def documents() -> dict[str, list[str]]:
    """Every markdown document by bare filename, which is how the corpus cites them.

    Not just `design/`: the same `§"…"` form points at `FINDINGS.md`, `FINDINGS-archive.md`,
    `CLAUDE.md` and notes under `research/`, and a design-only map reported every one of those as a
    missing document — a guard that cries wolf on correct pointers is a guard somebody switches off.

    **A list of bodies per name, not one body**, because this tree has duplicate filenames: seven
    `README.md` — the root, `design/`, `research/`, `reviews/`, both `experiments/` subdirectories
    and `spikes/claude-code-installer/` — and three `SKILL.md`. Keeping only the first would
    make the guard depend on `rglob` order, which is unspecified — a guard that passes or fails by
    directory-walk order is worse than none, and it would have looked correct for as long as nobody
    wrote a pointer at one of those names. A pointer resolves if **any** file of that name contains
    the section; ambiguity is reported separately below.

    **Keyed by both spellings.** A document is filed under its bare name *and* under its path
    relative to the repository, because the corpus writes a bare name and a `design/`-prefixed one
    interchangeably. A path-prefixed pointer therefore resolves against exactly one file, which is
    strictly better than the bare-name fallback: it removes the ambiguity the duplicate-filename
    test below exists to police, for the roughly three in ten pointers that carry a prefix.
    """
    found: dict[str, list[str]] = {}
    ignored = {".git", ".venv", ".venv-matrix", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    for path in sorted(REPO.rglob("*.md")):
        if any(part in ignored or part.startswith(".pytest_cache") for part in path.parts):
            continue
        body = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO).as_posix()
        found.setdefault(path.name, []).append(body)
        # Only when the two spellings differ: a root-level file's path *is* its name, and filing it
        # twice would make it look duplicated to the ambiguity check below.
        if relative != path.name:
            found.setdefault(relative, []).append(body)
    return found


def test_every_section_pointer_resolves(documents: dict[str, list[str]]) -> None:
    """A pointer to a section that does not exist is worse than no pointer.

    All of them are reported at once rather than one assertion per file: the failure is a *set*,
    and a guard that stops at the first break invites exactly the fix-the-site-not-the-class habit
    this corpus keeps recording.
    """
    broken: list[str] = []
    for path in _tracked_files():
        relative = path.relative_to(REPO).as_posix()
        # This file is skipped wholesale, and the reason is not squeamishness: its comments carry
        # **deliberately fake** pointers — `foo.md` §"Some section" as the pattern's worked example,
        # `architecture.md` §"Nothing Named This" as a mutation oracle — which must not resolve.
        # Scanning it would turn every illustration into a permanent exemption entry, which is the
        # list-of-holes failure `QUOTED_AS_EVIDENCE` is keyed by citing file to avoid.
        if relative.startswith(EXCLUDED_PREFIXES) or path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8")
        for match in POINTER.finditer(_flat(text) if "\n" in text else text):
            document, section = match[1], _flat(match[2]).strip()
            if (relative, document, section) in QUOTED_AS_EVIDENCE:
                continue
            bodies = documents.get(document)
            if bodies is None:
                broken.append(f"{relative}: no document named {document}")
            elif not any(section in _defining_text(_flat(body)) for body in bodies):
                broken.append(f'{relative}: {document} §"{section}" does not resolve')
    assert not broken, "section pointers that go nowhere:\n" + "\n".join(broken)


def test_no_pointer_names_a_filename_this_tree_has_twice(documents: dict[str, list[str]]) -> None:
    """A pointer at an ambiguous filename resolves against whichever file happens to match.

    `README.md` exists seven times in this tree; `SKILL.md` three. Neither is cited by
    a `§"…"` pointer today, so the guard above is unambiguous — but the first person to write one
    would get a check that silently means "some file of this name", which is not what the pointer
    says. Stated as its own failure so that day is loud.
    """
    ambiguous = {name for name, bodies in documents.items() if len(bodies) > 1}
    cited: set[str] = set()
    for path in _tracked_files():
        if path.relative_to(REPO).as_posix().startswith(EXCLUDED_PREFIXES) or path == Path(
            __file__
        ):
            continue
        # `_flat`, exactly as the resolve test above uses it: a raw scan here misses every pointer
        # that wraps, so the two tests would be checking different sets in one file, one line
        # apart. Measured when this was fixed: the raw scan saw one pointer fewer.
        cited.update(
            document for document, _ in POINTER.findall(_flat(path.read_text(encoding="utf-8")))
        )
    collisions = sorted(cited & ambiguous)
    assert not collisions, (
        f"these filenames are cited by a section pointer and exist more than once: {collisions}. "
        "Cite the path, or rename the file — a pointer must name one document."
    )


def test_the_guard_can_see_a_break(documents: dict[str, list[str]]) -> None:
    """The oracle check: a guard green over a correct tree proves nothing about the guard.

    Stated as its own test rather than trusted, because this file's whole subject is a correct
    instrument whose result was reported without being re-run.
    """
    assert POINTER.findall('cites `architecture.md` §"Nothing Named This" here') == [
        ("architecture.md", "Nothing Named This")
    ]
    assert not any("Nothing Named This" in body for body in documents["architecture.md"])


def test_the_evidence_exemptions_are_still_broken_pointers(documents: dict[str, list[str]]) -> None:
    """The exemption list is not a place to park a repairable pointer.

    Each entry exists because some file quotes it *as the defect*. If one starts resolving —
    somebody added that heading — the quote has become confusing rather than illustrative and the
    entry must go, so this fails rather than letting the list rot into a blanket exclusion.

    **Also checks that the citing file still cites it**, because the other way an exemption rots is
    quieter: the finding gets rewritten, the quotation goes, and the entry stays behind as a
    standing permission for a pointer nobody writes any more.

    **The two directions must define "resolves" identically, and for one gate run they did not.**
    This test kept the loose whole-text containment after the forward test gained `_defining_text`,
    so a `FINDINGS.md` → `FINDINGS.md` §"Track C" exemption was simultaneously *required* by the
    forward test (it does not resolve) and *rejected* here (it appeared to). **A guard split across
    two assertions is two guards, and they go out of agreement in the direction nobody runs** — the
    same two-sites failure this corpus records about prose, in the file enforcing it.
    """
    resolving = sorted(
        f'{citing} quotes {document} §"{section}", which now resolves'
        for citing, document, section in QUOTED_AS_EVIDENCE
        # `_flat` and `_defining_text` in the same order the forward test applies them: an exemption
        # whose heading came back only across a wrap would otherwise stay exempt silently, and one
        # that "came back" only as a quoted pointer never came back at all.
        if any(section in _defining_text(_flat(body)) for body in documents.get(document, []))
    )
    unused = sorted(
        f'{citing} no longer quotes {document} §"{section}"'
        for citing, document, section in QUOTED_AS_EVIDENCE
        if section not in _flat((REPO / citing).read_text(encoding="utf-8"))
    )
    assert not resolving + unused, "the evidence exemptions have drifted:\n" + "\n".join(
        resolving + unused
    )


#: Every path under `.zikaron/` is derived from `paths.store_dir(scope_dir)`, and `scope_dir` is the
#: harness's own project directory where it names one — `$CLAUDE_PROJECT_DIR` under Claude Code —
#: falling back to the cwd only when it does not. D17 was amended to say so on 2026-08-18.
_CWD_SPELLING: Final = "<" + "cwd>/.zikaron"


def test_no_document_spells_a_store_path_as_relative_to_the_working_directory() -> None:
    """`<cwd>/.zikaron/...` is a spelling D17's amendment made false, and it survived in six places.

    **Why a guard rather than a fix.** The amendment landed in one bullet of a four-bullet list and
    left its three siblings, the configuration-precedence table, the worked TOML sample and D33's
    own row — all saying `<cwd>`, all wrong the same way, all in documents reviewed since. Under
    Claude Code the scope is `$CLAUDE_PROJECT_DIR`, which is exactly what the amendment exists to
    distinguish from the working directory: one measured session made 39 cwd transitions.

    The invariant is total, which is what makes it guardable: **no path under `.zikaron/` is
    relative to the cwd**, so any occurrence is a defect with no exception to carve out.
    """
    offenders = [
        f"{path.relative_to(REPO).as_posix()}:{number}"
        for path in _tracked_files()
        # `reviews/` is excluded for the reason it is excluded above: a review round that quoted the
        # pre-amendment spelling is a record of what was believed on that date, not a live claim.
        # Measured when this guard was written: two such lines, both in reviews predating D17.
        #
        # `FINDINGS.md` and its archive are excluded on the same ground, and the exclusion was added
        # **because this guard reddened on the entry describing the defect it guards** — the
        # write-up has to name the spelling it is about. Those two files are working memory and
        # history; neither tells a reader where a store lives, which is what this check protects.
        # Same shape as `QUOTED_AS_EVIDENCE` above: a corpus that withdraws claims in place must let
        # the withdrawal quote what it withdrew.
        if path.suffix == ".md"
        and path != Path(__file__)
        and path.name not in {"FINDINGS.md", "FINDINGS-archive.md"}
        and not path.relative_to(REPO).as_posix().startswith(EXCLUDED_PREFIXES)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _CWD_SPELLING in line
    ]
    assert not offenders, (
        "store paths written as relative to the working directory:\n"
        + "\n".join(offenders)
        + "\nUse <scope>/.zikaron/... — the scope is the harness's project directory, not the cwd."
    )
