"""M34's replay: seed a fresh store from a real store's rows, then compare what consolidation made.

`design/build-plan.md` §M34 "The instrument" is the specification. Two subcommands:

    .venv/bin/python experiments/m34_gist_replay.py seed [--source DIR] [--out DIR]
    .venv/bin/python experiments/m34_gist_replay.py compare [--out DIR]

`seed` snapshots the source store with `Connection.backup()` — never a file copy, and never a
write — and re-inserts every row a `remember` created, in `created_at` order, as a journal entry of
a fresh store under `<out>/replay`, through the service's own `memory_remember`. It writes
`<out>/seed.json`, which maps each source uuid to the replay uuid it became. The operator then
installs Zikaron into `<out>/replay` and invokes the consolidation skill there by hand.

`compare` follows each seed row to the long-term record that holds it after consolidation — in
place, or through `superseded_by` — and writes `<out>/compare.md`: the verdict-marker rate over the
seed's gists against the output's, then every output record beside the seed rows it absorbed.

The seed is each row's *current* prose, not the prose it was written with: events carry none, and
amend, merge and promote rewrite rows in place. So a row that absorbed others still carries their
findings, and the seed repeats them — which is what a journal holding a genuine repeat looks like.
"""

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from zikaron.mcp.connection import ServiceConnection
from zikaron.project.initialize import main as initialize

#: A conclusion marker in a gist: a connective introducing a verdict, a bare verdict adjective, or
#: an appended dash clause. A **floor** for reading, not a classifier — `design/build-plan.md`
#: §M34's bar compares this regex's rate on both sides and is confirmed by reading the pairs.
VERDICT_MARKER = re.compile(
    r"\b(so|therefore|thus|hence|which means|meaning)\b"
    r"|\b(is|are) (wrong|unsafe|useless|invalid|broken)\b"
    r"| — ",
    re.IGNORECASE,
)

_SEED_ROWS = """
SELECT m.uuid, m.gist, m.content
  FROM memory m
 WHERE EXISTS (SELECT 1 FROM event e WHERE e.memory_uuid = m.uuid AND e.kind = 'remember')
 ORDER BY m.created_at, m.uuid
"""

_DEFAULT_OUT = Path.home() / "zikaron-m34-replay"
_DEFAULT_SOURCE = Path.home() / "Trading" / "LeibaTrader"


def _snapshot(source_db: Path, snapshot: Path) -> None:
    source = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    target = sqlite3.connect(snapshot)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _marker_rate(gists: list[str]) -> tuple[int, int]:
    return sum(bool(VERDICT_MARKER.search(gist)) for gist in gists), len(gists)


async def _remember_all(project: Path, rows: list[tuple[str, str, str]]) -> dict[str, str]:
    connection = ServiceConnection(project)
    mapping: dict[str, str] = {}
    for source_uuid, gist, content in rows:
        response = await connection.request(
            "memory_remember",
            {"gist": gist, "content": content},
            envelope=connection.envelope(kind="mcp"),
        )
        if "error" in response:
            sys.exit(f"remember refused {source_uuid}: {response['error']}")
        result = response["result"]
        if not isinstance(result, dict):
            sys.exit(f"remember returned no record for {source_uuid}: {result!r}")
        mapping[source_uuid] = str(result["uuid"])
    return mapping


def seed(source: Path, out: Path, only: set[str] | None = None) -> int:
    """`only`, when given, restricts the seed to those source uuids — a targeted re-run of the
    rows an earlier replay got wrong, rather than the whole journal again."""
    snapshot = out / "snapshot.db"
    project = out / "replay"
    if snapshot.exists() or project.exists():
        sys.exit(f"refused: {out} already holds a seed; remove it to start over")
    out.mkdir(parents=True, exist_ok=True)
    project.mkdir()
    _snapshot(source / ".zikaron" / "memory.db", snapshot)

    reader = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    rows: list[tuple[str, str, str]] = [
        row for row in reader.execute(_SEED_ROWS).fetchall() if only is None or row[0] in only
    ]
    missing = (only or set()) - {row[0] for row in rows}
    if missing:
        sys.exit(
            f"refused: {len(missing)} requested uuid(s) are not rows a remember created, "
            f"e.g. {sorted(missing)[0]} (full uuids only); remove {out} before re-running"
        )
    live: list[str] = [
        gist
        for (gist,) in reader.execute(
            "SELECT gist FROM memory WHERE active = 1 AND tier = 'long_term'"
        )
    ]
    reader.close()

    if initialize(["--project", str(project)]) != 0:
        sys.exit(f"refused: could not create a store in {project}")
    mapping = asyncio.run(_remember_all(project, rows))

    seed_hits, seed_total = _marker_rate([gist for _, gist, _ in rows])
    live_hits, live_total = _marker_rate(live)
    (out / "seed.json").write_text(
        json.dumps({"source": str(source), "rows": mapping}, indent=2) + "\n"
    )
    print(f"seeded {len(mapping)} journal rows into {project}")
    print(f"marker rate, seed rows:              {seed_hits}/{seed_total}")
    print(f"marker rate, source live long-term:  {live_hits}/{live_total}")
    return 0


