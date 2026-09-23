"""`zikaron.service.main.run` — the process-entry-point coroutine, specifically its own resource
ownership: once `serve()` has bound a real listening socket, a failure in any of the setup steps
that still run before the idle/signal race begins (`chmod` and task creation) must not leave that
listener open with nobody holding it, nor its socket path behind on disk. Every other lifecycle test
exercises `run()`/`main()` only indirectly, as a subprocess
`test_service_lifecycle_integration.py` spawns — this is the one place `run()` itself is called
directly as a plain coroutine, which is what makes a setup-step failure between `serve()` and that
race reachable without needing a real signal or a real client connection at all.

**Signal-handler installation is no longer one of those steps**, and the test that it precedes the
bind is here for the same reason: the ordering is only observable from inside the process. Until
the handlers are on, a `SIGTERM` gets its default disposition and leaves the socket file behind —
and no caller can wait for the moment they go on, since `asyncio.start_unix_server` serves from the
instant it returns.

Default tier: `FastEmbedEncoder.load` is monkeypatched to a `FakeEncoder`-compatible stand-in so
`ServiceContext.assemble` (which `run()` calls internally) does not pay a real model load, matching
`test_service_context_assemble.py`'s own established pattern for testing this exact code path
hermetically.
"""

import asyncio
import logging
import os
import signal
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.fake_encoder import FakeEncoder
from zikaron.core.config.resolution import resolve
from zikaron.core.store.store import Store
from zikaron.service import main
from zikaron.service.server import ShutdownTimeoutError


def _event_loop_class() -> type[asyncio.AbstractEventLoop]:
    """The running loop's class — what the tests below patch signal-handler methods onto.

    The class rather than the instance, because `main.run` calls `asyncio.run` and so builds a loop
    of its own that these tests never hold a reference to. Only callable from inside a running loop,
    which every caller is.
    """
    return type(asyncio.get_running_loop())


