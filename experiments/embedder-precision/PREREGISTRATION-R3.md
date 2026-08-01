# Preregistration addendum — round 3

**Written 2026-08-01T03:15:04Z**, before any round-3 result was computed or inspected.

> **Chronology caveat, stated up front.** This file has an **amendment log at the bottom**, added
> after results existed, so its filesystem mtime is now *later* than the round-3 result files and
> cannot be used as evidence of when the body was written. Round 2's reviewer already noted that
> mtime is "filesystem evidence rather than a tamper-evident external timestamp"; that is even more
> true here. What can be checked: every threshold and decision rule in §R3.1–R3.6 is either a
> restatement of the frozen `PREREGISTRATION.md` or a rule whose *outcome went against the
> hypothesis it was written to test* (R3.5's tie-causation rule returned negative), and the two
> amendments are disclosures of things that moved, not relaxations of anything.

`PREREGISTRATION.md` is **frozen and unedited**. This is a separate, additive document, written for
the same reason: round 2 of the independent review
(`reviews/embedder-benchmark-independent.md`, round 2) found four analysis/wording defects, and two
of them require *new computation*. Declaring the rules first removes the chance to pick the
favourable estimand or the favourable tie rule after the fact.

**No threshold in `PREREGISTRATION.md` is changed, relaxed or reinterpreted here.** Every gate in
§5 of that file still governs. What follows only (a) disambiguates one estimand that the frozen
document named but did not pin down operationally, (b) fixes a counting bug, (c) declares one
**exploratory** diagnostic and what would have to happen for it to support a causal claim, and
(d) renames two things that were mislabelled.

---

## R3.1 The discrimination index has two estimands; the frozen document declared one

`PREREGISTRATION.md` §5.5 says:

> **The reportable quantity** is the **discrimination index** = mean near-miss margin ÷ mean
> exact-control margin, per model

That is unambiguously a **ratio of means** (RoM). Round 2 reported the RoM as the per-model
aggregate (e.g. 0.2046, 0.2330) but computed the *between-model contrast* as the mean of per-block
ratios (MBR), which is a different estimand — Jensen's inequality alone guarantees they differ.
The report did not say it had switched. Review round 2, BLOCKER 1 is correct.

Declared, before recomputation:

- **Primary estimand: ratio of means (RoM)**, exactly as §5.5 words it. `DI_RoM(model) =
  mean(near_miss margin over all trials of that model) / mean(exact margin over all trials)`.
- The **between-model contrast is the difference of RoMs**, `DI_RoM(A) − DI_RoM(B)`, with a
  **paired cluster bootstrap over the 14 twin sets**: resample twin sets with replacement, and
  *within each resample* recompute both models' RoM from the resampled blocks' near-miss and exact
  margins, then take the difference. Same resample applied to both models. 10 000 resamples,
  95 % percentile interval. This is a ratio estimator, so the bootstrap distribution is not
  expected to be symmetric and the point estimate is the full-sample RoM difference, not the
  bootstrap mean.
- **Secondary estimand: mean block ratio (MBR)** = mean over the 14 blocks of
  `(block near_miss margin / block exact margin)`. Reported *alongside* RoM, named, with its own
  paired-block CI. It is retained because it is what round 2 quoted, and dropping it silently would
  hide a correction.
- **The §5.5 gate is unchanged and is applied to the primary estimand**: a between-model difference
  counts as a capacity effect only if the paired-by-block CI excludes 0 **and** the point
  difference is **≥ 0.15**. If the two estimands disagree about the CI, that disagreement is
  reported rather than resolved in whichever direction is convenient.

## R3.2 Wording: what the instrument can and cannot conclude about capacity

`PREREGISTRATION.md` §5.1 already forbids "scale is disproved" language for the *task* comparison.
The same restriction is hereby declared to apply to the *instrument* comparison, because Threat 5 of
the report (quantized bge-small vs unquantized bge-large) applies identically there — the
instrument uses the same two deployed artifacts.

Permitted form: **"this deployed bge-large artifact did not materially improve the controlled
identifier instrument"** / "no demonstrated capacity remedy". Forbidden forms: "capacity does not
help", "capacity does not fix it", "refuted" applied to capacity as a mechanism.

## R3.3 The v1-development versus v2-blind gap is descriptive, not causal

Round 2 called the dev−blind difference "self-authorship inflation" and said it *isolates* query
authorship and *bounds* the effect. It does not: the two sets differ in author **and** in register,
length, detail level and deliberate underspecification (39/192 rows). Author identity is not
separable from that distribution change. Review round 2, BLOCKER 2 is correct.

Declared:

- The quantity is renamed the **v1-development versus v2-blind query-set gap** everywhere, in code
  keys and in prose. The words "isolates", "inflation", "real" and "bounds" are not used of it.
- It is a **sensitivity analysis**: it shows the aggregate is not robust to swapping the query
  distribution, which is a reason to distrust round-1 conclusions drawn from differences of that
  size. It **supports no decision** and estimates no general rate.
- One interval is added for completeness — a cluster bootstrap over stubs of
  `dev(stub) − mean(3 blind variants of that stub)` — and is labelled as an interval on **this
  set difference**, not on an authorship effect.

## R3.4 The top-5 tie statistic: a counting fix, declared before recomputation

`retrieval2.rrf_counted` incremented `ties_in_top5` by the **number of tied adjacent pairs** inside
the top five, and `tie_report` then divided that by the query count and called it
`frac_queries_with_tie_inside_top5`. A query with two adjacent ties contributed 2. The reported
"12.5 % of queries" is therefore not the quantity named. Review round 2, BLOCKER 3 is correct.

Declared before rerunning: the fix is a **per-fusion boolean** (`any_tie_in_top5`), reported as
`frac_queries_with_any_tie_inside_top5`. The pair count is retained under an honestly named key
(`mean_tied_adjacent_pairs_in_top5`). Both are **facts about this implementation** and fall under
`PREREGISTRATION.md` §6 (exempt from effect-size gates, quoted with host/version qualifiers).
Whatever the corrected number turns out to be, it replaces the old one; there is no version of this
where the old number survives.

## R3.5 Do insertion-order ties *cause* the hybrid to absorb the dense gain? — EXPLORATORY

Round 2 observed that bge-large beats bge-small dense-only and not in the RRF hybrid, and offered
tie-breaking by insertion order as the mechanism. Tie *prevalence* does not establish that.

This diagnostic is **exploratory** under `PREREGISTRATION.md` §7 and **may not support a
decision**. It is declared here only so that the decision rule is fixed before the numbers exist.

Design: recompute the hybrid configurations under four tie-handling rules, changing nothing else
(same arms, same `k=60`, same depth, same query set, same labels):

| Rule | What it does |
|---|---|
| `bm25_first` | the canonical round-2 behaviour: BM25 arm passed first, Python stable sort |
| `dense_first` | dense arm passed first, so insertion order favours dense instead |
| `tiebreak_dense` | explicit deterministic tie-break on the dense arm's own rank |
| `tiebreak_bm25` | explicit deterministic tie-break on the BM25 arm's own rank |

**Declared decision rule.** Insertion-order ties will be described as the *cause* of the vanishing
dense gain only if the `large_vs_small_hybrid` `useful_hit@5` contrast reaches the §5.1 adoption
threshold — **point ≥ +0.05 with a 95 % CI excluding 0** — under **at least one** of the three
alternative rules. If it does not, the report must say that ties are a **design defect of
unquantified consequence** and that the mechanism behind the vanishing gain is **not established**.
Intermediate outcomes (the contrast moves, but not to the threshold) are reported as a measured
sensitivity with the movement quoted, and still do not license the causal claim.

A second, non-tie decomposition is run alongside, and is also exploratory: for the queries where
bge-large's dense arm puts a primary in the top 5 and bge-small's does not, count how many of those
primaries were **already** in the BM25 arm's top 5 (so fusion had nothing to add) versus how many
were **lost** in fusion. This measures the alternative mechanism — unweighted RRF over two arms
lets the arm that already agrees dominate — without appealing to ties at all.

## R3.6 `L_G_split` is a composite, not an isolated factor

`L_G_split` is `RRF(BM25 unicode61 gist+content, BM25 tokenchars tokens-only)` and was compared
against a single BM25 ranking (`L_A_unicode61`). That contrast changes four things at once: it adds
the tokens index, adds a second retrieval arm, introduces RRF rank normalisation, and inherits
insertion-order tie behaviour. Calling it "custom tokenization confined to the tokens field" was
wrong. Review round 2, BLOCKER 4 is correct.

Declared: the contrast is renamed **`split_index_composite`** and described as a **composite
split-index RRF architecture comparison**. No new experiment is run, because the decision-bearing
contrast for the tokens column is `L_E_tok_w3` vs `L_B_tokchar` (tokenizer and original fields held
fixed), which is unaffected, and the non-adoption decision already rests on the failed held-out
extractor gate.

## R3.7 What round 3 does not attempt

Unchanged from round 2 and restated so no reader mistakes silence for progress: the corpus is still
synthetic and still 187 memories; the graded labels still share an author with the memories; there
is still no held-out repository; the hook→MCP path is still unmeasured; and 512-token truncation is
still declared unsettleable by this dataset.

## R3.8 Frozen input hashes, re-verified at the time of writing

`verify_freeze.py` passed on all seven artefacts at 2026-08-01T03:13:56Z, immediately before this
file was written. The round-2 result files
(`results/eval_v2.json`, `results/twin_counterfactual.json`, `results/extractor_heldout.json`,
`results/tokens_cost.json`, `results/rerank_scaling.json`) are also hashed below, so the round-3
reruns can be shown to have changed only what they were supposed to change.

```
9e3b9f4239bcfb0bc3fc78451a0e222e784ac477192510b619f181c435c70222  results/eval_v2.json
ee3c0984e39489424d9a22237dd607d9e021ad5efc6fe80b8f94cb412bdbb847  results/twin_counterfactual.json
cd22631289e97343b8ce7f48e67ad535fab10602541265bbbe0787b1372f2452  results/extractor_heldout.json
32ae2da39ee6e913a2521f765f36c9654331623d801876bf5027ae9e487c14d7  results/tokens_cost.json
7402c39def09019ae119a0b757a9c014c355d2a106048bf85a7b8fe6d6c16063  results/rerank_scaling.json
174d9bb900367a0d80c4a126ff81e05609c815ca6a766950df12511fa9801c3a  results/eval_v2_gist_only.json
7550e0c592fa5493d2ddb95dfa4b962f9a2ab6738012804c9f1d7ac1337f0072  results/latency.json
```

Expected changes from the round-3 reruns, declared in advance so an unexpected one is visible:

- `results/eval_v2.json` — **only** the `ties` blocks (R3.4 counting fix), the renamed
  `query_set_gap` key (R3.3), and the renamed `split_index_composite` contrast label (R3.6). Every
  metric, contrast point estimate and CI must be **bit-identical**, because inference is
  deterministic and the embedding cache is keyed by model name. If any metric moves, something is
  wrong and it must be found before the report is touched.
- `results/twin_counterfactual.json` — **added** RoM/MBR estimand labelling and the RoM-difference
  bootstrap (R3.1). All existing margins, per-block values and win rates must be bit-identical.
- The other five round-2 result files are **not re-run** and their hashes must not change.

---

## Amendment log

Everything above this line was written **before any round-3 result existed**. Anything appended below
was written **after**, is timestamped, and is listed here rather than edited into the text above —
because a silently-edited preregistration is worth nothing.

**A1 — 2026-08-01T03:41Z, disclosure only, no threshold or decision rule changed.**
One value moved that the "expected changes" list above did not anticipate:
`twin_counterfactual.json` → `models.*.*.discrimination_index.aggregate` changed in the **fourth
decimal** (0.2046 → 0.2045, 0.2330 → 0.2331, 0.2085 → 0.2087, and carrier 0.2094 → 0.2096). Cause:
round 2 computed `aggregate` by dividing two margins that had *already* been rounded to 4 dp, while
the new `ratio_of_means` bootstrap works from the unrounded per-block margins. Rather than carry two
nearly-identical numbers, `aggregate` was made to return `ratio_of_means.point`, so there is exactly
one discrimination index per model per probe. The letter of the constraint above was not broken —
"all existing margins, per-block values and win rates" *are* bit-identical, and `aggregate` is none
of those — but the omission is recorded because the report quotes the number. `report_figures.py`
asserts `aggregate == ratio_of_means.point`.

**A2 — 2026-08-01T03:44Z, addition to an exploratory diagnostic, declared after the fact and
labelled as such.** R3.5's second diagnostic was extended with two descriptive counts —
mean size of the two arms' candidate-set intersection and union — to test whether "all fused top-5
slots come from the intersection" is trivially true. It is not (21.7 of 77.3, 28 %). This is a
descriptive statistic on the retrieval arms, not a hypothesis test, it was added after seeing the
100 % figure specifically because a reader would challenge it, and it remains **exploratory** and
decision-free like the rest of R3.5.
