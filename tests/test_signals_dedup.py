"""`signals.dedup` — signal 2, dedup offered → resolved (D15's near-duplicate hand-back outcome)."""

from pathlib import Path

import pytest

from tests.signals_fixtures import Call, insert_event, open_store
from zikaron.core.events import ClientKind, EventKind
from zikaron.core.signals.dedup import DedupOutcome, DedupResolution, dedup_resolution
from zikaron.core.store.store import Store

_OFFER_AT = "2026-01-01T00:00:00.000000+00:00"


async def _offered(tmp_path: Path, *, offered_uuid: str = "X", created_uuid: str = "N") -> Store:
    """One `dedup_offered` row: `remember(N)` offered back the pre-existing `X`."""
    store = await open_store(tmp_path)
    await insert_event(
        store,
        call=Call(
            at=_OFFER_AT, session_id="s1", client_kind=ClientKind.MCP.value, op_id="remember-op"
        ),
        kind=EventKind.DEDUP_OFFERED.value,
        memory_uuid=offered_uuid,
        detail={"created_uuid": created_uuid, "cosine": 0.9, "rank": 1},
    )
    return store


async def _amend(store: Store, *, at: str, uuid: str, op_id: str = "amend-op") -> None:
    await insert_event(
        store,
        call=Call(at=at, session_id="s1", client_kind=ClientKind.MCP.value, op_id=op_id),
        kind=EventKind.AMEND.value,
        memory_uuid=uuid,
    )


async def _retire(
    store: Store, *, at: str, uuid: str, superseded_by: str, op_id: str = "retire-op"
) -> None:
    await insert_event(
        store,
        call=Call(at=at, session_id="s1", client_kind=ClientKind.MCP.value, op_id=op_id),
        kind=EventKind.RETIRE.value,
        memory_uuid=uuid,
        detail={"superseded_by": superseded_by},
    )


async def test_amend_and_retire_within_deadline_closes_early_as_fully_resolved(
    tmp_path: Path,
) -> None:
    """Hand-computed: `A ∧ R` both within the deadline. Must classify `fully_resolved` even though
    `now` has not yet reached the deadline — the design's own "closes early" rule."""
    async with await _offered(tmp_path) as store:
        await _amend(store, at="2026-01-05T00:00:00.000000+00:00", uuid="X")
        await _retire(store, at="2026-01-06T00:00:00.000000+00:00", uuid="N", superseded_by="X")
        result = await dedup_resolution(
            store.connection, now="2026-01-10T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.FULLY_RESOLVED) == 1
        assert result.count_for(DedupOutcome.PENDING) == 0


async def test_amend_only_before_deadline_is_pending_not_a_failure(tmp_path: Path) -> None:
    """The design's own named risk: an amend-only offer, still inside its deadline, must not be
    published as a failure while an in-deadline retire could still complete it."""
    async with await _offered(tmp_path) as store:
        await _amend(store, at="2026-01-05T00:00:00.000000+00:00", uuid="X")
        result = await dedup_resolution(
            store.connection, now="2026-01-10T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.PENDING) == 1
        assert result.count_for(DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE) == 0


async def test_amend_only_after_deadline_matures_as_amended_but_duplicate_left_live(
    tmp_path: Path,
) -> None:
    async with await _offered(tmp_path) as store:
        await _amend(store, at="2026-01-05T00:00:00.000000+00:00", uuid="X")
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE) == 1
        assert result.count_for(DedupOutcome.PENDING) == 0


async def test_retire_only_after_deadline_matures_as_duplicate_discarded_without_amend(
    tmp_path: Path,
) -> None:
    async with await _offered(tmp_path) as store:
        await _retire(store, at="2026-01-05T00:00:00.000000+00:00", uuid="N", superseded_by="X")
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND) == 1


async def test_neither_after_deadline_matures_as_ignored(tmp_path: Path) -> None:
    async with await _offered(tmp_path) as store:
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.IGNORED) == 1


