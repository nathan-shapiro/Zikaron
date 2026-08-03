"""`zikaron.hook.push.run`: suppression, the single connect attempt, the `surface` RPC, and the
failure-relay path (`hook.log` plus a model-facing stdout instruction — see `push.py`'s own
module docstring for the measurement behind this shape: a live spike found a non-zero exit
suppresses stdout injection entirely and does not visibly surface stderr, so the design settled
on always exit 0 and relaying a failure through the one confirmed-working channel).

`architecture.md` §"Degraded modes" and §"Subagent sessions" are normative.
"""

import json
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from zikaron.hook import connect, push


class _FakeSurfaceService:
    """A UDS server answering exactly one `surface` call with a fixed response, real enough to
    exercise `push.run`'s actual socket path end to end without a real `zikaron-service`."""

    def __init__(
        self, sock_path: Path, *, store_db_path: Path, respond_with: dict[str, object]
    ) -> None:
        self._store_db_path = store_db_path
        self._respond_with = respond_with
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(sock_path))
        self._server.listen(4)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve_forever, daemon=True)
        self._thread.start()

    def _serve_forever(self) -> None:
        self._server.settimeout(0.05)
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            with connection:
                # `connect_once` sends `health()` first and then hands the *same* socket back to
                # its caller for the real request — `push.run` sends `surface` over that identical
                # connection rather than opening a second one, so this loop must answer as many
                # requests as arrive on one accepted connection, not exactly one.
                while True:
                    request = self._read_one_request(connection)
                    if request is None:
                        break
                    self._answer(connection, request)

    def _read_one_request(self, connection: socket.socket) -> dict[str, object] | None:
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = connection.recv(4096)
            if not chunk:
                return None
            buffer += chunk
        parsed = json.loads(buffer.decode("utf-8"))
        assert isinstance(parsed, dict)
        return parsed

    def _answer(self, connection: socket.socket, request: dict[str, object]) -> None:
        method = request.get("method")
        response: dict[str, object]
        if method == "health":
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id", 1),
                "result": {
                    "ready": True,
                    "store_path": str(self._store_db_path),
                    "store_id": "test-store-id",
                },
            }
        else:
            response = {"jsonrpc": "2.0", "id": request.get("id", 1), **self._respond_with}
        connection.sendall((json.dumps(response) + "\n").encode("utf-8"))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._server.close()


@pytest.fixture
def fake_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[dict[str, object]], _FakeSurfaceService]:
    """A fake service bound at exactly the socket path `push.run` will itself resolve for
    `cwd=tmp_path`, so `push.run` connects to it as though it were the real thing — patches
    `connect.resolve_sock_path` rather than the environment, since the real derivation involves a
    sha256 hash this fixture has no reason to reimplement."""
    sock_path = tmp_path / "test.sock"
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    store_db_path = store_dir / "memory.db"

    def _make(respond_with: dict[str, object]) -> _FakeSurfaceService:
        service = _FakeSurfaceService(
            sock_path, store_db_path=store_db_path, respond_with=respond_with
        )
        monkeypatch.setattr(connect, "resolve_sock_path", lambda _store_dir: sock_path)
        return service

    return _make


def test_a_matching_kiro_session_id_and_payload_proceeds_to_surface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "session-1")
    service = fake_service({"result": {"text": "- a gist\n- another gist"}})
    try:
        output = push.run(cwd=tmp_path, payload_session_id="session-1", prompt="what failed", pid=1)
        assert output == "- a gist\n- another gist"
    finally:
        service.close()


def test_a_subagent_session_is_suppressed_with_no_rpc_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "top-level")
    # No fake service bound at all: if push.run tried to connect, this would raise
    # HookTransportError rather than silently succeeding, so a passing "output is None" outcome
    # here is only possible if the RPC path was never reached.
    output = push.run(cwd=tmp_path, payload_session_id="a-subagent", prompt="p", pid=1)
    assert output is None


def test_a_missing_kiro_session_id_never_suppresses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    monkeypatch.delenv("KIRO_SESSION_ID", raising=False)
    service = fake_service({"result": {"text": ""}})
    try:
        output = push.run(cwd=tmp_path, payload_session_id="anything", prompt="p", pid=1)
        assert output == ""
    finally:
        service.close()


