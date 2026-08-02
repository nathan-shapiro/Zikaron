"""Suite-wide guard: a store left open must fail its test, never hang the run.

`aiosqlite.Connection` runs its SQL on a **non-daemon** worker thread, so a connection that is never
closed keeps the interpreter alive after the last test finishes. The failure mode that produces is
uniquely bad, and it was measured here rather than reasoned about: a run whose tests completed in
0.76 s hung indefinitely showing *nothing at all*, because four failing tests had skipped their own
cleanup on the way out and the summary was written to a pipe the process never closed.

The rule that prevents it is the ordinary one — hold a `Store` with `async with`, exactly as any
caller outside the tests must (`coding-standards.md` §6) — and this fixture exists because a
*failing* assertion is precisely what skips the cleanup written after it. So a leak becomes a named
failure of the test that caused it, and the surviving thread is stopped through `aiosqlite`'s own
`stop()` so the session can still exit and report what it found.

Detection is by thread target rather than by tracking connections, so it covers every test whether
or not it went through a shared helper. The `gc` walk that finds the objects runs **only** once a
leak has already been detected, so the ordinary path pays for one `threading.enumerate()`.
"""

import gc
import threading
from collections.abc import Iterator

import aiosqlite
import pytest
from aiosqlite.core import _connection_worker_thread


def _live_connection_threads() -> list[threading.Thread]:
    """Every alive thread running `aiosqlite`'s worker loop.

    Matched on the target function object rather than on the thread's name, which is
    `Thread-N (_connection_worker_thread)` and therefore both unstable and easy to collide with.
    `asyncio.to_thread`'s executor threads run a different target, so the embedding calls the read
    path makes off the event loop are not mistaken for store connections.
    """
    return [
        thread
        for thread in threading.enumerate()
        if getattr(thread, "_target", None) is _connection_worker_thread and thread.is_alive()
    ]


def _stop_open_connections() -> None:
    """Stop every `aiosqlite` connection still holding an open handle.

    `Connection.stop()` is the library's own path for this — it is what its `__del__` uses — and it
    needs no running event loop, which matters because the loop the connection was opened on is
    already closed by the time a fixture tears down.
    """
    for candidate in gc.get_objects():
        if isinstance(candidate, aiosqlite.Connection) and candidate._connection is not None:
            candidate.stop()


@pytest.fixture(autouse=True)
def _no_leaked_store_connections() -> Iterator[None]:
    """Fail the test that left a store open, and stop the thread it left behind."""
    before = len(_live_connection_threads())
    yield
    leaked = len(_live_connection_threads()) - before
    if leaked > 0:
        _stop_open_connections()
        pytest.fail(
            f"{leaked} aiosqlite connection thread(s) still running: this test left a store open. "
            "An unclosed connection is a non-daemon thread, so it hangs the whole session at "
            "interpreter shutdown instead of reporting anything. Hold the store with `async with`.",
            pytrace=False,
        )
