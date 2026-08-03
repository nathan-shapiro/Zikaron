"""Additional coverage for `zikaron.hook.connect`'s malformed-response and retry paths.

`_health`'s three ways of rejecting a response that connected successfully but answered wrong,
and `_poll_until_reachable`'s retry-after-a-connect-that-then-fails-health branch — both real
behaviour paths worth their own assertions rather than left as untested lines a coverage report
would otherwise leave silent about.
"""

import json
import socket
import threading
from pathlib import Path

import pytest

from zikaron.hook.connect import _health, _poll_until_reachable


def _connected_pair() -> tuple[socket.socket, socket.socket]:
    return socket.socketpair()


class TestHealthRejectsAMalformedResponse:
    def test_a_non_dict_top_level_response_raises(self) -> None:
        client, server = _connected_pair()
        try:
            server.sendall(b"[1, 2, 3]\n")
            with pytest.raises(ConnectionError, match="not a JSON object"):
                _health(client)
        finally:
            client.close()
            server.close()

    def test_a_response_with_no_result_object_raises(self) -> None:
        client, server = _connected_pair()
        try:
            server.sendall((json.dumps({"jsonrpc": "2.0", "id": 1}) + "\n").encode())
            with pytest.raises(ConnectionError, match="did not return a result"):
                _health(client)
        finally:
            client.close()
            server.close()

    def test_a_ready_value_that_is_truthy_but_not_the_json_boolean_true_raises(self) -> None:
        """Mirrors `zikaron.service.lifecycle._health`'s own reasoning exactly: a JSON string
        `"false"` is truthy in Python but must not be accepted as readiness."""
        client, server = _connected_pair()
        try:
            response = {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"ready": "false", "store_path": "x", "store_id": "y"},
            }
            server.sendall((json.dumps(response) + "\n").encode())
            with pytest.raises(ConnectionError, match="not the JSON boolean true"):
                _health(client)
        finally:
            client.close()
            server.close()


class TestPollUntilReachableRetriesAfterAConnectThatFailsHealth:
    def test_a_connection_that_answers_health_badly_is_retried(self, tmp_path: Path) -> None:
        """A server that accepts a connection and then answers `health()` with a malformed
        response (rather than not answering at all) must be treated as "not yet ready" and
        polled again — not raised on immediately — since a service mid-startup can legitimately
        accept sockets before it can answer correctly.
        """
        sock_path = tmp_path / "test.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock_path))
        server.listen(4)
        attempts = {"count": 0}

        def _serve() -> None:
            server.settimeout(2.0)
            # First connection: accept, then answer nothing useful and close — simulates a
            # service accepting before it can answer health() correctly.
            first, _ = server.accept()
            attempts["count"] += 1
            first.close()
            # Second connection: answer correctly.
            second, _ = server.accept()
            attempts["count"] += 1
            request = second.recv(4096)
            parsed = json.loads(request.decode("utf-8").strip())
            response = {
                "jsonrpc": "2.0",
                "id": parsed.get("id", 1),
                "result": {"ready": True, "store_path": "the-path", "store_id": "the-id"},
            }
            second.sendall((json.dumps(response) + "\n").encode())
            second.close()

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        try:
            sock, health = _poll_until_reachable(sock_path)
            sock.close()
            assert health.store_path == "the-path"
            assert attempts["count"] == 2
        finally:
            thread.join(timeout=5.0)
            server.close()
