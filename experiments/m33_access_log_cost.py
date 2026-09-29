"""What the `call` row costs a caller: an A/B against an unlogged control, idle and under load.

    .venv/bin/python experiments/m33_access_log_cost.py [samples]

`research/m33-access-log-cost.md` carries the bar, **dated before this ran**, and the results.

**Two arms, same machine, interleaved sample by sample.** The control is a `ServiceContext` whose
`AccessLog` has been closed, which is the real unlogged path rather than a stub: `record` on a stopped
log returns without writing. The treatment is the same context shape with a live one. Alternating per
sample rather than running a block each, because machine drift over a block lands entirely on
whichever arm holds it.

**Two conditions.** Idle is the figure that matters, because it is what every push pays on every user
message. Under a writer taking the store's write lock in short transactions at a stated rate, the
question is different and narrower: whether the row can push `memory_surface` past
`push._DEADLINE_SECONDS`, which is the one latency budget in this system a user notices and the one
M17's defect broke.

**`memory_surface` is the verb, and it is the worst case on purpose.** It is the only call a user
waits on without having asked for anything, it already writes its own `surface_call` inside its own
transaction, and it runs once per user message — so if the added row is affordable anywhere it has to
be affordable there.
"""

import asyncio
import contextlib
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Sequence
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiosqlite  # noqa: E402

from tests.service_fixtures import envelope, open_context  # noqa: E402
from zikaron.core.store import ddl  # noqa: E402
from zikaron.core.store.connection import open_connection  # noqa: E402
from zikaron.hook import push  # noqa: E402
from zikaron.service import server  # noqa: E402
from zikaron.service.context import ServiceContext  # noqa: E402
from zikaron.service.params import event_origin  # noqa: E402

#: How many memories each arm's store holds before the measurement, so a push has something to fuse
#: and the retrieval work is not trivially short.
_SEEDED_MEMORIES = 40

#: Short transactions per second the background writer takes the write lock for. Stated rather than
#: "as fast as possible", so the loaded condition is reproducible and is not simply saturation.
_WRITER_TRANSACTIONS_PER_SECOND = 20.0

_DEFAULT_SAMPLES = 200


def _line(method: str, params: dict[str, object], op_id: str) -> bytes:
    import json

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **params,
            "client": {"session_id": "s1", "kind": "mcp", "pid": 100, "op_id": op_id},
        },
    }
    return (json.dumps(request) + "\n").encode("utf-8")


async def _seed(ctx: ServiceContext) -> None:
    for index in range(_SEEDED_MEMORIES):
        await server._handle_line(
            ctx,
            _line(
                "memory_remember",
                {
                    "gist": f"the build fails when setting {index} is absent",
                    "content": f"observed on run {index}; the fix is to set it before the build",
                },
                f"seed-{index}",
            ),
        )


@contextlib.asynccontextmanager
async def _background_writer(paths: Sequence[Path]) -> AsyncIterator[None]:
    """Take the write lock on each store in short transactions, at `_WRITER_TRANSACTIONS_PER_SECOND`.

    One writer per store, so both arms meet the same contention. A writer shared between them would
    make the arms compete with each other rather than each with a writer.
    """
    connections = [
        (await open_connection(path, pragmas=ddl.PRAGMAS, existing_only=True))[0] for path in paths
    ]
    stopping = asyncio.Event()

    async def _churn(db: aiosqlite.Connection) -> None:
        interval = 1.0 / _WRITER_TRANSACTIONS_PER_SECOND
        transactions = 0
        while not stopping.is_set():
            transactions += 1
            await db.execute("BEGIN IMMEDIATE")
            # **The value must change**, or this writer takes the lock and commits nothing. A `meta`
            # upsert to the value already there is a byte-identical overwrite: SQLite compares before
            # it writes, the page never dirties, and no WAL frame is appended — so the condition would
            # be lock contention with no cache invalidation, which is not what another writer does to
            # a store.
            await db.execute(
                "INSERT INTO meta (key, value) VALUES ('bench', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(transactions),),
            )
            await db.commit()
            await asyncio.sleep(interval)

    tasks = [asyncio.create_task(_churn(db)) for db in connections]
    try:
        yield
    finally:
        stopping.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for db in connections:
            await db.close()


