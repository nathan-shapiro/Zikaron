# Review — the first push after an idle stop (`cold-start-push`)

Artifact: the working-tree change set (`scratchpad/cold-start-push.diff`) and the files it touches
as they stand — chiefly `zikaron/hook/{push,connect,rpc,limits}.py`, their tests,
`design/architecture.md`, `design/distribution.md`, `design/harness.md`, `design/retrieval.md`,
`design/knowledge-index.md`, `design/coding-standards.md` §7, `README.md` §"When something is
wrong", `FINDINGS.md` §"Current state".

## Round 1 — 2026-10-11

**Summary judgment.** The mechanism is sound and the code is better than the design text that
describes it: the split deadline, the child-exit check in the poll, the bounded lock wait and the
re-armed socket timeout are each correct, each tested at the seam that matters, and the thirteen
mutations the brief reports cover the branches I would have asked for. What is not ready is the
prose the notice rests on: one of the two rules that make "needs no report" honest — *the next
message finds the service running* — is false in a reachable state the change does not close (a
start still unbound at the next message is spawned again, and the later binder takes the path from
the earlier), and the entry-point decision table still says the hook gives up at 1.2 s. Both are
cheap to fix; neither is optional under the intent's "keep `design/` true to the code".

### Findings

1. **[BLOCKER] `design/overview.md` D37 row (line 193) still says the hook "gives up at 1.2 s".**
   The Rationale reads: *"half a second paid once behind an unbound socket is invisible to the
   hook, which gives up at 1.2 s against a cold start already measured at 3.74 s."* Present tense,
   and the number is gone from the code. The sweep's grep terms (`~2 s`, `2 s`, `unanswered`,
   `deadline`) do not reach it, which is the "by meaning, not by match" case `CLAUDE.md` warns
   about. The decision table is the standing case where a withdrawn claim is struck and the
   correction set beside it, so the fix is not a rewrite:
   > half a second paid once behind an unbound socket ~~is invisible to the hook, which gives up at
   > 1.2 s against a cold start already measured at 3.74 s~~ — **amended 2026-10-11: a push that
   > finds the service absent now waits `HOOK_TIMEOUT_SECONDS` less 2 s for the start
   > (`architecture.md` §"Degraded modes"), so the half second is spent inside a budget it fits in
   > rather than past one the start already missed; the conclusion stands either way.**

