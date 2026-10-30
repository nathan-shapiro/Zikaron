"""Paged knowledge search replayed over M40's runs: which result ranks a reader acts on, and what
showing every result below the first three by name alone would have saved.

    .venv/bin/python experiments/paged_search_replay.py

For `research/paged-search-replay.md` (operator, 2026-10-30). Reads every kept treatment run's
transcript, its reply, and the documents in the treatment copy; no model call.

- **A use** is a result's source path, or its document's path, named by one of the next
  `WINDOW` tool calls after the search — a `Read`, a `Grep`, a `Bash` command — the predicate of
  `research/transcript-measurements-2026-10-30.md` §2, applied to every rank, not the top one.
- **A path's rank** is the best rank any search of the run had shown it at, up to and including
  this one, since a path shown whole earlier is not hidden by a later search naming it lower.
- **A named entry** is what paging would show below `WHOLE`: the document's path, the line
  range, the source's path and state, and the document's role line (`design/code-knowledge.md`
  §4), serialized as the result is.
- **Carried** is a result's size times the model calls after it, `m40_breakdown._carried`'s
  measure; paged carried replaces each search result's size with its paged size and assumes no
  page is fetched, so the saving is a ceiling.
"""

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m40_breakdown
import m40_eval

WHOLE = 3
WINDOW = 20
BUCKETS = ((1, "1"), (2, "2"), (3, "3"), (5, "4-5"), (10, "6-10"), (10**9, "11+"))
UNSHOWN = 10**9
_REPLY_PATH = re.compile(r"`([\w./-]+/[\w.-]+\.\w+)`")


@dataclass(frozen=True, slots=True)
class Search:
    index: int
    calls_after: int
    size: int
    limit: int
    results: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class Run:
    issue: int
    repeat: int
    letter: str
    tool_inputs: tuple[tuple[int, str, str], ...]
    searches: tuple[Search, ...]
    carried_total: float
    reply: str


@dataclass(slots=True)
class Tally:
    searches: int = 0
    over_whole: int = 0
    limits: Counter[int] = field(default_factory=Counter)
    roles: dict[tuple[str, str], str | None] = field(default_factory=dict)
    shown: Counter[str] = field(default_factory=Counter)
    used: Counter[tuple[str, str]] = field(default_factory=Counter)
    used_pairs: set[tuple[int, int, str]] = field(default_factory=set)
    deep_pairs: set[tuple[int, int, str]] = field(default_factory=set)
    deep_paths: Counter[str] = field(default_factory=Counter)
    size_full: int = 0
    size_paged: float = 0.0
    carried: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0] * 4))
    reply: Counter[tuple[str, bool]] = field(default_factory=Counter)
    reply_hidden: list[tuple[int, int, str, int, bool]] = field(default_factory=list)


def _bucket(rank: int) -> str:
    return next(label for ceiling, label in BUCKETS if rank <= ceiling)


def _names(text: str, path: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(path)}(?![\w.-])", text) is not None


def _results(content: object) -> tuple[dict[str, object], ...]:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(block.get("text", "") for block in content if isinstance(block, dict))
    else:
        return ()
    try:
        groups = json.loads(text)["result"]["groups"]
    except (ValueError, KeyError, TypeError):
        return ()
    return tuple(result for group in groups for result in group.get("results", ()))


