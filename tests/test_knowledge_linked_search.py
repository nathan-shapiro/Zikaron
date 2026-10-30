"""A search result from a linked document says whether what the document describes has moved.

`knowledge-index.md` §7.7 is normative, with invariant 17: a result carries `source` exactly when
its file's indexed bytes declare a link, and the link it reports is the one those bytes declare —
read from the row's record while that record was read from those bytes, and from the stored chunks
otherwise. `source.state` is computed when the search runs. Ranking is untouched.

Every corpus here sits outside any repository, so the hash is git's raw blob form and the expected
values are computed in the test.
"""

import asyncio
import hashlib
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import (
    add_base,
    add_request,
    build_settings,
    config_for,
    open_store,
    write_tree,
)
from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.knowledge import (
    groups,
    lifecycle,
    link_store,
    links,
    meta,
    registry,
    reporting,
    source_hash,
)
from zikaron.core.knowledge.paths import knowledge_db_path
from zikaron.service.serialize_knowledge import KnowledgeStatusResult

_SOURCE: Final = b"def fresh():\n    return 1\n"


def _blob(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content, usedforsecurity=False).hexdigest()


def _linked(source: str, blob: str, words: str) -> bytes:
    return f"---\nzikaron-source: {source}\nzikaron-source-blob: {blob}\n---\n{words}\n".encode()


