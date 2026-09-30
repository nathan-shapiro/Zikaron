"""A push the agent never saw is never recorded as shown.

`architecture.md` §"Degraded modes" and §Errors are normative. A `surface` row means *this session
was shown this memory* — the denominator of D30's repair signal — and the push hook abandons its
request at its own deadline. So `memory_surface` carries that deadline as `deadline_at_ms`, and
past it, less the margin, the service answers `deadline_passed` and commits nothing: no
`surface_call`, no `surface`.

Each scenario asserts what the store gained, because the property is about the rows. Where the
access log's `call` row is asserted, it is the case in which the write lock is free and the row
lands; under a held writer it is dropped, and nothing is asserted about it.
"""

import asyncio
import json
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

import pytest

from tests.contention_fixtures import call, error_of, external_writer
from tests.fake_encoder import FakeEncoder
from tests.service_fixtures import open_context
from zikaron.core.retrieval import reads
from zikaron.core.retrieval.retrieve import retrieve as real_retrieve
from zikaron.core.store import ddl
from zikaron.core.store.pool import POOL_SIZE
from zikaron.hook import push
from zikaron.service import dispatch
from zikaron.service.context import ServiceContext

_DEADLINE_PASSED: Final = -32026
_STORE_BUSY: Final = -32020
_BOUNDS: Final = -32005


def _deadline_in(seconds: float) -> int:
    return int((time.time() + seconds) * 1000)


async def _kinds(ctx: ServiceContext) -> list[str]:
    rows = await (await ctx.store.writer()).execute_fetchall("SELECT kind FROM event ORDER BY id")
    return [str(kind) for (kind,) in rows]


async def _surface_rows(ctx: ServiceContext) -> list[str]:
    return [kind for kind in await _kinds(ctx) if kind in ("surface_call", "surface")]


async def _call_rows(ctx: ServiceContext, method: str) -> list[dict[str, object]]:
    rows = await (await ctx.store.writer()).execute_fetchall(
        "SELECT detail FROM event WHERE kind = 'call' ORDER BY id"
    )
    details = [json.loads(detail) for (detail,) in rows]
    return [detail for detail in details if detail["method"] == method]


async def _seeded(ctx: ServiceContext) -> None:
    await call(ctx, "memory_remember", {"gist": "proto codegen drifts", "content": "pin it"})


