# M35 brief — the perturbation table, walked before review

Axes, from `design/build-plan.md` §M35:
- **Interruption point:** before `BEGIN`, waiting on the connection lock, between a read and a write,
  mid-commit, while holding a pool lease.
- **Other writer:** another in-process request on the writer, a read upgrading on a pool connection,
  the access log's connection, the indexer, a second service, an operator's shell.
- **Connection:** the writer, a pool connection, the access log's.

Cells are grouped where one argument covers them. Each group ends in **holds**, or in **the brief
change it forced**.

**Before `BEGIN` / waiting on the connection lock**
- *Any writer, writer connection, cancelled at shutdown.* The lock is released by the context
  manager; no transaction was open. Holds.
- *In-process writer holding a long transaction (the plan fallback, or a stuck one).* An unbounded
  wait queues every writer behind it forever, which is a wedge by construction.
  → **Forced: the lock wait is bounded by `busy_timeout` and answers `store_busy`**, minted from
  `LockWaitExpired` at dispatch (after round 14).
- *Pool exhausted.* The read waits for a lease within its request's one wait budget (item 2).
  Holds.
- *A write method's planning lease when the pool is exhausted* (added after round 8). An unbounded
  wait would let a consolidator's plan commit after its client had given up. No cycle, since the
  writer's lock is not held at either point. → **Forced: bounded by `ddl.BUSY_TIMEOUT_MS`,
  answering `store_busy` past it.**

**Between read and write**
- *Write verb, writer connection, any other writer.* No such window exists: `BEGIN IMMEDIATE` takes
  SQLite's write lock before the first read. Another process's commit waits on the busy handler (at
  most 5 s), or the verb does. Holds. This is the CI flake's cell.
- *Read verb upgrading for its events, pool connection, another writer committed since its
  snapshot.* `SQLITE_BUSY_SNAPSHOT`. **Changed, not unchanged** (review round 1, finding 6). Before
  M35 an in-process writer could never stale an in-process read, because they shared a connection.
  Now every `remember`, `amend`, `fetch` or consolidator commit inside a read's window does.
  → **Forced: one server-side retry of the read transaction, and a probe phase with that traffic.**
- *Read verb upgrading, pool connection, the writer holding the lock.* ~~The busy handler waits at
  most 5 s. Holds.~~ **Wrong** (review round 5, finding 1; measured by
  `spikes/m35_read_upgrade_probe.py`). SQLite never runs the busy handler for a connection already
  inside a read transaction, so the upgrade is refused at once with primary `SQLITE_BUSY`. This is
  the highest-traffic read cell after M35. → **Forced: the retry covers both codes and opens
  `IMMEDIATE`, so it waits for the writer.**
- *`next_group` embedding inside its transaction, writer connection.* Under `IMMEDIATE` it holds
  SQLite's write lock across the embed: milliseconds warm, seconds while the model loads.
  ~~→ Forced: the brief names it, and the implementation must say what it accepts.~~ Superseded by
  the audit-of-deferrals cell below: `next_group` waits for the model before its first transaction.

**Mid-commit**
- *Commit fails, rollback succeeds.* The primitive's ladder handles it; the connection is reusable.
  Holds.
- *Commit fails, rollback fails.* `finalize` closes the connection. Today that kills every later
  request.
  → **Forced: a closed connection is never handed out again. The pool replaces it and the writer is
  reopened, with a test.**

**Holding a pool lease**
- *Cancelled before the release.* The lease is released in `finally` and the primitive rolls the
  transaction back. Holds.
- *Cancelled during the release* — a retry's pragma restore, or a dropped handle's close — leaves the
  handle neither idle nor closed, and its worker thread keeps the process alive after a clean stop.
  → **Forced (implementation review round 6): the pool records it and closes it with the pool, with a
  test.**
- *Planning's read snapshot, held for about 12 s.* It blocks WAL checkpoints past its snapshot for
  that span. Before, the plan held the *write* lock for the same span, so this is strictly less.
  Holds.
- *Planning then taking the writer.* The snapshot is released first, by item 2's closing rule on
  waits, so no cycle is possible. Holds.

**Other writers, by kind**
- *Access log (`busy_timeout` 0).* `IMMEDIATE` holds SQLite's lock from `BEGIN` rather than from
  the first write, so a `call` row meets a held lock slightly more often and is dropped. That is
  best-effort under invariant 10's exemption, and out of scope by the fence. Holds; worth one line
  in the implementation's note.
