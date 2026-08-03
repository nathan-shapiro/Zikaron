"""`zikaron.hook.rpc.surface_once`: frame one `surface` request, parse its one response line.

Uses `socket.socketpair()` as a fake service: a real, connected pair of sockets, so `surface_once`
exercises real `sendall`/`recv` against real file descriptors rather than a mock of the socket API
— exactly the reasoning `coding-standards.md` §4 gives for keeping a real store in the default
tier, applied here to a real socket pair instead of a real database.
"""

import json
import socket
import threading

import pytest

from zikaron.hook.rpc import SurfaceRejectionError, surface_once
from zikaron.service.envelope import ClientEnvelope

_ENVELOPE = ClientEnvelope(session_id="a-session", kind="hook", pid=1234, op_id=None)


def _respond(server: socket.socket, response: dict[str, object]) -> None:
    server.sendall((json.dumps(response) + "\n").encode("utf-8"))


def test_sends_a_well_formed_surface_request() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": "irrelevant"}})
        surface_once(client, prompt="what failed", limit=5, envelope=_ENVELOPE)
        sent = server.recv(65536).decode("utf-8")
        request = json.loads(sent)
        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "surface"
        assert request["params"]["prompt"] == "what failed"
        assert request["params"]["limit"] == 5
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
        text = surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE)
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
        with pytest.raises(SurfaceRejectionError) as excinfo:
            surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE)
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
            surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE)
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_the_result_has_no_text_field() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"not_text": "x"}})
        with pytest.raises(ConnectionError):
            surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE)
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_neither_result_nor_error_is_present() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1})
        with pytest.raises(ConnectionError):
            surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE)
    finally:
        client.close()
        server.close()


def test_raises_connection_error_when_the_error_object_is_malformed() -> None:
    client, server = socket.socketpair()
    try:
        _respond(server, {"jsonrpc": "2.0", "id": 1, "error": {"message": "no code"}})
        with pytest.raises(ConnectionError):
            surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE)
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
            surface_once(client, prompt="p", limit=5, envelope=_ENVELOPE)
    finally:
        thread.join(timeout=5.0)
        client.close()
        server.close()


def test_the_bootstrap_form_sends_a_null_session_id() -> None:
    client, server = socket.socketpair()
    try:
        bootstrap = ClientEnvelope(session_id=None, kind="hook", pid=1, op_id=None)
        _respond(server, {"jsonrpc": "2.0", "id": 1, "result": {"text": ""}})
        surface_once(client, prompt="p", limit=5, envelope=bootstrap)
        sent = json.loads(server.recv(65536).decode("utf-8"))
        assert sent["params"]["client"]["session_id"] is None
    finally:
        client.close()
        server.close()
