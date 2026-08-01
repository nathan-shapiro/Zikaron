# Preregistration — embedder benchmark round 2

**Written 2026-08-01T02:28:08Z**, before any round-2 result was computed or inspected.

This document exists because round 1 stated a noise rule ("differences below about 0.05 are noise")
and then promoted a 0.0450 difference as its best-value finding. Review finding 7 caught that.
Predeclaring the decision thresholds removes the opportunity to repeat it.

**This file is frozen.** It must not be edited after the first round-2 result is produced. If a
threshold here turns out to be badly chosen, the correction goes in the report as a labelled
deviation, not as a silent edit here. Frozen input hashes are recorded at the bottom so a future
session can prove nothing moved underneath the analysis.

---

## 1. What was already known when this was written

Round-1 results (`results/sweep_gist_content.json`, `results/twin_duel.json`,
`results/latency.json`) and `research/embedder-benchmark-results.md` have been read. The round-1
numbers are therefore **not blind** to me and are treated as a **development set** throughout.

Nothing computed from `queries_blind.json`, from the factorial ablation, from the held-out
extractor test, from the counterfactual twin instrument, or from the write-cost measurement had
been looked at when this was written. Those are the round-2 results the thresholds below govern.

## 2. Datasets and their status

| Set | Status | n | Use |
|---|---|---|---|
| `dataset.json` queries (v1, 64) | **development** — memories and queries by the same author | 64 | reported for comparison only; **may not settle any decision** |
| `queries_blind.json` (v2, 192) | **primary** — prompts authored without ever reading the memory prose | 192 prompts / 64 stubs | every decision below |
| `stubs_v2.json` graded labels | primary label source | 67 primary / 120 also_useful / 48 harmful_if_applied | every decision below |
| held-out extractor material | to be authored in round 2, never used to develop `identifiers.py` | ~60 strings | extractor gate only |

The v1→v2 difference is itself a **planned measurement**: the size of the self-authorship
inflation, reported as a number rather than as a worry.

## 3. Unit of analysis and uncertainty (declared before seeing results)

- **The stub is the resampling unit**, not the query. The three phrasing variants of one stub are
  the same underlying information need and are correlated. All confidence intervals are **cluster
  bootstrap over the 64 stubs**, 10 000 resamples, 95 % percentile intervals, on the **paired
  difference** between configurations (same resample of stubs applied to both arms).
- **Twin sets block the near-miss analysis.** The 28 near-miss stubs are 14 mirrored twin sets.
  The near-miss unit is the **twin set (n=14)**, and that number will be stated wherever a
  near-miss result is quoted.
- **Phrasing uncertainty** is estimated from the three registers (`terse` / `mid` / `verbose`) as
  the spread of the metric across the three single-variant evaluations. It is reported alongside
  the pooled number, never hidden inside it.
- **Raw changed-query counts** accompany every difference. "+0.03 recall" must always be
  accompanied by "n queries changed: k up, m down".
- A deterministic rerun is **not** a replication and will not be presented as one.

## 4. Primary metrics (declared)

Computed over `queries_blind.json` with graded labels, top-5 because D12 injects five gists.

1. **`useful_recall@5`** — fraction of prompts with at least one `primary` memory in the top 5.
   *The headline.*
2. **`harmful_exposure@5`** — fraction of prompts with at least one `harmful_if_applied` memory in
   the top 5. Reported **separately** from useful recall; the two are not netted against each
   other.
3. **`harmful_displacement@5`** — a `harmful_if_applied` memory in the top 5 **and** ranked above
   every `primary` memory. The operational displacement measure, and the **primary** displacement
   measure (review finding 13).
4. **`mrr@10`** over `primary` memories.
5. **`relevant_recall@5`** — recall of the union `primary ∪ also_useful`, reported as a secondary
   view because D12's five slots make a second useful memory a benefit, not a failure.

Reported split by **intent** (`current_action` n=60 / `historical_intent` n=4) and never pooled
when the interpretation differs. The historical-intent cell has **n=4 stubs / 12 prompts** and
will be labelled *indicative only, too small for inference*.

