"""Emphasis markers balance, so a document renders the way its source reads.

**The class this exists for is invisible to everything else the project has.** `ruff` does not read
`.md`; no test renders Markdown; and a reader of the *source* sees the words in the right order, so
the defect lives only in the rendered view. Nothing in this repository had ever looked at that view.

**Found in `FINDINGS.md` §"Current state — resume here" — the first paragraph a fresh session
reads.** A `**` opened on
its first line was never closed, and Markdown pairs greedily: every emphasis downstream rendered
**inverted**, each load-bearing clause plain and each connective and fragment bold. It arrived when
the heading above it was demoted to body text and the marker travelled with it — and the editorial
note four lines up describes fixing that same paragraph for an unclosed `**`, which is how long it
had been wrong in a way nobody could see.

Two more sat in normative design documents: a second `**` opened *inside* a bold run in
`architecture.md`, and a `**` closed with a single `*` in `consolidation.md`.

**Parity, not a parser.** The check is that each block contains an even number of `**` runs. That
cannot tell a correct document from a differently-wrong one, but it catches every defect of this
shape **in the blocks it scans** at no cost, and a real Markdown parser is a dependency this suite
does not have and does not want.

**Its reachable scope is narrower than "every block", and saying so is the point.** A block
containing a code fence is skipped whole — a fence may open in one block and close in another, so
counting its contents would be worse than skipping it — which leaves those blocks unchecked. None
is unbalanced today. *An earlier version of this docstring claimed it catches "every defect of
this shape", which is the stated-scope-exceeds-reachable-scope class this suite has now produced
five times, in the file written to close a different one.*

*The first version of this scan reported eight offenders and five were false — `**` inside a code
span, counted because the scan did not strip them. A guard that cries wolf on correct prose is a
guard somebody switches off, which is why stripping happens before counting.*
"""

import re
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parent.parent

#: Inline code spans, stripped before counting. They may contain `**` that is content rather than
#: emphasis — a quoted marker, a glob, a shell operator — and counting those is what produced
#: every false positive this scan has had: the first version reported eight offenders, five of
#: them `**` inside backticks.
#:
#: *A `FENCED` pattern sat beside this and was **dead code**: blocks containing a fence are skipped
#: whole before any substitution runs, so it could never match. Measured over this guard's own file
#: set — zero blocks in which it could fire. Removed rather than left as decoration, which is the
#: same disposition this suite gave two unreachable evidence exemptions.*
INLINE_CODE: Final = re.compile(r"`[^`]*`")


#: The documents a human reads rendered: `README.md`, `CLAUDE.md`, `FINDINGS.md`,
#: `FINDINGS-archive.md` and the normative design corpus — enumerated rather than described,
#: because the description that stood here ("the two always-loaded files, the public front door,
#: the instruction file") named four things for a four-file list while `CLAUDE.md` is itself one
#: of the two always-loaded. `reviews/`, `research/`, `experiments/` and `spikes/` are deliberately
#: out — they are an evidence trail read as source, and a stray marker in one misleads nobody.
def _rendered_documents() -> list[Path]:
    """Every document whose rendered appearance is part of what it is for."""
    named = [
        REPO / name for name in ("README.md", "CLAUDE.md", "FINDINGS.md", "FINDINGS-archive.md")
    ]
    return [path for path in [*named, *sorted((REPO / "design").glob("*.md"))] if path.is_file()]


def test_every_document_has_balanced_bold_markers() -> None:
    """An odd number of `**` in one block means everything after it renders inverted.

    Blocks are blank-line separated, which is what Markdown itself treats as a paragraph boundary
    and therefore the unit over which a run of emphasis can actually span. A block containing a
    fence is skipped whole rather than partially stripped: a fence that opens in one block and
    closes in another would otherwise leave its contents counted.
    """
    offenders: list[str] = []
    for path in _rendered_documents():
        relative = path.relative_to(REPO).as_posix()
        text = path.read_text(encoding="utf-8")
        line = 1
        for block in text.split("\n\n"):
            if "```" not in block:
                stripped = INLINE_CODE.sub("", block)
                if stripped.count("**") % 2:
                    first = block.strip().splitlines()[0][:60] if block.strip() else ""
                    offenders.append(f"{relative}:{line} — {first}")
            line += block.count("\n") + 2
    assert not offenders, (
        "unbalanced `**` — everything after the stray marker renders with emphasis inverted:\n"
        + "\n".join(offenders)
    )
