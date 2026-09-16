"""What `list` and `status` report when a corpus is not in good order, and the rules behind it.

Two claims are load-bearing and easy to get subtly wrong. A knowledge base whose database is
**present but unreadable** must report `error` rather than *needs a build*, because a build does
not obviously repair a corrupt file and an operator needs the difference. And `files_remaining` is
a count only under a rule with a persisted discriminator in it, because "the walk finished and
nothing changed" and "the walk is still running" are otherwise byte-identical states.
"""

import os
import uuid
from pathlib import Path
from typing import Final

import pytest

from tests.knowledge_fixtures import add_base, config_for, corpus_root, open_store
from zikaron.core.clock import timestamp
from zikaron.core.knowledge import ddl as knowledge_ddl
from zikaron.core.knowledge import lifecycle, lock, meta, reporting
from zikaron.core.knowledge.registry import KnowledgeBase
from zikaron.core.knowledge.state import KnowledgeState
from zikaron.core.store.connection import open_connection

#: A pid no process can have, so *not running* is a fact rather than a race with the scheduler.
_DEAD_PID: Final = 2**22 + 7


async def _write_meta(db_path: Path, **rows: str) -> None:
    """Write `meta` rows a build would write, directly.

    Directly because no build exists to write them: what is under test is the reader, and stubbing
    the reader instead would assert this suite's belief back to itself.
    """
    db, _inode = await open_connection(db_path, pragmas=knowledge_ddl.PRAGMAS, existing_only=True)
    try:
        for key, value in rows.items():
            await db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        await db.commit()
    finally:
        await db.close()


async def _add(tmp_path: Path, store_dir: Path, db: object, **kwargs: object) -> lifecycle.Created:
    config = config_for(tmp_path)
    return await add_base(
        store_dir,
        db,  # type: ignore[arg-type]
        config,
        lifecycle.AddRequest(
            name=str(kwargs.get("name", "docs")),
            root=corpus_root(tmp_path),
            description="a corpus",
        ),
    )


class TestADatabaseThatWillNotOpen:
    async def test_a_corrupt_database_reports_error_rather_than_needing_a_build(
        self, tmp_path: Path
    ) -> None:
        """Kept apart from `reindex_required` deliberately: a refresh repairs that one and does
        not obviously repair this one, and collapsing them would send an operator to run a build
        against a corrupt file forever."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            created.database_path.write_bytes(b"this is not a SQLite database")

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.state is KnowledgeState.ERROR
            assert report.details is None
            assert report.summary.name == "docs"

    async def test_a_database_whose_meta_is_gone_reports_error(self, tmp_path: Path) -> None:
        """A database missing every required key cannot say what encoder produced its vectors, so
        it is unreadable in the sense that matters rather than merely incomplete."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            dropped, _inode = await open_connection(
                created.database_path, pragmas=knowledge_ddl.PRAGMAS, existing_only=True
            )
            try:
                await dropped.execute("DROP TABLE meta")
                await dropped.commit()
            finally:
                await dropped.close()

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.state is KnowledgeState.ERROR


