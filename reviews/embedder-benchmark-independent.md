# Independent review — embedder benchmark and conclusions

## Round 1 — 2026-07-31

### Summary judgment

This is a useful engineering probe and a much more candid report than most synthetic benchmarks, but it is not capable of settling the model-quality and mechanism questions at the specificity claimed. The strongest results are operational facts about these exact implementations—latency, the failure of this 50-pair CPU reranker, and the loss from gist-only embeddings—while the model ordering, extracted-token benefit, and twin-duel mechanism claims are under-controlled and underpowered. Several conclusions are safe only in narrower forms than the report states; conclusion 3 is not ready for adoption, and conclusion 8 should be withdrawn rather than merely caveated.

### Findings

1. **[BLOCKER] [Conclusions 1, 2, 3, 5, 7, 8] The synthetic, self-authored set invalidates the report's production-distribution claims, not merely their decimal precision.** In `experiments/embedder-precision/dataset.json` (`queries`, especially `q-c1-*`, `q-c2-*`, and `q-c5-*`), the same author knew each target while choosing both the query wording and the distractors. This specifically invalidates “realistic full queries make the identifier weakness moot” (8), “bge-small is adequate in practice” (1), and the claimed production value of the prefix and token extractor (2–3): those depend on how real users phrase prompts, not just on deterministic behavior over fixed text. It does **not** invalidate measured process latency (6), proof that these six records exceed 512 BGE tokens (5), or the observed behavior of the exact reranker run (4). Replace the architecture-closing language with “hypotheses from a synthetic development set,” and require a held-out set of real memories with prompts authored by someone who has not read the target memory before closing conclusions 1, 3, or 8.

2. **[BLOCKER] [Conclusions 1, 2, 3, 8] The aggregate is dominated by saturated categories and an arbitrary category mixture.** In `research/embedder-benchmark-results.md` (`Results / recall@5`), 28 near-miss and 10 error-string queries—38/64, 59% of the set—score 1.000 for every configuration. For the hybrid model comparison, polarity and over-length also score 1.000, so the bge-small/large/nomic recall ordering is effectively decided by only the ten paraphrase queries: 6/10, 5/10, and 8/10 respectively. The ALL row therefore does not estimate production quality; it is a weighted average whose weights were chosen by dataset construction. Report unsaturated-category counts and paired outcomes first, omit an overall “winner” unless category weights come from observed usage, and stop using ALL recall to settle model choice.

3. **[BLOCKER] [Conclusion 8; secondarily 1] The twin duel does not isolate sub-token identity, and 28 trials are only 14 dependent twin sets.** `experiments/embedder-precision/twin_duel.py` embeds a bare identifier but compares it against two full, topically different documents. Passage topic, identifier frequency, document length, and asymmetric containment remain available. Several pairs are nested (`AUTH_TOKEN`/`AUTH_TOKEN_V2`, `staging`/`staging-2`, `retry_backoff`/`retry_backoff_ms`): the newer document often mentions both forms while the older document mentions only the base form, producing directional wins/losses without demonstrating fine-grained token representation. Each pair is then counted twice with reversed gold, so the 28 Bernoulli observations are correlated. “Chance = 0.500” is only the random-guess baseline; it is not a justified sampling null for these non-exchangeable, deterministically labeled passages. Build a counterfactual instrument with byte-identical passage templates whose identifiers are swapped, randomize assignment, treat each twin set as the statistical block, and include exact-token and token-masked controls.

4. **[MAJOR] [Conclusion 8] The claimed scale effect is two or three dependent outcomes and is not evidence of a monotonic capacity effect.** In `results/twin_duel.json` (`*.probes.bare`), prefixed bge-small wins 20/28, bge-large 22/28, and nomic 23/28. Those are differences of two and three outcomes over the same 14 underlying sets; no paired test or block bootstrap is reported, and nomic changes tokenizer, training, dimensions, context, and quantization rather than “scale.” The neutral probe is tied at 21/28 for large and nomic, while mean bare margins are 0.0375, 0.0419, and 0.0356—no monotonic scale pattern. Discard “scale measurably helps” and “mechanistically confirmed”; the supported statement is only that this diagnostic produced imperfect, model-dependent ordering.

