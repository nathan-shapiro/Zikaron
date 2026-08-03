"""`zikaron.mcp.connection.ServiceConnection.request` — the retry-once bound applies only to a
request whose `send` accepted **zero** bytes; a failure with positive send progress, or any
failure discovered while reading the response, raises `AmbiguousMutationError` rather than being
silently retried, since the service may already have received and committed a mutation whose
outcome the client cannot observe.
"""

from pathlib import Path

import pytest

from zikaron.mcp.connection import (
    AmbiguousMutationError,
    ServiceConnection,
    _send_request,
    _ZeroProgressSendError,
)
from zikaron.service.envelope import ClientEnvelope


class _FakeSocket:
    """A `socket.socket`-shaped placeholder with a real, harmless `.close()` — `request()` closes
    whatever `_connected_socket` handed back on every failure path, so a bare `object()` would
    raise `AttributeError` from inside the code under test rather than from the assertion this
    file is trying to make.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServiceConnection:
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    return ServiceConnection(tmp_path)


def _stub_connected_socket(monkeypatch: pytest.MonkeyPatch, sockets: list[_FakeSocket]) -> None:
    """`_connected_socket` returns each of `sockets` in order — one call per attempt, matching
    what a real reconnect-after-close sequence would hand back."""
    queue = list(sockets)

    async def fake_connected_socket(_self: ServiceConnection) -> _FakeSocket:
        return queue.pop(0)

    monkeypatch.setattr(ServiceConnection, "_connected_socket", fake_connected_socket)


async def test_a_zero_progress_send_failure_is_retried_once_through_a_fresh_connection(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case `architecture.md` actually names: a held socket found dead — `_send_request`'s
    own manual send loop accepted zero bytes of this request before failing, so retrying through
    a fresh connection is safe."""
    _stub_connected_socket(monkeypatch, [_FakeSocket("first"), _FakeSocket("second")])

    calls: list[str] = []

    def fake_send_request(
        _sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope
        calls.append("send")
        if len(calls) == 1:
            raise _ZeroProgressSendError(ConnectionError("held socket was already dead"))

    def fake_read_response(_sock: object) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", fake_read_response)

    response = await connection.request("search", {}, envelope=connection.envelope(kind="mcp"))
    assert response["result"] == {"ok": True}
    assert calls == ["send", "send"], "the second attempt must actually re-send"


async def test_a_send_failure_with_positive_progress_is_ambiguous_and_not_retried(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact distinction that makes byte-tracking necessary: `socket.sendall`'s own
    documentation states that once a send fails, "it's impossible to tell how much data has been
    sent" — so a send failure that is **not** the tracked zero-progress case must be treated
    identically to a response-read failure (ambiguous, never retried), never assumed safe merely
    because it failed during the send half rather than the receive half.
    """
    _stub_connected_socket(monkeypatch, [_FakeSocket("only")])

    send_calls = 0

    def fake_send_request(
        _sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope
        nonlocal send_calls
        send_calls += 1
        # A bare OSError, not wrapped in `_ZeroProgressSendError` — representing the real
        # `_send_request`'s own behavior once even one byte has been accepted by the socket.
        raise ConnectionError("connection reset after partially sending the request")

    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)

    with pytest.raises(AmbiguousMutationError) as excinfo:
        await connection.request("remember", {}, envelope=connection.envelope(kind="mcp"))

    assert excinfo.value.method == "remember"
    assert send_calls == 1, "a send failure with positive progress must never be retried"


async def test_a_failure_reading_the_response_raises_ambiguous_mutation_error_and_is_not_retried(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact case this fix exists for: `remember` may have already committed on the service,
    with only its response lost — silently retrying would risk creating a second row, so this
    must raise rather than resend.
    """
    _stub_connected_socket(monkeypatch, [_FakeSocket("only")])

    send_calls = 0
    read_calls = 0

    def fake_send_request(
        _sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope
        nonlocal send_calls
        send_calls += 1

    def fake_read_response(_sock: object) -> dict[str, object]:
        nonlocal read_calls
        read_calls += 1
        raise ConnectionError("connection reset while reading the response")

    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", fake_read_response)

    with pytest.raises(AmbiguousMutationError) as excinfo:
        await connection.request("remember", {}, envelope=connection.envelope(kind="mcp"))

    assert excinfo.value.method == "remember"
    assert send_calls == 1, "the request must be sent exactly once — never resent after this"
    assert read_calls == 1


async def test_the_socket_is_discarded_after_an_ambiguous_failure_so_a_later_call_reconnects(
    connection: ServiceConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The socket a lost response came back on is not trustworthy either way — this asserts the
    connection is dropped rather than reused, without asserting on `request` retrying (which it
    must not, per the sibling test above): the *next*, separate tool call is what reconnects.
    """
    first_socket = _FakeSocket("first")
    second_socket = _FakeSocket("second")
    _stub_connected_socket(monkeypatch, [first_socket, second_socket])

    read_attempts = 0

    def fake_send_request(
        _sock: object, _method: str, _params: dict[str, object], *, envelope: object
    ) -> None:
        del envelope

    def fake_read_response(sock: _FakeSocket) -> dict[str, object]:
        nonlocal read_attempts
        read_attempts += 1
        if sock is first_socket:
            raise ConnectionError("lost")
        return {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    monkeypatch.setattr("zikaron.mcp.connection._send_request", fake_send_request)
    monkeypatch.setattr("zikaron.mcp.connection._read_response", fake_read_response)

    with pytest.raises(AmbiguousMutationError):
        await connection.request("remember", {}, envelope=connection.envelope(kind="mcp"))
    assert first_socket.closed
    assert connection._sock is None

    # A later, separate tool call reconnects and succeeds normally — this is not the same
    # `request()` call retrying; it is the model calling a tool again, which is the caller's own
    # decision this module has no opinion about.
    response = await connection.request("search", {}, envelope=connection.envelope(kind="mcp"))
    assert response["result"] == {"ok": True}
    assert read_attempts == 2


class _SocketThatFailsAfterNBytes:
    """A raw `send()`-shaped double that accepts up to `fail_after` bytes across however many
    calls it takes, then raises on the next call — this is what actually exercises
    `_send_request`'s own manual send loop and its byte-counting, rather than a fake that
    replaces the whole function and can only assert on the dispatcher around it.
    """

    def __init__(self, fail_after: int) -> None:
        self._remaining_before_failure = fail_after
        self.total_sent = 0

    def send(self, data: bytes) -> int:
        if self._remaining_before_failure <= 0:
            raise ConnectionError("socket died mid-send")
        accepted = min(len(data), self._remaining_before_failure)
        self._remaining_before_failure -= accepted
        self.total_sent += accepted
        return accepted


class _DiesOnFirstSend:
    """A raw `send()`-shaped double that never accepts any bytes at all."""

    def send(self, _data: bytes) -> int:
        raise ConnectionError("dead before anything was written")


def test_send_request_reports_zero_progress_when_the_first_send_call_itself_fails() -> None:
    """`_send_request`'s own manual send loop, exercised directly: a socket that fails on the
    very first `send()` call has accepted zero bytes, which is the one case
    `ServiceConnection.request` treats as safe to retry."""
    with pytest.raises(_ZeroProgressSendError):
        _send_request(_DiesOnFirstSend(), "search", {}, envelope=_bare_envelope())  # type: ignore[arg-type]


def test_send_request_propagates_a_bare_error_once_any_byte_was_already_accepted() -> None:
    """The exact distinction `socket.sendall`'s own documentation warns is otherwise
    unrecoverable: once a send has accepted at least one byte and then fails, `_send_request`
    must **not** raise the retry-safe `_ZeroProgressSendError` — this proves the loop tracks
    real cumulative progress rather than only "did the very first call fail."
    """
    fake_socket = _SocketThatFailsAfterNBytes(fail_after=5)
    params = {"query": "something long enough that the fake socket's small budget is exceeded"}
    with pytest.raises(ConnectionError) as excinfo:
        _send_request(fake_socket, "search", params, envelope=_bare_envelope())  # type: ignore[arg-type]
    assert not isinstance(excinfo.value, _ZeroProgressSendError)
    assert fake_socket.total_sent == 5, "the loop must have accepted exactly the modeled budget"


class _ReturnsZeroOnFirstCall:
    """A raw `send()`-shaped double that returns `0` (no exception) on its very first call —
    the case the socket API permits without raising: no bytes accepted, connection stuck.
    """

    def __init__(self) -> None:
        self.call_count = 0

    def send(self, _data: bytes) -> int:
        self.call_count += 1
        return 0


class _ReturnsZeroAfterNBytes:
    """A raw `send()`-shaped double that accepts `accept_first` bytes on its first call, then
    returns `0` (no exception) on every call after — modeling a connection that made some
    progress and then stalled without the OS ever reporting it as an error.
    """

    def __init__(self, accept_first: int) -> None:
        self._accept_first = accept_first
        self.call_count = 0
        self.total_sent = 0

    def send(self, data: bytes) -> int:
        self.call_count += 1
        if self.call_count == 1:
            accepted = min(len(data), self._accept_first)
            self.total_sent += accepted
            return accepted
        return 0


def test_send_request_terminates_and_reports_zero_progress_when_send_returns_zero_immediately() -> (
    None
):
    """The socket API permits `send()` to return `0` — signalling no forward progress — without
    raising at all, and `_send_request`'s loop must not call `send()` again unconditionally on
    that outcome: doing so with an unchanged remaining payload would call it forever, and this
    function runs synchronously inside `ServiceConnection.request`'s own `asyncio.Lock`, so an
    infinite loop here would block every other call through the connection and the event loop
    itself. A returned `0` on the very first call, with zero bytes ever accepted, is the
    retry-safe case.
    """
    fake_socket = _ReturnsZeroOnFirstCall()
    with pytest.raises(_ZeroProgressSendError):
        _send_request(fake_socket, "search", {}, envelope=_bare_envelope())  # type: ignore[arg-type]
    assert fake_socket.call_count == 1, "the loop must not call send() again after a 0 return"


def test_send_request_terminates_and_raises_ambiguous_when_send_returns_zero_after_progress() -> (
    None
):
    """The same `0`-return case, but after some bytes were already genuinely accepted — this must
    raise a bare error (never the retry-safe `_ZeroProgressSendError`), for the identical reason a
    positive-progress exception must not be retried: the service side of that partial send is
    unknown, and the loop must still terminate rather than spin regardless."""
    fake_socket = _ReturnsZeroAfterNBytes(accept_first=5)
    params = {"query": "something long enough that the fake socket's small budget is exceeded"}
    with pytest.raises(ConnectionError) as excinfo:
        _send_request(fake_socket, "search", params, envelope=_bare_envelope())  # type: ignore[arg-type]
    assert not isinstance(excinfo.value, _ZeroProgressSendError)
    assert fake_socket.call_count == 2, "the loop must terminate on the very next 0 return"
    assert fake_socket.total_sent == 5


def _bare_envelope() -> ClientEnvelope:
    return ClientEnvelope(session_id=None, kind="mcp", pid=1, op_id=None)
