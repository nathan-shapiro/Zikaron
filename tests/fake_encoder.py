"""A deterministic `Encoder` for the unit tier, with explicit fault injection.

Shared by every indexing test the way `design_tables.py` is shared by the drift guards, and kept
out of the package because it is test scaffolding rather than something Zikaron ships.

**Tokens are maximal runs of non-whitespace.** That is not what WordPiece does, and it is the point:
every budget in the chunking preflight becomes hand-computable from the text a test wrote, so a test
asserting "this splits into two chunks at 5 tokens" is asserting the *packing rule* rather than
re-deriving BGE's vocabulary. The integration tier runs the same code against the real artifact,
which is where fidelity to the deployed tokenizer is actually checked.

**Vectors are deterministic and deliberately unnormalized.** Seeded from the text, so the same prose
embeds identically in every process — which is what lets a test assert a stored vector byte for
byte. Unnormalized, so the write path's own L2 normalization is observable rather than accidentally
satisfied by an embedder that happened to return unit vectors.
"""

import hashlib
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

_TOKEN: Final = re.compile(r"\S+")

#: BGE's own `[CLS]`/`[SEP]` count and sequence cap, so the unit tier budgets against the same
#: numbers the deployed model reports unless a test deliberately says otherwise.
DEFAULT_N_SPECIAL: Final = 2
DEFAULT_MAX_SEQUENCE: Final = 512

DEFAULT_MODEL: Final = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM: Final = 384


@dataclass
class FakeEncoder:
    """An `Encoder` that counts whitespace-delimited tokens and hashes text into vectors.

    The three fault-injection fields are how the `embed` stage's three failure modes are reached:
    an embedder that raises, one that returns the wrong number of vectors, and one that returns the
    wrong width. Each is a real thing a swapped model can do, and each has to become `index_failed`
    rather than a mislabelled vector.
    """

    model_name: str = DEFAULT_MODEL
    dim: int = DEFAULT_DIM
    n_special_tokens: int = DEFAULT_N_SPECIAL
    max_sequence_tokens: int = DEFAULT_MAX_SEQUENCE
    embed_error: Exception | None = None
    vector_count_delta: int = 0
    vector_width: int | None = None
    embedded: list[tuple[str, ...]] = field(default_factory=list)

    def count_tokens(self, text: str) -> int:
        return len(_TOKEN.findall(text))

    def token_char_spans(self, text: str) -> tuple[tuple[int, int], ...]:
        return tuple(match.span() for match in _TOKEN.finditer(text))

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        self.embedded.append(tuple(texts))
        if self.embed_error is not None:
            raise self.embed_error
        width = self.dim if self.vector_width is None else self.vector_width
        vectors = [vector_for(text, width) for text in texts]
        if self.vector_count_delta > 0:
            vectors.extend(vector_for("surplus", width) for _ in range(self.vector_count_delta))
        elif self.vector_count_delta < 0:
            vectors = vectors[: max(0, len(vectors) + self.vector_count_delta)]
        return tuple(vectors)


def vector_for(text: str, width: int) -> tuple[float, ...]:
    """The vector `FakeEncoder` produces for `text` — exposed so a test can predict a stored row.

    Seeded from a SHA-256 digest rather than from `hash()`, whose string seed is randomized per
    process and would make "the same prose embeds identically" false across runs.
    """
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    rng = random.Random(seed)  # noqa: S311
    return tuple(rng.uniform(-2.0, 2.0) for _ in range(width))
