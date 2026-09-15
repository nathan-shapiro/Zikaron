# Which quantity orders the groups — measured on a three-KB corpus

**Date:** 2026-09-15. **Harness:** `spikes/spike_group_ordering.py`, re-runnable
(`.venv/bin/python spikes/spike_group_ordering.py`; document vectors cache to
`/tmp/zk-spike-c-embeddings.npz`, so a re-run after the first is ~30 s).
**Consumer:** `design/knowledge-index.md` §7.2 and §16 open question 2. **Milestone:** M19 spike C.
**Environment:** `bge-small-en-v1.5` (D20), `rrf_k = 60`, `fusion_depth = 50`, per-file cap 2,
group size 5 — every parameter at its shipped default. **Result 3 varies `fusion_depth` deliberately**;
everything else stays at these values throughout.

## The question

§7.2 orders result groups by **best dense cosine** within the group, and names its own blind spot:
a group whose top result is a **pure lexical hit** — an exact identifier, an error string, a flag
name — is invisible to that signal, and that is exactly the code-knowledge case. The candidate fix it
names but does not adopt is ordering by **best fused contribution**, rank-derived and cross-KB-safe by
the same argument that makes RRF rank-based.

This is a **code-shape question, not a parameter question**: `rrf_k` and `fusion_depth` are `meta`
keys and can be swept later, but which quantity orders the groups is a branch in the ranking path.

## Method

Three real corpora, deliberately heterogeneous:

| KB | contents | chunks | files | words |
|---|---|---|---|---|
| `zikaron_code` | this project's `zikaron/**/*.py` | 443 | 103 | 139,011 |
| `amazonq_code` | `amazon-q-developer-cli/crates/chat-cli/src/**/*.rs` | 494 | 146 | 146,999 |
| `amazonq_docs` | that project's markdown | 41 | 18 | 11,524 |

**Queries and ground truth are mechanical, not authored.** An identifier is admitted to the query set
only if it occurs **≥ 3 times in exactly one KB and zero times in the other two**; 8 are sampled per
KB at a fixed seed. The correct group is then the KB that contains it, by construction rather than by
judgement. Three families:

1. **identifier (bare)** — the identifier alone. This is §7.2's stated case.
2. **identifier (in prose)** — `"what does <identifier> do and where is it used"`. Same ground truth,
   ordinary words added.
3. **prose (unique tokens masked)** — a sampled 12–35-word span from a file, with the lexical giveaway
   removed. Precisely, and stated as the instrument does it rather than as the intent: a word is
   dropped if it **contains, as a substring, any token unique to any of the three KBs** — not merely
   if it *is* a token unique to *its own* KB. That masks strictly more than intended, in the
   conservative direction (it removes lexical signal the true KB could have used), and it is why some
   sampled spans read as fragments. Ground truth is the span's source KB.

72 queries in total. Each KB is retrieved independently — dense (exact cosine) and lexical (real FTS5
`bm25()`) each cut to `fusion_depth`, fused by `Σ 1/(rrf_k + rank)`, group assembled under §7.3's
per-file cap — and the three groups are then ordered three ways: by best cosine, by best fused
contribution, and by fused with cosine breaking ties.

## Result 1 — the hypothesised failure did not occur once

> **The true KB's best chunk was a lexical-only hit 0 times in 72.** In all 72, it was found by
> **both** arms.

At the shipped `fusion_depth = 50` against these corpora, the dense arm returns the top ~11% of every
KB, which is deep enough that nothing the lexical arm found was outside it. **That is a property of
the corpus size, not of the design** — see result 3, which is the load-bearing one.

## Result 2 — the candidate fix does not win, and loses outside its own family

| family | n | cosine top-1 | fused top-1 | fused+cosine | paired (cosine vs fused) |
|---|---|---|---|---|---|
| identifier (bare) | 24 | 0.62 | **0.71** | 0.71 | cosine only 4, fused only 6 — **p = 0.75** |
| identifier (in prose) | 24 | **0.75** | 0.54 | 0.54 | cosine only 8, fused only 3 — p = 0.23 |
| prose (masked) | 24 | **0.83** | 0.46 | 0.58 | cosine only 12, fused only 3 — **p = 0.035** |
| **all** | 72 | **0.74** | 0.57 | 0.61 | cosine only 24, fused only 12 — p = 0.065 |

(MRR follows top-1: 0.850 / 0.759 / 0.782 aggregate. Paired test is two-sided exact McNemar on the
discordant pairs.)

