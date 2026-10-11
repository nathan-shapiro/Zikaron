"""One service per socket path — per store within a runtime directory: the lock a service holds for
as long as it may have its store open.

`architecture.md` §"Start-if-absent, without a thundering herd" is normative. Start-if-absent's own
lock is held by a *client*, and only through its poll, so a start that outlasts the poll is
started again by the next client — and `asyncio.start_unix_server` removes an existing socket file
before it binds, so the later service would take the path from the earlier while both held the
store. This lock is held by the service itself, from before it opens the store until after it has
closed it.
"""

import asyncio
import contextlib
import fcntl
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from zikaron.service import paths, security

#: A service that found another holding its store exits with this: `EX_TEMPFAIL`, which every
#: spawning client's poll — `lifecycle` and `hook/connect` alike — reads as another service serving
#: or starting the store, and keeps polling for.
ANOTHER_SERVICE_EXIT_STATUS: Final = os.EX_TEMPFAIL

#: How long a starting service waits for the lock. A holder that is shutting down lets go once it
#: has closed its store — its `shut_down` is bounded by its own deadline, and the close after it is
#: short; one still holding it after that is serving or starting the store, and waiting longer
#: would only keep this process resident.
PREDECESSOR_WAIT_SECONDS: Final = 10.0

_POLL_INTERVAL_SECONDS: Final = 0.05


class AnotherServiceError(Exception):
    """Another process still held this store's service lock at the end of the wait."""


@dataclass(frozen=True, slots=True)
class StoreHold:
    """The store this process holds, for the moment it starts letting go."""

    _fd: int

    def still_here(self) -> None:
        """Stamp the lock file's mtime now, as a sign this holder is alive and polling.

        A push queued behind a holder reads that stamp's age to tell a start that has stalled from
        a service that is running but cannot be reached — one whose socket was removed, which
        stops at its next poll.
        """
        os.utime(self._fd)

    def stepping_down(self) -> None:
        """Clear this holder's name as its shutdown begins, while it still holds the store.

        A push queued behind a holder that is going away is waiting on a successor, not on a
        start that has stalled, and a shutdown can outlast that push's deadline.
        """
        _name_the_holder(self._fd, "")


@contextlib.asynccontextmanager
async def holding_the_store(sock_path: Path) -> AsyncIterator[StoreHold]:
    """Hold the service lock for `sock_path` for the duration of the body.

    Raises:
        AnotherServiceError: another process still held it after `PREDECESSOR_WAIT_SECONDS`.
        ZikaronError: `security.ensure_runtime_dir` refused the directory the lock lives in.
    """
    security.ensure_runtime_dir(sock_path.parent, uid=security.current_uid())
    fd = os.open(str(paths.service_lock_path(sock_path)), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        await _lock_within(fd, seconds=PREDECESSOR_WAIT_SECONDS)
        try:
            _name_the_holder(fd, f"{os.getpid()}\n")
            yield StoreHold(fd)
        finally:
            _name_the_holder(fd, "")
    finally:
        os.close(fd)


def _name_the_holder(fd: int, content: str) -> None:
    """Write which process holds the store into the lock file, or clear it on the way out.

    The write also stamps the file's mtime, which `StoreHold.still_here` renews, so a client queued
    behind a named holder can tell how long it has gone without a sign of life; the push hook stops
    calling that wait a start once it is too long (`hook/connect.py`). A holder that has begun
    shutting down is no longer named.
    """
    os.ftruncate(fd, 0)
    os.pwrite(fd, content.encode("ascii"), 0)


async def _lock_within(fd: int, *, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise AnotherServiceError("another service holds this store") from None
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        else:
            return
