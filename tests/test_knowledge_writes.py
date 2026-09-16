"""`zikaron.core.knowledge.writes` — one file's chunks, postings and vectors moving together.

Nothing across these three tables cascades, so every test here is about the one transaction that
keeps them in step, and most of them are written to catch the silent failure rather than the loud
one: an external-content full-text index left holding postings for text that is gone answers
queries normally, and a vector whose chunk row has been deleted matches and resolves to nothing.
"""

from pathlib import Path

import aiosqlite
import pytest

from tests.fake_encoder import FakeEncoder
from tests.knowledge_fixtures import (
    add_request,
    build_index,
    open_corpus,
    open_index,
    write_tree,
)
from zikaron.core.errors import ErrorCode, IndexStage, ZikaronError
from zikaron.core.knowledge import files, writes
from zikaron.core.knowledge.chunking import plan_file_chunks
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.meta import GitMode
from zikaron.core.store.transactions import in_one_transaction, propagate

_INTEGRITY_CHECK = "INSERT INTO chunks_fts (chunks_fts, rank) VALUES ('integrity-check', 1)"


async def _count(db: aiosqlite.Connection, statement: str) -> int:
    rows = await db.execute_fetchall(statement)
    ((found,),) = list(rows)
    return int(found)


async def _chunk_ids(db: aiosqlite.Connection) -> list[int]:
    rows = await db.execute_fetchall("SELECT id FROM chunks ORDER BY id")
    return [int(chunk_id) for (chunk_id,) in rows]


async def _vector_ids(db: aiosqlite.Connection) -> list[int]:
    rows = await db.execute_fetchall("SELECT chunk_id FROM chunks_vec ORDER BY chunk_id")
    return [int(chunk_id) for (chunk_id,) in rows]


async def _matching(db: aiosqlite.Connection, expression: str) -> list[str]:
    """Every chunk's text whose postings match `expression`, best first.

    Reads a **column** rather than only the rowid, deliberately: a `MATCH` over an index whose
    content rows have vanished still answers a rowid normally and raises only when a column is
    projected, so a check that read the rowid alone would pass over exactly the corruption these
    tests exist to catch.
    """
    rows = await db.execute_fetchall(
        "SELECT text FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts)",
        (expression,),
    )
    return [str(text) for (text,) in rows]


async def _fts_is_consistent(db: aiosqlite.Connection) -> bool:
    """Whether the full-text index and its content table still agree, in **both** directions.

    Argument 1 is required: the bare form and argument 0 check only the index's own internal
    consistency and report OK both for a posting whose content row is gone and for a content row
    with no posting.
    """
    try:
        await db.execute(_INTEGRITY_CHECK)
    except aiosqlite.DatabaseError:
        return False
    return True


