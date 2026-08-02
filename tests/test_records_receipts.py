"""`zikaron.core.records.receipts` — the mint/spend/revoke mechanics in isolation, against a bare
`read_receipt` table (no `memory.py` verb in the loop), plus `require_all`'s payload assembly.
"""

from pathlib import Path

import pytest

from zikaron.core.config.resolution import EffectiveConfig, resolve
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records import receipts
from zikaron.core.records.receipts import ReceiptKey, ReceiptSource
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store


def _config(tmp_path: Path) -> EffectiveConfig:
    return resolve(tmp_path / "system.toml", tmp_path / "project.toml")


async def _open_store(tmp_path: Path) -> Store:
    store_dir = tmp_path / ".zikaron"
    config = _config(tmp_path)
    embedder = FakeEmbedder(model_name="BAAI/bge-small-en-v1.5", dim=384)
    return await Store.create(store_dir, config, embedder)


async def _insert_memory(store: Store, uuid: str) -> None:
    """A minimal `memory` row for `read_receipt`'s foreign key to point at — this module tests
    receipt mechanics, not `memory.py`'s verbs, so the row is inserted directly."""
    now = "2026-08-01T00:00:00+00:00"
    await store.connection.execute(
        "INSERT INTO memory "
        "(uuid, tier, gist, content, active, superseded_by, version, created_at, updated_at, "
        " session_id, token_count) "
        "VALUES (?, 'journal', 'g', 'c', 1, NULL, 1, ?, ?, 's1', 0)",
        (uuid, now, now),
    )
    await store.connection.commit()


def _key(
    session_id: str = "s1", client_kind: str = "mcp", memory_uuid: str = "m1", version: int = 1
) -> ReceiptKey:
    return ReceiptKey(
        session_id=session_id, client_kind=client_kind, memory_uuid=memory_uuid, version=version
    )


async def test_mint_then_spend_finds_the_receipt(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "m1")
        key = _key()
        await receipts.mint(store.connection, key=key, at="t0", source=ReceiptSource.FETCH)
        await store.connection.commit()
        assert await receipts.spend(store.connection, key=key) is True


async def test_spend_with_no_matching_receipt_returns_false(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "m1")
        assert await receipts.spend(store.connection, key=_key()) is False


async def test_spend_does_not_consume_the_receipt(tmp_path: Path) -> None:
    """Named `spend` for what the caller's own version bump does next, not for a deletion this
    function itself performs — checking twice must find the same receipt both times."""
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "m1")
        key = _key()
        await receipts.mint(store.connection, key=key, at="t0", source=ReceiptSource.FETCH)
        await store.connection.commit()
        assert await receipts.spend(store.connection, key=key) is True
        assert await receipts.spend(store.connection, key=key) is True


async def test_mint_is_an_idempotent_upsert_refreshing_at_and_source(tmp_path: Path) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "m1")
        key = _key()
        await receipts.mint(store.connection, key=key, at="t0", source=ReceiptSource.FETCH)
        await receipts.mint(store.connection, key=key, at="t1", source=ReceiptSource.GROUP)
        await store.connection.commit()
        rows = await store.connection.execute_fetchall(
            "SELECT at, source FROM read_receipt WHERE memory_uuid = ?", ("m1",)
        )
        assert list(rows) == [("t1", "group")]


async def test_mint_does_not_violate_the_primary_key_on_a_repeat_call(tmp_path: Path) -> None:
    """A plain `INSERT` would raise `IntegrityError` on the second call; the upsert must not."""
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "m1")
        key = _key()
        for _ in range(3):
            await receipts.mint(store.connection, key=key, at="t", source=ReceiptSource.FETCH)
        await store.connection.commit()
        rows = await store.connection.execute_fetchall(
            "SELECT COUNT(*) FROM read_receipt WHERE memory_uuid = ?", ("m1",)
        )
        assert int(next(iter(rows))[0]) == 1


async def test_revoke_on_version_bump_deletes_every_other_receipt_for_the_uuid(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "m1")
        await receipts.mint(
            store.connection,
            key=_key(session_id="a", version=1),
            at="t",
            source=ReceiptSource.FETCH,
        )
        await receipts.mint(
            store.connection,
            key=_key(session_id="b", version=1),
            at="t",
            source=ReceiptSource.FETCH,
        )
        writer_key = _key(session_id="writer", version=2)
        await receipts.mint(
            store.connection, key=writer_key, at="t", source=ReceiptSource.OWN_WRITE
        )
        await receipts.revoke_on_version_bump(store.connection, keep=writer_key)
        await store.connection.commit()
        rows = await store.connection.execute_fetchall(
            "SELECT session_id, version FROM read_receipt WHERE memory_uuid = ?", ("m1",)
        )
        assert list(rows) == [("writer", 2)]


async def test_revoke_on_version_bump_does_not_touch_receipts_for_a_different_uuid(
    tmp_path: Path,
) -> None:
    async with await _open_store(tmp_path) as store:
        await _insert_memory(store, "m1")
        await _insert_memory(store, "m2")
        await receipts.mint(
            store.connection,
            key=_key(memory_uuid="m2", version=1),
            at="t",
            source=ReceiptSource.FETCH,
        )
        writer_key = _key(memory_uuid="m1", session_id="writer", version=2)
        await receipts.mint(
            store.connection, key=writer_key, at="t", source=ReceiptSource.OWN_WRITE
        )
        await receipts.revoke_on_version_bump(store.connection, keep=writer_key)
        await store.connection.commit()
        rows = await store.connection.execute_fetchall(
            "SELECT memory_uuid FROM read_receipt ORDER BY memory_uuid"
        )
        assert [str(r[0]) for r in rows] == ["m1", "m2"]


def test_require_all_passes_when_every_uuid_holds_a_receipt() -> None:
    receipts.require_all(["a", "b"], uuids=["a", "b"])  # must not raise


def test_require_all_names_every_missing_uuid_in_one_call() -> None:
    with pytest.raises(ZikaronError) as excinfo:
        receipts.require_all(["a"], uuids=["a", "b", "c"])
    assert excinfo.value.code is ErrorCode.NO_READ_RECEIPT
    assert excinfo.value.data["uuids"] == ["b", "c"]
    assert excinfo.value.data["hint"] == "fetch it first"


def test_receipt_sources_match_the_ddl_check_constraints_own_four_values() -> None:
    assert receipts.RECEIPT_SOURCES == (
        ReceiptSource.FETCH,
        ReceiptSource.GROUP,
        ReceiptSource.CONFLICT,
        ReceiptSource.OWN_WRITE,
    )
