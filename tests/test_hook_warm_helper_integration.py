"""`zikaron.hook.warm_helper.run` against the real `zikaron.service.main` process.

Integration tier, per `coding-standards.md` §4. This is what `spawn_warm.py` actually invokes as a
detached child under `python -m zikaron.hook.warm_helper <sock_path> <store_dir>` — verified here
against the real service rather than only through `test_hook_warm_helper.py`'s unit-tier pieces.
"""

import asyncio
import json
import os
import signal
import socket
import time
from contextlib import suppress
from pathlib import Path
from typing import Final

import pytest

import zikaron.hook.warm_helper as warm_helper_module
from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.core.store.store import Store
from zikaron.hook.warm_helper import run
from zikaron.service.lifecycle import default_server_command

pytestmark = pytest.mark.integration

MODEL: Final = "BAAI/bge-small-en-v1.5"


@pytest.fixture(scope="module")
def encoder() -> FastEmbedEncoder:
    return FastEmbedEncoder.load(MODEL)


def _config(store_dir: Path) -> EffectiveConfig:
    return resolve(store_dir / "system.toml", store_dir / "config.toml")


async def _create_store(store_dir: Path, encoder: FastEmbedEncoder) -> None:
    async with await Store.create(store_dir, _config(store_dir.parent), encoder):
        pass


@pytest.fixture
def store_dir(tmp_path: Path, encoder: FastEmbedEncoder) -> Path:
    directory = tmp_path / "project" / ".zikaron"
    directory.mkdir(parents=True)
    asyncio.run(_create_store(directory, encoder))
    return directory


def _reap(pid: int, *, deadline_seconds: float) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if reaped_pid != 0:
            return
        time.sleep(0.02)
    raise TimeoutError(f"pid {pid} never exited")


def _pid_from_health(sock_path: Path) -> int | None:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2.0)
        sock.connect(str(sock_path))
    except OSError:
        return None
    try:
        sock.sendall(b'{"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}\n')
        buffer = b""
        while not buffer.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buffer += chunk
        parsed = json.loads(buffer.decode("utf-8"))
        pid = parsed["result"]["pid"]
        assert isinstance(pid, int)
        return pid
    finally:
        sock.close()


def test_run_warms_a_cold_store_and_logs_success(store_dir: Path, tmp_path: Path) -> None:
    sock_path = tmp_path / "test.sock"
    run(sock_path, store_dir)

    pid = _pid_from_health(sock_path)
    try:
        assert pid is not None, (
            "the warm helper's own health check reported success, so the service it started "
            "must still be reachable"
        )
        warmup_log = store_dir / "warmup.log"
        assert warmup_log.exists()
        contents = warmup_log.read_text(encoding="utf-8")
        assert "service_warm" in contents
        # `architecture.md`'s filesystem-security table: `warmup.log` "log[s] only a fixed
        # failure-kind label and an error code, never prompt or memory content" — an earlier
        # version of the success log line included `store_path=...` and `store_id=...` verbatim,
        # which violates that guarantee directly. Checked against the real, resolved values this
        # specific run actually used, not merely the literal substring `"store_path="`.
        assert str(store_dir) not in contents
        assert str(store_dir / "memory.db") not in contents
    finally:
        if pid is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            with suppress(TimeoutError):
                _reap(pid, deadline_seconds=10.0)


def test_run_never_raises_when_the_service_can_never_be_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run()`'s own docstring: "Never raises — this process's own exit code is not observed by
    anything." Forced deterministically by making `default_server_command` build a command that
    can never bind the socket (a nonexistent interpreter path), rather than relying on a real
    service happening to fail for some other, less controllable reason.
    """
    monkeypatch.setattr(
        warm_helper_module,
        "default_server_command",
        lambda _sock_path, _store_dir: ["/nonexistent/interpreter/path", "-c", "pass"],
    )
    sock_path = tmp_path / "test.sock"
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    run(sock_path, store_dir)  # must not raise
    warmup_log = store_dir / "warmup.log"
    assert warmup_log.exists()
    assert "warm_failed" in warmup_log.read_text(encoding="utf-8")


def test_run_warms_a_genuinely_fresh_project_whose_zikaron_directory_never_existed(
    tmp_path: Path,
) -> None:
    """The exact first-run case a first version of `run()` could not survive: `store_dir` (the
    `.zikaron` directory itself) does not exist at all before this call, not merely `memory.db`
    within it — the ordinary state of a project that has never run Zikaron. `_configure_warmup_
    log`'s own `Path.touch()` needs that directory to exist, and an earlier version of `run()`
    called it before any failure boundary was in scope, so this exact case raised
    `FileNotFoundError` uncaught and produced no warmup log at all.
    """
    sock_path = tmp_path / "test.sock"
    store_dir = tmp_path / "project" / ".zikaron"
    assert not store_dir.exists()

    run(sock_path, store_dir)

    pid = _pid_from_health(sock_path)
    try:
        assert pid is not None, (
            "run() must have started a real service for this genuinely fresh project"
        )
        warmup_log = store_dir / "warmup.log"
        assert warmup_log.exists()
        contents = warmup_log.read_text(encoding="utf-8")
        assert "service_warm" in contents
        assert str(store_dir) not in contents
        assert str(store_dir / "memory.db") not in contents
        mode = oct(store_dir.stat().st_mode)[-3:]
        assert mode == "700"
    finally:
        if pid is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            with suppress(TimeoutError):
                _reap(pid, deadline_seconds=10.0)


def test_a_warm_failure_never_writes_a_traceback_to_warmup_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`architecture.md` §"Filesystem security": `warmup.log` "log[s] only a fixed failure-kind
    label and an error code, never prompt or memory content" — `logger.exception` would have
    written the full traceback and exception message, which is not a fixed label. Forced with the
    same unreachable-interpreter construction as the test above, checking specifically for the
    absence of traceback markers rather than only the presence of the fixed label.
    """
    monkeypatch.setattr(
        warm_helper_module,
        "default_server_command",
        lambda _sock_path, _store_dir: ["/nonexistent/interpreter/path", "-c", "pass"],
    )
    sock_path = tmp_path / "test.sock"
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    run(sock_path, store_dir)
    contents = (store_dir / "warmup.log").read_text(encoding="utf-8")
    assert "Traceback" not in contents
    assert "warm_helper.py" not in contents


def test_default_server_command_still_used(tmp_path: Path) -> None:
    """A cheap sanity check that `run()` really does build a `zikaron.service.main` command
    rather than something else — `default_server_command`'s own shape is asserted directly, since
    `run()` itself has no return value to inspect.

    `warm_helper.py`'s own `main()` wrapper and its `if __name__ == "__main__":` guard are
    exercised behaviourally by `test_hook_spawn_warm.py::test_a_top_level_session_spawns_the_
    warm_helper_with_this_stores_paths` (which asserts the exact argv `spawn_warm.py` builds for
    this module) and, in real production use, by every real spawn `test_hook_connect_real_service_
    integration.py`'s own tests trigger — but a subprocess's own execution is not attributable to
    this test process's coverage data without subprocess coverage instrumentation, which nothing
    else in this codebase adopts either (`zikaron/service/main.py`'s identical class of gap is the
    established precedent, per `test_hook_main.py`'s own note on the same question).
    """
    command = default_server_command(tmp_path / "s.sock", tmp_path / "store")
    assert command[1:3] == ["-m", "zikaron.service.main"]