- *Indexer.* Its build row is written through the primitive against `memory.db`, so it becomes
  `IMMEDIATE` too. Both sides wait on the busy handler, not on a snapshot. Item 6 moves the row
  inside the corpus lock. Holds.
- *Second service on the same store.* Start-if-absent should prevent it; if it happens, both use
  `IMMEDIATE` and serialize through SQLite. Holds.
- *Operator shell holding a write transaction.* ~~Writers answer `store_busy` after 5 s. Correct.~~
  True for the first writer only. A writer queued behind one blocked in SQLite's busy handler waited
  5 s for the lock and 5 s more, past the MCP client's 10 s timeout (review round 3, finding 1).
  → **Forced: one wait budget per transaction, lock and SQLite together.**
- *Two consolidators planning at once.* Both compute on snapshots. The write transactions
  serialize, and the second finds the first's run effectively active, so takeover rules apply as
  today. Holds.
- *Journal writes during a plan.* The fingerprint moves and the write transaction plans inside
  itself. The worst case is two plans, which halves the row ceiling.
  → **Forced: the bound is fixed at zero replans, and the ceiling is restated.**

**Added after review round 1** (`reviews/m35-brief-review.md`):
- *Long-term writes during a plan: an anchor retired, merged into or promoted.* A journal-only
  fingerprint misses them, and the write would commit anchors that are no longer targetable.
  → **Forced: the fingerprint covers every active row, both tiers.**
- *Same-task re-entrancy: a transaction opened from inside one on the same connection.* Under a
  plain lock it waits on itself for `busy_timeout` and answers a retryable code for a programming
  error.
  → **Forced: an owner check that fails at once.**
- *Writers queued on the lock when a failed rollback closes the writer.* ~~They run `BEGIN` on the
  closed handle and answer `internal_error` once. Accepted, and stated.~~ Superseded by the
  audit-of-deferrals cell below: the primitive finds the closed mark before any statement, raises
  `WriterClosedError`, and dispatch answers `store_busy`.
- *`next_group` finding a stranger's run between its snapshot and its write.* It answers `Busy`,
  never replans, since `next_group` never takes over.
  → **Forced: stated with the atomic replan-and-serve.**
- *Cold-model pool exhaustion.* Reads embed before their transaction but lease for the handler's
  span, so each read arriving during a model load pins a connection.
  → **Forced: the pool's size is chosen to cover it, and the handler-span lease is justified.**
- *A handler cancelled while holding the writer mid-statement.* The statement completes on the
  worker thread and the `finally` rollback queues behind it, so the lock is held for one statement
  plus at most `busy_timeout`. Holds.
- *The registry table's first creation from a read verb on a pool connection.* A presence read
  followed by a `CREATE` is the CI failure's shape.
  → **Forced: only a write, or the indexer, creates it.**
- *The indexer's failure row.* It is written after the lock's release as well as the success row.
  → **Forced: a completion callback in `scan.run` covers both.**

**Added after review round 2:**
- *A write handler's statement outside the primitive, on the writer, while another handler's
  transaction is open.* It runs inside that transaction and reads uncommitted rows. That is not
  nesting; it is a phantom read on a write path, at three known knowledge-write sites.
  → **Forced: the rule that every writer statement goes through the primitive, and the three sites
  moved.**
- *`next_group` finding its own run at step 3*, written by a concurrent call from the same MCP
  process. → **Forced: discard the plan and serve from that run.**
- *The completion callback raising, and a post-lock failure reaching both writers of the row.*
  → **Forced: a write-once latch, and a callback guarded whole.**
- *A `search` arriving during the fallback window rather than the snapshot phase.* It meets a
  write lock held for a whole plan. Its first attempt is refused at once, and its `IMMEDIATE` retry
  waits and answers `store_busy` when the fallback outlasts its budget. This is the pre-M35 cost,
  paid only when a memory row moved during the plan. Accepted, and the plan property is scoped to
  the snapshot phase.

**Added after review round 3:**
- *A queued writer behind a writer blocked by another process.* See the corrected operator-shell
  cell. → **Forced: one budget.**
