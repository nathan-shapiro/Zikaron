"""`zikaron.hook.rpc`: frame one `memory_surface` or `knowledge_remind` request, parse its one
response line.

Uses `socket.socketpair()` as a fake service: a real, connected pair of sockets, so `surface_once`
exercises real `sendall`/`recv` against real file descriptors rather than a mock of the socket API
— exactly the reasoning `coding-standards.md` §4 gives for keeping a real store in the default
tier, applied here to a real socket pair instead of a real database.
"""

import json
import socket
import threading
import time

import pytest

from tests.loop_lateness import thread_lateness
from zikaron.hook.envelope import HookEnvelope
from zikaron.hook.rpc import (
    HookDeadline,
    NotSentError,
    ServiceRejectionError,
    remind_once,
    surface_once,
)

_ENVELOPE = HookEnvelope(session_id="a-session", kind="hook", pid=1234, op_id=None)
_DEADLINE = 1_900_000_000_000


def _soon() -> HookDeadline:
    """A deadline no test here reaches unless it means to, sent as `_DEADLINE`."""
    return HookDeadline(at_ms=_DEADLINE, by=time.monotonic() + 5.0)


def _respond(server: socket.socket, response: dict[str, object]) -> None:
    server.sendall((json.dumps(response) + "\n").encode("utf-8"))


def test_sends_a_well_formed_surface_request() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": "irrelevant"}})
        surface_once(
            client,
            prompt="what failed",
            limit=5,
            envelope=_ENVELOPE,
            deadline=_soon(),
        )
        sent = server.recv(65536).decode("utf-8")
        request = json.loads(sent)
        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "memory_surface"
        assert request["params"]["prompt"] == "what failed"
        assert request["params"]["limit"] == 5
        assert request["params"]["deadline_at_ms"] == _DEADLINE
        assert request["params"]["client"] == {
            "session_id": "a-session",
            "kind": "hook",
            "pid": 1234,
            "op_id": None,
        }
    finally:
        client.close()
        server.close()


def test_returns_the_text_on_a_successful_result() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": "gist one\ngist two"}})
        text = surface_once(
            client,
            prompt="p",
            limit=5,
            envelope=_ENVELOPE,
            deadline=_soon(),
        )
        server.recv(65536)  # drain the request so the socket does not matter to the assertion
        assert text == "gist one\ngist two"
    finally:
        client.close()
        server.close()


def test_raises_surface_rejection_on_an_error_response() -> None:
    client, server = socket.socketpair()
    try:
        _respond(
            server,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32020, "message": "store busy", "data": {"verb": "surface"}},
            },
        )
        with pytest.raises(ServiceRejectionError) as excinfo:
            surface_once(
                client,
                prompt="p",
                limit=5,
                envelope=_ENVELOPE,
                deadline=_soon(),
            )
        assert excinfo.value.code == -32020
        assert excinfo.value.message == "store busy"
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_the_response_is_not_a_json_object() -> None:
    client, server = socket.socketpair()
    try:
        server.sendall(b"[1, 2, 3]\n")
        with pytest.raises(ConnectionError):
            surface_once(
                client,
                prompt="p",
                limit=5,
                envelope=_ENVELOPE,
                deadline=_soon(),
            )
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_the_result_has_no_text_field() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"not_text": "x"}})
        with pytest.raises(ConnectionError):
            surface_once(
                client,
                prompt="p",
                limit=5,
                envelope=_ENVELOPE,
                deadline=_soon(),
            )
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize("text", [None, 7], ids=["null", "not a string"])
def test_a_push_answered_with_no_text_string_is_a_connection_error(text: object) -> None:
    """`null` is a reminder's answer for none due; a push always has a block to give."""
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": text}})
        with pytest.raises(ConnectionError):
            surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE, deadline=_soon())
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize(("text", "expected"), [(None, None), ("a line", "a line")])
def test_a_reminder_s_text_is_a_string_or_null(text: object, expected: str | None) -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": text}})
        answered = remind_once(
            client, paths=["/a"], agent_id=None, envelope=_ENVELOPE, deadline=_soon()
        )
        assert answered == expected
        assert "agent_id" not in json.loads(server.recv(65536))["params"]
    finally:
        client.close()
        server.close()


