"""`zikaron.service.context.ServiceContext.assemble` — the store is closed on any failure after
it opens or creates it, never left open for a later failure to abandon; and the create-on-absent
first-run path itself.

Most of this file is default tier: a real store on `tmp_path`, `FastEmbedEncoder.load`
monkeypatched to a fake, and the failure injected at a construction step *after* the open — on the
open path a failing load never raises from `assemble` at all, which is why the injection point is
where it is. No real model load is needed to prove the store-closing contract, and
`tests/conftest.py`'s own autouse leak-detection fixture is the actual proof that nothing was left
open, not a fixture built specifically for this test. The create-on-absent tests are marked
`integration` individually: they call the real `FastEmbedEncoder.load`, since the create path's own
dimension/model-name check against a real embedder is exactly what they exist to exercise.
"""

import asyncio
import threading
from pathlib import Path

import pytest

from tests.fake_encoder import FakeEncoder
from zikaron.core.config.resolution import resolve
from zikaron.core.errors import BadConfigSource, ErrorCode, ZikaronError
from zikaron.core.store.store import Store
from zikaron.service.context import ServiceContext


async def test_assemble_closes_the_store_when_a_later_construction_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A construction step that runs **after** `_open_or_create` succeeds — `IndexingContext.
    for_store` here — is not hypothetical: `assemble`'s own docstring names "the encoder loading
    but the store call after it failing" as a real case, and if the store `_open_or_create` had
    already opened were left open, the non-daemon `aiosqlite` worker thread that backs it would
    keep the whole interpreter alive after `main.run()` logs the failure and tries to exit.
    `tests/conftest.py`'s autouse `_no_leaked_store_connections` fixture is what actually proves
    this: it fails *this* test directly if any store connection is still open when it ends, which
    is a stronger and more honest check than asserting on this module's own internals.

    The failure is injected at `IndexingContext.for_store`, not at `FastEmbedEncoder.load`, and
    that choice is load-bearing rather than incidental. On the open path the load runs on its own
    thread and nothing waits for it, so a failing `load` would not raise from `assemble` at all —
    it would be latched and surface at the first request. Injecting there would test nothing about
    this contract, and would not even fail.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load",
        staticmethod(lambda model_name: _FakeEmbedder()),  # noqa: ARG005 — must match `.load`'s signature.
    )

    def _for_store_always_fails(*_args: object, **_kwargs: object) -> object:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            file=None,
            key="chunk_max_tokens",
            value="deliberately broken for this test",
            expected="a construction step this test deliberately fails after the store opens",
        )

    monkeypatch.setattr(
        "zikaron.service.context.IndexingContext.for_store", staticmethod(_for_store_always_fails)
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
    guarantee it cannot raise, and this asserts the specific `BAD_CONFIG` from the failing
    construction step is what a caller's own `except` catches, not whatever `Store.close` raised
    instead.

    Failure injection point matches the sibling test above, for the reason its sibling above
    states: this test runs the open path, where the load happens on its own thread and a failing
    `FastEmbedEncoder.load` never raises from `assemble` at all — so injecting there would leave
    the close-failure path this test exists to defend unreached, and would not even fail."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load",
        staticmethod(lambda model_name: _FakeEmbedder()),  # noqa: ARG005 — must match `.load`'s signature.
    )

    def _for_store_always_fails(*_args: object, **_kwargs: object) -> object:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            file=None,
            key="chunk_max_tokens",
            value="deliberately broken for this test",
            expected="a construction step this test deliberately fails after the store opens",
        )

    monkeypatch.setattr(
        "zikaron.service.context.IndexingContext.for_store", staticmethod(_for_store_always_fails)
    )

    real_close = Store.close
    close_was_called = False

    async def _close_fails_but_still_really_closes(self: Store) -> None:
        # `assemble` must observe a raised exception from this call, to prove the construction
        # error survives a close failure — but the underlying connection still has to be closed
        # for real underneath that raise, or this test's own deliberately-broken monkeypatch
        # would leak the connection past its own scope and trip the unrelated leak-detection
        # fixture over a failure this test caused on purpose, not a genuine leak.
        nonlocal close_was_called
        close_was_called = True
        await real_close(self)
        raise RuntimeError("close also failed, deliberately, for this test")

    monkeypatch.setattr(Store, "close", _close_fails_but_still_really_closes)

    with pytest.raises(ZikaronError) as excinfo:
        await ServiceContext.assemble(store_dir, config)
    assert excinfo.value.code is ErrorCode.BAD_CONFIG
    assert excinfo.value.data["key"] == "chunk_max_tokens"
    assert close_was_called, "the raising close path must actually have been reached"


