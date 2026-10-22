"""M40's retrieval replay: every knowledge search a treatment reader sent, run against both corpora.

    .venv/bin/python experiments/m40_retrieval_replay.py

For `research/m40-evaluation.md` §5 (operator, 2026-10-21): whether the regenerated documents
rank a truth file higher than the Sonnet 4.6 ones for the same queries, free of the reader's
variance. The queries are the treatment's, as each run record holds them — the slice's, archived,
and the three repeats' — and both corpora are registered in the clone's store, so the same project
root links both to the same sources and only the documents differ.

Second, from the transcripts: the tool calls each kept run made before it first touched a truth
file — a `Read` of it, a `Grep` given it as `path`, or a `Bash` command naming it.
"""

import asyncio
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from zikaron.knowledge.client import connected

BASE = Path.home() / "Zikaron-m40"
CLONE = BASE / "warp"
RUNS = {"slice": Path.home() / "Zikaron-m40-archive" / "eval-06deae8" / "runs", "repeats": BASE / "eval" / "runs"}
ISSUES = Path(__file__).resolve().parent / "m40_eval_issues.json"
CORPORA = {"sonnet46": "replay-sonnet46-terminal", "regenerated": "code-knowledge/app/src/terminal"}


def _truth() -> dict[int, set[str]]:
    issues = json.loads(ISSUES.read_text(encoding="utf-8"))["issues"]
    return {int(i["issue"]): set(i["truth"]) for i in issues}


def _queries() -> list[dict[str, object]]:
    found = []
    for origin, runs in RUNS.items():
        for path in sorted(runs.glob("r*-*-treatment-*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            for search in record.get("searches") or []:
                found.append(
                    {
                        "origin": origin,
                        "run": path.stem,
                        "issue": int(record["issue"]),
                        "query": search["query"],
                        "limit_per_kb": search.get("limit_per_kb"),
                    }
                )
    return found


def _rank(results: list[dict[str, object]], truth: set[str]) -> tuple[int | None, int]:
    """The first truth file's place among the distinct sources returned, and how many truth files."""
    sources: list[str] = []
    for result in results:
        source = result.get("source")
        path = source.get("path") if isinstance(source, dict) else None
        if isinstance(path, str) and path not in sources:
            sources.append(path)
    rank = next((n + 1 for n, s in enumerate(sources) if s in truth), None)
    return rank, len(truth & set(sources))


async def _replay(queries: list[dict[str, object]], truth: dict[int, set[str]]) -> None:
    async with connected(CLONE) as client:
        for q in queries:
            for label, corpus in CORPORA.items():
                params: dict[str, object] = {"query": q["query"], "knowledge_bases": [corpus]}
                if q["limit_per_kb"] is not None:
                    params["limit_per_kb"] = q["limit_per_kb"]
                answer = await client.call("knowledge_search", params)
                groups = answer.get("groups") or []
                results = groups[0]["results"] if groups else []  # type: ignore[index]
                q[label] = _rank(list(results), truth[int(str(q["issue"]))])


def _summary(rows: list[dict[str, object]], label: str) -> str:
    ranks = [r[label][0] for r in rows]  # type: ignore[index]
    hits = sum(1 for k in ranks if k is not None)
    mrr = statistics.fmean(1 / k if k else 0 for k in ranks) if ranks else 0.0
    found = sum(r[label][1] for r in rows)  # type: ignore[index]
    return f"hit {hits}/{len(rows)}  first {sum(1 for k in ranks if k == 1)}  MRR {mrr:.3f}  truth files returned {found}"


def _first_touch(transcript: Path, truth: set[str]) -> int | None:
    calls = 0
    for line in transcript.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("type") != "assistant":
            continue
        for block in record["message"]["content"]:
            if block.get("type") != "tool_use":
                continue
            given = block.get("input") or {}
            text = json.dumps(given)
            touched = (
                block["name"] in ("Read", "Grep")
                and any(str(given.get(k, "")).endswith(t) for k in ("file_path", "path") for t in truth)
            ) or (block["name"] == "Bash" and any(t in text for t in truth))
            if touched:
                return calls
            calls += 1
    return None


def main() -> int:
    truth = _truth()
    queries = _queries()
    asyncio.run(_replay(queries, truth))
    print(f"queries: {len(queries)}, distinct {len({(q['issue'], q['query']) for q in queries})}")
    for origin in ("all", *RUNS):
        rows = [q for q in queries if origin in ("all", q["origin"])]
        for label in CORPORA:
            print(f"{origin:8} {label:12} {_summary(rows, label)}")
    print("\nper issue (regenerated vs sonnet46: queries with a truth file, of all)")
    by_issue: dict[int, list[dict[str, object]]] = defaultdict(list)
    for q in queries:
        by_issue[int(str(q["issue"]))].append(q)
    for issue, rows in sorted(by_issue.items()):
        new = sum(1 for r in rows if r["regenerated"][0] is not None)  # type: ignore[index]
        old = sum(1 for r in rows if r["sonnet46"][0] is not None)  # type: ignore[index]
        print(f"  {issue:6} {new:3} vs {old:3} of {len(rows)}")
    print("\ntool calls before first touching a truth file, kept runs of repeats 1-3 (median, untouched)")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import m40_eval

    touches: dict[str, list[int | None]] = defaultdict(list)
    for (_, issue), arms in sorted(m40_eval.kept_runs(m40_eval.Layout(BASE)).items()):
        for arm, record in arms.items():
            if record is not None:
                transcript = RUNS["repeats"] / str(record["transcript"])
                touches[arm].append(_first_touch(transcript, truth[issue]))
    for arm, values in sorted(touches.items()):
        seen = [v for v in values if v is not None]
        median = statistics.median(seen) if seen else None
        print(f"  {arm:9} runs {len(values)}  median {median}  never {len(values) - len(seen)}")
    (BASE / "eval" / "replay.json").write_text(json.dumps(queries, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
