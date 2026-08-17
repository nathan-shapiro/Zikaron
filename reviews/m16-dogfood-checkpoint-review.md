# Review — research/claude-code-dogfood-checkpoint.md

## Round 1 — 2026-08-16

**Summary judgment.** This is a strong evidence note: every load-bearing transcript quote I spot-checked
verifies against the actual JSONL files (including `claude-sonnet-5` ×8 in the subagent transcript), the
§9.1 policy quotes match `write_policy.py:74` and `:94` exactly, the §7 double-run explanation matches
`core/consolidation/serving.py:360` verbatim, and the scope fence holds — I found no numeric cross-harness
comparison anywhere; every mention of the pre-migration numbers is a condition contrast, and §10 restates
the fence. But it is not shippable as M16's evidence yet: one done-when clause of the brief is entirely
unaddressed (and my own probe of the evidence suggests its answer is currently "not observed"), §7's
"independent ground truth" phrase misstates the strength of its evidence, and three sets of numbers inside
the note do not reconcile with each other — in a corpus whose binding rule is naming the quantity before
quoting a number, those are blockers.

### Findings

1. **[BLOCKER] The brief's subagent-policy done-when clause is unaddressed, and the evidence on disk says
   it is currently unmet.** `design/build-plan.md` §M16 done-when: *"a subagent is observed to have
   actually **received** the write policy, rather than only our side being observed to emit it."* The note
   never mentions `SubagentStart` or policy receipt at all. The only subagent spawned in the whole
   checkpoint is the consolidator — and per `design/harness.md` §Subagents (*"inject the policy on
   `SubagentStart` for every `agent_type` **except `zikaron-consolidator`**"*) it is the one subagent that
   must *not* receive it. I grepped its transcript
   (`~/.claude/projects/-home-nathan-zk-dogfood/2ec96274…/subagents/agent-a7279cf475665f84c.jsonl`) for the
   policy's text: zero occurrences, while the main-session transcript carries it twice — so the
   *suppression* half worked and is verifiable from a file the note already read for the model id. Fix,
   concretely: (a) spawn one ordinary (non-consolidator) subagent in the throwaway and grep its transcript
   for the policy text — one cheap turn; report the result in a new subsection; and (b) record the
   consolidator suppression as verified, since that observation is free and is the other half of the same
   harness.md rule. If (a) is instead deliberately deferred, the note must say so explicitly and say where
   the clause gets satisfied — silence against a named done-when is exactly what a fresh session will
   misread as "done".

2. **[BLOCKER] §7's "independent ground truth" over-claims on both words, and the phrase is already
   propagating.** The writing agent is `opus` (`experiments/dogfood/zikaron-dogfood.md` frontmatter) and
   the consolidator is `sonnet` — same model family — and both judgments are downstream of prompt texts
   that were revised in the *same anti-merge direction* on 2026-08-04 (the write policy's gist rules; the
   consolidator's "prefer sharp distinct records" principle, which §7 itself notes the consolidator quoted
   back verbatim). Two correlated-prompt, same-family models agreeing to split is *concordance*, not
   independence — and neither is *ground truth*; no operator or human label of the pair exists. The
   zero-merge caveat paragraph is adequate as far as it goes, but it does not neutralize the headline
   phrase, which FINDINGS.md:537–539 has already inherited ("corroborated … independently"). Suggested
   edit: retitle the claim to "the first split verdict with a concordant second judgment", and add one
   sentence naming the two correlations (shared model family; both prompts revised toward splitting on
   2026-08-04), so a future reader weighing merge-criterion evidence does not count this as two
   independent votes.

3. **[BLOCKER] Three sets of numbers inside the note do not reconcile, in a corpus whose binding rule is
   "name the quantity before quoting a number about it."**
   - **§10:** *"0 of 5 searches came back empty once the store was non-empty (the two empty ones hit an
     empty store on turn 1)"* — self-contradictory as written: 2 of the 5 *were* empty. The quantity is
     **0 of 3** post-seed searches; say that.
   - **§1 vs §10:** §1's gate-3 row counts *"5 writes and 6 reads"*; §10's table totals 6 writes
     (4 `remember` + 2 `amend`) and 8 reads (5 `search` + 3 `fetch`), and no per-session subset matches
     5/6 either. Either the §1 tally includes/excludes consolidator calls or was taken mid-checkpoint —
     name which calls it counts, or recompute from the store.
   - **§7 and §12:** *"third consecutive zero-merge outcome (`~/Memory` run 2: 0 of 31; here 0 of 2)"* and
     §12's *"Three consecutive runs have merged nothing"* — the parenthetical names **two** runs. Either
     name the third (if one exists — M12's fresh-directory e2e consolidation?) or fix the ordinal to
     "second". FINDINGS.md:540 carries the same count and should be fixed from the same answer.

4. **[IMPROVEMENT] §2 credits a mechanism whose counterfactual was not checked.** *"Had the policy carried
   bare names, the `select:` would have missed and the agent would have concluded there were no memory
   tools — silently"* is stated as fact, but ToolSearch's matching behaviour on a bare `zikaron_search`
   (exact vs. substring/fuzzy) was never probed. One headless turn with a bare-name `select:` settles it;
   otherwise write "would likely have missed". Same section, smaller: the deferral re-reading of
   `installer-probe` §9 assumes MCP tools are also deferred under headless `claude -p`, which was only
   observed interactively — "different conditions" hedges this but should name it, since it is the one
   assumption the competing explanation stands on. (The competing-vs-refuting framing itself is honest:
   "Neither reading is refuted (n=1 each)" is exactly right.)

5. **[IMPROVEMENT] §11(a)'s decline is sound on its main premise — verified: `install/main.py:157`
   resolves `Commands.from_this_interpreter()` once, and `test_install_targets.py:311` pins the Claude
   consolidator's `["--mode", "consolidator"]` hermetically — but two sentences overstate.**
   (a) *"both targets therefore write the same two command strings"*: same **paths**, but kiro's hook
   command is `shlex.quote`d and Claude's is not (`entries.py::hook_command_string` vs
   `claude_hooks_value`), and Claude's consolidator `.mcp.json` entry is a hand-written literal in
   `claude_mcp_servers_value` rather than the shared `mcp_servers_value` builder — so there *is* a
   Claude-only spelling, covered by the golden assertion, not by the shared path the sentence implies.
   (b) *"That is precisely what `tests/test_install_claude_live.py` now tests"*: the live tier covers the
   prompt hook, the **primary** server, and label linking — it never touches the consolidator server, the
   skill, or the subagent spawn path. That leg's only end-to-end evidence is this checkpoint's single
   manual run. Either say that residual out loud (one sentence), or add a fourth live test that spawns the
   consolidator. The decline itself can stand; its stated coverage claim cannot.

