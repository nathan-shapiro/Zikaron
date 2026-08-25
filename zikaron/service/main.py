"""The process entry point: assemble the store, listen, and run until told to stop.

Invoked as `python -m zikaron.service.main <sock_path> <store_dir>` — `lifecycle.py`'s
`default_server_command` builds exactly this argv, and a client's start-if-absent spawns it
detached. Not `<h>.sock` derivation and not config-file discovery: both the socket path and the
store directory are the **caller's** decision (a client that already resolved them for its own
`connect()` attempt), so this process trusts them rather than re-deriving them and risking a
disagreement between what the client will `connect()` to and what this process binds.
"""

import asyncio
import logging
import os
import signal
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from zikaron.core.config.resolution import (
    default_system_config_path,
    project_config_path,
    resolve,
)
from zikaron.core.store import permissions
from zikaron.service import lifecycle, log, security
from zikaron.service.context import ServiceContext
from zikaron.service.paths import service_log_path
from zikaron.service.server import RunningServer, ShutdownTimeoutError, serve


@asynccontextmanager
async def _stop_on_sigterm_or_sigint(stop: asyncio.Event) -> AsyncIterator[None]:
    """Install `SIGTERM`/`SIGINT` handlers that set `stop`, and remove them again on the way out
    — whatever the way out is.

    Extracted from `run()` itself specifically to give the removal half of this a home:
    `loop.add_signal_handler` calls with no matching `remove_signal_handler` on any path used to
    leave a handler permanently installed even after a fully successful run, closing over this
    specific invocation's `stop` event, and — if installing the *second* signal failed — even the
    *first* one remained installed with nothing removing it. The production subprocess normally
    exits (and so closes its event loop) immediately after `run()` returns, which is why this went
    unnoticed in practice, but a direct in-process caller — `tests/test_service_main.py`'s own
    tests, or any future embedding of `run()` — does not get that for free. Installed signals are
    tracked incrementally (`installed`, not one literal tuple) so the `finally` below removes
    exactly the ones that succeeded, never one that was never installed at all.
    """
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    try:
        for one_signal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(one_signal, stop.set)
            installed.append(one_signal)
        yield
    finally:
        for one_signal in installed:
            loop.remove_signal_handler(one_signal)


def _raise_if_any_task_genuinely_failed(
    done: set[asyncio.Task[Any]], *, ignoring: asyncio.Task[Any]
) -> None:
    """Re-raise the first genuine exception among `done`'s tasks, if any — `asyncio.wait`'s own
    `done` set is what actually says why it returned, and `idle_task.done() and not idle_task.
    cancelled()` used to treat a genuinely *raised* `idle_self_stop` identically to a normal idle
    exit, since a raised task is `done()` and not `cancelled()` either. Retrieving each completed
    task's own exception here, before anything is cancelled, is what turns a silently swallowed
    crash back into one `run()` actually propagates. `ignoring` (`signal_wait`) legitimately
    completes with no exception at all (`Event.wait()` returns `True`) and is excluded from this
    check for exactly that reason — it is the one task among the two whose normal completion
    genuinely means what the caller already treats it as meaning.
    """
    for task in done:
        if task is ignoring or task.cancelled():
            continue
        error = task.exception()
        if error is not None:
            raise error


async def _assemble_or_log_and_raise(store_dir: Path) -> ServiceContext:
    """Resolve the effective config and open the store, logging any failure before it propagates.

    Extracted from `run()` only to keep that function within `coding-standards.md`'s own
    statement-count guideline; the logging-before-propagating behaviour is the point, and its
    rationale is in `run()`'s own docstring (`architecture.md` §"Degraded modes": a startup failure
    is one client-observable outcome — `health()` never becomes reachable — so what is owed is that
    the failure be diagnosable from this process's own log rather than lost to a detached child's
    `/dev/null` stderr).
    """
    try:
        config = resolve(
            default_system_config_path(os.environ.get("XDG_CONFIG_HOME"), Path.home()),
            project_config_path(store_dir),
        )
        log.log_resolved_config(config)
        return await ServiceContext.assemble(store_dir, config)
    except Exception:
        logging.getLogger("zikaron.service").exception("failed to start")
        raise


