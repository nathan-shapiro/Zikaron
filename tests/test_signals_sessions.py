"""`signals.sessions` — linked-session scope and link coverage."""

from pathlib import Path

import pytest

from tests.signals_fixtures import T0, Call, insert_event, open_store
from zikaron.core.events import ClientKind, EventKind
from zikaron.core.signals.sessions import LinkCoverage, link_coverage, linked_session_ids


async def test_a_session_with_only_hook_events_is_not_linked(tmp_path: Path) -> None:
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.HOOK.value, op_id="op1"),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        assert await linked_session_ids(store.connection) == frozenset()


async def test_a_session_with_only_mcp_events_is_not_linked(tmp_path: Path) -> None:
    """Linkage requires **both** clients — an mcp-only session is exactly as unlinked as a
    hook-only one, and it is also outside the hook-session denominator `link_coverage`
    divides by."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="op1"),
            kind=EventKind.REMEMBER.value,
            memory_uuid="m1",
        )
        assert await linked_session_ids(store.connection) == frozenset()


async def test_a_session_with_both_client_kinds_is_linked(tmp_path: Path) -> None:
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
            kind=EventKind.REMEMBER.value,
            memory_uuid="m1",
        )
        assert await linked_session_ids(store.connection) == frozenset({"s1"})


async def test_a_consolidator_event_does_not_link_a_session(tmp_path: Path) -> None:
    """`ClientKind.CONSOLIDATOR` is neither `hook` nor `mcp` — a session with a hook event and a
    consolidator event only is exactly as unlinked as one with only a hook event, since linkage is
    defined over the two clients D30's cross-client signals actually join, not over "any second
    client kind"."""
    async with await open_store(tmp_path) as store:
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.HOOK.value, op_id="op1"),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        await insert_event(
            store,
            call=Call(
                at=T0, session_id="s1", client_kind=ClientKind.CONSOLIDATOR.value, op_id="op2"
            ),
            kind=EventKind.MERGE.value,
            memory_uuid="m1",
        )
        assert await linked_session_ids(store.connection) == frozenset()


async def test_link_coverage_is_none_when_no_session_ever_had_a_hook_event(tmp_path: Path) -> None:
    """A fraction with no denominator is not zero coverage — it is a store the hook side never
    touched, and the two must not be plotted as though they meant the same thing."""
    async with await open_store(tmp_path) as store:
        coverage = await link_coverage(store.connection)
        assert coverage.hook_sessions == 0
        assert coverage.coverage is None


async def test_link_coverage_is_exactly_one_when_every_hook_session_is_linked(
    tmp_path: Path,
) -> None:
    async with await open_store(tmp_path) as store:
        for session_id in ("s1", "s2"):
            await insert_event(
                store,
                call=Call(
                    at=T0,
                    session_id=session_id,
                    client_kind=ClientKind.HOOK.value,
                    op_id=f"{session_id}-op1",
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
                    op_id=f"{session_id}-op2",
                ),
                kind=EventKind.REMEMBER.value,
                memory_uuid="m1",
            )
        coverage = await link_coverage(store.connection)
        assert coverage.hook_sessions == 2
        assert coverage.linked_sessions == 2
        assert coverage.coverage == 1.0


async def test_link_coverage_is_a_proper_fraction_with_one_unlinked_hook_session(
    tmp_path: Path,
) -> None:
    async with await open_store(tmp_path) as store:
        # s1: hook + mcp, linked. s2: hook only, unlinked.
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.HOOK.value, op_id="s1-op1"),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s1", client_kind=ClientKind.MCP.value, op_id="s1-op2"),
            kind=EventKind.REMEMBER.value,
            memory_uuid="m1",
        )
        await insert_event(
            store,
            call=Call(at=T0, session_id="s2", client_kind=ClientKind.HOOK.value, op_id="s2-op1"),
            kind=EventKind.SURFACE_CALL.value,
            memory_uuid=None,
        )
        coverage = await link_coverage(store.connection)
        assert coverage.hook_sessions == 2
        assert coverage.linked_sessions == 1
        assert coverage.coverage == 0.5


def test_link_coverage_refuses_more_linked_sessions_than_hook_sessions() -> None:
    """Invariant test: linked is defined as a subset of hook-sessions, so a `LinkCoverage`
    claiming otherwise is a defect in whoever constructed it, caught at construction rather than
    allowed to report a coverage fraction above 1."""
    with pytest.raises(ValueError, match="linked_sessions"):
        LinkCoverage(linked_sessions=3, hook_sessions=2)
