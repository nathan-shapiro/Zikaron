"""What a service that has stopped answering writes about itself, read from a real process's log.

`architecture.md` §Lifecycle is normative. The two dumps and the signal stop line are asserted
against a real spawned service, because a signal's disposition is a fact about the process: a
handler installed in the test's own loop would prove nothing about the one the operator signals.
Each dump must also leave the process running, since both signals default to *terminate*.
"""

import os
import signal
import time
from pathlib import Path

import pytest

from tests.test_service_lifecycle_integration import (  # noqa: F401 — the autouse sweep rides along.
    MODEL,
    _running_server,
    _sweep_known_server_pids_after_every_test,
)
from zikaron.core.indexing.encoder import FastEmbedEncoder
from zikaron.service.paths import service_log_path

pytestmark = pytest.mark.integration

_LOG_DEADLINE_SECONDS = 10.0

#: Enough to make the crash below near-certain: `faulthandler.register`'s handler, which walks other
#: threads' frames without the GIL, died on five dumps in 55 of 60 runs and on one in 19 of 60.
_DUMPS = 5


@pytest.fixture(scope="module")
def encoder() -> FastEmbedEncoder:
    return FastEmbedEncoder.load(MODEL)


def _log_once_it_contains(store_dir: Path, needle: str, *, count: int = 1) -> str:
    deadline = time.monotonic() + _LOG_DEADLINE_SECONDS
    while True:
        text = service_log_path(store_dir).read_text(encoding="utf-8", errors="replace")
        if text.count(needle) >= count:
            return text
        if time.monotonic() > deadline:
            pytest.fail(f"service.log never contained {needle!r} {count} time(s):\n{text[-2000:]}")
        time.sleep(0.05)


async def test_sigusr1_dumps_every_threads_stack_and_leaves_the_service_running(
    tmp_path: Path, socket_dir: Path, encoder: FastEmbedEncoder
) -> None:
    """Several dumps, each sent once the last has landed, straight after the socket accepts — while
    the open path's model load can still be running Python on its own thread, which is what a dump
    that walks other threads' frames without the GIL crashes on."""
    async with _running_server(tmp_path, socket_dir, encoder) as (_sock, store_dir, _id, process):
        for sent in range(1, _DUMPS + 1):
            os.kill(process.pid, signal.SIGUSR1)
            _log_once_it_contains(store_dir, "Current thread", count=sent)
            assert process.poll() is None


async def test_sigusr2_dumps_the_requests_in_flight_and_every_task(
    tmp_path: Path, socket_dir: Path, encoder: FastEmbedEncoder
) -> None:
    async with _running_server(tmp_path, socket_dir, encoder) as (_sock, store_dir, _id, process):
        os.kill(process.pid, signal.SIGUSR2)
        text = _log_once_it_contains(store_dir, "request(s) in flight")
        _log_once_it_contains(store_dir, "task ")
        assert "dump: 0 request(s) in flight" in text
        assert process.poll() is None


@pytest.mark.parametrize(
    ("sent", "reason"), [(signal.SIGTERM, "sigterm"), (signal.SIGINT, "sigint")]
)
async def test_a_signal_exit_names_its_signal_in_the_stop_line(
    tmp_path: Path,
    socket_dir: Path,
    encoder: FastEmbedEncoder,
    sent: signal.Signals,
    reason: str,
) -> None:
    """A service that logged this was not wedged; a wedged loop never runs the handler."""
    async with _running_server(tmp_path, socket_dir, encoder) as (_sock, store_dir, _id, process):
        os.kill(process.pid, sent)
        process.wait(timeout=_LOG_DEADLINE_SECONDS)
        _log_once_it_contains(store_dir, f"stopping: reason={reason}")
