"""`zikaron.hook.connect.connect_once`: the hook's own single-attempt start-if-absent sequence.

Unit tier: a hand-rolled fake UDS service (a background thread answering `health()` over a real
socket) rather than a real spawned `zikaron.service.main` subprocess — real enough to exercise
`connect_once`'s actual socket calls, cheap enough to run in the default tier.
`test_hook_connect_integration.py` covers the real-spawn, real-subprocess path this file cannot.
"""

import json
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.hook.connect import (
    HookTransportError,
    StoreIdentityError,
    _try_connect,
    connect_once,
    default_server_command,
    resolve_sock_path,
)


class _FakeService:
    """A UDS server, on a background thread, answering exactly one `health()` per connection
    with a fixed `{store_path, store_id}` — enough for `connect_once`'s identity check without
    the cost of a real `zikaron-service` process.
    """

    def __init__(self, sock_path: Path, *, store_path: str, store_id: str) -> None:
        self._store_path = store_path
        self._store_id = store_id
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
                self._answer_health(connection)

    def _answer_health(self, connection: socket.socket) -> None:
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = connection.recv(4096)
            if not chunk:
                return
            buffer += chunk
        request = json.loads(buffer.decode("utf-8"))
        response = {
            "jsonrpc": "2.0",
            "id": request.get("id", 1),
            "result": {
                "ready": True,
                "store_path": self._store_path,
                "store_id": self._store_id,
            },
        }
        connection.sendall((json.dumps(response) + "\n").encode("utf-8"))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._server.close()


@pytest.fixture
def sock_path(socket_dir: Path) -> Path:
    return socket_dir / "test.sock"


def test_connects_to_an_already_listening_service(sock_path: Path, tmp_path: Path) -> None:
    store_db_path = tmp_path / "memory.db"
    service = _FakeService(sock_path, store_path=str(store_db_path), store_id="abc-123")
    try:
        sock = connect_once(
            sock_path,
            store_db_path=store_db_path,
            store_id="abc-123",
            server_command=["python3", "-c", "pass"],  # never reached: already listening
        )
        sock.close()
    finally:
        service.close()


def test_store_id_none_skips_the_id_comparison_but_still_checks_the_path(
    sock_path: Path, tmp_path: Path
) -> None:
    """`store_id=None` is this client's own permanent case — every invocation is a fresh,
    single-shot process with no independent id to compare against, per `architecture.md`
    §"Store identity is verified, not assumed"'s own hook exception, not merely "this store does
    not exist on disk yet." The path is still checked unconditionally."""
    store_db_path = tmp_path / "memory.db"
    service = _FakeService(sock_path, store_path=str(store_db_path), store_id="whatever-it-is")
    try:
        sock = connect_once(
            sock_path,
            store_db_path=store_db_path,
            store_id=None,
            server_command=["python3", "-c", "pass"],
        )
        sock.close()
    finally:
        service.close()


def test_raises_on_a_store_id_mismatch(sock_path: Path, tmp_path: Path) -> None:
    store_db_path = tmp_path / "memory.db"
    service = _FakeService(sock_path, store_path=str(store_db_path), store_id="the-real-one")
    try:
        with pytest.raises(HookTransportError, match="store_identity"):
            connect_once(
                sock_path,
                store_db_path=store_db_path,
                store_id="a-different-one",
                server_command=["python3", "-c", "pass"],
            )
    finally:
        service.close()


def test_a_store_id_mismatch_raises_specifically_store_identity_error(
    sock_path: Path, tmp_path: Path
) -> None:
    """`StoreIdentityError` is the one subclass of `HookTransportError` a caller can check for to
    distinguish an identity mismatch from every other way this single attempt can fail — pinned
    at the exact type, not merely its base class, so `push.py`'s own classification (which checks
    for this subclass specifically before falling back to the generic base-class case) cannot
    silently regress to matching only the base type again.
    """
    store_db_path = tmp_path / "memory.db"
    service = _FakeService(sock_path, store_path=str(store_db_path), store_id="the-real-one")
    try:
        with pytest.raises(StoreIdentityError) as excinfo:
            connect_once(
                sock_path,
                store_db_path=store_db_path,
                store_id="a-different-one",
                server_command=["python3", "-c", "pass"],
            )
        assert excinfo.value.expected == "a-different-one"
        assert excinfo.value.actual == "the-real-one"
    finally:
        service.close()


def test_raises_on_a_store_path_mismatch(sock_path: Path, tmp_path: Path) -> None:
    service = _FakeService(sock_path, store_path="/some/other/path/memory.db", store_id="x")
    try:
        with pytest.raises(HookTransportError, match="store_identity"):
            connect_once(
                sock_path,
                store_db_path=tmp_path / "memory.db",
                store_id="x",
                server_command=["python3", "-c", "pass"],
            )
    finally:
        service.close()


