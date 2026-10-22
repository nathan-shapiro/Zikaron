# Review: `research/knowledge-index-issue-triage.md`

## Round 1 — 2026-10-22

**Summary judgment.** The note reads well, leads with its result, and its numbers hold: I checked
the headline table, the three §4 tables and Appendix D against `research/m40-evaluation.md`
§4–§6 and `scores.json`; Appendix A's call counts and search order against the treatment and
control transcripts (searches 4 and 7 are the first to carry `FollowsBottomOfMostRecentBlock` and
`output_grid_displayed_height`, call 11 is the grep, call 15's result holds both names the fix
turns on, 20 searches and 7 "other" calls); Appendix B's 25 and 83 calls, its fifth file and its
costs; Appendix C against the file on disk; the control's 8 of 48 runs with Zikaron calls; the PR
numbers, titles and the CTIM-Rover attribution. What keeps it from shipping is two statements of
method that a skeptical reader would check and find wrong — a model check called "by hand", and
two ground-truth fixes generated with Claude Code presented as "written by a person", one of them
the second-largest contributor to the treatment's lean — plus three things that differ between
the arms or the data that the note does not disclose. All are cheap sentences.

### Findings

1. **[BLOCKER] §4.4 and §7 — a model check is described as a hand check.** §4.4: *"By hand, a
   separate agent checked every claim in two documents, about 190 claims"*; §7: *"In about 190
   hand-checked claims"*. The source (`research/m40-toy-run.md` §17) says the checking was done by
   an Opus 5.5 subagent, with one of its findings re-checked by hand. For the audience this note is
   written for, "by hand" means a human, and a method misstatement about the one accuracy check
   the note offers is the kind of thing that discredits the rest. Fix: §4.4 — *"Separately, a model
   (Claude Opus 5.5) checked every claim in two documents, about 190 claims, against the code, and
   we re-checked one of its findings by hand: 3 were wrong and 1 unsupported, …"*; §7 — *"In about
   190 model-checked claims"*. Saying which two documents (the two source files behind issue 15666)
   would also let a reader see they were not chosen for being easy.

2. **[BLOCKER] §3.2, §6, Appendix D — two ground-truth fixes were generated with Claude Code, and
   the note says every fix was "written by a person".** PR 16440 (issue 3970) and PR 11457 (issue
   11262) carry a *"Generated with Claude Code"* trailer (`research/m40-evaluation.md` §1;
   `experiments/m40_eval_issues.json` `agent_written: true`). The protocol reports that kind apart
   for the same reason the note gives for excluding Warp's bot PRs: a Claude investigator graded
   against a Claude-written fix by a Claude judge is agreement one step removed. It matters here
   because 3970 is the second-largest contributor to the lean — treatment `ccc` against control
   `wpc`, +3 of the net +9 grade points (10144 +4, 3970 +3, 14234/9013/3265 +1 each, 12425 −1).
   Without 3970 the count is four issues better and one worse, one-sided sign-test p = 0.16; the
   lean survives but the reader must be shown it does. Fix: (a) §3.2 after *"Sixteen issues
   qualified."*: *"Two of the sixteen fixes say in the pull request that they were generated with a
   coding agent (Claude Code), by the person who opened them; we kept them and mark them in
   Appendix D."* (b) §6, a new bullet: *"**Two ground-truth fixes were generated with Claude Code**
   (issues 3970 and 11262), so on those a Claude investigator is graded against a Claude-written fix
   by a Claude grader. Without 3970 the knowledge base graded better on four issues and worse on
   one, p = 0.16."* (c) Appendix D: extend the closing sentence — *"Issues 3970 and 11262 are the two
   whose fix was generated with Claude Code."*

3. **[IMPROVEMENT] §3.4 — a third difference between the arms is not disclosed.** The section is
   titled *"Two arms that differ only in the knowledge base"* and says the prompts differ in three
   paragraphs. A product feature in the treatment also differs: after a grep, glob or shell search
   of the documented module, Zikaron's hook appends a one-line reminder naming the knowledge base,
   at most once per 300 s. It fired in 23 of the 48 treatment runs, 55 lines in all (`scores.json`
   `search_reminders`; 5 of them in the Appendix A run), and cannot fire in the control, which has no
   documented module. It is legitimately part of "the knowledge base as shipped", but it can only
   push the treatment toward more searches, which is the cost mechanism §4.3 describes, so a reader
   weighing the cost finding should know it exists. Fix: after the prompt paragraph, *"The
   treatment also carried one feature of the product the control cannot trigger: after some grep
   calls over the documented module, a hook appended a one-line reminder naming the knowledge base.
   It fired in 23 of 48 treatment runs, 55 lines in all."* And retitle §3.4 to *"Two arms that
   differ in the knowledge base and what introduces it"*.

4. **[IMPROVEMENT] §6 — the prompt confound is argued from in Appendix B and §5 but is not a listed
   limitation.** Appendix B names the treatment prompt's *"check anything a document says about
   another file in that file"* as a plausible cause of over-verification, and §5's first proposed
   change is a prompt change — so the note itself treats the prompt as a live explanation for the
   cost result. A reader of §6 alone would not learn it. Fix: add a bullet — *"**The treatment's
   prompt differs too.** Its three extra paragraphs introduce the knowledge base and tell the agent
   to check what a document says against the code. The extra cost on medium issues may come from
   those paragraphs rather than from the documents; the arm that would separate them has not been
   run."*

5. **[IMPROVEMENT] §7 "Does a better document writer make better documents?" — the question does
   not match the answer, the two versions are never identified, and the 194 includes searches
   from outside this experiment.** The reader is told of "two" sets of documents with "different
   models and instructions" but not which the experiment used, nor that the newer set was written
   by a *cheaper* model (Haiku 5.5, under the current prompt) than the first (Sonnet 4.6, under an
   earlier one), so "better writer" is the wrong frame. And of the 194 replayed searches, 13 came
   from a pilot run over the first set of documents that is not among the 96 runs this note reports
   (`research/m40-evaluation.md` §5: 181 from the three repeats, 13 from the slice), so *"the
   investigators' own 194 searches"* overstates. Fix: retitle *"Would different documents have
   changed the result?"* and write: *"We documented the module twice: first with Claude Sonnet 4.6
   under an earlier prompt, then with Haiku 5.5 under the current one — the version this experiment
   used. We replayed 194 knowledge searches that investigating agents had sent, 181 from these
   runs and 13 from a pilot over the first set, against both versions. The current documents ranked
   a fixed file higher for 32 searches and lower for 41. For finding the right file the two sets
   were equivalent, so whatever the documents contributed was in what they said once found, not in
   which file they pointed at."*