async def test_a_setup_failure_after_binding_closes_the_listener_and_unlinks_the_socket(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Task creation is the setup step made to fail here, standing in for the fallible operations
    between `serve()` returning a bound listener and the idle/signal race beginning — `chmod` and
    task creation are both in that window, and this test targets one of them directly rather than
    trying to force both. Before this fix, `run()`'s only `finally` closed the `ServiceContext` and
    said nothing about the listener `serve()` had already bound: the socket path would still exist
    on disk and the underlying `asyncio.Server` would still be open, with nothing left holding a
    reference to close it.

    **It used to fail `loop.add_signal_handler` instead, and that stopped reaching this window.**
    The handlers now go on before the bind, so a failure there aborts before any socket exists and
    the assertion below would hold whether or not `run()` cleaned anything up — a guard passing
    over a state it can no longer produce. Retargeted rather than deleted, since the property it
    names is still real for the steps that remain."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    def _task_creation_always_fails(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("task creation failed, deliberately, for this test")

    monkeypatch.setattr(main, "_self_stopping_tasks", _task_creation_always_fails)

    with pytest.raises(RuntimeError, match="task creation failed"):
        await main.run(sock_path, store_dir)

    # The listener `serve()` bound must not survive this failure: its socket path is gone, which
    # is the one externally observable fact a test with no reference to the closed
    # `asyncio.Server` object itself can still check directly.
    assert not sock_path.exists()


async def test_the_signal_handlers_are_installed_before_the_socket_is_bound(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering that decides whether a `SIGTERM` can leave a socket file behind.

    `serve()` publishes `sock_path` the instant it binds. A `SIGTERM` arriving before the handlers
    are on gets its default disposition — the process dies where it stands and the socket stays on
    disk, which start-if-absent then reads as a live service and connects to nothing. The window is
    small and widens under load, which is exactly the shape that makes it an intermittent rather
    than a bug somebody notices.

    **Asserted here rather than by signalling a real process, because no external observer can see
    it.** A test that waits for the socket and then signals is waiting on the *start* of the very
    window it means to rule out, and there is no later event to wait for instead:
    `asyncio.start_unix_server` accepts from the moment it returns, so even a successful health
    call proves only that the listener is up. What is observable from inside is that
    `loop.add_signal_handler` installs a process-wide disposition, so reading it at the moment
    `serve()` is called answers
    the question directly.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    before = signal.getsignal(signal.SIGTERM)
    at_bind_time: list[object] = []

    async def _record_the_disposition_then_stop(*_args: object, **_kwargs: object) -> None:
        at_bind_time.append(signal.getsignal(signal.SIGTERM))
        raise RuntimeError("bound, deliberately, for this test")

    monkeypatch.setattr(main, "serve", _record_the_disposition_then_stop)

    with pytest.raises(RuntimeError, match="bound, deliberately"):
        await main.run(sock_path, store_dir)

    assert at_bind_time, "serve() was reached, so the reading below is a real one"
    assert at_bind_time[0] is not before, (
        "SIGTERM still had its entry disposition when the socket was about to be published"
    )
    # `SIG_DFL` rather than `before`: `loop.remove_signal_handler` does not restore the previous
    # disposition, it installs the default one — measured, not assumed. Asserting `is before` would
    # pass here only because this runner leaves SIGTERM at `SIG_DFL`, and would fail against correct
    # code under any runner that installs its own.
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL, (
        "and the handler is removed again on the way out, whatever the way out is"
    )


async def test_a_failure_after_both_tasks_exist_still_cancels_and_awaits_every_one(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`idle_task`/`signal_wait` are both created before `asyncio.wait` is ever called on them —
    a failure reaching this point from *inside* that call (or from `run()` itself being cancelled
    while awaiting it) used to jump straight past the cancellation loop that only ran after
    `asyncio.wait` returned normally, leaking whichever tasks had already been created.
    `asyncio.wait` itself is the fallible step forced to fail here, standing in for that whole
    class of failure — it is the one call that only happens after both tasks genuinely exist,
    which is exactly the window this test targets and
    `test_a_setup_failure_after_binding_closes_the_listener_and_unlinks_the_socket` (a failure
    *before* either task exists) cannot reach."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    observed_tasks: list[asyncio.Task[object]] = []

    async def _wait_records_tasks_then_fails(
        tasks: object, **_kwargs: object
    ) -> tuple[set[object], set[object]]:
        assert isinstance(tasks, set)
        observed_tasks.extend(tasks)
        raise RuntimeError("asyncio.wait failed, deliberately, for this test")

    monkeypatch.setattr(asyncio, "wait", _wait_records_tasks_then_fails)

    with pytest.raises(RuntimeError, match=r"asyncio\.wait failed"):
        await main.run(sock_path, store_dir)

    assert not sock_path.exists()
    # idle self-stop, the deferred-load watch (this store already exists, so `assemble` took the
    # open path and left a load running), and the signal wait. Counted exactly rather than
    # loosely: the point of this test is that *every* task created reaches a terminal state, and
    # a count that tolerated extras would silently stop covering the next one added.
    assert len(observed_tasks) == 3
    for task in observed_tasks:
        assert task.done(), f"{task} was left running after run() propagated its failure"


async def test_a_context_close_failure_does_not_mask_an_earlier_setup_failure(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`run()`'s own outer `finally: await ctx.close()` used to let a close failure **replace**
    whatever exception was already propagating — the identical exception-masking class already
    fixed once inside `ServiceContext.assemble` itself, but at a different call site: this is
    `run()`'s own cleanup, which runs *after* `assemble` has already returned successfully,
    against whatever failure happens later in `run()`'s own body. Forces both a
    `loop.add_signal_handler` failure — which, now that the handlers go on before the bind, is the
    earliest failure `run()`'s outer `finally` must preserve, reached with no socket bound and no
    `except BaseException:` clause in the way — and a
    `Store.close` failure, and asserts the *setup* failure is what a caller's own `except`
    catches — not the close failure that happened while handling it."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    def _add_signal_handler_always_fails(_sig: object, _callback: object, *_args: object) -> None:
        raise RuntimeError("signal handler installation failed, deliberately, for this test")

    monkeypatch.setattr(
        _event_loop_class(),
        "add_signal_handler",
        _add_signal_handler_always_fails,
        raising=False,
    )

    real_close = Store.close

    async def _close_fails_but_still_really_closes(self: Store) -> None:
        # `run()` must observe a raised exception from this call, to prove the setup failure
        # survives it — but the underlying connection still has to be closed for real underneath
        # that raise, or this test's own deliberately-broken monkeypatch would leak the
        # connection past its own scope and trip the unrelated leak-detection fixture over a
        # failure this test caused on purpose, not a genuine leak. Mirrors
        # `test_service_context_assemble.py`'s own established pattern for the identical situation.
        await real_close(self)
        raise OSError("store.close() failed, deliberately, for this test")

    monkeypatch.setattr(Store, "close", _close_fails_but_still_really_closes)

    with pytest.raises(RuntimeError, match="signal handler installation failed"):
        await main.run(sock_path, store_dir)


async def test_idle_self_stop_raising_after_all_tasks_exist_propagates_rather_than_exiting_clean(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`idle_task.done() and not idle_task.cancelled()` used to treat a genuinely *raised*
    `idle_self_stop` identically to a normal idle exit, since a raised task is `done()` and not
    `cancelled()` either — meaning a real crash inside the idle-poll loop (an unlink failure, a
    `shut_down()` failure, anything) would be silently swallowed by the unconditional `gather(...,
    return_exceptions=True)` in `run()`'s own cleanup `finally`, and the process would exit with
    status zero having genuinely failed. `lifecycle.idle_self_stop` is monkeypatched to raise
    immediately here, standing in for any real internal failure of that function; since `run()`
    awaits `asyncio.wait(..., return_when=asyncio.FIRST_COMPLETED)` on every task together — three
    of them here, since this store exists and so the open path creates the load watch beside the
    idle poll and the signal wait — the
    monkeypatched coroutine racing `signal_wait` at all is enough to land in the `done` set this
    test exists to defend — no synchronization needed beyond `create_task` scheduling it to run at
    the next opportunity, which `asyncio.wait` itself already waits for."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    async def _idle_self_stop_always_fails(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("idle_self_stop failed, deliberately, for this test")

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop", _idle_self_stop_always_fails
    )

    with pytest.raises(RuntimeError, match="idle_self_stop failed"):
        await main.run(sock_path, store_dir)


async def test_an_ordinary_already_done_task_failure_logs_no_false_secondary_record(
    tmp_path: Path,
    socket_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The converse of the masking-preservation test: an ordinary lifecycle-task failure — no
    concurrent, distinct secondary failure at all — must propagate with **no** "a lifecycle task
    raised ... while an earlier failure was already propagating" log record, even though `gather`
    genuinely reports the identical, already-raised exception object again during cleanup.
    An earlier version of this fix keyed only on a boolean "is a primary already active", which
    could not distinguish that reappearance from a genuinely distinct concurrent failure, and would
    have logged this exact, ordinary case as if it were one.
    """
    sock_path, store_dir = await _prepared_store_and_paths(tmp_path, socket_dir, monkeypatch)

    async def _idle_self_stop_always_fails_again(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("idle_self_stop failed, deliberately, for this test")

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop", _idle_self_stop_always_fails_again
    )

    with (
        caplog.at_level(logging.ERROR, logger="zikaron.service"),
        pytest.raises(RuntimeError, match="idle_self_stop failed"),
    ):
        await main.run(sock_path, store_dir)
    false_secondary_records = [
        record
        for record in caplog.records
        if "while an earlier failure was already propagating" in record.getMessage()
    ]
    assert false_secondary_records == []


async def test_a_shut_down_failure_while_handling_idle_self_stop_failure_preserves_the_original(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The combined regression the previous test's own docstring names but does not itself force:
    `idle_self_stop` raising lands in `run()`'s post-bind `except BaseException:` via the innermost
    `finally`'s task cancellation, which runs and re-propagates unchanged
    (`_stop_on_sigterm_or_sigint`'s own handler removal now runs *after* that clause, on the way
    out of the `async with` that wraps the bind) — and that `except` clause's own
    `server.shut_down()` retry used to have
    no `try` of its own around it, so a *second* failure there would
    **replace** the first rather than being logged as secondary. Forces both to fail and asserts
    the *original* `idle_self_stop` failure — not the `shut_down()` retry's own `RuntimeError` —
    is what `run()` actually raises."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    async def _idle_self_stop_always_fails(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("idle_self_stop failed, deliberately, for this test")

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop", _idle_self_stop_always_fails
    )

    async def _shut_down_always_fails(_self: object) -> None:
        raise OSError("shut_down() also failed, deliberately, for this test")

    monkeypatch.setattr("zikaron.service.server.RunningServer.shut_down", _shut_down_always_fails)

    with pytest.raises(RuntimeError, match="idle_self_stop failed"):
        await main.run(sock_path, store_dir)


async def test_a_failure_installing_the_second_signal_handler_still_removes_the_first(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`loop.add_signal_handler` calls with no matching `remove_signal_handler` on any path used
    to leave a handler permanently installed even after a fully successful run — including the
    narrower case this test targets specifically: `SIGTERM` (installed first, per
    `_stop_on_sigterm_or_sigint`'s own `(signal.SIGTERM, signal.SIGINT)` order) succeeding while
    `SIGINT` (installed second) fails, which used to leave `SIGTERM`'s handler installed forever
    with nothing removing it, closing over this specific invocation's `stop` event. Wraps the real
    `remove_signal_handler` to record which signals it was actually called with, rather than
    merely asserting the fake `add_signal_handler` was called the expected number of times — the
    removal is the behaviour
    under test,
    not the installation."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    removed: list[object] = []
    real_remove_signal_handler = _event_loop_class().remove_signal_handler

    def _add_signal_handler_fails_on_the_second_call(
        _loop: object, sig: object, _callback: object, *_args: object
    ) -> None:
        if sig == signal.SIGINT:
            raise RuntimeError("second signal handler installation failed, for this test")

    def _remove_signal_handler_records_calls(loop: asyncio.AbstractEventLoop, sig: int) -> bool:
        removed.append(sig)
        result = real_remove_signal_handler(loop, sig)
        assert isinstance(result, bool)
        return result

    monkeypatch.setattr(
        _event_loop_class(),
        "add_signal_handler",
        _add_signal_handler_fails_on_the_second_call,
        raising=False,
    )
    monkeypatch.setattr(
        _event_loop_class(),
        "remove_signal_handler",
        _remove_signal_handler_records_calls,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="second signal handler installation failed"):
        await main.run(sock_path, store_dir)

    assert removed == [signal.SIGTERM]


async def test_signal_handlers_are_removed_after_a_fully_successful_signal_driven_exit(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The normal-exit half of the same fix: even a run that installs both signal handlers
    successfully and then exits cleanly (here, via the `stop` event being set directly rather
    than a real `os.kill`) must not leave either handler installed afterward — closing over a
    `stop` event whose own `run()` invocation has already returned is exactly the kind of stale
    reference the removal fix exists to prevent.

    **It is also the only in-process test that lets the pre-bind-signal path run to a clean exit.**
    That path is what the handler-before-bind ordering newly made reachable: the callback fires
    synchronously inside `add_signal_handler`, which now runs *before* `serve()`, so `stop` is
    already set when the socket is bound and the run proceeds bind → `chmod` → tasks → unlink →
    `shut_down()` → clean return. Three other tests in this file fire `SIGTERM` the same way but
    force a failure downstream of the unlink, so only here does the socket assertion below pin
    `run()`'s own signal-path unlink rather than a later cleanup's — the one sibling that also
    asserts on the file
    (`test_a_shutdown_timeout_forces_process_exit_from_inside_the_running_coroutine`) has the
    force-exit unlink satisfying it as well, and the other two assert nothing about it."""
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    real_add_signal_handler = _event_loop_class().add_signal_handler
    installed_events: dict[int, Callable[..., object]] = {}

    def _add_signal_handler_captures_and_fires_sigterm(
        loop: asyncio.AbstractEventLoop,
        sig: int,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        # Firing `SIGTERM`'s own callback synchronously, right here inside the call that installs
        # it, eliminates the race a separately-scheduled polling task would otherwise have against
        # `run()`'s own setup progressing — no timing assumption of any kind, since this runs at
        # the exact point `run()` itself calls `add_signal_handler(signal.SIGTERM, stop.set)`,
        # never before or after it. `stop.set()` merely sets an `asyncio.Event`, which is safe to
        # call synchronously from here (it does not itself await anything), and `run()`'s own
        # `signal_wait` task is what actually observes it once installed.
        installed_events[sig] = callback
        real_add_signal_handler(loop, sig, callback, *args)
        if sig == signal.SIGTERM:
            callback(*args)

    removed: list[object] = []
    real_remove_signal_handler = _event_loop_class().remove_signal_handler

    def _remove_signal_handler_records_calls(loop: asyncio.AbstractEventLoop, sig: int) -> bool:
        removed.append(sig)
        result = real_remove_signal_handler(loop, sig)
        assert isinstance(result, bool)
        return result

    monkeypatch.setattr(
        _event_loop_class(),
        "add_signal_handler",
        _add_signal_handler_captures_and_fires_sigterm,
        raising=False,
    )
    monkeypatch.setattr(
        _event_loop_class(),
        "remove_signal_handler",
        _remove_signal_handler_records_calls,
        raising=False,
    )

    await main.run(sock_path, store_dir)

    assert set(removed) == {signal.SIGTERM, signal.SIGINT}
    # The signal path's own unlink. From 3.13 a closing Unix server would remove the socket path
    # itself, at which point this assertion would stop distinguishing `run()`'s unlink from
    # asyncio's; `serve` switches that off wherever it exists, so this stays a statement about
    # `run()` on every supported version.
    assert not sock_path.exists()


async def test_a_signal_with_an_idle_open_connection_still_returns_promptly(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact deadlock a version of `main.run` used to hang on, and this test independently
    reproduces before the fix landed: `main.run` used to wait on `asyncio.Server.serve_forever()`
    as one of the three things that could mean "stop," and cancelling that task makes
    `asyncio.Server` itself call `close()` and await its **own** `wait_closed()` before
    re-raising — a second, independent wait for the same connections `RunningServer.shut_down()`
    exists to drain, which ran *first* and deadlocked against an idle open connection before this
    coroutine's own draining logic ever got a chance to run.

    A real client connects, sends one request, reads its real response — proving the connection
    is genuinely registered server-side, not merely open — and then stays connected, deliberately
    never closing, while this test delivers a real `SIGTERM` to the running process (itself, via
    `os.kill(os.getpid(), ...)`, since `run()` is under test as a plain in-process coroutine here,
    not a subprocess). `asyncio.wait_for` bounds the whole assertion so a genuine regression fails
    this test in a few seconds rather than hanging the suite. Confirmed by direct measurement
    before writing this test: reverting `main.run` to the pre-fix `serve_forever`-based structure
    and running this exact scenario left `run()` still pending after the same bound.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    run_task = asyncio.create_task(main.run(sock_path, store_dir))
    try:
        for _ in range(500):
            if sock_path.exists():
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("the server never bound its socket")

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        try:
            writer.write(b'{"jsonrpc": "2.0", "id": 1, "method": "health", "params": {}}\n')
            await writer.drain()
            response_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            assert b'"ready": true' in response_line

            # The connection stays open here — deliberately never closed by this test — the
            # exact idle-but-registered state the deadlock this test defends against needs.
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.wait_for(run_task, timeout=5.0)
        finally:
            writer.close()
    finally:
        if not run_task.done():
            run_task.cancel()


async def test_a_shutdown_timeout_forces_process_exit_from_inside_the_running_coroutine(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Directed by the human operator:** keep the graceful shutdown path exactly as
    already built, and if its own 5 s deadline expires, end the process rather than chasing every
    `asyncio`-internals edge case that could theoretically leave something open.

    The force-exit fires from **inside** the coroutine `asyncio.run` is running, not from `main()`
    outside it — an earlier version caught `TimeoutError` around `asyncio.run(...)` and was proven
    unreachable by direct measurement: `asyncio.run` cancels and awaits every remaining task before
    re-raising, and the very task that made the deadline expire is by definition one that did not
    finish cancelling, so the runner's own teardown hangs forever and the outer `except` never
    runs. This test therefore drives `run()` itself, with `shut_down` raising the dedicated
    `ShutdownTimeoutError`, and asserts the spy fired — proving the handling is on a path `run()`
    actually reaches.

    Two separate safety measures, both deliberate: the spy replaces
    `main._force_exit_after_shutdown_timeout`, never the real `os._exit` (un-catchable, and would
    kill the `pytest` worker itself rather than merely the code under test); and `os._exit` itself
    is *additionally* replaced with a fail-fast sentinel, so if a future edit ever moved the real
    call out from behind that indirection, this test fails loudly instead of terminating the test
    run.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    def _load_fake_encoder(_model_name: str) -> FakeEncoder:
        return FakeEncoder()

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load", staticmethod(_load_fake_encoder)
    )

    def _os_exit_must_never_be_called_for_real(_code: int) -> None:
        raise AssertionError(
            "the real os._exit was reached — the _force_exit_after_shutdown_timeout indirection "
            "was bypassed, which would kill the pytest worker in a real run"
        )

    monkeypatch.setattr(os, "_exit", _os_exit_must_never_be_called_for_real)

    forced_exit_calls: list[None] = []

    def _spy_force_exit() -> None:
        forced_exit_calls.append(None)

    monkeypatch.setattr(main, "_force_exit_after_shutdown_timeout", _spy_force_exit)

    async def _shut_down_always_times_out(_self: object) -> None:
        raise ShutdownTimeoutError("shutdown deadline expired, deliberately, for this test")

    monkeypatch.setattr(
        "zikaron.service.server.RunningServer.shut_down", _shut_down_always_times_out
    )

    # A signal exit is the path that calls `shut_down()` directly from `run()`'s own body; firing
    # `SIGTERM`'s handler synchronously the instant it is installed avoids any race between this
    # test and `run()`'s own setup (the same technique the signal-handler-removal tests use).
    real_add_signal_handler = _event_loop_class().add_signal_handler

    def _add_signal_handler_and_fire_sigterm(
        loop: asyncio.AbstractEventLoop,
        sig: int,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        real_add_signal_handler(loop, sig, callback, *args)
        if sig == signal.SIGTERM:
            callback(*args)

    monkeypatch.setattr(
        _event_loop_class(),
        "add_signal_handler",
        _add_signal_handler_and_fire_sigterm,
        raising=False,
    )

    await main.run(sock_path, store_dir)

    # `>= 1`, not `== 1`: in production the first `os._exit` never returns, so exactly-once holds
    # by construction. A spy that *does* return lets execution continue into whatever later
    # terminal route the same failure also reaches, which is an artefact of the spy rather than a
    # property of the code. What matters, and what this asserts, is that the terminal path is
    # reached at all rather than the failure being swallowed.
    assert len(forced_exit_calls) >= 1
    assert not sock_path.exists(), "the socket must be unlinked before the process is ended"


async def _prepared_store_and_paths(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """A created store plus `(sock_path, store_dir)`, with `FastEmbedEncoder.load` stubbed.

    The same six-line preamble every test in this file needs; factored out here rather than
    copied a seventh time now that three more shutdown-routing tests need exactly it.
    """
    store_dir = tmp_path / ".zikaron"
    store_dir.mkdir()
    sock_path = socket_dir / "server.sock"
    config = resolve(tmp_path / "system.toml", tmp_path / "project.toml")

    class _FakeEmbedder:
        model_name = config.get_str("embed_model")
        dim = config.get_int("embed_dim")

    async with await Store.create(store_dir, config, _FakeEmbedder()):
        pass

    monkeypatch.setattr(
        "zikaron.service.context.FastEmbedEncoder.load",
        staticmethod(lambda _model_name: FakeEncoder()),
    )
    return sock_path, store_dir


def _spy_on_force_exit(monkeypatch: pytest.MonkeyPatch) -> list[None]:
    """Replace the force-exit indirection with a spy, and the real `os._exit` with a fail-fast
    sentinel — the two-layer protection needed by every test that drives a terminal shutdown
    path."""

    def _os_exit_must_never_be_called_for_real(_code: int) -> None:
        raise AssertionError(
            "the real os._exit was reached — the _force_exit_after_shutdown_timeout indirection "
            "was bypassed, which would kill the pytest worker in a real run"
        )

    monkeypatch.setattr(os, "_exit", _os_exit_must_never_be_called_for_real)

    calls: list[None] = []
    monkeypatch.setattr(main, "_force_exit_after_shutdown_timeout", lambda: calls.append(None))
    return calls


async def test_an_idle_path_shutdown_timeout_reaches_the_terminal_path(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The idle exit calls `shut_down()` inside `lifecycle.idle_self_stop`, not in `run()`'s own
    body, so its `ShutdownTimeoutError` reaches `run()` by a different route than the signal
    path's: the task completes, lands in `asyncio.wait`'s `done` set, and
    `_raise_if_any_task_genuinely_failed` re-raises it. This test pins that route as sound so it
    stays that way."""
    sock_path, store_dir = await _prepared_store_and_paths(tmp_path, socket_dir, monkeypatch)
    forced_exit_calls = _spy_on_force_exit(monkeypatch)

    async def _idle_self_stop_times_out_shutting_down(*_a: object, **_k: object) -> None:
        raise ShutdownTimeoutError("idle-path shutdown deadline expired, for this test")

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop", _idle_self_stop_times_out_shutting_down
    )

    await main.run(sock_path, store_dir)

    # `>= 1`, not `== 1`: in production the first `os._exit` never returns, so exactly-once holds
    # by construction. A spy that *does* return lets execution continue into whatever later
    # terminal route the same failure also reaches, which is an artefact of the spy rather than a
    # property of the code. What matters, and what this asserts, is that the terminal path is
    # reached at all rather than the failure being swallowed.
    assert len(forced_exit_calls) >= 1


async def test_a_shutdown_timeout_while_cleaning_up_another_failure_reaches_the_terminal_path(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unrelated lifecycle failure enters `except BaseException:`, whose cleanup `shut_down()`
    then times out. That nested handler used to log the `ShutdownTimeoutError` as a mere secondary
    failure and fall through to ordinary propagation and `ctx.close()` — exactly the "keep going
    after the graceful path already gave up" the operator's direction rules out."""
    sock_path, store_dir = await _prepared_store_and_paths(tmp_path, socket_dir, monkeypatch)
    forced_exit_calls = _spy_on_force_exit(monkeypatch)

    async def _idle_self_stop_fails_unrelated(*_a: object, **_k: object) -> None:
        raise RuntimeError("an unrelated lifecycle failure, for this test")

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop", _idle_self_stop_fails_unrelated
    )

    async def _shut_down_times_out(_self: object) -> None:
        raise ShutdownTimeoutError("cleanup shutdown deadline expired, for this test")

    monkeypatch.setattr("zikaron.service.server.RunningServer.shut_down", _shut_down_times_out)

    # The original `RuntimeError` re-raises only because the force-exit spy *returns*; in
    # production `os._exit` ends the process at that point and this `raise` is never reached.
    # Expecting it here is accounting for the spy, not asserting production behaviour.
    with pytest.raises(RuntimeError, match="an unrelated lifecycle failure"):
        await main.run(sock_path, store_dir)

    # `>= 1`, not `== 1`: in production the first `os._exit` never returns, so exactly-once holds
    # by construction. A spy that *does* return lets execution continue into whatever later
    # terminal route the same failure also reaches, which is an artefact of the spy rather than a
    # property of the code. What matters, and what this asserts, is that the terminal path is
    # reached at all rather than the failure being swallowed.
    assert len(forced_exit_calls) >= 1


async def test_a_shutdown_timeout_surfacing_only_during_task_cancellation_still_forces_exit(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a signal won the `asyncio.wait` snapshot while `idle_self_stop` was concurrently inside
    its own `shut_down()`, that task's `ShutdownTimeoutError` arrives as a **return value** of
    `gather(..., return_exceptions=True)` in the cancellation `finally` — never inspected by
    `_raise_if_any_task_genuinely_failed`, which only saw the earlier `done` set — and would be
    silently discarded without a further check. `_surface_any_genuine_task_failure` is what
    routes it to the terminal path instead."""
    sock_path, store_dir = await _prepared_store_and_paths(tmp_path, socket_dir, monkeypatch)
    forced_exit_calls = _spy_on_force_exit(monkeypatch)

    async def _idle_self_stop_times_out_when_cancelled(*_a: object, **_k: object) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Stands in for a task that was already inside its own `shut_down()` when the signal
            # exit began, and whose deadline expires as it is being torn down.
            raise ShutdownTimeoutError(
                "deadline expired during cancellation, for this test"
            ) from None

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop", _idle_self_stop_times_out_when_cancelled
    )

    # Make the signal win the initial wait, deterministically, by firing SIGTERM's own handler
    # synchronously the instant it is installed.
    real_add_signal_handler = _event_loop_class().add_signal_handler

    def _add_and_fire_sigterm(
        loop: asyncio.AbstractEventLoop,
        sig: int,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        real_add_signal_handler(loop, sig, callback, *args)
        if sig == signal.SIGTERM:
            callback(*args)

    monkeypatch.setattr(
        _event_loop_class(),
        "add_signal_handler",
        _add_and_fire_sigterm,
        raising=False,
    )

    await main.run(sock_path, store_dir)

    # `>= 1`, not `== 1`: in production the first `os._exit` never returns, so exactly-once holds
    # by construction. A spy that *does* return lets execution continue into whatever later
    # terminal route the same failure also reaches, which is an artefact of the spy rather than a
    # property of the code. What matters, and what this asserts, is that the terminal path is
    # reached at all rather than the failure being swallowed.
    assert len(forced_exit_calls) >= 1


async def test_a_non_shutdown_timeout_failure_surfacing_during_cancellation_still_propagates(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The identical signal-wins-the-snapshot race as the test above, but for a genuine
    exception that is **not** `ShutdownTimeoutError`. An earlier version of
    `_surface_any_genuine_task_failure` (then named `_force_exit_if_shutdown_timed_out`) checked
    only for that one exception type and silently discarded anything else found among `gather`'s
    collected outcomes, which became newly reachable once the inode-drift self-stop started
    deliberately letting an unexpected `stat` failure (a genuine `PermissionError`, for one
    concrete case) propagate out of `idle_self_stop` rather than swallowing it. A lifecycle task
    raising something other than `ShutdownTimeoutError` while a signal wins the earlier
    `asyncio.wait` snapshot must still reach this coroutine's own ordinary propagation, not vanish
    silently the way `ShutdownTimeoutError` alone used to be the only exception routed anywhere.
    """
    sock_path, store_dir = await _prepared_store_and_paths(tmp_path, socket_dir, monkeypatch)

    async def _idle_self_stop_raises_something_else_when_cancelled(
        *_a: object, **_k: object
    ) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Stands in for a task concurrently raising a genuine, unrelated exception at the
            # exact moment a signal is winning the earlier snapshot — the inode-drift check's own
            # `PermissionError` is the concrete real-world case this stands in for.
            raise PermissionError("deliberately denied, for this test") from None

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop",
        _idle_self_stop_raises_something_else_when_cancelled,
    )

    real_add_signal_handler = _event_loop_class().add_signal_handler

    def _add_and_fire_sigterm(
        loop: asyncio.AbstractEventLoop,
        sig: int,
        callback: Callable[..., object],
        *args: object,
    ) -> None:
        real_add_signal_handler(loop, sig, callback, *args)
        if sig == signal.SIGTERM:
            callback(*args)

    monkeypatch.setattr(
        _event_loop_class(),
        "add_signal_handler",
        _add_and_fire_sigterm,
        raising=False,
    )

    with pytest.raises(PermissionError, match="deliberately denied, for this test"):
        await main.run(sock_path, store_dir)


async def test_a_secondary_cancellation_failure_does_not_mask_the_primary_exception(
    tmp_path: Path,
    socket_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The exact interaction: a primary exception already propagating into
    the task-cleanup `finally` must not be **replaced** by a distinct, secondary exception a
    different task raises while being cancelled — `raise outcome` inside a `finally` block
    displaces whatever was already in flight unconditionally, surviving only as the secondary's
    own `__context__` rather than as what the caller actually sees, which is precisely the
    exception-masking class `_close_context_preserving_any_active_failure` already exists to
    avoid for the *outer* cleanup, now fixed here for this *inner* one too.

    Constructed with a genuine primary and a genuine, distinct secondary, not a contrived
    monkeypatch of the masking mechanism itself, and specifically ordered so a version that
    merely iterates `outcomes` and raises the first non-`ShutdownTimeoutError` exception it finds
    cannot pass by coincidence of iteration order: `asyncio.wait` itself is replaced with one that
    raises `RuntimeError("primary failure")` directly, entering the `finally` with a real, active
    primary exception while **both** `idle_task` and `signal_wait` are still genuinely running —
    neither has completed naturally, so the `finally`'s own cancellation loop is what tears down
    both. `idle_self_stop` is `idle_task`'s own coroutine, and it is the **first** entry in
    `main.py`'s own `tasks` list — meaning its outcome is `outcomes[0]` in `gather`'s own
    argument-order-preserving return, which a version of the fix that merely happened to iterate
    the primary before the secondary would pass vacuously. Making `idle_self_stop` supply the
    *secondary* failure (`PermissionError`, raised from its own `CancelledError` handler) is what
    defeats that coincidence: the secondary is deliberately the one that would be seen *first* by
    a naive iteration, so only a version that actually checks `primary_already_active` before
    raising anything from `outcomes` at all can pass this specific ordering. `main.run()` must
    still propagate the primary `RuntimeError`, never the secondary `PermissionError`.
    """
    sock_path, store_dir = await _prepared_store_and_paths(tmp_path, socket_dir, monkeypatch)

    async def _idle_self_stop_raises_a_different_error_when_cancelled(
        *_a: object, **_k: object
    ) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise PermissionError("secondary failure") from None

    real_wait = asyncio.wait
    wait_call_count = 0

    async def _wait_raises_the_primary_failure_once(
        *args: object, **kwargs: object
    ) -> tuple[set[asyncio.Task[object]], set[asyncio.Task[object]]]:
        nonlocal wait_call_count
        wait_call_count += 1
        if wait_call_count == 1:
            # A real yield first — not merely a synchronous raise — so both `idle_task` and
            # `signal_wait` genuinely get scheduled and reach their own first `await` at least
            # once before being cancelled. A task cancelled before it has ever run its first line
            # never actually reaches its own `except CancelledError` handler at all (confirmed
            # directly): `task.cancel()` on a task with no prior scheduling opportunity raises
            # `CancelledError` at task-creation granularity, not inside the coroutine's own body,
            # so the secondary failure this test depends on would never fire without this.
            await asyncio.sleep(0)
            raise RuntimeError("primary failure")
        return await real_wait(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "zikaron.service.main.lifecycle.idle_self_stop",
        _idle_self_stop_raises_a_different_error_when_cancelled,
    )
    monkeypatch.setattr(asyncio, "wait", _wait_raises_the_primary_failure_once)

    with (
        caplog.at_level(logging.ERROR, logger="zikaron.service"),
        pytest.raises(RuntimeError, match="primary failure") as excinfo,
    ):
        await main.run(sock_path, store_dir)
    assert not isinstance(excinfo.value, PermissionError)
    # The secondary failure must still be visible to the operator, distinctly from the primary —
    # Preserving the primary must not come at the cost of silently dropping the secondary
    # altogether.
    secondary_records = [
        record for record in caplog.records if "secondary failure" in record.getMessage()
    ]
    assert len(secondary_records) == 1
