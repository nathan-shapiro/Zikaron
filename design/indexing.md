# Indexing and chunking — v0 spec

> Settled with the user 2026-08-01. Summarized as **D28** in `FINDINGS.md`; this is the build contract.
> **Scope: the memory store only.** The knowledge index chunks by a different contract — file-oriented,
> carrying line ranges, with no gap and no overlap — in `design/knowledge-index.md` §4.3.
> Evidence for the surrounding retrieval choices (D20–D25) is in `research/embedder-benchmark-results.md`.

## Why chunk at all
`bge-small-en-v1.5` silently truncates past 512 WordPiece tokens, and D21 embeds gist + content, so long
memories lose their tail from the dense index with no error. Two further pressures:

- **Memories grow through amendment.** D6 and D11 have the agent rewrite `content` in full, so the
  most-repaired — i.e. most useful — records accrete and are the likeliest to overflow.
- **We have no measured evidence that truncation is benign.** The benchmark's "BM25 rescues over-length
  records" claim was withdrawn: all six over-length fixtures shared one near-identical template, so it was
  one case, not six.

Chunking was chosen over single-vector-plus-truncation on **migration cost**, not on measured retrieval
gain. The `vec0` shape change is free against an empty store and a silent-corruption risk against a
populated one (D20: same-dimension vector-space changes corrupt `vec0` with no schema protection).
Parameterized chunking is a **superset** of the single-vector design — set `chunk_max_tokens` high and it
degenerates to one vector per memory — so a future long-context model swap makes chunks large rather than
making this code dead.

## Chunk construction

The budget is computed against the **final embedded sequence**, not against content alone. The original spec
filled content to `chunk_max_tokens` and *then* prepended the gist, so a 100-token gist plus a 450-token
chunk exceeded BGE's 512 cap and fastembed truncated it silently — reintroducing exactly the failure
chunking exists to prevent.

**The tokenizer is the deployed model's own.** Counting uses the same `bge-small-en-v1.5` WordPiece
tokenizer fastembed will use at embed time, obtained from the same artifact, including its special tokens
(`[CLS]`, `[SEP]`) and its `model_max_length` of 512. Counting with anything else — a regex, a word count,
another model's tokenizer — makes the guarantee approximate, and an approximate guarantee here is worth
nothing because the failure is silent.

**The counting tokenizer must have truncation disabled, and that is not a detail.** Measured on the deployed
artifact: fastembed's own `Tokenizer` instance carries `truncation.max_length = 512`, so asking *it* for a
count returns **512 for a 1600-token text**. A preflight counting through it would find every over-length
paragraph to be exactly at the cap, never hard-split, never set `truncated`, and hand fastembed the whole
paragraph to truncate silently — reintroducing the precise failure this document exists to prevent, with
every recorded number looking healthy. So the counting tokenizer is an **independent instance built from the
same artifact** with truncation switched off, and the embedding path's own tokenizer is left exactly as
fastembed configured it. The cap is read off the deployed tokenizer's truncation config *before* that copy is
made, and `n_special` is **measured** — encode one word with and without special tokens and subtract —
rather than assumed to be 2, since both are properties of the artifact and D20 keeps the artifact
configurable.

**`separator_tokens` is 1 by contract and measures 0 on the deployed model.** A bare `\n` is whitespace,
which BGE's WordPiece pre-tokenizer discards, so the separator's true cost there is zero tokens. The formula
keeps the term at 1 regardless: the error is then one token of unused budget rather than one token of
overflow, and step 7's assertion is a bug-catcher rather than a routine path, so it must not be what
discovers a future model whose separator does tokenize.

**Preflight, per memory:**

1. Count the gist. Over `gist_max_tokens` (default **64**) ⇒ **reject the write** with the `bounds` error
   naming the limit and the actual count. This is the one place a write is refused, and it is safe to refuse:
   the agent still holds its own text and can shorten a gist in the same turn, whereas a silently truncated
   embedding is undiscoverable. Content is never refused for length.
2. Compute the per-chunk content budget:
   `content_budget = 512 − n_special − gist_tokens − separator_tokens`, then
   `effective_budget = min(chunk_max_tokens, content_budget)`.
   With the defaults — 512 cap, 2 specials, 64-token gist ceiling, 1 separator — the floor is 445, so
   `chunk_max_tokens = 450` is *usually* the binding constraint and the gist ceiling is what keeps it so.
