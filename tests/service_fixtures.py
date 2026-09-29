"""A `ServiceContext` built by hand with a `FakeEncoder`, for the default tier's dispatch tests.

`ServiceContext.assemble` always loads `FastEmbedEncoder`, which is exactly the integration-tier
cost `test_service_context_integration.py` pays deliberately and once. Every other dispatch test
needs the same *shape* of context — a real store, real config, real `IndexingContext`/
`RetrievalSettings`/`ConsolidationSettings` — without that cost, so this module builds one directly
through `ServiceContext`'s own constructor rather than through `assemble`: `encoder` is typed as
the `Encoder` protocol precisely so a `FakeEncoder` is a legal value for it, structurally.
"""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Final

from tests.fake_encoder import FakeEncoder
from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.consolidation.context import ConsolidationSettings
from zikaron.core.indexing.writes import IndexingContext
from zikaron.core.retrieval.retrieve import RetrievalSettings
from zikaron.core.store.store import Store
from zikaron.service.access_log import AccessLog
from zikaron.service.context import ActivityTracker, ServiceContext
from zikaron.service.envelope import ResolvedEnvelope

MAX_DEPTH: Final = 32


def config(tmp_path: Path, overrides: str = "") -> EffectiveConfig:
    project = tmp_path / "project.toml"
    project.write_text(overrides, encoding="utf-8")
    return resolve(tmp_path / "system.toml", project)


def envelope(
    session_id: str = "s1", kind: str = "mcp", pid: int = 100, op_id: str = "op1"
) -> ResolvedEnvelope:
    return ResolvedEnvelope(session_id=session_id, kind=kind, pid=pid, op_id=op_id)


@asynccontextmanager
async def _access_log(store: Store) -> AsyncIterator[AccessLog]:
    """A live access log over `store`, closed however the test ends.

    Live rather than stopped, deliberately. Every dispatch test then runs with the seam's
    instrumentation on, which is what makes a test *about* the access log ordinary rather than
    special — and a shape that could be built with it off would let the whole of it be unexercised
    while every dispatch test still passed. A test that wants the unlogged control closes it.
    """
    log = await AccessLog.open(store.path)
    try:
        yield log
    finally:
        await log.close()


@asynccontextmanager
async def open_context(tmp_path: Path, overrides: str = "") -> AsyncIterator[ServiceContext]:
    """A real store on `tmp_path`, opened directly (not through `ServiceContext.assemble`) so a
    `FakeEncoder` can stand in for `FastEmbedEncoder` — hermetic and fast, per
    `coding-standards.md` §4's "a real store... stays in the default tier."
    """
    cfg = config(tmp_path, overrides)
    encoder = FakeEncoder()
    async with (
        await Store.create(tmp_path / ".zikaron", cfg, encoder) as store,
        _access_log(store) as log,
    ):
        yield ServiceContext(
            store=store,
            config=cfg,
            encoder=encoder,
            index=IndexingContext.for_store(store, cfg, encoder),
            retrieval=RetrievalSettings.from_config(cfg),
            consolidation=ConsolidationSettings.from_config(cfg),
            supersession_max_depth=cfg.get_int("supersession_max_depth"),
            activity=ActivityTracker(last_activity=time.monotonic()),
            access_log=log,
        )


@asynccontextmanager
async def context_over(store_dir: Path, config_source: Path) -> AsyncIterator[ServiceContext]:
    """A `ServiceContext` over a store that **already exists**, for a caller that made it itself.

    `open_context` creates one; this opens one, which is what a test driving a surface through its
    own entry point needs — that surface is the thing under test and has already put a store where
    it expects to find it.
    """
    cfg = resolve(config_source / "system.toml", config_source / "project.toml")
    encoder = FakeEncoder()
    async with (
        await Store.open(store_dir, cfg) as store,
        _access_log(store) as log,
    ):
        yield ServiceContext(
            store=store,
            config=cfg,
            encoder=encoder,
            index=IndexingContext.for_store(store, cfg, encoder),
            retrieval=RetrievalSettings.from_config(cfg),
            consolidation=ConsolidationSettings.from_config(cfg),
            supersession_max_depth=cfg.get_int("supersession_max_depth"),
            activity=ActivityTracker(last_activity=time.monotonic()),
            access_log=log,
        )
