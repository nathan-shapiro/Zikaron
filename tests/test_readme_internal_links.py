"""Every `](#…)` link in `README.md` resolves, and none of them points at its own section.

**Resolution alone was never the failing half.** All four anchors in this file resolved on the day
two of them were found wrong: one had been repaired from a plain-prose *"see Requirements"* — which
named a section that does not discuss its subject — into a working link to `#install`, written from
a line already inside §Install. The other had been doing the same thing since it was written. A
reader following either is told to go somewhere they already are.

So the guard is in two parts, and the second is the one with evidence behind it:

- **Resolution**: the target heading exists, by GitHub's own slug rules.
- **Direction**: the link is not inside the section it points to, which is decided by line number
  against the heading map rather than by reading.

`README.md` alone, deliberately. It is the document a stranger reads first and the only one whose
cross-references are rendered as links; the design corpus points with `§"…"` pointers instead, which
`test_design_pointers_resolve.py` already guards.
"""

import re
from pathlib import Path
from typing import Final

import pytest

README: Final = Path(__file__).resolve().parent.parent / "README.md"

#: `[text](#anchor)` — the only link form that can point inside this document.
INTERNAL_LINK: Final = re.compile(r"\[[^\]]*\]\(#([^)]+)\)")

#: An ATX heading and its level, so a section's extent can be computed from the next heading of the
#: same level *or shallower* — a `###` does not end the `##` it sits under.
HEADING: Final = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

#: Fences are skipped: a shell block can contain `#` at the start of a line as a comment, and one
#: did. Counting those as headings shifts every section boundary after it.
FENCE: Final = re.compile(r"^\s*```")


def _slug(heading_text: str) -> str:
    """GitHub's anchor for a heading, close enough for this document and **not exactly**.

    Lowercase; strip everything that is not a word character, a space or a hyphen; then whitespace
    to hyphens. Written out rather than imported so the guard has no dependency that could change
    under it.

    **Two limits, both measured against this README's headings rather than assumed.** The strip
    removes exactly one character in the whole document — the colon in
    `### Knowledge bases: searching what the project wrote down`; the backticks, asterisks and em
    dashes it would also remove appear in the design corpus's headings, not here. And it collapses
    a *run* of whitespace to one hyphen where github-slugger emits one hyphen **per space**, so
    `A  B` is `a--b` upstream and `a-b` here. No heading in this file has two adjacent spaces, so
    nothing exercises it today; it would diverge silently the day one does.

    *An earlier version of this docstring claimed it implemented "the rules, not an approximation
    of them", and listed the characters it removes as ones "this README's headings use freely" —
    a description of a different document, in the guard's own explanation of itself.*
    """
    text = heading_text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text).strip("-")


@pytest.fixture(scope="module")
def sections() -> list[tuple[str, int, int, int]]:
    """Every heading as `(slug, level, first_line, last_line)`, 1-indexed and inclusive."""
    lines = README.read_text(encoding="utf-8").splitlines()
    found: list[tuple[str, int, int]] = []
    in_fence = False
    for number, line in enumerate(lines, start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.match(line)
        if match:
            found.append((_slug(match[2]), len(match[1]), number))
    extents: list[tuple[str, int, int, int]] = []
    for index, (slug, level, start) in enumerate(found):
        end = len(lines)
        for _, later_level, later_start in found[index + 1 :]:
            if later_level <= level:
                end = later_start - 1
                break
        extents.append((slug, level, start, end))
    assert extents, "README.md has no headings, which cannot be right"
    return extents


def test_every_internal_link_resolves_to_a_heading(
    sections: list[tuple[str, int, int, int]],
) -> None:
    """A link to an anchor this document does not have renders as a link and goes nowhere."""
    known = {slug for slug, _, _, _ in sections}
    lines = README.read_text(encoding="utf-8").splitlines()
    broken = [
        f"line {number}: #{match[1]}"
        for number, line in enumerate(lines, start=1)
        for match in INTERNAL_LINK.finditer(line)
        if match[1] not in known
    ]
    assert not broken, "README internal links that resolve to no heading:\n" + "\n".join(broken)


def test_no_internal_link_points_at_the_section_it_sits_in(
    sections: list[tuple[str, int, int, int]],
) -> None:
    """The half that actually caught something: a link telling the reader to go where they are.

    **Two existed when this was written**, and one of them had just been *created* by repairing a
    different defect — a plain-prose "see Requirements" that named the wrong section was rewritten
    as a working link to `#install`, from a line 70 lines inside §Install. Fixing resolution made
    the direction wrong, and nothing could see it, because every check anyone had was about whether
    the anchor existed.

    **The test is only whether the link's line falls inside the target's own extent**, which is one
    comparison rather than a walk up the heading tree. A link under a `###` still fails when it
    points at the `##` containing it, and that is intended: a reader inside §Install told to go to
    §Install gains nothing from the fact that they are in a subsection of it.
    """
    lines = README.read_text(encoding="utf-8").splitlines()
    offenders: list[str] = []
    for number, line in enumerate(lines, start=1):
        for match in INTERNAL_LINK.finditer(line):
            target = match[1]
            inside_target = any(
                slug == target and start <= number <= end for slug, _, start, end in sections
            )
            if inside_target:
                offenders.append(
                    f"line {number}: links to #{target}, which is the section it is in"
                )
    assert not offenders, (
        "README internal links pointing at their own section:\n"
        + "\n".join(offenders)
        + "\nSay 'above' or 'below', or drop the link — the reader is already there."
    )