`precision@5` is dropped: with a mean of ~1.05 primaries per stub its ceiling is ~0.21 and it
carries no information beyond `useful_recall@5`. Round 1 reported it because the brief asked; it
misled nobody but added nothing.

## 5. Decision thresholds — the smallest effect worth an architecture change

These are the numbers the round-2 results will be judged against.

### 5.1 Replacing the embedder (bge-large or nomic in place of bge-small)

A model swap is an operational commitment: model download, disk, per-message latency, and a full
corpus reindex on any future change. It must clear a **quality gate and a cost gate**.

Quality gate — **all three**:
- paired `useful_recall@5` improvement on the blind set with a 95 % cluster-bootstrap CI that
  **excludes 0**; and
- point estimate **≥ +0.05** absolute (≈ 10 of 192 prompts); and
- the improvement is **not confined to a single trap category** (it must appear in ≥ 2 of the 5).

Cost gate — the required quality gain **scales with measured cost**, using round-1 warm-embed p50
as the cost axis (bge-small 5.5 ms, nomic 27.0 ms ≈ 5×, bge-large 72.4 ms ≈ 13×):
- ≤ 3× incumbent embed latency → **≥ +0.05** useful_recall@5 suffices;
- 3–10× → **≥ +0.08**;
- \> 10× → **≥ +0.12**.

If the quality gate is not met, the recorded conclusion is **"no demonstrated task gain at
measured cost X"** — explicitly *not* "worse" and *not* "scale is disproved".

### 5.2 Adopting the extracted-identifier `tokens` column

This adds a schema column, a regex extractor to maintain, and a hard invariant (extractor and FTS
tokenizer must stay in sync or the column silently degrades). Gate — **all four**:

- **Isolated effect.** The contrast that counts is `tokens field at weight 3` **vs** *the same
  custom tokenizer with no tokens field* — not vs the `unicode61` baseline. That contrast must
  show a paired improvement with 95 % CI excluding 0 and a point estimate of **≥ +0.02**
  `useful_recall@5` **or** **≥ +0.03** `mrr@10`.
- **No harm.** `harmful_exposure@5` must not worsen by more than **+0.02**, and
  `harmful_displacement@5` must not worsen at all beyond bootstrap noise.
- **Held-out extractor quality.** On material the extractor has never seen: token-level
  **precision ≥ 0.80** and **recall ≥ 0.70**, with **no false-positive class that fires on more
  than 25 % of ordinary prose sentences**. A false positive that collides two genuinely distinct
  identifiers is disqualifying regardless of the aggregate.
- **Cost.** Write-path p95 increase **≤ 5 ms** per memory and total index growth **≤ 50 %**.

If the isolated effect is attributable to the tokenizer change alone, or to the duplicate-emission
term-frequency boost alone, the correct conclusion is **"the tokens column is not the active
ingredient"**, and the cheaper factor is what gets adopted.

### 5.3 The BGE query prefix

Retained as a **convention** unless the paired difference is *negative* with a CI excluding 0. The
measured cost (5.45 → 6.64 ms warm embed p50; 7.97 → 9.14 ms end-to-end p50) is disclosed in the
same sentence as the recommendation. The word "free" is not used.

### 5.4 A cross-encoder reranker on the push path

Hard latency budget declared in advance: **p95 ≤ 200 ms** for the whole rerank stage, chosen
because it is ~20× the measured warm hybrid path (9 ms) and still invisible next to a model turn.
`bge-reranker-base` at 50 unchunked pairs measured 6069 ms, so it fails by ~30×. The rejection is
recorded as **specific to that model, that candidate count, unchunked pairs, and CPU** — it does
not generalise to smaller rerankers, fewer or chunked candidates, gist-only reranking, or the pull
path, none of which were measured.

### 5.5 The counterfactual twin instrument

Declared **before** construction, because this is where round 1's analysis was weakest:

- **The null is not a coin flip.** With byte-identical passage templates differing only in the
  identifier, a model that is entirely blind to the identifier produces **two identical passage
  embeddings and a margin of exactly 0** — not a 50/50 win rate. So the analysis is on the
  **margin distribution**, blocked by twin set, with a sign test across the 14 blocks. Win rate is
  reported for continuity but is explicitly ill-conditioned near the null and will be labelled as
  such.