5. **[BLOCKER] [Conclusion 3] Config 5 is not an ablation of an extracted `tokens` column.** In `experiments/embedder-precision/retrieval.py` (`build_lexical`, `TOKENIZE_TEXT`, `TOKENIZE_TOK`, and `bm25`), baseline `fts_text` uses ordinary `unicode61`, while config 5 queries `fts_tok`, where the custom `tokenchars '_-./'` tokenizer applies to **gist and content as well as tokens**. Thus config 5 simultaneously (a) changes tokenization of the original fields, (b) adds an extracted field, (c) weights that field 3×, and (d) repeats every whole extracted token twice in `identifiers.extract`, effectively adding another undocumented term-frequency boost. The MRR change cannot be attributed to identifier extraction. Run a clean factorial ablation: same custom tokenizer without a tokens field; tokens field present but weight 0/1/3; no duplicate emission; and, ideally, a baseline where only the extracted field receives custom tokenization.

6. **[BLOCKER] [Conclusion 3] The extractor was developed against the test traps and has no held-out precision or harm evaluation.** `identifiers.py` names the `conftest.py`/`conf_test.py` case in comments and was changed after the first implementation collided on that exact evaluation pair. Fixing a known bug was reasonable engineering, but it makes this dataset a development set, not evidence for generalization. The regex set is tailored to the authored trap shapes, and false positives on URLs, Windows paths, scoped packages, hashes, mixed-language identifiers, prose numbers, and punctuation-heavy commands were not measured. Freeze the implementation, test it on unseen real memories and identifier pairs, report extraction precision/recall plus retrieval regressions, and only then decide whether to add schema and index complexity.

7. **[MAJOR] [Conclusion 3] The reported improvement fails the report's own noise rule and its cost is not measured.** `research/embedder-benchmark-results.md` says differences below about 0.05 are noise, then promotes MRR 0.8372→0.8822, a 0.0450 change, as the best-value result. The displacement changes are three outcomes among 40 overall and two among 10 polarity queries; recall is identical. `wall_seconds_all_queries` excludes extraction, index creation, database growth, write/amend maintenance, and cache effects, so “negligible cost” is also unmeasured. Treat conclusion 3 as rejected for now, measure paired confidence intervals at the query/topic level, and report index bytes plus insert/amend p50/p95 before adoption.

8. **[MAJOR] [Conclusion 1] The benchmark never performs the necessary dense-only large-vs-small task comparison.** `experiments/embedder-precision/sweep.py` has dense-only configs only for bge-small; bge-large and nomic are tested only behind BM25+RRF. Fixed unweighted RRF can mask or invert dense-arm improvements, and `rrf()` resolves exact score ties by insertion order, favoring the first (BM25) arm. Therefore config 4p vs 6 is an operational pipeline comparison, not a clean embedder-capacity comparison. Add dense-only large and nomic configurations, report paired rank changes and candidate overlap, and either define a semantic tie-breaker or quantify tie frequency.

9. **[MAJOR] [Conclusion 1; secondarily 8] The quantization confound is acceptable for a deployment comparison but breaks the causal scale control.** `research/embedder-benchmark-results.md` (`Threats to validity #6`) argues that quantized small matching unquantized large “only strengthens” the anti-scale quality finding. That assumes quantization has a monotonic harmful effect and ignores export/runtime differences; neither is established here. It is fair to compare the exact fastembed artifacts Zikaron would deploy and conclude that large has no demonstrated operational benefit. It is not fair to call this a scale-only control or infer that capacity is the wrong axis. Reframe conclusion 1 as “do not pay for this deployed bge-large artifact on current evidence,” not “bge-large is worse” or “scale is answered no.”

10. **[MAJOR] [Conclusions 1 and 2] The report violates its own statistical rule for both headline comparisons.** With 64 queries, bge-large's 0.9219 vs bge-small's 0.9375 is one query, and the MRR gap is 0.014. The prefix's dense-only 0.9062→0.9531 is three queries and 0.0469—also below the stated 0.05 threshold—while the actual hybrid configs 4 vs 4p have identical recall (0.9375), identical near-miss displacement (0.0357), and only +0.013 MRR. No confidence intervals, paired randomization test, or topic-block bootstrap is provided. Conclusion 1 may say “large did not demonstrate an improvement”; conclusion 2 may recommend the documented prefix as a low-risk convention, but must not call it proven free quality in the production hybrid.