- *A read's lease wait followed by its upgrade wait.* ~~These compound the same way. Accepted.~~
  The first attempt's upgrade never waits (round 5). What would compound is the lease wait plus the
  `IMMEDIATE` retry's wait. → **Forced (author's re-read after round 5): one wait budget per read
  request, covering both.**
- *A knowledge write's registry transaction, and whether a corpus open falls inside it.* Wrapping
  `builds.plan` or `reporting.status` whole would hold the writer, or a snapshot, across N corpus
  opens. → **Forced: the transaction covers the registry statements only.**
- *The pool closed at shutdown under a live lease.* The handler's next statement raises
  `ValueError` and answers `internal_error`, inside the shutdown's quiescence deadline. Holds.

**Added after review round 4:**
- *The access log's connection under the budget.* It is a bare-handle holder, so it gets neither
  the budget nor the pragma, its `busy_timeout` stays 0, and its transaction stays deferred. The
  round-4 review read the access-log cell above as making it `IMMEDIATE`; that sentence is the
  indexer's. The indexer's `memory.db` handle is its `Store`'s writer, so it does become `IMMEDIATE`
  and gets the budget, which equals its opened pragma; only its corpus connections are bare.
  → **Forced: the pragma is set only on the writer and on a pool connection leased for a read's
  retry, never on a bare-handle holder** (restated after round 11).
- *A build cancelled mid-scan.* The callback does not run for `CancelledError`; the lock is released
  and no row is written. → **Forced: the callback fires on `Exception` only.**
- *The store replaced at its path, then a lazy pool open or a writer reopen.* The new connection
  would read the new file while the others hold the old one. → **Forced: an inode check on every
  post-startup open.**
- *Two writes dispatched into the writer's reopen.* Both would reopen. → **Forced: the reopen runs
  once, under the store's lock.**

**Added after review round 5:**
- *A `search` or `surface` refused at a held lock, then its `call` row attempted while the lock is
  still held.* The row's connection has `busy_timeout` 0, so the refusal goes unlogged. Accepted
  under invariant 10's exemption. It is stated because the refusal-rate measurement depends on it,
  which is why that measurement counts responses rather than log rows.
- *A retried read under `BEGIN IMMEDIATE` holding SQLite's write lock for its span while the
  writer's `BEGIN IMMEDIATE` waits behind it.* The writer's wait is bounded by its remaining budget.
  There is no cycle, since the writer never waits on a lease. Holds.
- *A memory verb versus a knowledge verb on a post-startup open that finds the file replaced or
  absent.* Each answers by its family's existing rule, so no verb gains a wire code. → **Forced: a
  test per family.**

**Added in the author's re-read after round 5:**
- *A `surface` retry that commits after the push hook has given up.* `surface` rows mean *"this
  session was shown this memory"*, the denominator of D30's repair signal, so a commit after the
  hook's 2 s deadline records an injection the agent never saw. The same outcome from a slow embed
  or a cold model predates M35. → **Forced (operator, 2026-09-29, rejecting a first draft that fenced
  the older case out): item 7.** The hook sends its deadline as an absolute instant,
  `deadline_at_ms`. The service rolls back past it and answers `deadline_passed`. That covers every
  cause at once, and it replaces a separate `surface` budget constant with the caller's own
  deadline.
- *A `surface` whose commit lands just inside the deadline margin, then a response slower than the
  margin.* It is still counted as shown. ~~The margin is set well above a local socket's response
  time.~~ Corrected after round 15: the margin covers the commit path from the pre-`COMMIT` check
  to the hook's `recv`, WAL `fsync` included, set from a stated high percentile of that path
  measured under real load. Accepted and stated.
- *A leased pool connection's `busy_timeout` left at a retry's remainder.* The next read on that
  connection would inherit a shortened wait. → **Forced: the pool restores the store's value when
  the lease returns.**

**Added after review round 6:**
- *A `surface` refused for contention after its deadline.* The retry would time out behind the
  writer and answer `store_busy`. → **Forced: past the deadline, the check points answer
  `deadline_passed`, and the retry's wait ends at the deadline less the margin.** A non-contention
  failure keeps its own code (narrowed after round 7).
- *A request read late by a busy loop, or found in the socket buffer by a wedge that clears.* A
  relative deadline would restart from the late read and commit as shown. → **Forced: an absolute
  wall-clock deadline.** A clock step is the residual, rare and stated.
