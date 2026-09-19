# M25 fusion sweep — preregistration

**Written 2026-09-18, before the corpus finished building and before any cell was scored.** That
ordering is the point: a 252-cell grid produces a best cell whatever the truth is, and choosing
which number to believe after seeing them all is how a sweep manufactures a result. Everything
below — metric, families, thresholds, and the conditions under which we change nothing — is fixed
here and is not to be revised in the light of the numbers. If it turns out to need revising, the
revision is recorded as a deviation with its reason, in place, and the original stays.

## The question

`rrf_k = 60` and `fusion_depth = 50` were tuned against a **187-record** memory benchmark. A
knowledge base is ~~two orders of magnitude larger~~ **1.2 orders larger, as built — 2,720 chunks
against 187, and an order of magnitude *short* of the ~22,800 §16 item 1 poses the question at.
Annotated in place 2026-09-18; the note's own "~15×" was the honest figure and this line was not.**
`knowledge-index.md` §16 item 1 says the sweep
"must run before a ranking here is trusted"; item 3 asks the separate question of whether the
**dense/lexical balance** is right, which unweighted RRF has never tested because arm weighting has
never been implemented.

Three parameters, all applied at **search** time, so one build serves the whole grid:

- `rrf_k` — the RRF denominator offset.
- `fusion_depth` — how deep each arm contributes.
- **arm weight** `w` — not implemented in the product. Fused score becomes
  `w · 1/(k + rank_dense) + (1 − w) · 1/(k + rank_lexical)`, with `w = 0.5` reproducing the shipped
  unweighted sum up to a constant factor, which does not change order.

## Corpus

