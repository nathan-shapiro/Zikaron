"""`lifecycle.stop_on_encoder_failure` — the exit path a deferred model load makes necessary.

Deferring the load moves one failure across the bind: a model that cannot be loaded, or one whose
width disagrees with the store, is now discovered *after* the socket is already accepting
connections. `health()` answers from the store's metadata and never touches the encoder, so
nothing about that state is visible to a client until it sends a request that needs a vector — and
because start-if-absent only spawns a server when it finds none listening, nothing replaces the
process either. This is the task that ends it instead.
"""

import asyncio
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from tests.fake_encoder import FakeEncoder
from tests.service_fixtures import open_context
from zikaron.core.errors import ErrorCode
from zikaron.core.indexing.encoder import BackgroundLoadedEncoder
from zikaron.service import lifecycle, server


def _failing_load(model_name: str) -> FakeEncoder:
    raise RuntimeError(f"no artifact for {model_name}")


def _loaded_against(dim: int) -> BackgroundLoadedEncoder:
    encoder = BackgroundLoadedEncoder(model_name="m", load=lambda _name: FakeEncoder())
    encoder.declare_dim(dim)
    return encoder


async def test_a_failed_load_unlinks_the_socket_and_stops_the_server(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The whole point: a service that cannot serve must stop being reachable, rather than keep
    answering `health()` truthfully about a store while failing every request that needs a model.

    The log line is asserted alongside the teardown because a stop nobody can see in the log is
    the state that record exists to end — an operator looking at `service.log` has to be able to
    tell this apart from an idle stop or a crash."""
    async with open_context(tmp_path) as ctx:
        sock_path = tmp_path / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        loading = BackgroundLoadedEncoder(model_name="m", load=_failing_load)
        loading.declare_dim(384)

        with caplog.at_level("INFO", logger="zikaron.service"):
            await asyncio.wait_for(
                lifecycle.stop_on_encoder_failure(ctx, running, sock_path, loading), timeout=5.0
            )

        assert not sock_path.exists()
        assert "reason=encoder_failed" in caplog.text


async def test_a_width_disagreement_stops_the_service_the_same_way(tmp_path: Path) -> None:
    """The identity guard, reached through the process rather than through the encoder: a store
    whose recorded width the artifact does not match is unusable, and the service must not stay up
    pretending otherwise."""
    async with open_context(tmp_path) as ctx:
        sock_path = tmp_path / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        disagreeing = BackgroundLoadedEncoder(
            model_name="m", load=lambda _name: FakeEncoder(dim=384)
        )
        disagreeing.declare_dim(768)

        await asyncio.wait_for(
            lifecycle.stop_on_encoder_failure(ctx, running, sock_path, disagreeing), timeout=5.0
        )

        assert not sock_path.exists()


async def test_a_successful_load_never_completes_this_task(tmp_path: Path) -> None:
    """Completion is the caller's signal to tear the service down, so a successful load must leave
    this task pending rather than returning. A version that returned on success would shut the
    service down the moment the model finished loading — which is to say, immediately, on every
    healthy start.

    Asserted by *waiting* on it and requiring the wait to time out, rather than by checking
    `done()` right away: the latter would pass against a task that had simply not been scheduled
    yet, which is the same observation for the wrong reason."""
    async with open_context(tmp_path) as ctx:
        sock_path = tmp_path / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        healthy = _loaded_against(384)

        watch = asyncio.create_task(
            lifecycle.stop_on_encoder_failure(ctx, running, sock_path, healthy)
        )
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(watch), timeout=0.2)
            assert sock_path.exists(), "a healthy load must leave the service reachable"
        finally:
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)
            await running.shut_down()
            sock_path.unlink(missing_ok=True)


async def test_the_watch_does_not_block_the_event_loop_while_the_model_loads(
    tmp_path: Path,
) -> None:
    """The wait belongs on a worker thread, not on the loop. If it ran on the loop, a service
    would accept connections and then answer none of them for as long as the model took — the
    exact failure the deferral exists to remove, reintroduced by the thing watching for it."""
    release = threading.Event()
    finished = threading.Event()

    def _slow_load(_model_name: str) -> FakeEncoder:
        release.wait(timeout=5.0)
        try:
            return FakeEncoder()
        finally:
            finished.set()

    async with open_context(tmp_path) as ctx:
        sock_path = tmp_path / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        slow = BackgroundLoadedEncoder(model_name="m", load=_slow_load)
        slow.declare_dim(384)

        watch = asyncio.create_task(
            lifecycle.stop_on_encoder_failure(ctx, running, sock_path, slow)
        )
        try:
            for _ in range(5):
                await asyncio.sleep(0)
            # The load is the assertion, not the count: five `sleep(0)` turns always complete, so
            # counting them proves nothing. What distinguishes an off-loop wait from an on-loop
            # one is *when* those turns were able to run — before the load finished, or only
            # after a blocked loop was freed by the gate's own timeout expiring.
            assert not finished.is_set(), "the wait for the model ran on the event loop"
        finally:
            release.set()
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)
            await running.shut_down()
            sock_path.unlink(missing_ok=True)


async def test_a_request_needing_the_model_is_answered_with_the_wire_error(
    tmp_path: Path,
) -> None:
    """The middle link of the chain, and the only one a client actually sees at the time: a
    request that needs the model is refused with `bad_config` on the wire, carrying the two widths
    that disagree.

    Asserted here rather than left to composition. The two ends of this chain are covered
    separately — the encoder raises the latched error, and the service stops itself — and it is
    tempting to treat the middle as implied by them. It is not: nothing about a latched
    `ZikaronError` guarantees it survives the read path, the thread boundary and the response
    mapping with its code and payload intact, and a wrapper anywhere along the way that turned it
    into a generic failure would leave both endpoints passing.

    `search` rather than a write, deliberately: the read path reaches the encoder through
    `asyncio.to_thread`, so this test's own event loop stays live while the request blocks. A
    write would block the loop inside `plan_chunks`, which is a real property of the write path
    and stated where it happens, but it would make this test about the wrong thing.

    Driven through `server._handle_line` rather than over a real socket, following this suite's
    own split: `_handle_line`'s return value *is* the response line a client reads, byte for byte,
    so the socket would carry the assertion without contributing to it.
    """
    async with open_context(tmp_path) as base:
        disagreeing = BackgroundLoadedEncoder(
            model_name=base.store.meta.embed_model,
            load=lambda _name: FakeEncoder(dim=base.store.meta.embed_dim * 2),
        )
        disagreeing.declare_dim(base.store.meta.embed_dim)
        ctx = replace(base, encoder=disagreeing, index=replace(base.index, encoder=disagreeing))

        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "memory_search",
            "params": {
                "query": "anything at all",
                "client": {"session_id": "s1", "kind": "mcp", "pid": 100},
            },
        }
        response_line = await server._handle_line(ctx, (json.dumps(request) + "\n").encode("utf-8"))

        assert response_line is not None
        parsed = json.loads(response_line)
        assert parsed["error"]["code"] == ErrorCode.BAD_CONFIG.value
        reported = str(parsed["error"]["data"])
        assert str(base.store.meta.embed_dim * 2) in reported
        assert str(base.store.meta.embed_dim) in reported
