"""What a cross-encoder costs per (query, chunk) pair, measured so ambient load cannot fake it.

A first pass at this ran each configuration to completion in turn and was worthless: the machine
carries a persistent multi-core background load whose own demand moves, so configurations measured
later ran against a different machine than those measured earlier, and one configuration repeated
across two runs differed by a third. Sequential measurement on a shared machine measures the
machine's mood.

Two instrument properties fix that, and both matter:

- **Configurations are interleaved, not run to completion.** One timed call per configuration per
  round, cycling through the whole grid each round. Ambient load then falls across the grid
  roughly evenly instead of landing on whichever configuration happened to be running, so the
  *relative* cost of two configurations stays meaningful even while the absolute figures drift.
- **The minimum is reported beside the median.** Contention can only ever make a call slower, so
  over enough rounds the minimum is the closest thing available to the uncontended cost, while the
  median describes what a user on a working machine would actually see. Quoting either alone
  overstates the precision: the pair is the measurement.

The load average is sampled every round and printed with the results, because a figure from a
shared machine without its load beside it is not a measurement.

Run:

    .venv/bin/python spikes/spike_cross_encoder_budget.py ~/zk-m26-cockroach/cockroach/docs/RFCS
"""

import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from zikaron.core.indexing.encoder import Encoder, FastEmbedEncoder, token_head

MINILM = "Xenova/ms-marco-MiniLM-L-6-v2"
TINY = "jinaai/jina-reranker-v1-tiny-en"
CHUNK_TOKENS = 450
ROUNDS = 7
QUERY = "how does a range lease get transferred between replicas"


@dataclass
class Cell:
    """One configuration and every timing it has collected so far."""

    model_name: str
    threads: int | None
    head: int
    pool: int
    samples: list[float] = field(default_factory=list)

    @property
    def label(self) -> str:
        short = self.model_name.split("/")[-1]
        return f"{short:<24} threads={str(self.threads):<4} head={self.head:<4} pool={self.pool:<3}"

    def report(self) -> str:
        best = min(self.samples) * 1000
        middle = statistics.median(self.samples) * 1000
        worst = max(self.samples) * 1000
        return (
            f"{self.label} min {best:7.0f} ms ({best / self.pool:5.1f}/pair)  "
            f"median {middle:7.0f}  max {worst:7.0f}"
        )


def full_chunks(root: Path, encoder: Encoder, *, wanted: int) -> list[str]:
    """Chunks of exactly `CHUNK_TOKENS` tokens, cut on the tokenizer this index counts with."""
    out: list[str] = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        spans = encoder.token_char_spans(text)
        for start in range(0, len(spans), CHUNK_TOKENS):
            window = spans[start : start + CHUNK_TOKENS]
            if len(window) < CHUNK_TOKENS:
                continue
            out.append(text[window[0][0] : window[-1][1]])
            if len(out) >= wanted:
                return out
    return out


def main() -> int:
    from fastembed.rerank.cross_encoder import TextCrossEncoder  # noqa: PLC0415

    root = Path(sys.argv[1]).expanduser()
    bge = FastEmbedEncoder.load("BAAI/bge-small-en-v1.5")
    full = full_chunks(root, bge, wanted=50)
    documents = {
        head: [token_head(chunk, tokens=head, encoder=bge) for chunk in full]
        for head in (450, 256, 128, 64)
    }
    print(f"{len(full)} chunks of {CHUNK_TOKENS} tokens from {root}")
    print(f"{os.cpu_count()} cores, {ROUNDS} interleaved rounds\n")

    cells = [
        Cell(MINILM, None, 450, 10),
        Cell(MINILM, None, 450, 25),
        Cell(MINILM, None, 450, 50),
        Cell(MINILM, None, 256, 25),
        Cell(MINILM, None, 128, 25),
        Cell(MINILM, None, 128, 50),
        Cell(MINILM, None, 64, 50),
        Cell(MINILM, 2, 450, 25),
        Cell(MINILM, 4, 450, 25),
        Cell(TINY, None, 450, 25),
        Cell(TINY, None, 128, 25),
    ]
    # Built once and reused across rounds: a per-round construction would put a model load inside
    # every timing, and the load is what the service pays once rather than per search.
    models = {
        (cell.model_name, cell.threads): TextCrossEncoder(
            model_name=cell.model_name, threads=cell.threads
        )
        for cell in cells
    }
    for model in models.values():
        list(model.rerank(QUERY, full[:1]))

    loads: list[float] = []
    for round_index in range(ROUNDS):
        loads.append(os.getloadavg()[0])
        for cell in cells:
            model = models[(cell.model_name, cell.threads)]
            begin = time.perf_counter()
            scores = list(model.rerank(QUERY, documents[cell.head][: cell.pool]))
            cell.samples.append(time.perf_counter() - begin)
            assert len(scores) == cell.pool, f"{len(scores)} scores for {cell.pool} documents"
        print(f"round {round_index + 1}/{ROUNDS} done, load {loads[-1]:.2f}")

    print(f"\nload average over the run: {min(loads):.2f} to {max(loads):.2f}\n")
    for cell in cells:
        print(cell.report())

    print("\n=== how much the reranker moves the order it was handed ===")
    model = models[(MINILM, None)]
    for head in (450, 128):
        scores = list(model.rerank(QUERY, documents[head][:25]))
        top = sorted(range(25), key=lambda i: -scores[i])[:5]
        print(f"head {head:>4}: top 5 = {top}, kept from the pool's own top 5: "
              f"{len(set(top) & set(range(5)))}/5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
