"""The invariants a build must hold, each tested by trying to break it.

- **A chunk's path always names a row in `files`, and `files.chunk_count` equals that path's chunk
  count.** No foreign key spans these tables — no usable declarative cascade exists for a `vec0`
  table or for external-content full text — so the per-file transaction is the only thing that can
  maintain them.
- **Every chunk has exactly one posting and exactly one vector**, for the same reason and
  maintained by the same transaction.
- **`chunks.part_index` counts from 0, and a chunk's line range is `1 <= start <= end`.** These
  are row constraints, because a writer that got one wrong would otherwise produce a row that
  reads back plausibly and points at nothing.
- **Every vector was made by the encoder `meta` records.** The width is checkable against what is
  stored; the model is not, so a build refuses an encoder that disagrees rather than leaving a
  corpus nothing can later detect the inconsistency in.
- **A chunk's text is its file's bytes** for the range it names, and a file's chunks partition it.
- **A file's rows move in a single transaction, never partially visible.**
- **A path in `pending` names a file whose row, if any, predates the current walk.** The table is
  emptied by the index phase disposing of every path, or by the walk phase replacing it wholesale
  — never by anything else, and in particular never by an indexer exiting. Two survivals are
  correct and must not be swept: rows left by a crash, and a path whose disposal could not
  complete.

Each test is written to **fail if the invariant is violated** rather than to demonstrate the happy
path, and every oracle is shown failing on a planted violation before it is trusted on rows that
hold. A planted row uses a part index no build can have produced, so that it is an extra chunk the
invariant can see rather than a collision the table itself refuses.
"""

from pathlib import Path

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import (
    Corpus,
    add_request,
    build_index,
    open_corpus,
    open_index,
    write_config,
    write_tree,
)
from tests.test_knowledge_search import read_lines
from zikaron.core.errors import ZikaronError
from zikaron.core.knowledge import disposal, files, lexical, lifecycle, pending
from zikaron.core.knowledge.meta import GitMode

_CHUNK = "INSERT INTO chunks (path, part_index, start_line, end_line, text) VALUES (?, ?, ?, ?, ?)"

#: Both directions of the full-text index's agreement with its content table. The argument is not
#: optional: the bare form and argument 0 check the index's own internal consistency and report OK
#: both for a posting whose content row is gone and for a content row with no posting.
_FTS_INTEGRITY = "INSERT INTO chunks_fts (chunks_fts, rank) VALUES ('integrity-check', 1)"

#: Bytes per stored coordinate, which is what turns a vector's blob length into its width.
_FLOAT32_BYTES = 4

#: A corpus whose files are shaped to make a chunker produce something other than one tidy chunk
#: each: blank runs, trailing whitespace, a missing final newline, CRLF endings, and a line long
#: enough to be its own chunk. Shared by every invariant below that needs real chunks to look at.
AWKWARD_LAYOUT: dict[str, bytes] = {
    "trailing.md": b"alpha step   \n\n\n   \nsecond paragraph\t\n",
    "indented.py": b"def step():\n    # a comment\n        deeper = True\n",
    "unterminated.sh": b"set -euo pipefail\nmake release",
    "carriage.md": b"one\r\ntwo\r\n",
    "nested/deep.md": b"nested prose\n",
}


async def _unpaired_vectors(db: aiosqlite.Connection) -> list[str]:
    """Every path holding a chunk with no vector of its own, or more than one."""
    rows = await db.execute_fetchall(
        "SELECT chunks.path FROM chunks "
        "LEFT JOIN chunks_vec ON chunks_vec.chunk_id = chunks.id "
        "GROUP BY chunks.id HAVING count(chunks_vec.chunk_id) != 1"
    )
    return [str(path) for (path,) in rows]


async def _require_fts_agrees(db: aiosqlite.Connection) -> None:
    """Raise unless the full-text index and the chunk table agree in both directions."""
    await db.execute(_FTS_INTEGRITY)


async def _build(corpus: Corpus) -> lifecycle.Refreshed:
    return await build_index(corpus)


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
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await _orphaned_chunk_paths(opened.connection) == []

    async def test_the_query_that_guards_it_can_actually_see_a_violation(
        self, tmp_path: Path
    ) -> None:
        """A guard that never fires proves nothing, so the oracle is shown failing on a row that
        violates the invariant before it is trusted on rows that do not."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute(_CHUNK, ("gone.md", 0, 1, 1, "x"))
                assert await _orphaned_chunk_paths(opened.connection) == ["gone.md"]
                await opened.connection.rollback()

    async def test_deleting_a_file_takes_its_chunks_with_it(self, tmp_path: Path) -> None:
        """No declarative cascade exists across these tables, so a deletion that removed only the
        `files` row would leave chunks pointing at a file the corpus no longer has."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            (corpus.root / "b.md").unlink()
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await _orphaned_chunk_paths(opened.connection) == []


