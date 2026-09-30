# M34 implementation — review trail

Artifact: everything uncommitted relative to `8ce198f` (`git status` at the time of each round), against
`design/build-plan.md` §"M34 — A headline carries no verdict". Reviewer: `memory-reviewer`.

## Round 1 — 2026-09-29

### Summary judgment

The code half is sound and small: `_PLANNING_TIMEOUT_SECONDS` reaches both calls that can plan, the
"`memory_next_group` plans inline" claim is true of the service (`core/consolidation/serving.py`
lines 349–351, 426), a timed-out plan still lands the bridge in `FAILED` through
`AmbiguousMutationError`, and the new bridge test goes red on the defect it names. The four prose
surfaces agree with each other, with the re-rendered goldens, with `write_policy.py`'s deferral, and
with `architecture.md`'s promote ladder; `write-policy.md` §1 states the rule where the brief asks.
What is not ready is the **evidence**: the research note's headline counts contradict the
`compare.md` they cite, the preregistered "under a quarter" bar is not shown met and the note reports
a pass by a different measure, and the done-when's second replay has not run and is described three
different ways in three documents. `FINDINGS.md` Q22 also still quotes a `write-policy.md` sentence
this milestone deleted.

### Findings

1. **[BLOCKER] The "Verdicts removed" bar is not shown to be met, and the note reports a pass by a
   measure the bar does not state.** `design/build-plan.md` §M34 (lines 4500–4502) preregisters:
   *"conclusion marker at under a quarter of the seed's rate, counted by the same marker regex and
   confirmed by reading."* `research/m34-gist-form-replay.md` §"Per bar" (line 41) says *"passes on
   rewritten records (2 of 64 residual)"*. By the note's own table: all output 23/105 = 21.9% against
   seed 72/134 = 53.7% is **0.41** of the seed rate; the rewritten subset 9/64 = 14.1% is **0.26** —
   neither is under a quarter by the regex, and the by-reading figure (2/64) has no seed-side
   by-reading denominator anywhere in the note, so the ratio the bar asks for cannot be computed by a
   reader. Fix, in the note: read the 72 marked seed gists under the same rule and state the count, then
   state both ratios explicitly — *by regex: 0.41 whole output (fails, and the in-place leak is why),
   0.26 rewritten; by reading: 2/64 against N/134 = R* — and say which one the bar is judged on. If the
   judgement is by reading, amend the bar's sentence in `build-plan.md` §M34 so the second replay is
   scored against the text as written rather than against a reinterpretation of it. As it stands the
   brief says *"Short of that, the wording goes back to `memory-reviewer`"* and the note does not show
   that it was not short of that.

2. **[BLOCKER] The note's headline counts contradict its own `compare.md`.** `research/m34-gist-form-replay.md`
   §Setup (lines 17–18): *"105 long-term records from 134 seed rows, 190 promotes (41 in place, 149
   new rows), 0 discards."* `~/zikaron-m34-replay/compare.md` has 105 `## ` holders whose `absorbed N`
   values sum to 134 (4 + 3×6 + 2×14 + 1×84), and the note's own table puts 41 in place, so there are
   **64** records the consolidator authored — *"149 new rows"* cannot be a count of records created,
   and 41 + 149 = 190 cannot coexist with 105 live long-term records (a promote never retires a
   long-term row). Name the quantity — event rows, or the consolidator's own report — and re-derive it
   from the replay store's `event` table (`kind='promote'` grouped by `role`/`form`), or delete the
   clause. A research note whose arithmetic does not close is the class `CLAUDE.md` §"Measure before
   you assert" exists for.