`cockroachdb/cockroach` `docs/RFCS/` — 188 files, 4,121,360 bytes, median file 17,080 bytes, largest
181,756. *(As planned. **The build admitted 198 files / 4,135,684 bytes**: the harness passed no
`include` glob, so the default took 9 `.puml` files and an `.svg` too — see the note's §Corpus.)*
Public, somebody else's, and chosen because large badly-addressed documents are where
retrieval has work to do: the filename names the RFC's subject and nothing names where inside it an
answer sits. Indexed at the shipped defaults with `git_mode = off`.

**Stated in advance as a limit on generality:** this is one corpus, of technical design prose, in
English. Nothing here licenses a claim about source code, and §16 item 3's question is explicitly
about code. A result on this corpus is evidence about *this shape of corpus*.

## The oracle, and why it is mechanical

No human labels anything and no agent authors a relevance judgement. Ground truth comes from the
corpus's own structure, which is what makes the query set reproducible and unbiased between the two
arms — an authored query set would be written in whatever vocabulary its author had just read.

Three families. **Each carries a dial that moves lexical signal**, which is what makes them able to
separate the arms rather than merely score them:

1. **`verbatim`** — a contiguous 15-word span lifted from one chunk; truth is that chunk. Lexically
   trivial by construction. This is an **anchor, not evidence**: any sane configuration scores near
   the ceiling, and its job is to catch a broken harness.
2. **`masked`** — the same spans with their most distinctive terms removed, at two rates (half, and
   all, of the terms whose corpus document-frequency is below the span's median). ~~As masking rises
   the lexical arm degrades by construction and the dense arm must carry the query. **This is the
   instrument for arm weighting.**~~
   **— REFUTED BY MEASUREMENT, `research/m25-fusion-sweep.md`.** Masking removes *terms from the
   query*; it does not make the surviving terms any less of an exact match in the target. Measured
   over all 150 queries per family, the fraction of query terms appearing verbatim in the true chunk
   is **0.9975 to 1.0000 at every masking rate, and never below 0.70 on any single query** —
   against 0.5950 for `heading`. *(Those figures read "1.000, minimum included / 0.571" until the
   overlap was tokenized as the lexical arm tokenizes rather than as this harness did; round 2
   finding 7. The refutation is unchanged — it is the tokenizer that moved, not the conclusion.)*
   So all three
   span families hand the lexical arm a perfect term match by construction, none of them can inform
   arm balance, and the "instrument for arm weighting" was the one thing this family could not be.
   **`heading` is the only valid family**, and the conclusion rests on it alone. Kept in place
   because the wrongness is the finding: the dial felt like it removed lexical signal and removed
   only its rare-term component, and what caught it was measuring the instrument rather than
   reasoning about it.
3. **`heading`** — a markdown section heading as the query; truth is the chunks of that section
   **excluding the chunk that contains the heading line itself**. The exclusion is what stops it
   being a third verbatim family. This is the most task-like family — a short natural-language
   phrase against body prose that does not repeat it — and it is the one the conclusion should
   lean on.

## Metric

**MRR@10 over the fused pool**, per family, where the pool is the fused ranking before the
per-file cap and `limit_per_kb` are applied. Reported alongside:

- **hit@5** — whether a true chunk is in the top five, which is what a caller at the shipped
  `limit_per_kb` would actually see.
- the same two **after** the shipped `max_chunks_per_file = 2` cap, reported separately, because the
  cap can evict a true chunk that ranking placed correctly and that is a different failure.

Pooled MRR@10 across families is reported but is **not** the decision metric on its own; a gain
confined to `verbatim` is a harness artefact, not a result.

## The grid

- `rrf_k ∈ {10, 20, 40, 60, 100, 200}`
- `fusion_depth ∈ {10, 25, 50, 100, 200, 400}`
- `w ∈ {0.0, 0.25, 0.4, 0.5, 0.6, 0.75, 1.0}`

252 cells. Both arms are fetched **once per query at depth 400** and truncated for smaller depths.
That is exact rather than an approximation: the dense arm is `vec0`, which brute-forces, so its
top-400 prefix is its top-*d* for every `d ≤ 400`; the lexical arm is `ORDER BY bm25 LIMIT`, whose
prefix property is the same. **Recorded because if either ever stopped being exhaustive this
equivalence would break silently.**

At `w = 0` and `w = 1` the fusion is single-arm, so `rrf_k` cannot change the order. Any apparent
`rrf_k` effect in those rows is a reporting bug and is to be treated as one.

## Decision thresholds — fixed before any number exists

> **RECORDED DEVIATION, entered 2026-09-18 after review round 1 and after the data was seen.**
> Thresholds 1, 2 and 4 below are defined on **pooled** MRR@10. The note applies them to the
> **`heading` family alone**, because three of the four families were measured invalid — they hand
> the lexical arm a verbatim copy of the answer — and a pooled metric that is 75% invalid by
> construction cannot decide anything. **That re-scoping is post-hoc and it is decisive**: on the
> pooled quantity as written, **48 cells clear all four thresholds**, with gains to +0.1314 and
> bootstrap intervals excluding zero. On `heading` none does.
> **The threshold *value* was fixed in advance and never moved; the quantity it applies to did.**
> The original text stands below unedited, because the whole use of a preregistration is destroyed
> if it is quietly rewritten to match its outcome.
> **This document is also internally inconsistent and was so before the run**: §Metric says pooled
> "is **not** the decision metric on its own", while threshold 1 makes it exactly that. The note
> inherited that inconsistency and resolved it silently; it is named here instead.
> **What should have been preregistered and was not: what makes a family admissible.** Had that
> been fixed in advance — say, *a family is admissible only if its queries are not substrings of
> their own answers* — the pooled metric would have contained one family from the start and no
> post-hoc re-scoping would have been needed.

A shipped default moves **only** if all four hold:

1. **Effect size:** pooled MRR@10 improves by **≥ 0.02 absolute** over the shipped cell
   (`rrf_k = 60`, `fusion_depth = 50`, `w = 0.5`).
2. **Significance:** a paired bootstrap over queries (10,000 resamples) gives a 95% CI on the
   difference that **excludes 0**.
3. **No family regresses** by more than **0.01** absolute.
4. **The gain is not confined to `verbatim`** — it must appear in `heading` or `masked`.

**If no cell clears that bar, the finding is that the defaults survive contact with a corpus ~~two
orders of magnitude~~ *(1.2 orders, as built — the same correction as line 13, which round 1 flagged
at both sites and round 2 found applied to only one)* larger than the one they were chosen on**,
§16 item 1 closes positive, and
nothing ships. That is a real and publishable outcome, and naming it here is deliberate: a sweep
with no acceptable null result will always find something.

**Arm weighting specifically** is built as a config key only if a single `w ≠ 0.5` clears the bar
**and** is stable in direction across `heading` and `masked`. A weight that is optimal only at one
masking rate is evidence that the right weight is query-dependent, which is an argument against a
global constant rather than for a particular value.

## Threats named in advance

- **One corpus, one language, one embedding model.** No claim about code follows.
- **`masked` is synthetic.** Removing a span's rarest terms produces text no human would type. It is
  a controlled degradation of lexical signal, not a sample of real queries.
- **`heading` truth is generous** — any chunk of the section counts — so its absolute numbers are
  higher than a single-chunk oracle would give. Only differences between cells are being read.
- **Chunks from one file resemble each other**, so a near-miss inside the right file scores zero on
  this oracle while being useful to a reader. The metric therefore understates practical quality,
  equally across cells.
- **No agent's real query is in this set.** The strongest available answer to "does search return
  what was needed" is the live install, which is track A, and it is not this measurement.