6. **[IMPROVEMENT] §4.4 — the dependency-path check reports one miss where the source reports two.**
   *"of the 3,086 file paths they cite as dependencies, one is a bare file name"* — §17 of the
   toy-run note says two paths did not resolve: `view_impl_tests.rs`, a bare file name, and
   `telemetry.rs`, a parenthetical beside `lifecycle/mod.rs`, which exists. The sentence as written
   implies 3,085 resolve. Fix: *"and of the 3,086 file paths they cite as dependencies, two do not
   resolve to a file: one is a bare file name where a repository path belongs, the other a
   parenthetical name beside a path that does."*

7. **[IMPROVEMENT] §3.4 — the note never says the investigating agent ran as Claude Code.** §1
   mentions Claude Code only as a host for Zikaron's hooks; §3.5 then relies on *"Claude Code reports
   each run's cost"* and *"the same Claude Code version, 2.1.306"* without having said that the agent
   under test *is* a Claude Code session. A reader new to the project has to infer it. Fix: open
   §3.4 with *"Both arms ran as Claude Code, Anthropic's command-line coding agent, headless, with
   the same model, settings and tools, in identical copies of the repository, cut off from GitHub:
   …"*.

8. **[NITPICK] Summary, paragraph 1** — *"the fix a contributor actually wrote"* reads as merged;
   §3.1 and §6 say proposed. *"the fix a contributor has proposed for it"*.

9. **[NITPICK] §3.5** — *"and whether any of its five is"* is announced as a measure and never
   reported. Either drop the clause or add one line where the first-file figure appears: *"A fixed
   file among the five named: 44 of 48 with the knowledge base, 45 without."*

10. **[NITPICK] Appendix B** — *"by call 18"* against the companion note's *"by its sixteenth"*
    (`research/m40-evaluation.md` §6). From the transcript, call 16 is the last read of the privacy
    settings and calls 17–18 are the greps that show the settings macro, so 18 is the defensible
    number if the macros count as reached; make the two notes agree.

11. **[NITPICK] Summary, paragraph 2** — *"with no wrong ones against 2"* is hard to parse on first
    read. *"and produced no wrong diagnoses where the control produced two."*

12. **[NITPICK] §6 "The grader is a model"** — its training data (June 2026) postdates most of the
    issue threads, so it may have read the discussions and the bot's comments; it is given the fix
    regardless, so the residue is small, but one clause saying so costs nothing.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-10-22

**Summary judgment.** All twelve round-1 findings are applied as proposed and the note now reads
as a piece a skeptic can check. I re-traced what round 1 did not: the tier median times against
`scores.json` (hard 29.15 / 25.03 min, medium 13.68 / 4.28, easy 1.0 / 0.96 — all as printed);
the $434 over 100 runs ($421.93 kept plus $11.87 for the four discarded 3970 runs); both sign
tests (7/64 and 6/32); Warp's public date (root commit 2026-04-28); the Opus 4.6 cutoff and the
judge's blind, shuffled, tool-less protocol against the spec; the CTIM-Rover mechanism and the
Gloaguen figures against the notes they come from; every claim in Appendix C against `alias.rs`
and `alias_tests.rs`, and its two dependency paths on disk; Appendix B's "no reminder" (none in
that transcript); the 10144 treatment's call order. Nothing is wrong against the measurements.
Three places where the note's own argument does not close remain, each a one-sentence fix, and
four wording items.

### Findings

1. **[IMPROVEMENT] §4.3 — the cost model the section states is contradicted by its own hard row,
   and nothing reconciles them.** The section opens *"An agent's cost is dominated by re-reading
   its own context … a result's real cost is its size times the number of calls that follow it"*,
   then the table shows the treatment carrying 42.6 M characters to the control's 37.5 M on hard
   issues (+14%) while §4.1 and §5 say the arms cost the same there. A reader applying the model
   as stated expects the treatment to cost ~14% more on hard issues, and the note does not say
   why it does not. The source (`research/m40-evaluation.md` §6) has the answer: the carried
   figure counts tool results only, and over the whole context the hard arms were even — at the
   median pair the treatment made 0.96× the control's calls at 0.96× the mean context, for 0.97×
   the dollars. Fix: head the column *"Tool results carried a run"* and add, after *"We measured
   that product for every tool result:"* or below the table, *"The figure counts tool results
   only. The prompt and the agent's own reasoning are carried too, and over everything in the
   context the hard arms were even: at the median pair the treatment made 0.96× the control's
   model calls at 0.96× the context a call, for 0.97× the dollars — which is how the same cost
   goes with more search text carried."*

2. **[IMPROVEMENT] Appendix B — "the treatment's prompt is the only thing that differs between
   the arms" contradicts §3.4, which now discloses the search reminder as a third difference.**
   *"Besides the documents, the treatment's prompt is the only thing that differs between the
   arms, and its paragraph … is a plausible cause."* As a statement about the arms it is false
   by the note's own §3.4 and §6. As a statement about this run it is true — I grepped
   `r2-11262-treatment-0.jsonl` for `hook_additional_context` and found none — and saying so
   makes the argument stronger, not weaker. Fix: *"No search reminder fired in this run, so
   besides the documents the treatment's prompt is the only thing that differed, and its
   paragraph telling the agent to check what a document says about other files is a plausible
   cause."*

