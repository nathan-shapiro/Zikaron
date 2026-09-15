"""The invariants a build must hold, each tested by trying to break it.

- **A chunk's path always names a row in `files`, and `files.chunk_count` equals that path's chunk
  count.** No foreign key spans these tables — no usable declarative cascade exists for a `vec0`
  table or for external-content full text — so the per-file transaction is the only thing that can
  maintain them.
- **`chunks.part_index` counts from 0, and a chunk's line range is `1 <= start <= end`.** These
  are row constraints, because a writer that got one wrong would otherwise produce a row that
  reads back plausibly and points at nothing.
- **A file's rows move in a single transaction, never partially visible.**
- **A path in `pending` names a file whose row, if any, predates the current walk.** The table is
  emptied by the index phase disposing of every path, or by the walk phase replacing it wholesale
  — never by anything else, and in particular never by an indexer exiting. Two survivals are
  correct and must not be swept: rows left by a crash, and a path whose disposal could not
  complete.

Each test is written to **fail if the invariant is violated** rather than to demonstrate the happy
path. Those that concern chunks are exercised against rows written by hand, because a build that
has no chunker to run writes none — which makes them checks that keep holding rather than checks
of something already there.
"""

from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import Corpus, add_request, open_corpus, open_index
from zikaron.core.knowledge import files, lifecycle, pending, scan
from zikaron.core.knowledge.meta import GitMode

_CHUNK = "INSERT INTO chunks (path, part_index, start_line, end_line, text) VALUES (?, ?, ?, ?, ?)"


def _tree(root: Path, layout: dict[str, bytes]) -> Path:
    for relative, content in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return root


async def _build(corpus: Corpus) -> lifecycle.Refreshed:
    return await lifecycle.refresh(corpus.store_dir, corpus.db, corpus.config, name=corpus.name)


async def _orphaned_chunk_paths(db: aiosqlite.Connection) -> list[str]:
    rows = await db.execute_fetchall(
        "SELECT chunks.path FROM chunks LEFT JOIN files ON files.path = chunks.path "
        "WHERE files.path IS NULL"
    )
    return [str(path) for (path,) in rows]


async def _disagreeing_chunk_counts(db: aiosqlite.Connection) -> list[str]:
    rows = await db.execute_fetchall(
        "SELECT files.path FROM files LEFT JOIN chunks ON chunks.path = files.path "
        "GROUP BY files.path HAVING files.chunk_count != count(chunks.id)"
    )
    return [str(path) for (path,) in rows]


class TestAChunkAlwaysNamesAnIndexedFile:
    async def test_a_built_corpus_holds_no_orphaned_chunk(self, tmp_path: Path) -> None:
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await _orphaned_chunk_paths(opened.connection) == []

    async def test_the_query_that_guards_it_can_actually_see_a_violation(
        self, tmp_path: Path
    ) -> None:
        """A guard that never fires proves nothing, so the oracle is shown failing on a row that
        violates the invariant before it is trusted on rows that do not."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute(_CHUNK, ("gone.md", 0, 1, 1, "x"))
                assert await _orphaned_chunk_paths(opened.connection) == ["gone.md"]
                await opened.connection.rollback()

    async def test_deleting_a_file_takes_its_chunks_with_it(self, tmp_path: Path) -> None:
        """No declarative cascade exists across these tables, so a deletion that removed only the
        `files` row would leave chunks pointing at a file the corpus no longer has."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            (corpus.root / "b.md").unlink()
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await _orphaned_chunk_paths(opened.connection) == []


class TestTheChunkCountAgreesWithTheChunks:
    async def test_a_built_corpus_agrees_everywhere(self, tmp_path: Path) -> None:
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n", "docs/b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await _disagreeing_chunk_counts(opened.connection) == []

    async def test_the_query_that_guards_it_can_actually_see_a_violation(
        self, tmp_path: Path
    ) -> None:
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute(_CHUNK, ("a.md", 0, 1, 1, "alpha"))
                assert await _disagreeing_chunk_counts(opened.connection) == ["a.md"]
                await opened.connection.rollback()


