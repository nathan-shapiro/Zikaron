"""The registry's own refusals, and the one that must not be mistaken for another.

`sqlite3` reports three genuinely different faults on this table through a single exception class,
and only one of them is the ordinary "that name is taken". Telling them apart is read off the
result code rather than off the message, because the message is prose that varies between builds
while the code is the contract SQLite publishes.
"""

import sqlite3
import uuid
from pathlib import Path

import aiosqlite
import pytest

from tests.knowledge_fixtures import open_store
from zikaron.core.knowledge import registry
from zikaron.core.knowledge.errors import (
    DuplicateNameError,
    InvalidNameError,
    UnknownKnowledgeBaseError,
)


async def _ensure(db: aiosqlite.Connection) -> None:
    await db.execute(registry.CREATE_TABLE)
    await db.commit()


class TestNormalisingAName:
    @pytest.mark.parametrize(
        ("given", "stored"),
        [
            ("docs", "docs"),
            ("Docs", "docs"),
            ("DESIGN RECORDS", "design records"),
            ("Ünïcode Näme", "ünïcode näme"),
            ("  padded  ", "  padded  "),
            ("with-punctuation!", "with-punctuation!"),
        ],
    )
    def test_case_is_the_only_normalisation(self, given: str, stored: str) -> None:
        """Surrounding whitespace is preserved rather than stripped: a name is free-form text, and
        silently returning something other than what was asked for is a worse answer than storing
        it as given."""
        assert registry.normalize_name(given) == stored

    @pytest.mark.parametrize("blank", ["", " ", "\t", "\n", "   \t  "])
    def test_a_blank_name_is_refused(self, blank: str) -> None:
        """The one thing a name may not be, because a name is how a corpus is asked for again."""
        with pytest.raises(InvalidNameError):
            registry.normalize_name(blank)

    def test_lower_rather_than_casefold(self) -> None:
        """Casefold is the right tool for caseless *comparison*, but this is a canonical value
        being stored, and its extra folding would alter a name more than whoever typed it
        expects."""
        assert registry.normalize_name("Straße") == "straße"


class TestTellingTheConstraintsApart:
    async def test_a_name_collision_becomes_the_refusal_a_caller_acts_on(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            await registry.insert(db, name="docs", description="a", created_at="now")
            with pytest.raises(DuplicateNameError):
                await registry.insert(db, name="docs", description="b", created_at="now")

    async def test_a_constraint_that_is_not_the_name_collision_propagates_as_itself(
        self, tmp_path: Path
    ) -> None:
        """A `CHECK` failure means a value reached the insert un-normalized, which is a defect in
        this module rather than a name conflict — and reporting it as one would hand a caller a
        confident, wrong explanation for it.

        Forced by writing through the table directly with a name the registry would have
        lower-cased, which is precisely the mistake the backstop exists to catch.
        """
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            with pytest.raises(sqlite3.IntegrityError) as caught:
                await db.execute(
                    "INSERT INTO knowledge_bases VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), "NotLowered", "d", "now"),
                )
            assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_CHECK

    async def test_a_rename_collision_becomes_the_refusal_a_caller_acts_on(
        self, tmp_path: Path
    ) -> None:
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            await registry.insert(db, name="one", description="a", created_at="now")
            await registry.insert(db, name="two", description="b", created_at="now")
            with pytest.raises(DuplicateNameError):
                await registry.rename(db, name="one", new_name="two")

    async def test_an_insert_that_skipped_the_normalisation_propagates_as_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Through `insert` rather than around it, which is what makes this about the error
        mapping rather than about the constraint. The normalisation is disabled to produce the
        exact defect the backstop exists to catch, and the refusal that comes back must not claim
        the name was taken — it was not."""
        monkeypatch.setattr(registry, "normalize_name", lambda name: name)
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            with pytest.raises(sqlite3.IntegrityError) as caught:
                await registry.insert(db, name="NotLowered", description="d", created_at="now")
            assert not isinstance(caught.value, DuplicateNameError)
            assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_CHECK

    async def test_a_rename_that_skipped_the_normalisation_propagates_as_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same discrimination on the update path, which has its own `except` and could
        therefore have been written differently from the insert's."""
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            await registry.insert(db, name="one", description="a", created_at="now")
            monkeypatch.setattr(registry, "normalize_name", lambda name: name)
            with pytest.raises(sqlite3.IntegrityError) as caught:
                await registry.rename(db, name="one", new_name="NotLowered")
            assert not isinstance(caught.value, DuplicateNameError)
            assert caught.value.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_CHECK

    async def test_a_rename_whose_table_is_gone_propagates_as_itself(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            await registry.insert(db, name="one", description="a", created_at="now")
            found = await registry.find(db, "one")
            assert found is not None
            await db.execute("DROP TABLE knowledge_bases")
            await db.commit()
            with pytest.raises(aiosqlite.Error):
                await registry.rename(db, name="one", new_name="two")


class TestTheOrdinaryVerbs:
    async def test_insert_generates_the_id_rather_than_taking_one(self, tmp_path: Path) -> None:
        """There is no parameter a caller could use to influence where a corpus's file lands."""
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            first = await registry.insert(db, name="one", description="a", created_at="now")
            second = await registry.insert(db, name="two", description="b", created_at="now")
            assert first.id != second.id
            assert first.id.version == 4

    async def test_listing_is_ordered_by_name(self, tmp_path: Path) -> None:
        """Ordered in SQL rather than by the caller, so two runs over one store produce the same
        listing — a caller comparing output across runs should be comparing content, not sort
        luck."""
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            for name in ("zebra", "alpha", "middle"):
                await registry.insert(db, name=name, description="d", created_at="now")
            assert [base.name for base in await registry.list_all(db)] == [
                "alpha",
                "middle",
                "zebra",
            ]

    async def test_find_returns_nothing_for_an_unregistered_name(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            assert await registry.find(db, "absent") is None

    async def test_require_refuses_an_unregistered_name(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            with pytest.raises(UnknownKnowledgeBaseError):
                await registry.require(db, "absent")

    async def test_delete_returns_what_it_removed(self, tmp_path: Path) -> None:
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            added = await registry.insert(db, name="docs", description="d", created_at="now")
            removed = await registry.delete(db, name="docs")
            assert removed == added
            assert await registry.find(db, "docs") is None

    @pytest.mark.parametrize(
        "stored_id",
        [
            pytest.param("../memory", id="path-shaped"),
            # Exactly 36 characters, so it survives the length check and is refused by the parse
            # itself — the branch the other two cases never reach.
            pytest.param("zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz", id="right length, not hex"),
            pytest.param(str(uuid.uuid1()), id="a uuid of the wrong version"),
        ],
    )
    async def test_a_row_whose_id_is_not_a_version_4_uuid_fails_when_it_is_read(
        self, tmp_path: Path, stored_id: str
    ) -> None:
        """Parsed rather than trusted, so a registry somebody edited by hand raises when it is read
        instead of when it is joined onto a directory.

        Through the **same** parser the knowledge base's own `meta` uses, which is why a version 1
        uuid is refused here too: the registry row and that `meta` hold one value, and two parsers
        of differing strictness would make it fatal in one place and silently fine in the other.
        """
        async with open_store(tmp_path) as (_store_dir, db):
            await _ensure(db)
            await db.execute(
                "INSERT INTO knowledge_bases VALUES (?, ?, ?, ?)",
                (stored_id, "docs", "d", "now"),
            )
            with pytest.raises(ValueError, match="uuid"):
                await registry.list_all(db)
