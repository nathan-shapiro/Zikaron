"""What stops a build, and the two ways one caller's answer differs from another's.

The classification itself is the subject: one function decides it, a sweep *reports* what it
decided and a named call *raises* it, and the property that matters is that the two can never
disagree. So every obstacle below is exercised through both surfaces, and the ordering — which
condition wins when two hold at once — is exercised deliberately rather than left to whichever
fixture happened to produce one condition at a time.
"""

import os
from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.knowledge_fixtures import (
    DEAD_PID,
    add_base,
    add_request,
    config_for,
    corpus_root,
    open_store,
    write_meta,
)
from zikaron.core.clock import timestamp
from zikaron.core.knowledge import builds, lock
from zikaron.core.knowledge.builds import BuildObstacle
from zikaron.core.knowledge.errors import (
    CorpusRootMissingError,
    DanglingKnowledgeBaseError,
    IndexerBusyError,
    InvalidNameError,
    UnknownKnowledgeBaseError,
)
from zikaron.core.knowledge.state import KnowledgeState


async def _planted(tmp_path: Path, store_dir: Path, db: object, name: str = "docs") -> Path:
    """Register one corpus and return the path of the database it created."""
    created = await add_base(
        store_dir,
        db,  # type: ignore[arg-type]
        config_for(tmp_path),
        add_request(corpus_root(tmp_path, name), name=name),
    )
    return created.database_path


def _remove_tree(root: Path) -> None:
    for child in root.iterdir():
        child.unlink()
    root.rmdir()


async def _hold_the_lock(db_path: Path, *, pid: int) -> None:
    await write_meta(
        db_path, lock_pid=str(pid), lock_host=lock.this_host(), lock_started_at=timestamp()
    )