class TestAChunksOwnCoordinatesAreConstrained:
    @pytest.mark.parametrize(
        "row",
        [
            ("a.md", -1, 1, 1, "x"),
            ("a.md", 0, 0, 1, "x"),
            ("a.md", 0, 5, 4, "x"),
        ],
    )
    async def test_a_row_that_would_point_at_nothing_is_refused(
        self, tmp_path: Path, row: tuple[str, int, int, int, str]
    ) -> None:
        """Constraints rather than conventions: a negative part, a line before the first, or a
        range that ends before it begins all read back as an ordinary row."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                with pytest.raises(aiosqlite.IntegrityError):
                    await opened.connection.execute(_CHUNK, row)

    async def test_two_chunks_cannot_share_a_part_of_one_path(self, tmp_path: Path) -> None:
        """Contiguity from zero is what makes a part index an address, and a duplicate would make
        two rows claim one."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute(_CHUNK, ("a.md", 0, 1, 1, "x"))
                with pytest.raises(aiosqlite.IntegrityError):
                    await opened.connection.execute(_CHUNK, ("a.md", 0, 2, 2, "y"))
                await opened.connection.rollback()


class TestAFilesRowsMoveInOneTransaction:
    async def test_a_disposal_that_fails_leaves_that_file_exactly_as_it_was(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Committed files stay committed and the file in flight is untouched, which is what makes
        a crashed build resumable by doing the same thing again."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            real = files.record

            async def _fail_on_the_second(
                db: aiosqlite.Connection, indexed: files.IndexedFile
            ) -> None:
                await real(db, indexed)
                if indexed.path == "b.md":
                    raise RuntimeError("the indexer died mid-transaction")

            monkeypatch.setattr(files, "record", _fail_on_the_second)
            with pytest.raises(RuntimeError):
                await _build(corpus)
            async with open_index(corpus) as opened:
                stored = await files.load_all(opened.connection)
        assert set(stored) == {"a.md"}


class TestWhatMayEmptyThePendingTable:
    async def test_a_completed_scan_disposes_of_every_path(self, tmp_path: Path) -> None:
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n", "logo.png": b"\x89PNG"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await pending.count(opened.connection) == 0

    async def test_a_scan_that_finds_nothing_changed_empties_it_by_replacing_it(
        self, tmp_path: Path
    ) -> None:
        """The wholesale replacement is on the allowlist precisely because of this case, and it is
        also what clears rows a crash or an unreadable file left behind."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await pending.replace_all(
                    opened.connection, ["stale.md"], noticed_at="2026-01-01T00:00:00+00:00"
                )
                await opened.connection.commit()
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await pending.paths(opened.connection) == []

    async def test_a_crashed_build_keeps_the_rows_it_never_reached(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Those rows are the only thing keeping a stale flag honest between the crash and the
        next scan, so nothing sweeps them on the way out."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:

            async def _die(*_args: object, **_kwargs: object) -> None:
                raise RuntimeError("the indexer died")

            monkeypatch.setattr(scan, "_dispose", _die)
            with pytest.raises(RuntimeError):
                await _build(corpus)
            async with open_index(corpus) as opened:
                assert await pending.paths(opened.connection) == ["a.md", "b.md"]

    async def test_a_path_whose_disposal_could_not_complete_keeps_its_row(
        self, tmp_path: Path
    ) -> None:
        """The second correct survival: the work its row names has not been done, so a search
        keeps saying so until a later walk decides otherwise."""
        root = _tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            (root / "a.md").chmod(0o000)
            try:
                await _build(corpus)
                async with open_index(corpus) as opened:
                    assert await pending.paths(opened.connection) == ["a.md"]
            finally:
                (root / "a.md").chmod(0o600)