async def _call_rows(ctx: ServiceContext) -> int:
    rows = await ctx.store.connection.execute_fetchall(
        "SELECT count(*) FROM event WHERE kind = 'call'"
    )
    return int(list(rows)[0][0])


async def _timed_write(ctx: ServiceContext, op_id: str) -> float:
    """The row write alone, with no surface call around it.

    **This is what discriminates a slow write from a noisy machine.** The paired delta is a
    difference of two calls that each do retrieval, embedding and their own transaction, so its tail
    carries every scheduling hiccup either of them met. Timing `record` on its own bounds the write's
    own contribution, and a tail here that is far below the paired delta's says the excess is the
    surface call's variance rather than this row.
    """
    origin = event_origin(envelope(session_id="s1", kind="mcp", pid=100, op_id=op_id))
    started = time.perf_counter()
    await ctx.access_log.record(
        origin=origin, method="memory_surface", refused=None, duration_ms=1.0
    )
    return (time.perf_counter() - started) * 1000.0


async def _timed_surface(ctx: ServiceContext, op_id: str) -> float:
    line = _line("memory_surface", {"prompt": "the build fails"}, op_id)
    started = time.perf_counter()
    answered = await server._handle_line(ctx, line)
    elapsed = time.perf_counter() - started
    assert answered is not None
    return elapsed * 1000.0


@contextlib.asynccontextmanager
async def _recording_handler_durations() -> AsyncIterator[dict[Path, list[float]]]:
    """Every dispatched handler's own elapsed time, per store, in call order.

    The figure `_run_handler` already computes for the `call` row, captured on **both** arms — the
    control writes no row, so its copy exists nowhere else. Read straight off the dispatch seam rather
    than out of the treatment store afterwards, which would give one arm and not the other.
    """
    seen: dict[Path, list[float]] = {}
    original = server._run_handler

    async def _wrapped(
        ctx: ServiceContext, request: object, resolved: object, handler: object
    ) -> object:
        dispatched = await original(ctx, request, resolved, handler)  # type: ignore[arg-type]
        seen.setdefault(ctx.store.path, []).append(dispatched.duration_ms)
        return dispatched

    server._run_handler = _wrapped  # type: ignore[assignment]
    try:
        yield seen
    finally:
        server._run_handler = original  # type: ignore[assignment]


