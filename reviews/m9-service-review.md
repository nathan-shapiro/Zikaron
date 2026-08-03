## Author's response to Round 14 — 2026-08-02

One blocker and two improvements — all three accepted and fixed. This is the **final** review round;
the loop stops here by the operator's direction ("address feedback diligently but do not re-review
afterwards"). Round 14 also independently answered the one open safety question I most wanted
checked, and answered it favourably: skipping `ctx.close()` on the force-exit path is safe for the
*next* process to open the store — the kernel releases SQLite's fds and locks, WAL is the configured
journal, committed frames remain recoverable, and an incomplete transaction is ignored rather than
made durable. Leftover `-wal`/`-shm` files are recovery work, not damage.

1. **[BLOCKER] accepted as stated — two routes could still absorb a `ShutdownTimeoutError` instead
   of reaching the directed terminal path.** The reviewer's analysis of which routes were already
   sound was correct (signal-path `shut_down()` raises straight to the dedicated catch; an
   idle-path timeout present in `asyncio.wait`'s `done` set is re-raised by
   `_raise_if_any_task_genuinely_failed`), and so was its analysis of the two that were not:

   *Route (a)* — a `ShutdownTimeoutError` from the cleanup `shut_down()` inside
   `except BaseException:` was caught by that block's own broad nested handler, logged as a mere
   secondary failure, and execution then fell through to ordinary propagation **and** `ctx.close()`
   — exactly the "keep going after the graceful path already gave up" the operator's direction
   rules out. Fixed with a dedicated `except ShutdownTimeoutError:` ahead of the broad handler,
   which logs the primary exception first (since forcing the exit means it will not propagate to
   anyone) and then routes to `_force_exit_after_failed_graceful_shutdown`.

   *Route (b)* — if a signal won the `asyncio.wait` snapshot while `idle_self_stop` was concurrently
   inside its own `shut_down()`, that task's `ShutdownTimeoutError` arrived in the cancellation
   `finally` as a **return value** of `gather(..., return_exceptions=True)`, never inspected by
   `_raise_if_any_task_genuinely_failed` (which only saw the earlier `done` set), and was silently
   discarded. `return_exceptions=True` is required there — it stops one task's failure from
   skipping the cancellation of the others — so the fix inspects the outcomes:
   `_force_exit_if_shutdown_timed_out(outcomes, sock_path)`.

   Added the three discriminating tests the finding asked for: idle timeout as the first completion
   (pinning the already-sound route), a shutdown timeout while cleaning up an unrelated lifecycle
   failure (route a), and an idle task yielding `ShutdownTimeoutError` only during cancellation
   after a signal won the original wait (route b). Verified both fixes discriminate by reverting
   each in turn and confirming the corresponding test fails. **One correction worth recording about
   my own verification process:** my first discrimination run reported route (b)'s test passing
   against the reverted code, which would have meant the test proved nothing — the revert script had
   silently failed, leaving the file unmodified, and I only saw a truncated tail. Re-running cleanly
   showed the expected assertion failure. Trusting the first result would have shipped a fix I had
   not actually verified.

   Also corrected a genuine test-design error the new tests exposed: three of them initially
   asserted the force-exit spy was called *exactly once*, and two failed with `2 == 1`. That count
   is a spy artefact, not a property of the code — in production the first `os._exit` never returns,
   so exactly-once holds by construction, while a spy that *does* return lets execution continue
   into whatever later terminal route the same failure also reaches. The assertions now check that
   the terminal path is reached at all, with the reasoning recorded inline; one test additionally
   expects the original exception to re-raise, explicitly noted as accounting for the spy rather
   than asserting production behaviour.

2. **[IMPROVEMENT] accepted as stated.** `close_all_connections` built its own absolute deadline and
   `shut_down` then started a *fresh* full five-second `wait_for` on `wait_closed()`, so the single
   "5 s deadline" the directed policy names could in fact take nearly ten seconds before the
   force-exit path ran. `shut_down` now computes one absolute deadline for the whole method, threads
   it into `close_all_connections(deadline)`, and gives `wait_closed()` only the remaining budget —
   raising `ShutdownTimeoutError` immediately if none remains. `close_all_connections`'s parameter
   defaults to `None` (compute your own) so its existing direct callers and tests are unaffected.

3. **[IMPROVEMENT] accepted as stated.** `ShutdownTimeoutError`'s own docstring still claimed it was
   raised only from `close_all_connections`'s two branches, which round 13's own `wait_closed()`
   bound had already made false — now says all three graceful-shutdown deadline exits. Narrowed the
   two remaining absolute claims the settled accept-pipeline exception contradicts: `main.run`'s
   "every open connection" and `shut_down`'s "close every one already accepted" both now say
   *observable* connections under a bounded deadline. The reviewer confirmed the detailed
   "normally, not provably" passage does not understate the guarantee, so it stands unchanged.

**Verification.** `ruff format`/`ruff check`/`mypy --strict` clean across `zikaron/service` and the
touched tests. Full `check.sh` gate run twice: **1064 tests passing**, 99.74% coverage on
`zikaron/core`, ~40–45 s. Service integration suite (10 tests) run three times consecutively with
process and zombie checks after each — clean every time. Full repo-wide `-m integration` suite
(30 tests) clean. `/tmp` spot-check clean.

## Author's response to Round 13 — 2026-08-02

One blocker and three improvements — all four accepted and fixed. The blocker is the important
one, and it is a genuine implementation defect in the operator-directed fallback rather than a
re-litigation of the directed decision: **the fallback as I first implemented it could not fire in
the exact scenario it exists for.** The reviewer was right, and I confirmed it empirically before
touching anything.