6. **[IMPROVEMENT] §10's attribution affordance decays silently, and half the note's evidence base decays
   with it.** Transcripts under `~/.claude/projects/` are subject to Claude Code's retention cleanup
   (`cleanupPeriodDays`, default ~30 days). "Solved externally" is therefore time-limited: a session
   following §10's advice months from now finds the transcripts gone — and so is every quoted reasoning
   line's source, since the note says *"Every quoted reasoning line in this note came from there."* The
   header's own lesson (the `/tmp` snapshots) applies to the other half of the evidence: copy the two
   session transcripts and the subagent transcript next to `~/zikaron-m16-dogfood-evidence.db`, and
   soften "solved" to "answerable post hoc while transcripts survive", naming the retention setting.

7. **[IMPROVEMENT] §1 states an unmeasured inference as fact, and omits its safety-relevant converse.**
   *"this gate would **not** have appeared in an already-trusted directory"* was not measured — mark it
   inferred. And if it is true, then installing Zikaron into an *already-trusted* directory pre-approves
   two tool servers with **no warning ever shown to anyone** — the first-entry dialog is the only
   disclosure point, and it is skipped precisely where installs will normally happen (a developer's own
   trusted projects). One sentence naming that asymmetry belongs in §1; it is the more consequential half
   of the trust observation.

8. **[IMPROVEMENT] Session 2's dedup offer is in the §10 table (`dedup offered: 1`) and nowhere in the
   prose.** §6 calls session 1's offer *"the eighth … and the eighth judged a false positive … the highest
   cosine among them"* — but the ninth offer's cosine and resolution are unreported, so "highest" is
   asserted against an incomplete series and the false-positive streak's current length is unstated. Add
   one sentence: what session 2's offer paired, its cosine, and how the agent resolved it.

9. **[IMPROVEMENT] §9.4 contradicts itself and over-generalizes in one sentence.** *"the agent invented a
   soft link from the only address it thought it had"* is refuted two lines later by *"The uuid was in
   hand both times."* The stronger, correct finding: the agent **had** the uuid and *preferred* gist
   prose as the human-readable address — twice, in two sessions. And *"n=2 makes this a habit, not an
   accident"* outruns n=2 from one agent/model; say "twice in two sessions by one agent — a pattern worth
   designing for" and let the reader weigh it.

10. **[NITPICK] §3's interval is wrong at both ends.** Intact at 9,503 units ⇒ cap ≥ 9,503; truncated at
    10,502 ⇒ cap < 10,502. So cap ∈ **[9,503, 10,502)**, not "(9,503, 10,502]". The conclusion (10,000)
    is inside both, so nothing downstream moves — but the same wrong interval is already propagated into
    `design/harness.md` §"Injection budgets" (line ~335); fix both from one edit.

11. **[NITPICK] The header date is 2026-08-17 while the repository's today is 2026-08-16.** If the
    sessions' UTC timestamps (§8's 01:54:29) straddle midnight, say so and name the timezone once;
    otherwise a reader diffing this note against commit dates will conclude one of them is wrong.

12. **[NITPICK] §4's "it earns its sentence" pronounces a verdict on the proposal gate from n=2 firings.**
    The keep/wind-down decision has its own named criterion (FINDINGS open question 1: searches-per-turn
    rising while fetch-follow falls below 32%). "Fired as designed, twice, unprompted" reports the same
    evidence without pre-empting the criterion.

13. **[NITPICK] §9.1 is honest and well-supported — the withdrawal quotes the false version, the two
    policy lines are quoted accurately, and the resolution is genuinely deferred — but two touches would
    sharpen it.** (a) *"a policy that cannot be consistently followed"* slightly overstates: the section
    itself calls the agent's specificity-precedence resolution "correct policy-following", so the defect
    is *no stated precedence between two rules that disagree on this class*. (b) The conflict is stronger
    than the two quoted lines: `write_policy.py:80` ("Failures and their causes, above all silent ones")
    *also* admits the symlink item, so three policy clauses vote 2–1 and the policy still loses — worth
    citing when the M16 policy change is argued.

**What I verified and am deliberately not raising:** the scope fence (no cross-harness instrument
comparison anywhere, including implicit ones); the §7 double-run explanation against
`serving.py:354–366`; the §2 tool-count split (5/4, D32); the §11(b) fixed-in-M15 claim against
`test_install_harness.py::_require_kiro` and `_require_claude`; the transcript quotes in §4, §5, §7, §8;
the existence and location of both evidence artefacts; and the §3 astral rows' internal consistency
(bytes and code points genuinely refuted on the data shown).

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-08-16

Scope widened per the brief: the note, the shipped policy change (`zikaron/hook/write_policy.py` +
`design/write-policy.md`), `design/harness.md`'s new/changed sections, `tests/test_install_claude_live.py`,
and FINDINGS' M16 block plus open questions 1, 2, 3, 11, 12, 13, 14, 15.

