"""The `files` and `pending` tables, and the two reads that maintain them.

Both are exercised against a real knowledge-base database rather than a fake, because what they
are for is a row that survives a crash — and the `CHECK` constraints on those rows are part of the
contract.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import config_for, corpus_root, open_store
from zikaron.core.knowledge import database, files, pending
from zikaron.core.knowledge.counters import SkipReason
from zikaron.core.knowledge.database import KnowledgeDatabase, NewKnowledgeBase, seed_identity
from zikaron.core.knowledge.registry import KnowledgeBase, ensure_table, insert
from zikaron.core.store.transactions import in_one_transaction, propagate

_NOW = "2026-01-01T00:00:00+00:00"


@pytest.fixture
async def knowledge_db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """An open, empty knowledge-base database, created the way a real one is."""
    async with open_store(tmp_path) as (store_dir, memory_db):
        config = config_for(tmp_path)

        async def _register(connection: aiosqlite.Connection) -> KnowledgeBase:
            await ensure_table(connection)
            return await insert(connection, name="docs", description="a corpus", created_at=_NOW)

        registered = await in_one_transaction(memory_db, _register, failure=propagate)
        spec = NewKnowledgeBase(
            name=registered.name, root=corpus_root(tmp_path), description="a corpus"
        )
        async with await KnowledgeDatabase.create(
            store_dir, seed_identity(registered.id, spec, config)
        ) as opened:
            yield opened.connection


def _row(**overrides: object) -> files.IndexedFile:
    defaults: dict[str, object] = {
        "path": "a.md",
        "size": 10,
        "content_hash": "a" * 40,
        "git_blob_hash": None,
        "chunk_count": 0,
        "indexed_at": _NOW,
    }
    return files.IndexedFile(**(defaults | overrides))  # type: ignore[arg-type]


class TestTheContentHash:
    def test_it_is_taken_over_the_bytes_as_read(self) -> None:
        """Before a byte-order mark is stripped and before decoding, so two files differing only
        by a mark are correctly different files."""
        assert files.content_hash(b"hello") != files.content_hash(b"\xef\xbb\xbfhello")

    def test_it_is_stable_for_the_same_bytes(self) -> None:
        assert files.content_hash(b"hello") == files.content_hash(b"hello")

    def test_it_is_never_a_git_blob_hash(self) -> None:
        """Git hashes a header plus the content, so the two can never agree — which is why each is
        only ever compared against its own prior value."""
        assert files.content_hash(b"hello") != "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"


class TestTheBoundedRead:
    def test_it_returns_the_bytes_when_they_fit(self, tmp_path: Path) -> None:
        target = tmp_path / "a.md"
        target.write_bytes(b"12345")
        assert files.read_bounded(target, 5) == b"12345"

    def test_one_byte_past_the_limit_is_over_the_cap(self, tmp_path: Path) -> None:
        """Bounded rather than read whole, so a file that grew since it was measured cannot be
        read into memory entire."""
        target = tmp_path / "a.md"
        target.write_bytes(b"123456")
        assert files.read_bounded(target, 5) is SkipReason.OVER_SIZE_CAP

    def test_a_file_that_cannot_be_opened_is_unreadable(self, tmp_path: Path) -> None:
        assert files.read_bounded(tmp_path / "absent.md", 10) is SkipReason.UNREADABLE


class TestTheFilesTable:
    async def test_a_row_written_comes_back_as_it_was(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        written = _row(path="a.md", git_blob_hash="b" * 40, chunk_count=3)
        await files.record(knowledge_db, written)
        assert await files.load_all(knowledge_db) == {"a.md": written}

    async def test_writing_the_same_path_twice_replaces_it(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """Both cases arrive down one path — a file the corpus has never seen and a file whose
        content moved — and the row that results is identical either way."""
        await files.record(knowledge_db, _row(path="a.md", size=1))
        await files.record(knowledge_db, _row(path="a.md", size=2))
        assert (await files.load_all(knowledge_db))["a.md"].size == 2

    async def test_forgetting_a_path_removes_it(self, knowledge_db: aiosqlite.Connection) -> None:
        await files.record(knowledge_db, _row(path="a.md"))
        await files.forget(knowledge_db, "a.md")
        assert await files.load_all(knowledge_db) == {}

    async def test_the_count_and_the_byte_total_describe_the_rows(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await files.record(knowledge_db, _row(path="a.md", size=10))
        await files.record(knowledge_db, _row(path="b.md", size=32))
        assert await files.count(knowledge_db) == 2
        assert await files.total_size(knowledge_db) == 42

    async def test_the_byte_total_of_an_empty_index_is_zero_rather_than_nothing(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        assert await files.total_size(knowledge_db) == 0

    async def test_a_blob_hash_can_be_refreshed_without_touching_anything_else(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """A file committed after it was indexed keeps a null blob hash, and without writing the
        new one it is read and hashed on every scan for the rest of its life."""
        await files.record(knowledge_db, _row(path="a.md", indexed_at=_NOW))
        await files.record_git_blob_hash(knowledge_db, "a.md", "c" * 40)
        row = (await files.load_all(knowledge_db))["a.md"]
        assert row.git_blob_hash == "c" * 40
        assert row.indexed_at == _NOW

    @pytest.mark.parametrize("bad", [{"path": ""}, {"size": -1}, {"chunk_count": -1}])
    async def test_the_row_constraints_refuse_a_value_that_would_read_back_plausibly(
        self, knowledge_db: aiosqlite.Connection, bad: dict[str, object]
    ) -> None:
        """Constraints rather than conventions: a row with a negative size or an empty path reads
        back as an ordinary row and points at nothing."""
        with pytest.raises(aiosqlite.IntegrityError):
            await files.record(knowledge_db, _row(**({"path": "a.md"} | bad)))


class TestTheGitFastPath:
    def test_a_file_with_no_row_is_changed_by_definition(self) -> None:
        assert not files.unchanged_by_git(
            "a.md", None, listed={"a.md": "x"}, reported_changed=frozenset()
        )

    def test_a_null_stored_hash_never_clears_a_file(self) -> None:
        """The load-bearing half: an untracked file has no listing entry and no stored hash, so a
        comparison of two absent values would clear it as unchanged forever."""
        assert not files.unchanged_by_git(
            "a.md", _row(path="a.md"), listed={}, reported_changed=frozenset()
        )

    def test_a_matching_hash_with_a_quiet_status_clears_the_file(self) -> None:
        row = _row(path="a.md", git_blob_hash="b" * 40)
        assert files.unchanged_by_git(
            "a.md", row, listed={"a.md": "b" * 40}, reported_changed=frozenset()
        )

    def test_a_reported_path_is_never_cleared(self) -> None:
        row = _row(path="a.md", git_blob_hash="b" * 40)
        assert not files.unchanged_by_git(
            "a.md", row, listed={"a.md": "b" * 40}, reported_changed=frozenset({"a.md"})
        )

    def test_a_differing_hash_is_not_cleared(self) -> None:
        row = _row(path="a.md", git_blob_hash="b" * 40)
        assert not files.unchanged_by_git(
            "a.md", row, listed={"a.md": "c" * 40}, reported_changed=frozenset()
        )

    def test_a_file_missing_from_the_listing_is_not_cleared(self) -> None:
        row = _row(path="a.md", git_blob_hash="b" * 40)
        assert not files.unchanged_by_git(
            "a.md", row, listed={"other.md": "b" * 40}, reported_changed=frozenset()
        )


class TestThePendingTable:
    async def test_replacing_discards_whatever_was_there(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """Replaced rather than appended to, so a file edited and then reverted between two scans
        loses its row instead of being flagged stale forever."""
        await pending.replace_all(knowledge_db, ["a.md", "b.md"], noticed_at=_NOW)
        await pending.replace_all(knowledge_db, ["c.md"], noticed_at=_NOW)
        assert await pending.paths(knowledge_db) == ["c.md"]

    async def test_replacing_with_nothing_empties_it(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """A scan that finds no changes legitimately empties the table, and that is the one way it
        is allowed to happen apart from a disposal."""
        await pending.replace_all(knowledge_db, ["a.md"], noticed_at=_NOW)
        await pending.replace_all(knowledge_db, [], noticed_at=_NOW)
        assert await pending.count(knowledge_db) == 0

    async def test_paths_come_back_ordered(self, knowledge_db: aiosqlite.Connection) -> None:
        """The order decides which files a partly-completed scan has committed, so an arbitrary
        one makes two runs over a corpus incomparable."""
        await pending.replace_all(knowledge_db, ["c.md", "a.md", "b.md"], noticed_at=_NOW)
        assert await pending.paths(knowledge_db) == ["a.md", "b.md", "c.md"]

    async def test_disposing_removes_only_the_named_path(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await pending.replace_all(knowledge_db, ["a.md", "b.md"], noticed_at=_NOW)
        await pending.dispose(knowledge_db, "a.md")
        assert await pending.paths(knowledge_db) == ["b.md"]

    async def test_disposing_a_path_that_is_not_there_is_not_an_error(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        await pending.dispose(knowledge_db, "never-seen.md")
        assert await pending.count(knowledge_db) == 0


class TestTheMetaWrites:
    async def test_writing_creates_what_is_absent_and_overwrites_what_is_not(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """One statement covers both, because the two kinds of key here are written by different
        rules — counters exist from creation, a scan-outcome key is absent until something has one
        to record."""
        await database.write_meta(knowledge_db, {"files_seen": "9", "last_scan_started_at": _NOW})
        raw = await database.read_meta(knowledge_db)
        assert raw["files_seen"] == "9"
        assert raw["last_scan_started_at"] == _NOW

    async def test_clearing_ignores_what_is_not_there(
        self, knowledge_db: aiosqlite.Connection
    ) -> None:
        """Absence is the ordinary outcome: these are the keys whose absence carries the meaning,
        so clearing one never written is the state already being correct."""
        await database.write_meta(knowledge_db, {"lock_pid": "4242"})
        await database.clear_meta(knowledge_db, ["lock_pid", "lock_host"])
        raw = await database.read_meta(knowledge_db)
        assert "lock_pid" not in raw