1. **[BLOCKER] accepted as stated, and confirmed by direct measurement.** Wrote a standalone
   script that starts a cancellation-resistant task, then raises `TimeoutError` out of the
   coroutine passed to `asyncio.run`, with an `except TimeoutError:` around `asyncio.run` — exactly
   the shape I had shipped. Result: the process hung and the outer `except` **never ran at all**
   (killed by the shell's own timeout; the "reached" print never appeared). `asyncio.run` cancels
   and awaits every remaining task before re-raising, and the very task that made the shutdown
   deadline expire is *by definition* one that did not finish cancelling — so the runner's own
   teardown hangs and nothing outside it is ever reached. The fallback was unreachable from the
   only failure it was built for.

   Fixed by moving the force-exit **inside** the coroutine `asyncio.run` runs: `run()` now has a
   dedicated `except ShutdownTimeoutError:` clause, ahead of its existing `except BaseException:`,
   which calls the new `_force_exit_after_failed_graceful_shutdown(sock_path)`. That path unlinks
   the socket, logs, and exits — and deliberately **skips** both the `except BaseException:`
   retry and the outer `finally`'s `ctx.close()`, which the reviewer correctly identified as a
   second `shut_down()` with a fresh 5 s deadline plus a store close: precisely the "keep asking
   the graceful path to try again" the operator's direction rules out, and either of which could
   hang on the same stuck task. `main()` is now a plain `asyncio.run(...)` with no handler at all,
   and its docstring records why the catch cannot live there. Also fixed the third part of this
   finding: `shut_down()`'s final `server.wait_closed()` was awaited **unbounded**, so a stall
   there produced no `ShutdownTimeoutError` for the fallback to act on — now wrapped in
   `asyncio.wait_for` against the same deadline constant (`wait_for` is sufficient at that specific
   line, unlike inside `close_all_connections`, because `wait_closed()` is the stdlib's own future
   and has no task of ours to suppress cancellation).

   Rewrote the test accordingly: `test_a_shutdown_timeout_forces_process_exit_from_inside_the_
   running_coroutine` now drives the real `run()` with `RunningServer.shut_down` raising
   `ShutdownTimeoutError`, firing `SIGTERM`'s handler synchronously at installation to reach the
   signal path deterministically, and asserts both that the spy fired and that the socket was
   unlinked. Confirmed it discriminates by removing the new `except` clause and re-running: it
   failed, and its traceback independently exhibited the double-`shut_down()` retry the fix now
   skips. The reviewer's own note that the previous immediate-raise stub "cannot expose this
   ordering defect" was exactly right — that stub is gone.

2. **[IMPROVEMENT] accepted as stated.** Introduced `ShutdownTimeoutError(TimeoutError)` in
   `server.py`, raised **only** from the deadline branches (both in `close_all_connections` and
   the newly bounded `wait_closed()`), and the terminal path catches only that type. A bare
   `TimeoutError` could reach that boundary from anywhere — a startup step, a lifecycle task, a
   dependency's own internal timeout, a store close — and none of those prove *this* deadline
   expired or warrant bypassing the normal, diagnosable failure path with an un-catchable
   `os._exit`. Every other exception continues through the established primary/secondary
   preservation path unchanged.

3. **[IMPROVEMENT] accepted as stated.** The reviewer confirmed the indirection is safe under
   current code and ordinary pytest ordering/xdist, but that a future edit moving `os._exit(1)`
   out from behind `_force_exit_after_shutdown_timeout` would bypass the spy and kill a worker.
   Added the suggested second line of defence: the test now *also* monkeypatches `os._exit` itself
   to a fail-fast sentinel that raises `AssertionError`, so an accidental bypass fails the test
   loudly instead of terminating the run. Ran the rewritten test in isolation first, with a hard
   shell-level timeout, and confirmed the shell exited normally — proving neither the real
   `os._exit` nor the sentinel was reached.

4. **[IMPROVEMENT] accepted as stated, and this one is worth naming plainly: my docstrings were
   claiming a property the operator had explicitly decided not to buy.** `close_all_connections`
   still said `_active_count` "can only ever count *down*" after `close()`, and that reaching zero
   made the following `wait_closed()` "guaranteed to return immediately rather than merely likely
   to" — both of which are exactly what the settled accept-pipeline exception says is *not* proven.
   Rewrote that passage to state the narrower truth: the counter normally counts down but not
   provably, naming the pre-attachment accept race and pointing at the process fallback as its
   actual coverage, and describing what the loop does guarantee (it drains what it can observe
   under its deadline, and raises rather than waiting indefinitely). Also removed the "first and
   *only* thing tried" / "failed once" framing from `main()`, which had become inaccurate the
   moment the retry existed — and which is now accurate again for a different reason, since the
   terminal path genuinely skips that retry.

**Verification.** `ruff format`/`ruff check`/`mypy --strict` clean across `zikaron` and `tests`
(131 source files). Full `check.sh` gate run twice: **1061 tests passing**, 99.74% coverage on
`zikaron/core`, ~43 s both times. Service integration suite (10 tests) run three times
consecutively with process and zombie checks after each: clean every time. Full repo-wide
`-m integration` suite (30 tests) clean. `/tmp` spot-check clean.

## Author's response to Round 12 — 2026-08-02

Two blockers and two improvements — all four resolved, though finding 2 was resolved by an
explicit human-operator policy decision rather than by closing the underlying race, made after
stepping back with the user to reconsider what problem this milestone is actually solving.

1. **[BLOCKER] accepted as stated, and confirmed by direct measurement that the fix in round 11
   was itself insufficient.** Verified the reviewer's exact citation of `wait_for`'s own
   docstring — "if the task suppresses the cancellation and returns a value instead, that value
   is returned" — and confirmed empirically with a standalone script: a handler that suppresses
   *every* cancellation (not merely one, which is all the round-11 regression test happened to
   model) leaves `asyncio.wait_for(gather(...), timeout=remaining)` waiting forever, since `gather
   (..., return_exceptions=True)` never lets a child's `CancelledError` propagate as its own.
   Rewrote `close_all_connections` to use `asyncio.wait(list(self._connections), timeout=
   remaining)` instead — verified directly this genuinely returns at the deadline regardless of
   whether the underlying tasks ever finish cancelling (its own docstring states plainly "this
   does not raise TimeoutError... futures that aren't done... are returned in the second set"),
   confirmed with an identical standalone script before rewriting the production code. Rewrote the
   regression test's own resistant handler to suppress cancellation behind a **separately
   releasable gate** rather than a fixed count, specifically because a fixed "swallow exactly
   once" handler is exactly what let the insufficient round-11 fix look correct — the timeout's
   own cancellation of the outer future supplies exactly one more cancellation to the inner task,
   which a swallow-once handler then lets through, passing the test for the wrong reason.
   **Writing this corrected test took one more genuinely wrong attempt, caught by direct tracing
   rather than by the test failing outright**: the gated handler never called `writer.close()` on
   its own transport when it finally exited, which left that transport counted by `_active_count`
   forever regardless of the handler task itself finishing — traced directly to a hang at `bare_
   server.wait_closed()` after every other step had printed successfully; fixed by adding the
   same `finally: writer.close()` production `_handle_connection` already has. Confirmed the final
   test discriminates by reverting to the round-11 `wait_for(gather(...))` implementation and
   re-running: it genuinely hung past the outer bound; restored the fix and reconfirmed all 26
   tests in the file pass.

2. **[BLOCKER] resolved by explicit human-operator decision, not by closing the race.** Verified
   the reviewer's exact citation of the stdlib accept pipeline directly: `_accept_connection`
   calls `sock.accept()` synchronously and then schedules `_accept_connection2` as a *separate*
   task, so a connection can be accepted at the raw-fd level before `Server._attach()` — the call
   that increments `_active_count` — has run. Attempted to reproduce the exact window empirically
   with two separate standalone scripts; both attempts either showed the connection had not yet
   been accepted at all (rejected by `close()` before the accept callback ever ran) or had already
   fully attached before `close()` ran — confirming the window is real per the stdlib source but
   is either extremely narrow or requires bypassing `asyncio.Server` entirely (a hand-rolled
   accept loop via `loop.sock_accept()`/`loop.connect_accepted_socket()`, the reviewer's own
   suggested fix) to construct deterministically, at a cost proportional to a real architectural
   rewrite rather than a local patch.

   **Stepped back with the user before committing to that rewrite**, and the user redirected the
   question productively: is airtight closure of every asyncio-internals accept race actually the
   right bar, when a bounded, loud failure already exists? The user's own stated position — keep
   the graceful path exactly as already built (it stays the *first* and *only* thing tried, with
   its own real 5 s deadline), and if it has already tried and failed, stop trying to make it
   provably perfect and just end the process — was implemented directly: `main.main()` now catches
   `TimeoutError` specifically (the exact exception `close_all_connections`'s own deadline
   produces) and calls a new `_force_exit_after_shutdown_timeout`, which calls `os._exit(1)`.
   **Per the user's own explicit follow-up caution, the real `os._exit` call is never exercised
   by any test** — it is factored into its own named function specifically so a test can
   monkeypatch that name to a spy, since `os._exit` is un-catchable and would kill the `pytest`
   worker process itself, not merely the code under test, if ever called for real inside one.
   Added `test_main_forces_process_exit_when_graceful_shutdown_times_out`, monkeypatching both
   `main.run` (to raise `TimeoutError` directly, standing in for a real deadline expiring) and
   `main._force_exit_after_shutdown_timeout` (to a spy), asserting the spy was called exactly
   once. Ran this specific test in complete isolation first, with a hard shell-level timeout as
   an extra safety net, before running it alongside anything else, precisely because of the risk
   the user flagged. Confirmed the test discriminates by reverting `main()`'s `try/except` and
   re-running: `TimeoutError` propagated uncaught rather than reaching the spy, and — critically —
   `pytest` itself still exited normally reporting the failure, confirming the real `os._exit`
   was genuinely never invoked on either the passing or the failing path. Documented this as a
   normative decision in `design/architecture.md` §"Idle self-stop" (re-indexed into the
   `zikaron-design` knowledge base), stating plainly that this is a deliberate choice of
   engineering effort, not a claim that the graceful path is airtight against every internal race
   in a dependency this project does not own.

3. **[IMPROVEMENT] accepted as stated.** `main.run`'s outer `except BaseException:` called `server.
   shut_down()` a second time unconditionally, with no `try` of its own around it — a real second
   failure there would have replaced whatever exception was already propagating into that clause.
   Fixed identically to the already-established `ctx.close()` pattern in the outer `finally`, with
   one simplification confirmed correct by direct measurement rather than assumed: verified with a
   standalone script that `sys.exc_info()`'s `exc_value` is never `None` inside a running `except
   BaseException:` block, since being inside it at all requires an active exception — meaning,
   unlike the outer `finally`'s own genuinely-reachable "nothing was already failing" case, there
   is no such case to distinguish here, so the retry's own failure is unconditionally logged as
   secondary rather than needing a branch that would have been dead code. Added
   `test_a_shut_down_failure_while_handling_idle_self_stop_failure_preserves_the_original`, forcing
   both `idle_self_stop` and the retried `shut_down()` to fail and asserting the *original*
   `idle_self_stop` failure is what propagates. Confirmed the test discriminates by reverting the
   fix and re-running: the retry's own `OSError` replaced the original `RuntimeError`, exactly the
   defect described; restored the fix and reconfirmed.

4. **[IMPROVEMENT] accepted as stated.** `handler_started` proved the *connection handler* task had
   reached the gate, but nothing proved the *`shut_down` task* itself had started running before
   the "still pending" assertion — those are two independently-scheduled tasks with no ordering
   guarantee between them, so the assertion could pass merely because `shut_down_task` had simply
   never been scheduled yet. Added a `shutdown_started` event, set as the very first synchronous
   action of a small wrapper coroutine around `running.shut_down()`, awaited under a timeout before
   the pending-assertion — proving the shutdown task specifically has begun running, independent
   of the connection handler's own timing. Checked directly whether the vacuity was reachable in
   practice on this environment (a standalone script showed the polling loop's own break condition
   was satisfied after exactly one turn, before the handler had reached its own `handler_started.
   set()` line at all) — the specific ordering the old test happened to get right today, but the
   fix removes the dependency on it holding rather than merely happening to observe that it does.

**Full verification after all four fixes.** `ruff format`/`ruff check`/`mypy --strict` clean across
every touched file (`server.py`, `main.py`, `test_service_server.py`, `test_service_main.py`).
`design/architecture.md` updated and `zikaron-design` re-indexed. Full `check.sh` gate run twice
for stability: both completed in 38-41 s with **1061 tests passing**, 99.74% coverage on
`zikaron/core`. Integration suite (10 tests) re-run three times consecutively with zero
process/zombie leaks each time. The complete `-m integration` suite across the whole repository
(30 tests) re-run clean once more. `/tmp` spot-check clean, no leftover repro/backup/diagnostic
artifacts.

## Author's response to Round 11 — 2026-08-02

Three blockers, two improvements, and one nitpick — all six independently verified against the
code and fixed. Rather than adding a fourth layer of nested cleanup, the user was consulted
directly (per their own explicit standing request to check in before implementing anything that
looked like a fresh set of demanded changes rather than a continuation) and approved a structural
fix: `main.run` no longer calls `asyncio.Server.serve_forever()` at all. This one change resolves
findings 2, 3, and 5 together, since all three trace back to the same root cause the user and I
diagnosed together before implementing: `serve_forever()` was never necessary in the first place
— `asyncio.start_unix_server` (inside `serve()`) already accepts and dispatches connections the
instant it returns — and waiting on it as a third "why did we stop" signal meant that cancelling
it invoked `asyncio.Server`'s own internal `close()`/`wait_closed()` sequence, a second,
independent wait for the same connections `RunningServer.shut_down()` exists to drain, which ran
*first* and could deadlock against an idle open connection before this coroutine's own draining
logic ever got a chance to run.

1. **[BLOCKER] accepted as stated, and it is the sixth genuinely severe production defect this
   review has found (after rounds 5, 8, 9, and 10's finding 1's two intermediate attempts).**
   Removed the `serve_forever` task entirely: `run()` now races only `idle_task` and `signal_
   wait`, and on either exit path calls `server.shut_down()` directly — no `async with server:`,
   no `server.server.serve_forever()` reference anywhere. Removed `RunningServer.__aenter__`/
   `__aexit__` as now-genuinely-unused code (confirmed via a fresh grep: nothing in the codebase
   used them as an async context manager once `main.run`'s own `async with server:` was gone),
   along with the now-unused `Self` import. Fixed every stale docstring reference to `async with
   server:`/`main.run`'s three-task wait across `server.py`, `main.py`, and `test_service_main.
   py`'s own module docstring. Updated the two tests that depended on the removed `serve_forever`
   task: `test_a_failure_after_all_three_tasks_exist_still_cancels_and_awaits_every_one` renamed
   and its assertion narrowed from three tasks to two; `test_serve_forever_raising_after_all_
   tasks_exist_propagates_rather_than_exiting_clean` removed outright, since the code path it
   tested no longer exists.

   **Independently verified the fix resolves the exact deadlock described, and that the old code
   genuinely had it**, using the same standard held throughout this review: wrote a standalone
   script that runs `main.run` as a real task, opens a real connection, sends a real request and
   reads its real response (proving genuine server-side registration, not merely an open socket),
   leaves the connection open, and delivers a real `SIGTERM` via `os.kill(os.getpid(), ...)` —
   confirmed the fixed code returns promptly, then temporarily reverted to the exact pre-fix
   `serve_forever`-based structure and re-ran the identical script: it genuinely hung past a 5 s
   bound. Restored the fix, added `test_a_signal_with_an_idle_open_connection_still_returns_
   promptly` to `tests/test_service_main.py` using the same real-request/real-signal shape, and
   confirmed it discriminates via the identical revert-and-rerun procedure.

2. **[BLOCKER] resolved as a consequence of finding 1's structural fix, not by a separate local
   patch.** With `serve_forever` gone, there is no competing internal `close()`/`wait_closed()`
   wait for `_active_count`'s own post-close rise to interact badly with — `RunningServer.shut_
   down()` is now the only thing that ever closes anything, called directly rather than reached
   through a second, asyncio-owned cancellation path.

3. **[BLOCKER] this is finding 1 and finding 2 from the reviewer's own numbering — restated here
   because the reviewer's own finding 3 is the one that named the actual deadlock mechanism most
   precisely** (a cycle between `main.run`'s inner `gather` on `serve_forever`'s own cancellation
   and `RunningServer.__aexit__`'s need to run first): resolved by the same structural fix as
   finding 1, verified with the same standalone script.

4. **[IMPROVEMENT] accepted as stated.** `close_all_connections`'s deadline was checked only
   *after* its `await gather(...)` returned, with no timeout on the `gather` itself — a handler
   that catches and suppresses its own cancellation could leave that `gather` waiting forever,
   never reaching the deadline check at all. Fixed by wrapping the `gather` in `asyncio.wait_for`
   bounded by the *remaining* time on the deadline, so the deadline now applies to that specific
   wait rather than only being checked between loop iterations. Added `test_close_all_connections_
   raises_loudly_rather_than_hanging_inside_gather`, monkeypatching the module's shutdown-deadline
   constant to a small value and constructing a handler that swallows exactly one cancellation.
   **Writing this test's handler correctly took two genuinely wrong attempts, each caught by
   direct tracing rather than by the test merely failing**: the first attempt built the resistant
   handler around `reader.readline()`, and tracing showed cancelling a task suspended there can
   surface as `readline()` returning an ordinary empty result rather than raising `CancelledError`
   into the surrounding `try` at all — a genuinely different asyncio behaviour from what the test
   needed to construct on purpose, not a bug in the fix. The second attempt (after switching the
   resistant sleep to `asyncio.sleep`, which does reliably raise) still hung, traced to a much
   simpler cause: the test's own bare `_on_connect` closure never called `running._connections.
   add(...)` at all, so `close_all_connections` correctly had nothing to cancel — the exact same
   "constructed via a bare `asyncio.start_unix_server`, forgot the manual registration line"
   mistake round 10's own accepted-but-not-registered test had already needed once. Fixed by
   adding the manual registration line, mirroring that test's own established pattern. Confirmed
   the corrected test discriminates by reverting the timeout-bounding fix and re-running: it
   failed with a bare, message-less `TimeoutError` from `wait_for` itself after the full 5 s
   outer bound — exactly the uninformative failure mode the fix replaces with a clear message —
   rather than the expected "responded to cancellation" message; restored the fix and reconfirmed.

5. **[IMPROVEMENT] accepted as stated.** The accepted-but-not-registered regression test's own
   single `await asyncio.sleep(0)` before asserting `shut_down_task` was still pending could pass
   vacuously if that task simply had not been scheduled to run at all yet, proving nothing about
   whether it was genuinely blocked on the gate specifically. Added a `handler_started` event, set
   by the gated handler *before* it awaits the registration gate, and changed the test to wait on
   that real, observable fact under an explicit timeout before making the "still pending" assertion
   — removing the vacuous single-turn wait entirely rather than merely adding more turns. The
   existing bounded `_active_count` polling loop in the same test was left unchanged, since the
   reviewer's own assessment already confirmed it checks a genuine condition each pass rather than
   assuming a fixed number of turns.

6. **[NITPICK] resolved as a side effect of finding 1.** The one test that reached through
   `asyncio.base_events.Server` rather than the public `asyncio.Server` alias was the now-removed
   `serve_forever`-raising test; a fresh sweep confirms no other reference to the private module
   path remains anywhere in `zikaron/service/` or `tests/`.

**Full verification after all six fixes.** `ruff format`/`ruff check`/`mypy --strict` clean across
every touched file (`server.py`, `main.py`, `test_service_server.py`, `test_service_main.py`). Full
`check.sh` gate run **twice** for stability confirmation given round 10's own coverage-timing
incident: both runs completed in ~38 s with **1059 tests passing**, 99.74% coverage on `zikaron/
core`. Integration suite (10 tests) re-run three times consecutively with zero process/zombie leaks
each time. The complete `-m integration` suite across the whole repository (30 tests) re-run clean
once more. `/tmp` spot-check clean, no leftover repro/backup/diagnostic artifacts.

## Author's response to Round 10 — 2026-08-02

One blocker, one severe blocker, two improvements, and one nitpick — all five independently
verified against the code and fixed. Finding 1 required abandoning two intermediate fix attempts
before landing on the correct one, each disproven by direct measurement rather than argument; the
fix that survived is the fourth genuinely severe production defect this review has found (after
round 5's health-readiness-before-lock-release, round 8's consolidator wire-name mismatch, and
round 9's `wait_closed()` hang).

1. **[BLOCKER] accepted as stated, and it took three iterations to actually close.** Verified the
   reviewer's exact asyncio-source claim directly: `_SelectorTransport.__init__` calls `self.
   _server._attach()` **synchronously** (incrementing the private counter `wait_closed()` waits
   on), while `StreamReaderProtocol.connection_made` — the callback that creates the handler task
   `RunningServer._connections` tracks — is only *scheduled* via that same constructor's `loop.
   call_soon`, one or more turns later. Wrote a standalone repro reconstructing the exact
   production shape (register on the very first line, no `await` before it) and measured directly:
   even a single bare `asyncio.sleep(0)` between opening a connection and calling `shut_down()`
   left it hanging — confirming the gap is real, not theoretical. **My first fix attempt** — loop
   until one full pass adds no new task to `self._connections` — was itself wrong, caught by
   re-running the same repro against it: registration reliably took **three** turns, not one, so
   two consecutive "no change" checks could both land mid-pipeline and falsely read as
   quiescence. **My second fix attempt** — subclass `asyncio.Server` to intercept `_attach` at its
   exact synchronous moment — was investigated and abandoned before writing any code: `asyncio.
   unix_events._UnixSelectorEventLoop.create_unix_server` hard-codes `base_events.Server`
   directly, with no factory hook any public API exposes for substituting a subclass. **The fix
   that survived**: `close_all_connections` now polls `self.server._active_count` itself — the
   exact private counter `wait_closed()` waits on, accessed with an explicit, documented `type:
   ignore[attr-defined]` at every read since `asyncio.Server`'s public surface exposes no
   equivalent — cancelling every task that *has* registered on each pass, bounded by a 5 s deadline
   that raises loudly rather than hanging forever if a handler never responds. Re-ran the exact
   repro that disproved both earlier attempts, including the tightest possible case (zero yields
   at all between connecting and calling `shut_down`): both now return promptly. Added
   `test_shut_down_survives_a_connection_accepted_but_not_yet_self_registered`, which builds the
   exact window deterministically — a real `asyncio.Server`/`RunningServer` pair with an
   intentionally empty `_connections` set and a gated handler task that only registers once a
   test-controlled `asyncio.Event` is released — rather than trying to time a real accept
   precisely, which would be nondeterministic by construction. Confirmed the test discriminates by
   reverting to the round-9 single-snapshot implementation and re-running: it correctly timed out
   after the full 5 s bound; restored the fix and reconfirmed all 24 tests in the file pass.

2. **[BLOCKER] accepted as stated.** `idle_task.done() and not idle_task.cancelled()` treated a
   genuinely *raised* `idle_self_stop` identically to a normal idle exit, since a raised task is
   `done()` and not `cancelled()` either — and the unconditional `gather(..., return_exceptions=
   True)` in the cleanup `finally` never retrieved or re-raised it, so a real crash would have
   exited the process with status zero. Extracted `_raise_if_any_task_genuinely_failed` (also
   resolving a `PLR0915`/`PLR0912` complexity violation `run()` had grown into), which retrieves
   each completed task's own exception *before* anything is cancelled and re-raises the first
   genuine one found — excluding `signal_wait` (whose normal completion carries no exception at
   all) and excluding cancelled tasks (not yet possible at this point in the flow, but correct in
   principle). `idle_exited = idle_task in done` replaces the old boolean expression, now correct
   specifically because any genuine exception has already caused an early `raise` by the time this
   line runs. Added two discriminating tests — one monkeypatching `lifecycle.idle_self_stop`
   itself to raise, one monkeypatching `asyncio.base_events.Server.serve_forever` to raise — both
   asserting `run()` propagates rather than returning normally. Confirmed both discriminate by
   reverting to the old boolean expression and re-running: `run()` returned cleanly with no
   exception in both cases, exactly the defect described; restored the fix and reconfirmed.

3. **[IMPROVEMENT] accepted as stated.** No `remove_signal_handler` call existed on any path —
   installed handlers survived even a fully successful run, closing over that invocation's `stop`
   event, and a failure installing the *second* signal left the *first* one installed forever with
   nothing removing it. Extracted `_stop_on_sigterm_or_sigint`, an `@asynccontextmanager` that
   installs both signals on entry (tracking successes incrementally) and removes exactly those that
   succeeded in an unconditional `finally` on the way out — this extraction was also needed to keep
   `run()` under `coding-standards.md`'s statement-count guideline once the task-cancellation and
   exception-preservation fixes had already grown it past the threshold. Added two tests: one
   forcing the *second* installation to fail and asserting the *first* signal was removed (spying
   on the real `remove_signal_handler` rather than merely counting `add_signal_handler` calls,
   since removal is the actual behaviour under test); one asserting both handlers are removed after
   a fully successful signal-driven exit. **The second test surfaced a genuinely consequential bug
   in my own first draft, caught only because the user asked me to run the full check gate rather
   than trusting the file's own isolated result**: it used a separately-scheduled polling task
   racing `run()`'s own setup to detect when `SIGTERM`'s handler had been installed, bounded by
   10,000 `asyncio.sleep(0)` turns — this passed in isolation and under plain `pytest -q`, but
   hung for the full bound under `pytest --cov` specifically, whose tracing overhead changes the
   real-time-per-turn ratio enough that 10,000 turns were not "enough" under coverage the way they
   reliably were without it, and the full `check.sh` gate (which does run under coverage) failed
   and took 30 minutes instead of 30 seconds as a direct result. Redesigned to fire `SIGTERM`'s own
   callback **synchronously, inside** the monkeypatched `add_signal_handler` call itself, at the
   exact point `run()` calls it — eliminating the race entirely rather than widening a timeout bound
   that would still have been a guess under some future, slower environment. Re-ran the full `check.
   sh` gate twice after the redesign: both completed in ~38 s with all 1058 tests passing, matching
   the established baseline; re-confirmed the redesigned test still discriminates the fix from the
   bug via the same revert-and-rerun procedure.

4. **[IMPROVEMENT] accepted as stated.** The application-error test's own docstring claimed to
   prove a client "bootstraps into a failing first call" and still learns its label, but it
   supplied an already-labeled `_client("s1")`, proving only that an existing label survives an
   error — never that a freshly *minted* one does. Changed it to a genuine bootstrap envelope
   (`session_id=None`) asserting a minted `zk-...` label at the top-level `client` field. Also
   added `test_an_unhandled_handler_exception_still_echoes_the_resolved_label`, the one `encode_
   error` call site (the `except Exception:` internal-error fallback) no test had exercised at
   all — monkeypatching `server._METHODS["remember"]` to raise a genuine, non-`ZikaronError`
   exception, asserting the resolved label still appears at the top level and not inside `error.
   data`. Confirmed this new test discriminates by dropping the `session_id` keyword from that one
   call site and re-running: it failed with `KeyError: 'client'`, exactly the regression it exists
   to catch; restored the fix and reconfirmed.

5. **[NITPICK] accepted as stated.** `dispatch_consolidation.py`'s own opening line still said "the
   consolidator's four verbs plus `plan_groups`/`next_group`" — the same count/category confusion
   round 9's sweep had already corrected in `dispatch.py` but missed in this file's own first
   line. Fixed to match: "`plan_groups`, `next_group`, and the three consolidator write methods."

**Full verification after all five fixes, plus the self-caught test-hang bug.** `ruff format`/
`ruff check`/`mypy --strict` clean across every touched file (`server.py`, `main.py`,
`dispatch_consolidation.py`, `test_service_server.py`, `test_service_main.py`). Full `check.sh`
gate re-run **twice** after the finding-3 test redesign specifically, to confirm the earlier
30-minute/1-failure anomaly is genuinely resolved and not merely not-yet-reproduced: both runs
completed in ~38 s with **1058 tests passing**, 99.74% coverage on `zikaron/core`. Integration
suite (10 tests) re-run three times consecutively with zero process/zombie leaks each time. The
complete `-m integration` suite across the whole repository (30 tests) re-run clean once more.
`/tmp` spot-check clean, no leftover repro/backup/measurement artifacts.

## Author's response to Round 9 — 2026-08-02

Two new blockers, two improvements, and two nitpicks — all six independently verified against the
code and fixed. Finding 2 is the third genuinely severe defect this review has found (alongside
round 5's health-readiness-before-lock-release and round 8's consolidator wire-name mismatch): a
completely ordinary, long-lived client connection could hang the entire service's shutdown forever,
on both the idle and signal paths.

1. **[BLOCKER] accepted as stated.** Re-read `architecture.md`'s exact line ("Returns `client.
   session_id` in the response envelope — on success and on every error alike") and confirmed
   `server.py`'s `METHOD_NOT_FOUND`, `ZikaronError`, and internal-error paths were all splicing
   `session_id` into `error.data` instead of attaching it as the same top-level `client.session_id`
   sibling `encode_result` correctly uses for a success — polluting every declared error `data`
   shape with an undocumented extra field, and giving a client no top-level `client` object to read
   a minted bootstrap label from on a failing first call. Fixed `rpc.encode_error` to take the
   identical `session_id` keyword parameter `encode_result` already has, attaching it as the same
   top-level sibling; fixed all three call sites in `server.py`'s `_dispatch_request` to pass
   `session_id=envelope.session_id` instead of splicing it into `data`. Fixed the three tests that
   had cemented the wrong path (`tests/test_service_server.py`) to assert `client.session_id` at
   the top level and `"session_id" not in data`, strengthening them into regression guards against
   this exact mistake recurring. Added `test_encode_error_with_a_session_id_attaches_it_as_a_
   sibling_of_error_not_inside_data` and `test_encode_error_with_no_session_id_attaches_no_client_
   field_at_all` directly against `rpc.encode_error`, since no existing test had covered the new
   keyword parameter at all. Full default-tier suite re-run clean after the signature change.

2. **[BLOCKER] accepted as stated, and independently confirmed by direct measurement before
   writing the fix — the single most severe defect this review has found in production behavior.**
   Wrote a standalone repro (`/tmp/repro_wait_closed_hang.py`, deleted after use) that started a
   real `asyncio.start_unix_server`, connected one client that sent nothing, called `server.
   close()`, then awaited `server.wait_closed()` under a 3 s `asyncio.wait_for` — confirmed directly
   on this project's own pinned Python 3.12.3 that `wait_closed()` was still pending after the
   timeout, exactly matching the reviewer's citation of the installed stdlib source ("wait until
   server is closed and all connections have been dropped"). This meant *any* client that finished
   a request and kept its connection open — the documented norm, not an edge case, per
   `architecture.md`'s "the client adopts the returned label and reuses it for its process
   lifetime" — could hang the service's shutdown forever, on both `idle_self_stop`'s own `close()`/
   `wait_closed()` pair and `main.run`'s `async with server:` on the signal path, since both called
   the identical sequence.

   Fixed by introducing `server.RunningServer` — a small dataclass wrapping the real `asyncio.
   Server` alongside a `set[asyncio.Task[None]]` tracking every accepted connection's own handler
   task (not merely its `StreamWriter`, since closing only the writer leaves the handler still
   suspended in `reader.readline()` until the transport closing eventually surfaces as an empty
   read — "eventually" being exactly the unbounded wait this exists to make bounded).
   `close_all_connections()` cancels every tracked task and awaits all of them; `shut_down()` closes
   the listener, then closes every connection, then waits for the listener itself — in that order,
   since closing connections first is what makes the final `wait_closed()` actually resolve.
   `RunningServer` is itself an async context manager (`__aenter__`/`__aexit__` calling `shut_down`),
   so `main.run`'s existing `async with server:` needed no restructuring at that specific line.
   `serve()` now returns `RunningServer` instead of a bare `asyncio.Server`; `idle_self_stop`'s
   signature and body updated to call `server.shut_down()` instead of the bare `close()`/
   `wait_closed()` pair; `main.run`'s two other `close()`/`wait_closed()` call sites (the direct
   `server.server.serve_forever()` reference and the exception-path `shut_down()` call) updated to
   match.

   Added `test_shut_down_returns_promptly_even_with_an_idle_client_still_connected` to
   `test_service_server.py` — a deliberate, narrow exception to that file's own stated real-
   socket-free convention, since a real `asyncio.start_unix_server`/`asyncio.open_unix_connection`
   pair is the only way to reproduce the actual hang. **My own first draft of this test was
   itself wrong, caught only by verifying it against the reverted code rather than trusting it
   after one green run**: it opened the connection and immediately called `shut_down()` with no
   request/response round trip first, which raced the event loop's own scheduling of the server-
   side accept callback — reverting the fix and re-running that first draft *still passed*,
   because the connection had frequently not yet been registered as "accepted" by the time
   `shut_down()` ran, on either the fixed or the broken code. Rewrote the test to send a real
   `health` request and read its real response before leaving the connection open and calling
   `shut_down` — this is what actually distinguishes the two, confirmed by reverting the fix a
   second time and observing a genuine `TimeoutError` after the full 5 s bound, then restoring the
   fix and confirming the test passes again in well under a second. This finding, and the process
   of catching my own test's initial false pass, directly informed the user's separate steering
   about sleep-based timing in tests this same round — the corrected version needed no sleep at
   all, only a real, deterministic round trip, which is both more reliable and faster.

3. **[IMPROVEMENT] accepted as stated.** `idle_task`/`signal_wait`/`serve_forever` were all
   created before `asyncio.wait` was ever called on them, but the cancellation loop only ran
   *after* `asyncio.wait` returned normally — a failure inside that call, or `run()` itself being
   cancelled while awaiting it, jumped straight to the exception-path handler (or propagated past
   it entirely) with whichever tasks already existed never cancelled or awaited. Fixed by building
   a `tasks: list[asyncio.Task[object]]` incrementally as each task is actually created, wrapped in
   its own `try`/`finally` that unconditionally cancels every task in the list and awaits all of
   them via `asyncio.gather(*tasks, return_exceptions=True)` — incrementally rather than one literal
   tuple, specifically so the `finally` sees exactly the tasks that exist at the point of failure,
   never one that was never created; `gather` with `return_exceptions=True` rather than the
   previous per-task loop so one task's own failure during cancellation cannot skip cancelling the
   rest. Added `test_a_failure_after_all_three_tasks_exist_still_cancels_and_awaits_every_one` to
   `test_service_main.py`, monkeypatching `asyncio.wait` itself to record the tasks it was given
   and then raise — the one call that only happens after all three tasks genuinely exist, which the
   existing test (a failure *before* any task exists) could not reach. Confirmed by reverting the
   fix and re-running: `signal_wait`'s own `Event.wait()` task was left genuinely pending
   afterward, plus a secondary "Task exception was never retrieved" warning from the abandoned
   `serve_forever` task — both gone once the fix was restored.

4. **[IMPROVEMENT] accepted as stated.** `main.run`'s outer `finally: await ctx.close()` let a
   close failure **replace** whatever exception was already propagating out of the function — the
   identical exception-masking class already fixed once inside `ServiceContext.assemble` itself,
   but at a genuinely different call site (`run()`'s own cleanup, running after `assemble` has
   already returned successfully, against a failure occurring later in `run()`'s own body). Fixed
   using `sys.exc_info()` to distinguish "close failed while something else was already failing"
   from "close failed on an otherwise normal exit": only the first case has a primary exception
   worth preserving, logged rather than raised; the second has nothing to mask, so the close
   failure there is the one genuinely wrong thing and propagates as itself. Added
   `test_a_context_close_failure_does_not_mask_an_earlier_setup_failure`, forcing both a setup
   failure and a `Store.close` failure and asserting the setup failure is what a caller's `except`
   catches. The test's own first draft leaked its store connection for the same reason round 7's
   analogous `ServiceContext.assemble` test did — forcing `close()` to fail on purpose means it
   genuinely never closes for real inside the code under test — fixed identically, by having the
   fake close call the real close underneath before raising, mirroring `test_service_context_
   assemble.py`'s own established pattern rather than inventing a new one. Confirmed by reverting
   the fix and re-running: the `OSError` from the close failure propagated instead of the expected
   `RuntimeError`, exactly the defect described.

5. **[NITPICK] accepted as stated.** The readiness regression test's own docstring claimed it
   defended against "a value more exotic than a plain boolean (a truthy string, say)," but the
   fixture only ever sends the literal JSON `false`, never a truthy non-boolean. Narrowed the
   docstring to state precisely what the test proves and explicitly disclaim what it does not,
   rather than extending the fake server script's already-intricate f-string template to add a
   third response variant for one nitpick-level claim — the fake server script's own docstring
   (a separate location the reviewer also cited) was re-checked and found already correctly scoped,
   needing no change.

6. **[NITPICK] accepted as stated.** `dispatch.py`'s module docstring said "the four consolidator
   methods (`plan_groups`, `next_group`, `merge`, `promote`, `discard`)" — wrong on two counts:
   there are five RPC methods in that module, and three of the five names were still the stale bare
   form round 8 fixed everywhere else. Fixed to name all five RPC methods with their correct wire
   names, and to explicitly distinguish this from D32's "four consolidator tools" figure (`plan_
   groups` deliberately excluded from that count, per `architecture.md`'s own clarification), so one
   number is not quoted for two different things. Swept `dispatch_consolidation.py` for the same
   stale bare-name pattern and found two more genuine instances (its own module docstring and
   `_consolidation_call`'s docstring, both using `merge` as an example of a directly-callable method
   name) — fixed both to `apply_merge`. Confirmed the one remaining bare-form reference in that file
   (the round-8 comment explaining the wire-name-versus-design-prose distinction itself) is a
   deliberate contrast, not a stale claim, and needs no change.

**Sleep-based test timing — a live correction during this round, not merely a style note.** The
user flagged that no test in this codebase should use `sleep` for timing, since it makes tests
flaky. Checked: my own finding-2 fix's first test draft did not use `sleep` directly, but had the
equivalent defect — proceeding immediately after opening a connection with no deterministic wait
for the server side to have actually processed it, which raced the event loop's own scheduling and
passed for the wrong reason even with the fix reverted, exactly the "test that could pass for a
reason unrelated to the property it claims to defend" pattern this project's own `FINDINGS.md`
already names as a recurring failure mode. The fix was not to add a sleep to "give it enough time"
— that would have been slower, still nondeterministic, and exactly the anti-pattern flagged — but
to replace the race with a real, deterministic operation (a request/response round trip) that
blocks exactly until the property being tested is genuinely true. Swept the whole `tests/`
directory for every occurrence of `sleep(`: the only instances are three pre-existing, legitimate
deadline-bounded polling loops in `test_service_lifecycle_integration.py` (`_wait_for_socket`,
`_wait_for_pid_file`, `_reap` — each checks a real condition on a short interval against a hard
deadline, raising `TimeoutError` on exhaustion, which is categorically different from a fixed-
duration "probably enough time" wait) and three in `zikaron/service/lifecycle.py` itself, which are
the actual production polling intervals `architecture.md` specifies (`idle_self_stop`'s 30 s poll,
`_poll_until_reachable`'s retry interval) — not test code at all. No sleep-based test exists in this
codebase after this round, and none was introduced by it.

**Full verification after all six fixes.** `ruff format`/`ruff check`/`mypy --strict` clean across
every touched file (`rpc.py`, `server.py`, `lifecycle.py`, `main.py`, `dispatch.py`,
`dispatch_consolidation.py`, `test_service_server.py`, `test_service_main.py`,
`test_service_rpc.py`, `test_service_lifecycle_integration.py`). Full `check.sh` gate: **1052
tests, 99.74% coverage on `zikaron/core`.** The complete `-m integration` suite across the *whole*
repository (not only the service lifecycle file) re-run clean at the user's explicit request: 30
tests total, covering `test_indexing_integration.py` and `test_retrieval_integration.py` (M4/M5,
untouched by this round but re-confirmed unaffected) alongside the service lifecycle suite (grown
to 10 tests). The service lifecycle suite specifically re-run three times consecutively with an
explicit process/zombie check after each run: zero leftover `zikaron.service`/`fake_slow_server`
processes and zero zombies every time. `/tmp` spot-check clean, no leftover repro/backup artifacts.

## Author's response to Round 8 — 2026-08-02

Two new blockers, two improvements, and one nitpick — all five independently verified against the
code and fixed. Finding 1 is the second-most consequential defect the whole review has found (after
round 5's health-readiness-before-lock-release fix): a wire-protocol method-name mismatch that would
have made every consolidator write unreachable by any client built against the design.

1. **[BLOCKER] accepted as stated, and confirmed by direct citation of the exact normative
   sentence.** Re-read `architecture.md` §"Service RPC surface" directly: it names the three
   consolidator write methods `apply_merge(...)`, `apply_promote(...)`, `apply_discard(...)` — not
   the bare `merge`/`promote`/`discard` my own `CONSOLIDATOR_METHODS` dict registered them under,
   which I had silently matched to the *core library's own function names* instead of the wire
   protocol's own stated names. Grepped the whole design corpus for `apply_merge`/`apply_promote`/
   `apply_discard` and confirmed the RPC surface section is the *only* place any of them appear —
   and it is the one place that section exists specifically to state the wire method names, so
   there is no competing design statement to reconcile, only a straightforward implementation
   miss. Fixed the three dict keys; `server.py`'s own lookup logic needed no change, since it
   already looks up whatever key is present. Confirmed no other production code constructed an
   RPC request with the old bare method-name strings, and no test called any RPC method by its
   wire name at all for these three — every existing consolidator test calls the Python handler
   functions directly, exactly as the reviewer's own diagnosis states, which is precisely why this
   defect was invisible to the whole existing suite. Added four new wire-level tests to
   `test_service_server.py` — `test_apply_discard_is_reachable_by_its_documented_wire_name`,
   `test_apply_promote_is_reachable_by_its_documented_wire_name`,
   `test_apply_merge_is_reachable_by_its_documented_wire_name`, and
   `test_plan_groups_is_reachable_by_its_documented_wire_name` — each going through `server.
   _handle_line`'s own method-name lookup exactly as a real socket connection would, with local
   orphan-pair/anchored-pair fixtures mirroring `test_service_dispatch_consolidation.py`'s own
   (kept local rather than imported across test files, per this project's convention of
   self-contained test modules). Confirmed all three `apply_*` tests genuinely discriminate by
   temporarily reverting the three dict keys to their old bare names and re-running: all three
   failed with `KeyError: 'result'` (a `METHOD_NOT_FOUND` response with no `result` key), exactly
   the defect the fix addresses, while `plan_groups`'s own test correctly kept passing since that
   method was never affected; restored the fix afterward and reconfirmed all four pass.

2. **[BLOCKER] accepted as stated, and traced to the exact coercion.** Confirmed `_health`'s
   `ready=bool(result["ready"])` accepts any truthy value — a JSON string `"false"` included,
   since a non-empty Python string is truthy — and confirmed `.ready` is never actually checked
   anywhere downstream in `lifecycle.py`: neither `_poll_until_reachable`'s spawn-branch loop nor
   `connect_start_if_absent`'s bare-connect branches gate on it at all, so any structurally valid
   response that merely *parses* was being treated as a completed handshake regardless of its
   `ready` value. Fixed `_health` to require the literal JSON boolean `True` (`if ready is not
   True: raise ConnectionError(...)`), which routes through both existing reaction paths
   correctly without needing to touch either caller: the spawn-branch loop already catches
   `ConnectionError` and keeps polling, and `connect_start_if_absent`'s bare-connect branches
   already propagate through their own `except BaseException: sock.close(); raise`. Extended
   `_fake_server_script` with a `ready_false_attempts` parameter, which answers with a
   structurally perfect response whose `ready` is the literal JSON `false` for that many
   attempts before ever answering `true` — added
   `test_a_structurally_valid_but_not_ready_health_response_is_not_treated_as_started`, which
   documents in its own docstring the subtlety the reviewer's own finding implies: a literal
   `false` is not actually the case `bool(...)` coercion gets wrong (`bool(False) == False`), so
   this test defends the *fixed* code's behavior going forward (requiring literal `True`, not
   merely truthiness) rather than re-proving the original bug through the one value that
   happens not to trigger it. Confirmed by reverting to the old `bool(...)` coercion and
   re-running: the test failed with `HealthCheck(ready=False, ...)` returned as if it were a
   completed handshake — `_poll_until_reachable` had returned on the very first `ready:false`
   response — exactly the defect described; restored the fix and reconfirmed both health-
   readiness tests pass.

3. **[IMPROVEMENT] accepted as stated.** Re-read `main.run` and confirmed exactly the window the
   reviewer traced: `serve()` binds a real listening socket, then `sock_path.chmod`, signal-handler
   installation, and task creation all run before `async with server:` ever takes ownership of
   it — a failure in any of those left the listener open and the socket path on disk, since the
   function's only `finally` closed `ctx`, not `server`. Wrapped everything from immediately after
   `serve()` returns through the end of the `async with server:` block in its own `try`/`except
   BaseException: server.close(); await server.wait_closed(); sock_path.unlink(missing_ok=True);
   raise`. Verified precisely, rather than assumed, that `asyncio.Server.close()` and `.
   wait_closed()` are both idempotent (by reading their actual source: `close()` checks `if
   sockets is None: return` at the top, `wait_closed()` checks `if self._waiters is None: return`)
   before relying on calling them unconditionally on any exception reaching that point, including
   one that originated *inside* `async with server:` after its own `__aexit__` already ran the
   identical close sequence. Added `tests/test_service_main.py` — a new file, since no test had
   ever called `run()`/`main()` directly as a plain coroutine before, only indirectly through the
   subprocess `main.py` spawns in the integration tier — with
   `test_a_setup_failure_after_binding_closes_the_listener_and_unlinks_the_socket`, which
   monkeypatches `loop.add_signal_handler` to fail (standing in for any of the several fallible
   steps in that window) and asserts the socket path is gone afterward. Confirmed the test
   discriminates by reverting the fix and re-running: it failed with the socket path still present
   on disk, exactly the defect described; restored the fix and reconfirmed the test passes.

4. **[IMPROVEMENT] accepted as stated.** Confirmed precisely: my own round-7 `finally` block did
   `with suppress(TimeoutError): _reap(pid, deadline_seconds=5.0)` with no registration in
   `_KNOWN_SERVER_PIDS` at all, unlike `_kill_and_reap_server_at`'s own established pattern of
   registering *before* attempting anything and discarding only on confirmed success — meaning an
   unconfirmed reap on this specific path had no sweep-fixture backstop. Fixed by extracting the
   duplicated logic (present identically in both health-readiness tests, since I had copy-pasted
   it for the second test written this same round) into a shared `_kill_and_reap_from_pid_file`
   helper that registers the pid before the kill/reap attempt and discards it only once `_reap`
   confirms completion, matching `_kill_and_reap_server_at`'s own documented reasoning.

5. **[NITPICK] accepted as stated.** `test_service_rpc.py`'s docstring still claimed a "bare-list
   or bare-string" `result` shape, but the only such exceptional shape is `search`'s bare list —
   `surface` returns `{text: ...}`, an object — a claim round 7 had already corrected in
   production code (`rpc.encode_result`'s own docstring) without sweeping the test suite for the
   same phrase. Fixed, and swept the whole `zikaron/service/` and `tests/` trees for any other
   occurrence of "bare-string"/"bare string" — none found.

**Full verification after all five fixes.** `ruff format`/`ruff check`/`mypy --strict` clean across
every touched file (`dispatch_consolidation.py`, `lifecycle.py`, `main.py`,
`test_service_server.py`, `test_service_lifecycle_integration.py`, `test_service_main.py` (new),
`test_service_rpc.py`). Full `check.sh` gate: **1047 tests, 99.74% coverage on `zikaron/core`.**
Integration suite (10 tests, grew from 9) run three times consecutively with an explicit
process/zombie check after each run: all three runs passed with zero leftover
`zikaron.service`/`fake_slow_server` processes and zero zombies. `/tmp` spot-check clean, no
leftover repro/backup artifacts.

## Author's response to Round 7 — 2026-08-02

All five findings independently re-verified against the code and, for the blocker, verified with a
direct read of the exact failure sequence the reviewer traced before writing the fix.

1. **[BLOCKER] accepted as stated, and the traced failure sequence checks out exactly.** Re-read
   the old code at the cited lines and confirmed precisely: `_KNOWN_SERVER_PIDS.add(int(second_
   result["pid"]))` ran only after both `connect_start_if_absent` *and* a second `health` exchange
   had already succeeded, so a failure inside `connect_start_if_absent` during the refused-
   handshake phase — the exact regression this test exists to catch — left the pid unregistered,
   and the `finally` block's own recovery attempt (`_kill_and_reap_server_at`, which opens a fresh
   connection to discover the pid) competes with the fake server's own `refused_attempts` global
   counter and could itself land in the refusal window. Implemented the reviewer's own suggested
   fix rather than inventing an alternative: `_fake_server_script` now takes a `pid_file` path and
   writes its own pid there immediately after `bind()`, independent of the health handshake
   entirely. The test reads that file in its `finally` block — not inside the `try`, since the pid
   file's own appearance can lag slightly behind the fake process's own start, so a `_wait_for_
   pid_file` helper polls for it with the same bounded-deadline shape `_wait_for_socket` already
   uses — and kills/reaps that pid unconditionally, regardless of what happened inside the `try`.
   Ran the fixed test in isolation with a hard `timeout 30` wrapper and confirmed it passes with no
   leftover process (`ps aux` clean immediately after).

2. **[IMPROVEMENT] accepted as stated.** `except BaseException: await store.close(); raise` let a
   `Store.close()` failure replace the original construction error a caller actually needs to
   diagnose. Fixed to catch the close failure separately, log it, and use a bare `raise` to
   re-raise the construction error specifically — confirmed this is what a bare `raise` does at
   that point (not the swallowed close failure) by writing a standalone three-line reproduction
   with a `ValueError` as the outer exception and a caught-and-swallowed `RuntimeError` as the
   inner one, run directly, before relying on it in production code. Added
   `test_assemble_preserves_the_original_error_even_if_closing_the_store_also_fails`, which
   monkeypatches `Store.close` to call the real close (so the connection is genuinely released)
   and then raise on top of it, and asserts the `BAD_CONFIG`/`embedding.embed_model` error is what
   propagates — not the `RuntimeError`. Confirmed the test discriminates by temporarily reverting
   `context.py` to the pre-fix bare `await store.close(); raise` and re-running it: it failed with
   the `RuntimeError` propagating instead of the expected `ZikaronError`, exactly the defect the
   fix addresses, before restoring the fix.

3. **[IMPROVEMENT] accepted as stated.** `_connect` allocated a socket and called `.connect(...)`
   with no exception handling to close it on failure — the same exception-path-ownership class
   already fixed for the post-`_health` case. Wrapped in `try`/`except BaseException: sock.close();
   raise`. No new dedicated test added: the finding did not request one (unlike findings 1 and 2,
   which explicitly did), and the existing `_poll_until_reachable`/lifecycle tests already exercise
   `_connect`'s failure path repeatedly (every `ENOENT`/`ECONNREFUSED` retry attempt against a
   not-yet-bound or stale socket runs through exactly this code), so a dedicated test would mostly
   re-assert socket-close behavior the standard library itself guarantees rather than add new
   discriminating power — consistent with `FINDINGS.md`'s own standing caution against tests that
   exist to chase a line rather than a behavior.

4. **[NITPICK] accepted as stated, docstring-only, no test added — matching the reviewer's own
   explicit instruction not to.** Changed `_dispatch_request`'s docstring from the stale "never
   raises" claim to describe the actual contract: `_compute_response_line`'s own two `except`
   clauses map ordinary `ZikaronError`s and handler exceptions to an encoded error line, while
   `_handle_line`'s outer catch is the genuine server-boundary fallback for a failure this
   function's own inner mapping could not itself account for (a failure in `health`'s own
   dispatch, in envelope resolution, in response encoding, or in `ctx.activity`'s own bookkeeping).
   Agreed with the reviewer's own characterization: this is a real defensive branch for a genuine
   unexpected failure, not the coverage-chasing anti-pattern `FINDINGS.md` warns against, so no
   monkeypatch-only test was added to cover it.

5. **[NITPICK] accepted as stated.** `rpc.encode_result`'s docstring still cited "surface's
   ready-to-print text" as a second bare-value example alongside search's bare list, but
   `SurfaceResult.as_json()` returns `{"text": ...}` — an object, not a bare string. Removed the
   incorrect claim, keeping only `search`'s bare-list case as the motivating example for why
   `session_id` must be a sibling field.

**Round 7 summary judgment also reconfirmed, no action needed:** activity bracketing every parsed
request without interfering with notification suppression, legitimate consolidator envelopes still
constructing `ConsolidationCall` correctly, the primary-method/consolidator-method asymmetry being
principled (`client.kind` is provenance for primary methods, authorization for consolidator ones),
and the stale search-shape prose fix from Round 6 — all independently reconfirmed correct by the
reviewer and requiring no further action.

**Full verification after all five fixes.** `ruff format`/`ruff check`/`mypy --strict` clean across
every touched file (`context.py`, `lifecycle.py`, `server.py`, `rpc.py`,
`test_service_lifecycle_integration.py`, `test_service_context_assemble.py`). Full `check.sh` gate:
**1041 tests, 99.74% coverage on `zikaron/core`.** Integration suite (9 tests) run three times
consecutively with an explicit process/zombie check after each run: all three runs passed with zero
leftover `zikaron.service`/`fake_slow_server` processes and zero zombies. One genuinely stale
`/tmp/fake_test_dir` artifact from an earlier manual repro (unrelated to this round's work) was
found during the routine `/tmp` spot-check and removed.

## Author's response to Round 6 — 2026-08-02

All six findings independently re-verified against the code and, for the two blockers with the
most consequential real-world impact, verified with a temporary mutation-and-repro rather than
argument alone.

1. **[BLOCKER] accepted as stated.** The regression test's `sock, health = await
   asyncio.to_thread(connect_start_if_absent, ...)` had no outer `try`/`finally`, and the fake
   server's own `while True: accept()` loop never exits on its own, so any failure in that call —
   this fix regressing, or any unrelated bug — would leak a permanently-running fake process for
   the rest of the session; the daemon-thread reaper only reaps a child once it exits, which this
   one structurally never does on its own. Wrapped the whole call in `try`/`finally`, registering
   the discovered pid in `_KNOWN_SERVER_PIDS` immediately once the second health exchange
   confirms it. Also fixed the fake server's own success branch to keep the connection open for
   further requests rather than closing after one exchange, and added a genuine second
   `_send(sock, "health", {})` after `connect_start_if_absent` returns — the previous version's
   docstring claimed the returned socket "genuinely answers" but never actually tested a second
   request on it.

2. **[BLOCKER] accepted as stated, and independently confirmed the leak is real before writing
   the fix.** `ServiceContext.assemble` opened the store, then called `FastEmbedEncoder.load` and
   several settings constructors with no exception handling — the function's own `Raises` section
   already documents that `FastEmbedEncoder.load` can fail, so a leaked store on that path was not
   a hypothetical. `coding-standards.md` §6's binding rule is exactly what this violated: a
   non-daemon `aiosqlite` worker thread abandoned on a later construction failure keeps the whole
   interpreter alive after `main.run()` has already logged the failure and is trying to exit.
   Wrapped every post-open step in `try`/`except BaseException: await store.close(); raise`.
   Added `test_assemble_closes_the_store_when_a_later_construction_step_fails`, which monkeypatches
   `FastEmbedEncoder.load` to fail after a real `Store.open` and relies on `tests/conftest.py`'s
   own autouse leak-detection fixture — not a check this test invented — to prove nothing was left
   open; confirmed the test itself is discriminating by temporarily reverting the fix and
   re-running it, which failed exactly as expected at the leak-detection teardown rather than at
   the test's own assertion, before restoring the fix.

3. **[BLOCKER] accepted as stated, and it is the second most consequential defect this round.**
   `ctx.activity.begin_request()` ran only in the branch that found a matching handler — the
   `health` early return, an envelope-resolution failure, and an unknown method all bypassed
   activity tracking entirely, contrary to `architecture.md` §"Idle self-stop"'s unqualified
   "`last_activity` is refreshed when each request completes" and this module's own docstring
   claim that begin/end "bracket the *whole* dispatch." The `health` gap is the dangerous one: a
   client's own start-if-absent sequence repeatedly polls exactly that method while waiting for
   readiness, and none of those polls were preventing idle self-stop from firing mid-poll. Moved
   `begin_request`/`end_request` to bracket all of `_dispatch_request`, around the call to
   `_compute_response_line`, so every successfully parsed request — health, notifications,
   resolved errors, and ordinary calls alike — updates the clock. Added three tests asserting
   `last_activity` genuinely advances (not only that `in_flight` returns to zero, which the two
   pre-existing tests checked and which this bug could pass regardless): for `health`, for an
   unknown method, and for a malformed envelope.

4. **[IMPROVEMENT] accepted as stated.** `connect_start_if_absent`'s `_health(sock)` call for the
   two bare-connect branches had no exception handling — a previously reachable server closing or
   malforming its response during this handshake left `sock`'s cleanup to exception-frame
   destruction rather than an explicit close. Wrapped in `try`/`except BaseException: sock.close();
   raise`.

5. **[BLOCKER] accepted as stated, and it repeats a mistake I had already made once this same
   review** (round 1's finding about `method_not_found` running before resolution) **in a
   different module.** The claim that a non-consolidator envelope is "unreachable through the real
   dispatch path... a caller picks its method, not its kind" conflates two independent fields of
   one request exactly the way the earlier mistake did: nothing about `PRIMARY_METHODS`/
   `CONSOLIDATOR_METHODS` being disjoint *method names* prevents an `mcp`-kind client from naming
   `merge` or `next_group` directly, since `server.py` dispatches purely by method name and
   `client.kind` is a separate field the caller controls independently. This was genuinely
   reachable and produced a `-32603 INTERNAL_ERROR` — indistinguishable from a server bug — for
   what is actually a declared, anticipatable caller mistake. Added an explicit `client.kind`
   check in `_consolidation_call`, before `ConsolidationCall` is ever constructed, raising
   `BOUNDS` naming `client.kind` — `ConsolidationCall`'s own invariant exists to protect receipt
   scoping, not to police callers, so checking earlier is not a duplicate of that invariant, it is
   moving the *caller-facing* rejection to where a caller-facing error belongs. Corrected the
   module's own docstring rather than leaving the false claim standing. Added
   `test_a_primary_agent_envelope_calling_a_consolidator_method_is_a_bounds_error`.

6. **[NITPICK] accepted as stated.** Fixed `dispatch.search`'s docstring to state the bare-list
   shape (`-> [SearchHit, ...]`) and `serialize.py`'s module preamble to say `as_json()` produces
   "the JSON value... object," not unconditionally a `dict[str, object]`.

Full `check.sh` re-run after every fix above: 1040 tests, `ruff format --check`/`ruff check`
clean, `mypy --strict zikaron tests` clean, 99.74% coverage on `zikaron/core`. Integration suite
(9 tests) run three times in immediate succession with no leftover live process or zombie after
any run.
## Author's response to Round 5 — 2026-08-02

Both findings independently re-verified against the code and the normative design text before
acting; finding 1 required a genuine architectural fix, not a patch.

1. **[BLOCKER] accepted as stated, and it is the most consequential defect found across all five
   rounds.** Re-read `architecture.md` §Lifecycle literally, word by word: step 4 states "spawn...
   **then poll `health()`** until a deadline" as one step, with "release the lock" as the *next*,
   separate step (step 5), and identity verification (step 6) as a *third*, separate step after
   that. `_poll_until_reachable` polled only for a bare socket connection to succeed — never
   `health()` — so a freshly spawned process that accepts a connection well before finishing
   `ServiceContext.assemble()`'s own model load, or one that accepts a connection and then dies
   mid-handshake, would have the lock released the instant the bare connect succeeded, exactly the
   premature-release failure the design's own step ordering exists to rule out.

   Fixed structurally, not by patching the one function: `_poll_until_reachable` now polls for a
   genuine `health()` response, closing each failed attempt's own socket before retrying, and
   `_try_connect_twice_under_lock`'s return type widened to `tuple[socket.socket, HealthCheck |
   None]` — `None` for the two "already connected" branches (steps 1 and 3, a bare reachability
   check for "another client may have won," which the design's own wording never asks to be
   health-confirmed, since `connect_start_if_absent`'s own step 6 runs unconditionally afterward
   regardless of which branch answered), and a real, already-confirmed `HealthCheck` for the one
   branch that actually needs to confirm readiness before releasing the lock: the spawn branch,
   which is the only one where "the process exists" and "the process is ready" can genuinely
   disagree.

   Added a dedicated regression test rather than trusting the description of the fix alone:
   `test_a_connected_but_not_yet_health_ready_server_is_not_treated_as_started` spawns a small,
   dedicated fake server (written to a real script file, not `main.py`, specifically so the test
   does not have to pay for a real store or a real model load to exercise this) that accepts a
   fixed number of connections and silently closes each one with no response before finally
   answering correctly — deterministic on **connection count**, not wall-clock timing, so the test
   cannot flake against machine speed. Verified the test is not merely coincidentally passing: ran
   a standalone reproduction of the *old* buggy logic (bare connect, no `health()` check at all)
   against the identical fake server before writing the fix into the file, and confirmed directly
   that the old logic hands back a socket on the very first connection attempt whose first real
   use then fails with a closed connection and no response — exactly the failure this fix and its
   test both exist to prevent, and exactly what a reviewer verifying "does this test actually
   distinguish fixed from buggy" would want confirmed rather than asserted.

2. **[BLOCKER] accepted as stated, both halves.** The racing test's own
   `_connect_and_report_server_pid` discovered a server pid via an explicit `health()` call and
   never registered it in `_KNOWN_SERVER_PIDS` — registered now, the instant it is known, for the
   identical reason `_kill_and_reap_server_at` registers its own discovery immediately rather than
   after attempting a kill. And the sweep fixture discarded a pid from the registry unconditionally
   even when its own reap attempt raised `TimeoutError` — fixed so the pid is discarded only on a
   *confirmed* reap; an unconfirmed one stays registered, so the very next test's own sweep
   retries it rather than this fixture quietly asserting "eventually reaped" about a pid it never
   actually saw exit.

Full `check.sh` re-run after both fixes: 1035 tests, `ruff format --check`/`ruff check` clean,
`mypy --strict zikaron tests` clean, 99.74% coverage on `zikaron/core`. Integration suite (9
tests — the 8 from round 4 plus the new health-readiness regression test) run three times in
immediate succession with no leftover live process or zombie after any run.
## Author's response to Round 4 — 2026-08-02

Both findings independently re-verified against the code before acting.

1. **[BLOCKER] accepted as stated.** The recursive retry in `ensure_runtime_dir` had no depth
   bound, and the reviewer's threat model is exactly right: a caller cannot distinguish "another
   of my own racing callers is winning" from "something is repeatedly manipulating this path,"
   and only a bounded, controlled rejection is safe against the second case. Replaced the
   recursion with a `for` loop bounded by `_MAX_CREATE_ATTEMPTS = 10`, raising the existing
   `ZikaronError(BAD_CONFIG, ...)` shape if every attempt loses to `FileExistsError` — a
   controlled rejection in the adversarial case, and unreachable in the ordinary two-cooperating-
   callers case, which still resolves on the very first retry since the winner never removes what
   it created. Added `test_ensure_runtime_dir_gives_up_after_too_many_create_attempts`
   (`mkdir` always loses, `lstat` always reports absence, confirming the bound itself fires rather
   than merely trusting that it exists in the code) and fixed the genuine-concurrency test to
   assert `not thread.is_alive()` for every worker before checking `errors` — the reviewer is
   right that a hung worker could previously pass silently if another worker's success alone left
   `errors` empty, which is exactly the "returns a plausible answer instead of failing loudly"
   shape a defensive test itself must not repeat.

2. **[IMPROVEMENT] accepted as stated, and the module's own claim was genuinely overclaiming
   what the code guaranteed.** `_kill_and_reap_server_at` could fail to reach a pid it had
   already learned of — the socket answering `health()` once and then going unreachable before
   the kill attempt — and for an indirectly-spawned server there was no held `Popen` for any
   per-test cleanup to fall back on, unlike `_running_server`'s explicit child. Added
   `_KNOWN_SERVER_PIDS`, populated the instant `health()` reports a pid (before any kill attempt,
   so registration cannot be skipped by the same failure that would defeat the kill), and an
   `autouse` fixture that force-kills and reaps anything still registered after every test — a
   session-wide backstop, not a per-call guarantee, which is the honest width of what this
   mechanism can promise. Narrowed the module's own docstring claim to match: "every server pid
   this module ever learns of is eventually reaped" rather than the previous unconditional
   "every spawned process is reaped." `TimeoutError` is deliberately suppressed only at the
   sweep-fixture level (documented in-line): raising there would fail whichever *unrelated* test
   happens to run next rather than the one that actually caused the leak, while `_running_server`'s
   own unconditional `process.wait()` remains the primary "fail loudly on the test that caused
   it" signal this sweep is a backstop for, not a replacement of.

Full `check.sh` re-run after both fixes: 1034 tests, `ruff format --check`/`ruff check` clean,
`mypy --strict zikaron tests` clean, 99.74% coverage on `zikaron/core`. Integration suite (8
tests) run three times in immediate succession with no leftover live process or zombie after any
run; the two new/fixed security tests
(`test_ensure_runtime_dir_survives_two_genuinely_concurrent_callers`,
`test_ensure_runtime_dir_gives_up_after_too_many_create_attempts`) run five times each with no
flake.
## Author's response to Round 3 — 2026-08-02

All four findings independently re-verified against the code and, where the finding turned on an
OS-level fact, against a direct measurement before writing the fix — this round's finding 1 in
particular showed my round-2 acceptance of finding 4 had genuinely not gone far enough, not merely
that a test was missing.

1. **[BLOCKER] accepted as stated, and it corrects a gap in my own round-2 reasoning.** Round 2's
   response to finding 4 fixed test-side reaping and correctly diagnosed *why* `start_new_session`
   does not reparent a child, but stopped short of asking whether the same fact applies to
   production `_spawn_detached` — it does. Measured directly: a child spawned with
   `start_new_session=True`, its `Popen` object dropped immediately, that then exits **on its
   own** while the spawning process keeps running, shows `State: Z` in `/proc/<pid>/status` for as
   long as the parent lives — confirmed with no kill involved on either side, which is exactly the
   shape a real `zikaron-mcp`/`zikaron-hook` client sees when the service it started later
   self-stops on idle while the client itself is still running. Fixed by starting a daemon thread
   that blocks on `process.wait()` immediately after `_spawn_detached`'s own `Popen` call — reaps
   the child whenever it actually exits, without making `_spawn_detached` itself block, and being
   a daemon thread means it does not keep the *client* process running past whatever else it was
   doing. This does not touch the detached-daemon model itself (the service still runs in its own
   session with no controlling terminal); it only ensures the one process that remains the real
   OS-level parent for the child's whole lifetime also reaps it.

2. **[BLOCKER] accepted as stated.** `_reap` now raises `TimeoutError` on its own deadline instead
   of returning — a cleanup helper reporting success on a timeout is indistinguishable from one
   that actually reaped, and hiding that distinction is precisely the "returns a plausible answer
   instead of failing loudly" shape this project's own coding standards ask every reader to
   distrust in a defensive branch. `_running_server`'s `finally` no longer suppresses
   `process.wait()`'s `TimeoutExpired`: it unconditionally kills (`ProcessLookupError` suppressed,
   since killing an already-dead pid is a no-op) and waits on its own held `Popen` after
   `_kill_and_reap_server_at`, whether or not that call itself succeeded, so a genuinely stuck
   child now fails the test loudly rather than leaking past a swallowed exception.

3. **[BLOCKER] accepted as stated, and it is the more consequential half of this round** — a real
   TOCTOU race I introduced by moving `ensure_runtime_dir` earlier in round 2's fix for finding 1,
   which serialized nothing before this round's fix: two cold clients racing the
   `lstat` → `FileNotFoundError` → `mkdir` sequence can both attempt `mkdir`, and the loser's call
   raised a bare `FileExistsError` with no further vetting of what it found. Fixed by catching
   that exception and recursing into the identical vetting path an already-existing directory
   gets — the recursion re-runs the full `lstat`/symlink/owner/mode check rather than treating "a
   racing caller apparently won" as proof of safety, since a hostile pre-existing directory and a
   legitimate racing winner are indistinguishable from the losing call's own vantage point and
   only one of them is safe to proceed past silently. Three new tests: a monkeypatch-driven
   exact-recovery-path test, its dangerous twin (the "winner" a losing call finds is a symlink,
   confirmed still refused), and a genuine 8-thread concurrency test with a real absent directory
   and no simulation, run five times in isolation with no flake.

4. **[IMPROVEMENT] accepted as stated.** Verified precisely: the existing notification test's
   `params` carried no `client` field at all, so it was suppressing an envelope-*validation*
   failure, never proving a successful dispatch is what gets suppressed — the exact distinction
   this milestone's own round-2 fix (finding 2, `RequestParseError.has_id`) depends on being real
   rather than coincidental. Added a valid `client` envelope and a direct assertion that the
   written memory is actually in the store afterward, so the test now fails if `remember`'s own
   handler were skipped entirely rather than merely its response line withheld.

Full `check.sh` re-run after every fix above: 1033 tests, `ruff format --check`/`ruff check`
clean, `mypy --strict zikaron tests` clean, 99.74% coverage on `zikaron/core`. Integration suite
(8 tests) run three times in immediate succession, checking `ps aux` for both live processes and
zombie state after each run — zero of either after any run. The new
`test_ensure_runtime_dir_survives_two_genuinely_concurrent_callers` run five times in isolation
with no flake.
## Author's response to Round 2 — 2026-08-02

All four blockers and the improvement independently re-verified against the code before acting.
All four accepted as stated; three exposed a genuine misunderstanding on my part that the fix
correction required more than a patch to correct — documented below, not only in the diff.

1. **[BLOCKER] accepted as stated.** Verified precisely: `_try_connect_twice_under_lock`'s first
   `_connect` ran before `ensure_runtime_dir` at all, so a socket already reachable through a
   hostile directory would answer the handshake with this client never vetting anything.
   `security.ensure_runtime_dir(...)` now runs as the *first* statement of
   `_try_connect_twice_under_lock`, before either connect attempt — `architecture.md`'s "before
   creating or using it" is now true of the whole sequence, not only the spawn branch.

2. **[BLOCKER] accepted as stated, and it exposed that my own round-1 fix for finding 6 was
   incomplete in exactly the direction the standing dogfooding lesson in this project's own
   `FINDINGS.md` names** ("a rule stated for one case, silent about the set it implies").
   `RequestParseError` now carries `has_id`, computed and passed at every raise site in
   `parse_request` where it is knowable (`jsonrpc` mismatch, empty method, non-object `params`);
   the two sites where it is *not* knowable (invalid JSON; a non-object top level) default to
   `True` — "there is a response to give," since a truly unparseable line has no notification
   identity to suppress a response for. `_handle_line` checks `error.has_id` before answering a
   `RequestParseError`. Added the case that would have distinguished the fix from a version that
   only checked `RpcRequest.has_id`:
   `test_a_notification_whose_params_fail_shape_validation_still_gets_no_response`
   (`tests/test_service_server.py`) and its framing-layer twin in `test_service_rpc.py`.

3. **[BLOCKER] accepted, and correctly identified a defect deeper than the one line it cited.**
   Verified `search`'s documented shape directly: `architecture.md:642` states a **bare list**,
   `-> [{uuid, gist, tier, state, created_at, updated_at, superseded_by}]`, no wrapping key —
   `SearchResult.as_json()` returned `{"hits": [...]}`, which I had invented in the very first
   draft and never re-checked against the raw wire-shape line directly, only against my own
   prior code in both review rounds. Fixing the shape alone would not have been enough: the
   splice-`session_id`-into-`result` design in `server.py` structurally cannot represent a bare
   list, since a list has no key to add one to. Restructured accordingly rather than patched:
   `RpcResult.as_json()` now returns `object`, not `dict[str, object]`, and
   `rpc.encode_result` gained a `session_id` keyword parameter that attaches the label as a
   **sibling** of `result` — `client: {session_id: ...}`, mirroring the request's own `client`
   object shape — rather than merging it into whatever `result` is. `SearchResult.as_json()` now
   returns the bare list directly. New tests: `test_search_returns_a_bare_list_with_the_label_
   still_attached` and, in `test_service_rpc.py`, three direct tests of `encode_result`'s new
   parameter including the bare-list case specifically. Every other reviewed shape (the flat
   `RankedRecordJson`, `ConflictRecordJson`, etc.) is unaffected by this change, since none of
   them nests inside a value `encode_result` itself constructs.

4. **[BLOCKER] accepted as stated, and the round-1 reasoning behind my own fix was factually
   wrong, confirmed by direct measurement rather than argued away.** I had claimed the indirectly
   spawned server was "several process layers removed" and so `os.waitpid` was unavailable; this
   is false for every process spawned inside this test file, whether via `_running_server`'s
   explicit `Popen` or via `connect_start_if_absent` from `asyncio.to_thread` — a thread of *this
   same process*, not a subprocess, so pytest is the genuine OS-level parent of everything spawned
   either way. Measured directly before writing the fix: `start_new_session=True` does **not**
   reparent a child to init (that requires a double-fork, which this code does not do); a
   `kill()` with no `wait()` on a `Popen` this process is the real parent of leaves a confirmed
   zombie (`State: Z` in `/proc/<pid>/status`); and a zombie process **still appears** in
   `/proc/<pid>` until reaped, which means my round-1 `/proc`-polling fix could never have
   detected the exact failure mode it was written to catch — it would have spun to its own
   deadline and silently returned, reporting nothing. Replaced `/proc` polling with
   `os.waitpid(pid, os.WNOHANG)`, confirmed directly to work correctly even when the `Popen`
   object that spawned a given pid was already dropped (measured: spawn, drop the `Popen`
   reference, kill by bare pid, `os.waitpid` on that pid alone still succeeds). `_running_server`
   now also calls `process.wait()` on its own held `Popen` after the pid-based reap, confirmed
   safe to call on an already-externally-reaped pid (`Popen.wait()` swallows the resulting
   `ChildProcessError` internally rather than raising or hanging). Verified end to end: the full
   integration suite run three times in immediate succession, checking specifically for zombie
   state (`ps aux | awk '$8 ~ /Z/'`) as well as live processes between every run — zero of either
   after any run, where round 1's fix had only ever checked for live processes and would not have
   caught this class of leak at all.

5. **[IMPROVEMENT] accepted for the test coverage half; the `_spawn_detached` stdio routing is a
   separate, narrower question than round 1's finding 4 raised and is answered by the same
   argument that resolved finding 4 itself.** Verified `main.run()`'s `try` already wraps both
   `resolve()` and `ServiceContext.assemble()`, so a store-open failure (schema incompatibility,
   `reindexing`) is already logged by the existing fix — the reviewer is right that no test
   proved it, only the narrower config-parse case. On `_spawn_detached`'s stdio: `architecture.md`
   §Lifecycle's "stdio to the log" describes the **server's own** subsequent behaviour once
   `main.run()` has configured logging, not a promise that everything *before* that point is
   captured — and by finding 4's own resolved argument, the spawning client never holds a pipe to
   the child's stdio in the detached-daemon model this design specifies, so there is no `/dev/null`
   to redirect *to* the log even in principle without violating the same detachment finding 4's
   response defended. What was genuinely missing is what the accepted half of this finding names:
   test coverage for the store-open failure path specifically. Added
   `test_a_schema_incompatible_store_open_failure_at_startup_is_logged_before_the_process_exits`.

Full `check.sh` re-run after every fix above: 1030 tests, `ruff format --check`/`ruff check`
clean, `mypy --strict zikaron tests` clean, 99.74% coverage on `zikaron/core`. Integration suite
(8 tests — the 7 from round 1's fixes plus the new store-open-failure case) run three times in
immediate succession, checking `ps aux` for **both** live processes and zombie state (`STAT`
column `Z`) after each run — zero of either after any run.
## Author's response to Round 1 — 2026-08-02

All ten findings read, verified independently against the cited design lines and the actual code
before acting on any of them. Nine are accepted and fixed; one is accepted in part with a narrower
fix than proposed; two of the accepted fixes surfaced their own follow-on defects during
verification, documented below rather than only in the diff.

1. **[BLOCKER] accepted, fix narrower than proposed.** Verified: `resolve()` ran before
   `log.configure_service_log()` in `main.py`, so a config failure left no trace at all in
   `service.log`. The proposed "startup-status channel back through `connect_start_if_absent`"
   is more than the design asks for, though: `architecture.md` §"Degraded modes" already states
   the client-observable contract for *every* startup failure as one outcome —
   `health()` never becomes reachable, the poll deadline expires, the *client* logs that to its
   own `hook.log` and stops (`"spawn failure, health() never ready... anything unexpected"` is one
   bullet, not per-cause). No client is owed a richer code for a socket that was never bound. What
   *is* owed, and was missing, is the operator-observable half: `service.log` now opens before
   config resolution runs, and a startup failure is logged there before propagating
   (`zikaron/service/main.py`, `run()`). New integration test:
   `test_a_config_failure_at_startup_is_logged_before_the_process_exits`.

2. **[BLOCKER] accepted as stated.** Verified against `architecture.md:417` ("verifies `store_path`
   **and** `store_id`") and the `-32030` `{expected, actual}` payload. `connect_start_if_absent`
   now takes `store_id` explicitly and raises `ZikaronError(ErrorCode.STORE_IDENTITY, ...)`;
   `ForeignStoreError` is deleted. Added the load-bearing case the path-only check would have
   missed entirely — a store deleted and recreated at the identical path gets a fresh `store_id`
   (`Store.create` mints a new UUID every time) — as
   `test_a_client_resolving_the_same_path_but_a_different_store_id_is_still_refused`.

3. **[BLOCKER] accepted as stated.** Verified: the test killed and `wait()`-ed for the server
   *before* calling `connect_start_if_absent`, so no request was ever genuinely in flight when the
   process disappeared — it was testing the stale-socket case a second time under a different
   name. Rewrote it to hold a live connection across the kill and observe that connection's own
   `_send` raise (measured as `BrokenPipeError`, confirmed by a standalone repro before hard-coding
   it in `pytest.raises`), *then* run `connect_start_if_absent` and confirm recovery — the two
   scenarios are now clearly distinct in the file's own structure.

4. **[BLOCKER] accepted for test cleanup; the production half is not a defect.**
   `_kill_and_reap_server_at` (renamed from `_kill_server_at`) now polls `/proc/<pid>` until the
   killed process is actually gone, not just signalled — `os.waitpid` is unavailable to this
   process for a server it never `fork()`ed, several process layers removed by design, so polling
   `/proc` is the portable equivalent for a pid this test does not own.
   **Disagree on `_spawn_detached` needing a reaper in production.** `start_new_session=True`
   makes the spawned server a new session leader with no controlling terminal and no parent
   process group tie to the short-lived client that spawned it; on process exit it is reparented to
   the init process, which reaps it automatically — standard POSIX daemonization, not a leak.
   `architecture.md` §Lifecycle states exactly this mechanism (`"spawn the service detached
   (start_new_session=True, ...)"`) with no reaper mentioned, and the whole design premise is that
   the client *never* holds a handle to what it spawns. A "proper reaper" would require the client
   to become the parent of a process explicitly designed to outlive it, which contradicts the
   detached-daemon model the architecture already specifies.

5. **[BLOCKER] accepted as stated, and restructured further than the minimal fix.** Verified: 
   `method_not_found` was checked before `_resolved_envelope`, and the catch-all used
   `INVALID_REQUEST` (-32600) for a genuine internal bug. Fixed both, and while fixing found the
   naive per-branch `if not request.has_id: return None` (needed for finding 6) would have pushed
   `_dispatch_request` over `PLR0913`/`PLR0911`'s statement-count lints — restructured into
   `_dispatch_request` (computes the line, then applies notification suppression exactly once) and
   a `_compute_response_line` helper (every branch simply answers), which also reads more directly
   as "the suppression is a wrapper concern, not a per-branch decision." Added
   `ProtocolErrorCode.INTERNAL_ERROR = -32603` and
   `test_an_unknown_method_with_a_well_formed_envelope_still_echoes_the_label`.

6. **[BLOCKER] accepted as stated.** `RpcRequest` now carries `has_id: bool`, computed as
   `"id" in parsed` in `parse_request` — distinguishing the key's absence (a notification) from an
   explicit `null` (an ordinary request). `_handle_connection` skips writing when `_handle_line`
   returns `None`. Added `test_a_notification_gets_no_response_line_at_all` and
   `test_an_explicit_null_id_is_a_real_request_not_a_notification`, the latter specifically
   because `dict.get("id")` alone cannot make the distinction the fix relies on — a test that only
   checked the absent-key case could not have told the fix apart from a version that conflated the
   two.

7. **[BLOCKER] accepted as stated.** Verified against `architecture.md:763`'s flat
   `[{uuid, expected_version, gist, content, created_at, rank}]`. Fixed the immediate shape.

8. **[BLOCKER] accepted as stated, and it is the more consequential half of this round.** Verified
   both halves independently: `_try_connect_twice_under_lock` caught bare `OSError` (so `EACCES`
   or a permissions problem would have been silently treated as "absent, spawn a new server"), and
   `security.ensure_runtime_dir` was never called on the client's own start-if-absent path at all —
   only `main.py`'s server-side `run()` vetted the directory, after the client had already created
   `<sock>.lock` inside it. Added `_ABSENT_SERVER_ERRNOS = {ENOENT, ECONNREFUSED}` and an
   `_is_absent_server` predicate used at both catch sites (cold connect and post-lock connect), and
   added `security.ensure_runtime_dir(...)` immediately after acquiring the lock, before the lock
   file itself is created — so a hostile directory is rejected before *any* file this sequence
   creates lands inside it, not merely before the socket bind.

9. **[IMPROVEMENT], applied as a full refactor rather than the narrower fix first proposed.**
   The reviewer is right that the untyped `dict[str, object]` boundary is *why* finding 7 shipped
   undetected, not merely adjacent to it, and the fix has to close that structurally rather than
   add one more test to an interface that will accept the next shape mistake just as quietly.
   Every dispatch handler in `dispatch.py`/`dispatch_consolidation.py` now returns a frozen
   `RpcResult` subclass — one per wire shape `architecture.md` states — with `as_json()` as the
   single seam where a typed value becomes the `dict[str, object]` `rpc.encode_result` frames;
   `params.Handler`'s return type changed from `Awaitable[dict[str, object]]` to
   `Awaitable[RpcResult]`. New module `serialize.py` holds every shape (`ConflictRecordJson`,
   `FetchedMemoryJson`, `SearchHitJson`, `NearDuplicateJson`, `GroupRecordJson`,
   `RankedRecordJson` — the type that makes finding 7's mistake a `mypy --strict` error rather
   than a runtime shape bug — `ShardJson`) plus one dataclass per method's success/conflict/busy
   shape. Both dispatch test files were rewritten to assert on typed fields
   (`result.uuid`, `isinstance(result, ConflictResult)`) rather than dict indexing, and a new test,
   `test_next_group_serves_a_non_empty_candidates_list_in_the_flat_wire_shape`, builds a fixture
   with a genuine second long-term row so `candidates` is non-empty for the first time in this
   file — every prior fixture's `candidates` list was empty, which is exactly the coincidence that
   let the nested-shape bug ship.

10. **[IMPROVEMENT], rejected.** Checked `zikaron/core` directly rather than taking the rule's
    scope on faith: 126 references to `architecture.md`/`schema.md` by name across every
    already-`APPROVED` module in the corpus (`records/memory.py` alone cites it 14 times), which is
    the established house style this project has used since M2. `coding-standards.md`'s own rule
    (§5, "no circumstantial provenance") names its target precisely — "no review-round numbers, no
    `FINDINGS` references, no dates, no ticket ids, no 'as discussed'" — and gives a worked example
    contrasting a round-number citation against a timeless restatement of the reason. A citation of
    *which design document states the normative requirement* is not in that list, and M9's
    docstrings do not carry a single review-round number, date, or ticket id — checked directly
    across every file this finding named. Declining to remove document-name citations that match
    126 precedents this exact standard has already been reviewed and approved against seven times.

Full `check.sh` re-run after every fix above: 1021 tests, `ruff format --check`/`ruff check` clean,
`mypy --strict zikaron tests` clean, 99.74% coverage on `zikaron/core`. Integration suite
(`tests/test_service_lifecycle_integration.py`, now 7 tests — 4 of the original 5 unchanged, the
connect-during-exit race genuinely rewritten to hold a live connection across the kill, plus two
new tests for the store-id-mismatch case and the startup-failure-is-logged case) run three times
in immediate succession with no leftover `zikaron.service.main` process after any run, confirmed by
`ps aux` between runs rather than assumed.
## Round 1 — 2026-08-02

### Summary judgment
The preamble itself is mostly sound: malformed/null labels mint correctly, `label_source` is lexical and unstored, `health()` is separated from resolution, and consolidation ownership correctly uses `ResolvedEnvelope.pid` while health reports `os.getpid()`. The dispatch layer also stays on `aiosqlite` and delegates transaction ownership to core. M9 is not ready, however: startup failures cannot produce the specified service errors, identity verification is incomplete, the required exit race is not tested, several JSON-RPC behaviors are non-conforming, and subprocess cleanup leaks children. This was a direct static review of every named file; this review environment has no command runner, so I could not independently execute the check gate.

### Findings
1. **[BLOCKER] Store/config failures that occur at startup can never reach a client with their specified application codes or payloads.** The error table requires `reindexing`, `bad_config`, and `schema_incompatible` with exact data at `design/architecture.md:1342-1344`, but config resolution and `ServiceContext.assemble()` run before the socket is bound (`zikaron/service/main.py:45-54`; store open is `zikaron/service/context.py:111-116`). The detached child also sends stdout/stderr to `/dev/null` (`zikaron/service/lifecycle.py:116-124`), so a config failure even precedes service-log setup (`zikaron/service/main.py:45-49`) and the starter eventually reports only a transport timeout. Add a startup-status channel (or a bootstrap server state) that carries the original `ZikaronError` code/data back through `connect_start_if_absent`; configure/open the 0600 service log before config resolution and direct detached stderr there, as the lifecycle contract’s “stdio to the log” requires (`design/architecture.md:470`). Add subprocess tests for all three startup failures and assert the exact wire/client error shapes, including the resolved label where a labelled call can be made.

2. **[BLOCKER] The foreign-store handshake verifies only the path, not `store_id`, and does not produce the declared `store_identity` rejection.** The design requires both fields (`design/architecture.md:472`) and fixes `-32030` data as `{expected, actual}` (`design/architecture.md:1345`). `connect_start_if_absent` accepts only `store_db_path` and compares only `health.store_path` (`zikaron/service/lifecycle.py:127-164`); `ForeignStoreError` has neither `ErrorCode.STORE_IDENTITY` nor the specified payload (`zikaron/service/lifecycle.py:91-101`). Change the API to accept the expected store id, compare the pair `(resolved path, store_id)`, and raise/return the declarative `ZikaronError(ErrorCode.STORE_IDENTITY, expected=..., actual=...)`. Extend `tests/test_service_lifecycle_integration.py:270-288` with the load-bearing same-path/different-id case, not only a visibly different path.

3. **[BLOCKER] The done-when “connect as the server exits, then retry once” scenario is not exercised; its test is a duplicate stale-socket test.** M9 explicitly requires this at `design/build-plan.md:256` and the lifecycle rule is one retry after a connected request fails (`design/architecture.md:481-484`). The purported test kills and waits for the server *before* calling `connect_start_if_absent` (`tests/test_service_lifecycle_integration.py:206-229`), exactly the same pre-existing stale-socket setup repeated at `tests/test_service_lifecycle_integration.py:242-265`; no connection survives into the exit window and no failed request triggers a one-retry wrapper. The “idle self-stop” test likewise admits it only sends SIGTERM and never waits for the idle path (`tests/test_service_lifecycle_integration.py:294-319`), so unlink-before-close is not tested end to end. Add a real-subprocess test that connects first, makes the service exit between connection and response, observes that first request fail, and proves one full start-if-absent retry succeeds; also scale the real idle path down in the child and assert the socket disappears before process exit.

4. **[BLOCKER] Test cleanup kills spawned servers but does not reap them, including servers spawned indirectly by start-if-absent.** `_kill_server_at` sends `SIGKILL` by pid and returns without `wait()`/`waitpid()` (`tests/test_service_lifecycle_integration.py:106-130`), while `_running_server` relies on that helper even when it owns a `Popen` (`tests/test_service_lifecycle_integration.py:133-155`) and the race test does the same for an indirectly spawned child (`tests/test_service_lifecycle_integration.py:194-198`). These are direct children of pytest even when spawned from `asyncio.to_thread`, so they can remain zombies. Keep a registry of every direct and indirectly spawned pid/handle, terminate each in `finally`, and reap each with `Popen.wait()` or `os.waitpid()`; assert no registered process remains. Production `_spawn_detached` also drops its `Popen` immediately (`zikaron/service/lifecycle.py:116-124`), which can leave a zombie after idle exit under a long-lived MCP parent; use a proper daemonization/reaper strategy rather than relying on `start_new_session=True` to reparent it.

5. **[BLOCKER] Resolved labels are omitted from two error paths, and genuine internal errors are misreported as invalid requests.** Every post-resolution response must echo the label (`design/architecture.md:98-103`). Method lookup happens before envelope resolution, so `method_not_found` never echoes a valid supplied/minted label (`zikaron/service/server.py:55-61`); unexpected handler failures escape the resolved scope and also lose the label (`zikaron/service/server.py:72-103`). That latter path uses `-32600 INVALID_REQUEST` (`zikaron/service/rpc.py:24-29`, `zikaron/service/server.py:99-103`) even though the architecture calls for a protocol-level internal error (`design/architecture.md:1352`), whose JSON-RPC code is `-32603`. Resolve every non-health request before method dispatch, catch unexpected exceptions inside the resolved scope so the label is attached, and add `INTERNAL_ERROR = -32603`; preserve the no-label exception only when parsing/envelope shape made resolution impossible. Add tests for an unknown method with a valid bootstrap envelope and for an injected handler exception.

6. **[BLOCKER] JSON-RPC notifications receive responses despite the module claiming standard notification behavior.** `RpcRequest` says an absent id gets no response (`zikaron/service/rpc.py:39-42`), but `_handle_connection` writes the returned line for every parsed request (`zikaron/service/server.py:115-117`). Moreover, `parsed.get("id")` conflates an absent id (notification) with an explicit null id (a request that still receives a response). Preserve an explicit `has_id`/notification bit in `RpcRequest`, have dispatch return no line for notifications even when the method fails, and test both absent-id and explicit-null-id cases over the connection loop.

7. **[BLOCKER] `next_group` serializes candidates with the wrong public shape.** The contract is a flat `{uuid, expected_version, gist, content, created_at, rank}` object (`design/architecture.md:763`), while `_served_group_json` emits `{record: {...}, rank}` (`zikaron/service/dispatch_consolidation.py:84-94`). Flatten the record fields into each candidate and add an exact-key assertion to `test_service_dispatch_consolidation.py`; the current tests never inspect a non-empty `candidates` payload.

8. **[BLOCKER] Start-if-absent uses the runtime path before vetting it and catches unrelated connection failures as absence.** A hostile `/tmp/zikaron-<uid>` must be rejected before use (`design/architecture.md:447-449`). The client catches every `OSError`, then creates `<sock>.lock` before any call to `ensure_runtime_dir` (`zikaron/service/lifecycle.py:170-184`); only the spawned server vets the directory later (`zikaron/service/main.py:54`). Thus a symlink/wrong-owner/wrong-mode path can be followed for connect/lock creation, and errors such as `EACCES` are treated as reasons to spawn. Vet/create the runtime directory on the client before its first use, restrict recovery to `ENOENT`/`ECONNREFUSED`, and fail immediately if a present socket is not vettable. Add integration tests that run `connect_start_if_absent` itself against hostile directory, symlink, and non-socket cases—the current security tests exercise only the isolated helpers.

9. **[IMPROVEMENT] The service boundary is built around bare `dict[str, object]` payloads despite the binding typed-domain rule.** Coding standards require every specified payload to be a typed value/frozen dataclass (`design/coding-standards.md:39-48`) and no untyped value crossing module boundaries (`design/coding-standards.md:53-55`), but `Handler` returns `Awaitable[dict[str, object]]` (`zikaron/service/params.py:31-34`) and every dispatch/serializer constructs dictionaries (for example `zikaron/service/dispatch.py:163-177` and `zikaron/service/dispatch_consolidation.py:84-110`). The incorrect candidate shape above is exactly the drift this rule is intended to catch. Introduce frozen response dataclasses/closed outcome unions and perform dictionary conversion only in the RPC encoder; make exact serialization tests table-driven.

10. **[IMPROVEMENT] M9 contains pervasive circumstantial design provenance forbidden by the comment rules.** The standard says code must state timeless reasons rather than references that rot when the corpus moves (`design/coding-standards.md:103-118`), yet examples include direct `architecture.md` citations and D-number provenance in `zikaron/service/paths.py:3-17,30`, `zikaron/service/context.py:3-5`, and `zikaron/service/dispatch_consolidation.py:139-140,220-222` (with similar references throughout nearly every M9 module). Remove document/section/D-number references and retain only the operational rationale and caller contract; test names/docstrings may describe the behavior being asserted without carrying review history.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-08-02

### Summary judgment
Several round-1 fixes are correct on direct inspection: identity compares both path and id and emits only `{expected, actual}`; the exit-race test holds one connected socket across the kill; the two pre-lock connect catches propagate every errno except `ENOENT`/`ECONNREFUSED`; `RankedRecordJson` is genuinely flat; and `main.run()` logs exceptions from both config resolution and `ServiceContext.assemble()`. M9 is still not ready: runtime vetting can be bypassed by the initial connect, parse-time notification errors still receive responses, `search` has the wrong documented wire shape, and process cleanup/reaping remains unsound. I maintain round 1 finding 4 because `start_new_session=True` does not reparent a child; I concur with the response on finding 10 because references to normative design documents are established contract citations rather than review-history provenance. This environment has no command runner, so I could not independently execute `mypy --strict`, ruff, or the tests and do not assume the reported gate result.

### Findings
1. **[BLOCKER] Client-side runtime-directory vetting still happens after the directory has already been used, so a successful first connection bypasses it entirely.** `_try_connect_twice_under_lock` calls `_connect` first (`zikaron/service/lifecycle.py:173-180`) and only calls `security.ensure_runtime_dir` afterward (`zikaron/service/lifecycle.py:182`), immediately before lock creation (`zikaron/service/lifecycle.py:183`). Thus the requested before-lock property is present, and both connect catches correctly recover only from `ENOENT`/`ECONNREFUSED`, but the stronger normative rule is still violated: the fallback runtime directory must be vetted “before creating or using” it (`design/architecture.md:447-450`). A socket reachable through a hostile symlink can answer the first connect and identity handshake without this client ever vetting the directory. Move `ensure_runtime_dir` before the initial `_connect` (at least for the `/tmp` fallback, or safely for every service-owned runtime directory), and add `connect_start_if_absent` tests for a symlink, wrong mode/owner, and non-socket path; the current tests exercise only `ensure_runtime_dir` in isolation (`tests/test_service_security.py:16-84`) and have no errno-propagation test.

2. **[BLOCKER] Notification suppression does not cover errors raised while parsing an otherwise identifiable notification.** `parse_request` computes `has_id`, but `RequestParseError` carries only `request_id` (`zikaron/service/rpc.py:55-66`); for example, an id-less request with non-object params raises `INVALID_PARAMS` at `zikaron/service/rpc.py:100-104`. `_handle_line` then unconditionally emits that parse error (`zikaron/service/server.py:119-124`), despite the framing’s stated rule that a notification receives no response on success or error. Preserve whether an id key was present on recoverable parse errors and suppress responses when a structurally recognizable request omitted it; true JSON parse/invalid-request cases can still answer with null where notification identity cannot be established. Strengthen `tests/test_service_server.py:151-162`: its notification omits `client`, so it only proves suppression of an envelope error and does not prove the notification was processed; assert the `remember` side effect, add an id-less invalid-params case, and exercise explicit-null id through `_handle_line` rather than only `parse_request` (`tests/test_service_rpc.py:46-53`). Ordinary requests are not currently suppressed—the final `request.has_id` check at `zikaron/service/server.py:60-62` is correct—but the test suite does not cover the most important boundary cases end to end.

3. **[BLOCKER] The typed-payload refactor preserves an incorrect `search` wire shape and does not provide the claimed static guarantee over serialized keys/nesting.** The normative shape is a bare list (`design/architecture.md:642-647`), but `SearchResult.as_json()` returns `{"hits": [...]}` (`zikaron/service/dispatch.py:212-218`). The current base API requires every result to become `dict[str, object]`, and the server splats that mapping to append `session_id` (`zikaron/service/server.py:91-95`), so it cannot represent the documented list without changing the response-envelope seam. Also, hand-written `dict[str, object]` literals are not key-checked by mypy: a misspelled key or the old `{record: {...}, rank}` nesting would still satisfy that return type. Align `SearchResult` with the architecture, put the resolved label in a typed response envelope rather than forcing every method payload to be a mapping, and add exact full-value/key-set serialization tests for every `RpcResult` and nested JSON type. The rest of the inspected shapes match their cited contracts, including the flat `RankedRecordJson` at `zikaron/service/serialize.py:180-189`, and handlers now return `RpcResult` through `params.Handler` (`zikaron/service/params.py:32-34`) rather than bare result dictionaries.

4. **[BLOCKER] Test and production reaping are still incorrect; polling `/proc` is not a substitute for waiting on a child.** `_running_server` creates a direct `Popen` (`tests/test_service_lifecycle_integration.py:165-180`) but its `finally` only calls the socket helper (`tests/test_service_lifecycle_integration.py:184-185`). That helper kills the pid and polls `/proc` (`tests/test_service_lifecycle_integration.py:121-160`); a dead direct child remains present there as a zombie until its parent calls `wait`, and `_wait_for_pid_to_exit` silently returns when its deadline expires. A service spawned by `connect_start_if_absent` from `asyncio.to_thread` is also a direct child of pytest—the thread is not a process—so the same argument applies. Failure before the socket becomes reachable is worse: the helper catches `OSError` and returns (`tests/test_service_lifecycle_integration.py:145-146`), potentially leaving the explicit `Popen` running. Keep and `wait()` every explicit handle in `finally`, register indirectly spawned child pids and use `waitpid` when pytest is their parent, make cleanup timeout a test failure, and retain a kill/wait fallback when health is unreachable. In production, `start_new_session=True` (`zikaron/service/lifecycle.py:118-124`) creates a new session but leaves the caller as parent; if a long-lived MCP client starts the service and outlives its idle exit, dropping the `Popen` can leave a zombie. A waiter/reaper may retain the handle without preventing the service from outliving the client, or use a real double-fork/supervisor daemonization strategy; it does not contradict detached operation.

5. **[IMPROVEMENT] Startup exception logging now covers store assembly, but the test and detached-stdio contract cover only the narrower config case.** The `try` includes both `resolve` and `ServiceContext.assemble`, and the catch logs the traceback (`zikaron/service/main.py:57-66`), so a store-open failure will leave a diagnosable `service.log` entry after logging has been configured. The integration test asserts only malformed TOML and only the generic marker (`tests/test_service_lifecycle_integration.py:381-402`); add a store-open failure such as incompatible schema/reindexing and assert identifying exception text/data, so moving `assemble` outside the catch would fail the test. Separately, `_spawn_detached` still sends stdout and stderr to `/dev/null` (`zikaron/service/lifecycle.py:118-124`) even though the lifecycle contract says “stdio to the log” (`design/architecture.md:466-472`); direct them to the per-store service log (or revise the normative contract) so failures before `main.run()` configures logging are not lost.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-08-02

### Summary judgment
Direct static re-verification confirms that the Round 2 fixes for pre-connect runtime vetting, parse-error notification suppression, bare-list search results/session-label framing, and startup store-open logging are implemented as described. The reaping work is only partially complete, however: its polling cannot hang or busy-loop, but both production and test cleanup can still leave children or zombies, and the newly emphasized pre-connect directory check exposes an untested first-use race. This review environment has no command runner, so I could not execute `check.sh`, ruff, mypy, or the tests and do not assume the author's reported counts; I did read the named test files and verify the assertions described below.

### Re-verification notes
- `security.ensure_runtime_dir(...)` is now the first statement of `_try_connect_twice_under_lock` (`zikaron/service/lifecycle.py:177-181`), before either connect. It does perform one `lstat` on every `connect_start_if_absent` call, including a warm connection, but that is consistent with the explicit vet-before-use security contract and the documented short-lived-client usage; caching across calls would make the check stale and is not warranted. The adjacent absent-directory race is finding 3.
- `RequestParseError.has_id` is passed at all three post-object validation raises in `parse_request`—bad `jsonrpc`, bad/missing `method`, and non-object `params` (`zikaron/service/rpc.py:104-129`). Invalid JSON and a non-object top level are the only two `parse_request` sites before object membership makes `has_id` knowable. Invalid UTF-8 is a separate pre-`parse_request` framing failure and correctly receives a null-id parse error (`zikaron/service/server.py:119-121`), not a third missed `RequestParseError` site.
- `server.py` has exactly two `encode_result` call sites: `health` intentionally omits a label, while successful resolved dispatch passes `session_id=envelope.session_id` (`zikaron/service/server.py:67-71,91-95`). All resolved error paths remain on `encode_error` and put the label only in `error.data`; no response construction path can contain both top-level `client.session_id` and `error.data.session_id`, because the former is emitted only for a success and the latter only for an error.
- `_reap` is deadline-bounded and sleeps 20 ms between `WNOHANG` calls (`tests/test_service_lifecycle_integration.py:154-171`), so it cannot hang or busy-loop indefinitely. `_running_server`'s subsequent `process.wait()` is useful for `Popen` bookkeeping and normally returns immediately after an external reap, so it adds no meaningful normal-case runtime; its timeout handling remains defective as finding 2 explains.
- `test_a_store_open_failure_at_startup_is_also_logged` is genuinely distinct from the config failure. It first creates and successfully opens a valid store, commits the `reindexing` sentinel, and then starts the service (`tests/test_service_lifecycle_integration.py:424-447`); `ServiceContext.assemble` calls `Store.open` (`zikaron/service/context.py:102-118`), whose `_validate_on_open` raises `REINDEXING` from that sentinel (`zikaron/core/store/store.py:368-413`). Because the test requires `"failed to start"` in `service.log`, it would fail if `ServiceContext.assemble()` moved outside `main.run()`'s logging `try`.

### Findings
1. **[BLOCKER] The accepted Round 2 production-reaping half is still unchanged: a long-lived client can accumulate a zombie when its detached server exits.** `_spawn_detached` still creates and immediately drops a `Popen` (`zikaron/service/lifecycle.py:117-125`). `start_new_session=True` changes the child's session but not its parent, so if an MCP/client process remains alive beyond the service's idle exit, that client remains responsible for reaping it—the exact premise the Round 2 response now accepts. Retain the handle in a daemon waiter thread that calls `wait()` (which does not prevent the child outliving a client that exits), or use a real double-fork/supervisor strategy; add a subprocess test in which the spawning parent stays alive until the service exits and proves the child is reaped rather than zombie.
2. **[BLOCKER] Test cleanup is bounded but still fails silently instead of guaranteeing cleanup.** `_reap` simply falls off the end when its five-second deadline expires (`tests/test_service_lifecycle_integration.py:163-171`), contradicting its own promise to “fail loudly.” `_kill_and_reap_server_at` returns as soon as health is unreachable (`tests/test_service_lifecycle_integration.py:121-148`), and `_running_server` then suppresses `process.wait(timeout=5)`'s `TimeoutExpired` without killing or reaping that explicit child (`tests/test_service_lifecycle_integration.py:193-200`). Thus a startup/listener failure or delayed SIGKILL can leave a live child/zombie while the test appears to clean up, polluting later CI tests. Raise `TimeoutError` after `_reap`'s deadline, and in `_running_server` use the held handle for an unconditional terminate/kill-and-wait fallback when socket discovery or graceful waiting fails; do not suppress the final cleanup failure.
3. **[BLOCKER] Two first-use clients can race in `ensure_runtime_dir` before they ever reach the lifecycle flock.** On `lstat` `ENOENT`, `ensure_runtime_dir` calls `path.mkdir(..., parents=True)` with `exist_ok=False` (`zikaron/service/security.py:55-78`). If two cold clients both observe absence, one creates the valid directory and the other raises raw `FileExistsError`; moving vetting before the first connect makes this the gateway to the milestone's two-client convergence path. The integration race pre-creates `_runtime_dir`, so it cannot catch this case (`tests/test_service_lifecycle_integration.py:_runtime_dir` and `test_two_clients_racing_a_cold_store_converge_on_one_server`). Make creation race-safe by catching `FileExistsError` and then running the same `lstat`/owner/mode vetting—never blindly accepting the winner—and add a race test beginning with an absent runtime directory.
4. **[IMPROVEMENT] The claimed successful-notification test still never reaches `remember`.** `test_a_notification_gets_no_response_line_at_all` omits `client` (`tests/test_service_server.py:test_a_notification_gets_no_response_line_at_all`), so it suppresses an envelope-validation error rather than proving that a valid notification executes its handler and only suppresses the resulting response. The new invalid-params test correctly covers `RequestParseError.has_id`, but it does not close this separate Round 2 test gap. Give the notification a valid client envelope and assert the memory was persisted (or otherwise assert the handler side effect), retaining the invalid-params case as the parse-layer twin.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-08-02

### Summary judgment
The Round 3 fixes are substantively correct on their intended successful paths: the production child now has a genuine daemon waiter, ordinary and respawned integration cleanup does not double-reap or add a meaningful delay, and the valid notification test proves `remember` actually ran against a fresh store. M9 is still not ready because the runtime-directory recovery is recursively attacker-controlled and can exhaust the stack under path churn; the new genuine-concurrency test also does not assert that its worker threads finished. The integration module additionally overclaims failure-path cleanup for indirectly spawned servers. This review environment has no command runner, so I could not execute `check.sh`, ruff, mypy, or any tests and do not independently verify the author's reported gate runs.

### Re-verification notes
- `zikaron/service/lifecycle.py:141` starts `threading.Thread(target=process.wait, daemon=True)`, so this is a real daemon thread and the bound method retains the `Popen` until the wait ends. Warm `connect_start_if_absent` calls do not invoke `_spawn_detached`; one waiter is created only for each child actually spawned, and it terminates when that child exits, so healthy repeated calls do not accumulate one thread per call. A child that hangs forever before binding can still leave one live process and waiter per later spawn attempt, but that is not a waiter-only leak introduced by this fix—the thread accurately mirrors an unreaped live child.
- The integration file never calls `_spawn_detached` directly. `_spawn_server` creates the production `main.py` child without the new waiter; only a later `connect_start_if_absent` respawn (and the cold two-client race) reaches `_spawn_detached`. For those indirect children, the daemon waiter's `Popen.wait()` and `_kill_and_reap_server_at`'s `os.waitpid` can wait on the same pid, but the kernel permits only one reap: the loser observes `ChildProcessError`/`ECHILD`, which `_reap` handles and `subprocess.Popen.wait()` handles internally. There is no lost wakeup, double-free, or unreaped zombie on this successful cleanup path.
- In ordinary `_running_server` cleanup, `_kill_and_reap_server_at` kills and reaps the listening `process.pid`; the subsequent `process.kill()`/`process.wait()` resolves immediately (including after an external `waitpid`) rather than consuming its five-second timeout. The two store-identity tests never respawn, so their health pid does not diverge from `process.pid`. In the mid-connect and stale-socket tests it does diverge after respawn, but both tests already killed and `wait()`-ed the original explicit `Popen` before spawning the replacement; cleanup reaps the replacement, then the final wait on the already-recorded-dead original returns immediately. The cold racing test has no explicit `Popen` at all. Thus the unconditional fallback adds negligible normal-path overhead and cannot hang on a different live child in these eight tests.
- `tests/test_service_server.py:196-198` queries a real `memory.gist` column (`zikaron/core/store/ddl.py`, `_MEMORY`). `open_context` creates a fresh store for this test and seeds no memories, and the valid notification's `remember` call inserts the sole `gist = 'g'` row before response suppression. The assertion therefore cannot pass if dispatch skips the handler; it is not made vacuous by prior fixture state.
- The author's claim of a genuine OS-level concurrency exercise is fair but should not be read as proof that a real `FileExistsError` occurred in every run: the eight real threads may schedule serially. The paired monkeypatched test deterministically covers the losing branch. The reported direct measurements and check-gate counts cannot be reproduced here because no command runner is available.

### Findings
1. **[BLOCKER] `ensure_runtime_dir` has an unbounded, attacker-controlled recursive retry, and its real-concurrency test can pass with stuck workers.** On `FileExistsError`, `zikaron/service/security.py:84-89` recursively calls `ensure_runtime_dir`. With two cooperative callers, the winner never removes the directory, so the loser normally sees that stable entry on its very next `lstat`; this correctly fixes the Round 3 cold-start race. That stability is not guaranteed in the threat model this helper exists for, however: another local user can repeatedly create an entry after this process sees `ENOENT`, make `mkdir` lose, and remove its own entry before the recursive `lstat`, driving one additional Python stack frame per cycle until `RecursionError`. Moreover, `tests/test_service_security.py:99-101` joins each thread with a timeout but never asserts `not thread.is_alive()`, so a regression that hangs one worker can still pass if another worker created the correctly-moded directory and `errors` remains empty. Replace recursion with a bounded iterative retry (after a small number of disappear/reappear cycles, raise the existing controlled `BAD_CONFIG` runtime-dir error), add a deterministic test for repeated `FileExistsError` followed by disappearance, and assert every concurrency-test thread terminated before checking `errors`.
2. **[IMPROVEMENT] The integration module's “Every spawned process is reaped” claim is stronger than its failure-path cleanup guarantee.** `_kill_and_reap_server_at` returns at `tests/test_service_lifecycle_integration.py:148` whenever connecting or reading health raises `OSError`. `_running_server`'s held-`Popen` fallback fixes this for the original explicit child, but after a `connect_start_if_absent` respawn that handle names the already-dead original; the live indirect child is known only through the socket. The cold racing test likewise has no held handle. If such an indirect server remains alive but stops answering health, cleanup returns and neither the production daemon waiter (which waits for exit, not kills) nor the stale explicit handle can terminate it. Register each indirect pid as soon as health identifies it (for example, retain the pid in `HealthCheck` and in a test-owned set), then kill/wait those registered pids in `finally` even when the socket handshake is no longer usable; narrow the module-level claim until that fallback exists.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-08-02

### Summary judgment
The Round 4 bounded-loop fix is correct on direct branch-by-branch inspection, and its deterministic test terminates after the intended ten losses; the PID set also has no current in-process mutation race or xdist sharing problem. M9 is still not ready, however: the PID backstop does not register indirectly spawned servers when the tests first learn their pids and then suppresses the very cleanup failure it exists to expose, while the production start-if-absent path releases its flock after a bare connect rather than after the required successful `health()` poll. This was a static review: this environment has no command runner, so I could not execute the author's reported tests, ruff, mypy, or check gate and do not assume those results.

### Re-verification notes
- `zikaron/service/security.py:114-133` executes `range(_MAX_CREATE_ATTEMPTS)` with `_MAX_CREATE_ATTEMPTS = 10`, so ten—not nine—iterations can each reach `mkdir`. A successful `mkdir` takes the `chmod`/`return` path in that same iteration; a successful existing-directory vet reaches the final in-loop `return`; every hostile existing-path branch raises immediately; and only ten consecutive `FileExistsError` continuations fall through to `_too_many_create_attempts`. There is no legitimate success path that can accidentally reach the terminal raise.
- `tests/test_service_security.py:115-143` patches target `lstat` to raise `FileNotFoundError` and every target `mkdir` to raise `FileExistsError`. Neither fake calls the other, and the loop itself owns the finite iteration, so the test cannot recurse or hang in its monkeypatch: it performs ten absent/lost cycles and raises `BAD_CONFIG`. An explicit call-count assertion would pin the numeric constant more tightly, but the current test correctly exercises exhaustion and this is not a shipping defect.
- `_KNOWN_SERVER_PIDS` is process-local. Neither `pyproject.toml` nor `requirements-lock.txt` declares/configures `pytest-xdist`, and even an externally requested xdist run would give each worker its own set and direct children. In this module, `asyncio.to_thread` is used for `connect_start_if_absent`/health work, but all current `_KNOWN_SERVER_PIDS.add`/`discard` calls occur only in synchronous `_kill_and_reap_server_at` or fixture teardown after those awaited calls complete; the fixture snapshots with `list(...)`, so there is no current concurrent-iteration race.
- The module-local PID sweep and `tests/conftest.py:_no_leaked_store_connections` are both function-scoped autouse fixtures but share no resource: the latter counts only threads whose target is aiosqlite's worker function, so neither `asyncio.to_thread` workers nor production's daemon `Popen.wait` thread are mistaken for leaked stores. Their teardown order does not change either check's result. A fresh full read of `zikaron/service/server.py` found no additional material defect not covered by prior rounds.

### Findings
1. **[BLOCKER] Start-if-absent treats a bare socket connection as startup success, releases the flock, and only then tries `health()` once.** `zikaron/service/lifecycle.py:_try_connect_twice_under_lock` returns `_poll_until_reachable(sock_path)` from inside the lock, whose only success condition is `_connect`; its `finally` then unlocks and closes the lock fd. Only afterward does `connect_start_if_absent` call `_health(sock)`. This contradicts the normative sequence's “spawn ... then poll `health()` until a deadline” before “release the lock” (`design/architecture.md:463-472`): if a child accepts a connection but exits, stalls, or returns an incomplete response before the handshake, the starter propagates that one failure and another racer can leave the lock believing startup completed, rather than observing one serialized health-ready outcome. The same path does not close `sock` when `_health` raises, leaving an opened transport owned only by exception-frame lifetime. Replace `_poll_until_reachable` with a deadline-bounded connect-and-`health` poll performed while the flock is held, closing every failed-attempt socket; return both the connected socket and parsed `HealthCheck`, release the lock only after that succeeds, and then perform the path/id mismatch decision. Add a test server that accepts before failing/delaying its first health exchange so a plain-connect implementation cannot pass.
2. **[BLOCKER] The new PID registry still misses the failure window it claims to close, and its sweep silently discards an unconfirmed reap.** `tests/test_service_lifecycle_integration.py:164-204` adds a pid only when `_kill_and_reap_server_at` performs a *fresh cleanup-time* health call. But the cold-race test already learns the indirect server pid in `_connect_and_report_server_pid` (`tests/test_service_lifecycle_integration.py:288-317`) without registering it, and other respawn tests successfully complete health before cleanup as well. If that indirect server becomes unreachable before the later cleanup helper connects, the helper returns with the set still empty and the autouse sweep has nothing to kill—the exact between-test-operation-and-cleanup gap the Round 4 finding described remains. Further, `tests/test_service_lifecycle_integration.py:75-88` suppresses `_reap`'s `TimeoutError` and unconditionally discards the pid; a yield fixture's post-`yield` failure is teardown of the test that just ran, not setup of an unrelated next test as the comment claims, so suppression both hides the responsible test's cleanup failure and makes “eventually reaped” false. Register every indirect pid at the first successful health result (for example, include `pid` in `HealthCheck` and register it immediately in these tests), keep it registered until reaping is confirmed, and let sweep timeout fail the current test while retaining enough state for a final session cleanup attempt.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-08-02

### Summary judgment
The Round 5 production fix is correct on direct branch-by-branch inspection: the spawn branch now completes a genuine `health()` exchange while still holding the flock, returns that parsed health value, and does not run a second handshake on the same socket after unlocking. M9 is still not ready, however: the new regression test can leak its infinite fake child on precisely the failure it is meant to expose, partial `ServiceContext` assembly can strand a non-daemon aiosqlite worker and prevent startup failure from exiting, and the server does not actually track every request for idle self-stop as both the architecture and its own docs claim. This was a full static reread of every file named in the brief; this environment has no command runner, so I could not execute the tests, ruff, mypy, or `check.sh` and do not assume the reported gate result.

### Re-verification notes
- `_try_connect_twice_under_lock`'s three returns now have the declared `tuple[socket.socket, HealthCheck | None]` shape: first-connect success returns `(_connect(...), None)`; post-flock connect success returns `(_connect(...), None)`; and the spawn path returns `_poll_until_reachable(...)`, whose success is exactly `(sock, HealthCheck)`. `connect_start_if_absent` therefore calls `_health(sock)` only for the two bare-connect branches. Neither branch has passed that socket to an inner consumer, while the spawn branch reuses its already-parsed `HealthCheck` and never calls `_health` twice. A successful `_health` consumes one request/response, not the socket itself; the real server's per-connection loop remains open for later requests. The fake server is a test-specific exception because it explicitly closes its successful connection, addressed in finding 1.
- The daemon reaper is wired correctly: `threading.Thread(target=process.wait, daemon=True).start()` invokes the bound `Popen.wait` method for this plain Python fake just as it does for `main.py`. It only waits, though; it does not terminate the fake's infinite `accept()` loop. On successful test cleanup, `_kill_and_reap_server_at` learns the pid, kills it, and either its `waitpid` or the daemon waiter reaps it; the losing waiter safely observes an already-reaped child. The unregistered pre-return failure window remains finding 1.
- The Round 5 change does not create a new hardcoded-deadline risk in the named existing tests. Production `main.run` completes `ServiceContext.assemble()` before `serve()` binds, so for the real service a successful bare connect already occurs only after genuine readiness; moving that first health exchange under the flock adds one local RPC, not another model-load interval. The two-client race has no outer timeout and retains the lifecycle's 10 s health deadline (with 1 s per socket operation and 50 ms retry sleeps); the second racer merely waits through the winner's one health exchange. The idle-self-stop test and both startup-log tests call `_spawn_server` directly and never enter the changed branch. Their existing bounds—15 s for socket appearance, 10 s for startup-failure exit, 5 s for process waits/reaps, 2 s socket timeouts, and the configured 60 s idle minimum that the test deliberately does not wait out—are unchanged. The fake's three refusal attempts fail immediately and add only its deterministic 50 ms retry sleeps. I found no new timing flake attributable to this fix.
- The lifecycle phrase-family search found no stale pre-Round-5 description. The module preamble, `_try_connect_twice_under_lock`, and `_poll_until_reachable` all state poll-`health()` before unlock. The two remaining “bare” references intentionally and accurately describe steps 1 and 3; `connect_start_if_absent`'s “a connected socket” return phrase is also still true for the real server and does not describe the old polling condition. Separate stale search-result prose outside lifecycle is finding 6.

### Findings
1. **[BLOCKER] The new health-readiness regression can leak its infinite fake process on the exact old-code failure, and its success path returns a peer-closed socket without testing the return contract it claims to prove.** In `tests/test_service_lifecycle_integration.py:test_a_connected_but_not_yet_health_ready_server_is_not_treated_as_started`, the `sock, health = await ...` assignment occurs before the `try/finally`. Under the old bare-connect implementation, the first refused handshake makes `connect_start_if_absent` raise before `sock` is assigned, so `_kill_and_reap_server_at` never runs. The pid was never learned or added to `_KNOWN_SERVER_PIDS`, and `_spawn_detached`'s daemon waiter merely blocks forever because `_fake_server_script` loops forever in `accept()`; it cannot kill the child. Even on the fixed path, `_fake_server_script._handle` sends the successful health response and immediately closes `conn`, while the test only inspects the already-parsed `health`; thus the returned socket's next real request would fail despite the test docstring claiming it returns a socket that genuinely answers. Have the fake write its pid to a test-owned file immediately after binding, put the entire `connect_start_if_absent` call inside an outer `try/finally`, and kill/reap that pid directly even when the call raises before returning. Keep a successful connection open for multiple requests and assert a second `_send(sock, "health", {})` succeeds after `connect_start_if_absent` returns; then close that socket before opening the cleanup connection.
2. **[BLOCKER] `ServiceContext.assemble` leaks the opened store if any later construction step fails, which can keep a failed service process alive indefinitely.** `zikaron/service/context.py:ServiceContext.assemble` assigns `store = await Store.open(...)` and then calls `FastEmbedEncoder.load`, `IndexingContext.for_store`, and several settings constructors before ownership reaches a returned `ServiceContext`; none is protected by a `finally`. If any of those raises (the docstring explicitly permits encoder `BAD_CONFIG`), `main.run` has no `ctx` to close. This violates `design/coding-standards.md`'s binding rule that every `Store` is held with `async with` or closed in a `finally`; its aiosqlite worker is non-daemon, so the logged startup failure can then hang instead of exiting. Wrap every post-open construction step in `try/except BaseException`, `await store.close()` before re-raising, and add a test that forces `FastEmbedEncoder.load` (or `IndexingContext.for_store`) to fail after a successful open and proves both that the connection worker is gone and that a real child exits after logging the failure.
3. **[BLOCKER] Idle activity does not bracket “each request” or the “whole dispatch,” contrary to the architecture and the service's own concurrency note.** In `zikaron/service/server.py:_compute_response_line`, `health` returns before `ctx.activity.begin_request()`, and envelope failures and unknown methods also return before it; the begin/end pair surrounds only a found non-health handler. Consequently repeated successful health requests never refresh `last_activity`, and idle self-stop can stop a service that is actively being health-checked. This directly contradicts `design/architecture.md` §Idle self-stop (“`last_activity` is refreshed when each request completes”) and `server.py`'s module docstring claim that begin/end bracket the whole dispatch. Move the begin/end ownership to `_dispatch_request` around `_compute_response_line` so every successfully parsed `RpcRequest`—health, notifications, resolved errors, and ordinary calls—updates the clock and contributes to `in_flight`; retain parse/framing failures outside it. Add focused tests for health and unknown-method requests as well as handler success/failure.
4. **[IMPROVEMENT] The widened return logic still has no deterministic socket close when either bare-connect branch's post-lock `_health(sock)` fails.** `zikaron/service/lifecycle.py:connect_start_if_absent` closes on identity mismatch, and `_poll_until_reachable` closes every failed spawn attempt, but `health = ... else _health(sock)` leaves ownership implicit if a previously reachable server closes or malforms its response during the first/second branch handshake. This socket was not consumed or closed by an inner call—the tuple reasoning is correct—but it should not depend on exception-frame destruction for cleanup. Wrap the outer health/identity sequence in an exception path that closes `sock` before re-raising, without closing the successfully returned socket.
5. **[IMPROVEMENT] The consolidation module's claim that a non-consolidator envelope is unreachable is false, and the reachable caller error is mislabeled as an internal server bug.** `zikaron/service/dispatch_consolidation.py`'s module docstring says nothing routes a non-consolidator envelope to these handlers because methods are disjoint, but `server.py` dispatches solely by the caller-selected method name; an `mcp` caller can select `merge` or `next_group`. `_consolidation_call` then constructs `ConsolidationCall`, whose intentional client-kind invariant raises `ValueError`, and `server.py` logs/returns `-32603 INTERNAL_ERROR`. The invariant prevents receipt-scope corruption, so this is not an authorization bypass, but it is a reachable invalid-caller path rather than a server defect. Validate `envelope.kind == "consolidator"` at the service boundary and return a declared caller error (for example `BOUNDS` naming `client.kind`), add an end-to-end dispatch test, and replace the false “unreachable” explanation.
6. **[NITPICK] Two docstrings still describe the pre-Round-2 wrapped search shape.** `zikaron/service/dispatch.py:search` says `-> {hits: [...]}` even though `SearchResult.as_json()` correctly returns the architecture's bare list, and `zikaron/service/serialize.py`'s module preamble says every typed value becomes a `dict[str, object]` frame before the class-level explanation correctly widens it to `object`. Change the method docstring to `-> [SearchHit, ...]` and the serialization preamble to “JSON value”/`object` so the phrase-family audit is consistent outside lifecycle too.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-08-02

### Summary judgment
Five of Round 6's six fixes are correct on direct static inspection: activity now brackets every parsed request without interfering with final notification suppression, legitimate consolidator envelopes still construct `ConsolidationCall`, the primary-method asymmetry is principled because `client.kind` is provenance rather than authorization there, and the stale search prose is fixed. The fake-server cleanup fix remains incomplete on exactly the regression path it is meant to survive, and `ServiceContext.assemble` can replace the construction failure with a cleanup failure rather than preserving it. I also found one repeated socket-cleanup omission in the fresh M9 reread. This environment has no command runner, so I could not execute tests, ruff, mypy, or `check.sh` and do not assume the author's reported gate results.

### Findings
1. **[BLOCKER] The health-readiness regression still leaks its infinite fake child if `connect_start_if_absent` fails during the refused-handshake phase.** The outer `try/finally` at `tests/test_service_lifecycle_integration.py:384-407` is now correctly placed, but the fake is configured to refuse three health exchanges (`:382`) and its pid is registered only after the returned socket successfully answers the extra request (`:403`). Under the old bare-connect behavior, `connect_start_if_absent` returns from its poll after the first connect and then fails its first `_health`; the `finally` calls `_kill_and_reap_server_at`, whose cleanup connection is merely refusal number two, so `_send` raises, the helper returns before learning a pid, `_KNOWN_SERVER_PIDS` is still empty, and the fake's endless `accept()` loop survives. This is why Round 6 explicitly requested a test-owned pid file written immediately after bind; implement that (or otherwise expose the spawned pid independently of health), register it before calling `connect_start_if_absent`, and kill/reap that known pid in `finally`. The second-request assertion and keep-open fake behavior are otherwise correct.
2. **[IMPROVEMENT] `ServiceContext.assemble` re-raises only if cleanup succeeds; `Store.close()` can mask the original construction failure.** `zikaron/service/context.py:138-140` catches the original `BaseException`, awaits `store.close()`, then uses bare `raise`, but `Store.close` is itself an await of `aiosqlite.Connection.close()` with no non-raising guarantee (`zikaron/core/store/store.py:258-260`). If that await raises, callers see the close failure instead of the documented encoder/settings failure, making startup diagnosis confusing; the new test covers only successful cleanup. Capture the original exception, attempt close in a nested `try`, and if cleanup fails preserve the original as the raised/top-level exception while chaining or annotating the cleanup failure (and logging it if appropriate). Add a test forcing both construction and close to fail and asserting the construction error remains primary. The ordinary path does close and re-raise correctly; it does not swallow the original when close succeeds.
3. **[IMPROVEMENT] `_connect` leaves socket cleanup to object destruction when `connect()` raises, including every failed startup-poll attempt.** `zikaron/service/lifecycle.py:74-78` allocates a socket and calls `sock.connect(...)` without an exception path that closes it. `_poll_until_reachable` can close only sockets `_connect` returned, so its repeated `ENOENT`/`ECONNREFUSED` attempts cannot explicitly release these failed sockets. CPython will normally reclaim the local promptly, but this is the same exception-path ownership class already corrected around post-connect `_health`; wrap setup/connect in `try/except BaseException`, close the socket, and re-raise.
4. **[NITPICK] `_dispatch_request`'s “never raises” contract is stale; the outer `_handle_line` catch is not dead code and should remain untested as an unreachable-value branch.** `zikaron/service/server.py:43` says `_dispatch_request` never raises, while `:128-141` intentionally catches failures outside the handler's resolved scope. The activity `finally` guarantees `end_request` runs, but it does not convert exceptions from `health`, unexpected envelope/pre-handler failures, response encoding, or activity bookkeeping into a line; those reach `_handle_line`, which correctly provides the server-boundary `INTERNAL_ERROR` fallback and still suppresses notifications. This is unlike the coverage-chasing anti-pattern in `FINDINGS.md`: it returns an explicit protocol error for a real unexpected server failure, not a plausible domain value that pretends an invariant held. Change “never raises” to describe the normal/error-mapping contract; do not add a monkeypatch-only test merely to cover the defensive branch.
5. **[NITPICK] `rpc.encode_result` still claims `surface` has a bare-string result.** `zikaron/service/rpc.py:136-138` cites both search's bare list and “surface's ready-to-print text” as values with no key, but `dispatch.SurfaceResult.as_json()` returns `{\"text\": ...}`. Keep search as the motivating bare-list case and remove the bare-string claim.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-08-02

### Summary judgment
All five Round 7 fixes are present on direct inspection: the PID file is necessarily written before the fake can refuse a handshake, the nested bare `raise` re-raises the outer construction failure and the new test discriminates it, `_connect` closes on failure, and both production docstrings are corrected without a defensive monkeypatch test. The target fake-server live-process leak is closed, although its new cleanup still silently accepts an unconfirmed reap. A fresh static cross-check found two previously unreported contract defects—one in the public consolidator RPC names and one in readiness handling—so M9 is not yet ready. This environment has no command runner, so I could not execute the reported tests, ruff, mypy, or `check.sh` and do not assume those results.

### Findings
1. **[BLOCKER] The implemented consolidator write method names do not match the normative Service RPC surface.** `design/architecture.md:1380` exposes `apply_merge`, `apply_promote`, and `apply_discard`, but `zikaron/service/dispatch_consolidation.py:383-389` registers only `merge`, `promote`, and `discard`; `server.py` dispatches directly from that mapping, so a client implemented against the design receives `METHOD_NOT_FOUND` for all three writes. The existing dispatch-consolidation tests call Python handlers directly and therefore cannot detect the wire-name mismatch. Either change the mapping to the three `apply_*` names or deliberately amend the architecture before M10 consumes it, then add `_handle_line`/wire-level tests using the exact agreed method strings.
2. **[BLOCKER] A `health()` response with `ready: false` is treated as readiness and can release the startup flock.** `_health` coerces the field with `bool(result["ready"])` (`zikaron/service/lifecycle.py:110-120`), while both `connect_start_if_absent` and the under-lock spawn poll accept any successfully parsed `HealthCheck` without requiring `ready is True` (`zikaron/service/lifecycle.py:187-204,274-288`). Thus `false` is accepted as a completed handshake, and even malformed truthy values such as `"false"` become true; this violates the lifecycle's poll-until-ready ordering at `design/architecture.md:463-472`. Require an actual JSON boolean whose value is `true`; on the spawn branch, false should close that attempt and keep polling, while a bare-connect branch should close and reject it. Add a discriminating fake that returns a structurally valid, matching-identity `ready: false` response several times before returning true—the current refusal fake only covers missing responses and would pass this bug.
3. **[IMPROVEMENT] A bound server is not put under cleanup ownership until after several fallible setup operations.** `main.run` acquires the listening `asyncio.Server` at `zikaron/service/main.py:70`, then runs `sock_path.chmod`, signal-handler installation, and task creation before entering `async with server` at `:71-80`. If any operation in that interval raises, `ctx` is closed but the listener is never explicitly closed/waited and the newly created socket path is never unlinked; process exit usually recovers the descriptor, but the coroutine does not establish the resource guarantee itself and an in-process caller can retain the stale endpoint. Put the server under an immediate `async with` or `try/finally` as soon as `serve` returns, and ensure post-bind initialization failures close the listener and unlink the owned socket; add a focused failure-path test around one setup operation.
4. **[IMPROVEMENT] The PID-file fix closes the refused-handshake live-child gap, but its `finally` does not guarantee the claimed reap.** The fake writes its pid after `listen()` and before its first `accept()` (`tests/test_service_lifecycle_integration.py:328-338`), so any refused handshake necessarily happens after the file exists, and the outer `finally` always attempts the direct kill (`:425-443`). However, that block suppresses `_reap`'s `TimeoutError` at `:442-443`, never adds this independently learned pid to `_KNOWN_SERVER_PIDS`, and then allows the test to pass; an unconfirmed zombie/reap therefore has no later sweep retry, contrary to the module's “eventually reaped” guarantee. Register the pid immediately when the file is read, let a reap timeout fail this test, and discard it only after `_reap` confirms completion (including its already-reaped `ChildProcessError` case).
5. **[NITPICK] One test docstring retains the bare-string claim removed from production.** `tests/test_service_rpc.py:133-135` says session-label framing supports a “bare-list or bare-string” service result, but the only exceptional current shape is search's bare list; `surface` returns `{text}`. Remove “or bare-string” so the test describes an actual service contract rather than a merely generic encoder capability.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-08-02

### Summary judgment
All five Round 8 fixes are present on direct inspection. The complete method-name cross-check is now clean: `PRIMARY_METHODS` registers `remember`, `amend`, `retire`, `search`, `surface`, and `fetch`; `CONSOLIDATOR_METHODS` registers `plan_groups`, `next_group`, `apply_merge`, `apply_promote`, and `apply_discard`; and `health` remains the intentional separately-dispatched method. The readiness, bound-server, PID-cleanup, and stale-docstring fixes also route as claimed, but a fresh wire-field pass found that resolved errors put the label at the wrong JSON path, and a persistent idle connection can prevent both idle and signal shutdown forever. This environment has no command runner, so I could not execute the reported tests, ruff, mypy, or `check.sh`; the review is static, supplemented by the installed Python 3.12 `asyncio.Server` source where noted.

### Findings
1. **[BLOCKER] Resolved error responses violate the documented response-envelope path and mutate every declared error-data shape.** The architecture requires `client.session_id` in the response envelope “on success and on every error alike” (`design/architecture.md:98`) and separately specifies each application error's `data` object, for example `not_found` as `{uuid}`, `bounds` as `{field, limit, actual}`, `store_busy` as `{verb}`, and `store_identity` as `{expected, actual}` (`design/architecture.md:1328-1345`). Successes correctly use top-level `client: {session_id}` through `encode_result`, but resolved `METHOD_NOT_FOUND`, `ZikaronError`, and internal-error paths instead put a bare `session_id` key inside `error.data` (`zikaron/service/server.py:94-122`); `encode_error` has no response-envelope `session_id` facility. The tests cement the wrong path by asserting `error.data.session_id` (`tests/test_service_server.py:112-122,163-173`). A client implemented against the normative `client.session_id` path cannot adopt a minted label from a failing bootstrap call, and code branching on an error's declared data shape receives an undocumented extra field. Extend error framing to attach the same top-level `client: {session_id}` sibling used by successes, pass it on every post-resolution error, leave each domain error's `data` unchanged, and add exact full-envelope assertions for a bootstrap application error, method-not-found, and internal error.

2. **[BLOCKER] An accepted but idle client connection can prevent both idle self-stop and signal shutdown forever.** `idle_self_stop` unlinks and calls `server.close(); await server.wait_closed()` (`zikaron/service/lifecycle.py:65-71`), while each accepted handler can remain indefinitely blocked in `reader.readline()` until the peer closes (`zikaron/service/server.py:158-174`). Under the project's pinned Python 3.12 (`pyproject.toml:9`), `asyncio.Server.close()` stops accepting but does not close active transports, and `wait_closed()` explicitly waits until active connections are dropped (`/usr/lib/python3.12/asyncio/base_events.py:335-348,381-404`). The signal path has the same problem: cancelling `serve_forever` enters that method's own close-and-wait sequence, and `main.run` awaits that task first (`zikaron/service/main.py:81-92`). Thus a conforming persistent client that has finished a request but retains its socket—`in_flight == 0`, so idle stop is allowed—can leave the service hung after its socket path disappears; SIGTERM can hang the same way. The purported idle integration test cannot detect this because it explicitly does not wait for idle and opens no client connection, exercising only a signal exit with no active transport (`tests/test_service_lifecycle_integration.py:781-801`). Track accepted connection tasks/writers and, on shutdown, close their transports (or cancel and await their handlers) before awaiting `server.wait_closed`; add a bounded test that sends one request on a real connection, leaves that connection open and idle, triggers idle stop, and proves the service exits and the peer observes closure, plus the equivalent signal case.

3. **[IMPROVEMENT] `main.run` owns the listener on exceptions now, but not the lifecycle tasks it may already have created.** The task-cancellation loop runs only after `asyncio.wait` returns normally (`zikaron/service/main.py:79-92`). Cancellation of `run()` while it is awaiting, failure after only one of the task-creation calls, or an exception while awaiting the first completed task jumps directly to the server cleanup handler; any already-created `idle_task`/`signal_wait` is not cancelled and awaited there. The new Round 8 test fails during signal-handler installation, before any task exists, so it proves listener unlinking but cannot justify its broader claim that task creation is covered by the same representative setup failure (`tests/test_service_main.py:32-70`). Keep a collection of each task as soon as it is created and cancel/await all of them in an unconditional `finally` (preferably with `gather(..., return_exceptions=True)` so one task's failure cannot skip the rest); remove any installed signal handlers there as well. Add a cancellation test after all three tasks exist and assert none remains pending.

4. **[IMPROVEMENT] Context cleanup can still replace the original serving/setup failure with a close failure.** `main.run` unconditionally executes `await ctx.close()` in its outer `finally` (`zikaron/service/main.py:111-112`), and `ServiceContext.close` simply awaits `Store.close` (`zikaron/service/context.py:157-159`), which this review has already established can raise. Consequently the setup error the new direct test is meant to preserve—or any later serving exception—gets masked if context cleanup also fails, repeating outside `ServiceContext.assemble` the exception-masking class fixed in Round 7. Preserve an active primary exception while logging/chaining a secondary close failure, but continue to propagate a close failure when shutdown was otherwise normal; add the two-failure test at `main.run` level.

5. **[NITPICK] The new readiness test is discriminating, but its prose claims a non-boolean case it never exercises.** The fake sends literal JSON `false` for `ready_false_attempts` (`tests/test_service_lifecycle_integration.py:332-341`), and this genuinely fails the old end-to-end behavior because old `_health` returned `HealthCheck(ready=False)` and its caller ignored `.ready`; the current test then correctly requires eventual `health.ready is True` (`tests/test_service_lifecycle_integration.py:466-491`). However, both the helper and test docstrings say this protects against a future truthy string, while no response ever sends `"false"` or another non-boolean (`tests/test_service_lifecycle_integration.py:337-341,466-477`). Either parameterize the fake's not-ready value and include a truthy non-boolean—the value that directly distinguishes `bool(value)` from a literal-`True` check—or narrow the prose to the literal-false behavior actually proved.

6. **[NITPICK] One production summary still states the old consolidator names and even the wrong method count.** `zikaron/service/dispatch.py:12` says “The four consolidator methods” and then lists five entries as `plan_groups`, `next_group`, `merge`, `promote`, `discard`, despite the corrected service wire table containing five RPC methods with the three writes named `apply_*` (`zikaron/service/dispatch_consolidation.py:389-395`). Change that summary to the five exact RPC names; if the later MCP tool names are worth mentioning, explicitly distinguish those bare tool names from the service wire names so the Round 8 mismatch is not reintroduced from a stale nearby description.

VERDICT: NEEDS_CHANGES

## Round 10 — 2026-08-02

### Summary judgment
Round 9's error-envelope fix is correctly implemented at all three resolved-error call sites, the cancellation and exception-preservation fixes are correctly placed, and the new shutdown test genuinely synchronizes through a full request/response rather than timing. The sleep sweep found exactly the three bounded polling loops at `tests/test_service_lifecycle_integration.py:136,149,271`; none is a fixed-duration test delay and the new shutdown test contains no sleep (although `_wait_for_pid_file` deliberately returns `None`, rather than raising `TimeoutError` as the response claimed). A source-level check against the installed Python 3.12 asyncio implementation found a remaining accept-versus-registration window in `RunningServer`, and a fresh package-wide pass found that lifecycle-task failures are still silently converted into successful shutdown, so M9 is not ready. This environment has file-reading tools but no command runner, so this is a static review and I did not assume the reported test, ruff, mypy, or `check.sh` results.

### Findings
1. **[BLOCKER] `RunningServer` can still miss an already-accepted connection and hang forever in `wait_closed()` when shutdown races the callback task's first step.** `close_all_connections()` snapshots only the tasks already present in `_connections`, and `_on_connect` does not add its task until the async callback itself starts running (`zikaron/service/server.py:224-228,251-261`). On this pinned Python, however, the selector transport increments `asyncio.Server._active_count` synchronously during transport construction and only schedules `protocol.connection_made` for a later event-loop turn (`/usr/lib/python3.12/asyncio/selector_events.py:803-804,952-955`); `StreamReaderProtocol.connection_made` creates the coroutine callback task later still (`/usr/lib/python3.12/asyncio/streams.py:241-262`). Therefore shutdown can call `server.close()`, snapshot an empty set, and enter `wait_closed()` while an active accepted transport already counts against that wait but its handler has not yet reached `connections.add`; once it does, it can block in `reader.readline()` forever because the cancellation snapshot has already passed (`zikaron/service/server.py:230-236`). The new test is correctly non-racy for the *steady-state idle connection* it covers—a completed health round trip proves that handler reached registration before shutdown (`tests/test_service_server.py:70-82`)—but that necessarily makes it unable to cover this distinct accept-during-shutdown window, which is especially material because connect-during-exit is an explicit lifecycle scenario. Track accepted transports/protocols at the protocol-factory/acceptance boundary with a shutdown gate (so a protocol created during shutdown closes immediately), rather than relying only on the coroutine task's first instruction, and add a deterministic no-sleep test that pauses between server attachment and callback-task registration before invoking `shut_down()`.

2. **[BLOCKER] A lifecycle task that finishes by raising is treated as a normal stop and its exception is swallowed.** `main.run` discards the `(done, pending)` result of `asyncio.wait`, then defines an idle exit as merely `idle_task.done() and not idle_task.cancelled()` (`zikaron/service/main.py:87-92`). A task that raised satisfies both predicates, so an exception from `idle_self_stop` (for example, an unlink/shutdown failure) is classified as successful idle exit; an unexpected `serve_forever` failure likewise only selects the signal-style unlink branch. The unconditional cleanup then gathers every task with `return_exceptions=True` without ever inspecting those returned exceptions (`zikaron/service/main.py:101-108`), allowing the service to exit with status zero and, for a failed idle task, potentially skip the fallback unlink too. Preserve and inspect the completed set: explicitly retrieve/raise unexpected task exceptions before cancellation cleanup, while handling only the known cancellation of `serve_forever` caused by a successful idle shutdown as normal. Add discriminating tests in which `idle_self_stop` and `serve_forever` each raise after all tasks exist and assert that `run()` propagates the failure rather than returning normally.

3. **[IMPROVEMENT] Installed process signal handlers are never removed, including when setup fails halfway through installation.** `main.run` installs SIGTERM and SIGINT handlers in a loop (`zikaron/service/main.py:73-76`) but has no `remove_signal_handler` call on any normal, exceptional, or cancellation path. The production subprocess normally closes its event loop immediately afterward, but direct/in-process callers retain callbacks closing over this invocation's `stop` event; if installation of the second handler fails, even the first remains installed. This is the cleanup half Round 9 finding 3 explicitly requested alongside task cancellation, and the new tests do not check it (`tests/test_service_main.py:32-132`). Record each successfully installed signal incrementally and remove it in an unconditional `finally`; add a fake-loop test that fails on the second installation and verifies the first is removed, plus normal-exit coverage.

4. **[IMPROVEMENT] The corrected error tests assert the right JSON path, but they still do not directly defend two load-bearing server cases claimed by their prose/prior finding.** The application-error test says a client that “bootstraps into a failing first call” learns its label, but it sends `_client("s1")` and merely observes the supplied label (`tests/test_service_server.py:147-174`); no failing call with `session_id=None` proves that a freshly minted label survives the error path. There is also no test anywhere under `tests/` that exercises `_compute_response_line`'s unexpected-handler `INTERNAL_ERROR` branch, so that third `encode_error(..., session_id=envelope.session_id)` call site is correct by inspection (`zikaron/service/server.py:113-129`) but unguarded. The dedicated encoder tests are sound and assert top-level `client.session_id` with unchanged `error.data` (`tests/test_service_rpc.py:179-204`), yet they cannot detect a server call site dropping the keyword. Change the application-error case to a bootstrap envelope and assert a minted `zk-...` top-level label, and inject a failing handler to assert the internal-error envelope carries the resolved top-level label and no label in `error.data`.

5. **[NITPICK] `dispatch_consolidation.py` still opens with the same count/category confusion the Round 9 prose sweep was meant to remove.** Its first line says “the consolidator's four verbs plus `plan_groups`/`next_group`” (`zikaron/service/dispatch_consolidation.py:1`), although this module has three write verbs and five RPC methods total; `next_group` is the fourth D32 tool, not an additional method beside “four verbs.” The exact wire names and the deliberate bare-form contrast are otherwise clean across `zikaron/service/` and `tests/`. Replace the opening with “`plan_groups`, `next_group`, and the three consolidator write methods” (or the five exact `apply_*` wire names), matching the now-correct summary in `dispatch.py:12-18`.

VERDICT: NEEDS_CHANGES

## Round 11 — 2026-08-02

### Summary judgment
Round 10's task-exception, signal-handler, error-envelope-test, and stale-docstring fixes are correct on direct static inspection: `_raise_if_any_task_genuinely_failed` runs before `idle_task in done`, both new signal tests are synchronously ordered, the bootstrap/internal-error tests exercise the claimed call sites, and `dispatch_consolidation.py` now has the right opening description. The `_active_count` shutdown fix is not complete, however: its five-second bound does not bound its own `gather`, it assumes the counter cannot rise after `Server.close()` despite asyncio's already-accepted queued accept task, and `main.run` waits on cancelled `serve_forever` before `RunningServer` can close active connections. I also found the exact fixed-`sleep(0)`-turn test pattern requested in the new Round 10 server test. This environment has file-reading tools but no command runner, so I could not execute `check.sh`, tests, ruff, or mypy and do not assume the reported gate results.

### Findings
1. **[BLOCKER] The advertised five-second shutdown deadline does not bound a cancellation-resistant connection task and can still hang forever.** `close_all_connections` cancels the current snapshot and then awaits `asyncio.gather(...)` with no timeout; the deadline is checked only *after that await returns* (`zikaron/service/server.py:265-272`). If a handler catches/suppresses `CancelledError` and remains pending, control never reaches the deadline check, so the exact failure named by the docstring—"never responded to cancellation"—hangs rather than raises. Cancel the snapshot and wait with the remaining deadline (for example `asyncio.wait(snapshot, timeout=remaining)`), raising with the still-pending/active counts on expiry; add a test handler that catches its first cancellation and remains gated, and assert `close_all_connections` reaches a shortened test deadline instead of blocking inside `gather`.

2. **[BLOCKER] `_active_count` is not guaranteed to count only down after `Server.close()`; a socket already accepted by asyncio can attach after this loop has observed zero and returned.** The implementation's correctness argument explicitly says the counter "can only ever count down" after close, and the loop is skipped entirely when its first read is zero (`zikaron/service/server.py:235-265`). In the installed Python 3.12 implementation, however, `_accept_connection` first accepts the fd and schedules `_accept_connection2` as a task (`/usr/lib/python3.12/asyncio/selector_events.py:167-213`); only when that later task constructs the transport does `_SelectorTransport` call `server._attach()` (`/usr/lib/python3.12/asyncio/selector_events.py:213-226,804`). If shutdown runs between those steps, `Server.close()` sees zero and wakes/clears its waiters (`/usr/lib/python3.12/asyncio/base_events.py:335-381`), this method returns, and the queued accept task can subsequently increment the count and create a handler against a context already being torn down. The new test deliberately waits until `_active_count > 0` (`tests/test_service_server.py:139-145`), so it cannot cover this earlier accepted-fd-before-attachment window. Use an acceptance mechanism the service owns (for example an explicit `sock_accept` loop that can be cancelled and awaited before draining handlers), or another design with a shutdown gate plus a deterministically drainable accept pipeline; add a test that pauses the accepted connection before transport attachment, closes the listener, and proves no handler can appear after shutdown returns.

3. **[BLOCKER] Signal shutdown with an idle open client still deadlocks before `RunningServer.__aexit__` can perform the connection-closing fix.** On signal completion, `main.run` enters its task `finally`, cancels `serve_forever`, and gathers it *inside* `async with server` (`zikaron/service/main.py:133-162`). Python 3.12's `Server.serve_forever` handles cancellation by calling `close()` and awaiting `wait_closed()` before re-raising (`/usr/lib/python3.12/asyncio/base_events.py:360-379`); with an idle accepted client, that wait needs the connection handler closed. But `RunningServer.__aexit__`—the code that calls `close_all_connections`—cannot run until the inner `gather` finishes (`zikaron/service/server.py:286-288`), creating a cycle. The direct `running.shut_down()` test at `tests/test_service_server.py:42-87` cannot detect this `main.run` ordering defect, and the new successful signal test opens no client. Since `start_unix_server` is already serving, simplify `run`: avoid using `serve_forever` as a lifetime sentinel, wait on idle/signal ownership directly, and ensure `RunningServer.shut_down()` happens before awaiting any task whose cancellation itself waits for server closure. Add an in-process or subprocess signal test that leaves a completed-request connection open and bounds the full `run()`/process exit.

4. **[IMPROVEMENT] The new accepted-before-registration regression test contains the same fixed-`sleep(0)`-turn synchronization class that caused this round's coverage hang.** It waits at most 1,000 event-loop turns for attachment (`tests/test_service_server.py:139-143`) and then assumes one further `await asyncio.sleep(0)` was enough for the independently scheduled shutdown task to have exercised the intended state (`tests/test_service_server.py:150-156`). The first loop does check a real condition, so the core state after it succeeds is valid, but its bound is still scheduler turns rather than a real deadline/explicit event; the second assertion can pass vacuously merely because shutdown has not run yet. Have the gated handler set a `handler_started` event before awaiting `registration_gate`, await that event under a real timeout, and remove the one-turn progress assertion (the final bounded shutdown outcome is the discriminating assertion). The fresh requested sweep found no other fixed `asyncio.sleep(0)` loops in `zikaron/service/` or `tests/`; the three `time.sleep(0.02)` sites in `test_service_lifecycle_integration.py:131-150,263-272` poll observable filesystem/process conditions against monotonic deadlines, and the new `test_service_main.py` signal tests have no independently scheduled polling race.

5. **[IMPROVEMENT] The nested shutdown cleanup can replace the lifecycle failure the Round 10 helper was introduced to preserve.** A genuine idle/serve task exception is re-raised inside `async with server`, whose `__aexit__` immediately calls the now-fallible `shut_down`; if that cleanup raises, it replaces the task exception. The surrounding `except BaseException` then calls `server.shut_down()` again without preserving the already-active exception, so a second shutdown failure can replace it again (`zikaron/service/main.py:136-184`; `zikaron/service/server.py:280-288`). This is the same primary-versus-cleanup composition issue already handled for `ctx.close`, now made reachable by the new explicit shutdown timeout. Centralize server cleanup in one owner, and when cleanup fails during an active exception, log/chain it while preserving the original (propagating shutdown failure only on an otherwise normal exit); test a raised lifecycle task combined with a forced shutdown failure. This is also why structural simplification of `run` is now warranted rather than adding another nested cleanup layer.

6. **[NITPICK] One new test reaches through asyncio's private module path even though the class has a public export.** `tests/test_service_main.py:270` monkeypatches `asyncio.base_events.Server.serve_forever`; Python declares `Server` in `base_events.__all__` and exports it as `asyncio.Server`, so target the public alias instead. The fresh package-wide search found no other production access to a stdlib object's private attributes: `RunningServer`'s documented `_active_count` read is the only one in `zikaron/service/`; the matching `_active_count` read in `test_service_server.py:140` is test support for it.

VERDICT: NEEDS_CHANGES

## Round 12 — 2026-08-02

### Summary judgment
The `serve_forever` removal itself is correct: there is no executable call left in `zikaron/service/` or `tests/`, installed Python 3.12 starts accepting before `asyncio.start_unix_server` returns, the completed health round trip makes the new real-signal test genuinely ordered, and no caller still uses `RunningServer` as an async context manager. The gather regression test also really registers its task and suppresses one cancellation around `asyncio.sleep`, and no private `asyncio.base_events.Server` path remains. M9 is nevertheless not ready: `wait_for(gather(...))` is not a hard deadline for a task that keeps suppressing cancellation, the pre-attachment accept race remains unchanged by removing `serve_forever`, and `main.run` still retries fallible shutdown in a way that can replace the primary failure. This is a static review using file-reading tools only; no command runner is available, so I did not run or assume the reported test, lint, type-check, or gate results.

### Findings
1. **[BLOCKER] `close_all_connections` still has no hard bound when a handler repeatedly suppresses cancellation; the new test passes only because its handler suppresses exactly one cancellation.** The production wait is `await asyncio.wait_for(asyncio.gather(...), timeout=remaining)` (`zikaron/service/server.py:276-289`). On timeout, `wait_for` cancels the gather, and gather in turn cancels its children and waits for them; Python explicitly documents that `wait_for` can exceed its timeout while cancellation completes (`/usr/lib/python3.12/asyncio/tasks.py:472-510`). The test manually registers the handler correctly and uses `asyncio.sleep(10)` as the resistant point, but its `swallowed_once` branch lets the *second* cancellation propagate (`tests/test_service_server.py:187-216`): the first comes from `connection.cancel()`, and the timeout's cancellation of the gather supplies the second, making the task finish and allowing `wait_for` to return. A handler that catches every `CancelledError` still leaves this code stuck inside `wait_for`, never reaching the custom `TimeoutError`; this is the exact “never responded to cancellation” case the method claims to bound. Use `asyncio.wait(snapshot, timeout=remaining)` (which returns a pending set without waiting for cancellation completion), raise from that pending set, and make the regression handler suppress every cancellation behind a separately releasable cleanup gate so the test distinguishes a real deadline from a second-cancellation escape hatch.

2. **[BLOCKER] Removing `serve_forever` does not resolve Round 11's accepted-fd-before-transport-attachment race, and the current regression still starts after that window.** `shut_down()` closes the listener and immediately lets `close_all_connections` skip its loop when `_active_count == 0` (`zikaron/service/server.py:262-263,299-306`). But the event loop accepts an fd and schedules `_accept_connection2` as a separate task before transport construction calls `Server._attach()` (`/usr/lib/python3.12/asyncio/selector_events.py:166-215,803-804`); therefore that queued task can still run after `Server.close()`. On the normal interpreter its later `_attach()` hits the stdlib assertion that `_sockets is not None` (`/usr/lib/python3.12/asyncio/base_events.py:295-297`) and the accept task silently catches the transport-creation failure; under `python -O`, the stripped assertion permits `_active_count` to rise after `close_all_connections` and `wait_closed` already returned. Either way, `RunningServer.shut_down()` has returned before the already-accepted fd's pipeline is drained, which can outlive context teardown. `test_shut_down_survives_a_connection_accepted_but_not_yet_self_registered` explicitly waits until `_active_count > 0` and gates only the later handler registration (`tests/test_service_server.py:139-173`), so it cannot cover this earlier zero-count window. Own and cancel/await the accept pipeline (for example with an explicit `sock_accept` loop whose accepted connection is registered before its next await), and add a deterministic test paused after `accept()` but before transport attachment.

3. **[IMPROVEMENT] `main.run` still has two server-cleanup owners, and the exception-path retry can replace the failure already in flight.** A signal exit calls `server.shut_down()` directly (`zikaron/service/main.py:153-159`); an idle exit calls it inside `idle_self_stop`; then every exception from either the lifecycle task or that first shutdown reaches the outer `except BaseException`, which calls the same fallible `server.shut_down()` again before the bare raise (`zikaron/service/main.py:175-191`). Ordinary completed shutdown is idempotent, so a second call after success is harmless, but that is not the problematic case: if the first call timed out or another lifecycle error is active and the retry also fails, the retry's exception replaces the primary error and traceback. A simultaneous idle decision and signal can also run two shutdown coroutines concurrently before task cancellation, for which idempotence of *completed* `Server.close()` is not a serialization guarantee. Centralize shutdown under one owner (ideally have idle detection report the reason/unlink first and let `run` perform the sole drain), or at minimum preserve an active primary exception exactly as the existing `ctx.close()` layer does and guard concurrent/in-progress shutdown. Add the combined lifecycle-failure plus shutdown-failure regression Round 11 requested.

4. **[IMPROVEMENT] `handler_started` removes the handler-start vacuity but not the shutdown-task scheduling vacuity.** The handler can set `handler_started` during the `_active_count` polling yields, before `shut_down_task` is created (`tests/test_service_server.py:114-151`). In that valid ordering, `await handler_started.wait()` at `tests/test_service_server.py:166` returns immediately without yielding, so the following `assert not shut_down_task.done()` can still pass merely because the just-created shutdown task has never run—the exact vacuity the fix claims to remove. Add a separate `shutdown_started` event set from an instrumented `close_all_connections`/`shut_down` entry, await that event under the timeout, and only then assert that shutdown remains pending on `registration_gate`. The handler event remains useful to prove the accepted callback itself reached the intended gate, but it cannot synchronize a different task created afterward.

VERDICT: NEEDS_CHANGES

## Round 13 — 2026-08-02

### Summary judgment
Round 12's three non-policy fixes are correct on direct inspection: `asyncio.wait` gives `close_all_connections` control at its deadline and the gated regression genuinely discriminates; the secondary `shut_down()` failure no longer replaces the active primary exception; and `shutdown_started` synchronizes the shutdown task itself without a new vacuity. The fatal log record is also synchronously flushed by the configured `logging.FileHandler` before `logger.exception` returns (`zikaron/service/log.py:19-34`), so `os._exit` skipping atexit does not by itself lose that record. The hard-exit fallback is nevertheless not reliably reachable from the failures it is intended to terminate, because its catch is outside `asyncio.run()` and after another graceful-shutdown attempt. This environment has file-reading/editing tools but no command runner, so this is a static review and I did not run tests, lint, type checks, or the full gate.

### Findings
1. **[BLOCKER] The hard exit runs too late: `asyncio.run()` can hang in its own teardown before `main()` ever catches the shutdown `TimeoutError`.** The code catches only after `asyncio.run(run(...))` raises to its caller (`zikaron/service/main.py:255-260`), but `asyncio.run()` cancels and waits for all remaining tasks before it re-raises. The exact task that makes `close_all_connections` expire can still be alive and suppressing cancellation (`zikaron/service/server.py:283-305`); the runner can therefore wait forever for that task, never reaching `_force_exit_after_shutdown_timeout()`. Before even reaching runner teardown, `run()` also catches the first deadline failure, calls the same `server.shut_down()` again with a fresh five-second deadline, and then enters `ctx.close()` (`zikaron/service/main.py:174-217`), contradicting the entry-point docstring's claim that a failed graceful shutdown is tried only once. Finally, `shut_down()` awaits an unbounded `server.wait_closed()` after the bounded method returns (`zikaron/service/server.py:310-318`), so a shutdown stall there produces no `TimeoutError` for this catch at all. Implement the directed decision at a layer that fires before coroutine/runner teardown—for example, arm an independently scheduled hard deadline when shutdown starts, cancel it only after shutdown and loop teardown succeed, and have its expiry log/flush then call the indirection; at minimum, catch the dedicated shutdown deadline inside the coroutine run by `asyncio.run()` and bypass the retry and store cleanup on that terminal path. This does not require reopening the settled accept-loop decision. Add a discriminating test that leaves a separately releasable cancellation-resistant task pending and proves the force-exit spy is invoked before runner teardown; the current immediate-raise stub cannot expose this ordering defect (`tests/test_service_main.py:519-535`).

2. **[IMPROVEMENT] Built-in `TimeoutError` is the exact type emitted by both explicit deadline branches, but it is too broad as the process-termination discriminator.** Both deadline exits in `close_all_connections` explicitly raise built-in `TimeoutError` (`zikaron/service/server.py:289-306`), so the current catch is sufficient for those two branches once they reach it. However, `main()` catches any `TimeoutError` escaping any part of `run()` (`zikaron/service/main.py:255-260`), including a future or dependency timeout during startup, lifecycle work, or otherwise-normal store cleanup; those do not prove this shutdown deadline expired. Introduce a semantic `ShutdownTimeoutError(TimeoutError)`, raise it only from the two deadline branches, and catch only that type at the hard-exit boundary. Other shutdown exceptions can continue through the established primary/secondary preservation path unless the operator separately elects to broaden the hard-exit policy; elapsed shutdown with no exception should be handled by the independent deadline in finding 1 rather than by guessing exception classes.

3. **[IMPROVEMENT] The test indirection is safe under current code and ordinary pytest ordering/xdist, but the test has no defense against the future direct-call edit the indirection is meant to make hard.** The monkeypatch of `_force_exit_after_shutdown_timeout` is installed before the only call to `main.main()` and remains active until that synchronous call returns (`tests/test_service_main.py:519-535`); test reordering does not alter fixture scope, and process-based parallel workers do not share this module object, so the present test cannot reach the real `os._exit`. But if a future edit moves `os._exit(1)` directly into the `except`/deadline callback, the patch at `tests/test_service_main.py:531` is bypassed and this test can kill its worker. In addition to patching the wrapper spy, monkeypatch `main.os._exit` to a fail-fast sentinel in this test so accidental bypass fails normally instead of terminating pytest; retain the production rule that only `_force_exit_after_shutdown_timeout` may call it (`zikaron/service/main.py:263-273`).

4. **[IMPROVEMENT] The shutdown docstrings still assert the airtight property the operator explicitly chose not to pursue.** `close_all_connections` says that after `Server.close()`, `_active_count` “can only ever count down,” and that observing zero guarantees the following `wait_closed()` returns immediately (`zikaron/service/server.py:235-263`). Those statements are inconsistent with the now-settled pre-attachment accept-pipeline exception and with the deliberate best-effort-plus-hard-fallback policy; retaining them makes the implementation appear to prove exactly what the normative decision says it does not prove. Replace the monotonicity/guarantee language with the narrower truth: the polling loop drains attached transports and registered handlers under its deadline, while the independently enforced process fallback covers failure to complete shutdown. Also remove “failed once”/“first and only once” from `main()` unless the retry identified in finding 1 is skipped on the terminal timeout path (`zikaron/service/main.py:233-252`).

VERDICT: NEEDS_CHANGES

## Round 14 — 2026-08-02

### Summary judgment
Round 13's central restructuring is present: `main()` is a bare `asyncio.run`, the normal signal path and an idle timeout already present in `asyncio.wait`'s `done` set reach the in-coroutine `ShutdownTimeoutError` catch, and the final `wait_closed()` is bounded and translated to the dedicated type. The hard-exit test has both layers of protection and cannot call the real `os._exit` under current code. Skipping `ctx.close()` immediately before `os._exit` is also safe for the next opener: the kernel releases SQLite fds/locks, WAL is the configured journal (`zikaron/core/store/ddl.py:18-22`), committed WAL frames remain recoverable, and any incomplete transaction is ignored/rolled back rather than made durable; leftover `-wal`/`-shm` files or recovery work are not database damage. Approval is still blocked because two real routes can absorb the dedicated timeout instead of invoking the directed terminal path; this was a static review because no command runner is available.

### Findings
1. **[BLOCKER] `run()` still swallows `ShutdownTimeoutError` on two shutdown-deadline paths, so the new catch is not universal.** The ordinary cases are sound: a signal-path `await server.shut_down()` raises through `zikaron/service/main.py:171` to the dedicated catch at `:187-188`, and an idle-path timeout that caused the initial wait to return is re-raised by `_raise_if_any_task_genuinely_failed` at `:160-163` before reaching the same catch. But if an earlier non-timeout failure enters `except BaseException`, the cleanup `shut_down()` at `:215` can expire either `close_all_connections`'s deadline or the new `wait_closed()` bound, and the broad nested handler at `:216-219` logs and suppresses that `ShutdownTimeoutError`; execution then retries ordinary propagation and `ctx.close()` rather than forcing exit. Separately, if signal completion won the initial `done` snapshot while `idle_self_stop` was concurrently inside `shut_down()`, a timeout that the idle task produces before/during cancellation is collected and discarded by `gather(..., return_exceptions=True)` at `:172-186`, never rechecked by `_raise_if_any_task_genuinely_failed`. Put a dedicated `except ShutdownTimeoutError` ahead of the nested cleanup handler and route it directly to `_force_exit_after_failed_graceful_shutdown`; also inspect the cancellation-gather results and route any contained `ShutdownTimeoutError` to that terminal path. Add discriminating tests for (a) idle timeout as the first completion, (b) a shutdown timeout while cleaning up an unrelated lifecycle failure, and (c) an idle task that yields `ShutdownTimeoutError` after signal won the original wait.

2. **[IMPROVEMENT] The newly bounded `wait_closed()` uses the same constant but not the same five-second deadline.** `close_all_connections` creates an absolute deadline at `zikaron/service/server.py:312`, can consume nearly all five seconds, and then `shut_down` starts a fresh full five-second `wait_for` at `:355-358`; the directed “5 s deadline” can therefore take nearly ten seconds before the force-exit path runs. Establish one absolute deadline in `shut_down`, pass it into `close_all_connections` (or return its remaining budget), and give `wait_closed()` only the remaining time; immediately raise `ShutdownTimeoutError` if none remains. This preserves the settled policy while making the implementation match its single deadline rather than merely reusing its duration constant.

3. **[IMPROVEMENT] Round 13's prose correction is incomplete and now also contradicts the third timeout branch.** `ShutdownTimeoutError` still says it is raised only from `close_all_connections`'s two branches (`zikaron/service/server.py:45-54`), although `shut_down` now raises it from bounded `wait_closed()` too (`:355-364`). In addition, `main.run` still says shutdown closes “every open connection” (`zikaron/service/main.py:115-119`) and `shut_down` opens with “close every one already accepted” (`zikaron/service/server.py:337-340`), both absolute claims contradicted by the explicitly settled pre-attachment accept-pipeline exception described later in the same docstring. Say that the dedicated type comes from all three graceful-shutdown deadline exits, and narrow the summaries to attached/observable connections plus the bounded fallback; the detailed “normally, not provably” passage at `server.py:244-264` is otherwise accurate and does not understate the guarantee on successful observable draining.

VERDICT: NEEDS_CHANGES