@pytest.mark.integration
async def test_assemble_creates_the_store_when_memory_db_is_absent(tmp_path: Path) -> None:
    """A fresh `.zikaron` directory with no `memory.db` inside it is the ordinary state of a
    project that has never run Zikaron — not a `bad_config` to reject. `assemble` must create the
    store itself rather than requiring some separate, unbuilt bootstrap step to have run first, or
    the system could never reach its own working state from an empty directory unassisted.

    Integration-tier: unlike every other test in this file, this one does not monkeypatch
    `FastEmbedEncoder.load` — the create path's own dimension/model-name check is exactly what is
    under test, and faking the encoder would fake away the one thing this test needs to be real.
    """
    store_dir = tmp_path / ".zikaron"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    assert not (store_dir / "memory.db").exists()

    ctx = await ServiceContext.assemble(store_dir, config)
    try:
        assert (store_dir / "memory.db").exists()
        assert ctx.store.meta.embed_model == config.get_str("embed_model")
        assert ctx.store.meta.embed_dim == config.get_int("embed_dim")
    finally:
        await ctx.close()


@pytest.mark.integration
async def test_assemble_creates_the_store_directory_itself_when_even_zikaron_is_absent(
    tmp_path: Path,
) -> None:
    """The create path must not assume `.zikaron` already exists either — `ensure_store_dir`
    (called inside `Store.create`) creates it, so `assemble` reaching all the way from a directory
    with **nothing** Zikaron-related in it to a fully open store is the actual first-run case, not
    only the narrower one where `.zikaron` exists but is merely empty."""
    store_dir = tmp_path / ".zikaron"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    assert not store_dir.exists()

    ctx = await ServiceContext.assemble(store_dir, config)
    try:
        assert store_dir.is_dir()
        assert ctx.store.path == store_dir / "memory.db"
    finally:
        await ctx.close()


@pytest.mark.integration
async def test_assemble_opens_rather_than_recreates_an_existing_store(tmp_path: Path) -> None:
    """The existence check must key off `memory.db` reappearing on a **second** `assemble` call
    against the same directory: a create-on-absent path that instead re-created the store on every
    startup would destroy whatever the first run had already written, which is the one failure
    mode this test exists to rule out."""
    store_dir = tmp_path / ".zikaron"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    first = await ServiceContext.assemble(store_dir, config)
    try:
        first_store_id = first.store.meta.store_id
    finally:
        await first.close()

    second = await ServiceContext.assemble(store_dir, config)
    try:
        assert second.store.meta.store_id == first_store_id
    finally:
        await second.close()


