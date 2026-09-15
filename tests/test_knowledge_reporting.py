"""What `list` and `status` report when a corpus is not in good order, and the rules behind it.

Two claims are load-bearing and easy to get subtly wrong. A knowledge base whose database is
**present but unreadable** must report `error` rather than *needs a build*, because a build does
not obviously repair a corrupt file and an operator needs the difference. And `files_remaining` is
a count only under a rule with a persisted discriminator in it, because "the walk finished and
nothing changed" and "the walk is still running" are otherwise byte-identical states.
"""

import uuid
from pathlib import Path

import pytest

from tests.knowledge_fixtures import add_base, config_for, corpus_root, open_store
from zikaron.core.knowledge import ddl as knowledge_ddl
from zikaron.core.knowledge import lifecycle, meta, reporting
from zikaron.core.knowledge.registry import KnowledgeBase
from zikaron.core.knowledge.state import KnowledgeState
from zikaron.core.store.connection import open_connection


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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
            assert report.summary.state is KnowledgeState.OK


class TestHowManyFilesAreLeft:
    """A number only when the lock is held **and** the walk phase's own completion instant is at
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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (before,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
            assert before.details is not None
            assert before.details.git_mode_effective is None

            await _write_meta(created.database_path, last_scan_git_mode_effective="off")
            (after,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
            assert after.details is not None
            assert after.details.git_mode_effective is meta.GitMode.OFF

    async def test_an_unrecognised_recorded_git_mode_reports_nothing_rather_than_guessing(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (store_dir, db):
            config = config_for(tmp_path)
            created = await _add(tmp_path, store_dir, db)
            await _write_meta(created.database_path, last_scan_git_mode_effective="sideways")

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (report,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
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

            (listed,) = (await lifecycle.list_bases(store_dir, db, config)).knowledge_bases
            (detailed,) = (
                await lifecycle.status(store_dir, db, config, name="docs")
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
