"""How long a real chunk actually is, and what that means for a reranker's sequence budget.

The latency spikes cut every document to exactly `chunk_max_tokens`, which is the ceiling rather
than the typical case: the chunker packs whole paragraphs and breaks early wherever the budget
would be exceeded, so a real chunk is usually shorter. Since a cross-encoder's cost is linear in
sequence length, a worst-case chunk length gives a worst-case cost, and the distribution is what
a budget should actually be built from.

It also settles a question the stored schema makes easy to get wrong. **`chunks.text` is not
bounded by `chunk_max_tokens`.** The budget binds what is *embedded*; a single line longer than the
budget is stored whole and embedded from its head, so the stored text of such a chunk can be
arbitrarily long. A reranker handed `chunks.text` would therefore be handed sequences the model
silently truncates — the failure class this corpus refuses to ship unmeasured — while one handed
the embedded form inherits a bound that is already proved.

Reports both, plus how a (query, chunk) pair sits against the reranker's own 512-token window.

Run:

    .venv/bin/python spikes/spike_real_chunk_lengths.py ~/zk-m26-cockroach/cockroach/docs/RFCS
"""

import statistics
import sys
from pathlib import Path

from tokenizers import Tokenizer

from zikaron.core.knowledge.chunking import plan_file_chunks
from zikaron.core.indexing.encoder import FastEmbedEncoder

CHUNK_MAX_TOKENS = 450
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
#: A query longer than any this corpus has seen, to show where the window binds rather than where
#: a short query happens to leave it comfortable. The real ones measured are 9 to 11 words.
LONG_QUERY = (
    "when a range lease is transferred between replicas during a decommission, how does the "
    "incoming leaseholder learn the closed timestamp it must respect before serving follower "
    "reads, and what happens if that information is stale"
)
SHORT_QUERY = "how does a range lease get transferred between replicas"


def percentiles(values: list[int]) -> str:
    ordered = sorted(values)
    def at(fraction: float) -> int:
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]
    return (
        f"min {ordered[0]}, p50 {statistics.median(ordered):.0f}, p90 {at(0.90)}, "
        f"p99 {at(0.99)}, max {ordered[-1]}, mean {statistics.mean(ordered):.0f}"
    )


def main() -> int:
    root = Path(sys.argv[1]).expanduser()
    bge = FastEmbedEncoder.load("BAAI/bge-small-en-v1.5")

    from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415

    rerank_tokenizer = TextCrossEncoder(model_name=RERANK_MODEL).model.tokenizer
    if not isinstance(rerank_tokenizer, Tokenizer):
        raise TypeError(f"{RERANK_MODEL} exposes no tokenizers.Tokenizer")
    counting = Tokenizer.from_str(rerank_tokenizer.to_str())
    counting.no_truncation()
    window = int(rerank_tokenizer.truncation["max_length"])

    stored: list[int] = []
    embedded: list[int] = []
    head_only = 0
    files = 0
    for path in sorted(root.rglob("*.md")):
        relative = str(path.relative_to(root))
        plan = plan_file_chunks(
            path=relative,
            text=path.read_text(encoding="utf-8", errors="replace"),
            encoder=bge,
            chunk_max_tokens=CHUNK_MAX_TOKENS,
        )
        files += 1
        head_only += plan.head_only_chunks
        for chunk, assembled in zip(plan.chunks, plan.embedded_texts(), strict=True):
            stored.append(len(counting.encode(chunk.text, add_special_tokens=False).ids))
            embedded.append(len(counting.encode(assembled, add_special_tokens=False).ids))

    print(f"{files} files, {len(stored)} chunks, budget {CHUNK_MAX_TOKENS} bge tokens")
    print(f"chunks whose stored text exceeds the embedding budget (head-only): {head_only}\n")
    print("counted with the RERANKER's tokenizer, which is what decides its window:")
    print(f"  chunks.text        : {percentiles(stored)}")
    print(f"  path + separator + embedded body : {percentiles(embedded)}\n")

    print(f"reranker window: {window} tokens (special tokens included)")
    for label, query in (("short (9 words)", SHORT_QUERY), ("long (36 words)", LONG_QUERY)):
        query_tokens = len(counting.encode(query, add_special_tokens=False).ids)
        # A cross-encoder pair is [CLS] query [SEP] document [SEP] — three special tokens.
        room = window - query_tokens - 3
        over_stored = sum(1 for n in stored if n > room)
        over_embedded = sum(1 for n in embedded if n > room)
        print(
            f"  {label}: {query_tokens} tokens, leaves {room} for the document -> "
            f"truncated: chunks.text {over_stored}/{len(stored)} "
            f"({100 * over_stored / len(stored):.1f}%), "
            f"embedded form {over_embedded}/{len(embedded)} "
            f"({100 * over_embedded / len(embedded):.1f}%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