def _ensure_store_dir_exists(store_dir: Path) -> Path:
    """`store_dir`, created and vetted through the same path `Store.create` itself uses — never a
    bare `mkdir`, which would let `log.configure_service_log` write into a directory reached
    through a symlink, or one left wider than `0700` by an earlier build, before either has ever
    been checked.

    Exists only so `log.configure_service_log` — which must run **before** `ServiceContext.
    assemble` so a first-run `Store.create` failure is itself diagnosable
    (`run`'s own docstring) — has somewhere to `touch` `service.log` into. Without this, the very
    case `architecture.md` §"First run" exists to support (an empty directory, `.zikaron` absent
    entirely) would fail with a bare `FileNotFoundError` from the log setup itself, before the
    store-creation path this whole function exists to reach is ever attempted — a real defect,
    not a hypothetical, caught by running the create-on-absent path end to end rather than only
    unit-testing `ServiceContext.assemble` in isolation. `permissions.ensure_store_dir` is what
    `Store.create` itself calls for the identical directory a moment later, so this is the same
    check running once earlier rather than a second, weaker one invented for this narrower purpose
    — `Store.create`'s own call is then a no-op against a directory this function already left
    correctly vetted and at `0700`.

    Raises:
        ZikaronError: `BAD_CONFIG` if `store_dir`, once resolved, is reached through a symlink
            anywhere along its path — the identical refusal `permissions.ensure_store_dir` states
            for `Store.create`, now enforced before the log is ever opened rather than after.
    """
    permissions.ensure_store_dir(store_dir)
    return store_dir


def _self_stopping_tasks(
    ctx: ServiceContext,
    server: RunningServer,
    sock_path: Path,
    *,
    original_store_inode: int,
) -> list[asyncio.Task[object]]:
    """The background tasks that stop this service on their own terms, rather than on a signal.

    Kept apart from the signal wait because the difference decides who unlinks the socket: each of
    these unlinks before closing the server, to close the connect-during-exit race window, so
    `run` must not unlink again after one of them has fired. Returning them as a list, rather than
    letting `run` name each one, is also what keeps this set open to a third condition without
    another branch appearing in the wait.

    The load watch is created only when there is a deferred load to watch. A store this process
    created has already waited for its model, so a failure there was raised during assembly and
    this process never reached the point of serving anything.
    """
    tasks: list[asyncio.Task[object]] = [
        asyncio.create_task(
            lifecycle.idle_self_stop(
                ctx, server, sock_path, original_store_inode=original_store_inode
            )
        )
    ]
    if ctx.encoder_load is not None:
        tasks.append(
            asyncio.create_task(
                lifecycle.stop_on_encoder_failure(ctx, server, sock_path, ctx.encoder_load)
            )
        )
    return tasks


