# Review — Claude Code port plan (build-plan.md §§M13–M16)

Artifact: `design/build-plan.md` lines 352–515 (M13–M16), reviewed against
`research/claude-code-harness-probe.md` (the measured source), `research/claude-code-harness-contract.md`
(the weaker documentation reading), `design/architecture.md` (§"Subagent sessions", §"What the shared label
affects", §"Degraded modes", §"Warming", §"Two hook formats", §"The consolidator's model is a shipped config
field", §"The install contract"), and the M0–M12 house format in the same file.

## Round 1 — 2026-08-16

**Summary judgment.** The four briefs are well-shaped, correctly ordered, and the one-codebase constraint
genuinely holds — the seam is data, the installer variance is serialization, and no fork is smuggled in.
But M13 fails its own done-when bar in three places: it flattens a measured two-process observation into
"one MCP server process per session", it asserts an injection channel (`SubagentStart` stdout → subagent
context) the probe never measured, and its D29 mitigation names a mechanism no milestone builds. Two
accepted limitations are also described more narrowly than the evidence supports. All fixable with prose
and one cheap probe extension; none require rethinking the plan's structure.

### Findings

1. **[BLOCKER] M13's "one MCP server process per session" contradicts probe §4, and the flattening hides a
   real hazard.** (build-plan.md ~line 396–399.) The probe measured **two** `zkprobe` server processes in
   one session (pids 2256657/2256689, call served by the second) and explicitly leaves "why two processes
   start, and whether either restarts mid-session" unmeasured. M13 states "Claude Code runs one MCP server
   process per **session**" as fact. This matters beyond traceability: `_PlanBridge`'s guard is
   **per-process**, so a second or restarted consolidator-server process mid-run gets a fresh guard, and
   its first forwarded `next_group` lazily fires `plan_groups` — a **spurious takeover of the run's own
   live work with no human invocation behind it**, exactly the residual open question 10 left unresolved
   under kiro, now with measured evidence that multiple processes do occur. The stated blast radius ("two
   consolidators launched from one session are served the same run") omits this. Suggested change: the
   ownership bullet says "one or more server processes per session (two observed in one probe session,
   restart behaviour unmeasured — probe §4)", states the fresh-guard-per-process consequence, and bounds it
   (a spurious self-takeover costs in-flight reasoning and a replan, never a journal row — never-lose and
   row-level completion hold). Cheaper still: extend the probe with one run that watches whether the second
   process ever serves calls after the first has.

2. **[BLOCKER] The D32 exposure is understated: under Claude Code the primary agent can run an entire
   consolidation itself, with `search` and `fetch` in hand.** (build-plan.md ~line 375–382, "the exposure
   is a wasted expensive call, not a corrupted store".) Session-wide `.mcp.json` registration gives the
   primary all four consolidation verbs (probe §6), and ownership is `(session_id, pid)` where pid is the
   shared consolidator-server process — so a primary that calls `next_group` presents the **same pair a
   real consolidator in that session would**, triggers the lazy `plan_groups` (or inherits a live/unexpired
   lease), and is served groups as the owner. Under kiro this was mechanically impossible; under Claude
   Code the only thing between the primary and authoring long-term records **with broad retrieval
   available** is prose. That is not "a wasted expensive call": it is D7's code-picks-candidates
   enforcement reduced to prompt-only *end to end*, including the merge-judgment step, and a bad merge
   authored by an unrestricted model is the "manufactures a false record" failure `consolidation.md` names
   — journal rows safe, long-term content not. Suggested change: the bullet's consequence sentence becomes
   "the exposure is an unauthorized consolidation performed by an unrestricted model — wasted tokens and
   possibly a poorly-judged merge written to long-term; never-lose, the receipts and the journal are
   untouched", and D34/D32's amended rows carry that wording. The acceptance can stand; the description
   cannot.

3. **[BLOCKER] The D29 mitigation is unassigned and rests on an unmeasured claim.** (build-plan.md
   ~line 405–411.) "The model actually used is recorded per consolidation run from the harness's own
   record" names no owner anywhere in M14–M16: `SubagentStop` is absent from M14's trigger vocabulary
   (`SessionStart`/`UserPromptSubmit`/`SubagentStart` only, line 435–438), absent from M15's four-artefact
   list (line 465–467), and M16's done-when observes a consolidation run but never checks that its model
   was recorded. Nothing says **where** the value lands (an event? a `consolidation_run` column? `meta`?)
   — a storage decision that belongs in M13's design delta. Separately, "the transcript records the
   concrete model per assistant message" is traceable to **no numbered probe section** — probe §3 measured
   that `SubagentStop` carries `agent_transcript_path` and nothing about transcript message contents — so
   by M13's own done-when it must be probed or marked unmeasured. The spike transcripts in
   `spikes/claude-code-harness/` already exist; one grep settles it. Suggested change: M13 names the
   storage location; M14 adds `SubagentStop` (filtered to `agent_type == "zikaron-consolidator"`) to the
   seam vocabulary; M15 adds the hook entry to the artefact list; M16's done-when adds "the checkpoint
   run's concrete model is present in the store's record of it".

4. **[BLOCKER] M13's "the write policy reaches subagents, precisely" asserts an injection channel the
   probe never measured.** (build-plan.md ~line 386–389.) Probe §5 verified stdout→context end to end for
   `SessionStart` and `UserPromptSubmit` **only**; whether a `SubagentStart` hook's exit-0 stdout reaches
   the *subagent's* context (rather than the parent's, or nobody's) was not measured and is not even in
   probe §7's not-measured list. The entire bullet — and M14's `SubagentStart` policy path, whose done-when
   tests only that our side prints — rests on it. By M13's own traceability rule this is a blocker as
   written. Suggested change: either extend the probe with the same secret-word test through a
   `SubagentStart` hook (one headless run), or mark the bullet unmeasured in M13 and add "the subagent is
   observed to have received the policy" to M16's done-when.

5. **[BLOCKER] M16's "one consolidation run … against a real store" invites burning the one corpus that
   cannot be regrown.** (build-plan.md ~line 508–511.) FINDINGS priority 1 reserves the next `~/Memory`
   consolidation for designing and testing the positive merge criterion, on a journal grown by real work —
   a one-shot experiment, and M13's own scope fence exists because a confounded consolidation result is
   the phase's most expensive mistake. A future session executing M16 literally, with no memory of this,
   will reach for the primary real-work store — which is `~/Memory`. And the checkpoint run happens under
   a changed harness *and* a changed model (the `sonnet` alias), so using it for the merge-criterion
   experiment would confound exactly what the fence protects. Suggested change: M16 names the store — this
   repository's seeded store or a throwaway — and the scope fence gains "the checkpoint consolidation does
   not run against `~/Memory`; priority 1's run is separate work".

6. **[IMPROVEMENT] The nesting limit's observability claim is wrong in its main case.** (build-plan.md
   ~line 362–366: "a mis-resolution shows up there as a shortfall".) Both clients resolve the label from
   the environment by construction (architecture §"Both clients resolve the same label"), so a kiro
   session nested inside a Claude Code shell has *both* clients read the same stale `CLAUDE_CODE_SESSION_ID`
   — they **agree**, link coverage reads ~1.0, and the session's pushes, writes and searches are silently
   attributed to a *different, live* session's instruments. Agreement-by-construction is precisely what
   prevents the shortfall from appearing. Accepting the limit is fine; the stated detector does not detect
   it. Suggested change: either state it honestly ("unobservable when both clients agree on the stale
   label; it contaminates the outer session's per-session instruments"), or make it genuinely observable
   for one client's worth of evidence: the hook has the payload's `session_id`, so one `hook.log` line on
   payload-vs-resolved-env divergence is a no-RPC, no-behaviour-change tripwire.

7. **[IMPROVEMENT] The 10,000 threshold's unit is unverified, and the gist byte bound will be sized
   against it.** (build-plan.md line 390 "10,000 characters"; M14 done-when line 452.) Probe §5's table
   mixes "stdout bytes" and "content the model sees" counts, and the bisection payloads were presumably
   ASCII, where the two units coincide. If the cap is bytes, a five-row block of multibyte-heavy gists
   overruns at well under 10,000 characters — and this corpus has already been burned once by exactly this
   shape (tokens do not bound bytes, open question 11). Suggested change: one probe run with multibyte
   payload to pin bytes vs characters, and M14's done-when states the bound in the measured unit.

8. **[IMPROVEMENT] Two model-check claims in M13 need their sourcing marked.** (build-plan.md
   ~line 405–406.) "Claude Code offers no `--list-models` analogue" traces only to the documentation
   reading (contract §9), not the probe; and the behaviour of an unknown model id in subagent frontmatter
   is explicitly unmeasured (probe §7, contract §9 "Action needed"). The `sonnet` alias sidesteps the
   second today, but an operator pinning a concrete id for the A/B that `consolidation.md` calls for walks
   straight into it. Suggested change: mark both per M13's own rule, and add one line: "pinning a concrete
   id in the frontmatter has unmeasured failure behaviour — measure before relying on it."

9. **[IMPROVEMENT] Even once built, recording is not validation — say who reads the recorded model and
   when.** (build-plan.md ~line 408–411.) D29's stated failure is "two runs incomparable while both look
   healthy". A per-run record removes *undetectable*, not *unnoticed*: both runs still look healthy unless
   the comparison step consults the recorded value. Suggested change: one sentence in M13 — any
   cross-run comparison (the merge-criterion A/B first among them) must read the recorded model of both
   runs and refuse or annotate on mismatch — so the discharge is a protocol, not a hope.

10. **[IMPROVEMENT] M15 needs two decisions it currently leaves to the implementer, and a scope fence.**
    (build-plan.md ~line 459–487.) (a) **Which settings layer**: `.claude/settings.json` is the shared,
    checked-in layer, and the installer writes absolute venv paths (machine-local by construction, same
    reasoning as the install contract's console-script rule) — `settings.local.json` is the defensible
    target, but the brief must choose and say why. (b) **`.mcp.json` approval**: Claude Code requires
    per-user approval of project-scoped MCP servers before they load; unmeasured, unmentioned, and it means
    a fresh install can silently lack every tool until the user approves. The installer should report the
    approval step the way it already reports the `subagent` tool requirement under kiro. (c) M15 is the
    only port brief with **no scope fence**, and there is a real trap to fence: an implementer trying to
    restore the primary's tool gating will reach for `permissions.deny`, which probe §6 measured to
    unregister the tool for the consolidator too, breaking it outright — name it, alongside "no run-token
    build" (currently fenced only in M13's prose).

11. **[NITPICK] FINDINGS' refuted migration claims should be withdrawn in place as part of M13.** The
    harness section still asserts "the prompt field is `user_input`, not `prompt`" and "no session-id
    environment variable exists" — both refuted by probe §§1–2. Continuous maintenance may catch it, but
    M13's done-when is the natural place to guarantee the withdrawal happens per the house rule.

12. **[NITPICK] M14 should state what "policy-only" excludes and includes.** (build-plan.md line 437.) Say
    explicitly that the `SubagentStart` path does not spawn the warm helper (the session's `SessionStart`
    already did) and that it honours the `.zikaron/write-policy.md` override the same as the spawn path —
    both are what a reader would guess, and guessing is what the briefs exist to prevent.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-08-16

**Summary judgment.** The round-1 fixes are real, not cosmetic: the D32 exposure now states its true size
with the ownership-pair mechanics spelled out correctly; the blast-radius bullet matches probe §4 including
the fresh-guard consequence and its bound; the two-channel fact (probe §7b) is propagated to M13's harness
table, M14's seam ownership and done-when, and M16's "subagent observed to receive" check, and nothing in
M15 assumes one channel; the character-unit correction is applied consistently on the Claude Code side; and
every new claim I spot-checked traces cleanly to §§7a–7c. Two problems remain, both introduced or exposed by
the edits themselves: M15 now contradicts its own settings-layer decision in its artefact list, and the
`consolidation_run` model column is quietly Zikaron's **first schema migration against non-empty live
stores** — a consequence no milestone plans for and M13's own storage-location reasoning does not confront.

### Findings

1. **[BLOCKER] M15's artefact list contradicts its own decision (a) on which settings file the installer
   writes.** (build-plan.md lines 529–530 vs 536–540.) The four-artefact enumeration says "hook entries
   merged into `.claude/settings.json`", while decision (a) two paragraphs later says — emphatically, with
   the breaks-every-other-clone rationale — "**`.claude/settings.local.json`, not `settings.json`**". A
   normative brief naming two different files for its primary artefact is exactly the ambiguity these
   briefs exist to remove, and the enumeration is the part a skimming implementer will copy. One-word fix:
   the artefact list reads "hook entries merged into `.claude/settings.local.json` (decision (a) below)".

2. **[BLOCKER] The `consolidation_run` column is v0's first schema migration, against stores that are no
   longer empty, and no milestone owns that.** (build-plan.md lines 447–449, 486–487.) M13 names "a column
   on `consolidation_run`" as the storage location. That is a DDL change, and `schema.md` §"Migration
   posture" is explicit: `schema_version` is a **hard gate** at exactly 1, "the first version that needs
   to open more than one schema gets an explicit supported range plus a migration or capability contract,
   written then" — and its "the store is empty" premise is now false (`~/Memory` holds 57 records; this
   repository's store exists). A future session implementing M14 as written must either refuse to open
   every existing store (new DDL, version still 1) or add the column without bumping the version, violating
   the posture; nothing in M13's amend list (`schema.md` §"Linked sessions" only), M14's normative list
   (§Bounds only), or any done-when covers "an existing v1 store opens under the new binary". Two honest
   ways out, pick one explicitly: (i) plan the migration — M13's amend list gains `schema.md` §Tables and
   §"Migration posture", and M14's done-when gains "a v1 store opens, is migrated to 2, and a v2 store is
   refused by the old binary per the posture table"; or (ii) reconsider the storage location: a new
   run-scoped **event kind** (`schema.md` §"The `event` log, per kind" is additive prose + code, no DDL,
   no version bump) — M13's rejection of an event as "not a per-row fact" is shaky, since the event log
   already records non-per-memory-row facts (`search`), and cheapness against live stores is a stronger
   criterion than taxonomic fit. Either is fine; silence is not.

3. **[IMPROVEMENT] The `SubagentStop` → store write path is named but not specified: verb, run
   identification, and idempotency are all left to the implementer.** (build-plan.md lines 486–487,
   511–513.) "Read the concrete model out of `agent_transcript_path` and record it against the run (M13
   names the column)" requires a **new service RPC method** the hook client calls — no existing envelope
   method writes consolidation state from the hook — and a rule for *which* run: the hook holds
   `session_id` and the transcript path, not a `run_id`, and M13's own accepted limitation means one
   session can legitimately contain **two runs** (the spurious self-takeover closes the first
   `taken_over`); the run may also be closed, or never closed if the consolidator died mid-run. Suggested
   change, three sentences in M13 or M14: name the method; state the rule ("recorded against the
   session's most recently created run regardless of status, last-write-wins, so a died-mid-run
   consolidator still gets its model recorded"); and state that a `SubagentStop` for a session with no run
   is a silent no-op (a consolidator spawned that never called `next_group` — M13's own do-not-take-the-lock
   case).

4. **[IMPROVEMENT] The character bound discharges only half of open question 11 as stated — the kiro
   byte cap that motivated the question is never re-proved.** (build-plan.md lines 501–504, 513–514.)
   Open question 11's defect was stated against kiro's **byte**-counted `max_output_size`; M14 now
   specifies a **character** bound (correct for Claude Code per §7a) and its done-when asserts fit against
   10,000 characters only. Characters do bound bytes — UTF-8's 4-bytes-per-character maximum is a real
   ceiling, unlike the invented 4-bytes-per-token factor this corpus already burned itself on — so a
   five-row block fitting 10,000 characters is ≤ ~40,000 bytes, inside kiro's 65,536, and the character
   bound genuinely closes the question for both harnesses. But that derivation exists only in my head and
   the author's; the brief should state it and the done-when should assert the kiro side ("the same
   worst-case block at 4 B/char is asserted under the shipped kiro `max_output_size`"), both so the M12
   drift guard's byte assertion becomes provable rather than accidental, and so the ×4 factor's
   *legitimacy here* is distinguished in writing from the token-factor mistake the review history records.

5. **[IMPROVEMENT] The `CLAUDECODE` detection marker is documentation-only, and it is the single key the
   whole harness seam turns on.** (build-plan.md line 362.) The marker traces to the contract file
   (line 283, env table) and appears **nowhere** in the probe note or the spike logs
   (`spikes/claude-code-harness/` greps clean for it) — so by M13's own done-when rule ("traceable to a
   numbered section of the probe note or explicitly marked unmeasured") the detection rule fails the bar
   the same way round-1 finding 8's claims did, and this one gates *every* downstream behaviour: trigger
   normalization, budget, channel, session variable. Suggested change: mark it "(contract only,
   unmeasured)" and pin it cheaply — one line dumping `CLAUDECODE` from an existing hook run, or add "the
   marker variable is observed set in a live hook process" to M16's done-when.

6. **[NITPICK] D34's table enumeration omits the column the §7b bullet mandates.** (build-plan.md
   lines 360–362 vs 407–409.) The table is specified as "marker variable, session variable, trigger names,
   injection budget, artefact locations", while the two-channel bullet calls the channel "a normative fact
   for the harness table". Add "its output channel per event" to the enumeration so the table's spec and
   its contents cannot drift.

7. **[NITPICK] M15's `.mcp.json` approval claim should carry its sourcing.** (build-plan.md lines
   540–543.) It is stated as fact; it traces only to the contract's documentation reading ("Pending
   approval" status, contract §"Per-Server Pre-approval") and no probe measured it. One parenthetical —
   "(documented, unmeasured; M16's end-to-end run verifies it implicitly, since no tool loads until
   approval)" — keeps the corpus's documentation-is-not-measurement discipline intact.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-08-16