def _report_handler_split(
    control: Sequence[float],
    treatment: Sequence[float],
    control_handler: Sequence[float],
    treatment_handler: Sequence[float],
) -> None:
    """Which side of the seam the paired delta sits on, because the remedy only reaches one of them.

    Moving the row after `writer.drain()` removes cost the caller waits for **outside the handler**
    and nothing inside it. So the delta is split at that seam.

    **Both halves are paired per call, and the additive check is on means rather than medians.** A
    difference of two arms' own quantiles is not a per-call anything (`_report`), and medians do not add
    even when paired — so the line that can say the halves account for the whole is the one over means,
    which add exactly by linearity.
    """
    handler_delta = [
        after - before for before, after in zip(control_handler, treatment_handler, strict=True)
    ]
    treatment_outside = [
        total - handler for total, handler in zip(treatment, treatment_handler, strict=True)
    ]
    control_outside = [
        total - handler for total, handler in zip(control, control_handler, strict=True)
    ]
    outside_delta = [
        after - before for before, after in zip(control_outside, treatment_outside, strict=True)
    ]
    whole = [after - before for before, after in zip(control, treatment, strict=True)]
    print(f"{'':32} {'p50':>9} {'p95':>9} {'mean':>9}")
    for name, values in (
        ("handler alone, control", control_handler),
        ("handler alone, treatment", treatment_handler),
        ("outside the handler, control", control_outside),
        ("outside the handler, treatment", treatment_outside),
        ("paired handler delta", handler_delta),
        ("paired outside delta", outside_delta),
        ("paired whole delta", whole),
    ):
        print(
            f"  {name:<30} {_quantile(values, 0.50):9.3f} "
            f"{_quantile(values, 0.95):9.3f} {statistics.mean(values):9.3f}"
        )
    print(
        "  means add exactly: "
        f"{statistics.mean(handler_delta):.3f} + {statistics.mean(outside_delta):.3f} = "
        f"{statistics.mean(handler_delta) + statistics.mean(outside_delta):.3f} "
        f"against {statistics.mean(whole):.3f}"
    )


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _report(label: str, control: list[float], treatment: list[float]) -> None:
    """Both arms' own quantiles, and then the **paired** differences, which are the delta.

    **A difference of two independently-computed quantiles is not a per-call delta**, and reading one
    as though it were is how this first reported a p95 that moved from 1.670 ms to 0.481 ms between
    two runs whose paired medians were 0.989 and 0.891. Each arm's p95 is a different call, so their
    difference is the gap between two unrelated samples of a noisy distribution. The delta a caller
    actually pays is defined per call, so it is computed per call and then quantiled.
    """
    paired = [
        treatment_sample - control_sample
        for control_sample, treatment_sample in zip(control, treatment, strict=True)
    ]
    print(f"\n{label}  (n={len(control)} per arm)")
    print(f"{'':24} {'p50':>9} {'p95':>9} {'max':>9}")
    for name, values in (
        ("control, unlogged", control),
        ("treatment, logged", treatment),
        ("paired delta per call", paired),
    ):
        print(
            f"  {name:<22} {_quantile(values, 0.50):9.3f} "
            f"{_quantile(values, 0.95):9.3f} {max(values):9.3f}"
        )
    print(f"  mean paired delta: {statistics.mean(paired):.3f} ms")


async def _report_environment() -> None:
    """The store connection's `synchronous`, the scratch directory and its filesystem."""
    scratch = Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory() as directory:
        async with open_context(Path(directory)) as ctx:
            rows = await ctx.store.connection.execute_fetchall("PRAGMA synchronous")
            mode = int(list(rows)[0][0])
    names = {0: "OFF", 1: "NORMAL", 2: "FULL", 3: "EXTRA"}
    filesystem = subprocess.run(
        ["df", "-T", str(scratch)], capture_output=True, text=True, check=False
    ).stdout.splitlines()
    kind = filesystem[-1].split()[1] if len(filesystem) > 1 else "unknown"
    print(f"store connection synchronous: {names.get(mode, mode)}  (ddl.PRAGMAS sets none)")
    print(f"scratch: {scratch} on {kind}")


