"""Score the chunking arms on questions real people actually asked.

Every earlier comparison here used **section headings** as queries, and that is not how anyone
reaches a knowledge base: the chance of a user's words matching a heading is low, and the arm that
won cuts the corpus *at* headings, so the result and the instrument share a bias nothing in the
run could separate. This harness replaces the query set with 20 verified questions asked by real
people on forums, mailing lists and issue trackers, gathered without regard to whether any
document answers them.

**Truth is a line range, and a grader supplies it.** A real question has no mechanical answer key.
So each arm's results are pooled, a separate model labels every pooled passage for whether it
answers the question, and the line ranges of the passages it labels as answering become truth.
That definition is **independent of how any arm cut the corpus**, which is what lets one labelling
pass score seven differently-chunked indexes — and what makes the labels reusable for arms that do
not exist yet.

**Pooling is over every arm, at a depth past what a caller sees**, so no arm's own ranking decides
what is eligible to be truth. A question with no answering passage anywhere is reported and
excluded: it cannot distinguish arms.

Two steps, because the middle one is a model:

    .venv/bin/python experiments/m26_real_questions.py pool  <questions.json> <arms-root> <out.json>
    .venv/bin/python experiments/m26_real_questions.py score <pool.json> <labels.json> <arms-root>
"""

import asyncio
import json
import statistics
import sys
from pathlib import Path
from uuid import UUID

import aiosqlite

from zikaron.core.config.resolution import resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge import arms as knowledge_arms
from zikaron.core.knowledge import search
from zikaron.core.knowledge.database import KnowledgeDatabase

KB_NAME = "levers"
ARMS = (
    "baseline",
    "no_overlap",
    "overlap",
    "breadcrumb",
    "section",
    "section_overlap",
    "section_overlap_crumb",
)

#: What a caller actually receives, and what the arms are scored on.
LIMIT_PER_KB = 5
MAX_CHUNKS_PER_FILE = 2

#: The pool is deeper than the caller's view and ignores the per-file cap, so that what is eligible
#: to be truth is not decided by the same ranking under test.
POOL_LIMIT = 10
POOL_MAX_PER_FILE = 10

#: An arm is credited when it delivers this share of an answering passage's lines. A passage is a
#: paragraph or two, so a fragment of one is usually not the answer; demanding all of it would
#: measure the snippet budget instead of the retrieval.
COVERAGE = 0.5


async def _open(workspace: Path) -> tuple[KnowledgeDatabase, object]:
    config = resolve(workspace / "system.toml", workspace / "project.toml")
    store_dir = workspace / ".zikaron"
    async with aiosqlite.connect(store_dir / "memory.db") as memory:
        found = await memory.execute_fetchall(
            "SELECT id FROM knowledge_bases WHERE name = ?", (KB_NAME,)
        )
    if not found:
        raise SystemExit(f"no knowledge base {KB_NAME!r} in {store_dir}")
    return await KnowledgeDatabase.open(store_dir, UUID(str(found[0][0]))), config


async def _results(
    knowledge: KnowledgeDatabase,
    config: object,
    encoder: FastEmbedEncoder,
    text: str,
    *,
    limit: int,
    per_file: int,
) -> tuple[search.Result, ...]:
    built = await asyncio.to_thread(
        knowledge_arms.unit_query,
        text,
        encoder=encoder,
        prefix=config.get_str("embed_prefix_query"),  # type: ignore[attr-defined]
        max_terms=config.get_int("fts_query_max_terms"),  # type: ignore[attr-defined]
    )
    return await search.search_one(
        knowledge.connection,
        query=built.prepared,
        corpus=knowledge.meta,
        settings=search.SearchSettings(
            limit_per_kb=limit,
            max_chunks_per_file=per_file,
            snippet_max_chars=config.get_int("knowledge_snippet_max_chars"),  # type: ignore[attr-defined]
        ),
    )