3. **[BLOCKER — the acknowledged remaining step, listed so the verdict is legible.]** §M34 "Done when"
   (lines 4516–4517): *"the replay has run, **and so has the targeted re-run** of the rows the first one
   leaked"*. It has not, and its design is stated three ways: the note's §"What follows" (line 82–84)
   says *"seed only the in-place-promoted verdict rows above"* (five listed); `reviews/m34-prose-review.md`
   Round 2 predicts over *"the 14 marked in-place rows"* (~8 real verdicts flip, ~6 causal stay in place);
   `FINDINGS.md` §"Current state" (line 93) says *"the 14 leaked rows plus 6 clean controls"*; and
   `~/zikaron-m34-replay-inplace/seed.json` holds **20** rows. Before the run, preregister the actual
   design in the research note — 20 rows in three strata, the prediction per stratum (real verdict or
   order → new record with the verdict in `content`; causal-`so`/measurement-dash → still in place;
   6 unmarked → still in place), and what each outcome does (all 14 flip → over-fired, wording back; a
   real verdict still in place → operator question, per the prose review). Then run it and record the
   per-row result. Until that is in the note, the milestone is short of its own done-when.

4. **[IMPROVEMENT] The note quotes prompt text that no longer exists, in the present tense.**
   `research/m34-gist-form-replay.md` line 56–57: *"The prompt says a verdict gist 'is never repeated
   byte-for-byte to promote an entry in place'"* — that sentence was replaced by Round 2 (now *"The one
   gist you do not write is an entry's own, promoted in place"*, `assets.py` line 152–153). §Setup
   line 15, *"the shipped skill with the M34 text installed"*, does not say it was Round 1's text with
   the promote description and verb paragraph still unconditioned. A reader grepping the tree finds
   neither claim. Fix: *"At the time of this run the prompt's authoring section said …, and
   `zikaron_memory_promote`'s description stated the in-place form with no condition; both were replaced
   after it (`reviews/m34-prose-review.md` Round 2)."* Research is a record, and a record has to say
   which version it records.

5. **[IMPROVEMENT] `FINDINGS.md` Q22 asserts a sentence M34 deleted and does not record that M34 shipped
   the rule.** Lines 537–540: *"`design/write-policy.md` says 'lead with the observable symptom rather
   than the conclusion'"* — `write-policy.md` no longer contains that clause (line 74–76 now reads *"lead
   with the observable situation"*, and lines 78–86 carry the presence rule). Nothing in Q22 says the
   rule is now on all four surfaces, so a fresh session reading Q22 alone would re-propose it. Add a
   dated line: *"M34 (2026-09-29) put the rule on `remember`/`amend`/`promote`'s descriptions and the
   consolidator prompt; `write-policy.md` §1 states it. Still open: the marker rate among new `remember`
   writes after release, and the targeted in-place replay."* And put the quotation in the past tense.
   `tests/test_quoted_design_prose_is_verbatim.py` cannot catch this — its stated scope is `zikaron/` and
   `tests/` only.

6. **[IMPROVEMENT] `zikaron/install/assets.py` module docstring (lines 13–19) is false on both halves,
   and this milestone widened the gap.** *"Three prohibitions are stated in both this prompt and the
   write policy … `tests/test_install_assets.py` asserts all three appear in both texts."* The write
   policy defers every headline rule to `remember`'s description (`hook/write_policy.py` line 90);
   `_authoring_surfaces` compares the prompt against **that description**, not the policy; and
   `TestTheSharedRulesAreOnEveryAuthoringSurface` now pins **six** rules, the sixth (the verdict) added
   by this change. Rewrite: *"The authoring rules are stated in both this prompt and
   `zikaron_memory_remember`'s description … `tests/test_install_assets.py` pins each shared rule on both
   surfaces as a property."* This is a comment in a file M34 edits, and `CLAUDE.md` says what an
   unguarded comment is worth.

7. **[IMPROVEMENT] `amend`'s one sentence of its own is unpinned.** §M34 names amend as a surface
   (*"names it in its summary"*); the prose review says amend earns *"a corrected verdict is still a
   verdict"* because it was the surface in front of the agent when `3e1f6c7a` was repaired into another
   verdict. `tests/test_mcp_tool_descriptions.py::test_the_write_surface_states_what_an_agent_could_not_infer`
   pins amend only on *"may be shorter than the one it replaces"*, and
   `test_install_assets.py::test_it_keeps_the_verdict_out_of_the_headline` reads `remember` and the
   prompt only. Add the row `("zikaron_memory_amend", "a corrected verdict is still a verdict")` — that
   test's own docstring says a one-paragraph rule inside a long docstring is exactly what goes missing
   with every other test green.