async def _foreign_commit_probe(samples: int) -> None:
    """What one commit by **another** connection costs the next call — the access log removed entirely.

    **A mechanism probe, not part of the bar.** The split above puts part of the row's cost *inside* the
    handler, where nothing about the row's own write explains it. A checkpoint cannot: at the default
    `wal_autocheckpoint` threshold it fires once per some hundreds of commits, so it would show as a
    tail over a median near zero rather than as a shift in the median.

    Two candidates act on every call, and the probe varies **two** axes for them. What the outsider
    *writes* decides which mechanism is present, because a reset is insensitive to it and a per-frame
    cost is not — see `_ForeignWrite`, which is where the three footprints and the positive control are
    described. The outsider's `synchronous` then separates a reset from a deferred sync.

    A **page-cache reset**: a WAL-mode connection beginning a transaction after another connection has
    committed sees a changed wal-index header and discards its cache, so it re-reads every page it
    touches. That fires whatever the writer's sync mode was, so either outsider tests it.

    A **deferred `fsync`**: the access log commits at `synchronous = NORMAL`, leaving its WAL frames
    dirty, and the next `surface_call` commit at `FULL` syncs the WAL *file* — every dirty page of that
    inode, the row's included. So the row's `fsync` is deferred to the next caller rather than avoided,
    and only the `NORMAL` outsider reproduces it. `ddl.PRAGMAS` keeps `FULL`, `ACCESS_LOG_PRAGMAS` is
    `NORMAL` with `wal_autocheckpoint` at zero, which is the shipped writer's own pragma set.

    Both surface arms run with the access log closed, so no row is written in either; the row-write
    arms are the log's own write and necessarily run with it open. Interleaved and paired throughout.
    """
    for label, pragmas, statement in (
        # The **statement** comparison, on the shipped writer's own pragma set. Three footprints,
        # ordered by how many WAL frames each writes: none, one, and the row's own six.
        ("NORMAL", ddl.ACCESS_LOG_PRAGMAS, _ForeignWrite.UNCHANGED_META),
        ("NORMAL", ddl.ACCESS_LOG_PRAGMAS, _ForeignWrite.ONE_FRAME_META),
        ("NORMAL", ddl.ACCESS_LOG_PRAGMAS, _ForeignWrite.ROW_SHAPED),
        # The **sync-mode** comparison, at one footprint. Run last so the row-shaped `NORMAL` arm
        # above and this one differ in nothing but the pragma tuple and their position.
        ("FULL", ddl.PRAGMAS, _ForeignWrite.ROW_SHAPED),
    ):
        await _one_foreign_commit_arm(
            samples, label=label, pragmas=pragmas, statement=statement
        )


class _ForeignWrite(StrEnum):
    """What the outsider commits, which is the axis that decides between two mechanisms.

    **A page-cache reset clears the whole cache on any wal-index header change, so its cost is a
    function of the *timed* call's footprint and not of the foreign commit's.** It therefore predicts
    the same cost for one frame as for six. Anything that scales with the committer's frames is a
    different mechanism. Three statements separate them:

    `UNCHANGED_META` writes **no frame at all** — a `meta` upsert whose value is a constant is a
    byte-identical overwrite, and SQLite compares before it writes, so the page never dirties, the
    pager stays below `PAGER_WRITER_CACHEMOD` and the commit never reaches the WAL. A null from this
    arm is a no-op arm rather than a small-footprint one, which is why a probe needs a positive
    control — **and here the control is the mechanism's own counter**: `PRAGMA data_version` reads the
    pager's `iDataVersion`, which `pager_reset` increments as it clears the cache, so an arm at 600 of
    600 is the reset observed running. That read is on the shared connection, so it is what clears the
    cache; the timed call then pays the re-read, which is the cost being measured.

    `ONE_FRAME_META` is the same statement with a value that changes each call — one frame, of a page
    `memory_surface` never touches. If the cost is a reset this reads like the row-shaped arm; if it
    scales with frames, it reads like nothing.

    `ROW_SHAPED` is the `INSERT INTO event` that `log_event` issues, which dirties that table's leaf
    and every index in `EVENT_INDEXES`.
    """

    UNCHANGED_META = "meta, unchanged value (no frame)"
    ONE_FRAME_META = "meta, changing value (one frame)"
    ROW_SHAPED = "event row, as log_event writes it"


