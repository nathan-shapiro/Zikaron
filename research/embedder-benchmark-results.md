# Embedder precision on tribal-knowledge retrieval — measured results

Answers the question left open by `research/embedding-models-technical-prose.md`: **is
`bge-small-en-v1.5` the wrong embedder for identifier-dense tribal knowledge, and is "something
more capable" the fix?** That note established there is **no published study** measuring near-miss
identifier discrimination, so this had to be measured on our own data.

Code, data and re-run instructions: `experiments/embedder-precision/` (read its README first).
Preregistration: `experiments/embedder-precision/PREREGISTRATION.md` (round 2, frozen and unedited)
and `experiments/embedder-precision/PREREGISTRATION-R3.md` (round-3 addendum, written before any
round-3 result).
Independent review that drove rounds 2 and 3: `reviews/embedder-benchmark-independent.md`.
Raw results: `experiments/embedder-precision/results/*.json`.

**Round 3, 2026-08-01.** Review round 2 accepted 12 of the 18 round-1 findings as resolved and
returned NEEDS_CHANGES on four analysis/wording defects. All four are fixed here, and none of them
changed a recommendation:

| Round-2 BLOCKER | What was wrong | What round 3 did |
|---|---|---|
| 1 | causal "capacity does not fix it" language despite the report's own quantization caveat; and the quoted discrimination-index contrast used a **different estimand** from the one displayed | the discrimination index now reports **both** estimands by name (ratio-of-means, primary and preregistered; mean-block-ratio, secondary), each with its own cluster bootstrap; capacity language is narrowed to the deployed artifact |
| 2 | the dev−blind gap was called a "real, bounded self-authorship inflation" | renamed throughout to the **observed v1-development versus v2-blind query-set gap**, kept as a sensitivity analysis, with a stub-clustered interval on that set difference and no causal reading |
| 3 | `ties_in_top5` counted tied *adjacent pairs* but was reported as a *fraction of queries*; and tie prevalence was used causally with no sensitivity run | per-query boolean added and both quantities reported separately; **a four-rule tie-handling sensitivity run** now measures whether ties cause the effect (they do not — max movement 0.0052) and an alternative mechanism is quantified instead |
| 4 | `L_G_split` was described as isolating "custom tokenization confined to the tokens field" when it changes four things | relabelled a **composite split-index RRF architecture comparison**; the decision-bearing `L_E` vs `L_B` contrast is untouched |

Every **task-metric** number in this report is **bit-identical** to round 2: inference is
deterministic and the embedding cache is keyed by model name, so the `eval_v2` rerun changed only the
tie block and the two renamed keys — every configuration mean, contrast point estimate and confidence
interval reproduced exactly. Two sets of numbers *did* move, both disclosed: the discrimination-index
levels shifted in the fourth decimal (0.2046 → 0.2045, 0.2330 → 0.2331, 0.2085 → 0.2087) because
`aggregate` was computing the ratio from already-rounded margins and now shares one code path with
the bootstrap; and the tie statistics for `H_nomic` and `L_G_split` changed because the old count was
the wrong quantity. `report_figures.py --assert` checks all **95** quoted figures against the JSON.

**Round 2, 2026-08-01.** An independent review returned NEEDS_CHANGES on round 1 with 5 BLOCKERs,
11 MAJORs and 2 MINORs. This report has been rebuilt around that review. The short version of what
changed:

| | Round 1 | Round 2 |
|---|---|---|
| Primary query set | 64 prompts, same author as the memories | **192 prompts authored without ever reading the memory prose**; the 64 are relabelled a **development set** and the gap between them is now a measured number |
| Labels | one gold + "hard negatives" | **graded**: `primary` / `also_useful` / `harmful_if_applied`, plus a `current_action` vs `historical_intent` axis |
| Thresholds | a noise rule stated then violated | **preregistered before any round-2 result was computed**, with UTC timestamp and frozen input hashes |
| Uncertainty | none | paired **cluster bootstrap over stubs** (10 000 resamples), raw changed-query counts, phrasing spread across three registers |
| `tokens` column | one config changing four things at once | **7-way factorial** separating tokenizer / field / weight / duplicate emission, plus a **held-out** test of the frozen extractor and its true write cost |
| Identifier mechanism | bare token vs two topically different documents | **byte-identical passage templates differing only in the identifier**, twin set as the statistical block, with validated floor and ceiling controls |
| Capacity | bge-large only behind BM25+RRF | **dense-only controls** for bge-large and nomic, plus RRF tie frequency |

Two round-1 headline claims did not survive: "scale measurably helps identifier discrimination"
and "the `tokens` column earns its place". Two got **stronger** in a narrower form.

---

## Headline

1. **Keep `bge-small-en-v1.5`.** No alternative cleared the preregistered gate. But the reason is
   narrower than round 1 said: the deployed bge-large artifact **does** beat the deployed bge-small
   artifact when each is measured dense-only (useful-recall@5 0.932 vs 0.896, MRR@10 **+0.0705**, CI
   [+0.0283, +0.1156]) — and that gain does not survive the RRF hybrid (0.922 vs 0.938) while costing
   13× warm embed latency, 20× disk and 4.1× cold start. The honest statement is **"no demonstrated
   task gain in the deployed pipeline at high measured operational cost"** — not "bge-large is
   worse", and not "scale is disproved". Section 3 measures *why* fusion absorbs it, and it is not
   the tie-breaking round 2 blamed.
2. **The identifier weakness is mechanistically real, and now properly isolated.** With
   byte-identical passages differing only in the identifier, every model's near-miss margin is
   **~19–24 % of the separation it achieves on unmistakably distinct tokens** (discrimination index
   0.194–0.233 as a ratio of means; preregistered interpretation: ≤0.35 is a real weakness). The
   instrument's floor and ceiling both validated: masking the identifier gives margin **exactly
   0.000000**, and the distinct-token control wins **100 %** of trials.
3. **No demonstrated capacity remedy — and this instrument cannot test capacity cleanly.**
   Discrimination index (ratio of means, the preregistered estimand): bge-small **0.2045**,
   bge-large **0.2331**, nomic **0.2087**. Paired across the 14 twin sets, bge-large − bge-small is
   **+0.0286, CI [−0.0162, +0.0617]** on that estimand and **+0.0181, CI [−0.0160, +0.0482]** on the
   secondary mean-block-ratio estimand — a fifth of the preregistered 0.15 bar either way, with both
   CIs including 0. Round 1's "scale measurably helps (0.714 → 0.786 → 0.821)" does not reproduce
   under control. The honest statement is **"this deployed bge-large artifact did not materially
   improve the controlled identifier instrument"**. It is *not* "capacity does not help": fastembed
   serves a **quantized** bge-small against an **unquantized** bge-large, so this is a comparison of
   two deployed artifacts, exactly as threat 5 says of the task comparison.
4. **The weakness does not bind on this corpus.** Near-miss useful-recall@5 is **0.952–1.000** for
   every configuration on the blind set — and the only two configurations below 0.976 are the
   `tokenchars` lexical variants, whose losses come from the tokenizer, not the embedder. The reason is visible in the instrument: direction is
   almost always right (14/14 twin sets positive, 92–96 % of trials) — it is the *margin* that is
   thin, **0.036–0.051 cosine, about a fifth of the exact control's 0.18–0.24**, so a **contrary**
   signal of comparable magnitude overturns it. Where real twins differ in topic as well as
   identifier, topic is exactly such a signal, and the thin margin never has to decide. **This is not a general
   dismissal**: on a corpus of topically identical memories differing only by version — which the
   instrument simulates — the 0.20 discrimination index is the relevant prediction.
   *(Erratum 2, §7: this bullet said "any competing signal overturns it".)*
5. **The extracted-`tokens` column is not adopted.** Its retrieval effect is real once isolated
   (+0.0365 useful-recall@5, CI [+0.0104, +0.0677]; MRR +0.0656, CI [+0.0306, +0.1039] against the
   correct baseline) and its cost is genuinely small (+5.0 % database, amend p95 +0.39 ms). But
   round 1 attributed the gain to the wrong factor, and the **frozen extractor fails its held-out
   test decisively**: recall 0.42 against a preregistered ≥0.70, precision 0.36–0.54 against ≥0.80,
   and it fires spurious tokens on **6 of 7** ordinary numeric prose sentences. Fix the extractor
   first; the schema change is cheap and the idea is sound, but the current regex set does not
   generalise beyond the shapes it was written for.
6. **Round 1 attributed the `tokens` gain to the wrong thing.** The custom `tokenchars` tokenizer,
   applied to gist and content, **costs** −0.0521 useful-recall@5 on its own (CI [−0.0885,
   −0.0156], 12 queries lost, 2 gained). The tokens field recovers +0.0365 of that. Net against the
   true `unicode61` baseline: **−0.0156 useful-recall@5** (CI includes 0) with MRR +0.0325 (CI
   [+0.0009, +0.0636]). The duplicate whole-token emission — an undocumented term-frequency boost —
   changes **nothing at all** (0 queries at every weight).
7. **A superseded memory is nearly always *shown*, and outranks its correction about a third of the
   time.** On the 6 current-action polarity stubs (18 prompts, n=6 blocks), a
   `harmful_if_applied` superseded record is in the injected top 5 in **83–100 %** of prompts and
   outranks every primary in **28–50 %**. Round 1 quoted the mixed rate as "roughly half the time";
   the 4 historical-intent stubs it pooled in have **no harmful label at all**, because there the
   old record is the legitimately relevant one. **Supersession must be structural**, and structural
   suppression must not be blanket — the historical prompts are exactly what it would break.
8. **The aggregate is not robust to swapping the query set.** The v1-development set scores
   **+0.0106** useful-recall@5 higher than the v2-blind set on average across 18 configurations × 2
   depths (range −0.0208 to +0.0573). The gap is largest for dense-only bge-small (+0.0573,
   stub-clustered CI [+0.0104, +0.1146]) and zero for the incumbent hybrid. This is an **observed
   query-set difference, not a measured authorship effect**: the two sets differ in author *and* in
   register, length, detail and deliberate underspecification, and those are inseparable here. What
   it licenses is narrow and still useful — round 1 drew conclusions from 0.014–0.047 differences,
   which is inside the range that swapping the query set moves things, so those conclusions were not
   safe. It licenses no rate and no decision.

### Facts that stand on their own

Direct measurements of these exact artifacts on this host, exempt from the effect-size gates:

- Warm embed p50 **5.45 ms** (bge-small, no prefix) / **6.64 ms** (with prefix); warm end-to-end
  hybrid p50 **7.97 → 9.14 ms**. The BGE prefix is **not free** — it is a low-cost, documented,
  reversible convention costing ~1.2 ms.
- Cold whole process **783 ms** for bge-small, 3198 ms for bge-large, 1716 ms for nomic.
- `bge-reranker-base` on CPU: **6592 ms** p50 for 50 gist+content pairs. Now with the scaling curve:
  the *only* operating point inside a 200 ms push budget is **gist-only at 5 candidates** (184 ms) —
  and reranking 5 candidates when 5 is the injection budget cannot change what the agent sees.
