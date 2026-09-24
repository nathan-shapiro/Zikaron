"""`zikaron.service.dispatch_knowledge` — the one RPC method that answers from a corpus of files.

What is checked here is the translation: raw parameters in, the wire object out, and the
malformed-request rejections that belong to a boundary. The retrieval itself is tested against
`zikaron.core.knowledge`'s own modules, where it does not have to travel through a dispatch table
first.
"""

from pathlib import Path

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import add_request, build_settings, write_tree
from tests.service_fixtures import envelope, open_context
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import lifecycle
from zikaron.core.knowledge.meta import GitMode
from zikaron.service import dispatch_knowledge
from zikaron.service.context import ServiceContext
from zikaron.service.params import Handler
from zikaron.service.serialize import RpcResult


async def _with_corpus(ctx: ServiceContext, tmp_path: Path, name: str = "docs") -> None:
    """Register and build one corpus against this context's own store."""
    root = write_tree(tmp_path / name, {"a.md": b"the protobuf step fails silently\n"})
    request = add_request(root, name=name, git_mode=GitMode.OFF)
    await lifecycle.add(ctx.store_directory, ctx.store.connection, ctx.config, request)
    await lifecycle.refresh(
        ctx.store_directory,
        ctx.store.connection,
        ctx.config,
        name=name,
        build=build_settings(ctx.config, encoder=FakeEncoder()),
    )


async def _search(ctx: ServiceContext, params: dict[str, object]) -> dict[str, object]:
    result = await dispatch_knowledge.knowledge_search(
        ctx.store.connection, ctx, envelope(), params
    )
    payload = result.as_json()
    assert isinstance(payload, dict)
    return payload


