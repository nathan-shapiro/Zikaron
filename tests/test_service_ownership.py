"""`zikaron.service.ownership`: one service per socket path — per store within a runtime directory —
held from before the store is opened until after it is closed.

`architecture.md` §"Start-if-absent, without a thundering herd" is normative. Two holders inside
one process conflict exactly as two processes do, since a `flock` belongs to an open file
description and each holder opens its own; `test_hook_connect_real_service_integration.py` covers
two real services.
"""

import asyncio
import fcntl
import os
import time
from pathlib import Path

import pytest

from zikaron.hook import connect
from zikaron.service import lifecycle, ownership, paths, server


def _hold(sock_path: Path) -> int:
    """Take the service lock for `sock_path` the way another process would, returning its fd."""
    fd = os.open(str(paths.service_lock_path(sock_path)), os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


async def test_a_start_gives_up_on_a_store_another_still_holds(
    socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ownership, "PREDECESSOR_WAIT_SECONDS", 0.2)
    sock_path = socket_dir / "test.sock"
    holder = _hold(sock_path)
    try:
        with pytest.raises(ownership.AnotherServiceError):
            async with ownership.holding_the_store(sock_path):
                pytest.fail("held the store beside another holder")
    finally:
        os.close(holder)


async def test_a_start_takes_over_from_a_holder_that_lets_go_within_the_wait(
    socket_dir: Path,
) -> None:
    """A predecessor shutting down lets go once it has closed its store; the start that found it
    there waits for that rather than leaving the store unserved."""
    sock_path = socket_dir / "test.sock"
    holder = _hold(sock_path)
    asyncio.get_running_loop().call_later(0.2, os.close, holder)
    async with ownership.holding_the_store(sock_path):
        pass


async def test_the_store_is_let_go_on_the_way_out(socket_dir: Path) -> None:
    sock_path = socket_dir / "test.sock"
    async with ownership.holding_the_store(sock_path):
        pass
    fd = os.open(str(paths.service_lock_path(sock_path)), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


async def test_the_holder_names_itself_while_it_holds_the_store_and_not_after(
    socket_dir: Path,
) -> None:
    """The push hook reads this to tell a start still running from one that has stalled, so a
    name left behind after the holder let go would read as a holder that never did."""
    sock_path = socket_dir / "test.sock"
    lock = paths.service_lock_path(sock_path)
    async with ownership.holding_the_store(sock_path):
        assert lock.read_text(encoding="ascii") == f"{os.getpid()}\n"
    assert lock.read_text(encoding="ascii") == ""


async def test_a_holder_stepping_down_stops_naming_itself_but_keeps_the_store(
    socket_dir: Path,
) -> None:
    """A holder in shutdown is no stalled start to a push queued behind it, and is still the one
    that has the store open, so it must not be succeeded until it lets go."""
    sock_path = socket_dir / "test.sock"
    lock = paths.service_lock_path(sock_path)
    async with ownership.holding_the_store(sock_path) as hold:
        hold.stepping_down()
        assert lock.read_text(encoding="ascii") == ""
        fd = os.open(str(lock), os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)


async def test_a_holder_still_here_renews_its_stamp(socket_dir: Path) -> None:
    sock_path = socket_dir / "test.sock"
    lock = paths.service_lock_path(sock_path)
    async with ownership.holding_the_store(sock_path) as hold:
        long_ago = time.time() - 600.0
        os.utime(lock, (long_ago, long_ago))
        hold.still_here()
        assert time.time() - lock.stat().st_mtime < 5.0


def test_a_live_holder_renews_its_stamp_well_inside_the_stalled_bound() -> None:
    """A serving service renews its stamp once per idle poll, so a push queued behind it — one
    whose socket was removed, say — must never find the stamp older than the stalled-start bound
    while it is still polling."""
    assert connect._STALLED_START_SECONDS >= 2 * lifecycle.IDLE_POLL_INTERVAL_SECONDS


def test_the_wait_outlasts_a_predecessors_own_shutdown() -> None:
    """A holder that is shutting down lets go shortly after its shutdown deadline — the store close
    that follows is not under it; a wait shorter than that would turn a successor away from a store
    about to be free."""
    assert ownership.PREDECESSOR_WAIT_SECONDS > server._SHUTDOWN_QUIESCENCE_DEADLINE_SECONDS


def test_the_hook_reads_the_exit_status_a_deferring_service_exits_with() -> None:
    """The hook restates the status rather than importing this module, so the two are held equal
    here: a mismatch would read a deferring start the push lived to see exit as a failed one."""
    assert connect._ANOTHER_SERVICE_EXIT_STATUS == ownership.ANOTHER_SERVICE_EXIT_STATUS