- `tokens` column: whole database **+5.0 %**, FTS shadow tables **+5.4 %** (index-only, per 187 rows:
  +8.3 %); paired median write cost insert p50 **+0.061 ms**, amend p50 **+0.215 ms**, amend p95
  **+0.394 ms** over 935 transactions × 3 paired trials, extraction itself 0.101 ms p50.
- **RRF ties are pervasive, and are not what erased bge-large's dense advantage.** Every hybrid
  query has at least one exact fused-score tie; ~17.5 tied adjacent pairs per query, and
  **12.5 % of queries** (15.6 % `H_large`, 11.5 % `H_nomic`, 7.8 % `H_tok_w3`) have a tie *inside
  the top 5*, where order falls to Python's stable sort — i.e. to the BM25 arm being passed first.
  That is an undeclared thumb on the scale and should be replaced by an explicit tie-breaker. But
  it is **not** the mechanism behind section 3: re-running the hybrid under three alternative tie
  rules (dense arm first, explicit tie-break on the dense rank, explicit tie-break on the BM25
  rank) moves the bge-large − bge-small contrast by at most **0.0052** — one query — and none of
  them comes near the +0.05 adoption threshold. What does explain it: **960 of 960** fused top-5
  slots are held by documents that *both* arms returned, so unweighted RRF over two arms is decided
  by arm agreement, and a dense-only gain on a document BM25 ranks 30th or not at all cannot reach
  the top 5.

---

## What is settled, what is narrowed, what is open

| Claim | Status | Evidence and scope |
|---|---|---|
| Keep bge-small; do not deploy this bge-large artifact now | **settled, narrowed** | Fails the preregistered quality gate in the deployed hybrid (−0.0156, CI includes 0) at 13× embed latency. Dense-only it is *better*; the hybrid erases it. |
| Add the BGE query prefix as a convention | **settled, narrowed** | Dense-only +0.0260 useful-recall@5, CI [+0.0052, +0.0521], 5 queries up / 0 down. In the hybrid +0.0104, CI includes 0. Costs ~1.2 ms. Low-risk, reversible, model-documented — not "free proven quality". |
| Embed gist + content, not gist alone | **settled, now on the blind set** | Gist-only costs −0.026 to −0.130 useful-recall@5 across the eight dense-bearing configurations; paraphrase −0.13 to −0.27. Directionally unambiguous. |
| Reject `bge-reranker-base` on the push path | **settled, narrow** | 6592 ms at 50 gist+content pairs; the full scaling curve shows no useful operating point under 200 ms. Says nothing about smaller rerankers, GPUs, chunked passages, or the pull path (1908 ms for 50 gist-only pairs may be fine there). |
| Do not load a model in the `userPromptSubmit` hook | **settled** | 783 ms cold whole process, of which 149 ms is bare interpreter + `sqlite_vec`. |
| Supersession must be structural, not ranked | **settled, resemanticised** | Harmful exposure 83–100 % on current-action polarity stubs (n=6). Blanket suppression rejected: 4 historical-intent stubs need the old record. |
| The identifier weakness is mechanistically real | **settled** | Discrimination index 0.194–0.233 (ratio of means), validated floor (0.000000) and ceiling (100 % win), 14/14 blocks positive, sign test p ≈ 1.2×10⁻⁴. |
| A more capable embedder fixes the identifier weakness | **no demonstrated remedy; capacity itself untested** | All four artifacts 0.19–0.24; no paired block comparison excludes 0 on either estimand; all ~5× below the preregistered 0.15 bar. **Not** a refutation of capacity — quantized small vs unquantized large is an artifact comparison (threat 5). |
| Insertion-order RRF ties explain why the hybrid absorbs bge-large's dense gain | **refuted** | Three alternative tie rules move the contrast by ≤0.0052 (one query). Ties remain a real design defect worth fixing on their own terms. |
| Unweighted two-arm RRF is decided by arm agreement | **supported, exploratory** | 960/960 fused top-5 slots are documents both arms returned; of 9 dense-only gains, 4 were already answered by the small hybrid, 1 survived, 4 were destroyed. Exploratory under prereg §7. |
| The extracted-`tokens` column earns its place | **rejected for now** | Isolated retrieval effect passes, cost passes, **extractor held-out quality fails hard**. Re-test after a rewrite. |
| Duplicate whole-token emission helps | **refuted** | Zero effect on every metric at every weight. Remove it; it was undocumented. |
| 512-token truncation is safely accepted | **open, explicitly not settled** | The 6 over-length records are one template realised six times. No real long-memory length distribution exists yet. |
| nomic-embed-text-v1.5 is worth adopting | **open** | Best deployed useful-recall@5 (0.9479) and best on historical-intent (0.917 vs 0.750, n=4 stubs), but +0.0104 vs incumbent with CI including 0. Its 8192-token context is the real argument and is untested against real long memories. |

---

## Methods (round 2)

### Query sets

| Set | n | Authorship | Status |
|---|---|---|---|
| `queries_blind.json` | **192** prompts / 64 stubs | authored from prose-free stubs by an agent that never opened `dataset.json`, `dataset_src/`, `results/` or this report | **PRIMARY.** Every decision. |
| `dataset.json` queries | 64 | same author as the memories | **development only.** Reported for the query-set gap in section 2. |

The dev set differs from the blind set in **more than one variable** — author, register, length,
detail level and deliberate underspecification all change together — so the dev−blind difference is
reported as a **query-set gap** and never as an isolated authorship effect
(`PREREGISTRATION-R3.md` R3.3).

The bridge is `stubs_v2.json`: one stub per v1 query carrying only what a real user would already
have in hand — trap category, intent, *user-side* identifiers, and a ≤15-word `situation` held
mechanically to zero 3-word overlaps with any memory gist or content. Answer-side identifiers the
user could not know (`PLATFORM_OVERRIDE_ALLOW`, `/var/run/secrets/...`) are excluded so a prompt
cannot quote the punchline.

Three prompts per stub, deliberately **not** paraphrases of one sentence: `terse` (8.6 words mean),
`verbose` (45.2), `mid` (13.0, entered from a different angle). 39 of 192 are marked
`underspecified` — a cue a careful author would have supplied is withheld. The builder mechanically
rejects twin-identifier bleed across 22 exclusion pairs, so no `v2.3.10` appears in a `v2.3.1`
prompt.

**What the blind set does and does not fix.** It removes *query-side* vocabulary leakage, which was
review finding 1's core objection. It does **not** make the corpus real, does not change the
category mixture, and does not change the fact that the graded labels were assigned by the memory
author. Two properties rest on authoring discipline rather than machinery, and are declared as such
in the README: that no prompt names a resolution, and that the four historical-intent stubs really
do ask about the past in all three variants.

### Labels and metrics

Graded per review finding 11: **67 `primary`** (3 stubs have co-primaries), **120 `also_useful`**,
**48 `harmful_if_applied`** across 24 stubs. 16 of the round-1 "hard negative" labels did not
survive the bar of *would applying this actually misdirect the agent*. Intent per finding 12: **60
`current_action` / 4 `historical_intent`**.

- **`useful_hit@5`** — any `primary` in the top 5. The headline; top-5 because D12 injects five.
- **`harmful_exposure@5`** — any `harmful_if_applied` in the top 5. Reported **separately**; never
  netted against useful recall.
- **`harmful_disp@5`** — a harmful record in the top 5 *and* above every primary. The **primary**
  displacement measure.
- **`mrr@10`** over primaries; **`relevant_recall@5`** over `primary ∪ also_useful`.
- `precision@5` dropped: with ~1.05 primaries per stub its ceiling is ~0.21 and it carries no
  information beyond `useful_hit@5`.

`hnd` from round 1 is retired. It was computed over a 50-candidate arm union and described as the
full ranking (finding 13). Round 2 runs every configuration at **depth 50** (operational) and
**depth 187** (whole corpus) and reports both. One honest limit: at depth 187 the dense and hybrid
arms really do rank all 187 documents, but a pure-BM25 arm can only rank documents that share a term
with the query — mean 158–160 of 187. So `harmful_disp_full` for lexical-only configurations is
displacement within the *matching* set, and is labelled that way.

### Uncertainty

The **stub is the resampling unit**, not the query: three variants of one stub are one information
need. Paired cluster bootstrap over the 64 stubs, 10 000 resamples, same resample applied to both
arms, 95 % percentile intervals on the difference. Every difference is quoted with **raw
changed-query counts**. The near-miss instrument blocks on the **twin set, n = 14**, and says so.

Phrasing uncertainty is estimated from the three registers rather than from reruns: model inference
is deterministic, so a rerun estimates nothing. Register spread on `useful_hit@5` is **0.016–0.063**
(1–4 queries of 64 per register) — smaller than expected, and worth stating because it is the one
uncertainty axis this design can actually sample. `underspecified` prompts cost little on the
incumbent hybrid: 0.9231 (n=39) vs 0.9412 (n=153).

**Multiplicity, acknowledged not corrected:** 15 declared contrasts × 4 metrics at 95 %. Roughly
three intervals should exclude 0 by chance. Where an interval barely excludes 0 — `mrr10` on
`tokens_w3_vs_baseline`, CI [+0.0009, +0.0636] — that is said rather than treated as a discovery.

**Two estimands for the discrimination index, both named.** `PREREGISTRATION.md` §5.5 defines the
index as "mean near-miss margin ÷ mean exact-control margin" — a **ratio of means (RoM)**. Round 2
displayed the RoM per model but bootstrapped the **mean of per-block ratios (MBR)** for the
between-model contrast without saying it had switched; Jensen's inequality guarantees the two
differ. Round 3 reports both, labelled, each with its own cluster bootstrap over the 14 twin sets;
the RoM bootstrap recomputes *both* models' ratio inside every resample, so uncertainty in the
denominator propagates. The preregistered 0.15 gate is applied to the RoM. Both estimands agree on
the decision here, and that agreement is stated rather than assumed.

**Exploratory versus declared.** `PREREGISTRATION.md` §7 requires anything outside the declared
contrast list to be labelled exploratory and to support no decision. Two analyses in this report are
exploratory and are marked as such where they appear: the tie-handling sensitivity run and the
arm-agreement decomposition in section 3.

---

## Results

### 1. Primary blind-set table (depth 50, the operational pipeline)

