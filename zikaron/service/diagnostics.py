"""What a service that has stopped answering writes about itself, and when.

`architecture.md` §"What a service that stops answering writes" is normative. Three mechanisms,
because a wedge takes two shapes and nobody may be at the terminal when it happens:

- **`SIGUSR1` dumps every thread's stack**, through `faulthandler` from a Python-level handler, so
  it needs no event loop — the one dump that works when the loop itself is blocked, in Python code
  or in a wait a signal interrupts. A loop stuck inside a single C call that no signal interrupts
  is dumped when that call returns. It writes raw text to `service.log`'s own stream, with no
  timestamp or `pid=` prefix, since it bypasses `logging`.
- **`SIGUSR2` dumps every asyncio task's stack and the requests in flight**, through a loop signal
  handler. It sees what the first cannot: a loop that is idle while a coroutine awaits forever.
- **A request that outlives the idle poll's interval is logged by that poll**, on each poll while
  it stays in flight, so the end of the log names a wedge with nobody at the terminal. The poll
  runs on the loop, so a *blocked* loop logs no such line; only `SIGUSR1` sees that case.
"""

import asyncio
import contextlib
import faulthandler
import io
import logging
import signal
import sys
from collections.abc import AsyncIterator, Iterator
from types import FrameType
from typing import TextIO

from zikaron.service.context import ActivityTracker

_LOGGER = logging.getLogger("zikaron.service")


def log_long_requests(activity: ActivityTracker, *, older_than: float) -> None:
    """One `INFO` line for each request in flight longer than `older_than` seconds.

    A planning method on a large journal is expected to run this long; its method field is what
    tells it from a wedge.
    """
    for request in activity.requests():
        if request.age() > older_than:
            _LOGGER.info("long request: %s", request.describe())


def dump_tasks(activity: ActivityTracker) -> None:
    """Every request in flight, then every asyncio task's stack, into `service.log`."""
    requests = activity.requests()
    _LOGGER.info("dump: %d request(s) in flight", len(requests))
    for request in requests:
        _LOGGER.info("in flight: %s", request.describe())
    for task in asyncio.all_tasks():
        stack = io.StringIO()
        task.print_stack(file=stack)
        _LOGGER.info("task %s:\n%s", task.get_name(), stack.getvalue().rstrip())


def _log_stream() -> TextIO:
    """The stream `service.log`'s handler writes to, or stderr where no such handler is attached.

    `faulthandler` writes to a file descriptor, so it needs the handler's own stream rather than the
    logger; a process run without `service.log` — an embedding, a test — dumps to stderr instead.
    """
    for handler in _LOGGER.handlers:
        if isinstance(handler, logging.FileHandler) and handler.stream is not None:
            return handler.stream
    return sys.stderr


@contextlib.contextmanager
def thread_dump_on_signal() -> Iterator[None]:
    """Install the `SIGUSR1` thread dump, and remove it again on the way out.

    It needs only `service.log`'s stream, so it goes on as soon as the log is open — ahead of the
    store's open, its migration and a created store's model load, since a slow start is exactly
    when an operator would send one, and the signal's default is *terminate*.

    **A Python-level handler, not `faulthandler.register`.** The latter's handler runs in whichever
    thread the signal lands on and walks every other thread's frames without the GIL, so a thread
    running Python meanwhile is read mid-change and the process dies of `SIGSEGV`, as a starting
    service did while its model load was importing `fastembed`. This handler runs on the main thread
    holding the GIL, where every other thread's frames are at rest. A thread that `sigwait`s for the
    signal would not depend on the main thread, but it receives the signal only if every thread
    blocks it, and importing `numpy` starts a pool of native threads that do not.
    """
    stream = _log_stream()

    def dump(_signum: int, _frame: FrameType | None) -> None:
        faulthandler.dump_traceback(file=stream, all_threads=True)

    previous = signal.signal(signal.SIGUSR1, dump)
    try:
        yield
    finally:
        signal.signal(signal.SIGUSR1, signal.SIG_DFL if previous is None else previous)


@contextlib.asynccontextmanager
async def task_dump_on_signal(activity: ActivityTracker) -> AsyncIterator[None]:
    """Install the `SIGUSR2` task dump, and remove it again on the way out.

    It reads the in-flight registry, so it goes on once the service's context exists, alongside the
    `SIGTERM`/`SIGINT` pair and before the socket is bound; its default is *terminate* too.
    """
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGUSR2, dump_tasks, activity)
    try:
        yield
    finally:
        loop.remove_signal_handler(signal.SIGUSR2)
