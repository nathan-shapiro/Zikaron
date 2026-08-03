"""`zikaron.service.context.ServiceContext.assemble` — the store is closed on any failure after
it opens, never left open for a later failure to abandon.

Default tier: a real store on `tmp_path`, `FastEmbedEncoder.load` monkeypatched to fail — no real
model load needed to prove the store-closing contract, and `tests/conftest.py`'s own autouse
leak-detection fixture is the actual proof that nothing was left open, not a fixture built
specifically for this test.
"""

from pathlib import Path

import pytest

from zikaron.core.config.resolution import resolve
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.store.store import Store
from zikaron.service.context import ServiceContext


async def test_assemble_closes_the_store_when_a_later_construction_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`FastEmbedEncoder.load` failing after a successful `Store.open` is not hypothetical —
    `assemble`'s own docstring names it — and if the store it already opened were left open, the
    non-daemon `aiosqlite` worker thread that backs it would keep the whole interpreter alive
    after `main.run()` logs the failure and tries to exit. `tests/conftest.py`'s autouse
    `_no_leaked_store_connections` fixture is what actually proves this: it fails *this* test
    directly if any store connection is still open when it ends, which is a stronger and more
    honest check than asserting on this module's own internals."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_always_fails(model_name: str) -> object:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            file=None,
            key="embedding.embed_model",
            value=model_name,
            expected="a model this test deliberately never provides",
        )

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_always_fails)
    )

    with pytest.raises(ZikaronError) as excinfo:
        await ServiceContext.assemble(store_dir, config)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    # No explicit close call here, and none needed: `assemble` raised before ever handing back a
    # `ServiceContext` for this test to close, so if the store were still open, the module-wide
    # autouse leak fixture — not this test — is what would fail and say so.


async def test_assemble_preserves_the_original_error_even_if_closing_the_store_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close failure on top of a construction failure must not displace the construction error
    a caller actually needs to diagnose — `Store.close` is itself an ordinary `await`, with no
    guarantee it cannot raise, and this asserts the specific `BAD_CONFIG` from `FastEmbedEncoder.
    load` is what a caller's own `except` catches, not whatever `Store.close` raised instead."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_always_fails(model_name: str) -> object:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            file=None,
            key="embedding.embed_model",
            value=model_name,
            expected="a model this test deliberately never provides",
        )

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_always_fails)
    )

    real_close = Store.close

    async def _close_fails_but_still_really_closes(self: Store) -> None:
        # `assemble` must observe a raised exception from this call, to prove the construction
        # error survives a close failure — but the underlying connection still has to be closed
        # for real underneath that raise, or this test's own deliberately-broken monkeypatch
        # would leak the connection past its own scope and trip the unrelated leak-detection
        # fixture over a failure this test caused on purpose, not a genuine leak.
        await real_close(self)
        raise RuntimeError("close also failed, deliberately, for this test")

    monkeypatch.setattr(Store, "close", _close_fails_but_still_really_closes)

    with pytest.raises(ZikaronError) as excinfo:
        await ServiceContext.assemble(store_dir, config)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "embedding.embed_model"
    assert excinfo.value.data["key"] == "embedding.embed_model"