| Configuration | useful_hit@5 | MRR@10 | harmful_exposure@5 | harmful_disp@5 | relevant_recall@5 |
|---|---|---|---|---|---|
| `L_A_unicode61` — BM25, `unicode61` | 0.8802 | 0.7555 | 0.4722 | 0.1389 | 0.5271 |
| `L_B_tokchar` — BM25, `tokenchars`, no tokens field | 0.8281 | 0.7224 | 0.3333 | 0.0833 | 0.4609 |
| `L_C_tok_w0` — tokens field, weight 0 | 0.8333 | 0.7166 | 0.3194 | 0.0972 | 0.4543 |
| `L_D_tok_w1` — tokens field, weight 1 | 0.8646 | 0.7823 | 0.3194 | 0.0694 | 0.4760 |
| `L_E_tok_w3` — tokens field, weight 3 (round-1 arm) | 0.8646 | 0.7880 | 0.3194 | 0.0694 | 0.4786 |
| `L_F_tok_w3_nodup` — no duplicate emission | 0.8646 | 0.7871 | 0.3194 | **0.0556** | 0.4786 |
| `L_G_split` — **composite**: BM25 + tokens-only arm, fused | 0.8594 | 0.7628 | 0.4444 | 0.0972 | 0.4990 |
| `D_small_noprefix` — dense only | 0.8698 | 0.7659 | 0.5972 | 0.1528 | 0.5609 |
| `D_small_prefix` — dense only | 0.8958 | 0.7806 | 0.5833 | 0.1528 | 0.5778 |
| `D_large_prefix` — dense only | 0.9323 | **0.8511** | **0.7083** | 0.0972 | 0.5994 |
| `D_nomic` — dense only | 0.9271 | 0.8274 | 0.5833 | 0.1389 | 0.5968 |
| `H_small_noprefix` — RRF, round-1 config 4 | 0.9271 | 0.8158 | 0.5972 | 0.1528 | 0.5754 |
| **`H_small_prefix`** — RRF, **the incumbent baseline** | 0.9375 | 0.8147 | 0.6111 | 0.1528 | 0.5794 |
| `H_tokchar_notok` — tokenizer change only, hybrid | 0.9167 | 0.8172 | 0.5000 | 0.1250 | 0.5310 |
| `H_tok_w3` — round-1 config 5 | 0.9271 | 0.8468 | 0.5000 | 0.0972 | 0.5412 |
| `H_tok_w3_nodup` | 0.9271 | 0.8447 | 0.5000 | 0.0833 | 0.5386 |
| `H_large` — round-1 config 6 | 0.9219 | 0.8412 | 0.6806 | 0.1528 | 0.5865 |
| `H_nomic` — round-1 config 7 | **0.9479** | 0.8378 | 0.6667 | 0.1389 | 0.5895 |

`harmful_exposure@5` and `harmful_disp@5` are over the 72 prompts (24 stubs) that carry a harmful
label. Note the pattern the round-1 metrics could not see: **the dense arms are the ones that
surface harmful records**, 0.58–0.71 against 0.32–0.47 for lexical, and bge-large is the worst
offender precisely where it is the best retriever. Capacity pulls in more of the topically adjacent
cluster, correct and incorrect alike.

By trap category, `useful_hit@5` (blind, depth 50):

| Configuration | near_miss (28) | paraphrase (10) | error_string (10) | polarity (10) | over_length (6) |
|---|---|---|---|---|---|
| `L_A_unicode61` | 0.9881 | 0.6667 | 0.9667 | 0.7333 | 0.8333 |
| `D_small_prefix` | 0.9881 | 0.6667 | 0.9667 | 0.8667 | 0.7778 |
| `D_large_prefix` | 1.0000 | 0.8333 | 1.0000 | 0.9000 | 0.7222 |
| `D_nomic` | 0.9762 | 0.8000 | 1.0000 | 0.9667 | 0.7222 |
| `H_small_prefix` | 0.9881 | 0.8000 | 1.0000 | 0.8333 | 1.0000 |
| `H_tok_w3` | 1.0000 | 0.8000 | 0.9667 | 0.7667 | 1.0000 |
| `H_large` | 0.9881 | 0.8333 | 1.0000 | 0.8000 | 0.8333 |
| `H_nomic` | 0.9881 | 0.8333 | 1.0000 | 0.9333 | 0.8889 |

Review finding 2 stands and is not repaired by the blind set: **near-miss and error-string remain
near-saturated** — across all 18 configurations near_miss spans 0.9524–1.0000 and error_string
0.9000–1.0000, with both minima belonging to lexical `tokenchars` variants rather than to any
embedder. So the aggregate is still a weighted average whose weights come from dataset
construction, not from observed usage. The unsaturated cells are **paraphrase (0.5667–0.8333, 10
stubs)** and **polarity (0.6667–0.9667, 10 stubs)**, and those are where the model differences
live; over_length spans 0.6111–1.0000 but is 6 stubs from one template. No overall "winner" is
declared from the ALL column.

### 2. The v1-development versus v2-blind query-set gap

Same graded labels, same configurations, dev queries vs blind queries (depth 50). This is a
**sensitivity analysis on the query set**, not a measurement of authorship — see the caveat below
the table.

| Configuration | useful_hit@5 dev | blind | gap | MRR dev | blind | gap |
|---|---|---|---|---|---|---|
| `L_A_unicode61` | 0.8594 | 0.8802 | **−0.0208** | 0.7852 | 0.7555 | +0.0297 |
| `D_small_prefix` | 0.9531 | 0.8958 | **+0.0573** | 0.8311 | 0.7806 | +0.0505 |
| `D_large_prefix` | 0.9531 | 0.9323 | +0.0208 | 0.8859 | 0.8511 | +0.0348 |
| `D_nomic` | 0.9688 | 0.9271 | +0.0417 | 0.8320 | 0.8274 | +0.0046 |
| `H_small_prefix` | 0.9375 | 0.9375 | 0.0000 | 0.8372 | 0.8147 | +0.0225 |
| `H_tok_w3` | 0.9375 | 0.9271 | +0.0104 | 0.8822 | 0.8468 | +0.0354 |
| `H_large` | 0.9219 | 0.9219 | 0.0000 | 0.8232 | 0.8412 | −0.0180 |
| `H_nomic` | 0.9688 | 0.9479 | +0.0209 | 0.8344 | 0.8378 | −0.0034 |

Mean across all 18 configurations × 2 depths: **+0.0106**, range −0.0208 to +0.0573. Stub-clustered
intervals on the set difference (each stub's dev prompt against the mean of its three blind
variants, 64 stubs): `D_small_prefix` **+0.0573, CI [+0.0104, +0.1146]** (8 stubs dev-higher, 54
tied, 2 blind-higher); `H_small_prefix` **0.0000, CI [−0.0625, +0.0573]**; `L_A_unicode61`
**−0.0208, CI [−0.1094, +0.0625]**.

**What this is not.** It is not an isolated self-authorship effect, and calling it one — as round 2
did — was wrong. The v1 set and the v2 set differ in author *and* in register (8.6 / 13.0 / 45.2
mean words versus v1's single register), in detail level, and in 39 rows that deliberately withhold
a cue. Author identity is not separable from that distribution change by any analysis of these two
sets, and averaging 36 highly correlated configuration×depth cells is descriptive, not an
uncertainty estimate for a general rate.

**What it is.** Evidence that the aggregate is **not robust to swapping the query distribution**,
with the movement concentrated where the mechanism would predict it (dense-only bge-small moves
most; the hybrid, which has a lexical arm to fall back on, does not move at all). That is enough to
say round 1's 0.014–0.047 conclusions were inside the range that a query-set swap moves, and
therefore were not safe. It is not enough to quantify how much of that came from authorship. What
would separate them: a second blind author writing prompts in the *same* registers as v1, or a v1
author rewriting the v1 prompts in the three v2 registers.

Two limitations remain regardless: the blind set removes only *query-side* leakage, and the graded
labels still come from the memory author.

### 3. Dense-only versus hybrid: comparing the deployed artifacts (review finding 8)

Round 1 tested bge-large and nomic **only behind BM25+RRF**, so it compared pipelines and called it
an embedder comparison. With dense-only controls added:

| Contrast | useful_hit@5 | 95 % CI | changed ↑/↓ | MRR@10 | 95 % CI |
|---|---|---|---|---|---|
| bge-large − bge-small, **dense only** | +0.0365 | [+0.0000, +0.0781] | 9 / 2 | **+0.0705** | [+0.0283, +0.1156] |
| nomic − bge-small, **dense only** | +0.0312 | [−0.0052, +0.0729] | 9 / 3 | **+0.0468** | [+0.0150, +0.0840] |
| bge-large − bge-small, **hybrid** | −0.0156 | [−0.0521, +0.0156] | 2 / 5 | +0.0265 | [+0.0009, +0.0527] |
| nomic − bge-small, **hybrid** | +0.0104 | [−0.0156, +0.0417] | 4 / 2 | +0.0231 | [+0.0014, +0.0459] |
| bge-large − bge-small, harmful_exposure@5, dense only | **+0.1250** | [+0.0139, +0.2361] | 12 / 3 | — | — |

This is the single most important correction round 2 makes to round 1's *reasoning*. As a deployed
embedding artifact, **bge-large retrieves better than bge-small on this data when used alone** —
clearly on ranking quality (MRR +0.0705, CI excludes 0, 37 queries improved against 16 worsened),
directionally on recall. Round 1 could not see this because it only ever tested large behind the
fusion, which absorbs the difference; the mechanism for that absorption is measured below rather
than asserted.

Neither model clears the preregistered gate, and the gate is what governs the decision: the deployed
comparison needs ≥ +0.05 useful_hit@5 with a CI excluding 0, escalating to ≥ +0.12 at bge-large's
13× latency. bge-large is at −0.0156. So the recommendation is unchanged and the reason is now
correct: **the hybrid does not let this artifact's advantage through, and the cost is real.** If RRF
weighting or `k` were tuned — which this experiment deliberately does not do — the calculus could
change, and that is now a concrete, testable follow-up rather than a hunch. Note also what this
contrast is and is not: quantized small against unquantized large is a comparison of the artifacts
Zikaron would deploy, **not** a capacity control (threat 5).

**Why the hybrid absorbs it. Not ties — arm agreement.** Round 2 blamed insertion-order tie
resolution and offered tie prevalence as the evidence. Prevalence is not causation, and the
sensitivity run says it is not the cause. Re-running the hybrid under four tie-handling rules,
changing nothing else (**exploratory**, `PREREGISTRATION-R3.md` R3.5, decision rule fixed before the
numbers existed):

| Tie rule | bge-large − bge-small, useful_hit@5 | 95 % CI | ↑/↓ |
|---|---|---|---|
| `bm25_first` — canonical, BM25 passed first | −0.0156 | [−0.0521, +0.0156] | 2 / 5 |
| `dense_first` — dense passed first | −0.0104 | [−0.0417, +0.0208] | 2 / 4 |
| `tiebreak_dense` — explicit break on the dense arm's rank | −0.0104 | [−0.0417, +0.0208] | 2 / 4 |
| `tiebreak_bm25` — explicit break on the BM25 arm's rank | −0.0156 | [−0.0521, +0.0156] | 2 / 5 |

Maximum movement from the canonical rule: **0.0052 — one query**. The declared bar was "reaches
+0.05 with a CI excluding 0 under at least one alternative rule"; nothing comes close. So
**insertion-order ties are a real design defect with a measured, near-null effect on this
comparison**, and the round-2 sentence blaming them is withdrawn. The defect is still worth fixing —
12.5 % of queries have an injected slot ordered by which arm was passed first, and no fusion tuning
should be trusted until that is explicit — but it explains nothing here.

**The tie statistic itself was miscounted, and two of the four numbers changed.** Round 2's
`ties_in_top5` incremented by the number of tied *adjacent pairs* inside the top five and the report
divided that by the query count and called it a *fraction of queries*. Round 3 tracks a per-query
boolean as well, and reports both:

| Configuration | queries with **any** top-5 tie (boolean) | mean tied adjacent **pairs** in top 5 | round-2 report said |
|---|---|---|---|
| `H_small_prefix` | **0.1250** | 0.1250 | 12.5 % — right by luck |
| `H_large` | **0.1562** | 0.1562 | 15.6 % — right by luck |
| `H_nomic` | **0.1146** | 0.1198 | 11.98 % — **wrong** |
| `H_tok_w3` | **0.0781** | 0.0781 | 7.8 % — right by luck |
| `L_G_split` | **0.1719** | 0.1979 | not quoted — would have been **wrong** |

The two coincidences are because no query in those configurations happened to have two adjacent ties
inside its top five. The defect was definitional, the correction is small, and it is recorded rather
than glossed because a metric that is right by luck is still wrong.

**What does explain it** (also exploratory): with two unweighted arms, a document both arms return
collects two reciprocal-rank contributions and a document only one arm returns collects one. Fusion
is therefore decided by agreement, and the measurement is stark — **960 of 960 fused top-5 slots
across the 192 blind prompts are held by documents present in *both* arms' candidate lists.** That is
not trivially true: the two arms' returned sets intersect in only **21.7 documents of a mean union of
77.3 (28 %)**, so **72 % of the candidate pool is structurally unable to reach the injection budget**,
however much one arm likes it. Tracing the 9 prompts where bge-large's dense
arm puts a primary in the top 5 and bge-small's does not:

- **4** were already answered by the small *hybrid* — BM25 had the primary in its own top 5, so
  there was no gain available to capture;
- **1** became a genuine differential gain in the hybrid;
- **4** were destroyed: the primary sat at dense rank 1–5 but BM25 rank 14, 30, 50 or absent, and
  fusion pulled it back out of the top 5 (`q-c2-03-v1`, `q-c2-06-v2`, `q-c2-06-v3`, `q-c1-03-v2`).

That is a property of **unweighted RRF at `k=60` over these two arms**, not of bge-large. It makes
"weight the arms, or tune `k`" a concrete follow-up with a specific predicted mechanism, and it is
labelled exploratory because it was not on the declared contrast list.

### 4. The `tokens` column, factorially separated (review BLOCKER 5)

Round-1 config 5 changed four things at once. Separated, on the blind set at depth 50, lexical-only
so no fusion can confound it:

| Contrast — what it isolates (unless marked composite) | useful_hit@5 | 95 % CI | ↑/↓ | MRR@10 | 95 % CI |
|---|---|---|---|---|---|
| **tokenizer alone** (`tokenchars` on gist+content, no tokens field) | **−0.0521** | [−0.0885, −0.0156] | 2 / 12 | −0.0331 | [−0.0694, +0.0011] |
| tokens field present at weight **0** | +0.0052 | [+0.0000, +0.0156] | 1 / 0 | −0.0058 | [−0.0150, +0.0013] |
| tokens field at weight **1** | +0.0365 | [+0.0156, +0.0625] | 7 / 0 | **+0.0600** | [+0.0284, +0.0946] |
| tokens field at weight **3** — the isolated effect | **+0.0365** | [+0.0104, +0.0677] | 8 / 1 | **+0.0656** | [+0.0306, +0.1039] |
| **duplicate whole-token emission** | +0.0000 | [+0.0000, +0.0000] | 0 / 0 | +0.0009 | [−0.0070, +0.0085] |
| **COMPOSITE, isolates nothing** — `L_G_split` split-index RRF vs one BM25 ranking | −0.0208 | [−0.0521, +0.0052] | 2 / 6 | +0.0073 | [−0.0411, +0.0537] |
| **round-1's comparison** (w=3 vs `unicode61` baseline) | −0.0156 | [−0.0469, +0.0156] | 4 / 7 | +0.0325 | [+0.0009, +0.0636] |
| isolated effect **inside the hybrid** | +0.0104 | [+0.0000, +0.0260] | 2 / 0 | +0.0296 | [+0.0096, +0.0521] |
| round-1 config 5 vs 4p (confounded) | −0.0104 | [−0.0417, +0.0156] | 3 / 5 | +0.0321 | [+0.0051, +0.0595] |

Four findings, in order of importance:

1. **The custom tokenizer is a net cost, not a neutral enabler.** Applying `tokenchars '_-./'` to
   gist and content makes `conftest.py` a single token, so a query mentioning `conftest` stops
   matching it. That loses 12 queries and gains 2. Round 1 never measured this factor and folded it
   into the credit for the tokens column.
2. **The tokens field does work, at weight 1 or 3, and the weight barely matters.** Weight 1 and
   weight 3 are identical on `useful_hit@5` (+0.0365 both) and near-identical on MRR (+0.0600 vs
   +0.0656). Round 1's a-priori 3.0 was not load-bearing. Weight 0 is inert (+0.0052, one query —
   the field can still cause a *match*, but with zero scoring weight it cannot reorder).
