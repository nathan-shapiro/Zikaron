"""The `call` event: that the seam covers every dispatched method, and that it costs the caller
nothing.

`schema.md` §"`call` is an access log" is normative. Two claims live here and they are independent.

**Completeness.** The whole reason the row is written at the dispatch seam rather than per verb is
that a method added later is instrumented because it is in `_METHODS`, not because somebody
remembered — the knowledge verbs are what per-verb discipline already cost. So the sweep below
**drives a real call per method** rather than reading the table: a test that enumerated `_METHODS`
and asserted something about the mapping would pass with the row write deleted.

**Isolation.** The row is attempted after the handler has committed, on a connection of its own at
`busy_timeout = 0`, and the response line is encoded before it. So nothing the write does can reach
the caller — which matters because a failure propagating from there would answer `internal_error`
for a `memory_remember` that is durably in the store, the agent would retry, and the store would
gain a duplicate.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.served_group_fixtures import (
    CONSOLIDATOR,
    write_anchored_pair,
    write_orphan_pair,
)
from tests.service_fixtures import open_context
from zikaron.core.errors import ErrorCode
from zikaron.core.events import (
    EVENT_SPECS,
    ClientKind,
    DetailField,
    EventDetail,
    EventKind,
    EventOrigin,
    EventSpec,
)
from zikaron.core.knowledge import reporting
from zikaron.core.records.memory import log_event
from zikaron.core.store import ddl
from zikaron.core.store.connection import open_connection
from zikaron.core.store.store import Store
from zikaron.knowledge.indexer import detach
from zikaron.service import access_log, rpc, server
from zikaron.service import context as service_context
from zikaron.service import paths as service_paths
from zikaron.service.access_log import AccessLog
from zikaron.service.context import ServiceContext

#: The bound `tests/test_knowledge_counters.py` uses for the same claim: a write that declines to
#: wait must return in a fraction of the timeout it is declining, not merely faster than it.
_NO_WAIT_BOUND_SECONDS: Final = ddl.BUSY_TIMEOUT_MS / 5_000


@pytest.fixture(autouse=True)
def no_real_builds(monkeypatch: pytest.MonkeyPatch) -> None:
    """`knowledge_add` and `knowledge_refresh` spawn a detached indexer; nothing here wants one.

    Autouse, because a test that merely forgot it would start a real build of a real corpus in a
    test process and outlive the test that caused it.
    """

    def _no_spawn(
        name: str, *, project: Path, full: bool = False, spawned_by_op_id: str | None = None
    ) -> list[str]:
        del full, spawned_by_op_id
        return detach.command(name, project=project, full=False)

    monkeypatch.setattr(detach, "spawn", _no_spawn)


def _line(method: str, params: dict[str, object], *, kind: str = "mcp") -> bytes:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            **params,
            "client": {"session_id": "s1", "kind": kind, "pid": 100, "op_id": "op1"},
        },
    }
    return (json.dumps(request) + "\n").encode("utf-8")


async def _answer(ctx: ServiceContext, line: bytes) -> dict[str, object]:
    response = await server._handle_line(ctx, line)
    assert response is not None
    parsed = json.loads(response)
    assert isinstance(parsed, dict)
    return parsed


async def _call_rows(ctx: ServiceContext) -> list[dict[str, object]]:
    """Every `call` row's detail, oldest first."""
    rows = await ctx.store.connection.execute_fetchall(
        "SELECT detail FROM event WHERE kind = ? ORDER BY id", (EventKind.CALL.value,)
    )
    return [json.loads(detail) for (detail,) in rows]


@dataclass(frozen=True, slots=True)
class _Arms:
    """One method's two arms: params that make it answer, and params that make it refuse.

    `kind` is the envelope's `client.kind`. `refused_kind` overrides it for the refused arm alone,
    which is how the two consolidator methods taking no params are refused at all: their
    consolidator-only check runs *inside* the handler, so it is a domain refusal and does produce a
    row, unlike the envelope's own shape check.

    `break_it` is for the one method with **no** domain refusal — `knowledge_list` takes no
    arguments — whose refused arm is therefore an injected driver failure. Named so that "every
    method" is not quietly weakened to "every method that has a refusal".
    """

    succeeding: dict[str, object]
    refused: dict[str, object]
    kind: str = "mcp"
    refused_kind: str | None = None
    break_it: Callable[[pytest.MonkeyPatch], None] | None = None


