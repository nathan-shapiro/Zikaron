# Review — `design/build-plan.md` §M35 brief

Artifact: `design/build-plan.md` §"M35 — One connection shared by every request, a plan that holds
the writer, and a wedge nobody can see into" (lines 4541–4703 at time of review), plus the walk in
`reviews/m35-brief-perturbation.md`.

## Round 1 — 2026-09-29

### Summary judgment

The diagnosis is correct against the code — every claim in §"What is wrong" checks out
(`server.py:187` hands one connection to every handler; `planning.py:87–94` inserts the run row
before `grouping.plan`; `memory.py:481` and `:955` are raw `BEGIN`s with no failure map;
`transactions.py:144–148` closes on a failed rollback) — and the shape (serialized writer, pooled
reads, `IMMEDIATE` writes, compute-then-revalidate planning) is the right one and is deadlock-free
under the no-hold-and-wait rule as long as every `BEGIN` goes through the primitive. Three things
stop it being what an implementation should be held to: item 3's fingerprint covers only the
journal half of the plan's input and so does not re-validate what it claims to; item 5 cannot be
done as written (the payload it moves does not exist until after the lock is released) and omits
the failure row, which leaves the property it is for still false; and item 2 silently reverses a
rule three normative sections state ("the table is created on first use by the registry") without
listing any of them as changing. The rest is improvements to the walk and to implementer clarity.

### Findings

1. **[BLOCKER] Item 3's fingerprint re-validates half of the plan's input.**
   `design/build-plan.md` §M35 item 3: *"re-derives a fingerprint of the plan's input: the active
   journal rows' `(rowid, version)`"*. `grouping.plan` (`grouping.py:341–383`) reads two sets: the
   active journal (`journal_entries`, `Consumer.ORPHAN`) **and the active long-term tier**
   (`anchor_for` → `Consumer.CONSOLIDATION` = `tier='long_term' AND active=1`, `grouping.py:164`).
   A journal-only fingerprint does not move when a long-term row is retired, merged into, or
   amended between the snapshot and the write — by the agent's `retire`, or by a second
   consolidator's `merge`/`promote` — so the write transaction commits `anchor_uuid`s the store no
   longer holds as targetable, and misses anchors a concurrent `promote` just created. Before M35
   that state was unreachable, because the plan and its write shared one transaction; after it,
   `consolidation.md:222`'s definition of `anchor_vacated` ("*stopped being* `long_term AND
   active=1`") is applied to anchors that never were. Serve-time re-validation makes it non-fatal,
   which is exactly why nothing would fail loudly.
   **Edit:** fingerprint every `active=1` row, both tiers — `SELECT rowid, version FROM memory
   WHERE active=1` is one indexed scan and closes both cases — and say so: *"the fingerprint is the
   `(rowid, version)` of every active row, journal and long-term, because the plan reads both
   tiers."* Add the cell *"long-term writes during a plan"* to the perturbation table with that as
   its forced requirement.

2. **[BLOCKER] Item 5 is not implementable as written, and half of what it promises is not in it.**
   `design/build-plan.md` §M35 item 5: *"The indexer writes its `knowledge_build` row before it
   releases the corpus lock."* The success row's payload is `log.succeeded(refreshed.result)`
   (`indexer/main.py:128`), built from `ScanResult`, which `scan.run` returns only after its own
   `finally: await _release(db)` (`scan.py:419–421`). The failure row (`log.failed`,
   `indexer/main.py:124–126`) is likewise written after that `finally` has run. So the row cannot
   simply be "written before release" — either `scan.run` grows a completion hook invoked before
   `_release` (for **both** rows; `core/knowledge` cannot import `knowledge/indexer/build_log`, so
   it is a callback parameter), or `_release` is hoisted out of `scan.run` into the indexer's own
   `finally`, which must then run before `KnowledgeDatabase`'s `async with` closes the connection
   (`lifecycle.py:313–314`). The brief must name which. And it must move the **failure row** too:
   with only the success row moved, `refresh --wait` on a build that fails returns before its row
   lands, which is the same falsity the item exists to remove.
   **Edit:** (a) state the mechanism (callback into `scan.run`, run before `_release`, on the
   success and the failure path alike); (b) state the narrower thing it buys — *"a build's
   `knowledge_build` row is visible when `--wait` returns"* — since the indexer process still
   outlives the release by its report and store close, so *"no indexer is running"* is not what
   this makes true; (c) note that refusals raised before the lock is taken (`IndexerBusyError`,
   `CorpusRootMissingError`, dangling; `indexer/main.py:115–117`) keep writing their row with no
   lock held, unchanged; (d) note the cost: the row is best-effort on a 5 s `busy_timeout` against
   `memory.db`, so the corpus lock is now held up to 5 s longer while the service's writer is busy,
   and `--wait`'s poll sees the lock for that long.

3. **[BLOCKER] Item 2 reverses a rule three normative sections state, and lists none of them.**
   `design/build-plan.md` §M35 item 2: *"A read verb never creates the knowledge registry table
   … only a write verb creates it."* Today every knowledge read creates it (`reporting.py:410,
   433`, `groups.py:420`, `builds.py:162` all call `registry.ensure`), and the design says so as a
   rule: `schema.md` §"Additive tables and the version gate" (*"created **on first use by the
   knowledge registry** … for every store alike"*), `schema.md` §"`call` is an access log" (*"The
   first knowledge verb on a fresh store **creates** it, and for that one call sits with the memory
   verbs"*), and `knowledge-index.md` §3.1a (*"created by the registry's own open, once per store"*).
   The change is right — a presence-read-then-`CREATE` on a pool connection is the CI failure's
   shape on the read path — but the brief's "Normative after this milestone" list names only
   `architecture.md` and `retrieval.md`. Also, "only a write verb" excludes the indexer, which
   keeps its own creation site (`indexer/main.py:106`, with its stated reason).
   **Edit:** add both `schema.md` sections and `knowledge-index.md` §3.1a to the normative-after
   list, and state the replacement rule once: *"created by the first write verb (`knowledge_add`)
   or by the indexer, always under `IMMEDIATE`; a read on a store without it answers as if the
   registry were empty (`list`/`search` → none; `status name=x`/`unlock` →
   `knowledge_base_unknown`)."* The `call`-is-an-access-log bullet simplifies as a result — the
   five read verbs' `call` row is now their only `memory.db` write on **every** store — say that
   rather than leaving the "on a store whose registry table exists" precondition standing.

4. **[IMPROVEMENT] The "no two transactions nest" property is structural only if every `BEGIN` goes
   through the primitive; the brief moves two of four raw ones.** `records/memory.py` has raw
   `BEGIN`s at `:400` (`create`), `:481` (`fetch`), `:875` (`amend`) and `:955` (`retire`). The brief
   moves `fetch` and `retire`. `create` and `amend` have no production caller (both verbs reach the
   store through `indexing.writes`' primitive-owning wrappers), but they are public, callable from
   tests, and a raw `BEGIN` on the writer bypasses the lock item 1 introduces — the exact latent
   nesting path the property says cannot exist. (`store.py:339` and `migration.py:154` run before
   the socket exists and are fine.)
   **Edit:** require that after M35 the only `BEGIN` issued on a service connection is the
   primitive's — delete or move `create`/`amend`'s raw wrappers — and add a guard test that greps
   the package for `execute("BEGIN` outside `transactions.py`, `store.py` and `migration.py`, in
   the style of the existing drift guards.

5. **[IMPROVEMENT] Same-task re-entrancy turns a defect into five seconds of stall and a retryable
   code.** Today a transaction-owning function called from inside another transaction on the same
   connection fails at once with `OperationalError: cannot start a transaction within a
   transaction` (`memory.py:398` documents this as the contract). Under item 1 the inner call waits
   on a lock its own task holds, is bounded by `busy_timeout`, and answers `store_busy` — a
   retryable contention code for a programming error, which the client's own retry then repeats.
   **Edit:** the primitive records the owning `asyncio.current_task()`; an acquisition from the
   task that already holds the connection's lock raises immediately (`RuntimeError` →
   `internal_error`), never waits. Add the property *"a same-task nested transaction fails at once,
   not after `busy_timeout`"* and the cell to the perturbation table.

