"""Building a knowledge base's index: what one scan writes, and what the next one does about it.

Every test here runs a real build over a real directory. The scan's whole subject is a filesystem
and a database, and a fake of either would check this suite's beliefs about them rather than the
behaviour the corpus depends on.

`git_mode` is stated as `off` wherever a test is not about git, so what these assert does not
depend on whether the machine running the suite happens to keep its temporary directory inside a
repository.
"""

import os
from contextlib import AbstractAsyncContextManager
from pathlib import Path

import pytest

from tests.knowledge_fixtures import Corpus, add_request, open_corpus, open_index
from zikaron.core.knowledge import files, lifecycle, lock, pending, scan
from zikaron.core.knowledge.counters import SkipReason
from zikaron.core.knowledge.database import read_meta
from zikaron.core.knowledge.errors import (
    CorpusRootMissingError,
    DanglingKnowledgeBaseError,
    IndexerBusyError,
)
from zikaron.core.knowledge.meta import (
    LAST_SCAN_COMPLETED_AT_KEY,
    LAST_SCAN_GIT_MODE_EFFECTIVE_KEY,
    LAST_WALK_COMPLETED_AT_KEY,
    GitMode,
)
from zikaron.core.knowledge.paths import knowledge_db_path
from zikaron.core.knowledge.registry import require
from zikaron.core.knowledge.state import KnowledgeState

#: A pid no process can have, so "the holder is gone" is a fact rather than a race.
_DEAD_PID = 2**22 + 7


def _tree(root: Path, layout: dict[str, bytes]) -> Path:
    for relative, content in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


def _corpus_over(
    tmp_path: Path, layout: dict[str, bytes], **options: object
) -> AbstractAsyncContextManager[Corpus]:
    root = _tree(tmp_path / "corpus", layout)
    return open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF, **options))


async def _hold_the_lock(corpus: Corpus, *, pid: int) -> None:
    """Record a lock against this corpus as though another indexer had taken it."""
    async with open_index(corpus) as opened:
        await lock.acquire(
            opened.connection,
            pid=pid,
            host=lock.this_host(),
            started_at="2026-01-01T00:00:00+00:00",
        )
        await opened.connection.commit()


async def _build(corpus: Corpus) -> lifecycle.Refreshed:
    return await lifecycle.refresh(corpus.store_dir, corpus.db, corpus.config, name=corpus.name)


async def _indexed(corpus: Corpus) -> dict[str, files.IndexedFile]:
    async with open_index(corpus) as opened:
        return await files.load_all(opened.connection)


class TestAFirstBuild:
    async def test_it_records_a_row_for_every_admitted_file(self, tmp_path: Path) -> None:
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n", "docs/b.md": b"beta\n"}) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"a.md", "docs/b.md"}
        assert rows["a.md"].content_hash == files.content_hash(b"alpha\n")
        assert rows["a.md"].size == len(b"alpha\n")

    async def test_nothing_from_a_pruned_directory_reaches_the_index(self, tmp_path: Path) -> None:
        async with _corpus_over(
            tmp_path,
            {"kept.md": b"x", ".git/objects/ab/cdef": b"x", "node_modules/p/index.js": b"x"},
        ) as corpus:
            await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"kept.md"}

    async def test_a_corpus_with_no_indexable_file_completes_and_is_usable(
        self, tmp_path: Path
    ) -> None:
        """A root holding nothing indexable has completed a build, so `ok` with nothing in it is
        the true answer rather than a corpus that was never made."""
        async with _corpus_over(tmp_path, {"logo.png": b"\x89PNG"}) as corpus:
            refreshed = await _build(corpus)
        assert refreshed.status.summary.state is KnowledgeState.OK
        assert refreshed.status.summary.files_indexed == 0

    async def test_the_counters_describe_the_corpus_it_leaves_behind(self, tmp_path: Path) -> None:
        async with _corpus_over(
            tmp_path, {"a.md": b"alpha\n", "b.md": b"bb", "logo.png": b"\x89PNG"}
        ) as corpus:
            refreshed = await _build(corpus)
            counters = refreshed.result.counters
            async with open_index(corpus) as opened:
                assert counters.files_indexed == await files.count(opened.connection)
                assert counters.bytes_indexed == await files.total_size(opened.connection)
        assert counters.files_seen == 3
        assert counters.skipped == {SkipReason.DENIED_EXTENSION: 1}

    async def test_nothing_is_left_pending_and_the_scan_records_its_completion(
        self, tmp_path: Path
    ) -> None:
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                raw = await read_meta(opened.connection)
                assert await pending.count(opened.connection) == 0
        assert raw[LAST_SCAN_COMPLETED_AT_KEY] >= raw[LAST_WALK_COMPLETED_AT_KEY]
        assert raw[LAST_SCAN_GIT_MODE_EFFECTIVE_KEY] == GitMode.OFF.value

    async def test_the_lock_is_given_up_when_the_build_finishes(self, tmp_path: Path) -> None:
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            refreshed = await _build(corpus)
        assert refreshed.status.summary.state is KnowledgeState.OK
        assert refreshed.status.summary.files_remaining is None