#: Builds one method's arms against a store it may seed first.
type _Setup = Callable[[ServiceContext], Awaitable[_Arms]]

_ABSENT_GROUP: Final = "00000000-0000-4000-8000-000000000000"
_NOT_AN_INT: Final = "not an integer"


async def _remembered(ctx: ServiceContext, gist: str = "a gist") -> str:
    answered = await _answer(ctx, _line("memory_remember", {"gist": gist, "content": "content"}))
    result = answered["result"]
    assert isinstance(result, dict)
    return str(result["uuid"])


async def _fetched_version(ctx: ServiceContext, uuid: str) -> int:
    """Fetch `uuid`, which is also what mints the receipt an amend or a retire requires."""
    answered = await _answer(ctx, _line("memory_fetch", {"uuids": [uuid]}))
    result = answered["result"]
    assert isinstance(result, dict)
    records = result["records"]
    assert isinstance(records, list)
    first = records[0]
    assert isinstance(first, dict)
    return int(str(first["version"]))


async def _added_corpus(ctx: ServiceContext, tmp_path: Path, name: str = "docs") -> None:
    await _answer(
        ctx,
        _line(
            "knowledge_add",
            {"name": name, "path": str(tmp_path), "description": "the docs corpus"},
        ),
    )


async def _served_group(ctx: ServiceContext) -> str:
    """Plan and serve one group, returning its id."""
    await _answer(ctx, _line("memory_plan_groups", {}, kind=CONSOLIDATOR.kind))
    answered = await _answer(ctx, _line("memory_next_group", {}, kind=CONSOLIDATOR.kind))
    result = answered["result"]
    assert isinstance(result, dict)
    return str(result["group_id"])


def _row(uuid: str, version: int = 1) -> dict[str, object]:
    return {"uuid": uuid, "expected_version": version}