async def test_neither_before_deadline_is_pending(tmp_path: Path) -> None:
    async with await _offered(tmp_path) as store:
        result = await dedup_resolution(
            store.connection, now="2026-01-10T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.PENDING) == 1
        assert result.n_matured == 0
        assert result.fully_resolved_rate is None


async def test_a_post_deadline_retire_does_not_change_a_matured_ignored_classification(
    tmp_path: Path,
) -> None:
    """The done-when's own requirement: classify as matured `ignored` (deadline passed, neither
    follow-up), then insert a late retire after that classification was made, and confirm
    re-running still reports `ignored` — never `duplicate_discarded_without_amend`."""
    async with await _offered(tmp_path) as store:
        past_deadline = "2026-02-15T00:00:00.000000+00:00"
        first = await dedup_resolution(store.connection, now=past_deadline, signal_horizon_days=30)
        assert first.count_for(DedupOutcome.IGNORED) == 1

        await _retire(store, at="2026-03-01T00:00:00.000000+00:00", uuid="N", superseded_by="X")
        second = await dedup_resolution(
            store.connection, now="2026-04-01T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert second.count_for(DedupOutcome.IGNORED) == 1
        assert second.count_for(DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND) == 0


async def test_a_post_deadline_amend_does_not_upgrade_a_matured_duplicate_discarded_pair(
    tmp_path: Path,
) -> None:
    """The same immutability property from the other side: a matured
    `duplicate_discarded_without_amend` pair must not become `fully_resolved` because a late
    amend arrives after the classification already matured."""
    async with await _offered(tmp_path) as store:
        await _retire(store, at="2026-01-05T00:00:00.000000+00:00", uuid="N", superseded_by="X")
        past_deadline = "2026-02-15T00:00:00.000000+00:00"
        first = await dedup_resolution(store.connection, now=past_deadline, signal_horizon_days=30)
        assert first.count_for(DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND) == 1

        await _amend(store, at="2026-03-01T00:00:00.000000+00:00", uuid="X")
        second = await dedup_resolution(
            store.connection, now="2026-04-01T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert second.count_for(DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND) == 1
        assert second.count_for(DedupOutcome.FULLY_RESOLVED) == 0


async def test_an_amend_on_the_wrong_uuid_does_not_qualify(tmp_path: Path) -> None:
    """`A` requires the amend to name the *offered* uuid `X`, not the created uuid `N` or some
    other row — an amend on the wrong memory must not satisfy the condition."""
    async with await _offered(tmp_path) as store:
        await _amend(store, at="2026-01-05T00:00:00.000000+00:00", uuid="N")
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE) == 0
        assert result.count_for(DedupOutcome.IGNORED) == 1


async def test_a_retire_with_the_wrong_superseded_by_does_not_qualify(tmp_path: Path) -> None:
    """`R` requires `detail.superseded_by = X` (the offered uuid) — a retire of `N` naming a
    *different* replacement must not satisfy the condition."""
    async with await _offered(tmp_path) as store:
        await _retire(
            store, at="2026-01-05T00:00:00.000000+00:00", uuid="N", superseded_by="some-other-uuid"
        )
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.DUPLICATE_DISCARDED_WITHOUT_AMEND) == 0
        assert result.count_for(DedupOutcome.IGNORED) == 1


async def test_an_amend_before_the_offer_by_id_does_not_qualify(tmp_path: Path) -> None:
    """ "Followed by" is `event.id > offer.id` — an amend inserted before the offer (earlier id)
    must not count, even with an `at` inside what would otherwise be the deadline window."""
    store = await open_store(tmp_path)
    async with store:
        await _amend(store, at="2025-12-01T00:00:00.000000+00:00", uuid="X")
        await insert_event(
            store,
            call=Call(
                at=_OFFER_AT, session_id="s1", client_kind=ClientKind.MCP.value, op_id="remember-op"
            ),
            kind=EventKind.DEDUP_OFFERED.value,
            memory_uuid="X",
            detail={"created_uuid": "N", "cosine": 0.9, "rank": 1},
        )
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE) == 0
        assert result.count_for(DedupOutcome.IGNORED) == 1


async def test_the_unit_is_the_offer_row_two_offers_on_the_same_uuid_pair_are_two(
    tmp_path: Path,
) -> None:
    """Two separate `remember` calls both offering back `X` are two independent
    `dedup_offered` rows and must classify independently, even against the same offered uuid."""
    store = await open_store(tmp_path)
    async with store:
        for op_id, created_uuid in (("remember-1", "N1"), ("remember-2", "N2")):
            await insert_event(
                store,
                call=Call(
                    at=_OFFER_AT, session_id="s1", client_kind=ClientKind.MCP.value, op_id=op_id
                ),
                kind=EventKind.DEDUP_OFFERED.value,
                memory_uuid="X",
                detail={"created_uuid": created_uuid, "cosine": 0.9, "rank": 1},
            )
        await _amend(store, at="2026-01-05T00:00:00.000000+00:00", uuid="X", op_id="amend-1")
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.AMENDED_BUT_DUPLICATE_LEFT_LIVE) == 2