class TestBuildingAgain:
    async def test_a_rescan_that_finds_nothing_changed_still_reports_the_whole_corpus(
        self, tmp_path: Path
    ) -> None:
        """The counters describe the corpus rather than the workload. Under the other reading a
        healthy corpus would advertise itself as empty the moment nothing changed — and that
        number is what a caller uses to choose between corpora."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n", "b.md": b"beta\n"}) as corpus:
            await _build(corpus)
            again = await _build(corpus)
        assert again.result.counters.files_indexed == 2
        assert again.result.counters.bytes_indexed == len(b"alpha\n") + len(b"beta\n")

    async def test_an_edited_file_is_reindexed(self, tmp_path: Path) -> None:
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            (corpus.root / "a.md").write_bytes(b"changed\n")
            await _build(corpus)
            rows = await _indexed(corpus)
        assert rows["a.md"].content_hash == files.content_hash(b"changed\n")

    async def test_a_file_whose_bytes_did_not_move_keeps_its_indexing_instant(
        self, tmp_path: Path
    ) -> None:
        """`indexed_at` records when the content was indexed rather than when it was last looked
        at, so an unchanged file is not rewritten."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            first = (await _indexed(corpus))["a.md"]
            await _build(corpus)
            second = (await _indexed(corpus))["a.md"]
        assert first == second

    async def test_a_new_file_is_picked_up(self, tmp_path: Path) -> None:
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            (corpus.root / "b.md").write_bytes(b"beta\n")
            await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"a.md", "b.md"}

    async def test_a_deleted_file_loses_its_row(self, tmp_path: Path) -> None:
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n", "b.md": b"beta\n"}) as corpus:
            await _build(corpus)
            (corpus.root / "b.md").unlink()
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"a.md"}
        assert refreshed.result.files_deleted == 1

    async def test_a_file_that_grows_past_the_cap_is_deleted_from_the_index(
        self, tmp_path: Path
    ) -> None:
        """A file can stop being part of the corpus without disappearing, and the corpus is
        exactly what the current walk admits."""
        async with _corpus_over(tmp_path, {"a.md": b"small"}, max_file_bytes=16) as corpus:
            await _build(corpus)
            assert set(await _indexed(corpus)) == {"a.md"}
            (corpus.root / "a.md").write_bytes(b"x" * 64)
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert rows == {}
        assert refreshed.result.counters.skipped == {SkipReason.OVER_SIZE_CAP: 1}

    async def test_a_file_that_becomes_binary_is_deleted_and_counted(self, tmp_path: Path) -> None:
        """The indexed text no longer corresponds to anything indexable, and serving it forever
        behind a stale flag is worse than removing it."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            (corpus.root / "a.md").write_bytes(b"\x00\x01\x02")
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert rows == {}
        assert refreshed.result.counters.skipped == {SkipReason.BINARY: 1}

    async def test_a_newly_excluded_file_is_deleted_without_being_read(
        self, tmp_path: Path
    ) -> None:
        """Configuration is persisted per corpus, so this is done by rebuilding the knowledge base
        with a different exclusion rather than by editing a global default."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n", "draft.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            assert set(await _indexed(corpus)) == {"a.md", "draft.md"}
            await lifecycle.remove(corpus.store_dir, corpus.db, corpus.config, name=corpus.name)
            await lifecycle.add(
                corpus.store_dir,
                corpus.db,
                corpus.config,
                add_request(
                    root,
                    git_mode=GitMode.OFF,
                    exclude_globs=("draft*",),
                    home=corpus.store_dir.parent / "not-the-home-directory",
                ),
            )
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"a.md"}
        assert refreshed.result.counters.skipped == {SkipReason.EXCLUDED_BY_GLOB: 1}


