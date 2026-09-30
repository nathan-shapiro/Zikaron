"""A plan is computed from a read snapshot, and written in a short transaction that re-checks it.

`architecture.md` §"Consolidation lifecycle" is normative. Planning a large journal takes seconds,
and holding the writer for all of it failed every other request's transaction in that window. So
`grouping.plan` runs on a read-pool connection, holding no write lock, and only the write takes the
writer — re-deriving the fingerprint of every active row first, and planning again inside itself if
a row moved meanwhile.

Each test holds the snapshot phase open with an event, which is what makes "while the plan
computes" a moment a test can act in rather than a race.
"""

import asyncio
import dataclasses
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import aiosqlite
import pytest

from tests.consolidation_fixtures import CONSOLIDATOR_PID, Consolidator, consolidator
from tests.contention_fixtures import call, error_of, patch_budget
from tests.fake_encoder import FakeEncoder
from tests.service_fixtures import open_context
from zikaron.core.consolidation import grouping, planning, serving
from zikaron.core.consolidation.payload import Busy, ServedGroup
from zikaron.core.consolidation.runs import RunStatus
from zikaron.core.events import ClientKind
from zikaron.core.indexing.encoder import BackgroundLoadedEncoder, Encoder
from zikaron.core.indexing.writes import IndexingContext
from zikaron.core.records.memory import Tier
from zikaron.service.context import ServiceContext

_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_B = ("proto codegen also fails locally", "the same drift shows up in the dev container")
_ANCHOR = ("the proto toolchain is pinned", "the pinned version lives in requirements.txt")


@dataclass(frozen=True, slots=True)
class _Held:
    """Set by the held plan when it starts; set by the test to let it finish."""

    started: asyncio.Event
    release: asyncio.Event


