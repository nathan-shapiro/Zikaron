"""`zikaron.mcp.connection.ServiceConnection`'s per-instance `asyncio.Lock` — two concurrent
first calls through one connection must not both bootstrap independently or both establish a
socket; the whole round trip is serialized.
"""

import asyncio
from pathlib import Path

import pytest

from zikaron.mcp.connection import ServiceConnection


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServiceConnection:
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    return ServiceConnection(tmp_path)


async def test_two_concurrent_first_calls_establish_exactly_one_socket(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the lock, two concurrent calls could both observe `self._sock is None` before
    either finished establishing one. With the lock, the second call cannot even *enter*
    `_connected_socket` until the first call's entire `request()` body — establish, send, read,
    adopt — has finished and released the lock, which is what this test actually proves: not a
    race resolved in the fix's favour, but the race made unreachable, since the two calls can
    never run any part of their bodies concurrently at all.
    """
    establish_calls = 0
    entered_concurrently = False
    currently_inside = False

    async def fake_connected_socket(_self: ServiceConnection) -> _FakeSocket:
        nonlocal establish_calls, entered_concurrently, currently_inside
        establish_calls += 1
        if currently_inside:
            entered_concurrently = True
        currently_inside = True
        await asyncio.sleep(0)  # yield once, to give a genuine race a chance to manifest
        currently_inside = False
        return _FakeSocket()

    def fake_send_request(
        _sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope

    def fake_read_response(_sock: object) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)
    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", fake_read_response)

    envelope_a = connection.envelope(kind="mcp")
    envelope_b = connection.envelope(kind="mcp")

    results = await asyncio.gather(
        connection.request("search", {}, envelope=envelope_a),
        connection.request("search", {}, envelope=envelope_b),
    )

    assert establish_calls == 2, "both calls still each need a socket — the lock serializes, "
    "it does not let the second call skip establishing its own"
    assert not entered_concurrently, "the lock must never let both calls be inside at once"
    assert all(result["result"] == {"ok": True} for result in results)


async def test_a_label_adopted_by_the_first_of_two_concurrent_calls_is_used_by_the_second(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both calls build a bootstrap envelope (`session_id=None`) before either response is
    adopted, since `.envelope(kind=...)` is called before either `request()` call has a chance to
    run. Without the lock and the fresh re-read inside `request()`, the *second* call would send
    the stale bootstrap envelope its own `.envelope()` call captured, splitting one process's
    writes across two service-minted labels. This proves the second call instead sends whatever
    the first call's response actually adopted.
    """
    sent_session_ids: list[object] = []
    responses = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"ok": True},
            "client": {"session_id": "zk-adopted-by-the-first-call"},
        },
        {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
    ]

    async def fake_connected_socket(_self: ServiceConnection) -> _FakeSocket:
        return _FakeSocket()

    def fake_send_request(
        _sock: object,
        _method: str,
        _params: dict[str, object],
        *,
        envelope: object,
    ) -> None:
        sent_session_ids.append(envelope.session_id)  # type: ignore[attr-defined]

    def fake_read_response(_sock: object) -> dict[str, object]:
        return responses.pop(0)

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)
    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", fake_read_response)

    # Both envelopes are built while `_session_id` is still `None` — the exact stale-envelope
    # scenario the lock and the fresh re-read inside `request()` exist to correct.
    envelope_a = connection.envelope(kind="mcp")
    envelope_b = connection.envelope(kind="mcp")
    assert envelope_a.session_id is None
    assert envelope_b.session_id is None

    await connection.request("search", {}, envelope=envelope_a)
    await connection.request("amend", {}, envelope=envelope_b)

    assert sent_session_ids == [None, "zk-adopted-by-the-first-call"]