def test_a_store_busy_rejection_is_logged_and_relayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service(
        {"error": {"code": -32020, "message": "the store was locked", "data": {"verb": "surface"}}}
    )
    try:
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        assert "operator" in output
        assert "hook.log" in output
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "store_busy" in hook_log
        assert "-32020" in hook_log
    finally:
        service.close()


def test_a_bad_config_rejection_is_logged_and_relayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service(
        {"error": {"code": -32023, "message": "bad config", "data": {"key": "embed_dim"}}}
    )
    try:
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "bad_config" in hook_log
    finally:
        service.close()


def test_a_reindexing_rejection_is_logged_and_relayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service({"error": {"code": -32022, "message": "reindexing"}})
    try:
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "reindexing" in hook_log
    finally:
        service.close()


def test_a_schema_incompatible_rejection_is_logged_and_relayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service({"error": {"code": -32024, "message": "schema incompatible"}})
    try:
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "schema_incompatible" in hook_log
    finally:
        service.close()


def test_an_unrecognized_error_code_still_logs_something_identifiable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service({"error": {"code": -32005, "message": "bounds"}})
    try:
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "-32005" in hook_log
    finally:
        service.close()


def test_no_service_at_all_is_logged_and_relayed_as_transport_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service is not merely rejecting — it never even answers, and the single-attempt
    contract means `push.run` must not retry a second start-if-absent sequence: this deliberately
    points the spawn command at a script that does nothing, so the whole sequence exhausts its
    own poll deadline exactly once."""
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    (tmp_path / ".zikaron").mkdir()
    sock_path = tmp_path / "test.sock"
    monkeypatch.setattr(connect, "resolve_sock_path", lambda _store_dir: sock_path)
    monkeypatch.setattr(
        connect, "default_server_command", lambda _sock, _store: ["python3", "-c", "pass"]
    )
    output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
    assert output is not None
    hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
    assert "transport" in hook_log


def test_a_failure_output_names_hook_log_so_the_operator_can_verify_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    """The relay instruction is deliberately not the source of truth — `hook.log` is — so the
    returned text must point at it, per `push.py`'s own module docstring: "the model's relay only
    has to be a low-friction... nudge rather than the source of truth."""
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service({"error": {"code": -32020, "message": "busy"}})
    try:
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        assert ".zikaron/hook.log" in output
    finally:
        service.close()


def test_a_store_identity_mismatch_is_logged_and_relayed_with_its_own_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`hook.log` must name a store-identity mismatch specifically as `store_identity` with the
    design's own `-32030` code, not the generic `transport` an earlier version of this module's
    classification collapsed every `HookTransportError` into.

    Forced through the **path** comparison, the one identity check this hook can make without
    reading the store file itself — `connect.py`'s own module docstring states why the hook's
    identity check stays path-only rather than reading an existing store's own `store_id`: the
    hook has no persistent connection across invocations to have learned a real `store_id` from,
    and reading it directly would violate `architecture.md`'s "never a reader of the store, under
    any failure." A fake service reporting a `store_path` different from the one `push.run`
    itself derives for `tmp_path` is exactly the shape of a stale socket left over from a
    deleted-and-recreated store, or a hash collision — the case `architecture.md` §"Store
    identity is verified, not assumed" names as needing detection at all.
    """
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    (tmp_path / ".zikaron").mkdir()

    sock_path = tmp_path / "test.sock"
    service = _FakeSurfaceService(
        sock_path,
        store_db_path=tmp_path / "a-completely-different-store" / "memory.db",
        respond_with={"result": {"text": "should not matter"}},
    )
    # `_FakeSurfaceService._answer` reports `str(self._store_db_path)` in its own `health()`
    # response — a genuinely different path from the one `push.run` itself derives for
    # `tmp_path`, which is exactly the mismatch this test wants.
    try:
        monkeypatch.setattr(connect, "resolve_sock_path", lambda _store_dir: sock_path)
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "store_identity" in hook_log
        assert "-32030" in hook_log
    finally:
        service.close()


def test_an_unexpected_exception_from_the_socket_is_treated_as_a_transport_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    """A malformed response (not `SurfaceRejectionError`, not `HookTransportError`, but a bare
    `ConnectionError`/`OSError` from `rpc.surface_once` itself) must still be caught and
    reported."""
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service({"unexpected": "shape"})  # neither result nor error
    try:
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "transport" in hook_log
    finally:
        service.close()


