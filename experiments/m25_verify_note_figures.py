#!/usr/bin/env python
"""Check M25's published figures against the committed run, across every file that carries them.

**Why this exists, and why it is stricter than its first version.** Review round 1 found the note's
two load-bearing figures could not be regenerated at all. Round 2 found **six** figures from a
superseded run still standing in the note, after I reported sweeping for them — the sweep was a
`grep` for strings I remembered changing, which finds what it is told to look for. Round 3 then
found **five more**, four of them in files the first version of this checker did not read, plus the
hole below.

**The hole, which matters more than the figures.** The first version's oracle was *"this number
appears somewhere in the JSON"*. That JSON holds thousands of distinct four-decimal values in
[0, 1], so a stale figure reconciles **by coincidence** at a rate that is not small — demonstrated:
the note's historical `0.2671` passed only because one unrelated cell happens to carry it as
`mrr10_capped_heading`. A check that accepts by luck and reports success is worse than no check,
because it is quoted as coverage. Two changes follow: the coincidence rate is **printed**, so the
number is never read as stronger than it is; and a figure the note quotes *historically* must be
**declared** below with its reason rather than passing by collision.

What this closes: a figure that is simply stale. What it cannot reach: a figure that reconciles and
is quoted about the wrong quantity — which is what round 2's and round 3's real blockers were. No
string check reaches that; only reading does.

Run:  .venv/bin/python experiments/m25_verify_note_figures.py
Exit: 0 if everything reconciles, 1 otherwise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "experiments" / "results" / "m25_fusion_sweep.json"

#: Four decimals is this project's convention for a measured MRR, hit rate, delta or interval
#: bound. Each entry is (path, start marker, end marker); markers scope a file to the M25 material
#: so that other subjects' figures are not dragged in. `None` means the whole file.
SOURCES: tuple[tuple[str, str | None, str | None], ...] = (
    ("research/m25-fusion-sweep.md", None, None),
    ("research/m25-fusion-sweep-preregistration.md", None, None),
    ("FINDINGS.md", "**Track B's result", "**What to do next"),
    ("design/knowledge-index.md", "## 16. Open questions", None),
    ("zikaron/core/retrieval/__init__.py", None, None),
    ("design/schema.md", "arm-weighting and `fusion_depth` pass", "Not pruning also removes"),
    (
        "design/build-plan.md",
        "Open questions in `FINDINGS.md` are open on purpose",
        "The design is normative",
    ),
)

#: Figures quoted deliberately as history, or belonging to another measurement entirely. Declared
#: rather than allowed to pass by collision — that is the whole point of the list.
ALLOWED: dict[float, str] = {
    0.2671: "the pre-instrument-fix `heading` value at the shipped cell, quoted as superseded",
    0.2475: "the pre-leak-fix lexical-only `heading` value, quoted as superseded",
    0.2515: "`(10, 10, 0.0)` under the zero-weight leak, quoted as the symptom that revealed it",
    0.0705: "FINDINGS open question 2: bge-large minus bge-small MRR@10 on the memory benchmark",
    0.1156: "the upper bound of that same interval",
    0.0283: "the lower bound of that same interval",
    0.1081: "open question 2's arm-intersection figure",
    0.2724: "a memory-store figure predating M25",
    0.0052: "the tie-movement bound from open question 2's investigation",
    0.6325: "schema.md, unrelated to M25",
    0.8367: "schema.md, unrelated to M25",
    0.0164: "schema.md, unrelated to M25",
    0.0182: "schema.md, unrelated to M25",
    0.6800: "build-plan, unrelated to M25",
    4.2067: "a knowledge-index figure predating M25",
    # Derived in prose from two reported values. Declared rather than tolerated: a derivation is
    # legitimate, but it must be stated beside the figure so a reader can redo it, and declaring it
    # here is what forces that to have happened.
    0.0033: "widened 0.3259 minus as-scored 0.3226, the sensitivity table's largest disagreement",
    0.2206: "pooled max 0.7056 minus shipped 0.4850 — the artefactual lexical-only win",
}

#: Integers the note states in prose that the run also reports. The first version checked only
#: four-decimal figures, and round 3's `27`-against-23 went straight through that hole.
#:
#: **This closes half of it, and the half it does not close is the half that failed.** The check
#: asserts the run's integer *appears* in the note; it cannot see a **stale** integer that is also
#: present. A note saying "27 of 150" in one sentence and "23" in another passes. Calling this
#: "named integers are checked" would be the docstring's own warning — a check quoted as coverage —
#: turned on itself.
NAMED_INTEGERS: tuple[tuple[str, str], ...] = (
    ("instrument.overlap.heading.at_zero_overlap", "heading queries at zero overlap"),
    ("instrument.headings_seen", "headings seen"),
    ("instrument.headings_dropped_generic", "headings dropped as generic"),
    ("instrument.heading_queries_with_duplicate_title", "sampled queries with a repeated title"),
    ("chunks", "chunks in the corpus"),
    ("files", "files in the corpus"),
)

_FIGURE = re.compile(r"\d\.\d{4}")


def _known(run: object, into: set[float]) -> set[float]:
    if isinstance(run, bool):
        return into
    if isinstance(run, (int, float)):
        into.add(round(abs(float(run)), 4))
    elif isinstance(run, dict):
        for value in run.values():
            _known(value, into)
    elif isinstance(run, list):
        for value in run:
            _known(value, into)
    return into


def _scoped(path: Path, start: str | None, end: str | None) -> str:
    """The M25 region of a file, or a loud failure.

    **A marker that stops matching must not scope the file to nothing.** An earlier revision
    returned `""` for an unfound start marker, which yields zero figures and prints `ok` — so
    editing any of the sentences `SOURCES` keys on would have turned that file's check silently
    vacuous, which is this corpus's own "a guard that never executes proves nothing" arriving
    inside the guard written to stop it.
    """
    text = path.read_text(encoding="utf-8")
    for marker, which in ((start, "start"), (end, "end")):
        if marker is not None and marker not in text:
            raise SystemExit(f"{path.name}: {which} marker not found — {marker!r}")
    if start is not None:
        text = text[text.find(start) :]
    if end is not None:
        text = text[: text.find(end)]
    return text


def _at(run: dict[str, object], dotted: str) -> object:
    node: object = run
    for part in dotted.split("."):
        node = node[part]  # type: ignore[index]
    return node


def main() -> int:
    run = json.loads(RESULTS.read_text(encoding="utf-8"))
    known = _known(run, set())

    print(f"distinct four-decimal values in the run: {len(known)}")
    print(
        "  a stale figure in [0, 1] reconciles by coincidence"
        f" with probability ~{len(known) / 10000:.1%}"
    )
    print("  -> this check closes *stale*, not *wrong quantity*; see the docstring.\n")

    failures = 0
    for name, start, end in SOURCES:
        path = ROOT / name
        quoted = sorted({round(float(m), 4) for m in _FIGURE.findall(_scoped(path, start, end))})
        unmatched = [f for f in quoted if f not in known and f not in ALLOWED]
        # A scoped source contributing nothing means its markers moved, not that it is clean.
        empty = not quoted and (start is not None or end is not None)
        status = (
            "ok"
            if not unmatched and not empty
            else (
                f"UNMATCHED {unmatched}"
                if unmatched
                else "NO FIGURES IN SCOPE — markers have drifted"
            )
        )
        print(f"{name}: {len(quoted)} figures — {status}")
        failures += bool(unmatched) or empty

    print()
    note = _scoped(ROOT / "research/m25-fusion-sweep.md", None, None)
    for dotted, described in NAMED_INTEGERS:
        value = _at(run, dotted)
        present = re.search(rf"\b{value:,}\b".replace(",", "[,]?"), note) is not None
        print(
            f"{described}: run says {value:,} — {'quoted' if present else 'NOT QUOTED in the note'}"
        )
        failures += not present

    if failures:
        print(
            "\nEach unmatched figure is stale, or is history that belongs in ALLOWED with a reason."
        )
        return 1
    print("\nall figures reconcile or are declared historical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
