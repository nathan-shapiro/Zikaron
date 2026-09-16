"""Searching across knowledge bases: which corpora answer, in what order, and within what bounds.

Everything here is about the answer's *shape* rather than its content — which corpus appears, what
it says about itself, and what happens when the whole thing will not fit. The one rule underneath
all of it: a corpus a caller named is never silently absent from the answer, because "searched and
found nothing" and "not searched" are different facts and only one of them is evidence of absence.
"""

import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder, unit_at
from tests.knowledge_fixtures import (
    add_base,
    add_request,
    build_settings,
    config_for,
    open_store,
    write_config,
    write_tree,
)
from zikaron.core.config.keys import CONFIG_KEYS_BY_NAME, IntBounds
from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.knowledge import database as knowledge_database
from zikaron.core.knowledge import groups, lifecycle, lock, paths, registry, reporting
from zikaron.core.knowledge import pending as knowledge_pending
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.groups import Group, SearchRequest, SearchResponse, UnknownGroup
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.knowledge.search import Result
from zikaron.core.knowledge.state import KnowledgeState
from zikaron.core.store.transactions import in_one_transaction, propagate

_QUERY: Final = "protobuf"
_PROTOBUF: Final = b"the protobuf step fails silently\n"
_STARTED_AT: Final = "2026-01-01T00:00:00+00:00"
_WALKED_AT: Final = "2026-01-02T00:00:00+00:00"


def _result(*, path: str = "a.md", score: float = 0.5, snippet: str = "alpha\n") -> Result:
    return Result(
        path=path,
        start_line=1,
        end_line=1,
        snippet=snippet,
        truncated=False,
        score=score,
        stale=False,
    )


def _group(name: str, *results: Result, state: KnowledgeState = KnowledgeState.OK) -> Group:
    return Group(
        knowledge_base=name,
        description=f"{name} corpus",
        state=state,
        files_remaining=None,
        results=tuple(results),
    )


class TestTheAssemblyRules:
    def test_a_group_is_ordered_by_its_best_cosine(self) -> None:
        low = _group("low", _result(score=0.1), _result(score=0.2))
        high = _group("high", _result(score=0.9))
        assert low.order_key == pytest.approx(0.2)
        assert high.order_key == pytest.approx(0.9)

    def test_an_empty_group_sorts_after_every_populated_one(self) -> None:
        assert _group("empty").order_key < _group("full", _result(score=-1.0)).order_key

    def test_a_group_reports_its_state_and_progress_beside_its_results(self) -> None:
        payload = _group("docs", _result()).payload()
        assert payload["state"] == "ok"
        assert payload["files_remaining"] is None
        assert "dropped" not in payload

    def test_an_unknown_name_reports_itself_and_nothing_else(self) -> None:
        """Deliberately not the registry: that list describes the store rather than this name, and
        carrying it here multiplied the whole registry by the number of names a caller got wrong."""
        assert UnknownGroup(knowledge_base="dcos").payload() == {
            "knowledge_base": "dcos",
            "error": "unknown_knowledge_base",
        }

    def test_the_names_that_do_exist_ride_on_the_response_once(self) -> None:
        response = SearchResponse(
            groups=(UnknownGroup(knowledge_base="dcos"), UnknownGroup(knowledge_base="dosc")),
            groups_dropped=False,
            known_knowledge_bases=(groups.KnownBase(name="docs", description="design records"),),
        )
        assert response.payload()["known_knowledge_bases"] == [
            {"name": "docs", "description": "design records"}
        ]

    @pytest.mark.parametrize(
        ("asked", "applied"), [(1, 1), (5, 5), (20, 20), (21, 20), (10_000, 20), (0, 1), (-3, 1)]
    )
    def test_the_limit_is_clamped_rather_than_refused(self, asked: int, applied: int) -> None:
        assert groups.clamp_limit(asked) == applied

    def test_the_cap_matches_the_range_configuration_allows_for_a_per_file_cap(self) -> None:
        """A per-file allowance above the output cap could never bind, so the configuration
        schema's maximum and this cap are the same number — stated in two places and checked
        here, because the argument for that maximum is this constant."""
        bounds = CONFIG_KEYS_BY_NAME["knowledge_max_chunks_per_file"].bounds
        assert isinstance(bounds, IntBounds)
        assert bounds.maximum == groups.LIMIT_PER_KB_CAP


