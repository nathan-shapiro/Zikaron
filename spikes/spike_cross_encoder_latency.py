"""Can a cross-encoder rerank a fused candidate pool inside a search's latency budget?

Three questions, none of which is answerable from a model card:

1. **How many (query, chunk) pairs can be scored per unit time**, at the chunk size this index
   actually produces. A reranker that manages ten pairs in a quarter of a second cannot rerank a
   fifty-chunk pool, and the whole stage would then be reordering a handful of candidates that
   fusion had already ordered.
2. **What a cold load costs**, since the first search after a service starts pays it.
3. **How often a pair overruns the model's sequence window.** Both candidate rerankers wrap a
   512-token model, and a 450-token chunk plus a query plus separators is close enough to that
   ceiling that the answer cannot be assumed — and the failure is silent truncation, which scores
   a chunk on its head and reports nothing.

Run it against a directory of real documents:

    .venv/bin/python spikes/spike_cross_encoder_latency.py ~/zk-m26-cockroach/cockroach/docs/RFCS
"""

import statistics
import sys
import time
from pathlib import Path

from tokenizers import Tokenizer

from zikaron.core.indexing.encoder import FastEmbedEncoder

CANDIDATES = ("Xenova/ms-marco-MiniLM-L-6-v2", "jinaai/jina-reranker-v1-turbo-en")
CHUNK_TOKENS = 450
POOL_SIZES = (10, 25, 50)
QUERIES = (
    "how does a range lease get transferred between replicas",
    "what happens when a node is decommissioned while it holds leases",
    "how are closed timestamps propagated to followers",
    "why does a transaction need to refresh its read timestamp",
    "what is the interaction between zone configuration and replication",
)


def realistic_chunks(root: Path, *, wanted: int) -> list[str]:
    """Chunks of about `CHUNK_TOKENS` tokens, cut on the tokenizer this index counts with."""
    encoder = FastEmbedEncoder.load("BAAI/bge-small-en-v1.5")
    chunks: list[str] = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        spans = encoder.token_char_spans(text)
        for start in range(0, len(spans), CHUNK_TOKENS):
            window = spans[start : start + CHUNK_TOKENS]
            if len(window) < CHUNK_TOKENS:
                continue
            chunks.append(text[window[0][0] : window[-1][1]])
            if len(chunks) >= wanted:
                return chunks
    return chunks


def sequence_lengths(model_name: str, query: str, documents: list[str]) -> list[int]:
    """Token length of each (query, document) pair, as the reranker's own tokenizer pairs them."""
    from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415

    encoder = TextCrossEncoder(model_name=model_name)
    tokenizer = encoder.model.tokenizer
    if not isinstance(tokenizer, Tokenizer):
        raise TypeError(f"{model_name} exposes no tokenizers.Tokenizer")
    counting = Tokenizer.from_str(tokenizer.to_str())
    counting.no_truncation()
    return [len(counting.encode(query, document).ids) for document in documents]


def measure(model_name: str, chunks: list[str]) -> None:
    from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415

    started = time.perf_counter()
    encoder = TextCrossEncoder(model_name=model_name)
    list(encoder.rerank(QUERIES[0], chunks[:1]))
    cold = time.perf_counter() - started
    print(f"\n=== {model_name} ===")
    print(f"cold load + first score: {cold * 1000:.0f} ms")

    for pool in POOL_SIZES:
        elapsed: list[float] = []
        for query in QUERIES:
            documents = chunks[:pool]
            begin = time.perf_counter()
            scores = list(encoder.rerank(query, documents))
            elapsed.append(time.perf_counter() - begin)
            assert len(scores) == pool, f"{len(scores)} scores for {pool} documents"
        median = statistics.median(elapsed) * 1000
        print(
            f"pool {pool:>3}: median {median:7.1f} ms  "
            f"({median / pool:5.1f} ms/pair, min {min(elapsed) * 1000:.0f}, "
            f"max {max(elapsed) * 1000:.0f})"
        )

    lengths = sequence_lengths(model_name, QUERIES[0], chunks[:50])
    over = [length for length in lengths if length > 512]
    print(
        f"pair token length over 50 chunks: median {statistics.median(lengths):.0f}, "
        f"max {max(lengths)}, over 512: {len(over)}/{len(lengths)}"
    )

    ordered = list(encoder.rerank(QUERIES[0], chunks[:25]))
    ranking = sorted(range(len(ordered)), key=lambda i: -ordered[i])
    print(f"top 5 of 25 by reranker: {ranking[:5]}  (spread {max(ordered) - min(ordered):.2f})")


def main() -> int:
    root = Path(sys.argv[1]).expanduser()
    chunks = realistic_chunks(root, wanted=50)
    print(f"{len(chunks)} chunks of {CHUNK_TOKENS} tokens from {root}")
    for model_name in CANDIDATES:
        measure(model_name, chunks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