3. **Duplicate emission does nothing.** Zero changed queries on `useful_hit@5` at every weight,
   +0.0009 MRR. It was an undocumented term-frequency boost and should be removed — not because it
   hurt, but because unmeasured mechanisms are how round 1's attribution error happened.
4. **The package is a trade, not a win.** Against the true baseline: useful recall −0.0156 (CI
   includes 0), MRR +0.0325 (CI barely excludes 0, and one of ~3 expected chance exclusions),
   harmful exposure **−0.1528** (CI [−0.3056, −0.0278]), harmful displacement −0.0694 (CI touches
   0). The harm reduction is real and large — but it comes from the **tokenizer** (−0.1389 on its
   own, CI excludes 0), not from the tokens field (−0.0139). So if reducing harmful exposure is the
   goal, the tokenizer is the lever, and it costs useful recall to pull.

In the hybrid the isolated tokens effect is +0.0104 useful_hit@5 (CI touches 0) and **+0.0296 MRR**
— which **misses the preregistered ≥0.03 MRR bar by 0.0004**. That is a meaningless difference and
the gate is still the gate: reported as not passed, not spun as a pass, and not offered as evidence
of absence either.

**`L_G_split` isolates nothing and is not evidence about tokenization.** Review round 2, BLOCKER 4 is
right. `L_G_split` is `RRF(BM25 unicode61 gist+content, BM25 tokenchars tokens-only)` compared
against a *single* BM25 ranking, so the contrast simultaneously adds the tokens index, adds a second
retrieval arm, introduces RRF rank normalisation, and inherits insertion-order tie behaviour (which
it has in 17.2 % of queries inside the top 5). It is a **composite split-index architecture
comparison** and is reported as one. Nothing depends on it: the decision-bearing contrast is
`L_E_tok_w3` vs `L_B_tokchar`, which holds tokenizer and original fields fixed, and the non-adoption
decision rests on the failed held-out extractor gate in section 5.

An honest note on what the factorial therefore does *not* answer: "custom tokenization applied only
to an extracted field, with everything else held fixed" remains **untested**. FTS5 cannot give one
table two tokenizers, so testing it cleanly needs a different substrate (for example a single
`unicode61` table plus a manually pre-tokenized identifier column), and that was not built. If the
extractor is rewritten and the column reconsidered, that arm is the one to add.

### 5. The frozen extractor, held out (review BLOCKER 6)

`identifiers.py` frozen at sha256 `836dbd85…` (verified by `verify_freeze.py`), then run on 60
strings across the classes the reviewer named. Labels authored before running and not revised.

| Metric | Measured | Preregistered gate | |
|---|---|---|---|
| Token recall | **0.4186** | ≥ 0.70 | **FAIL** |
| Precision (lenient: required + accepted) | **0.5362** | ≥ 0.80 | **FAIL** |
| Precision (strict: required only) | 0.3600 | — | |
| Ordinary numeric prose emitting a false token | **6 / 7 (86 %)** | ≤ 25 % of prose sentences | **FAIL** |
| Ordinary prose, no numbers | 0 / 7 | — | pass |
| Held-out near-miss pairs collapsing to one form | 2 / 12 | 0 | **FAIL** |

Per class:

| Class | n | recall | false positives / case | example false positives |
|---|---|---|---|---|
| url | 7 | 0.833 | 1.29 | `github.com/qdrant/fastembed/issues/412`, `pypi.org/project/sqlite-vec/0.1.9` |
| winpath | 6 | 0.600 | 0.33 | `bundle.crt` (from `ca-bundle.crt`) |
| npm (scoped) | 6 | **0.125** | 0.33 | — |
| git hashes | 6 | **0.125** | 0.33 | `2.7` from `release/2.7`, `v0.4.0` from `v0.4.0-rc2` |
| mixed-language | 6 | 0.800 | 0.00 | — |
| numeric prose | 7 | — | **1.43** | `200`, `30`, `15`, `12` |
| shell | 7 | 0.364 | 1.00 | `omit`, `rm`, `20` |
| plain prose | 7 | — | 0.00 | — |

The failure has a clear shape: **the regex set covers the shapes it was written for and misses whole
classes of real identifier.** Scoped npm packages (`@types/node` → `node`) and git hashes
(`4f9a2c1`, a 40-hex SHA) are simply not in it. URLs are shredded into path fragments that will
never be typed by a user. Bare numbers in ordinary prose are captured as identifiers on 6 of 7
sentences, which pollutes a column whose entire purpose is precision.

The two held-out collisions are `0042_add_index`/`0042_add_indexes` and `client-s3`/`client-sts`,
and both collide by producing **empty** extractions — an absence, not the *wrong merge* that round
1's `conftestpy` bug produced. That distinction matters: an empty extraction degrades the column to
a no-op for that memory, while a wrong merge actively manufactures a collision. Still a failure of
the distinctness property the column exists to provide.

**Post-hoc sensitivity, clearly labelled as not a gate.** Some labels expect the leading dashes of a
flag (`--rm`) or an npm scope (`@types/node`). The extractor strips leading `-./`, and so does
`retrieval._fts_query` on the query side, so the pair is internally consistent and a `--rm` query
would still match an `rm` index token. Recomputed with both sides normalised: recall 0.4884,
precision 0.5797 / 0.4200. Still far below the gates. It changes nothing and is reported so the
strict numbers are not read as harsher than the mechanism warrants.

**One honest limitation.** I had read `identifiers.py` before authoring this material, so this is
not a blind test — only a held-out one. What protects it: the reviewer chose the classes, the
implementation was frozen by hash first, and it was not edited afterwards.

### 6. What the `tokens` column actually costs (review finding 7)

Round 1 quoted query wall time and called the cost negligible. This is a write-side feature, so the
write side is what matters. Two databases built from scratch, one commit per memory (a Zikaron write
is a transaction, not a bulk load), 5 writes per memory = 935 transactions, sizes after `VACUUM`.

**These timings are `fsync`-dominated and move ~30 % between runs.** A first single-shot run gave a
baseline insert p50 of 2.055 ms and a later one 1.596 ms, and it produced the nonsensical artifact of
insert p95 *improving* by 0.5 ms when extra work was added. The measurement is therefore **3 paired
trials**, both databases built back-to-back within each trial, quoting only the paired delta. The
artifact disappeared: with pairing every delta is positive or within noise of zero, which is the
physically sensible direction.