class TestEverySkipReasonIsReachable:
    async def test_the_walk_time_reasons_each_fire_exactly_once(self, tmp_path: Path) -> None:
        """A file silently missing from an index is indistinguishable from a file with nothing
        relevant in it; one is a legitimate answer and the other is a defect, so each refusal is
        counted under a reason a report can name."""
        root = _tree(
            tmp_path / "corpus",
            {
                "kept.md": b"x",
                "logo.png": b"\x89PNG",
                "big.md": b"y" * 64,
                "draft.md": b"z",
                "binary.dat": b"\x00\x01",
                "bad.md": b"\xff\xfe",
            },
        )
        (root / "link.md").symlink_to(root / "kept.md")
        async with open_corpus(
            tmp_path,
            add_request(root, git_mode=GitMode.OFF, exclude_globs=("draft*",), max_file_bytes=32),
        ) as corpus:
            refreshed = await _build(corpus)
        assert refreshed.result.counters.skipped == {
            SkipReason.DENIED_EXTENSION: 1,
            SkipReason.OVER_SIZE_CAP: 1,
            SkipReason.EXCLUDED_BY_GLOB: 1,
            SkipReason.SYMLINK: 1,
            SkipReason.BINARY: 1,
            SkipReason.DECODE_ERROR: 1,
        }

    async def test_an_unreadable_file_is_counted_and_keeps_its_pending_row(
        self, tmp_path: Path
    ) -> None:
        """The work its row names has not been done, so a search keeps reporting results for it as
        stale until a later walk decides otherwise."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            (corpus.root / "a.md").chmod(0o000)
            try:
                refreshed = await _build(corpus)
                async with open_index(corpus) as opened:
                    left = await pending.paths(opened.connection)
            finally:
                (corpus.root / "a.md").chmod(0o600)
        assert refreshed.result.counters.skipped == {SkipReason.UNREADABLE: 1}
        assert left == ["a.md"]
        assert refreshed.result.files_remaining == 1


class TestAFileThatMovesBetweenTheTwoReads:
    """A scan reads a changed file twice — once to notice, once to index — and the file can move
    in between. Each of these stages that window rather than racing it, because a race is not
    reproducible and what matters is which phase ends up accounting for the file."""

    async def test_a_file_that_grows_between_the_stat_and_the_noticing_read_is_deleted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The size the walk checked was read before the file was opened. Refusing at the read is
        the same size rule arriving later, not a new one."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            monkeypatch.setattr(files, "read_bounded", lambda *_args: SkipReason.OVER_SIZE_CAP)
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert rows == {}
        assert refreshed.result.counters.skipped == {SkipReason.OVER_SIZE_CAP: 1}
        assert refreshed.result.files_deleted == 1

    async def test_a_new_file_that_grows_before_the_indexing_read_is_skipped_not_stored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file with no row is never read by the walk, so the index phase is where its size is
        rediscovered — and a path with no row serves nothing, so recording the skip is the whole
        of the disposal."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            monkeypatch.setattr(files, "read_bounded", lambda *_args: SkipReason.OVER_SIZE_CAP)
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
            async with open_index(corpus) as opened:
                assert await pending.count(opened.connection) == 0
        assert rows == {}
        assert refreshed.result.counters.skipped == {SkipReason.OVER_SIZE_CAP: 1}
        assert refreshed.result.files_deleted == 0

    async def test_a_file_unreadable_at_the_first_read_is_disposed_of_by_the_second(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The walk could answer neither of its questions, so the file goes forward as changed and
        the index phase's own read decides. Finding a file no longer indexable *and* already
        indexed is how a deletion reaches the index phase — by this route, and by the one below,
        where the walk's read succeeded and the file changed again before the second."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            answers: list[bytes | SkipReason] = [SkipReason.UNREADABLE, b"\x00\x01\x02"]
            monkeypatch.setattr(files, "read_bounded", lambda *_args: answers.pop(0))
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert rows == {}
        assert refreshed.result.counters.skipped == {SkipReason.BINARY: 1}
        assert refreshed.result.files_deleted == 1

    async def test_a_file_that_grows_between_the_two_reads_is_deleted_by_the_second(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other route into an index-phase deletion, and the one an enumeration written around
        text detection alone leaves out: the walk's read succeeds and finds ordinary changed text,
        so the file enters the pending list — and by the time the indexing read runs it is past the
        cap. The same size rule, arriving one phase later."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}, max_file_bytes=64) as corpus:
            await _build(corpus)
            (corpus.root / "a.md").write_bytes(b"changed\n")
            answers: list[bytes | SkipReason] = [b"changed\n", SkipReason.OVER_SIZE_CAP]
            monkeypatch.setattr(files, "read_bounded", lambda *_args: answers.pop(0))
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
            async with open_index(corpus) as opened:
                assert await pending.count(opened.connection) == 0
        assert rows == {}
        assert refreshed.result.counters.skipped == {SkipReason.OVER_SIZE_CAP: 1}
        assert refreshed.result.files_deleted == 1


class TestTheWalkReportsProgressAsItGoes:
    async def test_it_is_pulled_in_batches_and_flushes_what_it_has_seen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The seen count is the only evidence a build is progressing before it has worked out
        what changed, so it reaches the database during the walk rather than at the end of it."""
        layout = {f"f{index:02d}.md": b"body\n" for index in range(7)}
        monkeypatch.setattr(scan, "_WALK_BATCH", 2)
        flushes: list[int] = []
        real = scan._write_counters

        async def _counting(db: object, counters: object, extra: object = None) -> None:
            flushes.append(1)
            await real(db, counters, extra)  # type: ignore[arg-type]

        async with _corpus_over(tmp_path, layout) as corpus:
            monkeypatch.setattr(scan, "_write_counters", _counting)
            refreshed = await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == set(layout)
        assert refreshed.result.counters.files_seen == 7
        # Four batches of at most two, then the empty pull that ends the walk.
        assert len(flushes) >= 4