11. **[MAJOR] [Conclusions 1–5] One-gold labeling is incomplete and sometimes calls an equally useful memory a hard negative.** In `dataset.json`, `c2-cert-chain` and `c3-ssl-verify` encode essentially the same missing-intermediate diagnosis, yet `q-c3-03` labels the former a hard negative; `c1-ver-2-3-1` and `c3-symbol-lookup` likewise encode the same glibc/pipeline diagnosis and are opposed for `q-c3-06`. Other topically adjacent distractors can also be useful. Since D12 shows five gists, returning both is not a retrieval failure. Have independent annotators assign all relevant memories (preferably graded relevance/currentness), measure recall of the relevant set and harmful-stale exposure separately, and reserve “hard negative” for a record that would actually mislead the agent.

12. **[MAJOR] [Conclusion 7] The polarity statistic is described with the opposite semantics for four of its ten queries.** In `dataset.json` (`q-c4-06` through `q-c4-09`), the old memory is deliberately gold because the prompt asks about an old version or historical reason. There, displacement means the newer correction outranked the historically relevant old record—not that “a superseded memory outranks its correction.” The aggregate 0.300–0.500 therefore cannot support the quoted “roughly half the time” staleness claim. Split current-action and historical-intent queries, label both records' usefulness, and evaluate the structural policy: a `superseded_by` edge is sound, but blanket suppression of the old node would fail the historical prompts this dataset intentionally includes.

13. **[MAJOR] [Conclusions 3, 7, 8] `hnd` is not computed over the full corpus ranking as claimed.** `retrieval.py` caps each arm at `FUSE_DEPTH = 50`; `sweep.evaluate` then calls that returned list the full ranking. A pair absent beyond the top 50 (or absent from both top-50 arm unions) is assigned default positions and may be counted as not displaced. The raw output already contains `null` gold and hard-negative ranks. Rename this metric to “displacement within returned candidate union,” or retrieve/scored all 187 documents for the diagnostic. `hnd_top5` remains operationally interpretable and should be the primary displacement measure for D12.

14. **[MAJOR] [Conclusion 4] The evidence rejects one exact reranker deployment, not cross-encoder reranking as a remedy.** `sweep.py` chooses the best first stage on this same test set and reranks nomic, not the incumbent bge-small pipeline. The six over-length documents share a near-identical 600+ token prefix, so the 1.000→0.333 collapse is partly a deliberately cloned-tail artifact. Nevertheless, `results/latency.json` robustly shows about 6.1 s for this exact 50-pair CPU setup, which is sufficient to reject it from the push path. Narrow the conclusion to `bge-reranker-base`, 50 unchunked gist+content pairs, CPU push path; do not generalize to smaller rerankers, fewer candidates, gist-only reranking, chunked passages, or the pull path.

15. **[MAJOR] [Conclusion 5] “Embed gist+content” survives, but “accept truncation because BM25 rescued every case” does not.** The gist-only drop is large (dense recall 0.9531→0.7969; paraphrase 0.8→0.2) and directionally credible even under this weak set: omitting content removes information. By contrast, all six over-length records in `dataset.json` reuse almost the same long prefix and place query-matching terms in synthetic tail punchlines; this makes dense collisions and lexical rescue unusually likely. Six cases are one case template, not six independent examples, and no real length distribution was measured. Adopt gist+content as the default, but keep truncation/chunking open until real long memories are tested; do not record “512 truncation accepted” as settled.

16. **[MAJOR] [Conclusion 6] The subprocess finding is actionable, but the proposed warm-MCP alternative remains unmeasured.** `results/latency.json` has only four “cold” launches on one host with model files already downloaded and filesystem pages plausibly warm; it is process-cold, not reboot/download-cold. It still clearly establishes an avoidable ~0.78 s per-message cost for this machine, so rejecting a fresh model process in every hook invocation is reasonable. But MCP lifecycle, IPC latency, concurrent requests, startup races, hook failure behavior, and whether the server is always resident were not tested. Keep the narrow prohibition, then run an actual hook→MCP smoke/latency test before settling the replacement architecture.

