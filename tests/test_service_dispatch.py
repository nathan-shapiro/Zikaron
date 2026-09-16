"""`zikaron.service.dispatch` — the five primary-agent verbs plus `health`, against a real store."""

import os
from pathlib import Path

import pytest

from tests.fake_encoder import FakeEncoder, unit_at
from tests.service_fixtures import envelope, open_context
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.indexing.chunking import PREFIX_SEPARATOR
from zikaron.service import dispatch
from zikaron.service.dispatch import ConflictResult, VersionResult


async def test_health_reports_store_identity(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        status = dispatch.health(ctx)
        assert status.ready is True
        assert status.store_path == str(ctx.store.path)
        assert status.store_id == ctx.store.meta.store_id
        assert status.embed_model == ctx.store.meta.embed_model
        assert status.embed_dim == ctx.store.meta.embed_dim
        assert status.schema_version == ctx.store.meta.schema_version
        assert status.pid == os.getpid()


async def test_health_json_shape_matches_architecture_mds_field_set(tmp_path: Path) -> None:
    """The exact key set `health()` returns — `architecture.md`'s
    `{ready, store_path, store_id, embed_model, embed_dim, schema_version, pid}` — with no
    `session_id`, since `health` resolves no label."""
    async with open_context(tmp_path) as ctx:
        status = dispatch.health(ctx)
        assert set(status.as_json()) == {
            "ready",
            "store_path",
            "store_id",
            "embed_model",
            "embed_dim",
            "schema_version",
            "pid",
        }


async def test_remember_returns_uuid_and_version_one(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        result = await dispatch.remember(
            ctx.store.connection,
            ctx,
            envelope(),
            {"gist": "a gist", "content": "some content"},
        )
        assert result.version == 1
        assert isinstance(result.uuid, str)
        assert result.near_duplicates == ()


async def test_remember_rejects_a_missing_gist(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        with pytest.raises(ZikaronError) as excinfo:
            await dispatch.remember(ctx.store.connection, ctx, envelope(), {"content": "c"})
        assert excinfo.value.code is ErrorCode.BOUNDS
        assert excinfo.value.data["field"] == "gist"


async def test_remember_offers_near_duplicates_above_the_threshold(tmp_path: Path) -> None:
    """The dedup search runs inside `remember`'s own transaction, exactly the shape
    `write.tools.remember` composes — this asserts the dispatch layer wires it through rather
    than re-testing the algorithm the write-path tests already cover.

    Vectors are planted at a 1-degree angle (cosine ~0.9998) rather than left to the encoder's
    ordinary text hash, so the pair clears `dedup_threshold` deterministically regardless of what
    two independent random hashes happen to score."""
    async with open_context(tmp_path, overrides="[dedup]\ndedup_threshold = 0.5\n") as ctx:
        assert isinstance(ctx.encoder, FakeEncoder)
        ctx.encoder.planned[f"first{PREFIX_SEPARATOR}first content"] = unit_at(0.0, ctx.encoder.dim)
        ctx.encoder.planned[f"second{PREFIX_SEPARATOR}second content"] = unit_at(
            1.0, ctx.encoder.dim
        )
        await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "first", "content": "first content"}
        )
        second = await dispatch.remember(
            ctx.store.connection,
            ctx,
            envelope(),
            {"gist": "second", "content": "second content"},
        )
        assert len(second.near_duplicates) >= 1
        near_duplicate_json = second.near_duplicates[0].as_json()
        assert set(near_duplicate_json) == {"uuid", "gist", "cosine", "rank"}


async def test_amend_returns_the_new_version(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        written = await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "g", "content": "c"}
        )
        result = await dispatch.amend(
            ctx.store.connection,
            ctx,
            envelope(),
            {"uuid": written.uuid, "version": 1, "gist": "g2", "content": "c2"},
        )
        assert isinstance(result, VersionResult)
        assert result.uuid == written.uuid
        assert result.version == 2


async def test_amend_on_a_stale_version_returns_a_conflict_shape(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        written = await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "g", "content": "c"}
        )
        result = await dispatch.amend(
            ctx.store.connection,
            ctx,
            envelope(),
            {"uuid": written.uuid, "version": 99, "gist": "g2", "content": "c2"},
        )
        assert isinstance(result, ConflictResult)
        assert result.current.record.uuid == written.uuid
        assert result.current.record.version == 1


