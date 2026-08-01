# M0 spike results

> Written 2026-08-01. Exercises the four assumptions named in `design/build-plan.md`'s M0 brief — the ones
> underpinning the architecture that no line of code had ever tested — plus one follow-up spike added the same
> day after a design conversation about spike 3's finding. Throwaway per the brief's fence: scripts live in
> `spikes/`, are not production code, and carry no test suite. Environment: Python 3.12.3, stdlib `sqlite3`
> 3.45.1, `sqlite-vec==0.1.9`, `fastembed==0.8.0`, `aiosqlite==0.22.1`, in a dedicated venv at `spikes/.venv`.
>
> **Bottom line: all four of M0's original assumptions held, and the follow-up spike settled a real design
> decision.** Spikes 1, 2 and 4 needed no correction beyond rationale notes. Spike 3 exposed a genuine
> implementation bug (a self-inflicted deadlock from running blocking SQL inline on the event loop) whose first
> fix — `asyncio.to_thread` at each call site — is superseded by spike 5's finding: `aiosqlite` prevents the
> same bug structurally rather than by convention, and is now mandated for all of `zikaron-core`'s SQL. One
> deliberate scope-down (idle timeout shortened for observability, spike 3) is noted where it appears.

## Environment check

`design/schema.md`'s header claims stdlib `sqlite3` has FTS5 compiled in and `enable_load_extension`
available, verified locally. Re-verified here, same result: Python 3.12.3, `sqlite3.sqlite_version` 3.45.1,
`ENABLE_FTS5` and `ENABLE_LOAD_EXTENSION` both present in `PRAGMA compile_options`. No discrepancy.

## Spike 1 — sqlite-vec

**Script:** `spikes/spike1_sqlite_vec.py`. **Assumption tested:** the extension loads, the `float[<embed_dim>]`
DDL template substitutes correctly at a non-default width, the explicit-rowid join holds, KNN returns
distances, and a dimension mismatch is caught rather than silently corrupting data.

| Check | Result |
|---|---|
| Extension load | `sqlite_vec.load(con)` succeeds; `vec_version()` reports `v0.1.9` |
| DDL template at non-384 width | `CREATE VIRTUAL TABLE memory_vec USING vec0 (embedding float[8])` — tested at 8, not 384, since 384 is the one width every other measurement already covers and the template mechanism itself is what needed exercising |
| Explicit-rowid join | Inserting with `INSERT INTO memory_vec (rowid, embedding) VALUES (?, ?)` at `rowid = chunk_id` makes `memory_vec.rowid == memory_chunk.chunk_id` hold exactly, confirmed by joining the two tables |
| KNN | `WHERE embedding MATCH ? AND k = ?` returns rows ordered by a numeric `distance` column; nearest-first ordering matched the geometrically closer vector in the fixture |
| Dimension mismatch | Inserting a 3-d vector into an 8-d column raises `sqlite3.OperationalError: Dimension mismatch for inserted vector for the "embedding" column. Expected 8 dimensions but received 3.` — an exact, actionable message, not silent corruption |
| Mismatch detectable **before** insert | Yes, two ways: `vec_length(embedding)` on any existing row reports the declared width, and `sqlite_master.sql` for the virtual table shows the declared DDL (`float[8]`) directly |

**Verdict: held cleanly, no correction needed.** The dimension-mismatch behavior matters for M2's done-when
clause ("a dimension mismatch is rejected before any table exists") — this spike confirms the width is
inspectable pre-insert via either mechanism above, so that clause is achievable as written.

## Spike 2 — FTS5 external-content

**Script:** `spikes/spike2_fts5.py`, with two follow-up isolation scripts (`spike2b_corruption_isolation.py`,
`spike2c_filebacked_recheck.py`) after the main script surfaced something worth pinning down precisely.
**Assumption tested:** the amend sequence (delete-then-insert inside one transaction, `content='memory'`) and
the documented erasure sequence (the FTS5 `'delete'` command using current values) both behave as
`design/schema.md` and `design/write-policy.md` assume, and a stale term is genuinely unmatchable afterward.