8. **[IMPROVEMENT] `experiments/m34_gist_replay.py` `--rows` can seed nothing and say so only in passing.**
   `seed()` filters `row[0] in only` on full uuids (line 101) and never checks that every requested uuid
   was found; `compare.md` prints `source_uuid[:8]` (lines 186, 190), so a rows file built from it seeds
   zero rows, creates the store anyway, and prints *"seeded 0 journal rows"*. The done-when says the
   script is re-runnable *"by `--rows`"*. Fix: after filtering, `missing = only - {row[0] for row in rows}`
   and `sys.exit` naming them (or accept prefixes and refuse ambiguity). Noted with the operator's
   2026-09-22 decision in view — `experiments/` is out of sweep scope — but this is the instrument the
   brief puts under review.

9. **[NITPICK] `_PLANNING_TIMEOUT_SECONDS = 300.0` states the measurement and not what the number
   buys.** `zikaron/mcp/consolidator.py` lines 54–59 give 12.2 s for 284 rows and then a constant 25×
   that, with nothing saying why — e.g. *"linear in the journal, so ~7,000 rows at the measured rate"*,
   or its relation to `run_lease`. The 13.1 s live-through-the-bridge figure from the brief is worth a
   parenthesis beside 12.2 s.

10. **[NITPICK] `CLAUDE.md` line 26 says "Four kinds do"; `FINDINGS.md`'s preamble (lines 6–9) now
    enumerates five** (it adds *"a defect with the fix proposed"* as a kind, where `CLAUDE.md` adds it as
    a rule about entries). `CLAUDE.md` forbids tallies elsewhere for exactly this reason — drop "Four",
    or make the FINDINGS list mirror the four-plus-rule shape.

11. **[NITPICK] `FINDINGS.md` line 94, "The self-review round runs in parallel."** Process narration,
    false the moment the round ends; §"Project memory" says it goes nowhere. Delete.

12. **[NITPICK] `design/harness.md` §"Tool descriptions are capped" (lines 484–491) documents a
    primary-only measurement**, and §M34 points at it for `promote`, which lives on the consolidator
    server. Replace the snippet with the `build_server(mode, scope_dir=…)` form the prose review gave, so
    the documented command covers both modes.

13. **[NITPICK] `design/write-policy.md` line 85–86, "`zikaron_memory_promote` offers that form only
    for an entry already meeting every rule"**, reads as a mechanical restriction, which §M34's fence says
    was not made. *"…its description reserves that form for an entry already meeting every rule."*

14. **[NITPICK] `FINDINGS.md` lines 247–249's re-derive command for M35 depends on
    `~/zikaron-m34-replay/replay/.zikaron/memory.db` existing** (`spikes/m34_service_staleness_probe.py`
    line 14). Say *"after `experiments/m34_gist_replay.py seed`"*, or the command fails on any machine but
    this one.

15. **[NITPICK] Two instruments on one quantity read as a correction.** `build-plan.md` §M34 line 4416:
    *"93 of 169 … by `VERDICT_MARKER`"*; `FINDINGS.md` Q22 line 524: *"58 of 169 … carry an explicit
    conclusion marker"*. Both name their instrument, but a reader meets 58 first and 93 second. One clause
    in Q22 — *"93 by the wider `VERDICT_MARKER` screen"* — closes it.