- *A `deadline_passed` answered while the writer still holds its lock.* Its `call` row is dropped.
  → **Forced: `hook.log` counts what the access log cannot.** The kinds were split after round 12:
  `unanswered` for a post-send timeout, `deadline_passed` for the refusal. After round 13, the two
  `deadline_passed` counts are named as different populations, with no floor either way.

**Added in the author's audit of deferrals:**
- *`next_group` embedding cold under `IMMEDIATE`.* It would hold SQLite's write lock for seconds.
  → **Forced: it waits for the model before `BEGIN`.**
- *Two builds acquiring the corpus lock at once.* Under a deferred `BEGIN` the loser gets `database
  is locked`. → **Forced: item 5 — `IMMEDIATE` on an acquisition that saw no holder, so the loser
  reads the holder and refuses `IndexerBusyError`** (narrowed after round 7).
- *Writers queued when the writer closes.* Nothing ran. → **Forced: they answer `store_busy`, not
  `internal_error`.**

**Added after review round 7:**
- *A writer queued on a closed handle, and where its `store_busy` is minted.* The primitive has no
  `verb`, and a constructed driver error would falsify `is_contention`'s contract. → **Forced: a
  dedicated `WriterClosedError`, answered at the two dispatch sites that hold the method name.**
- *A second build arriving during the winner's index phase rather than its acquisition.* Under
  `IMMEDIATE` on every acquisition it would wait out an indexer transaction, and past 5 s answer
  `database is locked`. → **Forced: today's fast read outside a transaction refuses a live holder
  at once, and `IMMEDIATE` opens only from *no holder*.**
- *The cold-load test's probe writer.* `remember` embeds before its transaction, so it waits on the
  same load in both arms, and the test would pass with the fix reverted. → **Forced: the probe is
  `memory_fetch`, which writes without embedding.**
- *A non-contention failure in a `surface` past its deadline.* It keeps its own code, so a defect is
  never reported as lateness; it commits nothing either way. Holds.

**Added after review round 9:**
- *A build that fails after `scan.run` has returned* — the corpus close, or `observe`'s reads —
  with the row already latched `ok=true`. → **Forced: stated and accepted. The row describes the
  scan, which committed, and the exit status reports the failure. A fourth tested path.**
- *A `surface` whose lease wait expires at its deadline.* → **Forced: that expiry answers
  `deadline_passed`, not `store_busy`.**

**Added after review round 10:**
- *A retried read holding SQLite's write lock while other reads reach their event insert.* They are
  refused at once and retry behind it. Bounded by the pool's size times one read pass; no cycle.
  → **Forced: the retry's stated cost names the convoy, and the probe's per-attempt count shows
  it.**
- *A `surface` whose embed outlasts its deadline.* Without a check before `BEGIN` it would lease,
  run both arms and insert, only for the pre-`COMMIT` check to roll it back. → **Forced: a check
  point after the embed.**
- *A returned lease whose connection `finalize` closed.* Restoring its pragma would raise
  `ValueError`. → **Forced: dropped without the restore.**

**Added after review round 11:**
- *A `TimeoutError` from the connect phase, after the hook gains its post-send timeout catch*:
  `health()` on a listener that accepts and never answers — a blocked loop's `hook.log` signature.
  → **Forced: the catch is scoped to `surface_once`, so this stays `transport`, with a test that
  widening the catch fails.**
- *The access log's next `record` after a failed rollback closed its handle.* The universal
  pre-statement check raises `WriterClosedError` into the same `except Exception` branch, and the
  row is dropped as before. Holds; its comments are renamed.

**Added after review round 12:**
- *A push against a service whose loop is alive but whose `surface` handler never answers.*
  `health()` answers inside `connect_once`, and `surface_once` times out. It is logged under the new
  post-send kind, `unanswered`, not `transport`; `service.log`'s long-request line separates it
  from a slow embed. → **Forced: `hook.log` gains `unanswered`. `deadline_exceeded` stays the
  pre-send case alone, so each kind names one population.**
- *A `deadline_passed` answered while the writer holds its lock.* Its `call` row drops, but the
  hook still receives and logs the answer. → **Forced: `hook.log`'s `deadline_passed` lines are
  named as the complete count of delivered refusals.** ~~The access log's count as a floor on it.~~
  Corrected after round 13: the two counts are different populations, with no floor either way. A
  cold-load check-point-2 refusal lands its row and reaches a hook that has gone.

