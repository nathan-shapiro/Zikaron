"""Four ways to put the answering passage in front of the caller, measured against each other.

The diagnosis this follows from: reordering the candidate pool can recover about a sixth of
queries, while the larger share fails because the answering passage was never a well-formed
candidate — the right document is retrieved and represented in the pool by some *other* part of
itself. Where a chunk of the right file reached the pool without the answer, the two are usually
one or two chunks apart. That points at where the cuts fall, not at how the candidates are sorted.

Four arms, three of which change the index and one of which does not:

| arm | what changes |
|---|---|
| `baseline` | the shipped chunker: paragraphs packed greedily to the budget, no overlap |
| `overlap` | each chunk repeats the tail of the one before it |
| `section` | cuts fall at markdown headings first, packing only within a section |
| `neighbours` | the baseline index, with each delivered result widened to its adjacent chunks |

**The oracle had to change, and that is the point of this harness rather than a detail.** Every
earlier measurement here scored "is the truth *chunk id* in the top five", which cannot compare two
indexes that cut the corpus differently — their chunk ids describe different things. Truth is
therefore a **line range**: the body of the section a heading names, read from the file rather than
from any index. A query succeeds when the text actually delivered to the caller covers at least
`COVERAGE` of those lines. That definition is identical across all four arms, is independent of
chunking, and is closer to what a caller needs than any chunk identity.

**Delivered characters are reported beside the hit rate, because one arm buys coverage with
bytes.** Widening every result to its neighbours trivially raises coverage if the response is
allowed to grow without limit, and a comparison that ignored size would recommend it every time.

Usage:

    .venv/bin/python experiments/m26_chunking_levers.py <corpus-root> <workspace-root> [queries]
"""

import asyncio
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import aiosqlite

from zikaron.core.config.resolution import resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge import arms, disposal, lifecycle, search
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.knowledge.indexer.main import build_settings

import m26_chunking_variants as variants

KB_NAME = "levers"
SEED = 20260920
DEFAULT_QUERIES = 150
LIMIT_PER_KB = 5

#: What share of a section's body lines must reach the caller for the query to count as answered.
#: A section is prose rather than a single fact, so a fragment of it is usually not the answer;
#: requiring all of it would instead measure the budget rather than the retrieval.
COVERAGE = 0.5

#: Headings too generic to be a question about anything. The same list M25 settled on.
_GENERIC = frozenset(
    {
        "overview", "summary", "background", "motivation", "introduction", "conclusion",
        "guide-level explanation", "reference-level explanation", "detailed design",
        "drawbacks", "rationale and alternatives", "prior art", "unresolved questions",
        "future possibilities", "appendix", "references", "notes", "glossary", "abstract",
        "goals", "non-goals", "alternatives", "open questions", "design", "implementation",
    }
)
_HEADING = re.compile(r"^(#{2,4})\s+(.{4,90}?)\s*$")
_FENCE = "```"

#: A section with less body than this cannot be meaningfully "covered" and is not sampled.
_MIN_BODY_LINES = 6

#: How many consecutive lines a `verbatim` guard query is lifted from, and the least prose those
#: lines must carry — enough that the span is unique in the corpus rather than boilerplate.
_SPAN_LINES = 4
_SPAN_MIN_WORDS = 25


@dataclass(frozen=True, slots=True)
class LineTruth:
    """One query, and the lines that answer it — read from the file, never from an index."""

    family: str
    text: str
    path: str
    first_line: int
    last_line: int

    @property
    def lines(self) -> set[int]:
        return set(range(self.first_line, self.last_line + 1))


