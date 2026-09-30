# M34 — the gist form rule, replayed through the real consolidator

**Question.** Does the consolidator, given `design/build-plan.md` §M34's form rule, write gists that
carry no verdict — without losing severity, facts, conditions or triage?

**Answer.** Yes, after one fix, judged by reading (the marker regex over-counts; §"The marker regex"
says why and gives its ratios). Where the consolidator writes a gist the rule held (2 of 64 rewritten
records still carry a verdict). In-place promotion leaked: 14 of 41 kept a marked gist, about half
real verdicts, because that form *requires* the gist byte-identical. Conditioning in-place promotion
at the promote call closed it — in a targeted re-run four of the five leaked verdicts and orders were
rewritten, the fifth is a borderline historical claim, and every clean control still promoted in
place.

## Setup

- Source: a `Connection.backup()` snapshot of `~/Trading/LeibaTrader`, 2026-09-29. Seed: every row a
  `remember` created (284), current prose, re-inserted as journal entries in `created_at` order.
- Consolidator: the skill as installed at the time of this run — `reviews/m34-prose-review.md`
  Round 1's text, with `zikaron_memory_promote`'s description and the skill's promote paragraph still
  stating the in-place form with no condition (both replaced after it, Round 2) — run by the operator
  by hand; model per `design/consolidation.md` §"Consolidator identity and model".
- **Partial run, stopped deliberately** once the signal was clear: 77 groups dispositioned, 105
  long-term records holding 134 seed rows — 41 promoted in place and 64 created by the consolidator,
  8 merges having folded further rows into some of those 64 — and 0 discards. Groups are served
  oldest first, so this is the earliest ~47% of the journal; it includes the `3e1f6c7a` exemplar. Counted from the replay store's
  `event` table: `promote` by `role` (41 `flipped`, 64 `created`, 85 `absorbed`) and `merge` (8
  targets).
- Re-derive: `.venv/bin/python experiments/m34_gist_replay.py compare` over
  `~/zikaron-m34-replay/`, which writes `compare.md` — every output record beside the seed rows it
  absorbed.

## The marker regex is a screen, not a measure

`VERDICT_MARKER` in the script counts connectives (`so`, `therefore`, …), bare verdict adjectives
and an appended ` — ` clause. It over-counts: a causal *so* describing an observed mechanism —
*"forked under sbt --client, so their stdout never reaches the sbt log"* — is on the observed side of
the rule's own boundary, and a dash introducing a measurement (*"— r = -0.56"*) is data.

**So the "Verdicts removed" bar is judged by reading, and the brief now says so.** As first written it
asked for the output's regex rate under a quarter of the seed's, confirmed by reading. By regex this
run gives **0.41** of the seed rate over all output and **0.26** over the records the consolidator
wrote — neither under 0.25 — while reading the marked gists finds the regex's excess is causal
clauses, not verdicts. A ratio of two over-counts is not a verdict rate, so the bar was amended after
this run to the reading test (`design/build-plan.md` §M34): no verdict or order reaches long-term
through a gist the consolidator wrote or chose to keep, beyond isolated residuals each named here.
The amendment is recorded rather than silent because it was made after seeing the data.

| | marked / total |
|---|---|
| Seed rows absorbed so far | 72 / 134 (54%) |
| Output long-term records | 23 / 105 (22%) |
| — of which rewritten by the consolidator (new row or merge) | 9 / 64 |
| — of which promoted in place, gist unchanged | 14 / 41 |

## Per bar, by reading

**Verdicts removed — passes on rewritten records (2 of 64 residual); failed on in-place promotion in
this run, which the fix below closes.**
Of the nine marked rewritten gists, seven are causal-mechanism *so* clauses, measurement dashes or
descriptions; two are verdicts — *"tools/selection_replay.py is BROKEN at 91.3% against the engine"*
and *"… so two arms' modelled dollars aren't comparable when turnover differs"*. Dropped verdicts
include *"so … is wrong"*, *"— use bare `testOnly` instead"*, *"do not re-propose it"*, *"settled
NEGATIVE"* and *"which closes the … question"*. Of the 14 marked in-place gists, these are real
verdicts or orders, repeated byte-for-byte:

- *"… was a July artifact — over 125 days t = -0.29 …"*
- *"… is significantly harmful — t = -2.49 over 399 days …"*
- *"… only work AFTER the fact — …"*
- *"… because price-level trailing stops were tried repeatedly and never worked."*
- *"… — find the run's log path from ps yourself rather than waiting."* — an **order**, which the
  pre-existing observations-not-orders rule already forbids.

The regex selects verdict candidates only and matches no imperative, so all 82 unmarked output gists
were also read, for orders and bare rulings: **no order**, and three borderline *"is X, not Y"*
rulings, each carrying its evidence in the line — *"A single placebo draw is not a control: … sd
~102k"*, *"2022's … outperformance is tail ASYMMETRY, not higher volatility: …"*, *"slippage is a
high-variance two-sided term, not a cost: …"*. All three were promoted in place in this run, before
the promote condition existed. Counted as residuals, the final state carries 7 verdicts or borderline
rulings in 105 output gists — 3 of 72 rewritten, 4 of 33 kept in place — under the bar's pooled
one-in-ten, so they were not re-run.

