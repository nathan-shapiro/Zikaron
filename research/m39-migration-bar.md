# The corpus migration's write-lock hold, against M39's bar

**Measured 2026-10-13**, at the host's load (load average 6.8 / 5.7 / 5.5 — the host is busy, so the
figure is not comparable with an idle-host budget). Re-derive with:

    .venv/bin/python experiments/m39_migration_bar.py 7000 25 \
        --real ~/Trading/LeibaTrader/.zikaron/knowledge/ee05403f-d8c8-4597-832d-90a01df869ac.db

**The bar** (`design/knowledge-index.md` §7.7.1, `design/build-plan.md` §M39 item 4): the migration's
write-lock hold at p95 at most 1 s, over at least 20 migrations each of a fresh copy, on a schema-1
corpus of at least 7,000 `files` rows with chunks to match. What it protects: a build of the previous
version may be waiting on that lock under a 5 s `busy_timeout`.

## Result — met

| quantity | value |
|---|---|
| corpus | 7,000 `files` rows, 3 chunks of ~1,500 characters each, a third opening with a linked front-matter block |
| migrations | 25, each of a fresh copy of one schema-1 template |
| hold p50 | 0.704 s |
| **hold p95** | **0.752 s** — under the 1 s bar |
| hold max | 0.760 s |
| per row, at p95 | 107.5 µs |

The hold is `migration.migrate` from its `BEGIN IMMEDIATE` to its `COMMIT`, with nothing contending
for the lock, so it is the step's own work. The backfill therefore stays inside the step; the
fallback §7.7.1 names for a miss is not taken.

**The margin is a quarter of the bar, not a multiple of it.** The figure scales with rows, and the
linked third is the expensive part: each reads its chunks again past the first to find the block's
end. A corpus several times larger than this one, or a host under heavier load, could cross 1 s; the
next lever, if it is needed, is the fallback the section already specifies.

## The real store beside it

`~/Trading/LeibaTrader`'s `arcs` corpus, copied with `Connection.backup` while its service kept
serving: **24 rows, migrated in 0.003 s.** The real stores here are two orders of magnitude smaller
than the bar's corpus, which is why the bar is set on a synthetic one.