class TestABuiltFileIsPresentInAllThreeTables:
    async def test_every_chunk_has_a_posting_and_a_vector(self, tmp_path: Path) -> None:
        root = write_tree(
            tmp_path / "corpus", {"a.md": b"alpha beta\n\ngamma\n", "b.md": b"delta\n"}
        )
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                db = opened.connection
                chunks = await _chunk_ids(db)
                assert chunks
                assert await _vector_ids(db) == chunks
                assert await _count(db, "SELECT count(*) FROM chunks_fts") == len(chunks)
                assert await _fts_is_consistent(db)

    async def test_the_files_row_records_how_many_chunks_the_file_has(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                stored = await files.load_all(opened.connection)
                assert stored["a.md"].chunk_count == await _count(
                    opened.connection, "SELECT count(*) FROM chunks"
                )

    async def test_a_chunk_is_findable_by_a_word_of_its_text(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"the protobuf step fails silently\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                assert await _matching(opened.connection, '"protobuf"') == [
                    "the protobuf step fails silently\n"
                ]

    async def test_a_chunk_is_findable_by_a_component_of_its_path(self, tmp_path: Path) -> None:
        """The path earns its cost on the lexical arm, which is why it is a column of its own
        rather than something pasted into the text a reader is handed back."""
        root = write_tree(tmp_path / "corpus", {"runbooks/deploy.md": b"nothing to see\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                assert await _matching(opened.connection, '"runbooks"') == ["nothing to see\n"]

    async def test_the_stored_text_carries_no_path_prefix(self, tmp_path: Path) -> None:
        """The prefix exists for embedding only. A snippet is verbatim file content, so a reader
        never has to learn to strip anything off the front of one."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                rows = await opened.connection.execute_fetchall("SELECT text FROM chunks")
                assert [str(text) for (text,) in rows] == ["alpha\n"]


class TestReindexingReplacesEveryTrace:
    async def test_the_old_text_stops_matching(self, tmp_path: Path) -> None:
        """The failure this guards against is silent: an external-content index given the wrong
        values on delete accepts them, removes nothing, and keeps answering for text that is gone.
        """
        root = write_tree(tmp_path / "corpus", {"a.md": b"the protobuf step fails silently\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            (root / "a.md").write_bytes(b"the migration step is idempotent now\n")
            await build_index(corpus)
            async with open_index(corpus) as opened:
                assert await _matching(opened.connection, '"protobuf"') == []
                assert await _matching(opened.connection, '"migration"') == [
                    "the migration step is idempotent now\n"
                ]
                assert await _fts_is_consistent(opened.connection)

    async def test_no_vector_outlives_its_chunk(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n\nbeta\n\ngamma\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            (root / "a.md").write_bytes(b"delta\n")
            await build_index(corpus)
            async with open_index(corpus) as opened:
                assert await _vector_ids(opened.connection) == await _chunk_ids(opened.connection)

    async def test_a_deleted_file_leaves_nothing_in_any_table(self, tmp_path: Path) -> None:
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n", "b.md": b"beta\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            (root / "b.md").unlink()
            await build_index(corpus)
            async with open_index(corpus) as opened:
                db = opened.connection
                assert await _matching(db, '"beta"') == []
                assert await _vector_ids(db) == await _chunk_ids(db)
                assert await _fts_is_consistent(db)
                assert "b.md" not in await files.load_all(db)


class TestTheGuardsOnWhatIsWritten:
    async def _index(self, opened: KnowledgeDatabase, *, chunk_count: int, embeddings: int) -> None:
        plan = plan_file_chunks(
            path="a.md", text="alpha\n", encoder=FakeEncoder(), chunk_max_tokens=450
        )
        indexed = files.IndexedFile(
            path="a.md",
            size=6,
            content_hash="0" * 40,
            git_blob_hash=None,
            chunk_count=chunk_count,
            indexed_at="2026-01-01T00:00:00+00:00",
        )

        async def _work(db: aiosqlite.Connection) -> None:
            await writes.index_file(
                db, indexed=indexed, plan=plan, embeddings=[b"" for _ in range(embeddings)]
            )

        await in_one_transaction(opened.connection, _work, failure=propagate)

    async def test_a_row_claiming_a_different_chunk_count_is_refused(self, tmp_path: Path) -> None:
        """A `files` row that disagrees with its own chunks is the one inconsistency no later
        reader can detect, because both halves read back as ordinary values."""
        async with open_corpus(tmp_path) as corpus, open_index(corpus) as opened:
            with pytest.raises(ZikaronError) as excinfo:
                await self._index(opened, chunk_count=2, embeddings=1)
            assert excinfo.value.code is ErrorCode.INDEX_FAILED
            assert excinfo.value.data["stage"] == IndexStage.INDEX_WRITE

    async def test_a_vector_per_chunk_is_required(self, tmp_path: Path) -> None:
        async with open_corpus(tmp_path) as corpus, open_index(corpus) as opened:
            with pytest.raises(ZikaronError) as excinfo:
                await self._index(opened, chunk_count=1, embeddings=2)
            assert excinfo.value.code is ErrorCode.INDEX_FAILED
            assert excinfo.value.data["stage"] == IndexStage.INDEX_WRITE


class TestForgettingAFile:
    async def test_forgetting_a_path_that_was_never_indexed_removes_nothing(
        self, tmp_path: Path
    ) -> None:
        """The ordinary case during a scan: a path refused by a read that never had a row."""
        root = write_tree(tmp_path / "corpus", {"a.md": b"alpha\n"})
        async with open_corpus(tmp_path, add_request(root, git_mode=GitMode.OFF)) as corpus:
            await build_index(corpus)
            async with open_index(corpus) as opened:
                before = await _chunk_ids(opened.connection)

                async def _work(db: aiosqlite.Connection) -> None:
                    await writes.forget_file(db, path="never-indexed.md")

                await in_one_transaction(opened.connection, _work, failure=propagate)
                assert await _chunk_ids(opened.connection) == before
                assert await _fts_is_consistent(opened.connection)