3. **[IMPROVEMENT] §3.5 "Difficulty" — the tiering rule conditions on the control arm, and the
   note does not say the result survives a symmetric rule.** The choice is intentional and not
   at issue. What a reader of the cost-by-tier result will ask is whether it is an artefact of
   the rule: an issue the control happened to run cheap on lands in *medium*, where the treatment
   then looks dear; one the control ran dear on lands in *hard*, where the treatment then looks
   even — the exact pattern §4.1 reports. One clause closes it, and it is true: tiering by the
   mean of the two arms' medians (Appendix D) puts every issue in the same tier (9013 at $4.95
   and 8881 at $4.08 stay medium; the three hard issues stay above $10). Fix: append to the
   Difficulty paragraph, before the table, *"Tiering by the mean of both arms' medians instead
   gives the same three tiers."*

4. **[NITPICK] Appendix A, "The two investigations", treatment column — the call arithmetic
   does not close.** Ten searches, *"Call 11 … by call 15"*, then *"212 more calls"* sums to
   227 of 234. The transcript has calls 11–22 as twelve greps and call 23 as the eleventh
   search, so 212 is right and the middle phase is calls 11–22. Fix: *"Calls 11–22 are greps:
   call 11 greps `output_grid_displayed_height`, and by call 15 it has found `max_cursor_point`
   and `trim_trailing_blank_rows`, the two names the fix turns on."*

5. **[NITPICK] §3.5 "Protocol"** — *"the 100 runs cost $434"* against the headline table's
   $227 + $195 = $422 leaves a reader $12 short. Add *"(the four discarded runs were $12 of
   it)"* — $2.67 + $3.83 + $4.17 + $1.21 from `runs/r1-3970-*-0.json` and `r3-3970-*-0.json`.

6. **[NITPICK] §4.2** — *"We sorted the pairs by which arm spent more than one and a half times
   the other's cost"* describes a three-way split, not a sort. *"We split the pairs three ways by
   whether either arm spent more than one and a half times the other's, and compared their
   grades:"*

7. **[NITPICK] §4.3** — *"On easy issues it does exactly that"*: 1.9 searches a run replaced 1.5
   file reads and 1.2 greps, which is about two reads, not exactly. *"On easy issues it does about
   that, and the cost is a wash."*

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-10-22

**Summary judgment.** Round 2's seven findings are applied as proposed, and the one applied
differently — Appendix B's reminder — is now right against the data: the run record carries
`search_reminders: 1`, Claude Code's session file one `hook_additional_context`, and the
transcript's 50th `tool_use` is the `Grep` for `set_user_and_enterprise_secret_regexes`. I
re-derived what no earlier round had traced: §4.2's within-arm claim from `scores.json` (10144
$17.05 and $13.09 both correct, 14234 $13.86 and $7.93 both correct, 12425 $6.10 and $3.74 both
wrong, 9145 $8.63 wrong against $7.13 partly — fifteen issues the same, one worse); the symmetric
tiering (every issue stays in its tier); Appendix C's 53 lines against `alias.rs`; the Opus 4.6
cutoff (August 2025, spec §7) against the two 2023 issues; the build's $11.66 and 56 min 34 s, the
3,086 dependency paths with two unresolved, and the ~190 claims with 3 wrong and 1 unsupported
against `research/m40-toy-run.md` §17; the reminder's 300 s rule and its reset by a knowledge
search against `design/code-knowledge.md` §6; the three paragraphs the control's prompt omits
against `experiments/m40_eval.py`'s `_NAVIGATION` slice; and the "0.96× calls, 0.96× context,
0.97× dollars" sentence against `research/m40-evaluation.md` §6. All hold. What keeps it from
shipping is one number: Appendix B's tool-call count for the treatment run is a count of model
calls, and the same transcript counted the way Appendix A's and the control's are counted gives
94, not 83. Two numbers change and nothing else does.

### Findings

1. **[BLOCKER] Appendix B, "The two investigations" table — "83 tool calls" and "65 more
   calls" count model calls, not tool calls; the figure on the same basis as the control's 25 and
   Appendix A's 234 and 181 is 94.** `runs/r2-11262-treatment-0.jsonl` holds 94 `tool_use`
   blocks and 94 `tool_result`s, every id once. They sit in 83 distinct assistant messages,
   because the agent issued parallel calls in eleven messages — two or three `Grep`s at a time,
   such as the six `SettingsFile` greps at the hot-reload stage. The control's 25 messages carry
   25 calls, so its number is the same either way, and `r1-10144-treatment-0.jsonl` and
   `r1-10144-control-0.jsonl` give 234 and 181 by `tool_use`, so Appendix A is on the per-call
   basis. Appendix B's own "by call 18" and "at call 50" are per-call too — the 18th `tool_use`
   is the `macro_rules! register_settings_events` grep and the 50th the
   `set_user_and_enterprise_secret_regexes` grep — so the total in the same table must be. Fix:
   "What followed" → *"76 more calls through cloud-preference syncing, safe-mode settings,
   feature flags and settings hot-reload; …"*; "Totals" → *"94 tool calls; 15.5 minutes; $5.62"*.
   "About a fifth of the way through its run" still holds (18 of 94). The companion
   `research/m40-evaluation.md` §6 says *"went on to 83"* of the same run; make the two agree.

2. **[NITPICK] §4.2 — "no issue's most expensive run graded better than its cheapest" is true
   but has less resolution than it reads with.** Twelve of the sixteen issues graded the same in
   all three treatment runs, so the comparison can move on four at most; on three of those the
   costliest and cheapest runs graded the same, and on 9145 the costlier graded worse. One
   parenthetical lets the reader weigh it: *"no issue's most expensive run graded better than its
   cheapest (on fifteen the two graded the same; on the one that differed, the costlier graded
   worse)."*

3. **[NITPICK] §4.3 — "A knowledge search returns 7,000 to 9,000 characters" against the
   table's 9.3 k for medium issues, four lines above.** *"7,000 to 9,300 characters"*, or
   *"about 7,000 to 9,000"*.