def _break_knowledge_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `knowledge_list` fail on something no parameter could express.

    A plain `RuntimeError` rather than a driver error, so it reaches `internal_error` — the method
    table already converts an `aiosqlite.Error` into `store_unavailable`, and this is the one place
    in the suite where the seam's unhandled-exception branch writes a row.
    """

    async def _raise(*_args: object, **_keywords: object) -> object:
        raise RuntimeError("injected so a parameterless method has a refused arm")

    monkeypatch.setattr(reporting, "list_bases", _raise)


async def _remember_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(
        succeeding={"gist": "a gist", "content": "content"},
        refused={"gist": 1, "content": "content"},
    )


async def _amend_arms(ctx: ServiceContext) -> _Arms:
    uuid = await _remembered(ctx)
    version = await _fetched_version(ctx, uuid)
    return _Arms(
        succeeding={"uuid": uuid, "version": version, "gist": "g2", "content": "c2"},
        refused={"uuid": uuid, "version": _NOT_AN_INT, "gist": "g2", "content": "c2"},
    )


async def _retire_arms(ctx: ServiceContext) -> _Arms:
    uuid = await _remembered(ctx)
    version = await _fetched_version(ctx, uuid)
    return _Arms(
        succeeding={"uuid": uuid, "version": version},
        refused={"uuid": uuid, "version": _NOT_AN_INT},
    )


async def _search_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={"query": "a gist"}, refused={"query": 1})


async def _surface_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={"prompt": "a gist"}, refused={"prompt": 1})


async def _fetch_arms(ctx: ServiceContext) -> _Arms:
    uuid = await _remembered(ctx)
    return _Arms(succeeding={"uuids": [uuid]}, refused={"uuids": []})


async def _plan_groups_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={}, refused={}, kind=CONSOLIDATOR.kind, refused_kind="mcp")


async def _next_group_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={}, refused={}, kind=CONSOLIDATOR.kind, refused_kind="mcp")


async def _merge_arms(ctx: ServiceContext) -> _Arms:
    anchor, member = await write_anchored_pair(ctx)
    group = await _served_group(ctx)
    rewrite: dict[str, object] = {"gist": "merged gist", "content": "merged content"}
    return _Arms(
        succeeding={
            "group_id": group,
            "target": _row(anchor),
            "absorb": [_row(member)],
            **rewrite,
        },
        refused={
            "group_id": _ABSENT_GROUP,
            "target": _row(anchor),
            "absorb": [_row(member)],
            **rewrite,
        },
        kind=CONSOLIDATOR.kind,
    )


async def _promote_arms(ctx: ServiceContext) -> _Arms:
    first, second = await write_orphan_pair(ctx)
    group = await _served_group(ctx)
    absorb = [_row(first), _row(second)]
    rewrite: dict[str, object] = {"gist": "promoted gist", "content": "promoted content"}
    return _Arms(
        succeeding={"group_id": group, "absorb": absorb, **rewrite},
        refused={"group_id": _ABSENT_GROUP, "absorb": absorb, **rewrite},
        kind=CONSOLIDATOR.kind,
    )


async def _discard_arms(ctx: ServiceContext) -> _Arms:
    first, second = await write_orphan_pair(ctx)
    group = await _served_group(ctx)
    absorb = [_row(first), _row(second)]
    return _Arms(
        succeeding={"group_id": group, "absorb": absorb, "reason": "duplicate noise"},
        refused={"group_id": _ABSENT_GROUP, "absorb": absorb, "reason": "duplicate noise"},
        kind=CONSOLIDATOR.kind,
    )


async def _knowledge_search_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={"query": "anything"}, refused={"query": 1})


async def _knowledge_list_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={}, refused={}, break_it=_break_knowledge_list)


async def _knowledge_status_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={}, refused={"knowledge_base": 1})


def _corpus_request(ctx: ServiceContext, name: str) -> dict[str, object]:
    return {
        "name": name,
        "path": str(service_paths.scope_of(ctx.store_directory)),
        "description": "the docs corpus",
    }


async def _knowledge_add_arms(ctx: ServiceContext) -> _Arms:
    request = _corpus_request(ctx, "docs")
    # The refused arm is the same request again: a name already taken is `knowledge_base_exists`,
    # which is this verb's own refusal rather than a malformed parameter.
    return _Arms(succeeding=request, refused=dict(request))


async def _knowledge_remove_arms(ctx: ServiceContext) -> _Arms:
    await _added_corpus(ctx, service_paths.scope_of(ctx.store_directory))
    removal: dict[str, object] = {"name": "docs", "confirm": True}
    return _Arms(succeeding=removal, refused=dict(removal))


async def _knowledge_rename_arms(ctx: ServiceContext) -> _Arms:
    await _added_corpus(ctx, service_paths.scope_of(ctx.store_directory))
    return _Arms(
        succeeding={"name": "docs", "new_name": "runbooks"},
        refused={"name": "docs", "new_name": "anything"},
    )


async def _knowledge_refresh_arms(ctx: ServiceContext) -> _Arms:
    del ctx
    return _Arms(succeeding={}, refused={"name": "no corpus by that name"})


async def _knowledge_unlock_arms(ctx: ServiceContext) -> _Arms:
    await _added_corpus(ctx, service_paths.scope_of(ctx.store_directory))
    return _Arms(
        succeeding={"knowledge_base": "docs"},
        refused={"knowledge_base": "no corpus by that name"},
    )


#: One entry per dispatched method. A method added to `_METHODS` without one fails
#: `test_every_dispatched_method_has_a_recipe`, which is what keeps the sweep exhaustive rather than
#: merely long.
_ARMS: Final[dict[str, _Setup]] = {
    "memory_remember": _remember_arms,
    "memory_amend": _amend_arms,
    "memory_retire": _retire_arms,
    "memory_search": _search_arms,
    "memory_surface": _surface_arms,
    "memory_fetch": _fetch_arms,
    "memory_plan_groups": _plan_groups_arms,
    "memory_next_group": _next_group_arms,
    "memory_apply_merge": _merge_arms,
    "memory_apply_promote": _promote_arms,
    "memory_apply_discard": _discard_arms,
    "knowledge_search": _knowledge_search_arms,
    "knowledge_list": _knowledge_list_arms,
    "knowledge_status": _knowledge_status_arms,
    "knowledge_add": _knowledge_add_arms,
    "knowledge_remove": _knowledge_remove_arms,
    "knowledge_rename": _knowledge_rename_arms,
    "knowledge_refresh": _knowledge_refresh_arms,
    "knowledge_unlock": _knowledge_unlock_arms,
}


def test_every_dispatched_method_has_a_recipe() -> None:
    """The sweep below is only exhaustive if this passes, and a new method is why it might not.

    Asserted as set equality in both directions: a recipe naming a method the table no longer holds
    is a test driving nothing, which reads as coverage.
    """
    assert set(_ARMS) == set(server._METHODS)


@pytest.mark.parametrize("method", sorted(_ARMS))
async def test_every_dispatched_method_writes_exactly_one_call_row(
    method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The property the whole seam design exists for, driven rather than read off the table.

    One well-formed call and one refused call, each producing **exactly one** row: the count is what
    catches a second write added downstream, and the pair is what catches a seam that logs only one
    of the two outcomes.
    """
    async with open_context(tmp_path) as ctx:
        arms = await _ARMS[method](ctx)
        baseline = len(await _call_rows(ctx))

        answered = await _answer(ctx, _line(method, arms.succeeding, kind=arms.kind))
        assert "result" in answered, answered
        rows = await _call_rows(ctx)
        assert len(rows) == baseline + 1, f"{method}: {len(rows) - baseline} rows for one call"
        assert rows[-1] == {
            "method": method,
            "ok": True,
            "error_code": None,
            "duration_ms": rows[-1]["duration_ms"],
        }
        assert isinstance(rows[-1]["duration_ms"], float)

        if arms.break_it is not None:
            arms.break_it(monkeypatch)
        refused_kind = arms.refused_kind if arms.refused_kind is not None else arms.kind
        answered = await _answer(ctx, _line(method, arms.refused, kind=refused_kind))
        assert "error" in answered, answered
        rows = await _call_rows(ctx)
        assert len(rows) == baseline + 2, (
            f"{method}: {len(rows) - baseline - 1} rows for one refusal"
        )
        assert rows[-1]["method"] == method
        assert rows[-1]["ok"] is False
        assert isinstance(rows[-1]["error_code"], str)