At the time of this run the prompt's authoring section said a verdict gist *"is never repeated
byte-for-byte to promote an entry in place"*, while the tool description the consolidator reads at
the moment of choosing — `zikaron_memory_promote` — described in-place promotion as the mechanism
with no condition on it. The decision point carried the invitation and not the rule.

**Severity kept — passes.** Rewrites often made severity *more* concrete: *"matching … by timestamp
alone is wrong"* became *"produced 1,856 mismatching instance-days of 2,640"*; *"cannot convert even
a perfectly anti-correlated hedge into value"* became *"cost -46.8% cumulative PnL … selected only
7.8% of the time"*. Contents checked for both: the conclusion survives there.

**Facts and conditions kept — passes.** The words a keyword diff flagged as lost were gist phrasing
that moved to content, or to the other half of a split, or orders the older rule removes.

**Triage kept — passes.** Every gist names its subject. Merges of a claim and its later refutation
became one gist carrying both (*"claimed up to 7.8x … later measured at chance"*).

## Side effect: register was flattened unasked

`re-EVALUATES … NOT re-selection` became `re-evaluates … not necessarily a re-selection`. That is
Q21's tone pass, arriving without being requested. Severity held here, but *"not necessarily"* is a
hedge the finding did not carry — the direction Q21 names as the failure. One instance; evidence for
Q21, not a bar failure.

## The fix, and the targeted re-run that verified it

The fix is at the decision point: `zikaron_memory_promote`'s description and the skill's promote
paragraph now say in-place promotion writes no prose, so it fits only an entry already meeting every
authoring rule (`reviews/m34-prose-review.md` Round 2). Re-run on 20 rows seeded alone
(`seed --rows`, `~/zikaron-m34-replay-inplace/`), in three strata. For the 14 marked rows that review
predicted before the run: real verdicts and orders → new record, verdict in `content`; causal clauses
and measurements → still in place. The 6 unmarked in-place controls were added to catch over-firing,
predicted to stay in place. All real verdicts still in place would have meant the prose had no grip;
all 14 marked rows flipped would have meant it over-fired.

- **Four of the five leaked verdicts and orders left the in-place path.** *"was a July artifact"* became
  *"looked good in July 2021 alone; pooled across six months t = -0.29"*; *"is significantly
  harmful — t = -2.49"* became *"drops per-position win rate from 65% to 31% (t = -2.49, 399 days)"*;
  the order *"find the run's log path from ps yourself"* became the symptom *"polled a detached run to
  completion … leaving the caller waiting for hours"*. The fifth stayed in place: *"… because
  price-level trailing stops were tried repeatedly and never worked"* — a historical record of what
  was tried, which the consolidator read as observation. Borderline, and the one residual.
- **No over-fire on the controls: all 6 still promoted in place.** Five other marked rows also
  stayed in place, each a causal mechanism, a measurement dash or a description — the rule's
  observed side.
- **Mild over-fire on causal clauses, at no loss of content.** Four causal-mechanism rows were
  rewritten anyway. One dropped the observable symptom from the line — *"so pgrep -f … finds nothing
  and a live job looks dead"* became the mechanism alone — so push, which shows gists only, loses the
  words an agent would recognise; pull still finds them, since D21 embeds content too, and the
  content keeps them. One residual verdict word survived a rewrite (*"an unfixable brick-height
  problem"*).

Per bar, for the 8 rewritten: verdicts removed, one residual word (above); severity kept; facts and
conditions kept, contents checked; triage kept by the letter — the pgrep record's rewritten gist,
*"A forked sbt runMain JVM's ps entry is just `java @/tmp/sbt-args<random>.tmp`, with the main class
hidden inside the argfile rather than on the command line"*, still names its subject, but the shape
it lost — *mechanism, so symptom*, where the `so` clause **is** what was observed — is a known limit
of the shipped wording (`FINDINGS.md` Q22 carries it).

Net: 12 in place, 8 rewritten, 0 discarded. The leak is closed; the over-fire costs a spent uuid per
row and, once in four, some of a gist's symptom.

## A fix for the over-fire, refuted

One clause added to "A gist carries no verdict" (`reviews/m34-prose-review.md` Round 3) said a "so"
clause may introduce either what was seen or what the writer concluded, with a minimal pair. Same 20
rows, fresh store (`~/zikaron-m34-replay-inplace2/`): **19 promoted in place, 1 rewritten**. Every
causal symptom survived — and so did three real verdicts, back on the in-place path unchanged:
*"was a July artifact"*, *"is significantly harmful"*, *"only work AFTER the fact"*. Only the order
was still rewritten. The clause was reverted; the shipped text is Round 1's paragraph with Round 2's
promote condition. The over-fire stays as a known limit because its cost falls on push alone, and a
leaked verdict is the failure the rule exists for.
