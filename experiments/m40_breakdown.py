"""M40's runs broken down by issue difficulty, which arm spent more, and which graded better.

    .venv/bin/python experiments/m40_breakdown.py

For `research/m40-evaluation.md` §6 (operator, 2026-10-22): whether the treatment spends more
dollars on hard issues and buys a better answer with them, and what the extra goes to. Reads
`<base>/eval/scores.json` and every kept run's transcript; no model call. Spend is measured in
dollars, `total_cost_usd`, which prices cached, uncached and output tokens apart (operator,
2026-10-22), where a token sum counts a cache read as much as an output token.

- **Difficulty** is the control's median dollars over its three runs: what an issue costs a
  reader with no documents, independent of what the treatment spent.
- **A pair** is one repeat of one issue, both arms run at once; it is the unit compared.
- **Spend** is the treatment's dollars over the control's in that pair.
- **Grade** scores correct 2, partly 1, wrong 0; a pair's grade difference is treatment minus
  control.
- **Calls and context**: total tokens are almost all cache reads, which a call pays once per token
  of its context, so they factor into the number of model calls times the mean context per call.
"""

import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m40_eval  # noqa: E402

BASE = Path.home() / "Zikaron-m40"
GRADE = {"correct": 2, "partly": 1, "wrong": 0}
SEARCH = "mcp__zikaron__zikaron_knowledge_search"
TIERS = (("trivial", 1.0), ("medium", 8.0), ("hard", math.inf))