- **Instrument validation is mandatory.** Two controls must behave, or the instrument is reported
  as broken rather than as a result: an `identity` control (identifier masked in *both* passages)
  must yield margin **= 0.0000** to 4 dp; an `exact` control (two unmistakably distinct tokens in
  place of the twins) must yield a win rate **≥ 0.90** and a clearly larger mean margin.
- **The reportable quantity** is the **discrimination index** = mean near-miss margin ÷ mean
  exact-control margin, per model — "how much of the achievable separation does this model get on
  a near-miss pair". Declared interpretation: **≥ 0.75 is usable discrimination; ≤ 0.35 is a real
  weakness.** Between those, inconclusive.
- **A between-model difference counts as a capacity effect only if** the paired-by-block CI on the
  discrimination-index difference excludes 0 **and** the point difference is **≥ 0.15**. Two or
  three flipped outcomes out of 14 blocks will not be called a scale effect.
- `nomic` changes tokenizer, training data, dimension, context length and quantization at once.
  Whatever it does, it is **not** evidence about scale, and will not be described as such.

### 5.6 Truncation past 512 tokens

Declared **not settleable** by this dataset: the six over-length records share one long prefix
template, so they are one case realized six times. No round-2 result will be allowed to close
this. The reportable statements are the measured token counts and the measured behaviour of this
one template. Closing it requires a real long-memory length distribution, which does not exist
yet.

## 6. Facts exempt from the gates above

These are direct measurements of these exact artifacts, not inferences about model quality, and
stand on their own: warm/cold latency, on-disk footprint, index bytes, insert/amend timings,
WordPiece token counts, `rrf()` tie frequency, and extraction counts. They are limited to the
measured host, versions and batch sizes, and are quoted with those qualifiers.

## 7. Analysis discipline

- **One planned pass.** The contrasts to be computed are exactly those in §5 plus the descriptive
  breakdowns in §4. Any contrast run beyond that list is labelled **exploratory** in the report
  and may not support a decision.
- **No per-configuration tuning.** RRF `k=60` and fusion depth stay fixed. The tokens-column
  weight is *swept* (0/1/3) because the review demanded the factorial — the sweep is the
  experiment, and the whole curve is reported, not the best point.
- **No metric substitution.** If `useful_recall@5` does not move but some other metric does, the
  headline stays `useful_recall@5` and the other metric is reported as secondary.
- **Multiplicity is acknowledged, not corrected away.** ~20 planned contrasts at 95 % means roughly
  one spurious exclusion of 0 is expected. Wherever a CI barely excludes 0, that is said out loud
  instead of being treated as a discovery.
- **Failure is publishable.** If nothing clears a gate, the report says so and the recommendation
  is "keep the incumbent".

## 8. Frozen input hashes (sha256)

```
836dbd85ab63ea578eeacd1c0eb2ab9a6205aaf2769258157880dedd76b5b35f  identifiers.py
bad01b8afceb0e553e60345cb77e762eb886200392e2ed9b63c226812fb54662  retrieval.py
743034ff7c72e951041b77aa9acd03333b34a4a02eeaf07221a5c63b14e8dac9  sweep.py
a24a16726d1d6fc3280fab224047768d7a214f4c156a1ed13062c6ef48a36147  twin_duel.py
b2daf74c01744bd2428a78b0d3f8f186afce35ae7b46bc5dec82a5e4cc607320  stubs_v2.json
a55970cb0d81a17958ee317160aa589c09d9a4c62505e59e7448caa4a8090c5d  queries_blind.json
4c3e82412f0de87e109de9c6b4c141f481c3aad062d6782eb89af7c1ba8b994d  dataset.json
```

`identifiers.py` is **frozen at the hash above** for the held-out test of §5.2. `verify_freeze.py`
re-checks it. If it ever needs to change, the held-out test must be re-authored on fresh material,
because the current material stops being held out the moment the extractor is tuned against it.