4. **[NITPICK] Appendix B, last paragraph — "That leaves the treatment's prompt" reads as an
   elimination down to one cause, while the documents are the other candidate and the next
   sentence says so.** The search results are themselves in the context the agent then verified
   from: the first search's top result already said *"the inline comment says the lists are
   empty until safe mode is enabled; the code does not check safe mode"*, and safe-mode settings
   is the branch that reached its answer. *"Besides the documents themselves, that leaves the
   treatment's prompt, whose paragraph telling the agent to check what a document says about
   other files is a plausible cause."*

VERDICT: NEEDS_CHANGES

## Round 4 — 2026-10-22

**Summary judgment.** Round 3's four findings are applied as proposed, and the companion note
agrees (`research/m40-evaluation.md` §6 *"went on to 94"*). I traced what no earlier round had:
the two pre-cutoff issues against `experiments/m40_eval_issues.json` (3265 and 3970 are 2023;
every other issue was filed in 2026, so none falls between the Opus 4.6 cutoff and Warp's
publication); the $14 grading cost, the 44-of-48 and 45-of-48 any-of-five figures and the whole
§4.3 table, cell by cell, against `research/m40-evaluation.md` §4–§6; the contamination check
and the 407-of-407 format check against `research/m40-toy-run.md` §17; and every tier sum and
per-issue score in §4.1–§4.2 and Appendix D by arithmetic. Nothing is wrong against the
measurements. What remains is three one-sentence items where the note's own honesty does not
quite close — a limit it names the size of but not the consequence of, a cause stated as fact in
§4.3 that §6 holds as a hypothesis, and a speed claim in the Summary that the body supports only
with a count — and five wording items.

### Findings

1. **[IMPROVEMENT] §3.2 and §4.4 — the 30,181-line file's document is partial, and the note
   never says so.** §3.2 names the file's size, which invites the question of how a per-file
   document handles it, and §4.4 then says *"every document has the expected format and the
   correct link to its source"*. The document the treatment searched describes `view.rs` in
   part — lines 1–3,200 and two short later ranges read in full, the rest located by search, 208
   of about 750 functions listed — and its first line says so (`research/m40-toy-run.md` §17).
   The file is among the fixed files of four issues (3265, 3970, 14234, 15590) and the only one
   under the module for 3265 and 15590 (`research/m40-evaluation.md` §1), so a reader weighing
   the hard-tier result — 15590 graded `ppp` in both arms — should know. Fix: §3.2, after
   *"including one file of 30,181 lines"* — *"…, longer than a document writer can read whole;
   its document describes the file in part, about 3,200 lines read in full and the rest located
   by search, and says so in its first line. That file is among the fixed files of four of the
   sixteen issues."* Or the same as a §6 bullet, *"One fixed file's document is partial."*

2. **[IMPROVEMENT] §4.3, last paragraph — "it followed the instruction to verify, and verified
   broadly" states as fact what §6 and Appendix B hold as untested.** §6's bullet says the extra
   cost *"may come from those rather than from the documents; the arm that would separate them
   has not been run"*, and Appendix B calls the prompt *"a plausible cause"*. §4.3 is the one
   place the prompt is named as the cause outright, and it is the paragraph a skeptic reads
   most closely. Fix: *"The agent searched, then read more files than the control, not fewer —
   as if verifying everything it had read rather than what it would state. Appendix B shows the
   clearest example."* §5's *"verified as if it had not"* already has this shape and needs no
   change.

3. **[IMPROVEMENT] Summary and §5 — "not faster file-finding" is a speed claim, and the only
   evidence given for it is a count.** The Summary says *"The knowledge base produced better
   diagnoses, not faster file-finding"* and §5 *"It does not help the agent find the file"*, both
   supported by the first-file figures (29 and 28), which measure what was named, not when a
   fixed file was reached. The measured speed datum exists and says the same thing:
   `research/m40-evaluation.md` §5 — over the 48 kept runs an arm, the median run first read,
   grepped or named a truth file at its fourth tool call, in both arms, and 3 runs an arm never
   did. Fix: §5, second bullet, after *"(29 and 28 times)"* — *", and in both arms the median
   run first read, grepped or named a fixed file at its fourth tool call."*

4. **[NITPICK] §1 — "knowledge base" is the note's term from the Summary on, and §1 never
   attaches it to anything.** §1 calls the unit a *"named collection of files"* and a
   *"collection"*; the prompt in Appendix A then calls it *"the `code-knowledge/app/src/terminal`
   knowledge base"*. One phrase closes it: *"It indexes named collections of files — knowledge
   bases — and returns matching fragments…"*.

5. **[NITPICK] §1 — "hooks in the agent's tool (Claude Code or kiro-cli)".** "Tool" is the word
   the note uses for MCP tools from §3.4 on. *"and hooks in the coding agent itself (Claude Code
   or kiro-cli)"*.

6. **[NITPICK] §3.1 — "the files that fix changes"** reads on first pass as *the files that fix
   [verb] changes*, in the sentence that defines the ground truth. *"the files the fix changes"*.

7. **[NITPICK] §7 "Would different documents have changed the result?" — "the two sets were
   equivalent"** overstates a two-sided p of 0.35 over 73 informative queries, which shows no
   difference rather than equivalence. *"For finding the right file we could not tell the two
   sets apart, so…"*.

8. **[NITPICK] Appendix D, closing paragraph — 8881 and 9013 report one crash and share one
   fix** (PR 13041, `research/m40-evaluation.md` §1), so they are not two independent issues; the
   note marks them only as the two outside the module. *"Issues 8881 and 9013 report one crash
   and share one fix, whose file lies outside the documented module."*

VERDICT: NEEDS_CHANGES

## Round 5 — 2026-10-22

**Summary judgment.** Round 4's eight findings are applied, and the two applied differently from
the proposal are right against the data: the document the treatment searched
(`~/Zikaron-m40/eval/root/b/warp/code-knowledge/app/src/terminal/view.rs.md`, blob `cd214a5a…`,
byte-identical in `eval/pristine/b/`) carries the role line §3.2 now paraphrases, and its five
read ranges sum to 942 lines; `_first_touch` in `experiments/m40_retrieval_replay.py` returns the
number of calls *before* the first `Read`, `Grep` or `Bash` on a fixed file, so "after four tool
calls" is the right reading of the median 4 in `research/m40-evaluation.md` §5. I traced what no
round had: Appendix B's two medians against `scores.json` (control $1.23 at 1.7 min; treatment
$5.62 at 15.5 min, its median time 16.2 min). Two things keep it from shipping, both in the
honesty-about-limits column and each one sentence: §3.2's new parenthetical says the two-thirds of
`view.rs` past line 10,039 is "located by search" when the document holds no declaration from it,
and Appendix B's own run records show the control detoured on 11262 too, once in three.

