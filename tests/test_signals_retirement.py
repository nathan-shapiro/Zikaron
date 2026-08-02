"""`signals.retirement` — signal 4, retire count split by `superseded_by`, over `remember` count."""

from pathlib import Path

from tests.signals_fixtures import T0, Call, insert_event, open_store
from zikaron.core.events import ClientKind, EventKind
from zikaron.core.signals.retirement import retire_count


async def test_split_by_superseded_by_null_versus_not_null(tmp_path: Path) -> None:
    """Hand-computed: two outright retirements (`superseded_by IS NULL`) and one superseding
    retirement (`superseded_by` names a replacement)."""
    async with await open_store(tmp_path) as store:
        for uuid in ("m1", "m2"):
            await insert_event(
                store,
                call=Call(
                    at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id=f"retire-{uuid}"
                ),
                kind=EventKind.RETIRE.value,
                memory_uuid=uuid,
                detail={"superseded_by": None},
            )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="retire-m3"),
            kind=EventKind.RETIRE.value,
            memory_uuid="m3",
            detail={"superseded_by": "m4"},
        )
        result = await retire_count(store.connection)
        assert result.n_outright == 2
        assert result.n_superseding == 1
        assert result.n_retire == 3


async def test_denominator_is_remember_count_in_the_same_window(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        for i in range(4):
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
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="retire-m0"),
            kind=EventKind.RETIRE.value,
            memory_uuid="m0",
            detail={"superseded_by": None},
        )
        result = await retire_count(store.connection)
        assert result.n_remember == 4
        assert result.retire_per_write == 0.25


async def test_retire_per_write_is_none_over_zero_remembers(tmp_path: Path) -> None:
    """An empty denominator must report `None`, never a division error and never `0.0` — a
    genuinely zero rate and an undefined one are different facts."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="retire-m0"),
            kind=EventKind.RETIRE.value,
            memory_uuid="m0",
            detail={"superseded_by": None},
        )
        result = await retire_count(store.connection)
        assert result.n_remember == 0
        assert result.retire_per_write is None


async def test_retire_per_write_may_exceed_one_and_that_is_not_a_defect(tmp_path: Path) -> None:
    """Retire-per-write is deliberately not bounded to `[0, 1]` — the design's own name for it is
    a *ratio*, not a rate over one shared population, so more retirements than remembers in the
    store's current window is a legitimate reading, not a value this type should refuse."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="remember-1"),
            kind=EventKind.REMEMBER.value,
            memory_uuid="m1",
        )
        for i in range(2):
            await insert_event(
                store,
                call=Call(
                    at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id=f"retire-{i}"
                ),
                kind=EventKind.RETIRE.value,
                memory_uuid=f"m{i}",
                detail={"superseded_by": None},
            )
        result = await retire_count(store.connection)
        assert result.retire_per_write == 2.0


async def test_retire_count_is_zero_over_an_empty_store(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        result = await retire_count(store.connection)
        assert result.n_outright == 0
        assert result.n_superseding == 0
        assert result.n_remember == 0
        assert result.retire_per_write is None


async def test_determinism_retire_count(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="retire-1"),
            kind=EventKind.RETIRE.value,
            memory_uuid="m1",
            detail={"superseded_by": "m2"},
        )
        first = await retire_count(store.connection)
        second = await retire_count(store.connection)
        assert first == second