**Read honestly, and this is the part not to overstate.** Only the *weakest* family reaches
significance, and it is weakest for two reasons named below. The aggregate trend favours cosine at
p = 0.065, which is not a result. And in family 1 — **the family §7.2's blind spot argument is
about** — the fused ordering's apparent +0.09 is **four queries against six, p = 0.75**: no evidence
of a difference in the one place the fix was proposed for.

So on this evidence the fix is not merely unproven; there is **no family in which it is measurably
better**, and two in which it is directionally worse.

## Result 3 — the sensitivity sweep, which is the decisive measurement

Lowering `fusion_depth` approximates a **larger corpus at the same absolute arm depth**: it is the
ratio of arm depth to corpus size that governs whether a lexical hit can land outside the dense arm's
reach. §16 estimates a real KB at ~22,800 chunks, where depth 50 is **0.2%** of the corpus rather than
the 11% these corpora give it.

| `fusion_depth` | cosine top-1 | fused top-1 | fused+cosine | true-KB top lexical-only | any-KB top lexical-only | queries with a fused tie at the top | with a cosine tie | groups with **no** dense-found chunk |
|---|---|---|---|---|---|---|---|---|
| 50 (shipped) | 0.74 | 0.57 | 0.61 | 0/72 | 0/216 | 7/72 | 0/72 | **0/216** |
| 20 | 0.72 | 0.57 | 0.61 | 1/72 | 8/216 | 7/72 | 0/72 | **0/216** |
| 10 | 0.75 | 0.56 | 0.60 | 3/72 | 23/216 | 9/72 | 0/72 | **0/216** |
| 5 | 0.76 | 0.51 | 0.58 | 10/72 | 39/216 | 14/72 | 0/72 | **0/216** |
| 3 | 0.76 | **0.38** | 0.58 | 16/72 | 51/216 | **31/72** | 0/72 | **0/216** |

**Two things move together, and they move the wrong way for the candidate fix.** The phenomenon §7.2
worries about **does** appear as the ratio tightens — lexical-only tops go from 0 to 16 of 72, and
from 0 to 51 of 216 groups. And over exactly that range, **cosine ordering gets slightly better
(0.74 → 0.76) while fused ordering collapses (0.57 → 0.38).**

**So the inference §7.2 makes does not hold.** The existence of lexical-only top hits does not imply
that cosine is the wrong *group-ordering* signal — because a group whose *top* chunk is lexical-only
still contains dense-found chunks, and its best cosine is computed from those. The blind spot is real
at the level of the individual chunk and does not propagate to the level of the group.

## Why the fused ordering fails: saturation, measured

Max-RRF's discriminating event is narrow: a group reaches the top value only when **both arms agree
on one chunk**. As soon as a query contains ordinary words, every corpus produces that event.

| family | groups (of 3) whose top chunk both arms found | groups with any lexical match | median fused spread | median cosine spread | ratio |
|---|---|---|---|---|---|
| identifier (bare) | **2** | 2 | 0.01404 | 0.07552 | **5.4×** |
| identifier (in prose) | **3** | 3 | 0.00367 | 0.05855 | **16×** |
| prose (masked) | **3** | 3 | 0.00262 | 0.10446 | **40×** |

Cosine keeps a continuous margin **5–40× wider by family** than fused across the same three groups,
and never ties at the top; fused ties in 1–3 of 24 queries per family at the shipped depth and has a
median of **2–3 distinct values across 3 groups**. Breaking those ties with cosine (`fused+cosine`)
recovers part of the loss in the prose family (0.46 → 0.58) and none of it elsewhere, which is what a
saturated primary key with a good tiebreak looks like.

**Note what is and is not median here**, since the two are easy to merge into one overstated
sentence. What is median is that **all three groups' top chunks are found by both arms** (families 2
and 3), which compresses the keys into a narrow band. An **exact** tie at the top is rarer than that
at the shipped depth — 7 of 72 queries — and becomes common only as depth tightens, 31 of 72 at depth
3. Compression is the mechanism; exact ties are its visible tail.

**One cause is specific to this system rather than to RRF.** `zikaron/core/retrieval/query.py` builds
the lexical side as **`OR` over quoted terms** — a deliberate choice, documented there, because
phrases would drop non-adjacent matches on dotted identifiers and paths. The consequence here is that
any query containing common words matches *something* in every corpus, which is precisely the
saturation above. A different lexical construction would give a different answer, and the finding
should not be quoted as a fact about RRF in general.

## Threats to validity, stated rather than implied

