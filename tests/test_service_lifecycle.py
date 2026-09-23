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
from pathlib import Path

import pytest

from tests.service_fixtures import open_context
from zikaron.service import lifecycle, server


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
        ctx.activity.in_flight = 1  # never idle: `may_stop` must return `False` throughout.
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
        ctx.activity.in_flight = 1
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
        ctx.activity.in_flight = 1
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
        ctx.activity.in_flight = 1
        sock_path = socket_dir / "server.sock"
        running = await server.serve(ctx, str(sock_path))
        original_inode = ctx.store.path.stat().st_ino
        idle_task = asyncio.create_task(
            lifecycle.idle_self_stop(ctx, running, sock_path, original_store_inode=original_inode)
        )

        ctx.store.path.unlink()

        await asyncio.wait_for(idle_task, timeout=5.0)
        assert not sock_path.exists()


async def test_idle_self_stop_propagates_a_genuine_unexpected_stat_failure_rather_than_exiting(
    tmp_path: Path, socket_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only absence or a changed inode counts as "replaced". An earlier version of
    `_store_path_now_differs` folded *every* `OSError` into an unconditional shutdown
    decision, which would make a genuine `PermissionError` (or any other unrelated stat failure)
    indistinguishable from an actual store replacement. Forced by monkeypatching `Path.stat` to
    raise a `PermissionError` deterministically, rather than trying to construct a real permission
    failure on the filesystem, which would be both slower and less portable across test
    environments.
    """
    monkeypatch.setattr(lifecycle, "IDLE_POLL_INTERVAL_SECONDS", 0.05)
    async with open_context(tmp_path) as ctx:
        ctx.activity.in_flight = 1
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
        ctx.activity.in_flight = 1  # never idle, so only the replacement branch can fire.
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
        ctx.activity.in_flight = 0
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
