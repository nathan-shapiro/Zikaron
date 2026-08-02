"""`signals.writes` — signal 1 (writes per session, zero-write rate) and signal 5 (write sizes)."""

from pathlib import Path

from tests.signals_fixtures import T0, Call, insert_event, open_store
from zikaron.core.events import ClientKind, EventKind
from zikaron.core.signals.writes import write_size_distribution, writes_per_session


async def test_a_linked_session_with_no_writes_is_zero_write(tmp_path: Path) -> None:
    """The exact case signal 1 exists to find: a linked session (both clients present) whose only
    activity is a push, with no `remember` or `amend` at all."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.HOOK.value, op_id="op1"),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op2"),
            kind=EventKind.FETCH.value,
            memory_uuid="m1",
        )
        result = await writes_per_session(store.connection)
        assert result.n_linked_sessions == 1
        assert result.n_zero_write_sessions == 1
        assert result.zero_write_rate == 1.0
        [session] = result.sessions
        assert session.n_remember == 0
        assert session.n_amend == 0
        assert session.wrote_nothing is True


async def test_remember_and_amend_are_counted_separately_and_summed(tmp_path: Path) -> None:
    """Hand-computed: one session makes two `remember` calls and one `amend` call. Signal 1 must
    report `n_remember=2`, `n_amend=1`, and `n_writes=3` — separately and summed, per the design's
    own phrasing, not one or the other."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.HOOK.value, op_id="op0"),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        for i in range(2):
            await insert_event(
                store,
                call=Call(
                    at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id=f"remember-{i}"
                ),
                kind=EventKind.REMEMBER.value,
                memory_uuid=f"m{i}",
            )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="amend-0"),
            kind=EventKind.AMEND.value,
            memory_uuid="m0",
        )
        [session] = (await writes_per_session(store.connection)).sessions
        assert session.n_remember == 2
        assert session.n_amend == 1
        assert session.n_writes == 3


async def test_an_unlinked_session_is_excluded_rather_than_counted_as_zero_write(
    tmp_path: Path,
) -> None:
    """The failure the design names explicitly: an mcp-only session that wrote plenty must not be
    counted as a linked zero-write session just because it has no `hook` event to link against —
    it must be excluded from the denominator entirely."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="unlinked", client_kind=ClientKind.MCP.value, op_id="op1"),
            kind=EventKind.REMEMBER.value,
            memory_uuid="m1",
        )
        result = await writes_per_session(store.connection)
        assert result.n_linked_sessions == 0
        assert result.sessions == ()


async def test_zero_write_rate_is_none_over_an_empty_store(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        result = await writes_per_session(store.connection)
        assert result.zero_write_rate is None


async def test_zero_write_rate_cannot_exceed_one(tmp_path: Path) -> None:
    """A fixture where every linked session wrote nothing: the rate must land at exactly `1.0`,
    never above it, since the numerator is a subset count of the exact denominator population."""
    async with await open_store(tmp_path) as store:
        for session_id in ("s1", "s2", "s3"):
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-hook",
                ),
                kind=EventKind.SURFACE_CALL.value,
                memory_uuid=None,
            )
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id=session_id,
                    client_kind=ClientKind.MCP.value,
                    op_id=f"{session_id}-mcp",
                ),
                kind=EventKind.FETCH.value,
                memory_uuid="m1",
            )
        result = await writes_per_session(store.connection)
        assert result.zero_write_rate == 1.0


async def test_determinism_writes_per_session(tmp_path: Path) -> None:
    """The same fixture read twice returns byte-identical results — order of `sessions` included,
    since it is built by sorting the linked-session ids rather than by insertion or dict order."""
    async with await open_store(tmp_path) as store:
        for session_id in ("zeta", "alpha"):
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-hook",
                ),
                kind=EventKind.SURFACE_CALL.value,
                memory_uuid=None,
            )
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id=session_id,
                    client_kind=ClientKind.MCP.value,
                    op_id=f"{session_id}-mcp",
                ),
                kind=EventKind.REMEMBER.value,
                memory_uuid="m1",
            )
        first = await writes_per_session(store.connection)
        second = await writes_per_session(store.connection)
        assert first.sessions == second.sessions
        assert [s.session_id for s in first.sessions] == ["alpha", "zeta"]


async def test_total_remember_and_total_amend_sum_across_sessions(tmp_path: Path) -> None:
    """`total_remember`/`total_amend` are store-wide sums across every linked session, distinct
    from any one session's own `n_remember`/`n_amend` — exercised directly since they are public
    API a caller may read without ever inspecting `sessions` itself."""
    async with await open_store(tmp_path) as store:
        for session_id in ("s1", "s2"):
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-hook",
                ),
                kind=EventKind.SURFACE_CALL.value,
                memory_uuid=None,
            )
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id=session_id,
                    client_kind=ClientKind.MCP.value,
                    op_id=f"{session_id}-remember",
                ),
                kind=EventKind.REMEMBER.value,
                memory_uuid="m1",
            )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="s1-amend"),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        result = await writes_per_session(store.connection)
        assert result.total_remember == 2
        assert result.total_amend == 1


# ---------------------------------------------------------------------------
# Signal 5 — write size distribution
# ---------------------------------------------------------------------------


async def test_remember_and_amend_token_counts_are_both_included(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op1"),
            kind=EventKind.REMEMBER.value,
            memory_uuid="m1",
            detail={"token_count": 42},
        )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op2"),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
            detail={"token_count": 84},
        )
        sizes = (await write_size_distribution(store.connection)).values
        assert sorted(sizes) == [42, 84]


async def test_a_merge_target_row_is_included_and_an_absorbed_row_is_not(tmp_path: Path) -> None:
    """Hand-computed: one `merge` call emits a `target` row (authored prose, `token_count=100`)
    and two `absorbed` rows (no prose, `token_count=NULL`). Only the target's size may appear."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="merge-1"
            ),
            kind=EventKind.MERGE.value,
            memory_uuid="target-uuid",
            detail={"role": "target", "token_count": 100},
        )
        for absorbed_uuid in ("absorbed-1", "absorbed-2"):
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id="s1",
                    client_kind=ClientKind.CONSOLIDATOR.value,
                    op_id="merge-1",
                ),
                kind=EventKind.MERGE.value,
                memory_uuid=absorbed_uuid,
                detail={"role": "absorbed", "token_count": None},
            )
        sizes = (await write_size_distribution(store.connection)).values
        assert sizes == (100,)