def build_span_queries(corpus_root: Path, wanted: int) -> list[LineTruth]:
    """Exact contiguous spans lifted from the corpus, as a guard rather than as the measurement.

    A chunking change that improved conceptual lookup by breaking exact-phrase lookup would not be
    an improvement, and this is the family that would show it: the query appears verbatim in
    exactly one place, so any arm should find it. Truth is the line range the span was taken from,
    so the oracle is the same one the heading family uses and is equally index-independent.
    """
    candidates: list[tuple[str, int, int, list[str]]] = []
    for path in sorted(corpus_root.rglob("*.md")):
        relative = str(path.relative_to(corpus_root))
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for start in range(0, len(lines) - _SPAN_LINES, _SPAN_LINES * 4):
            window = lines[start : start + _SPAN_LINES]
            if sum(len(line.split()) for line in window) >= _SPAN_MIN_WORDS and not any(
                line.lstrip().startswith(_FENCE) for line in window
            ):
                candidates.append((relative, start + 1, start + _SPAN_LINES, window))
    rng = random.Random(SEED + 1)  # noqa: S311 — sampling a query set, not generating a secret
    rng.shuffle(candidates)
    return [
        LineTruth(
            family="verbatim",
            text=" ".join(" ".join(window).split()),
            path=relative,
            first_line=first,
            last_line=last,
        )
        for relative, first, last, window in candidates[:wanted]
    ]


def build_queries(corpus_root: Path, wanted: int) -> list[LineTruth]:
    """Heading queries whose truth is the section's body line range, in file coordinates.

    The heading line itself is excluded from truth: it contains the query verbatim, so a result
    covering only the heading would score as an answer while telling the caller nothing.
    """
    candidates: list[LineTruth] = []
    for path in sorted(corpus_root.rglob("*.md")):
        relative = str(path.relative_to(corpus_root))
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        fenced = False
        headings: list[tuple[int, int, str]] = []
        for number, line in enumerate(lines, start=1):
            if line.lstrip().startswith(_FENCE):
                fenced = not fenced
                continue
            if fenced:
                continue
            match = _HEADING.match(line)
            if match and match.group(2).strip().lower() not in _GENERIC:
                headings.append((number, len(match.group(1)), match.group(2).strip()))
        for position, (number, level, title) in enumerate(headings):
            following = next(
                (n for n, lv, _ in headings[position + 1 :] if lv <= level), len(lines) + 1
            )
            first, last = number + 1, following - 1
            if last - first + 1 >= _MIN_BODY_LINES:
                candidates.append(
                    LineTruth(
                        family="heading",
                        text=title,
                        path=relative,
                        first_line=first,
                        last_line=last,
                    )
                )
    rng = random.Random(SEED)  # noqa: S311 — sampling a query set, not generating a secret
    rng.shuffle(candidates)
    return candidates[:wanted]


async def is_complete(workspace: Path) -> bool:
    """Whether this arm's index is a *finished* build rather than merely a file that exists.

    An interrupted build leaves a database that opens cleanly and answers every query with
    whatever it had committed, so "the file is there" is not evidence that the arm is comparable
    to the others — it would quietly contribute a short corpus to the comparison. The build's own
    completion stamp is the evidence, and it is written only when the scan finished.
    """
    store_dir = workspace / ".zikaron"
    if not (store_dir / "memory.db").exists():
        return False
    try:
        async with aiosqlite.connect(store_dir / "memory.db") as memory:
            found = await memory.execute_fetchall(
                "SELECT id FROM knowledge_bases WHERE name = ?", (KB_NAME,)
            )
        if not found:
            return False
        from uuid import UUID  # noqa: PLC0415

        path = store_dir / "knowledge" / f"{UUID(str(found[0][0]))}.db"
        async with aiosqlite.connect(path) as kb:
            rows = await kb.execute_fetchall(
                "SELECT value FROM meta WHERE key = 'last_scan_completed_at'"
            )
        return bool(rows and str(rows[0][0]))
    except (aiosqlite.Error, OSError, ValueError):
        return False


async def build_store(corpus_root: Path, workspace: Path, chunker) -> float:  # noqa: ANN001
    """Build one knowledge base with `chunker` in place of the shipped one. Returns seconds."""
    workspace.mkdir(parents=True, exist_ok=True)
    config = resolve(workspace / "system.toml", workspace / "project.toml")
    store_dir = workspace / ".zikaron"
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
    started = time.monotonic()
    async with await Store.create(store_dir, config, embedder) as store:
        await lifecycle.add(
            store_dir,
            store.connection,
            config,
            lifecycle.AddRequest(
                name=KB_NAME,
                root=corpus_root,
                description="chunking lever experiment",
                git_mode=GitMode.OFF,
            ),
        )
        build = await build_settings(config)
        with patch.object(disposal.chunking, "plan_file_chunks", chunker):
            await lifecycle.refresh(
                store_dir, store.connection, config, name=KB_NAME, build=build
            )
    return time.monotonic() - started


