"""M42's done-when 2: stage 1's queries replayed through the paged search, at two cutoffs and two
opening limits.

    .venv/bin/python experiments/m42_paged_replay.py

For `research/paged-search-replay.md` §"Through the build" (operator, 2026-10-30). Every search
the 48 kept treatment runs made is run again in-process through `groups.search_all`, with the real
encoder, against the treatment copy's store, each with its own `limit_per_kb` and corpora, at
`knowledge_whole_results` 3 and 20 and with `excerpts.OPENING_MAX_CHARS` at 400 and 200. The cutoff
is resolved from a scratch project configuration holding only the key, so the store's own file,
which stage 2's arms set, is never written; the replay refuses to run while that file exists,
since its other keys would then be missing from the scratch one. Opens the store without migrating
it.

Measured, per setting: the result lists' characters (`json.dumps` of each group's `results`,
unescaped, stage 1's quantity), `groups.response_bytes` of the whole responses, and how many
openings were cut; then, over every path any page named, the length of its title and role line.
Refuses a response with a group not `ok` or with groups dropped, which would shrink the totals
rather than fail.
"""

import asyncio
import json
import sqlite3
import statistics
import sys
import tempfile
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import m40_breakdown
import m40_eval
import paged_search_replay

from zikaron.core.config.resolution import project_config_path, resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.knowledge import excerpts, groups, links
from zikaron.core.store.store import Store

STORE_DIR = m40_breakdown.BASE / "eval" / "root" / "b" / "warp" / ".zikaron"
SYSTEM_CONFIG = Path("/nonexistent/zikaron-replay-system.toml")
OPENING_LIMITS = (400, 200)


def _requests(layout: m40_eval.Layout) -> list[groups.SearchRequest]:
    requests = []
    for arms in m40_eval.kept_runs(layout).values():
        record = arms.get("treatment")
        if record is None:
            continue
        run = paged_search_replay._read_run(layout.runs / str(record["transcript"]), record)
        inputs = {index: text for index, _name, text in run.tool_inputs}
        for search in run.searches:
            arguments = json.loads(inputs[search.index])
            names = arguments.get("knowledge_bases")
            requests.append(
                groups.SearchRequest(
                    text=str(arguments["query"]),
                    limit_per_kb=int(arguments.get("limit_per_kb", 5)),
                    names=tuple(names) if names else None,
                )
            )
    return requests


def _scratch_config(directory: Path, cutoff: int) -> Path:
    """A project configuration that sets the cutoff and nothing else."""
    target = directory / f"project-{cutoff}.toml"
    own = project_config_path(STORE_DIR)
    if own.exists():
        raise SystemExit(f"{own} exists: merge the cutoff into a copy of it by hand")
    target.write_text(f"[retrieval]\nknowledge_whole_results = {cutoff}\n", encoding="utf-8")
    return target


async def _measure(
    requests: list[groups.SearchRequest], cutoff: int, scratch: Path
) -> dict[str, int]:
    config = resolve(SYSTEM_CONFIG, _scratch_config(scratch, cutoff))
    encoder = await asyncio.to_thread(FastEmbedEncoder.load, config.get_str("embed_model"))
    totals = {"result_chars": 0, "response_bytes": 0, "openings": 0, "openings_cut": 0}
    async with await Store.open(STORE_DIR, config) as store:
        for request in requests:
            response = await groups.search_all(
                STORE_DIR, store.connection, config, request, encoder=encoder, migrate=False
            )
            payload = response.payload()
            states = {group.get("state") for group in payload["groups"]}  # type: ignore[attr-defined]
            if states != {"ok"} or response.groups_dropped:
                raise SystemExit(
                    f"precondition: states {states}, dropped {response.groups_dropped}"
                )
            totals["response_bytes"] += groups.response_bytes(response)
            for group in payload["groups"]:  # type: ignore[attr-defined]
                results = group.get("results", [])
                totals["result_chars"] += len(json.dumps(results, ensure_ascii=False))
                for result in results:
                    if "opening" in result:
                        totals["openings"] += 1
                        totals["openings_cut"] += result["opening"].endswith("…")
                        TITLE_AND_ROLE.setdefault(result["path"], None)
    return totals


#: Every path named on any page, then the length of its title and role line: the first chunk's
#: text after its front matter, whitespace collapsed, up to its first `##`.
TITLE_AND_ROLE: dict[str, int | None] = {}


def _title_and_role_lengths(corpus_db: Path) -> list[int]:
    with closing(sqlite3.connect(f"file:{corpus_db}?mode=ro", uri=True)) as db:
        for path in TITLE_AND_ROLE:
            (text,) = db.execute(
                "SELECT text FROM chunks WHERE path = ? AND part_index = 0", (path,)
            ).fetchone()
            collapsed = " ".join(text[links.front_matter_end(text) :].split())
            TITLE_AND_ROLE[path] = len(collapsed.split("##", 1)[0].strip())
    return sorted(length for length in TITLE_AND_ROLE.values() if length is not None)


def _corpus_db() -> Path:
    (found,) = (STORE_DIR / "knowledge").glob("*.db")
    with closing(sqlite3.connect(f"file:{found}?mode=ro", uri=True)) as db:
        (version,) = db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    print(f"corpus {found.name}, schema {version}")
    return found


async def main() -> int:
    requests = _requests(m40_eval.Layout(m40_breakdown.BASE))
    print(f"searches replayed: {len(requests)}, store {STORE_DIR}")
    corpus_db = _corpus_db()
    with tempfile.TemporaryDirectory() as scratch:
        unpaged = await _measure(requests, 20, Path(scratch))
        print(f"cutoff 20: {unpaged}")
        for limit in OPENING_LIMITS:
            excerpts.OPENING_MAX_CHARS = limit
            paged = await _measure(requests, 3, Path(scratch))
            print(
                f"cutoff 3, opening {limit}: {paged}; result characters "
                f"{paged['result_chars'] / unpaged['result_chars']:.1%} of unpaged, response "
                f"bytes {paged['response_bytes'] / unpaged['response_bytes']:.1%}"
            )
    lengths = _title_and_role_lengths(corpus_db)
    within = ", ".join(
        f"within {limit}: {sum(n <= limit for n in lengths)}" for limit in OPENING_LIMITS
    )
    print(
        f"title and role line, {len(lengths)} named paths: median "
        f"{statistics.median(lengths)}, {within}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
