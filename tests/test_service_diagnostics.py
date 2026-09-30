"""What a wedged service writes about itself, asserted in-process.

`architecture.md` §Lifecycle is normative. The idle poll already wakes every interval; while a
request stays in flight longer than that, each poll logs it, from the same registry `SIGUSR2`
dumps. Asserted with the interval patched down, as the idle-stop tests do, since a real process
would wait out a 30 s poll. The dumps' content and their installation are asserted here too; that
a real process survives each signal, and names a signal exit in its stop line, is
`test_service_diagnostics_integration.py`'s.
"""

import asyncio
import faulthandler
import logging
import os
import signal
import time
from pathlib import Path

import pytest

from tests.service_fixtures import open_context
from zikaron.service import diagnostics, lifecycle, main, server
from zikaron.service import log as service_log
from zikaron.service.context import ActivityTracker


async def test_a_request_outliving_the_poll_is_logged_on_each_poll_until_it_ends(
    tmp_path: Path,
    socket_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Named by method and, before its envelope resolves, as `session=unresolved` — a request
    wedged that early has no session to report yet."""
    interval = 0.05
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", interval)
    caplog.set_level(logging.INFO, logger="zikaron.service")
    async with open_context(tmp_path) as ctx:
        wedged = ctx.activity.begin_request("memory_plan_groups")
        wedged.started -= 10 * interval
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        polling = asyncio.create_task(
            lifecycle.idle_self_stop(
                ctx, running, sock_path, original_store_inode=ctx.store.opened_inode
            )
        )
        await asyncio.sleep(6 * interval)
        ctx.activity.end_request(wedged)
        logged_while_in_flight = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("long request:")
        ]
        caplog.clear()
        await asyncio.sleep(3 * interval)
        polling.cancel()
        await asyncio.gather(polling, return_exceptions=True)
        await running.shut_down()
    assert len(logged_while_in_flight) >= 2, logged_while_in_flight
    assert all(
        "method=memory_plan_groups session=unresolved" in line for line in logged_while_in_flight
    )
    assert not [record for record in caplog.records if "long request:" in record.getMessage()]


def test_only_a_request_older_than_the_threshold_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request in flight for less than the poll's interval is ordinary and names no wedge."""
    caplog.set_level(logging.INFO, logger="zikaron.service")
    tracker = ActivityTracker(last_activity=time.monotonic())
    young = tracker.begin_request("memory_search")
    young.session_id = "young"
    old = tracker.begin_request("memory_plan_groups")
    old.session_id = "old"
    old.started -= 60
    diagnostics.log_long_requests(tracker, older_than=30)
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 1, lines
    assert "method=memory_plan_groups session=old" in lines[0]


async def test_the_task_dump_lists_the_requests_in_flight_and_every_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="zikaron.service")
    tracker = ActivityTracker(last_activity=time.monotonic())
    request = tracker.begin_request("memory_next_group")
    request.session_id = "s1"
    diagnostics.dump_tasks(tracker)
    lines = [record.getMessage() for record in caplog.records]
    assert lines[0] == "dump: 1 request(s) in flight"
    assert lines[1].startswith("in flight: method=memory_next_group session=s1 age=")
    assert any(line.startswith("task ") for line in lines[2:])


def test_the_thread_dump_goes_to_service_logs_own_stream_or_to_stderr_without_one(
    tmp_path: Path,
) -> None:
    """`faulthandler` writes to a file descriptor, so it needs the handler's stream, not the logger;
    with no `service.log` attached it falls back to stderr rather than failing to install."""
    logger = logging.getLogger("zikaron.service")
    handler = logging.FileHandler(tmp_path / "service.log")
    assert diagnostics._log_stream() is not handler.stream
    ahead = logging.StreamHandler()
    logger.addHandler(ahead)
    logger.addHandler(handler)
    try:
        assert diagnostics._log_stream() is handler.stream
    finally:
        logger.removeHandler(handler)
        logger.removeHandler(ahead)
        handler.close()


async def test_the_task_dump_is_installed_for_the_block_and_removed_after_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`SIGUSR2` dumps into the log while installed, and is back at its default disposition
    afterwards — which is *terminate*, so leaving it installed would change what an operator's
    signal does to a later process-embedding caller."""
    caplog.set_level(logging.INFO, logger="zikaron.service")
    tracker = ActivityTracker(last_activity=time.monotonic())
    async with diagnostics.task_dump_on_signal(tracker):
        os.kill(os.getpid(), signal.SIGUSR2)
        await asyncio.sleep(0.05)
    assert any(record.getMessage().startswith("dump: ") for record in caplog.records)
    assert signal.getsignal(signal.SIGUSR2) is signal.SIG_DFL


def test_the_thread_dump_is_installed_for_the_block_and_removed_after_it() -> None:
    # typeshed declares `unregister` as returning `None`; CPython returns whether a handler was
    # registered.
    with diagnostics.thread_dump_on_signal():
        assert faulthandler.unregister(signal.SIGUSR1) is True  # type: ignore[func-returns-value]
        faulthandler.register(signal.SIGUSR1, file=diagnostics._log_stream(), all_threads=True)
    assert faulthandler.unregister(signal.SIGUSR1) is False  # type: ignore[func-returns-value]


def test_the_thread_dump_is_armed_before_the_store_opens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow start — a migration, a created store's model load — is when an operator would send
    `SIGUSR1`, and its default is *terminate*. So the dump is registered by the time the store's
    open begins, which is observed from inside that open."""
    armed: list[object] = []

    async def observing_open(_store_dir: Path) -> object:
        armed.append(faulthandler.unregister(signal.SIGUSR1))  # type: ignore[func-returns-value]
        raise RuntimeError("stop after observing")

    monkeypatch.setattr(service_log, "configure_service_log", lambda _path: None)
    monkeypatch.setattr(main, "_assemble_or_log_and_raise", observing_open)
    with pytest.raises(RuntimeError, match="stop after observing"):
        asyncio.run(main.run(tmp_path / "server.sock", tmp_path / ".zikaron"))
    assert armed == [True]