3. Split `content` on blank lines into paragraphs.
4. Greedily merge adjacent paragraphs while the running total stays within `effective_budget`.
5. Hard-split, **on token boundaries**, only a single paragraph that alone exceeds the budget.
6. **No overlap.**
7. **Prepend the gist** (plus one `\n` separator) to every chunk, then assert the assembled sequence
   tokenizes to ≤ 512 including specials. A failed assertion is a bug, not a truncation: it raises
   `index_failed` and rolls back.
8. Empty or whitespace-only content is invalid at the tool boundary (`schema.md` §Bounds), so
   `zikaron_memory_remember` rejects it rather than producing a memory with zero vectors. If content ever became
   admissible, the defined behaviour is exactly one gist-only chunk — invariant 12 requires every active
   memory to have at least one.

**`truncated` is set by this preflight**, and only by it: it records that step 5 hard-split a paragraph. It
is never inferred from fastembed, which does not report truncation at all. That is what makes it a usable
canary rather than a hopeful comment.

**There is a matching preflight on the query side, and it resolves differently.** A user prompt or a
group-gist concatenation can also exceed 512 tokens, and `retrieval.md` §"Query construction" budgets it with
this same tokenizer — but **truncates rather than rejects**, because a write can be handed back to an agent
that still holds its text while refusing a user's prompt would mean refusing to retrieve. The asymmetry is
deliberate and is stated in both places so neither reads as an oversight. What both halves share is that no
truncation is ever silent: the write side raises, the read side records `query_truncated`.

Rationale for the boundaries themselves. Agent-authored content has real structure — problem, symptom, fix,
caveat — and fixed token windows cut across it; paragraph boundaries follow author intent, and for the common
short memory this yields exactly one chunk. Overlap is rejected because near-duplicate chunks both retrieve
and D12 has only five injected slots to spend. Gist-prepending is the load-bearing detail: a bare chunk is an
orphan ("run `make clean` first" with no indication of what it concerns), and prepending restores topic
framing for a handful of tokens while preserving D21's measured gist+content result *at chunk level* rather
than quietly reverting part of the store to content-only.

## Storage
`vec0` keyed by `(memory_uuid, part_index)`. Per part, record:

| Field | Purpose |
|---|---|
| `embed_model` | forces full reindex on model change (D20) |
| `embed_dim` | guards the fixed-dimension `vec0` contract |
| `token_count` | lets us measure the real length distribution once real memories exist |
| `truncated` | canary, set **only** by the preflight's hard-split step — never inferred from fastembed, which reports nothing |

**Both counts are of `content` alone, and `part_index` is 0-based.** Three things an earlier draft left to be
inferred, stated because two conforming implementations could have disagreed on all three:

- **`memory.token_count` and the `remember`/`amend` event's `detail.token_count` count `content`** — not the
  gist, not the separator, not the special tokens. `gist_tokens` is a sibling field of the same event, so a
  `token_count` that included the gist would double-count it and neither the write-size distribution nor the
  gist budget could be read off the pair. The `memory` column is that quantity for the row as it now stands;
  the event field is that quantity per write. Same measurement, two lifetimes, exactly as the column comment
  in `schema.md` says.
- **`memory_chunk.token_count` counts that chunk's own slice of `content`** — the quantity `effective_budget`
  bounds — and not the assembled, gist-prepended sequence that was embedded. Nothing is lost: the assembled
  length is `gist_tokens + separator_tokens + token_count + n_special`, and `gist_tokens` is recorded per
  write in the event. Recording the slice is what makes the column a measurement of the chunker against its
  own parameter, which is what open question 3 wants it for.
- **`part_index` is 0-based**, so a memory's first chunk — the one every internal query reuses as its dense
  side (`retrieval.md` §"Two kinds of query") — is `part_index = 0`. Contrast consolidation's deliberately
  1-based `shard: {index, of}`, which is 1-based because it is *shown to the consolidator* and an unsplit
  group reads better as `{1, 1}` than as a third convention. Chunk parts are shown to nobody
  (§"MCP surface"), so their only consumer is code, where 0 is the ordinary first index and matches the
  position in the list the preflight returns.