16. **[NITPICK] Crew twins.** `.claude/agents/memory-reviewer.md` and `py-runner.md` are modified in this
    tree; `.kiro/agents/memory-reviewer.json` and `py-runner.json` are not (`CLAUDE.md` §Harness: *"worth
    keeping in step with their twins"*). Outside M34, noted because the brief puts the `.claude` edits in
    the commit.

17. **[NITPICK] `design/overview.md` D30 row** still describes the gist instruction as *"cue-shaped
    (lead with the observable symptom)"* — the ordering rule Q22 diagnosed as obeyed-and-insufficient.
    One clause, *"and, since M34, carrying no verdict"*, keeps the decision table's audit trail whole;
    optional, since `write-policy.md` §1 is where D30 points.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-09-29

### Summary judgment

Round 1's three blockers are closed and the evidence now holds up under an independent re-reading:
I correlated the 20 re-seeded rows (`~/zikaron-m34-replay/inplace-rows.txt`) against the first run's
`compare.md` myself, and all 14 marked rows and all 6 controls were in-place promotions there, five of
the 14 are verdicts or orders and nine are causal or measurement clauses — the note's classification,
not the prose review's "~8". Findings 4–15 and 17 are applied as described; 16's non-application is
reasoned and accepted. The code half is unchanged from Round 1 and still sound. What is left is not a
blocker: the amended bar has no threshold and the owed corpus-repair pass inherits it; the re-run's
per-bar result is not stated and one of its rows is a live Triage question; and the planning wait is a
client behaviour the design corpus does not state and whose 300 s is bounded by a harness limit the
tree never measured. Each is a one-edit item.

### Findings

1. **[IMPROVEMENT] The amended "Verdicts removed" bar has no threshold, and it is the gate the next
   milestone inherits.** `design/build-plan.md` §M34 lines 4500–4506 now read *"no verdict or order
   reaches long-term through a gist the consolidator wrote or chose to keep, beyond isolated residuals
   each named in the research note"* — nothing says how many residuals stop being *isolated*, so no
   outcome could have failed it, which is the inverse of the defect `FINDINGS.md` §"How the next review
   should be briefed" (lines 341–347) records for M33. It matters beyond M34 because `FINDINGS.md`
   §"Owed work" lines 271–272 says the corpus-repair pass is *"judged on the same four bars"*. Write the
   number the pass was actually taken at: by reading, 3 verdicts in 72 rewritten gists (2 of 64 in the
   first run, 1 of 8 in the re-run) and 1 borderline in 12 kept in place. Suggested wording: *"by
   reading, no order survives in any gist, and at most one rewritten gist in ten carries a verdict; each
   residual is quoted in the research note."* Or, per the operator's own rule, drop the gate and report
   — but then delete *"Short of the reading test, the wording goes back"*, which is a gate.

2. **[IMPROVEMENT] The re-run's per-bar result is not stated, and one row is a live Triage question.**
   `research/m34-gist-form-replay.md` §"The fix, and the targeted re-run" (lines 107–125) reports the
   leak and the over-fire but never says which of the four bars the 8 rewritten records pass; the
   done-when asks for *"the per-bar result and the gists that decided it"*. The one that needs an explicit
   verdict is lines 119–121: seed `d7eee984` — *"A forked sbt runMain JVM shows in ps as
   `java @/tmp/sbt-args*.tmp`, so pgrep -f on the main class finds nothing and a live job looks dead"* —
   was rewritten to *"the mechanism alone"*. Here the `so` clause **is** the observed symptom: the gist
   was written mechanism-first, the prompt's literal *"drop the clause after 'so'"* fired, and its
   boundary sentence (*observed versus made of it*) did not hold it back. Under my reading the rewrite
   still names its subject, so "Triage kept" passes by the bar's letter while push loses the words a
   query would carry. Fix: (a) quote the rewritten gist and state the Triage verdict; (b) record the
   over-fire shape — *mechanism, so symptom* — as a known limit of the shipped wording in `FINDINGS.md`
   Q22's "still open" line (lines 538–540), since the corpus-repair pass will meet it often and the fix is
   one clause in `assets.py`'s "A gist carries no verdict" paragraph (e.g. *A "so" clause that names what
   was seen — "so the job looks dead" — is the symptom and stays*). Whether to change the prompt now is the
   operator's call at n=1 of 8; recording it is not. (Line 8's *"about half real verdicts"* reads as
   verdicts the re-run never examined; it is five of 14, which the section itself then says.)

