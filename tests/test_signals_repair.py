"""`signals.repair` — signal 3, amend after surface (does D11's repair loop fire?)."""

from pathlib import Path

from tests.signals_fixtures import Call, insert_event, open_store
from zikaron.core.events import ClientKind, EventKind
from zikaron.core.signals.horizon import deadline
from zikaron.core.signals.repair import amend_after_surface
from zikaron.core.store.store import Store

_SURFACE_AT = "2026-01-01T00:00:00.000000+00:00"


async def _surfaced_session(tmp_path: Path, *, session_id: str = "s1") -> Store:
    """A linked session (`hook` + `mcp`) with one `surface` row on `m1`, at `_SURFACE_AT`."""
    store = await open_store(tmp_path)
    await insert_event(
        store,
        call=Call(
            at=_SURFACE_AT,
            session_id=session_id,
            client_kind=ClientKind.HOOK.value,
            op_id=f"{session_id}-surface-call",
        ),
        kind=EventKind.SURFACE_CALL.value,
        memory_uuid=None,
    )
    await insert_event(
        store,
        call=Call(
            at=_SURFACE_AT,
            session_id=session_id,
            client_kind=ClientKind.HOOK.value,
            op_id=f"{session_id}-surface-call",
        ),
        kind=EventKind.SURFACE.value,
        memory_uuid="m1",
    )
    # A same-session MCP event is what makes the session linked at all.
    await insert_event(
        store,
        call=Call(
            at=_SURFACE_AT,
            session_id=session_id,
            client_kind=ClientKind.MCP.value,
            op_id=f"{session_id}-fetch",
        ),
        kind=EventKind.FETCH.value,
        memory_uuid="m1",
    )
    return store


