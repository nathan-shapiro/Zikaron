# M35 implementation review

Artifact: the M35 working tree — `zikaron/core/store/{transactions,holders,pool,deadline,store}.py`,
`zikaron/service/{server,methods,dispatch,dispatch_knowledge,dispatch_consolidation,diagnostics,
lifecycle,main,access_log}.py`, `zikaron/core/retrieval/reads.py`, `zikaron/core/consolidation/
{planning,serving}.py`, `zikaron/core/knowledge/{scan,lock,registry,lifecycle,builds,reporting}.py`,
`zikaron/knowledge/indexer/{main,build_log}.py`, `zikaron/hook/{push,rpc}.py`, `zikaron/mcp/
connection.py`, the twelve new test files plus `tests/contention_fixtures.py`, and the normative
sections of `design/architecture.md`, `design/retrieval.md`, `design/schema.md`,
`design/knowledge-index.md`, `design/write-policy.md` and `README.md` the brief names. Held to
`design/build-plan.md` §M35 and its perturbation walk.

## Round 1 — 2026-09-30

### Summary judgment

The implementation does what items 1–7 say, and the concurrency reasoning survives an adversarial
read: the lock-then-closed-mark ordering, the one-budget arithmetic on both halves, the
which-bound-cut-the-wait rule, the snapshot-then-`IMMEDIATE` plan with a fingerprint over both
tiers, and the completion-callback latch all hold as written, and the tests pin each property in a
way that goes red when it is broken. The design documents describe the code as it now is. What
remains is one stale docstring that the done-when's own grep rule catches, one cheap structural
hardening the brief left open that closes a real wedge-by-one-stray-statement class, and two places
where a normative sentence is true of writes and only nearly true of reads. None is a correctness
defect in what ships; the first fails the done-when literally, so this is not approvable as-is.

### Findings

1. **[IMPROVEMENT] A third copy of "`duration_ms` covers the handler alone" survived the rewrite.**
   `zikaron/core/events.py:888` (`CallDetail`'s docstring): *"`duration_ms` covers the handler alone
   and not envelope resolution, which every call pays alike"*. The brief's done-when named
   `schema.md`'s `call` row and `_Dispatched` (both rewritten: `design/schema.md:704`,
   `zikaron/service/server.py:171-174`) and then said *"The grep for each claim, not this list,
   decides completeness"*; this is the claim's third site, in the class that carries the payload, and
   it now contradicts the schema row beside it. Replace the sentence with: *"`duration_ms` spans what
   the caller waited on that differs between calls — the wait for its connection, for
   `memory_surface` the parse of `deadline_at_ms`, and the handler — and not envelope resolution,
   which every call pays alike;"*.

2. **[IMPROVEMENT] Every store connection runs under `sqlite3`'s legacy transaction control, so a
   `BEGIN` the drift guard cannot see is one stray DML statement away, and it wedges the writer.**
   `zikaron/core/store/connection.py:177-179` calls `aiosqlite.connect(...)` with no
   `isolation_level`, so Python issues an implicit deferred `BEGIN` before any `INSERT`/`UPDATE`/
   `DELETE` executed outside an open transaction (`zikaron/core/knowledge/database.py:318-321`
   already relies on that fact for its `CREATE` argument). `tests/test_transaction_begin_sites.py`
   reads string literals, so it holds the claim in `transactions.py:16` and
   `design/architecture.md:963` — *the only `BEGIN` on a service connection is the primitive's* —
   only for explicit ones. Walk the consequence: a future `execute("INSERT …")` on the writer outside
   the primitive opens an implicit transaction that nothing commits; the next primitive transaction's
   `BEGIN IMMEDIATE` (`transactions.py:205`) fails *cannot start a transaction within a
   transaction*, which is not contention, so `_raise_mapped` answers `index_failed`/`internal_error`
   **before** the `try` that owns `finalize` — no rollback, no closed mark, no reopen — and every
   later writer transaction fails the same way: a wedge with nothing in flight for `SIGUSR2` to show,
   and one M35's own recovery machinery never triggers on. I swept every handler path and found no
   such statement today, so this is a hardening, not a defect; the brief accepted the rule as
   non-structural for the phantom-read class because the alternative was a wrapper that changes every
   core signature. This class has a one-argument fix: open every store connection with
   `isolation_level=None` in both branches of `open_connection`. Audit for what that changes: the
   only `commit()`/`rollback()` sites in `zikaron/` are `transactions.py:104,106,152`,
   `store.py:421` and `migration.py:159,168,170`, every one after an explicit `BEGIN`, and
   `sqlite3.Connection.commit()`/`rollback()` still issue `COMMIT`/`ROLLBACK` whenever SQLite is
   inside an explicit transaction whatever `isolation_level` is. Under autocommit a stray DML commits
   at once instead of leaving a transaction open, and the guard's claim becomes true by construction.
   Add a test that runs a bare `INSERT` on a fresh store connection with no transaction open and
   asserts `db.in_transaction` is `False` afterwards, and reword `database.py:318-321` to say no
   implicit transaction is ever opened. A complementary self-heal, independent of the mode: after
   `holder.acquire` and before `BEGIN`, if `db.in_transaction` is unexpectedly true, roll it back
   and log once, so this class can never be the LeibaTrader-style silent wedge again.

3. **[IMPROVEMENT] A read's budget runs from its dispatch and is spent by its embed; a write's runs
   from its `BEGIN`. The normative sentence covers only the first half of that.**
   `zikaron/service/server.py:209` takes `method.deadline(params)` before the lease, and
   `dispatch._read_call` (`dispatch.py:147`) hands that same instant to the read, so the embed in
   `reads._prepare` — a cold load included — counts against the budget the retry's
   `busy_timeout` is set from (`transactions.py:203`). A write's `in_one_transaction` computes
   `Deadline.budget()` at entry (`transactions.py:195`), after `writes.prepare` has embedded, and the
   deadline `_connection` receives for a `WRITE` is never used (`server.py:188-191`). So under a load
   longer than the budget a `memory_search` reaching a busy writer gets a zero-wait retry and answers
   `store_busy` with `duration_ms` ≈ load, which `_Dispatched`'s docstring and `schema.md:704` say
   reads as a lease-exhaustion figure. `design/architecture.md:989-990` states one budget *"for the
   wait for its connection and SQLite's own wait together"*, and `design/retrieval.md:267-268` says
   *"from its dispatch"*; neither says the embed sits inside it. The practical cost is bounded — the
   MCP client gives up at 10 s regardless — so state it rather than change it: add to
   `retrieval.md`'s budget bullet *"The budget runs from the dispatch, so an embed that outlasts it
   leaves the retry no wait; a write's budget starts at its `BEGIN`, after its own embed"*, and a
   matching clause in `architecture.md` §"The service's connections". Optionally drop the unused
   `deadline` computation for writes in `_invoke`, or make `_connection` not take it for `WRITE`,
   so the asymmetry is visible in the code rather than only in prose.

4. **[IMPROVEMENT] The `SIGUSR1` dump is installed after `assemble`, so the one dump that works
   when the process is stuck cannot be taken during the part of startup most likely to stick.**
   `zikaron/service/main.py:236` awaits `_assemble_or_log_and_raise` — permission enforcement, the
   migration under `BEGIN IMMEDIATE`, and on the create path the whole model load — and only then
   enters `diagnostics.dumps_on_signal` (`main.py:267-270`), so a `SIGUSR1` sent to a service that
   has not bound yet terminates it. The brief's placement (*"alongside the `SIGTERM`/`SIGINT` pair,
   before `serve()`"*) is met, but its reason — *"a slow start is exactly when an operator would
   send one"* — is served only for the open path, whose slow part is deferred past the bind.
   `faulthandler.register` (`diagnostics.py:74`) needs the log stream and nothing else, so it can
   go immediately after `log.configure_service_log` at `main.py:235`; `SIGUSR2` needs the tracker
   and stays with the pair. Then `design/architecture.md:832-833` says the thread dump is armed from
   the moment the log is open and the task dump with the signal pair.

5. **[NITPICK] `zikaron/hook/rpc.py:55`** — `Raises: SurfaceRejection:` names a class that does not
   exist; the class is `SurfaceRejectionError` (line 20). The docstring was touched for
   `deadline_at_ms`, so this is the moment to fix it.

6. **[NITPICK] `zikaron/core/store/deadline.py:22`** — `_MS_PER_SECOND = 1000.0` restates
   `zikaron.core.events.MS_PER_SECOND`, which `server.py` and `dispatch.py` already import for the
   same conversion. If `core/store` may import `core/events` under the dependency rules, use it;
   if not, leave it (the hook's copy in `push.py` is forced by stdlib-only and is not this).

Verified and not raised, so the next round does not re-check them: the fingerprint's `rowid` is
stable (`memory.rowid INTEGER PRIMARY KEY`, `ddl.py:57`), so `VACUUM` cannot renumber it; the
planning snapshot embeds nothing (`query.internal_query` reads the stored first-chunk vector); every
knowledge handler's registry statement on the writer goes through `registry.lookup*`, and every
corpus open follows its transaction; `merge`/`promote` embed before their transaction; check point
3's removal is outcome-invisible by the brief's own argument, so its absence from the mutation table
is correct; the perturbation walk's re-walk matches the code; and the research note supports the
one decision it is cited for (`DEADLINE_MARGIN_MS = 20`, above the 2,000-push maximum on a busy
host).

VERDICT: NEEDS_CHANGES

### Author's response to round 1

1. **Accepted.** `CallDetail`'s docstring (`zikaron/core/events.py`) now says what `duration_ms` spans: the connection wait, `deadline_at_ms`'s parse for `memory_surface`, and the handler. No other copy of the claim remains outside M33's historical brief.
2. **Accepted, all but the self-heal.** `open_connection` opens every store connection with `isolation_level=None`, in both branches, with the reason in its docstring. `test_store_connection.py::test_a_statement_outside_a_transaction_opens_none` runs a bare `INSERT`, asserts `in_transaction` is false, then opens `BEGIN IMMEDIATE` on the same handle. It goes red with the argument removed (mutation recorded in the research note). `database.py`'s `_create_tables_and_meta` docstring and `knowledge-index.md`'s bullet on the repair transaction now describe autocommit. The existing connect stub in the same file took a fixed signature and was widened. **The self-heal is declined.** Under autocommit, the only way to be inside a transaction outside the primitive is an explicit `BEGIN`, which `test_transaction_begin_sites.py` forbids. A rollback-and-log in the primitive would discard another path's uncommitted work in silence and keep a defect alive that currently fails every call loudly.
3. **Accepted as a statement, not a behaviour change.** The asymmetry is kept: a read's budget runs from dispatch and includes its embed, while a write's starts at each `BEGIN`, after its embed. Moving the write's budget earlier would shorten a `remember`'s lock wait after a cold load for no gain. It is now visible in `server._connection`'s docstring (the deadline is a read's alone), in `retrieval.md`'s budget bullet, and in `architecture.md` §"The service's connections", whose paragraph now opens *"Every transaction on the writer, and every read, has one wait budget"* instead of claiming one per request.
4. **Accepted.** `diagnostics.dumps_on_signal` is split in two. `thread_dump_on_signal` (a plain context manager, `SIGUSR1`) wraps everything in `main.run` after `log.configure_service_log`, and the rest of `run`'s body is now `_open_and_serve`. `task_dump_on_signal` (`SIGUSR2`) stays with the `SIGTERM`/`SIGINT` pair. `test_the_thread_dump_is_armed_before_the_store_opens` observes the registration from inside the store's open, and goes red with the dump moved back. Both integration tests go red with both dumps removed from a spawned child. `architecture.md`'s signal paragraph says which dump goes on when.
5. **Accepted.** `rpc.py`'s `Raises:` names `SurfaceRejectionError`.
6. **Declined, on the condition the finding set.** `core/store` imports nothing outside `core/store`, and `core/events` imports `core/knowledge`, so using its constant would make the store layer depend on the knowledge subsystem. `deadline.py` keeps its own.

## Round 2 — 2026-09-30

### Summary judgment

Round 1's six items are resolved in the tree as the response says — I checked each against the code,
not the response — and the two declines are right on their own terms. Read fresh, the implementation
holds everywhere I pushed on it: the fingerprint sees every way a memory row can move, the registry
table has exactly two creation sites and both are `IMMEDIATE` on a writer, the indexer's handle really
is a `Store` writer, the `SIGUSR1` dump reaches `service.log` rather than a detached process's
`/dev/null`, the four `surface` check points are where the brief puts them, and every design sentence
the brief's top list names now reads as the code behaves. One defect remains, and it is in the
primitive the whole milestone rests on: the connection lock's wait is unbounded in a one-iteration
window after every release, which is the compounding item 1 exists to rule out. The fix is three
lines and has a deterministic test; nothing else here needs to move.

### Findings

