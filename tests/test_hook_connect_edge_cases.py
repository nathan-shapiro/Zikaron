"""`zikaron.hook.connect`'s parsing of a `health()` answer and its poll's harder paths, driven
directly rather than through a whole `connect_once`.
"""

import json
import os
import socket
import subprocess
import threading
import time
import unittest.mock
from pathlib import Path

import pytest

from zikaron.hook import connect
from zikaron.hook.connect import (
    Health,
    HookTransportError,
    ServiceStartingError,
    _health,
    _poll_until_reachable,
)
from zikaron.service import paths


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


def test_a_health_answer_arriving_in_pieces_cannot_outrun_its_timeout() -> None:
    """The whole exchange gets `_CONNECT_TIMEOUT_SECONDS`, not each read, so how far a connect can
    run past a push's deadline is bounded. This peer sends a byte at a time for 1.5 s and then
    closes; a timeout set per read would wait for the close and raise something else."""
    client, server = _connected_pair()
    stop = threading.Event()

    def _dribble() -> None:
        server.recv(4096)
        until = time.monotonic() + 1.5
        while time.monotonic() < until and not stop.wait(0.05):
            server.sendall(b" ")
        server.close()

    thread = threading.Thread(target=_dribble)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            _health(client)
        assert time.monotonic() - started < 2 * connect._CONNECT_TIMEOUT_SECONDS
    finally:
        stop.set()
        thread.join(timeout=5.0)
        client.close()


class TestHealthReadsWhetherTheServiceIsStillStarting:
    @staticmethod
    def _health_answering(extra: dict[str, object]) -> Health:
        client, server = _connected_pair()
        try:
            result = {"ready": True, "store_path": "x", "store_id": "y", **extra}
            server.sendall(
                (json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}) + "\n").encode()
            )
            return _health(client)
        finally:
            client.close()
            server.close()

    def test_a_young_service_still_loading_its_model_is_still_starting(self) -> None:
        health = self._health_answering({"model_loaded": False, "uptime_seconds": 1.5})
        assert health.still_loading_within(8.0)
        assert not health.still_loading_within(1.0)

    def test_a_loaded_model_is_not_a_start_however_young(self) -> None:
        health = self._health_answering({"model_loaded": True, "uptime_seconds": 0.1})
        assert not health.still_loading_within(8.0)

    def test_a_service_too_old_to_report_reads_as_loaded(self) -> None:
        health = self._health_answering({})
        assert health.model_loaded is True
        assert health.uptime_seconds is None
        assert not health.still_loading_within(8.0)

    def test_an_uptime_that_is_not_a_number_is_not_read_as_one(self) -> None:
        health = self._health_answering({"model_loaded": False, "uptime_seconds": True})
        assert health.uptime_seconds is None
        assert not health.still_loading_within(8.0)


class TestPollKeepsGoingWhenItsChildDefersToAnotherService:
    def test_a_child_that_exits_because_another_service_holds_the_store_keeps_the_poll_going(
        self, socket_dir: Path
    ) -> None:
        """That child found the store held: the other service is the one to wait for, so its exit
        is no reason to stop looking. The other service here binds once the child has exited."""
        sock_path = socket_dir / "test.sock"
        deferred = unittest.mock.create_autospec(subprocess.Popen, instance=True)
        deferred.poll.return_value = os.EX_TEMPFAIL
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        def _bind_late_and_answer() -> None:
            time.sleep(0.3)
            server.bind(str(sock_path))
            server.listen(1)
            server.settimeout(5.0)
            connection, _ = server.accept()
            connection.recv(4096)
            result = {"ready": True, "store_path": "the-path", "store_id": "the-id"}
            reply = {"jsonrpc": "2.0", "id": 1, "result": result}
            connection.sendall((json.dumps(reply) + "\n").encode())
            connection.close()

        thread = threading.Thread(target=_bind_late_and_answer, daemon=True)
        thread.start()
        try:
            sock, health = _poll_until_reachable(
                sock_path, deadline=time.monotonic() + 5.0, child=deferred
            )
            sock.close()
            assert health.store_path == "the-path"
        finally:
            thread.join(timeout=5.0)
            server.close()


