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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from tests.fake_encoder import FakeEncoder
from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.knowledge import disposal, lifecycle, registry
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store


def config_for(tmp_path: Path) -> EffectiveConfig:
    """The effective config with both layers absent — every key at its built-in default."""
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


def write_config(tmp_path: Path, toml_text: str) -> None:
    """Write the project configuration layer `config_for` will read for this store.

    Call before anything opens the store: a knowledge base copies the tuning keys into its own
    `meta` when it is created, which is the whole point of seeding them, so a value written
    afterwards would not reach the corpus under test.
    """
    (tmp_path / "project.toml").write_text(toml_text, encoding="utf-8")


def corpus_root(tmp_path: Path, name: str = "docs") -> Path:
    """A directory with a file in it, for a knowledge base to be pointed at.

    Idempotent, so a test that needs the path again names it by asking for it rather than by
    rebuilding the string — which is how a test comes to point at a directory it did not create.
    """
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    (root / "a.md").write_text("a line\n", encoding="utf-8")
    return root


def write_tree(root: Path, layout: dict[str, bytes]) -> Path:
    """Write `layout`'s paths under `root`, creating directories, and return `root`.

    Bytes rather than text, because several callers are about what happens to a file that is not
    valid UTF-8 at all.
    """
    for relative, content in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
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


@dataclass(frozen=True, slots=True)
class Corpus:
    """One registered knowledge base over a real directory, with everything a verb needs.

    Held together because every knowledge-base verb takes the same four things, and a test that
    assembled them one at a time could point a verb at a store other than the one it created.
    """

    store_dir: Path
    db: aiosqlite.Connection
    config: EffectiveConfig
    name: str
    root: Path


def build_settings(
    config: EffectiveConfig, *, encoder: Encoder | None = None, full: bool = False
) -> disposal.BuildSettings:
    """What a build needs beyond the corpus itself, with the deterministic encoder by default.

    The batch size comes from the configuration rather than from a literal here, so a test never
    asserts against a second statement of a default that is free to drift from the real one.
    """
    return disposal.BuildSettings(
        encoder=encoder if encoder is not None else FakeEncoder(),
        embed_batch=config.get_int("knowledge_embed_batch"),
        full=full,
    )


async def build_index(
    corpus: "Corpus", *, encoder: Encoder | None = None, full: bool = False
) -> lifecycle.Refreshed:
    """Build one corpus's index the way every command does, and report what the build did."""
    return await lifecycle.refresh(
        corpus.store_dir,
        corpus.db,
        corpus.config,
        name=corpus.name,
        build=build_settings(corpus.config, encoder=encoder, full=full),
    )


def add_request(root: Path, **options: Any) -> lifecycle.AddRequest:  # noqa: ANN401
    """An `AddRequest` over `root` with everything a test is not varying already filled in.

    `options` are `AddRequest`'s own field names, checked by `dataclasses.replace` at call time —
    which is why they are untyped here. Declaring each of them instead would be a second copy of
    that signature, free to drift from it and to hide a field a test wanted to set.
    """
    return dataclasses.replace(
        lifecycle.AddRequest(name="docs", root=root, description="a corpus"), **options
    )


@asynccontextmanager
async def open_corpus(
    tmp_path: Path, request: lifecycle.AddRequest | None = None
) -> AsyncIterator[Corpus]:
    """A store with one knowledge base registered, ready to be built.

    With no request, the corpus is the default root `corpus_root` writes — which is what a test
    about scanning rather than about configuration wants.
    """
    async with open_store(tmp_path) as (store_dir, db):
        config = config_for(tmp_path)
        asked = request if request is not None else add_request(corpus_root(tmp_path))
        await add_base(store_dir, db, config, asked)
        yield Corpus(store_dir=store_dir, db=db, config=config, name=asked.name, root=asked.root)


@asynccontextmanager
async def open_index(corpus: Corpus) -> AsyncIterator[KnowledgeDatabase]:
    """This corpus's own database, open, for a test that needs to read what a build wrote."""
    registered = await registry.require(corpus.db, corpus.name)
    async with await KnowledgeDatabase.open(corpus.store_dir, registered.id) as opened:
        yield opened


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