### Findings

1. **[IMPROVEMENT] §3.2 — "the rest located by search" is not what the document says or does.**
   The document's Declarations section is three groups — constants and statics (lines 567–784),
   free functions and types (701–3,046), and *"Methods of `impl TerminalView` (line 3046 onward,
   through line 10039 as indexed; the bodies between 3186 and 9235 were not read)"* — and outside
   its role line, its Purpose and the test module's `Depends on:` line (30,179–30,181), no line
   number between 10,040 and 30,169 appears anywhere in it (two greps over the file). What its
   Purpose says is that the declarations whose *bodies* were not read (3,186–9,235) come from a
   grep index; the twenty thousand lines after 10,039 are not indexed at all. So *"declarations
   indexed through line 10,039, the rest located by search"* tells a reader the rest of the file
   is covered some other way, when it is not covered. It matters where the note sends the reader:
   this is the fixed file of four issues, including the hard one both arms graded `ppp`. Fix:
   *"Its document describes it in part — under a thousand lines read in full, its declarations
   indexed through line 10,039 (those whose bodies were not read taken from a grep), and no
   declaration from the twenty thousand lines after that — and says so in its first line."*

2. **[IMPROVEMENT] Appendix B — the control detoured on this issue too, and the appendix reads as
   if it never does.** `scores.json`: the control's three 11262 runs cost $4.77 (repeat 1, 79 tool
   calls, 11.5 minutes), $1.00 (repeat 2, the run shown) and $1.23 (repeat 3, 1.7 minutes); the
   treatment's cost $7.28, $5.62 and $5.50, at 15.5–16.4 minutes. The medians the appendix prints
   are right and the round-2 pair is the clearest contrast, but a reader given *"$1.23 and under
   two minutes"* against *"$5.62 and sixteen minutes"* and one trajectory each will conclude that
   the grep-only agent stops when it has the answer and the documented one does not. The data
   says the grep-only agent *usually* stops: it over-verified once in three, at about four times
   its own median, with no documents and no reminder — which also bears on the prompt-versus-
   documents question the last paragraph raises, since the behaviour exists without either. Fix:
   after *"with it, $5.62 and sixteen minutes."* add *"The control was not immune: its first-round
   run made 79 tool calls and cost $4.77. But it detoured once in three runs, and the agent with
   the knowledge base did in all three, at $5.50 to $7.28."* Then *"In the second round:"* as now.

3. **[NITPICK] §5, second bullet — "read, grepped or named a fixed file" reuses "named" from the
   sentence before it, where it means the answer's FILES block.** A reader takes *"first … named
   a fixed file after four tool calls"* as the answer and cannot square it with a count of four.
   The replay's third kind of touch is a `Bash` command whose text contains the path
   (`_first_touch`). *"and in both arms the median run first read, grepped or ran a shell command
   on a fixed file after four tool calls."*

4. **[NITPICK] §4.4 "the module overview" against the prompt's "a module README" (Appendix A).**
   One name for one file: *"Writing the 407 documents and the module README"*.

5. **[NITPICK] Outside the artifact — the companion note disagrees with §3.2.**
   `research/m40-evaluation.md` §1 (*"its current document lists 136 functions of about 750, and
   its role line says so: 'lines 1–3200, 27463–27463, 28982–29590 …'"*) quotes the Sonnet 4.6
   document's role line (`research/m40-toy-run.md` §8) as the current one; the runs searched the
   Haiku 5.5 document whose role line §3.2 now paraphrases (toy-run §17: 208 `fn` bullets). Earlier
   rounds held the two notes to agreeing about the same run; one sentence there closes it.

VERDICT: NEEDS_CHANGES

## Round 6 — 2026-10-22

**Summary judgment.** Round 5's five findings are applied, and the rewording of finding 2 is the
more honest one: Appendix B now gives the control's detour as one run with its own figures and
the treatment's as a range over three, rather than inferring "detoured" from cost. I re-read the
whole note and traced what no round had: the `view.rs` document's role line (five ranges summing
to 942 lines, the declaration index to 10,039, and — the one thing §3.2 now gets slightly wrong —
lines 30,170–30,181 read in full and the test module declared there named under Dependencies);
PR 10729 for 10144 (`agent_written: false`, truth `model/block.rs`) and PR 11457 for 11262
(`agent_written: true`, truth `secret_regex_updater.rs`) in `experiments/m40_eval_issues.json`;
the 8881/9013 file's rename out of the module at commit `21f413b79`; §4.3's "two file reads or
five to eight greps", "18 fewer file reads" and "searched ten times" against
`research/m40-evaluation.md` §6; the grader's June 2026 cutoff against the models overview quoted
in `research/m40-eval-sonnet5-issue-sets.md`; and every tier sum, per-issue score, both p-values
and the cost ratios (1.164×, 0.925, 1.386×, 3.19×) by arithmetic. Nothing is wrong against the
measurements. One honesty item remains, one clause long, and one nitpick.

### Findings

1. **[IMPROVEMENT] §4.1, "Hard issues" — "At the same cost" is a tier average that nets the one
   issue where the knowledge base paid against the two where it saved, and the note says so only
   in Appendix A's last paragraph.** Appendix D's medians: 10144 $14.86 with against $11.01
   without (+35%), 14234 $9.03 against $11.60 (−22%), 15590 $9.89 against $12.42 (−20%). §4.1
   itself says most of the hard-tier gain is 10144, so a skeptic reading "at the same cost …
   4 correct in 9" and then Appendix D will read the tier figure as having hidden the one issue
   that carries the result — the Summary ("On the three hardest it cost the same") and §5
   ("where it also cost nothing extra") repeat it, and only Appendix A's *"In this round the
   knowledge base cost more, not less"* corrects it. §4.2's hard row is the real defence (three
   of the four better-graded pairs within 1.5× cost) and already follows, so one clause in §4.1
   is enough. Fix: *"**Hard issues** are where the knowledge base pays. Over the tier the arms
   cost the same — more with the knowledge base on the issue in Appendix A, $14.86 to $11.01 at
   the median, and less on the other two — and the agent with it produced 4 correct diagnoses in
   9 runs and none wrong; without it, 1 correct and 2 wrong."* The Summary and §5 can stand on
   that; if §5 is touched, *"where over the three issues it cost nothing extra"*.