class TestAPushQueuedBehindAStalledStartIsNotAStart:
    """At the deadline, this push's own child is still alive. If it is the one starting the
    service, that is a start; if it is waiting behind another holder that is still named — not
    shutting down — and has shown no sign of life for too long, it is not, and the operator has to
    hear about it. A holder in shutdown names nobody."""

    @staticmethod
    def _poll_at_the_deadline(
        socket_dir: Path, *, holder: str, held_for: float, child_pid: int = 999_999
    ) -> None:
        sock_path = socket_dir / "test.sock"
        lock = paths.service_lock_path(sock_path)
        lock.write_text(holder, encoding="ascii")
        named_at = time.time() - held_for
        os.utime(lock, (named_at, named_at))
        still_running = unittest.mock.create_autospec(subprocess.Popen, instance=True)
        still_running.poll.return_value = None
        still_running.pid = child_pid
        _poll_until_reachable(sock_path, deadline=time.monotonic() - 1.0, child=still_running)

    def test_a_live_holder_that_has_shown_no_life_too_long_is_reported(
        self, socket_dir: Path
    ) -> None:
        with pytest.raises(HookTransportError) as raised:
            self._poll_at_the_deadline(socket_dir, holder=f"{os.getpid()}\n", held_for=600.0)
        assert not isinstance(raised.value, ServiceStartingError)

    def test_a_holder_alive_under_another_uid_counts_as_alive(
        self, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`kill(pid, 0)` answers `EPERM` for a live process this uid may not signal — a pid reused
        after a crashed holder left its name behind."""

        def _not_ours(_pid: int, _signal: int) -> None:
            raise PermissionError

        monkeypatch.setattr(os, "kill", _not_ours)
        with pytest.raises(HookTransportError) as raised:
            self._poll_at_the_deadline(socket_dir, holder="4242\n", held_for=600.0)
        assert not isinstance(raised.value, ServiceStartingError)

    @pytest.mark.parametrize(
        ("holder", "held_for", "child_pid"),
        [
            pytest.param(f"{os.getpid()}\n", 5.0, 999_999, id="young-holder"),
            pytest.param(f"{os.getpid()}\n", 600.0, os.getpid(), id="the-holder-is-this-child"),
            pytest.param("", 600.0, 999_999, id="no-holder-named-as-in-shutdown"),
            pytest.param(f"{2**22 + 7}\n", 600.0, 999_999, id="holder-gone"),
        ],
    )
    def test_anything_else_is_still_a_start(
        self, socket_dir: Path, holder: str, held_for: float, child_pid: int
    ) -> None:
        with pytest.raises(ServiceStartingError):
            self._poll_at_the_deadline(
                socket_dir, holder=holder, held_for=held_for, child_pid=child_pid
            )


class TestPollUntilReachableRetriesAfterAConnectThatFailsHealth:
    def test_a_connection_that_answers_health_badly_is_retried(self, socket_dir: Path) -> None:
        """A server that accepts a connection and then answers `health()` with a malformed
        response (rather than not answering at all) must be treated as "not yet ready" and
        polled again — not raised on immediately — since a service mid-startup can legitimately
        accept sockets before it can answer correctly.
        """
        sock_path = socket_dir / "test.sock"
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
        still_running = unittest.mock.create_autospec(subprocess.Popen, instance=True)
        still_running.poll.return_value = None
        try:
            sock, health = _poll_until_reachable(
                sock_path, deadline=time.monotonic() + 5.0, child=still_running
            )
            sock.close()
            assert health.store_path == "the-path"
            assert attempts["count"] == 2
        finally:
            thread.join(timeout=5.0)
            server.close()