async def run(sock_path: Path, store_dir: Path) -> None:
    """Assemble the store, bind the socket, and serve until an idle exit or a signal.

    The log is configured **before** config resolution or the store open, not after: either can
    raise, and the design's own degraded-modes chapter treats every startup failure as one
    client-observable outcome — `health()` never becomes reachable, so a client's poll deadline
    expires and it logs that fact to its own log and gives up (`architecture.md` §"Degraded
    modes": "spawn failure, `health()` never ready... anything unexpected"). No richer channel
    back through a socket that was never bound is owed to the client for that reason; what *is*
    owed is that the failure be diagnosable from this process's own log rather than lost entirely
    to a detached child's `/dev/null` stderr, which is why every startup failure is logged here
    before it propagates.

    Every exit path converges on the same cleanup: whichever finishes first of `idle_self_stop`'s
    poll loop, the watch on a deferred model load, or a `SIGTERM`/`SIGINT` handler, and
    `server.shut_down()` is what actually closes the listener and every connection it can observe,
    under one bounded deadline. The load watch exists only when the encoder was still loading when
    the socket was bound, which is the open path; a store this process created has already waited
    for its model and has nothing left to watch. **`asyncio.Server.serve_
    forever()` is deliberately never called at all** — `asyncio.start_unix_server` (inside
    `serve()`) already accepts and dispatches connections the instant it returns, with no separate
    "start serving" call needed; `serve_forever()` is only a convenience wrapper for blocking until
    cancelled, and using it as this function's own third thing-to-wait-on created a real bug:
    cancelling it makes `asyncio.Server` itself call `close()` and await its **own**
    `wait_closed()` before re-raising, which is a second, independent wait for exactly the same
    connections `RunningServer.shut_down()` exists to drain — and that second wait ran *first*,
    deadlocking against an idle open connection before this function's own draining logic ever got
    a chance to run. Waiting only on `idle_task` and `signal_wait`, and calling `server.shut_down()`
    directly, removes the competing wait entirely rather than trying to sequence around it.

    The socket is unlinked exactly once — by whichever self-stopping task fired (each unlinks
    *before* closing the server, to close the connect-during-exit race window, per their own
    docstrings) and by this function on the signal path, where no such race exists to close early.

    Raises:
        ZikaronError: whatever `config.resolution.resolve` or `ServiceContext.assemble` raise —
            `BAD_CONFIG`, `REINDEXING`, `SCHEMA_INCOMPATIBLE` — if the store cannot be opened at
            all. There is nothing useful to serve in that case, so the process exits with that
            exception rather than binding a socket for a store it could not open.
    """
    log.configure_service_log(service_log_path(_ensure_store_dir_exists(store_dir)))
    ctx = await _assemble_or_log_and_raise(store_dir)
    # `ctx.store.opened_inode` — not a fresh `ctx.store.path.stat()` here — because a version
    # that re-`stat`ed the path at this point was measured wrong: `ServiceContext.assemble` opens
    # the connection through `Store.open`/`Store.create`, and both run further awaited validation
    # or creation SQL *inside that one `await`*, after SQLite's own connect already succeeded —
    # every one of those is a real yield point a replacement could land in, all of them strictly
    # *before* control ever returns here. `Store.opened_inode` is captured immediately after
    # `_open_connection`'s own connect returns instead, with no further `await` before the read
    # (`_open_connection`'s own docstring has the full reasoning, including the narrow, human-
    # authorized gap this deliberately accepts rather than a materially larger VFS-level fix).
    original_store_inode = ctx.store.opened_inode

    try:
        security.ensure_runtime_dir(sock_path.parent, uid=security.current_uid())
        server = await serve(ctx, str(sock_path))
        try:
            sock_path.chmod(0o600)

            stop = asyncio.Event()
            async with _stop_on_sigterm_or_sigint(stop):
                tasks: list[asyncio.Task[object]] = []
                try:
                    self_stopping = _self_stopping_tasks(
                        ctx, server, sock_path, original_store_inode=original_store_inode
                    )
                    tasks.extend(self_stopping)
                    signal_wait = asyncio.create_task(stop.wait())
                    tasks.append(signal_wait)
                    done, _pending = await asyncio.wait(
                        set(tasks), return_when=asyncio.FIRST_COMPLETED
                    )
                    _raise_if_any_task_genuinely_failed(done, ignoring=signal_wait)
                    if not done & set(self_stopping):
                        # Both self-stopping tasks unlink before closing the server, to close the
                        # connect-during-exit race window — see their own docstrings. A signal
                        # exit has no such window to close early, so this path owns the
                        # unlink instead.
                        sock_path.unlink(missing_ok=True)
                        await server.shut_down()
                finally:
                    # Every task appended above must be cancelled and awaited whatever happened —
                    # `asyncio.wait` itself raising, this coroutine being cancelled from outside
                    # while awaiting it, or any other exception reaching this point all jump past
                    # the ordinary cancellation loop that used to run only after `asyncio.wait`
                    # returned normally, leaving whichever of `idle_task`/`signal_wait` had
                    # already been created running forever with nothing left holding a reference
                    # to stop it. `tasks` is built incrementally rather than as one literal tuple
                    # specifically so this `finally` sees exactly the tasks that actually exist
                    # at the point of failure, never one that was never created. `gather(...,
                    # return_exceptions=True)` rather than a per-task loop so one task's own
                    # failure during cancellation cannot skip the rest.
                    #
                    # `sys.exc_info()` is read as the very first statement in this `finally` —
                    # before cancelling anything — for the identical reason `_close_context_
                    # preserving_any_active_failure` reads it below: whatever is already
                    # propagating into this block (a failure from `asyncio.wait`, from
                    # `_raise_if_any_task_genuinely_failed`, or from `server.shut_down()` on the
                    # idle-exit branch) is the *primary* failure, and a distinct exception a
                    # cancelled task produces while being torn down must not silently replace it —
                    # exactly the masking class round-6 review found this block's own generic
                    # re-raise could cause, since raising inside a `finally` unconditionally
                    # displaces whatever exception was already in flight. The exception *object*
                    # itself is kept, not only a boolean flag it exists — round-7 review found
                    # that a boolean alone could not distinguish "a task raised something new
                    # during cancellation" from "this is the exact same exception `gather` is
                    # simply reporting again for the task that already raised it as the primary,"
                    # which produced a misleading duplicate log entry on every ordinary
                    # lifecycle-task failure — the identical `idle_task`, still `done()`, still
                    # holding the same exception object, is genuinely gathered a second time here.
                    primary_exception = sys.exc_info()[1]
                    for task in tasks:
                        task.cancel()
                    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
                    # `return_exceptions=True` is what keeps one task's failure from skipping the
                    # cancellation of the rest — but it also *collects* every exception instead of
                    # raising it, which silently swallowed exceptions that must never be
                    # swallowed. Concretely: if a signal won the `asyncio.wait` snapshot above
                    # while a lifecycle task was concurrently raising — `ShutdownTimeoutError`
                    # from an in-progress `shut_down()`, or any other genuine exception, such as
                    # `idle_self_stop`'s own inode-drift check propagating an unexpected `stat`
                    # failure — that exception arrives here as a *return value*, never seen by
                    # `_raise_if_any_task_genuinely_failed` (which only inspected the earlier
                    # `done` set). Inspecting the outcomes is what routes a shutdown-deadline
                    # failure to the directed terminal path and re-raises everything else
                    # *when nothing else is already propagating*, rather than dropping either
                    # kind on the floor or masking whatever primary failure brought us here.
                    _surface_any_genuine_task_failure(
                        outcomes, sock_path, primary_exception=primary_exception
                    )
        except ShutdownTimeoutError:
            _force_exit_after_failed_graceful_shutdown(sock_path)
        except BaseException:
            # `server` is already a bound, listening socket the instant `serve()` returns — a
            # failure in any setup step between here and the signal-handler/task-installation
            # block above (`chmod`, signal handler installation, task creation) must not leave
            # that listener open with nobody holding it, nor its socket path behind on disk. The
            # same resource-leak-on-exception-path shape recurs across this codebase (the store in
            # `ServiceContext.assemble`, the socket in `lifecycle._connect`, the background tasks
            # just above); `shut_down()` here is safe to run unconditionally even if the idle-exit
            # branch above already ran its own identical shutdown, since
            # `asyncio.Server.close()`/`wait_closed()` are both themselves idempotent no-ops once
            # already closed (verified directly against the installed Python 3.12.3 source) and
            # `close_all_connections` against an already-empty connection set is trivially a
            # no-op too.
            #
            # A bare `await server.shut_down()` here would let *this* retry's own failure
            # **replace** whatever is already propagating into this `except` clause — the
            # identical exception-masking class already fixed once for `ctx.close()` in the
            # outer `finally` below, now recurring at this call site specifically because this
            # retry had no `try` of its own around it. Unlike the outer `finally`, there is no
            # "nothing was already failing" case to distinguish here: reaching this `except`
            # clause at all means something already failed — confirmed directly (`sys.exc_
            # info()`'s `exc_value` is never `None` inside a running `except BaseException:`
            # block, since being inside it at all requires an active exception) — so this
            # retry's own failure is always the *secondary* one, logged, never allowed to
            # displace whatever the bare `raise` below re-raises.
            try:
                await server.shut_down()
            except ShutdownTimeoutError:
                # Ahead of the broad handler below on purpose: a shutdown deadline expiring *here*
                # is the same terminal condition as one expiring on the ordinary paths, and the
                # broad handler would otherwise log it as a mere secondary failure and let
                # execution fall through to ordinary propagation and `ctx.close()` — exactly the
                # "keep going after the graceful path already gave up" the operator's direction
                # rules out. The primary exception that brought us into this clause is logged
                # first, since forcing the exit means it will not propagate to anyone.
                logging.getLogger("zikaron.service").exception(
                    "shutdown deadline expired while handling an earlier failure"
                )
                _force_exit_after_failed_graceful_shutdown(sock_path)
            except BaseException:
                logging.getLogger("zikaron.service").exception(
                    "shut_down() failed while handling an earlier failure"
                )
            sock_path.unlink(missing_ok=True)
            raise
    finally:
        await _close_context_preserving_any_active_failure(ctx)


