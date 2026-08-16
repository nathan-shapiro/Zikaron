"""Suite-wide guards: a store left open must fail its test, and the enclosing harness must not
leak into it.

The second guard is here because it was found the hard way, and by exactly the mechanism it now
prevents. This suite is routinely run *inside* one of the harnesses Zikaron supports, and a harness
exports its marker and session variables into every process it spawns — including pytest, and
including any subprocess a test spawns from pytest. Four tests that ran a real `zikaron.hook.main`
subprocess began failing for a reason that had nothing to do with what they asserted: the hook
detected the *enclosing* session's harness, read its session id, found it differed from the test's
own payload, and correctly suppressed itself. The tests were never hermetic; nothing had exported
those variables before.

That is the same environment-inheritance mechanism `design/harness.md` describes under the nesting
limit, so the fixture below is not merely test hygiene — it is the suite declining to be the
misdetected inner session.

The first guard, on store connections:

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

from zikaron.harness.spec import SPECS


@pytest.fixture(autouse=True)
def _no_inherited_harness_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every harness marker and session variable before each test.

    Autouse and suite-wide rather than per-file, because the contamination is per-*process*: any
    test that reads the environment, and any test that spawns a subprocess which does, inherits
    whatever harness launched pytest. A test asserting "no marker means the unmarked harness" would
    otherwise pass or fail according to which terminal the suite was started from.

    Deleting rather than pinning a value: a test that needs a harness present sets exactly the
    variables it means, and starting from nothing is what makes that set complete.
    """
    for spec in SPECS.values():
        if spec.marker_variable is not None:
            monkeypatch.delenv(spec.marker_variable, raising=False)
        monkeypatch.delenv(spec.session_variable, raising=False)


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