3. **[IMPROVEMENT] The planning wait is a client behaviour the design corpus does not state.**
   `design/architecture.md` §"Consolidation lifecycle" §Planning (lines 1518–1523) says planning is a
   pure function called implicitly by `next_group` and nothing about its cost or what the client does
   while it runs; the only design-corpus statement is the M34 brief (`build-plan.md` lines 4488–4492),
   which is archived with the milestone, while `zikaron/mcp/connection.py` line 57–58 now carries the
   fact (*"planning scales with the journal, and its callers pass their own timeout"*). An M35 brief
   that reads §Planning — and M35 is exactly the milestone that moves planning onto a read snapshot —
   will not learn that two calls wait 300 s. Add one sentence to §Planning: *"Planning runs in time
   proportional to the journal (12.2 s for 284 rows, measured), so the two client calls that can trigger
   it — `memory_plan_groups`, and a `next_group` that plans inline — wait `_PLANNING_TIMEOUT_SECONDS`
   rather than the 10 s every other request gets; a plan that outlasts it is terminal for the bridge
   (`failed`), not retried."*

4. **[IMPROVEMENT] "Buys a journal of roughly 7,000 rows" assumes the harness lets a tool call run for
   300 s, and nothing in the tree says it does.** `zikaron/mcp/consolidator.py` lines 54–60. Neither
   `design/harness.md`'s table nor any research note records a per-tool-call timeout for either harness
   (the only hit is `research/claude-code-harness-contract.md:269`, which is the hook `timeout` field);
   the one measured point is 13.1 s through the bridge. If the harness cancels first, the bridge goes
   `FAILED` by design and a journal past that size fails consolidation every time — so the effective
   bound is `min(300 s, harness tool-call timeout)` with the second term unknown. Fix: qualify the
   docstring (*"if the harness lets a tool call run that long — only 13.1 s is measured"*) and add a
   *tool-call timeout* row to `harness.md`'s harness table with *unmeasured* in both cells, or measure it
   once with a stub tool that sleeps past the candidate values. A hidden assumption in a constant's
   rationale is the class `CLAUDE.md` §comments warns about; nothing in the gate compares it to anything.

5. **[NITPICK] `zikaron/install/assets.py` line 30, "the three shared prohibitions would drift silently
   between them."** Round 1's finding 6 corrected the module docstring's count at lines 13–19; this
   sentence eleven lines later still carries it, and the pinned set is now six. *"the shared rules would
   drift silently between them."*

6. **[NITPICK] `FINDINGS.md` lines 268–272, the proposed corpus-repair shape, cannot run as stated.**
   *"run the consolidator over existing long-term records through the same replay harness"* — the
   harness's `_SEED_ROWS` (`experiments/m34_gist_replay.py` lines 45–50) selects only rows a `remember`
   created, and the consolidator's verbs reach a long-term record only as a merge target. What puts each
   of the 169 live long-term rows through the gatekeeper is re-seeding them as journal entries — a query
   change in `seed`, or a `--tier long_term` flag. `CLAUDE.md` says a defect entered here carries its fix;
   say that, so the M35+ brief does not rediscover it.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-09-29

### Summary judgment

Round 2's findings are closed as the brief says, and what I could check independently holds: the
harness-table row, the `architecture.md` §Planning paragraph and the constant's comment agree with
each other and with the spike's docstring; the installed kiro server entry carries no `timeout`
(`zikaron/install/` writes one only on hooks), so the probe's condition is the shipped condition; the
reverted Round 3 clause survives nowhere but as `FINDINGS.md` Q22's paraphrase of what was refuted,
and neither golden nor fixture carries it; the write-side rule is pinned on `remember` by its
operative clause and on `amend` by its own sentence. The code is unchanged since Round 1 and still
sound. One thing stands between this and approval, and it is in the evidence rather than the text:
the amended bar's first clause — *no order survives in any gist* — is judged by a procedure that
cannot find an order, so it is shown for 23 of 105 output gists and asserted for the other 82. It is
one read to close, not a run.

### Findings

