"""Measure how often a surfaced memory is voluntarily read before the agent writes.

The quantity FINDINGS owed: of the memories Zikaron puts in front of an agent, what share does it
open with `memory_fetch` before its next write in that session. Three things this has to get right,
each of which moved the answer by an order of magnitude when it was got wrong:

- **The unit is the `(session, uuid)` pair, not the surfacing.** A uuid pushed thirty times in one
  session and read once was read. Counting per surfacing scores that 1/30 and reports a rate that is
  mostly a function of how chatty the session was.
- **D26-forced fetches are not reads.** `amend` and `retire` refuse without a read receipt, so any
  pair the session went on to write to *had* to be fetched whatever the agent wanted. Those pairs
  are excluded, not counted — including them measures the tool's grip, not the agent's habit.
- **Push surfacings are bucketed by the text the agent saw.** `surface_call.detail.preamble_digest`
  names the framing a push rendered, and a `surface` row shares its call's `op_id`, so a stamped
  surfacing says which prose it arrived under; `research/injected-prose-log.md` maps the digest to
  its bytes. Pooling two framings averages two different products.

Rows predating the field cannot say, and fall back to `--cut`: a timestamp guess at the one text
change inside that era with a known deployment instant. They report `(pre-digest, before|after
cut)`, and the guess is why the field exists — it cannot see a change nobody wrote down, and it
dates a deployment rather than a render.

Push surfacings come from `surface` rows, which name the memory. Pull surfacings come from `search`
rows, whose `detail.uuids` carries what the call returned; **the pull path renders no framing**, so
that arm reports one bucket.

**The result is not a compliance rate.** Push has no relevance floor, so most surfaced rows are not
about the work in hand and were never candidates for reading. The ceiling under perfect compliance
is unknown and far below 100%.

Read-only: the store is opened `mode=ro`, so a live service is unaffected.

    .venv/bin/python experiments/read_path_baseline.py [store.db] [--cut ISO8601]
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

DEFAULT_STORE = Path.home() / "Trading" / "LeibaTrader" / ".zikaron" / "memory.db"
#: What a push recorded before `surface_call.detail` carried the framing it rendered. More than one
#: text rendered in that era; `research/injected-prose-log.md` records the last two, and `--cut` is
#: the one instant that separates the last of them from everything before it.
PRE_DIGEST = "(pre-digest"
PULL = "(pull: no framing)"
#: The one text change inside the pre-digest era that is known and datable: when the
#: fetch-before-assert paragraph reached `~/Trading/LeibaTrader`, per `FINDINGS-archive.md`
#: §"The gist-as-abstract fix, and M27". Only those rows need it; a stamped row says what it saw.
DEFAULT_CUT = "2026-09-20T09:40:06Z"
#: What closes a pair's window, per `design/retrieval.md` §"Push output format"'s signal: the three
#: primary-agent writes. `merge` is absent because it is the consolidator's, and a consolidation run
#: closing a window it never read in would score the primary agent's session.
WRITE_KINDS = ("remember", "amend", "retire")
#: Writes that require a read receipt for the row they name, so the fetch was compelled.
FORCING_KINDS = ("amend", "retire", "merge")


def _writes_by_session(conn: sqlite3.Connection) -> dict[str, list[str]]:
    marks = ",".join("?" * len(WRITE_KINDS))
    rows = conn.execute(
        f"select session_id, at from event where kind in ({marks})"  # noqa: S608
        " and session_id is not null order by at",
        WRITE_KINDS,
    )
    out: dict[str, list[str]] = defaultdict(list)
    for session_id, at in rows:
        out[session_id].append(at)
    return out


def _fetches(conn: sqlite3.Connection) -> dict[tuple[str, str], list[str]]:
    rows = conn.execute(
        "select session_id, memory_uuid, at from event"
        " where kind = 'fetch' and session_id is not null order by at"
    )
    out: dict[tuple[str, str], list[str]] = defaultdict(list)
    for session_id, uuid, at in rows:
        out[(session_id, uuid)].append(at)
    return out


def _session_ends(conn: sqlite3.Connection) -> dict[str, str]:
    """The last event each session recorded, which closes a window no write closed."""
    return dict(
        conn.execute(
            "select session_id, max(at) from event where session_id is not null group by 1"
        )
    )


def _forced(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    marks = ",".join("?" * len(FORCING_KINDS))
    rows = conn.execute(
        f"select distinct session_id, memory_uuid from event where kind in ({marks})"  # noqa: S608
        " and memory_uuid is not null and session_id is not null",
        FORCING_KINDS,
    )
    return {(session_id, uuid) for session_id, uuid in rows}


def _first_surfacing(
    conn: sqlite3.Connection, arm: str, cut: str
) -> dict[tuple[str, str], tuple[str, str]]:
    """Each pair's earliest surfacing, as `(when, which framing it arrived under)`."""
    out: dict[tuple[str, str], tuple[str, str]] = {}
    if arm == "push":
        rows = conn.execute(
            "select surfaced.session_id, surfaced.memory_uuid, surfaced.at, call.detail"
            " from event as surfaced join event as call on call.op_id = surfaced.op_id"
            " and call.kind = 'surface_call'"
            " where surfaced.kind = 'surface' and surfaced.session_id is not null"
            " order by surfaced.at"
        )
        for session_id, uuid, at, detail in rows:
            stamped = json.loads(detail or "{}").get("preamble_digest")
            side = "before" if at < cut else "after"
            out.setdefault((session_id, uuid), (at, stamped or f"{PRE_DIGEST}, {side} cut)"))
        return out
    rows = conn.execute(
        "select session_id, at, detail from event"
        " where kind = 'search' and session_id is not null order by at"
    )
    for session_id, at, detail in rows:
        for uuid in json.loads(detail or "{}").get("uuids") or []:
            out.setdefault((session_id, uuid), (at, PULL))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", nargs="?", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--cut", default=DEFAULT_CUT, help="splits the pre-digest rows only")
    args = parser.parse_args()
    if not args.store.exists():
        print(f"no store at {args.store}")
        return 1

    conn = sqlite3.connect(f"file:{args.store}?mode=ro", uri=True)
    writes = _writes_by_session(conn)
    fetches = _fetches(conn)
    forced = _forced(conn)
    ends = _session_ends(conn)
    print(f"store {args.store}\n")

    for arm in ("push", "pull"):
        tally: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for (session_id, uuid), (at, framing) in _first_surfacing(conn, arm, args.cut).items():
            session_writes = writes.get(session_id, [])
            index = bisect.bisect_right(session_writes, at)
            closes = session_writes[index] if index < len(session_writes) else ends[session_id]
            row = tally[framing]
            if (session_id, uuid) in forced:
                row[2] += 1
                continue
            row[0] += 1
            times = fetches.get((session_id, uuid), [])
            after = bisect.bisect_right(times, at)
            if after < len(times) and times[after] <= closes:
                row[1] += 1
        print(f"{arm}: pairs surfaced, by the framing they arrived under")
        print(f"  {'framing':26}{'eligible':>10}{'read first':>12}{'rate':>9}   D26-forced")
        for framing in sorted(tally):
            eligible, read, skipped = tally[framing]
            rate = f"{100 * read / eligible:.2f}%" if eligible else "n/a"
            print(f"  {framing:26}{eligible:>10}{read:>12}{rate:>9}   {skipped}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