def _holder(db: sqlite3.Connection, uuid: str) -> str | None:
    """The live long-term record holding `uuid`'s finding, following `superseded_by`."""
    seen: set[str] = set()
    current: str | None = uuid
    while current is not None and current not in seen:
        seen.add(current)
        row = db.execute(
            "SELECT tier, active, superseded_by FROM memory WHERE uuid = ?", (current,)
        ).fetchone()
        if row is None:
            return None
        tier, active, superseded_by = row
        if active and tier == "long_term":
            return current
        current = superseded_by
    return None


def compare(out: Path) -> int:
    seeded = json.loads((out / "seed.json").read_text())["rows"]
    snapshot = sqlite3.connect(f"file:{out / 'snapshot.db'}?mode=ro", uri=True)
    replay = sqlite3.connect(f"file:{out / 'replay' / '.zikaron' / 'memory.db'}?mode=ro", uri=True)

    absorbed: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for source_uuid, replay_uuid in seeded.items():
        holder = _holder(replay, replay_uuid)
        if holder is None:
            unresolved.append(source_uuid)
        else:
            absorbed.setdefault(holder, []).append(source_uuid)

    def prose(db: sqlite3.Connection, uuid: str) -> tuple[str, str]:
        gist, content = db.execute(
            "SELECT gist, content FROM memory WHERE uuid = ?", (uuid,)
        ).fetchone()
        return gist, content

    absorbed_rows = [uuid for sources in absorbed.values() for uuid in sources]
    seed_hits, seed_total = _marker_rate([prose(snapshot, uuid)[0] for uuid in absorbed_rows])
    out_gists = [prose(replay, uuid)[0] for uuid in absorbed]
    out_hits, out_total = _marker_rate(out_gists)

    lines = [
        "# M34 replay — seed against output",
        "",
        f"- marker rate, seed rows absorbed so far: **{seed_hits}/{seed_total}**",
        f"- marker rate, output long-term records: **{out_hits}/{out_total}**",
        f"- seed rows held by no live long-term record (journal left, or discarded): "
        f"{len(unresolved)}",
        "",
    ]
    for holder, sources in sorted(absorbed.items(), key=lambda item: -len(item[1])):
        gist, content = prose(replay, holder)
        marked = " · MARKER" if VERDICT_MARKER.search(gist) else ""
        lines += [f"## `{holder}` — absorbed {len(sources)}{marked}", "", f"**Gist:** {gist}", ""]
        lines += ["<details><summary>content</summary>", "", content, "", "</details>", ""]
        for source_uuid in sources:
            seed_gist, _ = prose(snapshot, source_uuid)
            seed_marked = " · MARKER" if VERDICT_MARKER.search(seed_gist) else ""
            lines.append(f"- seed `{source_uuid[:8]}`{seed_marked}: {seed_gist}")
        lines.append("")
    if unresolved:
        lines += ["## Seed rows with no long-term holder", ""]
        lines += [f"- `{uuid[:8]}`: {prose(snapshot, uuid)[0]}" for uuid in unresolved]
    (out / "compare.md").write_text("\n".join(lines) + "\n")
    print(f"marker rate: seed {seed_hits}/{seed_total}, output {out_hits}/{out_total}")
    print(f"wrote {out / 'compare.md'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    seed_parser = sub.add_parser("seed")
    seed_parser.add_argument("--source", type=Path, default=_DEFAULT_SOURCE)
    seed_parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    seed_parser.add_argument(
        "--rows", type=Path, help="a file of source uuids, one per line, to seed instead of all"
    )
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args()
    if args.command == "seed":
        only = set(args.rows.read_text().split()) if args.rows else None
        return seed(args.source.expanduser(), args.out.expanduser(), only)
    return compare(args.out.expanduser())


if __name__ == "__main__":
    os.umask(0o077)
    sys.exit(main())
