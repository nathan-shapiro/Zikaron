# A hard split inside a word refused the write

Measured 2026-10-29 against `BAAI/bge-small-en-v1.5`, the deployed embedder, in the M41-2 worktree.

## What failed

M41-2's kiro spill test seeded three memories through the primary MCP server, each a single
paragraph of 6,160 characters, one sentence repeated 80 times. Every `zikaron_memory_remember`
was refused with `index_failed` at stage `assembly`. The same script against `main`'s code refused
the same way, so this predates M41-2.

## Why

`design/indexing.md` step 5 hard-splits a paragraph longer than the chunk budget. The old cut took
windows of exactly `budget` tokens and sliced the paragraph from the first token's start offset to
the last token's end offset. With `chunk_max_tokens = 450` the paragraph is 1,360 tokens, and the
first cut fell inside `reconnects`, which WordPiece splits into several tokens. The second piece
then opened on the fragment `cts`. Counted on its own, WordPiece reads a fragment at the start of a
text as a word, not as a continuation, and tokenizes it differently: the piece counted 451 tokens
for a window of 450. The preflight's post-condition recounts every emitted chunk against the
budget, so it refused the write. That check worked as designed. The cut was the defect.

A piece made of whole words cannot drift this way. BERT's pre-tokenizer splits at whitespace, and
WordPiece tokenizes each word alone, so a slice that starts and ends on word boundaries tokenizes to
exactly its window.

## The fix

`zikaron/core/indexing/chunking.py` `_hard_split` now ends each piece at the last word start the
budget reaches. A word start is a token preceded by whitespace, read from the spans. Where a window
holds no word start, a single run longer than the budget, the cut stays on a token boundary, and
the piece shrinks a token at a time until its own count fits. Boundaries remain a function of the
text alone. The knowledge index has no such split: it embeds an over-long line's head
(`token_head`), and a prefix cut at a token boundary re-tokenizes to the same tokens.

## Measured

`.venv/bin/python experiments/hard_split_sweep.py [--chunking FILE]` plans the seeded paragraph at
450, then 60 random paragraphs of 300 to 900 words, drawn from 13 words WordPiece splits, at each of
the budgets 64, 128, 256 and 450:

| Chunker | Seeded paragraph | Sweep: refused of 240 | Sweep: content lost |
|---|---|---|---|
| before (`git show 8617308:zikaron/core/indexing/chunking.py`) | refused | 177 | 0 |
| after | planned, pieces of 448, 450, 450 and 12 tokens | 0 | 0 |

**No real store has hit it.** The four stores' call logs (`~/Trading/LeibaTrader`, `~/Dividends`,
`~/Memory`, `~/PythonPlayground`) hold 136 `memory_remember` and `memory_amend` calls up to
2026-10-29, and none failed with `index_failed`. Real memories are short or broken into
paragraphs, so the defect was latent. It reached only a paragraph over the budget whose cut fell
inside a word.