async def _close_context_preserving_any_active_failure(ctx: ServiceContext) -> None:
    """Close the store, without letting a close failure displace a failure already propagating.

    A bare `await ctx.close()` in `run()`'s own `finally` would let a close failure **replace**
    whatever exception was propagating out of the `try` — the identical exception-masking class
    already fixed once inside `ServiceContext.assemble` itself (a *different* call site: this is
    `main.run`'s own outer cleanup, not construction's). `sys.exc_info()` is what distinguishes
    "close failed while something else was already failing" from "close failed on an otherwise
    normal exit": only the first case has a primary exception worth preserving over the close
    failure; the second has nothing to mask, so a close failure there is the one thing genuinely
    wrong and must propagate as itself.
    """
    _exc_type, exc_value, _exc_tb = sys.exc_info()
    try:
        await ctx.close()
    except BaseException:
        if exc_value is not None:
            logging.getLogger("zikaron.service").exception(
                "failed to close the store while handling an earlier failure"
            )
        else:
            raise


def main() -> None:
    """The server entry point: `sys.argv[1:3]` are `sock_path` and `store_dir`, exactly as
    `lifecycle.default_server_command` constructs them.

    Deliberately a plain `asyncio.run(...)` with no exception handling of its own: the
    operator-directed hard-exit fallback for a graceful shutdown that has already tried and failed
    lives **inside** `run()`, at the point the failure actually happens, not out here. Confirmed by
    direct measurement why it cannot live here: `asyncio.run` cancels and awaits every remaining
    task before re-raising anything, and the very task that made shutdown's deadline expire is by
    definition one that did not finish cancelling — so `asyncio.run`'s own teardown hangs forever
    and an `except` at this level is never reached at all. Every *other* failure — a startup
    failure, a lifecycle crash, a store close failure — propagates from here normally, with its
    real traceback and a non-zero exit status, which is what makes it diagnosable.
    """
    sock_path = Path(sys.argv[1])
    store_dir = Path(sys.argv[2])
    asyncio.run(run(sock_path, store_dir))