async def test_fully_resolved_rate_cannot_exceed_one(tmp_path: Path) -> None:
    """A fixture where the offered uuid receives many amends and the created uuid many retires —
    a naive count of qualifying rows rather than a per-offer classification would overcount. The
    correct rate, over one offer row, must land at exactly `1.0`."""
    async with await _offered(tmp_path) as store:
        for i in range(3):
            await_at = f"2026-01-0{2 + i}T00:00:00.000000+00:00"
            await _amend(store, at=await_at, uuid="X", op_id=f"amend-{i}")
        for i in range(3):
            retire_at = f"2026-01-1{i}T00:00:00.000000+00:00"
            await _retire(store, at=retire_at, uuid="N", superseded_by="X", op_id=f"retire-{i}")
        result = await dedup_resolution(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.FULLY_RESOLVED) == 1
        assert result.n_matured == 1
        assert result.fully_resolved_rate == 1.0


async def test_rate_is_over_the_four_matured_classes_only(tmp_path: Path) -> None:
    """Hand-computed: one fully-resolved offer (matured) and one pending offer. `n_matured` must
    be `1`, not `2` — the pending offer is excluded from the rate's denominator entirely."""
    store = await open_store(tmp_path)
    async with store:
        await insert_event(
            store,
            call=Call(
                at=_OFFER_AT, session_id="s1", client_kind=ClientKind.MCP.value, op_id="offer-1"
            ),
            kind=EventKind.DEDUP_OFFERED.value,
            memory_uuid="X1",
            detail={"created_uuid": "N1", "cosine": 0.9, "rank": 1},
        )
        await _amend(store, at="2026-01-05T00:00:00.000000+00:00", uuid="X1", op_id="amend-1")
        await _retire(
            store,
            at="2026-01-06T00:00:00.000000+00:00",
            uuid="N1",
            superseded_by="X1",
            op_id="retire-1",
        )
        await insert_event(
            store,
            call=Call(
                at="2026-02-01T00:00:00.000000+00:00",
                session_id="s1",
                client_kind=ClientKind.MCP.value,
                op_id="offer-2",
            ),
            kind=EventKind.DEDUP_OFFERED.value,
            memory_uuid="X2",
            detail={"created_uuid": "N2", "cosine": 0.9, "rank": 1},
        )
        result = await dedup_resolution(
            store.connection, now="2026-02-10T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.count_for(DedupOutcome.FULLY_RESOLVED) == 1
        assert result.count_for(DedupOutcome.PENDING) == 1
        assert result.n_matured == 1
        assert result.fully_resolved_rate == 1.0


async def test_signal_horizon_days_travels_with_the_result(tmp_path: Path) -> None:
    async with await _offered(tmp_path) as store:
        result = await dedup_resolution(
            store.connection, now="2026-01-10T00:00:00.000000+00:00", signal_horizon_days=45
        )
        assert result.signal_horizon_days == 45


async def test_resolution_is_empty_over_an_empty_store(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        result = await dedup_resolution(
            store.connection, now="2026-01-01T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_matured == 0
        assert result.fully_resolved_rate is None
        assert all(result.count_for(outcome) == 0 for outcome in DedupOutcome)


async def test_determinism_dedup_resolution(tmp_path: Path) -> None:
    async with await _offered(tmp_path) as store:
        await _amend(store, at="2026-01-05T00:00:00.000000+00:00", uuid="X")
        now = "2026-02-15T00:00:00.000000+00:00"
        first = await dedup_resolution(store.connection, now=now, signal_horizon_days=30)
        second = await dedup_resolution(store.connection, now=now, signal_horizon_days=30)
        assert first == second


def test_dedup_resolution_refuses_a_negative_count() -> None:
    """Invariant test: every count reaching this type comes from tallying classified rows, which
    cannot be negative — so a negative value here is a defect in whoever constructed it, caught at
    construction rather than allowed to make `fully_resolved_rate` exceed 1."""
    with pytest.raises(ValueError, match="non-negative"):
        DedupResolution(
            fully_resolved=-1,
            amended_but_duplicate_left_live=0,
            duplicate_discarded_without_amend=0,
            ignored=0,
            pending=0,
            signal_horizon_days=30,
        )
