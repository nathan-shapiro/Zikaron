# Review — `main.run()` installs the signal handlers before the bind

Artifact: `zikaron/service/main.py` (`run()` restructure), `tests/test_service_main.py`,
`tests/test_service_lifecycle_integration.py` (renamed end-to-end test), `FINDINGS.md` priority
item 6. Targeted change, not a milestone.

## Round 1 — 2026-09-16

### Summary judgment
The fix is the right one and the new structure is sound: with `_stop_on_sigterm_or_sigint` wrapping
`ensure_runtime_dir` and `serve()`, every moment at which the socket file exists is a moment at which
`SIGTERM`/`SIGINT` set `stop` rather than killing the process, and I walked the newly reachable
pre-bind-signal path through every cleanup branch without finding a double unlink, a leaked listener,
or a skipped `ctx.close()`. No behaviour defect. What remains is this corpus's named dominant class:
two test docstrings still describe the *old* nesting (one states the handler-removal order inverted),
the load-bearing comment states an unscoped universal ("makes a stale socket file impossible") that
`SIGKILL` and the project's own stale-socket test refute, the tail of FINDINGS item 6 was not
re-read with its edited head, and the one path this change newly makes reachable has no in-process
test asserting its post-condition. One round should close it.

### Assumptions and re-verification notes
- **I had no shell, so I could not run `git show HEAD:zikaron/service/main.py`.** I reconstructed the
  pre-change nesting from the brief and from the two test docstrings that still describe it
  (findings 1 and 2): `serve()` was assigned inside the outer `try`, the `async with` sat inside the
  inner `try` beneath `chmod`, and the two `except` clauses hung off that inner `try`. On that
  reconstruction the re-indent preserves semantics: `ensure_runtime_dir` and `serve()` failures still
  reach the outer `finally` (`ctx.close()`), post-bind setup failures still reach `except
  BaseException:` with `server` bound, and the only ordering that changed is that handler *removal*
  now runs after the `except` clauses rather than before them. The one path that could observe that
  — `remove_signal_handler` raising after a clean exit — has no realistic trigger (invalid signal
  number or a closing loop, neither reachable here), and the listener and socket are already gone by
  then on every branch. I did not attempt a byte-for-byte diff; the author's "47-line mechanical
  re-indent" is taken on the gate and the tests, not verified here.
- **The pre-bind-signal path (brief question 2), walked:** handler callback runs on the loop and sets
  `stop` → `ensure_runtime_dir` → `serve()` binds → `chmod` → `idle_self_stop` created (first await is
  a 30 s sleep, cannot complete) → on the open path `stop_on_encoder_failure` created (first await is
  `to_thread`, cannot complete in the same iteration; on success it waits forever, on failure it is a
  self-stopping task that unlinks and shuts down itself, which `done & set(self_stopping)` then
  correctly credits) → `signal_wait` created over an already-set `Event`, completes on its first step
  → `asyncio.wait` returns `done={signal_wait}` → `_raise_if_any_task_genuinely_failed` is a no-op →
  `not done & set(self_stopping)` is true → `sock_path.unlink` (once) → `server.shut_down()` with an
  empty or cancellable connection set → inner `finally` cancels and gathers → normal exit of the
  `try` → `async with` exit removes both handlers → outer `finally` closes the store. A client that
  connected in the microseconds between bind and unlink is cancelled by `shut_down()` and lands in the
  "connect exactly as the server exits" retry the design already requires of clients. Exactly one
  unlink; no path skips `ctx.close()`.
- **`_stop_on_sigterm_or_sigint`'s docstring (question 3) is still true.** It makes no claim about
  where the context manager sits relative to the bind; its subject is the removal half, and every
  sentence of it holds under the new placement.