2. **[NITPICK] §3.2 — "nothing from the twenty thousand lines after that" is contradicted by the
   first line the sentence sends the reader to.** The document's role line reads *"lines 1–200,
   2513–3002, 9236–9375, 9944–10043 and 30170–30181 were read in full"*, and its Dependencies
   name *"the test module declared at lines 30179–30181"*. The document's own Purpose states the
   unread span exactly — *"from line 10040 to line 30169, were not read"* — and the note can
   borrow it: *"…declarations indexed through line 10,039, and nothing from lines 10,040 to
   30,169 — and says so in its first line."* A reader who opens the document, which this
   audience will, then finds the note and the role line agreeing.

VERDICT: NEEDS_CHANGES

## Round 7 — 2026-10-22

**Summary judgment.** Round 6's two findings are applied as proposed and the four places they
touch agree with each other and with the data: §3.2's "nothing from lines 10,040 to 30,169" is
the `view.rs` document's own Purpose sentence; §4.1's hard paragraph, the Summary's "cost the same
in total" and §5's "$108 against $107" all rest on the tier sums $107.73 and $107.02, which are
the §4.1 means times nine. I re-read the whole note against the measurements and traced what no
round had: §6's "8 of its 48 runs, mostly to search memory" from `scores.json` entry by entry
(9145, 10144 and 14234 in repeat 1, 10144 and 14234 in repeat 2, 10144, 12425 and 15590 in
repeat 3 — eleven memory searches to three knowledge searches); the "17% more" against the exact
totals ($227.11 / $194.82 = 1.166, which the rounded $227 / $195 would not give); and the two
discards against `runs/r1-3970-control-0.json`, `runs/r3-3970-treatment-0.json`, `scores.json`'s
`discarded` list and the audit rule in `design/code-knowledge.md` §7. That last trace is the one
finding: the note's account of the discards is the audit's label, not what happened, and both
discards fell on the issue that is the second-largest contributor to the lean. One sentence closes
it. The rest is wording.

### Findings

