"""The one thing the store needs from an embedder: its width, and the model name it reports.

The store's dimension check must run before `memory_vec` is created, and creating a store embeds
nothing — so this is deliberately the *narrowest* thing an embedder can be asked for. `fastembed`
is a dependency of `zikaron-core` as a whole, not of this module: the indexing layer's `Encoder`
extends this protocol with the tokenizer and embedding calls a write path needs, and the store is
written against this narrow form so it never depends on them.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """What the store needs to check before it fixes a `vec0` column's width forever.

    `vec0` fixes a column's width at `CREATE` time (`schema.md` §"Creating the dense index"), so
    the store must know the width a configured model actually emits before any table exists. A
    real implementation loads the model named by `model_name`; this protocol says nothing about
    *how* `dim` is produced; only that it is available without embedding anything.
    """

    @property
    def model_name(self) -> str:
        """The model identifier this embedder reports, for comparison against `meta.embed_model`."""
        ...

    @property
    def dim(self) -> int:
        """The width of every vector this embedder would produce."""
        ...


@dataclass(frozen=True, slots=True)
class FakeEmbedder:
    """An `Embedder` that reports a width without loading anything.

    The store's own tests use this to exercise the width check deterministically and without
    `fastembed`'s cold-start cost; nothing about the store's creation or open path can tell it
    apart from a real one, since both are used purely through the protocol above.
    """

    model_name: str
    dim: int