1. **[BLOCKER — cheap] The bar's no-order clause is judged by a selector that matches no order, so
   it is shown for the marked 23 output gists and asserted for the unmarked 82.**
   `design/build-plan.md` §M34 lines 4500–4507: *"no order survives in any gist … The regex selects
   what to read"*. `VERDICT_MARKER` (`experiments/m34_gist_replay.py` lines 38–43) matches three
   connectives, five `is/are <adjective>` rulings and an appended dash — no imperative, no `must`,
   `never`, `always`, `cannot`, `do not`. The one order the first run found (*"— find the run's log
   path from ps yourself"*) was caught by its dash, not by being an order. The note's reading of the
   first run is explicitly over the marked set — *"Of the nine marked rewritten gists …"*, *"Of the
   14 marked in-place gists …"* (`research/m34-gist-form-replay.md` lines 59, 63) — and the residual
   *"2 of 64"* is computed from those nine, so an unmarked verdict among the 55 unmarked rewritten
   gists, or an unmarked order among the 27 unmarked in-place ones, is uncounted on both sides of the
   gate. The re-run read all 8 rewritten rows and found a residual verdict word the regex does not
   match (*"unfixable"*), which is the shape this misses. Why it touches a decision rather than
   polish: the residual count is against a preregistered 1-in-10 bar with headroom of about four
   rows, and the 27 unmarked in-place rows of the first run were never exposed to the shipped
   `promote` text at all — an order among them is exactly the case the shipped description names
   (*"an observation rather than an order"*) and has not been tested against it. Fix, in this order:
   (a) read the 82 unmarked output gists in `~/zikaron-m34-replay/compare.md` for orders and bare
   rulings — one pass over 82 lines; (b) state the result in §"Per bar, by reading", e.g. *"The regex
   selects candidates for verdicts only and matches no imperative, so every output gist was read for
   orders and bare rulings: N among the 82 unmarked (none / quoted)"*, folding any find into the
   residual count; (c) if any of the 27 unmarked in-place rows is an order or verdict, it joins the
   re-run set, since it never met the shipped text; (d) in `build-plan.md` line 4504, after *"The
   regex selects what to read"*, add *"for verdicts — it matches no imperative, so the no-order clause
   is read over every output gist"*. If the 82 were in fact read and none found, the fix is sentence
   (b) alone; the note has to say it either way, because *"the gists that decided it"* is the
   done-when's own requirement.

2. **[NITPICK] The timeout guard is green for a constant that reproduces the defect it names.**
   `tests/test_mcp_consolidator_bridge.py` lines 251–253 assert only `> REQUEST_TIMEOUT_SECONDS`;
   `_PLANNING_TIMEOUT_SECONDS = 10.5` passes and still loses the 12.2 s plan the docstring (line
   224) cites. Pin it to the measurement: `assert timeouts["memory_plan_groups"] >= 2 * 13.1` (the
   through-the-bridge figure `consolidator.py` line 56 records) for both planning calls, or import
   the constant and assert equality plus `_PLANNING_TIMEOUT_SECONDS > 13.1`. `CLAUDE.md` asks that a
   guard be mutation-verified; this one was not against the mutation that matters.

3. **[NITPICK] `architecture.md` §Planning reads as if only a `next_group` that plans waits 300 s.**
   Lines 1523–1528: *"`memory_plan_groups` and a `next_group` that plans inline, wait
   `_PLANNING_TIMEOUT_SECONDS`"*. The client cannot know whether the service will plan — a lapsed
   lease replans on the owner's next call — so `consolidator.py` line 269 applies the 300 s ceiling to
   every `next_group`. The consequence worth one clause, because M35 owns it: on a wedged service
   (`FINDINGS.md` §"Owed work", 2026-09-29) a consolidator now holds each `next_group` for 300 s
   before it reports, not 10 s. Suggested: *"… and `next_group`, every call of which may plan inline
   after a lapsed lease and so carries the same ceiling whether or not it does — so a service that
   stops answering holds a consolidator 300 s per call"*.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-09-29

### Summary judgment

Round 3's three findings are closed as the brief says, and each checks out independently: the note
records all 82 unmarked output gists as read for orders, the timeout guard now goes red below twice
the through-the-bridge figure (`> 2 * 13.1` on both planning calls), and §Planning carries the
every-`next_group` ceiling with its wedged-service consequence. The code is unchanged since Round 1
and still sound; the goldens carry the shipped promote paragraph and neither they nor the fixture
carries the reverted Round 3 clause. What stands between this and approval is the same class as the
last two rounds and cheaper than either: the reading of the 82 found three more residuals, the note
counts them against the bar, and the bar's pass figure in `build-plan.md` still omits them — and in
the split form that sentence uses, the kept-in-place pool is now over the one-in-ten it names. One
arithmetic sentence in each file closes it. Beside it, the harness-duration measurement the 300 s
constant rests on is evidenced by the server's own log, which cannot show the half of the claim that
matters.

### Findings

1. **[BLOCKER — cheap] The bar's pass figure in the brief omits the three residuals the Round 3
   reading found, and the note does not say which denominator keeps the bar "intact".**
   `design/build-plan.md` §M34 line 4504: *"M34 passed at 3 in 72 rewritten and 1 borderline in 12
   kept in place"*. `research/m34-gist-form-replay.md` lines 73–79 now add three borderline *"is X,
   not Y"* rulings among the unmarked in-place gists of the first run and say *"Counted as residuals
   they leave the bar's one-in-ten intact"* — with no ratio. By the note's own counts the final-state
   population is 105 records: **72 rewritten** (64 + 8) with **3** residuals, and **33 kept in place**
   — the 21 first-run in-place rows never re-seeded, plus the re-run's 12 — with **4** (the three,
   plus *"tried repeatedly and never worked"*). Pooled, 7 of 105 is 6.7% and passes. Per pool, kept
   in place is 4 of 33 — **12%, over the bar's *"one gist in ten"*** — and the brief's sentence,
   written as two pool figures, invites exactly that reading. Three of the four kept residuals also
   never met the shipped promote text, which the note says (lines 77–78) and the brief does not.
   Fix: (a) in the note's §"Per bar, by reading", replace *"Counted as residuals they leave the
   bar's one-in-ten intact"* with the arithmetic — *"Counted as residuals, the final state carries 7
   verdicts or borderline rulings in 105 output gists: 3 of 72 rewritten, and 4 of 33 kept in place,
   three of those promoted before the promote condition existed and one under it"*; (b) in
   `build-plan.md` line 4504, replace the two figures with *"M34 passed at 7 in 105 by reading,
   pooled over rewritten and kept alike (3 of 72 rewritten; 4 of 33 kept, three of them never
   exposed to the shipped promote text)"* — or, if the operator judges the pools separately, the
   kept pool is over the bar and the three rows join the re-run set as Round 3's (c) proposed.
   Either way the brief and the note must carry the same count and the bar must say whether it is
   pooled: `FINDINGS.md` §"Owed work" (lines 273–274) says the corpus-repair pass is *"judged on the
   same four bars"*, and this is the bar it will be judged on.

