# Cross-KB ranking: what SQLite actually permits, measured

**Date:** 2026-09-14. **Harnesses:** `spikes/spike_attach_limits.py`, `spikes/spike_attach_cross_kb.py`
(both re-runnable against the project venv). **Occasion:** the operator's design for a file-indexing
sibling system stores **one SQLite file per knowledge base**, so a KB is deleted by unlinking the file
rather than by a filtered `DELETE`. That raises the question this note answers: how do you rank across
several database files?

## Measured

| # | Question | Result |
|---|---|---|
| 1 | `ATTACH` limit | **10**, hard. Attaching the 11th raises `too many attached databases - max 10` |
| 2 | FTS5 `MATCH` on an attached DB | **works** |
| 3 | `bm25()` on an attached DB | **works** |
| 4 | `vec0` KNN on an attached DB | **works** |
| 5 | `UNION ALL` across two attached `vec0` tables | **works**, ordering by `distance` is meaningful |
| 6 | `UNION ALL` across two attached FTS5 tables **sharing a table name** | **fails** — `no such column: kbb.chunks` |
| 7 | Same, with a table **alias** (`FROM kbb.chunks d WHERE d MATCH …`) | **fails** — `no such column: d`. FTS5's `MATCH` requires the real table name on its left; it cannot be aliased or schema-qualified |
| 8 | Same, with **unique table names per KB** (`chunks_a`, `chunks_b`) | **works** |

## The finding that decides the design

**BM25 is not comparable across corpora, and the failure is severe rather than marginal.** Two corpora
of **identical size** (200 documents each), containing the **same matching sentence** — "reciprocal
rank fusion explained here" — queried for `fusion`:

| corpus | documents | matching | best `bm25()` |
|---|---|---|---|
| `kb_a` | 200 | **1** | **−4.20678** |
| `kb_b` | 200 | **100** | **−0.00000** |

Lower is better in FTS5's `bm25()`, so `kb_b`'s rows are scored as **worthless** — despite containing
exactly the text searched for. The cause is document frequency: a term that is common *within its own
KB* earns an idf near zero there. **This is not a corpus-size effect** — the corpora are the same size.

**Consequence: sorting pooled `bm25()` values across KBs is wrong, and wrong in a way that
systematically buries the most on-topic documents** in whichever KB is most about the query's subject.
A KB dedicated to retrieval would rank *last* for the query "fusion".

Cosine/L2 distance has no such property — it is a function of two vectors and nothing else — so the
dense arm pools across KBs correctly and the lexical arm does not.

## What follows

1. **Do not use `ATTACH`.** The 10-database ceiling means a single-query path cannot be relied on past
   9 KBs, so the implementation needs a per-KB query path regardless; having both is two code paths
   where one suffices. Query each KB independently and merge in the service.
2. **Dense arm: pool globally by distance.** Valid by construction.
3. **Lexical arm: rank within each KB, then merge by rank, never by score.** RRF is rank-based, so
   once a global lexical ordering exists by any defensible rule, fusion proceeds unchanged.
4. **The merge rule for per-KB lexical ranks is a real open choice** — round-robin interleave (equal
   footing per KB, biased toward small KBs) versus size-weighted. Unmeasured; needs a decision.
5. **If `ATTACH` is ever used anyway, FTS5 table names must be unique per KB** (finding 8). A shared
   name is not merely awkward, it is unqueryable.