- **`design/` (question 4):** no design sentence depended on the old ordering. `architecture.md:714-716`
  ("On exit the socket is unlinked before the process ends") and `write-policy.md:192` ("`SIGTERM` it;
  it unlinks its socket on exit") are both made *more* true by the change; `architecture.md:592`'s
  stale-socket signature still describes `SIGKILL`. Nothing there needs correcting (finding 9 is an
  optional anchor, not a correction).
- **Corpus sweep for the old ordering and the old test name**, in every phrasing I could think of
  (`installed after`, `after the socket is bound`, `after binding`, `handlers … before/after …
  bind/bound/serve`, `known intermittent`, `idle-self-stop intermittent`, the old test name):
  the live hits are `FINDINGS.md:1733-1755` (the edit), `FINDINGS.md:478-479` (M20's false-red
  paragraph, still accurate — it says the file "records" the intermittent, which it does),
  `FINDINGS-archive.md:1644-1654` (finding 6), and the two `test_service_main.py` docstrings
  (findings 1 and 2). Review-trail hits are history and correctly untouched.
- **The renamed integration test's factual claims check out:** `schema.md:593` gives `idle_timeout`
  the range 60–86400, so its old name did claim an exit it could never take inside a 5 s wait, and
  its body has always used `process.terminate()`.
- **The new guard measures the right thing.** `loop.add_signal_handler` installs `_sighandler_noop`
  synchronously via `signal.signal`, so reading `signal.getsignal(SIGTERM)` at the moment `serve()`
  is entered answers the ordering question directly, and the author reports it red under the old
  ordering. See finding 7 for the one fragile assertion in it.

### Findings

1. **[IMPROVEMENT] A test docstring states the handler-removal order the change inverted.**
   `tests/test_service_main.py:346-350`
   (`test_a_shut_down_failure_while_handling_idle_self_stop_failure_preserves_the_original`): *"lands
   in `run()`'s outer `except BaseException:` (via the innermost `finally`'s task cancellation, then
   `_stop_on_sigterm_or_sigint`'s own signal-handler cleanup, both of which run and re-propagate
   unchanged)"*. Under the new nesting the `except BaseException:` at `main.py:309` is *inside* the
   `async with` at `main.py:232`, so the handler removal runs **after** that clause completes, not
   before the failure reaches it; "outer" is also no longer the right word for a clause that now
   sits one level inside the context manager. This is the brief's own question 4, and the corpus's
   named prose-contradicts-code class. Suggested text: *"lands in `run()`'s post-bind `except
   BaseException:` via the innermost `finally`'s task cancellation, which runs and re-propagates
   unchanged (`_stop_on_sigterm_or_sigint`'s own handler removal now runs *after* that clause, on the
   way out of the `async with` that wraps the bind) — and that `except` clause's own
   `server.shut_down()` retry used to have no `try` of its own…"*.

2. **[IMPROVEMENT] A stale cross-reference to the retargeted test, and a "setup failure" that is now
   pre-bind.** `tests/test_service_main.py:215-216`
   (`test_a_context_close_failure_does_not_mask_an_earlier_setup_failure`): *"Forces both a setup
   failure (the same `loop.add_signal_handler` failure the first test in this file uses)"*. The first
   test now fails `_self_stopping_tasks` (its own docstring at L57-61 says why it moved); no other
   test in the file fails `add_signal_handler` on the first call. Worse, the module docstring (L2-4)
   now defines "setup steps" as the post-bind ones (`chmod` and task creation), and this test's
   forced failure is the one pre-bind failure left — which is a *feature* of the test worth stating:
   it is the earliest failure `run()`'s outer `finally` has to preserve, reached with no socket bound
   and no `except BaseException:` in between. Suggested: *"Forces both a `loop.add_signal_handler`
   failure — which, now that the handlers go on before the bind, is the earliest failure `run()`'s
   outer `finally` must preserve, reached with no socket bound and no `except BaseException:` clause
   in the way — and a `Store.close` failure…"*.

3. **[IMPROVEMENT] The load-bearing comment states an unscoped universal, at two sites.**
   `zikaron/service/main.py:222-223`: *"that ordering is the whole of what makes a stale socket file
   impossible"*, and L227: *"the file's existence implies a process that will clean it up"*;
   `FINDINGS.md:1740`: *"so the socket file's existence implies a process that will clean it up"*.
   `SIGKILL`, an OOM kill and a power loss all leave the file — `architecture.md:592` names exactly
   that signature and `test_start_if_absent_clears_a_stale_socket_left_by_a_killed_server` exists for
   it. What the ordering makes impossible is a stale socket **from any signal this process can
   handle**. This is the M22-round-4 class (a universal stated without the scope its own neighbours
   supply), in the comment that justifies the change. Suggested, both sites: *"…the whole of what
   makes a stale socket file impossible for any signal this process can handle — `SIGKILL` still
   leaves one, which is what start-if-absent's vet-and-unlink is for"* and *"the file's existence
   implies a process that will clean it up on `SIGTERM`/`SIGINT`"*.

4. **[IMPROVEMENT] FINDINGS item 6's tail was not re-read with its edited head.**
   `FINDINGS.md:1756-1768`, the paragraph immediately under the withdrawal: (a) *"Do not raise
   `fail_under` close to the observed value without pinning the race first"* — the head of the same
   item now says the race **is** pinned, so the sentence reads as a condition just satisfied, while
   the paragraph's own argument (the flap is not localised to this race; no per-file cross-run diff
   was taken) means the caution stands regardless. Restate: *"The race above is now pinned; that does
   not license raising `fail_under`, because nothing attributes the flap to it."* (b) *"`fail_under`
   is 90% against an actual ~97%"* — `pyproject.toml:203` reads `fail_under = 95` and the M22 block
   of this same file records the move. Pre-existing drift, but it sits three lines under the edit,
   and the correction sharpens the point rather than weakening it: against the recorded 96.85% low
   the margin is ~1.85 points, not ~7. Suggested: *"`fail_under` is now 95% (M22) against a measured
   96.85–98.07% spread, so the margin that absorbs the flap is under two points."*

5. **[IMPROVEMENT] The path this change newly makes reachable has no in-process test asserting its
   post-condition.** `tests/test_service_main.py:456-532`
   (`test_signal_handlers_are_removed_after_a_fully_successful_signal_driven_exit`) fires `SIGTERM`'s
   callback synchronously inside `add_signal_handler` — which is now *before* `serve()` — so it is
   exactly the "stop already set → bind → chmod → tasks → unlink → `shut_down()` → clean return"
   sequence of brief question 2, and it asserts only handler removal. Every other in-process
   `assert not sock_path.exists()` reaches the unlink through `except BaseException:` (`main.py:354`)
   or the force-exit path (`main.py:486`), so the ordinary signal-path unlink at `main.py:255` is
   guarded only by the integration test whose signal arrives *after* the bind — the one that used to
   be flaky. Add `assert not sock_path.exists()` after `await main.run(sock_path, store_dir)` at
   L530, and mutation-verify by deleting `main.py:255` (`asyncio.Server.close()` does not unlink a
   Unix socket path, so only this assertion should go red in the default tier). Worth one sentence
   in that test's docstring saying it is now the pre-bind-signal path.

6. **[NITPICK] The archive's copy of the diagnosis has no forward pointer.**
   `FINDINGS-archive.md:1644-1654` still reads *"left unfixed deliberately"* and *"the fix wants its
   own change"*. `CLAUDE.md` sends every fresh session to the archive's dogfooding notes before
   proposing anything, so this is the second site of a two-site claim. Add one line at the end of the
   bullet: *"**Fixed 2026-09-16**: the handlers now go on before the bind — FINDINGS priority item
   6."* History stays; the pointer stops a re-derivation.

7. **[NITPICK] The new test asserts a restoration asyncio does not perform.**
   `tests/test_service_main.py:149-151`: `assert signal.getsignal(signal.SIGTERM) is before`.
   `loop.remove_signal_handler` does not restore the previous disposition; it installs `SIG_DFL`
   (`default_int_handler` for `SIGINT`). The assertion holds today only because `before` is `SIG_DFL`
   under this runner, and would fail with the code correct under any runner that sets its own
   `SIGTERM` handler. Assert what removal actually does — `is signal.SIG_DFL` — or `is not
   at_bind_time[0]`, and say which in the message.

8. **[NITPICK] A vestigial config line in the renamed integration test.**
   `tests/test_service_lifecycle_integration.py:802` writes `idle_timeout = 60`. The docstring now
   says the test never takes the idle path, but not why the shortest legal idle timeout is still
   configured. Either drop the line (the 1800 s default is further from the 5 s window) or add a
   clause: *"the shortest legal `idle_timeout` is written so the idle path is as near as it can
   legally be and still cannot fire inside this test's 5 s bound."*

9. **[NITPICK] The design nowhere states the ordering two of its sentences now rest on.**
   `architecture.md:714-716` ("On exit the socket is unlinked before the process ends") and
   `write-policy.md:192` ("`SIGTERM` it; it unlinks its socket on exit") are true because of an
   ordering only a code comment and a test record. One sentence after `architecture.md:716` would
   give `test_the_signal_handlers_are_installed_before_the_socket_is_bound` a normative anchor and
   connect the stale-socket signature at L592 to its cause: *"The `SIGTERM`/`SIGINT` handlers are
   installed before the socket is bound, so a signal at any moment the file exists is handled; only a
   `SIGKILL` leaves a stale socket, which is the case step 4 of §"Start-if-absent" clears."*
   Optional; the brief's own question was whether the design *contradicts* the change, and it does not.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-16

### Summary judgment
All nine round-1 findings are addressed as the brief describes, and I re-derived each against the
current files rather than taking the brief's account: the docstrings at `test_service_main.py:49-61`,
`:215-224` and `:352-360` now describe the nesting the code has, the comment at `main.py:222-230` and
FINDINGS item 6 are scoped, the `is signal.SIG_DFL` assertion is the right one, the socket assertion
at `:552` pins the unlink it names, and the archive carries its forward pointer. The whitespace-
insensitive diff closes the one item round 1 could not verify. What this round found is the class the
brief asked about, twice: a universal installed by round-1 fix 5 that three sibling tests in the same
file refute, and a universal installed by round-1 fix 9 — my own suggested sentence — that names two
causes of a stale socket where the signature it cites at `architecture.md:592` deliberately names none.
Neither touches behaviour. One short round closes it.

### Re-verification notes
- **The brief's mutation claim for fix 5 is consistent only with a run scoped to
  `test_service_main.py`.** `test_service_lifecycle_integration.py:49` marks the module
  `pytest.mark.integration`, which `check.sh` does not exclude (only `integration_kiro` and
  `integration_claude` are), so over the default tier a no-op at `main.py:257` must also fail
  `test_a_signal_arriving_as_soon_as_the_socket_appears_still_unlinks_it` at `:816` — nothing else in
  that process unlinks within its 5 s window (on the pinned 3.12 `Server.close()` does not, and neither
  self-stopping task fires that early). "That test was the only failure" is therefore either a
  file-scoped run, which is fine, or evidence that the integration test did not catch the mutation,
  which would be a finding about *it*. Please say which; I have assumed the former.
- **All three sibling tests that fire `SIGTERM` synchronously inside `add_signal_handler`
  (`test_service_main.py:687-706`, `:856-875`, `:919-938`) now take the pre-bind-signal path**, since
  that call precedes `serve()`. Walked each: `stop` set → bind → `chmod` → tasks → `asyncio.wait`
  returns with `signal_wait` done → `main.py:257` unlink → `shut_down()` → then the forced failure
  each test plants (a timing-out `shut_down()`; a `ShutdownTimeoutError` or a `PermissionError` raised
  during cancellation). So the unlink at `:257` runs in four tests, and is *asserted* in a way
  attributable to it in exactly one — the basis of finding 1.
- **The new `architecture.md:718-723` paragraph, checked clause by clause.** "`serve()` publishes the
  socket the instant it binds" — `server.py:405` is a single `start_unix_server` call with nothing
  after it but the return. "A signal at any moment the file exists is handled" — true for
  `SIGTERM`/`SIGINT`: on every exit path the unlink precedes the `async with` exit that removes the
  handlers (signal path `:257`; both self-stopping tasks unlink before closing; `:356` before the
  re-raise; `:488` before `os._exit`). "Step 4 clears" — `:585` is the vet-and-unlink step. The
  remaining clause is finding 2.
- **Corpus sweep for the old ordering (brief question 3)**, repo-wide excluding `reviews/`, in the
  phrasings `add_signal_handler`, `signal handler(s)`, `handlers are/were/go/went installed/on`,
  `binds the socket`, `installed after`, `after the socket is bound`, and the old test name: live
  hits are the sites already fixed. `lifecycle.py:64` names "`main.py`'s signal handler" without
  asserting an ordering; `spikes/spike3_server.py:217` is a throwaway probe; the two hook-test hits
  describe fake servers that bind after a delay. Nothing still describes the old ordering.
- **Neighbouring docstrings not edited by round 1, read for consistency:** the module docstring
  (`:1-14`), `:161-168`, `:399-407`. The last says "per `run()`'s own `(signal.SIGTERM,
  signal.SIGINT)` order" where the tuple now lives in `_stop_on_sigterm_or_sigint`; that predates
  this change (the extraction did) and is out of scope — noted, not raised.
- **FINDINGS item 6 tail arithmetic:** 96.85 − 95 = 1.85, so "under two points" holds. The low end
  is M16's tree and the high end today's, ~1,000 tests apart; the M22 block already treats M16's
  three runs as "the spread", so the conservative reading is the corpus's own. Not raised.

### Findings

1. **[IMPROVEMENT] A universal installed by round-1 fix 5, refuted three times in the same file.**
   `tests/test_service_main.py:472`: *"**It is also the only in-process test of the pre-bind-signal
   path**"*. `test_a_shutdown_timeout_forces_process_exit_from_inside_the_running_coroutine`
   (`:687-706`), `test_a_shutdown_timeout_surfacing_only_during_task_cancellation_still_forces_exit`
   (`:856-875`) and `test_a_non_shutdown_timeout_failure_surfacing_during_cancellation_still_propagates`
   (`:919-938`) all fire `SIGTERM`'s callback synchronously inside `add_signal_handler` — `:684-686`
   even says *"the same technique the signal-handler-removal tests use"* — and since that call now
   precedes `serve()`, every one of them is a pre-bind-signal run. What is genuinely unique here is
   that this is the only one that lets the path run to a **clean** exit with no forced failure
   downstream of the unlink, which is why its socket assertion is attributable to `main.py:257`
   alone: `:716`'s identical assertion is also satisfied by the force-exit unlink at `:488`, and the
   other two assert nothing about the file. Round 1 finding 5 said "assertion"; the docstring
   generalised it to "test". Suggested: *"**It is also the only in-process test that lets the
   pre-bind-signal path run to a clean exit** — three others in this file fire `SIGTERM` the same way
   but force a failure downstream of the unlink, so only here does the socket assertion below pin
   `run()`'s own signal-path unlink rather than a later cleanup's."* Keep the rest of the paragraph.

2. **[IMPROVEMENT] The new design paragraph states a false universal about what leaves a stale
   socket — and the sentence is round 1 finding 9's, installed without re-scoping.**
   `design/architecture.md:722`: *"Only a `SIGKILL` or a power loss leaves a stale socket"*. Any
   terminating default disposition this process does not handle leaves the file: `SIGSEGV`/`SIGABRT`
   out of native code — this process loads onnxruntime through fastembed and the sqlite-vec C
   extension, so a native crash is a realistic death for it, not a hypothetical — an OOM kill,
   `SIGHUP` or `SIGQUIT` sent explicitly. The signature the paragraph connects to at `:592` is
   deliberately cause-agnostic (*"a service that died without cleaning up"*), and the two other
   sites state a *list* rather than an *only*: `main.py:229-230` ("`SIGKILL`, an OOM kill and a
   power loss still leave the file") and `FINDINGS.md:1741` ("`SIGKILL` and a power loss still leave
   one"). So the normative document is now the narrowest of the three statements, in the one place a
   reader would take it as the rule. The wording is mine from round 1 — the knowledge-index trail's
   "the reviewer identified its own prior recommendation as where the ambiguity entered", met again.
   Suggested: *"Only a death this process cannot handle — `SIGKILL` (an OOM kill included), a crash
   in native code, a power loss — leaves a stale socket, which is the case §"Start-if-absent" step 4
   clears, and why the signature above names no cause."*

3. **[NITPICK] A comment true on the pinned interpreter and false from the next one, guarding an
   assertion that goes vacuous with it.** `tests/test_service_main.py:549-551`: *"`asyncio.Server.
   close()` does not remove a Unix socket's path"*. True on the pinned Python 3.12.3. From 3.13,
   `loop.create_unix_server` gained `cleanup_socket=True` by default and `close()` unlinks the path
   itself (gh-111246, in that release's What's New), so on that interpreter this test's socket
   assertion holds with `main.py:257` deleted — the guard added by round-1 fix 5 would pass over a
   state the interpreter now produces for it. Round 1 finding 5 stated the same claim unscoped;
   owning that. Scope it the way `main.py:322-323` and `lifecycle.py:74-75` already scope their
   neighbouring interpreter facts: *"…does not remove a Unix socket's path on the pinned 3.12.3 —
   from 3.13 it does, by default, at which point this assertion stops distinguishing `run()`'s
   unlink from asyncio's."*

4. **[NITPICK] An inserted test shifted a "previous test" referent.**
   `tests/test_service_main.py:167`: *"the previous test (a failure *before* either task exists)
   cannot reach"* — written when `test_a_setup_failure_after_binding…` was immediately previous;
   `test_the_signal_handlers_are_installed_before_the_socket_is_bound` now sits between them at
   `:95`. Both candidates satisfy the parenthetical (one fails task creation, the other fails inside
   `serve()`), so the sentence stays true but no longer names one thing. Replace "the previous test"
   with the test's name.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-16

### Summary judgment
Round 2's four fixes landed as the brief describes and introduced no new contradiction: the two edits
inside `test_signal_handlers_are_removed_after_a_fully_successful_signal_driven_exit` agree with each
other and with `main.py:238-260`; the stale-socket cause list is the same four items at
`main.py:229-232`, `architecture.md:722-723` and `FINDINGS.md:1741-1742`; and the archive's forward
pointer (`FINDINGS-archive.md:1655-1657`) — the fourth site the brief asked about — is scoped and
consistent with them. The mutation question is answered the way round 2 derived it. What remains is
four wording nitpicks, one of them in a sentence I wrote in round 2; none touches behaviour and none
would lead a reader to a wrong action. Ship it.

### Re-verification notes
- **Mutation claim (round 2, first note): accepted.** Both failures are the two round 2 derived, so
  the guard set is the stronger one and the round-1 statement was a scoping error, not a gap.
- **Fix 1 and fix 3 agree with each other and with the code.** The docstring's sequence "bind →
  `chmod` → tasks → unlink → `shut_down()` → clean return" (`:476-477`) is `main.py:238-260` in
  order; "pin `run()`'s own signal-path unlink rather than a later cleanup's" (`:478-479`) and the
  comment's "stops distinguishing `run()`'s unlink from asyncio's" (`:552`) describe one property
  from two sides. The brief says the docstring "names the three siblings"; it *counts* them without
  naming them, and the count is right — `:700`, `:869`, `:932` are the only other synchronous
  `callback(*args)` fires in the file (`:614` is a real `os.kill` after the bind), which is what my
  round-2 wording proposed. Nothing to fix there.
- **Fix 3's interpreter fact checked, not taken.** 3.13's What's New (gh-111246): `create_unix_server`
  gained `cleanup_socket=True` and `Server.close()` unlinks the path; `start_unix_server` forwards
  its kwargs. `pyproject.toml:9` reads `requires-python = "==3.12.*"`. The comment's "the pinned
  3.12.3" conflates the pin with the installed patch level, but the same idiom sits at
  `lifecycle.py:75`, `server.py:231` and `main.py:324`, and the comment's own last sentence states
  the pin exactly. Not raised.
- **Sweep for the stale-socket claim (brief question 2)**, repo-wide excluding `reviews/`, in the
  phrasings `stale socket`, `SIGKILL`, `power loss`, `OOM`, `died without cleaning up`,
  `leaves the file/behind`, `cannot handle`, `can handle`, `implies a process`, `clean it up`. Four
  sites carry the claim and agree — `main.py:222-232`, `architecture.md:718-724`,
  `FINDINGS.md:1739-1743`, `FINDINGS-archive.md:1655-1657` (scoped "on any signal it can handle",
  no list, defers to item 6) — and one further site carries it unscoped: finding 1. `architecture.md:
  715-716`'s "On exit the socket is unlinked before the process ends" is universal but the paragraph
  directly beneath it now scopes it; pre-existing, not raised. `lifecycle.py:45`, `connect.py:63-64`,
  `test_hook_connect_integration.py:109-110` and `test_mcp_connection_integration.py:127` quote the
  cause-agnostic signature and are fine.
- **FINDINGS item 6 read whole (`:1733-1774`)**: the struck head, the scoped clause, the retargeted
  guard, the `exec`-window caveat, the coverage tail and the "now pinned; does not license" sentence
  are mutually consistent. `fail_under = 95` at `pyproject.toml:203` matches.
- **`test_service_main.py:240-340`, which neither round listed as read**: nothing about the ordering.
  One pre-existing stale count at `:283`, folded into finding 4.

### Findings

1. **[NITPICK] The lede of the test that pins the ordering is the fifth site of the stale-socket
   claim, and the only unscoped one.** `tests/test_service_main.py:98`: *"The ordering that decides
   whether a socket file can outlive its process."* Under `SIGKILL` the file outlives the process
   whatever the ordering — `test_service_lifecycle_integration.py:631-643` asserts exactly that. The
   body scopes it to `SIGTERM` two sentences later, which is why this is a nitpick rather than round 1
   finding 3 again; but a headline reads as the claim, and the brief asked whether a further site
   existed. Suggested: *"The ordering that decides whether a `SIGTERM` can leave a socket file
   behind."*

2. **[NITPICK] Round-2 fix 1's appended clause is wider than the file.**
   `tests/test_service_main.py:479-480`: *"— elsewhere the same assertion is satisfied by the
   force-exit unlink too."* Of the three siblings, only
   `test_a_shutdown_timeout_forces_process_exit_from_inside_the_running_coroutine` (`:718`) asserts on
   the file; `:830` and `:889` assert nothing about it. And the file's two other
   `assert not sock_path.exists()` (`:92`, `:203`) are satisfied by the `except BaseException:` unlink
   at `main.py:358`, not the force-exit one — so on either reading of "elsewhere" the clause
   overstates. The clause was added beyond my suggested text, which is where the widening entered.
   Suggested: *"— the one sibling that also asserts on the file
   (`test_a_shutdown_timeout_forces_process_exit_from_inside_the_running_coroutine`) has the
   force-exit unlink satisfying it as well, and the other two assert nothing about it."*

3. **[NITPICK] "Cannot handle" is the wrong predicate, at all four sites — and it is my wording.**
   Round 2 finding 2 listed *"`SIGHUP` or `SIGQUIT` sent explicitly"* among the causes of a stale
   socket; the sentence I proposed in the same finding excludes them by predicate, since both are
   catchable — this process *can* handle them and does not. `kill -HUP <service pid>` leaves the
   file, and `architecture.md:722`'s "only a death this process cannot handle" says it does not.
   Operational consequence is nil (step 4 clears it), hence the tag. Optional; **if taken, take all
   four sites in one pass**, since this is a one-claim, four-site edit of exactly the kind the trail
   records cascading:
   - `design/architecture.md:722`: *"Only a death this process does not handle — `SIGKILL` (an OOM
     kill included), a crash in native code, any other signal left at its default disposition, a
     power loss — leaves a stale socket…"*
   - `zikaron/service/main.py:223`: *"impossible for either signal this process handles"*; `:229`:
     *"A death this process does not handle still leaves the file"*.
   - `FINDINGS.md:1741`: *"any death it does not handle still leaves one"*.
   - `FINDINGS-archive.md:1657`: *"on either signal it handles"*.

4. **[NITPICK] `:399-407` should travel with this change — yes — and so should its one sibling of
   the same class in the same file.** `tests/test_service_main.py:402-403`: *"per `run()`'s own
   `(signal.SIGTERM, signal.SIGINT)` order"* — `run()` no longer contains the tuple (`main.py:52`), so
   the citation resolves to nothing. It predates this change, but it is a stale referent in a file
   this change is editing for exactly that class, and it is one edit: *"per
   `_stop_on_sigterm_or_sigint`'s own `(signal.SIGTERM, signal.SIGINT)` order"*. On the same
   principle, `:283` (*"on both tasks together"*) has been three tasks since M17's load watch
   (`main.py:158-163`; this test's store exists, so the open path is taken and the watch is created):
   *"on every task together"*. Class over site, in a file already open; both are optional on the
   brief's own terms.

VERDICT: APPROVED
