"""The three questions the access log exists to answer, as queries against a real store.

    .venv/bin/python experiments/m33_call_log_queries.py [store.db]

Defaults to `~/Trading/LeibaTrader/.zikaron/memory.db`, read-only. Prints each answer beside the
query that produced it, so a figure quoted from here can be re-derived without reading this file.

`design/schema.md` §"`call` is an access log" is normative for all three, and for the two bounds that
keep them honest:

- **the drop rate is over distinct `op_id`s, never rows** — a push writes six semantic rows under
  one and a `fetch` of *n* uuids writes *n*, so counting rows would let one dropped push weigh six
  times a dropped `remember` and the figure would move with the mix of verbs;
- **it starts at the first `call` row and excludes `client_kind='indexer'`** — every pre-schema-3
  `op_id` qualifies as a "drop" otherwise, and every `knowledge_build` does so by construction, since
  a build answers no RPC. That start is a **floor**: the first post-migration calls may themselves
  have dropped, and a floor is accepted rather than adding a `meta` key whose initialization contract
  is more surface than an exact boundary is worth.
"""

import os
import sqlite3
import sys
from pathlib import Path

#: Everything below this `event.id` predates the migration that admitted `call`, so its `op_id`s
#: cannot have had a row and must not count as drops. A floor, per the module docstring.
_FIRST_CALL = "(SELECT min(id) FROM event WHERE kind = 'call')"

_PER_METHOD_VOLUME = """
SELECT json_extract(detail, '$.method') AS method,
       count(*)                         AS calls,
       sum(json_extract(detail, '$.ok') = 0) AS refused,
       round(avg(json_extract(detail, '$.duration_ms')), 2) AS mean_ms,
       round(max(json_extract(detail, '$.duration_ms')), 2) AS worst_ms
  FROM event
 WHERE kind = 'call'
 GROUP BY method
 ORDER BY calls DESC
"""

_REFUSALS_BY_CODE = """
SELECT json_extract(detail, '$.method')     AS method,
       json_extract(detail, '$.error_code') AS error_code,
       count(*)                             AS refusals
  FROM event
 WHERE kind = 'call' AND json_extract(detail, '$.ok') = 0
 GROUP BY method, error_code
 ORDER BY refusals DESC
"""

#: How often a `remember` is refused as `bounds`, which is what M33 instrumented it for: a gist over
#: the token bound loses the whole finding and not merely its label, so the rate decides whether the
#: bound is where it should be. **`bounds` does not say which field, and it cannot** — the row carries
#: no argument values by design, so a gist past the bound and a `gist` that was not a string at all are
#: indistinguishable here. The first is the one this rate is about and the second is a client defect;
#: a store seeing many of these wants the session transcript to tell them apart.
_BOUNDED_WRITE_REFUSALS = """
SELECT count(*) AS attempts,
       sum(json_extract(detail, '$.error_code') = 'bounds') AS bounded,
       sum(json_extract(detail, '$.ok') = 1) AS accepted
  FROM event
 WHERE kind = 'call' AND json_extract(detail, '$.method') = 'memory_remember'
"""

_DROP_RATE = f"""
WITH scoped AS (
  SELECT op_id,
         max(kind = 'call')  AS logged,
         max(kind <> 'call') AS semantic
    FROM event
   WHERE client_kind <> 'indexer'
     AND id > {_FIRST_CALL}
   GROUP BY op_id
)
SELECT count(*)                        AS op_ids_with_a_semantic_row,
       sum(logged = 0)                 AS with_no_call_row,
       round(100.0 * sum(logged = 0) / count(*), 3) AS dropped_percent
  FROM scoped
 WHERE semantic = 1
"""

_BUILD_HISTORY = """
SELECT json_extract(detail, '$.knowledge_base_id') AS knowledge_base,
       count(*)                                    AS builds,
       sum(json_extract(detail, '$.ok') = 0)        AS failed,
       sum(json_extract(detail, '$.rebuilt') = 1)   AS rebuilds,
       round(sum(json_extract(detail, '$.duration_ms')) / 1000.0, 1) AS total_seconds,
       sum(json_extract(detail, '$.spawned_by_op_id') IS NULL) AS unattributed
  FROM event
 WHERE kind = 'knowledge_build'
 GROUP BY knowledge_base
 ORDER BY total_seconds DESC
"""

_QUERIES: tuple[tuple[str, str], ...] = (
    ("per-method call volume, with its latency population", _PER_METHOD_VOLUME),
    ("what each method refuses, by code", _REFUSALS_BY_CODE),
    ("the refusal rate of a bounded write", _BOUNDED_WRITE_REFUSALS),
    ("the access log's own drop rate, over distinct op_ids", _DROP_RATE),
    ("what building each corpus has cost", _BUILD_HISTORY),
)


def run(db: sqlite3.Connection, title: str, sql: str) -> None:
    print(f"\n--- {title}")
    print("\n".join(f"    {line}" for line in sql.strip().splitlines()))
    cursor = db.execute(sql)
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()
    if not rows:
        print("\n    (no rows)")
        return
    widths = [
        max(len(str(column)), *(len(str(row[index])) for row in rows))
        for index, column in enumerate(columns)
    ]
    print()
    print("    " + "  ".join(f"{column:<{widths[index]}}" for index, column in enumerate(columns)))
    for row in rows:
        print("    " + "  ".join(f"{value!s:<{widths[index]}}" for index, value in enumerate(row)))


def main() -> int:
    source = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.expanduser("~/Trading/LeibaTrader/.zikaron/memory.db")
    )
    if not source.exists():
        print(f"no store at {source}", file=sys.stderr)
        return 1
    print(f"store {source}, sqlite {sqlite3.sqlite_version}")
    db = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        held = db.execute("SELECT count(*) FROM event WHERE kind = 'call'").fetchone()[0]
        if not held:
            print(
                "\nThis store holds no `call` rows yet, so every query below answers empty. That is"
                "\nthe ordinary state of a store whose service has not run this build: the kind is"
                "\nadmitted by schema 3 and written from the next dispatched RPC onward."
            )
        for title, sql in _QUERIES:
            run(db, title, sql)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