class TestWhatStopsABuild:
    async def test_an_ordinary_corpus_may_start(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            await _planted(tmp_path, store_dir, db)
            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.may_start
            assert planned.obstacle is None
            assert planned.refusal is None

    async def test_a_live_local_lock_is_already_indexing(self, tmp_path: Path) -> None:
        """This process's own pid, so *running* is a fact rather than a race: a build that cannot
        be shown to be dead is one a second build must not join."""
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            await _hold_the_lock(db_path, pid=os.getpid())

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.obstacle is BuildObstacle.ALREADY_INDEXING
            assert isinstance(planned.refusal, IndexerBusyError)

    async def test_a_dead_local_lock_does_not_stop_one(self, tmp_path: Path) -> None:
        """Lock rows survive a killed build deliberately, and treating those as a live writer would
        make one crash enough to make a knowledge base unbuildable for good."""
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            await _hold_the_lock(db_path, pid=DEAD_PID)

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.may_start

    async def test_a_missing_database_is_no_database(self, tmp_path: Path) -> None:
        """Everything that says what this corpus indexes lived in that file, so a build has
        nothing to walk and nothing to invent one from."""
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            db_path.unlink()

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.obstacle is BuildObstacle.NO_DATABASE
            assert isinstance(planned.refusal, DanglingKnowledgeBaseError)

    async def test_a_missing_root_is_root_missing(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            await _planted(tmp_path, store_dir, db)
            _remove_tree(corpus_root(tmp_path))

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.obstacle is BuildObstacle.ROOT_MISSING
            assert isinstance(planned.refusal, CorpusRootMissingError)

    async def test_a_database_that_will_not_open_is_unreadable(self, tmp_path: Path) -> None:
        """And the refusal is the driver's own exception rather than one invented here: nothing
        this module could write would say what actually went wrong, and a build does not repair
        it."""
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            db_path.write_bytes(b"this is not a SQLite database")

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.obstacle is BuildObstacle.UNREADABLE
            assert planned.refusal is not None
            assert not isinstance(planned.refusal, DanglingKnowledgeBaseError)

    async def test_a_corpus_needing_a_rebuild_may_still_start(self, tmp_path: Path) -> None:
        """An encoder mismatch is `reindex_required` and is emphatically *not* an obstacle: the
        build is what repairs it, and refusing here would leave the one state nothing else
        clears."""
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            await write_meta(db_path, embed_model="some/other-model")

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.status.summary.state is KnowledgeState.REINDEX_REQUIRED
            assert planned.may_start


class TestTheOrderTwoConditionsAreResolvedIn:
    """Two obstacles can hold at once, and which is reported is behaviour rather than an accident:
    it is the same precedence every other reader of a corpus's state already sees."""

    async def test_a_missing_root_outranks_a_live_lock(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            await _hold_the_lock(db_path, pid=os.getpid())
            _remove_tree(corpus_root(tmp_path))

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.obstacle is BuildObstacle.ROOT_MISSING

    async def test_an_unreadable_database_outranks_a_missing_root(self, tmp_path: Path) -> None:
        """Nothing can read a root path out of a database that will not open, so the unreadable
        answer is the only one this condition can honestly give."""
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            _remove_tree(corpus_root(tmp_path))
            db_path.write_bytes(b"this is not a SQLite database")

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            assert planned.obstacle is BuildObstacle.UNREADABLE


class TestWhichCorporaAreAnsweredFor:
    async def test_no_names_plans_every_registered_corpus(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            await _planted(tmp_path, store_dir, db, name="docs")
            await _planted(tmp_path, store_dir, db, name="runbooks")

            planned = await builds.plan(store_dir, db, config_for(tmp_path), names=None)
            assert {entry.knowledge_base.name for entry in planned} == {"docs", "runbooks"}

    async def test_no_names_over_an_empty_store_plans_nothing(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            assert await builds.plan(store_dir, db, config_for(tmp_path), names=None) == ()

    async def test_names_are_answered_in_the_order_given(self, tmp_path: Path) -> None:
        """So a caller can line the answers up against what it asked for without matching on
        names."""
        async with open_store(tmp_path) as (store_dir, db):
            await _planted(tmp_path, store_dir, db, name="docs")
            await _planted(tmp_path, store_dir, db, name="runbooks")

            planned = await builds.plan(
                store_dir, db, config_for(tmp_path), names=["runbooks", "docs"]
            )
            assert [entry.knowledge_base.name for entry in planned] == ["runbooks", "docs"]

    async def test_one_corpus_being_stopped_does_not_stop_the_others(self, tmp_path: Path) -> None:
        """The whole reason a sweep reports rather than raises: failing it for one corpus's sake
        would deny the rest a build they could have had."""
        async with open_store(tmp_path) as (store_dir, db):
            broken = await _planted(tmp_path, store_dir, db, name="docs")
            await _planted(tmp_path, store_dir, db, name="runbooks")
            broken.unlink()

            planned = await builds.plan(store_dir, db, config_for(tmp_path), names=None)
            by_name = {entry.knowledge_base.name: entry for entry in planned}
            assert by_name["docs"].obstacle is BuildObstacle.NO_DATABASE
            assert by_name["runbooks"].may_start

    @pytest.mark.parametrize(
        ("names", "expected"),
        [
            pytest.param(["absent"], UnknownKnowledgeBaseError, id="unknown"),
            pytest.param(["  "], InvalidNameError, id="blank"),
        ],
    )
    async def test_a_name_nothing_answers_for_fails_the_call(
        self, tmp_path: Path, names: Iterable[str], expected: type[Exception]
    ) -> None:
        """A fact about the request rather than about a corpus: there is no corpus to report it
        against, so it is raised rather than carried in a result."""
        async with open_store(tmp_path) as (store_dir, db):
            await _planted(tmp_path, store_dir, db)
            with pytest.raises(expected):
                await builds.plan(store_dir, db, config_for(tmp_path), names=list(names))


class TestPrepare:
    """The named form raises what the sweep would have reported, from the same decision."""

    async def test_it_returns_the_corpus_when_nothing_stops_a_build(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            await _planted(tmp_path, store_dir, db)
            registered = await builds.prepare(store_dir, db, config_for(tmp_path), name="DOCS")
            assert registered.name == "docs"

    @pytest.mark.parametrize(
        ("break_it", "expected"),
        [
            pytest.param("unlink", DanglingKnowledgeBaseError, id="no database"),
            pytest.param("root", CorpusRootMissingError, id="root missing"),
            pytest.param("lock", IndexerBusyError, id="already indexing"),
        ],
    )
    async def test_it_raises_the_refusal_the_sweep_would_have_reported(
        self, tmp_path: Path, break_it: str, expected: type[Exception]
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            db_path = await _planted(tmp_path, store_dir, db)
            if break_it == "unlink":
                db_path.unlink()
            elif break_it == "root":
                _remove_tree(corpus_root(tmp_path))
            else:
                await _hold_the_lock(db_path, pid=os.getpid())

            (planned,) = await builds.plan(store_dir, db, config_for(tmp_path), names=["docs"])
            with pytest.raises(expected) as raised:
                await builds.prepare(store_dir, db, config_for(tmp_path), name="docs")
            assert str(raised.value) == str(planned.refusal), (
                "the raised message and the reported one are built once, from the same decision"
            )