async def _one_foreign_commit_arm(
    samples: int, *, label: str, pragmas: tuple[str, ...], statement: _ForeignWrite
) -> None:
    """One outsider's worth of `_foreign_commit_probe`. A fresh store per arm, so neither warms the
    other's cache or inherits its WAL."""
    moved = 0
    with tempfile.TemporaryDirectory() as scratch:
        directory = Path(scratch) / "probe"
        directory.mkdir()
        async with open_context(directory) as ctx:
            await _seed(ctx)
            outsider, _inode = await open_connection(
                ctx.store.path, pragmas=pragmas, existing_only=True
            )

            async def _data_version() -> int:
                rows = await ctx.store.connection.execute_fetchall("PRAGMA data_version")
                return int(list(rows)[0][0])

            async def _commit_from_outside(index: int) -> None:
                nonlocal moved
                before = await _data_version()
                await outsider.execute("BEGIN IMMEDIATE")
                if statement is _ForeignWrite.ROW_SHAPED:
                    await outsider.execute(
                        "INSERT INTO event (at, session_id, client_kind, op_id, kind, memory_uuid, "
                        "detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            "2026-09-28T00:00:00Z",
                            "s1",
                            "mcp",
                            f"probe-{index}",
                            "call",
                            None,
                            '{"method":"memory_surface","ok":true,"error_code":null,'
                            '"duration_ms":1.0}',
                        ),
                    )
                else:
                    value = "1" if statement is _ForeignWrite.UNCHANGED_META else str(index)
                    await outsider.execute(
                        "INSERT INTO meta (key, value) VALUES ('probe', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (value,),
                    )
                await outsider.commit()
                if await _data_version() != before:
                    moved += 1

            try:
                # One untimed call per half. In the `NORMAL` arms nothing checkpoints until the shared
                # connection's first commit meets a WAL both writers have been appending to — an
                # inflated first sample that moves a mean of 300 and leaves the median alone.
                await _timed_write(ctx, "warm-w")
                plain_writes: list[float] = []
                after_writes: list[float] = []
                for index in range(samples):
                    plain_writes.append(await _timed_write(ctx, f"pw-{index}"))
                    await _commit_from_outside(index)
                    after_writes.append(await _timed_write(ctx, f"aw-{index}"))
                await ctx.access_log.close()
                await _timed_surface(ctx, "warm-s")
                plain: list[float] = []
                after: list[float] = []
                for index in range(samples):
                    plain.append(await _timed_surface(ctx, f"p-{index}"))
                    await _commit_from_outside(samples + index)
                    after.append(await _timed_surface(ctx, f"a-{index}"))
            finally:
                await outsider.close()

    print(
        f"\nforeign-commit probe: {statement.value}, outsider at synchronous = {label}"
        f"  (n={samples}; {moved} of {2 * samples} commits moved data_version)"
    )
    print(f"{'':32} {'p50':>9} {'p95':>9} {'mean':>9}")
    for name, values in (
        ("the row write, no foreign commit", plain_writes),
        ("the row write, after one", after_writes),
        (
            "paired delta",
            [after - before for before, after in zip(plain_writes, after_writes, strict=True)],
        ),
        ("memory_surface, no foreign commit", plain),
        ("memory_surface, after one", after),
        ("paired delta", [a - b for b, a in zip(plain, after, strict=True)]),
    ):
        print(
            f"  {name:<30} {_quantile(values, 0.50):9.3f} "
            f"{_quantile(values, 0.95):9.3f} {statistics.mean(values):9.3f}"
        )


async def _null_arm(samples: int) -> list[float]:
    """The paired delta of two **unlogged** arms: what the estimator reads when the effect is zero.

    **This is what decides whether a p95 bar on a paired delta is attainable at all.** The delta is a
    difference of two `memory_surface` calls, each several milliseconds with its own spread, so the
    difference has a spread of its own that no implementation can reduce. If this arm's p95 is near the
    treatment's, the bar's p95 is measuring the variance of the instrument rather than the cost of the
    row — a fact about the estimator, not about the code under test.
    """
    with tempfile.TemporaryDirectory() as scratch:
        first_dir = Path(scratch) / "first"
        second_dir = Path(scratch) / "second"
        first_dir.mkdir()
        second_dir.mkdir()
        async with open_context(first_dir) as first, open_context(second_dir) as second:
            await first.access_log.close()
            await second.access_log.close()
            await _seed(first)
            await _seed(second)
            paired: list[float] = []
            for index in range(samples):
                one = await _timed_surface(first, f"n1-{index}")
                two = await _timed_surface(second, f"n2-{index}")
                paired.append(two - one)
            return paired