17. **[MINOR] [Conclusion 2] The prefix is not literally free.** `results/latency.json` measures warm embedding at 5.45 ms without the prefix and 6.64 ms with it, with end-to-end p50 7.97→9.14 ms. The absolute increment is small and likely acceptable, but “free” is factually wrong. Call it a low-cost, reversible, model-documented change and guard it with a real-data regression test.

18. **[MINOR] [All conclusions] The report presents deterministic reruns as statistical replication.** `sweep.py` sets a seed, but there is no sampling in model inference; rerunning the same text does not estimate dataset uncertainty. The needed uncertainty is over memories, prompt phrasings, users, topics, and repositories. Add paired bootstrap or randomization intervals blocked by twin/topic, multiple independently authored query variants, and a held-out repository; do not imply that a single deterministic run establishes rate precision.

### Minimum evidence needed before the next architecture-closing pass

1. Freeze all extractors/configuration before evaluation and build a held-out set from real Zikaron-like memories; have a second person/agent author prompts without seeing target wording.
2. Obtain complete or graded relevance labels, separate current-action from historical-intent queries, and report harmful stale exposure separately from useful recall.
3. Add dense-only small/large/nomic controls; frame quantized-vs-unquantized results as deployed-artifact comparisons unless matched exports are used.
4. Replace the twin duel with counterfactual identifier swaps in identical passage templates and analyze by independent twin set, not by the two mirrored queries.
5. Run the tokenizer×extracted-field factorial ablation, with held-out extractor tests and measured index/write/storage costs.
6. Report paired, topic-blocked uncertainty and raw changed-query counts; predeclare the smallest effect worth an architecture change.

## VERDICT

**Safe to act on now, in narrowed form:** (1) keep bge-small and do not deploy this bge-large artifact **for now**, because large has large measured operational cost and no demonstrated task gain—not because it was proved worse or scale was disproved; (2) add the documented BGE query prefix as a low-risk convention, not as proven hybrid quality; (4) reject this exact `bge-reranker-base`/50-pair/CPU push-path configuration, not reranking in general; (5) embed gist+content rather than gist alone, while leaving truncation/chunking open; (6) do not start a fresh embedding model process on every `userPromptSubmit`, while separately validating hook→MCP IPC; (7) store structural supersession metadata, but do not blanket-suppress history or quote the mixed polarity rate as “obsolete outranks correction.”

**Needs more evidence before acting:** (3) the extracted-identifier column. Its current positive result is causally confounded, below the report's own noise threshold, developed on the test traps, and missing cost/harm measurements. The underlying idea remains plausible and deserves the clean ablation above.

**Discard as stated:** (8) “mechanistically real but practically moot.” The twin duel does not isolate the proposed mechanism, its effective sample is 14 dependent sets, its model differences are two or three outcomes, and the “realistic” full-query success is exactly what self-authorship and topic leakage inflate. Also discard the stronger subclaims embedded in (1), (2), and (5) that bge-large is genuinely worse, the prefix is free proven quality, or 512-token truncation has been safely resolved.

VERDICT: NEEDS_CHANGES

## Round 2 — 2026-07-31

### Summary judgment

The remediation resolves most of Round 1: the primary set is credibly independent of the memory prose and contains realistic terse/mid/verbose prompts; the stub leakage check reports zero 3-word overlaps; the main uncertainty is correctly clustered by stub; and the extractor, dense-only, reranker, displacement, and counterfactual results are now honestly scoped. The preregistration chronology is also credible from the checked-in artefacts: its 02:29 UTC file time precedes the new harness files and every round-2 result timestamp, and all frozen hashes still match, although this is filesystem evidence rather than a tamper-evident external timestamp. Approval is blocked only by four analysis/wording defects below; none requires a larger or real-repository dataset.

### Round 1 finding disposition

