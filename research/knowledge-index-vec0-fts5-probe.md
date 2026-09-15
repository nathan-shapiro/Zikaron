# `vec0` DDL in a transaction, and external-content FTS5 without its content — measured

**Date:** 2026-09-14. **Harness:** `spikes/spike_vec0_fts5_ddl.py`, re-runnable
(`.venv/bin/python spikes/spike_vec0_fts5_ddl.py`; exits non-zero if any PASS/FAIL question fails).
**Consumers:** `design/knowledge-index.md` §3.2, §4.6, §8.4. **Milestone:** M19 spike A.
**Environment:** SQLite 3.45.1, `sqlite-vec` as vendored in this project's venv, CPython 3.12.

## The question

Two mechanisms in the knowledge-index design are asserted **from documentation**, and each would
force a redesign rather than a patch if it did not hold:

1. **§8.4's encoder-mismatch repair** drops `chunks`, `chunks_fts` and `chunks_vec` and recreates the
   vector table **at a new dimension in a single transaction**. Does DDL on a `vec0` virtual table
   participate in a transaction at all; does it roll back cleanly on failure; does the new dimension
   survive a reopen?
2. **§3.2's no-cascade reasoning** rests on external-content FTS5 not observing deletes on its content
   table, so rows must be removed explicitly — and on querying such an index returning *"garbage rather
   than an error"*.

Method: a miniature of §3.2 — `chunks` + external-content `chunks_fts` + `chunks_vec(float[4])`, three
rows — driven through each case, with FTS5's own `integrity-check` used as an independent oracle.

## Result: both mechanisms hold, and four traps sit beside them

| # | Question | Result |
|---|---|---|
| A1 | drop + recreate `vec0` at a new dimension inside one explicit transaction | **works** — declared dimension 4 → 6 |
| A2 | the new dimension survives close/reopen and is enforced | **works** — old-dimension insert rejected: *"Expected 6 dimensions but received 4"* |
| A3 | `ROLLBACK` after dropping and recreating restores the pre-repair state | **works** — 3 vectors back, dimension back to 4, FTS query answers again |
| A13 | `DROP TABLE` removes `vec0`'s shadow tables, so the recreate does not collide | **works** — 5 objects → 0 → 5 |
| A5 | FTS5 observes a delete on its external content table | **it does not**, as documented — `MATCH` still returns the rowid |
| A10 | the `'delete'` command with the original column values, then delete the content row | **works** — index clean, `integrity-check 1` OK |
| A12 | `'delete-all'` clears the index without needing any original values | **works** |
| A14 | an `AFTER DELETE` trigger on `chunks` maintaining **both** derived tables | **works** — 0 orphans, `integrity-check 1` OK |

**So §8.4's repair stands as specified and §3.2's no-cascade premise stands.** What the probe adds is
four things the design does not currently say, three of which are hazards an implementer would
otherwise meet at runtime.

## Trap 1 — "in one transaction" is not what Python's default connection does

`sqlite3`'s legacy transaction control (`isolation_level=""`, the default, and what `aiosqlite.connect`
passes through) opens an implicit transaction **only before DML**. A `DROP TABLE` issued with no
transaction open therefore runs in **autocommit**:

| # | Case | Outcome |
|---|---|---|
| A4 | `DROP TABLE` with no explicit `BEGIN` | `ROLLBACK` did **not** restore the table |
| A4b | `DROP TABLE` after a DML statement opened the implicit transaction | rolled back correctly |
| A4c | `executescript()` inside an explicit transaction | **committed the open transaction first** — 2 of 3 rows survived a `ROLLBACK` that should have restored all 3 |

A4c is the sharper one, because writing a five-statement repair as one `executescript` is the natural
thing to reach for and it *silently* dissolves the atomicity the section's whole argument rests on.

**This project is already safe by construction and only by construction**: every write goes through
`core/store/transactions.py::in_one_transaction`, which issues an explicit `BEGIN`. The constraint to
state in §8.4 is therefore narrow and checkable — **the repair must run through that helper, statement
by statement, never as an `executescript`.**

## Trap 2 — the orphaned index raises `database disk image is malformed`, it does not return garbage

§3.2 says querying external-content FTS5 whose content rows have vanished *"returns garbage rather than
an error"*. **Measured, that is wrong in the direction that matters**, and which of the two you get
depends on what the query projects:

| # | Query against an orphaned row | Result |
|---|---|---|
| A6 | `SELECT rowid, path, text … MATCH` | **`DatabaseError: database disk image is malformed`** |
| A8 | `snippet(…)` | **same error** |
| A8b | `highlight(…)` | **same error** |
| A7 | `bm25(…)` alone | **−0.554, no error** |
| A5 | `SELECT rowid`/`count(*)` alone | **answers normally** |

The split is exactly whether the query needs the *content*. Ranking and counting read the index only
and succeed silently; anything that reads a column goes to the content table, finds no row, and reports
the database as malformed.

**Two consequences.** The design's conclusion is unchanged and in fact strengthened — an orphan is not a
subtly wrong answer, it is a hard failure — but the *symptom* is one that reads like store corruption
and would plausibly route a real incident into the wrong degraded mode, quarantining a database whose
bytes are fine. And the "silent garbage" half is real but narrower than the sentence implies: it is
confined to the ranking arm, where an orphan keeps contributing a BM25 score to fusion with nothing
raising.

