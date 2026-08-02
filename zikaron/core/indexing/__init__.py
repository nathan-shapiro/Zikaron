"""Indexing: chunk the dense side, index the lexical side whole, and write both atomically.

`design/indexing.md` is normative for this package, and `design/schema.md` invariants 1, 2, 12 and
13 are what it must hold. The shape of it:

- `encoder` — the deployed artifact, tokenizer and model together, since the preflight must count
  with exactly what will embed.
- `chunking` — the preflight, pure: prose in, the exact chunks that will be embedded out.
- `lexical` — `memory_fts`, unchunked, one document per memory (D28, invariant 13).
- `vectors` — `memory_chunk` rows and their `vec0` vectors, written in the order invariant 1 and the
  no-foreign-key rule require.
- `writes` — the two indexed verbs, each one transaction (invariant 2).

Three semantics this package depends on, stated in `design/indexing.md` §Storage and not only here:
`token_count` counts `content` alone on both the row and the event, since `gist_tokens` is a sibling
field; `memory_chunk.token_count` counts that chunk's own slice of content rather than the assembled
sequence, whose length stays derivable from the two; and `part_index` is 0-based, unlike
consolidation's deliberately 1-based shard index, because chunk parts are shown to nobody and their
only consumer is code.

This is deliberately **not** the tool surface. `zikaron_remember`'s dedup hand-back and the
envelope's own bounds belong to the tool-facing write path, which composes
`writes.remember_within_transaction` into its own transaction — D15's dedup search has to run in the
same transaction as the write it reports on, since it queries the vectors that write just
inserted.
"""
