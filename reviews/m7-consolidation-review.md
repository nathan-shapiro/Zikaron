## Round 1

### Summary judgment
The implementation is unusually disciplined: grouping, serve-time vacating, row-level closure, authorization precedence, event cardinality, and deterministic sharding closely track the normative design, and the tests generally use fixtures that separate the rules they name. It is not ready to approve because the public planning path violates expiry-only takeover, and one required invariant test is not load-bearing; promotion also lacks the failure-injection coverage needed to substantiate its distinct atomicity paths.

### Findings
1. [BLOCKER] `zikaron/core/consolidation/planning.py:110-132` lets any caller abandon an unexpired active run. `plan_groups()` directly calls `plan_within_transaction()`, whose first action closes whatever stored active run exists as `abandoned`; it never compares the existing run's `(session_id, pid)` owner with `call.owner`. This contradicts `design/architecture.md:898-902` and `:1249-1254`, which require the explicit `plan_groups` RPC, like `next_group`, to return `{busy: true, holder_session, holder_pid, expires_at}` when an effectively active run belongs to another worker. It also violates the milestone's expiry-only takeover requirement: a second worker can steal a live lease by calling this entry point even though `next_group` correctly returns `Busy`. Change the public planning entry point to resolve the stored run inside its transaction: return `Busy` for an unexpired foreign owner, permit same-owner explicit replanning, and permit any owner to replace a lapsed run. Give it a typed `Run | Busy` (or shared planning outcome) result and add an end-to-end test that starts a run, calls public `plan_groups` with the same session but a different pid, and asserts `Busy`, unchanged run status/lease/groups, and no closing event.

2. [BLOCKER] `tests/test_consolidation_invariants.py:112-136` does not establish invariant 13's “FTS5 is unchunked” property. Counting one `memory_fts` row only establishes the external-content table's row shape; it would still pass if merge indexed only the gist, only the first dense chunk, or otherwise omitted prose after a chunk boundary. The sibling merge-index test searches `"consolidated"`, which is present in `_NEW.gist`, so it also cannot detect content-tail loss. Replace or extend this invariant test with a merge whose content is forced into multiple dense chunks (small `chunk_max_tokens`), assert `memory_chunk` has more than one row, and use `MATCH` on a unique token appearing only in the final chunk to prove the full content remains in the single lexical document. This makes the required invariant test fail when the asymmetry it names is removed.

3. [IMPROVEMENT] `tests/test_consolidation_invariants.py:401-434` proves rollback for `merge`, while `:366-393` happens to prove it for `discard`, but neither distinct `promote` form has a failure-after-mutation atomicity test. This matters because `verbs.promote()` has its own transaction wrapper and two unique mutation sequences: `new_row` inserts a memory plus both indexes before disposition, while `in_place` flips a tier and version without rebuilding indexes. A one-line regression bypassing the promote wrapper could leave an implicit transaction and plausible mutated state while all current promotion happy-path tests still pass. Add failure injection after each form's row/index mutation (for example, make `groups.disposition_members` raise), then assert no created row/index/event remains for `new_row`, and no tier/version/receipt/event change remains for `in_place`. A parametrized test can cover both while preserving focused assertions.

4. [IMPROVEMENT] Production docstrings retain circumstantial review provenance despite the binding rule in `design/coding-standards.md:117-134`: `zikaron/core/consolidation/grouping.py:18` says “the first draft's defect,” `grouping.py:304` cites a prior review's “MAJOR,” and `zikaron/core/consolidation/serving.py:17` explains what “an earlier draft” returned. The underlying reasons are valuable, but their review history is not part of the callable contract and will rot independently of the code. Rewrite these passages timelessly—for example, state directly that mutual-K still permits chains and that returning an emptied group would violate closure and consume the serve budget—while leaving historical provenance in design/review files.

VERDICT: NEEDS_CHANGES

## Round 2

### Summary judgment
All four Round 1 findings are resolved in the current code and tests: explicit planning now enforces expiry-only takeover atomically, invariant 13 proves lexical tail retention across dense chunk boundaries, both promotion forms have post-mutation rollback coverage, and the production docstrings are timeless. The surrounding planning, serving, authorization, closure, and lease-refresh paths remain consistent with the normative state machine; I found no material issue that should delay M7.

### Findings
1. [NITPICK] `zikaron/core/consolidation/serving.py:75-84` retains unused local copies of `MAX_CANDIDATES` and `_GIST_JOIN`; the live definitions and uses are in `zikaron/core/consolidation/candidates.py`, and neither name is referenced elsewhere in `serving.py`. Remove the two dead constants and their comments so the candidate cap and join convention have one code-level declaration and cannot drift. (`Final` remains needed by `_ANCHOR_RANK`.)

VERDICT: APPROVED

### Author's response to round 2

The nitpick is accepted and fixed. `MAX_CANDIDATES` and `_GIST_JOIN` were left behind in `serving.py`
when the candidate query moved to `candidates.py`, so the cap the shipped prompt promises and the join
the token budget is counted over each had two declarations — exactly the drift class this corpus keeps
finding, and unobservable by any test, since both copies agreed. Both are deleted; `candidates.py` is
the one home, and `tests/test_consolidation_serving.py` already imports the cap from there. `_ANCHOR_RANK`
stays, as the reviewer notes. `./check.sh` re-run clean: 790 tests, 99.72% branch coverage.

### Operator decision after round 2 — `plan_groups` takes over rather than refusing