| Check | Result |
|---|---|
| Amend sequence | `DELETE FROM memory_fts WHERE rowid = :id` → `UPDATE memory SET ...` → `INSERT INTO memory_fts (rowid, gist, content) VALUES (:id, ...)`, one transaction — committed cleanly |
| Stale term after amend | Genuinely unmatchable: searching the replaced term (`"staging"`) returns `[]` |
| Retained term after amend | A term present in both old and new content (`"protobuf"`) still matches |
| New term after amend | The newly-introduced term (`"prod-eu"`) matches |
| Documented erasure sequence | Read current values → FTS5 `'delete'` command with those values → `DELETE FROM memory` → `COMMIT` — zero errors, target term unmatchable afterward, `memory_fts` bare-select for the rowid returns empty |
| Post-erasure hygiene | `integrity-check`, `PRAGMA wal_checkpoint(TRUNCATE)`, `VACUUM` all succeed with zero errors — **once run outside any open transaction on a file-backed db** (see gotcha below) |

**Verdict: held, plus one real finding worth carrying into the design as a rationale note.**

### New finding: the naive alternative doesn't just fail, it corrupts — and not on the first query

`write-policy.md`'s documented erasure sequence explicitly maintains `memory_fts` with the `'delete'` command.
This spike asked what happens if that step is skipped — i.e., `DELETE FROM memory` alone, with no
corresponding FTS5 maintenance, since `content='memory'` might plausibly (and wrongly) be assumed to
auto-sync. Isolated in `spike2b_corruption_isolation.py` and re-confirmed on a file-backed db in true
autocommit mode (`isolation_level=None`) in `spike2c_filebacked_recheck.py`:

- The naive `DELETE FROM memory` (content-table side only) commits with **no error**.
- The **first** `MATCH` query afterward does not raise — it returns a **phantom stale row** (`[(1,)]`) that
  matches nothing real, since the term it was supposedly matching no longer exists anywhere. This is silently
  **wrong**, not silently absent and not an error.
- A **second**, identical `MATCH` query then raises `sqlite3.DatabaseError: database disk image is malformed`.

So the failure mode is: commit cleanly → one wrong-but-plausible-looking answer → corruption on the next touch.
Not "corrupts immediately" and not "fails loudly right away" — a caller who ran exactly one query after a bad
delete and saw a sensible-looking empty or wrong result would have no signal that anything was wrong until the
*next* access. This validates why `write-policy.md`'s sequence is written the way it is, but the specific shape
of the failure (silent-wrong-answer-then-corruption, not an immediate clean error) was not previously
documented anywhere in `design/` and is worth a rationale note — see "Design impact" below.

### Implementation gotchas for M2 (not design defects)