@asynccontextmanager
async def _first_plan_held(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[_Held]:
    """Hold the first `grouping.plan` open until `release` is set; later plans run free."""
    real = grouping.plan
    held = _Held(started=asyncio.Event(), release=asyncio.Event())
    calls = 0

    async def holding(db: aiosqlite.Connection, **options: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            held.started.set()
            await held.release.wait()
        return await real(db, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(grouping, "plan", holding)
    try:
        yield held
    finally:
        held.release.set()


async def _plan_in_background(c: Consolidator, **call: object) -> asyncio.Task[object]:
    return asyncio.create_task(
        planning.plan_groups(
            c.harness.store.connection,
            pool=c.harness.store.pool,
            call=c.call(**call),  # type: ignore[arg-type]
        )
    )


async def test_a_plan_holds_no_write_lock_while_it_computes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """During the snapshot phase a write on the writer succeeds at once — before this, the plan held
    the writer for its whole computation and every write in that window waited out its budget."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        async with _first_plan_held(monkeypatch) as plan_held:
            plan = await _plan_in_background(c)
            await plan_held.started.wait()
            assert not plan.done()
            written = await asyncio.wait_for(
                c.write(gist=_B[0], content=_B[1], minute=2, degrees=10.0), timeout=1.0
            )
            plan_held.release.set()
            run = await plan
        assert written
        assert run.status is RunStatus.ACTIVE  # type: ignore[attr-defined]


async def test_a_journal_row_written_while_the_plan_computed_is_among_the_runs_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-validation asserted on its outcome: the fingerprint moved, so the write planned again
    inside itself, and the row the snapshot never saw is in the run."""
    async with consolidator(tmp_path) as c:
        first = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        async with _first_plan_held(monkeypatch) as plan_held:
            plan = await _plan_in_background(c)
            await plan_held.started.wait()
            late = await c.write(gist=_B[0], content=_B[1], minute=2, degrees=10.0)
            plan_held.release.set()
            await plan
        members = {uuid for group in await c.groups() for uuid, *_ in await c.member_rows(group[0])}
        assert members == {first, late}


async def test_an_anchor_retired_while_the_plan_computed_anchors_no_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fingerprint covers the long-term tier too, since the plan reads it for anchors: an anchor
    retired in the window would otherwise be written as one."""
    async with consolidator(tmp_path) as c:
        anchor = await c.write(
            gist=_ANCHOR[0], content=_ANCHOR[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        async with _first_plan_held(monkeypatch) as plan_held:
            plan = await _plan_in_background(c)
            await plan_held.started.wait()
            await c.harness.retire(anchor)
            plan_held.release.set()
            await plan
        assert [group[1] for group in await c.groups()] == [None]


async def _next_group_in_background(c: Consolidator, **call: object) -> asyncio.Task[object]:
    return asyncio.create_task(
        serving.next_group(
            c.harness.store.connection,
            pool=c.harness.store.pool,
            call=c.call(**call),  # type: ignore[arg-type]
        )
    )


async def test_next_group_finding_its_own_run_at_the_write_discards_its_plan_and_serves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two `next_group` calls from one owner — ordinary, since one MCP process serves a session —
    both find no run and both plan. The one that writes second finds the first's run, which is its
    own, and serves from it rather than replacing it."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await c.write(gist=_B[0], content=_B[1], minute=2, degrees=90.0)
        async with _first_plan_held(monkeypatch) as plan_held:
            held = await _next_group_in_background(c, op_id="held")
            await plan_held.started.wait()
            first = await serving.next_group(
                c.harness.store.connection, pool=c.harness.store.pool, call=c.call(op_id="free")
            )
            plan_held.release.set()
            second = await held
        assert isinstance(first, ServedGroup)
        assert isinstance(second, ServedGroup)
        assert second.run_id == first.run_id
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.ACTIVE]


async def test_next_group_finding_a_strangers_run_at_the_write_is_busy_and_serves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`next_group` never takes a run over: a stranger whose run appeared while this call planned
    is `Busy`, exactly as if it had been there at the first step."""
    async with consolidator(tmp_path) as c:
        await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        async with _first_plan_held(monkeypatch) as plan_held:
            held = await _next_group_in_background(c, op_id="held")
            await plan_held.started.wait()
            stranger = await serving.next_group(
                c.harness.store.connection,
                pool=c.harness.store.pool,
                call=c.call(op_id="stranger", pid=CONSOLIDATOR_PID + 1),
            )
            plan_held.release.set()
            outcome = await held
        assert isinstance(stranger, ServedGroup)
        assert isinstance(outcome, Busy)
        assert outcome.holder_pid == CONSOLIDATOR_PID + 1
        assert [status for _, _, _, status in await c.runs()] == [RunStatus.ACTIVE]
        served = [one for one in await c.events() if one[0] == "group_served"]
        assert len(served) == 1


async def consolidator_call(ctx: ServiceContext, method: str) -> dict[str, object]:
    return await call(ctx, method, {}, kind=ClientKind.CONSOLIDATOR.value)


async def test_next_group_takes_no_write_lock_while_the_model_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A serve embeds inside its transaction, so a cold load there would hold SQLite's write lock
    for the whole load while every other writer met its budget. `next_group` waits for the load
    first. Probed with `memory_fetch`, which writes without embedding and so does not itself wait
    on the load — a `remember` would, and would pass either way. The fixture holds an active run of
    the caller's own with a servable group, so the serve embeds; an empty store embeds nothing."""
    budget_ms = 400
    patch_budget(monkeypatch, budget_ms)
    async with open_context(tmp_path) as ctx:
        remembered = await call(ctx, "memory_remember", {"gist": _A[0], "content": _A[1]})
        uuid = remembered["result"]["uuid"]  # type: ignore[index]
        await consolidator_call(ctx, "memory_plan_groups")
        assert isinstance(ctx.encoder, FakeEncoder)
        loaded = ctx.encoder

        def slow_load(_model_name: str) -> Encoder:
            time.sleep(3 * budget_ms / 1000)
            return loaded

        loading = BackgroundLoadedEncoder(model_name=loaded.model_name, load=slow_load)
        loading.declare_dim(loaded.dim)
        cold = dataclasses.replace(
            ctx,
            encoder=loading,
            encoder_load=loading,
            index=IndexingContext.for_store(ctx.store, ctx.config, loading),
        )
        serving_task = asyncio.create_task(consolidator_call(cold, "memory_next_group"))
        await asyncio.sleep(0.05)
        fetched = await call(cold, "memory_fetch", {"uuids": [uuid]})
        assert error_of(fetched) is None, fetched
        assert not serving_task.done(), "the load finished before the probe, so it tested nothing"
        served = await serving_task
        assert error_of(served) is None, served