def _slow_embed(encoder: FakeEncoder, seconds: float) -> None:
    real = encoder.embed

    def slow(texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        time.sleep(seconds)
        return real(texts)

    encoder.embed = slow  # type: ignore[method-assign]


async def test_an_ample_deadline_behaves_as_a_push_always_has(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        answered = await call(
            ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": _deadline_in(3)}
        )
        assert error_of(answered) is None, answered
        assert await _surface_rows(ctx) == ["surface_call", "surface"]


async def test_a_writers_hold_past_the_deadline_answers_deadline_passed_and_commits_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first attempt is refused at its upgrade, and the retry waits only until the deadline
    less the margin. A contention refusal from that retry is lateness, whenever the request carries
    a deadline — decided by the bound, not by a second clock reading.

    The margin is widened here so the bound separates a retry that stops short of it from one that
    waits to the deadline by far more than the host's scheduling jitter."""
    monkeypatch.setattr(dispatch, "DEADLINE_MARGIN_MS", 300)
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        with external_writer(ctx.store.path) as writer:
            writer.hold()
            started = time.monotonic()
            answered = await call(
                ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": _deadline_in(0.6)}
            )
            elapsed = time.monotonic() - started
        assert error_of(answered) == (_DEADLINE_PASSED, {"verb": "surface"}), answered
        assert elapsed < 0.45, elapsed
        assert await _surface_rows(ctx) == []


async def test_an_embed_that_outlasts_the_deadline_commits_nothing_and_its_call_row_lands(
    tmp_path: Path,
) -> None:
    """The older cause: a cold model load or a slow embed, with no writer anywhere. The write lock
    is free, so the access log's row lands and names the refusal."""
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        assert isinstance(ctx.encoder, FakeEncoder)
        _slow_embed(ctx.encoder, 0.6)
        answered = await call(
            ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": _deadline_in(0.4)}
        )
        assert error_of(answered) == (_DEADLINE_PASSED, {"verb": "surface"}), answered
        assert await _surface_rows(ctx) == []
        (row,) = await _call_rows(ctx, "memory_surface")
        assert row["error_code"] == "deadline_passed"


async def test_an_embed_that_outlasts_the_deadline_spends_no_read_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check after the embed: a push already late there never opens a transaction, since the
    check before `COMMIT` would only roll the pass back."""
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        assert isinstance(ctx.encoder, FakeEncoder)
        _slow_embed(ctx.encoder, 0.6)
        passes = _count_read_passes(monkeypatch)
        answered = await call(
            ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": _deadline_in(0.4)}
        )
        assert error_of(answered) == (_DEADLINE_PASSED, {"verb": "surface"}), answered
        assert passes == []


async def test_a_deadline_that_passes_inside_the_transaction_rolls_its_rows_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check before `COMMIT`: the embed is on time and the read pass is not. Its `surface_call`
    and `surface` rows are already written when the deadline passes, and they roll back."""
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)

        async def slow_retrieve(*args: object, **options: object) -> object:
            retrieved = await real_retrieve(*args, **options)  # type: ignore[arg-type]
            await asyncio.sleep(0.6)
            return retrieved

        monkeypatch.setattr(reads, "retrieve", slow_retrieve)
        answered = await call(
            ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": _deadline_in(0.4)}
        )
        assert error_of(answered) == (_DEADLINE_PASSED, {"verb": "surface"}), answered
        assert await _surface_rows(ctx) == []


def _count_read_passes(monkeypatch: pytest.MonkeyPatch) -> list[None]:
    passes: list[None] = []

    async def counted(*args: object, **options: object) -> object:
        passes.append(None)
        return await real_retrieve(*args, **options)  # type: ignore[arg-type]

    monkeypatch.setattr(reads, "retrieve", counted)
    return passes


async def _pin_the_pool_with_searches(
    ctx: ServiceContext,
) -> tuple[threading.Event, list[asyncio.Task[object]]]:
    """One `memory_search` per pool connection, each holding its lease inside a blocked embed —
    the shape of a wedge that has pinned every lease."""
    assert isinstance(ctx.encoder, FakeEncoder)
    released = threading.Event()
    real = ctx.encoder.embed
    entered: list[int] = []

    def blocked(texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        entered.append(1)
        released.wait(timeout=10)
        return real(texts)

    ctx.encoder.embed = blocked  # type: ignore[method-assign]
    searches: list[asyncio.Task[object]] = [
        asyncio.create_task(call(ctx, "memory_search", {"query": f"q{index}"}))
        for index in range(POOL_SIZE)
    ]
    while len(entered) < POOL_SIZE:
        await asyncio.sleep(0.01)
    return released, searches


async def test_an_exhausted_pool_answers_deadline_passed_at_the_lease_wait_and_its_row_lands(
    tmp_path: Path,
) -> None:
    """With a deadline, the lease wait is bounded by that deadline alone, and its expiry answers
    `deadline_passed` — check point 1's code, issued before check point 1 is reached. `call` rows
    behind it are what tell an exhausted pool from a held writer."""
    async with open_context(tmp_path) as ctx:
        released, searches = await _pin_the_pool_with_searches(ctx)
        try:
            answered = await call(
                ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": _deadline_in(0.5)}
            )
        finally:
            released.set()
            await asyncio.gather(*searches)
        assert error_of(answered) == (_DEADLINE_PASSED, {"verb": "memory_surface"}), answered
        (row,) = await _call_rows(ctx, "memory_surface")
        assert row["error_code"] == "deadline_passed"


async def test_without_a_deadline_an_exhausted_pool_answers_store_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flag the refusal records is set by the deadline's presence, not by the method."""
    monkeypatch.setattr(ddl, "BUSY_TIMEOUT_MS", 400)
    async with open_context(tmp_path) as ctx:
        released, searches = await _pin_the_pool_with_searches(ctx)
        try:
            answered = await call(ctx, "memory_surface", {"prompt": "proto"})
        finally:
            released.set()
            await asyncio.gather(*searches)
        assert error_of(answered) == (_STORE_BUSY, {"verb": "memory_surface"}), answered


@pytest.mark.parametrize(
    "value",
    [lambda: _deadline_in(-1), lambda: -(10**400)],
    ids=["a second ago", "beyond a float's range"],
)
async def test_a_deadline_already_past_answers_before_any_work(
    tmp_path: Path, value: Callable[[], object]
) -> None:
    """Not malformed — late. Refused at check point 1, so the model is never asked."""
    async with open_context(tmp_path) as ctx:
        await _seeded(ctx)
        assert isinstance(ctx.encoder, FakeEncoder)
        embedded_before = len(ctx.encoder.embedded)
        answered = await call(ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": value()})
        assert error_of(answered) == (_DEADLINE_PASSED, {"verb": "surface"}), answered
        assert len(ctx.encoder.embedded) == embedded_before
        assert await _surface_rows(ctx) == []


@pytest.mark.parametrize(
    "value",
    [lambda: _deadline_in(60), lambda: 10**400, lambda: "soon", lambda: True, lambda: 1.5],
    ids=["a minute ahead", "beyond a float's range", "a string", "a boolean", "a float"],
)
async def test_a_deadline_further_ahead_than_the_budget_or_not_an_integer_is_bounds(
    tmp_path: Path, value: Callable[[], object]
) -> None:
    """Validated whole by the dispatcher, before the lease, inside the access log's accounting — so
    the refusal has its `call` row like any handler's. Each value is made when the test runs, since
    a deadline made at collection would have passed by then."""
    async with open_context(tmp_path) as ctx:
        answered = await call(ctx, "memory_surface", {"prompt": "proto", "deadline_at_ms": value()})
        refused = error_of(answered)
        assert refused is not None, answered
        assert refused[0] == _BOUNDS, answered
        assert refused[1]["field"] == "deadline_at_ms"
        (row,) = await _call_rows(ctx, "memory_surface")
        assert row["error_code"] == "bounds"


async def test_bounds_is_decided_before_lateness(tmp_path: Path) -> None:
    """A request both malformed and late answers `bounds`: a malformed parameter is checked before
    any deadline is."""
    async with open_context(tmp_path) as ctx:
        answered = await call(
            ctx, "memory_surface", {"prompt": 7, "deadline_at_ms": _deadline_in(-1)}
        )
        refused = error_of(answered)
        assert refused is not None, answered
        assert refused[0] == _BOUNDS, answered


async def test_a_malformed_push_whose_deadline_cuts_its_lease_wait_answers_deadline_passed(
    tmp_path: Path,
) -> None:
    """The one exception to `bounds` first: `prompt` is validated in the handler, after the lease,
    so a lease wait its deadline cut answers before that rung is reached."""
    async with open_context(tmp_path) as ctx:
        released, searches = await _pin_the_pool_with_searches(ctx)
        try:
            answered = await call(
                ctx, "memory_surface", {"prompt": 7, "deadline_at_ms": _deadline_in(0.3)}
            )
        finally:
            released.set()
            await asyncio.gather(*searches)
        assert error_of(answered) == (_DEADLINE_PASSED, {"verb": "memory_surface"}), answered


def test_the_margin_is_inside_the_hooks_own_deadline() -> None:
    """A margin as large as the hook's deadline would refuse every push before it began."""
    assert 0 < dispatch.DEADLINE_MARGIN_MS < push._DEADLINE_SECONDS * 1000
