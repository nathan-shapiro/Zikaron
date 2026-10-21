"""`knowledge_remind` and its throttle (`design/code-knowledge.md` §6).

Driven through the dispatcher, so what is checked includes what runs around the handler: the
receipt `memory_surface` notes before its deadline is read, the caller's deadline, the `bounds`
rejections and the `call` row.
"""

import asyncio
import dataclasses
import json
import time
from pathlib import Path
from typing import Final, cast

import pytest

from tests.contention_fixtures import call, error_of
from tests.knowledge_fixtures import add_request
from tests.service_fixtures import open_context
from zikaron.core.errors import ErrorCode
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.knowledge import lifecycle
from zikaron.core.knowledge.meta import GitMode
from zikaron.service.context import ServiceContext
from zikaron.service.params import PATHS_MAX
from zikaron.service.reminders import ReminderTimes

_REMIND: Final = "knowledge_remind"
_MODULE: Final = "code-knowledge/src/mod"
_DEADLINE_PASSED: Final = int(ErrorCode.DEADLINE_PASSED)
_BOUNDS: Final = int(ErrorCode.BOUNDS)


async def _register(ctx: ServiceContext, tmp_path: Path, name: str) -> None:
    """Register a corpus by name; the reminder reads the registry alone, so nothing is built."""
    root = tmp_path / "corpora" / name.replace("/", "_")
    root.mkdir(parents=True)
    request = add_request(root, name=name, git_mode=GitMode.OFF)
    await lifecycle.add(ctx.store_directory, ctx.store.connection, ctx.config, request)


async def _remind(
    ctx: ServiceContext, *paths: str, agent_id: str | None = None, **params: object
) -> dict[str, object]:
    sent: dict[str, object] = {"paths": list(paths), **params}
    if agent_id is not None:
        sent["agent_id"] = agent_id
    return await call(ctx, _REMIND, sent, kind="hook")


def _text(response: dict[str, object]) -> str | None:
    result = response.get("result")
    assert isinstance(result, dict), response
    text = result["text"]
    assert text is None or isinstance(text, str)
    return text


async def _surface(ctx: ServiceContext, **params: object) -> dict[str, object]:
    return await call(ctx, "memory_surface", {"prompt": "anything", **params}, kind="hook")


def _deadline_in(seconds: float) -> int:
    return int((time.time() + seconds) * 1000)