async def test_promote_created_and_flipped_rows_are_included_absorbed_is_not(
    tmp_path: Path,
) -> None:
    """Hand-computed, covering both of `promote`'s forms in one fixture: a `new_row` promotion's
    `created` row (`token_count=55`) and its `absorbed` row (null), plus an `in_place` promotion's
    single `flipped` row (`token_count=30`) — the design's own cardinality rule, that an in-place
    promotion contributes exactly one authored row."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="promote-1"
            ),
            kind=EventKind.PROMOTE.value,
            memory_uuid="created-uuid",
            detail={"role": "created", "token_count": 55},
        )
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="promote-1"
            ),
            kind=EventKind.PROMOTE.value,
            memory_uuid="absorbed-uuid",
            detail={"role": "absorbed", "token_count": None},
        )
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="promote-2"
            ),
            kind=EventKind.PROMOTE.value,
            memory_uuid="flipped-uuid",
            detail={"role": "flipped", "token_count": 30},
        )
        sizes = (await write_size_distribution(store.connection)).values
        assert sorted(sizes) == [30, 55]


async def test_discard_and_retire_contribute_no_size_at_all(tmp_path: Path) -> None:
    """`discard` and `retire` author no prose and carry no `token_count` field at all — a
    distribution over authored writes must not manufacture a value for either kind."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op1"),
            kind=EventKind.RETIRE.value,
            memory_uuid="m1",
        )
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="op2"
            ),
            kind=EventKind.DISCARD.value,
            memory_uuid="m2",
        )
        sizes = (await write_size_distribution(store.connection)).values
        assert sizes == ()


async def test_write_size_distribution_is_empty_over_an_empty_store(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        assert (await write_size_distribution(store.connection)).values == ()


async def test_determinism_write_size_distribution(tmp_path: Path) -> None:
    """The values are ordered by the underlying `event.id`, so two reads of one store must return
    byte-identical results — not merely the same multiset in some order `UNION ALL` happened to
    produce. Built to distinguish true `event.id` order from an accidental branch-scan order: a
    `merge` target row is inserted **before** a `remember` row, so `event.id` order and the
    query's own three-branch order disagree — a `UNION ALL` with no `ORDER BY` would return
    branch order (the `remember`/`amend` branch scanned first, in its own `event.id` order, then
    the `merge` branch's), which is exactly backwards from the true global order this fixture
    checks."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="op0"
            ),
            kind=EventKind.MERGE.value,
            memory_uuid="m0",
            detail={"role": "target", "token_count": 999},
        )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op1"),
            kind=EventKind.REMEMBER.value,
            memory_uuid="m1",
            detail={"token_count": 111},
        )
        first = await write_size_distribution(store.connection)
        second = await write_size_distribution(store.connection)
        assert first == second
        assert first.values == (999, 111)