async def test_a_refusals_error_code_is_recorded_as_its_name(tmp_path: Path) -> None:
    """The stored value is the snake_case name, never the wire integer: a signal query written
    against `-32005` is a number nobody can check."""
    async with open_context(tmp_path) as ctx:
        await _answer(ctx, _line("memory_fetch", {"uuids": []}))
        (row,) = await _call_rows(ctx)
        assert row["error_code"] == ErrorCode.BOUNDS.wire_name


async def test_a_handler_that_crashes_is_recorded_as_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`internal_error` is the one `ProtocolErrorCode` member a `call` row can hold: every other is
    decided by an exit ahead of dispatch. A call that reached a handler and crashed is what an
    access log is for, so it is the value a query against this column has to expect."""
    async with open_context(tmp_path) as ctx:
        _break_knowledge_list(monkeypatch)
        await _answer(ctx, _line("knowledge_list", {}))
        (row,) = await _call_rows(ctx)
        assert row["ok"] is False
        assert row["error_code"] == rpc.ProtocolErrorCode.INTERNAL_ERROR.wire_name


async def test_a_call_row_carries_its_own_call_s_envelope(tmp_path: Path) -> None:
    """An `op_id` with a semantic row and no `call` row *is* a dropped access-log row, so the two
    have to share one — which is what makes the drop rate computable at all."""
    async with open_context(tmp_path) as ctx:
        await _answer(ctx, _line("memory_remember", {"gist": "a gist", "content": "content"}))
        rows = await ctx.store.connection.execute_fetchall(
            "SELECT kind, session_id, client_kind, op_id FROM event ORDER BY id"
        )
        by_kind = {kind: (session, client, op) for kind, session, client, op in rows}
        assert by_kind[EventKind.CALL.value] == by_kind[EventKind.REMEMBER.value]


@pytest.mark.parametrize(
    ("name", "line"),
    [
        ("health", _line("health", {})),
        ("an unparseable line", b"{ not json\n"),
        ("a line that is not utf-8", b"\xff\xfe\n"),
        ("a malformed envelope", _line("memory_search", {"query": "q"}).replace(b'"mcp"', b"7")),
        (
            "an envelope naming the indexer, the one kind the store admits and the wire does not",
            _line("memory_search", {"query": "q"}, kind=ClientKind.INDEXER.value),
        ),
        ("an unknown method", _line("no_such_method", {})),
    ],
)
async def test_the_exits_ahead_of_dispatch_write_no_row(
    tmp_path: Path, name: str, line: bytes
) -> None:
    """Exclusions rather than gaps, each for its own reason — `schema.md`'s exit table.

    Complete **as of these inputs** rather than by construction: an exit added later that fires on
    some other input would be invisible here, which is why the design states the list rather than
    claiming it follows from the code.
    """
    del name
    async with open_context(tmp_path) as ctx:
        await server._handle_line(ctx, line)
        assert await _call_rows(ctx) == []


async def test_a_client_naming_the_indexer_kind_is_refused_before_dispatch(tmp_path: Path) -> None:
    """The row is absent because the envelope never resolved, which is the whole of the protection.

    A client accepted under `indexer` would have its writes filed as a spawned build's: outside the
    drop-rate query, invisible to linkage, and named back to it in a `bounds` payload as a value to
    send. The refusal is asserted beside the absent row, since an exit that answered something else
    and *also* wrote nothing would satisfy the row half alone.
    """
    async with open_context(tmp_path) as ctx:
        answered = await _answer(
            ctx, _line("memory_search", {"query": "q"}, kind=ClientKind.INDEXER.value)
        )
        error = answered["error"]
        assert isinstance(error, dict)
        assert error["code"] == int(ErrorCode.BOUNDS)
        data = error["data"]
        assert isinstance(data, dict)
        assert data["field"] == "client.kind"
        assert ClientKind.INDEXER.value not in data["limit"]
        assert await _call_rows(ctx) == []


# ---------------------------------------------------------------------------
# What the write costs a caller, which is meant to be nothing
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _write_lock_held(ctx: ServiceContext) -> AsyncIterator[None]:
    """Hold `memory.db`'s write lock from a second connection for the body of the block."""
    holder, _inode = await open_connection(ctx.store.path, pragmas=ddl.PRAGMAS, existing_only=True)
    try:
        await holder.execute("BEGIN IMMEDIATE")
        await holder.execute("INSERT INTO meta (key, value) VALUES ('held', '1')")
        yield
        await holder.rollback()
    finally:
        await holder.close()