class TestTheResponseCap:
    def _oversized(self, name: str, *, results: int = 10) -> Group:
        return _group(name, *(_result(snippet="x" * 900, score=0.5) for _ in range(results)))

    def test_a_response_within_the_cap_keeps_every_result(self) -> None:
        response = groups._fit_to_cap([_group("docs", _result())], known=(), max_bytes=10_000)
        assert response.groups_dropped is False
        assert isinstance(response.groups[0], Group)
        assert response.groups[0].results

    def test_the_lowest_ranked_group_loses_its_results_first(self) -> None:
        best = self._oversized("best")
        worst = self._oversized("worst")
        # The cap is derived rather than picked: exactly the size of the answer with the last
        # group's results gone. A literal here would have to be re-guessed whenever the accounting
        # changes, and a test that silently stops exercising one drop is worth nothing.
        one_dropped = groups.response_bytes(
            SearchResponse(
                groups=(best, replace(worst, results=(), dropped=True)), groups_dropped=True
            )
        )
        response = groups._fit_to_cap([best, worst], known=(), max_bytes=one_dropped)
        assert response.groups_dropped is True
        first, second = response.groups
        assert isinstance(first, Group)
        assert isinstance(second, Group)
        assert first.results
        assert second.results == ()
        assert second.dropped is True
        assert second.payload()["dropped"] is True

    def test_a_dropped_group_keeps_its_name_state_and_progress(self) -> None:
        response = groups._fit_to_cap(
            [self._oversized("a"), self._oversized("b")], known=(), max_bytes=800
        )
        for group in response.groups:
            assert isinstance(group, Group)
            payload = group.payload()
            assert payload["knowledge_base"] in {"a", "b"}
            assert payload["state"] == "ok"
            assert "files_remaining" in payload

    def test_no_named_corpus_is_removed_even_when_stubs_alone_exceed_the_cap(self) -> None:
        """The floor is presence. Once every group's results are gone there is nothing left to
        drop, and a corpus the caller asked about is not a thing this may remove to save bytes."""
        response = groups._fit_to_cap(
            [self._oversized(f"corpus-{index}") for index in range(20)], known=(), max_bytes=100
        )
        assert len(response.groups) == 20
        assert response.groups_dropped is True
        assert groups.response_bytes(response) > 100

    def test_a_group_with_nothing_to_drop_is_passed_over(self) -> None:
        """Only results can be dropped. An empty group and an unknown name have none, so the cap
        walks past them to the next group that does — and both are still in the answer afterwards,
        which is the point of dropping results rather than groups."""
        unknown = UnknownGroup(knowledge_base="dcos")
        response = groups._fit_to_cap(
            [self._oversized("first"), _group("empty"), unknown, self._oversized("last")],
            known=(),
            max_bytes=10_000,
        )
        assert [group.knowledge_base for group in response.groups] == [
            "first",
            "empty",
            "dcos",
            "last",
        ]
        assert response.groups_dropped is True

    def test_many_wrong_names_cost_one_registry_listing_between_them(self) -> None:
        """The shape that used to defeat the cap outright. When each unknown name carried the whole
        registry, a caller naming thirty wrong corpora against a store of twenty produced the
        registry thirty times over — bytes nothing could drop, past a cap whose overflow is a silent
        truncation at the harness."""
        known = tuple(
            groups.KnownBase(name=f"corpus-{index}", description="design records " * 4)
            for index in range(20)
        )
        response = groups._fit_to_cap(
            [UnknownGroup(knowledge_base=f"wrong-{index}") for index in range(30)],
            known=known,
            max_bytes=groups.RESPONSE_MAX_BYTES,
        )
        assert len(response.groups) == 30
        assert response.known_knowledge_bases == known
        assert groups.response_bytes(response) <= groups.RESPONSE_MAX_BYTES

    def test_the_registry_listing_is_the_last_thing_shed(self) -> None:
        """Dropped results announce themselves; a withheld listing does not, because its absence is
        also what a request with no bad names looks like. So the announced loss is spent first, and
        the silent one only once the answer is already nothing but stubs."""
        known = tuple(
            groups.KnownBase(name=f"corpus-{index}", description="design records " * 20)
            for index in range(40)
        )
        response = groups._fit_to_cap(
            [self._oversized("docs"), UnknownGroup(knowledge_base="dcos")],
            known=known,
            max_bytes=2_000,
        )
        assert response.groups_dropped is True
        assert response.known_knowledge_bases == ()
        assert [group.knowledge_base for group in response.groups] == ["docs", "dcos"]

    def test_the_measurement_is_the_compact_unescaped_payload_counted_once(self) -> None:
        """Non-ASCII on purpose: the encoding is measured unescaped, because that is the shape the
        transport serializes in, and escaping it here would count a document nobody receives.

        **Counted once**, which is the half worth pinning: the transport delivers the payload twice
        — as text and again as structured content — and charging the cap for both would halve the
        answer, because the threshold this cap sits under was measured through that same duplication
        and recorded in single-counted payload size. The two numbers are in one unit."""
        response = SearchResponse(
            groups=(_group("docs", _result(snippet="héllo\n")),), groups_dropped=False
        )
        assert groups.response_bytes(response) == len(
            '{"groups": [{"knowledge_base": "docs", "description": "docs corpus", "state": "ok", '
            '"files_remaining": null, "results": [{"path": "a.md", "start_line": 1, '
            '"end_line": 1, "snippet": "héllo\\n", "truncated": false, "score": 0.5, '
            '"stale": false}]}], "groups_dropped": false, "known_knowledge_bases": []}'.encode()
        )