@pytest.fixture(autouse=True)
def _no_repository_above(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@asynccontextmanager
async def _store(
    tmp_path: Path, corpora: dict[str, dict[str, bytes]]
) -> AsyncIterator[tuple[Path, aiosqlite.Connection, EffectiveConfig]]:
    """A store holding each named corpus, built, with its documents' sources under `src/`."""
    write_tree(
        tmp_path / "src",
        {"fresh.py": _SOURCE, "changed.py": b"edited since\n", "a_directory/x": b""},
    )
    async with open_store(tmp_path) as (store_dir, db):
        config = config_for(tmp_path)
        for name, layout in corpora.items():
            root = write_tree(tmp_path / name, layout)
            await add_base(
                store_dir, db, config, add_request(root, name=name, git_mode=meta.GitMode.OFF)
            )
            await lifecycle.refresh(
                store_dir,
                db,
                config,
                name=name,
                build=build_settings(config),
                migrate=True,
            )
        yield store_dir, db, config


_FOUR_STATES: Final = {
    "fresh.md": _linked("src/fresh.py", _blob(_SOURCE), "linked fresh"),
    "changed.md": _linked("src/changed.py", _blob(b"before the edit\n"), "linked changed"),
    "missing.md": _linked("src/gone.py", _blob(b"x\n"), "linked missing"),
    "unverifiable.md": _linked("src/a_directory", _blob(b"x\n"), "linked unverifiable"),
    "malformed.md": b"---\nzikaron-source: src/fresh.py\n---\nlinked malformed\n",
    "plain.md": b"linked plain\n",
}


async def _search(
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
    text: str,
    names: tuple[str, ...] | None = None,
) -> groups.SearchResponse:
    return await groups.search_all(
        store_dir,
        db,
        config,
        groups.SearchRequest(text=text, limit_per_kb=20, names=names),
        encoder=FakeEncoder(),
        migrate=True,
    )


def _results(response: groups.SearchResponse) -> dict[str, dict[str, object]]:
    """Every result of every group, keyed `<corpus>/<path>`."""
    found: dict[str, dict[str, object]] = {}
    for group in response.groups:
        assert isinstance(group, groups.Group)
        for result in group.payload()["results"]:  # type: ignore[attr-defined]
            found[f"{group.knowledge_base}/{result['path']}"] = result
    return found


async def _counters(
    store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig, name: str
) -> dict[str, int | None]:
    """`files_linked` and the link counters as `status` reports them."""
    listing = await reporting.status(store_dir, db, config, name=name, migrate=True)
    payload = KnowledgeStatusResult(reports=listing.knowledge_bases, orphans=()).as_json()
    entries = payload["knowledge_bases"]
    assert isinstance(entries, list)
    (entry,) = entries
    assert isinstance(entry, dict)
    reported: dict[str, int | None] = {}
    for key in ("files_linked", *meta.LINK_COUNTER_KEYS):
        value = entry[key]
        assert value is None or isinstance(value, int)
        reported[key] = value
    return reported


class TestWhatAResultCarries:
    async def test_invariant_17_source_is_present_exactly_where_a_link_is_declared(
        self, tmp_path: Path
    ) -> None:
        async with _store(tmp_path, {"docs": _FOUR_STATES}) as (store_dir, db, config):
            results = _results(await _search(store_dir, db, config, "linked"))
        assert set(results) == {f"docs/{path}" for path in _FOUR_STATES}
        assert "source" not in results["docs/plain.md"]
        assert results["docs/fresh.md"]["source"] == {"path": "src/fresh.py", "state": "fresh"}
        assert results["docs/changed.md"]["source"] == {
            "path": "src/changed.py",
            "state": "changed",
        }
        assert results["docs/missing.md"]["source"] == {"path": "src/gone.py", "state": "missing"}
        assert results["docs/unverifiable.md"]["source"] == {
            "path": "src/a_directory",
            "state": "unverifiable",
        }
        assert results["docs/malformed.md"]["source"] == {"path": None, "state": "unverifiable"}

    async def test_the_counters_rise_by_what_each_search_returned(self, tmp_path: Path) -> None:
        corpora = {"docs": _FOUR_STATES, "notes": {"a.md": b"plain words\n"}}
        async with _store(tmp_path, corpora) as (store_dir, db, config):
            await _search(store_dir, db, config, "linked", names=("docs", "notes"))
            linked = await _counters(store_dir, db, config, "docs")
            unlinked = await _counters(store_dir, db, config, "notes")
        assert linked == {
            "files_linked": 5,
            "results_linked": 5,
            "results_source_changed": 1,
            "results_source_missing": 1,
            "results_source_unverifiable": 2,
        }
        assert unlinked == {"files_linked": 0, **dict.fromkeys(meta.LINK_COUNTER_KEYS, 0)}, (
            "a search whose results declare no link raises none of them"
        )

    async def test_a_record_is_trusted_only_while_it_was_read_from_the_rows_bytes(
        self, tmp_path: Path
    ) -> None:
        """A row a previous-schema build rewrote keeps a record of other bytes, or none at all, and
        is read again from the stored chunks; a record read from the row's bytes is used as it is,
        which `trusted.md` shows by recording a blob its chunks do not declare."""
        layout = {
            "kept.md": _linked("src/fresh.py", _blob(_SOURCE), "linked kept"),
            "nulled.md": _linked("src/fresh.py", _blob(_SOURCE), "linked nulled"),
            "trusted.md": _linked("src/fresh.py", _blob(_SOURCE), "linked trusted"),
        }
        async with _store(tmp_path, {"docs": layout}) as (store_dir, db, config):
            registered = await registry.require(db, "docs")
            with closing(sqlite3.connect(knowledge_db_path(store_dir, registered.id))) as raw:
                raw.execute(
                    "UPDATE files SET link_read_from = 'other bytes', source_path = 'wrong.py' "
                    "WHERE path = 'kept.md'"
                )
                raw.execute(
                    "UPDATE files SET link_read_from = NULL, link_declared = NULL, "
                    "source_path = NULL, source_blob = NULL WHERE path = 'nulled.md'"
                )
                raw.execute(
                    "UPDATE files SET source_blob = ? WHERE path = 'trusted.md'", ("0" * 40,)
                )
                raw.commit()
            results = _results(await _search(store_dir, db, config, "linked"))
        for path in ("docs/kept.md", "docs/nulled.md"):
            assert results[path]["source"] == {"path": "src/fresh.py", "state": "fresh"}
        assert results["docs/trusted.md"]["source"] == {"path": "src/fresh.py", "state": "changed"}

    async def test_a_long_document_is_read_only_as_far_as_its_prefix(self, tmp_path: Path) -> None:
        body = "".join(f"line {number} of a long linked document\n" for number in range(2000))
        layout = {"long.md": _linked("src/fresh.py", _blob(_SOURCE), body)}
        async with _store(tmp_path, {"docs": layout}) as (store_dir, db, _config):
            registered = await registry.require(db, "docs")
            database = knowledge_db_path(store_dir, registered.id)
            async with aiosqlite.connect(database) as corpus:
                prefix = await link_store.stored_prefix(corpus, "long.md")
        assert prefix.startswith("---\nzikaron-source: src/fresh.py\n")
        assert links.LINK_PREFIX_CHARS < len(prefix) < len(body)


class TestOneBudgetForTheWholeSearch:
    async def test_a_source_that_blocks_spends_the_budget_for_the_corpora_after_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Corpora are searched in name order: `a` before the one that blocks, `c` after it."""
        corpora = {
            name: {f"{name}.md": _linked("src/fresh.py", _blob(_SOURCE), "linked")}
            for name in ("a", "b", "c")
        }
        async with _store(tmp_path, corpora) as (store_dir, db, config):
            # A budget of a second against a check blocked for ten, and another request at a tenth
            # of one. The ceiling below is not corrected for lateness: a check run on the loop
            # rather than on its own thread is a defect it must see, and would be lateness. So the
            # margin is the defence — a search abandoning the check answers in about a second, one
            # waiting for it in ten, and the ceiling sits at five.
            monkeypatch.setattr(source_hash, "LINK_HASH_TIMEOUT_SECONDS", 1.0)
            real_check = source_hash._checked
            calls: list[str] = []

            def _check(root: Path, declared: str) -> object:
                calls.append(declared)
                if len(calls) == 2:
                    time.sleep(10)
                return real_check(root, declared)

            monkeypatch.setattr(source_hash, "_checked", _check)
            answered_at: dict[str, float] = {}

            async def _the_search() -> groups.SearchResponse:
                found = await _search(store_dir, db, config, "linked")
                answered_at["search"] = time.monotonic()
                return found

            async def _another_request() -> None:
                await asyncio.sleep(0.1)
                await reporting.list_bases(store_dir, db, config, migrate=True)
                answered_at["other"] = time.monotonic()

            started = time.monotonic()
            response, _ = await asyncio.gather(_the_search(), _another_request())
            searched_for = time.monotonic() - started
        results = _results(response)
        assert results["a/a.md"]["source"] == {"path": "src/fresh.py", "state": "fresh"}
        assert results["b/b.md"]["source"]["state"] == "unverifiable"  # type: ignore[index]
        assert results["c/c.md"]["source"]["state"] == "unverifiable"  # type: ignore[index]
        assert len(calls) == 2, "the corpus after the spent budget ran no check"
        assert searched_for < 5, f"the blocked check was not abandoned: {searched_for:.3f}s"
        assert answered_at["other"] < answered_at["search"], (
            "no other request was answered while the check was blocked"
        )