def _surface_any_genuine_task_failure(
    outcomes: Sequence[object], sock_path: Path, *, primary_exception: BaseException | None
) -> None:
    """Route every genuine exception `gather(..., return_exceptions=True)` collected to somewhere
    that actually surfaces it, instead of letting any of them be silently discarded as a mere
    return value — `ShutdownTimeoutError` to the directed terminal path always, and any other
    genuine exception re-raised so it reaches this coroutine's own ordinary propagation, **but
    only when it is not the identical exception object `primary_exception` already names**.

    `return_exceptions=True` is required where it is used — it keeps one task's failure from
    skipping the cancellation of the others — but it converts exceptions into *results*, and
    checking only for `ShutdownTimeoutError` here was itself a real, measured gap: an unrelated
    genuine failure (M11's own inode-drift self-stop propagating a `PermissionError` from an
    unexpected `stat` failure, for one concrete case, or any future lifecycle task's own
    unanticipated defect) landing in `outcomes` — reachable specifically when a signal wins the
    earlier `asyncio.wait` snapshot while a lifecycle task concurrently raises something other
    than `ShutdownTimeoutError` — would otherwise vanish here with nothing downstream ever
    re-raising it, the exact "genuinely raised but never seen" shape `_raise_if_any_task_
    genuinely_failed`'s own docstring already names for the *earlier* snapshot. `asyncio.
    CancelledError` results are excluded, since every task in `tasks` is cancelled immediately
    before this `gather` runs as a matter of course, and a cancellation this function itself
    caused is not a failure to surface.

    `primary_exception` is the caller's own `sys.exc_info()[1]` read, taken *before* this
    function's own cancellation work began — the identical masking concern `_close_context_
    preserving_any_active_failure` already handles for the outer cleanup `finally`, applied here
    for this inner one: `raise outcome` runs unconditionally inside a `finally` block and would
    otherwise **replace** whatever exception was already propagating into it (a failure from
    `asyncio.wait` itself, or from `_raise_if_any_task_genuinely_failed`), surviving only as its
    `__context__` rather than as what actually reaches the caller — round-6 review found this
    exact interaction. Passing the exception *object* itself, not only a boolean that one is
    active, is what a further review round found necessary: `_raise_if_any_task_genuinely_
    failed`'s own raise leaves the task it came from still `done()` and still holding that
    identical exception object, which `gather` genuinely reports again here for the ordinary
    case where nothing else concurrently failed — a version that only checked a boolean logged
    that reappearance as if it were a *distinct* secondary failure on every ordinary lifecycle-
    task crash, which is itself a misleading diagnostic this function must not produce.
    `ShutdownTimeoutError` is deliberately exempt from the identity check and always routes to
    the terminal path regardless: `_force_exit_after_failed_graceful_shutdown` calls `os._exit`
    and never returns, so there is no "caller" for it to displace anything from — the process
    simply ends. A genuine, *distinct* non-timeout secondary failure, when a primary is already
    active, is logged rather than raised, so the operator can still see it happened without it
    silently taking the primary's place.
    """
    for outcome in outcomes:
        if isinstance(outcome, ShutdownTimeoutError):
            logging.getLogger("zikaron.service").error(
                "a lifecycle task's graceful shutdown exceeded its deadline: %s", outcome
            )
            _force_exit_after_failed_graceful_shutdown(sock_path)
        elif (
            isinstance(outcome, BaseException)
            and not isinstance(outcome, asyncio.CancelledError)
            and outcome is not primary_exception
        ):
            if primary_exception is not None:
                logging.getLogger("zikaron.service").error(
                    "a lifecycle task raised %r while an earlier failure was already propagating "
                    "— the earlier failure is what this process reports",
                    outcome,
                )
            else:
                raise outcome