1. **[BLOCKER] `ConnectionHolder.acquire`'s untimed branch admits an unbounded lock wait in the
   window after every `release()`.** `zikaron/core/store/holders.py:92-102`. `asyncio.Lock.release()`
   clears `_locked` and wakes the first waiter through `call_soon`; until that waiter's task runs,
   `Lock.locked()` answers `False` while `_waiters` is non-empty (3.12–3.14 alike: `locked()` is
   `return self._locked`). A task reaching `acquire` in that window — a `remember` whose embed
   finished on the loop iteration a `next_group` released, say — takes the `else` branch and awaits
   `self._lock.acquire()` with **no timeout**; `Lock.acquire` sees a live waiter, queues behind it,
   and the newcomer then waits for every queued transaction to run to completion, unbounded by
   `deadline`. That is exactly the compounding `design/architecture.md:991-1002` says the one budget
   rules out, with the consequence it names: a `memory_remember` that outlasts the client's 10 s
   answers `AmbiguousMutationError` and commits anyway. If the transaction it queued behind is the
   stuck one, this request hangs for good and `LockWaitExpired` is never raised — item 4's
   long-request line would show it, but item 1 was supposed to prevent it. No existing test can
   catch it: `tests/test_service_writer.py::test_the_wait_for_the_writers_lock_ends_at_the_budget`'s
   newcomer arrives while `_locked` is `True`. (`ReadPool._take` has no equivalent: its predicate is
   `_idle`/`_opened` under the condition, not `locked()`.) **Fix:** drop the fast path and take every
   acquisition under the timeout. `asyncio.timeout(0)` around a free lock does not raise — `Lock.acquire`
   returns without yielding, and the `call_soon`-scheduled expiry is cancelled on `__aexit__` — so the
   body of `acquire` after the nested check becomes:
   ```python
   try:
       async with asyncio.timeout(deadline.remaining()):
           await self._lock.acquire()
   except TimeoutError:
       raise LockWaitExpired(set_by_caller=deadline.set_by_caller) from None
   self._owner = task
   ```
   and the `Raises:` line reads *"the lock was still held, or queued for, at `deadline`"*. **Test**,
   beside `tests/test_store_pool.py::test_a_held_connection_lock_refuses_a_spent_deadline_at_once`:
   ```python
   async def test_a_wait_that_begins_as_the_lock_is_released_still_ends_at_its_deadline(tmp_path):
       async with open_context(tmp_path) as ctx:
           holder = holders.holder_of(ctx.store.connection)
           await holder.acquire(Deadline.budget())
           queued = asyncio.create_task(holder.acquire(Deadline.budget()))
           await asyncio.sleep(0)            # `queued` is now a waiter
           holder.release()                  # wakes it; it has not run yet, so `locked()` is False
           with pytest.raises(LockWaitExpired):
               await asyncio.wait_for(holder.acquire(_spent(set_by_caller=False)), timeout=1.0)
           await queued
           holder.release()
   ```
   Red today — the newcomer queues untimed behind `queued`, which holds the lock until the test ends,
   so `wait_for` raises `TimeoutError` rather than `LockWaitExpired` — and green with the fix. Add
   the row to `research/m35-implementation-evidence.md` §"Every guard, shown red".

Verified and not raised, so the next round does not re-check them: the `(rowid, version)` fingerprint
sees a promote as well as an amend, a retire and a new row, because `records/memory.py:812` bumps
`version` with `tier`; `ensure_table` has exactly two callers (`core/knowledge/lifecycle.py:198`,
`knowledge/indexer/main.py:105` through `ensure`), both on a writer, and every read path answers from
the presence read; the indexer opens through `Store.open` (`knowledge/scope.py:102`), so the build row's
`IMMEDIATE` claim in `build_log.py` is true; `diagnostics._log_stream()` searches the same logger
`log.configure_service_log` attaches the `FileHandler` to, so a detached service's `SIGUSR1` dump lands
in `service.log`; `tests/contention_fixtures.patch_budget` patches `ddl.PRAGMAS` as well as the
constant, so the tests' "opened pragma is the budget" premise holds; `surface`'s four check points are
at entry, after `_prepare`, between attempts and last inside `work`, and `_checked_limit` precedes the
first, so `bounds` beats lateness; `TransactionRefused` and `StoreReplacedError` raised from inside a
consolidator handler's `planning.snapshot` still reach `_invoke`'s two `except` clauses; the hook's
`except TimeoutError` is around `surface_once` alone and a connect-phase timeout falls to `transport`;
`test_service_diagnostics_integration.py` carries `pytest.mark.integration`, which `addopts` does not
deselect, so the dump and stop-line assertions run in the gate; and the research note supports the two
decisions it is cited for — the 20 ms margin above a 2,000-push maximum of 15.81 ms, and the retry's
necessity at 2,617 refusals against 0.

VERDICT: NEEDS_CHANGES

### Author's response to round 2

1. **Accepted.** `ConnectionHolder.acquire` now times every acquisition under `asyncio.timeout(deadline.remaining())`, with no fast path through `locked()`. Its comment gives the reason, and `Raises:` reads *"still held, or queued for"*. `tests/test_store_pool.py` gains the test proposed here, as written. It goes red with the old branch restored (mutation recorded in `research/m35-implementation-evidence.md`). It also gains `test_a_free_lock_is_taken_whatever_the_deadline`, which pins the premise the fix depends on: a spent deadline is refused only when the acquisition would queue.

## Round 3 — 2026-09-30

### Summary judgment

Round 2's blocker is closed as the response says, and I checked the mechanics rather than the prose:
`ConnectionHolder.acquire` (`zikaron/core/store/holders.py:95-99`) takes every acquisition under
`asyncio.timeout(deadline.remaining())`, which on 3.12–3.14 never fires on a free lock — `__aenter__`,
the synchronous return from `Lock.acquire` and `__aexit__`'s cancel of the scheduled expiry run with
no loop iteration between them — and does cut a queued one, with `Lock.acquire`'s own cancel path
(`locks.py:116-118` on 3.12.14) removing the waiter and waking the next when the lock is free. The new
test drives exactly the release-to-run window. This round went where the earlier ones had not — the
pool's condition variable, the knowledge subsystem's registry transactions on both connection kinds,
the corpus lock's acquisition, the indexer's callback and latch, the hook's two ends, and every design
passage the brief lists — and found one behavioural gap of the same class as round 2's, narrower and
bounded, in the *other* wait primitive, plus one normative sentence that overstates an order the
section itself calls a contract. Neither is a defect in what ships on the ordinary path; both are cheap.

### Findings