| | median delta | range across 3 trials |
|---|---|---|
| regex extraction alone (absolute) | p50 **0.101 ms**, p95 0.24–0.29 ms | p50 0.101–0.102 ms |
| insert p50 | **+0.061 ms (+3.8 %)** | +0.015 … +0.140 ms (+0.9 … +8.9 %) |
| insert p95 | +0.022 ms | −0.006 … +0.291 ms |
| amend p50 | **+0.215 ms (+13.6 %)** | +0.169 … +0.308 ms (+10.5 … +19.4 %) |
| amend p95 | **+0.394 ms** | +0.390 … +0.677 ms |
| whole database, after `VACUUM` | **+86 016 B (+5.0 %)** | exactly reproducible |
| FTS5 shadow tables (contentful, 935 rows) | **+61 440 B (+5.4 %)** | exactly reproducible |
| FTS5 index only, 187 rows (`fx_text` → `fx_tok_dup`) | 196 608 → 212 992 B (**+8.3 %**) | deterministic |
| extracted text volume | 5.4 % of source chars | 3.3 % without duplicate emission |

Amend is the honest signal because it does strictly more work: FTS5 has no in-place update, so an
amend is delete + reinsert, and D6/D11 make amendment a hot-path operation. Byte figures are
deterministic and reproduce exactly across trials.

**The cost gate passes** — amend p95 +0.394 ms (worst trial +0.677 ms) against the preregistered
≤5 ms, index growth 5.0–8.3 % against ≤50 %. The column is cheap. It is rejected on extractor
quality, not on cost, which is exactly why the extractor rewrite is worth doing.

### 7. The counterfactual identifier instrument (review BLOCKER 3)

The round-1 twin duel is retired. It embedded a bare identifier and compared it against two full,
topically **different** documents, so topic, length, frequency and asymmetric containment were all
still available; it then counted 14 twin sets twice with reversed gold and called the 28 outcomes
independent trials against a 0.500 "chance" baseline.

The replacement: **byte-identical passage templates differing in exactly one substring**, verified
per trial rather than asserted. 14 twin sets × 3 conditions × 6 neutral memory-voice templates × 2
directions = **504 trials per probe per model**. Both directions always run within a set, so an
identifier that is intrinsically more similar to arbitrary prose cannot produce a directional
artifact. **The twin set is the block; n = 14.**

**The null is not a coin flip.** If a model is blind to the identifier, the two passages embed
identically and the margin is **exactly 0** — not 50/50. So the analysis is on margins, with a sign
test across blocks. Two controls validate the instrument before anything is read from it:

| Control | Purpose | Result |
|---|---|---|
| `identity` — identifier masked in **both** passages | floor: margin must be 0 | **0.000000** for all 4 models × 2 probes |
| `exact` — an unrelated, unmistakably distinct token pair per set | ceiling: what achievable separation looks like | win rate **1.000**, margin 0.183–0.235 |

The measurement, bare-token probe. **Two estimands** for the discrimination index, both reported
because `PREREGISTRATION.md` §5.5 declared the first and round 2 quoted the second in its
between-model contrast without saying so (`PREREGISTRATION-R3.md` R3.1):

| Model | near-miss margin | 95 % CI (n=14 blocks) | blocks +/− | exact margin | **DI, ratio of means** *(primary)* | RoM 95 % CI | DI, mean block ratio *(secondary)* | MBR 95 % CI |
|---|---|---|---|---|---|---|---|---|
| bge-small, no prefix | +0.0402 | [+0.0281, +0.0552] | 14 / 0 | +0.1965 | **0.2048** | [0.135, 0.290] | 0.2269 | [0.162, 0.296] |
| bge-small, prefix | +0.0430 | [+0.0294, +0.0597] | 14 / 0 | +0.2102 | **0.2045** | [0.133, 0.291] | 0.2266 | [0.162, 0.296] |
| bge-large, prefix | +0.0513 | [+0.0390, +0.0636] | 14 / 0 | +0.2202 | **0.2331** | [0.173, 0.294] | 0.2448 | [0.187, 0.302] |
| nomic | +0.0490 | [+0.0365, +0.0618] | 14 / 0 | +0.2350 | **0.2087** | [0.143, 0.277] | 0.2375 | [0.168, 0.312] |

RoM is a ratio estimator, so its bootstrap propagates uncertainty in the *denominator* (the
exact-control margin) as well as the numerator, which is why its intervals are wider than MBR's. The
two estimands differ by 0.02–0.03 in level and agree on every ordering and every decision here.

Carrier probe ("Tell me about X."): RoM 0.194 / 0.210 / 0.232 / 0.198 — same picture.

**Three conclusions, each matched to what the instrument shows.**

- **The weakness is real.** Discrimination index 0.194–0.233 against a preregistered "≤0.35 is a
  real weakness". A near-miss identifier buys about a fifth of the separation the same model gets
  from a token it can clearly tell apart. Absolute query→passage cosines on the near-miss condition
  run **0.72–0.80**, depending on model and probe — the deployed bge-small-with-prefix at 0.76–0.79,
  bge-large-with-prefix at 0.72–0.74 — and the near-miss margins on top of them are **0.036–0.051**.
  So the ordering rests on a margin roughly a fifth of the exact control's (0.18–0.24), and a
  **contrary signal of comparable magnitude** overturns it.

  > **Erratum 2 — 2026-08-01.** The two preceding sentences replace one withdrawn sentence. As
  > originally approved this bullet ended: *"Absolute cosines are ~0.73 with margins of 0.04, so any
  > competing signal overturns it."* Two defects, both about scope rather than arithmetic. **"Any
  > competing signal"** asserts something this instrument cannot: it measures one axis, so it fixes
  > neither the direction nor the magnitude of any other signal. A *reinforcing* signal leaves the
  > ordering intact, and a contrary signal weaker than the margin does not flip it — what is supported
  > is that a contrary signal of comparable magnitude decides instead, because the margin is small in
  > absolute terms. **"~0.73"** is a single level and not the deployed one: it is **bge-large-with-prefix's**
  > level (0.7385 bare / 0.7214 carrier), while bge-small-with-prefix — the model D20 keeps — sits at
  > 0.76–0.79 and nomic straddles the two at 0.74–0.79; the
  > instrument's full range across models, probes and conditions is 0.72–0.85 (`twin_counterfactual`
  > `mean_cos_gold`, `results/twin_counterfactual.json`). Headline item 4 carried the same "any
  > competing signal" clause and is narrowed identically. Raised by
  > `reviews/design-corpus-review.md` round 8, finding 3; disposition in
  > `reviews/embedder-benchmark-independent.md` §"Erratum 2". **Evidence fidelity only:** no figure,
  > interval, gate or model decision changes, the three §7 conclusions stand, and the APPROVED verdict
  > is not reopened.
- **It is a margin weakness, not blindness.** 14/14 blocks positive for every model (exact sign
  test, two-sided p ≈ 1.2 × 10⁻⁴), 92–96 % of individual trials won. Round 1's 0.71–0.82 "win rate"
  was *worse* than this because it was polluted by topical noise, and its 0.500 baseline was not a
  justified null. The direction is reliably right; the confidence is thin.
- **No demonstrated remedy from the larger artifact — and this is not a capacity test.** Paired
  across blocks, bge-large − bge-small on DI is **+0.0286, CI [−0.0162, +0.0617]** (ratio of means;
  10 of 14 blocks favouring large) and **+0.0181, CI [−0.0160, +0.0482]** (mean block ratio). nomic
  − bge-small is **+0.0042, CI [−0.0435, +0.0483]** (RoM) and +0.0109, CI [−0.0383, +0.0585] (MBR).
  Every one is roughly a fifth of the preregistered 0.15 bar with a CI including 0. On raw margins
  the same: +0.0083 and +0.0060, CIs including 0. Round 1's monotonic "0.714 → 0.786 → 0.821" does
  not reproduce under control. **What this does not establish:** that capacity is the wrong axis.
  fastembed serves a quantized bge-small against an unquantized bge-large, so the comparison is
  between two deployed artifacts (threat 5), and nomic changes tokenizer, training, dimension,
  context and quantization at once. A genuine capacity control needs matched exports of the same
  family, which was not built. The supported claim is **"neither larger artifact available to us
  materially improved the instrument"**, and the practical consequence — do not buy bge-large to fix
  identifiers — is unchanged.

Containment, which review finding 3 flagged: the 9 **nested** sets (`AUTH_TOKEN`/`AUTH_TOKEN_V2`,
`staging`/`staging-2`, `v2.3.1`/`v2.3.10`, …) give slightly *smaller* margins than the 5 disjoint
sets (bge-small-prefix +0.0381 vs +0.0518), consistent with containment making discrimination
harder — but the CIs overlap heavily at n=9 and n=5 and this is not an inferential claim.

**On "mechanistically real but practically moot".** The first half is now earned. The second half is
not, as stated, and is replaced: **the weakness does not bind on this corpus, because these twin
memories differ in topic as well as identifier and topic decides before the thin margin has to.**
That is a property of the corpus, not a property of embedders. The instrument is precisely the case
where topic is held constant, and there the discrimination index is 0.20. If Zikaron ever holds
memories that are near-identical apart from a version, the 0.20 is the relevant number: with topic
held constant the dense margin is thin but consistently signed, not absent. Whether the lexical arm's
exact-token match compensates — in the full BM25 ranking, or after fusion — was not measured here,
and no arm of this instrument can settle it.

> **Erratum 1 — 2026-08-01.** The preceding two sentences replace one withdrawn clause. As originally
> approved the paragraph ended: *"…the 0.20 is the relevant number and the lexical arm is the only thing
> standing between the agent and a coin flip."* Both halves of that clause are unsupported **on this
> report's own evidence**. "Coin flip" contradicts §7's `identity` control, which establishes that
> blindness implies a margin of exactly 0 rather than 50/50, and the 14/14 signed blocks (sign test
> p ≈ 1.2 × 10⁻⁴) that show a weak-but-present signal; §9 already restates it correctly. "The only thing"
> is an exclusivity claim about an arm this instrument never ran — the counterfactual embeds one probe
> against two passage templates under four embedders, with no BM25 arm, no fusion step and no ranking
> metric, so it cannot establish that lexical matching compensates or that nothing else does. Raised by
> `reviews/design-corpus-review.md` rounds 6–7; full argument and disposition in
> `reviews/embedder-benchmark-independent.md` §"Erratum 1". **Evidence fidelity only:** no figure,
> interval, gate or model decision changes, the three §7 conclusions stand, and the APPROVED verdict is
> not reopened.

### 8. Graded relevance and the intent split (review findings 11 and 12)

**Harmful exposure and useful recall move independently**, which one-gold labelling could not show.
`D_large_prefix` has the best useful recall (0.9323) *and* the worst harmful exposure (0.7083).
`L_E_tok_w3` has poor useful recall (0.8646) and the best harmful exposure (0.3194). Optimising the
round-1 metric would have picked differently from optimising for what the agent should be shown.

