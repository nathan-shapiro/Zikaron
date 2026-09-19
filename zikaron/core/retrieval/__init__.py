"""Retrieval: two arms, one fusion, one eligibility predicate, and the block the push path prints.

`design/retrieval.md` is normative for this package and `design/schema.md` invariants 18 and 20 are
what it must hold. The shape of it, lowest layer first:

- `eligibility` — the one predicate and the complete table of per-consumer filters. The only place
  in `core` that writes `active`, `tier` or `superseded_by` into a retrieval `WHERE` clause.
- `query` — construction on both arms, for both kinds of query: quoted-term FTS5 expressions, the
  dense preflight's head truncation, and an internal query's reuse of a stored first-chunk vector.
- `arms` — the dense overfetch loop with its three terminal reasons, and the lexical arm's single
  statement with its two. `ArmOutcome` enforces invariant 20 at construction.
- `ranking` — pure: RRF, the demotion penalties, the five-step total order, the supersession repair.
- `similarity` — `s(X → Y)`, the one directed score all three cosine cutoffs threshold. A read,
  not a ranking: the pool says which rows are candidates, this says whether each clears a floor.
- `retrieve` — the algorithm every consumer runs, composable into a transaction a caller holds.
- `block` — the injected block's exact text.
- `reads` — `search` and `surface`: one transaction each, with the instrumentation inside it.

Two things this package deliberately does not do. It **does not tune fusion**: arm weighting is a
measurement rather than a judgement, so `rrf_k`, `fusion_depth` and `chunk_overfetch` stay config
keys and the pass stays a sweep — which is safe to defer precisely because none of them invalidates
a stored vector.

**"The largest known quality lever" used to stand in that sentence unqualified, and one half of it
has now been measured and did not hold.** Swept over 2,720 chunks of technical prose in the
knowledge index — 252 cells of `rrf_k` by `fusion_depth` by an arm weight — no configuration beat
the shipped one by more than 0.0069 MRR@10 **on the one query family measured valid** (`heading`,
n=150), against a 0.02 bar fixed in advance. **Two scope warnings belong with that number.** The
other three families were measured invalid — their queries are substrings of their own answers, so
they hand the lexical arm the result — and **on the pooled metric the preregistration actually
named, 48 cells cleared every threshold**, the largest by +0.1314. And `rrf_k` is flat only on that
valid family: on exact-phrase queries it is emphatically not, `rrf_k = 10` beating 60 by **0.102**
MRR@10 on one family. **That is not an opposite-optima result** — every family's maximum is at
`k = 10`, the valid one included — so the honest statement is that smaller `k` and smaller depth are
weakly dominant everywhere, with gains large only where one arm is confidently right and about
+0.004 on the valid family, which is under the bar. Nothing moves. `fusion_depth` is
flat-to-slightly-negative across 40-fold on the shipped slice, and the optimal weight sat on a broad
plateau containing the unweighted fusion that ships. `research/m25-fusion-sweep.md`.
**What that does not touch is the claim the phrase came from**, which is `FINDINGS.md` open question
2: on the *memory* store's 187-record benchmark, unweighted RRF erased a dense-model improvement of
+0.0705 MRR@10. That is a different corpus, a different scale, and a different question — an
embedder upgrade rather than a parameter — so it is neither replicated nor refuted here and stays
open. The phrase is removed because it was stated of fusion tuning in general and is now known to
be false of at least one real corpus, not because the finding behind it went away.

And it **does not rerank** on the
push path (D23), because the measured latency curve leaves one affordable point there and reranking
five candidates is operationally pointless; the pull path is explicitly not rejected.

The five consumers are here; three of them are not. Dedup, consolidation anchoring and orphan
adjacency each name themselves in `eligibility.Consumer` and call `retrieve.retrieve` with an
internal query — the mechanism is built here, and the verbs that use it belong to their own layers.
"""
