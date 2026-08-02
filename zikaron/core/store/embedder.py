"""The one thing the store needs from an embedder: its width, and the model name it reports.

`build-plan.md`'s M2 fence is exactly this module's reason to exist: the store's dimension check
must run before `memory_vec` is created, but nothing in this milestone chunks, embeds or writes a
vector. `fastembed` is a dependency of `zikaron-core` as a whole, not of this module — a real,
`fastembed`-backed implementation of this protocol is later work, and the store is written
against the protocol so that landing it costs no change here.
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