def _read_run(transcript: Path, record: dict[str, object]) -> Run:
    seen_calls: set[str] = set()
    names: dict[str, tuple[int, str, dict[str, object]]] = {}
    arrivals: list[tuple[str, int, int, object]] = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("type") == "assistant":
            seen_calls.add(entry["message"]["id"])
            for block in entry["message"]["content"]:
                if block.get("type") == "tool_use":
                    names[block["id"]] = (len(names), block["name"], block["input"])
        elif entry.get("type") == "user" and isinstance(entry["message"]["content"], list):
            for block in entry["message"]["content"]:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in names:
                    content = block.get("content")
                    size = len(content) if isinstance(content, str) else len(json.dumps(content))
                    arrivals.append((block["tool_use_id"], size, len(seen_calls), content))
    total = len(seen_calls)
    searches = []
    carried = 0.0
    for use_id, size, before, content in arrivals:
        carried += size * (total - before)
        index, name, arguments = names[use_id]
        if name == m40_breakdown.SEARCH:
            limit = int(str(arguments.get("limit_per_kb", 5)))
            searches.append(Search(index, total - before, size, limit, _results(content)))
    return Run(
        issue=int(str(record["issue"])),
        repeat=int(str(record["repeat"])),
        letter=str(record["letter"]),
        tool_inputs=tuple(
            (i, name, json.dumps(arguments)) for i, name, arguments in names.values()
        ),
        searches=tuple(sorted(searches, key=lambda one: one.index)),
        carried_total=carried,
        reply=json.dumps(record["reply"]),
    )


def _role_line(document: Path) -> str | None:
    try:
        lines = document.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if lines and lines[0].strip() == "---":
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        lines = lines[closing + 1 :] if closing is not None else lines
    after_title = [line for line in lines if line.strip()][1:]
    role = []
    for line in after_title:
        if line.startswith("##"):
            break
        role.append(line.strip())
    return " ".join(role) or None


def _source(result: dict[str, object]) -> str | None:
    source = result.get("source")
    return str(source["path"]) if isinstance(source, dict) and source.get("path") else None


def _paged_ratio(search: Search, documents: Path, letter: str, tally: Tally) -> float:
    """The paged result's size over the returned one's, both serialized the same way."""
    if not search.results:
        return 1.0
    paged: list[dict[str, object]] = list(search.results[:WHOLE])
    for result in search.results[WHOLE:]:
        key = (letter, str(result["path"]))
        if key not in tally.roles:
            tally.roles[key] = _role_line(documents / str(result["path"]))
        paged.append(
            {
                "path": result["path"],
                "start_line": result["start_line"],
                "end_line": result["end_line"],
                "role": tally.roles[key] or "",
                "source": result.get("source"),
            }
        )
    return len(json.dumps(paged)) / len(json.dumps(list(search.results)))


def _uses(run: Run, search: Search, best: dict[str, int], tally: Tally) -> None:
    """Credit each distinct path this search showed with a use if the window names it."""
    first_rank: dict[str, tuple[int, str]] = {}
    for rank, result in enumerate(search.results, start=1):
        document = f"{m40_eval.CORPUS}/{result['path']}"
        first_rank.setdefault(_source(result) or document, (rank, document))
    window = [
        text
        for index, name, text in run.tool_inputs
        if search.index < index <= search.index + WINDOW and name != m40_breakdown.SEARCH
    ]
    for path, (rank, document) in first_rank.items():
        effective = min(rank, best.get(path, rank))
        tally.shown[_bucket(effective)] += 1
        if any(_names(text, path) for text in window):
            how = "source"
        elif any(_names(text, document) for text in window):
            how = "document"
        else:
            continue
        tally.used[(_bucket(effective), how)] += 1
        tally.used_pairs.add((run.issue, run.repeat, path))
        if effective > WHOLE:
            tally.deep_pairs.add((run.issue, run.repeat, path))
            tally.deep_paths[path] += 1
    for path, (rank, _document) in first_rank.items():
        best[path] = min(rank, best.get(path, rank))


def _reply(run: Run, best: dict[str, int], truth: set[str], tally: Tally) -> None:
    """Class each file the reply names by how the reader had it."""
    reads = " ".join(text for _, name, text in run.tool_inputs if name != m40_breakdown.SEARCH)
    for named in sorted(set(_REPLY_PATH.findall(run.reply))):
        is_truth = named in truth
        rank = best.get(named, UNSHOWN)
        if _names(reads, named):
            how = "read"
        elif rank <= WHOLE:
            how = "shown whole, unread"
        elif rank < UNSHOWN:
            how = "only below the whole, unread"
            tally.reply_hidden.append((run.issue, run.repeat, named, rank, is_truth))
        else:
            how = "never shown, unread"
        tally.reply[(how, is_truth)] += 1