def _origin() -> EventOrigin:
    return EventOrigin(session_id="s1", client_kind="mcp", op_id="op1")


async def test_the_writer_alone_drops_its_row_rather_than_waiting_for_the_lock(
    tmp_path: Path,
) -> None:
    """The mechanism, isolated from any handler: `busy_timeout = 0` and a swallowed refusal.

    **The elapsed time is the assertion that makes this test its own name.** Whether the connection
    waits out the five seconds or refuses at once, no row lands and nothing raises — so a version
    that inherited the ordinary timeout would pass every other assertion here and put five seconds
    of a caller's latency behind a lock it has no stake in.
    """
    async with open_context(tmp_path) as ctx:
        async with _write_lock_held(ctx):
            started = time.perf_counter()
            await ctx.access_log.record(
                origin=_origin(), method="memory_surface", refused=None, duration_ms=1.0
            )
            elapsed = time.perf_counter() - started
        assert await _call_rows(ctx) == []
    assert elapsed < _NO_WAIT_BOUND_SECONDS, f"it waited {elapsed:.3f}s for the lock"


async def test_a_knowledge_list_under_a_held_lock_answers_exactly_as_an_unlogged_one_would(
    tmp_path: Path,
) -> None:
    """`knowledge_list` specifically, and the choice of verb is the whole test.

    A **memory** verb already holds the write lock for its own semantic event, so a store held
    throughout fails *the handler* at `store_busy` with or without this milestone, and a test built
    on one proves nothing about the access log. `knowledge_list` writes nothing to `memory.db` of
    its own, so the `call` row is the call's first and only write there and a held lock isolates it
    exactly — **on a store whose `knowledge_bases` table already exists**, since `registry.ensure`
    creates it on the one call that finds it absent. So one list runs before the lock is taken.

    `knowledge_add`, `remove` and `rename` write the registry and sit with the memory verbs, which
    is why this names `knowledge_list` rather than "a knowledge verb".
    """
    async with open_context(tmp_path) as ctx:
        control = await server._handle_line(ctx, _line("knowledge_list", {}))
        rows_before = len(await _call_rows(ctx))
        async with _write_lock_held(ctx):
            started = time.perf_counter()
            answered = await server._handle_line(ctx, _line("knowledge_list", {}))
            elapsed = time.perf_counter() - started
        assert answered == control, "the dropped row changed the line a caller reads"
        assert len(await _call_rows(ctx)) == rows_before, "a contended row must not land"
    assert elapsed < _NO_WAIT_BOUND_SECONDS, f"it waited {elapsed:.3f}s for the lock"