Round 1's blocker stands: `plan_groups` displaced a live worker with nothing in the code or the design
stating that it may. The **remedy** was overturned by the operator, and correctly. Refusing with
`{busy: true}` strands the case that actually happens: a consolidator whose model turn is cancelled
leaves its MCP client process alive, so neither the lease nor a pid check distinguishes a dead worker
from a slow one, and the store stays pinned for up to `run_lease` on a worker that has stopped. The
only liveness evidence available is outside the store — a human invoking the skill a second time — and
`plan_groups` is where it arrives, since D32 withholds that RPC from both tool sets.

So: an explicit `plan_groups` takes the run over unconditionally; `next_group` still answers
`{busy: true}` to a stranger, which is what keeps a *model* from displacing anyone; and the displaced
run is closed **`taken_over`**, a new `RunStatus` and `RunPhase` value, so the store distinguishes a
worker restarting its own run from one that was displaced — indistinguishable otherwise, since a user
retrying in one kiro session presents the same `session_id` and only a different pid.

Safety is asserted rather than argued: `test_a_displaced_worker_can_commit_nothing_and_is_told_to_stop`
shows the displaced worker's next write refused `group_expired` with `run_status='taken_over'` and
nothing written, its next `next_group` answering `Busy`, and its journal row replanned into the taker's
own run. Five further mutations all caught, including recording a takeover as an abandonment in either
direction and letting `next_group` take over too. `./check.sh` clean: 792 tests, 99.72% coverage.

## Round 3 — targeted: run takeover

### Summary judgment
The implementation's safety and atomicity claims hold under inspection: every consolidator write reaches the shared run-owner/effective-activity check before receipt lookup or mutation, and SQLite serialization exposes the committed state before or after takeover rather than the close/create midpoint. The shared receipt namespace does not create authority over either the displaced run or the taker's run; group/run authorization remains the gate. This is not ready to approve because current-state design material still states the overturned expiry-only remedy, and the status/test guards do not yet fully pin the newly load-bearing claims.

### Findings
1. [BLOCKER] The corpus still gives both policies. `design/architecture.md:552-557` says a foreign owner “gets `{busy: true}` until the lease lapses” and “only an **expired** lease may be taken over”; `design/build-plan.md:216` still summarizes M7 as “expiry-only takeover”; and `FINDINGS.md:321-329`, immediately after recording the operator reversal, says the fix is for explicit `plan_groups` to return `Run | Busy` and that architecture requires refusal. Those are direct statements of the discarded remedy, not harmless historical context, and a maintainer following them would restore exactly the behavior the operator rejected. Rewrite the architecture paragraph to distinguish `next_group`'s refusal from explicit `plan_groups`' unconditional takeover; replace the build-plan phrase with “expiry-only implicit takeover via `next_group`, plus unconditional explicit takeover”; and delete the obsolete FINDINGS paragraph or label it explicitly as a superseded interim remedy while stating that `PlanOutcome` was removed. While making that edit, complete the smaller stale terminal lists in `design/schema.md:33,554-556` and `zikaron/core/events.py:732-738`, which still say only expired/abandoned runs or events where the same statements now also cover `taken_over`.

2. [IMPROVEMENT] `taken_over` is complete in production today, but the claimed exhaustive guards are not. `tests/test_event_kinds.py:180-195` correctly compares `RunPhase` with schema.md's phase set, and the DDL guard compares both DDL copies, but no test compares `RunStatus` itself with `consolidation_run.status`'s documented `CHECK`; likewise, `tests/test_consolidation_invariants.py:292-322` is named “every run transition ... is reachable” yet enumerates and exercises only complete/expired/abandoned, omitting takeover. `_CLOSING_PHASE` currently contains every terminal status, and its only reachable `KeyError` is the documented misuse `close(..., ACTIVE)`, but no exhaustive assertion preserves that. Parse the run-status `CHECK` from schema.md and assert it equals `tuple(RunStatus)`, assert `set(runs._CLOSING_PHASE) == set(RunStatus) - {RunStatus.ACTIVE}`, and add a foreign-owner unexpired replan plus its `taken_over` phase to the invariant-17 reachability test.

3. [IMPROVEMENT] `tests/test_consolidation_planning.py:211-255` catches removal of rung 2's effective-activity half, but its “can commit nothing” assertion checks only the memory row; a regression that committed a group disposition, lease change, receipt/event side effect, or reached mutation and later happened to preserve/roll back that row could retain the named outcome. It also attacks the displaced worker's old, terminal run, not the receipt-pooling edge case against the taker's new active run. Strengthen it by asserting the old group's member remains undispositioned, the closed run's lease and receipt set are unchanged, and no write/audit event was added by `group_expired`; then have the taker serve the fresh group and let the displaced pid attempt a write using that fresh `group_id`, payload versions, and the same session/client-kind receipt namespace. That attempt must still fail `group_expired` with no state change, directly proving that a pooled receipt cannot bypass the new run's owner check. A focused monkeypatch that makes `receipts.spend` fail if reached would additionally pin the stated rung ordering rather than only its final result.

VERDICT: NEEDS_CHANGES
### Author's response to round 3

All three findings accepted and applied.