def _calls(transcript: Path) -> dict[str, object]:
    """Model calls, their mean context, tool use by name, and the bytes search results returned."""
    context: dict[str, int] = {}
    tools: Counter[str] = Counter()
    search_ids: set[str] = set()
    search_bytes = 0
    reads: set[str] = set()
    for line in transcript.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("type") == "assistant":
            message = record["message"]
            usage = message.get("usage") or {}
            context[message["id"]] = (
                usage.get("input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
            )
            for block in message["content"]:
                if block.get("type") == "tool_use":
                    tools[block["name"]] += 1
                    if block["name"] == SEARCH:
                        search_ids.add(block["id"])
                    if block["name"] == "Read":
                        reads.add(str(block["input"].get("file_path")))
        elif record.get("type") == "user" and isinstance(record["message"]["content"], list):
            for block in record["message"]["content"]:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in search_ids:
                    search_bytes += len(json.dumps(block.get("content")))
    sizes = list(context.values())
    return {
        "calls": len(sizes),
        "mean_context": statistics.fmean(sizes) if sizes else 0.0,
        "tools": tools,
        "search_bytes": search_bytes,
        "files_read": len(reads),
    }


def _carried(transcript: Path) -> dict[str, list[float]]:
    """Per tool kind, each result's size in characters and that size times the model calls made
    after it arrived: a result stays in the context and is read again, from the cache, on every
    later call, so the product is what it costs the run, where its size is what it costs once."""
    names: dict[str, str] = {}
    seen_calls: set[str] = set()
    arrivals: list[tuple[str, int, int]] = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("type") == "assistant":
            seen_calls.add(record["message"]["id"])
            for block in record["message"]["content"]:
                if block.get("type") == "tool_use":
                    names[block["id"]] = "search" if block["name"] == SEARCH else block["name"]
        elif record.get("type") == "user" and isinstance(record["message"]["content"], list):
            for block in record["message"]["content"]:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in names:
                    content = block.get("content")
                    size = len(content) if isinstance(content, str) else len(json.dumps(content))
                    arrivals.append((names[block["tool_use_id"]], size, len(seen_calls)))
    total = len(seen_calls)
    out: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for name, size, before in arrivals:
        out[name][0] += 1
        out[name][1] += size
        out[name][2] += size * (total - before)
    return out


def _tier(dollars: float) -> str:
    return next(name for name, ceiling in TIERS if dollars < ceiling)


def main() -> int:
    layout = m40_eval.Layout(BASE)
    scores = json.loads((layout.eval / "scores.json").read_text(encoding="utf-8"))
    graded = {(r["repeat"], r["issue"], r["arm"]): r for r in scores["runs"] if r["kept"]}
    runs: dict[tuple[int, int, str], dict[str, object]] = {}
    for (repeat, issue), arms in m40_eval.kept_runs(layout).items():
        for arm, record in arms.items():
            if record is None:
                continue
            row = graded[(repeat, issue, arm)]
            runs[(repeat, issue, arm)] = {
                "tokens": row["usage"]["sum"],
                "cost": row["total_cost_usd"] or 0.0,
                "seconds": (row["duration_ms"] or 0) / 1000,
                "grade": GRADE[row["grade"]],
                "first": row["first_is_truth"],
                "carried": _carried(layout.runs / str(record["transcript"])),
                **_calls(layout.runs / str(record["transcript"])),
            }
    issues = sorted({issue for _, issue, _ in runs})
    difficulty = {
        i: statistics.median(r["cost"] for (_, n, a), r in runs.items() if n == i and a == "control")
        for i in issues
    }
    tier = {i: _tier(difficulty[i]) for i in issues}
    print("issues by difficulty (control's median dollars):")
    for i in sorted(issues, key=difficulty.get):
        print(f"  {i:6} ${difficulty[i]:6.2f}  {tier[i]}")

    pairs = []
    for repeat, issue, arm in runs:
        if arm != "treatment" or (repeat, issue, "control") not in runs:
            continue
        t, c = runs[(repeat, issue, "treatment")], runs[(repeat, issue, "control")]
        pairs.append(
            {
                "repeat": repeat,
                "issue": issue,
                "tier": tier[issue],
                "ratio": t["cost"] / c["cost"],
                "calls_ratio": t["calls"] / c["calls"],
                "context_ratio": t["mean_context"] / c["mean_context"],
                "delta": t["grade"] - c["grade"],
                "t": t,
                "c": c,
            }
        )

    def spend(ratio: float) -> str:
        return "T > 1.5x" if ratio > 1.5 else ("C > 1.5x" if ratio < 1 / 1.5 else "within 1.5x")

    print("\npairs: tier x spend -> grade (T better / equal / T worse), pairs")
    table: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for p in pairs:
        outcome = "better" if p["delta"] > 0 else ("worse" if p["delta"] < 0 else "equal")
        table[(p["tier"], spend(p["ratio"]))][outcome] += 1
    for name, _ in TIERS:
        for s in ("T > 1.5x", "within 1.5x", "C > 1.5x"):
            n = table[(name, s)]
            if n:
                total = sum(n.values())
                print(f"  {name:8} {s:12} better {n['better']:2}  equal {n['equal']:2}  worse {n['worse']:2}  of {total}")

    print("\nper tier: medians of the pair ratios (T/C) and grade sums")
    for name, _ in TIERS:
        ps = [p for p in pairs if p["tier"] == name]
        if not ps:
            continue
        t_grade = sum(p["t"]["grade"] for p in ps)
        c_grade = sum(p["c"]["grade"] for p in ps)
        print(
            f"  {name:8} pairs {len(ps):2}  dollars {statistics.median(p['ratio'] for p in ps):.2f}x"
            f" (T ${sum(p['t']['cost'] for p in ps):.0f} vs C ${sum(p['c']['cost'] for p in ps):.0f})"
            f"  calls {statistics.median(p['calls_ratio'] for p in ps):.2f}x"
            f"  context/call {statistics.median(p['context_ratio'] for p in ps):.2f}x"
            f"  grade T {t_grade} vs C {c_grade} of {2 * len(ps)}"
            f"  first-is-truth T {sum(p['t']['first'] for p in ps)} vs C {sum(p['c']['first'] for p in ps)}"
        )

    print("\nper tier and arm: mean tool calls per run by kind, files read, search result KB")
    kinds = ("Read", "Grep", "Glob", "Bash", SEARCH)
    for name, _ in TIERS:
        for arm in ("treatment", "control"):
            rs = [r for (_, i, a), r in runs.items() if a == arm and tier[i] == name]
            if not rs:
                continue
            counts = "  ".join(
                f"{k.split('_')[-1] if k == SEARCH else k} {statistics.fmean(r['tools'][k] for r in rs):5.1f}"
                for k in kinds
            )
            print(
                f"  {name:8} {arm:9} calls {statistics.fmean(r['calls'] for r in rs):6.1f}  {counts}"
                f"  files read {statistics.fmean(r['files_read'] for r in rs):5.1f}"
                f"  search KB {statistics.fmean(r['search_bytes'] for r in rs) / 1000:6.1f}"
            )

    print("\nper tier and arm, per run: tool results by kind — count, mean size (chars),")
    print("and carried (size x later calls, M chars), the share of the run's carried total")
    for name, _ in TIERS:
        for arm in ("treatment", "control"):
            rs = [r for (_, i, a), r in runs.items() if a == arm and tier[i] == name]
            if not rs:
                continue
            totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
            for r in rs:
                for kind, (n, size, carried) in r["carried"].items():
                    totals[kind][0] += n
                    totals[kind][1] += size
                    totals[kind][2] += carried
            everything = sum(v[2] for v in totals.values()) or 1.0
            cells = "  ".join(
                f"{kind} {v[0] / len(rs):4.1f}x{v[1] / max(v[0], 1):6.0f}c "
                f"{v[2] / len(rs) / 1e6:5.1f}M ({100 * v[2] / everything:2.0f}%)"
                for kind, v in sorted(totals.items(), key=lambda kv: -kv[1][2])
                if kind in ("Read", "Grep", "search", "Bash", "Glob")
            )
            print(f"  {name:8} {arm:9} carried {everything / len(rs) / 1e6:6.1f}M  {cells}")

    print("\nwithin the treatment: does more spend go with a better grade on the same issue?")
    hi_better = hi_worse = 0
    for i in issues:
        rs = sorted(
            (r for (_, n, a), r in runs.items() if n == i and a == "treatment"),
            key=lambda r: r["cost"],
        )
        if len(rs) == 3 and rs[0]["grade"] != rs[-1]["grade"]:
            hi_better += rs[-1]["grade"] > rs[0]["grade"]
            hi_worse += rs[-1]["grade"] < rs[0]["grade"]
    print(f"  issues whose costliest treatment run graded better than its cheapest: {hi_better}, worse: {hi_worse}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