**Assumption, stated:** this review thread has no shell, so I could not run SQL against
`~/zikaron-m16-evidence/store.db`. I verified instead by (a) binary/text greps of the evidence artefacts —
both session ids, both consolidation run ids (`3123f762`, `aa03e70c`) and `surface_call` present in
`store.db`; `claude-sonnet-5` appears **exactly ×8** in `consolidator-subagent.jsonl`, matching §7; cosines
0.876 (×2, session 1) and 0.8246 (session 2) present in the respective transcripts, corroborating §6's
nine-offer series — and (b) full internal reconciliation of every number the note quotes (6+8 = the §10
table's totals; 0.83 = 5/6; 9 = 7 prior offers + 2; 0-of-3 vs 2-of-5 consistent). The exact row counts
(38 events, 4 memories) are not independently re-derived; everything derivable without SQL checks out.

**Summary judgment.** The note itself is now in genuinely good shape: all thirteen round-1 findings were
accepted and twelve of them landed correctly *in the note*, §7b's "closed early in M15" claim verifies
against `installer-probe` §9 word for word, and the WAL discovery is exactly the kind of lesson this corpus
exists to keep. The dominant remaining defect is **propagation**: four of the round-1 corrections were
applied at the point of the finding and not in the copies — `design/harness.md` and `FINDINGS.md` still
carry the pre-correction numbers, the withdrawn "independent" headline, the retracted "earns its sentence"
verdict, and two flat assertions the note now hedges. The policy change is well-argued and does resolve the
observed contradiction, with one residual its rationale should name; the new test file is sound code with
one docstring claim the corpus's own probe refutes.

### Findings

1. **[BLOCKER] Round-1 numeric corrections did not reach the propagated copies.** Two places still carry
   numbers the note now refutes:
   - `design/harness.md:279` (§"Three approval gates", gate-3 row): *"no prompt, across 5 writes and 6
     reads"*. The corrected count is **6 writes and 8 reads** (4 `remember` + 2 `amend`; 5 `search` +
     3 `fetch`) — the 5/6 figure is from the pre-recount draft, i.e. it is the number the truncated
     snapshot produced, surviving in the *normative* document after the note fixed it.
   - `FINDINGS.md:213–214` (item 2): *"0 of 5 searches empty once the store was non-empty"* — the exact
     self-contradiction round-1 finding 3 flagged (2 of the 5 **were** empty; they hit the empty store).
     The note now says it right (*"of the 3 searches issued after the store held anything, 0 came back
     empty"*, note line ~390); FINDINGS, the always-loaded file, still says it wrong.
   Fix both from the note's §1/§10, which are correct.

2. **[BLOCKER] Withdrawn verdict language survives as headlines in three places whose own bodies refute
   it.** Round-1 findings 2 and 12 were accepted and fixed in the note's *bodies*, but:
   - `research/claude-code-dogfood-checkpoint.md:199`: the §7 **title** still reads *"a split with
     independent corroboration"*, two paragraphs above *"Concordance is not independence, and neither is
     ground truth."* Retitle: *"a split with a concordant second judgment"*.
   - `FINDINGS.md:544`: open question 12's new lead sentence — *"M16 adds the first split judgment with
     independent ground truth"* — is **new text written this round**, not a preserved original, and it
     restates the withdrawn phrase in bold while the withdrawal sits five lines below. A skimming reader
     (the design use-case for bold leads) inherits exactly the claim round 1 blocked. Reword the lead to
     "first split judgment with a concordant second judgment".
   - `FINDINGS.md:218–219` (item 2): *"it earns its sentence, and the researcher's objection to it is
     withdrawn"* — the note deliberately retracted that exact verdict (§4: *"deliberately not 'it earns
     its sentence', because the keep-or-wind-down decision has its own named criterion"*). Keep the
     objection-withdrawn fact if it stands; drop "earns its sentence" for the note's own "fired as
     designed, twice, unprompted".

3. **[BLOCKER] `design/harness.md` states two unmeasured claims as fact, against its own preamble rule
   ("every Claude Code claim … is either traceable to a numbered section … or explicitly marked
   unmeasured or decided").**
   - `harness.md:288–289`: *"Note gate 1 does **not** fire in an already-trusted directory"* — flat
     assertion, no citation, no marking. The cited source (note §1) says *"Inferred, not measured"*, a
     correction round-1 finding 7 forced. Write "presumably does not fire — inferred, unmeasured
     (dogfood-checkpoint §1)". While there: the converse the note now carries — install into an
     already-trusted directory pre-approves two servers with **no disclosure ever shown** — is the more
     consequential half and belongs in this normative section, one sentence, beside the
     `--no-trust-tools` escape it motivates.
   - `harness.md:300–302`: *"A policy carrying bare names **would** leave an agent unable to find them"*
     — the note (§2) hedges this to *"likely"* precisely because `ToolSearch`'s matching on a bare name
     was never probed (round-1 finding 4, accepted). The normative doc asserts the unprobed
     counterfactual flatly. Add "likely" or the one-headless-turn probe.

4. **[BLOCKER] `tests/test_install_claude_live.py:144–157` — test 2's docstring claims a composition the
   corpus's own probe says this test cannot check.** The docstring: *"it is the only check that
   `.mcp.json` plus `enabledMcpjsonServers` plus `permissions.allow` compose into a callable tool."* But
   the test drives **headless** `claude -p`, and `installer-probe` §8 measured that headless runs reach
   the tool **with the approval keys and with an empty settings file alike** ("a headless run approves
   everything" — the note's §1 and FINDINGS both state it). So this test passes identically if the
   installer omits *both* approval keys — the exact conflation drift `harness.md` §"What the install
   reports" warns was made once — and by M14's own break-the-code discipline the composition claim is
   vacuous. The assertion itself is still worth keeping (registration → callable tool, end to end); fix
   the claim: (a) rewrite the docstring to say what headless can establish, citing `installer-probe` §8
   for why the approval keys are out of its reach and dogfood §1 for where they were measured; (b) the
   checkable half is hermetic — extend `test_the_installed_settings_name_this_harness_own_triggers`
   (line 212) to also assert `enabledMcpjsonServers` and `permissions.allow` contents, which actually
   guards the conflation drift.

5. **[IMPROVEMENT] The policy change resolves the observed contradiction but its rationale implies the
   resolution is lossless, and one residual conflict survives unstated.** The clause
   (`write_policy.py:94–97`) admits a general fact *as the decision it forced* — which covers the
   dogfood case and most debugging cases, since discovery usually forces a fix, a workaround, or a
   ruling-out. The residual: a general fact that **cost real time but has forced nothing here yet**
   (learned incidentally, or mid-investigation before any code exists). On that class,
   `write_policy.py:112–114` (*"Err toward writing … If you just spent real time discovering something,
   record it"*) and the new clause give opposite instructions — the same no-stated-precedence structure
   §9.1 diagnosed, at smaller scale — and the pressure of "err toward writing" is what would make an
   agent *manufacture* a decision-costume record, the brief's second failure mode.
   `design/write-policy.md:336–340` says *"the fact is admitted, in applied form"*, which quietly
   presumes an applied form always exists. Three one-sentence fixes in §"Why general facts enter as the
   decision they forced": (a) name the residual as an **accepted loss with a deferral window** — the
   fact enters when it first forces something, and until then the next agent may re-pay it; (b) state
   which clause wins on that residual (the exclusion, presumably, since "no decision" leaves nothing to
   record — say so); (c) carry the *"unmeasured; the write corpus behind it is n=4"* caveat that the
   note (§9.1) and FINDINGS (oq13) both carry but the normative design doc — the place a future
   policy-tuner reads — does not. The test-runner example itself is good: language-neutral, and its
   admitted form is consistent with the "constraints with their reason" bullet, so it teaches the right
   generalisation.

6. **[IMPROVEMENT] "so it is a habit" — the n=2 overstatement round-1 finding 9 removed from the note is
   reintroduced verbatim in both new copies.** `design/write-policy.md:353–354` (*"Observed twice in one
   day, once per session, so it is a habit"*) and `FINDINGS.md:648–649` (*"so it is a habit rather than
   an accident"*). The note's corrected form — *"twice in two sessions by one agent on one model is a
   pattern worth designing for, not yet a law"* — is the one the author accepted; use it in both. The
   rest of both rationale texts (uuid rejection, subject-reference, consolidation-rewrites-gists) is
   sound and verified against `fetch`'s no-active-filter behaviour as claimed.

7. **[IMPROVEMENT] `tests/test_install_claude_live.py:30–32` — the module docstring draws the
   non-determinism boundary in the wrong place.** *"That one test is therefore the only place in this
   repository where a model's choice can turn the suite red"* is false:
   `test_both_clients_resolve_one_session_label` (line 180) also asks a model to call a named tool, and
   `assert mcp_sessions` (line 204) goes red if the model declines. Two tests sit on the model-choice
   side of the boundary; say so. Two small companions: test 3 discards `_turn`'s result, so its
   failures carry no `claude` stderr while tests 1–2's do (capture and include it); and test 1's
   surface_call-missing message (line 140) would be more actionable if it also named
   `hook.log`'s path the way `_events`' no-store branch does.

8. **[IMPROVEMENT] The `漢` row of the budget table is arithmetically impossible under its own label, in
   both copies** (note §3, line 113; `harness.md:329`). 9,016 code points of pure `漢` is 9,016 × 3 =
   **27,048** UTF-8 bytes, not the printed 27,016. The printed numbers are only consistent as 9,000 `漢`
   **plus 16 ASCII marker characters** — while the astral rows are exact multiples of 4 (6,000 × 4 =
   24,000; 4,600 × 4 = 18,400), i.e. content-only with markers excluded. So the table's rows count
   different things without saying so. No conclusion moves (the margins dwarf 16 units, and all three
   refutations survive either bookkeeping), but this is the corpus's name-the-quantity rule applied to
   its own headline measurement: add one footnote stating what each row's counts include, or restate
   the `漢` row content-only (9,000 / 9,000 / 27,000).

9. **[IMPROVEMENT] The evidence snapshot is a live, writable WAL-mode database — the exact shape the
   note's own header lesson warns about.** `~/zikaron-m16-evidence/` contains `store.db-wal` and
   `store.db-shm` beside `store.db`; the `-wal` is empty **today**, so nothing is currently missing,
   but the sidecars mean the snapshot has been opened since it was taken, and any future writable open
   can put frames back into the `-wal` — at which point "read `store.db`" silently under-reports again,
   in the directory the note tells future sessions to treat as canonical. Freeze it: checkpoint and
   drop WAL mode (`PRAGMA journal_mode=DELETE`, or re-snapshot via `VACUUM INTO`), delete the
   sidecars, and `chmod a-w` all four artefacts. The note's "Evidence, all of it" list should then
   match the directory's contents exactly.

10. **[IMPROVEMENT] Two summaries lag their sections' own corrections.** (a) `harness.md:58` (the D34
    table's injection-budget row) still says *"fixed **10,000 characters**"* citing §5/§7a, while
    §"Injection budgets" below now exists to pin that very word to **UTF-16 code units**, measured
    (dogfood §3). The table is the quick normative reference; say "10,000 UTF-16 code units" there and
    cite the checkpoint. (b) `FINDINGS.md:325` opens *"the attribution problem is solved outside the
    store, for free"* with no expiry caveat — round-1 finding 6's "solved overstates it" was accepted
    in the note (§10: answerable *while the transcripts survive*, `cleanupPeriodDays`); add the clause
    here too, since oq1 is where a future session will read the claim.

11. **[NITPICK] Dates disagree across the change with no UTC note outside the checkpoint.**
    `design/write-policy.md:322` says *"found by dogfooding on 2026-08-17"* and `FINDINGS.md:614`/`:669`
    say *"shipped 2026-08-17"*, while `FINDINGS.md:155` says the same work is *"DONE, 2026-08-16"* and
    the commits will be dated 2026-08-16. Only the note carries the UTC explanation. Pick one convention
    (local dates, per the repository) and apply it, or annotate UTC where 08-17 stays.

12. **[NITPICK] Note §9.1's present-tense, line-cited quotes now point at revised text.** *"The policy
    says both of these: `write_policy.py:74` … `:94` …"* — line 94 now holds the **new** clause, so a
    reader checking the citation finds different words. Change to "the policy as dogfooded said" and
    mark `:94` as since revised (the section's closing paragraph already says so; the quotes' framing
    should agree with it).

13. **[NITPICK] "that quadrant is the largest one" is asserted as fact** (`design/write-policy.md:
    326–328`, `FINDINGS.md:602–604`) on no measurement — "plausibly the largest" is what the evidence
    (one session, one corpus) supports. Also `FINDINGS.md:57`'s phase header still reads *"M16 is the
    last milestone, and it is the next thing to do"* above an item 0 whose dogfooding half is DONE;
    reconcile when M16 lands.

**What I verified and am deliberately not raising:** the drift test
(`test_hook_write_policy.py::test_prompt_matches_the_design_document_exactly`) does compare the parsed
fence byte-for-byte and the two texts match, both new paragraphs included; the new clause does resolve
§9.1's observed case (the symlink gotcha enters as the code decision it forced); §7b's "closed early in
M15" verifies against `installer-probe` §9, which contains the canary-subagent verbatim-receipt observation
and itself claims the done-when clause; oq13's "the consolidator prompt needed no mirror" — grep of the
shipped package finds scope language nowhere outside `write_policy.py`; the dogfood agent's frontmatter is
`model: opus`, supporting §7's same-family argument; the corrected interval [9,503, 10,502) landed in both
files; round-1 findings 5, 6, 8, 9, 10, 11, 13 are all correctly resolved in the note; the ×3
bytes-per-unit arithmetic in `harness.md` §"Injection budgets" is right; the live tier's env-hygiene claim
matches `conftest._no_inherited_harness_environment` (autouse) and its fail-not-skip claim matches
`pytest_runtest_makereport`; and the scope fence still holds — no cross-harness instrument comparison
anywhere in the revised note or FINDINGS.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-08-16

Confirming pass, same scope as round 2. **Assumption, stated:** this thread has no shell, so three
things in the freeze claim are not independently verifiable here: the read-only bits, `journal_mode`,
and the store's exact row counts. What *is* verifiable was checked: `~/zikaron-m16-evidence/` contains
exactly the four named files and no `-wal`/`-shm` sidecars, matching the note's "four files, no
others".

**Summary judgment.** All thirteen round-2 findings landed, and I recounted the ones that could be
recounted: the corrected numbers are internally consistent everywhere I could re-derive them, the
policy prompt reads coherently end to end with no clause undercutting another, and the new test
assertions do what their messages claim against the real installed file. But the round-2 fix to §7b
introduced a fresh miscount — I measured the transcripts and the note's "1 occurrence" is wrong under
its own stated unit — and one pre-M16 "unmeasured" claim about the approval keys survives in the
normative `harness.md` and in FINDINGS' resume block, directly contradicting the "measured in M16"
sections of the same two files. Both fixes are one-sentence; neither is optional in a corpus whose
binding rule is naming the quantity.

### Findings

1. **[BLOCKER] Note §7b's grep count is wrong, and the round-2 revision replaced a correct count with
   an incorrect one.** The note (line ~266): *"Grepping the policy's opening line ('memory store
   holding tribal knowledge'): **0 occurrences** in the consolidator's subagent transcript, **1** in
   the main session's."* Measured against the frozen evidence: the policy's opening line appears
   **twice** in `2ec96274….jsonl` (and twice in `998d776e….jsonl`) — once in a `"stdout"` field (the
   hook's recorded emission) and once in a `"content"` field (the injected receipt), both inside one
   JSONL record — and 0 times in `consolidator-subagent.jsonl`. Round 1 recorded "twice" against the
   live transcript; "1" is what a *line*-count grep (`rg -c` / `grep -c`) reports because JSONL puts
   both occurrences on one line. Two smaller defects in the same sentence: the phrase as quoted
   matches **zero** times literally, since the transcript text is `memory store holding **tribal
   knowledge**` with the markdown emphasis inline; and the load-bearing half (0 in the consolidator's)
   survives under every phrasing, so no conclusion moves. Fix, and it makes §7b *stronger*: state 2
   occurrences in one record, name the two fields — the transcript separately records emission
   (`stdout`) and receipt (`content`), which is precisely the emit-versus-receive distinction the
   done-when clause draws — and quote the greppable literal.

2. **[BLOCKER] The pre-M16 "documented, unmeasured" claim about the two approval keys survives in two
   places whose own files now say "measured".**
   - `design/harness.md:495–499` (§"What the install reports rather than enforces", first bullet's
     closing paragraph): *"**That either key has its intended effect is documented, unmeasured**
     (`installer-probe` §8) … neither property is observable without an interactive session. M16.
     Until then the install *also* states the approval step in its output…"* — "M16" was a forward
     pointer and M16 has now answered it: §"Three approval gates" 200 lines above says *"Measured
     interactively in M16"* with the citation. The normative document says both "measured" and
     "unmeasured" about one fact — the exact "closed and open about one defect" failure M14's rounds
     named. Rewrite: the effects are measured interactively (dogfood-checkpoint §1; §"Three approval
     gates" above); the install *still* states the approval step in its output, because no
     install-time or headless check can verify the effect (`installer-probe` §8) — the belt-and-braces
     rationale survives with its reason corrected.
   - `FINDINGS.md:84–96`, the "M16 inherits four things" block, is present-tense stale in the
     always-loaded file: (a) *"are **documented, unmeasured**"* (now measured — same file, item 0,
     "What it settled: three approval gates"); (c) *"the astral-character injection-budget bisection,
     **open** since M14"* (now closed — same file, oq11: "CLOSED … measured in M16"). Items (b) and
     (d) are likewise resolved by the checkpoint. Rewrite the block in past tense with outcomes, or
     delete it and point at item 0; while there, reconcile line 108's *"M16 is outstanding"* with the
     phase header's "it is landing".

3. **[IMPROVEMENT] `zikaron/harness/spec.py`'s docstrings still call the unit unmeasured and name the
   astral experiment as future — the remaining copy of the corrected claim, and the one a seam-editor
   actually reads.** The `BudgetUnit` docstring (~lines 66–74): *"which kind of character … is
   unmeasured … The experiment that would settle it is a bisection run with an astral character"* —
   M16 ran it. `exceeds_injection_budget` (~lines 108–112): *"which of them a character-denominated
   harness actually counts is unmeasured (see `BudgetUnit`). Counting the larger of the two is what
   keeps this a bound rather than a guess."* The behaviour is right and unchanged, but the rationale
   is now wrong in a way that invites a bad edit: a future reader is told UTF-16 counting is an
   optional conservatism over an unknown, when the measurement says a `len()`-based count would be
   *incorrect*, not merely less safe (6,000 astral code points truncate at a 10,000 cap). Update both
   docstrings to cite `research/claude-code-dogfood-checkpoint.md` §3 as the measurement, per the
   project's own comments-record-measured-reasons rule.

4. **[IMPROVEMENT] Round-1 finding 9's self-contradiction, fixed in the note, survives verbatim in
   FINDINGS open question 15.** `FINDINGS.md:670–673`: *"the agent built a soft link from the only
   address it thought it had"* — refuted three lines later by *"The uuid was in hand both times, in
   the dedup payload and in its own `fetch`."* The note's §9.4 carries the corrected reading (had the
   uuid, *preferred* prose), and the design conclusion depends on which is true — "preferred prose"
   is what motivates subject-references over better uuid exposure. Replace the clause with the note's
   form: the agent had the uuid and chose gist prose as the human-readable address.

5. **[NITPICK] FINDINGS oq13's bold lead asserts what its own tail hedges.** `FINDINGS.md:621`:
   *"**The conflict is one quadrant and it is the largest one**"*, with *"plausibly lives there — an
   argument from experience, not a measurement"* two sentences later; `design/write-policy.md:327–328`
   has the corrected *"plausibly the largest"*. One word: "and it is plausibly the largest one" — the
   same bold-lead-versus-body pattern round 2 blocked in oq12.

**What I verified and am deliberately not raising:** every round-2 finding landed where claimed —
`harness.md:279` says 6 writes / 8 reads; FINDINGS item 2 says 0 of 3 post-seed searches; the §7 title
and FINDINGS oq12's lead both say "concordant second judgment"; "earns its sentence" survives only
inside its own retraction; both "habit" copies use the hedged form; `harness.md:288–294` marks gate 1
inferred/unmeasured and carries the no-disclosure converse; the bare-names counterfactual is "likely"
in both files; the live test's docstrings draw the model-choice boundary at the right two tests and
test 2's docstring correctly disclaims the approval keys with the §8 citation; the hermetic test's
set-equality assertions on `enabledMcpjsonServers` and `permissions.allow` resolve through
`MCP_SERVER_NAME`/`CONSOLIDATOR_AGENT_NAME` to the exact server names `entries.py` writes, guarding
drift in both directions; test 3 captures `result` and includes stderr, test 1 names `hook.log`'s
path; the 漢 footnote's arithmetic is right in both copies (27,048−27,016=32; astral rows exact
multiples of 2 and 4); the D34 table row says "10,000 UTF-16 code units" with the citation and the
Skill row is marked measured citing §7; the interval [9,503, 10,502) stands in both files with 10,000
inside; the note's numbers reconcile internally (0.83 = 5/6; 6+8 = the §10 table; 9 offers at
0.80–0.876 with 0.876 the maximum; 27/2 vs 38/4 matches FINDINGS' snapshot lesson; 377→1025 tokens,
1→3 chunks at `chunk_max_tokens` 450); dates are local 2026-08-16 everywhere with UTC explained once
in the note's header; §9.1's quotes are reframed as "the policy as dogfooded said" with `:94` marked
revised, and its 2–1 clause count is correct against the shipped text; the policy prompt read end to
end is coherent — the new general-fact clause, its test-runner example, the subject-reference rule
and "err toward writing" cohere, with the residual conflict named and adjudicated in
`design/write-policy.md` §"Why general facts enter as the decision they forced" alongside the n=4
caveat; every done-when clause of `build-plan.md` §M16 is addressed in the note, including both M15
observations (one declined with the premise corrected, one already fixed) and §7b's explicit
handling of the receipt clause via `installer-probe` §9; and the scope fence holds — no cross-harness
instrument comparison anywhere, and the checkpoint consolidation ran on the dogfood store, not
`~/Memory`.

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-08-16

Same scope as rounds 2 and 3, plus the post-round-3 table revert the brief flagged. **Assumption,
stated:** no shell in this thread, so the evidence files' read-only bits, the store's `journal_mode`,
its exact row counts, and the quoted `./check.sh` result (1702 passed) are taken on the brief's word.
Everything file-derivable was re-derived independently, including the §7b recount.

**Summary judgment.** The checkpoint note itself is now clean: I recounted §7b against the frozen
transcripts with an occurrence-level (not line-level) grep and every number and field attribution in
it is exactly right, and all five round-3 fixes landed correctly in the files they named. But the
pattern the brief warned about has happened a third time: the parser-constraint paragraph added to
`design/harness.md` after round 3 was inserted **mid-sentence**, splitting the section's load-bearing
conclusion in two, in the document whose preamble declares it normative for every harness-coupled
fact. And the round-3 propagation sweep stopped at the files round 3 named: shipped code still
carries one copy of each corrected claim (`install/targets.py` says the approval keys are
"documented, unmeasured"; `core/indexing/chunking.py` and `tests/test_harness_table.py` still call
the budget unit unmeasured/unknown). One garbled normative paragraph is a must-fix; the rest is the
same finding class round 3 tagged improvement, at improvement strength.

### Findings

1. **[BLOCKER] The post-round-3 paragraph in `design/harness.md` §"Injection budgets" was inserted
   mid-sentence, garbling the section's conclusion.** Line 350 ends *"…**UTF-16 code units survive
   all five**, with the cap in"* and line 351 — with **no blank line between them** — begins the new
   paragraph *"**Why the D34 table above still says "characters" rather than the measured unit.**"*
   Rendered, the normative document reads *"…with the cap in **Why the D34 table above still
   says…**"*, and the interrupted sentence's own ending — *"**[9,503, 10,502)** — intact at 9,503
   puts it at or above, truncated at 10,502 puts it strictly below. So
   `HarnessSpec.exceeds_injection_budget`…"* — resumes as an orphaned paragraph at line 362, eleven
   lines later, opening with a bare interval as its bold lead. Fix: rejoin the sentence
   (*"…survive all five, with the cap in **[9,503, 10,502)** — intact at 9,503 puts it at or above,
   truncated at 10,502 puts it strictly below"*, continuing into the `exceeds_injection_budget`
   conclusion) and move the parser paragraph after it, as its own paragraph. The paragraph's
   *content* is correct and I verified its mechanism independently: `test_harness_table.py`'s
   `_NUMBER = r"\d[\d,]*"` matches the "16" in "UTF-16" after `_SECTION_REFERENCE` stripping, so a
   cell naming the measured unit yields two numbers and `_quantity` raises — and the reverted cell
   ("fixed **10,000 characters**…") parses to exactly (10000, "characters") against the spec. This is
   the third consecutive round in which a fix introduced a defect; the next edit to this section
   deserves a rendered-markdown read before it lands.

2. **[IMPROVEMENT] The approval-keys correction has one surviving copy, in shipped code:
   `zikaron/install/targets.py:564–566`.** `_merged_permissions`'s docstring: *"That these entries
   actually remove the per-call prompt is **documented, unmeasured** — the same standing
   `enabledMcpjsonServers` already ships on, and for the same reason: a headless run approves
   everything, so the property cannot be observed without an interactive session. M16."* The "M16."
   forward pointer has been answered — both keys are measured (`dogfood-checkpoint` §1;
   `harness.md` §"Three approval gates") — so this docstring now contradicts the normative document,
   against the project's own comments-record-measured-reasons rule, in the function a future
   installer-editor reads. Rewrite on the pattern round 3's harness.md fix established: measured
   interactively in M16 (cite §1); the install still states the approval step in its output because
   no install-time or headless check can verify the effect (`installer-probe` §8), so nothing shipped
   can notice a key silently failing.

3. **[IMPROVEMENT] The budget-unit correction (round-3 finding 3, fixed in `spec.py`) has three more
   surviving copies, in the two files a bound-editor reads next.**
   - `zikaron/core/indexing/chunking.py:50–52`, the `GIST_MAX_CHARACTERS` comment: *"the same
     conservative unit the injection budgets use … which of the two such a harness counts is
     unmeasured; counting the larger keeps every claim below a bound rather than a guess"* — the
     exact pre-M16 rationale `spec.py` no longer carries. Same fix: the unit is measured
     (`dogfood-checkpoint` §3), and counting UTF-16 units is correct rather than conservative.
     (`utf16_units`'s "the conservative character count" at line 74 is milder — the never-under-
     reports property it states is still true — but the same one-word update applies.)
   - `tests/test_harness_table.py:317–325`,
     `test_astral_characters_count_two_against_a_character_budget`: *"The conservative reading of an
     unmeasured fact … whether such a harness counts code points or UTF-16 units is unknown."* M16
     answered exactly this; the docstring now invites the bad edit the round-3 spec.py fix exists to
     prevent (relaxing to `len()` as "merely less safe"). Update to cite the measurement; the
     assertion itself is unchanged and right. (`test_the_conservative_count_never_under_reports…` at
     line 359 frames code points as a live "other reading" — same one-sentence update, optional.)
   Round 3 called spec.py "the remaining copy"; this sweep (`unmeasured|conservative|unknown` over
   `zikaron/` and `tests/`) found these three and nothing else, so fixing them closes the class.

4. **[NITPICK] `zikaron/harness/spec.py:62–64` — the `BudgetUnit` docstring's `漢` arithmetic is
   internally impossible under its own wording.** *"9,016 characters of a 3-byte-per-character
   script — 27,016 bytes"*: 9,016 × 3 = 27,048. Both table copies carry the round-2 footnote
   explaining the 32-byte marker discrepancy; this third copy of the pair does not. One word fixes
   it ("≈27,000 bytes") or borrow the footnote's clause ("plus its ASCII markers").

**What I verified and am deliberately not raising:** §7b recounted independently against the frozen
transcripts with occurrence-level matching — the literal `memory store holding **tribal knowledge**`
appears exactly **2× in `2ec96274…jsonl` and 2× in `998d776e…jsonl`, both occurrences on one line
(one JSONL record) in each, one in a `"content"` field and one in a `"stdout"` field, and 0× in
`consolidator-subagent.jsonl`**, while the phrase without markdown emphasis matches 0× anywhere — every
clause of the revised §7b, including the recorded line-count-error postmortem, is exactly right;
`~/zikaron-m16-evidence/` contains exactly the four named files and no `-wal`/`-shm` sidecars; the
reverted D34 row parses green against the spec (10,000 / characters) and its pointer to §"Injection
budgets" is correct; FINDINGS' new priority item 5 states the parser constraint accurately including
"found by doing it"; both `spec.py` docstrings now cite §3, state the astral figures, call `len()`
wrong rather than less-safe, and name the rename residual with the parser caveat; FINDINGS' "M16
inherited four open things, and answered all four" block is past-tense with outcomes matching the
note's §1/§2/§3/§10, and the phase header ("it is landing") reconciles with line 108 ("measurement
half is done and it is in review"); oq15 carries "had the uuid both times … *preferred* gist prose"
with the self-contradicting clause gone; oq13's bold lead reads "plausibly the largest one"; oq11
records the unit as measured; oq12's lead and the note's §7 title both say "concordant second
judgment" and both zero-merge counts say "second consecutive"; the shipped policy read end to end is
coherent — occasions, gate, scope test, the general-fact clause with its test-runner example, secrets,
observations-not-orders, expiry, err-toward-writing, gist rules, the subject-reference rule, and
repair do not undercut one another, and the drift test plus a green gate pin the design-doc copy;
`_merged_permissions`' code (as opposed to its docstring) and its absence-conditioned notes are
correct; and the two historical research notes still carrying "documented, unmeasured"
(`installer-probe` §"…" line ~150, `install-artefact-contract` line ~156) are dated forward pointers
that resolved as predicted and lead a reader to the right place, so they need no edit.

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-08-16

Same scope as rounds 2–4, plus the three post-round-4 additions the brief named (the rejoined
`harness.md` section, the new `FINDINGS-archive.md` dogfooding entry, the coverage-variance
measurement in FINDINGS priority item 6). **Assumption, stated:** no shell in this thread, so the
quoted gate result (exit 0, 1702 passed, 97.64%) and the three coverage runs are taken on the
brief's word; everything file-derivable was re-read and re-derived.

**Summary judgment.** This has converged. All four round-4 findings landed correctly, and — checked
hardest, per the brief — none of the fixes introduced a new defect: the rejoined `harness.md`
conclusion reads correctly rendered, `_merged_permissions`' docstring, the `chunking.py` comment and
both `spec.py` docstrings are coherent end to end with every number in them re-verified, and the
propagation class is genuinely closed — my sweeps over `zikaron/`, `tests/` and `design/` for every
corrected claim of rounds 1–4 ("documented, unmeasured", the unmeasured/unknown budget unit, the
withdrawn verdict language, the pre-correction counts, the wrong interval, the dangling "Superseded
text") return nothing. The shipped policy, read one final time, is coherent with no clause
undercutting another. What remains is four nitpicks, none of which moves a conclusion or contradicts
a measurement; they can land in the closing commit without another round.

### Findings

1. **[NITPICK] FINDINGS.md item 6's lead attributes the coverage flap to the *specific* race while
   its own body attributes it to the class.** The item's subject is one named race — signal handlers
   installed after the socket is bound — and the added lead reads *"**Its** impact is wider than one
   flaky test: the coverage number itself varies"*, i.e. that race moves coverage. The evidence
   offered is per-file percentages from socket-and-timing code generally (*"error branches … taken
   or not depending on how **a** race lands"*), which supports the class, not the member — the flap
   could equally come from connect/retry or idle-stop timing in the same two files, and no cross-run
   per-file diff was taken to localise the ~46 statements. This is the round-3-finding-5 shape (a
   lead asserting what the body hedges), and it plants a falsifiable prediction the entry does not
   mean to make: a future session that pins *this* race would expect the flap to vanish. One-clause
   fix: *"Timing nondeterminism's impact is wider than this one flaky test"* (or diff the per-file
   report between a 97.64 and the 96.85 run and name the file that moved). While there: *"~46
   lines"* should be *"~46 statements"* — coverage counts statements and the sentence's own
   denominator says so. **The rest of the entry checks out as asked:** 97.64 − 96.85 = 0.79 points,
   × 5,882 = 46.5, so ~46 is right; and the ratchet argument is sound — the 90-vs-~97 margin is what
   absorbs the flap, this project has a recorded prior of a floor silently not doing its job, and
   "do not raise `fail_under` near the observed value until the race is pinned" follows regardless
   of which race is responsible.

2. **[NITPICK] `zikaron/hook/write_policy.py`'s docstrings carry ten widow-word wraps — pre-existing
   live instances of exactly the defect class the new archive entry records.** Lines 11 (`and an`),
   33 (`#: cannot`), 147 (`the`), 153 (`the`), 187 (`print`), 202 (`by`), 207 (`the`), 252 (`and`),
   257 (`private`), 260 (`which`) are each a stranded word or fragment on its own line
   mid-paragraph. The prose is *coherent* — joining lines restores every sentence, so unlike the
   three round-4 garbles no meaning is lost — but these are ragged re-wraps that `ruff format`,
   `mypy --strict` and 1702 tests cannot see, sitting in the module the brief asked read one final
   time, and they corroborate the archive entry's claim better than the entry could. One re-wrap
   pass over the five affected docstrings (module, `_OVERRIDE_FILENAME`, `_read_override`,
   `_read_regular_file`, `read_policy`), read back in context per the entry's own corollary. The
   `WRITE_POLICY_PROMPT` constant itself wraps cleanly throughout.

3. **[NITPICK] The new archive entry's "all in files the project calls normative" is one-third
   true.** `FINDINGS-archive.md:958`: of the three garbled files, only `design/harness.md` is
   something this project calls normative; `chunking.py` and `targets.py` are shipped code, whose
   comments are held to `coding-standards.md`'s measured-reasons rule but not called normative
   anywhere. Two words fix it: "in the normative `design/harness.md` and in shipped code". The rest
   of the entry is accurate against round 4's record — the mid-sentence anchor, the ending orphaned
   eleven lines below, the clause-short `chunking.py` replacement, the dangling phrase, and the
   claim that all three passed the whole gate (true even of the markdown one, since the design-table
   parser reads only the D34 table and not the prose the insertion split).

4. **[NITPICK, optional] One present-tense copy of "documented, unmeasured" survives outside the
   exempted research notes: `FINDINGS-archive.md:1716`** — the dated M15 installer-probe bullet ends
   *"that stays **documented, unmeasured** for M16"*. It is the same resolved-forward-pointer class
   round 4 exempted, and the M15 date on the bullet does most of the disambiguation — but the
   archive, unlike a frozen research note, is a maintained record, and a five-word parenthetical
   ("— M16 measured it, dogfood-checkpoint §1") closes the class completely. Raised because the
   brief asked for any remaining copy anywhere; exempting it is also defensible.

**What I verified and am deliberately not raising:** the round-4 blocker's fix — `harness.md:349–354`
now reads as one unbroken sentence (*"UTF-16 code units survive all five, with the cap in [9,503,
10,502) — intact at 9,503 puts it at or above, truncated at 10,502 puts it strictly below"*)
continuing into the `exceeds_injection_budget` conclusion, with the parser-constraint paragraph
following as its own paragraph, content unchanged and still correct; `_merged_permissions`' docstring
states both keys measured with both citations and the corrected belt-and-braces reason (no
install-time or headless check can verify the effect), and its counts match the corrected six writes
/ eight reads; `chunking.py:50–56` now reads coherently ("Counting code points here while the budget
counted units would leave…"), and every number in the comment re-derives (967 + 5×1024 = 6,087 = 61%
of 10,000; ×3 bytes/unit → 18,261 = 28% of 65,536; 1024 chars ÷ 6.55 chars/token ≈ 156-token onset;
~1,584 chars at the 256-token ceiling consistent with FINDINGS item 3); `utf16_units`' docstring
cites the measurement and no longer says "conservative"; both `spec.py` docstrings call `len()`
wrong rather than less safe with the §3 citation, and the repaired 漢 arithmetic is exact (9,000 × 3
+ 16 marker bytes = 27,016); the astral test's fixture math is right at both edges (5,000 astral
characters = exactly 10,000 units passes; one more fails) and its docstring cites the measurement;
the remaining "conservative" hits in `zikaron/` are all either unrelated (consolidator, detect,
grouping) or the corrected not-merely-conservative framing, and
`test_the_conservative_count_never_under_reports_against_code_points` keeps the round-4-optional
framing, which stands as the true mathematical property it states; the dangling "Superseded text"
phrase survives only inside the archive entry that describes it; FINDINGS' resume block is
internally consistent ("it is landing" / "measurement half is done and it is in review", the
inherited-four block past-tense with outcomes); the shipped policy read end to end one final time is
coherent — occasions, gate, scope test, general-fact clause, secrets, observations-not-orders,
expiry, err-toward-writing, gist rules, subject-reference, repair, with no precedence conflict left
unnamed — and the brief's green gate plus the byte-for-byte drift test pin the design-doc copy; and
the scope fence holds everywhere touched this round.

VERDICT: APPROVED