2. **[IMPROVEMENT] The harness-duration row proves the server slept 330 s, not that the harness
   waited for it.** `spikes/m34_tool_call_duration_stub.py` lines 3–4 make the evidence the tool's
   own `stub.log` — *"so the result does not depend on what the model reports"* — and
   `design/harness.md` line 75 states *"a 330 s call **completed**"* under both harnesses, which
   `zikaron/mcp/consolidator.py` lines 57–58 and `architecture.md` lines 1528–1529 then rest on. But
   the log reads identically whether the harness delivered the result at 330 s or cancelled the call
   at its own limit and let the server sleep on: the failure the row exists to exclude is the one
   the log cannot see. kiro's `mcpServers` entries accept a `timeout` field (the row itself says
   none was set), so the harness has a per-request limit whose default the probe did not name, and
   whether that default governs a tool call is what the row asserts. Fix: if the model-side outcome
   was observed — the reply carrying *"slept 330.0s"*, or a harness error at some earlier second —
   say so in the row and in the spike's docstring (*"and the model's reply carried the tool's own
   result"*); if it was not, the measurement is one re-run with that observed, and until then the
   row and the constant's comment should say the harness half is inferred. Raised because the 300 s
   constant is what M34 ships and the row is its only support.

3. **[NITPICK] `architecture.md` §Planning lines 1527–1528, *"A plan that outlasts it leaves the
   plan bridge `failed`, not retried"*, is true of the bridge's own `memory_plan_groups` and not of a
   `next_group` that planned inline.** That path runs through `_call` (`consolidator.py` lines
   264–270) with the bridge already `READY`; a timeout there is a `TransportFailureError` to the
   model, the bridge stays `READY`, and the consolidator's next `next_group` goes straight to the
   service, where the plan may meanwhile have committed. One clause: *"…leaves the plan bridge
   `failed` when the call was `memory_plan_groups`; an inline plan on `next_group` that outlasts it
   is reported as a transport failure, and the next call retries against whatever the service went
   on to commit"*. M35 moves planning, so the sentence it inherits should be the true one.