class TestAMissingRoot:
    async def test_a_corpus_whose_directory_is_gone_says_so(self, tmp_path: Path) -> None:
        """The index is retained rather than deleted, ready for the root's return — but the state
        says the corpus cannot be trusted, because a result pointing at a file nobody can read is
        worse than no result."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            root = Path(corpus_root(tmp_path))
            for child in root.iterdir():
                child.unlink()
            root.rmdir()

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.state is KnowledgeState.ROOT_MISSING
            assert created.database_path.is_file(), "the index is retained, not deleted"


class TestAnEncoderThatNoLongerAgrees:
    async def test_a_changed_embed_model_puts_the_corpus_into_needing_a_build(
        self, tmp_path: Path
    ) -> None:
        """The one divergence this store cannot serve around: vectors labelled with a model that
        did not produce them."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(created.database_path, embed_model="some/other-model")

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.state is KnowledgeState.REINDEX_REQUIRED

    async def test_a_changed_tuning_key_does_not(self, tmp_path: Path) -> None:
        """Same seeding mechanism, opposite policy: the tuning keys are absorbed per corpus at
        creation precisely so that changing a global default does not invalidate a built index."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(
                created.database_path,
                chunk_max_tokens="900",
                rrf_k="30",
                last_scan_completed_at="2026-01-01T00:00:00+00:00",
            )

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.state is KnowledgeState.OK


class TestHowManyFilesAreLeft:
    """A number only when a build is running **and** the walk phase's own completion instant is at
    least as recent as the build's start. Every other case is `None`, because `0` would read as
    *nothing left to do* when the truth is *not yet counted*."""

    @pytest.mark.parametrize(
        ("rows", "expected"),
        [
            pytest.param({}, None, id="no build running"),
            pytest.param({"lock_pid": "1"}, None, id="lock held, nothing else recorded"),
            pytest.param(
                {"lock_pid": "1", "last_scan_started_at": "2026-01-02T00:00:00+00:00"},
                None,
                id="walk has not finished",
            ),
            pytest.param(
                {
                    "lock_pid": "1",
                    "last_scan_started_at": "2026-01-02T00:00:00+00:00",
                    "last_walk_completed_at": "2026-01-01T00:00:00+00:00",
                },
                None,
                id="the recorded walk predates this build",
            ),
            pytest.param(
                {
                    "lock_pid": "1",
                    "last_scan_started_at": "2026-01-01T00:00:00+00:00",
                    "last_walk_completed_at": "2026-01-02T00:00:00+00:00",
                },
                2,
                id="lock held and the walk finished",
            ),
        ],
    )
    async def test_the_rule(
        self, tmp_path: Path, rows: dict[str, str], expected: int | None
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            pending, _inode = await open_connection(
                created.database_path, pragmas=knowledge_ddl.PRAGMAS, existing_only=True
            )
            try:
                await pending.execute("INSERT INTO pending VALUES ('a.md', 'now')")
                await pending.execute("INSERT INTO pending VALUES ('b.md', 'now')")
                await pending.commit()
            finally:
                await pending.close()
            if rows:
                await _write_meta(created.database_path, **rows)

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.files_remaining == expected


class TestTheDiagnosticFields:
    async def test_the_git_mode_the_last_build_used_is_reported_not_recomputed(
        self, tmp_path: Path
    ) -> None:
        """What explains an indexed corpus is the mode the build that produced it actually used,
        not whatever the environment happens to say when somebody asks."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)

            (before,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert before.details is not None
            assert before.details.git_mode_effective is None

            await _write_meta(created.database_path, last_scan_git_mode_effective="off")
            (after,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert after.details is not None
            assert after.details.git_mode_effective is meta.GitMode.OFF

    async def test_an_unrecognised_recorded_git_mode_reports_nothing_rather_than_guessing(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(created.database_path, last_scan_git_mode_effective="sideways")

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert report.details.git_mode_effective is None

    async def test_a_counter_somebody_corrupted_reports_zero_rather_than_refusing(
        self, tmp_path: Path
    ) -> None:
        """A diagnostic report is the wrong place to refuse over a counter. The identity keys,
        which decide whether a corpus can be served at all, are validated strictly instead — and
        that difference is asserted here rather than left to a reader to infer."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(created.database_path, files_indexed="not a number")

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.files_indexed == 0
            assert report.summary.state is KnowledgeState.REINDEX_REQUIRED

    async def test_every_skip_reason_is_reported_with_its_prefix_dropped(
        self, tmp_path: Path
    ) -> None:
        """The field names map to `meta` keys by dropping `skipped_`, stated as a rule so the
        difference is deliberate rather than drift."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await _add(tmp_path, store_dir, db)

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert set(report.details.skipped) == {
                key.removeprefix("skipped_") for key in meta.SKIP_REASON_KEYS
            }
            assert set(report.details.skipped.values()) == {0}

    async def test_a_summary_carries_only_what_a_caller_needs_to_choose(
        self, tmp_path: Path
    ) -> None:
        """`list` is `status` projected down, never a parallel answer — so the two share one
        gathering step and the summary is literally a field of the fuller report."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await _add(tmp_path, store_dir, db)

            (listed,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            (detailed,) = (
                await reporting.status(store_dir, db, config, name="docs")
            ).knowledge_bases
            assert listed.summary == detailed.summary


def test_a_knowledge_base_with_no_database_reports_no_diagnostics_rather_than_zeroes() -> None:
    """Absent rather than zeroed, so a caller is never handed a confident value that no stored one
    backs. `files_indexed` is the exception, and it is a claim about availability: a corpus with no
    readable database has nothing that can be served."""
    registered = KnowledgeBase(id=uuid.uuid4(), name="docs", description="d", created_at="now")
    report = reporting.without_details(registered, KnowledgeState.REINDEX_REQUIRED)
    assert report.details is None
    assert report.summary.files_indexed == 0
    assert report.summary.files_remaining is None


class TestWhoIsBuildingThisCorpus:
    """`state: indexing` says a build is running and nothing more, and two situations it covers are
    ones it cannot explain on its own: a lock recorded on another machine, which nothing here ever
    reclaims, and a local build whose process has died, which is the only trace a detached build
    that failed leaves at all."""

    async def test_no_lock_is_reported_as_no_lock(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            await _add(tmp_path, store_dir, db)

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert report.details.lock is None

    async def test_a_running_local_build_is_reported_as_live(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(
                created.database_path,
                lock_pid=str(os.getpid()),
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert report.details.lock is not None
            assert report.details.lock.live is True
            assert report.details.lock.pid == os.getpid()
            assert report.details.lock.age_seconds is not None

    async def test_a_local_build_whose_process_is_gone_is_reported_as_dead(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(
                created.database_path,
                lock_pid=str(_DEAD_PID),
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert report.details.lock is not None
            assert report.details.lock.live is False

    async def test_a_foreign_build_is_reported_without_a_verdict_on_it(
        self, tmp_path: Path
    ) -> None:
        """A local process probe says nothing about a process on another machine, and a verdict
        either way would be a guess — one of which starts a second writer."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(
                created.database_path,
                lock_pid=str(_DEAD_PID),
                lock_host="another-machine",
                lock_started_at=timestamp(),
            )

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert report.details.lock is not None
            assert report.details.lock.live is None
            assert report.details.lock.host == "another-machine"

    async def test_a_lock_whose_instant_cannot_be_read_has_no_age(self, tmp_path: Path) -> None:
        """Only a hand-edited row produces it, and the answer is to lose that one field rather than
        the report a human is reading in order to work out what happened."""
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(
                created.database_path,
                lock_pid=str(_DEAD_PID),
                lock_host=lock.this_host(),
                lock_started_at="the other day",
            )

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert report.details.lock is not None
            assert report.details.lock.age_seconds is None

    async def test_a_lock_whose_pid_cannot_be_read_gets_no_verdict_either(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(
                created.database_path,
                lock_pid="not-a-pid",
                lock_host=lock.this_host(),
                lock_started_at=timestamp(),
            )

            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            assert report.details is not None
            assert report.details.lock is not None
            assert report.details.lock.pid is None
            assert report.details.lock.live is None


class TestWhatCountsAsABuildInFlight:
    """`indexing` means *a scan is in flight*, and lock rows outlive the build that wrote them. So
    the test is a liveness one rather than a presence one — but only where liveness can be answered
    from here, which is the same line every other consumer of the lock draws. `state` and
    `files_remaining` both key off it, because `null` is what tells a caller no build is running
    and two answers to that would be one too many."""

    async def _report(self, tmp_path: Path, **rows: str) -> reporting.Status:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(
                created.database_path,
                last_scan_started_at="2026-01-01T00:00:00+00:00",
                last_walk_completed_at="2026-01-02T00:00:00+00:00",
                last_scan_completed_at="2026-01-03T00:00:00+00:00",
                **rows,
            )
            (report,) = (await reporting.list_bases(store_dir, db, config)).knowledge_bases
            return report

    async def test_a_live_local_build_is_a_build_in_flight(self, tmp_path: Path) -> None:
        report = await self._report(
            tmp_path,
            lock_pid=str(os.getpid()),
            lock_host=lock.this_host(),
            lock_started_at=timestamp(),
        )
        assert report.summary.state is KnowledgeState.INDEXING
        assert report.summary.files_remaining == 0

    async def test_a_build_on_another_machine_is_too(self, tmp_path: Path) -> None:
        """Nothing here can show a foreign process has stopped, and the reading that assumes it has
        is the one that lets two indexers write one database."""
        report = await self._report(
            tmp_path,
            lock_pid=str(_DEAD_PID),
            lock_host="another-machine",
            lock_started_at=timestamp(),
        )
        assert report.summary.state is KnowledgeState.INDEXING
        assert report.summary.files_remaining == 0

    async def test_a_killed_local_build_is_not(self, tmp_path: Path) -> None:
        """Its rows survive on purpose. Reported as a scan in flight, a corpus that is simply built
        and idle would say so for as long as nobody started another build — with a count beside it
        that could never move again."""
        report = await self._report(
            tmp_path,
            lock_pid=str(_DEAD_PID),
            lock_host=lock.this_host(),
            lock_started_at=timestamp(),
        )
        assert report.summary.state is KnowledgeState.OK
        assert report.summary.files_remaining is None
        assert report.details is not None
        assert report.details.lock is not None, "and the holder is what says a build died"

    async def test_a_corpus_nobody_is_building_is_not_either(self, tmp_path: Path) -> None:
        report = await self._report(tmp_path)
        assert report.summary.state is KnowledgeState.OK
        assert report.summary.files_remaining is None
