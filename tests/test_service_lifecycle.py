"""`zikaron.service.lifecycle.idle_self_stop`'s own logic, in-process — no subprocess, per
`coding-standards.md` §4's carve-out for a real socket bound on a background task of this same
test process. `test_service_lifecycle_integration.py` covers the real-subprocess race conditions
(start-if-absent, connect-as-server-exits); this file covers `idle_self_stop`'s own poll-loop
decisions directly, against a real `ServiceContext` and a real `RunningServer`.

`idle_self_stop` itself never captures its own baseline — it takes `original_store_inode` as a
required parameter. Production reads that value from `ctx.store.opened_inode`, a field
`Store.open`/`Store.create` set from a plain `db_path.stat()` inside
`zikaron.core.store.connection.open_connection`, immediately after its own `aiosqlite.connect()`
returns (that module's own docstring has the full history of what was tried before landing there,
and the accepted, human-authorized gap it deliberately leaves open). Every test below instead
reads a fresh `ctx.store.path.stat()` of its own, explicitly, before starting the poll task —
this is **not** an attempt to reproduce where production actually captures the value; it exists
purely to construct a real, valid input for `idle_self_stop`'s own parameter, isolating this
file's own job (does the poll loop compare and react correctly, given *some* baseline) from
`open_connection`'s own, separately tested job (is the baseline itself trustworthy at the moment
it is captured).
"""

import asyncio
import json
import os
import socket
import subprocess
import threading
import time
import unittest.mock
from pathlib import Path

import pytest

from tests.loop_lateness import thread_lateness
from tests.service_fixtures import open_context
from zikaron.service import lifecycle, ownership, server