## Trap 3 — the explicit delete has an ordering constraint, and getting it wrong is silent

The `'delete'` command requires the **original column values**. Supplying wrong ones is not rejected:

| # | Case | Result |
|---|---|---|
| A10 | `'delete'` with the original values, **then** delete the content row | clean; `integrity-check 1` OK |
| A11 | content row deleted **first**, then `'delete'` with NULLs (all that is left to pass) | **accepted, and a no-op** — `MATCH` still returns the row; `integrity-check 0` says **OK**; `integrity-check 1` says `database disk image is malformed` |

So §4.6's per-file transaction must **read `chunks.path` and `chunks.text` before deleting the `chunks`
rows**, and pass them with the row's id. An implementation that deletes the content row first has no
way to supply correct values and will corrupt the index while every call returns success.

`'delete-all'` (A12) clears a whole index with no values at all, and is the obvious escape — but
**nothing in this design has an occasion to use it.** The one whole-corpus operation, §8.4's
encoder-mismatch repair, *drops and recreates* `chunks_fts` rather than clearing it, which subsumes
the command; `remove` unlinks the file; `full=true` is per-file transactions. It is recorded here as a
measured property, not as a recommended path.

## Trap 4 — FTS5's `integrity-check` is blind to this unless you pass argument 1

| # | Form | orphaned index (FTS row, no content row) | missing row (content row, no FTS row) |
|---|---|---|---|
| A9 / A16 | `VALUES('integrity-check')` — the bare form | **OK** | **OK** |
| A9b / A16 | `VALUES('integrity-check', 0)` | **OK** | **OK** |
| A9c / A16 | `VALUES('integrity-check', 1)` | **`database disk image is malformed`** | **`database disk image is malformed`** |

Every cell is measured. The bare form is run against both corpora rather than assumed equivalent to
argument 0, because "the form an implementer reaches for first" is the bare one and that is precisely
the claim this trap makes.

Argument 0 checks only the index's internal consistency; 1 additionally compares it against the content
table, which is the only form that can see either defect. **This is the mechanical oracle invariant 3
needs** — `INSERT INTO chunks_fts(chunks_fts, rank) VALUES('integrity-check', 1)` — and the default
form, which is what an implementer would reach for, silently passes on exactly the corpus the invariant
exists to rule out.

**Both directions are measured deliberately, because invariant 3 has two of them** and an oracle that
saw only one would pass on half the corpus it exists to exclude. A16 is the inverse case: issue a
*valid* `'delete'` for one row and **keep** its content row, so `chunks` holds a row with no
`chunks_fts` entry. Argument 1 raises there too; argument 0 still reports OK.

**Recorded because it is this probe convicting itself of trap 4.** The first version of this harness
tested `integrity-check` in the **argument-less form only** — the form the table above shows cannot
see the defect the probe was written to characterise. It reported OK, and that was very nearly written
down as "the orphan is invisible to integrity-check" full stop. The arguments were added only after
asking what the argument was *for*. The natural implementation was the blind one.

## The finding that could change the design: a cascade does exist, via triggers

§3.2 argues the FK is dropped because *"SQLite provides no cascade across these three tables"*. That is
true of **foreign keys** and false as a statement about mechanisms. A14: a single `AFTER DELETE` trigger
on `chunks`, issuing the FTS5 `'delete'` command with `old.*` values and a `DELETE FROM chunks_vec`,
maintains **both** derived tables correctly — including the `vec0` virtual table — leaving zero orphans
and a clean `integrity-check 1`. It also closes trap 3 by construction, since `old.*` *is* the original
value and no ordering exists to get wrong.

**It is not free, and A15 measures the bill.** With that trigger installed, §8.4's repair — drop
`chunks_fts`, drop `chunks_vec`, then clear `chunks` — fails with **`OperationalError: no such table:
main.chunks_fts`**, because the trigger fires per deleted row against tables the same transaction has
already dropped. A design using triggers must drop the trigger first, or drop `chunks` as a table rather
than deleting its rows, and either way the repair acquires an ordering dependency on a piece of schema
that is invisible at the call site.

That is a genuine trade rather than a refutation, and it is recorded here so §3.2 states it rather than
asserting that no mechanism exists. The index phase writes chunks as well as deleting them, so triggers
would cover one half of the maintenance and not the other, and §4.6's transaction would still be doing
explicit work on every insert.

## What changes in the design

1. §3.2 — replace *"returns garbage rather than an error"* with the measured split (error on any query
   that projects a column; silent BM25 contribution on the ranking arm).
2. §3.2 — narrow *"SQLite provides no cascade"* to **declarative** cascades, and put the trigger
   alternative in §15 with A15's cost as the reason it is not adopted.
3. §4.6 — state the ordering constraint: the original column values are read before the content rows are
   deleted.
4. §8.4 — state that the repair runs through `in_one_transaction`, never as an `executescript`.
5. Invariant 3's test — use `integrity-check` **argument 1**, which is measured to raise in **both**
   directions (orphaned FTS row, and missing FTS row); the bare and argument-0 forms see neither.

Nothing here refutes a mechanism the design depends on, so **M20 is unblocked** by this spike.
