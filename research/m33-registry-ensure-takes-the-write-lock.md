# A no-op `CREATE TABLE IF NOT EXISTS` asks for the write lock on the connection the service holds

**Measured 2026-09-28**, on Python 3.12.3 / SQLite 3.45.1, WAL, `busy_timeout = 5000`.
Re-derive with `.venv/bin/python spikes/m33_registry_ensure_lock.py`.

## What was believed

`zikaron/core/knowledge/registry.py`'s `ensure_table` carried this, and `design/schema.md`
§"`call` is an access log" rested a normative bullet on it:

> `CREATE TABLE IF NOT EXISTS` against a table that already exists takes no write lock at all — it
> succeeds while another connection holds the writer lock.

## What was measured

A real store, its registry table already created, a second connection holding the write lock
(`BEGIN IMMEDIATE` plus an `INSERT`):

| The statement, and where from | Outcome |
|---|---|
| `CREATE TABLE IF NOT EXISTS knowledge_bases …`, on the connection `ServiceContext` holds | **`database is locked` after 5.009 s** |
| the identical statement, on a connection opened fresh against the same file | OK in 0.001 s |
| `SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?`, on the store's connection | OK in 0.001 s |

So the claim holds for a fresh connection and fails for the one that matters. The five-second wait
is what identifies it: an immediate refusal would be `SQLITE_BUSY_SNAPSHOT` from a stale WAL
snapshot, and waiting out `busy_timeout` is plain `SQLITE_BUSY` — the statement genuinely asked for
the write lock.

**The mechanism was not identified and is deliberately not guessed at here.** Seven narrowing
attempts failed to reproduce it outside the real store: not `isolation_level` (`None` and `''` both
pass on a bare connection), not `PRAGMA foreign_keys`, not the presence of an FTS5 virtual table,
not a loaded `sqlite-vec` with a live `vec0` table, not whether the creating connection is the one
re-issuing the statement, not an unclosed cursor, and not an open transaction — `in_transaction` is
`False` and an explicit `ROLLBACK` reports *no transaction is active*. What distinguishes the two
connections is state accumulated on the long-lived one, and the boundary is what the fix needs
rather than the cause.

## What it cost, before it was found

`registry.ensure` is the first thing **every** knowledge verb calls. So every one of them —
`knowledge_search` and `knowledge_list` included — asked for `memory.db`'s write lock and answered
`store_unavailable` whenever any write had been in flight for five seconds. Nothing surfaced it,
because nothing had ever driven a knowledge verb against a held lock: the case was reached only by
M33's access-log isolation test, whose whole subject is what a caller pays under contention.

## The fix, and why it is not the same claim

`ensure_table` now reads `sqlite_master` and issues nothing when the table is there. The five
read-only verbs therefore write **nothing** to `memory.db`, rather than writing something cheap —
which is stronger than the withdrawn claim and does not depend on how SQLite locks a no-op. The
`IF NOT EXISTS` stays, so two callers that both find it absent still cannot collide.

Guarded by `tests/test_knowledge_registry.py::TestWhatEnsuringTheTableCosts`, which asserts the
elapsed time under a held lock rather than counting statements: "takes no write lock" is the claim,
and a statement count would not notice the day SQLite changes its mind about a no-op.