**Summary judgment.** The round-2 fixes hold up under verification, including the two the author pushed
back on. The `consolidate_run` detail-JSON decision is genuinely DDL-free and violates no numbered
invariant — I verified the `CHECK (kind IN (…))` claim (schema.md lines 130–146), that `phase` lives only
in the JSON (line 544), and that invariants 10, 14, 17 and 18 all survive a further phase. And round-2
finding 5 was **my error, not the author's**: `CLAUDECODE=1` is present exactly as claimed — 4 occurrences
in `spikes/claude-code-harness/hook.log`, 6 in `mcp.log`, verified by direct file grep; my round-2
directory grep returned "0 across 0 files" because ripgrep's ignore rules excluded the `.log` files, and I
reported absence-of-evidence as evidence. The finding is withdrawn and probe §1 now carries the
measurement properly. Two real problems remain, both small and both direct consequences of this round's
own edits: the storage decision's "prose and code only" prose is not scheduled anywhere — the schema.md
section that fixes the event's shape is absent from every amend list — and one stale "(M13 names the
column)" pointer survived in M14, pointing at the abandoned column design.

### Findings

1. **[BLOCKER] The detail-JSON decision is sound, but the prose it changes is not in any amend list — the
   exact "silent violation" trade the author asked me to check for.** (build-plan.md lines 354–357 amend
   list vs 460–468; schema.md lines 148, 520, 544, 554–563; architecture.md lines 1321, 1338.) Verified:
   no DDL, no `CHECK` change, no version bump, no numbered-invariant breach — the claim holds as stated.
   But `detail` is governed by a load-bearing rule: "JSON with a **fixed shape per kind**" (schema.md
   line 520, and the DDL comment "per-kind shape fixed below, never free-form", line 148), a rule that
   exists because untyped detail made three of D30's six signals irreproducible. A new phase carrying
   `{run_id, model}` changes that documented shape in four places, and M13's amend list names only
   `schema.md` §"Linked sessions": (a) the `consolidate_run` row of the per-kind table (line 544 — the
   phase enum and the field set; the merge/promote rows already precedent per-role null fields, so
   "counts null on the model phase" is the house pattern); (b) the "three counts … identical on every
   later phase of that run" paragraph (lines 554–563), which the new phase falsifies as written; (c) the
   cardinality cell "one per run transition" — the brief names the stretch but the table must too, and
   since one session can legally hold two runs and a retried consolidator can stop twice, the last-write-wins
   rule needs its read half stated ("readers take the run's most recent model phase"); (d) the `event`
   DDL's observability comment "pushes come from 'hook', writes from 'mcp'" (schema.md lines 120–121),
   which the hook's first write path falsifies. The new RPC method has the same gap on the architecture
   side: `architecture.md`'s RPC surface and error table are in neither M13's nor M14's amend list, despite
   the brief's own "worth stating rather than smuggling". Fix is small and purely list-shaped: M13's
   amend list gains `design/schema.md` §"The `event` log, per kind" (+ the two DDL comments) and
   `design/architecture.md` §"Service RPC surface"; nothing about the decision itself needs to change.