async def pool(questions_path: Path, root: Path, out_path: Path) -> int:
    """Collect every passage any arm surfaces, deduplicated, for a grader to label."""
    questions = json.loads(questions_path.read_text())
    encoder = await asyncio.to_thread(FastEmbedEncoder.load, "BAAI/bge-small-en-v1.5")
    pooled: dict[str, dict[tuple[str, int, int], str]] = {q["id"]: {} for q in questions}
    for arm in ARMS:
        knowledge, config = await _open(root / arm)
        try:
            for question in questions:
                for result in await _results(
                    knowledge,
                    config,
                    encoder,
                    question["text"],
                    limit=POOL_LIMIT,
                    per_file=POOL_MAX_PER_FILE,
                ):
                    key = (result.path, result.start_line, result.end_line)
                    pooled[question["id"]].setdefault(key, result.snippet)
        finally:
            await knowledge.close()
        print(f"pooled {arm}", file=sys.stderr)

    payload = [
        {
            "id": question["id"],
            "question": question["text"],
            "passages": [
                {
                    "n": index,
                    "path": path,
                    "start_line": first,
                    "end_line": last,
                    "text": text,
                }
                for index, ((path, first, last), text) in enumerate(
                    sorted(pooled[question["id"]].items()), start=1
                )
            ],
        }
        for question in questions
    ]
    out_path.write_text(json.dumps(payload, indent=2))
    sizes = [len(item["passages"]) for item in payload]
    print(
        f"{len(payload)} questions, {sum(sizes)} passages to label "
        f"(median {statistics.median(sizes):.0f} each) -> {out_path}",
        file=sys.stderr,
    )
    return 0


async def score(pool_path: Path, labels_path: Path, root: Path) -> int:
    """Score every arm against the graded line ranges."""
    pooled = {item["id"]: item for item in json.loads(pool_path.read_text())}
    labels = json.loads(labels_path.read_text())
    truth: dict[str, list[tuple[str, set[int]]]] = {}
    for entry in labels:
        answering = {int(n) for n in entry["answering"]}
        spans: list[tuple[str, set[int]]] = []
        for passage in pooled[entry["id"]]["passages"]:
            if passage["n"] in answering:
                spans.append(
                    (passage["path"], set(range(passage["start_line"], passage["end_line"] + 1)))
                )
        truth[entry["id"]] = spans

    usable = [qid for qid, spans in truth.items() if spans]
    print(
        f"{len(usable)} of {len(truth)} questions have an answering passage; "
        f"{len(truth) - len(usable)} excluded as undecidable",
        file=sys.stderr,
    )

    encoder = await asyncio.to_thread(FastEmbedEncoder.load, "BAAI/bge-small-en-v1.5")
    report: dict[str, object] = {"questions": len(truth), "usable": len(usable), "arms": {}}
    per_question: dict[str, dict[str, int]] = {}
    for arm in ARMS:
        knowledge, config = await _open(root / arm)
        hits: list[int] = []
        delivered: list[int] = []
        try:
            for qid in usable:
                results = await _results(
                    knowledge,
                    config,
                    encoder,
                    pooled[qid]["question"],
                    limit=LIMIT_PER_KB,
                    per_file=MAX_CHUNKS_PER_FILE,
                )
                got = 0
                for path, lines in truth[qid]:
                    covered: set[int] = set()
                    for result in results:
                        if result.path == path:
                            covered |= set(
                                range(result.start_line, result.end_line + 1)
                            ) & lines
                    if len(covered) / len(lines) >= COVERAGE:
                        got = 1
                        break
                hits.append(got)
                delivered.append(sum(len(r.snippet) for r in results))
                per_question.setdefault(qid, {})[arm] = got
        finally:
            await knowledge.close()
        report["arms"][arm] = {  # type: ignore[index]
            "hit_rate": round(statistics.fmean(hits), 4),
            "hits": sum(hits),
            "of": len(hits),
            "median_delivered_chars": round(statistics.median(delivered), 1),
        }
        print(
            f"{arm:<24} {sum(hits):>2}/{len(hits)}  {statistics.fmean(hits):.4f}  "
            f"chars {statistics.median(delivered):.0f}",
            file=sys.stderr,
        )
    report["per_question"] = per_question
    print(json.dumps(report, indent=2))
    return 0


async def main() -> int:
    if len(sys.argv) < 2:  # noqa: PLR2004
        print(__doc__)
        return 2
    if sys.argv[1] == "pool":
        return await pool(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    if sys.argv[1] == "score":
        return await score(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
