"""`zikaron.mcp.connection.ServiceConnection` — cancellation safety. `asyncio.to_thread`'s worker
threads keep running a blocking call to completion regardless of whether their awaiting coroutine
is cancelled, so a cancelled tool call must not leave an orphaned worker still touching a socket
(or a leaked, unclosed one from a cancelled connection attempt) for a later call to collide with.
"""

import asyncio
import threading
from pathlib import Path

import pytest

from zikaron.mcp.connection import ServiceConnection


@pytest.fixture
def connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServiceConnection:
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    return ServiceConnection(tmp_path)


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


async def test_cancelling_during_send_closes_the_socket_so_a_later_call_gets_a_fresh_one(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact orphaned-worker scenario: `_send_request` is still "inside" its own blocking
    call (modeled with a real `threading.Event` a worker thread waits on, since `asyncio.
    to_thread` genuinely runs it on a separate OS thread) when the awaiting `request()` call is
    cancelled. The held socket must be detached from `self._sock` and closed at that point, so no
    subsequent, separate call through the same connection is ever handed that same socket object
    — this test proves detachment and non-reuse specifically, not that `close()` promptly wakes
    the orphaned worker's own blocked call: on Linux, closing a descriptor from another thread is
    not a reliable interrupt for an already-blocked `send`/`recv`, so the fake worker here is
    released explicitly by the test itself (`worker_may_proceed.set()`), exactly modelling that
    the real orphaned worker's eventual exit is bounded by its own socket timeout, not by this
    close.
    """
    worker_may_proceed = threading.Event()
    worker_finished = threading.Event()
    fake_socket = _FakeSocket()

    async def fake_connected_socket(_self: ServiceConnection) -> _FakeSocket:
        return fake_socket

    def blocking_send_request(
        _sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope
        worker_may_proceed.wait(timeout=5.0)
        worker_finished.set()

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)
    monkeypatch.setattr("zikaron.mcp.connection._send_request", blocking_send_request)

    envelope = connection.envelope(kind="mcp")
    task = asyncio.create_task(connection.request("remember", {}, envelope=envelope))
    # Give the task a real chance to reach the `await asyncio.to_thread(...)` line and actually
    # start the worker thread before cancelling — cancelling before the thread even starts would
    # not exercise the orphaned-worker case this test is for.
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_socket.closed, "the socket must be closed the instant cancellation is observed"
    assert connection._sock is None, "the connection must not still be holding the closed socket"

    # Release the orphaned worker so it can finish and the test's own cleanup does not leak a
    # thread — its own blocking call already has nothing left to observe.
    worker_may_proceed.set()
    assert worker_finished.wait(timeout=5.0), "the orphaned worker must still run to completion"


async def test_cancelling_during_read_closes_the_socket_so_a_later_call_gets_a_fresh_one(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identical scenario, on the response-reading half rather than the send half — both are
    separately wrapped in their own cancellation handling in `request()`, and this proves the
    read-side one specifically."""
    worker_may_proceed = threading.Event()
    worker_finished = threading.Event()
    fake_socket = _FakeSocket()

    async def fake_connected_socket(_self: ServiceConnection) -> _FakeSocket:
        return fake_socket

    def instant_send_request(
        _sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope

    def blocking_read_response(_sock: object) -> dict[str, object]:
        worker_may_proceed.wait(timeout=5.0)
        worker_finished.set()
        return {"jsonrpc": "2.0", "id": 1, "result": {}}

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)
    monkeypatch.setattr("zikaron.mcp.connection._send_request", instant_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", blocking_read_response)

    envelope = connection.envelope(kind="mcp")
    task = asyncio.create_task(connection.request("search", {}, envelope=envelope))
    await asyncio.sleep(0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_socket.closed
    assert connection._sock is None

    worker_may_proceed.set()
    assert worker_finished.wait(timeout=5.0)


async def test_a_later_call_after_a_cancelled_one_gets_a_genuinely_different_socket(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not just "the old socket is closed," but the actual property that matters: the *next*
    ordinary call through this connection must establish and use a socket the cancelled call's
    own orphaned worker never touches, proving the two calls cannot collide on the wire.
    """
    worker_may_proceed = threading.Event()
    first_socket = _FakeSocket()
    second_socket = _FakeSocket()
    sockets_handed_out = [first_socket, second_socket]

    async def fake_connected_socket(self: ServiceConnection) -> _FakeSocket:
        if self._sock is not None:
            return self._sock  # type: ignore[return-value]
        sock = sockets_handed_out.pop(0)
        self._sock = sock  # type: ignore[assignment]
        return sock

    def blocking_send_request(
        sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope
        if sock is first_socket:
            worker_may_proceed.wait(timeout=5.0)
        # the second call's own send is instant — this fake only blocks for the first socket.

    def instant_read_response(_sock: object) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)
    monkeypatch.setattr("zikaron.mcp.connection._send_request", blocking_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", instant_read_response)

    first_task = asyncio.create_task(
        connection.request("remember", {}, envelope=connection.envelope(kind="mcp"))
    )
    await asyncio.sleep(0.05)
    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task
    assert first_socket.closed

    response = await connection.request("search", {}, envelope=connection.envelope(kind="mcp"))
    assert response["result"] == {"ok": True}
    current_socket: object = connection._sock
    assert current_socket is second_socket, "the later call must be using the fresh socket"

    worker_may_proceed.set()


async def test_cancelling_while_establishing_a_connection_closes_the_eventually_returned_socket(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_connected_socket` itself runs `connect_start_if_absent` in a shielded task specifically
    so a cancellation of the *awaiting* coroutine does not discard whatever socket that call
    eventually, genuinely establishes — this proves the returned socket is closed rather than
    leaked once the shielded task actually finishes.
    """
    worker_may_proceed = threading.Event()
    established_socket = _FakeSocket()

    def blocking_connect(*_args: object, **_kwargs: object) -> tuple[_FakeSocket, object]:
        worker_may_proceed.wait(timeout=5.0)
        return established_socket, object()

    monkeypatch.setattr("zikaron.mcp.connection.connect_start_if_absent", blocking_connect)

    async def fake_read_store_identity(_store_dir: object) -> None:
        return None

    monkeypatch.setattr("zikaron.mcp.connection._read_store_identity", fake_read_store_identity)

    task = asyncio.create_task(connection._connected_socket())
    await asyncio.sleep(0.05)

    task.cancel()
    # Release the underlying blocking call **before** awaiting the cancelled task, not after:
    # `_connected_socket`'s own cleanup path awaits `connect_task` to completion as part of
    # handling its own cancellation (it must, to know what to close), so awaiting the outer task
    # first would block on that same completion — and since nothing had released
    # `worker_may_proceed` yet, that wait would silently run out the fake's own 5 s timeout
    # instead of exercising a fast, explicit release, which is a materially different test.
    worker_may_proceed.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Give the shielded task's own completion handling inside `_connected_socket` a chance to run
    # after the underlying blocking call returns.
    for _ in range(50):
        if established_socket.closed:
            break
        await asyncio.sleep(0.05)
    assert established_socket.closed, "a socket established after cancellation must be closed"
    assert connection._sock is None