async def test_assemble_returns_on_the_open_path_before_the_model_has_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole deferral exists for, asserted at the seam a caller actually uses.

    A cold service spends most of its startup inside the model load, and the client waiting to
    push memories into a user's first message gives it about a second before giving up. So
    `assemble` must return — leaving the caller free to bind a socket — while the model is still
    loading.

    **This is the test that fails if an eager read of the encoder ever creeps back into
    `assemble`.** That is not hypothetical: an earlier attempt at this deferral changed startup
    latency by nothing at all, because one construction step read the encoder's width during
    assembly and quietly put the whole load back on the critical path. Nothing failed and nothing
    was logged; only a measurement showed it. Here it deadlocks the test instead, which is a much
    louder way to be told.

    The load is gated on an event rather than made slow, so "still loading" is a fact rather than
    a race this happens to win."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    async with await Store.create(store_dir, config, FakeEncoder()) as store:
        recorded_dim = store.meta.embed_dim

    released = threading.Event()
    entered = threading.Event()
    finished = threading.Event()

    def _gated_load(_model_name: str) -> FakeEncoder:
        entered.set()
        # Bounded, so a regression fails the suite instead of hanging it — which is why the
        # assertion below is that the load has not *finished* rather than that it was not
        # released. An earlier version asserted the latter and was satisfied by this very
        # timeout expiring: `assemble` blocked for the full five seconds, the wait gave up, and
        # the test passed having measured nothing.
        released.wait(timeout=5.0)
        try:
            return FakeEncoder(dim=recorded_dim)
        finally:
            finished.set()

    monkeypatch.setattr("zikaron.service.context.FastEmbedEncoder.load", staticmethod(_gated_load))

    ctx = await asyncio.wait_for(ServiceContext.assemble(store_dir, config), timeout=5.0)
    try:
        assert entered.is_set(), "the load must have been started, not merely postponed"
        assert not finished.is_set(), "assemble waited for the model load"
        assert ctx.encoder_load is ctx.encoder, (
            "the open path must hand back the deferred load, so the process can watch it fail"
        )
    finally:
        released.set()
        await ctx.close()


async def test_assemble_has_nothing_left_to_watch_on_the_create_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Creating a store derives its recorded width from the model, so the create path has already
    waited for the artifact by the time it returns. There is no deferred load behind that encoder
    and nothing for the process to watch — a watch created anyway would wait forever on a load
    that finished before the socket was ever bound."""
    store_dir = tmp_path / ".zikaron"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    def _load_fake(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr("zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake))

    ctx = await ServiceContext.assemble(store_dir, config)
    try:
        assert ctx.encoder_load is None
        assert isinstance(ctx.encoder, FakeEncoder), (
            "the create path must hand back the artifact itself, not a facade over a finished load"
        )
    finally:
        await ctx.close()


async def test_assemble_releases_the_loader_when_the_store_cannot_be_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store that fails to open must not leave the loading thread waiting forever.

    The loader waits for the store's recorded width before it can check the artifact against it,
    so a caller that abandons the store owes it word that the width is never coming. Without that,
    every failed open leaks one thread blocked on a declaration with nobody left to make it —
    invisible in production, where the process is exiting anyway, and cumulative anywhere a
    process assembles more than once.

    Asserted by joining the loader thread itself rather than by inspecting the encoder, because
    the encoder is unreachable here: `assemble` raises, so nothing is returned to ask."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    async with await Store.create(store_dir, config, FakeEncoder()):
        pass

    loaders: list[threading.Thread] = []

    def _record_the_loading_thread(_model_name: str) -> FakeEncoder:
        loaders.append(threading.current_thread())
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_record_the_loading_thread)
    )

    async def _open_always_fails(*_args: object, **_kwargs: object) -> Store:
        raise ZikaronError(
            ErrorCode.BAD_CONFIG,
            source=BadConfigSource.FILE,
            file=None,
            key="embed_model",
            value="deliberately broken for this test",
            expected="an open this test deliberately fails, after the loader has been started",
        )

    monkeypatch.setattr(Store, "open", staticmethod(_open_always_fails))

    with pytest.raises(ZikaronError):
        await ServiceContext.assemble(store_dir, config)

    assert loaders, "the load must have been started before the open was attempted"
    loaders[0].join(timeout=2.0)
    assert not loaders[0].is_alive(), (
        "the loader was left waiting for a width declaration that will never come"
    )