def _force_exit_after_failed_graceful_shutdown(sock_path: Path) -> None:
    """The one terminal path: graceful shutdown's own deadline expired, so end the process here.

    Called from inside the coroutine `asyncio.run` is running, **not** from `main()` outside it.
    Confirmed by direct measurement why the outer placement was wrong: `asyncio.run` cancels and
    awaits every remaining task before re-raising, and the very task that made this deadline expire
    is by definition one that did not finish cancelling — so `asyncio.run`'s own teardown hangs
    forever and an `except` outside it is never reached at all.

    Deliberately skips both `run()`'s own `except BaseException:` shutdown retry and its outer
    `finally`'s `ctx.close()`: a second `shut_down()` with a fresh 5 s deadline and a store close
    are exactly the "keep asking the graceful path to try again" the operator's direction rules out
    once it has already failed once, and either could hang on the same stuck task. The socket is
    unlinked first so no client can find a dead endpoint, then the log record is written — `log.py`
    configures a plain `logging.FileHandler`, which flushes each record synchronously, so the
    diagnostic survives `os._exit` skipping `logging`'s own atexit flush — and only then does the
    process end.
    """
    sock_path.unlink(missing_ok=True)
    logging.getLogger("zikaron.service").exception(
        "graceful shutdown did not complete in time — forcing process exit"
    )
    _force_exit_after_shutdown_timeout()


def _force_exit_after_shutdown_timeout() -> None:
    """The one call this module makes to `os._exit` — factored into its own function purely so a
    test can monkeypatch *this* name to a spy rather than ever letting the real, un-catchable
    `os._exit` run inside the test process itself. `os._exit` bypasses the whole interpreter, with
    no way for any `except`/`finally` in the calling process (including a test's own) to intervene
    once it has been called — calling it for real from inside a `pytest` worker would kill the
    test run, not merely the code under test, which is exactly the mistake this indirection exists
    to make structurally hard to make by accident.

    **Directed by the human operator:** keep the graceful shutdown path exactly as
    built — it stays the *first* thing tried, with its own real 5 s deadline — and if that deadline
    expires, end the process rather than chasing every `asyncio`-internals edge case that could
    theoretically leave something open (`design/architecture.md` §"Idle self-stop"). `os._exit` is
    deliberately used over `sys.exit`/a bare `return`: it skips Python's own interpreter shutdown
    (atexit handlers, `finally` blocks, non-daemon thread joins) entirely, which is the one
    guarantee this fallback exists to provide — a graceful shutdown that has already failed once is
    not a promising place to still be waiting on those to complete cleanly either."""
    os._exit(1)  # pragma: no cover — deliberately never exercised for real; see the note above.


if __name__ == "__main__":
    main()