1. **Partially resolved, residue disclosed and nonblocking.** Query-side prose leakage is substantially repaired: `stubs_v2.json` exposes short situations and user-side identifiers but not memory prose or answer-side identifiers, `queries_blind.json` is varied and realistic rather than uniformly sanitised, and `results/stub_leakage_v2.json` reports zero forbidden 3-word overlaps. The remaining synthetic corpus, author-provided labels, and attested rather than mechanically provable blindfold are disclosed. The separate causal claim about “self-authorship inflation” is still open as Finding 2 below.
2. **Resolved.** `research/embedder-benchmark-results.md` leads with category counts, identifies saturation and construction-chosen weights, and does not select an overall winner from the ALL row.
3. **Resolved.** `twin_counterfactual.py` uses matched templates, both directions, the twin set as the block, and valid zero-margin floor and distinct-token ceiling controls.
4. **Partially resolved.** The old 20/28→22/28→23/28 scale claim is withdrawn and block-level uncertainty is present, but a broad capacity conclusion has been reintroduced despite the acknowledged artifact confound; see Finding 1.
5. **Resolved for the decision-bearing contrast.** `L_E_tok_w3` versus `L_B_tokchar` holds tokenizer and original fields fixed, while weights and duplicate emission are separately varied. The optional split-index arm is still mislabeled as isolating one factor; see Finding 4.
6. **Resolved.** The frozen extractor is evaluated on held-out classes, fails decisively, and the tokens column is not adopted. The lack of blindness is disclosed.
7. **Resolved.** The report honors preregistered gates, provides stub-clustered intervals and changed-query counts, and measures storage, extraction, insert, and amend costs. The fixed baseline-first trial order is a minor timing-design limitation but cannot plausibly change the ≤5 ms gate outcome given the reported range.
8. **Partially resolved.** Dense-only large/nomic controls are present and correctly reverse Round 1’s embedder-quality story. The new RRF tie diagnostic contains a counting error and is used causally without a sensitivity run; see Finding 3.
9. **Partially resolved.** The task comparison is correctly framed as deployed-artifact evidence and the “quantization only strengthens” argument is gone, but the counterfactual section again calls the result a refutation of capacity; see Finding 1.
10. **Resolved.** Headline comparisons now carry paired intervals, raw direction counts, and preregistered decision thresholds; the prefix is explicitly low-cost rather than free.
11. **Partially resolved, residue disclosed and nonblocking.** Graded primary/also-useful/harmful labels repair the one-gold error and the named false negatives. Independent annotation remains absent and is plainly disclosed.
12. **Resolved.** Current-action and historical-intent semantics are separated; harmful displacement excludes the historical prompts, and blanket suppression is tested against them.
13. **Resolved.** `harmful_disp@5` is primary, depth 187 is run, and pure-BM25’s matching-set limitation is accurately disclosed.
14. **Resolved.** The reranker conclusion is limited to `bge-reranker-base`, this CPU, and the push path; smaller models, GPUs, chunking, and pull are left open.
15. **Resolved.** Gist+content is supported on the blind set, while the 512-token decision is explicitly open and was declared unsettleable before round-2 results.
16. **Partially resolved, residue disclosed and nonblocking.** The process-cold prohibition is narrow and supported; hook→MCP remains explicitly unmeasured rather than assumed.
17. **Resolved.** Prefix latency is quoted in the recommendation and “free” is removed.
18. **Resolved.** Deterministic reruns are no longer treated as replication; query uncertainty is clustered by stub and phrasing-register spread is reported.

### Findings

1. **[BLOCKER] The report re-widens “no demonstrated improvement from this artifact” into the causal claim “capacity does not fix it,” despite its own quantization caveat, and the quoted DI difference is not the difference of the displayed DIs.** `research/embedder-benchmark-results.md` headline 3, the settled/open table, section 7 (“Capacity does not help”), and “Implications / Open question 4” call capacity refuted. Yet Threat 5 correctly says quantized bge-small versus unquantized bge-large is **not** a clean capacity control. In addition, `twin_counterfactual.py` reports aggregate DI as ratio of mean margins (`0.2330 - 0.2046 = 0.0284`) but computes the quoted `+0.0181` model contrast as the mean difference of per-block ratios; those are different estimands, and the report does not say it switched. Replace the causal language with “this deployed bge-large artifact did not materially improve the controlled identifier instrument” / “no demonstrated capacity remedy,” and either bootstrap the declared ratio-of-means difference or explicitly define and report the mean block-ratio estimand alongside the aggregate values. The unchanged practical conclusion may remain.