async def test_idle_self_stop_exits_on_a_genuine_store_replacement_even_while_active(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The inode-drift exit condition `architecture.md` §"Idle self-stop" describes: `memory.db`
    deleted and recreated at the identical path while this process still holds the original file
    open must cause a self-stop within one poll cycle — deliberately proven **while the store is
    still busy** (`in_flight` never reaches zero, `last_activity` never goes stale), so this test
    cannot pass merely because the *idle* condition also happened to be true at the same moment;
    only the replacement check can be responsible for the exit observed here.

    `IDLE_POLL_INTERVAL_SECONDS` is monkeypatched down from its real 30 s so the poll loop
    completes within a test's own reasonable wall-clock budget — the *interval* is what changes,
    never the *mechanism* being tested.
    """
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")  # never idle: `may_stop` stays `False`.
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        original_inode = ctx.store.path.stat().st_ino

        idle_task = asyncio.create_task(
            lifecycle.idle_self_stop(ctx, running, sock_path, original_store_inode=original_inode)
        )
        assert not idle_task.done(), "must not have exited before the store was ever replaced"

        ctx.store.path.unlink()
        ctx.store.path.write_text("a different store now lives at the identical path")

        await asyncio.wait_for(idle_task, timeout=5.0)
        assert not sock_path.exists(), "the socket must be unlinked on the replacement exit path"


async def test_idle_self_stop_detects_a_replacement_that_already_happened_before_it_started(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact race: `memory.db` replaced **before**
    `idle_self_stop` is even created, not merely before its first poll fires. This is what
    distinguishes "the baseline is captured at the right moment" from "the check works once
    running" — the first version of this fix could have passed the test above (which replaces
    *after* the task has already started) while still losing this earlier race, since that
    version's own capture happened inside the task's own body, later than this test's own
    replacement.

    Captures a fresh `original_inode` immediately after the context is open, with no `await`
    before the replacement below — the identical construction every test in this file uses to
    build a valid input for `idle_self_stop`'s own parameter (see this module's own docstring for
    why that is not an attempt to reproduce production's own capture site) — then replaces the
    store, and only *then* starts `idle_self_stop`. This proves the baseline supplied to
    `idle_self_stop` is genuinely independent of when the task itself happens to start: a
    version of the check that instead captured its own baseline from *inside* the task's body
    could not correctly detect a replacement that predates the task's own existence, since by the
    time such a version's own capture ran, it would already be reading the replacement.
    """
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        original_inode = ctx.store.path.stat().st_ino

        ctx.store.path.unlink()
        ctx.store.path.write_text("replaced before idle_self_stop ever started")

        idle_task = asyncio.create_task(
            lifecycle.idle_self_stop(ctx, running, sock_path, original_store_inode=original_inode)
        )
        await asyncio.wait_for(idle_task, timeout=5.0)
        assert not sock_path.exists()


async def test_idle_self_stop_does_not_exit_while_the_store_is_never_replaced_and_stays_busy(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The converse of the tests above, guarding against a version of the check that fires on
    every poll regardless of whether anything actually changed — `stat()`-ing the same,
    untouched file repeatedly must never itself look like a replacement."""
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        original_inode = ctx.store.path.stat().st_ino
        idle_task = asyncio.create_task(
            lifecycle.idle_self_stop(ctx, running, sock_path, original_store_inode=original_inode)
        )
        try:
            await asyncio.sleep(0.3)  # several poll cycles, at the shortened interval.
            assert not idle_task.done(), "an untouched store must never trigger a self-stop"
        finally:
            idle_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await idle_task
            await running.shut_down()


async def test_idle_self_stop_exits_when_the_store_is_deleted_with_nothing_recreated_yet(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `memory.db` that is deleted and never recreated (no file at all at the path right now)
    must be treated identically to a changed inode, not skipped as "nothing to compare against
    yet" — this process's own open store is not the one currently on disk either way, and a
    reader `stat`-ing an absent path must not be mistaken for a transient error worth ignoring.
    """
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        original_inode = ctx.store.path.stat().st_ino
        idle_task = asyncio.create_task(
            lifecycle.idle_self_stop(ctx, running, sock_path, original_store_inode=original_inode)
        )

        ctx.store.path.unlink()

        await asyncio.wait_for(idle_task, timeout=5.0)
        assert not sock_path.exists()


def test_a_child_that_defers_to_another_service_keeps_the_poll_going(socket_dir: Path) -> None:
    """A spawned service that exits because another holds its store has not failed: the other is
    the one to wait for. The other service here binds after the child has exited."""
    sock_path = socket_dir / "test.sock"
    deferred = unittest.mock.create_autospec(subprocess.Popen, instance=True)
    deferred.poll.return_value = ownership.ANOTHER_SERVICE_EXIT_STATUS
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def _bind_late_and_answer() -> None:
        time.sleep(0.3)
        listener.bind(str(sock_path))
        listener.listen(1)
        listener.settimeout(5.0)
        connection, _ = listener.accept()
        connection.recv(4096)
        result = {"ready": True, "store_path": "the-path", "store_id": "the-id"}
        connection.sendall(
            (json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}) + "\n").encode()
        )
        connection.close()

    thread = threading.Thread(target=_bind_late_and_answer, daemon=True)
    thread.start()
    try:
        sock, health = lifecycle._poll_until_reachable(sock_path, child=deferred)
        sock.close()
        assert health.store_path == "the-path"
    finally:
        thread.join(timeout=5.0)
        listener.close()