6. **[IMPROVEMENT] The perturbation cell "read upgrading, another writer committed since its
   snapshot — holds, unchanged" is not unchanged, and the staleness probe cannot see the change.**
   `reviews/m35-brief-perturbation.md` §"Between read and write", second bullet. Before M35 an
   in-process write could never stale an in-process read's snapshot — there was one connection, and
   the two collided as a nested `BEGIN` instead. After M35 every `search`/`surface` whose window
   overlaps a `remember`/`amend`/`merge`/`promote`/**`fetch`** commit (fetch is now a writer that
   commits receipts on every call) answers `store_busy` at its event insert. `retrieval.md` made
   that trade against *another process*; this is new traffic on it, and on the push path it is a
   skipped injection. The probe's phase A exercises `plan_groups` only, which item 3 turns into a
   pure read — so "no failed search during a plan" passes trivially and says nothing about this.
   **Edit:** mark the cell *changed* (new source: the in-process writer); extend the re-run with a
   phase that drives `next_group` + `merge` traffic against concurrent `search`/`surface`; and add
   to done-when a one-off measurement, no bar (consistent with the brief's own rule): the
   `store_busy` refusal rate on `memory_search`/`memory_surface` during that phase, from
   `experiments/m33_call_log_queries.py`'s refusal-by-code query. Name the fix that is *not* in
   scope — a server-side single retry of the whole read transaction on `SQLITE_BUSY_SNAPSHOT`,
   which is idempotent up to its event — so it is not re-derived per round.

7. **[IMPROVEMENT] Queued writers hold a reference to a connection `finalize` has closed.** Item 1:
   *"A connection the primitive has closed is never handed out again."* The dispatcher hands
   `ctx.store.connection` at dispatch time (`server.py:187`); a write handler already queued on the
   writer lock behind the transaction whose rollback failed will, on acquiring, run `BEGIN` on the
   closed handle — `ValueError`, not `aiosqlite.Error` (`dispatch_knowledge.py:539`) — and answer
   `internal_error`. The property "the next request succeeds" is consistent with that but the walk's
   cell (§"Mid-commit", second bullet) does not name the queued ones.
   **Edit:** either accept it in one sentence ("requests already queued on the writer fail
   `internal_error` on that path; requests dispatched after it succeed") or have the primitive
   resolve the writer *after* acquiring the lock (a provider, not a handle — which "the lock is
   taken at the transaction" already permits). Add the cell either way.

8. **[IMPROVEMENT] `SIGUSR1`/`SIGUSR2` default to *terminate*; install both before the bind, and
   amend the sentence that lists what is deliberately uncaught.** `architecture.md` §"Idle
   self-stop" (`:826–833`) gives the ordering argument for `SIGTERM`/`SIGINT` — a signal before the
   handlers go on kills the process and leaves the socket file — and names *"any other signal left
   at its default disposition (`SIGHUP` and `SIGQUIT` are catchable and deliberately uncaught)"*. A
   `USR1` sent while the service is still assembling is the moment an operator diagnosing a slow
   start would send one. Also say that `faulthandler.register(SIGUSR1, file=…)` writes raw,
   untimestamped text through the `FileHandler`'s own stream fd (`log.py:33`), bypassing `logging`
   — so the implementation reaches that stream rather than opening a second fd on the file, and a
   reader of `service.log` knows why the dump has no `pid=` prefix.
   **Edit:** item 4 gains *"both handlers are installed with the `SIGTERM`/`SIGINT` pair, before
   `serve()`"*; the normative-after list names §"Idle self-stop"'s uncaught-signal sentence as
   changing.

9. **[IMPROVEMENT] The `SIGUSR2` in-flight table is complementary to a per-request line, not a
   replacement — and the wedge that motivates it was diagnosed after the fact, with nobody present.**
   Item 4: *"The in-flight table replaces the per-request start line §"Owed work" proposed."* Two
   limits. If the loop is blocked, `loop.add_signal_handler`'s callback never runs, so `USR2` shows
   nothing — only `USR1` works, and it dumps *thread* stacks, which for an idle loop with a stuck
   coroutine is the wrong picture; the case `USR2` serves is exactly the one a start line without
   its end line would have shown post-mortem. And the 2026-09-29 wedge was found eleven minutes in,
   restarted, and then diagnosed from logs; a dump needs an operator at the terminal while it is
   live.
   **Edit (for the operator's decision, not this reviewer's):** keep the `USR2` table, and make the
   wedge self-reporting at zero steady-state cost: `lifecycle.idle_self_stop` already wakes every
   30 s (`lifecycle.py:102`) and `ActivityTracker` already counts `in_flight`; give the tracker the
   in-flight registry `USR2` needs anyway, and have the poll log one `INFO` line for any request
   older than the poll interval (method, session, age) — no line per request, and a wedge names
   itself in `service.log` before anyone is asked to send a signal.

10. **[IMPROVEMENT] Item 3 leaves two things open that decide its cost.** (a) On a fingerprint
    mismatch, *"it plans again"* — on which connection? Replanning while holding the writer *is* the
    fallback; the no-hold-and-wait rule forbids waiting for a pool lease while the writer is held.
    Say: *"roll back, release the writer, replan on a fresh pool snapshot, retake the writer."*
    (b) *"a bounded number of attempts … the implementation states [the bound]"* — the bound
    multiplies the planning ceiling. `consolidator.py:57` derives *"roughly 7,000 rows"* from one
    plan per `_PLANNING_TIMEOUT_SECONDS`; with N attempts plus the fallback the journal that fits
    is ~7,000/(N+1), and `architecture.md` §Planning (`:1523`) carries the same arithmetic. Fix the
    bound in the brief (one replan, then fallback — the smallest that makes re-validation mean
    anything) and require both restatements.

11. **[IMPROVEMENT] `next_group`'s inline replan needs one more sentence against
    `architecture.md` §Serving's atomicity requirement.** `serving.py:76–80` and the section it
    cites: *"an implicit replan and the serve that follows it have to be one atomic step."* Under
    item 3 the verb becomes: short writer transaction (is there an effectively-active run?) → if
    none, release, plan on a pool snapshot → one `IMMEDIATE` transaction that re-checks the run,
    re-checks the fingerprint, writes the plan **and serves**. That is consistent with the
    requirement, but *"uses the same path"* does not say it, and the write-side re-check has a new
    branch: a stranger's run created between the snapshot and the write is answered `Busy` — never
    replanned, since `next_group` never takes over. State both.

12. **[IMPROVEMENT] The writer "reopened" contradicts `Store` as built, and the naive reading is
    wrong.** `Store._db` is `Final` (`store.py:235`) and `connection` returns it. The reopen must be
    a connection-level reopen — `open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)`
    — not `Store.open(migrate=True)` (no re-validation; the schema moved at startup), and
    `opened_inode` stays the startup baseline, since the inode-drift poll (`lifecycle.py:108`)
    compares against the original file: a reopen after a replacement opens the new file, and the
    poll then stops the service, which is correct. Say it, and that `Store` gains the one method
    that does it.

13. **[IMPROVEMENT] Four comments and one docstring describe the pre-M35 mechanism and will be
    false the day item 1 lands** — `CLAUDE.md`'s "grep the claim" rule, applied in advance.
    `scan.py:176–179` (*"Closing it would mean a `BEGIN IMMEDIATE` variant of the shared
    transaction primitive"* — the variant now exists; the brief scopes `IMMEDIATE` to `memory.db`
    and should say whether the corpus lock acquisition adopts it or declines, one line);
    `lock.py:196–199` (same claim); `build_log.py:164–166` (the fresh-transaction/`BUSY_SNAPSHOT`
    rationale, moot under `IMMEDIATE`); `dispatch_knowledge.py:553–557` (*"arrives as
    `SQLITE_BUSY_SNAPSHOT` … because `registry.ensure_table` opens the transaction with a presence
    read"*); `server.py:8–15` (the concurrency note). Add them to done-when as edits, not as a
    count.

14. **[IMPROVEMENT] The classification rule's wording makes `search` a write, and the set is not
    stated.** Item 2: *"a write if it can write `memory.db` outside its audit events."* In this
    corpus "audit events" are invariant 10's rejection carve-out; `search`, `surface_call` and
    `surface` are **semantic** events (`schema.md` kind table, `:170`), so `search` writes
    `memory.db` outside its audit events and the rule as written classifies it a write. Reword:
    *"other than the event rows it emits about itself."* And list the set once — sixteen enveloped
    methods; the edge cases are `memory_fetch` (receipts → write), `knowledge_refresh`
    (`builds.plan` reads, spawns → read), `knowledge_unlock` (corpus database only → read), the
    three registry verbs and five consolidator methods (write) — because the property *"for every
    write verb"* needs the set to be checkable, and "beside its handler in the method table" is
    where the code says it, not where the brief does.

15. **[IMPROVEMENT] Pool exhaustion has one realistic cause and the walk does not name it.**
    A read leases for its handler's span, and `search`/`surface` embed *before* their transaction
    (`reads.py:152–158`, `to_thread`), as does `knowledge_search`. Across a cold model load — the
    seconds `architecture.md` §"The model loads behind the socket" is about — the first N reads
    after an idle gap each pin a pool connection while all wait on one load; the (N+1)th waits
    `busy_timeout` and answers `store_busy`. Bounded by the pool covering the client count, but
    the cell *"Pool exhausted"* in the walk names no cause.
    **Edit:** name it; and either lease at the transaction rather than at dispatch (the pool then
    holds only connections inside SQLite, matching "the lock is taken at the transaction" for
    writes) or say why the handler-span lease is kept (the knowledge verbs run several transactions
    and open corpus databases between them).

16. **[NITPICK] `reason=signal` separates a kill from a wedge in one direction only.** A wedged
    loop never runs the `SIGTERM` callback either, so a wedged service still logs nothing and is
    then `SIGKILL`ed, which logs nothing — the log reads as it did on 2026-09-29. What the line
    buys is that a service which *did* log it was not wedged. Say so, and name the signal
    (`reason=sigterm` / `sigint`) — one word.

17. **[NITPICK] Scope fence omissions.** `BUSY_TIMEOUT_MS` itself — the brief makes it the bound
    for two new waits, and raising it is the first thing a red test invites; the corpus databases'
    transaction mode (finding 13); a server-side read retry on `SQLITE_BUSY_SNAPSHOT` (finding 6).
    One sentence each, in or out.

18. **[NITPICK] Property 1's test must release inside `busy_timeout`.** *"holds one request's
    write transaction open and issues concurrent reads and writes, all of which succeed"* — the
    writes succeed only if the held transaction ends within `busy_timeout`; past it they correctly
    answer `store_busy` and the test is then testing property 6. Say the hold is short.

19. **[NITPICK] `(operator, 2026-09-30)` in §"Done when" is dated tomorrow.** Today is
    2026-09-29 and every other date in the section is on or before it.

### Perturbation walk — cells missing from `reviews/m35-brief-perturbation.md`

Named here once so the implementation's re-walk starts from the full set: same-task re-entrancy
(finding 5); long-term-tier writes during a plan (finding 1); writers queued behind a failed-rollback
close (finding 7); `next_group` finding a stranger's run between its snapshot and its write
(finding 11); cold-load pool exhaustion (finding 15); a handler cancelled while holding the writer
mid-statement — the statement completes on the worker thread, the `finally` rollback queues behind
it, and the lock is held for one statement plus at most `busy_timeout` (holds; worth the line). The
cell marked "holds, unchanged" for a read's snapshot upgrade is changed (finding 6).

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-29

### Summary judgment

Every round-1 finding is applied and the resolutions hold up against the code: the two-tier
fingerprint is sufficient (every consolidator write bumps `version` or clears `active` —
`apply_rewrite`, `apply_retirement`, `apply_tier` in `verbs.py`), the zero-replan bound with the
halved ceiling is consistent with `_PLANNING_TIMEOUT_SECONDS` covering both `plan_groups` and
`next_group` (`mcp/consolidator.py:149,270`), the retry is idempotent (`surface`'s only in-process
state is the constant `PREAMBLE_DIGEST`), and the lease-order argument is deadlock-free as stated.
What remains is one specification gap that would ship a data defect if implemented as written —
item 5 adds a second writer of the `knowledge_build` row without retiring the first, and the
property as phrased does not catch a double row — plus a retry whose trigger the code cannot
currently express (`is_contention` folds `SQLITE_BUSY_SNAPSHOT` into `SQLITE_BUSY` by design), and a
residual on the shared writer the walk has no cell for.

### Findings

1. **[BLOCKER] Item 5 leaves both of `main.build`'s row writes in place and adds a third, so a
   post-lock failure is recorded twice and every success is recorded twice.**
   `design/build-plan.md` §M35 item 5: *"`scan.run` takes a completion callback and invokes it
   before `_release`, on the success path and the failure path alike … The indexer passes one that
   writes the row."* `knowledge/indexer/main.py:124–128` still runs `await log.failed(error)` in
   its `except` and `await log.succeeded(refreshed.result)` after it, and the brief keeps the catch
   (*"Refusals raised before the lock is taken … keep writing their row with no lock held,
   unchanged"*). Nothing says the catch must skip a failure the callback already wrote, or that the
   success call goes. `experiments/m33_call_log_queries.py`'s `_BUILD_HISTORY` sums `duration_ms`
   per corpus, so a doubled row doubles what every build "cost". The stated property — *"committed
   before its corpus lock is released"* — passes with two rows, since the first one is. A second
   hazard rides on the same mechanism: `main.py:86–91` places `succeeded` after the `try` because
   its payload is built *outside* `_write`'s guard, and a failure there inside the `try` would enter
   the catch and write `ok=false` for a completed build; the callback now runs inside `scan.run`'s
   own `try`, so that exact path is reopened unless the callback is guarded whole.
   **Edit:** (a) state the property as *"exactly one `knowledge_build` row per build — before the
   lock's release when the lock was taken, after the refusal otherwise"*, and test the count on all
   three paths (success, post-lock failure, pre-lock refusal); (b) `BuildLog` writes at most once —
   one latch shared by the callback and `main.build`'s two call sites, which become no-ops once it
   has fired; (c) the callback never raises: payload construction moves inside `_write`'s guard,
   or the callback catches `Exception` around the whole of `succeeded`/`failed`.

2. **[IMPROVEMENT] The retry's trigger is a predicate the code does not have, and the one it has
   fires on the case that must not retry.** Item 2: *"a `memory_search` or `memory_surface`
   transaction refused `SQLITE_BUSY_SNAPSHOT` is retried once"*. `transactions.is_contention`
   (`:69–78`) masks to the **primary** code deliberately, and `architecture.md`'s `store_busy` row
   (`:2003`) states the same rule — so by the time `reads._failure_map` has produced a
   `ZikaronError`, stale-snapshot and waited-out-lock are indistinguishable. An implementer who
   retries on `store_busy` (the obvious reading of `is_contention`'s own docstring: *"contention by
   every meaning that matters"*) makes a `memory_search` under a held write lock wait
   2 × `busy_timeout` = 10 s and retry a condition that will fail again; the retry is only sound
   because a stale snapshot fails at once and a fresh one usually lands.
   **Edit:** name the predicate — a new `is_stale_snapshot` on the **extended** code
   `sqlite3.SQLITE_BUSY_SNAPSHOT`, beside `is_contention`, never a reuse of it — and where the retry
   sits: around `in_one_transaction` in `reads.search`/`surface`, where the driver error is still
   in hand (a retry placed at dispatch sees only the wire code). Add the negative test to the
   property: *a read that waited out `busy_timeout` answers `store_busy` after one attempt*. The
   `store_busy` row, already listed as changing, should say the retry's trigger is narrower than
   the code's own classification.

3. **[IMPROVEMENT] A write handler's statements outside the primitive run inside whatever
   transaction another handler holds on the writer, and the walk has no cell for it.** After M35
   write handlers share the writer *between* transactions. Three knowledge writes issue autocommit
   registry reads on it: `dispatch_knowledge.knowledge_add` calls `builds.plan(db)` after
   `lifecycle.add`'s transaction (`builds.py:162–166`: `registry.ensure` then `require`);
   `lifecycle.remove` runs `registry.ensure(db)` and `registry.require(db, name)` before its
   transaction (`lifecycle.py:382–383`); `_what_would_be_destroyed` reaches `reporting.status(db)`
   → `require` (`reporting.py:433–434`). With `isolation_level=None` a statement issued while
   another task's `BEGIN IMMEDIATE` is open on the same connection executes inside that transaction
   — it does not wait, and it reads uncommitted registry rows. The "no two transactions nest"
   property is true and this is not nesting; it is a phantom read on a write path, with a
   `remove` preview describing a corpus an `add` may roll back. Bounded, but unstated. Separately,
   `builds.plan`'s `ensure` is reached from `knowledge_refresh` (a read on a pool connection) and
   must go under item 2's rule.
   **Edit, one of:** (a) the rule *"every statement on the writer goes through the primitive"*,
   made structural rather than grepped — the writer is handed to handlers as a guarded connection
   whose `execute` outside a held lock raises, which is the same per-connection object finding 4
   needs anyway — and the three reads move into short primitive transactions or onto a pool lease
   (`knowledge_add`'s `builds.plan` can lease exactly as planning does); or (b) accept it in one
   sentence naming the three sites and add the cell to the walk. Under either, delete `ensure` from
   `builds.plan`.

4. **[IMPROVEMENT] Where the per-connection lock, the owning task and the closed flag live is
   unstated, and "never handed out again" depends on it.** Item 1 requires three facts per
   connection — its lock, the task holding it (re-entrancy), and whether `finalize` closed it —
   and `finalize` closes silently under `contextlib.suppress` (`transactions.py:147–148`), after
   which the next `BEGIN` raises `ValueError`, not `aiosqlite.Error`. A `WeakKeyDictionary[Connection,
   Lock]` gives the lock a home and the other two none, and the pool then has nothing to check
   before handing a connection out.
   **Edit:** name the object — a pool entry / guarded writer that owns all three — state that
   `finalize` marks it closed rather than only closing the handle, and that the pool and the
   writer's reopen consult that mark. Merges with finding 3(a) if that route is taken.

5. **[IMPROVEMENT] `next_group` step 3's re-check has three outcomes and the brief states two.**
   Item 3: *"A stranger's run created between the snapshot and that transaction is answered
   `Busy`, never replanned."* The third case is the caller's **own** run created in the window — a
   second `next_group` from the same `(session_id, pid)` that planned concurrently and wrote first.
   `architecture.md` §"Consolidation lifecycle"'s harness delta already names the shape (one shared
   MCP process per Claude Code session), and today's `_run_for` (`serving.py:366–375`) answers it by
   serving from the existing run. Step 3 should say: *own run → discard the computed plan and serve
   from it*. Also *"A short writer transaction asks whether an effectively-active run exists. If
   one does, it serves as today"* — the serve branch embeds inside that transaction and is not
   short; say "short when it finds none".

6. **[IMPROVEMENT] The plan property's test is timing-dependent as written, because the
   `remember` it issues is what triggers the window in which the `search` fails.** *"during a
   plan, `remember`, `search` and a knowledge write all succeed"* — the `remember` moves the
   fingerprint, so the write transaction replans inline and holds SQLite's write lock for a second
   full plan; a `search` whose event upgrade begins more than `busy_timeout` before that window
   ends answers `store_busy` (primary `SQLITE_BUSY`, which finding 2 correctly leaves unretried).
   Issued during the snapshot phase the three succeed; issued after the fallback has begun, the
   search does not. The staleness probe's phase A drives no writes, so its re-run is unaffected
   and still discriminates (a plan that always fell back would fail its searches).
   **Edit:** state the window the property asserts over — the snapshot phase — and that the
   fallback window is the accepted pre-M35 cost, paid only when a memory row moved. For the
   re-validation property, assert the **outcome** (the run's members include the row that landed;
   the retired anchor is no group's anchor) rather than only that the fallback ran — that is what
   fails if re-validation is reverted, and it does not depend on observing a mechanism.

7. **[NITPICK] Invariant 2's reading should be stated, since `next_group` becomes up to three
   transactions.** `schema.md` invariant 2 (`:1582`) is worded over *"every logical mutation"*, so
   the brief's claim holds — the mutation is the one `IMMEDIATE` transaction; step 1 and the
   snapshot mutate nothing — but `planning.plan_groups`'s docstring (*"in one transaction"*),
   `serving.next_group`'s (*"One transaction covering …"*) and `architecture.md` §Planning all say
   one transaction per verb and are on the rewrite list. One sentence under the invariants bullet.

8. **[NITPICK] The bound for the two new waits is the constant, not each connection's pragma.**
   *"Waiting for the connection lock is bounded by `busy_timeout`"* — the access log's connection
   carries `PRAGMA busy_timeout = 0` (`ddl.ACCESS_LOG_PRAGMAS`), and its transactions now go
   through the same primitive. Say `ddl.BUSY_TIMEOUT_MS`.

9. **[NITPICK] Pool: eager or lazy, and "chosen to cover that case" is per session.** If the pool
   opens at startup it adds N × (connect + `sqlite-vec` load + pragmas) to the bind latency
   §"The model loads behind the socket" budgets against the hook's deadline; if lazily, the first
   read pays it. Say which. And the client census is one session's — a second session's reads
   degrade to the bounded wait during a cold load, which is fine and worth one clause.

10. **[NITPICK] The empty-registry answers omit `refresh`, and `rename`/`remove` are left
    ambiguous.** Item 2 lists `list`/`search`/`status`/`unlock`; add `refresh` (no name → nothing
    to build; `name=x` → `knowledge_base_unknown`). And *"only the first `knowledge_add`, or the
    indexer"* creates the table, but `lifecycle.rename` calls `ensure_table` inside its transaction
    and `remove` calls `ensure` before its own (`lifecycle.py:267,382`); both can answer
    `knowledge_base_unknown` without creating anything. Say they do.

11. **[NITPICK] "Logged once" leaves a `tail` of a long wedge empty.** A single `INFO` line
    thirty seconds into an hour-long wedge is the line most likely to be scrolled past. Re-log at
    each poll while the request is older than `idle_timeout`, or at a geometric cadence — either is
    still zero cost in steady state.

12. **[NITPICK] The refusal-rate measurement needs a window.** `_REFUSALS_BY_CODE` groups the
    whole `event` table, and the probe's earlier phases also write `memory_search` rows on the same
    store copy. Say each arm of the with/without-retry comparison runs on its own copy and the rate
    is over rows with `id >` the phase's first.

### Perturbation walk — cells to add to `reviews/m35-brief-perturbation.md`

A write handler's autocommit statement on the writer while another handler's transaction is open
(finding 3); `next_group` finding its **own** run at step 3 (finding 5); the indexer's completion
callback raising, and a post-lock failure reaching both writers of the row (finding 1); a `search`
arriving during the fallback window rather than the snapshot (finding 6).

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-29

### Summary judgment

The round-2 resolutions hold against the code: the three knowledge-write sites are exactly the
autocommit statements on the writer (`dispatch_knowledge.py:385`, `lifecycle.py:382–384`,
`reporting.py:433–434`), the enveloped set the classification is held to is the nineteen methods in
the three tables and nothing else, `memory` carries an explicit `rowid` for the fingerprint, no
handler spawns a child task that touches `memory.db` (only `service/main.py`'s background tasks
exist), and the access log already serializes its own connection behind `_writing`
(`access_log.py:133`), so the primitive's lock changes nothing there. One thing the brief and the
walk both get wrong: the two new `busy_timeout`-bounded waits **compound** for a queued writer, and
`mcp/connection.py`'s 10 s request timeout was derived from the premise that a write is one
transaction under one `busy_timeout` — so the cell the walk marks *Correct* answers a write with
`AmbiguousMutationError` instead of `store_busy`. The rest is precision the implementer would
otherwise have to guess at.

### Findings

1. **[BLOCKER] A writer queued behind a writer that is itself inside SQLite's busy handler waits
   two `busy_timeout`s, and the client gives up at ten seconds with the one answer it can never
   retry.** `design/build-plan.md` §M35 item 1 (lines 4625–4628): the lock wait is bounded by
   `ddl.BUSY_TIMEOUT_MS`; `BEGIN IMMEDIATE`'s own wait is bounded by the connection's pragma, the
   same 5 s. They are sequential. W1 takes the writer's lock and blocks in the busy handler because
   another *process* holds the write lock (the walk's own cells: an operator's shell, a second
   service, a wedged predecessor mid-transaction); W2 waits up to 5 s for the lock, acquires it as
   W1 gives up, then waits up to 5 s more. `zikaron/mcp/connection.py:52–62` sets
   `REQUEST_TIMEOUT_SECONDS = 10.0` on the stated premise that *"every primary/consolidator RPC
   method but planning is a single such transaction with no other unbounded step … comfortably above
   the 5 s ceiling"*, and its `request` never retries past the first byte sent (`:275–278`): a
   `remember`, `amend`, `fetch` or `apply_merge` that arrives as W2 is reported
   `AmbiguousMutationError`, not `store_busy`. Today W2 fails at once as a nested `BEGIN`, so this
   is new traffic on the client's ceiling. `reviews/m35-brief-perturbation.md:63` (*"Writers answer
   `store_busy` after 5 s. Correct."*) is false for every writer but the first, and the property at
   line 4843 tests the lock wait alone, so the compound passes it.
   **Edit, one of:** (a) *one budget per transaction* — the primitive reads a deadline at entry,
   waits for the lock on the remainder, and on the writer sets `PRAGMA busy_timeout` to what is
   left before `BEGIN IMMEDIATE` (a per-statement pragma the corpus side already does at
   `counters.py:219–227`; safe because the writer's transactions are serialized behind the lock).
   Property: *a writer's total wait, lock plus SQLite, is bounded by one `BUSY_TIMEOUT_MS`*, with
   the test: an external connection holds `BEGIN IMMEDIATE` for 12 s, two writers are dispatched
   together, and the second answers `store_busy` within ~5 s of its dispatch — reverted, it answers
   at ~10 s. Or (b) accept the 2× and raise `REQUEST_TIMEOUT_SECONDS` with its docstring
   re-derived, naming it in the fence, which the docstring's premise otherwise contradicts silently.
   Either way: correct the walk's cell; add `mcp/connection.py:52–62` to the rewrite list at
   4887–4895; and state that a **read**'s lease wait plus its upgrade wait compounds the same way
   and is accepted — it needs pool exhaustion *and* a held write lock at once, and the hook's 2 s
   deadline is already below one `busy_timeout`.

2. **[IMPROVEMENT] The three moved sites contradict item 1's mode rule, and their extent is what
   decides whether the writer is held across corpus opens.** Lines 4589–4591: *"Every transaction
   a write method or the indexer opens against `memory.db` is `BEGIN IMMEDIATE`"*; lines 4611:
   *"Each moves into a short **read** transaction on the writer."* An implementer following the
   first makes them `IMMEDIATE`, the second deferred; both are safe, but the brief must say one.
   The extent matters more: `builds.plan` (`builds.py:162–169`) and `reporting.status`
   (`:433–435`) interleave `require` with `observe`, which opens the corpus database
   (`reporting.py:337`, connect + pragmas + `read_meta`), and `list_bases` observes every corpus
   and then reads every orphan (`:410–413`). Wrapping either call whole — the obvious reading of
   *"`knowledge_add`'s `builds.plan` … moves into a short read transaction"* — holds the writer's
   lock across those opens, and on a pool connection (`knowledge_refresh`, `knowledge_status`) a
   read snapshot across N of them, which is the checkpoint-starving hold the brief's own rule at
   4721–4723 exists to prevent.
   **Edit:** make the rule uniform — *every transaction on the writer is `IMMEDIATE`, read-only
   ones included*, since on a serialized writer an `IMMEDIATE` read costs nothing and the rule
   then needs no per-site judgement — and state the extent: *the transaction covers the registry
   statements (`require`, `list_all`) only; `observe`, `_orphans` and every corpus open stay
   outside it, on the writer and the pool alike*, which means `builds.plan` and `reporting.status`
   read the registry in one transaction and do the corpus work after it. Extend the property at
   4851–4852 with *"and no corpus database is opened inside it."*

3. **[IMPROVEMENT] How the primitive reaches the holder from a bare `aiosqlite.Connection` is
   unstated, and every caller's signature depends on the answer.** Lines 4619–4623 name the holder
   (lock, owning task, closed mark) but `in_one_transaction(db: aiosqlite.Connection, …)` is
   called with a bare handle from the indexer (`build_log.py:175`), the access log
   (`access_log.py:150`), every corpus-database site (`database.py:318`, `scan.py:350,357`) and
   every service caller. Threading a holder through those is the type change the brief declined
   for finding 3(a); subclassing the connection is worse.
   **Edit:** one sentence — *the primitive finds a connection's holder in a module-level registry
   keyed by the connection (a `WeakKeyDictionary`, or an attribute set on the handle), created on
   first use, so no signature moves; the pool and the writer's reopen consult that same registry;
   a connection outside the service gets a holder the same way and its lock is never contended.*

4. **[IMPROVEMENT] Item 5's "made to raise" property cannot be satisfied by the mechanism it sits
   beside, so the test will assert whichever reading the implementer picks.** Lines 4800–4803: the
   callback's whole body, payload construction included, sits inside `_write`'s guard, so it never
   raises. Line 4849–4850: *"A callback made to raise still writes one row and never `ok=false` for
   a completed build."* If the injected failure is in payload construction, the guard swallows it
   and **no** row can be written — there is no payload — so "still writes one row" is false unless
   `main.build`'s post-release `succeeded` (`main.py:128`) is allowed to try again, which depends
   on whether the latch marks an *attempt* or a *committed row*, and the brief does not say. If
   the latch marks a committed row, a build whose row was dropped on contention is retried after
   the release — the ordering item 5 exists to remove, in exactly the failure case.
   **Edit:** state the latch semantics — *the latch is set when the callback runs, so a row that
   is dropped or fails to build is not attempted again after the release; it is best-effort as
   today* — and reword the property to what is testable: *"a failure injected into the callback's
   payload construction leaves the build's exit status unchanged, writes no `ok=false` row, and
   leaves at most one row — never a second attempt after the release."*

5. **[IMPROVEMENT] `knowledge-index.md` §9's `--wait` sentence is the normative claim item 5
   explicitly narrows, and it is not on the list of sections that change.** Lines 4804–4807: *"What
   this buys is narrower than 'no indexer is running'."* `design/knowledge-index.md:2475`:
   *"**`refresh --wait` returns only once no indexer is running against a named corpus**"*, and
   `:2518–2519` (*"a build that fails after detaching is visible as a fact and not as a reason"*)
   is also touched, since the failure row now carries `error_code` when `--wait` returns. The
   normative-after list (4543–4554) names §3.1a only.
   **Edit:** add §9's `--wait` paragraph to the list with the replacement wording: *"returns once
   the build's lock is gone and its `knowledge_build` row has landed; the indexer process may still
   be exiting"* — and let `:2518–2519` say the row names the failure's wire name.

6. **[NITPICK] Step 3's first outcome should say "no *effectively-active* run".** Lines 4757–4762
   list *No run / own run / stranger's run*; `serving._run_for` (`:366–368`) treats a lapsed run as
   absent and `plan_within_transaction` closes it. Write *"no effectively-active run — none, or a
   lapsed one the write closes as today → write the plan and serve"*, so the takeover-by-lease-
   recovery path is visibly inside the first outcome rather than a fourth.

7. **[NITPICK] The in-flight entry exists before its session id does.** Lines 4771–4776: the line
   gives *method, session id and age*, but `ActivityTracker.begin_request` brackets the whole
   dispatch (`server.py:13–15`) and the envelope resolves inside it (`:130`). Say the entry is
   opened at `begin_request` with the method and updated with the session id on resolution, and
   that a request wedged before resolution is logged as `session=unresolved` — the property at
   4855–4856 asserts the line's fields, so the test needs to know which.

8. **[NITPICK] Small completeness items.** (a) The drift guard's pattern (line 4599) should also
   catch `executescript(` and an f-string `BEGIN`, or it is green for the wrong reason. (b) Add to
   the "among them" list at 4887–4895: `registry.ensure_table`'s docstring (`registry.py:118`,
   *"Every knowledge verb calls this first"*) and `registry.ensure`'s (`:149–152`, *"every read that
   merely needs the table to be there"*), both false under item 2; and `main.build`'s placement
   rationale (`main.py:86–91`), moot under item 5. (c) Walk cells to add: the compound wait of
   finding 1; the pool closed at shutdown under a live lease (the handler's next statement raises
   `ValueError` → `internal_error`, inside the quiescence deadline — holds, worth the line).

### Perturbation walk — cells to add to `reviews/m35-brief-perturbation.md`

A writer queued behind a writer blocked in SQLite's busy handler by another process (finding 1 —
the operator-shell cell is wrong as written); a knowledge write's registry transaction and whether
a corpus open falls inside it (finding 2); the pool closed at shutdown under a live lease
(finding 8c).

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-29

### Summary judgment

The round-3 resolutions hold against the code: route (a)'s single budget is implementable exactly as
`counters.py:219–227` already toggles the pragma, the timing property discriminates (≈5 s against
≈10 s) and is reverted by deleting one `PRAGMA`, `IMMEDIATE` on every writer transaction is
consistent with the extent rule, the holder registry needs no signature to move, and the latch-on-run
semantics give the "made to raise" property a single testable reading. `README.md` carries the two
sections and the `--wait` paragraph the done-when names. What remains is precision at four seams the
brief now touches but does not pin: which connections the budgeted pragma reaches (the walk and item
1 disagree about the access log, and the natural implementation reaches it), a normative sentence in
`schema.md` whose stated reason item 1's own mechanism falsifies, the exception class the completion
callback fires on (a `finally` would violate a rule `schema.md` states), and two opens the service now
performs after startup that never compare the inode they get. None is a blocker; each would change
what ships or how it is tested.

### Findings

1. **[IMPROVEMENT] Which connections the budgeted pragma reaches is unstated, the walk and item 1
   disagree about the access log, and the obvious implementation reintroduces M17.**
   `design/build-plan.md` lines 4644–4649: *"On the writer, it then sets `PRAGMA busy_timeout` to the
   remainder before `BEGIN IMMEDIATE`"*. Lines 4593–4595 make `IMMEDIATE` the mode for *"a write
   method or the indexer"*; `reviews/m35-brief-perturbation.md:54–57` says the access log's own
   transaction *becomes* `IMMEDIATE` too. The primitive is called with a bare handle by the access log
   (`access_log.py:150`), the indexer (`build_log.py:175`) and every corpus site, and item 1 gives it
   only a mode to decide by — so an implementer who keys the pragma on `IMMEDIATE` sets
   `busy_timeout` ≈ 5000 on the access log's connection before its `BEGIN`, and the `call` row, which
   sits on the response path (`server.py:147–154`: row attempted, then the line returned), waits up
   to 5 s under contention — the defect `schema.md:888` names as M17. `tests/test_access_log.py:62`'s
   `_NO_WAIT_BOUND_SECONDS` would go red, so it cannot ship silently; but the brief should say the
   mechanism rather than let a red test choose it.
   **Edit:** in the budget paragraph, *"The budget and the pragma apply to the holder `Store`
   registers as its writer. A holder created on first use for a bare handle — the access log, the
   indexer, a corpus database — gets neither: its lock is never contended and its pragma stays what
   it was opened with."* State the access log's mode in item 1 (deferred or `IMMEDIATE`; with
   `busy_timeout` 0 the outcome is the same, dropped at once) and make the walk's cell say the same
   and add *"its pragma is untouched"*.

2. **[IMPROVEMENT] Item 1's toggle contradicts a normative rule whose reason it removes, and that
   section is on the list for a different reason.** `schema.md` §"`call` is an access log", bullet at
   `:949–952`: *"On its own connection, opened with `busy_timeout = 0` rather than toggled. A toggle
   on the shared connection would leave it at zero for whatever other handler's statement ran in that
   window"* — restated at `ddl.py:34–37` and in `AccessLog`'s class docstring (`access_log.py:51–55`).
   Item 1 toggles the shared writer's pragma per transaction and says why it is safe (serialized
   behind the lock, every statement through the primitive). The private connection is still right,
   but for the other reason only: on the writer the row would queue behind the lock for up to
   `BUSY_TIMEOUT_MS`, on the response path. The normative-after entry (lines 4552–4554) names that
   section for item 2 alone.
   **Edit:** widen the entry: *"and its own-connection bullet, whose reason becomes: the row would
   otherwise queue behind the writer's lock on the response path; a toggle under that lock is safe,
   and item 1 relies on it"*. Add `ddl.ACCESS_LOG_PRAGMAS`'s comment and `AccessLog`'s docstring to
   the "among them" list (4928–4939).

3. **[IMPROVEMENT] The completion callback must fire on `Exception`, not in `scan.run`'s `finally`,
   or a cancelled build waits out `busy_timeout` to record its own death.** Lines 4827–4829: *"invokes
   it before `_release`, on the success path and the failure path alike"*. `_release` runs in a
   `finally` (`scan.py:419–420`), so the shortest implementation puts the callback beside it, where it
   also runs on `CancelledError` and `KeyboardInterrupt`. `schema.md:1107–1110` is normative against
   that: *"`Exception` and not `BaseException`, deliberately: a `KeyboardInterrupt` or a
   `CancelledError` must not be made to wait out `busy_timeout` on a lock so that its own death can be
   recorded. Such a build writes no row"* — and `main.build`'s catch (`main.py:93–95`, 124) is
   written to that rule. The row-count property (4887–4891) tests three paths; cancellation is a
   fourth it does not name.
   **Edit:** *"The callback runs for `Exception` only; a `CancelledError` or `KeyboardInterrupt`
   releases the lock and writes no row, as `schema.md` §"…" requires."* Add to the property: *"a build
   cancelled mid-scan leaves zero rows and no lock."*

4. **[IMPROVEMENT] Two opens the service now performs after startup never compare the inode they
   receive, and a replaced store is then served from two files for up to one poll interval.** Lines
   4733–4736 open pool connections lazily; lines 4669–4673 reopen the writer and say *"A reopen after
   the file was replaced therefore opens the new file, and the inode-drift poll then stops the
   service, which is correct."* Before M35 every request ran on the one fd bound at startup, so a
   `memory.db` replaced at its path (deleted and recreated, restored from a backup) was invisible
   until the poll stopped the service. After M35 a pool connection opened lazily inside that window —
   or a writer reopened in it — opens the *new* file while the other connections hold the old inode:
   reads answer from one database and writes land in another for up to
   `IDLE_POLL_INTERVAL_SECONDS`. `open_connection` already returns the inode it opened
   (`access_log.py:87`), so the check is one comparison against `opened_inode`.
   **Edit:** *"Every connection the service opens after startup — a lazy pool open, a replacement, the
   writer's reopen — compares the inode `open_connection` returns with `opened_inode`; on a mismatch
   it is closed and the request answers `store_unavailable`, and the poll stops the service inside
   its interval."* Add the cell to the walk under what a human may change underneath the service.

5. **[IMPROVEMENT] The writer's reopen races with itself, and `Store` as built cannot do it from the
   property the brief keeps.** Lines 4641–4642 and 4666–4675: the mark is consulted *"before a
   connection is handed out"*, but the dispatcher hands out `ctx.store.connection` synchronously
   (`server.py:187`; `store.py:240–247` is a property over a `Final` field), and a reopen is an
   `await`. Two write requests dispatched after the close and before the first reopen completes both
   see the mark and both reopen — two writer connections, one abandoned with a live worker thread,
   which the autouse leak check catches only if a test drives that interleaving. The property at 4884
   dispatches one request.
   **Edit:** *"`_db` loses `Final`; the reopen runs under the store's own lock, once per closure, and
   a dispatch that finds the mark set awaits the reopen in progress rather than starting one."* Test
   with two writes dispatched concurrently after the closure: both succeed, one writer connection,
   no leaked thread.

6. **[IMPROVEMENT] The replacement `--wait` sentence over-promises a best-effort row.** Lines
   4555–4558 make `knowledge-index.md` §9 say *"returns once the build's lock is gone and its
   `knowledge_build` row has landed"*, and 4949 asks `README.md:528–532` to say the same. Item 5's own
   cost bullet (4847–4849) keeps the row best-effort — dropped after 5 s of continuous contention — so
   `--wait` can return with no row and the normative sentence is then false in a document the guards
   quote.
   **Edit:** *"returns once the build's lock is gone — and, since the row is attempted before the
   release, once its `knowledge_build` row has landed or been dropped as best-effort; the indexer
   process may still be exiting."* Same clause in the README paragraph.

7. **[NITPICK] The timing property's test spends 12 s per run for a 2× ratio it could assert in
   about one.** Lines 4880–4883. The primitive reads `ddl.BUSY_TIMEOUT_MS` at entry; a test that
   monkeypatches it to 500 ms and holds the external `BEGIN IMMEDIATE` for 1.2 s asserts the same
   ratio — second writer at ≈0.5 s, reverted ≈1.0 s — and pool pragmas set at open do not matter to a
   writer. Say the test asserts the ratio to the budget, not an absolute, consistent with "no latency
   bar" on a busy host.

### Perturbation walk — cells to add to `reviews/m35-brief-perturbation.md`

The access-log cell corrected for the pragma (finding 1); a build cancelled mid-scan under the
callback (finding 3); the store replaced at its path while a pool connection is opened lazily or the
writer is reopened (finding 4); two writes dispatched into the writer's reopen (finding 5).

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-29

### Summary judgment

Every round-4 resolution is applied as proposed and checks out against the code: the budget and
pragma are scoped to the registered writer with the bare-handle holders untouched (lines 4653–4658),
the access-log bullet's new reason is on the normative-after list (4554–4557), the callback fires on
`Exception` with the `schema.md` rule cited at the heading that carries it (`schema.md:1107–1110`),
every post-startup open compares against `opened_inode` (4681–4685), the reopen runs once under the
store's lock (4686–4689), the `--wait` sentence admits the best-effort row, and the timing test asserts
a ratio. The walk's access-log cell reads correctly as the writer's `IMMEDIATE` making the `call` row
meet a held lock more often, not as the log's own transaction changing mode — the round-4 misreading
is acknowledged and the round-4 cell says so. What stops this round at approval is one premise the
read path is reasoned from in four places and that SQLite does not honour: a connection already
inside a read transaction is **never** put through the busy handler when it asks for the write lock,
so a `search`/`surface` whose event insert meets the writer's held lock is refused at once, not after
`busy_timeout`. That falsifies a walk cell marked *Holds*, a brief bullet, the negative property as
written, the reasoning behind the retry's trigger, and — depending on the retry's mode — the
"no two transactions nest" property's test. Two smaller items follow from it.

### Findings

1. **[BLOCKER] A read's upgrade never waits, and four passages assume it does.** SQLite retries a
   write-lock request through the busy handler only when the requesting connection has **no**
   transaction open: `sqlite3BtreeBeginTrans`'s retry loop is conditioned on
   `pBt->inTransaction == TRANS_NONE`, and `sqlite3PagerBegin`'s WAL branch says it in one line —
   *the busy-handler is not invoked if another connection is holding the write-lock* — the documented
   deadlock-avoidance rule from `sqlite3_busy_handler`'s own page (a reader promoting to writer is
   refused rather than made to wait). `BEGIN IMMEDIATE` opens from no transaction, and `remember`'s
   first statement is an insert, which is why writes *do* wait (`tests/test_mcp_connection_integration.py:160–218`
   proves that case). A `search`/`surface` has run both arms and the `chunk_count` read before its
   event insert (`reads.py:198–223`), so its upgrade against a **held** lock is refused at once with
   primary `SQLITE_BUSY`, exactly as it is refused at once with `SQLITE_BUSY_SNAPSHOT` after a
   **commit** (`tests/test_retrieval_reads.py:495–526` proves *that* case; nothing in the tree
   exercises the held one). The two existing spikes cannot show it: `m35_busy_snapshot_probe.py:38–41`
   lets the second connection commit before the `UPDATE`. One run confirms it — hold `BEGIN IMMEDIATE`
   plus an insert on connection A for 2 s; on B, `busy_timeout = 5000`, run `BEGIN; SELECT …; INSERT …`:
   the `INSERT` returns `SQLITE_BUSY` in milliseconds, and with `BEGIN IMMEDIATE` on B it commits at
   ~2 s. I could not run it from this seat; the author can, and should, before applying the edits.
   What it falsifies, with the edit for each:
   - **`design/build-plan.md` line 4666–4668**, *"A read's lease wait and its upgrade wait still
     compound"*: there is no upgrade wait. Replace with: *"**A read's upgrade never waits.** SQLite
     runs the busy handler for a write-lock request only from a connection with no transaction open;
     a `search` or `surface` has read before its event insert, so an upgrade that meets the writer's
     held lock is refused at once with primary `SQLITE_BUSY`, and one that meets a commit since its
     snapshot with `SQLITE_BUSY_SNAPSHOT`, also at once. The only wait a read can pay is for a pool
     lease. Writes wait because `BEGIN IMMEDIATE` opens from no transaction; the two are not one case."*
   - **`reviews/m35-brief-perturbation.md:30–31`**, *"Read verb upgrading, pool connection, the writer
     holding the lock. The busy handler waits at most 5 s … Holds."* — wrong, and it is the
     highest-traffic cell on the read side after M35: today an in-process read never meets a held
     lock (it met a nested `BEGIN`), so every `remember`/`amend`/`fetch`/consolidator transaction now
     opens a window in which every `search`/`surface` reaching its event insert is refused at once.
     Rewrite: *refused at once, primary `SQLITE_BUSY`; what the retry does about it is the forced
     change.* **Lines 118–120** (the round-3 compound-wait cell) go with it.
   - **Item 2's trigger (lines 4722–4729).** The argument for `is_stale_snapshot` — retrying a
     waited-out lock *"would cost a search two full `busy_timeout`s"* — rests on the read having
     waited, which it never does; a read's driver-level `store_busy` is always immediate. So the
     predicate is not the wrong tool, but its justification is false and the choice it forces —
     leaving the held-lock refusal unretried — is the larger share of the new traffic, unaddressed.
     The brief must choose, and say which. **(a)** Retry once on `is_contention` (either code, since
     neither waited), deferred, from `BEGIN`: it costs one more read pass and no wait, and covers a
     writer transaction shorter than that pass; a longer one — the plan fallback, `next_group`'s cold
     embed, `apply_merge` — still refuses at once, and the brief states that residual. **(b)** Retry
     once with **`BEGIN IMMEDIATE`** on the pool connection: it waits for the writer, bounded by the
     pool pragma, and can neither be staled nor refused at once, at the cost of serializing that one
     retried read behind one writer — what `retrieval.md:252–253` declines for every read and can
     accept for a retry; on the push path the hook's deadline cuts the wait and the service still
     finishes the read. No cycle: the read holds a lease and waits for SQLite's lock; the writer
     never waits for a lease (planning releases the writer before it leases). **I recommend (b)**:
     it is what makes the brief's own property below true, and the retry exists because M35 creates
     this traffic. Under either, delete *"never a reuse of it"* and the `store_busy` row's
     "narrower than its own classification" clause, which no longer describes anything.
   - **Property at 4895–4897**, *"A read that waited out `busy_timeout` answers `store_busy` after one
     attempt"*: no test can construct it, since a read cannot wait at its upgrade. Replace with:
     *"A read whose upgrade meets a held write lock is refused within milliseconds on its first
     attempt — a second connection holds `BEGIN IMMEDIATE` across a `search` with the retry disabled,
     elapsed ≪ `BUSY_TIMEOUT_MS`. With the retry [under (b)]: the read succeeds once a hold shorter
     than the budget ends, and answers `store_busy` when the hold outlasts it. The retry runs at most
     once: refused twice, `store_busy`."*
   - **Property at 4872–4874**, *"holds one request's write transaction open briefly … issues concurrent
     reads and writes, all of which succeed."* Under (a) it is false for `search`/`surface`: a
     100 ms hold outlasts two read passes on a test store, and both attempts are refused at once. Under
     (b) it holds for any hold inside `busy_timeout`. If (a) is chosen, the assertion that
     discriminates nesting from contention is *"none answers `internal_error`; the writes and the
     knowledge reads succeed"* — a nested `BEGIN` is `internal_error` today, `store_busy` is not
     nesting.
   - **Property at 4884–4887**, *"a `search` arriving in [the fallback window] may answer `store_busy`"*
     — it does, at once; say so, since "may" reads as a race the retry might win.
   - **Normative-after, `retrieval.md` §"One read is one transaction" (4550–4551):** its cost bullet
     (`retrieval.md:247–249`) names the committed case *"by another process"*; it now needs the held
     case and the in-process writer, and the retry's mode.

2. **[IMPROVEMENT] `store_unavailable` is a `knowledge_*` code, and the inode check hands it to every
   method.** Lines 4683 and 4907–4908: *"the request answers `store_unavailable`"* for any
   post-startup open onto a replaced file. `architecture.md`'s row at `:2008` scopes the code to *"a
   `knowledge_*` method [that] met a driver or OS failure"*; `dispatch_knowledge.py:26` is the only
   place it is minted, and `:2016–2025` fixes the memory verbs' rule as *map contention, propagate
   everything else* — a driver failure on `memory_search` is `internal_error` by design. So a lazy
   pool open under a `memory_surface`, or the writer's reopen under a `memory_remember`, either
   answers a code the error table says those verbs never emit — a new wire code on twelve methods,
   which the fence at 4996 (*"Not a change to what any verb returns"*) excludes and the normative-after
   list (§"Errors": `store_busy` only) does not admit — or answers `internal_error`, and the property
   at 4907 is then false for them. The absent-file case (`existing_only` refusing at a lazy open) is
   the same fork. **Edit, one of:** state the per-family answer — *knowledge verbs `store_unavailable
   {operation, cause}` as today; memory and consolidator verbs `internal_error`, with one
   `service.log` line naming the inode drift, since the poll stops the service inside its interval
   anyway* — and test each family; or widen the `store_unavailable` row to every enveloped method,
   list §"Errors"' row as changing, and carve the exception into the fence in one clause.

3. **[IMPROVEMENT] The refusal-rate measurement cannot see the class it is measuring.** Lines
   4989–4992 take the `store_busy` rate on `memory_search`/`memory_surface` from
   `experiments/m33_call_log_queries.py`'s refusal-by-code query, over the `call` rows. A read refused
   because the writer **holds** the lock returns at once, and its `call` row is attempted on the
   response path (`server.py:147–153`) while the writer still holds it — on a connection with
   `busy_timeout = 0`, so it is dropped at once (walk line 54–57 says exactly this). Every held-lock
   refusal is therefore unlogged by construction, and only the stale-snapshot share — refused *after*
   the writer committed, so its row lands — reaches the query. The with/without-retry comparison is
   blind to the arm the retry's mode decides. **Edit:** the probe phase counts refusals from the
   responses it receives, per method and per attempt, and reports the log-derived rate beside it as
   the access log's undercount; one sentence in done-when.

4. **[NITPICK] The drift guard's scope.** Line 4607–4609: *"fails on any `BEGIN` issued outside
   `transactions.py`, `store.py` and `migration.py`"* — five tests and this milestone's own fixtures
   issue `BEGIN IMMEDIATE` on holder connections (`test_retrieval_reads.py:512`,
   `test_indexing_writes.py:505`, …). Round 1 said *"greps the package"*; the brief dropped it. Write
   *"in `zikaron/`"*.

5. **[NITPICK] The timing test must patch the budget before the store opens.** Lines 4899–4903: the
   writer's own pragma is `ddl.BUSY_TIMEOUT_MS` at open (`ddl.py:26`). Patched *after* open, the
   reverted run's second writer waits 0.5 s for the lock and then up to 5 s in SQLite, so it
   **succeeds** at ~2.4 budgets when the external hold ends rather than refusing at ~2 — still red,
   but not for the reason the property predicts. Say *"patched before the store opens, so the writer's
   pragma is the budget too."*

6. **[NITPICK] Unregister the two new handlers where the `SIGTERM`/`SIGINT` pair is removed.**
   `main.py:35–39` removes its loop handlers on the way out for a stated reason; `faulthandler.register`
   keeps the log file's fd (`log.py:33`) and `add_signal_handler(SIGUSR2)` the loop callback. One clause
   in item 4's install sentence (4832): *"and removed on the same path."*

### Perturbation walk — cells to correct or add in `reviews/m35-brief-perturbation.md`

Lines 30–31 (held-lock upgrade) and 118–120 (compound read wait) are wrong as written — finding 1.
Add: *a `search`/`surface` refused at a held lock, then its `call` row attempted while the lock is
still held* (finding 3: the refusal is unlogged; accepted under invariant 10's exemption, stated
because the measurement depends on it); *a retried read under `BEGIN IMMEDIATE` holding SQLite's
write lock for its span while the writer's `BEGIN IMMEDIATE` waits behind it* (finding 1(b): bounded
by the writer's remaining budget, no cycle); *a memory verb versus a knowledge verb on a post-startup
open that finds the file replaced or absent* (finding 2).

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-09-29

### Summary judgment

The round-5 resolutions hold against the code and the new spike: `m35_read_upgrade_probe.py` measures
exactly the case round 5 argued (deferred reader refused at once, `IMMEDIATE` committing behind the
hold), option (b) is applied consistently across item 1, item 2, the wait rule, the properties and the
walk, the single read budget is stated with the pool restoring the pragma, and the per-family inode
answer, the response-counted measurement, the `zikaron/`-scoped guard and the handler removal are all
as proposed. Item 6 is the right mechanism at the right seam — the hook's own remaining time, checked
before work and before `COMMIT`, is what makes "a push the agent never saw is never recorded as shown"
enforceable at zero steady-state cost — but as written it contradicts item 2 on the one path M35 itself
creates: a `surface` whose `IMMEDIATE` retry times out behind the writer is `store_busy` by item 2 and
`deadline_passed` by the property, and the test cannot pass against the mechanism. Beside that, the
relative deadline is only as good as the service's promptness in *reading* the request, a property the
brief asserts for transit alone; the rest is precision.

### Findings

1. **[BLOCKER] The deadline property asserts a code the mechanism never produces on the scenario the
   property describes.** `design/build-plan.md` line 4989–4991: *"With a `deadline_ms` shorter than a
   writer's hold, the `surface` answers `deadline_passed`"*. Trace it through the brief's own items:
   the first attempt reaches its event insert and is refused at once (item 2, line 4732–4738); the
   retry opens `BEGIN IMMEDIATE` with `busy_timeout` set to the request's remainder (line 4767–4770);
   the hold outlasts it, so `BEGIN IMMEDIATE` returns primary `SQLITE_BUSY` after the remainder;
   `is_contention` is true; and item 2, line 4762–4763, says *"A refused retry answers `store_busy` as
   today."* Item 6's two checks (line 4933–4934) are *before any work* and *immediately before
   `COMMIT`* — neither is on that path, since no `COMMIT` is reached. So the call answers `store_busy`,
   the test as written fails, and the measurement at line 4945–4948 (*"the rate of `deadline_passed`
   among `memory_surface` calls"*) counts the M35-introduced case — the retry waiting behind the writer,
   which item 6 names as its second cause at line 4924–4925 — under the *other* code. `store_busy`'s
   own row (`architecture.md:2003`: *"the caller may retry"*) is also false for a caller that has gone.
   **Edit:** state a precedence, once: *"Past `deadline − margin`, every exit of `surface` is
   `deadline_passed`, whatever the transaction's own outcome. The retry's `BEGIN IMMEDIATE` waits no
   later than that instant — the pragma is set to `deadline − margin − now`, not to the deadline — and
   a contention refusal at or after it is answered `deadline_passed`, not `store_busy`. The check
   therefore runs at three points: before any work, after a refused attempt before deciding to retry,
   and before `COMMIT`."* Amend line 4762–4763 to *"A refused retry answers `store_busy` as today,
   unless the request's deadline has passed (item 6)"*, and the property's negative arm to *"with the
   precedence reverted, the same call answers `store_busy` and still commits nothing"*, which is what
   discriminates the precedence from the rollback. If the operator would rather keep `store_busy` on
   that path, the property must say *"answers `deadline_passed` or `store_busy` and commits nothing"*
   and the measurement must sum both codes on `memory_surface` — but that trades away the one number
   item 6 promises. Add the cell to the walk: *a `surface` refused for contention after its deadline.*

2. **[IMPROVEMENT] The relative deadline holds only if the service reads the request promptly, and
   the brief argues transit alone.** Line 4927–4930: *"The service takes its deadline as the moment it
   read the request plus that figure … Transit makes the service's deadline later than the hook's by
   the milliseconds a local socket costs, which the margin below absorbs."* In `server.py` the moment
   "it read the request" is when the connection task's `readline()` returns and, with no yielding
   await between that and the handler (`:261–264`, `:99–101`, `:129–147`), when the loop got to that
   task. Anything that occupies the loop between the hook's `sendall` and that wake — a burst of ready
   callbacks, a busy host (the brief's own "busy for days"), and above all a wedge that *clears* — makes
   the service's deadline late by that delay, always in the permissive direction: the request the hook
   abandoned sits in the socket buffer, is read with a fresh full `deadline_ms`, and commits as shown.
   The 2026-09-29 wedge is the shape: six minutes of pushes queued behind a service that answered
   nothing; had it recovered instead of being restarted, every one would have been recorded as shown.
   **Edit, one of:** (a) send an absolute wall-clock deadline — `time.time()` at send plus the
   remainder — and compare against the service's own `time.time()`: *"both ends are one machine"* is
   exactly what makes that safe (one `CLOCK_REALTIME`; NTP slew is microseconds per second, and a step
   is the one failure, rare and self-limiting), and the bound becomes *"in the future by no more than
   `BUSY_TIMEOUT_MS`"*. Not `time.monotonic()`: its reference point is undefined across processes by
   the documentation even though Linux and macOS happen to share it. Or (b) keep `deadline_ms` and
   state the assumption and its failure: *"the deadline is exact to the delay between the hook's send
   and the service's read, which is transit on a live loop and unbounded across a wedge that clears;
   the error is always toward recording as shown."* Either way, add the cell to the walk.

3. **[IMPROVEMENT] "The access log records the refusal" is false in the property's own scenario, and
   item 6's measurement sentence lacks the caveat done-when already gives `store_busy`.** Line 4991: the
   `call` row is attempted on the response path (`server.py:148–153`), on the log's own connection with
   `busy_timeout` 0; in the scenario of line 4989–4990 the writer still holds the lock when the answer
   is written, so the row is dropped — round 5 finding 3's mechanism, now on the new code. Line
   4946–4948 then calls the `deadline_passed` rate *"a query rather than a guess"* while the
   writer-wait share of it is unlogged by construction; only the slow-embed and cold-load share lands.
   **Edit:** drop the clause from the writer-hold scenario, and put the row assertion on a second one
   where it is true — an encoder stub that sleeps past the deadline with no writer, where the row lands
   and the test also covers the pre-M35 cause the operator wanted inside the item. Give item 6's rate
   the same sentence done-when gives `store_busy` (line 5090–5094). If the number is wanted whole, the
   other half is on the hook's side: `push.py:99–106` logs a mid-request `socket.timeout` as
   `transport`, indistinguishable from an unreachable service, and naming that one kind
   (`deadline_exceeded`, which the pre-send branch at `:91–92` already uses) would make `hook.log`
   count what the access log cannot — a one-line change if the operator wants it, otherwise state that
   the rate is a floor.

4. **[IMPROVEMENT] "Beyond sending it, the hook needs no new handling" is one dictionary short.**
   Line 4938: `push._REJECTION_KINDS` (`push.py:117–122`) maps wire codes to the `hook.log` kind, and an
   unmapped code is logged as `rejected_<code>` (`:151`). `architecture.md:1105–1108` makes `hook.log`
   a closed vocabulary — *"the closed vocabulary this section's error table names"* — and the brief
   adds `deadline_passed` to §"Degraded modes"' list, so a `rejected_-32026` line breaks the claim the
   list is there to keep. `push.py:112` also counts *"five wire codes"*, a tally done-when's grep rule
   will catch but the brief's sentence tells the implementer not to look for. **Edit:** *"The hook's
   map from wire code to `hook.log` kind gains the code; nothing else in the hook changes."*

5. **[IMPROVEMENT] Two `schema.md` sentences outside the per-kind table become false and are not on
   the normative-after list.** `schema.md:1293–1300` (§"Honest limit on the session denominator"): *"A
   session whose every push failed contributes no events at all, because the hook never reaches the
   service on a failure and so never emits the `surface_call`"* — after item 6 a push reaches the
   service and emits none by design, and the closing sentence *"conditional on the service having been
   reachable and healthy"* needs *"and answering within the hook's deadline"*. `schema.md:991`: *"Every
   push writes `surface_call`, which is what keeps that wait short in practice"* — every push answered
   in time. **Edit:** add both to the normative-after entry for `schema.md` at line 4567–4568, with
   the replacement wording; the denominator paragraph is the one D30's zero-write signal is read
   through, so it is the one that matters.

6. **[NITPICK] Four precision items on `deadline_ms`, one sentence each.** (a) `errors.py:157–169`
   requires every code to declare a `Disposition`; say which — `refused` (the store is fine; the
   request was declined on its own terms) or `failed` (the caller cannot act) — since
   `zikaron knowledge` prints the word. (b) The order between `bounds` and the before-work check:
   *"`bounds` first, so a request both malformed and late answers `bounds`."* (c) Line 4773–4774 says
   the budget is *"capped at `ddl.BUSY_TIMEOUT_MS`"* and line 4931 says a value above it is `bounds`;
   the cap is vacuous — keep one. (d) `push.py:90–93` degrades at `remaining <= 0`, so for
   0 < `remaining` < 1 ms the hook sends `int(remaining * 1000) == 0`, which is `bounds` under the rule
   at line 4931 — a `bounds` line in `hook.log` for a push that was merely late. Send `max(1, …)` or
   treat under one millisecond as `deadline_exceeded` locally.

7. **[NITPICK] The long-request line has the same one-directional limit the stop line admits.** Line
   4867–4874: the idle poll runs on the loop, so a *blocked* loop logs no line either, and *"a wedge
   names itself in `service.log` with nobody at the terminal"* holds for a coroutine awaiting forever,
   not for the case only `SIGUSR1` can see. Line 4875–4878 says exactly this for `reason=sigterm`;
   one clause here keeps the two consistent.

8. **[NITPICK] "Both spikes re-run" (line 5048) now sits under a sentence naming three.** Line
   4575–4576 lists three spikes as evidence; the upgrade probe is a one-off measurement with nothing to
   re-run. Say *"the staleness and busy-snapshot probes re-run"*.

### Perturbation walk — cells to add to `reviews/m35-brief-perturbation.md`

A `surface` refused for contention after its deadline, and which code answers it (finding 1); a
request read late by a busy loop, and the abandoned requests a clearing wedge finds in its socket
buffers (finding 2); a `deadline_passed` answered while the writer still holds the lock — its `call`
row dropped, so the refusal is unlogged (finding 3).

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-09-29

### Summary judgment

The round-6 resolutions hold against the code: the absolute `deadline_at_ms` with `bounds` at the
ladder's position and `deadline_passed` for an instant already past, the three check points with the
retry's pragma cut at deadline − margin, the two-scenario test asserting the `call` row only where it
lands, the hook's mid-request branch (only `rpc.surface_once` can raise a raw `TimeoutError` after
`push.py:93`'s `settimeout(remaining)`, since `connect_once` catches its `OSError`s at
`connect.py:220`), the renumbered cross-references, and a fence that lists each changed refusal. The
three items brought into scope are each the right mechanism and none adds a wait that can cycle: the
encoder wait holds nothing, the corpus `IMMEDIATE` waits on SQLite alone, and a queued writer on a
closed handle waits on nothing. What keeps this from approval is precision on exactly those three,
each of which changes what ships or how it is tested: the cold-load property's probe writer embeds and
so waits on the same load in both arms; the primitive is told to answer `store_busy` for a queued
writer but has no `verb` to mint it with, and the one classifier it could reuse rules the case out by
contract; item 6 falsifies a `schema.md` section it cites for a different rule and does not list; and
the walk now contradicts the brief in two cells. Nothing is a blocker; each is a one-paragraph edit.

### Findings

1. **[IMPROVEMENT] The cold-load property's test cannot be mutation-verified with `remember` as its
   probe, because `remember` waits on the same load.** `design/build-plan.md` lines 5073–5075:
   *"`next_group` dispatched, then a `remember` while the load is still running. The `remember`
   succeeds. With the pre-`BEGIN` wait reverted, it answers `store_busy`."* `remember` embeds
   **before** its transaction (`core/indexing/writes.py:27`; item 1's own *"the embedding a write
   prepares before its `BEGIN` holds nothing"*, line 4657–4658), through the same deferred encoder,
   whose `encode` blocks in `_loaded.wait()` (`encoder.py:506`) until the stub's load ends. Reverted:
   `next_group` takes `BEGIN IMMEDIATE` and blocks in its embed; the `remember` blocks in *its*
   embed, outside any transaction, for the same span; the load ends, `next_group`'s embed completes
   and commits within milliseconds, and the `remember`'s `BEGIN IMMEDIATE` then finds the lock free
   or waits milliseconds. It **succeeds in both arms**, so the test is green with the fix deleted.
   **Edit:** the probe is a writer that does not embed — `memory_fetch` (a write by item 2's table;
   one row in the fixture) or `memory_retire` — and the property reads: *"then a `memory_fetch` while
   the load is still running; it succeeds. Reverted, it answers `store_busy` after one budget, with
   the load still running."* Also say **which** `BEGIN` the wait precedes (line 4726, *"before its
   `BEGIN`"*): step 1 serves, embed included, when a run exists (lines 4858–4859), and step 3 serves
   otherwise, so the wait sits before step 1 and covers both.

2. **[IMPROVEMENT] The primitive is told to answer `store_busy` for a writer queued on a closed
   handle, and cannot as specified: the code needs a `verb` the primitive does not have, and its only
   classifier rules the case out by contract.** Lines 4718–4721, the property at 5069–5072, and the
   fence at 5175–5176. `store_busy`'s spec requires `{verb}` (`errors.py:262–268`); the primitive's one
   caller-supplied hook is `failure: FailureMap`, typed over `aiosqlite.Error` (`transactions.py:38`),
   and every family's map derives the code from a *driver* error (`serving.py:451–462`,
   `dispatch_knowledge.py:558–559`, `reads._failure_map`). Anything else a handler raises is
   `internal_error` at `server.py:198–218`. The quickest route — raise a constructed
   `aiosqlite.OperationalError` with `sqlite_errorcode = SQLITE_BUSY` so the maps fire — is the case
   `is_contention`'s docstring excludes in so many words: *"An exception carrying no result code — one
   constructed rather than raised by the driver — is not contention by definition"*
   (`transactions.py:74–75`); the code would accept it and the sentence would be false.
   **Edit:** name the route. The cleanest is a dedicated exception (`WriterClosedError`, not an
   `aiosqlite.Error`) raised by the primitive on finding the mark, caught at the two dispatch sites
   that already hold the method name (`server.py:186`, `dispatch_knowledge.py:548`) and answered
   `ZikaronError(STORE_BUSY, verb=method)` — one clause in item 1 and one in the property (*"answers
   `store_busy` with the method as its `verb`"*). If the failure map's signature is widened instead,
   say so, since every caller's map then takes a second input type.

3. **[IMPROVEMENT] Item 6 falsifies a `schema.md` section it cites for a different rule, and the
   section is not on the normative-after list.** Item 6 (lines 4917–4919) cites `schema.md` §"What is
   instrumented, what is not, and why" for *`Exception`, not `BaseException`* (`schema.md:1107–1110`).
   The same section states where the row is written, and item 6 moves it: `:1100–1101` *"The row is
   written inside `build()`, on the connection `open_store` yielded, before the exception leaves that
   scope"* is true after M35 only for a refusal before the lock; `:1112–1116` *"On the success path
   the row is attempted after `_print_report` and — load-bearing — after the `try`/`except`"* is
   false, since the row now lands inside `scan.run`, before `_release` and before the report; and
   `:1118–1124`, on what that placement protects and how its mutation is caught, describes a
   placement that no longer exists (the callback's guard is whole — item 6's fourth bullet). The list
   at 4561–4575 names `schema.md` for items 2 and 7 only.
   **Edit:** add the section for item 6 with the replacement: *"For every outcome reached after the
   lock was taken, the row is written by `scan.run`'s completion callback before the lock's release —
   on `Exception` only, its whole body guarded, once per build by a latch. `build()`'s own two sites
   write only when the callback never ran, a refusal before the lock, and are no-ops otherwise."*
   `:1126–1131` (*"No row write is ever the reason a build reports failure"*) stays true, and the
   entry should say so.

4. **[IMPROVEMENT] The walk contradicts the brief in two cells the renumbering pass did not reach.**
   `reviews/m35-brief-perturbation.md:87–89`: *"Writers queued on the lock when a failed rollback
   closes the writer. They run `BEGIN` on the closed handle and answer `internal_error` once …
   Accepted, and stated."* The brief at 4718–4721 and the walk's own cell at 193–194 say `store_busy`,
   and the primitive now checks the mark before any statement, so no `BEGIN` runs on the closed
   handle at all. `:37–39`: *"→ Forced: the brief names it, and the implementation must say what it
   accepts"* is superseded by 188–189, where the brief decides. The walk is what the implementation
   re-walks (brief line 5109), so a cell stating the opposite of the requirement is the one place an
   implementer would be handed the old answer.
   **Edit:** strike both in the style of lines 31–32 and 68–69, each with a pointer to the cell that
   replaced it.

5. **[IMPROVEMENT] Item 5 trades a refusal that is correct at once for a wait, on a path it does not
   name, and the test's hold is unbounded.** Lines 4903–4911: *"Under `IMMEDIATE` the second
   acquisition waits for the first to commit, reads the holder, and refuses as documented."* That
   describes a second build arriving inside the winner's *acquisition* (`scan.py:192–208`, a few
   statements). A second build arriving during any **later** indexer transaction — the walk phase's
   wholesale `pending` replace is one transaction (`knowledge-index.md:1266–1268`), the index phase
   one per path — today opens deferred, reads the committed holder as a WAL reader with no wait, and
   answers `IndexerBusyError` at once; under item 5 its `BEGIN IMMEDIATE` waits for that transaction,
   up to the corpus connection's `busy_timeout` (`knowledge/ddl.py:19,37`: 5 s), and past it answers
   the driver's `database is locked` — the refusal the item exists to remove, reachable from a new
   direction. In practice the wait is milliseconds and only a single indexer transaction longer than
   5 s reaches the residual, but the brief should say so, and the test as written (*"hold one
   acquisition's transaction open while the other attempts its own"*) yields `IndexerBusyError` only
   if the hold ends inside that 5 s; past it the test asserts the driver error instead.
   **Edit, one of:** (a) keep today's fast path — read the holder once outside any transaction,
   refuse at once on a live holder, and open `IMMEDIATE` only from *no holder*, re-reading inside
   (one extra `SELECT`, no wait ever added); or (b) accept the bounded wait and state the residual.
   Either way the test's hold is *"shorter than the corpus `busy_timeout`"*, and the walk gets the
   cell: *a second build arriving during the winner's index phase rather than its acquisition.*

6. **[NITPICK] "Every exit of `surface` is `deadline_passed`" is wider than the three check points
   that implement it.** Lines 4965–4969: the sentence says *every* exit, *"whatever the transaction's
   own outcome"*; the points are before work, after a *contention* refusal, and before `COMMIT`. A
   non-contention failure past the deadline — `index_failed` from the map, or an `internal_error` —
   passes through none of them, so an implementer following the points leaves it with its own code
   and one following the sentence wraps the handler and masks a defect as `deadline_passed`. Both
   commit nothing, which is what the property tests, so only the wire code differs. Say which:
   *"a non-contention failure keeps its own code; the three points are the rule."*

### Perturbation walk — cells to correct or add in `reviews/m35-brief-perturbation.md`

Lines 87–89 and 37–39 are contradicted by later cells (finding 4). Add: *a second build arriving
during the winner's index phase rather than its acquisition* (finding 5); *a writer queued on a
closed handle, and where its `store_busy` is minted* (finding 2).

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-09-29

### Summary judgment

Every round-7 resolution holds against the code: `memory_fetch` embeds nothing and mints its receipts
inside its transaction (`records/memory.py:459–494`), so it discriminates the cold-load property;
`scan.run` takes the lock in `_begin` *outside* its `try` (`scan.py:392–393`), so "once it holds the
lock" is a real boundary and `IndexerBusyError`/`CorpusRootMissingError` fall to `main.build`'s own
site exactly as item 6 says; `running_holder` (`lock.py:172–188`) is the "no holder" predicate item 5's
fast read needs, dead-pid locks included; the two dispatch sites hold the method name
(`server.py:186–187`, `dispatch_knowledge.py:548–566`); both consolidator apply verbs embed through
`writes.prepare` *before* their transaction (`verbs.py:20–29, 213, 315`), so `next_group` is the only
cold embed under a held lock; and the only knowledge event kind is `knowledge_build`, so "the reads
whose transaction writes" is exactly `memory_search`/`memory_surface`. The walk no longer contradicts
the brief anywhere. What remains is one internal contradiction in the bold transaction-mode rule — it
makes item 3's planning snapshot `IMMEDIATE`, which is the defect the milestone opens with — and one
inequality item 7 rests on that no test pins. Both are one-sentence edits; the rest is wording.

### Findings

1. **[IMPROVEMENT] Item 1's mode rule, read literally, puts the plan's snapshot under `BEGIN
   IMMEDIATE`.** `design/build-plan.md` line 4628–4630: *"**Every transaction a write method or the
   indexer opens against `memory.db` is `BEGIN IMMEDIATE`**"*. `memory_plan_groups` and
   `memory_next_group` are write methods by item 2's table (4752–4755), and item 3 has each open a
   *deferred* read transaction on a pool connection for `grouping.plan` (4852–4853: *"runs in a read
   transaction on a pool connection and holds no write lock"*). Under the sentence as written that
   transaction is `IMMEDIATE`, which holds SQLite's write lock for the 12.2 s the plan takes — the
   first paragraph of §"What is wrong". The rule the rest of the brief actually follows is by
   *connection*, not by method: the writer is always `IMMEDIATE` (4653), a pool connection is deferred
   (4630–4631) except a read's one retry (4779–4780). The plan property (5059–5064) would go red on a
   literal implementation, so this cannot ship silently; but `retrieval.md`'s and `architecture.md`'s
   rewrites (4556–4560, 4547–4548) will be copied from whichever sentence the author reaches for, and
   this is the bold one.
   **Edit:** replace 4628–4630 with *"**Every transaction on the writer, and every transaction the
   indexer opens against `memory.db`, is `BEGIN IMMEDIATE`.** A transaction on a pool connection is
   deferred — a read's first attempt and item 3's planning snapshot alike — with one exception, a
   read's retry (item 2)."* Drop the "write method" framing; item 2's classification decides which
   connection a method gets, and the connection decides the mode.

2. **[IMPROVEMENT] The `bounds` rule in item 7 depends on an inequality between two constants in two
   packages that nothing pins.** Line 4991: *"an integer no more than `ddl.BUSY_TIMEOUT_MS` in the
   future, or `bounds`"*; line 4802–4803 restates it as something validation *"already keeps"*. The
   hook's side is `push._DEADLINE_SECONDS = 2.0` (`hook/push.py:40`), harness-independent, and the
   service's is `ddl.BUSY_TIMEOUT_MS`, which the fence (5222–5223) says stays 5 s. The relation
   2 000 ≤ 5 000 is what makes every push valid, and no test states it: raise the hook's deadline
   past 5 s, or lower the pragma below 2 s, and the service answers `bounds` to **every** push —
   `hook.log` shows `rejected_-32005` (the code is not in `_REJECTION_KINDS`, `push.py:117–122`), the
   store gains no `surface_call`, and every existing test stays green, since none sends the hook's
   real deadline through the service's real validator. The hook is stdlib-only and cannot import
   `ddl`; a test can import both.
   **Edit:** add to the properties list: *"`push._DEADLINE_SECONDS × 1000 ≤ ddl.BUSY_TIMEOUT_MS`,
   asserted by a guard test, so the hook's own deadline is always a valid `deadline_at_ms`"*, and at
   4991 say the bound is satisfied by the hook by construction and pinned by that test. The fence's
   "it stays 5 s" then has a test behind it.

3. **[NITPICK] `artifact()` is the member whose own docstring forbids the combination the service
   uses.** Line 4743: *"the deferred encoder's `artifact()` blocks until then"*.
   `indexing/encoder.py:432–444`: `artifact()` also calls `self._declared.set()` and says *"Releases
   the loader with nothing to check, so it must not be combined with `declare_dim` on the same
   object"* — and the service's encoder is the `declare_dim` case (`:411–419`, `:502–504`). After
   `declare_dim` the second `set()` is a no-op, so nothing breaks; but the implementer either
   violates the docstring or rewrites it. `failure()` (`:446–453`) is the wait with no side effect:
   block until the load ends, report what it raised. **Edit:** name `failure()`; `next_group` needs
   nothing from its return, since a failed load raises at its own embed regardless.

4. **[NITPICK] "The writer stays `ctx.store.connection`" cannot await the reopen the same item
   requires.** Line 4808 against 4723–4726: `connection` is a synchronous property (`store.py:240–247`)
   and the dispatcher resolves it at 187 before the handler runs, yet *"a dispatch that finds the mark
   set awaits the reopen already in progress"*. **Edit:** *"the dispatcher obtains the writer through
   an awaitable accessor `Store` gains with the reopen; the synchronous `connection` remains for the
   callers that run before the socket exists."*

5. **[NITPICK] The indexer's `memory.db` handle is a `Store`'s writer, not a bare one.** Lines
   4694–4696 list *"the indexer"* among bare-handle holders that get neither budget nor pragma;
   `main.build` writes its row on `store.connection` (`indexer/main.py:105`), the connection a `Store`
   opened, which 4685–4686 says *does* get the budget. The corpus connections are bare; this one is
   not. The outcome is identical — one budget equals the opened pragma, 5 s — so it is wording:
   *"the indexer's corpus connections"*. The walk's cell at `reviews/m35-brief-perturbation.md:137–141`
   (*"keeps its opened pragma"*) is true for the same coincidental reason.

6. **[NITPICK] The planning path's lease wait is unbounded as written.** Line 4819–4820 bounds a
   *read*'s wait for a lease; `memory_plan_groups` and `next_group`'s step 2 lease from the same pool
   (4842–4843) and are writes, and no sentence bounds their wait when the pool is exhausted. No cycle
   (they hold the writer's lock at neither point), but 4692–4693 calls an unbounded wait *"a wedge by
   construction"*, and a consolidator whose client has given up at `_PLANNING_TIMEOUT_SECONDS` would
   still be queued server-side and would plan and commit after it left. **Edit:** *"The planning path
   waits for its lease within `ddl.BUSY_TIMEOUT_MS` and answers `store_busy` past it, as a read does."*
   Add the cell to the walk beside *Pool exhausted*.

### Perturbation walk — cell to add to `reviews/m35-brief-perturbation.md`

*A write method's planning lease when the pool is exhausted* (finding 6) — bounded by the same
budget, no cycle, `store_busy` past it.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-09-30

### Summary judgment

Every round-8 resolution is applied as proposed and holds against the code: the mode rule is now by
connection with both exceptions named (lines 4628–4637), and nothing on the writer, the pool or a
corpus handle is left with an undecided mode; `failure()` (`encoder.py:446–453`) is the wait with no
side effect; `_PLANNING_TIMEOUT_SECONDS = 300` (`consolidator.py:62`) makes the halved ceiling
arithmetic true even with the three bounded waits `next_group` can now pay; `push._DEADLINE_SECONDS =
2.0` against `BUSY_TIMEOUT_MS = 5000` is the inequality the new guard pins; `builds.plan` issues no
write, so `knowledge_refresh` is correctly a read; `lifecycle.add` creates the corpus file outside its
`memory.db` transaction; the walk contradicts the brief nowhere. The lease-order argument is still
deadlock-free and nothing nests. What keeps this one round short of approval is the corpus-wide grep
the brief's own done-when prescribes and did not run for two claims: a second normative copy of the
"denominator" paragraph item 7 falsifies sits in `write-policy.md` and is not listed, and item 6
moves `knowledge_build`'s writer without noticing that `lifecycle.refresh` still has unguarded work
*after* `scan.run` returns, which opens a fourth row path the count property does not name. Both are
one-paragraph edits; the rest is precision.

### Findings

1. **[IMPROVEMENT] `design/write-policy.md` carries the "session denominator" paragraph item 7
   falsifies, and it is not on the normative-after list.** `design/build-plan.md` lines 4567–4570 and
   5046–5049 list `schema.md` §"Linked sessions"' *"Honest limit on the session denominator"* — found
   by round 6 — and give its replacement. The same claim is made a second time, as normative text, in
   `design/write-policy.md` §"3. How we find out which way it errs", lines 519–529: *"a session whose
   every push failed emits no `surface_call` event at all, because the hook never reaches the service
   on a failure and therefore never emits the event the service would have written. This holds
   uniformly across every failure kind — transport, `bad_config`, `reindexing`, contention, identity …
   So the rate is conditional on the service having been reachable **and healthy**."* After item 7 a
   push reaches the service and emits no `surface_call` by design, the kinds list gains
   `deadline_passed`, and the "never reaches the service" premise no longer holds uniformly. This is
   the paragraph the six signals are *read through* in the document that defines them, so it is the
   copy that matters more than `schema.md`'s.
   **Edit:** add to the item-7 normative-after entry (4567–4570): *"and `design/write-policy.md` §3's
   first 'honest limit', which restates the same paragraph: its uniformity claim gains
   `deadline_passed` as the one failure the service *does* see and still records nothing for, and its
   closing condition gains 'and answering within the hook's deadline'."*

2. **[IMPROVEMENT] Item 6 leaves a fourth row path unnamed: a build whose scan committed and whose
   process then exits 1 now carries an `ok=true` row, where today it carries `ok=false`.**
   `zikaron/core/knowledge/lifecycle.py:313–316`: after `scan.run` returns, `refresh` still closes the
   corpus handle (`database.py:248–254`, `__aexit__` → `close()`, which can raise `aiosqlite.Error`)
   and then runs `reporting.observe` (`:315`). `observe` guards only its *open* (`reporting.py:336–342`);
   `read_meta`, `state.resolve` and `gather` inside its `async with` (`:343–350`) are unguarded and
   reach `main.build`'s catch (`main.py:124–126`). Under item 6 the callback has already written
   `ok=true` and set the latch inside `scan.run`, so that catch's `log.failed` is a no-op and the
   process exits 1 over an `ok=true` row. The row is arguably *truer* than today's — the index was
   built and committed; what failed was the report — but the brief's property (5139–5144) tests
   *"success, post-lock failure, pre-lock refusal"* and a test that injects its post-lock failure into
   `observe` rather than into `scan.run` will assert `ok=false` and go red for the wrong reason, or
   assert `ok=true` without the brief having said that is the rule.
   **Edit:** in item 6, after the latch bullet: *"A failure after the release — the corpus handle's
   close, or `reporting.observe`'s reads inside its own open — reaches `main.build`'s catch after the
   callback has latched, so the build exits 1 over the `ok=true` row its scan earned. Accepted: the row
   describes the scan, which committed, and `--wait`'s reader is told the index is built, which it is."*
   Add the fourth path to the property: *"a failure injected after `scan.run` returns leaves one
   `ok=true` row and exit status 1"*, and the cell to the walk.

3. **[IMPROVEMENT] Item 2 says what a read answers on a store without the table and not how, and the
   `schema.md` sentence that today explains why `ensure` precedes `require` is listed only for item 6.**
   Lines 4844–4854 and 4659 (*"`ensure` leaves `builds.plan`"*): removing `ensure` from a read path
   alone makes `registry.require`'s and `list_all`'s `SELECT` raise *no such table* on a fresh store —
   an `aiosqlite.Error`, which `dispatch_knowledge`'s wrapper answers `store_unavailable`, not the
   empty registry the item promises. The property at 5137–5138 would catch it, but the brief should
   name the mechanism rather than let a red test choose between two: either `ensure_table`'s presence
   read (`sqlite_master`, which line 4851 already treats as harmless) stays on every path with its
   `CREATE` half moved to the writes, or the registry's reads catch the absent table. And
   `schema.md:1133–1141` (§"What is instrumented, what is not, and why") states the old rule as
   normative — *"`registry.ensure(db)` and then `registry.require(db, name)` supply it — the pair
   `lifecycle.unlock` and `remove` open with, and **`ensure` is not optional** … a `require` hoisted
   above it would … fail with *no such table*"* — which is false for `unlock` (a read) after item 2
   and describes exactly the failure the mechanism above prevents. That section is on the list (4571)
   for the `knowledge_build` placement only.
   **Edit:** in item 2's registry paragraph: *"`ensure_table` splits: its presence read stays on every
   path and its `CREATE` runs only on the writer; a registry read on a store without the table answers
   empty from the presence read, never from a driver error."* In the schema.md entry at 4571, add:
   *"and its paragraph on `build()` resolving the registry row, which names `unlock` among the callers
   of `ensure` and gives *no such table* as the reason `ensure` is not optional — after item 2 the
   indexer's `ensure` is the one creation site outside `knowledge_add`, and a bare `require` answers
   `knowledge_base_unknown`."*

4. **[NITPICK] The primitive's two new inputs are parameters, and the brief reads as if both were
   derived.** Line 4628 (*"It gains a mode, and which mode a transaction uses follows from its
   connection"*) is followed by two caller-chosen exceptions (a read's retry, item 5's acquisition),
   so the mode must be an argument with a connection-derived default. Line 4689 (*"The primitive
   takes a deadline at entry"*) against 4808–4809 (*"one wait budget per request. It covers the lease
   wait"*): a deadline taken at the primitive's entry starts after the lease, so for a read the
   deadline is taken at dispatch and passed in. One sentence: *"the primitive takes `immediate` and
   `deadline` as arguments; absent, the mode is the connection's and the deadline is entry plus
   `ddl.BUSY_TIMEOUT_MS`; a read passes the deadline its lease started, `surface` passes
   `deadline_at_ms − margin`."*

5. **[NITPICK] A `surface` whose lease wait reaches its deadline answers `store_busy` by line
   4833–4834 and `deadline_passed` by item 7's intent.** The three check points (5017–5019) are before
   work, after a refused attempt, and before `COMMIT`; the lease is acquired before the first of them,
   so its expiry is a fourth exit and the letter of 4833 gives it `store_busy` — a code whose row says
   *"the caller may retry"* to a caller that has gone, which is round 6 finding 1's argument on a
   different path. Reachable only for a second session's `surface` during a cold load, so rare; one
   clause: *"for `surface` the lease wait ends at the deadline less the margin and its expiry is
   answered `deadline_passed`, as check point 1."*

6. **[NITPICK] The cold-load property's fixture must give `next_group` something to embed, or the
   reverted arm passes.** Lines 5127–5131: with the wait reverted, the `fetch` is refused only if
   `next_group` holds the writer *across an embed* — step 1 serving from an effectively-active own run,
   or step 3 serving after a plan. On an empty store `next_group` embeds nothing, holds the lock for
   milliseconds, and the `fetch` succeeds either way. Say: *"the fixture holds an active run of the
   caller's own with a servable group, so step 1 serves and embeds."*

7. **[NITPICK] One more neighbouring sentence in the access-log section.** `schema.md:983–987`
   (§"`call` is an access log"): *"The shared connection keeps the default, so the WAL is checkpointed
   at whichever of **its** commits finds the WAL past `wal_autocheckpoint`'s page threshold"* — after
   M35 that is the writer and every pool connection, a read's `IMMEDIATE` retry commit included. The
   section is already on the list for its own-connection bullet (4563–4566); add this bullet in the
   same clause.

### Perturbation walk — cells to add to `reviews/m35-brief-perturbation.md`

*A build that fails after `scan.run` has returned — the corpus close, or `observe`'s reads — with the
row already latched `ok=true`* (finding 2); *a `surface` whose lease wait expires at its deadline*
(finding 5).

VERDICT: NEEDS_CHANGES

## Round 10 — 2026-09-30

### Summary judgment

Every round-9 resolution is applied as proposed and checks out against the corpus and the code: the
four sites the sweep added carry the claimed text under the claimed headings (`schema.md:757–759`
under §"The `event` log, per kind", `:1973–1975` under §"Migration posture", `:2012–2015` under
§"When the version moves", `architecture.md:478–480` under §"Validation: unknown keys per file…"),
`write-policy.md:522–529` is the paragraph item 7 falsifies, `-32026` is free beside
`store_unavailable`, `_dispatch_request` has `request.method` in hand at `begin_request`
(`server.py:99`), `log.py:33`'s `FileHandler` is not delayed so `faulthandler` has a stream to take,
and the DDL guard strips line comments (`test_ddl.py:262`), so no comment can touch the fence. The
lease-order argument is still deadlock-free, nothing nests, and the walk contradicts the brief
nowhere. What remains is four one-paragraph items, two of them on testability in exactly the class the
brief holds itself to — one property passes with its fix reverted as written, and one shipped
behaviour, the hook's mapping of the new code, has no property at all. None is a blocker.

### Findings

1. **[IMPROVEMENT] The read-budget property passes with its fix reverted, as written.**
   `design/build-plan.md` lines 5132–5133: *"A read's total wait, lease plus retry, is bounded by its
   budget, tested with the pool exhausted and the writer held at once."* The single budget shows only
   if the lease is *obtained* before the budget runs out: a pool that stays exhausted for the whole
   test answers `store_busy` at one budget from the lease wait alone, in both arms, and the retry
   never runs — the same shape as round 7's finding 1.
   **Edit:** *"the pinned leases return at about half the budget and the writer's hold outlasts one
   and a half; the read answers `store_busy` at about one budget from its dispatch — reverted, at
   about one and a half, since the retry then waits the connection's whole pragma. Budget patched
   before the store opens, as the writer's test does, so the pool's opened pragma is the budget too."*

2. **[IMPROVEMENT] The hook's handling of `deadline_passed` has no property, and nothing binds
   `push._REJECTION_KINDS` to the error table.** Lines 5065–5067 state the behaviour; the properties
   at 5147–5148 cover `deadline_at_ms` sent and `deadline_exceeded` logged, not the answer's mapping.
   `push.py:117–122` duplicates the codes as literals because the hook is stdlib-only; no test in
   `tests/` names the map, and `test_hook_push.py:264–339` tests each existing code through a fake
   service. With the map entry omitted, the hook logs `rejected_-32026` and prints the relay, every
   test stays green, and `architecture.md:1105–1108`'s closed-vocabulary claim is false in `hook.log`.
   **Edit:** add to the properties: *"a `deadline_passed` answer is logged in `hook.log` as
   `deadline_passed` with its code and prints the relay instruction, through the fake-service fixture
   the other codes use; and a guard that every key of `push._REJECTION_KINDS` is an `ErrorCode` whose
   `wire_name` equals its mapped kind"* — the same import-both shape as the deadline-inequality guard.

3. **[IMPROVEMENT] The long-request line fires on every ordinary plan over 30 s, and the README row
   tells an operator that line is the wedge.** Lines 4944–4953 log any request older than
   `IDLE_POLL_INTERVAL_SECONDS` (30 s, `lifecycle.py:34`) on every poll; `_PLANNING_TIMEOUT_SECONDS`
   is 300 s, and item 3's halved ceiling puts a ~3,500-row plan near 150 s at the measured 43 ms/row —
   five `INFO` lines on a healthy service. Lines 5246–5248 then send the operator from that line to
   `kill -USR2`. The line already names the method, so the fix is one sentence in each place rather
   than a per-method threshold, which would couple `lifecycle` to a client's constant.
   **Edit:** item 4: *"A `memory_plan_groups` or `memory_next_group` entry is expected to exceed the
   interval on a large journal, up to `_PLANNING_TIMEOUT_SECONDS`; its method field is what tells that
   from a wedge."* README row: *"a planning method under five minutes is a plan, not a wedge."*

4. **[IMPROVEMENT] The retry's stated cost omits that a retried read is a lock holder to every other
   read.** Lines 4824–4825: *"The cost is serializing that one retried read behind one writer."* An
   `IMMEDIATE` retry holds SQLite's write lock for its whole pass; every other `search`/`surface`
   reaching its event insert in that span is refused at once — a deferred reader's upgrade is refused
   whoever holds the lock, the round-5 rule — and retries `IMMEDIATE` behind it, so under any writer
   activity with concurrent reads, reads convoy. Bounded by the pool: at most N−1 queue behind one,
   each holding for one pass, so the worst case is about N passes plus the writer's hold, inside the
   budget warm; no starvation past the budget and no cycle. But `retrieval.md`'s cost bullet
   (4559–4563) will be copied from this sentence, and it reads as one read behind one writer.
   **Edit:** *"…and, while it holds the lock, every other read's first attempt is refused and retries
   behind it: under a writer, concurrent reads serialize, bounded by the pool's size times a read
   pass."* Add the cell to the walk beside lines 160–162, and say in done-when that the per-attempt
   count is what shows it — a first-attempt refusal whose holder was a retried read, not the writer.

5. **[NITPICK] Five precision items, one sentence each.** (a) Line 4982, *"no wait is ever added"*:
   between the fast read and the `BEGIN IMMEDIATE` the winner can commit its acquisition and open its
   walk transaction, and the loser then waits behind that — a microsecond window, but "never" should
   say so. (b) A `surface` whose embed outlasts its deadline (a cold load) still leases, runs both
   arms and inserts before check point 3 rolls it back — a wasted pass per stalled push during exactly
   the burst item 2's pool is sized for; a check between the embed and `BEGIN` removes it, at the cost
   that the encoder-stub test must revert both checks to show the commit. (c) Lines 5076–5077, *"well
   above a local socket's response time"*: say the order — single-digit milliseconds — since every
   millisecond of margin is push budget the hook has already partly spent on connect. (d) Lines
   4836–4837, the pool restoring the pragma on return: a lease whose connection `finalize` closed is
   dropped without the restore, or the restore raises `ValueError` into a handler that already
   failed. (e) Two neighbouring sentences in `schema.md`, in a listed section but not a listed
   sentence: `:896–900`, *"a store held continuously by another writer fails the handler, at
   `store_busy`"* — a `surface` carrying a deadline fails at `deadline_passed`; and the DDL comment at
   `:154`, `-- push path fired; EXISTS EVEN AT ZERO RESULTS`, whose first clause a `deadline_passed`
   push falsifies — the guard strips comments, so it can move in both copies or stay with the second
   clause as the point.

### Perturbation walk — cell to add to `reviews/m35-brief-perturbation.md`

*A retried read holding SQLite's write lock while other reads reach their event insert* (finding 4)
— refused at once, retried behind it; bounded by the pool's size; no cycle.

VERDICT: NEEDS_CHANGES

## Round 11 — 2026-09-30

### Summary judgment

Every round-10 resolution is applied as described and holds against the code: `_prepare` runs before
`in_one_transaction` in both read verbs (`reads.py:196, 267`), so check point 2 has a place to sit;
`-32026` is free beside `store_unavailable`; `ErrorCode.wire_name` is `name.lower()`, so the
`_REJECTION_KINDS` guard holds for today's four entries and for the new one; `log.py:33` is a plain,
non-rotating `FileHandler`, so the fd `faulthandler` takes stays valid for the process's life; the
four raw `BEGIN`s in `records/memory.py` are exactly `create`/`fetch`/`amend`/`retire`;
`store.py:339` and `migration.py:154` are the two pre-socket `BEGIN`s the guard allows; the access
log already serializes `record` behind its own `_writing` lock, so its holder's primitive lock is
indeed never contended; `builds.plan` and `reporting` issue no `memory.db` write, so
`knowledge_refresh` is a read; `IndexingContext.for_store` captures `store.meta` only, so no
consolidator write reaches a connection the dispatcher did not choose; `grouping.py` embeds nothing,
so a plan on a pool snapshot never waits on the model; the lease-order argument is still
deadlock-free and nothing nests. Two things keep it one round short. The hook's new
`deadline_exceeded` mapping, as specified and as its property tests it, lets the obvious
implementation relabel a wedged service's `health()` timeout — the very `hook.log` signature the
2026-09-29 wedge left — as a late push. And item 1's budget-and-pragma rule says "writer only"
where item 2 sets the same pragma on a leased pool connection.

### Findings

1. **[IMPROVEMENT] The hook's `deadline_exceeded` catch must be scoped to `surface_once`, or a
   wedged service's `health()` timeout is logged as a late push.** `design/build-plan.md` lines
   5087–5091 say a timeout *mid-request* becomes `deadline_exceeded`, and the property at 5173–5174
   tests that direction only. `push.run` wraps `connect_once` and `surface_once` in one `try`
   (`push.py:81–106`), and `connect_once`'s warm branch re-raises whatever `_health(sock)` raises,
   bare (`connect.py:155–159`); `_try_connect` re-raises any non-absent `OSError` the same way
   (`:220–224`). `socket.timeout` is `TimeoutError`, an `OSError`, so on a listener that accepts and
   never answers — a blocked loop, or a coroutine awaiting forever — `_health`'s `recv` times out at
   the connect timeout and reaches `run()` as a bare `TimeoutError`, logged `transport` today. That
   is the eleven minutes of `transport` in LeibaTrader's `hook.log` that item 4 exists to explain.
   The obvious implementation — an `except TimeoutError` clause added to `run()`'s existing `try` —
   relabels it `deadline_exceeded`, which item 7 then counts (5112–5113) as *"the pushes the hook
   abandoned whatever the service did"*: the wedge's own signature disappears into the lateness
   floor, and the two conditions item 4 separates in `service.log` are merged again in `hook.log`.
   Every existing test stays green, and the property as written passes.
   **Edit** to the hook bullet at 5087: *"The catch sits around `rpc.surface_once` alone, not
   `run()`'s `try`: a `TimeoutError` from `connect_once` — `health()` on a listener that accepts and
   never answers, which `connect.py`'s warm branch re-raises bare and which is the wedge's own
   `hook.log` signature — stays `transport`."* Add to the properties after 5174: *"A `TimeoutError`
   raised inside `connect_once` — the fake service accepts and never answers `health` — is still
   logged `transport`; with the catch widened to the whole `try`, it logs `deadline_exceeded`."* Add
   the cell to the walk under a round-11 header.

2. **[IMPROVEMENT] Item 1 says the pragma applies to the writer only; item 2 sets it on a leased
   pool connection.** Lines 4725–4726: *"**The budget and the pragma apply only to the holder
   `Store` registers as its writer.**"* Lines 4845–4847: *"The primitive sets the leased connection's
   `busy_timeout` to what remains before the retry's `BEGIN IMMEDIATE`."* Both are normative, and
   the first is what `architecture.md` §"Lifecycle" will be written from. An implementer keying the
   pragma on "is the registered writer" makes the read-budget test red for the right reason, so the
   code is caught — but the design sentence would ship false, and the walk's round-4 cell
   (`reviews/m35-brief-perturbation.md:146`, *"the budget applies to a registered writer only"*)
   repeats it. The default-deadline sentence at 4659–4661 (*"Absent … the deadline is entry plus
   `ddl.BUSY_TIMEOUT_MS`"*) and the bare-handle bullet at 4734–4737 (*"gets neither the budget nor
   the pragma"*) also disagree about whether a bare handle has a lock-wait deadline — moot, since
   that lock is never contended, but the predicate should be stated once.
   **Edit** 4725–4726 to: *"**The pragma is set on exactly two holders — the writer, and a pool
   connection under lease for a read's retry (item 2) — and never on a holder created for a bare
   handle, whose pragma stays what it was opened with.** The lock-wait deadline is the primitive's on
   every holder; only those two ever wait for it."* Correct the walk's cell to match.

3. **[NITPICK] The no-nesting property asserts every read retried.** Lines 5123–5124: *"All of them
   succeed, the reads through their `IMMEDIATE` retry"*. Only a read whose first attempt reaches its
   event insert while the hold is open retries; one dispatched after the commit succeeds first time,
   and one whose snapshot predates the commit retries on `BUSY_SNAPSHOT`. A test asserting a retry
   per read is timing-dependent. Say *"the reads dispatched during the hold through their
   `IMMEDIATE` retry"*, and assert outcomes — all succeed, none `internal_error` — not retries.

4. **[NITPICK] `surface`'s lease-wait bound is read from `deadline_at_ms` before the ladder validates
   it.** The dispatcher leases before the handler runs (4855–4862) and bounds the wait at the
   deadline less the margin (4871–4873), while `deadline_at_ms`'s `bounds` rung sits in the handler's
   ladder (5060–5064). With the pool exhausted, a deadline the ladder would refuse — ten seconds
   ahead — bounds the lease wait at ten seconds, past `BUSY_TIMEOUT_MS`, before `bounds` is ever
   answered. One sentence: *"the `bounds` rung for `deadline_at_ms` runs at dispatch, ahead of the
   lease, so the lease wait is bounded only by a value the ladder accepted"* — or bound the wait at
   `min(deadline − margin, budget)` and say so.

5. **[NITPICK] Whether the closed-mark check runs on every holder is stated for the writer only, and
   one comment names the old symptom.** Item 1 sets the mark on any `finalize` close (4714–4716) but
   describes the pre-statement check only for requests queued on the writer (4768–4770). If the
   check is universal, the access log's next `record` after a failed rollback raises
   `WriterClosedError` rather than the `ValueError` its comments name (`access_log.py:138–140,
   154–158`) — the same `except Exception` branch and the same disposition, so behaviour is
   unchanged, but the name is a misnomer there and the comment goes stale. Say which — *"the check
   runs on every holder; `WriterClosedError` is named for the one place it is answered"* — and the
   done-when's grep then finds the comment.

### Perturbation walk — cell to add to `reviews/m35-brief-perturbation.md`

*A `TimeoutError` from the connect phase — `health()` on a listener that accepts and never answers —
after the hook gains its `deadline_exceeded` catch* (finding 1) — stays `transport`; the catch is
scoped to `surface_once`.

VERDICT: NEEDS_CHANGES

## Round 12 — 2026-09-30

### Summary judgment

Every round-11 resolution is applied as described and holds against the code: `push.run` wraps
`connect_once` and `surface_once` in one `try` (`push.py:81–106`) and `connect_once`'s warm branch
re-raises `_health`'s `TimeoutError` bare (`connect.py:155–159`), so the scoped catch is the right
shape and its negative arm discriminates; the pragma rule names both holders and the walk's round-4
cell matches; `require_int` answers `bounds` for a wrong type (`params.py:89–90`), so the dispatch-time
rung answers the same code the handler would; the access log's closed-handle branch is `except
Exception` (`access_log.py:154–167`), so `WriterClosedError` lands where `ValueError` did; every corpus
database is opened per call (`KnowledgeDatabase.open`, `reporting.py:381`), so a bare-handle holder's
lock is genuinely never contended; the `BEGIN` census in `zikaron/` is unchanged. The round-11 deltas
add no wait, and nothing new can deadlock, starve or nest. What keeps this one round short is the
narrowed claim about what `hook.log`'s `deadline_exceeded` lines count: `hook.log` carries no phase,
the pre-send branch already writes that word, and a stuck handler behind a live loop — the wedge item
4 is built to see — passes `connect_once` and lands in that count, so the sentence is wrong in both
directions and would be copied into `architecture.md` §"Degraded modes" as written. One normative
position is also still stated twice.

### Findings

1. **[IMPROVEMENT] `hook.log`'s `deadline_exceeded` lines are three populations, the brief's count
   names one, and the round-11 sentence over-claims which wedge stays `transport`.**
   `design/build-plan.md` lines 5127–5129: *"`hook.log`'s `deadline_exceeded` lines, which count the
   pushes the hook abandoned after sending them, whatever the service did. A push abandoned in the
   connect phase — a wedge — is logged `transport` and is not among them."* Three things the code
   says otherwise. (a) `failure._format_line` (`hook/failure.py:91–104`) writes `{timestamp} {kind}
   [{code}]` and nothing else, and `push.py:90–92` already writes `deadline_exceeded` **before any
   send** when the connect phase consumed the 2 s — the brief's own line 5099 cites that branch as the
   name's source, and `tests/test_hook_push.py:509–535` tests it. So after M35 one word covers a push
   the service never received and a push it received and could not answer in time, and the count is
   not *"a floor on its own"* for the sent-and-abandoned share: it is an upper bound on it. (b) A
   service whose loop is alive answers `health` at `server.py:125` **before any handler runs**, so a
   wedge in which a handler awaits forever — the case item 4's long-request line and `SIGUSR2` exist
   for, and the one the shared connection would produce — passes `connect_once`, sends, and times out
   in `surface_once`: `deadline_exceeded`, not `transport`. Lines 5102–5106 (*"the wedge's own
   `hook.log` signature"*) hold for a blocked loop only, and the 2026-09-29 wedge's kind is unknown.
   (c) `architecture.md` §"Degraded modes" names *"the internal deadline"* as a case (`:1083`) but
   never spells `deadline_exceeded` — my grep finds no occurrence in that file — so the entry at
   4556–4558 (*"a timeout mid-request is logged `deadline_exceeded`"*) would introduce the word to the
   design as if mid-request were its only source.
   **Edit, one of:** (i) split the kind by phase — `deadline_exceeded` stays for the pre-send branch
   as tested, and the post-send timeout gets its own word (`unanswered`: sent, no answer by the
   deadline); §"Degraded modes"' list gains both words; the property at 5190–5191 asserts the new
   word and the negative arm at 5192–5194 stays; lines 5127–5129 then count the post-send word and
   say a stuck handler is in it. Or (ii) keep one word and rewrite 5127–5129 to what the lines are:
   *"pushes abandoned at the deadline, before the send (connect consumed the budget: a slow spawn, a
   loaded host) or after it (a slow embed, a writer wait, or a handler that never answers behind a
   live loop); an upper bound on the sent-and-abandoned share, not a floor."* Under either, correct
   5102–5106 to *"a **blocked loop**'s signature stays `transport`; a stuck handler behind a live loop
   answers `health` and lands in the post-send kind, and `service.log`'s long-request line is what
   names it"*, and give the README wedge row (5302–5305) the same two sentences, since
   `hook.log` is the first place that row sends an operator.

2. **[IMPROVEMENT] The most complete count of service-side refusals is in `hook.log` already, and
   the "two counts" paragraph omits it.** Lines 5123–5129 list the access log's `deadline_passed`
   (undercounts the writer-hold share, since the `call` row drops) and `hook.log`'s
   `deadline_exceeded` (finding 1). A `deadline_passed` answered inside the margin reaches the hook
   whether or not the writer still holds its lock, and item 7's own map entry (5092–5096) logs it as
   `deadline_passed -32026` — a line the access log's dropped row cannot lose. That is the complete
   count of delivered refusals, grep-able with nothing added.
   **Edit:** a third bullet: *"`hook.log`'s `deadline_passed` lines: every refusal the service
   answered inside the margin, writer-hold share included, since the hook receives the answer whether
   or not the `call` row landed. The access log's count is a floor on this one, not the other way
   round."*

3. **[IMPROVEMENT] `deadline_at_ms`'s `bounds` rung has two stated positions.** Line 5070–5071:
   *"at the position the validation ladder gives parameter bounds"* — rung 1, which for `surface`
   runs in the handler after the lease (`dispatch.py:274–287` calls `require_int`/`require_str`;
   the lease covers the handler's span, 4870–4871). Lines 4881–4883: *"runs at dispatch, ahead of
   the lease."* Both answer `bounds`, so the split is observable only in `data.field` on a request
   malformed in both a `prompt` and its deadline, and in a malformed `prompt` paying a bounded lease
   wait first — but §"Validation precedence" is normative and on the list (4553–4554) for exactly
   this, and the dispatcher must parse the value whole (type as well as range) to bound the wait at
   all, which neither sentence says.
   **Edit:** replace 5070–5071 with *"`deadline_at_ms` is validated whole — an integer, no more than
   `ddl.BUSY_TIMEOUT_MS` in the future — by the dispatcher before the lease; the rest of `surface`'s
   rung 1 runs in the handler after it. Both answer `bounds`, so the order is observable only in
   `data.field`."* Say the same at 4553–4554. The alternative that keeps the ladder whole — bound
   the lease wait at the budget alone and let check point 1 catch the expired deadline after it —
   costs up to one budget of lease wait for a caller gone at 2 s; if that is preferred, say so
   and delete 4881–4883.

4. **[NITPICK] The fence names writers only for a code item 1 now gives any request.** Lines
   5330–5331: *"writers queued on a closed writer, answer `store_busy`"*; lines 4717–4719 answer
   `WriterClosedError` `store_busy` *"wherever it arises, a read's included."* Write *"any request
   the primitive finds on a closed handle"*.

### Perturbation walk — cell to add to `reviews/m35-brief-perturbation.md`

*A push against a service whose loop is alive but whose `surface` handler never answers — `health()`
answers inside `connect_once`, `surface_once` times out* (finding 1): it lands in the post-send
kind, not `transport`; the long-request line in `service.log` is what separates it from a slow embed.

VERDICT: NEEDS_CHANGES

## Round 13 — 2026-09-30

### Summary judgment

Every round-12 resolution is applied as described and holds against the code: `dispatch.health`
(`dispatch.py:95–120`) is synchronous and touches no connection, and `_handle_connection` is one task
per client, so a live loop answers `health` whatever any handler is doing; `push.py:99–106`'s
catch-all takes a post-send `TimeoutError` as `transport` today, which is what makes the pre-M35
sentence true; `connect.py:155–159` re-raises `_health`'s exception bare, so the scoped catch's
negative arm discriminates; `test_hook_push.py:422–438` already pins a `ConnectionError` from
`surface_once` to `transport`, so the new catch cannot be widened to `OSError` without a red test;
`require_int` still answers `bounds` for a wrong type. The round-12 deltas add no wait, and nothing
new can deadlock, starve or nest. Two things keep it one round short, both in the prose the operator
reads. The `unanswered` split describes the signature of one narrow wedge — the push's own handler
hanging — while item 7's deadline machinery turns the likelier one, a stuck writer holder, into a run
of `deadline_passed` answered in time; the README row would send an operator the wrong way. And the
"floor" sentence round 12 proposed is wrong, and the brief's own encoder-stub property is the
counter-example. Both are prose; neither changes a mechanism.

### Findings

1. **[IMPROVEMENT] A wedge that holds the writer, or has pinned every lease, reads in `hook.log` as
   `deadline_passed` on every push, not `unanswered`, and the brief and the README row say the
   opposite.** `design/build-plan.md` lines 5113–5116: *"A handler stuck behind a live loop is
   different, and lands in `unanswered`. The service answers `health()` before any handler runs, so
   such a push passes `connect_once`, sends, and times out in `surface_once`."* That holds only when
   the stuck handler is the push's *own* — an embed that never returns, a statement that never
   returns on its lease. Walk the case the milestone was opened for, a handler holding the writer
   forever, through the brief's own item 7: a later push leases a pool connection, embeds warm,
   reaches its event insert, is refused at once against the held lock (item 2, `SQLITE_BUSY`), passes
   check point 3, opens its `IMMEDIATE` retry with `busy_timeout` set to deadline − margin − now
   (5091–5093), is refused at that instant and — by the same lines — answers `deadline_passed`,
   **delivered inside the margin**. So `hook.log` logs `deadline_passed -32026` on every push for as
   long as the wedge lasts, its `call` row drops under the held lock (5141–5143), and the store shows
   no event in the window — which is exactly the 2026-09-29 store signature (4652–4655). A wedge that
   pins leases instead — the encoder never finishing, a worker thread stuck in SQLite — gives
   `unanswered` for the first *pool-size* pushes and `deadline_passed` at check point 1 for every one
   after. So `unanswered` is the signature of a push whose own handler hangs; a run of
   `deadline_passed` with no `call` rows behind it is the signature of the wedge that stalls
   everybody else. The README row (5325–5327, *"a handler stuck behind a live loop logs
   `unanswered`"*) would have an operator read a wall of `deadline_passed` as slowness, and the count
   bullet at 5137–5140 (*"the complete count of delivered refusals"*) is true but a reader needs to
   know a run of them is a wedge, not lateness.
   **Edit** 5113–5119 to: *"A handler stuck behind a live loop is different, and where it shows
   depends on what it holds. A push whose own handler hangs — an embed that never returns, a
   statement that never returns on its lease — passes `connect_once`, sends, and times out in
   `surface_once`: `unanswered`. A wedge that holds the writer answers every later push
   `deadline_passed` at check point 3, in time, with its `call` row dropped under the held lock; one
   that has pinned every lease does the same at check point 1 once the pool is exhausted. So a run of
   `deadline_passed` in `hook.log` with no `call` rows behind it is the post-M35 signature of the
   wedge this milestone was opened for, and `service.log`'s long-request line (item 4) is what names
   the request holding it. Before M35 every kind logged `transport`, since today's catch-all also
   takes a timeout after the send; the 2026-09-29 lines do not say which it was."* Give the README
   row (5325–5327) the same three sentences: *"a blocked loop logs `transport` on every push though
   the socket connects; a wedge holding the writer logs `deadline_passed` on every push with no
   `call` rows behind them; a push whose own handler hangs logs `unanswered`. In every case the
   long-request line in `service.log` names the request."* Add one clause to the count bullet at
   5137–5140: *"a run of them across consecutive pushes is a wedge, not lateness — see item 4."* No
   new property: the held-writer scenario at 5197–5201 already asserts the delivered
   `deadline_passed` and the dropped row. Add the cell to the walk under a round-13 header.

2. **[IMPROVEMENT] "The access log's count is a floor on `hook.log`'s `deadline_passed`" is false,
   and round 12 proposed that wording — this round corrects it.** Lines 5141–5143: *"The access log's
   `deadline_passed` among `memory_surface` calls: a floor on the line above."* The two are different
   populations and neither bounds the other. A check-point-3 refusal, answered while the writer holds
   the lock, reaches the hook in time and drops its row — in `hook.log`'s count, not the access
   log's, the direction round 12 saw. But a check-point-2 refusal on a cold load lands its row and
   reaches a hook that gave up seconds earlier, so it is `unanswered` in `hook.log` — in the access
   log's count, not `hook.log`'s `deadline_passed`. The brief's own encoder-stub property (5202–5205,
   *"the access log's `call` row carrying `deadline_passed` is asserted, because it lands"*) is
   that case, and on a cold load it is the whole population, not a corner. The walk repeats the
   claim twice (`reviews/m35-brief-perturbation.md:192–195`, *"the access log's rate is stated as a
   floor"*, and `:253–255`, *"the access log's count as a floor on it"*).
   **Edit** 5141–5143 to: *"The access log's `deadline_passed` among `memory_surface` calls: the
   refusals the service issued whose row landed — a different population from the line above, and
   neither bounds the other. A check-point-3 refusal answered under the held lock reaches the hook
   and drops its row; a check-point-2 refusal on a cold load lands its row and reaches a hook that
   has already gone, so it is `unanswered` above. The quantity D30's denominator loses is pushes the
   agent did not see: `hook.log`'s `deadline_passed` plus `unanswered`, less the margin race."*
   Correct both walk cells to *"the two counts are named as different populations, with no floor
   either way"*.

3. **[IMPROVEMENT] The long-request line, asserted from a real service process, is a 30 s test.**
   Lines 5262–5263: *"Each diagnostic writes what it promises: the two dumps, the long-request line
   and the signal stop line, asserted by reading `service.log` from a real service process."* The
   line fires only on a poll, at `IDLE_POLL_INTERVAL_SECONDS` = 30 s (`lifecycle.py:34`, slept at
   `:102`), a module constant with no config key and no environment override, so a spawned
   `zikaron.service.main` cannot be told to poll faster and the property as written waits out one
   interval — a tenth of the ~330 s suite for one assertion, and two intervals if the per-poll
   repetition is asserted. `test_service_lifecycle.py:44` already patches the constant to 0.05 s and
   drives `idle_self_stop` in-process, which is where this line lives.
   **Edit:** *"the two dumps and the stop line from a real service process; the long-request line
   in-process, with `IDLE_POLL_INTERVAL_SECONDS` patched down as `test_service_lifecycle.py` does,
   against an in-flight entry older than the interval, asserting the method, `session=unresolved`
   before the envelope resolves, and one line per poll while it stays in flight."*

4. **[NITPICK] The dispatcher's early `bounds` must sit inside the dispatched accounting, or it is a
   fifth no-row exit.** Lines 5073–5077 say `deadline_at_ms` is validated *"by the dispatcher before
   the lease"* and that the order is *"observable only in `data.field`"*. `server.py:107–154`'s four
   exits ahead of `_run_handler` write no `call` row, and `schema.md` §"`call` is an access log" is
   normative for that set; a `bounds` raised in `_compute_response_line` rather than inside
   `_run_handler`'s `try` would be a fifth, and the order would then be observable in the access log
   too. The natural placement — the parse before the lease, inside `_run_handler` — writes the row.
   One clause: *"inside `_run_handler`'s accounting, so its `bounds` writes a `call` row as the
   handler's does"*, and the edge property at 5206–5208 asserts the row.

5. **[NITPICK] Two `push.py` comments state the sentence item 7 falsifies, and the rewrite list names
   the file only for its count comment.** `push.py:100–101` (*"a timeout mid-request … the fixed word
   'transport'"*) and `:161–165` (*"a timeout mid-request. `architecture.md` draws no distinction
   between these and a plain transport failure"*). The done-when's grep finds them; one bullet under
   5299–5315 saves the grep.

### Perturbation walk — cell to add to `reviews/m35-brief-perturbation.md`

*A wedge that holds the writer, or has pinned every pool lease, seen from the push hook after item
7* (finding 1) — every later push is refused `deadline_passed` at check point 3 (or 1), delivered in
time, its `call` row dropped; `hook.log` shows a run of `deadline_passed`, the access log nothing,
`service.log`'s long-request line the holder. `unanswered` is the signature only of a push whose own
handler hangs.

VERDICT: NEEDS_CHANGES

## Round 14 — 2026-09-30

### Summary judgment

Every round-13 resolution is applied as described and holds against the code: `_run_handler`
(`server.py:172–221`) is the accounting boundary, so a `deadline_at_ms` parse and the lease placed
inside its `try` write a `call` row exactly as the brief says; `push.py:99–106` and `:161–165` are
the two comments now on the rewrite list; the "two counts" paragraph is arithmetically right (a
margin-race commit is an `unanswered` line with a row, so *deadline_passed + unanswered − margin race*
is what the denominator lacks); `apply_merge` retires absorbed rows (`verbs.py:194, 262, 412`), so
item 3's fingerprint moves on every consolidator write; and — the one mechanism no round had checked
— the primitive already routes a failed `BEGIN` past the rollback ladder (`transactions.py:166–169`),
so a `BEGIN IMMEDIATE` refused `SQLITE_BUSY` becomes `store_busy` without a spurious `ROLLBACK`
closing the writer. Nothing new can deadlock, starve or nest. Three things keep it one round short,
each a paragraph: the margin item 7 rests on is defined over a path shorter than the one it must
cover, and the operator-facing wedge signature round 13 wrote follows from the longer path; the
primitive's lock-wait expiry has no minting route, which is the gap round 7 closed for the closed
handle and the writer-budget test can be refused through either side of; and a normative sentence
about `duration_ms` becomes false once the lease sits inside the timer.

### Findings

1. **[IMPROVEMENT] The margin is budgeted for socket transit, but the path it has to cover runs from
   SQLite's busy handler giving up to the hook's `recv` returning — and includes the `call` row
   attempt on the response path.** `design/build-plan.md` lines 5097–5098: *"The margin covers
   writing the response and the hook reading it"*; lines 5130–5133: *"set well above a local socket's
   response time, which the implementation measures once … of the order of single-digit
   milliseconds"*. Trace the refusal that item 7's held-writer scenario (5211–5215) produces. The
   retry's `busy_timeout` expires on the aiosqlite worker thread; the result crosses to the loop
   (`call_soon_threadsafe`, one wake); the primitive maps it and the retry wrapper raises
   `deadline_passed`; `_run_handler` encodes; **then `_compute_response_line` attempts the `call` row
   before returning the line** (`server.py:147–154`) — on the access log's own connection, a `BEGIN`,
   an `INSERT` refused at once against the held lock, and a rollback, each a worker-thread round trip
   — and only then `writer.write`/`drain` and the hook's own wake. That is four to six thread or loop
   handoffs, each millisecond-scale on the host the brief itself calls *"busy for days"*, and
   `CLAUDE.md`'s own rule is that an idle in-process timing understated one such cost here by 2×. A
   single-digit margin measured as socket transit will be lost on that host with some regularity.
   It does not break item 7's promise — at deadline − margin the service has already rolled back, so
   nothing is recorded as shown whoever wins — but it changes what the operator reads, and round 13's
   signature was written as if the race were always won:
   - **Line 5121–5122** says the held-writer wedge answers *"at check point 3, in time"*. It does
     not: a warm first attempt is refused within milliseconds, check point 3 finds most of the budget
     left, and it is the retry's contention refusal at its expiry (5094–5096) that answers — **at**
     deadline − margin, on every push, so each push is `deadline_passed` only if that answer wins the
     margin race and `unanswered` if it loses. The run is a mix, all with no `call` rows. The walk's
     round-13 cell (`reviews/m35-brief-perturbation.md:260–264`, *"at check point 3 (or 1),
     delivered in time"*) says the same.
   - **README row (5349)** *"a wedge holding the writer logs `deadline_passed` on every push"* and
     the count bullet (5149–5150) inherit it.
   - **Line 5122–5123** *"One that has pinned every lease does the same at check point 1"*: its
     `call` row **lands**, since SQLite's write lock is free — so `deadline_passed` *with* rows behind
     it is an exhausted pool and *without* is a held writer, which is the one thing that tells the two
     apart in the store.
   **Edit:** (a) define the margin over the path: *"from the instant the retry's busy handler gives
   up, or `COMMIT` returns, to the hook's `recv` returning — the worker-to-loop handoff, the `call`
   row attempt on the response path, encoding, the socket, and the hook's wake — measured once under
   the load the host actually carries, as an A/B on the same machine, not as socket transit on an
   idle one"*; keep it a named constant, and drop *"single-digit"* until that number exists.
   (b) 5121–5123: *"A wedge that holds the writer answers every later push at deadline − margin, from
   the retry's own refusal: `deadline_passed` when that answer wins the margin race, `unanswered` when
   it loses, and its `call` row dropped either way. One that has pinned every lease answers at check
   point 1 once the pool is exhausted, and its `call` row lands."* (c) README row: *"a wedge holding
   the writer logs `deadline_passed` — or `unanswered`, when the answer lost the margin race — on
   every push, with no `call` rows behind them; the same run **with** `call` rows is an exhausted
   pool"*. (d) Correct the walk's cell the same way.

2. **[IMPROVEMENT] The primitive's lock-wait expiry has no minting route, and the writer-budget test's
   second writer is refused through either side of a microsecond race.** Lines 4728–4731: *"The
   primitive takes a deadline at entry and waits for the connection lock on what is left of it"*;
   the walk (`:16–18`) *"the lock wait is bounded by `busy_timeout` and answers `store_busy`"*. The
   only caller-supplied hook is `failure: FailureMap`, typed over `aiosqlite.Error`
   (`transactions.py:38`); a lock wait expires as `asyncio.TimeoutError`, which no map takes and which
   `_run_handler` answers `internal_error` (`server.py:198–218`). Round 7 closed exactly this gap for
   the closed handle — `WriterClosedError`, caught at the two dispatch sites that hold the method name
   (4783–4789) — and the brief says nothing for the lock wait, the commonest of the three new
   refusals. The test at 5240–5245 then asserts `store_busy` for a writer whose refusal arrives by
   either of two routes: W1's SQLite wait ends at one budget and W2's lock-wait deadline is one budget
   from an entry microseconds later, so W2 either times out on the lock (the unspecified route) or
   acquires it with ~0 left and is refused by `BEGIN IMMEDIATE` (a driver error, mapped). Reverted
   correctly it is red; implemented naively it is red or green by the microsecond. The planning path's
   lease wait (4886–4888) raises from inside a handler and needs the same answer.
   **Edit:** one base type — *"the primitive's refusals: `WriterClosedError` and `LockWaitExpired`,
   neither an `aiosqlite.Error`, share one base caught at `server.py`'s handler call and
   `dispatch_knowledge.py`'s wrapper and answered `store_busy` with the method as its `verb`; the
   pool's lease wait raises the same on expiry, so the planning path needs no map of its own"* — and
   in the property: *"whichever side of the budget refuses it, the lock or SQLite"*.

3. **[IMPROVEMENT] `duration_ms` is normatively "the handler alone", and the lease wait now sits
   inside it.** `schema.md:699` (§"The `event` log, per kind", the `call` row): *"`duration_ms`
   covers the handler alone, not envelope resolution"*; `server.py:162–164` (`_Dispatched`'s
   docstring) says the same. The brief puts the `deadline_at_ms` parse inside `_run_handler`'s
   accounting for the row's sake (5073–5077) and the lease before the handler (4866, 4882–4885), so
   under a cold load or an exhausted pool the figure gains up to one budget of waiting, and the
   `bounds` row for `deadline_at_ms` records a parse. `experiments/m33_call_log_queries.py`'s
   latency population reads that as handler time. The section is on the normative-after list (4587)
   for item 7's degraded-path sentence only. Including the wait is the better rule — a `store_busy`
   at `duration_ms` ≈ budget is what tells lease exhaustion from a slow handler — but the brief must
   say which.
   **Edit:** in item 2's "which connection" paragraph: *"`duration_ms` spans the lease wait and, for
   `surface`, the `deadline_at_ms` parse, as well as the handler: it is what the caller waited for."*
   Add `schema.md:699`'s sentence to the §"The `event` log, per kind" entry and `_Dispatched`'s
   docstring to the rewrite list.

4. **[NITPICK] The hook enforces its deadline on one clock and sends it on another; say how they
   are tied.** `push.py:60` reads `started_at = time.monotonic()`; `deadline_at_ms` is wall-clock
   (5062–5063). *"Computed from the same deadline it enforces"* (5064, 5224) holds only if
   `time.time()` is read at the same instant as `started_at` and the sent value is
   `int((wall_started + _DEADLINE_SECONDS) * 1000)`, with the socket timeout staying monotonic. One
   clause, and the property patches `time.time` and asserts the sent value rather than "the same".

### Perturbation walk — cell to correct in `reviews/m35-brief-perturbation.md`

Lines 260–264 (finding 1): the answer is issued at deadline − margin by the retry's own refusal,
`deadline_passed` or `unanswered` by the margin race; the pinned-lease half lands its `call` row.
Add: *a writer whose lock wait expires, and where its `store_busy` is minted* (finding 2).

VERDICT: NEEDS_CHANGES

## Round 15 — 2026-09-30

### Summary judgment

Every round-14 resolution is applied as described and holds against the code: the knowledge wrapper
(`dispatch_knowledge.py:548–566`) catches only `aiosqlite.Error` and `OSError`, so a base type that
is neither reaches `_run_handler`'s catch and the two-site rule is the right shape; `schema.md:699`
is the one normative sentence that says `duration_ms` covers the handler alone, and it is now
listed; nothing in `zikaron/hook/` reads `time.time()` today, so the test that patches it moves
only the deadline the hook sends; the held-writer wedge is now traced to the retry's own refusal at
deadline − margin, and the walk's round-13 cell is struck and corrected. Nothing new can deadlock,
starve or nest. Two things keep it one round short, both created by the round-14 edits. The new
base type's dispatch rule answers `store_busy` unconditionally, which contradicts the surface
lease-expiry rule three paragraphs later, and no property discriminates the two. And the margin's
definition starts its clock at *"`COMMIT` returns"*, after the one disk-bound step on the commit
path, and is framed as an A/B with no second arm — round 14 wrote both phrases, and this round
corrects them.

### Findings

1. **[IMPROVEMENT] The base type's dispatch rule and the surface lease-expiry rule contradict each
   other on the one case both cover, and no property tests it.** `design/build-plan.md` lines
   4789–4796: the primitive's refusals share one base, *"the pool's lease wait raises the same on
   expiry"*, and the two dispatch sites *"catch that base and answer `store_busy` with the method as
   its `verb`"* — unconditionally. Lines 4894–4896: *"For `surface` the lease wait ends at the
   deadline less the margin, and its expiry answers `deadline_passed`, as check point 1 of item 7
   does."* The lease is taken by the dispatcher before the handler (4873–4879), so a `surface`
   dispatched into an exhausted pool raises `LockWaitExpired` out of the lease wait into exactly the
   catch that answers `store_busy` — a retryable code to a caller that has gone, the round-6 argument
   on a fourth path. The walk's round-9 cell (`reviews/m35-brief-perturbation.md:225–226`) forces
   `deadline_passed` for this case, and the properties (5231–5245) test a held writer, an encoder
   stub and the edges, never an exhausted pool — so an implementer following 4794–4796 ships the
   contradiction green. It also decides the README row's signature: under the literal rule the
   pinned-pool wedge logs a run of `store_busy`, not the *"`deadline_passed` with `call` rows behind
   it"* that 5142–5145 and 5375–5377 promise.
   **Edit** 4794–4796 to: *"…catch that base and answer `store_busy` with the method as its `verb` —
   except a request carrying `deadline_at_ms` whose deadline less the margin has passed, which
   answers `deadline_passed`. For `surface` a lease wait can only expire at that instant, since item
   2 bounds it there, so the exception is what makes 'as check point 1 does' true; the answer is
   issued at the lease wait, before check point 1 is reached."* Add to the properties, beside the
   encoder-stub scenario: *"A `surface` dispatched into a pool whose every lease is pinned — N
   `search`es blocked in an encoder stub — with a deadline shorter than the leases' return answers
   `deadline_passed`, commits nothing, and its `call` row lands with that code, since the write lock
   is free. With the dispatcher's exception reverted, the same call answers `store_busy`."* Then
   5142–5143's *"answers at check point 1"* becomes *"is answered at its lease wait with check point
   1's code"*.

2. **[IMPROVEMENT] The margin is measured from the wrong instant on the path that matters, and "as
   an A/B" names a second arm that does not exist.** Lines 5111–5116: *"from the instant the retry's
   busy handler gives up, or `COMMIT` returns, through …"*. Three things. (a) Check point 4 is
   *"inside the transaction immediately before `COMMIT`"* (5106), so the decision that lets a commit
   through is taken **before** `COMMIT` runs, and `ddl.PRAGMAS` (`ddl.py:24–28`) sets no
   `synchronous`, so the store's connections carry WAL's default `FULL`: every commit `fsync`s the
   WAL. That `fsync` is the one disk-bound step on the whole path and the most variable one on the
   host the brief calls busy for days — and the definition starts the clock after it. (b) The two
   paths named are not equal in what losing costs. The retry-refusal path losing the race turns
   `deadline_passed` into `unanswered` in `hook.log`, which is cosmetic; the commit path losing it
   records a push as shown that nobody saw, which is the promise item 7 makes. So the constant is set
   from the commit path — pre-`COMMIT` check to hook `recv` — and the refusal path is merely covered
   by it. (c) An A/B compares two arms; this is one distribution, and *"kept as small as it allows"*
   (5153) has no referent until a statistic is named. Round 14 wrote *"`COMMIT` returns"* and *"as an
   A/B"*; both were wrong.
   **Edit** 5111–5116 to: *"**The margin covers the whole path from the service's decision to the
   hook's `recv` returning**, on the commit path: from the pre-`COMMIT` check passing, through
   `COMMIT` itself — a WAL `fsync` on the store's connections — the worker-to-loop handoff, the `call`
   row attempt on the response path, encoding, the socket, and the hook's wake. The refusal path is
   shorter and covered by the same constant. It is a named constant with its reason stated beside
   it, set once from the distribution of that path over N pushes measured under the load the host
   actually carries — both ends stamping `time.time()`, since they share a clock — at a stated high
   percentile, not from socket transit on an idle host."* Keep 5151–5154 as the accepted race, with
   the percentile as what bounds it.

3. **[NITPICK] One walk cell still carries the pre-round-14 framing.**
   `reviews/m35-brief-perturbation.md:178–180`: *"The margin is set well above a local socket's
   response time. Accepted and stated."* The brief no longer says that. Correct it to the whole-path
   definition, in the style of the round-13 cell's strike-and-correct.

### Perturbation walk — cell to add to `reviews/m35-brief-perturbation.md`

*A `surface` whose lease wait expires, seen from the dispatcher's catch after round 14* (finding 1)
— `LockWaitExpired` lands in the catch that answers `store_busy`; forced: the deadline-carrying
exception, answered `deadline_passed` at the lease wait, with a property.

VERDICT: NEEDS_CHANGES

## Round 16 — 2026-09-30

### Summary judgment

Every round-15 resolution is applied as described and holds against the code: `open_connection`
(`connection.py:176–202`) loads `sqlite-vec` and applies the pragmas inside the one call the writer's
reopen names, so that recipe is complete; nothing in `dispatch_consolidation.py` or
`core/consolidation/` catches `Exception` or `aiosqlite.Error`, so a `LockWaitExpired` raised from
the planning path's lease reaches `_run_handler`'s catch and *"needs no map of its own"* is true;
`main.py:248–250` installs the `SIGTERM`/`SIGINT` pair before `serve()`, so the two new handlers have
the home item 4 gives them; no test pins `duration_ms` to the handler alone, so item 2's widening
reddens nothing by accident; `-32026` is still free; the pinned-pool property's revert arm
discriminates (`store_busy` against `deadline_passed`, both committing nothing, the `call` row
landing in both). The margin's definition now starts before `COMMIT` and names one distribution.
Nothing new can deadlock, starve or nest. One thing keeps it a round short, and it is in the round-15
edits' own mechanism: both deadline-bounded refusals — the retry's and the lease wait's — are turned
into `deadline_passed` by a *second* reading of the clock, and the wait they compare against was
truncated to whole milliseconds, so the refusal can arrive a fraction of a millisecond before the
instant the clock check demands. The held-writer property runs that race on every execution.

### Findings

1. **[IMPROVEMENT] The `deadline_passed` decision is a clock comparison against a deadline the wait
   itself was truncated short of, so the held-writer property is red or green by the sub-millisecond,
   and a real push occasionally gets `store_busy` — a retryable code to a caller that has gone.**
   `design/build-plan.md` lines 5112–5114: *"its `busy_timeout` is set to deadline − margin − now
   … A contention refusal at or after that instant answers `deadline_passed`"*; lines 4796–4797:
   *"a request carrying `deadline_at_ms` whose deadline less the margin has passed: it answers
   `deadline_passed`"*. `PRAGMA busy_timeout` takes an integer, so the remainder is truncated:
   `int(D − M − now)` is short of the true remainder by a fraction `f ∈ [0, 1)` ms when `now` is a
   float. SQLite's default busy handler sleeps exactly its total (`sqliteDefaultBusyCallback` cuts
   the last delay to `tmout − prior` and returns 0 on the next call), so the retry's `BEGIN
   IMMEDIATE` is refused at `D − M − f` plus whatever the worker-to-loop handoff costs. The retry
   wrapper then reads the clock: when that handoff is shorter than `f` — a few hundred microseconds
   against a uniform fraction of a millisecond, so a large share of runs on a warm host — `now < D −
   M`, the rule's condition is false, and the answer is `store_busy`. The held-writer scenario at
   5243–5247 makes the retry run its whole remainder on **every** execution, so this is not a corner
   the test rarely visits; it is the test. The lease wait has the same shape: `asyncio.wait_for`
   fires at monotonic start plus the same truncated duration, and the dispatcher's exception (4796)
   reads `time.time()` again. An implementer who floors `now` before subtracting gets a remainder
   that rounds *up* and is safe; one who subtracts a float gets the race — the brief leaves the
   choice, and the two read identically. Both refusals are deadline-bounded **by construction**, so
   no second clock read is needed: the retry opens `BEGIN IMMEDIATE` from no transaction, so the
   only contention refusal it can produce is its busy handler giving up (`SQLITE_BUSY_SNAPSHOT` is
   impossible under `IMMEDIATE`, and a `surface` holding the write lock meets no contention inside
   its pass), and that wait was cut at the deadline; the `surface` lease wait is bounded by nothing
   but the deadline (4874–4875).
   **Edit:** (a) 5112–5115 to: *"The retry's `BEGIN IMMEDIATE` waits no later than the deadline less
   the margin: its `busy_timeout` is set to the remainder before it, not to the whole deadline. **A
   contention refusal from the retry answers `deadline_passed` whenever the request carries a
   deadline** — the retry opens from no transaction, so its only contention refusal is that wait
   giving up, and the wait was cut at the deadline. Decided by which bound cut the wait, never by a
   second reading of the clock: the pragma is a whole number of milliseconds, so the refusal can land
   a fraction of a millisecond before the instant a clock comparison would demand. Past it, the
   service rolls back …"* (b) 4789–4791: *"`LockWaitExpired`, which records whether the caller's
   deadline was the bound that cut the wait"*; and 4796–4800 to: *"**The one exception is a
   `LockWaitExpired` whose wait the caller's deadline bounded: it answers `deadline_passed`.** For a
   `surface` carrying `deadline_at_ms` the lease wait is bounded by that deadline alone, so its
   expiry answers with check point 1's code, issued at the lease wait before check point 1 is
   reached — decided by the bound, not by re-reading the clock. A `WriterClosedError` on such a
   request stays `store_busy`: a closed handle is not lateness."* (c) 4899–4900 stays; add *"decided
   by the bound that cut it"*. (d) Check point 3 (5109) keeps its clock read: a decision to retry
   with a remainder near zero opens a retry that is refused at once and answers `deadline_passed` by
   (a), so the race there is benign, and one clause can say so. (e) The properties at 5243–5247 and
   5252–5255 are unchanged; their revert arms — the retry wrapper's mapping deleted, the
   dispatcher's exception deleted — still answer `store_busy` and still commit nothing. Add the cell
   to the walk under a round-16 header.

2. **[NITPICK] The fence's list of what changes omits `call.duration_ms`'s new span.** Lines
   5417–5424 name four refusal changes and one parameter; item 2 (4886–4890) also changes what an
   existing payload value *means* — `duration_ms` now spans the lease wait and, for `surface`, the
   `deadline_at_ms` parse. Not a shape change, so the fence's first sentence stays true, but a reader
   of the fence alone would not expect `experiments/m33_call_log_queries.py`'s latency population to
   move. One bullet: *"`call.duration_ms` spans the lease wait as well as the handler (item 2)."*

3. **[NITPICK] A wedge holding the writer's lock outside a transaction reads as healthy in
   `hook.log`, and the README row does not say so.** Lines 5388–5394 describe three signatures, each
   read from `hook.log`. A handler that acquired the writer's `asyncio.Lock` and then hung on a
   statement *before* `BEGIN IMMEDIATE` — the `PRAGMA busy_timeout` set, on a worker thread stuck in
   a syscall — holds no SQLite lock, so every push commits normally and every write answers
   `store_busy` at one budget from `LockWaitExpired`. An operator reading `hook.log` sees nothing
   wrong; the MCP client sees a retryable code forever. The long-request line names it, as the row
   already says for every case. One clause after the three bullets: *"pushes healthy while every write
   answers `store_busy` at about one budget is a wedge holding the writer's lock with no transaction
   open; the long-request line names it too."*

### Perturbation walk — cell to add to `reviews/m35-brief-perturbation.md`

*A deadline-bounded wait — the retry's `BEGIN IMMEDIATE`, or a `surface`'s lease wait — whose
refusal lands a fraction of a millisecond before the clock's copy of the deadline* (finding 1): the
pragma and the timer take whole milliseconds, so a second clock read answers `store_busy` on a
share of runs. → **Forced: `deadline_passed` is decided by which bound cut the wait, never by
re-reading the clock; `LockWaitExpired` records the bound.**

VERDICT: NEEDS_CHANGES

## Round 17 — 2026-09-30

### Summary judgment

Every round-16 resolution is applied as described and holds against the code and the design. The
by-bound rule is consistent on every path: `deadline − margin` is the one instant the lease wait, the
retry's pragma and check points 2–4 all use, and the two minting sites — the retry wrapper in
`reads.surface` for a contention refusal on a deadline-carrying request, and the dispatcher's catch
for a `LockWaitExpired` whose bound was the caller's deadline — each answer without a second clock
read. *"The retry opens from no transaction, so its only contention refusal is that wait giving up"*
is true: `BEGIN IMMEDIATE` takes the WAL write lock before any read, so `SQLITE_BUSY_SNAPSHOT` is
unreachable, and a pass holding that lock acquires no read-mark and meets no contention. The
primitive routes a refused `BEGIN` past the rollback ladder (`transactions.py:166–169`), `_prepare`
runs before the transaction (`reads.py:196, 267`), the `call` row is attempted after the line is
computed (`server.py:147–154`), the knowledge wrapper catches only `aiosqlite.Error` and `OSError`
(`dispatch_knowledge.py:548–566`), `Disposition.REFUSED` exists (`errors.py:166`), `hook/failure.py`
validates `kind` against nothing so `unanswered` needs no registration there, and `harness.md:174,
179` names `hook.log`'s closed vocabulary without enumerating it. No `schema.md` invariant pins one
`surface_call` per push — invariant 20 constrains the rows that exist — and `README.md` makes no
per-push claim, so the normative-after list is complete on that axis. The fence's `duration_ms`
bullet and the README's healthy-looking wedge are as proposed, and the latter's signature is unique
to its cause: a held SQLite lock, an external holder, a hung reopen and a hung encoder each read
differently in `hook.log` or in the client. Nothing new can deadlock, starve or nest; the walk
contradicts the brief nowhere. Three nitpicks remain, each one clause, none changing a mechanism.

### Findings

1. **[NITPICK] Check point 1's revert arm is green.** `design/build-plan.md` lines 5274–5275: *"A
   deadline already past on arrival answers `deadline_passed` before any work."* With check point 1
   deleted, the call leases, embeds, and is refused at check point 2 with the same code and the same
   absence of rows, so the property as written passes against the revert — the one check of the four
   without a discriminating arm, where the encoder-stub scenario (5265–5268) shows points 2 and 4
   each sufficing by reverting the other. The observable difference is the embed. **Edit** 5274–5275
   to: *"A deadline already past on arrival answers `deadline_passed` before any work: the encoder
   stub records no call. With check point 1 reverted, it records one and the answer is unchanged."*

2. **[NITPICK] Check point 3's benign-race clause names one of two outcomes.** Lines 5127–5129:
   *"deciding to retry with a remainder near zero opens a retry that is refused at once"*. That is
   the held-lock case. With the lock free at that instant the retry's `BEGIN IMMEDIATE` succeeds on
   a near-zero pragma, runs its pass, and check point 4 rolls it back — the same code and the same
   empty commit, at the cost of one pass inside a sub-millisecond window. **Edit:** *"…opens a retry
   that is refused at once, or, with the lock free, runs a pass check point 4 rolls back; either way
   it answers `deadline_passed` by the rule above."*

3. **[NITPICK] A `surface` sent without `deadline_at_ms` at an exhausted pool must answer
   `store_busy`, and the edge property tests only the budget's length.** Lines 4799–4800 bound the
   lease wait by the caller's deadline *"for a `surface` carrying `deadline_at_ms`"*, so the flag
   `LockWaitExpired` records is set by the deadline's presence, not by the method; an implementer
   who sets it per method ships `deadline_passed` — terminal, *"the caller has already gone"* — to a
   caller that has not. Only tests and a non-hook client reach it, since the hook always sends one.
   Lines 5273–5274 (*"one given none uses the `search` budget"*) would pass either way. **Edit:**
   *"…one given none uses the `search` budget and, at an exhausted pool, answers `store_busy`."*

VERDICT: APPROVED
