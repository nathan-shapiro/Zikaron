"""`signals.contention` — signal 6, version-conflict and no-receipt rate."""

from pathlib import Path

import pytest

from tests.signals_fixtures import T0, Call, insert_event, open_store
from zikaron.core.events import ClientKind, EventKind
from zikaron.core.signals.contention import ConflictRate, conflict_rate


async def test_version_conflict_and_no_receipt_are_never_summed(tmp_path: Path) -> None:
    """Hand-computed: one committed `amend`, one `version_conflict` call, one `no_receipt` call.
    Both rates are read off the same three-call denominator, and neither numerator is the other's
    sum — a conflict means "read something stale", a missing receipt means "wrote without
    reading", and the design states these must never collapse into one number."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op-committed"
            ),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op-conflict"
            ),
            kind=EventKind.VERSION_CONFLICT.value,
            memory_uuid="m2",
        )
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op-no-receipt"
            ),
            kind=EventKind.NO_RECEIPT.value,
            memory_uuid="m3",
        )
        result = await conflict_rate(store.connection)
        assert result.n_calls == 3
        assert result.n_version_conflict == 1
        assert result.n_no_receipt == 1
        assert result.version_conflict_rate == 1 / 3
        assert result.no_receipt_rate == 1 / 3


async def test_a_three_row_conflicting_call_counts_once_not_three_times(tmp_path: Path) -> None:
    """The exact bug the design calls out by name: `version_conflict` commits one row **per
    contested uuid**, so a single rejected `merge` naming three offending uuids emits three rows
    sharing one `op_id`. A rate over calls must dedup by `op_id` — counting rows here would give
    3-over-1 and exceed 100%, which the design states explicitly as the failure to avoid."""
    async with await open_store(tmp_path) as store:
        for uuid in ("m1", "m2", "m3"):
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id="s1",
                    client_kind=ClientKind.MCP.value,
                    op_id="one-conflicting-merge",
                ),
                kind=EventKind.VERSION_CONFLICT.value,
                memory_uuid=uuid,
            )
        result = await conflict_rate(store.connection)
        assert result.n_version_conflict == 1
        assert result.n_calls == 1
        assert result.version_conflict_rate == 1.0


async def test_remember_is_excluded_from_the_denominator(tmp_path: Path) -> None:
    """`remember` names no pre-existing row and so cannot appear in either numerator — admitting it
    into the denominator would divide contention by write volume. A store with many `remember`
    calls and one conflicting `amend` must report a rate of `1.0`, not diluted by the remembers."""
    async with await open_store(tmp_path) as store:
        for i in range(10):
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
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op-conflict"
            ),
            kind=EventKind.VERSION_CONFLICT.value,
            memory_uuid="m0",
        )
        result = await conflict_rate(store.connection)
        assert result.n_calls == 1
        assert result.version_conflict_rate == 1.0


async def test_every_receipt_gated_kind_counts_toward_committed(tmp_path: Path) -> None:
    """`amend`, `retire`, `merge`, `promote`, `discard` — the five kinds the design names as the
    committed population — each contribute to `n_committed`, deduped by `op_id`."""
    async with await open_store(tmp_path) as store:
        kinds = (
            EventKind.AMEND,
            EventKind.RETIRE,
            EventKind.MERGE,
            EventKind.PROMOTE,
            EventKind.DISCARD,
        )
        for kind in kinds:
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id="s1",
                    client_kind=ClientKind.CONSOLIDATOR.value,
                    op_id=f"op-{kind.value}",
                ),
                kind=kind.value,
                memory_uuid="m1",
            )
        result = await conflict_rate(store.connection)
        assert result.n_committed == 5
        assert result.n_calls == 5


async def test_consolidator_calls_are_included_in_the_denominator(tmp_path: Path) -> None:
    """D30 requires consolidator writes in scope — a `merge` from `client_kind='consolidator'`
    counts exactly as a committed call from `mcp` would."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="op1"
            ),
            kind=EventKind.MERGE.value,
            memory_uuid="m1",
        )
        result = await conflict_rate(store.connection)
        assert result.n_committed == 1


async def test_a_retried_conflict_contributes_one_to_the_numerator_and_two_to_the_denominator(
    tmp_path: Path,
) -> None:
    """A conflict followed by a successful retry is two calls with two `op_id`s: the first is
    rejected (`version_conflict`), the second commits (`amend`). Each attempt counts once."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="attempt-1"),
            kind=EventKind.VERSION_CONFLICT.value,
            memory_uuid="m1",
        )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="attempt-2"),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        result = await conflict_rate(store.connection)
        assert result.n_version_conflict == 1
        assert result.n_committed == 1
        assert result.n_calls == 2
        assert result.version_conflict_rate == 0.5


async def test_both_rates_are_none_over_an_empty_store(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        result = await conflict_rate(store.connection)
        assert result.n_calls == 0
        assert result.version_conflict_rate is None
        assert result.no_receipt_rate is None


async def test_determinism_conflict_rate(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op1"),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        first = await conflict_rate(store.connection)
        second = await conflict_rate(store.connection)
        assert first == second


def test_conflict_rate_refuses_a_negative_call_count() -> None:
    """Invariant test: every count reaching this type comes from `COUNT(DISTINCT op_id)`, which
    cannot be negative — so a negative value here is a defect in whoever constructed it, caught at
    construction rather than allowed to report a nonsensical rate."""
    with pytest.raises(ValueError, match="non-negative"):
        ConflictRate(n_version_conflict=-1, n_no_receipt=0, n_committed=0)
