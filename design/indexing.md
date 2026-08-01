# Indexing and chunking — v0 spec

> Settled with the user 2026-08-01. Summarized as **D28** in `FINDINGS.md`; this is the build contract.
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
   `zikaron_remember` rejects it rather than producing a memory with zero vectors. If content ever became
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

- **Every mutation that touches indexed prose is one transaction**, not only `amend`. That is `remember`,
  `amend`, `retire`, `merge`, both forms of `promote`, and `discard` — see `schema.md` invariant 2, which
  is the authoritative statement. Inside it: the `memory` row, the `version` bump, explicit `memory_fts`
  maintenance, chunk and vector maintenance, receipts, and the events.
- **Delete vectors before chunks.** `memory_vec` is a virtual table with no foreign key to
  `memory_chunk`, so chunks-first would orphan vectors if the sequence were interrupted. The reverse
  order fails safe: an orphaned *chunk* row is detectable and repairable; an orphaned vector is a silent
  false positive in retrieval.
- **A `tier` flip rewrites the index too.** `promote`'s in-place form changes no prose, so its chunks are
  unchanged — but it still bumps `version` in the same transaction, and if the consolidator supplied
  different prose it is not an in-place flip at all (see `architecture.md`, which decides the form from the
  payload rather than guessing).
- **Retire (D16) leaves chunks in place**; eligibility excludes or demotes at query time, matching
  `~/Memory`'s soft-retire contract, and it is what keeps superseded rows retrievable under D25.
- **Full reindex is build-and-swap, or the store is unavailable while it runs** (`schema.md` invariant 3).
  D20's forced-reindex case includes an `embed_dim` change, which `vec0` cannot do in place — the table is
  dropped and recreated, so that case *must* take the unavailable form.
- `chunk_max_tokens` default **450**; `gist_max_tokens` default **64**. The relationship between them and
  the 512 cap is arithmetic, in the preflight above, not a comfortable margin.

## Open residual
The real length distribution of tribal-knowledge memories is **unknown** — we have zero real memories. The
instrumentation above exists so that revisiting `chunk_max_tokens`, and the chunk-versus-single-vector
question itself, is a measurement rather than another argument.