def _asking(*, names: tuple[str, ...] | None = None, limit_per_kb: int = 5) -> SearchRequest:
    """The standing query, varied by whatever one test is actually about."""
    return SearchRequest(text=_QUERY, limit_per_kb=limit_per_kb, names=names)


async def _search_all(
    tmp_path: Path,
    layouts: dict[str, dict[str, bytes]],
    *,
    request: SearchRequest | None = None,
    encoder: FakeEncoder | None = None,
    build: bool = True,
) -> SearchResponse:
    """Register a corpus per entry in `layouts`, build them, and run one search over all of them."""
    using = encoder if encoder is not None else FakeEncoder()
    asked = request if request is not None else _asking()
    async with open_store(tmp_path) as (store_dir, db):
        config = config_for(tmp_path)
        for name, layout in layouts.items():
            root = write_tree(tmp_path / name, layout)
            await add_base(
                store_dir, db, config, add_request(root, name=name, git_mode=GitMode.OFF)
            )
            if build:
                await lifecycle.refresh(
                    store_dir,
                    db,
                    config,
                    name=name,
                    build=build_settings(config, encoder=using),
                )
        return await groups.search_all(store_dir, db, config, asked, encoder=using)


class TestWhichCorporaAnswer:
    async def test_every_registered_corpus_answers_when_none_is_named(self, tmp_path: Path) -> None:
        response = await _search_all(
            tmp_path,
            {"docs": {"a.md": b"protobuf\n"}, "runbooks": {"b.md": b"unrelated\n"}},
        )
        assert {group.knowledge_base for group in response.groups} == {"docs", "runbooks"}

    async def test_only_the_named_corpus_is_searched(self, tmp_path: Path) -> None:
        response = await _search_all(
            tmp_path,
            {"docs": {"a.md": b"protobuf\n"}, "runbooks": {"b.md": b"protobuf\n"}},
            request=_asking(names=("docs",)),
        )
        assert [group.knowledge_base for group in response.groups] == ["docs"]

    async def test_a_name_differing_only_by_case_is_the_same_corpus(self, tmp_path: Path) -> None:
        response = await _search_all(
            tmp_path, {"docs": {"a.md": b"protobuf\n"}}, request=_asking(names=("DOCS",))
        )
        assert isinstance(response.groups[0], Group)

    async def test_one_corpus_named_twice_is_searched_and_reported_once(
        self, tmp_path: Path
    ) -> None:
        """Two identical groups would cost a second search, a second copy of the results and twice
        the bytes against the response cap, for an answer the caller already has."""
        response = await _search_all(
            tmp_path,
            {"docs": {"a.md": b"protobuf\n"}},
            request=_asking(names=("docs", "DOCS", "docs")),
        )
        assert [group.knowledge_base for group in response.groups] == ["docs"]

    @pytest.mark.parametrize(
        "asked",
        [("dcos", "dcos"), ("DCOS", "dcos"), ("dcos", "Dcos", "DCOS")],
        ids=["identical", "one case variant", "three spellings"],
    )
    async def test_one_unknown_name_repeated_is_reported_once(
        self, tmp_path: Path, asked: tuple[str, ...]
    ) -> None:
        """Case variants included, because a name differing only by case could only ever have meant
        the same corpus — so deduplicating on the raw spelling would report one absent corpus twice
        while claiming, three lines from the code, to deduplicate after normalisation."""
        response = await _search_all(
            tmp_path, {"docs": {"a.md": b"protobuf\n"}}, request=_asking(names=asked)
        )
        assert [group.knowledge_base for group in response.groups] == ["dcos"]

    @pytest.mark.parametrize("asked", ["dcos", "  ", ""], ids=["typo", "blank", "empty"])
    async def test_a_name_no_corpus_has_is_a_group_of_its_own(
        self, tmp_path: Path, asked: str
    ) -> None:
        """A per-group error rather than a failed call: naming one bad corpus among three still
        answers for the other two, and the answer a caller needs is the list of real names."""
        response = await _search_all(
            tmp_path, {"docs": {"a.md": b"protobuf\n"}}, request=_asking(names=(asked, "docs"))
        )
        unknown = next(group for group in response.groups if isinstance(group, UnknownGroup))
        assert unknown.knowledge_base == asked
        assert [one.name for one in response.known_knowledge_bases] == ["docs"]
        assert any(isinstance(group, Group) for group in response.groups)

    async def test_a_request_whose_names_all_resolve_carries_no_registry_listing(
        self, tmp_path: Path
    ) -> None:
        """The listing exists to answer "not that one — these". A caller whose names all matched is
        being told what it already knows, in bytes that count against the response cap."""
        response = await _search_all(
            tmp_path, {"docs": {"a.md": b"protobuf\n"}}, request=_asking(names=("docs",))
        )
        assert response.known_knowledge_bases == ()

    async def test_a_store_with_no_corpora_answers_with_no_groups(self, tmp_path: Path) -> None:
        response = await _search_all(tmp_path, {})
        assert response.groups == ()
        assert response.groups_dropped is False

    async def test_naming_only_unknown_corpora_never_reaches_the_model(
        self, tmp_path: Path
    ) -> None:
        """A typo costs no inference: the query is built once, and only when there is a corpus to
        run it against."""
        encoder = FakeEncoder()
        await _search_all(
            tmp_path,
            {"docs": {"a.md": b"x\n"}},
            request=_asking(names=("dcos",)),
            encoder=encoder,
            build=False,
        )
        assert encoder.embedded == []