1. **[IMPROVEMENT] §3.4, last paragraph — "ran a forbidden command … That happened twice"
   describes the second discard by the audit's label, and both discards were on issue 3970.**
   The first discard (repeat 1, control) is what the sentence says: the agent ran
   `find /home/nathan/Zikaron-m40 -path "*/urlocator*/src/lib.rs"` from the directory that holds
   both copies and the clone, so the search traversed the treatment's copy, though it matched
   nothing. The second (repeat 3, treatment) ran no forbidden command: its `discards` entry is
   `a denied command ran: Bash(cargo:*): echo $CARGO_HOME && ls -la … || echo "No cargo registry
   found"` — the audit matched the whole word `cargo` inside an `echo` string, which
   `research/m40-evaluation.md` §4 calls *"the false discard §7 names"* and §7 of the spec
   anticipates (*"A `grep` for the word `curl` … is the one false discard worth naming; the
   replacement rule absorbs it"*). Kept runs carry `refused_by_rule: {"cargo": 1}` without being
   discarded, so "ran a forbidden command" is not even the rule a reader could reconstruct from
   the data. Why it matters here rather than in the companion note: §6 names 3970 as the
   second-largest contributor to the lean, and a reader who later learns that both discards
   landed on that issue — one of them a false alarm — will ask whether the discards steered the
   result. They did not: the audit runs when a run finishes, the `discarded` records in
   `scores.json` carry no grade, and both arms were replaced together. But the note has to say
   so, because the reader cannot. Fix, replacing the paragraph's last two sentences: *"Every run
   was audited when it finished, before grading: a run that reached outside its own copy, or ran
   a forbidden command, was discarded and both arms of that issue were run again. That happened
   twice, both on issue 3970: once when the control ran a `find` over the directory holding both
   copies, and once when the audit matched the word `cargo` in a message the treatment echoed — a
   false match, replaced all the same."* For the author's own confidence rather than the note:
   the two discarded diagnoses are in the run records, ungraded. The discarded control's says
   `urlocator` does not recognize `file://` and the path scanner splits on `:`; the discarded
   treatment's says `urlocator` claims the whole token including `:35:24` and the `Url` arm hands
   it to the OS, which is PR 16440's stated root cause. Nothing in that direction favours the
   treatment, which is one more reason the sentence costs nothing to write.

2. **[NITPICK] §4.1, "Hard issues" — "$14.86 to $11.01 at the median" reads as a range on first
   pass.** §5 uses *"$108 against $107"* for the same kind of comparison two sections later.
   *"$14.86 against $11.01 at the median"*.

3. **[NITPICK] §4.3, after the table — "That is how the same cost goes with more search text
   carried."** The sentence is doing the work round 2 asked for, but the phrasing stops a reader.
   *"…for 0.97× the dollars — which is why carrying more search text did not cost more."*

4. **[NITPICK] §4.2, second paragraph — "On hard issues it was graded better without spending
   more"** sits beside a row showing one of its four better-graded hard pairs in the
   over-1.5× column. *"On hard issues three of its four better grades came without spending
   more."*

VERDICT: NEEDS_CHANGES

## Round 8 — 2026-10-22

**Summary judgment.** Round 7's four findings are applied as proposed and the note's numbers
still close end to end: I re-summed every tier and every per-issue score in §4.1, §4.2 and
Appendix D from the letter grades, both sign tests, the cost ratios and the hard-tier sums, and
traced what no round had — that the sixteen issues are the predicate's whole yield over 245
candidates (`research/m40-evaluation.md` §1), that all 407 documents describe `.rs` sources
(every `zikaron-source:` line in the treatment's corpus), and that three of the five easy
issues are *located* in `experiments/m40_eval_issues.json`, so "most of them name the faulty
file or symbol" holds. One thing keeps it from shipping, found by asking what the arms differ
in that the note does not list: the documents were files inside the treatment's checkout, and
its own `Grep` and `Read` reached them in seven of the 48 kept runs. The note never says the
agent's grep could touch the documents, the harness counts only one of the two routes, and
§4.3 books the other as greps. Two sentences close it. One nitpick on a unit.

### Findings

1. **[IMPROVEMENT] §3.4 — the documents sat under `code-knowledge/` in the treatment's copy,
   where its grep and file tools reached them outside the knowledge tool, and the note lists
   that nowhere.** The paragraph says the arms ran *"in identical copies of the repository"*
   and that the treatment's copy *"held the 407 documents, registered as a searchable
   knowledge base"*, and the Summary says the agent *"could also search a knowledge base"*;
   every count the note gives of document access is a knowledge search. The transcripts show
   a second route. In six kept treatment runs — 10144 rounds 1 and 2, 11262 rounds 1 and 2,
   12425 round 3, 15590 round 3 — a `Grep` issued with no `path` searched the whole copy and
   returned document lines beside code: ten results (an eleventh is one of them read back from
   the file Claude Code saves an oversized result to), in the `path:line:` form with
   `code-knowledge/app/src/terminal/….rs.md` paths, including Behavior bullets such as
   `secret_regex_updater.rs.md:26` and `:27` in both 11262 runs. In a seventh, 3970 round 1
   (`r1-3970-treatment-1.jsonl`, the kept attempt, graded correct where the control was wrong),
   the agent ran `Glob("**/code-knowledge/**/link_detection.rs.md")` and then `Read` thirty
   lines of that document directly. The harness counts the second route
   (`document_file_tool_calls: 1`, the only nonzero in `scores.json`) and `Bash` results that
   show a document path (none), but `routes()` in `experiments/m40_eval.py` never inspects a
   `Grep` result, so the first route is in no count anywhere; the control cannot take either,
   since its copy holds no documents and the audit discards a control run that sees a
   `code-knowledge/` path. The magnitude is small — ten results among roughly two thousand
   treatment greps, and Appendix A's narrative is untouched, since its call 15 found
   `max_cursor_point` and `trim_trailing_blank_rows` in `blockgrid.rs` before the one
   document-bearing grep at about call 18 — so nothing in §4 or §5 moves. What moves is the
   methods section's claim of completeness, for exactly the reader this note is written for:
   a skeptic who learns the Markdown was grep-able will ask whether the "knowledge base" was
   the search tool or the files, and the note has to be the one that tells them. Fix, in §3.4:
   first paragraph, *"in two copies of the repository, identical but for the documents, cut off
   from GitHub: …"*; then replace its last sentence with *"The treatment's copy held the 407
   documents as files under `code-knowledge/`, registered as a searchable knowledge base — and
   reachable by its own tools too: a grep run from the repository root returned document lines
   beside code in ten results across six of the 48 runs, and one run read a document directly
   after a glob found it. We count those as greps and reads, not as knowledge searches. The
   control's copy held no documents, so the same grep returned code alone and its knowledge
   searches returned nothing."* Re-derive the six runs and ten results with
   `rg -c 'code-knowledge/app/src/terminal/[A-Za-z0-9_/.-]+\.rs\.md[:-][0-9]+[:-]'
   ~/Zikaron-m40/eval/runs/*treatment-[01].jsonl` (eleven lines, one the re-read in
   `r1-11262-treatment-0.jsonl`), and the direct read with
   `rg -o '"name":"(Read|Glob)","input":\{[^}]*code-knowledge[^}]*\}'
   ~/Zikaron-m40/eval/runs/r1-3970-treatment-1.jsonl`. Outside the artifact, as round 5's
   item 5 was: `research/m40-evaluation.md` §4 says of the slice that *"no run read a document
   file directly"* and reports nothing for the 96 runs on either route; one sentence there
   keeps the two notes agreeing about the same data.

2. **[NITPICK] §4.3 table — the "carried" column is a product and its cells carry the wrong
   unit.** The text defines the quantity as *"its size times the number of calls that follow
   it"* and says *"We measured that product"*, then the cells read *"0.3 M characters"*. A
   reader who sums the Read, Grep and search columns of the same row gets about 40 k
   characters for an easy run and cannot square it with 0.3 M until they realise the cells are
   characters × later calls. Fix: head the column *"Tool-result characters × later calls, a
   run"* and drop the unit from the cells (*"0.3 M"*, *"7.1 M"*, *"42.6 M"*), or keep the
   heading and write *"0.3 M character-calls"* in the first cell only.

VERDICT: NEEDS_CHANGES

## Round 9 — 2026-10-22

**Summary judgment.** Round 8's two findings are applied, and the new §3.4 paragraph's figures
hold against the transcripts and `scores.json` on the basis the note uses — what the agent saw:
the thirteen kept treatment runs with a nonzero `grep_results_showing_documents` sum to 22, and
by hand those 22 split into 9 content-mode results across six runs (r3-15590, r2-11262 ×2,
r2-10144 ×3, r1-10144, r3-12425, r1-11262) and 13 file-list results across nine runs (r2-10355,
r1-9145, r2-11262, r1-15590, r3-11262 ×2, r3-14234, r2-3970, r1-9056, r1-11262 ×4); no control
transcript contains the string `code-knowledge` at all; the direct read is r1-3970-treatment-1
at transcript line 3400, after the `Glob` at 3399. The one figure that does not hold is the
total: that direct-read run has `grep_results_showing_documents: 0` (`scores.json` lines
213–218), so the union of the three routes is fourteen runs, and the sentence as placed says
thirteen. One number, one sentence; the rest is a clause and a pronoun.

### Findings

1. **[BLOCKER] §3.4, second paragraph — "In all, 13 runs touched the documents this way" is
   wrong by one, because the run that read a document directly is not among the thirteen that
   grepped one.** The six content-mode runs and the nine file-list runs overlap on r1-11262 and
   r2-11262, so the grep route alone is 6 + 9 − 2 = 13 runs — the thirteen with a nonzero
   `grep_results_showing_documents` in `scores.json`. The kept r1-3970 treatment run, the one
   that ran `Glob` and then `Read` `code-knowledge/app/src/terminal/view/link_detection.rs.md`,
   is the only run with `document_file_tool_calls: 1` and has `grep_results_showing_documents:
   0`, so it is a fourteenth. The sentence comes *after* "one run read a document directly" and
   ends "we count those calls as greps and reads", so a reader takes 13 as the total over all
   three routes, which is 14. The companion note's wording
   (`research/m40-evaluation.md` §4: *"13 runs in all; one run, 3970's first, read a document
   directly"*) puts the total before the read and so can be read as the grep route alone, but
   it invites the same misreading. Fix, replacing the sentence: *"Thirteen runs reached the
   documents through grep, and one more through that read; we count those calls as greps and
   reads, not as knowledge searches."* Re-derive with
   `rg -c '"grep_results_showing_documents": [1-9]' ~/Zikaron-m40/eval/scores.json` (13) and
   `rg -n -B3 '"document_file_tool_calls": 1' ~/Zikaron-m40/eval/scores.json` (one entry, the
   repeat-1 issue-3970 treatment, whose next line but two is `"grep_results_showing_documents":
   0`). If the companion note is touched, *"13 runs in all through grep"* keeps the two agreeing.

2. **[NITPICK] §3.4, second paragraph — "9 results" is the agent-visible count, and the tenth
   reached the agent by another door.** Round 8 counted ten content-mode results; the note now
   says nine, and nine is right on the note's basis: r1-11262's grep at transcript line 1840
   (`set_user_and_enterprise_secret_regexes`, content mode, `-C 5`, no path) produced a result
   Claude Code judged too long to show, so what the agent saw at line 1841 was a stub with a
   2 KB preview that holds no `code-knowledge/app/src/terminal` path (no match for `Output too
   large.{0,2150}code-knowledge/app/src/terminal` in `r1-11262-treatment-0.jsonl`), and the
   harness, which reads the same stub, does not count it. The agent then read the saved file at
   line 1842 and got the whole result at 1843 — the `secret_regex_updater.rs.md` Behavior and
   Dependencies bullets and `model/mod.rs.md`'s declarations among it — which neither
   `grep_results_showing_documents` nor `document_file_tool_calls` sees. No run count moves,
   since r1-11262 is already among the thirteen, and the result count is defensible as written.
   Optional, if the author wants the sentence to survive a reader with the transcripts: after
   *"13 more results across 9 runs"* add *"— and once, a grep result too long to show whole was
   read back from the file the agent's harness had saved it to, document text included"*.

3. **[NITPICK] §3.4, second paragraph — "reachable by its other tools too" has no antecedent
   with tools.** The subject of the sentence is *"The treatment's copy"*, which is a checkout;
   the tools belong to the arm. *"reachable by the treatment's other tools too"*.

VERDICT: NEEDS_CHANGES

## Round 10 — 2026-10-22

**Summary judgment.** Round 9's findings 1 and 3 are applied as proposed, and finding 2 stays
declined for the reason given, which I accept: that run is already among the thirteen. The passage
added at the operator's prompting holds against the whole corpus, not only the harness's count:
across all 48 kept treatment transcripts, `r1-3970-treatment-1.jsonl` is the only one whose
`Read`, `Glob` or `Bash` input names a document path (lines 3396, 3398, 3400 — a guessed path
under `.zikaron/knowledge/`, the glob, the read), its knowledge search at line 3394 names
`link_detection.rs.md` before them, and no other run so much as attempted one; the companion note's
§4 now says *"13 runs in all through grep … 14 runs by either route"*. I re-summed the headline
table, every §4.1 cell, the §4.2 pair counts (9 better and 2 worse, which is the per-issue net of
+9), both sign tests and the cost ratios from Appendix D's letter grades and medians once more, and
re-checked Appendix A's 20 searches and 7 "other" calls against the run record (20 knowledge
searches and one memory search). Everything closes. Nothing is wrong against the measurements and
nothing a reader new to the project needs is missing. Two wording items remain; I would ship the
note without either.

### Findings

1. **[NITPICK] §3.4, second paragraph — "went from a search result to the document file" follows
   "after a glob found it", and in this note a glob is a search too** (the next paragraph's *"a
   grep, glob or shell search"*). The sentence means a knowledge-search result: the search at
   transcript line 3394 names `link_detection.rs.md`, the `Read` at 3396 guesses a path under
   `.zikaron/knowledge/`, the `Glob` at 3398 finds the real one. And *"its full path"* reads as an
   absolute path, where a result gives `app/src/terminal/cli_agent.rs`, the path from the
   repository root — which is what makes it openable without a glob. Fix, two sentences in place
   of the dash clause: *"One run read part of a document directly after a glob found it — the only
   time an agent followed a knowledge-search result to the document file rather than to the source.
   A result names the source by its path from the repository root and the document only by its
   path within the knowledge base."*

2. **[NITPICK] Appendix A, "The two investigations" — five search reminders fired in the treatment
   run shown, and the appendix does not say so, where Appendix B discloses its one.** `scores.json`
   (repeat 1, issue 10144, treatment) carries `search_reminders: 5`. The finding is untouched: the
   ten opening searches precede the first grep, so no reminder could have prompted them, and call
   15's find of `max_cursor_point` and `trim_trailing_blank_rows` is in the grep phase. What it
   bears on is the closing sentence, *"it was more thorough, and the thoroughness ran long"* — a
   skeptic who has read in §3.4 that the product nags the agent to search will ask whether the
   later ten searches were the agent's own, and the appendix should be the one to tell them, as
   Appendix B does for its run. Fix, in the "The rest" cell: *"… including 10 more knowledge
   searches; five search reminders fired during them."*

VERDICT: APPROVED