async def _run(samples: int, *, loaded: bool) -> tuple[list[float], list[float]]:
    with tempfile.TemporaryDirectory() as scratch:
        control_dir = Path(scratch) / "control"
        treatment_dir = Path(scratch) / "treatment"
        control_dir.mkdir()
        treatment_dir.mkdir()
        async with (
            open_context(control_dir) as control,
            open_context(treatment_dir) as treatment,
        ):
            # The real unlogged path: `record` on a stopped log returns without writing, no stub.
            await control.access_log.close()
            await _seed(control)
            await _seed(treatment)
            control_times: list[float] = []
            treatment_times: list[float] = []
            writer = (
                _background_writer([control.store.path, treatment.store.path])
                if loaded
                else contextlib.nullcontext()
            )
            async with writer, _recording_handler_durations() as handler_ms:
                before = await _call_rows(treatment)
                writes = [await _timed_write(treatment, f"w-{index}") for index in range(samples)]
                landed = await _call_rows(treatment) - before
                # **How many landed is part of the figure.** A contended attempt returns at once with
                # no row, so a mean over attempts that includes refusals is part write and part
                # refusal — and reads *faster* under load than idle, which is the tell.
                print(
                    f"\n  the row write alone: p50 {_quantile(writes, 0.50):.3f}  "
                    f"p95 {_quantile(writes, 0.95):.3f}  max {max(writes):.3f} ms  "
                    f"({landed} of {samples} rows landed)"
                )
                for index in range(samples):
                    # Alternating which arm goes first, so neither systematically pays for a cache
                    # the other warmed.
                    order = (
                        (control, control_times, treatment, treatment_times)
                        if index % 2 == 0
                        else (treatment, treatment_times, control, control_times)
                    )
                    first, first_times, second, second_times = order
                    first_times.append(await _timed_surface(first, f"a-{index}"))
                    second_times.append(await _timed_surface(second, f"b-{index}"))
            _report_handler_split(
                control_times,
                treatment_times,
                handler_ms[control.store.path],
                handler_ms[treatment.store.path],
            )
            return control_times, treatment_times


async def main() -> int:
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_SAMPLES
    print(f"pid {os.getpid()}, {samples} samples per arm per condition")
    print(f"load1 before: {os.getloadavg()[0]:.2f}")
    # **Both are conditions the foreign-commit probe's conclusion depends on and neither is set by
    # this project.** `ddl.PRAGMAS` sets no `synchronous`, so the shared connection's mode is the
    # build's compile-time default — and were it `NORMAL`, nothing in that probe syncs and its
    # sync-mode comparison says nothing. The scratch filesystem decides whether a sync costs anything
    # at all: on tmpfs there is nothing to measure.
    await _report_environment()
    print(f"push deadline: {push._DEADLINE_SECONDS * 1000:.0f} ms")

    await _foreign_commit_probe(samples)

    null = await _null_arm(samples)
    print(
        f"\nnull arm, unlogged against unlogged  (n={samples})"
        f"\n  paired delta per call        p50 {_quantile(null, 0.50):9.3f} "
        f"p95 {_quantile(null, 0.95):9.3f} max {max(null):9.3f}"
        f"\n  standard deviation           {statistics.stdev(null):9.3f} ms"
    )

    control, treatment = await _run(samples, loaded=False)
    _report("idle", control, treatment)
    print(f"  standard deviation of the paired delta: {statistics.stdev(
        treatment_sample - control_sample
        for control_sample, treatment_sample in zip(control, treatment, strict=True)
    ):.3f} ms")

    control, treatment = await _run(samples, loaded=True)
    _report(
        f"under a writer at {_WRITER_TRANSACTIONS_PER_SECOND:.0f} short transactions/s",
        control,
        treatment,
    )
    print(f"\nload1 after: {os.getloadavg()[0]:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