4. **[NITPICK] `research/m34-gist-form-replay.md` line 8, *"about half real verdicts"*** — Round 2's
   parenthetical, still there: it is five of 14, which lines 63–71 then list. *"five of them real
   verdicts or an order"*.

5. **[NITPICK — outside M34's decision, so declinable under the operator's rule] `FINDINGS.md`
   lines 279–282 say the survey found *"the one servable candidate"*; the survey's own anchor table
   has a second.** `research/technical-embedders.md` line 43: `e5-small-v2`, 33M, MIT, ONNX, CoIR
   average 47.1 — above granite-30m's 47.0 — and StackOverflow-QA 83.5 against granite's 83.9, from
   the same table of the same paper; it appears in neither the servability screen (lines 96–104) nor
   the verdict. If the separate evaluation the scope fence names retests granite, the model one row
   above it on the same evidence belongs in the same run, or the note should say why not. One row in
   the screen.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-09-29

### Summary judgment

Round 4's findings are closed as the brief says, and each holds under an independent re-reading.
The bar in `design/build-plan.md` §M34 (lines 4500–4509) and the note's §"Per bar, by reading"
(lines 73–80) carry the same figure — 7 in 105, pooled; 3 of 72 rewritten; 4 of 33 kept, three of
those never exposed to the shipped promote text — and the arithmetic closes against the note's own
event-table counts (41 flipped + 64 created = 105; 41 + 85 promote-absorbed + 8 merge-absorbed = 134),
with all seven residuals quoted in the note as the bar requires. The harness row and the spike's
docstring both state the model-side observation under both harnesses; `architecture.md` §Planning
(lines 1527–1530) now separates a `memory_plan_groups` timeout (bridge `failed`) from an inline plan
on `next_group` (transport failure, next call meets what the service committed), and that matches
the code: `_call` at `consolidator.py` lines 264–270 runs with the bridge already `READY` and leaves
it so. The reverted Round 3 clause appears on no shipped surface (`.kiro/`, `tests/fixtures/`,
`zikaron/`, `design/`); the kiro `SKILL.md` golden is correctly untouched, since it spawns the agent
and embeds none of its prompt; `DESCRIPTION_BUDGET` is 1,900 as the brief's *"1,894 of 1,900"*
assumes; the amend and promote pins are in place. One sentence remains, in the one copy of the
Round 4 fact that the fix did not reach, and it is the same size Round 4 judged it. `./check.sh` has
not run; the done-when requires it green, and this verdict is on the artifact as read.

### Findings

1. **[NITPICK] The constant's comment still generalises the bridge's terminal treatment to both
   callers, which Round 4's finding 3 corrected in `architecture.md` and not here.**
   `zikaron/mcp/consolidator.py` lines 58–60: *"The bridge treats a lost response as terminal for
   the process, so a timeout here is a whole consolidation lost rather than one call."* True of
   `memory_plan_groups` (`ensure_planned`, line 174–178, moves to `FAILED` on
   `AmbiguousMutationError`); false of the other caller of the same constant — a `next_group` that
   outlasts it goes through `_call` with the bridge `READY`, raises `TransportFailureError`, and
   the next `next_group` reaches the service, which `architecture.md` lines 1527–1530 now say. A
   reader of the code learns the opposite of the normative sentence for one of the two calls, and
   M35 is the milestone that will read this constant. Replace the sentence with: *"For
   `memory_plan_groups` the bridge treats a lost response as terminal for the process, so a
   timeout there is a whole consolidation lost; a `next_group` that outlasts it is one call lost,
   and the next call meets whatever the service went on to commit."* The test docstring at
   `tests/test_mcp_consolidator_bridge.py` lines 224–226 names the plan's lost response and is true
   as written; leave it.

VERDICT: APPROVED
