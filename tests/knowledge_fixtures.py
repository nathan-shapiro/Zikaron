"""Shared setup for the knowledge-index tests: a real store, and a corpus root to point at.

Every knowledge-base test needs the same two things, and building them by hand in each file is how
two files come to disagree about what a fresh store looks like. A real store on `tmp_path` —
real SQLite, real FTS5, the real `sqlite-vec` extension — stays in the default tier per
`coding-standards.md`: it is hermetic, deterministic and fast, because `sqlite-vec` is an
in-process extension rather than a service.
"""

import dataclasses
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.knowledge import lifecycle
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store


def config_for(tmp_path: Path) -> EffectiveConfig:
    """The effective config with both layers absent — every key at its built-in default."""
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


def corpus_root(tmp_path: Path, name: str = "docs") -> Path:
    """A directory with a file in it, for a knowledge base to be pointed at.

    Idempotent, so a test that needs the path again names it by asking for it rather than by
    rebuilding the string — which is how a test comes to point at a directory it did not create.
    """
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    (root / "a.md").write_text("a line\n", encoding="utf-8")
    return root


@asynccontextmanager
async def open_store(tmp_path: Path) -> AsyncIterator[tuple[Path, aiosqlite.Connection]]:
    """A freshly created memory store, yielding its directory and its open connection.

    Yields the connection rather than the `Store` because every knowledge verb takes one, and
    handing out the wrapper would invite a test to hold it past the `async with` that closes it.
    """
    store_dir = tmp_path / ".zikaron"
    config = config_for(tmp_path)
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))
    async with await Store.create(store_dir, config, embedder) as store:
        yield store_dir, store.connection


async def add_base(
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
    request: lifecycle.AddRequest,
) -> lifecycle.Created:
    """Create one knowledge base, with a home no `tmp_path` root can ever equal.

    `home` is stamped here rather than left to default so the degenerate-root check is exercised
    against a stated value instead of against whichever home the machine running the suite has —
    which would otherwise make a test's outcome depend on where the suite was started from.
    """
    return await lifecycle.add(
        store_dir,
        db,
        config,
        dataclasses.replace(request, home=store_dir.parent / "not-the-home-directory"),
    )