async def test_amend_on_an_unknown_uuid_raises_not_found(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        with pytest.raises(ZikaronError) as excinfo:
            await dispatch.amend(
                ctx.store.connection,
                ctx,
                envelope(),
                {"uuid": "no-such-uuid", "version": 1, "gist": "g", "content": "c"},
            )
        assert excinfo.value.code is ErrorCode.NOT_FOUND


async def test_retire_without_superseded_by_retires_outright(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        written = await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "g", "content": "c"}
        )
        result = await dispatch.retire(
            ctx.store.connection, ctx, envelope(), {"uuid": written.uuid, "version": 1}
        )
        assert isinstance(result, VersionResult)
        assert result.uuid == written.uuid
        assert result.version == 2


async def test_retire_with_superseded_by_supersedes(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        replacement = await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "g1", "content": "c1"}
        )
        original = await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "g2", "content": "c2"}
        )
        result = await dispatch.retire(
            ctx.store.connection,
            ctx,
            envelope(),
            {
                "uuid": original.uuid,
                "version": 1,
                "superseded_by": replacement.uuid,
            },
        )
        assert isinstance(result, VersionResult)
        assert result.uuid == original.uuid
        assert result.version == 2


async def test_retire_on_a_stale_version_returns_a_conflict_shape(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        written = await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "g", "content": "c"}
        )
        result = await dispatch.retire(
            ctx.store.connection, ctx, envelope(), {"uuid": written.uuid, "version": 99}
        )
        assert isinstance(result, ConflictResult)


async def test_search_on_an_empty_store_returns_an_empty_list(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        result = await dispatch.search(ctx.store.connection, ctx, envelope(), {"query": "nothing"})
        assert result.hits == ()


async def test_search_finds_a_written_memory(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        written = await dispatch.remember(
            ctx.store.connection,
            ctx,
            envelope(),
            {"gist": "protobuf codegen fails", "content": "the staging cluster silently drops it"},
        )
        result = await dispatch.search(
            ctx.store.connection, ctx, envelope(), {"query": "protobuf codegen"}
        )
        assert any(hit.hit.uuid == written.uuid for hit in result.hits)


async def test_search_json_shape_matches_the_tool_surfaces_seven_fields(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        await dispatch.remember(
            ctx.store.connection,
            ctx,
            envelope(),
            {"gist": "protobuf codegen fails", "content": "the staging cluster silently drops it"},
        )
        result = await dispatch.search(
            ctx.store.connection, ctx, envelope(), {"query": "protobuf codegen"}
        )
        assert result.hits
        assert set(result.hits[0].as_json()) == {
            "uuid",
            "gist",
            "tier",
            "state",
            "created_at",
            "updated_at",
            "superseded_by",
        }


async def test_search_rejects_a_limit_outside_bounds(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        with pytest.raises(ZikaronError) as excinfo:
            await dispatch.search(ctx.store.connection, ctx, envelope(), {"query": "x", "limit": 0})
        assert excinfo.value.code is ErrorCode.BOUNDS


async def test_surface_on_an_empty_store_returns_empty_text(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        result = await dispatch.surface(ctx.store.connection, ctx, envelope(), {"prompt": "hi"})
        assert result.text == ""


async def test_surface_returns_a_rendered_block_for_a_matching_prompt(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        written = await dispatch.remember(
            ctx.store.connection,
            ctx,
            envelope(),
            {"gist": "protobuf codegen fails", "content": "the staging cluster silently drops it"},
        )
        result = await dispatch.surface(
            ctx.store.connection, ctx, envelope(), {"prompt": "protobuf codegen"}
        )
        assert written.uuid in result.text


async def test_fetch_returns_the_record_and_mints_a_receipt(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        written = await dispatch.remember(
            ctx.store.connection, ctx, envelope(), {"gist": "g", "content": "c"}
        )
        result = await dispatch.fetch(
            ctx.store.connection, ctx, envelope(), {"uuids": [written.uuid]}
        )
        assert len(result.records) == 1
        assert result.records[0].record.uuid == written.uuid
        assert result.records[0].record.content == "c"
        assert result.missing == ()


async def test_fetch_reports_an_unknown_uuid_as_missing_rather_than_failing(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        result = await dispatch.fetch(
            ctx.store.connection, ctx, envelope(), {"uuids": ["no-such-uuid"]}
        )
        assert result.records == ()
        assert result.missing == ("no-such-uuid",)


async def test_fetch_rejects_a_non_list_uuids_field(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        with pytest.raises(ZikaronError):
            await dispatch.fetch(ctx.store.connection, ctx, envelope(), {"uuids": "not-a-list"})