async def test_a_search_answers_with_groups_and_the_dropped_flag(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        await _with_corpus(ctx, tmp_path)
        payload = await _search(ctx, {"query": "protobuf"})
        assert set(payload) == {"groups", "groups_dropped", "known_knowledge_bases"}
        assert payload["groups_dropped"] is False
        groups = payload["groups"]
        assert isinstance(groups, list)
        (group,) = groups
        assert isinstance(group, dict)
        assert group["knowledge_base"] == "docs"
        assert group["state"] == "ok"
        (result,) = group["results"]
        assert set(result) == {
            "path",
            "start_line",
            "end_line",
            "snippet",
            "truncated",
            "score",
            "stale",
        }
        assert result["path"] == "a.md"


async def test_a_store_with_no_corpora_answers_with_an_empty_group_list(tmp_path: Path) -> None:
    """The registry is created on first use, so this also covers a store that predates it: the
    method answers rather than failing on a table that is not there yet."""
    async with open_context(tmp_path) as ctx:
        assert await _search(ctx, {"query": "anything"}) == {
            "groups": [],
            "groups_dropped": False,
            "known_knowledge_bases": [],
        }


async def test_naming_a_corpus_restricts_the_search_to_it(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        await _with_corpus(ctx, tmp_path, name="docs")
        await _with_corpus(ctx, tmp_path, name="runbooks")
        payload = await _search(ctx, {"query": "protobuf", "knowledge_bases": ["runbooks"]})
        groups = payload["groups"]
        assert isinstance(groups, list)
        assert [group["knowledge_base"] for group in groups] == ["runbooks"]


async def test_an_unknown_name_is_reported_in_its_own_group(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        await _with_corpus(ctx, tmp_path)
        payload = await _search(ctx, {"query": "protobuf", "knowledge_bases": ["dcos", "docs"]})
        groups = payload["groups"]
        assert isinstance(groups, list)
        errors = [group for group in groups if "error" in group]
        assert [group["error"] for group in errors] == ["unknown_knowledge_base"]
        assert {group["knowledge_base"] for group in groups} == {"dcos", "docs"}


async def test_the_limit_defaults_without_the_caller_naming_it(tmp_path: Path) -> None:
    """A direct RPC caller never passes through the tool signature that carries the default, so
    the method has to state one itself."""
    async with open_context(tmp_path) as ctx:
        root = write_tree(tmp_path / "docs", {f"f{index}.md": b"protobuf\n" for index in range(9)})
        await lifecycle.add(
            ctx.store_directory,
            ctx.store.connection,
            ctx.config,
            add_request(root, name="docs", git_mode=GitMode.OFF),
        )
        await lifecycle.refresh(
            ctx.store_directory,
            ctx.store.connection,
            ctx.config,
            name="docs",
            build=build_settings(ctx.config, encoder=FakeEncoder()),
        )
        payload = await _search(ctx, {"query": "protobuf"})
        groups = payload["groups"]
        assert isinstance(groups, list)
        assert len(groups[0]["results"]) == dispatch_knowledge.DEFAULT_LIMIT_PER_KB


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({}, "query"),
        ({"query": 7}, "query"),
        ({"query": "x", "limit_per_kb": "many"}, "limit_per_kb"),
        ({"query": "x", "knowledge_bases": "docs"}, "knowledge_bases"),
        ({"query": "x", "knowledge_bases": [1, 2]}, "knowledge_bases"),
    ],
    ids=[
        "missing query",
        "query not a string",
        "limit not an int",
        "names not a list",
        "names not strings",
    ],
)
async def test_a_malformed_request_is_refused_by_field(
    tmp_path: Path, params: dict[str, object], field: str
) -> None:
    async with open_context(tmp_path) as ctx:
        with pytest.raises(ZikaronError) as excinfo:
            await _search(ctx, params)
        assert excinfo.value.code is ErrorCode.BOUNDS
        assert excinfo.value.data["field"] == field


async def test_an_explicit_null_name_list_means_every_corpus(tmp_path: Path) -> None:
    """Absence and emptiness are different requests, and JSON's `null` is absence."""
    async with open_context(tmp_path) as ctx:
        await _with_corpus(ctx, tmp_path)
        payload = await _search(ctx, {"query": "protobuf", "knowledge_bases": None})
        groups = payload["groups"]
        assert isinstance(groups, list)
        assert [group["knowledge_base"] for group in groups] == ["docs"]


async def test_an_empty_name_list_asks_for_nothing_and_is_given_nothing(tmp_path: Path) -> None:
    async with open_context(tmp_path) as ctx:
        await _with_corpus(ctx, tmp_path)
        payload = await _search(ctx, {"query": "protobuf", "knowledge_bases": []})
        assert payload["groups"] == []


# ---------------------------------------------------------------------------
# A driver or OS failure reaches the caller with its reason, not as `internal_error`.
# ---------------------------------------------------------------------------


def _stub(error: BaseException) -> Handler:
    """A handler that only fails, standing in for whichever real one meets a bad disk."""

    async def handler(*_: object) -> RpcResult:
        raise error

    return handler


@pytest.mark.parametrize(
    "failure",
    [
        aiosqlite.OperationalError("attempt to write a readonly database"),
        aiosqlite.DatabaseError("database disk image is malformed"),
        OSError(28, "No space left on device"),
    ],
)
async def test_a_driver_or_os_failure_becomes_store_unavailable(
    tmp_path: Path, failure: BaseException
) -> None:
    wrapped = dispatch_knowledge._naming_the_store("knowledge_list", _stub(failure))
    async with open_context(tmp_path) as ctx:
        with pytest.raises(ZikaronError) as excinfo:
            await wrapped(ctx.store.connection, ctx, envelope(), {})
    assert excinfo.value.code is ErrorCode.STORE_UNAVAILABLE
    assert excinfo.value.data["operation"] == "knowledge_list"
    assert str(failure) in str(excinfo.value.data["cause"])


async def test_the_unwrapped_handler_lets_the_driver_failure_escape(tmp_path: Path) -> None:
    """The mutation behind the test above: without the wrapper the same call raises the driver's
    own exception, which `server.py` answers as `internal_error` with an empty payload."""
    failure = aiosqlite.OperationalError("disk I/O error")
    async with open_context(tmp_path) as ctx:
        with pytest.raises(aiosqlite.OperationalError):
            await _stub(failure)(ctx.store.connection, ctx, envelope(), {})


async def test_a_refusal_passes_through_the_wrapper_unchanged(tmp_path: Path) -> None:
    """The wrapper must not swallow a code a handler chose deliberately."""
    refusal = ZikaronError(ErrorCode.KNOWLEDGE_BASE_UNKNOWN, name="docs")
    wrapped = dispatch_knowledge._naming_the_store("knowledge_status", _stub(refusal))
    async with open_context(tmp_path) as ctx:
        with pytest.raises(ZikaronError) as excinfo:
            await wrapped(ctx.store.connection, ctx, envelope(), {})
    assert excinfo.value.code is ErrorCode.KNOWLEDGE_BASE_UNKNOWN


def test_every_method_in_the_table_is_wrapped() -> None:
    """A method added to the table without the wrapper answers `internal_error` for every driver
    failure it meets, which is invisible until someone's disk fills."""
    bare = {
        name: getattr(dispatch_knowledge, name)
        for name in dir(dispatch_knowledge)
        if name.startswith("knowledge_")
    }
    assert set(bare) == set(dispatch_knowledge.KNOWLEDGE_METHODS)
    unwrapped = [
        name
        for name, handler in dispatch_knowledge.KNOWLEDGE_METHODS.items()
        if handler is bare[name]
    ]
    assert unwrapped == []


async def test_a_store_that_cannot_be_written_reaches_the_caller_as_store_unavailable(
    tmp_path: Path,
) -> None:
    """End to end through the table, rather than over a stub: a real driver failure on a real
    method, with the driver's own words in the payload.

    `query_only` stands in for a revoked permission or a read-only mount. It is refused with
    `SQLITE_READONLY`, which `transactions.is_contention` does not classify as a lock, so it
    travels out as the driver's exception exactly as those would.
    """
    async with open_context(tmp_path) as ctx:
        root = write_tree(tmp_path / "docs", {"a.md": b"x\n"})
        await ctx.store.connection.execute("PRAGMA query_only = ON")
        with pytest.raises(ZikaronError) as excinfo:
            await dispatch_knowledge.KNOWLEDGE_METHODS["knowledge_add"](
                ctx.store.connection,
                ctx,
                envelope(),
                {"name": "docs", "path": str(root), "description": "a"},
            )
        await ctx.store.connection.execute("PRAGMA query_only = OFF")
    assert excinfo.value.code is ErrorCode.STORE_UNAVAILABLE
    assert excinfo.value.data["operation"] == "knowledge_add"
    assert "readonly" in str(excinfo.value.data["cause"])