class TestWhenABuildRefuses:
    async def test_a_missing_root_keeps_the_index_rather_than_emptying_it(
        self, tmp_path: Path
    ) -> None:
        """An empty walk would read as *every indexed file has been deleted*, which would destroy
        a whole index on the strength of an unmounted drive."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _build(corpus)
            (corpus.root / "a.md").unlink()
            corpus.root.rmdir()
            with pytest.raises(CorpusRootMissingError):
                await _build(corpus)
            rows = await _indexed(corpus)
        assert set(rows) == {"a.md"}

    async def test_a_knowledge_base_with_no_database_is_refused_rather_than_invented(
        self, tmp_path: Path
    ) -> None:
        """Everything that says what this corpus is lived in the file that is gone, so a build has
        nothing to walk — and the way back is to remove the name and add it again."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            registered = await require(corpus.db, corpus.name)
            knowledge_db_path(corpus.store_dir, registered.id).unlink()
            with pytest.raises(DanglingKnowledgeBaseError, match="remove it and add it again"):
                await _build(corpus)

    async def test_a_build_refuses_while_a_live_indexer_holds_the_lock(
        self, tmp_path: Path
    ) -> None:
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _hold_the_lock(corpus, pid=os.getpid())
            with pytest.raises(IndexerBusyError):
                await _build(corpus)

    async def test_a_refused_build_does_not_release_the_lock_it_never_took(
        self, tmp_path: Path
    ) -> None:
        """Releasing on the way out of a refusal would take the lock away from whoever holds it."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _hold_the_lock(corpus, pid=os.getpid())
            with pytest.raises(IndexerBusyError):
                await _build(corpus)
            async with open_index(corpus) as opened:
                assert lock.is_held(await read_meta(opened.connection))


class TestCrashAndResume:
    async def test_a_build_that_dies_leaves_its_pending_rows_and_the_next_one_finishes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Those rows are the only thing keeping a stale flag honest between the crash and the
        next scan, so nothing sweeps them — a sweep would look tidy and delete the signal."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n", "b.md": b"beta\n"}) as corpus:
            real = scan._dispose

            async def _die_on_the_second(*args: object, **kwargs: object) -> None:
                if _die_on_the_second.seen:  # type: ignore[attr-defined]
                    raise RuntimeError("the indexer died")
                _die_on_the_second.seen = True  # type: ignore[attr-defined]
                await real(*args, **kwargs)  # type: ignore[arg-type]

            _die_on_the_second.seen = False  # type: ignore[attr-defined]
            monkeypatch.setattr(scan, "_dispose", _die_on_the_second)
            with pytest.raises(RuntimeError, match="the indexer died"):
                await _build(corpus)
            async with open_index(corpus) as opened:
                assert await pending.paths(opened.connection) == ["b.md"]
                assert set(await files.load_all(opened.connection)) == {"a.md"}
                raw = await read_meta(opened.connection)
            assert LAST_SCAN_COMPLETED_AT_KEY not in raw

            monkeypatch.setattr(scan, "_dispose", real)
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await pending.count(opened.connection) == 0
                assert set(await files.load_all(opened.connection)) == {"a.md", "b.md"}

    async def test_a_dead_build_leaves_a_lock_the_next_build_reclaims(self, tmp_path: Path) -> None:
        """A wrongly reclaimed indexer costs one rescan, which resuming from the files table makes
        idempotent — so a pid that is gone is enough evidence here."""
        async with _corpus_over(tmp_path, {"a.md": b"alpha\n"}) as corpus:
            await _hold_the_lock(corpus, pid=_DEAD_PID)
            refreshed = await _build(corpus)
        assert refreshed.status.summary.state is KnowledgeState.OK