async def test_a_qualifying_amend_within_the_deadline_is_amended(tmp_path: Path) -> None:
    async with await _surfaced_session(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at="2026-01-02T00:00:00.000000+00:00",
                session_id="s1",
                client_kind=ClientKind.MCP.value,
                op_id="s1-amend",
            ),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        result = await amend_after_surface(
            store.connection, now="2026-01-03T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 1
        assert result.n_not_amended == 0
        assert result.n_pending == 0


async def test_no_amend_and_deadline_not_yet_passed_is_pending(tmp_path: Path) -> None:
    async with await _surfaced_session(tmp_path) as store:
        result = await amend_after_surface(
            store.connection, now="2026-01-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 0
        assert result.n_not_amended == 0
        assert result.n_pending == 1
        assert result.amend_after_surface_rate is None


async def test_no_amend_and_deadline_passed_is_not_amended(tmp_path: Path) -> None:
    async with await _surfaced_session(tmp_path) as store:
        result = await amend_after_surface(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 0
        assert result.n_not_amended == 1
        assert result.n_pending == 0
        assert result.amend_after_surface_rate == 0.0


async def test_a_post_deadline_amend_does_not_change_a_matured_not_amended_classification(
    tmp_path: Path,
) -> None:
    """The done-when's own requirement: classify a pair as matured `not_amended` (deadline
    already passed, no amend yet), then insert a late `amend` after that classification was made,
    and confirm re-running the query still reports `not_amended` — never `amended`."""
    async with await _surfaced_session(tmp_path) as store:
        past_deadline = "2026-02-15T00:00:00.000000+00:00"
        first = await amend_after_surface(
            store.connection, now=past_deadline, signal_horizon_days=30
        )
        assert first.n_not_amended == 1

        # The late follow-up: an amend whose own `at` is well past the pair's deadline.
        await insert_event(
            store,
            call=Call(
                at="2026-03-01T00:00:00.000000+00:00",
                session_id="s1",
                client_kind=ClientKind.MCP.value,
                op_id="s1-late-amend",
            ),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        second = await amend_after_surface(
            store.connection,
            now="2026-04-01T00:00:00.000000+00:00",
            signal_horizon_days=30,
        )
        assert second.n_amended == 0
        assert second.n_not_amended == 1
        assert second.n_pending == 0


async def test_an_amend_before_the_earliest_surface_by_id_does_not_qualify(
    tmp_path: Path,
) -> None:
    """ "Followed by" means `event.id` strictly greater than the earliest `surface` row's own id.
    An `amend` inserted with an earlier `id` — i.e. before the surface in this fixture's own
    insertion, hence event.id, order — must not count as a repair of that surfacing."""
    store = await open_store(tmp_path)
    async with store:
        await insert_event(
            store,
            call=Call(
                at="2025-12-31T00:00:00.000000+00:00",
                session_id="s1",
                client_kind=ClientKind.MCP.value,
                op_id="s1-early-amend",
            ),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        await insert_event(
            store,
            call=Call(
                at=_SURFACE_AT,
                session_id="s1",
                client_kind=ClientKind.HOOK.value,
                op_id="s1-surface-call",
            ),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        await insert_event(
            store,
            call=Call(
                at=_SURFACE_AT,
                session_id="s1",
                client_kind=ClientKind.HOOK.value,
                op_id="s1-surface-call",
            ),
            kind=EventKind.SURFACE.value,
            memory_uuid="m1",
        )
        await insert_event(
            store,
            call=Call(
                at=_SURFACE_AT, session_id="s1", client_kind=ClientKind.MCP.value, op_id="s1-fetch"
            ),
            kind=EventKind.FETCH.value,
            memory_uuid="m1",
        )
        result = await amend_after_surface(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 0
        assert result.n_not_amended == 1


async def test_the_unit_is_the_pair_two_amends_in_one_session_still_count_as_one(
    tmp_path: Path,
) -> None:
    """Two amends on the surfaced memory in the same session must not inflate the numerator past
    the one opportunity that pair represents — the rate's whole point is *whether* the loop fires,
    not how often."""
    async with await _surfaced_session(tmp_path) as store:
        for i in range(2):
            await insert_event(
                store,
                call=Call(
                    at="2026-01-02T00:00:00.000000+00:00",
                    session_id="s1",
                    client_kind=ClientKind.MCP.value,
                    op_id=f"s1-amend-{i}",
                ),
                kind=EventKind.AMEND.value,
                memory_uuid="m1",
            )
        result = await amend_after_surface(
            store.connection, now="2026-01-03T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 1
        assert result.amend_after_surface_rate == 1.0


async def test_the_earliest_qualifying_amend_is_the_one_that_decides_the_deadline_test(
    tmp_path: Path,
) -> None:
    """The witness for "some qualifying amend landed within the deadline" must be the
    *earliest*-timestamped qualifying amend, not the latest: a fixture with one amend inside the
    deadline and a second, later amend past it must still classify as `amended` — the deadline
    test's whole job is to find *any* qualifying amend within the window, and a witness that picks
    the latest one instead would wrongly report `not_amended` here."""
    async with await _surfaced_session(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at="2026-01-10T00:00:00.000000+00:00",
                session_id="s1",
                client_kind=ClientKind.MCP.value,
                op_id="s1-amend-early",
            ),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        await insert_event(
            store,
            call=Call(
                at="2026-03-01T00:00:00.000000+00:00",
                session_id="s1",
                client_kind=ClientKind.MCP.value,
                op_id="s1-amend-late",
            ),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        result = await amend_after_surface(
            store.connection, now="2026-04-01T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 1
        assert result.n_not_amended == 0


async def test_the_same_memory_surfaced_in_two_linked_sessions_is_two_opportunities(
    tmp_path: Path,
) -> None:
    """The unit is `(session_id, memory_uuid)`, not the memory alone: surfacing `m1` in two linked
    sessions and amending it from only one gives one amended pair and one not-amended pair, never
    a rate of 200% and never collapsed into a single memory-level count."""
    store1 = await open_store(tmp_path)
    async with store1 as store:
        for session_id in ("s1", "s2"):
            await insert_event(
                store,
                call=Call(
                    at=_SURFACE_AT,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-surface-call",
                ),
                kind=EventKind.SURFACE_CALL.value,
                memory_uuid=None,
            )
            await insert_event(
                store,
                call=Call(
                    at=_SURFACE_AT,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-surface-call",
                ),
                kind=EventKind.SURFACE.value,
                memory_uuid="m1",
            )
            await insert_event(
                store,
                call=Call(
                    at=_SURFACE_AT,
                    session_id=session_id,
                    client_kind=ClientKind.MCP.value,
                    op_id=f"{session_id}-fetch",
                ),
                kind=EventKind.FETCH.value,
                memory_uuid="m1",
            )
        await insert_event(
            store,
            call=Call(
                at="2026-01-02T00:00:00.000000+00:00",
                session_id="s1",
                client_kind=ClientKind.MCP.value,
                op_id="s1-amend",
            ),
            kind=EventKind.AMEND.value,
            memory_uuid="m1",
        )
        result = await amend_after_surface(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 1
        assert result.n_not_amended == 1
        assert result.amend_after_surface_rate == 0.5


async def test_an_unlinked_surfacing_session_is_excluded_entirely(tmp_path: Path) -> None:
    """A `surface` row in a session with no `mcp` event at all must not enter the denominator —
    an unlinked session's amend, if it had one, could never be found by this join anyway, so
    counting the surfacing without the linkage would look like an unrepaired opportunity that was
    never really observable."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at=_SURFACE_AT,
                session_id="unlinked",
                client_kind=ClientKind.HOOK.value,
                op_id="unlinked-surface-call",
            ),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        await insert_event(
            store,
            call=Call(
                at=_SURFACE_AT,
                session_id="unlinked",
                client_kind=ClientKind.HOOK.value,
                op_id="unlinked-surface-call",
            ),
            kind=EventKind.SURFACE.value,
            memory_uuid="m1",
        )
        result = await amend_after_surface(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 0
        assert result.n_not_amended == 0
        assert result.n_pending == 0
        assert result.link.hook_sessions == 1
        assert result.link.linked_sessions == 0


async def test_rate_is_none_over_an_empty_store(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        result = await amend_after_surface(
            store.connection, now="2026-01-01T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.amend_after_surface_rate is None


async def test_amend_after_surface_rate_cannot_exceed_one(tmp_path: Path) -> None:
    """A fixture built exactly to catch the wrong-unit bug: three surfaced pairs, each amended
    multiple times and by concurrent-looking `op_id`s. A naive count of qualifying *amend calls*
    over *distinct pairs* would report more amends than pairs; the correct pair-deduped rate must
    land at exactly `1.0`."""
    store = await open_store(tmp_path)
    async with store:
        for session_id in ("s1", "s2", "s3"):
            await insert_event(
                store,
                call=Call(
                    at=_SURFACE_AT,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-surface-call",
                ),
                kind=EventKind.SURFACE_CALL.value,
                memory_uuid=None,
            )
            await insert_event(
                store,
                call=Call(
                    at=_SURFACE_AT,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-surface-call",
                ),
                kind=EventKind.SURFACE.value,
                memory_uuid="m1",
            )
            for i in range(3):
                await insert_event(
                    store,
                    call=Call(
                        at="2026-01-02T00:00:00.000000+00:00",
                        session_id=session_id,
                        client_kind=ClientKind.MCP.value,
                        op_id=f"{session_id}-amend-{i}",
                    ),
                    kind=EventKind.AMEND.value,
                    memory_uuid="m1",
                )
        result = await amend_after_surface(
            store.connection, now="2026-01-03T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 3
        assert result.amend_after_surface_rate == 1.0


async def test_determinism_amend_after_surface(tmp_path: Path) -> None:
    async with await _surfaced_session(tmp_path) as store:
        now = "2026-01-15T00:00:00.000000+00:00"
        first = await amend_after_surface(store.connection, now=now, signal_horizon_days=30)
        second = await amend_after_surface(store.connection, now=now, signal_horizon_days=30)
        assert first == second


def test_deadline_helper_reused_matches_horizon_module() -> None:
    """Sanity check that this test file's own understanding of the deadline matches
    `signals.horizon.deadline` exactly, so the fixtures above are dated against the real rule.

    `isoformat()` drops a zero microsecond field, which is why the expected string here has none
    either — this is checking agreement with the real function's output, not asserting a specific
    string format microseconds must always appear in."""
    assert deadline(_SURFACE_AT, signal_horizon_days=30) == "2026-01-31T00:00:00+00:00"


async def test_signal_horizon_days_travels_with_the_result(tmp_path: Path) -> None:
    """`schema.md` requires both cross-event signals to report the horizon they used alongside
    the rate, since the same counts under two horizons are two different estimands — the same
    property `dedup.DedupResolution` already carries."""
    async with await _surfaced_session(tmp_path) as store:
        result = await amend_after_surface(
            store.connection, now="2026-01-10T00:00:00.000000+00:00", signal_horizon_days=45
        )
        assert result.signal_horizon_days == 45


async def test_a_surface_row_with_no_memory_uuid_is_excluded_rather_than_crashing(
    tmp_path: Path,
) -> None:
    """`kind='surface'` always names a memory in a well-formed row (`EVENT_SPECS`'s own contract),
    so this signal's query filters `memory_uuid IS NOT NULL` defensively rather than assuming the
    contract held upstream. Built directly against a raw, deliberately malformed row — this test
    helper bypasses `EventSpec.validate` by design — so a null `memory_uuid` on a `surface`-kind
    row is exactly the case the filter exists for, and its absence would surface as a crash deep
    in `has_passed`'s own date parsing rather than as a wrong count."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(
                at=_SURFACE_AT, session_id="s1", client_kind=ClientKind.HOOK.value, op_id="op1"
            ),
            kind=EventKind.SURFACE.value,
            memory_uuid=None,
        )
        await insert_event(
            store,
            call=Call(
                at=_SURFACE_AT, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op2"
            ),
            kind=EventKind.FETCH.value,
            memory_uuid="m1",
        )
        result = await amend_after_surface(
            store.connection, now="2026-02-15T00:00:00.000000+00:00", signal_horizon_days=30
        )
        assert result.n_amended == 0
        assert result.n_not_amended == 0
        assert result.n_pending == 0