def _replay(run: Run, tier: str, truth: set[str], layout: m40_eval.Layout, tally: Tally) -> None:
    best: dict[str, int] = {}
    documents = layout.copy(run.letter) / m40_eval.CORPUS
    row = tally.carried[tier]
    row[0] += 1
    row[1] += run.carried_total
    for search in run.searches:
        tally.searches += 1
        tally.over_whole += len(search.results) > WHOLE
        tally.limits[search.limit] += 1
        ratio = _paged_ratio(search, documents, run.letter, tally)
        tally.size_full += search.size
        tally.size_paged += search.size * ratio
        row[2] += search.size * search.calls_after
        row[3] += search.size * ratio * search.calls_after
        _uses(run, search, best, tally)
    _reply(run, best, truth, tally)


def _report(runs: int, tally: Tally) -> None:
    missing = sum(role is None for role in tally.roles.values())
    print(f"treatment runs {runs}, searches {tally.searches}, over {WHOLE}: {tally.over_whole}")
    print(f"limit_per_kb asked: {dict(sorted(tally.limits.items()))}")
    print(f"documents with no role line found: {missing} of {len(tally.roles)}")
    print("\nper search, a distinct path at its best rank so far (shown, used within the window):")
    for _, label in BUCKETS:
        shown = tally.shown[label]
        source, document = tally.used[(label, "source")], tally.used[(label, "document")]
        if shown:
            print(
                f"  rank {label:5} shown {shown:5}  used {source + document:4}"
                f"  ({(source + document) / shown:.1%})"
                f"  via source {source:3}, document {document:2}"
            )
    print(
        f"\nrun-path pairs used: {len(tally.used_pairs)}; first used while no search had shown "
        f"the path in the top {WHOLE}: {len(tally.deep_pairs)}"
    )
    print(f"uses below the top {WHOLE}, by path: {tally.deep_paths.most_common(8)}")
    print("\nreply's files, by how the reader had them (truth file or not):")
    for (how, is_truth), count in sorted(tally.reply.items()):
        print(f"  {how:28} truth={is_truth!s:5} {count}")
    for issue, repeat, path, rank, is_truth in tally.reply_hidden:
        print(f"    {issue} r{repeat} {path} best rank {rank} truth={is_truth}")
    print(
        f"\nsearch result characters, as returned {tally.size_full:,} and paged "
        f"{tally.size_paged:,.0f} ({tally.size_paged / tally.size_full:.1%})"
    )
    print("\ncarried per run, M chars (all results; search as returned; search paged; saving):")
    for name, _ in m40_breakdown.TIERS:
        count, total, full, paged = tally.carried[name]
        if count:
            print(
                f"  {name:8} runs {int(count):2}  total {total / count / 1e6:6.2f}"
                f"  search {full / count / 1e6:5.2f}  paged {paged / count / 1e6:5.2f}"
                f"  saving {(full - paged) / total:.1%} of the run"
            )


def main() -> int:
    layout = m40_eval.Layout(m40_breakdown.BASE)
    issues = json.loads(m40_eval.ISSUES.read_text(encoding="utf-8"))["issues"]
    truth = {int(issue["issue"]): set(issue["truth"]) for issue in issues}
    scores = json.loads((layout.eval / "scores.json").read_text(encoding="utf-8"))
    control_cost: dict[int, list[float]] = defaultdict(list)
    for row in scores["runs"]:
        if row["kept"] and row["arm"] == "control":
            control_cost[int(row["issue"])].append(row["total_cost_usd"] or 0.0)
    tier = {i: m40_breakdown._tier(statistics.median(c)) for i, c in control_cost.items()}
    tally = Tally()
    runs = 0
    for arms in m40_eval.kept_runs(layout).values():
        record = arms.get("treatment")
        if record is None:
            continue
        run = _read_run(layout.runs / str(record["transcript"]), record)
        _replay(run, tier[run.issue], truth[run.issue], layout, tally)
        runs += 1
    _report(runs, tally)
    return 0


if __name__ == "__main__":
    sys.exit(main())