2. **[BLOCKER] The dev-versus-blind gap does not isolate or bound an authorship effect.** `research/embedder-benchmark-results.md` headline 8, Methods (“dev-vs-blind isolates query authorship”), section 2 (“Self-authorship inflation, measured”), and Response 1 call the mean `+0.0106` a real, bounded self-authorship inflation. `eval_v2.py` compares one v1 prompt per stub with the mean of three newly written prompts having deliberately different registers, lengths, details, and underspecification; author identity is inseparable from that query-distribution change. Averaging the gaps over 18 highly correlated configurations × 2 depths is also descriptive, not an uncertainty estimate for a general inflation rate. Rename this throughout as the **observed v1-development versus v2-blind query-set gap**, retain it as a useful sensitivity analysis, and remove “isolates,” “real,” and “bounds the damage.” If an interval is wanted, bootstrap the per-stub dev value against the mean of that stub’s three blind variants, but still do not interpret it causally as authorship alone.

3. **[BLOCKER] The headline top-five tie percentage is not the metric the harness computes, and tie prevalence alone does not explain why hybrid fusion erases the dense gain.** In `retrieval2.py` `rrf_counted`, `ties_in_top5` is incremented by the **number of tied adjacent pairs** among the top five; `tie_report` then divides that count by queries and labels it `frac_queries_with_tie_inside_top5`. A query with two adjacent ties contributes twice, so the report’s “12.5% of queries” / “1 in 8 queries” in Facts, section 3, and Implications is not established. Further, insertion-order ties are a plausible mechanism, but no arm-order swap or explicit tie-break sensitivity shows that they caused the large model’s gain to disappear. Track a per-fusion boolean for “any top-five tie,” rerun the diagnostic and figure assertions, and describe ties as a possible mechanism/design defect unless a tie-break or arm-order sensitivity actually quantifies their effect. This does not invalidate the observed current-pipeline comparison.

4. **[BLOCKER] The `L_G_split` contrast still confounds the factor it is said to isolate.** `eval_v2.py` labels `split_tokenization` as isolating “custom tokenization confined to tokens,” and `research/embedder-benchmark-results.md` section 4 places it under “Contrast — what it isolates.” But `retrieval2.py` implements `L_G_split` as RRF between a baseline BM25 arm and a token-only BM25 arm, whereas `L_A_unicode61` is one BM25 ranking; the contrast simultaneously adds the tokens index, a second retrieval arm, RRF rank normalization, and insertion-order tie behavior. Relabel it as a **composite split-index RRF architecture comparison**, not an isolated effect. No new experiment is required because the clean `L_E` versus `L_B` contrast and failed held-out extractor already support the non-adoption decision.

VERDICT: NEEDS_CHANGES

## Round 3 — 2026-07-31

### Summary judgment

The four Round 2 blockers are genuinely resolved: the counterfactual comparison now uses and bootstraps the preregistered ratio-of-means estimand, capacity language is artifact-scoped, the dev/blind difference is noncausal, tie counting and causal sensitivity are separated, and `L_G_split` is honestly labelled composite. The preregistration trail is credible though not externally tamper-evident: `PREREGISTRATION-R3.md` states 03:15 UTC, before `eval_v2.json` at 03:21 and `tie_sensitivity.json` at 03:32, preserves the Round 2 gates, and openly segregates post-result amendments. The blind-query independence remains necessarily attested rather than mechanically provable, but the prose-free stubs, zero reported 3-word leakage violations, user-side-only identifiers, and realistic terse/mid/verbose prompts support the claimed scope; the residual synthetic-corpus and shared-label-author limits are disclosed rather than overrun.

### Round 2 finding disposition