- **n = 72 queries over 3 KBs, one machine, one embedding model.** With three groups, a rank is 1–3
  and one query moves top-1 by 0.042. Only the weakest family clears p = 0.05.
- **Family 3 is the weakest and should not carry the conclusion.** Its masked spans drawn from the two
  code KBs are *code fragments*, not prose, and the dense arm gets a free language-identification
  signal — Python vs Rust vs Markdown — that has nothing to do with relevance and inflates cosine's
  margin there. Family 2 is the clean comparison, and it does not reach significance.
- **The corpora are 20–500× smaller than the design's own KB estimate**, which is what result 3 exists
  to address — but lowering `fusion_depth` only approximates a larger corpus. It does not reproduce
  the BM25 statistics or the dense neighbourhood density of one, so the sweep is a sensitivity
  analysis rather than a simulation.
- **`amazonq_docs` is 41 chunks against 443 and 494.** The size asymmetry is realistic and
  uncontrolled; with `fusion_depth = 50` its dense arm returns the *entire* corpus, so nothing in that
  KB can be lexical-only by construction at that depth.
- **Chunking is spike-grade** — 350 words at line boundaries, not §4.3's paragraph-greedy token
  budget. Dense scoring is exact cosine in numpy rather than through `vec0`; `vec0` brute-forces, so
  the ordering is identical, but the storage path is not what was exercised.
- **The probe omits §8.3's explicit `chunks_vec` lookup, and that omission provably changes nothing
  here.** §8.3 gives a lexical-only chunk such a lookup, calling it *"the only way a group whose hits
  are all lexical gets an ordering key at all"*; the probe instead scores a group by the best cosine
  among its **dense-found** chunks only. Those coincide except in one shape. A lexical-only chunk is by
  definition outside the dense top-`fusion_depth`, so its cosine is at most the depth-th dense cosine,
  which is at most the cosine of *every* dense-found member — so the lookup can raise a group's key
  only if the group has **no dense-found member at all**. That is now counted rather than argued:
  **0 of 216 groups, at every depth in the sweep.** The margins above are therefore the shipped
  design's margins **exactly**, and an earlier revision of this bullet calling them a *lower bound* was
  flattering the result. What the omission does still mean is that this probe says nothing about how
  good a looked-up cosine is on identifier-shaped queries — open question 3, not this one.
- **Exact ties in the fused ordering resolve by KB insertion order, and ties are common precisely
  where the collapse is measured.** `rank_of` sorts with Python's stable sort, so a tie at the top
  falls to the order the KBs were built in (`zikaron_code`, `amazonq_code`, `amazonq_docs`) — a
  deterministic bias, not a coin flip. It binds exactly where the saturation analysis says it should:
  queries with a fused tie at the top rise from **7/72 at depth 50 to 31/72 at depth 3**, over the same
  range where fused top-1 falls 0.57 → 0.38, while cosine ties **0/72 at every depth**. Two things
  bound how much of the collapse this could manufacture rather than measure: ground truth is spread
  across all three KBs by construction — 8 identifiers sampled per KB — so the bias helps and hurts in
  roughly equal measure over the query set; and the `fused+cosine` row, which breaks exactly these ties
  on a signal that never ties, still reaches only 0.58 against cosine's 0.76. **The tie structure is
  part of what is wrong with the fused key rather than an artifact hiding it** — but it is a
  deterministic bias in the instrument, so it is named here rather than left in a reader's head.
- **Reproducibility:** three runs produced byte-identical cosine and fused figures.

## What changes in the design

**K4 stands, with a better reason than it had.** §7.2 keeps best-dense-cosine for group ordering.

1. §7.2 — the blind-spot paragraph is kept (the phenomenon is real and appears as corpora grow) but
   its **inference is corrected twice**. A lexical-only *chunk* does not make the *group* invisible to
   cosine, measured across a 16× depth sweep. And the word **"blind" was already refuted by §8.3 three
   sections away**, which gives exactly such a chunk an explicit `chunks_vec` lookup — so what is at
   stake is the *quality* of that key on identifier-shaped queries (open question 3), not the group's
   absence from the order. Two sections of one document disagreed, and only reading them against each
   other found it.
2. §7.2 — the "candidate fix named rather than adopted" paragraph becomes **named, measured, and
   rejected**, with the saturation mechanism as the reason.
3. §16 open question 2 — closed as a design branch. What remains open is the *within-KB* dense/lexical
   balance, which is open question 3 and a different question.

**M20 is unblocked by this spike**, and no code-shape branch is left undecided.