**Polarity, restated correctly.** Of the 10 polarity stubs, 6 carry a `harmful_if_applied` label
(the superseded record, for a current-action prompt) and 4 are `historical_intent` and carry **none**
— because there the older record *is* the primary. On the 6 current-action polarity stubs (18
prompts):

| Configuration | harmful_exposure@5 | harmful_disp@5 |
|---|---|---|
| `L_A_unicode61` | 0.8333 | 0.3889 |
| `D_small_prefix` | **1.0000** | 0.5000 |
| `D_large_prefix` | **1.0000** | 0.3333 |
| `H_small_prefix` | 0.9444 | 0.4444 |
| `H_tok_w3` | 0.9444 | 0.3333 |
| `H_nomic` | 0.8889 | 0.3889 |

So the correct statement is: **the superseded record is almost always among the five injected gists,
and it outranks the correction in roughly a third of prompts** — n = 6 stubs, which is far too few
for a rate to two decimal places. Round 1's "roughly half the time" pooled in four stubs where
displacement meant the *opposite* thing.

**Historical intent** (4 stubs, 12 prompts — *indicative only, too small for inference*): useful
recall 0.5833 (`L_A`, `H_tok_w3`) to 0.9167 (`D_nomic`, `H_nomic`). The incumbent hybrid is 0.7500.
The design consequence is the one that matters: a `superseded_by` edge that **blanket-suppresses**
the retired node would take these from 0.75 to 0 by construction. Structural supersession must
demote-in-context, not delete from the index.

### 9. Displacement depth (review finding 13)

`hnd_top5` is now `harmful_disp@5` and is the primary displacement measure, since 5 is the injection
budget. Depth 50 vs depth 187 for the incumbent hybrid: `harmful_disp@5` identical (0.1528, as it
must be — top-5 is inside both), `harmful_disp_full` 0.1806 at both depths. For the lexical-only
configurations, depth 187 changes `harmful_disp_full` a little (`L_A` 0.1667, `L_G` 0.1250) because
BM25 returns only matching documents — mean 158–160 of 187 — and that limitation is stated wherever
the number appears rather than being called a full-corpus ranking.

### 10. Reranker scaling (review finding 14)

Round 1 measured one operating point and wrote a conclusion broad enough to sound general. The
scaling curve, `bge-reranker-base` on this CPU, p50 / p95, against the preregistered 200 ms push
budget:

| Passages | 5 pairs | 10 | 25 | 50 | ms per pair |
|---|---|---|---|---|---|
| gist + content | 503 / 509 | 1058 / 1154 | 3058 / 3368 | 6592 / 6747 | 100–132 |
| gist only | **184 / 184** ✅ | 370 / 373 | 888 / 989 | 1908 / 2181 | 36–38 |

Exactly one operating point fits the push budget — gist-only over 5 candidates — and reranking 5
candidates when 5 is the injection budget can only reorder what the agent already sees. So the
rejection stands **for the push path, for this model, on CPU**, now with a curve instead of a point.
On the **pull path**, 1908 ms for 50 gist-only pairs is a different conversation and is not rejected
here. Nothing here measures a smaller reranker, a GPU, or chunked passages.

Round 1's separate observation that the reranker *lowered* recall, collapsing over-length from 1.000
to 0.333, is retained only with its caveat: the six over-length records share one long prefix
template, so that collapse is partly a cloned-tail artifact of the dataset (review finding 14) and
is not independent evidence about reranking.

### 11. What to embed (review finding 15)

Re-run on the **blind** set, dense arm embedding gist only:

| Configuration | gist+content | gist-only | delta | paraphrase g+c → gist | over_length g+c → gist |
|---|---|---|---|---|---|
| `D_small_prefix` | 0.8958 | 0.7708 | **−0.1250** | 0.667 → 0.400 | 0.778 → 0.500 |
| `D_large_prefix` | 0.9323 | 0.8333 | −0.0990 | 0.833 → 0.633 | 0.722 → 0.556 |
| `D_nomic` | 0.9271 | 0.8594 | −0.0677 | 0.800 → 0.667 | 0.722 → 0.500 |
| `H_small_prefix` | 0.9375 | 0.8542 | −0.0833 | 0.800 → 0.600 | 1.000 → 0.722 |
| `H_nomic` | 0.9479 | 0.9115 | −0.0364 | 0.833 → 0.833 | 0.889 → 0.556 |

**Embed `gist + "\n" + content`.** Directionally unambiguous on the blind set — every one of the
eight dense-bearing configurations loses useful recall, by −0.026 (`H_large`) to −0.130
(`D_small_noprefix`) — for the obvious reason: dropping the content drops information.

**512-token truncation is explicitly not settled.** The six over-length records reuse almost the
same 600-token prefix and place the query-matching terms in a synthetic tail, so they are one case
realised six times, and lexical rescue is unusually likely by construction. Round 1's "accept
truncation because BM25 rescued every case" is withdrawn. What is measured and stands: all six are
676–744 bge-small WordPiece tokens with the load-bearing punchline starting at token 618–664, and no
other memory in the corpus exceeds 512 (max 161). What would settle it: a real length distribution
from an actual Zikaron store, and a chunking arm.

### 12. Latency, and the prefix's real cost (review findings 16 and 17)

Unchanged from round 1 and still first-party; the only change is the framing.

| Model | warm embed p50 / p95 | warm hybrid p50 | cold whole process | on disk |
|---|---|---|---|---|
| bge-small, no prefix | **5.45 / 6.17 ms** | 7.97 ms | **783 ms** | **67 MB** |
| bge-small, with prefix | **6.64 / 7.62 ms** | 9.14 ms | 778 ms | 67 MB |
| bge-large | 72.41 / 74.40 ms | 77.93 ms | 3198 ms | 1338 MB |
| nomic | 27.0 / 29.0 ms | 31.2 ms | 1716 ms | 548 MB |
| BM25 only, no model | — | **0.26 ms** | 149 ms | 0 |

**The BGE prefix is not free**: +1.19 ms warm embed p50, +1.17 ms end-to-end. It is a low-cost,
documented, reversible convention — and on the blind set its demonstrable benefit is dense-only
(+0.0260, CI [+0.0052, +0.0521]) and does not survive into the hybrid (+0.0104, CI includes 0). Keep
it because it is what BGE documents and it costs a millisecond, not because it was proven to buy
hybrid quality.

**The cold-start prohibition stands and the replacement is still unmeasured.** 783 ms per user
message is a bad trade, and 149 ms of it is bare interpreter plus `sqlite_vec` before any model
loads. But the four "cold" launches were process-cold on one host with model files already on disk
and pages plausibly warm — not reboot-cold or download-cold. And the warm-MCP alternative has not
been tested at all: MCP lifecycle, IPC latency, concurrency, startup races, hook failure behaviour
and whether the server is reliably resident are all open. Keep the narrow prohibition; run an actual
hook→MCP smoke and latency test before settling the replacement architecture.

---

## Threats to validity (round 2)

Read these before quoting any number above.

1. **The corpus is still synthetic and still 187 memories.** Nothing in round 2 fixes this. Blind
   *queries* against synthetic *memories* is one of the two halves. Absolute numbers remain upper
   bounds; relative ordering and the instrument results are more robust.
2. **Labels share an author with the memories.** The graded relevance table was written by whoever
   wrote the memories. The blind set removes query-side leakage only. Independent annotation, which
   review finding 11 asked for, has not been done.
3. **Two saturated categories still set the aggregate weights.** near_miss (28 stubs) and
   error_string (10) are at 0.952–1.000 and 0.900–1.000 for everything. The ALL column is a
   weighted average whose
   weights come from dataset construction. Unsaturated cells are paraphrase (10) and polarity (10),
   both small.
4. **Historical intent is n = 4 stubs.** Every number in that cell is indicative. It is enough to
   establish that blanket suppression would be wrong, and not enough for a rate.
5. **The quantization confound is unfixed, and it applies to the instrument as well as the task.**
   fastembed serves a *quantized* bge-small (`…-onnx-q`) and an *unquantized* bge-large. So both the
   model comparison in section 3 **and** the between-model comparison in section 7 are comparisons of
   the exact artifacts Zikaron would deploy — which is the decision-relevant comparison — and are
   **not** clean capacity controls. Round 1's argument that this "only strengthens" the anti-scale
   finding assumed quantization is monotonically harmful and is withdrawn. Notably, the *unquantized*
   large model does win dense-only, which is the opposite direction from what round 1 implied. A real
   capacity control needs matched fp32 exports of the same family; that was not built, so **capacity
   as a mechanism is untested here, not refuted**.
6. **The counterfactual instrument uses 6 authored templates, not real memories.** Byte-identity
   buys causal cleanliness at the cost of realism: real memories about `WidgetV1` and `WidgetV2`
   differ in more than the identifier. The instrument measures the mechanism in the limit where only
   the identifier differs. That is exactly what it is for, and it is not a task measurement.
7. **The extractor held-out test is held out, not blind.** I had read `identifiers.py`. Mitigated by
   the reviewer choosing the classes and by hash-freezing before running, not eliminated.
8. **15 declared contrasts × 4 metrics at 95 %.** ~3 chance exclusions of 0 expected. The two
   borderline ones are named in the text where they occur.
9. **Single host, single hardware configuration.** 12 CPU cores, other processes idle-but-present.
   Latency and the reranker curve are for this box.
10. **RRF `k=60`, fusion depth 50 and the tokens weights were fixed, not tuned** — except the
    tokens weight, which was swept 0/1/3 because the review demanded the factorial, and the whole
    curve is reported rather than the best point. Nothing is tuned, so nothing is flattered; equally,
    a negative result for fixed `k=60` does not exclude a tuned fusion, and section 3 now shows that
    is a live question.
11. **No held-out repository.** The evaluation set exercises one authored corpus. Review finding 1's
    request for real Zikaron-like memories from a real repository history is not satisfied and is
    the single largest remaining gap.
12. **Two analyses are exploratory and support no decision.** The tie-handling sensitivity run and
    the arm-agreement decomposition in section 3 were not on the declared contrast list. They are
    reported because they answer a mechanism question the review raised, and they are labelled
    exploratory wherever they appear, per `PREREGISTRATION.md` §7. In particular, the
    arm-agreement finding argues *for* trying weighted fusion; it does not establish what weighted
    fusion would do.
13. **"Custom tokenization confined to an extracted field" is still untested.** `L_G_split` is a
    composite (tokens index + second arm + RRF + tie behaviour, all at once) and cannot isolate it.
    FTS5 cannot give one table two tokenizers, so a clean test needs a different substrate. Nothing
    in the tokens-column verdict depends on it.
14. **The v1-dev/v2-blind gap confounds author with query distribution.** It shows the aggregate is
    not robust to swapping the query set. It does not measure self-authorship, because register,
    length, detail and underspecification changed at the same time as the author did.
15. **The tie-handling sensitivity varies the rule, not the fusion weights.** It rules out
    insertion-order ties as the explanation for section 3; it does not test weighted RRF, a
    different `k`, or score-normalised fusion, any of which could change the picture.