def test_a_child_still_alive_at_the_deadline_ends_the_poll_as_a_plain_connection_error(
    socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deadline is the only bound on a start that neither answers nor exits, and it holds the
    start-if-absent lock until then. It is told from a start that failed by the exception's type,
    so `zikaron init` advises a retry for this one and the log for that one."""
    monkeypatch.setattr(lifecycle, "_HEALTH_POLL_DEADLINE_SECONDS", 0.3)
    alive = unittest.mock.create_autospec(subprocess.Popen, instance=True)
    alive.poll.return_value = None
    with thread_lateness() as lateness:
        started = time.monotonic()
        with pytest.raises(ConnectionError) as raised:
            lifecycle._poll_until_reachable(socket_dir / "test.sock", child=alive)
        elapsed = time.monotonic() - started
    assert not isinstance(raised.value, lifecycle.StartFailedError)
    assert elapsed - lateness.seconds < 2.0, (elapsed, lateness)


class TestOnlyTheSocketThisProcessBoundIsRemoved:
    """Every stop removes the socket path through `unlink_if_still_bound`, so what decides whether
    the path is still this process's is one comparison, made the same way on every path."""

    def test_the_socket_it_bound_is_removed(self, tmp_path: Path) -> None:
        path = tmp_path / "test.sock"
        path.touch()
        lifecycle.unlink_if_still_bound(path, socket_inode=path.stat().st_ino)
        assert not path.exists()

    def test_another_file_at_the_path_is_left_alone(self, tmp_path: Path) -> None:
        """The original is held open while the other file is made, as a bound listener holds its
        socket's inode: a freed inode can be handed straight to the next file, and was on Linux
        CI, which would make the two indistinguishable by a comparison production never faces."""
        path = tmp_path / "test.sock"
        path.touch()
        with path.open("rb") as held:
            bound = os.fstat(held.fileno()).st_ino
            path.unlink()
            path.write_text("someone else's", encoding="ascii")
            lifecycle.unlink_if_still_bound(path, socket_inode=bound)
        assert path.read_text(encoding="ascii") == "someone else's"

    def test_a_path_already_gone_is_not_an_error(self, tmp_path: Path) -> None:
        lifecycle.unlink_if_still_bound(tmp_path / "test.sock", socket_inode=1)


async def test_every_poll_that_does_not_stop_shows_a_sign_of_life(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A push queued behind this service's hold on its store reads how long ago it last did, so a
    service that is still polling must never read as one that has stalled.

    The test waits for the third sign rather than counting signs in a fixed sleep, which a stall of
    the process would empty; a poll that stopped giving them is a watchdog's ten seconds."""
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.02)
    signs: list[None] = []
    third_sign = asyncio.Event()

    def sign_of_life() -> None:
        signs.append(None)
        if len(signs) >= 3:
            third_sign.set()

    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")  # never idle: nothing stops it.
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        polling = asyncio.create_task(
            lifecycle.idle_self_stop(
                ctx,
                running,
                sock_path,
                original_store_inode=ctx.store.path.stat().st_ino,
                still_here=sign_of_life,
            )
        )
        try:
            await asyncio.wait_for(third_sign.wait(), timeout=10.0)
        finally:
            polling.cancel()
            await asyncio.gather(polling, return_exceptions=True)
            await running.shut_down()
    assert len(signs) >= 3


async def test_a_service_whose_socket_is_taken_from_it_stops_and_leaves_the_path_alone(
    tmp_path: Path,
    socket_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nobody can reach a service whose socket file was removed, and a replacement waits for its
    store rather than taking it, so the service has to be the one to go — while busy, and without
    removing whatever now sits at the path, which is no longer its own."""
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")  # never idle: only the lost socket can fire.
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        with caplog.at_level("INFO", logger="zikaron.service"):
            idle_task = asyncio.create_task(
                lifecycle.idle_self_stop(
                    ctx, running, sock_path, original_store_inode=ctx.store.path.stat().st_ino
                )
            )
            await asyncio.sleep(0)
            sock_path.unlink()
            sock_path.write_text("not this service's", encoding="utf-8")
            await asyncio.wait_for(idle_task, timeout=5.0)
        assert sock_path.read_text(encoding="utf-8") == "not this service's"

    records = [r.getMessage() for r in caplog.records if r.getMessage().startswith("stopping:")]
    assert len(records) == 1, f"expected exactly one stop record, got {records}"
    assert "reason=socket_lost" in records[0], records[0]


async def test_idle_self_stop_propagates_a_genuine_unexpected_stat_failure_rather_than_exiting(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only absence or a changed inode counts as "replaced". An earlier version of
    `_path_now_differs` folded *every* `OSError` into an unconditional shutdown
    decision, which would make a genuine `PermissionError` (or any other unrelated stat failure)
    indistinguishable from an actual store replacement. Forced by monkeypatching `Path.stat` to
    raise a `PermissionError` deterministically, rather than trying to construct a real permission
    failure on the filesystem, which would be both slower and less portable across test
    environments.
    """
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        original_inode = ctx.store.path.stat().st_ino

        real_stat = Path.stat

        def _permission_denied(self: Path, **kwargs: object) -> object:
            if self == ctx.store.path:
                raise PermissionError("deliberately denied, for this test")
            return real_stat(self, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "stat", _permission_denied)

        idle_task = asyncio.create_task(
            lifecycle.idle_self_stop(ctx, running, sock_path, original_store_inode=original_inode)
        )
        try:
            with pytest.raises(PermissionError):
                await asyncio.wait_for(idle_task, timeout=5.0)
        finally:
            monkeypatch.setattr(Path, "stat", real_stat)
            await running.shut_down()


@pytest.mark.asyncio
async def test_a_clean_stop_writes_a_record_naming_its_reason(
    tmp_path: Path,
    socket_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A clean exit must be visible in the log, and say which of the two conditions fired.

    The defect this closes was found by inspection of a running machine rather than by a test:
    four stores, one live service, and four `service.log` files whose last entry was the startup
    config dump — because `idle_self_stop` unlinked, shut down and returned in silence. The only
    line any exit path wrote was `main.py`'s forced-exit `exception()`, so the log's contract was
    inverted: silence meant a clean stop, a line meant a failed one, and "stopped or wedged?" was
    answerable only with `ps`.

    Asserted on both reasons, because a record that always says `idle` would satisfy a
    single-branch test while telling an operator the wrong thing on the branch that actually
    matters — a store moved or restored underneath a running service.
    """
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.begin_request("memory_search")  # never idle: only replacement can fire.
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        original_inode = ctx.store.path.stat().st_ino

        with caplog.at_level("INFO", logger="zikaron.service"):
            idle_task = asyncio.create_task(
                lifecycle.idle_self_stop(
                    ctx, running, sock_path, original_store_inode=original_inode
                )
            )
            ctx.store.path.unlink()
            ctx.store.path.write_text("a different store now lives at the identical path")
            await asyncio.wait_for(idle_task, timeout=5.0)

    records = [r.getMessage() for r in caplog.records if r.getMessage().startswith("stopping:")]
    assert len(records) == 1, f"expected exactly one stop record, got {records}"
    assert "reason=store_replaced" in records[0], records[0]
    assert str(tmp_path) in records[0], "the record must name which store stopped"


@pytest.mark.asyncio
async def test_an_idle_stop_says_idle_rather_than_store_replaced(
    tmp_path: Path,
    socket_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other branch, and the one an operator reads most often.

    The **activity clock** is aged rather than the **timeout** lowered, which is the difference
    between testing the mechanism and testing a smaller version of it: `idle_timeout` keeps its
    real 1800 s default here, and `may_stop` is made true the way production makes it true — by
    time passing with nothing in flight. Lowering the key was the first attempt and is not even
    expressible: `IntBounds(60, 86400)` refuses it, which is the config layer doing its job.

    Pairs with the test above: between them, a record that hard-coded either reason fails one.
    """
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        assert ctx.activity.in_flight == 0
        ctx.activity.last_activity -= 86_400  # a day of idleness, against a 1800 s default.
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))

        with caplog.at_level("INFO", logger="zikaron.service"):
            await asyncio.wait_for(
                lifecycle.idle_self_stop(
                    ctx, running, sock_path, original_store_inode=ctx.store.path.stat().st_ino
                ),
                timeout=5.0,
            )

    records = [r.getMessage() for r in caplog.records if r.getMessage().startswith("stopping:")]
    assert len(records) == 1, f"expected exactly one stop record, got {records}"
    assert "reason=idle" in records[0], records[0]