async def neighbours_of(
    db: aiosqlite.Connection, results: tuple[search.Result, ...]
) -> list[tuple[str, int, int, int]]:
    """Each result's line range widened to the chunks around it, with what that costs to deliver.

    The character count is the widened text's own, **not** the original snippet's. Widening buys
    coverage by sending more, so measuring the cost of the un-widened result would report the
    extra coverage as free and would recommend this arm on a quantity it never measured.
    """
    widened: list[tuple[str, int, int, int]] = []
    for result in results:
        rows = await db.execute_fetchall(
            "SELECT start_line, end_line, text FROM chunks WHERE path = ? "
            "AND part_index BETWEEN "
            "(SELECT part_index - 1 FROM chunks WHERE path = ? AND start_line = ?) AND "
            "(SELECT part_index + 1 FROM chunks WHERE path = ? AND start_line = ?)",
            (result.path, result.path, result.start_line, result.path, result.start_line),
        )
        if not rows:
            widened.append((result.path, result.start_line, result.end_line, len(result.snippet)))
            continue
        first = min(int(row[0]) for row in rows)
        last = max(int(row[1]) for row in rows)
        widened.append((result.path, first, last, sum(len(str(row[2])) for row in rows)))
    return widened


def stitched(ranges: list[tuple[str, int, int, int]]) -> list[tuple[str, int, int, int]]:
    """Results of one file whose line ranges touch or overlap, merged into single ranges.

    Two chunks that are adjacent in a file are two views of one continuous passage, and returning
    them separately makes a reader reassemble what the index took apart. Where the chunker
    overlaps, it also makes the caller read the shared lines twice and spends two of a file's
    capped slots on one span of text.

    The delivered cost is recomputed from the merged span rather than summed from the parts, since
    the whole point is that the shared lines are sent once. Ranges are assumed to carry a cost
    proportional to their length, which is what lets a merged span be priced without re-reading
    the file.
    """
    merged: list[tuple[str, int, int, int]] = []
    for path, first, last, cost in sorted(ranges):
        density = cost / max(1, last - first + 1)
        if merged and merged[-1][0] == path and first <= merged[-1][2] + 1:
            previous = merged[-1]
            span_last = max(previous[2], last)
            merged[-1] = (
                path,
                previous[1],
                span_last,
                round(density * (span_last - previous[1] + 1)),
            )
            continue
        merged.append((path, first, last, cost))
    return merged


async def score_arm(
    workspace: Path, queries: list[LineTruth], *, widen: bool = False, stitch: bool = False
) -> dict[str, object]:
    """One arm's coverage hit rate and what it cost in delivered characters."""
    config = resolve(workspace / "system.toml", workspace / "project.toml")
    store_dir = workspace / ".zikaron"
    async with aiosqlite.connect(store_dir / "memory.db") as memory:
        found = await memory.execute_fetchall(
            "SELECT id FROM knowledge_bases WHERE name = ?", (KB_NAME,)
        )
    from uuid import UUID  # noqa: PLC0415

    encoder = await asyncio.to_thread(FastEmbedEncoder.load, config.get_str("embed_model"))
    knowledge = await KnowledgeDatabase.open(store_dir, UUID(str(found[0][0])))
    settings = search.SearchSettings(
        limit_per_kb=LIMIT_PER_KB,
        max_chunks_per_file=config.get_int("knowledge_max_chunks_per_file"),
        snippet_max_chars=config.get_int("knowledge_snippet_max_chars"),
    )
    hits: dict[str, list[int]] = {}
    coverages: dict[str, list[float]] = {}
    delivered: dict[str, list[int]] = {}
    try:
        db = knowledge.connection
        chunk_total = (await db.execute_fetchall("SELECT COUNT(*) FROM chunks"))[0][0]
        for query in queries:
            built = await asyncio.to_thread(
                arms.unit_query,
                query.text,
                encoder=encoder,
                prefix=config.get_str("embed_prefix_query"),
                max_terms=config.get_int("fts_query_max_terms"),
            )
            results = await search.search_one(
                db, query=built.prepared, corpus=knowledge.meta, settings=settings
            )
            ranges = (
                await neighbours_of(db, results)
                if widen
                else [
                    (r.path, r.start_line, r.end_line, len(r.snippet)) for r in results
                ]
            )
            if stitch:
                ranges = stitched(ranges)
            covered: set[int] = set()
            for path, first, last, _ in ranges:
                if path == query.path:
                    covered |= set(range(first, last + 1)) & query.lines
            share = len(covered) / len(query.lines)
            coverages.setdefault(query.family, []).append(share)
            hits.setdefault(query.family, []).append(int(share >= COVERAGE))
            delivered.setdefault(query.family, []).append(sum(cost for *_, cost in ranges))
    finally:
        await knowledge.close()
    return {
        "chunks": int(chunk_total),
        "by_family": {
            family: {
                "queries": len(scores),
                "coverage_hit_rate": round(statistics.fmean(scores), 4),
                "any_overlap_rate": round(
                    statistics.fmean([int(c > 0) for c in coverages[family]]), 4
                ),
                "mean_coverage": round(statistics.fmean(coverages[family]), 4),
                "median_delivered_chars": round(statistics.median(delivered[family]), 1),
            }
            for family, scores in sorted(hits.items())
        },
    }


