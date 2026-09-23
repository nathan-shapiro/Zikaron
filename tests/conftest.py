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
leak has already been detected, so the ordinary path pays for two `threading.enumerate()` calls
per test — one for the `before` baseline, one for the delta — and nothing else.
*It said "one" until the baseline was added: the "identity, not arithmetic" rewrite introduced the
second call and did not revisit the sentence counting them.*
"""

import gc
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Generator, Iterable, Iterator
from pathlib import Path
from typing import Final

import aiosqlite
import pytest
from aiosqlite.core import _connection_worker_thread

from zikaron.harness.spec import KIRO, SPECS
from zikaron.install import harness as install_harness


@pytest.fixture(scope="session")
def short_tmp_root() -> Iterator[Path]:
    """A session-wide directory shallow enough that an `AF_UNIX` path under it can be bound.

    `/tmp` by name rather than `tempfile.gettempdir()`, and that is the whole point of the
    fixture. On macOS `gettempdir()` answers a per-session `/var/folders/…/T` path deep enough
    that `<runtime>/zikaron/<32 hex>.sock` under it no longer fits `sun_path`, and `bind()` fails.

    The product is not subject to this — its own path is short by construction (`architecture.md`
    §Paths; `paths.socket_path` enforces the bound `paths.sun_path_size` holds). Only the suite is,
    because
    pytest's temporary paths are deep and self-describing, so this is the suite buying the
    headroom production already has rather than a platform difference papered over.
    """
    root = Path(tempfile.mkdtemp(prefix="zk-", dir="/tmp"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def socket_dir(short_tmp_root: Path) -> Path:
    """A per-test `0700` directory short enough that a socket path under it can be bound.

    Stands in for `tmp_path` wherever a test builds something it will hand to `bind()` or
    `connect()`. Everything else a test needs a directory for — stores, configs, projects — still
    belongs on `tmp_path`, which names the test that made it and survives the run for inspection.

    `mkdtemp` rather than a name derived from the test's, for the reason the name would defeat:
    a descriptive test name alone can spend most of the budget.
    """
    return Path(tempfile.mkdtemp(dir=short_tmp_root))


@pytest.fixture(scope="session", autouse=True)
def _runtime_dir_is_never_the_developers(short_tmp_root: Path) -> Iterator[None]:
    """Point `$XDG_RUNTIME_DIR` at a temporary directory for the whole session.

    The socket path is a hash of the store directory, and tests create their stores under
    `tmp_path` — a fresh path per test, so a fresh hash per test. Start-if-absent creates
    `<hash>.sock.lock` beside the socket and, correctly, never unlinks it: unlinking a `flock`
    target is racy, because a process still holding an fd would lock a detached inode while a
    newcomer creates a fresh one, and the mutual exclusion silently stops existing.

    So every run of this suite leaves one zero-byte lock file per socket it opened, and without
    this fixture they land in the runtime directory of whoever ran it. Measured before it existed:
    **1,388 of them**, accumulating over seven weeks, in a directory whose hashed naming exists so
    that a human debugging one real store can find its socket among the others.

    Session-scoped, and under `short_tmp_root` rather than wherever `mkdtemp` defaults to, so that
    what real clients derive from this variable stays inside `sun_path`. Both properties are load
    bearing: a per-test directory would spend the budget on a name, and `gettempdir()` spends it
    on macOS before this suite contributes a byte.

    `os.environ` directly rather than `monkeypatch`, which is function-scoped; `mkdtemp` already
    creates the directory `0700`, which is what `security.ensure_runtime_dir` requires of it.
    """
    previous = os.environ.get("XDG_RUNTIME_DIR")
    directory = tempfile.mkdtemp(prefix="rt-", dir=short_tmp_root)
    os.environ["XDG_RUNTIME_DIR"] = directory
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = previous
        shutil.rmtree(directory, ignore_errors=True)


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
        # D17's store scope. This one repoints the **store**, so a
        # test that sets a marker and then reaches resolution would otherwise adopt whichever
        # project launched pytest — this repository — and read and write its real memories.
        if spec.project_dir_variable is not None:
            monkeypatch.delenv(spec.project_dir_variable, raising=False)


#: The tiers whose whole purpose is to notice a wrong `HarnessSpec.harness_binary`, and which
#: therefore may never report success for a machine that could not run them.
#: `pytester` runs a nested pytest in a temporary directory, which is the only way to test a hook
#: whose contract is with pytest itself rather than with our code — see
#: `tests/test_harness_tier_guard.py`.
pytest_plugins = ("pytester",)

_HARNESS_TIERS: Final = frozenset({"integration_kiro", "integration_claude"})


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],  # noqa: ARG001 — the hook's signature, not ours to trim.
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Turn a **skip** into a **failure** for any test in a harness tier.

    `design/coding-standards.md` §"five tiers" states this as a rule, and *stating* it is what kept
    going wrong: the paragraph claimed it while five of six tests used `pytest.skip`, was
    corrected, and was capable of going stale again the moment anyone added a test. So it is
    enforced here instead, and the document now describes a mechanism rather than an intention.

    **Why a skip is wrong specifically here.** These tiers are only ever reached by explicit
    request, so "the binary is missing" has two causes and a skip reports success for both: the
    machine lacks the harness — a mistake about where you ran it — or
    `HarnessSpec.harness_binary` names a binary that does not exist, which **no other test in
    the suite can see**, because the spec↔design drift guard pins the code against `harness.md`
    rather than against reality, and an upstream rename lands on both sides at once.

    Deliberately narrow: only these two markers, only a skip, and the original reason is kept in the
    message so the failure says what the skip would have.
    """
    report = yield
    if report.skipped and _HARNESS_TIERS.intersection(item.keywords):
        report.outcome = "failed"
        report.longrepr = (
            f"{item.nodeid} skipped inside a harness tier, which may not report success for a "
            "machine that cannot run it — see coding-standards.md §'five tiers'. "
            f"Original reason: {report.longrepr}"
        )
    return report