@pytest.mark.parametrize("failure", ["closed connection", "raised OSError"])
async def test_a_call_still_answers_when_the_row_write_fails_for_any_other_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Contention is dropped silently and so is everything else, because the alternative is worse.

    The row is attempted **after** the handler has committed, so a failure propagating from there
    would answer `internal_error` for a `memory_remember` that is durably in the store: the agent
    retries and the store gains a duplicate.

    Both causes the done-when names are driven **through the seam**, because that is where the
    property lives: the private connection closed under the writer, which is what
    `transactions.finalize` leaves behind after a rollback it could not complete, and an `OSError`
    from the write itself. Each reaches a different `except` in `record`, and the line a caller
    reads has to be byte-identical on both.
    """
    async with open_context(tmp_path) as ctx:
        control = await server._handle_line(ctx, _line("knowledge_list", {}))
        rows_before = len(await _call_rows(ctx))
        if failure == "closed connection":
            await ctx.access_log.close()
        else:

            async def _explode(*_args: object, **_keywords: object) -> None:
                raise OSError("no space left on device")

            monkeypatch.setattr(access_log, "log_event", _explode)
        answered = await server._handle_line(ctx, _line("knowledge_list", {}))
        assert answered == control
        assert len(await _call_rows(ctx)) == rows_before


async def test_a_closed_connection_stops_the_log_rather_than_being_reopened(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """One noisy failure over one quiet wrong answer, and a restart is what restores it.

    Reopening would retry against a store whose transaction state could not be repaired. The service
    log says so **once**: a full disk fails every call, so a line per call floods the log while one
    line ever hides the recovery.
    """
    async with open_context(tmp_path) as ctx:
        log = AccessLog(_connection=await _closed_connection(ctx))
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            for _attempt in range(3):
                await log.record(
                    origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
                )
        assert await _call_rows(ctx) == []
    assert len(caplog.records) == 1, "the log names the stop once, not once per call"


async def test_the_stop_is_reported_even_after_a_transient_failure_latched(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The realistic path to a stopped log runs *through* a latched transient failure.

    A driver error on the row that is not contention reports once and latches. `finalize` then
    closes it behind that, having failed to roll back, so **the stop arrives on the next call** —
    and a stop going through the same latch would find it already set and say nothing. The last line
    in the service log would then read as transient while the access log was off for good.

    Which is why the stop branch does not use the latch: it can fire at most once by construction,
    since `record` returns at its first line once the connection is `None`.
    """
    async with open_context(tmp_path) as ctx:
        # No `sqlite_errorcode`, so `is_contention` is false: a constructed driver error is not
        # contention by definition, which is what makes this the reported branch.
        async def _explode(*_args: object, **_keywords: object) -> None:
            raise aiosqlite.OperationalError("disk I/O error")

        monkeypatch.setattr(access_log, "log_event", _explode)
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
            # What `finalize` leaves behind when its own rollback could not complete. The connection
            # it replaces is closed here rather than abandoned, since this test substitutes what
            # `finalize` would have done to the original.
            await ctx.access_log.close()
            ctx.access_log._connection = await _closed_connection(ctx)
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
        messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2, f"the stop was swallowed by the transient latch: {messages}"
    assert "has stopped" in messages[1]


def _spec_demanding_an_absent_field() -> dict[EventKind, EventSpec]:
    """A `call` contract requiring a field `CallDetail` does not carry.

    What a producer and its own spec disagreeing looks like from inside the write. Substituted on
    the module rather than on the spec, which is frozen.
    """
    shipped = EVENT_SPECS[EventKind.CALL]
    return {
        EventKind.CALL: EventSpec(
            names_memory=False,
            detail_fields=(*shipped.detail_fields, DetailField("invented")),
        )
    }