class _UnusableEncoder:
    """An encoder whose every use fails, standing for one still loading."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the encoder was used: {name}")


class TestTheAnswer:
    async def test_a_search_of_a_documented_module_is_answered_with_the_line(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            text = _text(await _remind(ctx, str(tmp_path / "src/mod/a.rs")))
            assert text is not None
            assert _MODULE in text

    async def test_a_search_reaching_no_module_is_answered_with_null(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            assert _text(await _remind(ctx, str(tmp_path / "src/other"))) is None

    async def test_a_store_with_no_registry_is_answered_with_null(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            assert _text(await _remind(ctx, str(tmp_path))) is None

    async def test_a_hand_written_corpus_is_no_reason_to_remind(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, "docs")
            assert _text(await _remind(ctx, str(tmp_path))) is None

    async def test_it_answers_without_touching_the_encoder(self, tmp_path: Path) -> None:
        """So it answers while the embedding model is still loading."""
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            loading = dataclasses.replace(ctx, encoder=cast(Encoder, _UnusableEncoder()))
            assert _text(await _remind(loading, str(tmp_path))) is not None

    async def test_it_is_recorded_by_a_call_row(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _remind(ctx, str(tmp_path))
            rows = await (await ctx.store.writer()).execute_fetchall(
                "SELECT detail FROM event WHERE kind = 'call' ORDER BY id"
            )
            methods = [json.loads(detail)["method"] for (detail,) in rows]
            assert methods == [_REMIND]


class TestValidation:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"paths": []},
            {"paths": "/a"},
            {"paths": ["relative/path"]},
            {"paths": [1]},
            {"paths": [f"/p{n}" for n in range(PATHS_MAX + 1)]},
            {"paths": ["/a"], "agent_id": 7},
            {"paths": ["/a"], "deadline_at_ms": "soon"},
        ],
        ids=[
            "absent",
            "empty",
            "not a list",
            "relative",
            "not a string",
            "past the bound",
            "agent id not a string",
            "deadline not an integer",
        ],
    )
    async def test_a_malformed_request_is_refused_bounds(
        self, tmp_path: Path, params: dict[str, object]
    ) -> None:
        async with open_context(tmp_path) as ctx:
            refused = error_of(await call(ctx, _REMIND, params, kind="hook"))
            assert refused is not None
            assert refused[0] == _BOUNDS

    async def test_the_bound_itself_is_accepted(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            paths = [f"/p{n}" for n in range(PATHS_MAX)]
            assert error_of(await _remind(ctx, *paths)) is None


class TestTheThrottle:
    async def test_the_first_search_of_a_turn_reminds_and_a_second_within_the_interval_does_not(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            assert _text(await _remind(ctx, str(tmp_path))) is not None
            assert _text(await _remind(ctx, str(tmp_path))) is None

    async def test_a_user_prompt_opens_a_new_turn(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await _remind(ctx, str(tmp_path))
            await _surface(ctx)
            assert _text(await _remind(ctx, str(tmp_path))) is not None

    @pytest.mark.parametrize(
        ("deadline_at_ms", "code"),
        [(_deadline_in(-1), _DEADLINE_PASSED), ("soon", _BOUNDS)],
        ids=["past its deadline", "refused before its handler runs"],
    )
    async def test_a_refused_push_opens_the_turn_all_the_same(
        self, tmp_path: Path, deadline_at_ms: object, code: int
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await _remind(ctx, str(tmp_path))
            refused = error_of(await _surface(ctx, deadline_at_ms=deadline_at_ms))
            assert refused is not None
            assert refused[0] == code
            assert _text(await _remind(ctx, str(tmp_path))) is not None

    async def test_a_search_reaching_no_module_moves_no_time(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await _remind(ctx, str(tmp_path / "elsewhere"))
            assert _text(await _remind(ctx, str(tmp_path))) is not None

    async def test_an_interval_of_zero_reminds_on_every_such_search(self, tmp_path: Path) -> None:
        async with open_context(tmp_path, "[retrieval]\nknowledge_reminder_interval = 0\n") as ctx:
            await _register(ctx, tmp_path, _MODULE)
            assert _text(await _remind(ctx, str(tmp_path))) is not None
            assert _text(await _remind(ctx, str(tmp_path))) is not None

    async def test_a_subagent_s_first_search_reminds_whatever_its_parent_was_shown(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await _remind(ctx, str(tmp_path))
            assert _text(await _remind(ctx, str(tmp_path), agent_id="a1")) is not None
            assert _text(await _remind(ctx, str(tmp_path), agent_id="a1")) is None
            assert _text(await _remind(ctx, str(tmp_path), agent_id="a2")) is not None

    async def test_a_subagent_s_reminder_moves_no_time_of_its_parent_s(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await _remind(ctx, str(tmp_path), agent_id="a1")
            assert _text(await _remind(ctx, str(tmp_path))) is not None

    async def test_a_code_knowledge_search_counts_as_the_session_s_reminder(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await call(ctx, "knowledge_search", {"query": "x", "knowledge_bases": [_MODULE]})
            assert _text(await _remind(ctx, str(tmp_path))) is None

    async def test_a_search_of_every_corpus_counts_as_the_session_s_reminder(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await call(ctx, "knowledge_search", {"query": "x"})
            assert _text(await _remind(ctx, str(tmp_path))) is None

    async def test_a_search_of_hand_written_corpora_alone_moves_no_time(
        self, tmp_path: Path
    ) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            await _register(ctx, tmp_path, "docs")
            await call(ctx, "knowledge_search", {"query": "x", "knowledge_bases": ["docs"]})
            assert _text(await _remind(ctx, str(tmp_path))) is not None

    async def test_an_answer_past_the_hook_s_deadline_moves_no_time(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            late = await _remind(ctx, str(tmp_path), deadline_at_ms=_deadline_in(-1))
            refused = error_of(late)
            assert refused is not None
            assert refused[0] == _DEADLINE_PASSED
            assert _text(await _remind(ctx, str(tmp_path))) is not None

    async def test_two_requests_for_one_agent_at_once_yield_one_line(self, tmp_path: Path) -> None:
        async with open_context(tmp_path) as ctx:
            await _register(ctx, tmp_path, _MODULE)
            answers = await asyncio.gather(_remind(ctx, str(tmp_path)), _remind(ctx, str(tmp_path)))
            assert sum(_text(answer) is not None for answer in answers) == 1


class TestReminderTimes:
    def test_an_entry_past_the_interval_reminds_again(self) -> None:
        times = ReminderTimes()
        assert times.take("s", None, now=0.0, interval=10.0)
        assert not times.take("s", None, now=9.0, interval=10.0)
        assert times.take("s", None, now=10.0, interval=10.0)

    def test_an_entry_past_the_interval_is_dropped_when_the_table_is_touched(self) -> None:
        times = ReminderTimes()
        times.take("gone", "a", now=0.0, interval=10.0)
        times.take("s", None, now=20.0, interval=10.0)
        assert times._last == {("s", None): 20.0}

    def test_clearing_touches_only_the_main_session(self) -> None:
        times = ReminderTimes()
        times.take("s", None, now=0.0, interval=10.0)
        times.take("s", "a", now=0.0, interval=10.0)
        times.clear("s")
        assert times.take("s", None, now=1.0, interval=10.0)
        assert not times.take("s", "a", now=1.0, interval=10.0)

    def test_a_search_noted_counts_as_a_reminder(self) -> None:
        times = ReminderTimes()
        times.note_searched("s", now=0.0)
        assert not times.take("s", None, now=1.0, interval=10.0)