---

## Implications for Zikaron's open questions

- **Open question 2 (is bge-small right?) — closeable, with the reasoning corrected.** Keep
  bge-small; add the documented query prefix as a convention. The identifier weakness is real
  (discrimination index 0.20) and does not bind on a corpus whose twins also differ in topic. Record
  that fastembed serves the *quantized* build by default, and that bge-large **does** win dense-only
  — so the door is closed on cost and pipeline grounds. It is **not** closed on capacity grounds:
  with a quantized small and an unquantized large, capacity was never cleanly tested.
- **Open question 3 (benchmark plan) — executed twice.** bge-large and nomic are measured both
  unfused and fused. Warm CPU latency for bge-small via fastembed is **5.45 ms p50**. New entry for
  the plan: **RRF weighting and `k` now deserve their own pass**, because 960 of 960 fused top-5
  slots go to documents both arms returned, so unweighted fusion demonstrably cannot let a
  single-arm improvement through. Add an explicit tie-breaker at the same time — 12.5 % of queries
  have a top-5 slot ordered by which arm was passed first — though the sensitivity run shows that
  particular defect is not what cost bge-large its advantage.
- **Open question 4 (is the identifier problem an embedder problem?) — no remedy found on any of the
  three axes, and one of them was not properly tested.** (a) capacity: **no demonstrated remedy**
  from either larger artifact, but quantized-vs-unquantized means capacity itself is untested rather
  than refuted; a matched-export comparison is the experiment that would settle it, and it is cheap
  to want and expensive to build. (b) cross-encoder reranking: rejected for the push path with a
  scaling curve, open for the pull path. (c) deterministic identifier extraction: the *idea* passes
  its isolated retrieval test and its cost test, and the *current extractor* fails held-out
  precision, recall and prose false-positives. The parent's instinct to evaluate (c) before spending
  on (a)/(b) was right; the conclusion is "rewrite the extractor and re-run the factorial", not
  "adopt it".
