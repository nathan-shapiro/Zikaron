"""`zikaron.core.records.supersession` — `validate_new_edge` and `resolve_latest` against a bare
`memory` table, with no receipt or authorization machinery in the loop.
"""

from pathlib import Path

import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records import supersession
from zikaron.core.records.supersession import BadSupersessionReason, RootState
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store

_MAX_DEPTH = 32


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


async def _open_store(tmp_path: Path) -> Store:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    embedder = FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)
    return await Store.create(store_dir, config, embedder)


async def _insert_memory(
    store: Store, uuid: str, *, active: int = 1, superseded_by: str | None = None
) -> None:
    now = "2026-08-01T00:00:00+00:00"
    await store.connection.execute(
        "INSERT INTO memory "
        "(uuid, tier, gist, content, active, superseded_by, version, created_at, updated_at, "
        " session_id, token_count) "
        "VALUES (?, 'journal', 'g', 'c', ?, ?, 1, ?, ?, 's1', 0)",
        (uuid, active, superseded_by, now, now),
    )
    await store.connection.commit()


async def test_validate_new_edge_accepts_a_live_target(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "a")
        await _insert_memory(store, "b")
        await supersession.validate_new_edge(
            store.connection, from_uuid="a", to_uuid="b", max_depth=_MAX_DEPTH
        )  # must not raise


async def test_validate_new_edge_rejects_a_self_edge(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "a")
        with pytest.raises(ZikaronError) as excinfo:
            await supersession.validate_new_edge(
                store.connection, from_uuid="a", to_uuid="a", max_depth=_MAX_DEPTH
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == BadSupersessionReason.SELF_EDGE


async def test_validate_new_edge_rejects_an_unknown_target(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "a")
        with pytest.raises(ZikaronError) as excinfo:
            await supersession.validate_new_edge(
                store.connection, from_uuid="a", to_uuid="ghost", max_depth=_MAX_DEPTH
            )
        assert excinfo.value.code is ErrorCode.NOT_FOUND
        assert excinfo.value.data["uuid"] == "ghost"


async def test_validate_new_edge_accepts_a_superseded_but_not_outright_retired_target(
    tmp_path: Path,
) -> None:
    """A replacement may itself be superseded — that is how A -> B -> C arises."""
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "root")
        await _insert_memory(store, "middle", active=0, superseded_by="root")
        await _insert_memory(store, "leaf")
        await supersession.validate_new_edge(
            store.connection, from_uuid="leaf", to_uuid="middle", max_depth=_MAX_DEPTH
        )  # must not raise


async def test_validate_new_edge_rejects_a_retired_outright_target(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "dead", active=0, superseded_by=None)
        await _insert_memory(store, "a")
        with pytest.raises(ZikaronError) as excinfo:
            await supersession.validate_new_edge(
                store.connection, from_uuid="a", to_uuid="dead", max_depth=_MAX_DEPTH
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == BadSupersessionReason.TARGET_RETIRED_OUTRIGHT


async def test_validate_new_edge_rejects_a_two_hop_cycle(tmp_path: Path) -> None:
    """a -> b already exists; writing b -> a would close a cycle."""
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "b")
        await _insert_memory(store, "a", active=0, superseded_by="b")
        with pytest.raises(ZikaronError) as excinfo:
            await supersession.validate_new_edge(
                store.connection, from_uuid="b", to_uuid="a", max_depth=_MAX_DEPTH
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == BadSupersessionReason.CYCLE


async def test_validate_new_edge_rejects_a_longer_cycle(tmp_path: Path) -> None:
    """a -> b -> c already exists; writing c -> a would close a three-hop cycle."""
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "c")
        await _insert_memory(store, "b", active=0, superseded_by="c")
        await _insert_memory(store, "a", active=0, superseded_by="b")
        with pytest.raises(ZikaronError) as excinfo:
            await supersession.validate_new_edge(
                store.connection, from_uuid="c", to_uuid="a", max_depth=_MAX_DEPTH
            )
        assert excinfo.value.data["reason"] == BadSupersessionReason.CYCLE


async def test_validate_new_edge_walk_exhausting_max_depth_raises_depth_cap_hit(
    tmp_path: Path,
) -> None:
    """A chain deeper than `max_depth` must fail closed rather than hang, on a genuinely acyclic
    graph — proving the cap fires on depth alone, not only on an actual cycle."""
    async with await _open_store(tmp_path) as store:
        # A chain of 5 supersession edges: n4 -> n3 -> n2 -> n1 -> n0 (n0 is the live root).
        await _insert_memory(store, "n0")
        await _insert_memory(store, "n1", active=0, superseded_by="n0")
        await _insert_memory(store, "n2", active=0, superseded_by="n1")
        await _insert_memory(store, "n3", active=0, superseded_by="n2")
        await _insert_memory(store, "n4", active=0, superseded_by="n3")
        await _insert_memory(store, "probe")
        with pytest.raises(ZikaronError) as excinfo:
            await supersession.validate_new_edge(
                store.connection, from_uuid="probe", to_uuid="n4", max_depth=3
            )
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == BadSupersessionReason.DEPTH_CAP_HIT


async def test_resolve_latest_returns_none_for_a_root_row(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "root")
        result = await supersession.resolve_latest(
            store.connection, start_uuid="root", max_depth=_MAX_DEPTH
        )
        assert result is None


async def test_resolve_latest_walks_a_chain_to_its_live_root(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "root")
        await _insert_memory(store, "middle", active=0, superseded_by="root")
        await _insert_memory(store, "leaf", active=0, superseded_by="middle")
        result = await supersession.resolve_latest(
            store.connection, start_uuid="leaf", max_depth=_MAX_DEPTH
        )
        assert result is not None
        assert result.uuid == "root"
        assert result.state == RootState.LIVE


async def test_resolve_latest_reports_a_terminal_root_as_retired(tmp_path: Path) -> None:
    """A root that is itself `active=0 AND superseded_by IS NULL` is a terminal component —
    invariant 6's "a root is live or terminal, and both are legal"."""
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "root", active=0, superseded_by=None)
        await _insert_memory(store, "leaf", active=0, superseded_by="root")
        result = await supersession.resolve_latest(
            store.connection, start_uuid="leaf", max_depth=_MAX_DEPTH
        )
        assert result is not None
        assert result.uuid == "root"
        assert result.state == RootState.RETIRED


async def test_resolve_latest_one_hop_resolves_to_the_immediate_target(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "root")
        await _insert_memory(store, "leaf", active=0, superseded_by="root")
        result = await supersession.resolve_latest(
            store.connection, start_uuid="leaf", max_depth=_MAX_DEPTH
        )
        assert result is not None
        assert result.uuid == "root"


async def test_resolve_latest_raises_on_a_walk_exhausting_max_depth(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "n0")
        await _insert_memory(store, "n1", active=0, superseded_by="n0")
        await _insert_memory(store, "n2", active=0, superseded_by="n1")
        await _insert_memory(store, "n3", active=0, superseded_by="n2")
        with pytest.raises(ZikaronError) as excinfo:
            await supersession.resolve_latest(store.connection, start_uuid="n3", max_depth=1)
        assert excinfo.value.code is ErrorCode.BAD_SUPERSESSION
        assert excinfo.value.data["reason"] == BadSupersessionReason.DEPTH_CAP_HIT


def test_bad_supersession_reason_has_exactly_the_designs_five_cases() -> None:
    """`architecture.md` §Errors states the case list as prose: "self-edge, cycle, target
    retired-outright, edge already set, or depth cap hit" — five, not four."""
    assert len(BadSupersessionReason) == 5