1. **Resolved.** `twin_counterfactual.py` now computes the primary contrast as a paired twin-set bootstrap of the difference between two recomputed ratios of means, reports the old mean-block-ratio estimand separately, and applies the unchanged 0.15 gate to the former. `research/embedder-benchmark-results.md` consistently limits the inference to the deployed artifacts and explicitly says capacity itself is untested.
2. **Resolved.** `evalkit.py::set_gap_bootstrap` operates on each stub's development value minus its three-variant blind mean, while the report and JSON call this a query-set gap and deny an authorship interpretation or decision role.
3. **Resolved.** `retrieval2.py::rrf_counted` separately records a per-query top-five-tie boolean and an adjacent-pair count. `tie_sensitivity.py` holds arms and scoring fixed across four tie rules; the maximum useful-hit contrast movement is 0.0052, so the report withdraws the tie-causation claim and labels both replacement diagnostics exploratory.
4. **Resolved.** `L_G_split` / `split_index_composite` is labelled a composite everywhere decision-bearing, and the untested single-field-tokenization question is disclosed. The token-column rejection does not rely on this arm.

Round 1's 18-finding disposition remains as recorded in Round 2: 12 resolved and 6 partially resolved with their residue disclosed and nonblocking under the stated approval bar. In particular, this review does not convert the acknowledged synthetic corpus, non-independent labels, unmeasured hook→MCP path, or unavailable clean single-field tokenizer arm into new requirements.

### Findings

1. **[NITPICK] The report overstates the numerical precision feeding the revised discrimination index.** `experiments/embedder-precision/twin_counterfactual.py` builds `nmb` and `exb` from `res[*]["per_block_margin"]` after those values have been rounded to six decimals, while `PREREGISTRATION-R3.md` amendment A1 and `research/embedder-benchmark-results.md` (Round 2 response R2-1) say the shared code path uses “unrounded per-block margins.” This is immaterial at the reported four-decimal precision and changes no interval, threshold, or conclusion. For literal reproducibility, either retain full-precision per-block dictionaries for `rom_bootstrap` / `paired_rom_bootstrap`, or change those two descriptions to “six-decimal per-block margins rather than four-decimal aggregate margins.”

VERDICT: APPROVED

---

## Erratum 1 — 2026-08-01, raised by the design-corpus review (round 6, finding 3)
> **Status: APPLIED IN PLACE, 2026-08-01** (design-corpus review round 7, finding 2). Originally recorded here
> only, because `research/embedder-benchmark-results.md` is an **approved, frozen artifact** and the
> remediation's write scope was `design/`, `reviews/` and `FINDINGS.md`. Round 7 correctly held that an
> *external* erratum does not make the cited report internally sound: a reader of that document still met a
> claim contradicted by its own zero-margin null, its 14/14 signed blocks, and the absence of any lexical arm
> in the instrument. The report now carries this erratum inline at the §7 site, **quoting the withdrawn clause
> verbatim** so nothing is silently rewritten and the audit trail survives in both directions. The correction
> is a narrowing of one sentence and is **binding on the corpus**: no design document asserts the withdrawn
> claim, and `design/retrieval.md` §"The identifier weakness is real and unremedied" carries it inline too.

**Location.** §7, the paragraph beginning "On 'mechanistically real but practically moot'", final clause.

**The sentence, as written.** "If Zikaron ever holds memories that are near-identical apart from a version, the
0.20 is the relevant number and the lexical arm is the only thing standing between the agent and a coin flip."

**Why it is unsupported, on the report's own evidence.** Two independent defects, both of them the estimand
error this trail has now caught three times.

1. **"Coin flip" contradicts §7's own null.** The same section establishes that *blindness implies margin
   exactly 0, not 50/50* — the `identity` control returns 0.000000 for all four models × two probes — and the
   measurement then finds the correct direction in **14 of 14 blocks** (sign test p ≈ 1.2 × 10⁻⁴). A signal that
   is directionally right in every block is *weak*, not absent. §9's own restatement says so: "blindness implies
   margin 0, not a coin flip." So the closing clause asserts the null the section spent two controls refuting.