async def main() -> int:
    if len(sys.argv) < 3:  # noqa: PLR2004 — corpus root and workspace root
        print(__doc__)
        return 2
    corpus_root = Path(sys.argv[1]).expanduser().resolve()
    root = Path(sys.argv[2]).expanduser().resolve()
    wanted = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_QUERIES  # noqa: PLR2004

    queries = build_queries(corpus_root, wanted) + build_span_queries(corpus_root, wanted)
    counted = Counter(query.family for query in queries)
    print(f"{len(queries)} queries with line-range truth: {dict(counted)}", file=sys.stderr)

    from zikaron.core.knowledge.chunking import plan_file_chunks  # noqa: PLC0415

    # `no_overlap` is a control, not a candidate. The two variants pack lines greedily while the
    # shipped chunker packs whole paragraphs, so `overlap` against `baseline` would confound the
    # overlap with the change of packing unit. This arm is the variants' own packing with the
    # overlap set to zero, which separates the two: overlap's effect is `overlap` against this,
    # and the packing unit's effect is this against `baseline`.
    plans = {
        "baseline": plan_file_chunks,
        "no_overlap": variants.plan_without_overlap,
        "overlap": variants.plan_with_overlap,
        "section": variants.plan_by_section,
        "breadcrumb": variants.plan_with_breadcrumb,
        "section_overlap": variants.plan_section_overlap,
        "section_overlap_crumb": variants.plan_section_overlap_breadcrumb,
    }
    report: dict[str, object] = {
        "load_average_1m": round(os.getloadavg()[0], 2),
        "corpus_root": str(corpus_root),
        "coverage_threshold": COVERAGE,
        "queries": len(queries),
        "arms": {},
    }
    def show(name: str, scored: dict[str, object]) -> None:
        report["arms"][name] = scored  # type: ignore[index]
        for family, stats in scored["by_family"].items():  # type: ignore[union-attr]
            print(
                f"{name:<11} {family:<9} hit {stats['coverage_hit_rate']:.4f}  "
                f"any {stats['any_overlap_rate']:.4f}  "
                f"mean_cov {stats['mean_coverage']:.4f}  "
                f"chars {stats['median_delivered_chars']:.0f}  "
                f"(chunks {scored['chunks']})",
                file=sys.stderr,
            )

    for name, chunker in plans.items():
        workspace = root / name
        if not await is_complete(workspace):
            seconds = await build_store(corpus_root, workspace, chunker)
            print(f"built {name} in {seconds:.0f}s", file=sys.stderr)
        show(name, await score_arm(workspace, queries))

    # Query-time arms over indexes already built: widening every result to its neighbours, and
    # merging results that are adjacent in the same file. The second needs no extra text at all.
    show("neighbours", await score_arm(root / "baseline", queries, widen=True))
    for name in ("baseline", "overlap", "section", "section_overlap"):
        show(f"{name}+stitch", await score_arm(root / name, queries, stitch=True))

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