async def test_a_refused_payload_drops_one_row_and_leaves_the_log_running(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A payload the contract refuses says nothing about the next row, so the log keeps going.

    `schema.md` puts a non-contention failure under *dropped and logged once until the next row
    succeeds*, and reserves *stops* for the connection being closed. Both raise `ValueError`, which
    is why the payload is validated **before** the transaction: inside it the two would be one
    `except`, and one bad payload would switch the log off for the service's lifetime.
    """
    async with open_context(tmp_path) as ctx:
        monkeypatch.setattr(access_log, "EVENT_SPECS", _spec_demanding_an_absent_field())
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
        assert await _call_rows(ctx) == []
        assert len(caplog.records) == 1
        monkeypatch.undo()
        await ctx.access_log.record(
            origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
        )
        assert len(await _call_rows(ctx)) == 1, "a refused payload must not stop the log"


async def test_a_stopped_log_says_nothing_about_a_payload_it_would_have_refused(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A log that has stopped writes nothing and has already said so once — including this.

    Which is why the payload is validated *after* the connection check rather than before it: ahead
    of it, a stopped writer would answer a contract disagreement with a second line in the service
    log, from a writer the design says is silent.
    """
    async with open_context(tmp_path) as ctx:
        await ctx.access_log.close()
        monkeypatch.setattr(access_log, "EVENT_SPECS", _spec_demanding_an_absent_field())
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
    assert caplog.records == [], "a stopped log reported a payload it never tried to write"


async def test_a_second_distinct_failure_is_reported_once_the_latch_has_cleared(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*Logged once, until the next row succeeds* — the second half is what this pins.

    Without the clearing, "once" becomes once per process: a disk that fills after a payload was
    refused earlier in the same service's life is then silent, which is the failure the log exists
    to make visible. Two distinct failures with a landed row between them is the only sequence that
    tells the two readings apart.
    """
    broken = _spec_demanding_an_absent_field()
    async with open_context(tmp_path) as ctx:
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            monkeypatch.setattr(access_log, "EVENT_SPECS", broken)
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
            monkeypatch.undo()
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
            monkeypatch.setattr(access_log, "EVENT_SPECS", broken)
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
        assert len(await _call_rows(ctx)) == 1, "the middle call is what clears the latch"
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2, f"the second failure was swallowed by a stale latch: {messages}"


async def test_a_failure_no_layer_named_closes_the_connection_it_abandons(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stop branch is reachable with the connection still **open**, and then it owns closing it.

    `aiosqlite`'s worker thread is not a daemon, so a connection dropped by reference alone keeps
    the interpreter alive at exit with nothing printed. The usual way in is a connection `finalize`
    has already closed, where there is nothing to close; this drives the other way in — an exception
    below that is neither an `aiosqlite.Error` nor a payload the contract refused.
    """
    async with open_context(tmp_path) as ctx:
        connection = ctx.access_log._connection
        assert connection is not None

        async def _explode(*_args: object, **_keywords: object) -> None:
            raise ValueError("a failure no layer below named")

        monkeypatch.setattr(access_log, "log_event", _explode)
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            await ctx.access_log.record(
                origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
            )
        assert ctx.access_log._connection is None, "the log did not stop"
        # The type, not the message. `ValueError` is what makes the closed-connection case reach the
        # stop branch at all; were a release to move it under `aiosqlite.Error` — `sqlite3` raises
        # `ProgrammingError` for this — that case would latch and retry instead, and the log would
        # never stop. This is one of the two tests that would then say so.
        with pytest.raises(ValueError):  # noqa: PT011 — the type is the assertion; see above
            await connection.execute("SELECT 1")
    assert [record.getMessage() for record in caplog.records] == [
        "the access log has stopped; no further call events"
    ]


async def test_a_call_queued_behind_a_close_drops_its_row_without_reporting(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An orderly shutdown must not be logged as a failure.

    Three calls interleave: one holding the lock mid-write, `close` waiting behind it, and a second
    `record` waiting behind that. Read before the lock instead, the third would carry the handle
    `close` went on to shut and would report the stop — a traceback in the service log for a clean
    teardown, on every shutdown that catches a call in flight.
    """
    holding = asyncio.Event()
    release = asyncio.Event()

    async def _slow(
        db: aiosqlite.Connection,
        *,
        ctx: EventOrigin,
        detail: EventDetail,
        memory_uuid: str | None,
    ) -> None:
        holding.set()
        await release.wait()
        await log_event(db, ctx=ctx, detail=detail, memory_uuid=memory_uuid)

    async with open_context(tmp_path) as ctx:
        rows_before = len(await _call_rows(ctx))
        monkeypatch.setattr(access_log, "log_event", _slow)
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            first = asyncio.create_task(
                ctx.access_log.record(
                    origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
                )
            )
            await holding.wait()
            closing = asyncio.create_task(ctx.access_log.close())
            # One loop turn each, so the lock's waiters queue in this order rather than in whichever
            # order the gather below happens to start them.
            await asyncio.sleep(0)
            queued = asyncio.create_task(
                ctx.access_log.record(
                    origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
                )
            )
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(first, closing, queued)
        monkeypatch.undo()
        assert len(await _call_rows(ctx)) == rows_before + 1, "the in-flight row was lost"
    assert caplog.records == [], "a clean close was reported as a failure"


async def test_two_concurrent_calls_each_get_their_row(tmp_path: Path) -> None:
    """One writer at a time on the private connection, because the three statements interleave.

    `record` is awaited from every client connection's task and yields at `BEGIN`, the `INSERT` and
    `COMMIT`. Without the lock: A begins, B begins *inside* A's transaction and fails with
    `SQLITE_ERROR` — not contention, so it reports — and B's rollback discards **A's** row along
    with its own, leaving two calls, no rows and a log line blaming the disk. Two typed
    `zikaron knowledge` commands, or a person's CLI beside an agent's session, reach it.
    """
    async with open_context(tmp_path) as ctx:
        await asyncio.gather(
            *(
                ctx.access_log.record(
                    origin=EventOrigin(session_id="s1", client_kind="mcp", op_id=f"op{index}"),
                    method="knowledge_list",
                    refused=None,
                    duration_ms=1.0,
                )
                for index in range(2)
            )
        )
        assert len(await _call_rows(ctx)) == 2


async def _closed_connection(ctx: ServiceContext) -> aiosqlite.Connection:
    """A connection to this store that has already been closed — `finalize`'s own end state."""
    connection, _inode = await open_connection(
        ctx.store.path, pragmas=ddl.ACCESS_LOG_PRAGMAS, existing_only=True
    )
    await connection.close()
    return connection


async def test_a_second_failure_while_the_latch_holds_is_not_logged_again(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*Logged once* — the first half, which the clearing test above cannot reach.

    The latch exists to stop a flood: a store that refuses every payload would otherwise write a
    traceback per user message, and the one line worth reading would be buried in thousands. The
    test beside this one drives two failures with a landed row between them and asserts **two**
    messages, which is green whether or not the suppression works. Only two failures with nothing
    between them tell the latch from a counter that never latched at all.
    """
    async with open_context(tmp_path) as ctx:
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            monkeypatch.setattr(access_log, "EVENT_SPECS", _spec_demanding_an_absent_field())
            for _ in range(3):
                await ctx.access_log.record(
                    origin=_origin(), method="knowledge_list", refused=None, duration_ms=1.0
                )
        assert not await _call_rows(ctx), "the premise: every one of the three failed"
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1, f"the latch let a flood through: {messages}"


async def test_a_failing_access_log_close_is_logged_and_does_not_stop_the_store_closing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Startup cleanup attempts **both** closes, whichever of them fails.

    `_close_after_failed_startup` runs while a construction failure is being handled, and its own
    docstring promises each close is attempted and each failure logged rather than replacing the
    first. The access-log arm is the one nothing reached: a close that raises there would, without
    the guard, skip the store close entirely and leave a connection open behind a service that never
    started — and the caller's bare `raise` would surface *this* exception instead of the one worth
    diagnosing.
    """
    async with open_context(tmp_path) as ctx:
        closed: list[str] = []
        real_store_close = Store.close

        async def _explode(_self: AccessLog) -> None:
            raise OSError("cannot close the access log")

        async def _record_store_close(store: Store) -> None:
            closed.append("store")
            await real_store_close(store)

        # Patched on the classes rather than the instances, because `AccessLog` is slotted and an
        # instance attribute cannot be set on it at all — a failure that reads as a typo in the
        # attribute name. `Store` is not, and is patched the same way only for symmetry.
        monkeypatch.setattr(AccessLog, "close", _explode)
        monkeypatch.setattr(Store, "close", _record_store_close)
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            await service_context._close_after_failed_startup(ctx.store, ctx.access_log)
        # Before leaving the fixture, which closes both itself and would otherwise meet `_explode`
        # on the way out — a teardown failure that has nothing to say about what is under test.
        monkeypatch.undo()

    messages = [record.getMessage() for record in caplog.records]
    assert any("failed to close the access log" in message for message in messages), messages
    assert closed == ["store"], "the store close was skipped by the access log's failure"


async def test_startup_cleanup_with_no_access_log_closes_the_store_and_says_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """`None` is a real argument here: the log is opened after the store, so a failure between the
    two arrives with one to close and not the other. Skipping straight to the store is the whole
    behaviour, and a cleanup that spoke about a log that was never opened would send its reader
    looking for a connection that does not exist."""
    async with open_context(tmp_path) as ctx:
        with caplog.at_level(logging.ERROR, logger="zikaron.service"):
            await service_context._close_after_failed_startup(ctx.store, None)
    assert not caplog.records, [record.getMessage() for record in caplog.records]