- Python's `sqlite3` module defaults to `isolation_level=''`, which auto-`BEGIN`s a transaction before DML.
  Mixing that with explicit `BEGIN`/`COMMIT` strings left a transaction open across statements in an early
  version of this spike's file-backed recheck, which made `wal_checkpoint`/`VACUUM` fail with `database table
  is locked` / `cannot VACUUM from within a transaction` for a driver reason that had nothing to do with the
  design. Fixed by connecting with `isolation_level=None` (true autocommit). Whoever builds M2's store should
  be deliberate about this from the start.
- FTS5's unquoted `MATCH` syntax parses bare `-` as `NOT` and other punctuation specially (confirmed when an
  unquoted `"prod-eu"` query raised `no such column: eu`, i.e. parsed as `prod NOT eu`). `retrieval.md`'s real
  query construction already quotes terms, so this is not a design gap — just confirms why that quoting is
  there.

## Spike 3 — UDS JSON-RPC transport

**Scripts:** `spikes/spike3_server.py` (asyncio UDS server), `spikes/spike3_client.py` (implements
`architecture.md`'s exact start-if-absent sequence), plus one script per scenario:
`spike3a_warm_latency.py`, `spike3b_race_start.py`, `spike3c_connect_during_exit.py`,
`spike3d_busy_timeout.py`, `spike3e_busy_timeout_isolated.py`.

**Scope-down, stated plainly:** `idle_timeout` is a few seconds in these spikes, not the real 30-minute
default, so the idle-exit race is observable within a spike run rather than requiring a 30-minute wait. This
is a scale-down for observability, not a claim about the production default.

**Assumption tested:** the transport end to end — cold and warm round-trip latency, two clients racing
start-if-absent under `flock`, a client connecting exactly as the server exits on idle, and `busy_timeout`
behavior with two writers.

### Cold start

Full start-if-absent sequence (try connect → `ENOENT` → `flock` → try connect again → spawn detached → poll
`health()` → release lock → verify `health()`) end to end from a cold process: **~101 ms**, dominated by
Python interpreter start for the spawned server, not by the transport itself.

### Warm round-trip

200 sequential `echo()` calls over an already-connected socket:

| Metric | Value |
|---|---|
| min | 0.129 ms |
| p50 | 0.146 ms |
| p95 | 0.214 ms |
| p99 | 0.255 ms |
| max | 0.304 ms |
| mean | 0.159 ms |

Consistent with the design's own separately-measured client-side interpreter-cost figures (10.9 ms bare,
20.6 ms with `socket`+`json`) — the warm RPC itself is sub-millisecond; interpreter startup dominates cold-path
cost, not the transport.

### Two clients racing start-if-absent under `flock`

Two processes released at (as close as achievable) the same instant against a cold store: exactly **one**
server process spawned — both racers converged on the same pid. Racer-A won the connect race, took the lock,
spawned the server. Racer-B blocked on the lock, and on acquiring it found the server already up — the "try
connect again" step in the documented sequence correctly short-circuited it straight to a normal connect,
rather than spawning a second server. No thundering herd.

### A client connecting exactly as the server exits on idle

Busy-polling raw `connect()` through the idle deadline showed a clean, single transition:
`ok → fail:No such file or directory`, landing exactly at the deadline — the race is real and reproducible,
not theoretical. The client's `connect_start_if_absent()`, used **unmodified**, recovered fully via its own
retry-through-start-if-absent logic: no special-casing was needed beyond what `architecture.md` already
prescribes ("clients retry once through the full sequence before falling back").

### `busy_timeout` with two writers — a real finding about the *service*, not the database

First implementation of the spike server ran the blocking `sqlite3` calls (`BEGIN IMMEDIATE`, `COMMIT`)
**inline inside an `async def` handler**, on the asyncio event loop thread, simulating the write's hold with
`await asyncio.sleep()`. Result: even a trivial 0.5 s hold made the second writer fail with `store_busy:
database is locked` after waiting the full 5 s `busy_timeout` — looking exactly like `busy_timeout` was
failing to absorb ordinary contention.

It wasn't. Isolated in `spike3e_busy_timeout_isolated.py` using two real OS threads and no asyncio at all:
`busy_timeout=5000` **does** correctly absorb a 0.5 s hold when the blocking calls are off the event loop —
writer B blocked for ~0.5 s, then succeeded, counter incremented twice, no lost update. The original server's
bug was a **self-inflicted deadlock**: writer B's blocking `BEGIN IMMEDIATE` call froze the single-threaded
event loop, which prevented writer A's `asyncio.sleep()` from ever firing to release the lock — so B's own
`busy_timeout` ran out waiting on a release that could structurally never happen while B itself was blocking
the only thread that could deliver it.

Fixed by wrapping the blocking write in `asyncio.to_thread()`. After the fix, the through-the-transport
reading matched the isolated one:

| Scenario | Result |
|---|---|
| Two writers, 0.5 s hold each | Both succeed, serialized. Counter goes 1 → 2 (no lost update). Writer-2's `waited_s` = 1.04 s, consistent with waiting through writer-1's full cycle plus its own hold |
| One writer holding 6.0 s (longer than `busy_timeout`) vs. a second writer with no hold | Long-holder succeeds at 6.02 s. Second writer fails `store_busy: database is locked` at ~5.01 s — `busy_timeout`'s own ceiling, not an instant failure and not a hang |

**Design implication for M9, stated as a correctness requirement rather than an optimization:** the real
`zikaron-service` must run every blocking `sqlite3` call via `asyncio.to_thread` or a dedicated executor, never
inline in an `async def` handler. Getting this wrong under real write contention produces exactly the deadlock
above, and it will present as a `busy_timeout`/`store_busy` problem — inviting someone to "fix" `busy_timeout`
or the database when the actual defect is in the service's own concurrency model. See "Design impact" below.

**Verdict: the transport itself held on every documented behavior.** The one failure was a spike-server
implementation bug, caught, isolated, and fixed within this spike — and the fix surfaces a real requirement
for M9 that was previously implicit rather than stated.

## Spike 4 — fastembed cold vs. warm, and on-disk footprint

**Script:** `spikes/spike4_fastembed.py`. **Assumption tested:** the 783 ms cold / ~5.5 ms warm figures the
architecture rests on, plus the on-disk footprint (not previously stated anywhere in `design/`).

**Which figures, precisely** — the build brief's "783 ms / 5.5 ms" compresses several distinct numbers spread
across `design/overview.md`, and this spike measured each rather than guessing which one the shorthand meant:

- **D22:** cold whole-process `bge-small` load+embed = **783 ms**, contrasted against 0.26 ms warm BM25-only
  (no embedding at all) — the number behind "the hook must never load an embedding model".
- **D31:** warm, unprefixed = **5.45 ms** embed / 7.97 ms full path. Warm, prefixed (the config D20 actually
  adopts) = **6.64 ms** embed / 9.14 ms full path.
- **`retrieval.md`:** the query prefix costs **+1.19 ms**, measured separately from the two figures above.

**Model actually in use, confirmed rather than assumed:** `qdrant/bge-small-en-v1.5-onnx-q` — a **quantized**
ONNX export — cached at fastembed's own default `/tmp/fastembed_cache`, not at `~/.cache/huggingface`'s hub
layout (which holds only a small tokenizer/config blob; this was a real dead-end in this spike's own first
attempt at the footprint measurement, resolved by asking a live model instance for its `cache_dir` rather than
guessing a path).

| Measurement | Result | Design figure | Read |
|---|---|---|---|
| Cold total (import + construct + first embed) | 614–737 ms across 3 runs | 783 ms | Same order of magnitude, plausible machine/run variance |
| Prefix cost, isolated | +0.998 to +1.068 ms across 2 clean runs | +1.19 ms | Close match |
| Document-length warm embed (no prefix) | 6.4–6.8 ms mean across runs | 5.45 ms (unprefixed) / 6.64 ms (prefixed) | Same order of magnitude |
| On-disk footprint | **64.07 MiB**, cross-validated exactly against `du -sh` (`64M`) | not previously stated | New measurement, establishes the figure for the first time |

**Verdict: all figures confirm within expected variance. No design correction needed.**

### Why this took three rounds of self-caught measurement bugs, and why that's worth recording

None of the numbers above came out right on the first attempt, and each wrong attempt was caught by comparing
the result against something else known to be true (a design figure, `du`, or plain arithmetic) rather than
accepted at face value:

1. **Warm-up-order confound.** Measuring "unprefixed" and "prefixed" as two sequential blocks let residual
   ONNX runtime warm-up (thread pool, memory arena) bleed into whichever block ran first, making the *second*
   block look faster for a reason that had nothing to do with prefixing. Fixed by interleaving the two
   conditions call-by-call.
2. **Base-text-length confound.** Even after interleaving, prefixed still looked *faster* than unprefixed — the
   wrong direction. The actual cause: the "unprefixed" condition was embedding a 142-character document while
   the "prefixed" condition was embedding a 41-character query plus a 57-character prefix (98 characters
   total) — fewer total characters despite the added prefix. Comparing a document against a query is not a
   prefix-cost measurement at all. Fixed by holding the same base query text constant across both conditions
   and measuring document-length text as a separate, honestly-labeled data point.
3. **Symlink double-counting.** The first footprint number was 128.13 MiB, exactly double the correct 64.07
   MiB. HF hub's cache layout stores each file once under `blobs/<hash>` and symlinks it into
   `snapshots/<rev>/<name>` for human-readable access; naive `os.walk` + `os.path.getsize` summation follows
   the symlink and counts the 63.39 MiB weight file twice. `du` gets this right by default; fixed by deduping
   on `(st_dev, st_ino)`, and cross-checked the final number against `du -sh` directly (`64M`, exact match).

None of these three bugs were subtle in retrospect, and all three would have shipped silently into
`spike-results.md` as confident, wrong numbers if the results hadn't been checked against something external.
That is itself the argument for why this milestone was a spike rather than a from-memory writeup: a plausible
wrong number is not self-announcing, whether it comes from an outdated recollection or from an uncaught bug in
the very script measuring it.

## Spike 5 — `aiosqlite`, mandated after M0 closed

Added 2026-08-01, after M0 was otherwise complete: spike 3 found that an inline `async def` handler calling
blocking `sqlite3` directly self-deadlocks under write contention, and the fix applied at the time was
`asyncio.to_thread` at each call site. The user asked whether an official asyncio-friendly SQLite client
exists and proposed mandating `aiosqlite` instead — this spike verifies that choice against every mechanism
`zikaron-core` actually needs before it went into the design, rather than accepting it on the library's
popularity.

**Script:** `spikes/spike5_aiosqlite_check.py`. **What's checked:** `sqlite-vec` extension loading, the
`float[N]`/KNN/dimension-mismatch behavior spike 1 established, the FTS5 external-content amend/erasure
sequence spike 2 established, and the two-writer `busy_timeout` contention spike 3 exposed the deadlock in —
all run through `aiosqlite==0.22.1` inside a real asyncio event loop.

| Check | Result |
|---|---|
| Extension loading | `sqlite_vec.load(conn)` is `conn.load_extension(sqlite_vec.loadable_path())` under the hood, and `aiosqlite.Connection` exposes its own `load_extension` async method — `await db.load_extension(sqlite_vec.loadable_path())` works. Reaching into the wrapped connection directly (`db._conn`) does **not** work and raises `SQLite objects created in a thread can only be used in that same thread` — `aiosqlite` runs the real `sqlite3.Connection` on its own dedicated worker thread, and stdlib connections are hard-bound to their creating thread |
| `vec0` KNN | Identical results to spike 1's raw-`sqlite3` version |
| Dimension mismatch | Identical error message, correctly propagated through the async wrapper |
| FTS5 amend | Stale term unmatchable, new term matchable — identical to spike 2 |
| FTS5 erasure | Clean, zero errors — identical to spike 2 |
| Two writers, 0.5 s hold each, contending on `busy_timeout` | **Both succeed, serialized, no lost update.** Writer B's `waited_s = 1.04 s` — it genuinely waited through writer A's hold rather than the loop deadlocking |

**Verdict: every mechanism holds, and the contention check is the one that matters.** Spike 3's deadlock
happened because one connection's blocking call froze the *shared* event loop thread, preventing a different
coroutine's `asyncio.sleep()` from ever running to release its lock. `aiosqlite` avoids this **structurally**
rather than by convention: each connection's blocking calls run on its own worker thread, so there is no
synchronous call path for a handler to expose at all — the class of bug spike 3 found cannot occur through
`aiosqlite`, whereas `asyncio.to_thread` only prevents it if every call site remembers to use it. That is a
real, verified difference in kind, not just a nicer API, which is why it displaces the `asyncio.to_thread` note
rather than sitting alongside it as an alternative.

**One implementation detail worth carrying forward:** `sqlite_vec.load()` cannot be called against
`aiosqlite`'s connection the way it can against a raw `sqlite3.Connection` — it must be reconstructed as
`await db.load_extension(sqlite_vec.loadable_path())` through `aiosqlite`'s own sanctioned API. This surfaced
immediately (a thread-affinity error) rather than silently, which is the good case, but it means the store
layer's extension-loading code cannot simply call the library's documented `load()` helper unmodified.

## Design impact

**No D1–D33 decision needs to change, and one new decision was added.** All four of M0's spiked assumptions
held. One item below is a rationale note; the other started as one and was superseded by an actual design
addition once the user raised the async-SQLite-library question and spike 5 confirmed it:

1. **`design/write-policy.md`** — a rationale note: skipping the FTS5 `'delete'` maintenance step on erasure
   doesn't fail cleanly, it produces one silently wrong answer and then corrupts the database on the next
   touch. Strengthens the existing "the FTS5 side must be maintained explicitly" guidance with the specific,
   measured failure shape. Applied and re-indexed; no further change from spike 5.
2. **`design/architecture.md`'s RPC section, and `design/coding-standards.md` §6** — **superseded once, not
   merely amended.** The first correction (applied same day) said the service must run every blocking `sqlite3`
   call via `asyncio.to_thread`, discovered by spiking the transport and finding a self-inflicted deadlock that
   presents as a `busy_timeout`/`store_busy` defect. Spike 5, added after a design conversation about whether
   an official asyncio-friendly SQLite client exists, found `aiosqlite` closes the same defect **structurally**
   rather than by convention — no call site can forget to dispatch off the loop, because `aiosqlite` never
   exposes a synchronous call to make. That is a difference in kind, not degree, so it replaced the
   `asyncio.to_thread` note rather than sitting beside it: `aiosqlite` is now mandated for all of
   `zikaron-core`'s SQL, `asyncio.to_thread` is not mentioned as an alternative, and the hook's degraded-path
   direct read stays on bare stdlib `sqlite3` (no event loop to protect, and pulling in a dependency there
   would violate the hook's stdlib-only constraint for no benefit).

Both are additions to existing sections, not reversals of any D1–D33 decision, invariant, or table — but item 2
is now genuinely normative (a mandated dependency) rather than purely explanatory. Applied to `design/` and
re-indexed.