def test_raises_hook_transport_error_when_nothing_ever_answers(
    sock_path: Path, tmp_path: Path
) -> None:
    """No socket file at all, and a spawn command that does nothing — the single attempt must
    exhaust its own poll deadline and raise rather than hang or retry."""
    with pytest.raises(HookTransportError):
        connect_once(
            sock_path,
            store_db_path=tmp_path / "memory.db",
            store_id=None,
            server_command=["python3", "-c", "pass"],  # exits immediately, binds nothing
        )


def test_a_non_absent_oserror_on_the_first_connect_attempt_propagates() -> None:
    """`_try_connect` distinguishes "nobody is listening yet" (`ENOENT`/`ECONNREFUSED`, recovered
    by spawning) from any other `OSError`, which must propagate rather than be silently treated
    as a reason to spawn a second server over a problem this single attempt has no business
    papering over. Tested directly against `_try_connect` itself rather than through the full
    `connect_once` sequence: `security.ensure_runtime_dir`'s own vetting runs first and would
    reject the obvious way to force a non-absent connect error (an inaccessible parent
    directory) before `_try_connect` is ever reached at all — a real, separate defence this test
    would otherwise have to defeat rather than exercise the one it targets.

    A too-long `sun_path` reliably raises `OSError` with `errno=None` — a Python-level guard
    raised before any syscall, confirmed directly rather than assumed — and `None` is not in
    `_ABSENT_SERVER_ERRNOS`, so this exercises the intended propagation branch.

    **It reaches `_try_connect` below `paths.socket_path`, bypassing that function's own refusal,
    and that is deliberate.** What is under test is how this module treats an `OSError` it did not
    anticipate; routing the path through the guard would substitute a `ZikaronError` raised
    somewhere else and test nothing here.

    **Built as an absolute, self-contained 300-character path rather than `tmp_path / (long
    name)`**, deliberately: `tmp_path`'s own base directory length varies by machine and CI
    environment, so a path that only exceeds the limit through the *combination* of `tmp_path`'s
    own depth and an appended long name could fall back under the limit on a system where
    `tmp_path` happens to be shorter — silently turning this into a test that raises nothing at
    all rather than one that raises the wrong thing, since `pytest.raises` would then fail loudly
    on "no exception raised" rather than passing for an unintended reason. A path guaranteed long
    on its own has no such dependency on where the test happens to run, and 300 clears every
    platform's limit rather than sitting near one.
    """
    with pytest.raises(OSError, match=r"path too long"):
        _try_connect(Path("/" + "x" * 300))


def test_a_health_failure_on_an_already_listening_socket_closes_it_and_propagates(
    tmp_path: Path,
    socket_dir: Path,
) -> None:
    """The already-listening branch's own cleanup: a connect that succeeds but whose `health()`
    call then fails must close the socket before re-raising, rather than leaking it — distinct
    from the spawn-and-poll branch's own retry-on-health-failure behaviour
    (`test_hook_connect_edge_cases.py`), since a bare-connect success is never retried within one
    single attempt, only cleaned up and propagated.
    """
    sock_path = socket_dir / "test.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)

    def _accept_and_answer_garbage() -> None:
        server.settimeout(2.0)
        connection, _ = server.accept()
        connection.recv(4096)  # drain the request
        connection.sendall(b"not json at all\n")
        connection.close()

    thread = threading.Thread(target=_accept_and_answer_garbage)
    thread.start()
    try:
        with pytest.raises(json.JSONDecodeError):
            connect_once(
                sock_path,
                store_db_path=tmp_path / "memory.db",
                store_id=None,
                server_command=["python3", "-c", "pass"],
            )
    finally:
        thread.join(timeout=5.0)
        server.close()


def test_default_server_command_uses_this_interpreter_and_the_service_module(
    tmp_path: Path,
) -> None:
    command = default_server_command(tmp_path / "s.sock", tmp_path / "store")
    assert command[1:3] == ["-m", "zikaron.service.main"]


def test_resolve_sock_path_is_a_pure_function_of_store_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    first = resolve_sock_path(tmp_path)
    second = resolve_sock_path(tmp_path)
    assert first == second
    assert first.suffix == ".sock"


def test_resolve_sock_path_lets_an_unusable_runtime_directory_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`paths.socket_path` refuses a runtime directory with no room in `sun_path`, and this
    client must let that reach `push.py`, which classifies it. Catching it here would strand the
    diagnosis: the hook would report a transport failure for a path it never attempted.

    Pure — no socket, no filesystem, no service. What it pins is the wiring, which the boundary
    tests in `test_service_paths.py` cannot see.
    """
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/" + "x" * 110)
    with pytest.raises(ZikaronError) as raised:
        resolve_sock_path(tmp_path)
    assert raised.value.code is ErrorCode.BAD_CONFIG


@pytest.fixture(autouse=True)
def _cleanup_sock_path(sock_path: Path) -> Iterator[None]:
    yield
    sock_path.unlink(missing_ok=True)