class TestTheChunkCountAgreesWithTheChunks:
    async def test_a_built_corpus_agrees_everywhere(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n", "docs/b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await _disagreeing_chunk_counts(opened.connection) == []

    async def test_the_query_that_guards_it_can_actually_see_a_violation(
        self, tmp_path: Path
    ) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                # A part index the build cannot have used, so the planted row is an extra chunk
                # rather than a collision with the one the build wrote.
                await opened.connection.execute(_CHUNK, ("a.md", 99, 1, 1, "alpha"))
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
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                with pytest.raises(aiosqlite.IntegrityError):
                    await opened.connection.execute(_CHUNK, row)

    async def test_two_chunks_cannot_share_a_part_of_one_path(self, tmp_path: Path) -> None:
        """Contiguity from zero is what makes a part index an address, and a duplicate would make
        two rows claim one."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute(_CHUNK, ("a.md", 99, 1, 1, "x"))
                with pytest.raises(aiosqlite.IntegrityError):
                    await opened.connection.execute(_CHUNK, ("a.md", 99, 2, 2, "y"))
                await opened.connection.rollback()


class TestAFilesRowsMoveInOneTransaction:
    async def test_a_disposal_that_fails_leaves_that_file_exactly_as_it_was(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Committed files stay committed and the file in flight is untouched, which is what makes
        a crashed build resumable by doing the same thing again."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
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


class TestAKilledReindexLeavesNothingHalfWritten:
    async def test_a_failure_inside_one_files_transaction_rolls_all_three_tables_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three tables move together or not at all. A partial write here is the worst shape this
        index can take: postings and vectors for text that was never committed answer queries
        normally, and resolve to chunks that are not there."""
        write_config(tmp_path, "[indexing]\nchunk_max_tokens = 64\n")
        body = "".join(f"paragraph {index} of prose\n\n" for index in range(60))
        root = write_tree(
            tmp_path / "corpus", {"a-first.md": b"alpha\n", "b-many.md": body.encode()}
        )
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            real = lexical.insert
            written: list[str] = []

            async def _fail_partway(
                db: aiosqlite.Connection, *, chunk_id: int, document: lexical.Document
            ) -> None:
                await real(db, chunk_id=chunk_id, document=document)
                written.append(document.path)
                if written.count("b-many.md") == 2:
                    raise RuntimeError("the indexer died between two chunks of one file")

            monkeypatch.setattr(lexical, "insert", _fail_partway)
            with pytest.raises(RuntimeError):
                await _build(corpus)
            assert written.count("b-many.md") == 2, "the failure did not land inside one file"
            async with open_index(corpus) as opened:
                db = opened.connection
                rows = await db.execute_fetchall("SELECT DISTINCT path FROM chunks")
                assert [str(path) for (path,) in rows] == ["a-first.md"]
                assert await _unpaired_vectors(db) == []
                await _require_fts_agrees(db)
                assert set(await files.load_all(db)) == {"a-first.md"}


class TestWhatMayEmptyThePendingTable:
    async def test_a_completed_scan_disposes_of_every_path(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n", "logo.png": b"\x89PNG"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await pending.count(opened.connection) == 0

    async def test_a_scan_that_finds_nothing_changed_empties_it_by_replacing_it(
        self, tmp_path: Path
    ) -> None:
        """The wholesale replacement is on the allowlist precisely because of this case, and it is
        also what clears rows a crash or an unreadable file left behind."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
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
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:

            async def _die(*_args: object, **_kwargs: object) -> None:
                raise RuntimeError("the indexer died")

            monkeypatch.setattr(disposal, "dispose", _die)
            with pytest.raises(RuntimeError):
                await _build(corpus)
            async with open_index(corpus) as opened:
                assert await pending.paths(opened.connection) == ["a.md", "b.md"]

    async def test_a_path_whose_disposal_could_not_complete_keeps_its_row(
        self, tmp_path: Path
    ) -> None:
        """The second correct survival: the work its row names has not been done, so a search
        keeps saying so until a later walk decides otherwise."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            (root / "a.md").chmod(0o000)
            try:
                await _build(corpus)
                async with open_index(corpus) as opened:
                    assert await pending.paths(opened.connection) == ["a.md"]
            finally:
                (root / "a.md").chmod(0o600)


class TestEveryChunkIsInBothArmsExactlyOnce:
    """One `chunks` row, one posting, one vector — and nothing across the three cascades, so a
    build is the only thing that can keep them in step."""

    async def test_a_built_corpus_pairs_every_chunk_with_a_posting_and_a_vector(
        self, tmp_path: Path
    ) -> None:
        root = write_tree(tmp_path / "corpus", AWKWARD_LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                assert await _unpaired_vectors(opened.connection) == []
                await _require_fts_agrees(opened.connection)

    async def test_the_full_text_oracle_can_see_a_posting_with_no_content_row(
        self, tmp_path: Path
    ) -> None:
        """The oracle needs its argument: the argument-less form and argument 0 check only the
        index's own internal consistency and report OK for exactly this violation."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute("DELETE FROM chunks")
                with pytest.raises(aiosqlite.DatabaseError):
                    await _require_fts_agrees(opened.connection)
                await opened.connection.rollback()

    async def test_the_vector_oracle_can_see_a_chunk_with_no_vector(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                await opened.connection.execute("DELETE FROM chunks_vec")
                assert await _unpaired_vectors(opened.connection) == ["a.md"]
                await opened.connection.rollback()


class TestEveryChunksLineRangeIsReal:
    """`1 <= start_line <= end_line`. The `CHECK`s above refuse a row that violates it; this is
    the other half — that what a build actually writes satisfies it, over a corpus shaped to make
    a chunker produce awkward ranges."""

    async def test_every_chunk_a_build_writes_has_a_usable_range(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", AWKWARD_LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                rows = await opened.connection.execute_fetchall(
                    "SELECT start_line, end_line FROM chunks"
                )
                ranges = [(int(start), int(end)) for start, end in rows]
            assert ranges
            assert all(1 <= start <= end for start, end in ranges)


class TestEveryVectorMatchesTheRecordedEncoder:
    """`meta.embed_model` and `meta.embed_dim` describe every vector in the corpus. The width is
    checkable directly; the model is not, which is why a build refuses an encoder that disagrees
    rather than discovering it later."""

    async def test_every_stored_vector_has_the_recorded_width(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", AWKWARD_LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                rows = await opened.connection.execute_fetchall("SELECT embedding FROM chunks_vec")
                widths = {len(bytes(blob)) // _FLOAT32_BYTES for (blob,) in rows}
                assert widths == {opened.meta.embed_dim}

    async def test_a_build_with_another_model_is_refused_before_it_writes(
        self, tmp_path: Path
    ) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            with pytest.raises(ZikaronError):
                await build_index(corpus, encoder=FakeEncoder(model_name="something-else"))
            async with open_index(corpus) as opened:
                rows = await opened.connection.execute_fetchall("SELECT count(*) FROM chunks")
                ((chunks,),) = list(rows)
            assert int(chunks) == 0


class TestAChunksTextIsItsFilesBytes:
    """`chunks.text` is byte-identical to lines `start_line`-`end_line` of the file it names, with
    no prefix and no normalization. A snippet's round-trip against the file rests on this, so it is
    checked at the row where it is made rather than only at the answer where it is relied on."""

    async def test_every_chunk_reads_back_from_its_file_exactly(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", AWKWARD_LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                rows = await opened.connection.execute_fetchall(
                    "SELECT path, start_line, end_line, text FROM chunks"
                )
                stored = [
                    (str(path), int(start), int(end), str(text)) for path, start, end, text in rows
                ]
            assert stored
            for path, start, end, text in stored:
                assert text == read_lines(corpus.root / path, start, end)

    async def test_the_chunks_of_one_file_partition_it(self, tmp_path: Path) -> None:
        """Contiguous and complete: concatenating a file's chunks in part order reproduces the
        file, so nothing is indexed twice and nothing is dropped without anything saying so."""
        root = write_tree(tmp_path / "corpus", AWKWARD_LAYOUT)
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await _build(corpus)
            async with open_index(corpus) as opened:
                rows = await opened.connection.execute_fetchall(
                    "SELECT path, text FROM chunks ORDER BY path, part_index"
                )
            rebuilt: dict[str, str] = {}
            for path, text in rows:
                rebuilt[str(path)] = rebuilt.get(str(path), "") + str(text)
            assert rebuilt
            for path, text in rebuilt.items():
                assert text == (corpus.root / path).read_bytes().decode("utf-8")
