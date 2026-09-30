# Preregistration addendum — round 4: granite and e5 against the shipped bge-small

**Written 2026-09-30T02:10Z**, before any round-4 score was computed. The only round-4 outputs that
existed when this was written are a five-model load check — one query, one relevant and one
irrelevant passage, used to confirm each artifact loads, is unit-normalized and ranks the obvious
pair the right way round — which is not drawn from any evaluation set.

`PREREGISTRATION.md` stays frozen and `PREREGISTRATION-R3.md`'s estimand rules stay in force. **No
threshold in either is changed.** This file adds arms, names which contrast decides, and says what
each outcome leads to.

## R4.1 The question and why it is asked now

`research/technical-embedders.md` (2026-09-29) found one servable candidate that beats
`bge-small-en-v1.5` on the published proxy closest to this workload: **`granite-embedding-30m-english`**,
CoIR StackOverflow-QA +5.9 NDCG@10, average +1.2, same size and width. Every figure is from IBM's own
paper. This round asks whether that survives this project's own instruments.

## R4.2 Arms

| Tag | Artifact | Revision | Query / passage prefix | Role |
|---|---|---|---|---|
| `bge-small-prefix` | fastembed `BAAI/bge-small-en-v1.5` (qdrant quantized, the shipped one) | as shipped | BGE instruction / none | **incumbent** |
| `bge-small-fp32-prefix` | `BAAI/bge-small-en-v1.5` `onnx/model.onnx` | `5c38ec7c` | BGE instruction / none | artifact control |
| `granite-30m` | `ibm-granite/granite-embedding-30m-english` | `9b5b0964` | none / none | **candidate** |
| `e5-small` | `intfloat/e5-small-v2` | `ffb93f3b` | `query: ` / `passage: ` | candidate |
| `granite-125m` | `ibm-granite/granite-embedding-125m-english` | `4ab61ffd` | none / none | candidate, 768-dim |

Loaded through `custom_models.py` (`add_custom_model`, pooling from each repository's
`1_Pooling/config.json`). Every arm embeds gist + content (D21) and is fused with `L_A_unicode61` at
`k=60`, depth 50, exactly as `H_small_prefix` is.

## R4.3 What decides

**The decision is whether to replace the shipped embedder.** The deciding contrast per candidate is
**`H_<candidate>` − `H_small_prefix`** on the blind set at depth 50, under `PREREGISTRATION.md` §5.1
verbatim: a paired stub-cluster CI on `useful_recall@5` excluding 0, a point estimate ≥ +0.05, the
gain present in ≥ 2 of the 5 trap categories, and the cost gate on warm-embed p50 measured by
`latency.py` **in this round, on this host**, relative to the incumbent (≤ 3× → +0.05, 3–10× → +0.08,
> 10× → +0.12).

The hybrid decides because it is what ships; **Q2 already measured fusion erasing a dense-only gain**
(bge-large, MRR@10 +0.0705 dense-only, nothing in the hybrid). Dense-only contrasts are reported and
decide nothing.

**Three candidates means three chances.** At 95 %, one spurious exclusion of 0 in three is not
negligible; a pass that clears its CI by a hair is said out loud as that, per §7.

## R4.4 Reported, deciding nothing

- **Dense-only**: `D_<candidate>` − `D_small_prefix`, on the same metrics.
- **Artifact control**: `D_small_fp32` − `D_small_prefix` and the `H_` pair. This is the size of
  the quantization effect alone. **A candidate's gain is attributed to the model rather than to
  shipping it unquantized only if it also clears its CI against `H_small_fp32`.** It does not change
  the decision, which is about replacing the shipped artifact, but it changes what the note may say.
- **Identifier discrimination**, `twin_counterfactual.py`: the discrimination index under R3.1's
  primary estimand (ratio of means), with §5.5's bar (≥ +0.15, block CI excludes 0) applied to each
  candidate − incumbent. Instrument validity (identity control margin 0.0000 to 4 dp, exact control
  win rate ≥ 0.90) is re-checked per new model; a model failing it is reported as unmeasured.
- **Latency and footprint** (`PREREGISTRATION.md` §6 facts): warm embed p50, cold whole-process
  start, ONNX bytes.

## R4.5 What follows from each outcome

- **No candidate passes R4.3** → keep `bge-small`; the survey's granite lead is closed for this
  workload; the knowledge-index instruments are **not** run, since nothing they could show would
  change the decision. Q8 is updated with the result.
- **A candidate passes** → before any proposal, run it on the knowledge-index side too — M25's
  `heading` family and M26's 20 real questions, reporting how many of its top-k passages are
  unlabelled rather than scoring them as misses — where a regression with a CI excluding 0 vetoes.
  Surviving that, it becomes a milestone proposal, whose costs are already known: a new pin in
  `model_pin.py`, re-embedding every store under D20's recorded-model rule, and — for granite —
  chunk token counting in `encoder.py`, which uses bge's WordPiece while granite is a RoBERTa BPE
  model.

## R4.6 Frozen inputs (sha256), verified by `verify_freeze.py` at 2026-09-30T02:09Z

```
4c3e82412f0de87e109de9c6b4c141f481c3aad062d6782eb89af7c1ba8b994d  dataset.json
a55970cb0d81a17958ee317160aa589c09d9a4c62505e59e7448caa4a8090c5d  queries_blind.json
b2daf74c01744bd2428a78b0d3f8f186afce35ae7b46bc5dec82a5e4cc607320  stubs_v2.json
406a028bebb588b414ae642c6c990f4214516b90541fab3acd90d5648bf249a7  custom_models.py
```

**The existing round-2/3 configurations must reproduce bit-identically** on the rerun — the cache is
keyed by model name and inference is deterministic. If any incumbent number moves, that is found
before a candidate number is read.

## Amendment log

Anything below this line was written after the body above, each entry saying what existed when it
was.

**A1 — 2026-09-30T02:25Z, method only, written while `eval_v2` was running and before any latency
figure or any round-4 score had been read.** The operator reports the host will not be idle for
days. Retrieval metrics are deterministic and unaffected. The cost gate's axis becomes **the median
of per-rep warm-embed ratios to the incumbent**, with every model timed once per rep, round-robin,
so all arms share one load (`r4_latency.py`). The gate's thresholds (≤ 3×, 3–10×, > 10×) are
unchanged. Absolute milliseconds from this round are reported with the load average and are **not**
compared with round 1's or with any idle-host budget.

**A2 — 2026-09-30T02:40Z, after the quality results.** `r4_latency.py` was **not run**. No candidate
reached R4.3's lowest quality threshold (+0.05, the ≤ 3× tier), so no cost ratio could change any
verdict, and on a host the operator reports busy for days the absolute figures would be unusable
anyway. The script stays for a future round that has a candidate worth costing.
