# What schema 3 costs, and what `call` does to the growth figure

**Measured 2026-09-28** on Python 3.12.3 / SQLite 3.45.1, against a `VACUUM INTO` snapshot of
`~/Trading/LeibaTrader/.zikaron/memory.db` — 29,007 events, 5,448 distinct `op_id`s, spanning
41.2 days. The original was never opened for writing.

Re-derive with `.venv/bin/python spikes/m33_schema_three_and_call_volume.py`.

## The 2→3 migration

Run through `core.store.migration.migrate` rather than a re-implementation, so the figure is the one
production pays. `spikes/m31_check_widening.py` compared the two *routes* and is left alone; this
measures the route that was chosen.

| | |
|---|---|
| elapsed | **642 ms** |
| version reached | 3 |
| `PRAGMA integrity_check` | `ok` |
| `event` indexes surviving | 5 of 5 |

**Against M31's ~530 ms for the 2-step on 25,836 events**, which is the comparison to make: the store
has grown to 29,007 events (+12%) and the step does the same work, so 642 ms is the same route at a
larger size rather than a new cost. Both are paid once per store, behind a socket that is not yet
bound.

## What `call` adds to §"Retention"

`schema.md` §"Retention"'s 454 bytes/row and ~200 MB/year predate this kind and say so. They are
**re-derived rather than scaled**, since the multiplier depends on a project's mix of calls.

| | |
|---|---|
| one `call` row, live, five indexes included | **463.7 bytes** |
| distinct `op_id`s per day on this store | **132.4** |
| all events per day on this store | 704.9 |
| `call` at that rate | **22.4 MB/year** |
| rows added, as a share of what the log already holds | **18.8%** |

Bytes per row are the file's growth across a `VACUUM`, after inserting 20,000 rows carrying a detail
of the shape the seam writes — so the answer is the live cost of the row plus its indexes rather
than whatever free pages the store was carrying.

**The rate is a floor, and the reason is the milestone's own subject.** A `call` row is written per
dispatched RPC, and the eight knowledge verbs emitted nothing before this — so their calls left no
`op_id` in this log and cannot be counted from it at all. A project that uses the knowledge index
writes more than 132 a day.

**What this does not measure** is the effect of the `call` rows on the signal queries, which is the
other half of "no hot path reads `event`". Nothing on a latency path reads the table, so the cost is
disk plus whatever §"D30's six signals, as queries" pays; that was not timed here.
