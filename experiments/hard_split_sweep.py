"""How many chunk plans the memory preflight refuses on long one-paragraph prose of words WordPiece
splits, against the deployed `bge-small-en-v1.5` (`research/hard-split-word-cut.md`).

    .venv/bin/python experiments/hard_split_sweep.py [--chunking FILE]

`--chunking` loads `chunking.py` from another file, so the same sweep measures an earlier version:
`git show <commit>:zikaron/core/indexing/chunking.py > /tmp/old_chunking.py`. Prints the refusal of
the one paragraph the kiro live test seeded, then the sweep's count of refused plans and of plans
that lost a non-whitespace character.
"""

import argparse
import importlib.util
import random
from pathlib import Path
from types import ModuleType

from zikaron.core.errors import ZikaronError
from zikaron.core.indexing import chunking
from zikaron.core.indexing.encoder import FastEmbedEncoder

_MODEL = "BAAI/bge-small-en-v1.5"
_GIST = "integration test 0 reconnects to the broker after a dropped socket"
_SEEDED = "The flaky integration test reconnects to the broker after a dropped socket. " * 80
_WORDS = (
    "reconnects",
    "broker",
    "socket",
    "integration",
    "flaky",
    "idempotency",
    "deserialization",
    "kubernetes",
    "orchestrator",
    "tokenizer",
    "misconfiguration",
    "throughput",
    "unmarshalling",
)
_BUDGETS = (64, 128, 256, 450)
_TRIALS = 60
_SEED = 7


def _module(path: Path | None) -> ModuleType:
    if path is None:
        return chunking
    spec = importlib.util.spec_from_file_location("chunking_under_test", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"{path} is not a Python module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunking", type=Path)
    under_test = _module(parser.parse_args().chunking)
    encoder = FastEmbedEncoder.load(_MODEL)

    def plan(content: str, budget: int) -> bool | None:
        """Whether the plan kept every character, or `None` where it was refused."""
        try:
            chunks = under_test.plan_chunks(
                gist=_GIST,
                content=content,
                encoder=encoder,
                chunk_max_tokens=budget,
                gist_max_tokens=64,
            ).chunks
        except ZikaronError:
            return None
        return "".join("".join(chunk.text.split()) for chunk in chunks) == "".join(content.split())

    print(f"seeded paragraph at 450: {'refused' if plan(_SEEDED, 450) is None else 'planned'}")
    rng = random.Random(_SEED)  # noqa: S311 — a reproducible corpus, not a secret.
    outcomes = []
    for _ in range(_TRIALS):
        text = " ".join(rng.choice(_WORDS) for _ in range(rng.randint(300, 900)))
        outcomes.extend(plan(text, budget) for budget in _BUDGETS)
    refused = sum(outcome is None for outcome in outcomes)
    lossy = sum(outcome is False for outcome in outcomes)
    print(f"sweep: {len(outcomes)} plans, {refused} refused, {lossy} lost content")


if __name__ == "__main__":
    main()