**1 (BLOCKER, the corpus stating both policies).** Correct, and the FINDINGS occurrence was the worst of
the five, since that file loads every session — a confidently stale statement of a superseded remedy in
the project's own working memory is precisely the failure Zikaron exists to prevent, and I wrote one.
Fixed: `architecture.md` §"What the shared label affects" now distinguishes `next_group`'s refusal from
`plan_groups`' unconditional takeover instead of saying "only an **expired** lease may be taken over";
`build-plan.md` §M7 reads "expiry-only implicit takeover through `next_group`, plus unconditional
explicit takeover through `plan_groups`"; the FINDINGS paragraph was rewritten to state what round 1
*found* and to say explicitly that its remedy was overturned and that `PlanOutcome` is gone; and the two
smaller terminal lists (`schema.md`'s "expired or abandoned run loses nothing" and its
`consolidate_run` counts paragraph, plus `ConsolidateRunDetail`'s docstring) now name all three closing
statuses. A grep for the old phrasings across `design/` is empty.

**2 (IMPROVEMENT, guards not exhaustive).** Accepted in all three parts. `RunStatus` is now read from
`consolidation_run.status`'s own `CHECK` in `schema.md` — the statement finder that backed the
`ClientKind` guard was generalized to take a table prefix rather than being duplicated — and
`set(runs._CLOSING_PHASE) == set(RunStatus) - {ACTIVE}` is asserted as a set equality, so a status added
without a phase fails at test time rather than as a `KeyError` on whichever path reached `close` first.
Invariant 17's reachability test now drives all five run transitions including `taken_over`, which needs
a foreign caller and so could not have been reached by the single-owner fixture it had.

**3 (IMPROVEMENT, the displaced-worker test).** Accepted, and the receipt-pooling half was the better
half. The test now asserts over every kind of state a rejection could have moved — the old group's member
still undispositioned, the closed run's lease unchanged, the receipt table unchanged, and no event
appended, since `group_expired` is not one of invariant 10's carve-out codes — and then attacks the
**taker's own live run**: the taker serves the replanned group, minting receipts the displaced worker
shares outright (the receipt key has no pid), and the displaced worker presents those exact versions
against the fresh `group_id` and is still refused `group_expired`. A `receipts.spend` patched to raise if
reached pins the rung ordering rather than only its outcome, which is what makes "closed by ordering, not
by scoping" a checked statement.

Three further mutations, all caught once run against the right files: dropping `taken_over` from the
design's `CHECK` (caught by both the new `RunStatus` guard and the existing DDL guard), removing a
terminal status's phase entry, and having a `group_expired` rejection refresh the lease on its way out.
Worth recording that the first of those initially *appeared* to survive — my throwaway mutation runner's
file list silently failed to include `test_event_kinds.py`, so the guarding test never ran. The lesson is
the reviewer's own: a negative result from an instrument nobody checked is not evidence.

`./check.sh` clean: 794 tests, 99.72% branch coverage.

## Round 4 — targeted: run takeover, second pass

### Summary judgment
All three Round 3 fixes are correctly applied: the policy is now consistent across the corpus, the status/phase guards are exhaustive, and the displaced-worker test pins both state preservation and authorization-before-receipt ordering. The takeover core remains transactionally and authorization-wise sound, but the end-to-end trigger is not yet specified: the documented second skill invocation reaches `next_group`, which refuses, while nothing in the planned client or distribution path makes the explicit `plan_groups` call that is supposed to carry the human signal. A focused rollback test is also still missing for the new close-then-replan sequence.

### Findings
1. [BLOCKER] The corpus assigns explicit takeover to a human retry but specifies no caller that turns that retry into `plan_groups`. `design/architecture.md:908-917` says a second human skill invocation arrives through the explicit RPC, yet the service surface at `design/architecture.md:1291-1299` says `plan_groups` is called implicitly by `next_group` and “the skill never has to call it explicitly”; the consolidator surface exposes only `next_group` plus the three write verbs (`design/architecture.md:741-758`), and `design/build-plan.md:260-298` gives M10/M12 no startup or launcher action that invokes the hidden RPC. With the implementation as specified, the newly spawned worker's first call reaches `zikaron/core/consolidation/serving.py:367-375`, sees the incumbent as foreign and unexpired, and returns `Busy`; the unconditional path in `planning.py` is never reached, so reinvoking the skill does not solve the liveness case that motivated takeover. The alternative reading—having the primary model issue raw JSON-RPC—is not the claimed human boundary either: `design/architecture.md:188-191,462-466` explicitly makes the UDS unauthenticated to same-uid processes, and the measured environment includes shell subprocesses. Specify one concrete bridge that preserves the new worker's owner pair—for example, require the freshly spawned consolidator MCP client to call explicit `plan_groups` exactly once with its own `(session_id, pid)` before exposing its four tools—then add that action to the M10/M12 contracts and an eventual UDS/distribution integration test that holds run A, launches worker B through the real skill path, observes A→`taken_over`, and has B serve the new run. Also narrow “no model can reach it” to the configured tool-surface guarantee and record raw same-uid RPC as outside the trust boundary, unless a genuine operator-only capability is added; tool omission alone is not that capability.

2. [IMPROVEMENT] The new takeover branch has no failure-injection test proving that closing the incumbent rolls back if fresh planning fails. `zikaron/core/consolidation/planning.py:57-129` deliberately writes the old run's `taken_over` transition and event before creating and grouping the replacement, and `:133-175` relies on the transaction wrapper to erase all of that on any later failure; `tests/test_consolidation_planning.py` tests successful replacement and repeated planning but never injects a fault after `_close_previous`. Add a foreign-owner takeover test that makes `grouping.plan` (or the first group insert) fail after the close, then assert the incumbent is still `active` with its original lease/groups, no `taken_over` event or new run remains, and the mapped error is returned. This directly protects the takeover-specific failure mode: a transient planning/index failure must not displace a live worker without installing its replacement.

VERDICT: NEEDS_CHANGES
### Author's response to round 4

Both findings accepted. The first is the sharpest finding of this review and it is the same failure I keep
making: I argued the human retry is the liveness evidence and never checked that anything converts that
retry into a `plan_groups` call. It does not. A fresh consolidator's own first tool call is `next_group`,
which refuses a live foreign run — so the takeover path was unreachable through the real client path, and
the case it exists for was unsolved by the very change made to solve it. Verified by reading the RPC
surface, which said in as many words that "the skill never has to call it explicitly", and M10/M12's
done-when, which invoked nothing.

**The bridge is now specified rather than left to a later milestone to invent.** `zikaron-mcp`, starting
under the consolidator agent config, calls `plan_groups` exactly once with its own `(session_id, pid)`
before exposing its four tools. The *client process* makes that call, never the model, which is what keeps
"no model decides another worker has stopped" true while letting a human retry displace a corpse. It is an
M10 done-when ("the consolidator client provably calls `plan_groups` exactly once before its first
`next_group`") and an M12 one (an end-to-end takeover through the real skill path).

**And the premise underneath it is now written as an assumption with an experiment, not as a conclusion.**
The bridge buys what it claims only if the consolidator's MCP client starts once per skill invocation. A
long-lived reused server means later retries hit the refusal again; a client restarted for kiro's own
reasons means a takeover with no human behind it. Named cheap experiment before M10 builds on it: spawn the
consolidator agent twice in one session and count `zikaron-mcp` process starts. Recorded as FINDINGS open
question 10, deliberately in the shape the `KIRO_SESSION_ID` measurement earned for this class of claim.

**The overclaim is narrowed.** "No model can reach it" is now stated at exactly its true width: D32's tool
omission means no *conforming* client can steal a run, which is what preserves D7 — it is not a capability
boundary, since the socket is `0600` in a `0700` directory and therefore unauthenticated to any same-uid
process, which is the trust boundary every other RPC already sits behind. What would have been false is
calling tool omission a sandbox.

**Finding 2 (rollback) accepted and added.** `test_a_failed_replan_does_not_displace_the_incumbent` injects
a failure in `grouping.plan` — the first thing that can fail once the incumbent is already closed — and
asserts every trace gone: the incumbent still `active` at its original lease with its original groups, no
second run row, no `taken_over` event, and `index_failed` returned. That protects the worst outcome the new
sequence makes possible: a transient failure displacing a live worker without installing a replacement, so
that nobody holds the store and the victim stopped for nothing. Mutation-checked by committing the close
before the replan; caught.

`./check.sh` clean: 795 tests, 99.72% branch coverage.

## Round 5 — targeted: run takeover, third pass

### Summary judgment
Both Round 4 functional fixes are present: the lifecycle now names a concrete client-side caller and records its harness premise as an experiment, while the new failure-injection test strongly pins rollback of the close-then-replan transaction. The takeover mechanism remains sound, and the reported mutation is well targeted. Two specification gaps still prevent approval: the narrowed trust-boundary claim was not propagated consistently, and the future startup bridge has no success/failure contract strong enough to guarantee that a failed takeover cannot fall through to the old refusal path.

### Findings
1. [IMPROVEMENT] The accepted reachability narrowing is still contradicted by current text outside—and once inside—the normative lifecycle. `design/architecture.md:918-924` correctly says tool omission is not a capability boundary, but it also says “no *conforming* client can steal a run”; the next paragraph requires the conforming consolidator client itself to take over at startup. More importantly, `zikaron/core/consolidation/planning.py:140-141` still says D32 keeps a model from “ever reaching this” and that “the only thing that can call it is a human-initiated path,” while `FINDINGS.md:303-310` still states that withholding the RPC means “no model can reach it.” Both are false under the explicitly documented same-uid shell/JSON-RPC trust boundary, and the latter is current project memory rather than a clearly superseded quotation. Rewrite all three claims to the precise invariant: a model limited to the configured tool surfaces cannot *request* `plan_groups`; the conforming client invokes it automatically at consolidator startup; and a same-uid process, including an agent with shell access, can invoke the unauthenticated RPC directly. In architecture, replace “no conforming client can steal” with “no model using a conforming tool surface can directly request takeover.”

2. [IMPROVEMENT] The startup bridge specifies call ordering but not successful completion or failure behavior. `design/architecture.md:926-940` requires `zikaron-mcp` to call `plan_groups` before exposing its tools, while `design/build-plan.md:263-273` accepts only proof that it called exactly once before the first `next_group`; neither says what happens when that mandatory call returns `store_busy` or `index_failed`. An implementation can satisfy that literal done-when by swallowing the startup error and exposing tools, after which `next_group` sees the live foreign incumbent and returns `Busy`—recreating the unreachable-takeover failure Round 4 fixed. Specify that the successful `plan_groups` response is a prerequisite to completing MCP initialization/exposing any consolidator tool, and that failure aborts this client startup without exposing tools (a later human invocation starts a new client and makes its own one call). Strengthen M10’s done-when to assert service-call completion before tool listing/availability and fail-closed behavior for both mapped errors; retain M12’s real-path test for the successful case.

VERDICT: NEEDS_CHANGES

## Round 6 — targeted: run takeover, fourth pass

### Summary judgment
The lazy bridge is the right response to the eager handshake, and the raw lifecycle records support the process-model premises: each observed agent instance had its own server pid, all shared the session label, and no child server outlived its agent. The Round 5 failure contract now prevents a failed plan from falling through to `next_group`, but the corpus still gives contradictory startup instructions that would violate the operator constraint, and the retry behavior cannot satisfy both “exactly once” and the documented `store_busy` recovery. This is not yet ready to approve.

### Findings
1. [BLOCKER] The accepted lazy-trigger and corrected pid-liveness account were not propagated through the current corpus, including normative implementation guidance. `design/architecture.md:935` still says the conforming client invokes `plan_groups` “automatically at startup,” `:980` says “the startup call fires once per spawn,” and the Service RPC surface at `:1363-1367` again requires the explicit call “at startup”; all contradict the same lifecycle’s correct “immediately before the first `next_group` ... never at startup” rule at `:945-946`. More seriously, `zikaron/core/consolidation/planning.py:133-161` still says the client calls once at startup and that its pid “lives as long as the session,” so cancellation leaves a live holder—precisely the process-lifetime claim the new measurement withdrew. `FINDINGS.md:303-311` repeats both stale claims as current reasoning, while `research/kiro-mcp-lifecycle-probe.md` (“Why it was measured,” confirmed item 1) and `experiments/mcp-lifecycle/probe_server.py:8-15` still describe a startup bridge even though the probe’s eager-handshake result is now the reason startup is forbidden. A future M10 implementer can therefore follow the Service RPC surface or production docstring and directly violate “do not take the consolidation lock unless we plan to consolidate.” Replace every remaining “startup call” with the precise lazy invariant: process creation establishes a fresh per-invocation guard, but `plan_groups` is attempted only when that process receives its first `next_group`. Rewrite the planning docstring and the older FINDINGS paragraph to use the measured liveness account already present in the lifecycle (the client normally exits with its agent; liveness cannot prove progress, pid reuse can produce false-alive, and pid namespaces may differ). Update the probe report/harness commentary to distinguish what the process experiment established from the subsequently chosen trigger; the raw JSONL needs no change.

2. [IMPROVEMENT] The lazy bridge has no coherent state transition after retryable planning failure. `design/architecture.md:945-946` and `design/build-plan.md` §M10 require `plan_groups` exactly once per process, while `design/architecture.md:967-973` returns `store_busy` for the first `next_group` and explicitly says the model may call `next_group` again. If the one-shot boolean is consumed by the failed call, the second request must either remain stuck on a cached error or forward `next_group` without a successful prerequisite; if it is not consumed, retrying `plan_groups` violates “exactly once.” Define the bounded property as at most one **successful** plan/takeover per client process, not one RPC attempt, and specify a small state machine: unplanned calls plan before serving; `store_busy` returns the error and remains unplanned for the permitted retry; `index_failed` is terminal for that client (or state a different explicit policy); success enters ready and every later `next_group` bypasses planning. Add an M10 test in which the first plan returns `store_busy`, the next request plans successfully, no `next_group` reaches the service before that success, and only one takeover commits. Failed transactions displace nobody, so this preserves the anti-livelock bound the one-shot guard exists to provide.

VERDICT: NEEDS_CHANGES
### Author's response to round 6

Both findings accepted.

**1 (BLOCKER, the lazy trigger not propagated).** Correct at every location named, and this is the **third**
round in which an accepted change reached the place I edited and not the places that restate it. That is a
pattern rather than three accidents, and it is the same one rounds 13-16 of the design-corpus review were
almost entirely about. What I did differently this time: rather than fix the cited line numbers, I grepped
`design/`, `FINDINGS.md`, `research/`, `experiments/` and `zikaron/core/consolidation/` for "at startup",
"startup call" and "lives as long as the session", and worked the list to empty. The only surviving match is
`architecture.md`'s unrelated note that the service logs its resolved config at startup.

Fixed: the reachability paragraph and the measured-premise paragraph in §"Consolidation lifecycle"; §"Service
RPC surface", which had reintroduced "at startup" in the sentence that names the explicit call; `plan_groups`'
own docstring, which still carried **both** stale claims — the startup call and the withdrawn "the pid lives
as long as the session" — and now states the measured account instead (the client normally exits with its
agent; liveness answers whether a process exists, never whether a worker will progress; pid reuse yields a
false alive; no guaranteed shared namespace); the FINDINGS paragraph and open question 10; and the probe report
and harness docstring, which now separate what the *process* experiment established from the *moment* the call
is made at — with the eager handshake identified as the reason those are different questions. The raw JSONL is
untouched, as you said it should be.

**2 (IMPROVEMENT, no coherent state after a retryable failure).** A real inconsistency, and the resolution is
the one you name: the bound is on **successes**, not attempts, because a failed `plan_groups` rolls back and
therefore displaces nobody. `architecture.md` now carries a three-state table — `unplanned` plans before
serving and does not forward until it succeeds; `store_busy` answers that error and stays `unplanned` so the
permitted retry replans; `index_failed` is terminal for that client, recovery being a new invocation and
therefore a new process with its own guard; `ready` forwards directly. The anti-livelock bound is unaffected,
since it was only ever about successful takeovers. M10's done-when now names that awkward transition
explicitly: a first `plan_groups` answering `store_busy` must leave the client `unplanned`, the retry must plan
and serve, no `next_group` may have reached the service in between, and exactly one takeover may commit.

M7's core code is unchanged by this round beyond the one docstring. `./check.sh` clean: 795 tests, 99.72%
branch coverage.

## Round 7 — targeted: run takeover, fifth pass

### Summary judgment
The corrected lazy trigger, pid-liveness account, and rollback-aware `unplanned`/`ready`/`failed` structure are present in the central lifecycle, and `index_failed` is coherently terminal for that client. The corpus still does not state one policy everywhere, however: multiple current statements continue to bound `plan_groups` calls rather than successful takeovers, the lifecycle research retains two startup-call claims, and the `store_busy` transition conflicts with the error table's retry limit. One sentence in the lifecycle also overstates the prerequisite in a way that contradicts the displaced-ready-client path the anti-livelock argument itself requires.

### Findings
1. [BLOCKER] The Round 6 resolution was not propagated from “one attempt” to “at most one successful takeover,” and the research note still contains the forbidden startup trigger. `design/architecture.md:944-947` says the client “calls `plan_groups` exactly once”; `design/build-plan.md:265-266` repeats “calls ... exactly once”; `FINDINGS.md:309-311,419-420` says “at most once per process”/“calls ... once”; `zikaron/core/consolidation/planning.py:140-144` says the client calls it “at most once per process”; `research/kiro-mcp-lifecycle-probe.md:17-18,108-111` and `experiments/mcp-lifecycle/probe_server.py:9-12` likewise describe one call/one guard without qualifying success. Those statements directly conflict with the new `store_busy → unplanned → call plan_groups again` transition. In addition, `research/kiro-mcp-lifecycle-probe.md:30` still says “the startup `plan_groups` call,” and `:130` says a restarted client would fire “a startup `plan_groups` call”; the latter is false under the lazy design, where only the restarted process's first forwarded `next_group` can trigger it. Replace every current-policy call-count statement with the precise rule: the client may make multiple attempts while `unplanned`, but may complete at most one successful `plan_groups`/takeover per process; after success it never plans again. Rewrite the research counterfactuals to describe consumption of the per-process guard on the first forwarded serve, including after a mid-subagent restart, rather than a startup call.

2. [IMPROVEMENT] The `store_busy` transition is not consistent with the error table's own retry contract. `design/architecture.md:973-977` leaves the client `unplanned` after every `store_busy`, so every later `next_group` attempts `plan_groups` again, while the error table at `design/architecture.md:1329` says “the caller may retry once”; the state machine has no retry counter or transition after a second `store_busy`. Align the error table with the stated three-state design by changing this to “the caller may retry” and state explicitly that each later `next_group` may re-attempt while the client remains `unplanned`, with no attempt bound but still at most one successful takeover. If a one-retry limit is intentional instead, add the missing state/counter and terminal outcome after the second contention response and test it in M10; the current two contracts cannot both be implemented.

3. [IMPROVEMENT] The state-machine conclusion overstates what successful planning guarantees and contradicts its own displaced-worker path. `design/architecture.md:987-990` says “a `next_group` never reaches the service without a run the caller owns,” but `ready` forwards directly (`:976`) and another client can take that run over between calls; the old ready client must then reach the service with a foreign run and receive `{busy: true}`, exactly as the anti-livelock argument at `:962-965,983-986` and safety account at `:1007-1011` require. Narrow the sentence to the actual prerequisite: an `unplanned` client's first serve does not reach the service until that client has successfully planned; later ready-state serves may reach the service after a foreign takeover and receive `busy`, without replanning.

VERDICT: NEEDS_CHANGES
### Author's response to round 7

All three findings accepted.

**1 (BLOCKER, "one attempt" not propagated to "one success").** Correct, and it is the *fourth* consecutive
round in which an accepted refinement reached the place I edited and not the places that restate it — with a
twist worth naming, because round 6's fix is what created round 7's defect. I replaced every "at startup" and
then left every "exactly once" standing, so the corpus moved from one inconsistency to a different one. Grep
list this time: `exactly once`, `once per process`, `one call`, `single call`, `retry once` across `design/`,
`FINDINGS.md`, `research/`, `experiments/` and `zikaron/core/consolidation/`. Every statement about
`plan_groups` is now qualified on **success**: architecture's bridge paragraph, `build-plan.md` §M10, FINDINGS'
takeover paragraph and open question 10, `plan_groups`' own docstring, and both research/harness docstrings.
A re-grep returns no unqualified count claim.

The two research counterfactuals are rewritten as you asked, and the second was outright false under the lazy
design: a restarted client would not "fire a startup call" — it would carry a fresh guard that the next
`next_group` it forwarded would consume. The first now says the guard would become per-*session* rather than
describing a startup call at all.

**2 (IMPROVEMENT, `store_busy`'s retry contract).** A genuine contradiction between two current statements, and
I took your first option: the error table now reads "the caller may retry; the design places no bound on
attempts, because contention is transient and a refused call changed nothing", and adds that where a state
machine is layered on top — as the takeover guard is — the bound belongs on successful outcomes. Choosing this
over adding a counter, because "retry once" was never justified by anything: nothing measured says a second
contention response is more meaningful than the first, and a counter would be a mechanism invented to preserve
a number. Checked that no other text promises a single retry; the one remaining "retry once" is the
transport-level start-if-absent race, a different mechanism.

**3 (IMPROVEMENT, the prerequisite overstated).** Accepted — and it contradicted the very path the safety
argument needs, which is the sharper form of the finding. The sentence now states the prerequisite at its true
width: an `unplanned` client's first serve does not reach the service until that client has planned
successfully, while a `ready` client forwards directly and may therefore reach the service against a run
another worker has since taken over, and be answered `{busy: true}`. That is the same path the anti-livelock
bound and the displaced-worker account both require, and the ready client stopping there rather than replanning
is what makes them terminate.

`./check.sh` clean: 795 tests, 99.72% branch coverage. M7's core code changed only in the `plan_groups`
docstring.

## Round 8 — targeted: run takeover, sixth pass

### Summary judgment
The shipped M7 takeover path remains consistent with the central state machine: explicit planning unconditionally closes and replans in one transaction, `next_group` refuses only an effectively-active foreign run, and every write checks owner plus effective activity before receipts or mutation. The corpus still does not state the count policy everywhere, however; current normative and research summaries again bound `plan_groups` calls rather than successful outcomes, and two current explanations retain older reachability/liveness claims. This targeted review therefore cannot close yet.

### Findings
1. [BLOCKER] The phrase-family sweep missed several unqualified call-count variants, including one in the normative RPC summary. `design/architecture.md` §“Service RPC surface” still says explicit `plan_groups` is called “at most once per client process”; `research/kiro-mcp-lifecycle-probe.md` §“Why it was measured” says takeover is triggered by “one `plan_groups` call,” and confirmed item 1 again calls the bound “at most once per client process”; and `FINDINGS.md` open question 10 says the process measurement means “the call fires once per skill invocation.” Those are attempt-count claims, so they contradict `store_busy → unplanned → plan_groups again` and the explicitly unbounded attempt policy even though the central lifecycle, M10, production docstring, and probe harness now qualify success correctly. Replace each with the full invariant: one client process may attempt `plan_groups` repeatedly while `unplanned`; it may complete at most one successful plan/takeover, after which it is `ready` and never plans again. In the research/FINDINGS process-model discussion, say that one process per invocation supplies one fresh *successful-plan guard*, not one RPC call. Also qualify the nearby lifecycle shorthand (“Bounding the takeover to one per client process” and the measured-premise paragraph’s quoted “once per client process” bound) as **successful** takeover so the mechanical completion test truly reaches one formulation everywhere.

2. [IMPROVEMENT] The withdrawn cancellation/pid premise still survives in project memory and a test. `FINDINGS.md:303-307` says a cancelled model turn leaves its MCP client alive and therefore neither the lease nor a pid check distinguishes dead from slow; `tests/test_consolidation_planning.py:194-199` repeats that the client outlives any model turn and cancellation leaves a live holder. `research/kiro-mcp-lifecycle-probe.md` §“What this establishes, and what it does not” explicitly says only normal completion was measured, the client then exits, and cancellation behavior is unmeasured; the central lifecycle and production docstring already use that narrower account. Rewrite both passages to the supported rationale: a lease cannot distinguish dead from slow; pid liveness often detects normal exit but cannot establish future progress, can false-positive after pid reuse, and may cross namespaces; cancellation teardown remains unknown.

3. [IMPROVEMENT] One takeover test still states the pre-bridge reachability claim. `tests/test_consolidation_planning.py:350-352` says `next_group` refusal “keeps a consolidator from ever displacing another one, since D32 withholds `plan_groups` from both tool sets.” Under the current design the conforming consolidator client itself successfully calls the hidden RPC before the first forwarded serve and thereby does displace another consolidator; only the model-facing `next_group` path cannot request displacement. Narrow the docstring to that exact claim: this test proves a direct/model-driven `next_group` never takes over an unexpired foreign run, while the separate automatic client bridge may invoke explicit `plan_groups` once successfully.

VERDICT: NEEDS_CHANGES
### Author's response to round 8

All three findings accepted, and the first names the reason my own completion test kept failing.

**1 (BLOCKER, unqualified call-count variants).** The phrase sweep was the wrong instrument, and the miss is
instructive: I grepped `once per process`, and the surviving text said "at most once per **client** process",
which does not match. The phrases keep mutating, so matching them will keep missing. Switched to a **semantic**
sweep — enumerate every occurrence of `plan_groups` across `design/`, `FINDINGS.md`, `research/`,
`experiments/`, `zikaron/` and `tests/`, and read the claim each one makes. Four sites were wrong: §"Service RPC
surface"'s summary, the anti-livelock shorthand ("bounding the takeover to one per client process"), the
measured-premise paragraph's own quoted bound, and the research report's opening plus its confirmed item 1;
FINDINGS open question 10 said the measurement means "the call fires once per skill invocation", which is an
attempt claim about a process fact. All now state the invariant in full — a client may re-attempt while
`unplanned`, may complete at most one **successful** plan, and never plans again once `ready` — and the
process-model discussions say the process supplies the *guard*, not a limit on attempts, because a failed plan
rolls back and displaces nobody. A final sweep leaves one occurrence, correctly qualified.

**2 (IMPROVEMENT, the withdrawn cancellation premise in project memory and a test).** Correct, and the worst
of the three, since `FINDINGS.md` is what loads every session. Both passages now carry the measured account:
a lease is a timer; a pid check is *better than it looks* — the client normally exits with its own subagent —
but cannot carry the decision, because it answers whether a process exists rather than whether a worker will
progress, pid reuse can return a false alive, the namespaces are not guaranteed shared, and cancellation
teardown is **unmeasured**. A grep for the withdrawn phrasing now returns nothing anywhere.

**3 (IMPROVEMENT, a test asserting the pre-bridge reachability claim).** Accepted. That docstring now says what
the test actually proves — no model can *request* a displacement through `next_group` — and states plainly that
the conforming client's own automatic `plan_groups` does displace another consolidator, once successfully per
process, on a separate path not under test there.

`./check.sh` clean: 795 tests, 99.72% branch coverage. M7's core code is unchanged this round; the edits are
design text, FINDINGS, the research report and two test docstrings.
## Round 9 — targeted: run takeover, seventh pass

### Summary judgment
The call-count policy has converged: across every current `plan_groups` occurrence in the requested corpus, a client may re-attempt while `unplanned`, may complete at most one successful plan per process, and never plans again once `ready`; I found no surviving attempt bound or conflicting `store_busy` rule. The M7 takeover mechanism also remains sound. The corpus is not quite one coherent policy yet, because normative schema text still repeats the withdrawn “no model can reach takeover” claim; the separate restart wording is only editorial, but the schema contradiction is material enough to correct before closing this targeted review.

### Findings
1. [IMPROVEMENT] `design/schema.md:1144-1149`, in invariant 17’s explanation of `active → taken_over`, says an “explicit human-initiated `plan_groups` is the evidence” and concludes that because `next_group` refuses a foreign run, “no *model* can reach this transition.” That is the pre-bridge reachability claim Round 8 removed from the test: under the current policy, a model’s first `next_group` request causes the conforming client to call explicit `plan_groups` before forwarding, and that automatic call can produce `taken_over`. The model cannot **request takeover directly**, but it does reach the transition indirectly through the client bridge. Replace these sentences with the precise current account: a human-invoked skill supplies a fresh client guard; when the model first requests a serve, the client invokes explicit `plan_groups`; a model confined to the configured tool surface cannot directly request that RPC, while the client may perform one successful plan automatically. This is a material consistency fix because the false statement sits in the normative run-transition invariant, even though the central architecture and implementation are already correct.

2. [NITPICK] `design/architecture.md:1001-1004` and `FINDINGS.md:430-435` say a mid-subagent client restart “would fire the call with no human behind it.” Restart alone does not fire anything under the lazy policy; it supplies a fresh guard, and only the next forwarded `next_group` consumes it. The research report already uses that exact formulation. Change both shorthands to “would supply a fresh guard, which the next `next_group` it forwarded could consume without a new human invocation.” This is editorial rather than material: the surrounding lifecycle and open question both clearly state the lazy trigger, and neither passage reintroduces an attempt bound.

VERDICT: NEEDS_CHANGES

### Author's response to round 9

Both findings accepted.

**1 (IMPROVEMENT, invariant 17 repeating the withdrawn reachability claim).** Correct, and the miss has the
same shape as the last one: my round-8 sweep was scoped to *count* claims — I enumerated `plan_groups`
occurrences and filtered for count words — so a **reachability** claim carrying no count word passed straight
through. Fixed, and stated more precisely than the version it replaces, because the honest account has two
halves that the short form collapses: a model confined to the configured tool surface cannot *request* this
transition (`plan_groups` is in neither tool set, and `next_group` refuses a foreign unexpired run), but it can
*reach* it indirectly, since asking for a serve is exactly what causes the client's own automatic call.
Invariant 17 now says both, and says outright that "no model can reach this transition" would be false. A grep
for that phrasing now finds it only where it is being quoted in order to be corrected.

**2 (NITPICK, the restart shorthand).** Accepted and fixed in both places, to the research report's own
formulation: a restart would supply a fresh guard, which the next `next_group` that client forwarded could
consume without a new human invocation. Agreed that it was editorial — neither passage reintroduced an attempt
bound — but it is the kind of shorthand that becomes the next round's material finding, which is the pattern
this review has established five times over.

`./check.sh` clean: 795 tests, 99.72% branch coverage. M7's core code unchanged; the edits are `schema.md`
invariant 17, one `architecture.md` clause and one FINDINGS clause.

## Round 10 — targeted: run takeover, eighth pass

### Summary judgment
The two Round 9 fixes are correctly applied: schema invariant 17 now distinguishes direct request from indirect reachability, and both restart passages use the precise fresh-guard/next-forwarded-serve formulation. The normative lifecycle and shipped M7 core remain mutually consistent on unconditional explicit takeover, foreign-run refusal in `next_group`, transactional replacement, and displaced-worker authorization. One current working-memory summary still reintroduces the discarded one-attempt trigger claim, however, so the corpus does not yet state a single policy everywhere.

### Findings
1. [IMPROVEMENT] `FINDINGS.md:813-817`, in the reference entry for the MCP lifecycle probe, says the measurement confirms that “the takeover bridge fires once per skill invocation.” The probe established one fresh client process—and therefore one fresh successful-plan guard—per invocation; it did not observe the future bridge firing. More importantly, the current policy permits **zero** `plan_groups` attempts when no `next_group` is forwarded and multiple attempts while `unplanned` after `store_busy`, with only the first success consuming the guard. “Fires once” therefore reintroduces both the eager/per-invocation trigger implication and the attempt-count bound that Rounds 6–8 removed, in the project memory loaded every session. Replace that clause with, for example: “each skill invocation supplies a fresh per-process successful-plan guard; the first forwarded `next_group` may re-attempt `plan_groups` while the client remains `unplanned`, and the first success moves it to `ready` so it never plans again.” This is material rather than stylistic because an M10 implementer following the current sentence could implement exactly one attempt and strand the documented `store_busy` retry path.

VERDICT: NEEDS_CHANGES
### Author's response to round 10

Accepted and fixed. The references entry said the probe "confirms … the takeover bridge fires once per skill
invocation", which smuggled back both things rounds 6-8 removed: an eager per-invocation *trigger*, and an
*attempt* bound. The probe established one fresh process — hence one fresh successful-plan guard — per
invocation, and observed no bridge at all, since none exists yet. It now reads: each skill invocation supplies a
fresh per-process successful-plan guard; the first forwarded `next_group` may re-attempt `plan_groups` while the
client is still `unplanned`; and the first success moves it to `ready`, after which it never plans again.

You are right that this is material rather than stylistic, and right about which way it would have failed: an
M10 implementer following that sentence would have coded exactly one attempt and stranded the `store_busy`
retry path the same document specifies.

Worth recording that every one of the last five rounds found the same defect in the same *kind* of place — a
summary, a reference entry, an invariant's explanatory paragraph — never in the normative statement or the code.
That is now written up in `FINDINGS.md` as a dogfooding lesson, because it is precisely what Zikaron exists to
prevent: the rule was current where it is defined and stale everywhere a reader is likelier to look.

`./check.sh` clean: 795 tests, 99.72% branch coverage. M7's core code is unchanged since round 7.

## Round 11 — targeted: run takeover, ninth pass

### Summary judgment
Yes: the requested corpus now states one coherent takeover policy—unconditional explicit takeover; lazy acquisition on the first forwarded `next_group`; at most one successful plan per client process with unbounded attempts while `unplanned`; `store_busy` returning to `unplanned`; `index_failed` terminal for that client; and no model-facing tool able to request takeover even though the model can reach it indirectly through its client's automatic call. Yes: M7's shipped consolidation code and tests are consistent with that policy—the service core implements unconditional explicit replacement, implicit expired-run recovery, foreign live-run refusal, transactional rollback, and post-takeover authorization, while the intentionally future client-side guard remains correctly assigned to M10/M12. No material or editorial inconsistency remains in the requested scope.

### Findings
None.

VERDICT: APPROVED
