"""Does a reader page when the next page holds what it needs? Targeted sessions over queries whose
page 2 holds a truth file page 1 lacks.

    .venv/bin/python experiments/m42_page2_probe.py select
    .venv/bin/python experiments/m42_page2_probe.py run [--limit N]

It ran against M42 as built at `f9750c6`, whose search took an `offset`; that parameter was removed
on what this script measured, so `select` and the variants need that build checked out to run.

For `research/paged-search-replay.md` §"Page 2" (operator, 2026-10-31). `select` gathers every
knowledge search the evaluation's readers made — stage 1's runs under `~/Zikaron-m40`, and the
probes and the paging check under `~/Zikaron-m42` — replays each through `groups.search_all`
against the paged treatment copy's store at `offset` 0 and at `offset` = its own limit, and keeps a
query when its page 2 holds a source file the run's issue was fixed in and its page 1 does not.
`run` gives the reader each kept query as a task — explain it from the knowledge base, verified
against the source — then asks, in the same session, a neutral question about wanting more
results, then names what page 2 held and asks what wording would have made it page.

Everything it writes goes under `~/Zikaron-m42/page2/`, outside this repository.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m40_eval
import paged_search_replay

from zikaron.core.config.resolution import project_config_path, resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge import groups
from zikaron.core.store.store import Store

BASE = Path.home() / "Zikaron-m42"
OUT = BASE / "page2"
LAYOUT = m40_eval.Layout(BASE)
COPY_LETTER = "b"
SOURCES = (
    Path.home() / "Zikaron-m40" / "eval" / "runs",
    BASE / "eval-probe1-no-hint" / "runs",
    BASE / "eval-probe23-hint" / "runs",
    BASE / "eval" / "runs",
)
SYSTEM_CONFIG = Path("/nonexistent/zikaron-page2-system.toml")
TASK = (
    "Explain to me {query} in this codebase. Use the project's knowledge base to find where it "
    "lives, and verify what you say against the source code."
)
NEUTRAL = (
    "Thank you. One question about how you searched: did you consider asking the knowledge search "
    "for more results than it first gave you, or for its next results? Why, or why not?"
)
LEADING = (
    "Actually, if you had looked at the next page of results for that kind of search — the same "
    "query with `offset` {offset} — you would have seen `{source}` ({opening}), which is relevant "
    "to what I asked. Is there anything we could change in the knowledge search tool's description "
    "or in its responses so that next time you would query for additional pages?"
)


def _searches() -> list[dict[str, object]]:
    """Every knowledge search a reader made, with its run's issue, deduplicated."""
    issues = {int(i["issue"]): i for i in json.loads(m40_eval.ISSUES.read_text())["issues"]}
    seen: dict[tuple[int, str, int], dict[str, object]] = {}
    for runs in SOURCES:
        for path in sorted(runs.glob("r*-*-*-*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            transcript = runs / str(record["transcript"])
            if not transcript.exists():
                continue
            run = paged_search_replay._read_run(transcript, record)
            inputs = {index: text for index, _name, text in run.tool_inputs}
            for search in run.searches:
                arguments = json.loads(inputs[search.index])
                limit = int(arguments.get("limit_per_kb", 5))
                key = (run.issue, str(arguments["query"]).strip().lower(), limit)
                seen.setdefault(
                    key,
                    {
                        "issue": run.issue,
                        "query": str(arguments["query"]),
                        "limit": limit,
                        "names": arguments.get("knowledge_bases"),
                        "truth": sorted(issues[run.issue]["truth"]),
                    },
                )
    return list(seen.values())


def _sources(response: groups.SearchResponse) -> list[dict[str, object]]:
    found = []
    for group in response.payload()["groups"]:  # type: ignore[attr-defined]
        for rank, result in enumerate(group.get("results", []), start=1):
            source = (result.get("source") or {}).get("path") or result["path"]
            found.append({**result, "rank": rank, "source": source})
    return found


async def select() -> int:
    store_dir = LAYOUT.copy(COPY_LETTER) / ".zikaron"
    if project_config_path(store_dir).exists():
        raise SystemExit(f"{project_config_path(store_dir)} exists: this copy is not the paged arm")
    config = resolve(SYSTEM_CONFIG, project_config_path(store_dir))
    encoder = await asyncio.to_thread(FastEmbedEncoder.load, config.get_str("embed_model"))
    searches = _searches()
    kept = []
    async with await Store.open(store_dir, config) as store:
        for search in searches:
            names = tuple(search["names"]) if search["names"] else None  # type: ignore[arg-type]
            pages = []
            for offset in (0, int(search["limit"])):  # type: ignore[call-overload]
                request = groups.SearchRequest(
                    text=str(search["query"]),
                    limit_per_kb=int(search["limit"]),  # type: ignore[call-overload]
                    offset=offset,
                    names=names,
                )
                response = await groups.search_all(
                    store_dir, store.connection, config, request, encoder=encoder, migrate=False
                )
                pages.append(_sources(response))
            first = {result["source"] for result in pages[0]}
            hits = [
                result
                for result in pages[1]
                if result["source"] in search["truth"] and result["source"] not in first  # type: ignore[operator]
            ]
            if hits:
                kept.append({**search, "page2": hits[0], "page1_sources": sorted(first)})  # type: ignore[type-var]
    OUT.mkdir(exist_ok=True)
    (OUT / "selected.json").write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    print(f"searches {len(searches)}; page 2 holds a truth file page 1 lacks: {len(kept)}")
    for item in kept:
        page2 = item["page2"]
        print(
            f"  {item['issue']} limit {item['limit']} rank {page2['rank']} "  # type: ignore[index]
            f"{page2['source']} <- {str(item['query'])[:70]!r}"  # type: ignore[index]
        )
    return 0


def _ask(prompt: str, name: str, resume: str | None) -> dict[str, object]:
    """One turn of the reader in the paged copy, as the evaluation runs it; the result record."""
    command = m40_eval.reader_command(LAYOUT, prompt, budget_usd=5)
    if resume is not None:
        command = [*command[:-1], "--resume", resume, command[-1]]
    transcript = OUT / f"{name}.jsonl"
    with transcript.open("w", encoding="utf-8") as out:
        subprocess.run(
            command,
            cwd=LAYOUT.copy(COPY_LETTER),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.DEVNULL,
            timeout=1800,
            check=False,
        )
    records = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
    result = next(r for r in reversed(records) if r.get("type") == "result")
    offsets = [
        block["input"].get("offset", 0)
        for r in records
        if r.get("type") == "assistant"
        for block in r["message"]["content"]
        if block.get("type") == "tool_use" and str(block["name"]).endswith("knowledge_search")
    ]
    return {**result, "search_offsets": offsets}


def run(limit: int) -> int:
    selected = json.loads((OUT / "selected.json").read_text(encoding="utf-8"))
    # One query per issue, the first logged, so no issue's many searches outweigh the rest.
    chosen, issues_seen = [], set()
    for item in selected:
        if item["issue"] not in issues_seen:
            chosen.append(item)
            issues_seen.add(item["issue"])
    chosen = chosen[:limit]
    records = []
    for number, item in enumerate(chosen):
        page2 = item["page2"]
        name = f"q{number:02}"
        task = _ask(TASK.format(query=item["query"]), f"{name}-task", None)
        session = str(task["session_id"])
        neutral = _ask(NEUTRAL, f"{name}-neutral", session)
        leading = _ask(
            LEADING.format(
                offset=item["limit"], source=page2["source"], opening=page2.get("opening", "")[:160]
            ),
            f"{name}-leading",
            session,
        )
        answer = str(task.get("result", ""))
        record = {
            "item": item,
            "found": Path(str(page2["source"])).name in answer,
            "task_offsets": task["search_offsets"],
            "cost": sum(float(t.get("total_cost_usd") or 0) for t in (task, neutral, leading)),
            "answer": answer,
            "neutral": neutral.get("result"),
            "leading": leading.get("result"),
        }
        records.append(record)
        print(
            f"{name} {item['issue']} found={record['found']} offsets={record['task_offsets']} "
            f"${record['cost']:.2f}",
            flush=True,
        )
        (OUT / "results.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return 0


#: Edits to a variant's copy of the service code so each group reports `total`, the length of its
#: ranked list, and `has_more`, whether any of it lies past the page: the whole pool is ranked
#: rather than stopping at the page's end.
_HAS_MORE_EDITS = (
    (
        "search.py",
        "        if len(kept) >= settings.offset + settings.limit_per_kb:\n            break\n",
        "",
    ),
    ("search.py", "    ranked_empty: bool\n", "    ranked_empty: bool\n    total: int = 0\n"),
    (
        "search.py",
        "    page = ranked[settings.offset :]\n",
        "    page = ranked[settings.offset : settings.offset + settings.limit_per_kb]\n",
    ),
    (
        "search.py",
        "    return SearchPage(results=tuple(results), ranked_empty=not ranked)\n",
        "    return SearchPage(results=tuple(results), ranked_empty=not ranked, total=len(ranked))\n",
    ),
    (
        "groups.py",
        "    dropped: bool = False\n",
        "    dropped: bool = False\n    more: tuple[int, bool] | None = None\n",
    ),
    (
        "groups.py",
        '        if self.dropped:\n            payload["dropped"] = True\n',
        "        if self.more is not None and not self.dropped:\n"
        '            payload["total"], payload["has_more"] = self.more\n'
        '        if self.dropped:\n            payload["dropped"] = True\n',
    ),
    (
        "groups.py",
        "    results: tuple[search.Result | search.NamedResult, ...] = ()\n    if state in _SERVING:\n",
        "    results: tuple[search.Result | search.NamedResult, ...] = ()\n"
        "    more: tuple[int, bool] | None = None\n    if state in _SERVING:\n",
    ),
    (
        "groups.py",
        "        results = page.results\n",
        "        results = page.results\n"
        "        seen = searching.settings.offset + len(results)\n"
        "        more = (page.total, page.total > seen)\n",
    ),
    (
        "groups.py",
        "        results=results,\n    )\n",
        "        results=results,\n        more=more,\n    )\n",
    ),
)


def _variant_package(name: str, description: Path | None, *, has_more: bool = False) -> Path:
    """A copy of this repository's package with the search tool's description replaced, so a
    variant runs without touching the tree the real projects' `.venv` imports."""
    root = OUT / "variants" / name
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(Path(__file__).resolve().parent.parent / "zikaron", root / "zikaron")
    if has_more:
        for module, old, new in _HAS_MORE_EDITS:
            path = root / "zikaron" / "core" / "knowledge" / module
            text = path.read_text(encoding="utf-8")
            if text.count(old) != 1:
                raise SystemExit(f"{module}: the has_more edit no longer matches: {old!r}")
            path.write_text(text.replace(old, new), encoding="utf-8")
    if description is not None:
        primary = root / "zikaron" / "mcp" / "primary.py"
        text = primary.read_text(encoding="utf-8")
        start = text.index('"""', text.index("async def zikaron_knowledge_search("))
        end = text.index('"""', start + 3) + 3
        lines = description.read_text(encoding="utf-8").rstrip("\n").split("\n")
        body = lines[0] + "".join("\n" + (f"        {line}" if line else "") for line in lines[1:])
        primary.write_text(text[:start] + '"""' + body + '\n        """' + text[end:])
    config = json.loads(LAYOUT.mcp_config.read_text(encoding="utf-8"))
    config["mcpServers"]["zikaron"]["env"] = {"PYTHONPATH": str(root)}
    (root / "mcp.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return root


def variant(  # noqa: PLR0913 — an experiment's knobs, each a command-line flag.
    name: str, description: Path | None, repeats: int, limit: int, *, has_more: bool, first: int
) -> int:
    """The task turn alone, `repeats` times per chosen query, under one description."""
    # The copy's service is not stopped here: arms that share service code run concurrently, and
    # the caller stops it between arms whose service code differs.
    root = _variant_package(name, description, has_more=has_more)
    selected = json.loads((OUT / "selected.json").read_text(encoding="utf-8"))
    chosen, issues_seen = [], set()
    for item in selected:
        if item["issue"] not in issues_seen:
            chosen.append(item)
            issues_seen.add(item["issue"])
    records = []
    for repeat in range(first, first + repeats):
        for number, item in enumerate(chosen[:limit]):
            command = m40_eval.reader_command(
                LAYOUT, TASK.format(query=item["query"]), budget_usd=5
            )
            command[command.index(str(LAYOUT.mcp_config))] = str(root / "mcp.json")
            transcript = root / f"q{number:02}-r{repeat}.jsonl"
            with transcript.open("w", encoding="utf-8") as out:
                subprocess.run(
                    command,
                    cwd=LAYOUT.copy(COPY_LETTER),
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.DEVNULL,
                    timeout=1800,
                    check=False,
                )
            rows = [
                json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()
            ]
            result = next(r for r in reversed(rows) if r.get("type") == "result")
            offsets = [
                block["input"].get("offset", 0)
                for r in rows
                if r.get("type") == "assistant"
                for block in r["message"]["content"]
                if block.get("type") == "tool_use"
                and str(block["name"]).endswith("knowledge_search")
            ]
            found = Path(str(item["page2"]["source"])).name in str(result.get("result", ""))
            records.append(
                {
                    "query": number,
                    "repeat": repeat,
                    "issue": item["issue"],
                    "found": found,
                    "offsets": offsets,
                    "cost": float(result.get("total_cost_usd") or 0),
                }
            )
            print(f"{name} q{number:02} r{repeat} found={found} offsets={offsets}", flush=True)
            (root / "results.json").write_text(json.dumps(records, indent=2) + "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("select")
    running = commands.add_parser("run")
    running.add_argument("--limit", type=int, default=10)
    varying = commands.add_parser("variant")
    varying.add_argument("--name", required=True)
    varying.add_argument("--description", type=Path, help="the description's text; none = current")
    varying.add_argument("--repeats", type=int, default=2)
    varying.add_argument("--limit", type=int, default=10)
    varying.add_argument("--has-more", action="store_true", help="groups report total, has_more")
    varying.add_argument("--first-repeat", type=int, default=0, help="number the repeats from")
    args = parser.parse_args()
    if args.command == "select":
        return asyncio.run(select())
    if args.command == "variant":
        return variant(
            args.name,
            args.description,
            args.repeats,
            args.limit,
            has_more=args.has_more,
            first=args.first_repeat,
        )
    return run(args.limit)


if __name__ == "__main__":
    sys.exit(main())