2. **[BLOCKER] M14 still says "(M13 names the column)" — a stale pointer to the design this round
   abandoned, and it points at exactly the DDL the decision exists to avoid.** (build-plan.md line 515 vs
   450–468.) M13 no longer names a column anywhere; it argues at length that a column is a forbidden
   migration and lands on the `consolidate_run` detail phase. An implementer skimming M14's trigger
   vocabulary — the operational text, the part that gets copied — is instructed to record the model in a
   column M13 refuses to create. Same class as round 2's finding 1, same fix size: "…and record it against
   the run (M13 names the storage: a further `consolidate_run` event phase, not a column)".

3. **[IMPROVEMENT] The SubagentStop path's failure reporting should not inherit the userPromptSubmit
   two-channel rule — say so.** (build-plan.md lines 470–477, 513–515; architecture.md §"Degraded modes",
   lines 884–896.) On question (b): the new write path does **not** violate the section's letter or
   spirit — the rule is never-block-a-user-message, never-*read*-the-store, always exit 0; the hook still
   never opens the store (the service writes, over the same RPC posture `surface` uses), the event fires
   at subagent termination off any user-facing path, and the never-a-reader rationale (no second
   implementation of the read path) has no analogue for a fire-and-forget write. One genuine residual:
   the degraded-mode rule for `userPromptSubmit` mandates failure reporting on **two** channels, one of
   them model-facing stdout — but no output channel is measured for `SubagentStop` at all (§7b measured
   `SubagentStart` stdout reaching nobody; `SubagentStop` is unprobed), and there is no user message to
   relay into. One sentence in M13's rule (1) or M14: on failure this path writes its one `hook.log` line
   and nothing else — no stdout instruction, no retry — so the two-channel rule is explicitly scoped to
   the push path rather than silently generalized.

4. **[NITPICK] Round-2 finding 5's factual claim is formally withdrawn.** The spike logs do contain the
   marker (4× `hook.log`, 6× `mcp.log`, verified this round by direct file grep; the round-2 directory
   grep was defeated by ignore rules on `*.log`). Probe §1 lines 32–35 now record it, with the
   `AI_AGENT=claude-code_<version>_<role>` role-suffix observation verified against the logs
   (`claude-code_2-1-233_harness`, 4×). No action needed; recorded so the trail shows which side was
   wrong, per the house rule.

Everything else re-verified clean this round: M15's artefact list and decision (a) now agree on
`settings.local.json` (lines 567–568, 574–575); the three SubagentStop rules are stated as specified
(lines 470–477) and M14's done-when covers both the consolidator and the ignore case (lines 549–550); the
UTF-8 ≤4 B/char derivation is in writing with the kiro-side assertion in the done-when and the explicit
contrast with the invented token factor (lines 534–541, 550–552); the D34 enumeration carries "output
channel per event" (lines 361–362); and the `.mcp.json` approval claim is marked documented-unmeasured
with the implicit-verification note (lines 578–580). M16's store fence and the recorded-model done-when
check both stand from round 1.

VERDICT: NEEDS_CHANGES