@pytest.fixture
def stub_harness_binaries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answer for the harness binaries so a test can exercise **Zikaron's** processes without one.

    Opt-in, never autouse: tests that are *about* the binary checks must be able to see the real
    functions, and a suite-wide stub would silently disarm them.

    The distinction this exists to draw is between two kinds of "real". `tests/test_install_e2e.py`
    and `tests/test_install_takeover.py` spawn real hook processes, a real service, a real socket
    and a real MCP client — all Zikaron's own, all reproducible anywhere. They touch `kiro-cli` only
    because `install.main` validates the consolidator's model on the way past, which is incidental
    to everything they assert. Stubbing that one call makes them hermetic without weakening them by
    a single assertion, and what a real binary genuinely establishes stays in
    `test_install_harness.py::TestAgainstTheRealBinary` behind `integration_kiro`.

    Both harnesses are answered for, so a test using this can install for either.
    """
    monkeypatch.setattr(install_harness, "binary_is_available", lambda _name: True)
    monkeypatch.setattr(
        install_harness, "available_model_ids", lambda: frozenset({KIRO.consolidator_model})
    )
    monkeypatch.setattr(install_harness, "validate_agent_config", lambda _path: None)


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


#: How long to let a worker thread finish exiting before calling it leaked. **A thread that is
#: stopping is not a thread that leaked, and this guard could not tell them apart.** When a connect
#: *fails*, `aiosqlite`'s own `_connect` calls `stop()`, which sets a flag and queues a sentinel but
#: never joins — so the thread is alive for a few more milliseconds while it drains the queue and
#: returns. Checking the instant a test ends caught it mid-exit and failed the test that had done
#: nothing wrong. Measured before this wait existed: `tests/test_store_connection.py` alone reported
#: 1, 0, 0, 2 and 1 errors across five identical runs, and a full-suite run stayed green only
#: because later tests gave the thread room.
#:
#: **Generous on purpose, because with `join` the headroom is free.** This is an upper bound on
#: waiting, not a duration anything sleeps for: an exiting thread is joined the moment it ends, in
#: milliseconds, so a larger bound costs nothing in the ordinary case. It is only ever spent in full
#: by a genuinely leaked connection, which blocks on its queue forever — and that test was going to
#: fail regardless.
_EXITING_THREAD_GRACE_SECONDS: Final = 5.0


def _settle(threads: Iterable[threading.Thread]) -> list[threading.Thread]:
    """Wait for `threads` to finish exiting; return those still alive.

    Waits on the threads themselves rather than polling a clock: `join` returns the instant a thread
    ends, so a thread on its way out costs only the microseconds it needs. One deadline spans the
    whole set, so a test that leaves several behind cannot multiply the bound.
    """
    # Materialised once: this walks the set twice, and a generator argument would be empty the
    # second time — every leak silently passing.
    pending = list(threads)
    deadline = time.monotonic() + _EXITING_THREAD_GRACE_SECONDS
    for thread in pending:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        thread.join(timeout=remaining)
    return [thread for thread in pending if thread.is_alive()]


@pytest.fixture(autouse=True)
def _no_leaked_store_connections() -> Iterator[None]:
    """Fail the test that left a store open, and stop the thread it left behind.

    **Identity, not arithmetic.** Only the threads this test actually added are waited on and
    counted. Comparing a count before against a count after has two faults that identity does not:
    it would join threads a *wider-scoped* fixture is legitimately holding open, spending the whole
    deadline on each and reading as mysteriously slow tests rather than as a detector cost; and
    after a leak is detected, `_stop_open_connections` queues a stop without joining, so the next
    test's baseline could still include that exiting thread and its arithmetic would then hide one
    genuine leak.
    """
    before = set(_live_connection_threads())
    yield
    leaked = _settle([t for t in _live_connection_threads() if t not in before])
    if leaked:
        _stop_open_connections()
        # Joined before returning, so the next test does not start with these still exiting and
        # then have to distinguish them from its own.
        _settle(leaked)
        pytest.fail(
            f"{len(leaked)} aiosqlite connection thread(s) still running: this test left a store "
            "open. An unclosed connection is a non-daemon thread, so it hangs the whole session at "
            "interpreter shutdown instead of reporting anything. Hold the store with `async with`.",
            pytrace=False,
        )