**Added after review round 13:**
- *A wedge that holds the writer, or has pinned every pool lease, seen from the push hook.*
  ~~Every later push is refused at check point 3 (or 1), delivered in time.~~ Corrected after round
  14: a held writer's pushes are answered at deadline − margin by the retry's own refusal —
  `deadline_passed` when that answer wins the margin race, `unanswered` when it loses — with the
  `call` row dropped either way. A pinned pool is answered at its lease wait with check point 1's
  code (after round 15), and its `call` row lands.
  `service.log`'s long-request line names the holder. → **Forced: the brief and the README row
  describe each wedge by its `hook.log` signature, and by whether `call` rows stand behind it.**

**Added after review round 14:**
- *A writer whose connection-lock wait expires, and where its `store_busy` is minted.* It expires as
  `asyncio.TimeoutError`, which no failure map takes, so it would answer `internal_error`. The same
  holds for a planning lease. → **Forced: `LockWaitExpired`, sharing one base with
  `WriterClosedError`, answered `store_busy` at the dispatch sites; the writer-budget test passes
  whichever side of the budget refuses.**

**Added after review round 15:**
- *A `surface` whose lease wait expires, seen from the dispatcher's catch.* `LockWaitExpired` lands
  in the catch that answers `store_busy`, a retryable code to a caller that has gone. → **Forced: a
  request carrying `deadline_at_ms` past its deadline less the margin answers `deadline_passed`
  there, with a pinned-pool property whose revert answers `store_busy`.** (Refined after round 16:
  decided by which bound cut the wait, not by a clock read.)

**Added after review round 16:**
- *A deadline-bounded wait — the retry's `BEGIN IMMEDIATE`, or a `surface`'s lease wait — whose
  refusal lands a fraction of a millisecond before the clock's copy of the deadline.* The pragma and
  the timer take whole milliseconds, so a second clock read would answer `store_busy` on a share of
  runs, and the held-writer property runs that race every time. → **Forced: `deadline_passed` is
  decided by which bound cut the wait, never by re-reading the clock; `LockWaitExpired` records the
  bound.**
- *A handler holding the writer's asyncio lock, hung before its `BEGIN IMMEDIATE`.* It holds no
  SQLite lock, so pushes commit normally while every write answers `store_busy` at one budget.
  → **Forced: the README row names this healthy-looking wedge.**

## The walk repeated against the implementation

Each cell above was re-read against the code as built. They hold as stated, with these specifics:

- *Cancelled while waiting on the connection lock.* `ConnectionHolder.acquire` raises before the
  primitive's `try`, so nothing releases a lock that was never taken, and no `await` separates the
  lock's acquisition from recording the owner. Holds.
- *`merge` and `promote` embedding.* Both `prepare` — embed — before `in_one_transaction`, so the
  only serve that embeds under the write lock is `next_group`'s, which waits for the model. Holds.
- *The pool closed at shutdown under a live lease.* `ReadPool.close` closes the idle connections at
  once and a leased one when its lease returns, so the handler's remaining statements run on an open
  connection rather than raising. Stricter than the cell above. Holds.
- *A statement on the writer outside the primitive.* Swept by reading every handler's path: the three
  knowledge sites now go through `registry.lookup`, `lookup_each` and `lookup_all`, each a transaction
  covering the registry statements alone; no other handler issues one. Holds.
- *A knowledge write with two transactions on the writer* — `add` and `remove` each run a registry
  transaction and then a second. Each waits at most one budget, so the MCP client's 10 s request
  timeout is exceeded only when both wait nearly the whole budget and then both succeed.
  → **Stated in `REQUEST_TIMEOUT_SECONDS`'s derivation** rather than bounded per request: the brief
  sets the budget per transaction, and a first transaction refused at its budget ends the request.
- *Invariant 6's concurrent-cycle acceptance test.* It synchronized two writers so both read an
  edgeless graph before either wrote. Under `BEGIN IMMEDIATE` the second cannot read until the first
  commits, so the barrier deadlocked. → **The test now asserts the serialized outcome**: one edge
  commits and the other attempt is refused `bad_supersession` by its own validation.