**Vectors are L2-normalized by the write path itself**, not taken on trust from the embedder. `retrieval.md`
states the corpus is normalized at write time, and the three cosine cutoffs' arithmetic (`cos = 1 − d²/2`) is
true only of unit vectors. Measured: the deployed `bge-small` already returns unit vectors through fastembed,
so today this is a no-op — which is exactly why the guarantee has to be ours rather than inherited. D20 keeps
the model a config key, and a future model returning unnormalized vectors would otherwise invalidate every
threshold in the corpus with no error raised anywhere. A zero-norm vector cannot be normalized and is
`index_failed`, never a silent divide.

## Ranking
- Memory score = **`max`** over its chunk scores — which, in the metric the code actually handles, is
  **`min` over chunk distances**, because `vec0` KNN returns a distance where lower is better. Same
  operation, opposite sign. Stated explicitly because reading "max" literally against a distance column
  inverts the ranking, and the full algorithm (overfetch, eligibility, stopping condition) is in
  `design/retrieval.md` §"One eligibility predicate, one ranking algorithm".
- **Dedup at memory level is mandatory**, not an optimization: without it a five-chunk memory can occupy
  all five injected slots.
- `max` over `sum` because summing rewards length, which under D6's full-rewrite amendment would
  systematically favour the most-accreted records — the wrong incentive.

## FTS5 stays unchunked
Lexical indexing covers the **whole record**. BM25 already applies document-length normalization, so
chunking the lexical side is redundant work against a mechanism that is already correct. This asymmetry is
easy to break by reflex — chunk the dense side only.

## MCP surface: chunking is invisible
The push path injects gists (D12/D13); the pull path returns whole `content`. No tool signature mentions
chunks and the agent never reasons about parts, which also keeps the tool-call count down. Deliberately
rejected for v0: surfacing *which* chunk matched as a triage aid — it would complicate D13 for unproven
gain.

## Implementation constraints

- **Every *logical* mutation is one transaction**, not only `amend`. That is `remember`,
  `amend`, `retire`, `merge`, both forms of `promote`, and `discard` — see `schema.md` invariant 2, which
  is the authoritative statement and is worded exactly that way.
  *(This bullet read "every mutation that **touches indexed prose**", which is a narrower predicate
  than invariant 2's and false of three of the seven verbs it lists: `retire` touches no index —
  this document says so under §"`retire` touches no index", and `writes.py` opens with
  "Two verbs, not three" —
  `discard` "runs no chunking preflight and touches no index", and `promote`'s in-place form
  changes no prose. The list was widened to all seven while the narrow predicate stayed attached to
  it.)* Inside it: the `memory` row, the `version` bump, and — for the four that do touch indexed
  prose — explicit `memory_fts`
  maintenance, chunk and vector maintenance, receipts, and the events.
- **The row-level layer therefore emits no `remember`/`amend` event**, which follows from the rule
  above rather than being an omission in it. Those two kinds carry `token_count`, `gist_tokens`,
  `n_chunks` and `truncated` — outputs of the chunking preflight — and `schema.md`'s nullability
  table does not list them as nullable for these two kinds, unlike `merge`/`promote`, where a
  non-authoring row genuinely has none. An authoring write always has real prose, so those fields
  are meant to be populated, and `core/records/` cannot produce them honestly: it has neither
  tokenizer nor model. The indexing layer wraps `create`/`amend` in the **same** transaction and
  emits the composed event there. `retire` and `fetch` emit their own, neither naming a memory's
  size.
- **So each row-level verb is a thin, transaction-owning wrapper around a
  `<verb>_within_transaction` core** that assumes an already-open transaction and neither commits
  nor rolls back. A composing caller calls the neutral form directly, inside its own wider `BEGIN`
  covering the chunking writes and the composed event; calling the wrapper instead would raise on a
  nested `BEGIN`. `core/indexing/writes.py` exposes the same convention to the layer above it.
- **Delete vectors before chunks.** `memory_vec` is a virtual table with no foreign key to
  `memory_chunk`, so chunks-first would orphan vectors if the sequence were interrupted. The reverse
  order fails safe: an orphaned *chunk* row is detectable and repairable; an orphaned vector is a silent
  false positive in retrieval.