class TestWhatAGroupSaysAboutItself:
    async def test_a_built_corpus_with_nothing_matching_is_ok_and_empty(
        self, tmp_path: Path
    ) -> None:
        """Positive information: the corpus *was* searched. Its emptiness here is emptiness of the
        corpus rather than of the answer, since neither arm applies a relevance floor."""
        response = await _search_all(tmp_path, {"docs": {"logo.png": b"\x89PNG\x00"}})
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.OK
        assert group.results == ()

    async def test_a_corpus_that_was_never_built_says_so(self, tmp_path: Path) -> None:
        response = await _search_all(tmp_path, {"docs": {"a.md": b"protobuf\n"}}, build=False)
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.REINDEX_REQUIRED
        assert group.results == ()

    async def test_a_corpus_whose_root_is_gone_answers_empty_rather_than_from_the_index(
        self, tmp_path: Path
    ) -> None:
        """The index is kept, not deleted — the root may come back — but nothing is served from it
        while the files those fragments name cannot be read."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = write_tree(tmp_path / "docs", {"a.md": b"protobuf\n"})
            await add_base(
                store_dir, db, config, add_request(root, name="docs", git_mode=GitMode.OFF)
            )
            encoder = FakeEncoder()
            await lifecycle.refresh(
                store_dir, db, config, name="docs", build=build_settings(config, encoder=encoder)
            )
            (root / "a.md").unlink()
            root.rmdir()
            response = await groups.search_all(
                store_dir,
                db,
                config,
                SearchRequest(text=_QUERY, limit_per_kb=5),
                encoder=encoder,
            )
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.ROOT_MISSING
        assert group.results == ()

    async def test_a_corpus_built_by_another_model_refuses_to_serve(self, tmp_path: Path) -> None:
        """Vectors labelled with a model that did not produce them are the one inconsistency this
        store will not answer around, so the corpus reports that it needs rebuilding instead."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = write_tree(tmp_path / "docs", {"a.md": b"protobuf\n"})
            await add_base(
                store_dir, db, config, add_request(root, name="docs", git_mode=GitMode.OFF)
            )
            encoder = FakeEncoder()
            await lifecycle.refresh(
                store_dir, db, config, name="docs", build=build_settings(config, encoder=encoder)
            )
            write_config(tmp_path, '[embedding]\nembed_model = "a-different-model"\n')
            moved = config_for(tmp_path)
            response = await groups.search_all(
                store_dir,
                db,
                moved,
                SearchRequest(text=_QUERY, limit_per_kb=5),
                encoder=FakeEncoder(model_name="a-different-model"),
            )
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.REINDEX_REQUIRED
        assert group.results == ()

    async def test_a_corpus_whose_database_will_not_open_is_an_error_not_a_rebuild(
        self, tmp_path: Path
    ) -> None:
        """Kept apart from `reindex_required` deliberately: a build does not obviously repair a
        corrupt file, and an operator sent to run one forever is worse than being told the truth."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = write_tree(tmp_path / "docs", {"a.md": b"protobuf\n"})
            created = await add_base(
                store_dir, db, config, add_request(root, name="docs", git_mode=GitMode.OFF)
            )
            created.database_path.write_bytes(b"this is not a database")
            response = await groups.search_all(
                store_dir,
                db,
                config,
                SearchRequest(text=_QUERY, limit_per_kb=5),
                encoder=FakeEncoder(),
            )
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.ERROR

    async def test_a_corpus_that_opens_and_then_cannot_answer_is_an_error_too(
        self, tmp_path: Path
    ) -> None:
        """Opening reads `meta` and the vector table's own declaration, and nothing else — so a
        corpus can pass that and still fail on the first real query. The full-text table is one it
        never touches, which is why that is the one broken here. Reported as this corpus's own state
        rather than as a failed call, which is what keeps one damaged database from taking every
        other corpus's answer with it."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = write_tree(tmp_path / "docs", {"a.md": b"protobuf\n"})
            await add_base(
                store_dir, db, config, add_request(root, name="docs", git_mode=GitMode.OFF)
            )
            encoder = FakeEncoder()
            await lifecycle.refresh(
                store_dir, db, config, name="docs", build=build_settings(config, encoder=encoder)
            )
            registered = await registry.require(db, "docs")
            async with await KnowledgeDatabase.open(store_dir, registered.id) as opened:
                await opened.connection.execute("DROP TABLE chunks_fts")
                await opened.connection.commit()
            response = await groups.search_all(
                store_dir,
                db,
                config,
                SearchRequest(text=_QUERY, limit_per_kb=5),
                encoder=encoder,
            )
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.ERROR

    async def test_a_corpus_whose_vector_table_is_gone_fails_to_open_at_all(
        self, tmp_path: Path
    ) -> None:
        """The width a corpus will accept is read at open, so a vector table that is not there is
        caught before a query rather than by one — and reported as the same `error`, since what a
        caller can do about it is the same."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = write_tree(tmp_path / "docs", {"a.md": _PROTOBUF})
            await add_base(
                store_dir, db, config, add_request(root, name="docs", git_mode=GitMode.OFF)
            )
            encoder = FakeEncoder()
            await lifecycle.refresh(
                store_dir, db, config, name="docs", build=build_settings(config, encoder=encoder)
            )
            registered = await registry.require(db, "docs")
            async with await KnowledgeDatabase.open(store_dir, registered.id) as opened:
                await opened.connection.execute("DROP TABLE chunks_vec")
                await opened.connection.commit()

            with pytest.raises(aiosqlite.Error, match="no chunks_vec table"):
                await KnowledgeDatabase.open(store_dir, registered.id)

            response = await groups.search_all(
                store_dir,
                db,
                config,
                SearchRequest(text=_QUERY, limit_per_kb=5),
                encoder=encoder,
            )
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.ERROR

    async def test_a_corpus_whose_database_is_absent_is_an_empty_one(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            root = write_tree(tmp_path / "docs", {"a.md": b"protobuf\n"})
            await add_base(
                store_dir, db, config, add_request(root, name="docs", git_mode=GitMode.OFF)
            )
            registered = await registry.require(db, "docs")
            paths.knowledge_db_path(store_dir, registered.id).unlink()
            response = await groups.search_all(
                store_dir,
                db,
                config,
                SearchRequest(text=_QUERY, limit_per_kb=5),
                encoder=FakeEncoder(),
            )
        (group,) = response.groups
        assert isinstance(group, Group)
        assert group.state is KnowledgeState.REINDEX_REQUIRED


class TestEveryNamedCorpusIsInTheAnswer:
    """Populated, empty, errored, unknown, or a stub whose results were dropped — but never
    missing. A corpus silently absent from an answer reads as one that had nothing, which is the
    one reading an agent must not be given without it being true."""

    async def test_a_request_naming_corpora_in_every_condition_answers_for_all_of_them(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(groups, "RESPONSE_MAX_BYTES", 1_400)
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            encoder = FakeEncoder()
            for name, layout in {
                "full": {"a.md": ("protobuf " * 60 + "\n").encode()},
                "alsofull": {"b.md": ("protobuf " * 60 + "\n").encode()},
                "empty": {"logo.png": b"\x89PNG\x00"},
            }.items():
                root = write_tree(tmp_path / name, layout)
                await add_base(
                    store_dir, db, config, add_request(root, name=name, git_mode=GitMode.OFF)
                )
                await lifecycle.refresh(
                    store_dir,
                    db,
                    config,
                    name=name,
                    build=build_settings(config, encoder=encoder),
                )
            unbuilt = write_tree(tmp_path / "unbuilt", {"c.md": b"protobuf\n"})
            await add_base(
                store_dir,
                db,
                config,
                add_request(unbuilt, name="unbuilt", git_mode=GitMode.OFF),
            )
            asked = ("full", "alsofull", "empty", "unbuilt", "dcos")
            response = await groups.search_all(
                store_dir,
                db,
                config,
                SearchRequest(text=_QUERY, limit_per_kb=20, names=asked),
                encoder=encoder,
            )
        assert {group.knowledge_base for group in response.groups} == set(asked)
        assert response.groups_dropped is True
        states = {
            group.knowledge_base: group.state
            for group in response.groups
            if isinstance(group, Group)
        }
        assert states["empty"] is KnowledgeState.OK
        assert states["unbuilt"] is KnowledgeState.REINDEX_REQUIRED
        assert any(isinstance(group, Group) and group.dropped for group in response.groups)


class TestOrderAcrossCorpora:
    async def test_the_corpus_with_the_better_cosine_comes_first(self, tmp_path: Path) -> None:
        """The one cross-corpus decision the service makes, and the only signal valid for it: BM25
        cannot be compared between corpora at all, while a cosine is a function of two vectors."""
        encoder = FakeEncoder()
        prefix = config_for(tmp_path).get_str("embed_prefix_query")
        encoder.planned[f"{prefix}{_QUERY}"] = unit_at(0.0, encoder.dim)
        encoder.planned["near.md\nprotobuf\n"] = unit_at(10.0, encoder.dim)
        encoder.planned["far.md\nprotobuf\n"] = unit_at(80.0, encoder.dim)
        response = await _search_all(
            tmp_path,
            {"near": {"near.md": b"protobuf\n"}, "far": {"far.md": b"protobuf\n"}},
            encoder=encoder,
        )
        assert [group.knowledge_base for group in response.groups] == ["near", "far"]

    async def test_the_response_stays_within_the_cap_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cap is lowered rather than the corpus enlarged: what is under test is that the whole
        path applies it, not how many kilobytes of fixture it takes to reach the real one."""
        monkeypatch.setattr(groups, "RESPONSE_MAX_BYTES", 900)
        response = await _search_all(
            tmp_path,
            {
                "first": {"a.md": ("protobuf " * 80 + "\n").encode()},
                "second": {"b.md": ("protobuf " * 80 + "\n").encode()},
            },
            request=_asking(limit_per_kb=20),
        )
        assert response.groups_dropped is True
        assert len(response.groups) == 2
        assert groups.response_bytes(response) <= 900


