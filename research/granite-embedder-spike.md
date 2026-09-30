# Granite and e5 against the shipped bge-small: no candidate clears the gate

**Question.** `research/technical-embedders.md` found one servable embedder that beats
`bge-small-en-v1.5` on the published benchmark closest to Zikaron's workload:
`ibm-granite/granite-embedding-30m-english`, CoIR StackOverflow-QA +5.9 NDCG@10, on IBM's own
figures. Does that survive this project's own instruments?

**Answer: no.** In the deployed hybrid, granite-30m is **−0.0052 useful-recall@5, CI [−0.0365,
+0.0208]**, against a preregistered +0.05 bar. Neither `e5-small-v2` nor `granite-embedding-125m`
clears the bar either. Keep `bge-small`.

Preregistration: `experiments/embedder-precision/PREREGISTRATION-R4.md`, written before any score,
with two amendments that change no threshold. Raw results: `results/eval_r4.json`,
`results/twin_counterfactual_r4.json`. Reproduce (~5 min, most of it downloading and embedding):

```
cd experiments/embedder-precision
../../.venv/bin/python eval_v2.py --out results/eval_r4.json
../../.venv/bin/python twin_counterfactual.py --r4
../../.venv/bin/python r4_report.py
```

## The instrument, briefly

It is the round-2/3 harness unchanged (`experiments/embedder-precision/README.md`). There are 192
prompts, written without reading the 64 memory stubs they target, with graded labels. The headline is
useful-recall@5, the share of prompts with a primary memory among the five a push injects.
Confidence intervals come from a paired cluster bootstrap over stubs. The deciding contrast is
**candidate hybrid − shipped hybrid**, BM25 fused by RRF at k=60, depth 50. That hybrid is what
ships, and Q2 has already measured fusion erasing a dense-only gain.

**The rerun reproduced every round-3 figure bit-identically**: 72 results and 60 contrasts, plus the
identifier instrument's four existing models. So the new rows sit on the same instrument, not on a
drifted copy.

## Results — blind set, depth 50

| Arm | Dense alone: recall@5 | Dense alone: MRR@10 | Hybrid: recall@5 | Hybrid: MRR@10 |
|---|---|---|---|---|
| bge-small, shipped (quantized) | 0.8958 | 0.7806 | **0.9375** | 0.8147 |
| bge-small, fp32 | 0.8958 | 0.7806 | 0.9375 | 0.8147 |
| granite-30m | 0.9062 | 0.8026 | 0.9323 | 0.8170 |
| e5-small-v2 | 0.8854 | 0.7768 | 0.9115 | 0.7922 |
| granite-125m (768-dim) | **0.9635** | **0.8324** | 0.9375 | 0.8355 |

| Contrast (useful-recall@5) | Point | 95% CI | Prompts up / down |
|---|---|---|---|
| **granite-30m hybrid − shipped** (deciding) | −0.0052 | [−0.0365, +0.0208] | 2 / 3 |
| **e5-small hybrid − shipped** (deciding) | −0.0260 | [−0.0573, 0.0] | 1 / 6 |
| **granite-125m hybrid − shipped** (deciding) | 0.0000 | [−0.0469, +0.0417] | 5 / 5 |
| granite-30m dense − shipped dense | +0.0104 | [−0.0365, +0.0573] | |
| granite-125m dense − shipped dense | **+0.0677** | **[+0.0208, +0.1250]** | |
| fp32 − quantized bge-small, dense and hybrid | 0.0000 | [0, 0] | 0 / 0 |

**Identifier discrimination** (ratio of means; ≥ 0.75 usable, ≤ 0.35 a real weakness; a model
difference needs ≥ +0.15). All controls validated for every model: identity margin 0.0000, exact-control
win rate 1.00.

| Probe | bge-small shipped | bge-small fp32 | granite-30m | e5-small | granite-125m |
|---|---|---|---|---|---|
| bare | 0.2045 | 0.2044 | 0.2169 | 0.2417 | 0.1647 |
| carrier | 0.2096 | 0.2095 | 0.2013 | 0.2392 | 0.1561 |

The largest difference from the incumbent is +0.037 (e5, bare), a quarter of the bar. No bootstrap is
needed to call the gate: every candidate fails it on the point estimate alone.

## What this settles and what it adds

1. **Keep `bge-small-en-v1.5`.** IBM's published margin does not transfer. On the deployed hybrid,
   granite-30m is indistinguishable from the incumbent, and it would cost a new pin, a re-embed of
   every store and a tokenizer change in `encoder.py`: granite is RoBERTa BPE and `encoder.py` counts
   with bge's WordPiece.
2. **Q2 now has a second, independent instance.** granite-125m's dense-only gain is significant, at
   +0.0677 useful-recall@5 with a CI excluding 0 — the same size as bge-large's MRR@10 +0.0705 in
   round 2. The hybrid **erases it completely** (0.0000, 5 up / 5 down). Two different model families
   now show one structure: a better dense arm buys nothing through unweighted two-arm RRF on this
   corpus. The embedder is not where the next gain is. The fusion scheme is, if anywhere, and that
   is a D5 design change rather than a model swap.
3. **Round 2's threat 5 is closed on the incumbent's side.** The shipped quantized bge-small and
   BAAI's fp32 export give **identical** task metrics to four decimals and identical DIs to ±0.0001.
   Quantization is not what separated bge-small from bge-large in round 2, and it is not a reason to
   ship an fp32 artifact.
4. **Q8's identifier ceiling holds across two more families.** DI is now 0.16–0.24 over seven
   artifacts. The largest model, granite-125m, has the *lowest* DI: its exact-control margin
   shrinks more than its near-miss margin does, consistent with a more anisotropic space in which
   everything is closer together (mean gold cosine 0.91 against bge-small's 0.76).

## Threats to validity

- **One corpus, synthetic stubs**, authored for round 2. The published CoIR gain is on
  StackOverflow-QA, which is not this distribution. That the two disagree is the finding, not a
  defect of either, but this corpus cannot speak for a knowledge-index corpus of long Markdown. The
  knowledge-index instruments (M25 `heading`, M26 real questions) were **not** run, by R4.5's rule:
  no candidate passed the memory-store gate, so nothing they showed could change the decision.
- **Three candidates, three chances.** Nothing came close enough for multiplicity to matter.
- **granite's prefix.** The model card prescribes no query instruction and none was used. A
  prefix-tuned variant was not tried; that would be tuning a candidate after seeing its score, which
  §7 forbids.
- **No latency figures** (amendment A2). Irrelevant to this verdict. It would matter to any future
  candidate that passes on quality.