2. **"The only thing" is an exclusivity claim about an arm the instrument never ran.** The counterfactual
   instrument embeds a probe query against two passage templates under four **embedders**. It contains no BM25
   arm, no fusion step and no ranking metric, so it can neither establish that lexical matching compensates for
   this failure nor that nothing else does. That a `tokenchars`-free tokenizer emits `WidgetV1` and `WidgetV2`
   as distinct terms is a property of tokenization, not a measurement of ranking — and D24's factorial ablation
   is the standing warning that lexical identifier handling can cost useful recall on net (−0.052 for the
   tokenizer alone).

**Supported replacement.** "If Zikaron ever holds memories that are near-identical apart from a version, the
0.20 is the relevant number: with topic held constant the dense margin is thin but consistently signed, not
absent. Whether the lexical arm's exact-token match compensates — in the full BM25 ranking, or after
fusion — was not measured here, and no arm of this instrument can settle it."

**Scope of the correction.** Evidence fidelity only. No figure, gate, interval or model decision changes; the
report's three §7 conclusions and the D20–D25 decisions they support are untouched. This does not reopen the
APPROVED verdict above.

---

## Erratum 2 — 2026-08-01, raised by the design-corpus review (round 8, finding 3)
> **Status: APPLIED IN PLACE, 2026-08-01**, at both sites in `research/embedder-benchmark-results.md`
> (§7 "Three conclusions" and Headline item 4) and at the one design site that repeated the reading
> (`design/consolidation.md` §"Why not cosine alone"). Same disposition as Erratum 1 and for the same
> reason: an external-only note leaves a reader of the report meeting the withdrawn claim. The withdrawn
> sentence is quoted verbatim inline so nothing is silently rewritten.

**Location.** §7, "Three conclusions", first bullet ("The weakness is real"), final sentence; and Headline
item 4, the clause after "it is the *margin* that is thin".

**The sentence, as written.** "Absolute cosines are ~0.73 with margins of 0.04, so any competing signal
overturns it." (Headline item 4: "it is the *margin* that is thin, so any competing signal overturns it.")

**Why it is unsupported, on the report's own evidence.** Two defects, both scope rather than arithmetic.

1. **"Any competing signal" quantifies over signals the instrument never varied.** The counterfactual holds
   topic constant and swaps one substring, so it measures the size of *this* margin and nothing about the
   direction or magnitude of any other feature of a query. A reinforcing signal does not overturn an ordering
   it agrees with, and a contrary signal smaller than the margin does not flip it either. What the measurement
   supports is a statement about size: the near-miss margin is **0.036–0.051** cosine against an exact-control
   margin of **0.183–0.235**, so a **contrary signal of comparable magnitude** decides instead. This is the
   third time this trail has caught a claim widened past its estimand, and the same discipline applies: name
   the quantity before quoting a number about it.
2. **"~0.73" is a single level, and not the deployed one.** Query→passage `mean_cos_gold` on the near-miss
   condition is 0.7385 / 0.7214 for bge-large-with-prefix and 0.7415 / 0.7871 for nomic, but **0.7867 / 0.7626
   for bge-small-with-prefix**, the model D20 keeps; across all four models, both probes and all three
   conditions the range is 0.719–0.848 (`experiments/embedder-precision/results/twin_counterfactual.json`).
   Quoting a non-deployed model's level as *the* level is the same error round 4 caught when it withdrew the
   "twin pairs sit at ≈0.73" claim from `design/consolidation.md`, and it survived here because the report was
   never re-read for it.

**Supported replacement.** "Absolute query→passage cosines on the near-miss condition run **0.72–0.80**,
depending on model and probe — the deployed bge-small-with-prefix at 0.76–0.79, bge-large-with-prefix at
0.72–0.74 — and the near-miss margins on top of them are **0.036–0.051**. So the ordering rests on a margin
roughly a fifth of the exact control's (0.18–0.24), and a **contrary signal of comparable magnitude** overturns
it."

**Scope of the correction.** Evidence fidelity only. No figure, gate, interval or model decision changes; the
three §7 conclusions and the D20–D25 decisions they support are untouched, and the design's use of this
evidence is unchanged in substance — D15's hand-back is still "candidates to compare" and D29 still refuses
cosine-only clustering, both for the reason that survives: the discriminating signal is measured weak. This
does not reopen the APPROVED verdict.