2. **[BLOCKER] `design/architecture.md` §"Degraded modes", last bullet (line 1282): *"a start that
   never comes good is reported by the next message, which finds the service running"* is false
   whenever the start outlives the cold-start deadline plus the gap to the next message — and the
   state it leaves is two services on one store.** The lock lives exactly as long as the hook's
   poll (`_start_under_lock`'s `finally`), so message 1 releases it at 8 s with its child still
   starting; message 2's first connect fails, the lock is free, the recheck fails, the socket file
   does not exist yet so there is nothing to vet, and `_spawn_detached` runs again. Whichever
   service binds second wins the path: `server.serve` hands `path=` to
   `asyncio.start_unix_server`, and CPython's `create_unix_server` `os.remove`s an existing socket
   file before `bind` without asking whether anything is listening on it. The first service keeps
   running with the store open and whatever connections it already had (an established UDS
   connection survives the unlink, so a `zikaron-mcp` attached to it keeps it from idling), which
   breaks "at most one service per store" (§"The MCP server" line 807) for as long as both live.
   This hole predates the change — the 1.2 s poll had it wider — and the change narrows it, but
   the sentence is new, and it is one of the two rules the bullet says *"keep that notice honest"*.
   Two edits:
   - Qualify the rule: *"…is reported by the next message **if the start has bound by then**: it
     finds the service running — it stays up for the idle timeout — and alarms if it still cannot
     answer. A start still unbound at the next message is spawned again, because the lock is held
     only for the poll and nothing outlives the hook to hold it longer; the later of the two binds
     over the earlier (`asyncio.start_unix_server` removes an existing socket file before it
     binds), which is a hole start-if-absent has always had and this change narrows."*
   - Record it in `FINDINGS.md` §"Owed work" with the fix proposed, which is on the service side —
     the only side that outlives the hook: before `serve`, try to connect to `sock_path` and, if
     anything answers `health()`, log and exit rather than bind over it. That closes the hole for
     every client at once and costs one connect on a path that is normally absent.
   `README.md` line 793's *"A run of `starting` lines with nothing else between them means starts
   are slower than the hook allows, not that the service is broken"* should say the same thing in
   the user's terms: a run of `starting` lines **with one `service.log` start behind each** is a
   host where starts outlast the budget, and each such message starts another process.

3. **[IMPROVEMENT] `starting` erases which lateness it stands for, and the design then names a
   quantity `hook.log` can no longer yield.** `push._degrade` (line 202) logs bare `starting` for
   `deadline_exceeded`, `unanswered`, `deadline_passed`, the poll running out and the lock running
   out — five different facts about where a cold start spent its time. §"A push the agent never
   saw" (line 1327) then defines D30's lost denominator as *"`deadline_passed` plus `unanswered` in
   `hook.log`, **plus whichever `starting` lines were sent**"* — one sentence after saying the log
   does not record which were sent. And the operator's own diagnosis of this defect was made by
   reading `hook.log`'s kinds against `service.log`'s start lines; with no timing measurement
   (operator decision), `hook.log` is the only instrument left for whether 8 s is enough and
   whether the time goes before the bind (store open) or after it (model load). Suggested change:
   keep `starting` as the kind — the grep target and the closed vocabulary — and record what it
   stands for after it, from a closed set: `starting poll`, `starting lock`,
   `starting deadline_exceeded`, `starting unanswered`, `starting deadline_passed -32026`.
   Mechanically: a `phase` attribute on `ServiceStartingError` (set by `_lock_by` and
   `_poll_until_reachable`), `failure.record_failure(path, kind, *, code, detail: str | None)`
   with `_format_line` emitting `kind detail [code]`, and `_degrade` passing the folded kind as
   the detail. Then line 1327's clause is computable, and §"Degraded modes" line 1276's *"with no
   code"* and `README.md` line 807's description are updated. If the author prefers to keep the
   line bare, delete the *"plus whichever `starting` lines were sent"* clause and say the
   cold-start population is uncounted.

4. **[IMPROVEMENT] The `cold_start` predicate misses the service that bound moments ago and is
   still loading its model — the session-start sequence.** §"Warming" (line 1054) has the
   `SessionStart` helper spawn the service so *"the first push of a session is not the slow one"*,
   and §"The model loads behind the socket" has that service answer `health()` before the model is
   loaded. A first message arriving in that window — the user types as the session opens, on a
   loaded host where the deferred load takes two or three seconds — finds the socket present, so
   `cold_start` is `False`, the push gets 2 s, `surface` blocks on the load, and the agent is told
   *"Please let the operator know the memory hook failed"* — the symptom this change exists to
   remove, reached by the other path a cold service is created on. `HealthStatus`
   (`service/dispatch.py` line 75) carries no load state, so the hook cannot tell this service
   from a wedged one. Suggested change: a `health()` field for the encoder's load state (the
   `BackgroundLoadedEncoder` already knows it), with `cold_start = sock is None or not
   health.encoder_loaded`, and §"Degraded modes" line 1254's *"a service that was already
   running"* defined as one whose `health()` reports the model loaded. If that is out of this
   fix's scope, it belongs in `FINDINGS.md` §"Owed work" with that fix proposed, and the test
   docstring at `tests/test_hook_push.py` line 707 (*"the wedge case, which the operator has to
   hear about"*) should not call a service one second old a wedge.

5. **[IMPROVEMENT] The guard for the cold-start margin asserts no margin, and the design's
   accounting of the 2 s omits what actually spends most of it.** `tests/test_install_limits.py`
   line 274 asserts `push._DEADLINE_SECONDS < push._COLD_START_DEADLINE_SECONDS < TIMEOUT_MS / 1000`
   — a cold deadline of 9.99 s passes, while the docstring claims the failure path fires first.
   And §"Degraded modes" line 1258 says *"The 2 s left over is the hook's own interpreter start
   and its print"* — but the interpreter start is tens of milliseconds (D36 measured it), and the
   larger spend is the connect's own overrun past the deadline, which nothing in `connect.py`
   bounds by it: `_lock_by`'s last sleep, then a recheck `_try_connect` of up to
   `_CONNECT_TIMEOUT_SECONDS`, then `_health_or_close` at the same per-`recv` timeout; or, on the
   poll path, the last `_try_connect` plus `_health` before the deadline check at line 309 — about
   0.65 s past 8 s before `run` sees `remaining <= 0`. Suggested change: assert the margin
   against what it must cover, e.g. `TIMEOUT_MS / 1000 - push._COLD_START_DEADLINE_SECONDS >=
   2 * connect._CONNECT_TIMEOUT_SECONDS + connect._POLL_INTERVAL_SECONDS + 1.0` with the terms
   named in the docstring, and amend the design sentence (and `push.py` line 36's comment) to
   name the connect's overrun as the first thing the 2 s pays for.

6. **[NITPICK] `_MAX_DEADLINE_AHEAD_SECONDS = 5.0` sits exactly on the bound.** `dispatch.py`
   line 178 refuses `value - now_ms() > BUSY_TIMEOUT_MS`; the hook sends `int((time.time() + 5.0)
   * 1000)`, so the pair is legal only while the realtime clock does not step backward between
   the two reads. A `bounds` refusal would alarm on exactly the message this change quiets. `4.5`
   costs nothing and the guard at `tests/test_hook_push.py` line 785 can then assert strict `<`.

7. **[NITPICK] `connect._health` (line 314) keeps the per-call timeout on a recv-until-newline
   loop — the class `rpc.surface_once` was just fixed for, in the same helper shape.** Either
   bound it from the caller's deadline the way `_time_out_at` does, or say in `connect.py` why a
   one-line answer makes the per-call bound acceptable there, so the next reader does not re-find
   it.

8. **[NITPICK] §"Degraded modes" step 2 (line 1195) excepts only "lateness on a push that found the
   service absent"**, while §"A push the agent never saw" defines lateness as three kinds that do
   not include the poll or the lock running out — which the later bullet (line 1273) does list.
   Read in order, step 2 says `health()` never ready relays, and the bullet says it does not.
   Make step 2's clause *"except a start still running at the deadline on a push that found the
   service absent — the poll, the lock, or lateness after it"*.

9. **[NITPICK] `design/build-plan.md` §M35 describes the replaced mechanism and the old guard.**
   Lines 5093–5100 state the deadline as read at `started_at` from `_DEADLINE_SECONDS`, and line
   5306 states the invariant as `push._DEADLINE_SECONDS × 1000 ≤ ddl.BUSY_TIMEOUT_MS`, which the
   guard now asserts of `_MAX_DEADLINE_AHEAD_SECONDS`. The brief exempts §M17 by name; the rule it
   gives — the record of a landed milestone — covers §M35 as well. State the rule rather than the
   section in the brief and the PR, so the next reader does not take the named exemption as the
   whole of it.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-11

**Summary judgment.** Every round-1 finding is answered in the tree and answered well: the
ownership lock is held from before the store opens to after it closes, named by pid, bounded on
both sides, and tested with two real services; `health()` now lets the hook tell a young loading
service from a stalled one; `starting` carries what it waited on; the margin guard asserts what
the margin must cover; `_health` is bounded as a whole. One thing the fix for finding 2 did is
contradict the design in three places it did not touch: a deferring start now writes into the
serving service's `service.log`, and `architecture.md` says — in §Paths, in the filesystem table,
and in §"Warming" — that this file has exactly one writer and that the one-writer rule is what
spares the design from having to prove concurrent appends safe. That is a sentence's worth of fix.
Below it, the design presents the `EX_TEMPFAIL` reading as one of the three rules that keep the
notice honest, and on the shipped numbers the hook never makes that reading in time; and one
pre-existing self-healing path has become a lockout. Mechanism sound; prose and one edge to settle.

### Findings

1. **[BLOCKER] `service.log` has a second writer by design, and the design says in three places
   that it has one.** `main.run` (line 245–247) logs `not starting: reason=another_service` from
   a start that found the store held, while the serving service holds the same file open through
   its own `FileHandler`; `tests/test_service_main.py` line 387 asserts the line lands there, so
   this is intended. `design/architecture.md` line 403 (§Paths): *"Logs: one file per process,
   never shared … two independent processes writing the same path through `logging` is a real
   corruption risk … giving each process its own file removes the question entirely rather than
   requiring proof that concurrent appends are safe"*; line 633 (filesystem table, `service.log`
   row): *"Each is written by exactly one process, never shared"*; line 1077 (§"Warming"): *"two
   processes writing one file through `logging.FileHandler` with no cross-process locking is a
   corruption risk, not a convenience — see §Paths"*. `zikaron/service/log.py` line 5 and
   `zikaron/service/paths.py` line 166 say the same. The change now requires exactly the proof
   §Paths says it was built to avoid, and the proof exists: `FileHandler` opens in `a` mode, so
   the descriptor carries `O_APPEND`, and each record is one `write()` of one line, so two
   appenders interleave whole lines and corrupt nothing. State it rather than leave the three
   sentences false. Suggested edits — §Paths line 403, after *"by design:"* add *"**with one
   admitted exception**: a start that finds its store held by another service writes one
   `not starting` line into that service's `service.log` before it exits (§"Start-if-absent"),
   which is safe only because the handler appends — `O_APPEND`, one `write()` per record — so
   two writers interleave whole lines; that is the proof the rule otherwise spares us, and the
   exception is the one place it is needed"*; the table row's last clause becomes *"Each is
   written by one resident process — `service.log` also takes one line from a start that found
   the store held, appended whole (§Paths)"*; §"Warming" line 1077 keeps its sentence and adds
   *"the one exception, and why it is safe, is in §Paths"*; `log.py`'s module docstring and
   `paths.service_log_path`'s docstring get the same clause. If the author would rather keep the
   rule absolute, the alternative is a separate file for the deferring start — but that is a
   fourth log for one line, and the README already tells the operator to read `service.log` for
   it (line 759–760), so the amendment is the better fix.

2. **[IMPROVEMENT] The `EX_TEMPFAIL` reading is unreachable on the shipped numbers, and the design
   presents it as one of the three rules that keep the notice honest.** `ownership.
   PREDECESSOR_WAIT_SECONDS` is 10 s; `push._COLD_START_DEADLINE_SECONDS` is 8 s; the child's
   own interpreter start and imports precede its wait. So a push's own child exits 75 no earlier
   than ~11 s after the push began, and the push gave up at 8 s: `_poll_until_reachable`'s
   `exit_status != _ANOTHER_SERVICE_EXIT_STATUS` branch (connect.py line 350) never sees a 75
   while the push is alive, and what actually decides a queued push at its deadline is the
   "child still running" path plus `_raise_if_queued_behind_a_stalled_start` reading
   `<sock>.service`. Three passages say otherwise: `design/architecture.md` line 695–696 (*"exits
   `EX_TEMPFAIL` (75), which a spawning push reads as another service to wait for rather than a
   start that failed"*), line 1299–1302 (rule 1: *"unless it exited because another service holds
   the store … which is then the one waited for"*), and `connect.py` line 63–64 (*"that one is
   serving or starting the store, so the poll goes on looking for it"*). A reader who trusts
   those could remove the `.service` check believing the exit reading covers queued starts, and
   it does not. Do **not** shorten the wait to make the reading land: it must outlast a
   predecessor's 5 s quiescence plus its store close (the guard at `test_service_ownership.py`
   line 80 is right), and reading the exit at 7 s instead of finding the child alive at 8 s
   changes nothing the push does. Reword instead: §"Start-if-absent" — *"…exits `EX_TEMPFAIL`
   (75). A push whose own child defers is normally gone before that exit lands — the wait is
   longer than the push's deadline — so what the push reads at its deadline is the holder's
   name and age in `<sock>.service` (§"Degraded modes"); the poll also treats a 75 it does see
   as a start to keep waiting for, so a shorter wait could not read a deferral as a failure"*;
   rule 1 in §"Degraded modes" correspondingly; `connect.py`'s constant comment likewise; and
   the docstring of `test_the_hook_reads_the_exit_status_a_deferring_service_exits_with`
   (*"a mismatch would read every deferring start as a failed one"*) qualified to *"…would, on
   any wait shorter than the push's deadline"*. One clause on cost belongs beside it: every
   message during a start longer than the deadline spawns a service process that imports,
   waits ten seconds and exits — bounded, and worth saying where the operator reads
   `service.log` and sees one `not starting` per message.

3. **[IMPROVEMENT] "One service per store" is one service per socket path — per (runtime
   directory, store) — and the new paragraph overclaims.** `paths.socket_path` prefixes the
   store hash with the runtime directory, so one store reached from a session with
   `$XDG_RUNTIME_DIR` set and another without it (`/run/user/<uid>/zikaron/<h>.sock` against
   `/tmp/zikaron-<uid>/<h>.sock`) gets two `.service` files and two services, each holding its
   own lock, exactly as it always could. `design/architecture.md` line 688 (*"One service per
   store is enforced by the service"*), `ownership.py` line 1 and `main.run`'s docstring line
   203–205 state the per-store form; §"The MCP server" line 822 has carried the same
   imprecision since before this change. Do not move the lock beside the store to make the
   sentence true: the second runtime directory's clients cannot reach the first's socket, so a
   store-wide lock turns a harmless duplicate into a lockout — they would spawn, defer, and
   alarm until the first service idled out. Qualify instead: *"One service per socket path —
   one per store within a runtime directory — is enforced by the service … A store reached
   through two runtime directories can still be served twice, as before; SQLite's own file
   locking keeps that correct and the second idles out on its own clock."* Same clause in
   `ownership.py`'s docstring, and *"at most one service per store **and runtime directory**"*
   at line 822.

4. **[IMPROVEMENT] A serving service whose socket file is removed from under it used to
   self-heal and is now a lockout for up to `idle_timeout`.** Before: the next push found
   `ENOENT`, spawned a replacement that bound in the socket's place, and the orphan idled out
   while pushes kept working. Now: the replacement waits 10 s on the holder's `.service` lock
   and exits 75; the push's `_raise_if_queued_behind_a_stalled_start` reads the holder's lock
   mtime — its whole uptime, past 60 s on any service older than a minute — and reports
   `transport` on the first such push and every one after; `zikaron-mcp`'s
   `connect_start_if_absent` fails its 10 s poll and its one retry, so tool calls fail too; and
   it lasts until the holder's idle clock, which no request can now refresh, reaches
   `idle_timeout` (30 min) — one throwaway service per message meanwhile. The trigger is narrow
   — a human `rm` of `<h>.sock`, or a tool that unlinks sockets alone — since a runtime
   directory removed whole (logout clearing `$XDG_RUNTIME_DIR`, a `/tmp` reaper) takes the lock
   file with it, the orphan's `flock` then sits on an unlinked inode, and a successor locks a
   fresh file and heals as before. Fix, small and in the component that already polls:
   `lifecycle.idle_self_stop` (line 109) adds a third exit condition beside idle and
   `store_replaced` — `sock_path` missing, or its inode not the one `serve` bound — stopping
   with `reason=socket_lost`; the `unlink` at line 118 is already `missing_ok`. One `lstat` per
   30 s poll. §"Idle self-stop" (architecture.md line 859) then names three conditions, and
   README's `stopping: reason=…` list (line 757) gains the word. The operator's standing
   direction in this brief is to fix owed work found on the way rather than record it; if it is
   instead recorded, `FINDINGS.md` §"Owed work" needs the entry with this fix.

5. **[NITPICK] Two "stalled" bounds, one rationale stated.** A bound service still loading is a
   start for `_COLD_START_DEADLINE_SECONDS` (8 s, `push.py` line 124–126; design rule 2, line
   1302); an unbound holder is a start for `_STALLED_START_SECONDS` (60 s, connect.py line 73).
   There is a reason they differ — the unbound phase can hold a first-run model fetch, since the
   create path loads before it binds, while the bound-but-loading phase is a cached load — but
   neither passage says so, and the first number is the harness's hook budget less 2 s, which
   nothing links to how long a cached ONNX load takes under load. State the reason in rule 2
   (*"…longer than the cold-start deadline — a cached load that outlasts the whole budget a push
   can spend on it — is not starting"*), and note beside it that a push which found the service
   at once gives the request the 4.5 s cap, not the 8 s, so that is the time the load has.

6. **[NITPICK] A `TimeoutError` raised before the send is classified `unanswered`.**
   `rpc.surface_once` line 95 calls `time_out_at` before `sendall`, which raises if `deadline.by`
   has passed between `run`'s `remaining` computation (push.py line 129) and the send — the
   envelope build and the JSON encode, a sub-millisecond window when `remaining` is tiny — and
   `run` line 141–146 maps every `TimeoutError` to `unanswered`, whose definition at
   architecture.md line 1342 is *"a push sent … which the service did receive"*. Either drop the
   pre-send arm (`run`'s own `remaining <= 0` check already covers it, and `settimeout` can take
   the small positive value), or raise a distinct subclass from it and map that to
   `deadline_exceeded`. `test_a_deadline_already_past_times_out_without_sending` pins the current
   shape, so it changes with whichever fix.

7. **[NITPICK] `tests/test_service_server.py` line 298** still quotes `health()`'s field set as
   *"`architecture.md`'s `{ready, store_path, store_id, embed_model, embed_dim, schema_version,
   pid}`"*; the design's set grew by two. Point at §"Store identity is verified, not assumed" as
   `dispatch.health`'s docstring now does, rather than enumerate.

8. **[NITPICK] `FINDINGS.md` §"Current state", the "In progress" block (line 104–128).** *"Review
   round 1 (…) is applied"* and *"review round 2 with a re-read pass before it and before every
   round after, iterating to APPROVED"* are round narrative, which §"Project memory" sends
   nowhere; and the bullet *"**The fix** … A push that found the service absent … gets
   `HOOK_TIMEOUT_SECONDS` less 2 s"* is the narrower statement the paragraph above it already
   widened to *"or still loading"*. Trim to what is built — the split deadline, `starting` with
   its detail, the ownership lock, the `health()` fields — where each is normative, and what is
   next: the gate, a review, a PR on `cold-start-push` when asked.

9. **[NITPICK] `connect.py` line 69–72**: *"costs a message an alarm"* — a first run whose fetch
   outlasts a minute costs every message after that minute an alarm until it binds, which is
   what an operator reading a run of `transport` lines during a first install needs to know;
   README line 797 already says it that way.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-11

**Summary judgment.** Every round-2 finding is answered in the tree, and I checked each against
the code rather than the brief: the one-writer rule now admits its exception with the proof
(`O_APPEND`, one `write()` per record — true of `FileHandler`'s `a` mode plus `flush()` per
`emit`); the `EX_TEMPFAIL` reading is described as the thing the push normally never lives to see;
"one service per socket path" is qualified where it is stated; `socket_lost` is a real third exit
condition with a test that plants a foreign file at the path and asserts it survives; rule 2 says
why its bound differs; `NotSentError` makes the pre-send timeout `deadline_exceeded`. The ownership
lock is sound — never unlinked, so the flock-on-an-unlinked-inode race does not arise; the runtime
directory is vetted before the lock file is created; the holder's name is cleared before the fd is
closed. What remains is one predicate the design states and the hook cannot compute — rule 3's
"without answering" — which alarms once, with the exact relay this change exists to quiet, on a
predecessor whose shutdown outlasts the push's deadline; and three nitpicks. No blocker.

### Findings

1. **[IMPROVEMENT] Rule 3 states a predicate the hook does not test, and the gap is a non-fault
   that alarms.** `design/architecture.md` line 1330–1331: *"a push whose own start is queued
   behind another holder that has kept the store over a minute **without answering** reports
   `transport`"*; `connect.py` line 71–72 (*"hold the store without answering"*) and line 370–372
   (*"has held the store past `_STALLED_START_SECONDS` without answering has stalled"*) say the
   same. What `_raise_if_queued_behind_a_stalled_start` (line 377–391) actually tests is: the
   `.service` file's mtime is over a minute old, the named pid is alive, and it is not this push's
   child. The mtime is when the holder *took* the store (`ownership._name_the_holder`, written once
   at acquisition and again only at release), so "age" is the holder's whole uptime, and nothing in
   the check knows whether it ever answered. The two predicates differ on exactly one state: a
   predecessor **in shutdown**. It has unlinked its socket first (`idle_self_stop` line 128, and
   the signal path), so the push's first connect gets `ENOENT`, it spawns a child, and the child
   waits on `.service`, which still names the predecessor until its store is closed
   (`holding_the_store`'s `finally`). If the child has not taken the lock by the 8 s deadline —
   a `SIGTERM` or `store_replaced` landing during a long in-flight request spends up to
   `_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS` (5 s) in quiescence, then the store close, on the loaded
   host this defect was observed on — the push reads a holder older than a minute, alive, not its
   child, and reports `transport` with *"Please let the operator know the memory hook failed"*,
   for a service that answered every request for an hour and is stopping cleanly. Rare, bounded to
   one message, and diagnosable from `service.log` — but the design says it cannot happen. Two
   fixes, either sufficient:
   - **State it** (the cheap one). Rule 3 becomes *"…behind another holder that has kept the store
     over a minute reports `transport` — the hook reads the holder's age, not whether it ever
     answered, so a predecessor whose shutdown outlasts the push's deadline reads the same way and
     alarms once; `service.log`'s `stopping:` line followed by the successor's start says which it
     was"*; §"Start-if-absent" line 703–704 (*"the holder's name and age"*) and `connect.py`'s two
     passages drop "without answering" for "past `_STALLED_START_SECONDS`"; README line 797–798
     adds *"or a service whose shutdown took longer than a start is allowed, once"*.
   - **Or make the age mean the current phase**: have the service rewrite its name into the lock
     file when shutdown begins (`_name_the_holder(fd, f"{pid}\n")` again — a rewrite stamps mtime),
     so a stalled start's age keeps growing while a shutting-down predecessor's is its shutdown's
     duration, which alarms only when the shutdown itself is wedged. That needs the fd reachable
     from where shutdown starts (`idle_self_stop` and `_open_and_serve`'s signal branch) — a small
     object returned by `holding_the_store` rather than `None` — and a test that a holder stamped
     at shutdown is still a start to a push at its deadline.

2. **[NITPICK] Two older unqualified statements of "one service per store" remain.**
   `design/architecture.md` line 384 (§Paths, the socket bullet: *"One service per store."*) and
   line 506 (§Configuration: *"One service per store means two projects on one machine share
   layer 2…"*). Round 2's finding 3 reached the new paragraph, `ownership.py`, `main.run` and the
   census line; these two predate it. Line 384 sits in the very bullet that names the two runtime
   directories, so *"One service per socket path (§"Start-if-absent, without a thundering herd")"*
   is enough there; line 506's use of the claim is about config layers and is unaffected by the
   duplicate, so it can stay or take the same three words.

3. **[NITPICK] Two "exactly" claims that are "just under".** `design/architecture.md` line
   1225–1226: *"never more than `ddl.BUSY_TIMEOUT_MS` ahead … so a cold start's longer deadline
   is cut to **that**"* — the code cuts to `_MAX_DEADLINE_AHEAD_SECONDS` (4.5 s against 5 s), and
   `push.py` line 46–49 says why; make it *"cut to just under that, so the two ends' clock readings
   cannot straddle the bound"*. And `connect.py` line 151, `Connection`'s docstring: *"`sock`'s
   timeout is still `_CONNECT_TIMEOUT_SECONDS`"* — after `_health` re-armed it per read it is
   whatever was left of that; *"`sock`'s timeout is what `_health` left of
   `_CONNECT_TIMEOUT_SECONDS`"*, since the sentence's point (the caller sets its own) is right.

4. **[NITPICK] The notice promises "the next message", which the design says is not always
   true.** `push.py` line 65–69: *"memories are surfaced again from the next message"*;
   `design/architecture.md` line 1320–1321 and README line 796–797 say the same, while README line
   797 and §"Start-if-absent" line 706–707 admit a run of `starting` lines when a start outlasts
   the deadline. *"memories return once it has started — usually the next message"* is true in
   both cases and costs nothing; `test_a_late_push_to_a_service_it_found_absent…` asserts
   `output == push._STARTING_RELAY`, so no test moves.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-11

**Summary judgment.** Round 3's finding is answered the better of the two ways: `StoreHold.stepping_down`
clears the holder's name as the first act of `shut_down`, which every stop — idle, `store_replaced`,
`socket_lost`, signal, and the `except BaseException` retry — passes through, and a hard exit after a
failed graceful shutdown still leaves the name cleared because the clearing came first. I traced every
hook path against the code rather than the brief: the split budget, the 4.5 s cap, `NotSentError`,
`starting` with its detail, the child watch with the 75 exception, the lock wait ending at the
deadline, both exchanges timed whole, the ownership lock held from before the store opens to after it
closes and never unlinked, and the deferring start's single line — `configure_service_log` emits
nothing of its own, so the design's "a single `not starting` line" is exact. The four nitpicks of
round 3 are applied. What remains is narrower than any earlier round: one state the brief's intent
says is closed and the code does not close, one predicate the tests pin by its log word but not by
its budget, and three wordings. No blocker.

### Findings

1. **[IMPROVEMENT] A removed socket still alarms — every push whose deadline lands before the
   service's next 30 s poll — and neither the design nor the README says so, while the brief's
   intent says it does not happen.** Trace: service S has served a minute or more; its socket file is
   removed at t=0; a push at t=1 finds `ENOENT`, takes the lock, spawns C, and C waits on
   `<sock>.service`, which S holds. At the push's 8 s deadline `_raise_if_queued_behind_a_stalled_start`
   (`connect.py` lines 378–392) reads S's pid, finds it alive and not C, and `held_for` is S's whole
   uptime — the mtime is stamped at acquisition (`ownership._name_the_holder`, lines 76–84) and again
   only at step-down — so it exceeds `_STALLED_START_SECONDS` and the push reports `transport` with
   *"Please let the operator know the memory hook failed"*. S notices at its next poll
   (`IDLE_POLL_INTERVAL_SECONDS` = 30 s, `lifecycle.py` line 34), steps down, and the push after that
   is `starting`. So the lockout of round 2's finding 4 is gone and the alarm is bounded to one poll
   interval, which is a real fix; but rule 3 (`design/architecture.md` lines 1332–1338) and the new
   `socket_lost` paragraph (lines 922–930) are each true without either saying what they jointly
   imply, and README lines 797–799 name only *"a start that never finishes"* as what reads
   `transport` at the minute — where `connect.py` lines 71–76 also names a first-run fetch, and this
   case names a service that was serving correctly. Two fixes; the second is small and the operator's
   standing direction prefers it:
   - **State it.** §"Idle self-stop" lines 922–930, after *"a clock no request can now refresh"*: *"A
     push whose deadline lands before that poll reads the orphan as a holder that has kept the store
     too long and alarms once (§"Degraded modes", rule 3); the poll after it ends that."* README
     lines 798–799: *"a `transport` line after a run of `starting` is a holder that has kept the
     store a minute without answering — a first run still fetching its model, or a service whose
     socket file was removed, until it notices at its next poll and stops"*.
   - **Or make the age mean "since the holder last showed life", so a serving service never reads as
     stalled.** `StoreHold` gains `still_here()` → `os.utime(self._fd)` (`os.utime` takes an fd on
     both supported platforms), and `idle_self_stop` calls it on every poll that does not stop — the
     `continue` branch at `lifecycle.py` line 123 — with `_self_stopping_tasks` (`main.py` line 155)
     passing the hold through. Then a serving service's `.service` mtime is never older than 30 s
     against the 60 s bound, a lost-socket orphan reads as a start until it stops itself, a start that
     never reached the loop keeps its acquisition stamp and alarms at the minute exactly as now, and a
     bound service whose loop is blocked stops stamping and alarms too — which is closer to "stalled"
     than uptime is. Prose: rule 3's *"has kept the store over a minute"* → *"has shown no life for
     over a minute"*; §"Start-if-absent" line 702's *"name and age"* → *"name and last stamp"*;
     `connect.py` lines 71–76 and 369–373 and `_name_the_holder`'s docstring likewise. Tests: in
     `test_service_lifecycle.py`, a poll that does not stop advances the lock file's mtime; in
     `test_hook_connect_edge_cases.py`, the existing `young-holder` case already covers the hook side.
     Cost: one `utime` per 30 s.

2. **[IMPROVEMENT] The longer budget for a young loading service is pinned only by its log word.**
   `tests/test_hook_push.py` lines 777–807 (`…is_a_start_only_while_young`) asserts
   `starting unanswered` for `uptime_seconds=0.1` and `unanswered` for `30.0`, and nothing else. The
   mutation `budget = _COLD_START_DEADLINE_SECONDS if connection.cold_start else _DEADLINE_SECONDS`
   at `push.py` line 127 — dropping `still_loading_within` from the budget while the `cold_start`
   variable still folds the kind — passes both cases: the young push waits 0.2 s instead of 0.5 s and
   logs the same words. That is the second of the intent's two "starting" predicates, with no test
   that it buys any time. Suggested: a sibling of that test with a service that answers,
   `time.monotonic` patched to a constant and `time.time` to `T`, asserting
   `_sent_deadline_at_ms(service) == int((T + push._COLD_START_DEADLINE_SECONDS) * 1000)` for
   `uptime_seconds=0.1` and `int((T + push._DEADLINE_SECONDS) * 1000)` for `30.0`, both constants
   patched under `_MAX_DEADLINE_AHEAD_SECONDS` so the cap does not bite. The helper exists; it is
   six lines.

3. **[NITPICK] `design/write-policy.md` lines 528–529**: *"The hook's response to all of them is
   identical: one line to its own `hook.log` plus a model-facing relay on stdout"* — on a push that
   found the service starting, `deadline_passed` lands after `starting` and the stdout notice asks
   for no relay. The clause the sentence exists for (never a read; no `surface_call` row) is
   unchanged. *"…has one shape: one line to its own `hook.log` plus a model-facing notice on
   stdout — a relay, or, on a start still running, a statement that memories resume — never a
   read"*.

4. **[NITPICK] `connect.py` line 391**: the raised message still ends *"for {held_for:.0f} s
   unanswered"* — the predicate round 3 established the hook does not test, surviving in the one
   string nobody logs. Drop the word, or *"still named"*.

5. **[NITPICK] `push._STARTING_RELAY` (lines 65–69)**: *"This is expected when the service has not
   been running"* — on the warm-up path it was running and loading. *"when the service was not yet
   running, or had only just started"* covers both; the two tests assert equality with the constant,
   so nothing else moves.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-11

**Summary judgment.** Round 4's two improvements are answered the way they were asked: `StoreHold.still_here`
stamps the lock file from every idle poll that does not stop, `_self_stopping_tasks` hands it over and a test
pins the hand-over, and the young-loading budget is now asserted as the `deadline_at_ms` sent, under the cap.
I re-traced the whole mechanism against the code rather than the brief — the split budget and its cap,
`NotSentError`, the child watch with the 75 exception, the lock wait ending at the deadline, both exchanges
timed whole, the hold from before the store opens to after it closes, step-down as `shut_down`'s first act,
`socket_lost` leaving a foreign file alone, the stamp against the 60 s bound — and found no state in which a
serving service or a cleanly stopping one alarms, and none in which a failed start reads as a start for longer
than another client's own poll. That last clause is the one thing left: the design says three rules bound how
long a wait may be called a start, and the lock wait is bounded by none of them — it is bounded, by the other
client's deadline, but nothing says so, and on the shipped numbers a service that cannot start reads as
`starting lock` for the first message or two of a session. One test the intent names is missing, and three
wordings lag round 4's change. Close to the bar; not over it.

### Findings

1. **[IMPROVEMENT] The lock wait is the one way a wait is called a start that none of the three rules bounds,
   and a service that cannot start reads as `starting lock` for as long as another client polls for it.**
   `design/architecture.md` lines 1327–1328: *"Three rules keep that notice honest, each by bounding how long
   one start may be called one"* — the child watch (poll path), the uptime bound (loading), the minute (queued
   behind a holder). `_lock_by` (`connect.py` lines 227–247) raises `ServiceStartingError("lock")` at the
   deadline with no check of any kind, and line 676–678's step 2 says *"a lock still held there is a start
   still running"*. What holds `<sock>.lock` besides another hook is `lifecycle._try_connect_twice_under_lock`
   (lines 400–440) — `zikaron-mcp`, the warm helper, `zikaron init` — with a **blocking** `flock` kept through
   `lifecycle._poll_until_reachable` (lines 454–482), which does **not** watch the process it spawned and polls
   to its full 10 s. So at session start with a service that exits at once (a bad config): the warm helper
   takes the lock, spawns, and holds it 10 s; `zikaron-mcp` does the same, twice (`_MAX_ATTEMPTS = 2`); a push
   arriving in those windows waits to its 8 s deadline and logs `starting lock` with the notice that asks for
   no report. Rule 1's own justification — *"a service that cannot start would otherwise cost every message the
   whole cold-start deadline and read as one still starting"* — is exactly the cost those messages pay. It is
   bounded (≤ ~11 s per `lifecycle` attempt, ≤ 8 s per hook), so the notice is still honest in the end; the
   gap is that the design claims the bound comes from three rules and it comes from a fourth it does not state.
   Two fixes; the first is sufficient, the second is the operator's standing preference for owed work found on
   the way:
   - **State the fourth bound.** After rule 3 (line 1343): *"A lock another client still holds at the deadline
     is bounded by that client's own poll — `lifecycle._HEALTH_POLL_DEADLINE_SECONDS` (10 s) for `zikaron-mcp`,
     the warm helper and `zikaron init`, which do not watch the process they spawned, or another push's
     cold-start deadline — so a service that cannot start reads as `starting lock` for at most those windows,
     until a push of its own spawns it and reads the exit."* Same clause in `_lock_by`'s docstring (line
     228–233) and `ServiceStartingError`'s (line 99–105), and README line 797–798's *"A run of `starting` lines
     means starts are slower than the hook allows"* gains *"— or, for `starting lock` at the start of a session,
     that another client was still waiting on a start of its own"*.
   - **Or close it where the 10 s comes from.** `lifecycle._spawn_detached` (line 291–314) returns its `Popen`
     — `poll()` coexists with the reaper thread: `_internal_poll` takes `_waitpid_lock` non-blocking, answers
     `None` while `wait()` holds it, and `returncode` once it does not — and `lifecycle._poll_until_reachable`
     raises `ConnectionError` at once on an exit other than `EX_TEMPFAIL`, as `connect._poll_until_reachable`
     does. Then every `lifecycle` client stops waiting out a failed start, `zikaron-mcp`'s own first tool call
     fails in a second rather than twenty, and the lock window the hook can land in shrinks to interpreter
     start. Test: `tests/test_service_lifecycle.py`, a `server_command` of `[sys.executable, "-c", "raise
     SystemExit(3)"]` raising inside well under the poll deadline, and the `EX_TEMPFAIL` exit still polled
     through. Either way `design/architecture.md` §"Start-if-absent" step 4 (*"poll `health()` until a
     deadline"*) should say which clients watch the process and which do not, since it is normative for both.

2. **[IMPROVEMENT] `health()`'s whole-exchange timeout is pinned by nothing; the `surface` half is.** The
   intent names both: *"make the `surface` and `health()` exchanges' timeouts totals rather than per socket
   call"*. `tests/test_hook_rpc.py::test_an_answer_arriving_in_pieces_cannot_outrun_the_deadline` pins
   `surface_once`; for `connect._health` (lines 398–446) the only tests are the three malformed-answer cases in
   `tests/test_hook_connect_edge_cases.py` lines 30–66 and the field parsing at 69–101. The mutation *replace
   both `rpc.time_out_at(sock, answer_by)` with `sock.settimeout(_CONNECT_TIMEOUT_SECONDS)`* — per call, the
   shape round 1 asked to be fixed — passes the suite, and with it the margin the guard in
   `tests/test_install_limits.py` line 2431 computes from `2 * _CONNECT_TIMEOUT_SECONDS` is no longer what a
   dribbling peer can spend. Suggested: a sibling of the `surface_once` test, in `test_hook_connect_edge_cases.py`
   beside `TestHealthRejectsAMalformedResponse` — a `socketpair`, a thread that reads the request and then sends
   one space every 0.05 s for about 1.5 s and closes; `pytest.raises(TimeoutError)` around `_health(client)` and
   `time.monotonic() - started < 2 * connect._CONNECT_TIMEOUT_SECONDS`. The per-call mutation then reads to the
   close and raises `ConnectionError` at ~1.5 s, so the test fails on the exception type as well as the clock,
   and nothing in it can hang.

3. **[NITPICK] Three wordings still carry round 3's predicate — "kept/held the store too long" — after round 4
   changed it to "no sign of life".** `zikaron/hook/push.py` lines 212–213 (`_degrade`'s docstring: *"a start
   that has held the store too long is reported"*); `tests/test_hook_connect_edge_cases.py` lines 140–144 (the
   class docstring: *"has kept the store too long"*) and the test name at line 160
   (`…that_has_kept_the_store_too_long_is_reported`); and `tests/test_service_ownership.py` line 1, whose
   module docstring still says *"one service per store"* where `ownership.py`'s own first line was qualified to
   *"per store within a runtime directory"* in round 2. *"shown no sign of life for too long"* in the first two,
   `…that_has_shown_no_life_too_long_is_reported` for the name, and the qualifier for the last.

4. **[NITPICK] `tests/test_hook_push.py` line 383 still spawns bare `python3`**, where `test_hook_connect.py`
   moved to `_EXITS_AT_ONCE = [sys.executable, "-c", "pass"]` in this change. On a machine with no `python3` on
   `PATH` — the state `CLAUDE.md`'s setup deliberately produces for `python3.<minor>` — `Popen` raises
   `FileNotFoundError`, `run`'s `except Exception` logs `transport`, and the test passes without the poll or
   the child watch ever running, which is the thing its docstring now claims (*"a start that failed is a fault,
   not `starting`"*). Use `sys.executable`.

5. **[NITPICK] `zikaron/hook/failure.py` lines 10–13 gives the wrong reason for the right conclusion.** *"no
   other process shares this path, so the append below needs no cross-process locking"* — two sessions on one
   store run two hooks, and the tripwire writes here too, so the path is shared; the append is safe for the
   reason §Paths now states for `service.log` (`O_APPEND`, one `write()` per line), which `record_failure`
   already does. *"shared only by other hooks, each appending one line in one `write()` on an `O_APPEND`
   descriptor, so no cross-process locking is needed (`architecture.md` §Paths)"*.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-10-11

**Summary judgment.** Round 5's two improvements are answered the stronger way each time: every `lifecycle`
client's poll now watches the process it spawned and raises `StartFailedError` on any exit but 75, so a
failed start releases `<sock>.lock` at once for the hook queued on it, `zikaron init` tells an exited start
from a slow one by the exception's type, and the design states that bound where the three rules are; and
`connect._health` is pinned as a whole-exchange timeout by a dribbling peer that fails the per-call mutation
on exception type as well as the clock. I re-traced the mechanism against the code — the split budget and
its 4.5 s cap, `NotSentError`, `starting` with its detail, both child watches with the 75 exception, the lock
wait ending at the deadline, the hold from before the store opens to after it closes, step-down as
`shut_down`'s first act, the stamp from every poll that does not stop against the 60 s bound, `socket_lost`
leaving a foreign file alone — and found no state in which a serving or cleanly stopping service alarms, and
none in which a failed start reads as a start for longer than another client's own poll. What remains is
narrower than any earlier round: one bound the intent names and no test pins, and three wordings.

### Findings

1. **[IMPROVEMENT] The deadline exit of `lifecycle._poll_until_reachable` — now the only bound on a
   `lifecycle` client's wait once its child is alive — is exercised by no test, and it is the line the
   `exited`/slow distinction this round added rests on.** `zikaron/service/lifecycle.py` line 500, `raise
   ConnectionError(...)` after `while time.monotonic() < deadline`, is uncovered (the coordinator's correction
   says so, and I confirmed nothing drives it: every `pytest.raises(ConnectionError)` in the suite is a
   framing or send-loop case, and `tests/test_project_scope.py` lines 519, 544 and 571 reach
   `initialize._what_to_try`'s three non-exited wordings by monkeypatching `connected` to raise a plain
   `ConnectionError` — so `exited=False` is pinned at the consumer and unpinned at its only producer). The
   mutation *restructure the loop as `while True:` with the child-exit check as its only exit* passes the
   suite — `test_a_spawn_that_fails_ends_start_if_absent_at_once` and
   `test_a_child_that_defers_to_another_service_keeps_the_poll_going` both end by the child or by a late
   bind — and under it a child that neither answers nor exits (the 5 s-delayed server
   `test_hook_connect_integration.py` already uses, or a real service stuck in a model fetch) holds
   `zikaron-mcp`'s first tool call, the warm helper and `zikaron init` forever, with `<sock>.lock` held for
   as long, which is the exact state rule 1's *"it bounds the `lock` wait too"* says cannot occur. The hook's
   own two bounds have their tests (`test_a_lock_held_past_the_deadline_is_a_start_still_running`,
   `test_a_spawn_still_starting_at_the_deadline_is_service_starting_error`); this is the same property for the
   other three clients. Suggested, in `tests/test_service_lifecycle.py` beside
   `test_a_child_that_defers_to_another_service_keeps_the_poll_going`, unit tier, under a second:
   ```python
   def test_a_child_still_alive_at_the_deadline_ends_the_poll_as_a_plain_connection_error(
       socket_dir: Path, monkeypatch: pytest.MonkeyPatch
   ) -> None:
       """The bound on a start that neither answers nor exits — what `zikaron init` reads as "may
       still be starting" and `zikaron-mcp` as a transport failure — told from a start that failed by
       the exception's type, so a bare retry is offered for the first and refused for the second."""
       monkeypatch.setattr(lifecycle, "_HEALTH_POLL_DEADLINE_SECONDS", 0.3)
       alive = unittest.mock.create_autospec(subprocess.Popen, instance=True)
       alive.poll.return_value = None
       started = time.monotonic()
       with pytest.raises(ConnectionError) as raised:
           lifecycle._poll_until_reachable(socket_dir / "test.sock", child=alive)
       assert not isinstance(raised.value, lifecycle.StartFailedError)
       assert time.monotonic() - started < 2.0
   ```
   It fails the `while True` mutation by hanging the gate to its `timeout`, fails a deadline raise of
   `StartFailedError` on the type check, and fails a deadline that ignores the constant on the clock. Run
   the first mutation once rather than describing it, per `CLAUDE.md` §"Sweep the class".

2. **[NITPICK] `design/architecture.md` lines 858–859** — *"**on the self-stop and signal paths** the unlink
   comes *before* the close"* — now has a self-stop path with no unlink at all: `socket_lost` leaves the path
   alone (`lifecycle.py` lines 139–141, and the new paragraph at lines 925–934 says so). Read in order, the
   earlier sentence has the service unlinking a file it has just decided is not its own. *"on the idle and
   `store_replaced` self-stop paths and the signal path the unlink comes before the close — `socket_lost`
   unlinks nothing, below"*.

3. **[NITPICK] `FINDINGS.md` §"Current state", the "What is built" bullet** names the split deadline, the
   `health()` fields, the ownership lock, `socket_lost`, the lock wait and the two timed exchanges, and not
   the two things the last round added: every `lifecycle` client's poll ends when its child exits
   (`lifecycle.StartFailedError`), and `zikaron init` points an exited start at `service.log` rather than
   at a retry. The PR's commit message is written from this block, and both are user-visible — a
   `zikaron-mcp` tool call against a misconfigured store now fails in under a second rather than twenty.
   One clause after *"§"Idle self-stop"."*: *"Every client's poll ends when the process it spawned exits —
   `StartFailedError` for `zikaron-mcp`, the warm helper and `zikaron init`, which points such a start at
   `service.log` instead of a bare retry."*

4. **[NITPICK] `zikaron/service/ownership.py` lines 24–26** — *"which the push hook's poll reads as another
   service serving or starting the store, and keeps polling for"* — names the one client that normally does
   **not** live to see the 75 (`connect.py` lines 63–66 says why), and not the three `lifecycle` clients
   whose 10 s poll usually does. *"which every spawning client's poll — `lifecycle` and `hook/connect`
   alike — reads as another service serving or starting the store, and keeps polling for"*.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-10-11

**Summary judgment.** Round 6's four findings are applied as asked, and I checked each against the tree:
the deadline exit of `lifecycle._poll_until_reachable` has its test and the test fails the two mutations
the brief reports; §"Idle self-stop" excepts `socket_lost` from the unlink-before-close ordering wherever
that ordering is stated, in the design and in the three code comments that restate it; `FINDINGS.md`
names `StartFailedError` and `zikaron init`'s changed advice; `ownership.py` names both polls. I re-traced
the whole mechanism once more against the code rather than the brief — the split budget and its 4.5 s cap,
`NotSentError`, `starting` with its detail, both child watches with the 75 exception, the lock wait ending
at the deadline, both exchanges timed whole, the hold from before the store opens to after it closes with
step-down as `shut_down`'s first act and the stamp from every poll that does not stop, `socket_lost`
leaving a foreign file alone, `zikaron-mcp`'s outer retry not re-spawning a start that exited (the
`StartFailedError` rises from `_connected_socket()` outside the loop's `try`) — and found no state in which a
serving or cleanly stopping service alarms, none in which a failed start reads as a start past another
client's own poll, and no claim in `design/`, `README.md` or `FINDINGS.md` that the code falsifies. What
remains is narrower than any earlier round: one principle this change introduced and applies on one of
its three unlink paths, one design sentence the same change deleted while adding the paragraph that
depends on it, and three nitpicks. No blocker.

### Findings

1. **[IMPROVEMENT] "No longer this process's to remove" is decided on the idle poll's path and on no
   other.** `lifecycle.idle_self_stop` lines 139–141 skip the unlink on `socket_lost`, and §"Idle
   self-stop" lines 931–932 state the principle — *"leaves whatever now sits at the path alone, since it is
   no longer its own"*. Four other exits unlink the path unconditionally with no look at the inode:
   `stop_on_encoder_failure` (`lifecycle.py` line 207), the signal path (`main.py` line 326), the
   `except BaseException` retry (line 426) and `_force_exit_after_failed_graceful_shutdown` (line 563). So a
   socket lost and replaced, followed within one poll interval by a `SIGTERM`, a failed deferred load or a
   shutdown that overruns its deadline, removes the file the design says is not this process's. Beside it,
   the inode the poll compares against is read on the task's first scheduling (`lifecycle.py` line 119,
   `bound_socket_inode = sock_path.stat().st_ino`), not at the bind: a socket removed in the tick between
   `serve` returning and that line raises `FileNotFoundError` out of the task, which
   `_raise_if_any_task_genuinely_failed` re-raises, so that one case crashes the service instead of
   stopping it `socket_lost`. Both windows are a poll interval or a loop tick wide, the directory is
   `0700`, and nothing a client does can reach them — so this is coherence, not exposure, and the author may
   judge the code fix out of proportion. One change closes both: capture the inode in
   `main._open_and_serve` immediately after `serve` returns, with no `await` between (the argument
   `Store.opened_inode` already makes for the store), pass it to `idle_self_stop` as `bound_socket_inode=`
   and to `stop_on_encoder_failure` and `_force_exit_after_failed_graceful_shutdown`, and give every unlink
   site one helper, `lifecycle.unlink_if_still_bound(sock_path, inode)` — a `stat`, an inode compare, then
   `unlink(missing_ok=True)` — so the four paths and the poll decide the same way. Test: the existing
   `…_taken_from_it_stops_and_leaves_the_path_alone` for the poll, plus one for the signal path in
   `tests/test_service_main.py` — plant a foreign file at the path after the bind, deliver `SIGTERM`, assert
   the file survives. **The prose-only alternative**, if the code change is declined: §"Idle self-stop"
   line 932, after *"since it is no longer its own"*, add *"— on this stop; the signal, encoder-failure and
   forced-exit paths still unlink the path unconditionally, since each predates the orphan case and lands
   within one poll of it"*, and `main.run`'s docstring (line 229–232) says the same of the signal path.
   Either is sufficient; the design must not state a principle the code applies once.

2. **[IMPROVEMENT] `design/architecture.md` line 1033–1034 deleted "a second service" from the
   `BEGIN IMMEDIATE` rationale, and the same change added the paragraph that depends on it.** The sentence
   now reads *"Another connection can be another process — the detached indexer's build row, an operator's
   shell — so no in-process lock closes it; `IMMEDIATE` does"*. Line 711–714, new in this change, admits
   exactly the case removed: *"A store reached through two runtime directories … can still be served twice,
   as before; SQLite's own file locking keeps that correct"* — and §"The service's connections" is the one
   place that argues *how* it keeps that correct (a commit from another process between a deferred read
   and its write is refused with `SQLITE_BUSY_SNAPSHOT`, and `IMMEDIATE` takes the write lock first). The
   deletion reads as the author believing the second-service case was gone, which the author's own
   paragraph says it is not; a reader following the cross-reference finds the case missing from the
   argument it is sent to. Restore it qualified: *"— the detached indexer's build row, a second service on
   the same store through another runtime directory (§"Start-if-absent, without a thundering herd"), an
   operator's shell —"*.

3. **[NITPICK] `connect._raise_if_queued_behind_a_stalled_start` (line 391–392) catches
   `ProcessLookupError` from `os.kill(pid, 0)` and nothing else.** `PermissionError` — the pid is alive
   and belongs to another uid, reachable only by pid reuse after a crashed service left its name in the
   file — propagates through `_poll_until_reachable` and `connect_once` to `push.run`'s `except Exception`
   and lands as `transport`, which is the right answer (alive, old, not ours) reached by accident rather
   than by the function's own decision, and the docstring's *"alive"* is then decided somewhere else.
   Add `except PermissionError: pass` beside the `ProcessLookupError` arm so the raise below it is what
   answers; two lines, and a test patching `os.kill` to raise `PermissionError` and asserting
   `HookTransportError` if the author wants it pinned.

4. **[NITPICK] `tests/test_hook_connect_real_service_integration.py` lines 157–194
   (`…does_not_take_it_over`) passes without the ownership lock on a loaded host.** Its two assertions —
   `_read_health_pid(probe) == first_pid` throughout the 3 s watch, and `second.poll() is None` after it —
   both hold whenever the second service's interpreter start, imports and store open take longer than
   `_TAKEOVER_WATCH_SECONDS`, which under the load this host has carried for days they can; the comment at
   line 155–156 sizes the watch against an unloaded bind. The unit-tier
   `test_a_start_that_finds_its_store_held_opens_nothing_and_says_why` is the strong test of the mechanism,
   so this is about one integration test being green for the wrong reason rather than a gap. A
   machine-independent assertion to add at the end of the watch:
   `paths.service_lock_path(sock_path).read_text(encoding="ascii") == f"{first_pid}\n"` — without the lock
   no such file exists, and with one the second start failed to take, it still names the first.

5. **[NITPICK] Two docstrings outside the diff describe the `lifecycle` poll as ending only at its
   deadline.** `zikaron/knowledge/client.py` lines 117–119: *"The poll deadline is
   `lifecycle._HEALTH_POLL_DEADLINE_SECONDS`; past it this client gives up while the service keeps
   starting"* — now also *"or at once when the start exits, which `init` reports as such"*;
   `zikaron/hook/warm_helper.py` lines 35–40: *"`health()` polling to a deadline … exactly the budget this
   helper inherits"* — now also ends when the spawned service exits, which is what shortens the lock window
   a push can land in at session start (round 5, finding 1). Neither file is in the diff; both state the
   claim the diff changed, and `initialize.py`'s module docstring was updated for the same reason.

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-10-11

**Summary judgment.** Round 7's five findings are applied, and the first was taken the stronger way: the
inode is read inside `serve` itself, synchronously after `start_unix_server` returns, so there is no
`await` between the bind and the capture; `RunningServer.socket_inode` is a required field; every one of
the five unlink sites — the idle poll, `stop_on_encoder_failure`, the signal path, the `except
BaseException` retry and `_force_exit_after_failed_graceful_shutdown` — goes through
`lifecycle.unlink_if_still_bound`; `idle_self_stop` no longer `stat`s at task start and `socket_lost` no
longer special-cases the unlink; and §"Idle self-stop", the `cleanup_socket` paragraph, `main.run`'s
docstring, `server.serve`'s comment and `asyncio_compat.py` all state the one rule in the same words. The
`BEGIN IMMEDIATE` rationale names the second service through another runtime directory again; the
`PermissionError` arm is there with its test; the takeover test asserts the lock file's content; both
docstrings outside the diff are updated. I re-traced the whole mechanism once more against the code —
the split budget and its 4.5 s cap, `NotSentError`, `starting` with its detail, both child watches with
the 75 exception, the lock wait ending at the deadline, both exchanges timed whole, the hold from before
the store opens to after it closes, step-down as `shut_down`'s first act, the stamp from every poll that
does not stop against the 60 s bound, `socket_lost` leaving a foreign file alone — and found no state in
which a serving or cleanly stopping service alarms, none in which a failed start reads as a start past
another client's own poll, and no claim in `design/`, `README.md` or `FINDINGS.md` that the code
falsifies. What remains is one test-strength gap on a property the design names by path, and two
nitpicks. No blocker.

### Findings

1. **[IMPROVEMENT] Two of the five unlink sites are pinned only for "removes its own socket", not for
   "leaves another's alone" — and one of them is the path the design names.** `design/architecture.md`
   lines 933–935: *"leaves whatever now sits at the path alone … as every other stop does too, the
   signal, encoder-failure and forced-exit paths included (`lifecycle.unlink_if_still_bound`)"*. The
   brief's mutation list covers the helper, the signal path and the encoder-failure path. The mutation
   *replace `lifecycle.unlink_if_still_bound(sock_path, socket_inode=…)` with
   `sock_path.unlink(missing_ok=True)`* at `zikaron/service/main.py` line 575
   (`_force_exit_after_failed_graceful_shutdown`) passes the suite:
   `tests/test_service_main.py::test_a_shutdown_timeout_forces_process_exit_from_inside_the_running_coroutine`
   asserts only `not sock_path.exists()` (line 864), and on its path the signal branch's own
   `unlink_if_still_bound` has already removed the socket before `shut_down` raises, so the forced-exit
   site's call is a no-op either way. The same mutation at line 434 (the `except BaseException` retry)
   passes too: `test_a_setup_failure_after_binding_closes_the_listener_and_unlinks_the_socket` asserts
   the same thing (line 100). Both tests are right to keep what they assert — the listener's own socket
   must go — so the fix is a sibling for each, planting the foreign file inside the hook each test
   already monkeypatches:
   - For the forced-exit path, in a sibling of the shutdown-timeout test, `_shut_down_always_times_out`
     becomes: `sock_path.write_text("someone else's", encoding="ascii")` — the signal path has already
     unlinked the real socket by the time `shut_down` runs, so the path is free — then `raise
     ShutdownTimeoutError(...)`; after `await main.run(...)`, assert `sock_path.read_text(encoding="ascii")
     == "someone else's"`. Under the mutation `_force_exit` removes the file and `read_text` raises.
   - For the retry path, in a sibling of the setup-failure test, `_task_creation_always_fails` becomes:
     `sock_path.unlink(); sock_path.write_text("someone else's", encoding="ascii")`, then `raise
     RuntimeError(...)`; after the `pytest.raises`, assert the same. Under the mutation the file is gone.
   Run both mutations once rather than describing them, per `CLAUDE.md` §"Sweep the class". With these
   two, every path the design sentence names has a test that fails if that path stops deciding the way
   the helper does.

2. **[NITPICK] `README.md` line 747 says the socket sits in the runtime directory "with its lock
   file", singular.** There are now two beside it — `<h>.sock.lock`, which clients take while they start
   the service, and `<h>.sock.service`, which the service holds while it has the store open — and the
   runtime directory is the one place a user listing it would meet the new file with nothing in the
   README naming it, while `design/architecture.md`'s filesystem table (line 639) does. *"which with
   its two lock files — one clients take while they start it, one the service holds while it has the
   store open — sits in …"*.

3. **[NITPICK] The `zikaron.service` handler leak the brief records as owed is widened by this change,
   in a file the diff already edits, and the brief's own operator line says to fix owed work found on
   the way.** `log.configure_service_log` (`zikaron/service/log.py` lines 35–39) adds a `FileHandler`
   on every call and nothing in `tests/test_service_main.py` removes one; this change adds three more
   `main.run` callers to that file (`test_a_start_that_finds_its_store_held_opens_nothing_and_says_why`,
   `test_the_store_this_run_holds_is_renewed_while_it_polls_and_let_go_at_shut_down`,
   `test_a_signal_leaves_a_socket_path_that_is_no_longer_its_own`), each leaving a handler on the
   logger that points at a deleted `tmp_path`. The brief lists the item as intentionally deferred
   pending the operator, so this is recorded for the operator's decision rather than re-lodged; the
   fix `FINDINGS.md` proposes is the whole of it, and it is an autouse fixture at the top of the file:
   ```python
   @pytest.fixture(autouse=True)
   def _service_log_handlers_do_not_outlive_the_test() -> Iterator[None]:
       logger = logging.getLogger("zikaron.service")
       before = list(logger.handlers)
       yield
       for handler in logger.handlers:
           if handler not in before:
               logger.removeHandler(handler)
               handler.close()
   ```
   `tests/test_service_diagnostics.py`'s two thread-dump tests, run after this file, are what it fixes.

Neither nitpick bears on the verdict; finding 1 does, on the same standard rounds 4 and 6 applied — a
property the design states by name with no test that fails when one of its named paths stops holding it.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-10-11

**Summary judgment.** Round 8's three findings are applied as asked, and I checked each against the tree
rather than the brief: `test_a_forced_exit_leaves_a_socket_path_that_is_no_longer_its_own` plants the
foreign file inside the mocked `shut_down`, after the signal path has already removed the real socket, so
the forced-exit site's `unlink_if_still_bound` is the only thing that could remove it;
`test_a_setup_failure_leaves_a_socket_path_that_is_no_longer_its_own` does the same inside the mocked
`_self_stopping_tasks`, so the `except BaseException` retry's site is the one under test; `README.md`
names both lock files and what each is for; the autouse fixture in `tests/test_service_main.py` is
sufficient where it is, since the only other in-process callers — `tests/test_service_log.py`, which
removes and closes its own handler, and `tests/test_service_diagnostics.py`, which stubs
`configure_service_log` to a no-op — leave nothing on the logger. I re-traced the whole mechanism once
more against the code: the split budget and its 4.5 s cap, `NotSentError`, `starting` with its detail,
both child watches with the 75 exception, the lock wait ending at the deadline, both exchanges timed
whole, the hold from before the store opens to after it closes with step-down as `shut_down`'s first act
and the stamp from every poll that does not stop, `socket_lost` leaving a foreign file alone, every
unlink site through one helper, and `lifecycle`'s deadline exit with its test — and found no state in
which a serving or cleanly stopping service alarms, none in which a failed start reads as a start past
another client's own poll, and no claim in `design/`, `README.md` or `FINDINGS.md` that the code
falsifies. The stalled-start predicate is pinned on every branch (`TestAPushQueuedBehindAStalledStartIsNotAStart`:
old and alive, alive under another uid, young, this push's child, stepping down, gone); the young-loading
budget is pinned as the `deadline_at_ms` sent; the margin guard asserts what the margin must cover. What
remains is two wordings, both trivial.

### Findings

1. **[NITPICK] §"Idle self-stop" cites itself twice.** `design/architecture.md` lines 852–853 (*"while the
   path still names the socket this process bound (§"Idle self-stop")"*) and 861–863 (*"so none of them
   removes what is no longer this process's (§"Idle self-stop")"*) are both inside §"Idle self-stop", so
   the pointer sends a reader to the section they are in. Both sentences are new in this change. Replace
   each parenthetical with *"(the `socket_lost` paragraph below)"*, or drop it — the paragraph at lines
   928–939 is the one they mean.

2. **[NITPICK] "Bounded by its shutdown deadline" is one step short of true.** `zikaron/service/ownership.py`
   lines 29–31: *"A holder that is shutting down lets go once it has closed its store, which its own shutdown
   deadline bounds"*; `tests/test_service_ownership.py` lines 114–115: *"lets go after its shutdown deadline
   at the latest"*. `_SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS` bounds `RunningServer.shut_down`; the store close
   in `main._open_and_serve`'s outer `finally` runs after it, outside that deadline, and the hold is released
   only after that close (`holding_the_store`'s `finally`). In practice the close is milliseconds and the 10 s
   wait is sized correctly, so nothing in the code moves; the sentences should say what is bounded:
   *"…lets go once it has closed its store — its `shut_down` is bounded by its own deadline, and the close
   after it is short"*, and in the test *"lets go shortly after its shutdown deadline — the store close that
   follows is not under it"*. The guard's assertion (`PREDECESSOR_WAIT_SECONDS >
   _SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS`) stays as it is.

Neither bears on the verdict. The intent's every clause has its mechanism, its design sentence and a test
that fails when the mechanism stops holding, and the prose the change touches says what the code does.

VERDICT: APPROVED