- **Open question 5 (what to embed) — answered `gist + content`**, with model id and dimension
  recorded per vector (`vectors_meta`, plus a model-keyed embedding cache so a same-dimension swap
  cannot silently reuse another model's vectors). **Chunking and the 512 cap stay open.**
- **Open question 6 / D11 (residual staleness) — sharper and more actionable.** A superseded record
  is in the five injected gists 83–100 % of the time and outranks its correction ~1/3 of the time
  (n=6 stubs). Ranking will not fix this. But **blanket suppression of a retired node is also
  wrong** — the four historical-intent stubs need it, and nomic's 0.917 there versus the incumbent's
  0.750 suggests those prompts are answerable. Design consequence: `superseded_by` should demote in
  context and remain retrievable, and D16's soft-retire is the right primitive.
- **Push-path architecture (D12).** Unchanged: the hook must not load a model (783 ms). Either it
  talks to the warm MCP process or it runs BM25-only (0.26 ms warm, 149 ms cold, useful-recall@5
  0.880 against the hybrid's 0.938 on the blind set — a smaller gap than round 1's numbers implied,
  which makes BM25-only push a more credible degraded mode than it looked). The hook→MCP path is
  still unmeasured and should be smoke-tested before the design is settled.

---

## Response to independent review

### Round 1 — 18 findings

Every numbered finding from `reviews/embedder-benchmark-independent.md`, round 1. Review round 2
accepted 12 as resolved, 6 as partially resolved; the four that were still blocking are answered in
the round-2 section below.

**1. [BLOCKER] Self-authored set invalidates production-distribution claims — ACCEPT.**
Built `stubs_v2.json` (prose-free, graded, intent-labelled) and `queries_blind.json` (192 prompts by
an agent that never opened the memory prose, `dataset_src/`, `results/` or this report).
`queries_blind.json` is now the primary set; the 64 are labelled a development set. Every
architecture-closing sentence has been rewritten. The dev/blind difference is reported as a
**query-set gap** (mean +0.0106 useful_hit@5), explicitly not as a measured authorship effect —
see the round-2 response to BLOCKER 2. **Partial**: the review also asked for real memories from a
real repository. Not done — the memories are still synthetic, and this is named as the largest
remaining gap (threat 1, threat 11).

**2. [BLOCKER] Aggregate dominated by saturated categories and an arbitrary mixture — ACCEPT.**
Per-category counts lead; no overall winner is declared from the ALL column; the saturation is
restated as a standing threat (threat 3) rather than a footnote. near_miss and error_string are
still 0.952–1.000 and 0.900–1.000 on the blind set, so the blind queries did not desaturate them,
and I say so.

**3. [BLOCKER] The twin duel does not isolate sub-token identity — ACCEPT, fully rebuilt.**
`twin_counterfactual.py`: byte-identical templates verified per trial, both directions always run,
twin set as the block (n=14 stated everywhere), floor control (identity → margin exactly 0.000000)
and ceiling control (distinct tokens → 100 % win). "Chance = 0.500" is gone, replaced by the correct
observation that **blindness implies margin 0, not a coin flip**. The reportable quantity is the
discrimination index (0.194–0.233). Nested vs disjoint containment is reported as its own subgroup.

**4. [MAJOR] The claimed scale effect is two or three dependent outcomes — ACCEPT.**
"Scale measurably helps" and "mechanistically confirmed [that capacity helps]" are withdrawn. Under
the controlled instrument, bge-large − bge-small on the discrimination index is +0.0286, CI
[−0.0162, +0.0617] (ratio of means, the preregistered estimand), versus a preregistered 0.15 bar.
nomic is described as a tokenizer/training/dimension/context/quantization change, never as scale.
Round 3 additionally removed the reintroduced causal claim that capacity is *refuted* — see the
round-2 response to BLOCKER 1.

**5. [BLOCKER] Config 5 is not an ablation of an extracted tokens column — ACCEPT, and the review
was right about the direction of the error.** Seven-way factorial. The finding: the custom tokenizer
alone **costs** −0.0521 useful_hit@5 (CI excludes 0), the tokens field recovers +0.0365, duplicate
emission does **nothing** (0 changed queries), weight 1 ≈ weight 3, and the round-1 comparison
against the `unicode61` baseline is −0.0156. Round 1's attribution was wrong. **Partial**: the
review's optional fifth arm — custom tokenization applied only to the extracted field — is not
isolable in FTS5 and `L_G_split` does not isolate it; round 3 relabels that arm a composite and
records the gap (threat 13).

**6. [BLOCKER] The extractor was developed against the test traps — ACCEPT, and it fails.**
Frozen by sha256, `verify_freeze.py` enforces it, then tested on 60 held-out strings across the eight
classes the review named. Recall 0.4186 (gate 0.70), precision 0.5362 (gate 0.80), false tokens on
6/7 numeric prose sentences (gate 25 %), 2/12 held-out near-miss pairs collapsing. **The `tokens`
column is not adopted.** Disclosed: held out but not blind, since I had read the implementation.

**7. [MAJOR] The improvement fails the report's own noise rule and its cost is unmeasured —
ACCEPT.** The noise rule is replaced by a preregistration written before any round-2 result was
computed, with frozen input hashes. Cost measured over 3 paired trials, because the first
single-shot run produced an `fsync` artifact (insert p95 *improving* under extra work): whole
database +5.0 %, FTS shadow tables +5.4 %, amend p50 +0.215 ms, amend p95 +0.394 ms, extraction
itself 0.101 ms p50. The cost gate **passes**; the extractor gate
fails, so the verdict is still rejection — for the right reason this time. Where the hybrid MRR
effect misses the preregistered bar by 0.0004, I say so instead of rounding it into a pass.

**8. [MAJOR] No dense-only large-vs-small comparison; RRF ties favour BM25 — ACCEPT, and this
changed a conclusion.** Dense-only controls added for both models. **The deployed bge-large artifact
beats bge-small dense-only** (MRR +0.0705, CI [+0.0283, +0.1156]) and the hybrid does not pass it
through. Ties quantified: **100 %** of hybrid queries contain an exact tie, ~17.5 tied adjacent pairs
per query, **12.5 %** of queries have at least one tie inside the top 5, resolved by insertion order
in the BM25 arm's favour. An explicit tie-breaker is a recommendation. Round 3 fixed the tie
*counting* and tested whether ties are *causal* — they are not — see the round-2 response to
BLOCKER 3.

**9. [MAJOR] The quantization confound breaks the causal scale control — ACCEPT.**
Round 1's "only strengthens" argument is withdrawn as resting on an unestablished monotonicity
assumption. The comparison is reframed as deployed-artifact, and the reframing is load-bearing:
the unquantized large model *does* win dense-only, the opposite of what round 1 implied.

**10. [MAJOR] The report violates its own statistical rule for both headline comparisons —
ACCEPT.** Every comparison now carries a paired cluster bootstrap CI over stubs, raw changed-query
counts, and a preregistered threshold. Conclusion 1 says "no demonstrated task gain at high measured
cost". Conclusion 2 recommends the prefix as a low-risk documented convention and states its measured
1.2 ms cost in the same sentence.

**11. [MAJOR] One-gold labelling is incomplete — ACCEPT.**
Graded labels: 67 primary (including co-primaries for the `c2-cert-chain`/`c3-ssl-verify` and
`c1-ver-2-3-1`/`c3-symbol-lookup` pairs the review named), 120 also_useful, 48 harmful_if_applied
across 24 stubs. 16 round-1 hard-negative labels did not survive the "would actually mislead" bar.
Useful recall and harmful exposure are reported separately and demonstrably move independently.
**Partial**: the annotators are not independent of the memory author. Named as threat 2.

**12. [MAJOR] The polarity statistic has the opposite semantics for four of ten queries —
ACCEPT.** The four historical-intent stubs now carry **no** harmful label, so they are excluded from
displacement by construction rather than by argument. The statistic is quoted only for the 6
current-action polarity stubs, as "the superseded record is in the injected five 83–100 % of the time
and outranks the correction ~1/3 of the time, n=6". "Roughly half the time" is gone. The structural
policy is evaluated: `superseded_by` yes, blanket suppression no — it would take the historical cell
from 0.75 to 0.

**13. [MAJOR] `hnd` is not a full-corpus ranking — ACCEPT.**
`harmful_disp@5` is the primary displacement measure. Everything is run at depth 50 **and** depth
187. A limitation the review did not raise but which follows: even at depth 187 a pure-BM25 arm can
only rank documents sharing a term with the query (mean 158-160 of 187), so `harmful_disp_full` for
lexical configurations is displacement within the matching set and is labelled as such.

**14. [MAJOR] The evidence rejects one reranker deployment, not reranking — ACCEPT.**
Measured the scaling curve: 5/10/25/50 candidates × gist-only/gist+content. Exactly one point fits
the preregistered 200 ms push budget (gist-only, 5 candidates, 184 ms), and it is operationally
useless since 5 is the injection budget. The rejection is scoped to `bge-reranker-base`, unchunked
pairs, CPU, push path. The pull path is explicitly not rejected (1908 ms for 50 gist-only pairs).
The recall collapse is retained only with the cloned-tail caveat.

**15. [MAJOR] "Embed gist+content" survives; "accept truncation" does not — ACCEPT.**
Gist-only re-run on the blind set: −0.037 to −0.125 useful_hit@5, paraphrase −0.13 to −0.27.
Adopted. "512 truncation accepted" is withdrawn; the preregistration declared this
**not settleable** by this dataset before the results were seen, and the report says what would
settle it.

**16. [MAJOR] The warm-MCP alternative is unmeasured — ACCEPT.**
The narrow prohibition is kept and the four cold launches are relabelled process-cold on one host
with files already downloaded. MCP lifecycle, IPC, concurrency, startup races and residency are
named as untested, with a hook→MCP smoke test as the required next step. Not measured here — it is
an integration test against a server that does not exist yet.

**17. [MINOR] The prefix is not literally free — ACCEPT.**
"Free" is removed everywhere. It costs 5.45 → 6.64 ms warm embed p50 and 7.97 → 9.14 ms end-to-end,
quoted in the same sentence as the recommendation.

**18. [MINOR] Deterministic reruns presented as replication — ACCEPT.**
No rerun is presented as replication. Uncertainty is a paired cluster bootstrap over stubs (10 000
resamples, blocked because three variants of a stub are one need), the twin instrument blocks on the
twin set, every difference carries changed-query counts, and phrasing uncertainty is estimated from
the three registers (spread 0.016–0.063 on `useful_hit@5`). A held-out repository is still missing
and is named as such.

### Nothing in round 1 was rejected outright

All 18 round-1 findings were accepted. Four are accepted **partially**, and the residue is stated
rather than quietly dropped: real memories from a real repository (1, 11), independent annotators
(11), a measured hook→MCP path (16), and the un-isolable "tokenization confined to an extracted
field" arm (5). Two places push back on *scope* rather than on substance, and both are argued in the
text rather than asserted here: the held-out extractor test is held out but not blind (section 5),
and the counterfactual instrument trades realism for causal cleanliness by design (threat 6).

### Round 2 — 4 blocking findings

Every numbered finding from `reviews/embedder-benchmark-independent.md`, round 2. **All four
accepted; none changed a recommendation.** Round-3 work was declared in
`experiments/embedder-precision/PREREGISTRATION-R3.md` before any round-3 number was computed, and
`PREREGISTRATION.md` was not edited.

**R2-1. [BLOCKER] Causal capacity language re-widened, and the quoted DI contrast is a different
estimand from the displayed DIs — ACCEPT, both halves.**

*The estimand.* The review is exactly right and the diagnosis is precise: `twin_counterfactual.py`
displayed the **ratio of means** (0.2046, 0.2330) and bootstrapped the **mean of per-block ratios**
for the between-model contrast (+0.0181), and the report did not say it had switched. Round 3 pins
the estimand down in `PREREGISTRATION-R3.md` R3.1 — `PREREGISTRATION.md` §5.5 literally says "mean
near-miss margin ÷ mean exact-control margin", so **ratio of means is the preregistered estimand and
is now primary** — and reports both, named, each with its own cluster bootstrap over the 14 twin
sets. The RoM bootstrap recomputes both models' ratio inside every resample, so denominator
uncertainty propagates. New primary numbers: bge-large − bge-small **+0.0286, CI [−0.0162, +0.0617]**;
nomic − bge-small **+0.0042, CI [−0.0435, +0.0483]**. The secondary MBR numbers (+0.0181, +0.0109)
are retained beside them. Both estimands include 0 and both are ~5× below the 0.15 bar, so the
decision is unchanged — and that agreement is now stated rather than assumed. Per-model levels moved
in the fourth decimal (0.2046 → 0.2045) because `aggregate` was computing the ratio from
already-rounded margins; it now shares one code path with the bootstrap, so there is exactly one
number per model instead of two that nearly agree.

*The language.* Also accepted, and the internal contradiction was real: Threat 5 said
quantized-small-vs-unquantized-large is not a capacity control while section 7, headline 3 and the
implications called capacity refuted. Fixed everywhere. The settled/open table row is now "A more
capable embedder fixes the identifier weakness — **no demonstrated remedy; capacity itself
untested**". Section 7 states plainly that a genuine capacity control needs matched fp32 exports of
the same family, which was not built, and that the supported claim is "neither larger artifact
available to us materially improved the instrument". Threat 5 now covers the instrument as well as
the task comparison. `PREREGISTRATION-R3.md` R3.2 records the permitted and forbidden wording so this
cannot drift back.

**R2-2. [BLOCKER] The dev-versus-blind gap does not isolate or bound an authorship effect —
ACCEPT.** The review is right that author identity is inseparable from the register/length/detail/
underspecification change, and that averaging 36 correlated cells is not an uncertainty estimate.
Renamed throughout — in prose, in the JSON key (`authorship_inflation` → `query_set_gap`), in
`eval_v2.py`'s and `evalkit.load_dev`'s docstrings — to the **observed v1-development versus v2-blind
query-set gap**. "Isolates", "inflation", "real" and "bounds the damage" are gone. Section 2 now
states what the gap does and does not license, and adds the interval the review suggested: a
stub-clustered bootstrap of each stub's dev value against the mean of its three blind variants
(`D_small_prefix` +0.0573, CI [+0.0104, +0.1146], 8 stubs dev-higher / 54 tied / 2 blind-higher;
`H_small_prefix` 0.0000, CI [−0.0625, +0.0573]), labelled as an interval on the **set difference**.
Threat 14 records the confound. What the gap still supports, and all it supports: round 1 drew
conclusions from 0.014–0.047 differences, which is inside the range a query-set swap moves, so those
conclusions were not safe. Section 2 also names the experiment that *would* separate author from
distribution — a second blind author writing in v1's register, or v1's prompts rewritten into the
three v2 registers.

**R2-3. [BLOCKER] The headline tie percentage is not what the harness computes, and prevalence does
not explain the vanished dense gain — ACCEPT both, and the causal claim is withdrawn.**

*The counting bug.* Confirmed by reading the code the review pointed at: `ties_in_top5` summed tied
adjacent pairs and `tie_report` divided by the query count under a name that says "fraction of
queries". `retrieval2.rrf_counted` now tracks a per-fusion boolean (`fusions_with_tie_in_top5`)
alongside the pair count, and both are reported under names that say which is which. Corrected
numbers: `H_small_prefix` 0.1250, `H_large` 0.1562, `H_nomic` **0.1146** (report said 11.98 %),
`H_tok_w3` 0.0781, `L_G_split` **0.1719** (pair count 0.1979). Three of the five coincided only
because no query in those configurations had two adjacent top-5 ties; section 3 says so rather than
treating the coincidence as vindication.

*The causal claim.* Withdrawn, and replaced with a measurement. `tie_sensitivity.py` re-runs the
hybrids under the canonical rule, an arm-order swap, and two explicit tie-breaks — the decision rule
was fixed in `PREREGISTRATION-R3.md` R3.5 before the numbers existed ("point ≥ +0.05 with CI
excluding 0 under at least one alternative rule"). The `large_vs_small_hybrid` contrast moves from
−0.0156 to at most −0.0104: **maximum movement 0.0052, one query, nothing near the bar.** So ties are
described as a real design defect of near-null consequence for this comparison, worth fixing on its
own terms and explaining nothing here. A different mechanism is measured in its place: **960 of 960
fused top-5 slots are held by documents both arms returned**, and of the 9 prompts where bge-large's
dense arm gains a primary, 4 were already answered by the small hybrid, 1 survived, and 4 were
destroyed with the primary at dense rank 1–5 but BM25 rank 14/30/50/absent. Both analyses are
labelled **exploratory** (threats 12, 15) and support no decision; what they support is making
weighted fusion a named follow-up with a stated predicted mechanism.

**R2-4. [BLOCKER] `L_G_split` still confounds the factor it is said to isolate — ACCEPT.**
Relabelled a **composite split-index RRF architecture comparison** in the contrast list
(`split_tokenization` → `split_index_composite`), in the config description, in the section-4 table
("**COMPOSITE, isolates nothing**"), in the primary results table and in the README. The review is
right that no new experiment is needed, and round 3 adds the consequence the relabelling implies
rather than leaving it implicit: **"custom tokenization confined to an extracted field" is now listed
as untested** (threat 13), with the reason (FTS5 cannot give one table two tokenizers, so a clean
test needs a different substrate) and the note that it is the arm to add if the extractor is ever
rewritten. The decision-bearing `L_E` vs `L_B` contrast and the tokens-column verdict are untouched.

### Nothing in round 2 was rejected

All four findings were accepted in full. Two produced new measurements (the RoM bootstrap, the tie
sensitivity), two were wording and labelling corrections, and one — the tie counting — turned out to
have been numerically right by luck for the headline configurations and wrong for two others, which
is recorded rather than glossed.

---

## Artefacts

| Path | What |
|---|---|
| `experiments/embedder-precision/README.md` | How to re-run everything, file map, versions, gotchas |
| `experiments/embedder-precision/PREREGISTRATION.md` | Round-2 thresholds and analysis plan, timestamped before any round-2 result. Frozen and unedited. |
| `experiments/embedder-precision/PREREGISTRATION-R3.md` | Round-3 addendum: the RoM/MBR estimand pin-down, the tie-sensitivity decision rule, the renames. Written before any round-3 result; no round-2 threshold changed. Carries an **amendment log** for the two things that moved afterwards, so its mtime is later than the results and says so. |
| `experiments/embedder-precision/stubs_v2.json` | Prose-free authoring spec: graded relevance, intent, user-side identifiers |
| `experiments/embedder-precision/queries_blind.json` | **The primary eval set.** 192 prompts, 3 registers per stub |
| `experiments/embedder-precision/dataset.json` | 187 memories, 64 development queries |
| `results/eval_v2.json` | 18 configs × 2 query sets × 2 depths, graded metrics, 15 declared contrasts with CIs, the v1-dev/v2-blind query-set gap, tie accounting |
| `results/eval_v2_gist_only.json` | The what-to-embed comparison on the blind set |
| `results/twin_counterfactual.json` | The counterfactual identifier instrument, per block and per trial, both DI estimands |
| `results/tie_sensitivity.json` | **Exploratory.** Four tie-handling rules × 4 hybrids, plus the arm-agreement decomposition |
| `results/extractor_heldout.json` | Frozen-extractor held-out precision/recall, per class, with collisions |
| `results/tokens_cost.json` | Index bytes, database growth, insert/amend p50/p95 |
| `results/rerank_scaling.json` | Reranker latency across candidate counts and passage lengths |
| `results/latency.json` | Warm/cold latency and footprint (round 1, unchanged) |
| `results/truncation_check.json` | WordPiece token counts and punchline positions |
| `results/sweep_gist_content.json`, `results/twin_duel.json` | **Round-1 results, retained for audit.** Superseded by the above |
| `reviews/embedder-benchmark-independent.md` | The independent review this round answers |
| `reviews/embedder-precision-eval-design.md` | Round-1 self-critique (12 attacks) |
