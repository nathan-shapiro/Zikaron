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
- `retrieve` — the algorithm every consumer runs, composable into a transaction a caller holds.
- `block` — the injected block's exact text.
- `reads` — `search` and `surface`: one transaction each, with the instrumentation inside it.

Two things this package deliberately does not do. It **does not tune fusion**: arm weighting is the
largest known quality lever and it is a measurement rather than a judgement, so `rrf_k`,
`fusion_depth` and `chunk_overfetch` stay config keys and the pass stays a sweep — which is safe to
defer precisely because none of them invalidates a stored vector. And it **does not rerank** on the
push path (D23), because the measured latency curve leaves one affordable point there and reranking
five candidates is operationally pointless; the pull path is explicitly not rejected.

The five consumers are here; three of them are not. Dedup, consolidation anchoring and orphan
adjacency each name themselves in `eligibility.Consumer` and call `retrieve.retrieve` with an
internal query — the mechanism is built here, and the verbs that use it belong to their own layers.
"""