- ~~**A `tier` flip rewrites the index too.**~~ **A `tier` flip touches the index not at all.**
  `promote`'s in-place form changes no prose, so its chunks are unchanged:
  `consolidation/verbs.py` routes it to `_apply_in_place_promote`, which calls `records.apply_tier`
  and never `writes.reindex_rewrite`, since `memory_fts` indexes `gist` and `content` only and
  `tier` appears in neither index. It still bumps `version` in the same transaction, and if the
  consolidator supplied different prose it is not an in-place flip at all (see `architecture.md`,
  which decides the form from the payload rather than guessing).
- **Retire (D16) leaves chunks in place**; eligibility excludes or demotes at query time, matching
  `~/Memory`'s soft-retire contract, and it is what keeps superseded rows retrievable under D25.
- **Full reindex is build-and-swap, or the store is unavailable while it runs** (`schema.md` invariant 3).
  D20's forced-reindex case includes an `embed_dim` change, which `vec0` cannot do in place — the table is
  dropped and recreated, so that case *must* take the unavailable form.
- `chunk_max_tokens` default **450**; `gist_max_tokens` default **64**. The relationship between them and
  the 512 cap is arithmetic, in the preflight above, not a comfortable margin.
- **The preflight and the embedding run before the transaction opens; only the writes are inside it.**
  Invariant 2 is a rule about the writes, and the preflight reads nothing from the store — it is a pure
  function of the prose, the tokenizer and two config values, and the one error it raises is `bounds`, which
  is rung 1 of both validation ladders and so precedes existence, version and receipt anyway. Embedding is
  outside for a different reason: a cold fastembed call is ~780 ms (D22), and holding SQLite's single write
  lock across it would make every concurrent writer's `busy_timeout` a function of model-load time. Nothing
  is staged before `BEGIN`, so a failure before it loses nothing.
- **`memory_fts` is resynced with the explicit `'delete'` command carrying the *pre-write* values, not with
  `DELETE FROM memory_fts WHERE rowid = ?`.** Both forms work in isolation; only one composes with the
  validation ladder. The plain `DELETE` on an external-content table reads the **content table** to find the
  terms to remove, so it is correct only *before* the `memory` row is updated — which means before
  authorization has finished, since the row update and the version/receipt rungs are one indivisible step.
  That ordering is unsafe, and unsafely so in the quietest possible way: invariant 10's carve-out **commits** a
  `version_conflict`'s audit event and receipt, so a `DELETE` staged ahead of the version check would be
  durably committed by a *rejected* amend, leaving a live row with no lexical index and no error anywhere. The
  values-explicit form (`INSERT INTO memory_fts (memory_fts, rowid, gist, content) VALUES ('delete', …)`)
  consults no table, so it runs *after* the row is updated and nothing at all is staged before the call is
  authorized. It is the same command the erasure procedure uses, for the same reason.
- **`retire` touches no index, and that is consistent with invariant 2 rather than an exception to it.** The
  invariant requires each mutation's index maintenance to be *inside* its one transaction, not that every
  mutation has some. `retire` writes `active`, `superseded_by`, `version` and `updated_at`; none is an indexed
  column, `memory_fts` covers `gist` and `content` only, and D16 leaves chunks and vectors exactly where they
  are so the row stays retrievable. So there is nothing for its transaction to cover beyond the row, the
  receipt and the event — which is why the indexed write path has two verbs and not three.
- **`index_failed`'s `stage` has four values**, and they are the four ways an index write fails without the
  caller having done anything wrong: `budget` (the arithmetic above leaves no room for content under the
  effective gist bound — a configuration or model problem, not a prose one), `assembly` (the preflight could not
  produce chunks satisfying its own arithmetic — step 7's assertion, the same check applied to each
  chunk's own recounted slice, and a tokenizer whose token count and token spans disagree, which would
  otherwise cut a paragraph short and drop the remainder from the dense index with every later check
  still passing), `embed` (the embedder raised, or returned
  the wrong number of vectors or the wrong width), and `index_write` (the store raised while the transaction
  was being written). `architecture.md` §Errors carries the set as the payload contract.

## Open residual
The real length distribution of tribal-knowledge memories is **unknown** — we have zero real memories. The
instrumentation above exists so that revisiting `chunk_max_tokens`, and the chunk-versus-single-vector
question itself, is a measurement rather than another argument.