def test_a_reminder_s_text_that_is_neither_is_a_connection_error() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": 7}})
        with pytest.raises(ConnectionError):
            remind_once(client, paths=["/a"], agent_id="a1", envelope=_ENVELOPE, deadline=_soon())
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_neither_result_nor_error_is_present() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1})
        with pytest.raises(ConnectionError):
            surface_once(
                client,
                prompt="p",
                limit=5,
                envelope=_ENVELOPE,
                deadline=_soon(),
            )
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_the_error_object_is_malformed() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "error": {"message": "no code"}})
        with pytest.raises(ConnectionError):
            surface_once(
                client,
                prompt="p",
                limit=5,
                envelope=_ENVELOPE,
                deadline=_soon(),
            )
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_the_socket_closes_before_a_full_line() -> None:
    """A response that starts but is cut off before its terminating newline arrives — the exact
    case `surface_once`'s own "connection closed before a full response was read" raise guards
    against. Requires a background thread on the server side: `surface_once`'s `sendall` and the
    server's own drain-then-respond sequence must interleave, since both run against the same
    pair of blocking sockets and neither side may be left waiting on the other with nothing sent.
    """
    client, server = socket.socketpair()

    def _respond_with_a_cut_off_line() -> None:
        server.recv(65536)  # drain the request, so the client's own sendall can complete
        server.sendall(b'{"jsonrpc": "2.0"')  # a partial response, no trailing newline
        server.close()

    thread = threading.Thread(target=_respond_with_a_cut_off_line)
    thread.start()
    try:
        with pytest.raises(ConnectionError, match="closed before a full response"):
            surface_once(
                client,
                prompt="p",
                limit=5,
                envelope=_ENVELOPE,
                deadline=_soon(),
            )
    finally:
        thread.join(timeout=5.0)
        client.close()
        server.close()


def test_an_answer_arriving_in_pieces_cannot_outrun_the_deadline() -> None:
    """A socket timeout bounds one call, not the exchange: a peer sending a byte at a time, each
    well inside the timeout, would hold a timeout that is set once open for as long as it kept
    sending. This one sends for 3 s, so a deadline that is not re-armed shows as the full 3 s."""
    client, server = socket.socketpair()
    stop = threading.Event()

    def _dribble() -> None:
        server.recv(65536)
        until = time.monotonic() + 3.0
        while time.monotonic() < until and not stop.wait(0.05):
            server.sendall(b" ")

    thread = threading.Thread(target=_dribble)
    thread.start()
    try:
        with thread_lateness() as lateness:
            started = time.monotonic()
            with pytest.raises(TimeoutError):
                surface_once(
                    client,
                    prompt="p",
                    limit=5,
                    envelope=_ENVELOPE,
                    deadline=HookDeadline(at_ms=_DEADLINE, by=started + 0.3),
                )
            elapsed = time.monotonic() - started
        assert elapsed - lateness.seconds < 2.0, (elapsed, lateness)
    finally:
        stop.set()
        thread.join(timeout=5.0)
        client.close()
        server.close()


def test_a_deadline_already_past_times_out_without_sending() -> None:
    """Its own subclass, because a push that never reached the service is `deadline_exceeded`,
    not `unanswered` — which says the service received it."""
    client, server = socket.socketpair()
    try:
        with pytest.raises(NotSentError):
            surface_once(
                client,
                prompt="p",
                limit=5,
                envelope=_ENVELOPE,
                deadline=HookDeadline(at_ms=_DEADLINE, by=time.monotonic() - 1.0),
            )
        server.setblocking(False)
        with pytest.raises(BlockingIOError):
            server.recv(65536)
    finally:
        client.close()
        server.close()


def test_the_bootstrap_form_sends_a_null_session_id() -> None:
    client, server = socket.socketpair()
    try:
        bootstrap = HookEnvelope(session_id=None, kind="hook", pid=1, op_id=None)
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": ""}})
        surface_once(
            client,
            prompt="p",
            limit=5,
            envelope=bootstrap,
            deadline=_soon(),
        )
        sent = json.loads(server.recv(65536).decode("utf-8"))
        assert sent["params"]["client"]["session_id"] is None
    finally:
        client.close()
        server.close()