def test_a_genuinely_unanticipated_exception_type_is_still_caught_and_relayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run()`'s own catch-all is a genuine `except Exception`, not a finite list of anticipated
    types — proven here with `RuntimeError`, which is none of `connect.HookTransportError`,
    `rpc.SurfaceRejectionError`, or `ZikaronError`, and would previously have propagated straight
    past this function into `main.py`'s own outermost catch-all, which reports nothing on either
    channel. Forced by monkeypatching `connect.connect_once` itself to raise `RuntimeError`
    directly, so this test does not depend on any real code path happening to raise that type.
    """
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    (tmp_path / ".zikaron").mkdir()

    def _raise_runtime_error(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("a genuinely unanticipated failure")

    monkeypatch.setattr(connect, "connect_once", _raise_runtime_error)
    output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
    assert output is not None
    assert "operator" in output
    hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
    assert "transport" in hook_log
    assert "unanticipated" not in hook_log, "the exception's own message must never reach hook.log"


def test_a_hostile_runtime_directory_is_logged_and_relayed_rather_than_propagating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`security.ensure_runtime_dir`'s own `ZikaronError` on a hostile runtime directory
    "propagates as itself" out of `connect.connect_once`, per that function's own docstring — but
    `push.run` must still catch it, log it, and relay it identically to every other failure kind,
    rather than letting it escape uncaught into `main.py`'s outermost catch-all, which would
    silently skip both `hook.log` and the model-facing relay for this one failure kind alone.

    Forced by making the *runtime directory itself* — not merely something under
    `XDG_RUNTIME_DIR` — a plain file rather than a directory: `resolve_sock_path` derives it as
    `XDG_RUNTIME_DIR/zikaron`, so `XDG_RUNTIME_DIR` is pointed at a real, ordinary directory that
    already contains a file named `zikaron`, which is exactly the shape
    `ensure_runtime_dir`'s own `stat.S_ISDIR` check rejects with a `ZikaronError` — confirmed
    directly, since a shorter-looking construction (`XDG_RUNTIME_DIR` itself a bogus file, with
    `/zikaron/<hash>.sock` appended beneath it) instead raises a plain `NotADirectoryError` from
    the OS at a *different* point, one component higher, which is a real but different failure
    shape this test is not the one aimed at.
    """
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    (tmp_path / ".zikaron").mkdir()
    xdg_runtime_dir = tmp_path / "runtime"
    xdg_runtime_dir.mkdir()
    (xdg_runtime_dir / "zikaron").write_text("this is a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg_runtime_dir))
    output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
    assert output is not None
    assert "operator" in output
    hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
    assert "bad_config" in hook_log
    # `_classify_failure`'s `ZikaronError` branch must preserve the error's own numeric code
    # alongside its name — an earlier version of that branch returned only the wire name, which
    # left `hook.log` naming `bad_config` with no accompanying `-32023`, contrary to
    # `architecture.md`'s "naming the kind and, where one exists, the wire error code."
    assert "-32023" in hook_log


def test_the_internal_deadline_expiring_after_a_slow_connect_degrades_without_ever_sending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_service: Callable[[dict[str, object]], _FakeSurfaceService],
) -> None:
    """`architecture.md`: "enforce an internal deadline of ~2 s" — this forces the deadline check
    itself to fire by monkeypatching `time.monotonic` to report elapsed time far past
    `push._DEADLINE_SECONDS` immediately after `connect.connect_once` returns, rather than
    actually sleeping in the test.
    """
    monkeypatch.setenv("KIRO_SESSION_ID", "s1")
    service = fake_service({"result": {"text": "should never be requested"}})
    try:
        real_monotonic = time.monotonic
        calls = {"count": 0}

        def _fake_monotonic() -> float:
            calls["count"] += 1
            if calls["count"] == 1:
                return real_monotonic()
            return real_monotonic() + push._DEADLINE_SECONDS + 10.0

        monkeypatch.setattr(time, "monotonic", _fake_monotonic)
        output = push.run(cwd=tmp_path, payload_session_id="s1", prompt="p", pid=1)
        assert output is not None
        hook_log = (tmp_path / ".zikaron" / "hook.log").read_text(encoding="utf-8")
        assert "deadline_exceeded" in hook_log
    finally:
        service.close()