class TestTheOutputLimit:
    async def test_a_limit_above_the_cap_returns_at_most_the_cap(self, tmp_path: Path) -> None:
        layout = {f"f{index}.md": b"protobuf\n" for index in range(30)}
        response = await _search_all(tmp_path, {"docs": layout}, request=_asking(limit_per_kb=1000))
        (group,) = response.groups
        assert isinstance(group, Group)
        assert len(group.results) == groups.LIMIT_PER_KB_CAP


class TestACorpusBeingBuilt:
    """A search during a build answers from what has committed and says so. Checked at the search
    entry point rather than only through `status`, because the two read the same state through
    different code: the group's own `state` and `files_remaining` are what an agent sees, and
    nothing else asserts that a corpus mid-build is served at all rather than answered empty."""

    async def test_it_serves_what_is_committed_and_reports_a_falling_count(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            encoder = FakeEncoder()
            root = write_tree(tmp_path / "docs", {"a.md": _PROTOBUF, "b.md": b"beta prose\n"})
            await add_base(
                store_dir, db, config, add_request(root, name="docs", git_mode=GitMode.OFF)
            )
            await lifecycle.refresh(
                store_dir, db, config, name="docs", build=build_settings(config, encoder=encoder)
            )
            await _pretend_a_build_is_running(store_dir, db, pending_paths=["a.md", "b.md"])

            mid = await _one_group(store_dir, db, config, encoder)
            assert mid.state is KnowledgeState.INDEXING
            assert mid.files_remaining == 2
            assert mid.results, "committed files are served while a build runs"
            assert all(result.stale for result in mid.results), "every pending path is stale"

            await _dispose_one_pending(store_dir, db, "b.md")

            later = await _one_group(store_dir, db, config, encoder)
            assert later.files_remaining == 1


async def _one_group(
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
    encoder: FakeEncoder,
) -> Group:
    response = await groups.search_all(store_dir, db, config, _asking(), encoder=encoder)
    (group,) = response.groups
    assert isinstance(group, Group)
    return group


async def _pretend_a_build_is_running(
    store_dir: Path, db: aiosqlite.Connection, *, pending_paths: list[str]
) -> None:
    """Put the `docs` corpus into the state a live build leaves: this process holding its lock, a
    walk phase that has finished, and paths still waiting to be disposed of.

    Planted rather than produced by a real build, because what is under test is what a *reader* in
    another process sees while one runs — and the build that would produce it runs to completion
    before it returns.
    """
    registered = await registry.require(db, "docs")
    async with await KnowledgeDatabase.open(store_dir, registered.id) as opened:

        async def _work(connection: aiosqlite.Connection) -> None:
            await knowledge_pending.replace_all(connection, pending_paths, noticed_at=_WALKED_AT)
            await knowledge_database.write_meta(
                connection,
                {
                    "lock_pid": str(os.getpid()),
                    "lock_host": lock.this_host(),
                    "lock_started_at": _STARTED_AT,
                    "last_scan_started_at": _STARTED_AT,
                    "last_walk_completed_at": _WALKED_AT,
                },
            )

        await in_one_transaction(opened.connection, _work, failure=propagate)


async def _dispose_one_pending(store_dir: Path, db: aiosqlite.Connection, path: str) -> None:
    registered = await registry.require(db, "docs")
    async with await KnowledgeDatabase.open(store_dir, registered.id) as opened:

        async def _work(connection: aiosqlite.Connection) -> None:
            await knowledge_pending.dispose(connection, path)

        await in_one_transaction(opened.connection, _work, failure=propagate)


class TestOneUnreadableCorpusAmongHealthyOnes:
    """A corpus whose vector table cannot be interpreted is that corpus's own `error`, and nothing
    more. The failure this pins is the other one: a second exception type escaping the handlers
    every caller was written against, so that one damaged database ends a `search` or a `list` over
    twenty healthy ones in a traceback."""

    async def test_a_declaration_with_no_width_errors_that_corpus_alone(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            encoder = FakeEncoder()
            for name in ("broken", "healthy"):
                root = write_tree(tmp_path / name, {"a.md": _PROTOBUF})
                await add_base(
                    store_dir, db, config, add_request(root, name=name, git_mode=GitMode.OFF)
                )
                await lifecycle.refresh(
                    store_dir, db, config, name=name, build=build_settings(config, encoder=encoder)
                )
            await _erase_the_declared_width(store_dir, db, "broken")

            response = await groups.search_all(
                store_dir, db, config, SearchRequest(text=_QUERY, limit_per_kb=5), encoder=encoder
            )
            listing = await reporting.list_bases(store_dir, db, config)

        by_name = {group.knowledge_base: group for group in response.groups}
        broken = by_name["broken"]
        healthy = by_name["healthy"]
        assert isinstance(broken, Group)
        assert isinstance(healthy, Group)
        assert broken.state is KnowledgeState.ERROR
        assert healthy.results, "one damaged corpus must not take its neighbour's answer with it"

        states = {report.summary.name: report.summary.state for report in listing.knowledge_bases}
        assert states == {"broken": KnowledgeState.ERROR, "healthy": KnowledgeState.OK}


async def _erase_the_declared_width(store_dir: Path, db: aiosqlite.Connection, name: str) -> None:
    """Rewrite one corpus's `chunks_vec` declaration so it names no width at all.

    Through `writable_schema`, because nothing else can produce this: the extension refuses such a
    declaration at `CREATE`. What it stands in for is a database this build did not write — the
    population every other validation on the open path exists for.
    """
    registered = await registry.require(db, name)
    path = paths.knowledge_db_path(store_dir, registered.id)
    broken = sqlite3.connect(path)
    try:
        broken.execute("PRAGMA writable_schema = ON")
        broken.execute(
            "UPDATE sqlite_master SET sql = "
            "'CREATE VIRTUAL TABLE chunks_vec USING vec0 (chunk_id INTEGER PRIMARY KEY, embedding)'"
            " WHERE name = 'chunks_vec'"
        )
        broken.commit()
        broken.execute("PRAGMA writable_schema = OFF")
    finally:
        broken.close()