1. **[IMPROVEMENT] `ReadPool._take`'s wake-up can be lost on 3.12, leaving a returned connection idle
   while the next waiter runs out its whole budget.** `zikaron/core/store/pool.py:96-98` and
   `:104-107` wake a waiter with `Condition.notify()`, which resolves exactly one waiter's future.
   On the gate's own interpreter, 3.12.14, `Condition.wait` (`asyncio/locks.py:262-282`) has no
   re-notify on error: if that waiter's task is cancelled in the same loop iteration — and
   `asyncio.timeout`'s expiry *is* a `task.cancel()`, as is a client disconnect cancelling the handler
   task — `Task.cancel()` finds the future already done, sets `_must_cancel`, and the task's next step
   throws `CancelledError` at `await fut`; the `finally` removes the future and the notification is
   passed to nobody. 3.13.15 and 3.14.7 carry the fix (`locks.py:295-296`, *"Any error raised out of
   here _may_ have occurred after this Task believed to have been successfully notified"*). Walk the
   consequence: pool exhausted (a cold load with five concurrent reads, or the pinned-pool wedge
   `architecture.md:1293-1295` names); a lease returns as W1's deadline expires; W1 answers
   `LockWaitExpired` correctly, the connection sits in `_idle`, and W2 — whose future `notify(1)` never
   touched — waits to its own deadline and answers `store_busy` or `deadline_passed` with a connection
   free the whole time. That is the brief's *"waits for a lease within its budget"* (item 2) failing
   in the one direction M35 exists to close, bounded by one budget and needing a same-iteration
   coincidence, so it is a hardening rather than a wedge. **Fix:** `notify_all()` at both sites. Every
   waiter re-checks `while not self._idle and self._opened >= POOL_SIZE` under the lock, so waking all
   costs nothing but the re-check, and it covers the external-cancel case that a re-notify inside
   `_take`'s `except TimeoutError:` branch would not. **Test**, in `tests/test_store_pool.py`, which
   simulates the expiry with the same `task.cancel()` it performs, so it is deterministic on 3.12 and
   green either way on 3.13+ (the reason to name the version in the comment beside the fix):
   ```python
   async def test_a_notification_a_cancelled_waiter_consumed_still_reaches_the_next(
       tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       patch_budget(monkeypatch, 300)
       async with open_context(tmp_path) as ctx:
           pool = ctx.store.pool
           held = [pool.lease(Deadline.budget()) for _ in range(POOL_SIZE)]
           for lease in held:
               _ = await lease.__aenter__()
           first = asyncio.create_task(pool._take(Deadline.budget()))
           second = asyncio.create_task(pool._take(Deadline.budget()))
           await asyncio.sleep(0.01)
           await held[0].__aexit__(None, None, None)  # notifies `first`, which has not run yet
           first.cancel()  # what an expiry does, in the same iteration
           with contextlib.suppress(asyncio.CancelledError):
               await first
           db = await asyncio.wait_for(second, timeout=0.15)
           await pool._give_back(db)
           for lease in held[1:]:
               await lease.__aexit__(None, None, None)
   ```
   Red today on 3.12 — `second` would answer `LockWaitExpired` at 300 ms, so `wait_for` raises
   `TimeoutError` at 150 ms — and green with `notify_all()`. `held[0].__aexit__` yields to nothing:
   `_restored` returns without awaiting when `budget_moved` is false and the condition's lock is free,
   so `first.cancel()` lands before `first` runs. Add the row to
   `research/m35-implementation-evidence.md` §"Every guard, shown red".

2. **[IMPROVEMENT] `architecture.md` §"Validation precedence" states an order the code does not keep
   when the pool is exhausted.** `design/architecture.md:2055-2057`: *"`bounds` is decided before any
   deadline check, so a request both malformed and late answers `bounds`"*. The paragraph's own
   previous sentence says `prompt` and `limit` are validated *after* the lease, and
   §"The service's connections" (`:1004-1006`) says a lease wait the caller's deadline cut answers
   `deadline_passed` — so a `surface` with `prompt: 7` and a past `deadline_at_ms` answers `bounds`
   only while a lease is free; with the pool pinned, `pool._take` (`pool.py:69-71`) refuses at once
   and the handler's rung never runs. `tests/test_service_surface_deadline.py:267-276` tests the
   free-lease case only. The section's premise is that the order is a contract, so the summary
   sentence should carry the exception rather than leave it to be derived: *"`bounds` is decided
   before any of the four deadline checks, so a request both malformed and late answers `bounds` —
   unless it had to wait for a lease and the deadline cut that wait, which answers `deadline_passed`
   before the handler's rung runs (§"The service's connections"); a deadline already past is not
   malformed and answers `deadline_passed` (§"Degraded modes")."* Optionally pin it: beside
   `test_bounds_is_decided_before_lateness`, a case under `_pin_the_pool_with_searches` sending
   `{"prompt": 7, "deadline_at_ms": _deadline_in(0.3)}` and asserting
   `(_DEADLINE_PASSED, {"verb": "memory_surface"})`.

3. **[NITPICK] `tests/test_store_pool.py:3-6`** — the module docstring enumerates the edges the file
   covers (*"a deadline already spent on arrival, a connection handed back closed or unable to take
   back its pragma, and a pool closed while a lease is out"*) and the two round-2 tests are not among
   them. Either add *"the connection lock's release window, and a free lock under a spent deadline"*,
   or drop the list for the predicate — *"the edges a request cannot reach deterministically"* —
   which `coding-standards.md` §5 prefers anyway.

Verified and not raised, so the next round does not re-check them: `IndexingContext.for_store`
(`core/indexing/writes.py:104-113`) captures `meta` only, so a writer reopen strands no handle — the
one construction-time capture of a writer is the indexer's `OpenStore` (`knowledge/scope.py:112`),
single-task, with no reopen path; every `aiosqlite.connect` outside `open_connection` is the read-only
orphan breadcrumb (`reporting.py:381`), which issues no `BEGIN` and no DML; the knowledge writes'
registry statements each sit in a primitive transaction whose mode follows the connection —
`lifecycle.add._register` (`ensure_table` + `insert`), `remove`'s `lookup` then `delete`, `rename`,
`reporting.status`'s `lookup`, `builds.plan`'s `lookup_all`/`lookup_each` — so `knowledge_refresh`'s
copy of `builds.plan` is deferred on its pool connection and `knowledge_add`'s is `IMMEDIATE` on the
writer, with every `observe` outside; the corpus lock's `_begin` (`scan.py:206`) passes
`immediate=True` on a default holder that never sets the pragma, so the corpus `busy_timeout` stands;
`scan.run`'s callback runs on `Exception` and in the `else`, never for `BaseException`, before
`_release`; `BuildLog`'s latch is set on attempt at all three sites; `_naming_the_store` catches only
`aiosqlite.Error` and `OSError`, so `TransactionRefused` reaches `_invoke`; `AccessLog.record` stops on
`WriterClosedError` through its `except Exception`; `log.configure_service_log` sets `INFO`, so the
dumps and the long-request line land; `thread_dump_on_signal` wraps the whole of `_open_and_serve`;
the hook's `except TimeoutError` is around `surface_once` alone and `-32026` is in
`_REJECTION_KINDS`; `tests/test_hook_push.py:668` and `test_service_surface_deadline.py:281` pin the
two inequalities the margin and the budget rest on; the `_PLANNING_TIMEOUT_SECONDS` comment carries
the halving; `mcp/connection.py:52-62` describes the one-budget rule as shipped; and the design
passages the brief lists read as the code behaves — `architecture.md` §"The service's connections",
§"What a service that stops answering writes", §"Degraded modes" (`deadline_at_ms`, the three kinds of
lateness, the four wedge signatures), §Errors' `deadline_passed` row; `retrieval.md:247-273`;
`schema.md:689` (`surface_call`), `:762-767`, `:904-913`, `:1119-1131`, `:1299-1308`;
`knowledge-index.md:139-146` and `:2504-2507`; `write-policy.md:522-532`; `README.md:681-688` and the
`:727` troubleshooting row. The surface-deadline, read-contention, writer, diagnostics and
snapshot-planning tests assert outcomes with bounds the listed mutations move, not mechanisms.

VERDICT: NEEDS_CHANGES

### Author's response to round 3

1. **Accepted.** Both wake sites in `ReadPool` (`_give_back`, `_forget_one`) call `notify_all()`, and the reason, naming 3.12, sits at the top of `_take`, where the predicate each waiter re-checks lives. The proposed test is in `tests/test_store_pool.py` as written, apart from binding the cancelled task's await for `mypy`. On 3.12.3, the gate's interpreter, it goes red with `notify()` restored and green with the fix (mutation recorded in `research/m35-implementation-evidence.md`).
2. **Accepted, with the test.** `architecture.md` §"Validation precedence" carries the exception in the words proposed. `test_a_malformed_push_whose_deadline_cuts_its_lease_wait_answers_deadline_passed` pins it beside `test_bounds_is_decided_before_lateness`. The approved brief's own sentence (`build-plan.md` §M35 item 7) is left as approved.
3. **Accepted, the predicate form.** `tests/test_store_pool.py`'s module docstring now ends at *"the edges a request cannot reach deterministically"*.

## Round 4 — 2026-09-30

### Summary judgment

Round 3's three items are in the tree as the response says, and I checked the mechanics rather than
the prose: both wake sites in `ReadPool` (`pool.py:102`, `:111`) call `notify_all()` under the
condition, with the reason at `_take`'s predicate naming 3.12; the proposed test is present with the
one `mypy` binding; §"Validation precedence" (`architecture.md:2055-2059`) carries the exception in
the words proposed, and `test_a_malformed_push_whose_deadline_cuts_its_lease_wait_answers_deadline_passed`
pins it under a pinned pool. This round went where no earlier round's verified list reached: the
writer's reopen under the store's lock and the two-writes-into-the-gap test, `Store.close`'s ordering
against a lease still out, the classification test, the interleaved-commit fixture that drives all
twelve write verbs, the read-contention tests' arithmetic against the code's, the drift guard's
recogniser, the `faulthandler` stream's lifetime, `write/tools.py`'s embed-before-`BEGIN`, and the
design passages the brief's top list names that round 3's list did not — §Planning, the signal
paragraph under §"Idle self-stop", the stop-reason list, `knowledge-index.md` §6, `schema.md`'s
migration-posture sentence and README's wedge row. Every one reads as the code behaves. What remains
is one hardening of the milestone's own drift guard — it recognises `BEGIN` by spelling, and SQLite
defines a `SAVEPOINT` outside a transaction *as* a `BEGIN DEFERRED`, while the seven `commit()`/
`rollback()` sites round 1 audited by hand are pinned by nothing — and one validation hole a same-uid
caller needs a three-hundred-digit integer to reach. Nothing shipped is wrong; the first is five lines
in one test file and closes the last spelling of the wedge class this milestone exists to end.

### Findings

1. **[IMPROVEMENT] The drift guard holds "the only `BEGIN`" by spelling, and two other spellings open
   or end a transaction on the writer without one.** `tests/test_transaction_begin_sites.py:30-33`
   (`_BEGIN_STATEMENT`) and `:36-56` (`_begin_lines`). SQLite's own definition: a `SAVEPOINT` issued
   when no transaction is active *"behaves the same as `BEGIN DEFERRED TRANSACTION`"*, and `RELEASE` of
   the outermost savepoint is a `COMMIT`. Under the autocommit round 1 added, a stray `SAVEPOINT x` on
   the writer outside the primitive with no `RELEASE` is exactly the class round 1 item 2 closed for
   implicit DML: a transaction nothing commits, the next `BEGIN IMMEDIATE` (`transactions.py:205`)
   failing *within a transaction* before the `try` that owns `finalize`, and every later writer
   transaction failing the same way — a wedge with nothing in flight for `SIGUSR2` to show. From the
   other end, a `db.commit()` or `db.rollback()` issued outside the primitive while another task's
   transaction is open on the handle commits or discards *that* task's staged rows, which
   `transactions.py:8-10` names as the reason there is one ladder — and a method call is invisible to a
   string guard, so a second copy of the ladder is precisely what this guard cannot see. Both are
   clean today, so the widened guard is green on landing and pins round 1's audit: `zikaron/` holds no
   `SAVEPOINT`, `COMMIT` or `ROLLBACK` literal, and its only `.commit(`/`.rollback(` calls are the seven
   round 1 listed (`transactions.py:104,106,152`, `store.py:421`, `migration.py:159,168,170`), all in
   the three allowed modules. **Fix, in the test file alone.** Widen the recogniser to
   ```python
   _TRANSACTION_CONTROL: Final = re.compile(
       r"^\s*(BEGIN(\s+(DEFERRED|IMMEDIATE|EXCLUSIVE))?(\s+TRANSACTION)?"
       r"|COMMIT(\s+TRANSACTION)?|ROLLBACK(\s+TRANSACTION)?(\s+TO(\s+SAVEPOINT)?\s+\S+)?"
       r"|SAVEPOINT\s+\S+|RELEASE(\s+SAVEPOINT)?\s+\S+)\s*;?\s*$",
       re.IGNORECASE | re.MULTILINE,
   )
   ```
   leaving `END` out on purpose — `END` alone on a line of a formatted `CASE` expression would match
   under `MULTILINE` — and have `_begin_lines` also yield `node.lineno` for every `ast.Call` whose
   `func` is an `ast.Attribute` with `attr in {"commit", "rollback"}`. Extend
   `test_the_guard_finds_a_begin_in_every_form_a_call_can_carry_it` with two lines,
   `'await db.execute("SAVEPOINT s")\n'` and `'await db.commit()\n'`, asserting `[1, 2, 3, 4, 5]`.
   Reword the module docstring's first line to *the only transaction control a service connection
   sees is the transaction primitive's* and the offender test's name to match; `transactions.py:16`
   and `architecture.md:965` stay true as written and need no change. Add the row to
   `research/m35-implementation-evidence.md` §"Every guard, shown red" only if a mutation is run — a
   guard over source has no behaviour to revert, so the recogniser test is its own evidence.

2. **[NITPICK] `surface_deadline` answers `internal_error`, not `bounds`, for an integer beyond
   float range.** `zikaron/service/dispatch.py:180`: `value - time.time() * MS_PER_SECOND` raises
   `OverflowError: int too large to convert to float` for a JSON integer of about 310 digits or more,
   which `json.loads` builds without complaint; it escapes to `_run_handler`'s `except Exception` with
   a logged traceback. `Deadline.from_caller` (`deadline.py:53-54`) has the same arithmetic for a huge
   *negative* value, which passes the bound check. Reachable only from a same-uid caller on a `0600`
   socket, so nothing the hook does. Fix in integers: in `surface_deadline`, `now_ms = int(time.time()
   * MS_PER_SECOND)` and `if value - now_ms > ddl.BUSY_TIMEOUT_MS:`; in `from_caller`,
   `remaining_ms = max(deadline_at_ms - margin_ms - int(time.time() * _MS_PER_SECOND), -1)`, since
   `remaining()` and `passed()` already treat every negative remainder alike. Then `lambda: 10**400`
   joins the `bounds` parametrisation in `test_service_surface_deadline.py:246-249`, and
   `-(10**400)` answers `deadline_passed` in `test_a_deadline_already_past_answers_before_any_work`.

Verified and not raised, so the next round does not re-check them: `Store.writer()` (`store.py:264-282`)
reopens once per closure under `_reopening` with a re-check inside the lock, a request queued on the
old holder's lock answers `WriterClosedError` after acquiring, and a failed reopen leaves `_db` closed
so the next call retries rather than serving the dead handle; `Store.close()` closes the pool before the
writer and a lease still out is closed on its return (`pool.py:99-106`); `_take` after `close()` is
unreachable on every ordinary path, since `shut_down()` cancels and awaits every handler before
`ctx.close()` runs; `test_the_method_table_classifies_every_method_as_the_design_does` holds the table to
the brief's two sets; `_interleave_commits` patches the three modules that bind `in_one_transaction` by
name (`transactions`, `lifecycle`, `registry`) and asserts at least one interleaved transaction per verb,
so a verb that ran none fails rather than passes; `test_a_reads_lease_wait_and_retry_share_one_budget`'s
arithmetic — leases back at 0.5 budgets, the hold to 1.6, the bound 0.8–1.25 — refuses the unset-pragma
arm at about 1.5 as the brief says; `log.configure_service_log` builds its `FileHandler` without
`delay`, so `_log_stream()` finds an open stream at `faulthandler.register` time, before any record is
emitted; `write/tools.py` embeds in `writes.prepare` (`:189`) before `_in_one_transaction` (`:208`), and
`records/memory.py`'s four wrappers (`:417,495,883,959`) all sit on the primitive; no `BEGIN` literal
exists outside the three allowed modules and the recogniser does see an f-string's constant part;
`groups.search_all` reads the registry through `registry.lookup_all` (`groups.py:420`), a primitive
transaction on its pool connection, and the presence read answers an absent table for every read verb
in `test_a_store_without_the_registry_answers_as_an_empty_one_and_stays_without_it`; `_refusal` maps
`WriterClosedError` to `store_busy` whatever the deadline, as the brief requires; the design passages
the brief's top list names read as the code behaves — `architecture.md` §Planning (`:1676-1696`: the
snapshot, the fingerprint over both tiers, at most two plans, the halving, `next_group`'s three
transactions with the three run outcomes), the signal paragraph (`:828-839`: the `SIGUSR1`/`SIGUSR2`
split, `SIGHUP`/`SIGQUIT` deliberately uncaught), the stop-reason list (`:480`), §"The service's
connections" (`:959-1012`), `knowledge-index.md:1055-1063`, `schema.md:1982`, `README.md:685-686` and the
`:727` row with all four `hook.log` readings and the writer-lock-with-nothing-running case; the
done-when's rewrite list leaves no surviving copy — the only `fresh transaction` is `access_log.py:108`'s
legitimate use, `events.py:599` is narrowed to *answered within its deadline*, and `IMMEDIATE variant`,
`mid-request` and `covers the handler alone` match nothing in `zikaron/`; the research note's mutation
table carries both round-3 rows (`:116`, `:121`); and `test_the_margin_is_inside_the_hooks_own_deadline`
and `_REJECTION_KINDS`' `-32026` entry are as the brief's properties require.

VERDICT: NEEDS_CHANGES

### Author's response to round 4

1. **Accepted, with one more shape pinned.** `tests/test_transaction_begin_sites.py` recognises `BEGIN`, `COMMIT`, `ROLLBACK` (with `TO SAVEPOINT`), `SAVEPOINT` and `RELEASE` with the proposed pattern, and flags every `.commit()`/`.rollback()` call. `END` is left out for the reason given, and the module docstring states that reason. The recogniser test covers eight shapes. A new `test_a_case_expression_is_not_transaction_control` pins that a multi-line `CASE … END` is not matched. The docstring's first line and the offender test's name now say *transaction control*. The widened guard is green on landing: its only matches are the seven driver calls and three literals in the allowed modules. No mutation row was added, since the recogniser test is the evidence, as the finding says.
2. **Accepted.** `core/store/deadline.py` gains `now_ms()`, the wall clock in whole milliseconds rounded up, so a derived deadline errs early. `Deadline.from_caller` computes in integers and clamps at `-1`. `dispatch.surface_deadline` compares in integers through the same function and no longer imports `time` or `MS_PER_SECOND`. `10**400` joins the `bounds` parametrisation, and the past-deadline test is parametrised over `_deadline_in(-1)` and `-(10**400)`. With the float arithmetic restored, exactly those two cases go red (mutation recorded in the research note).

## Round 5 — 2026-09-30

### Summary judgment

Round 4's two items are in the tree as the response says, and I checked the mechanics rather than the
prose: `_TRANSACTION_CONTROL` (`tests/test_transaction_begin_sites.py:36-41`) matches every spelling
round 4 named and the eight-shape recogniser test plus the `CASE … END` negative pin it; the driver
recogniser reads `ast.Attribute.attr`, so `db.commit()`/`db.rollback()` are found whatever the handle is
called; `now_ms()` is `math.ceil` over the wall clock, `from_caller` subtracts in integers and clamps at
`-1`, `surface_deadline` compares in integers and excludes `bool` before `int`, and the two
parametrisations carry `10**400` and `-(10**400)`. This round went where no earlier verified list
reached: cancellation delivered inside the primitive, what the two dumps and the long-request line put
into a durable log, the in-flight registry's hashing and bracketing, the knowledge wrapper's `except`
set against the primitive's refusals, `create`'s atomicity under the autocommit round 1 added, the
fingerprint's predicate against the supersede path, and `consolidation.md`/`schema.md` for a surviving
single-connection claim. Every one holds. What remains is the done-when's own clause — *"every comment
and docstring that describes the pre-M35 mechanism is rewritten or removed"* — failed in one module and
its test, where the pre-M35 wrapper mechanism survives as dead code, an orphaned comment and a
docstring, and the dead code is a function-call alias of the commit decision that the widened guard
cannot see. Cheap to close; not approvable as-is by the same literal reading round 1 applied.

### Findings

1. **[IMPROVEMENT] The pre-M35 wrapper mechanism survives in `records/memory.py` as a re-export with
   no production caller, an orphaned comment, and a test docstring describing a `finally` that no
   longer exists.** `zikaron/core/records/memory.py:361-375`. Lines 361-364 are a `#:` block —
   *"The two codes invariant 10's rejection carve-out applies to are `store.transactions`'s to
   name…"* — followed by a blank line and a function: a doc-comment attached to nothing, left from
   the `_CARVE_OUT_CODES` constant that now lives at `transactions.py:62`. Lines 367-375 re-export
   `commit_or_roll_back` *"so that this module's own wrappers and the composing callers reading them
   see one name"* — but the four wrappers now sit on `transactions.in_one_transaction`
   (`:417,495,883,959`, round 4) and nothing under `zikaron/` calls this name; its only caller is
   `tests/test_records_memory.py:1273`. Walk the consequence rather than the tidiness: this is a
   plain function whose body is the driver's `COMMIT`/`ROLLBACK` decision, exported from the records
   module with a docstring inviting *composing callers* to use it. The widened guard sees
   `.commit(`/`.rollback(` by attribute name and `COMMIT`/`ROLLBACK` by literal; an `ast.Call` whose
   `attr` is `commit_or_roll_back` is invisible to it. A future caller reading that docstring and
   composing a transaction by hand on the writer would commit outside the holder's lock — ending
   whichever task's transaction is open on the handle, which `transactions.py:8-10` names as the
   reason there is one ladder — and the guard would stay green. The alias is therefore the one
   spelling of round 4's class that is still open, and it is dead code. The test half:
   `tests/test_records_memory.py:1442-1447` — *"`amend`'s own `finally: await
   commit_or_roll_back(db, error)` runs unconditionally … `amend`'s own `finally` block is the one
   place that actually commits them"* — and the comment at `:1469-1470`, *"survived amend's own
   finally block, because that block committed them"*, describe the pre-M35 wrapper; after M35 the
   commit is `transactions.finalize`'s, inside the primitive. **Fix, three edits.** (a) Delete
   `zikaron/core/records/memory.py:361-375` whole. (b) In `tests/test_records_memory.py`, move the
   `commit_or_roll_back` import at `:31` to `from zikaron.core.store.transactions import
   commit_or_roll_back` — `:1273`'s hand-composed transaction is a test driving the core directly on
   a single task, and the owner's inner decision is the right thing for it to call — and reword
   `:1244`'s *"the same way the wrapper does (`commit_or_roll_back`)"* to *"the same way the
   primitive's finalization does (`commit_or_roll_back`)"*; `:1291` and `:1330` name the function's
   contract rather than the wrapper's `finally` and stand. (c) Replace the docstring at `:1442-1447`
   with: *"`amend` runs on the transaction primitive, whose finalization commits for a
   `VERSION_CONFLICT` — one of `commit_or_roll_back`'s two carve-out codes — rather than rolling
   back: `_reject_version_conflict` itself only staged the receipt and event and raised, never
   touching the transaction, so the primitive's finalization is the one place that actually commits
   them. This test proves that end to end through the real public `amend` wrapper, and also checks
   the connection is left fully usable afterward."* and the comment at `:1469-1470` with *"The
   conflict's receipt and event survived the primitive's finalization, because it committed them —
   not because there was nothing left for a rollback to undo."* No mutation row: a deletion has no
   behaviour to revert, and the guard's recogniser is unchanged.

2. **[NITPICK] `_ALLOWED` exempts three whole modules where the docstring's reason is true of three
   functions.** `tests/test_transaction_begin_sites.py:28-34` and `:6-7`: *"both run before the
   socket exists: `store.py` creating a store, and `migration.py` moving one forward"*. That is
   true of `_create_tables_and_meta` and of the migration, but `store.py` now also holds `writer()`
   and `_open_checked`, which run under the socket, and a `BEGIN` added to either would pass the
   guard. Optional hardening: have `_control_lines` also yield the innermost enclosing
   `FunctionDef`/`AsyncFunctionDef` name, and assert the allowed modules' sites are exactly
   `{"_create_tables_and_meta"}` for `store.py`, `{"commit_or_roll_back", "finalize",
   "in_one_transaction"}` for `transactions.py`, and the migration's own function set — a predicate
   over names, not a count.

Verified and not raised, so the next round does not re-check them: the only cancellation a handler
task can receive mid-transaction is shutdown's (`RunningServer.close_all_connections`,
`server.py:440-442`); `_PLANNING_TIMEOUT_SECONDS` is enforced client-side in `mcp/consolidator.py`
(`:150`, `:271`) around the RPC, not around a service transaction, and `holders.acquire`'s and
`pool._take`'s `asyncio.timeout`s both sit before any `BEGIN` — so a `BEGIN IMMEDIATE` or `PRAGMA
busy_timeout` whose await is cancelled still runs on the worker thread with the lock released or
`budget_moved` unset, but only on a connection `ctx.close()` closes moments later; no `executescript`
call exists under `zikaron/` (its two mentions are docstrings), so the driver's implicit `COMMIT`
before a script is unreachable; `InFlightRequest.describe()` (`context.py:49-52`) emits
`method=… session=… age=…s` and `dump_tasks` prints frames without locals, so neither `SIGUSR2` nor
the long-request line puts a prompt or a gist into `service.log`; `InFlightRequest` is
`@dataclass(eq=False, slots=True)`, so the mutable entry hashes by identity, and `end_request` sits
in a `finally` around the whole of `_compute_response_line` (`server.py:105-109`), so an envelope
that fails to resolve leaks no entry to block idle self-stop; `_naming_the_store` catches
`aiosqlite.Error` and `OSError` alone (`dispatch_knowledge.py:551-562`), so a `WriterClosedError` from
inside `lifecycle.add._register` reaches `_invoke` and answers `store_busy` rather than
`store_unavailable`; `Store._create_tables_and_meta` issues an explicit `BEGIN` (`store.py:405`)
before its DDL, so creation stays atomic under `isolation_level=None`, and `ensure_table`'s docstring
(`registry.py:122-124`) states the autocommit consequence correctly; `_fingerprint` selects `active =
1`, and the supersede path (`records/memory.py:788`) sets `active = 0` and bumps `version` in one
statement, so an absorbed anchor leaves the fingerprint as a retired one does; `hook/push.py:66`
sends `int(...)`, `_DEADLINE_SECONDS = 2.0` against `BUSY_TIMEOUT_MS = 5000`, and `now_ms()`'s
round-up makes `surface_deadline`'s bound more permissive by under a millisecond, which moves
nothing; `design/consolidation.md` carries no single-connection or one-transaction claim about
planning, `schema.md:403-411` and `:915-926` speak of *"when every knowledge verb ran"* in the past
tense as struck history, and `architecture.md:2247` lists `deadline_at_ms?` on the RPC surface;
`research/m35-implementation-evidence.md:123` carries the round-4 mutation row; and the research
note is cited for no decision this round touches.

VERDICT: NEEDS_CHANGES

### Author's response to round 5

1. **Accepted, with one more site the finding did not list.** `records/memory.py`'s orphaned `#:` block and the `commit_or_roll_back` re-export are deleted. The module's four docstring references to that name now say `transactions.commit_or_roll_back`, through the transaction primitive. `core/indexing/writes.py:333` pointed at `records.memory.commit_or_roll_back` and now points at `store.transactions.commit_or_roll_back`. `tests/test_records_memory.py` imports the function from `store.transactions`, and its docstring and comment carry the proposed wording. Splitting `main.run` in round 1 also left `tests/test_service_main.py`'s close-masking docstring naming *"`run()`'s own outer `finally`"*. That now names the outer `finally` that `run()` reaches through `_open_and_serve`.
2. **Accepted.** `tests/test_transaction_begin_sites.py` keys its allowance on (module, innermost enclosing function): `transactions.py`'s `commit_or_roll_back`, `finalize` and `in_one_transaction`, `store.py`'s `_create_tables_and_meta`, and `migration.py`'s `migrate`. `test_every_allowed_function_still_issues_it` holds every allowance to a site that exists, so an unused one cannot linger. `test_a_site_is_attributed_to_its_innermost_function` pins the attribution: a nested function's site is its own, and a module-level one is nobody's. The module docstring names the two pre-socket functions and says why the allowance is per function.

## Round 6 — 2026-09-30

### Summary judgment

Round 5's two items are in the tree as the response says, and I checked the code rather than the
response: `records/memory.py` carries neither the orphaned `#:` block nor the re-export, and its four
docstring references (`:502`, `:577`, `:812`, `:844`) name `transactions.commit_or_roll_back` through the
primitive; `indexing/writes.py:333` points at `store.transactions`; `test_records_memory.py:40` imports
from `store.transactions` and `:1243-1249`/`:1470-1471` carry the proposed wording;
`test_service_main.py:219` names `_open_and_serve`; and `test_transaction_begin_sites.py` keys its
allowance on (module, innermost function), with `_walk` attributing every node to the nearest enclosing
`FunctionDef`/`AsyncFunctionDef`, `found >= _ALLOWED` holding each allowance to a live site, and the
five allowed functions matching exactly the sites in the code. This round went where no earlier
verified list reached: the pool's own lifecycle under the one cancellation a handler can receive, the
`Method` table's defaults, the consolidation dispatch against the snapshot's purity, the access log's
validate-before-transaction ordering, both diagnostics context managers against `main.run`, and the
brief's §"Done when" against the tree. One thing does not hold: the brief's property that every pool
connection is closed at shutdown fails in one cell of the perturbation walk that the walk marks as
holding — a handler cancelled while its lease is being *returned* — and the consequence is the
resident-process state the milestone's own diagnostics were written to end. Narrow window, small fix,
deterministic test; everything else I pushed on held.

### Findings

1. **[IMPROVEMENT] A handler cancelled while its lease is being returned strands the connection
   outside the pool, and the service process then never exits.** `zikaron/core/store/pool.py:61-64`
   (`lease`'s `finally: await self._give_back(db)`) and `:93-106`. `_give_back` suspends at three
   places: `_restored`'s `PRAGMA` (`:99`, only when a retry set `budget_moved`), and on the drop path
   `db.close()` (`:105`) and `_forget_one` (`:106`). A `CancelledError` delivered at any of them —
   `RunningServer.close_all_connections` cancels every handler task on the `SIGTERM`/`SIGINT` path and
   on `stop_on_encoder_failure`'s — propagates out of `lease`'s `finally` with the handle in neither
   `_idle` nor closed, and `_opened` still counting it; `close()` (`:113-120`) closes `_idle` alone. Walk
   the consequence: `Store.close()` returns, `ctx.close()` returns, `asyncio.run` returns, and the
   interpreter blocks joining the connection's non-daemon worker thread — the exact state
   `tests/conftest.py:308-311` and `connection.py:195-201` describe — so the process sits resident with
   the model loaded, its socket already unlinked and its `SIGTERM` handler already removed by
   `_stop_on_sigterm_or_sigint`'s `finally`, having written `stopping: reason=sigterm`. That is the
   "resident process" `stop_on_encoder_failure`'s docstring calls the worst state this service can be
   in, reached from a clean stop request, with the stop line saying the stop succeeded. The window is
   narrow — the cancel must land while the return is suspended, and only a read that retried, or a
   handle being dropped, suspends there — so it is a hardening of the same class as rounds 2 and 3, not
   a wedge on the ordinary path; the ordinary return (no retry) never suspends, since a free
   `Condition` is taken without yielding, and a cancel arriving *before* the return runs the
   `finally` to completion because a task is cancelled once. The perturbation walk's cell
   (`reviews/m35-brief-perturbation.md:56`, *"Cancelled. The lease is released in `finally` … Holds"*)
   covers that earlier arrival, not a cancel during the release itself, and the brief's property
   (`design/build-plan.md:5334-5335`, *"Pool connections are all closed at shutdown"*) rests on the
   autouse leak check, which no test drives through a cancelled return. (`_take`'s open path is not
   this: a cancel during `_opener()` reaches `open_connection`'s own `except BaseException` for
   everything after the connect, and the connect handoff itself is a pre-existing class shared by every
   caller of that function.) **Fix, in `pool.py`, with no await under cancellation:** add
   `self._abandoned: list[aiosqlite.Connection] = []` to `__init__`; wrap the whole body of `_give_back`
   after `holder.lease_deadline = None` in `try: … except asyncio.CancelledError: self._abandoned.append(db);
   raise`; and have `close()` take `abandoned, self._abandoned = self._abandoned, []` under the
   condition beside `idle` and close both lists, each `db.close()` under `contextlib.suppress(Exception)`
   since an abandoned handle may be half-closed (`aiosqlite`'s `close` is idempotent once
   `_connection` is cleared, and re-running it on one cut short finishes the stop). Leave `_opened`
   alone for the abandoned handles — `close` is terminal and the count means nothing after it — and
   keep `test_a_lease_out_when_the_pool_closes_is_closed_when_it_returns`'s contract, which the
   alternative of closing every leased handle at `close()` would break. `close`'s docstring becomes
   *"Close every idle connection, every leased one as its lease returns, and any whose return a
   cancellation cut short."* **Test**, in `tests/test_store_pool.py`:
   ```python
   async def test_a_lease_whose_return_is_cut_short_is_closed_with_the_pool(
       tmp_path: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       """A handler cancelled while its lease is being returned — a retry's pragma restore, a
       dropped handle's close — leaves the connection neither idle nor closed. It is closed with the
       pool, or its worker thread keeps the process alive after a clean stop."""
       async with open_context(tmp_path) as ctx:
           pool = ctx.store.pool
           restoring = asyncio.Event()

           async def _restore_that_never_returns(_db: aiosqlite.Connection) -> bool:
               restoring.set()
               await asyncio.Event().wait()
               return True

           monkeypatch.setattr(pool_module, "_restored", _restore_that_never_returns)
           leased: list[aiosqlite.Connection] = []

           async def one_read() -> None:
               async with pool.lease(Deadline.budget()) as db:
                   leased.append(db)

           task = asyncio.create_task(one_read())
           await restoring.wait()
           task.cancel()
           with contextlib.suppress(asyncio.CancelledError):
               await task
           await pool.close()
           with pytest.raises(ValueError, match=r"active connection|closed"):
               await leased[0].execute("SELECT 1")
   ```
   with `from zikaron.core.store import pool as pool_module`. Red today twice over — the `execute`
   succeeds on the open handle, and the autouse leak fixture then fails the test for the thread it
   left — and green with the fix. Add the row to `research/m35-implementation-evidence.md` §"Every
   guard, shown red" (*a cancelled return leaves the handle outside `close()`*), and mark the walk's
   cell at `m35-brief-perturbation.md:56` as split: before the release holds as written; during it,
   forced.

2. **[NITPICK] `zikaron/core/store/deadline.py:7-8`** — *"Most requests get the service's own budget,
   `ddl.BUSY_TIMEOUT_MS` from when they started"* is true of a read and not of a write, whose budget
   starts at each `BEGIN`, after its embed — the asymmetry round 1 item 3 settled and
   `architecture.md:992-995` and `server._connection`'s docstring now state. This module is where the
   two instants are defined, so it should carry the same split: *"`ddl.BUSY_TIMEOUT_MS` from when the
   wait is asked for — a read's dispatch, a write's own `BEGIN`"*.

Verified and not raised, so the next round does not re-check them: `in_one_transaction`'s ordering —
`acquire`, then the pragma and `BEGIN` under the failure map, `finalize` in the inner `finally` seeing
`error` for a driver failure and a `BaseException` alike, and `holder.release()` in the outer `finally`
so the lock spans finalization; `ReadPool._take` counts `_opened` before the open and `_forget_one`s on
any failure, and registers the handle `sets_budget=True`; `_restored` returns without awaiting when
`budget_moved` is unset, so the ordinary return has no suspension point; `Method`'s defaults
(`_service_budget`, `_unnamed`) and the two tables' classifications match the brief's two sets, `fetch`
a write and `surface` alone carrying `surface_deadline`; `dispatch_consolidation.next_group` waits on
`encoder_load.failure` off the loop before `serving.next_group`, and `plan_groups`'s handler holds the
writer's handle but not its lock while `snapshot` leases; `grouping.py` contains no `INSERT`, `UPDATE`,
`DELETE` or `log_event`, so the snapshot's deferred transaction cannot meet `SQLITE_BUSY_SNAPSHOT`;
`serving.next_group`'s three transactions and the `RuntimeError` for a plan neither written nor
superseded; `AccessLog.record` validates the payload before the primitive, swallows contention, and stops
on `WriterClosedError` through `except Exception`; `thread_dump_on_signal` is a plain context manager
wrapping `_open_and_serve` from `main.run`, and `task_dump_on_signal` sits beside the signal pair before
`serve`; `log_long_requests` runs on every idle poll before `may_stop`; `open_connection` passes
`isolation_level=None` in both branches; `migration.migrate` opens `BEGIN IMMEDIATE` and re-reads the
version inside it; `hook/push.py` reads `time.time()` at `started_at`, scopes `except TimeoutError` to
`surface_once`, and `_REJECTION_KINDS` carries `-32026`; the drift guard's `_TRANSACTION_CONTROL` does
not match `PRAGMA busy_timeout = `'s constant part, and a lambda's site is attributed to its enclosing
function, which is not a hole in today's tree; `architecture.md:959-1033` reads as the code behaves; and
the brief's §"Done when" rewrite list and README rows were verified in rounds 3 and 4 and nothing in this
round's changes touched them.

VERDICT: NEEDS_CHANGES

### Author's response to round 6

1. **Accepted, as proposed.** `ReadPool` keeps `_abandoned`. `_give_back`'s body is wrapped so that a `CancelledError` records the handle there, unless it already reached `_idle`, and re-raises. `close()` takes the list under the condition beside `_idle` and closes each abandoned handle under `contextlib.suppress(Exception)`. `_opened` is untouched, and so is the leased-when-closed contract. The docstring carries the proposed wording, plus the shutdown ordering that makes a cut-short return after `close()` unreachable: handlers are cancelled and awaited before the store closes. The proposed test is in `tests/test_store_pool.py`. With the record removed it is red twice, as predicted: the assertion, and then the thread-leak fixture (mutation recorded in the research note). The walk's cell in `reviews/m35-brief-perturbation.md` is split into *before the release* (holds) and *during it* (forced).
2. **Accepted.** `deadline.py`'s module docstring says the budget runs from when the wait is asked for: a read's dispatch, or a write's own `BEGIN`.

## Round 7 — 2026-09-30

### Summary judgment

Round 6's two items are in the tree as the response says, and I checked the mechanics against the
installed driver rather than the prose: `_give_back` (`zikaron/core/store/pool.py:96-114`) wraps every
suspension point of a return — the pragma restore, the condition's lock, the drop path's `close()` and
`_forget_one` — and records the handle on `CancelledError` unless it already reached `_idle`, which no
await after `append` can make true; `close()` takes the list under the condition and closes each under
`suppress`. Against `aiosqlite` 0.22.1 the list is load-bearing for exactly the two cuts that leave a
handle fully open (the restore, the lock) and harmless for the third, since that driver's `close()`
clears the handle and awaits the worker's stop in its own `finally` even when the await is cancelled. The
test drives the load-bearing path and the evidence row is present (`research/m35-implementation-evidence.md:117`).
This round went where no earlier verified list reached — the knowledge subsystem's transactions outside
the three sites the brief names, the brief's seven items read against the tree end to end, the property
list against `tests/test_service_surface_deadline.py`, and the four normative passages as they now stand —
and found nothing that fails the brief, the design or the standards. Two optional points remain, one a
docstring that attributes the stop to the wrong call and one a timing assertion whose kill margin equals
the host's scheduling jitter; neither changes what ships.

### Findings

1. **[NITPICK] `ReadPool.close`'s docstring attributes a cut-short handle's stop to the second
   `close()`, and on the installed driver it is the first.** `zikaron/core/store/pool.py:125-126`:
   *"An abandoned handle may be half-closed already, so its close is suppressed; `aiosqlite`'s `close`
   finishes the stop a cut-short one began."* In `aiosqlite` 0.22.1 (`core.py:199-214`) a `close()`
   whose `await self._execute(self._conn.close)` is cancelled runs its `finally`: `_connection = None`,
   `stop()` queues the sentinel with `_running = False`, and it awaits that future before the
   `CancelledError` goes on — so the cut-short call finishes its own stop, and the `close()` here on
   that handle returns at line 202 having done nothing. What the abandoned list actually rescues is a
   handle left *fully open*, cut in `_restored`'s pragma or at the condition's lock. The outcome the
   docstring promises holds; the mechanism it names does not, and a later editor reading it could
   conclude the second close is what covers the drop path. Reword to: *"An abandoned handle is either
   fully open — the cut landed in the pragma restore or at the condition's lock — or already stopped,
   since `aiosqlite`'s `close` finishes its own stop in a `finally` even when cancelled; so the close
   here is real for the first and a suppressed no-op for the second."*

2. **[NITPICK] `test_a_writers_hold_past_the_deadline_answers_deadline_passed_and_commits_nothing`
   pins the margin with a kill margin the size of the margin itself.**
   `tests/test_service_surface_deadline.py:97-101`: `deadline_at_ms = _deadline_in(0.6)` and
   `assert elapsed < 0.6`. Walk the arithmetic: the retry's `busy_timeout` is the remainder to the
   deadline less `DEADLINE_MARGIN_MS` (20 ms), so the service refuses at about 580 ms plus the first
   attempt's pass; the assertion has roughly 15 ms of headroom, and the mutation it exists to catch —
   a retry waiting to the whole deadline rather than the remainder before the margin — lands at about
   605 ms, 5 ms over the bound. Both distances are inside the scheduling jitter of the host the
   evidence note ran at (load 6.5–7.8), so the test can go red for the host's reason and green for the
   mutation's. The same assertion is what separates this arm from a retry waiting the connection's
   whole pragma (5 s), which any bound under a second does. Make the margin the measured quantity
   rather than an incidental 20 ms: `monkeypatch.setattr(dispatch, "DEADLINE_MARGIN_MS", 300)` in
   this test (`surface_deadline` reads the module global at call time), keep `_deadline_in(0.6)`, and
   assert `elapsed < 0.45` — the retry then ends at about 300 ms, a mutation that ignores the margin
   at about 600, and the kill margin becomes 150 ms. `test_the_margin_is_inside_the_hooks_own_deadline`
   is unaffected, since it reads the unpatched constant in its own test.

Verified and not raised, so the next round does not re-check them: every suspension in `_give_back` is
inside the `try` — `_restored`'s `execute`, the condition's `__aenter__`, `db.close()` and
`_forget_one`'s `__aenter__` — and `Condition.__aexit__` releases synchronously, so no cancel can land
after `_idle.append`; `_forget_one` has no cancellation point after `_opened -= 1`; `_abandoned` is
appended outside the condition and read under it, with no await between the append and the re-raise;
`close()` is idempotent in practice, which `open_context`'s exit after an explicit `pool.close()` relies
on in two tests; `close_all_connections` cancels a live handler once on its ordinary path, so a
cut-short `close()`'s own `await future` in the driver's `finally` is not cancelled a second time; the
knowledge subsystem's transactions outside the three sites the brief moved — `disposal.py`'s three,
`repair.drop_derived`, `lifecycle.unlock`'s `force_release`, `scan.py`'s six, `counters.py`'s and
`database.py`'s — all run on a corpus connection's bare holder, deferred, `_record_indexed` embedding
before its transaction; `lifecycle.unlock` and `lifecycle.remove` each resolve the corpus through
`registry.lookup` in a transaction of its own and open the corpus outside it; `ensure_table`'s two
callers (`lifecycle.add._register`, `registry.ensure`) each sit inside a primitive transaction on a
writer; `planning.snapshot` leases under `Deadline.budget()`, runs its one deferred transaction, and
releases before either caller takes the writer, and `serving.next_group`'s three outcomes at step 3
match the brief's (`_run_for`: none or lapsed → plan, own → serve from it, stranger → `Busy`); the
brief's items 1–7 each read against the tree hold — the primitive's two arguments and the mode following
the holder, the method table, the one-retry-from-`IMMEDIATE` and its four `surface` check points, the
snapshot-then-`IMMEDIATE` plan, the two dumps and the long-request line, the corpus lock's
`IMMEDIATE`-from-no-holder, the completion callback, and `deadline_at_ms` validated whole before the
lease; `_refusal` maps `LockWaitExpired(set_by_caller=True)` to `deadline_passed` and everything else to
`store_busy`; the `surface` check points refuse only a caller's deadline, so `search` under the service
budget commits a late pass; `hook/rpc.surface_once` sends `deadline_at_ms` as the integer the hook
computed at `started_at`; every property in the brief's list has a test in
`test_service_surface_deadline.py` asserting rows and codes, the `call` row asserted only where the
write lock is free; `architecture.md:959-1033`, `retrieval.md:247-273`, `README.md:681-688` and the
`:727` row read as the code behaves after round 6; and the perturbation walk's cell (`:56-61`) is split
as the response says.

VERDICT: APPROVED

### Author's response to round 7

Both nitpicks applied, though the verdict did not require them.

1. **Accepted.** `ReadPool.close`'s docstring carries the proposed wording: an abandoned handle is either fully open, and closed here for real, or already stopped by its own cancelled `close()`, and closed here as a suppressed no-op.
2. **Accepted.** The held-writer test patches `dispatch.DEADLINE_MARGIN_MS` to 300, keeps `_deadline_in(0.6)`, and asserts `elapsed < 0.45`, with a docstring sentence saying why the margin is widened. It passed three times in a row on this host. With `surface_deadline` passing `margin_ms=0` it goes red (mutation recorded in the research note).

## Round 8 — 2026-09-30

### Summary judgment

Round 7's two nitpicks are in the tree as the response says, and I checked the mechanics rather than
the prose. `ReadPool.close`'s docstring (`zikaron/core/store/pool.py:122-130`) carries the proposed
wording, and it is true of the code: the two cuts that leave a handle fully open are the only awaits
in `_give_back`'s idle path (`_restored`'s `execute` at `:103`, the condition's `__aenter__` at `:104`),
and its closing sentence — the service cancels its handlers before it closes the store — rests on the
one `cancel()` a connection task can receive, `close_all_connections` at `server.py:442`; a client
disconnect is `ConnectionResetError`/`BrokenPipeError`, caught at `server.py:324` and returned from,
so no handler enters `_give_back` under cancellation outside shutdown, and an abandoned handle's
`_opened` slot is never a live pool's loss. The retimed test
(`tests/test_service_surface_deadline.py:85-106`) patches `dispatch.DEADLINE_MARGIN_MS` to 300,
keeps `_deadline_in(0.6)` and asserts `elapsed < 0.45`; `surface_deadline` (`dispatch.py:185`) reads
the module global at call time and hands it to `Deadline.from_caller`, which subtracts it in integers
(`deadline.py:64`), so the patched margin is what the retry's `busy_timeout` is set from, the retry
ends at about 300 ms, the margin-ignored mutation at about 600, and the kill margin is 150 ms rather
than round 7's 15. The evidence row (`research/m35-implementation-evidence.md:128`) names the test
and the mutation. No other copy of the mechanism the docstring fix replaced exists outside `pool.py`
and this file. Nothing new to raise.

### Findings

None.

Verified and not raised, so the next round does not re-check them: the `_deadline_in(0.6)` value
passes `surface_deadline`'s bound, which is against `ddl.BUSY_TIMEOUT_MS` and not the margin; the
first attempt's upgrade is refused without a busy-handler wait, since SQLite invokes the handler on
`BEGIN`-time contention only while no read transaction is open on the btree, which is why the test's
elapsed time is the retry's wait alone; `test_the_margin_is_inside_the_hooks_own_deadline` reads the
unpatched constant, since `monkeypatch` is restored per test; and the `asyncio.timeout`s in `_take`
and `holders.acquire` sit before the lease body and before any `BEGIN`, so neither can deliver its
cancellation into `_give_back`.

VERDICT: APPROVED

## Round 9 — 2026-09-30

Scope, per the brief: `git diff f5bb459 474c146` and whatever that diff made false outside itself.
No shell was available to this round, so the diff was reconstructed by reading the current tree
against the brief's description and the round 7/8 record of what `f5bb459` contained.

### Summary judgment

The code half of the change is sound and I could not fault the poll. It terminates — every refusal
either raises or sleeps no longer than the remainder — lands within one attempt of the deadline on
either side of a timer that fires early, propagates a non-contention refusal at once, and leaves
nothing open on cancellation except in the pre-existing case of a cancel landing inside a
*successful* `BEGIN`, which this diff neither created nor widened. Every serving handle is at zero on
all three open paths; the only statements that waited in SQLite before — the writer's
`BEGIN IMMEDIATE`, a read's retry, the indexer's build row on a `Store` writer — now poll under the
same 5 s budget, and open, migration and table creation keep SQLite's wait and run before the serving
pragma. `BuildLog.succeeded` was dead by construction, and the serving split is equivalent to the
three step-3 outcomes round 7 verified. What fails the round is the design record: `design/build-plan.md`
§M35 still specifies the pragma-to-the-remainder mechanism and the pool's restore, so the brief the
implementation is held to now contradicts `architecture.md` on exactly the mechanism this change
introduced; and three sentences elsewhere name a connection's `busy_timeout` as the length of a wait
on a handle whose pragma now reads 0.

### Findings

1. **[BLOCKER] `design/build-plan.md` §M35 still specifies the mechanism this diff replaced, so the
   two `design/` files now disagree on it.** `FINDINGS.md` names §M35 as *"what the implementation is
   held to"*, and `CLAUDE.md` puts `build-plan.md` in scope and requires a refuted sentence to be
   replaced. Six passages state the old design as the specification:
   - `design/build-plan.md:4733-4739` — *"On the writer, it then sets `PRAGMA busy_timeout` to the
     remainder before `BEGIN IMMEDIATE` … **The pragma is set on exactly two holders** … a leased pool
     connection is exclusive, and waits only inside SQLite, on a read's retry."*
   - `:4872-4877` — *"The primitive sets the leased connection's `busy_timeout` to what remains before
     the retry's `BEGIN IMMEDIATE` … and the pool restores the store's value when the lease returns …
     A returned connection whose closed mark is set is dropped without the restore, which would
     otherwise raise `ValueError`…"* — the restore, `_restored` and the `ValueError` hazard no longer
     exist (`pool.py:91-107`).
   - `:5118-5119` — *"its `busy_timeout` is set to the remainder before it, not to the whole deadline."*
   - `:5124-5126` — *"The pragma is a whole number of milliseconds, so the refusal can land a fraction
     of a millisecond before the instant a clock comparison would demand."* The rule it justifies
     (decide by bound, not by a second clock read) still holds and `reads._retry_failure_map` still
     implements it, but the stated reason is now false: `_begin_immediate_by_polling` raises only
     once `deadline.passed()` is true (`transactions.py:188`), so the refusal lands at or after the
     instant, never before it.
   - `:5253` — *"so the pool's opened pragma is the budget too"* and `:5256` — *"because the retry
     then waits the connection's whole pragma."*
   This withdrawal is load-bearing in `CLAUDE.md`'s sense: setting the pragma to the remainder is the
   obvious design, a reader who never saw it would re-propose it, and it was refuted by measurement.
   So at `:4733-4739` strike and correct rather than replace, e.g.: *"~~On the writer, it then sets
   `PRAGMA busy_timeout` to the remainder before `BEGIN IMMEDIATE` … [through] … whose pragma stays
   what it was opened with.~~ **Withdrawn on measurement, and the withdrawal is load-bearing**: with the
   SQLite uv's managed Python ships, SQLite's busy handler overran the pragma by 0.6–1 s at
   `BEGIN IMMEDIATE` on macOS (`research/m35-implementation-evidence.md` §"SQLite's own wait on
   macOS"), so no value of the pragma bounds the wait. The store's serving connections — the writer,
   every pool connection, a reopened writer — run at `busy_timeout = 0` once the store is open
   (`ddl.SERVING_PRAGMA`), and the primitive retries a refused `BEGIN IMMEDIATE` itself, pausing 1 ms
   doubling to 25 ms, until the deadline (`architecture.md` §"The service's connections"). A holder
   created for a bare handle is left to SQLite's own wait. The primitive computes the lock-wait
   deadline on every holder, but only the writer's lock is ever contended; a leased pool connection is
   exclusive, and polls only on a read's retry."* The other five are plain replacements: at
   `:4872-4877` *"The deadline travels with the leased handle (`pool.lease_deadline`), and the retry's
   `BEGIN IMMEDIATE` polls for the write lock only until it; a pool connection's own `busy_timeout` is
   0 and nothing sets or restores it. A returned connection whose closed mark is set is dropped."*; at
   `:5118-5119` *"The retry's `BEGIN IMMEDIATE` polls no later than the deadline less the margin, not
   to the whole deadline."*; at `:5124-5126` *"That is decided by which bound cut the wait, never by a
   second reading of the clock: the refusal is the deadline's own, so the mapping is fixed when the
   deadline is."*; at `:5253` *"a serving connection's pragma is 0 whatever it opened with, so the
   patched constant is the whole wait"*; at `:5256` *"because the retry then polls a whole budget of
   its own."* Optionally `:4741`'s *"itself in SQLite's busy handler"* → *"itself polling for the write
   lock"*.

2. **[IMPROVEMENT] Four sentences name a store connection's `busy_timeout` as the length of a wait
   that is now the primitive's budget on a pragma that reads 0.** Behaviour is unchanged — the wait is
   still `BUSY_TIMEOUT_MS` — but a reader who checks `PRAGMA busy_timeout` on the writer or the
   indexer's handle sees 0 and concludes the row is dropped at once.
   - `design/schema.md:896-900` — *"Every connection this store opens carries `PRAGMA busy_timeout =
     5000` (`core/store/ddl.py`) … An access-log write inheriting that timeout would put **five seconds
     of the caller's latency** behind a lock"*. False for every serving connection since this diff.
     Suggest: *"Every connection this store opens carries `PRAGMA busy_timeout = 5000` at open
     (`core/store/ddl.py`); once the store is open its serving connections drop to zero and the
     transaction primitive polls for the write lock for the same `BUSY_TIMEOUT_MS` (`architecture.md`
     §"The service's connections"), and the seam returns its response line only after everything
     before the `return` completes. An access-log write on the writer, queued behind that lock and
     that budget, would put **five seconds of the caller's latency** behind a lock it has no stake in."*
     This also gives `schema.md` its one pointer to the serving override, which the DDL block at `:52`
     otherwise leaves a reader to infer.
   - `zikaron/knowledge/indexer/build_log.py:17-19` — *"So the write takes its connection's ordinary
     `busy_timeout` and swallows contention only after it"*. The connection is `scope.py:102`'s
     `Store.open` writer, at 0, polling under `Deadline.budget()`. Suggest: *"So the write polls for
     the write lock for the primitive's whole budget, `ddl.BUSY_TIMEOUT_MS`, and swallows contention
     only after it"*. (`_write`'s own docstring at `:183-184` already says *"the connection's budget"*.)
   - `design/schema.md:1978-1979` — the same sentence; same replacement.
   - `design/knowledge-index.md:114-115` — *"which waits its connection's ordinary `busy_timeout`"* →
     *"which waits the transaction primitive's whole budget for the write lock"*.

3. **[NITPICK] Residual phrasings that still place the serving wait inside SQLite.**
   - `zikaron/core/store/deadline.py:3-4` — *"for a connection's lock, for a pool lease, inside
     SQLite's busy handler"* → *"for a connection's lock, for a pool lease, for the write lock"*.
   - `tests/test_service_writer.py:104-106` — *"The first waits in SQLite … whether its
     connection-lock wait or SQLite refuses it"* → *"The first polls for the write lock … whether its
     connection-lock wait or the poll refuses it."*
   - `zikaron/core/errors.py:264` — *"an exhausted `busy_timeout` is the common case"* → *"an
     exhausted wait budget is the common case"*.
   - `design/schema.md:1010` and `:1390` — *"though the handler's `busy_timeout` expired seconds
     earlier"* → *"though the handler's wait budget expired seconds earlier"*.

4. **[NITPICK] `ExternalWriter` serializes `commit_a_write` and `close` but not `hold`/`release`, and
   `release` runs from `call_later` on the loop thread.** `tests/contention_fixtures.py:46-58`. No
   current test overlaps `release_after` with a `commit_a_write` worker on one instance (checked every
   caller: `test_service_write_contention.py`, `test_indexing_writes.py:658`, and the `hold()` sites in
   `test_service_writer.py`, `test_service_read_contention.py`, `test_service_surface_deadline.py`), so
   the fixture is safe as used. But the docstring's *"every use of the connection off the loop thread
   is serialized"* leaves a `ROLLBACK` from the loop thread free to race a worker's `INSERT` in the
   first test that combines the two — the same *API misuse* class this diff fixed. Make `_in_use` a
   `threading.RLock` and take it in `hold` and `release` as well (re-entrant so `close` → `release`
   does not deadlock).

5. **[NITPICK] `test_a_write_lock_freed_during_the_wait_is_taken` says "within a poll" and allows
   700 ms.** `tests/test_service_writer.py:147-158`: `0.3 <= elapsed < 1.0`. The recorded mutation
   (tried once → `store_busy`) is caught by `error_of`, not by the bound; a pause cap of several
   hundred milliseconds would pass. Either measure the primitive directly on `ctx.store.connection`
   with `_noop`, as `test_the_wait_for_the_write_lock_ends_at_the_deadline` does, and assert
   `elapsed - 0.3 < 4 * transactions._LONGEST_POLL_SECONDS`; or keep the verb and tighten to
   `elapsed < 0.5`, which still leaves the remember's own work 200 ms on a loaded runner.

6. **[NITPICK] `FINDINGS.md:91`'s lead sentence is stale against what this round's brief reports.**
   *"PR #14's required macOS job is red, and the fix is in progress"* — the paragraph was written in
   this diff (it names `1a79e02` and the fixture lock), and the brief says all four jobs are green on
   `474c146`. Reword to *"PR #14's required macOS job was red on `f5bb459`; the fix is in the tree and
   all four jobs are green on `474c146`"*, and drop the *"measured: two in flight"* narrative, which
   `CLAUDE.md` §"Project memory" routes nowhere.

Verified and not raised, so the next round does not re-check them: **the poll** — a refusal that is not
contention raises through `_raise_mapped` at once, and a `sqlite3.ProgrammingError` on a closed handle
carries no `sqlite_errorcode` so propagates as itself; `is_contention` masks the primary code, so
`SQLITE_BUSY_RECOVERY` and `SQLITE_BUSY_SNAPSHOT` are retried; the last sleep is `min(pause,
remaining())`, so the overrun is one attempt, and a timer that fires a tick early costs one extra
sub-millisecond attempt before `passed()` turns true; a past caller deadline still gets its one
attempt and is refused on the first refusal; `CancelledError` escapes the inner `try` (which catches
`aiosqlite.Error` only) to the outer `finally`'s `holder.release()`, with no transaction open when the
cut lands in `sleep` or a refused attempt, and a cut inside a *successful* `BEGIN` leaves one open
exactly as the single `execute` did before this diff, with shutdown's the only cancel a handler
receives (round 8). **Every serving connection at zero** — `Store.create` sets `SERVING_PRAGMA` after
`_create_tables_and_meta` inside the umask block and closes on failure; `Store.open` sets it after
`_validate_on_open`, so the `meta` read and `migration.migrate` keep SQLite's 5 s; `_open_checked`
applies `PRAGMAS` then `SERVING_PRAGMA`, last write winning, for the pool and the reopened writer; the
three `hold()` sites hand exactly those handles; `test_store.py:868-890` pins create and open and
`test_store_pool.py:142` the three. **Nothing else relied on SQLite's wait on a serving handle** — no
`wal_checkpoint`, `VACUUM`, `ANALYZE` or `PRAGMA optimize` anywhere in `zikaron/`;
`registry.ensure_table`'s `CREATE TABLE IF NOT EXISTS` runs inside an `IMMEDIATE` primitive
transaction on a writer, lock already held; a deferred read's upgrade never invoked the busy handler;
a WAL reader's `BUSY_RECOVERY` arises only for the first opener of the shm, which is `Store.open`'s
`meta` read at 5 s; the access log was at zero already; corpus handles are unregistered and keep
their own pragma; the last-connection WAL cleanup on close does not use the busy handler. **The
indexer's build row** — `scope.py:102` opens through `Store.open`, so the row polls under
`Deadline.budget()`, the same 5 s. **`BuildLog.succeeded` was dead** — `lifecycle.refresh:313-317`
returns only after `scan.run` returns, `scan.run:439-448` returns only through its `else`, which calls
`on_completion`, `main.build:122` always passes `log.settle`, and a `reporting.observe` failure lands in
`build`'s catch after the latch; `schema.md:1117-1130` and `main.py:85-94` say so. **The serving
split** — `_plan_then_serve` re-asks `_run_for` inside the `IMMEDIATE` transaction, plans only on
`None` (absent or lapsed, which `plan_within_transaction`'s `_close_previous` closes) and
`plan_within_transaction` returns `Run`, returns `Busy` untouched, serves an own run;
`next_group_within_transaction` returns `None` only when `_run_for` does, which is what `next_group`
keys the snapshot on; `at` is read once per transaction; `_serve_from` is bounded by `n_groups`.
**The pool** — `_give_back`'s idle path has one await, the condition, so `_abandoned` is still
load-bearing for exactly that cut and the docstring at `pool.py:118-122` matches. **Tests** —
`test_the_wait_for_the_write_lock_ends_at_the_deadline` bounds the overrun at 125 ms against a poll that
ends within one attempt; `test_a_writers_hold_past_the_deadline…` is unaffected by the mechanism;
`test_transaction_begin_sites.py` allows `_begin_immediate_by_polling` and holds the allowance to an
existing site. **Prose** — `holders.py`, `transactions.py`, `ddl.py`, `pool.py`,
`architecture.md:1002-1011`, `retrieval.md:267-274` and `schema.md:955-962` read as the code behaves.

VERDICT: NEEDS_CHANGES

### Author's response to round 9

1. **Accepted.** `design/build-plan.md` §M35's pragma-to-the-remainder paragraph is struck and corrected in place, as proposed, because the withdrawal is load-bearing. The other five passages are replaced with the proposed text, and `:4741` now reads *"itself polling for the write lock"*. A sweep of §M35 for the same class found five more, all replaced:
   - the writer's `IMMEDIATE` bullet (*"waits for the write lock within the budget"*);
   - the bare-holder bullet, which had said the indexer's budget *"equals the pragma it opened with"*;
   - item 2's *"whole milliseconds"* rationale, now the event loop firing a timer a clock tick early, which is the reason that still holds;
   - the build row's cost (*"a 5 s wait for `memory.db`'s write lock"*);
   - the writer-budget property, *"or the poll for the write lock"*.

   The self-nesting paragraph's *"waiting on itself for `busy_timeout`"* is now *"for the whole budget"*.
2. **Accepted.** `schema.md`'s best-effort paragraph carries the proposed wording, with the pointer to the serving override. `schema.md`'s build-row paragraph, `knowledge-index.md:114-115` and `build_log.py`'s module docstring now say the row polls for the primitive's whole budget.
3. **Accepted.** `deadline.py`, `tests/test_service_writer.py`'s two-writer docstring, `errors.py:264`, and `schema.md`'s two *"handler's `busy_timeout` expired"* now say *"wait budget"* or *"the write lock"*, as proposed.
4. **Accepted in substance, fixed differently.** Adding `hold` and `release` under the same lock would deadlock. A worker's `commit_a_write` holds the lock while SQLite waits for the write lock, and `release`, which frees that write lock, would block on the fixture lock on the loop thread. So the sharing is removed instead:
   - each `commit_a_write` opens its own connection, as another process would;
   - the held connection goes back to `sqlite3`'s default `check_same_thread`, so a future cross-thread use raises instead of racing;
   - the fixture lock is gone.

   Every file that uses the fixture passes.
5. **Accepted, the direct form.** The test now drives the primitive on `ctx.store.connection` with `_noop` and asserts the lateness after the release is under a fixed 100 ms. The bound is fixed rather than computed from `_LONGEST_POLL_SECONDS`, because the first version read the constant and survived a mutation raising the cap to 400 ms: the bound moved with it. With the literal it goes red under that mutation, and the row is in the research note.
6. **Accepted.** `FINDINGS.md`'s paragraph now states the green result and where the evidence and the review trail are, and drops the narrative.

## Round 10 — 2026-09-30

Scope, per the brief: `git diff f5bb459 0082391` and whatever that diff made false outside itself. No
shell was available to this round either, so the diff was taken as the round 9 record plus the
brief's list of what moved since, each read in the current tree.

### Summary judgment

Round 9's six items are in the tree as the response says, and the two it fixed differently are fixed
right. The fixture change is the correct one: locking `hold`/`release` under the same lock as
`commit_a_write` would deadlock exactly as the response argues — a worker holding the fixture lock
while SQLite waits on the lock the held connection owns, and the loop-thread `release` that would free
it blocked on the fixture lock — and giving each worker its own connection removes the shared object
rather than guarding it. Every caller still gathers its workers inside the `with`, and every use of the
held connection is on the loop thread, so `sqlite3`'s default same-thread check is a real guard rather
than a formality. The rewritten freed-lock test now measures the property it names, and its fixed
bound is the right choice over one read from the constant. `design/build-plan.md` §M35 now agrees with
`architecture.md` and the code on the mechanism, and the struck paragraph is struck for the right
reason. What remains is residue of the class round 9 raised, none of it in code: one verbatim copy of
the build-row sentence round 9 replaced, surviving in the test that pins that wait, and `FINDINGS.md`
naming a commit the amend has already moved past and a verdict round 9 reversed.

### Findings

1. **[IMPROVEMENT] The sentence round 9's finding 2 replaced in `build_log.py` survives verbatim in
   the test that asserts the wait.** `tests/test_knowledge_build_log.py:484-486`: *"a build has just
   spent minutes and that row is the only record of them, so it takes its connection's ordinary
   `busy_timeout`."* The connection is `scope.open_store`'s writer, whose pragma is 0 since this diff,
   and the test's own assertion — `elapsed < ddl.BUSY_TIMEOUT_MS / MS_PER_SECOND`, *"it gave up rather
   than waiting"* — is the one place the poll on the build's path is pinned; a reader who checks the
   pragma reads the docstring as saying the wait is zero and the assertion as testing nothing. `:397`
   says the same in the driver-arm test: *"A build waits its full `busy_timeout` rather than dropping
   its row"*. Suggest `:486` → *"so it polls for the write lock for the primitive's whole budget,
   `ddl.BUSY_TIMEOUT_MS`"* and `:397` → *"A build polls for the write lock for its whole budget rather
   than dropping its row"*. (The claim itself holds: `_build_against_a_briefly_held_lock` holds the lock
   for 0.2 s and the build's first `IMMEDIATE` transaction on the writer polls through it.)

2. **[IMPROVEMENT] `FINDINGS.md` names the commit the amend moved past, and a verdict this diff
   reversed.** `FINDINGS.md:91-92`: *"all four jobs and Codecov's patch (100%) are green on
   `474c146`"* — the branch's head is `0082391` (one commit per PR, amended and force-pushed after
   round 9), so `474c146` is reachable from the reflog alone and gone at the next `gc`; and the
   paragraph is slated to move to `FINDINGS-archive.md` verbatim on merge, where it would record a
   green run on a commit that no longer exists. `FINDINGS.md:86`: *"the implementation review is
   `reviews/m35-review.md` (APPROVED, every nitpick closed)"* — round 9, which this diff carries,
   returned `NEEDS_CHANGES`, so the sentence pins a verdict the file it points at contradicts, and it
   will be wrong again after any later round. Suggest `:91-92` → *"PR #14's required macOS job was red
   before the fix; the fix is in the tree, and all four jobs and Codecov's patch (100%) are green on the
   PR's current head (`gh pr checks`)"*, and `:86` → *"the implementation review is
   `reviews/m35-review.md`, whose last round is the verdict"*. `:97`'s *"bounded to `git diff
   f5bb459..HEAD`"* is the operator's own scope and can stay, but `f5bb459` is amended-away too, so
   say *"(reflog only)"* beside it or the instruction stops working at the same `gc`.

3. **[NITPICK] Residual phrasings that still place a serving wait in SQLite, or name the pragma as the
   budget.** Meaning survives in each; the fix is a word or two.
   - `design/build-plan.md:4749` — *"would wait 5 s for the lock and 5 s more for SQLite's"* → *"5 s
     more polling for the write lock"*; and its twin in the normative paragraph,
     `design/architecture.md:997-998` — *"one budget for the connection and another for SQLite"* →
     *"another for the write lock"*, since the very next paragraph says that wait is the primitive's,
     not SQLite's.
   - `design/build-plan.md:5306` — *"A writer's total wait, lock plus SQLite"* → *"connection lock plus
     write lock"*; the bullet's body was already rewritten and its header was not.
   - `design/build-plan.md:5232` — *"not after `busy_timeout`"* → *"not after the budget"*; the
     self-nesting paragraph at `:4765-4768` was fixed and this property bullet restates it.
   - `design/build-plan.md:5056`, `design/schema.md:1115` and
     `tests/test_knowledge_build_row_ordering.py:118` — the same sentence three times, *"must not wait
     out `busy_timeout` to record its own death"* → *"must not wait out the write-lock budget"*.
   - `tests/test_mcp_connection_integration.py:166` — *"up to `PRAGMA busy_timeout = 5000`'s full 5 s
     to resolve (`zikaron/core/store/ddl.py`)"* → *"up to `ddl.BUSY_TIMEOUT_MS`'s full 5 s"*; `:216`
     *"waited out the service's own busy_timeout"* → *"the service's own wait budget"*.

Verified and not raised, so the next round does not re-check them: **the fixture** — `_interleave_commits`
(`test_service_write_contention.py:79,144`) and `test_indexing_writes.py:658,672` each start
`commit_a_write` through `asyncio.to_thread` and gather every worker inside the `with`, so no worker's
private connection outlives the fixture; every `hold()`, `release()` and `close()` site
(`test_service_writer.py`, `test_service_read_contention.py`, `test_service_surface_deadline.py`,
`test_service_write_contention.py:168`) runs on the loop thread, `release_after`'s timer runs there too,
and a timer that fires after `close()` no-ops on `_holding`; the "two in flight" claim is consistent with
the mechanics — by the time a verb's first transaction commits, its worker is sleeping in SQLite's
handler in 100 ms steps while the second transaction's `BEGIN IMMEDIATE` polls at 25 ms or less, so the
verb usually retakes the lock first and the second worker starts while the first still waits; under the
old shared connection that second worker was the *API misuse*. **The rewritten test** — the lock is
freed at about 0.3 s, the next attempt lands within one pause of 25 ms plus a round trip, and
`late < 0.1` leaves the poll's cap three pauses of headroom; under the recorded mutation the pause that
straddles 0.3 s runs from about 255 to 511 ms, so `late` is about 0.21 s and the test is red; a cap of
100 ms or less would pass, which is what a bound of four pauses buys and is acceptable; `0 <= late` is a
tautology and harmless; with the primitive driven directly and `propagate`, the *tried once* mutation
raises `OperationalError` at once, as row `:118` of the evidence note records. **§M35 against the code** —
the struck paragraph's correction names `ddl.SERVING_PRAGMA`, the 1 ms → 25 ms poll
(`_FIRST_POLL_SECONDS`, `_LONGEST_POLL_SECONDS`) and the bare-holder exception, each as the code has it;
the timer-early rationale at `:4810-4813` matches `deadline.py:11-13` and the loop's
`end_time = time() + clock_resolution` rule, and the mapping it justifies is by `set_by_caller` in both
`holders.acquire` and `reads._retry_failure_map`, never by a second clock read; `:4880-4885` matches
`pool.lease`, `_give_back` and the absence of any restore; `:5126-5133` and `:5259-5264` read as
`reads._read_with_one_retry` and `test_a_reads_lease_wait_and_retry_share_one_budget` behave;
`schema.md:896-902`, `:1012`, `:1392` and `:1978-1987`, `knowledge-index.md:113-116`,
`build_log.py:15-20`, `deadline.py:3-5`, `errors.py:264` and `test_service_writer.py:103-107` carry
round 9's wording or an equivalent. **The research note** — the macOS table supports the decision it is
cited for, and nothing the design cites from it moved.

VERDICT: NEEDS_CHANGES

### Author's response to round 10

1. **Accepted.** `tests/test_knowledge_build_log.py:397` and `:486` carry the proposed wording.
2. **Accepted.** In `FINDINGS.md`:
   - the review is described as *"whose last round is the verdict"*;
   - the green run is described as being on *"the PR's current head (`gh pr checks`)"*;
   - `f5bb459` is marked as reachable from the reflog only.
3. **Accepted, and the class is now swept rather than read off this list.** Every phrasing the round named is replaced. A grep of the tree, with each hit judged, found six more that placed a serving wait in SQLite or named the pragma as the budget, all now fixed:
   - three code comments and `design/indexing.md:210`, on *"every concurrent writer's `busy_timeout`"*, now *"wait for the lock"*;
   - `architecture.md:86` (*"the full 5 s wait budget"*) and `:2571` (*"whether the 5 s wait budget is the right number"*);
   - `schema.md`'s `knowledge_build` row (*"behind the write-lock budget"*);
   - `FINDINGS.md:163`;
   - `knowledge-index.md:310`, which said `busy_timeout` means the same in a corpus as in the memory store, and now says a corpus connection keeps its 5 s while the store's serving connections drop to zero.

   The hits left standing are true as written:
   - corpus connections, which keep SQLite's wait;
   - the access log, which is at zero;
   - SQLite's own behaviour, such as *"`busy_timeout` never retries"* a stale snapshot;
   - measured history, such as `architecture.md:57-91` and `schema.md:406/921`, which record what a past version did.

## Round 11 — 2026-09-30

Scope, per the brief: `git diff f5bb459 dbe4c72` and whatever that diff made false outside itself. No
shell was available to this round either, so the diff was taken as the round 9/10 record plus the
response's list of what moved since round 10, each read in the current tree; the `busy_timeout` sweep
the response describes was re-run here with `Grep` and every hit judged independently, and repeated
for the same class phrased without the word — *busy handler*, *in SQLite*, *SQLite's own wait*,
*remainder*, *restore*, *pragma*.

### Summary judgment

Round 10's three items are in the tree as the response says, and the sweep it describes is complete
on my own re-run: every hit left standing is a corpus connection (which keeps SQLite's 5 s), the access
log (at zero by its own design), SQLite's own behaviour, or a measured record of what a past version
did, and the sweep for the class phrased without `busy_timeout` found only sentences that are true of
the code. Read fresh, the primitive polls only on a holder `hold()` registered (`polls_for_lock`), so
the corpus lock's `IMMEDIATE`-from-no-holder still gets SQLite's wait as the brief and
`knowledge-index.md:311` say; the three opens apply `SERVING_PRAGMA` after validation and creation;
the store is assembled before the socket is bound, which is what `architecture.md:1010` rests on; and
the "0.6–1 s" the withdrawal cites in three places is the research table's differences, not a figure
the table lacks. `FINDINGS.md`'s two state paragraphs no longer contradict each other. Two residual
phrasings remain, both trivial and both in this diff's own text.

### Findings

1. **[NITPICK] The header sentence of §M35's budget paragraph still uses the idiom round 10 replaced
   in its property bullet.** `design/build-plan.md:4730-4731`: *"one wait budget, `ddl.BUSY_TIMEOUT_MS`,
   for the lock and SQLite together.** That is the constant, not the connection's pragma, which is
   zero on the access log's."* Round 10's finding 3 replaced the same phrase at `:5307` (*"lock plus
   SQLite"* → *"connection lock plus write lock"*), and this sentence sits two lines above the struck
   paragraph that says the wait is no longer SQLite's; and its example — the access log's pragma
   being zero — is now true of every serving connection, so it reads as though the writer's pragma
   were the constant. Suggest: *"for the connection lock and the write lock together.** That is the
   constant, not a connection's pragma, which is zero on every serving connection once the store is
   open, as it always was on the access log's."*

2. **[NITPICK] `knowledge-index.md:311-312`'s new sentence overstates the corpus connection's pragma
   by one documented exception.** *"`busy_timeout` … stays at its opened 5 s on every corpus
   connection"* — this diff's wording — while `core/knowledge/counters.py:219-227` sets a corpus
   connection's `busy_timeout` to `_NO_WAIT_MS` for a §12 counter write and restores it, which the
   same document states at `:2635-2636`. Suggest: *"and it stays at its opened 5 s on every corpus
   connection — §12's counter write drops it to zero for its own statement and restores it — unlike
   the memory store's serving connections, which …"*.

Verified and not raised, so the next round does not re-check them: **round 10's items** —
`tests/test_knowledge_build_log.py:397` and `:484-487` carry the proposed wording and the assertion
at `:494` still pins the poll on the build's path; `FINDINGS.md:86` (*"whose last round is the
verdict"*), `:91-92` (*"the PR's current head (`gh pr checks`)"*), `:98-99` (reflog note) and
`:163-165` (*"waits its full wait budget for the write lock"*); `build-plan.md:4749`, `:5057`,
`:5233`, `:5307`; `architecture.md:86`, `:997-998`, `:2571-2572`; `schema.md:705` (the
`knowledge_build` row, *"behind the write-lock budget"*), `:1114-1115`;
`test_knowledge_build_row_ordering.py:118`; `test_mcp_connection_integration.py:166`, `:216`; the three
code comments (`indexing/writes.py:27`, `indexing/vectors.py:111`, `retrieval/reads.py:155`) and
`indexing.md:210`, *"wait for the lock"*; `knowledge-index.md:310-314`. **The standing hits, each
judged** — corpus connections: `core/knowledge/ddl.py:24,37`, `counters.py:219,227`,
`knowledge/vectors.py:37`, `test_knowledge_database.py:71-79`, `test_knowledge_counters.py`,
`test_knowledge_lock_race.py:48-49`, `build-plan.md:5037-5039,5043-5044`,
`knowledge-index.md:1063,2635-2636`; the access log: `ddl.py:42-57`, `access_log.py:76,125-126,195`,
`schema.md:957-964`, `test_access_log.py:13,533`, `build-plan.md:4129,4760,5366,5439`; SQLite's own
behaviour: `architecture.md:985`, `build-plan.md:4638,4843`, `test_service_write_contention.py:1-7`,
`retrieval.md:249-250`, `test_retrieval_reads.py:500`, `test_service_read_contention.py:53`; measured
history: `architecture.md:57-91`, `schema.md:406,921`, `test_knowledge_registry.py:225-226`,
`coding-standards.md:335-344`, `connection.py:123-126`, M33's brief at `build-plan.md:4102-4105`, and
`:4751-4752` on how the 10 s client timeout was derived. **The class without the word** —
`transactions.py:16-21,175-177,215-220`, `ddl.py:31-36`, `holders.py:9-14,69-71,117-119,127`,
`pool.py:8-10` and `close`'s docstring at `:118-122`, which no longer names a pragma restore;
`errors.py:264-266`; `test_store_pool.py:143-144`; `schema.md:963`; `deadline.py`; nothing in
`design/` or `README.md` says *remainder* or *restore* of the pool's pragma. **The code, fresh** —
`in_one_transaction:231-236` polls only when `opens_immediate and holder.polls_for_lock`, and
`polls_for_lock` is set only by `hold()` (`holders.py:121`), so a bare holder asked for `immediate=True`
issues one `BEGIN IMMEDIATE` under SQLite's wait; `store.py:298,384,474` apply `SERVING_PRAGMA` on the
reopen, after `_create_tables_and_meta`, and after `_validate_on_open`; `main.py:242-273` assembles
the store before the signal handlers and the bind. **The margin section** — `architecture.md:1266-1274`
and the `deadline_passed` row at `:2199` say *decided by which bound cut the wait* with the
timer-early rationale, which is `holders.acquire:93-97` and `reads._retry_failure_map:166-181`;
`reads._read_with_one_retry:193-203` says *for what remains of `deadline`* and nothing about a pragma.
**The research note, for the decision it supports** — §"SQLite's own wait on macOS, and why the
primitive polls instead" is at `:155`; the table at `:162-167` gives refusals of ~864, 1,359, 976 and
1,174 ms against pragmas of ~250, ~400, ~300 and ~500 ms, whose differences are 0.61–0.96 s, so the
*"0.6–1 s"* at `architecture.md:1006`, `ddl.py:34` and `build-plan.md:4739` is the table's, and the
heading the design cites is a prefix of the real one. **`FINDINGS.md`** — `:74` (M0–M34 landed) and
`:82` (M35 in a pull request) agree; `:92-96` states the macOS overrun and the serving override as
the code has them.

VERDICT: APPROVED

### Author's response to round 11

Both nitpicks are applied as proposed:

1. `build-plan.md:4730-4732` now reads *"for the connection lock and the write lock together"*, with the pragma sentence naming every serving connection.
2. `knowledge-index.md:310-315` now names §12's counter write as the one statement that drops a corpus connection's `busy_timeout` and restores it.

Both are prose only. The drift guards pass.
