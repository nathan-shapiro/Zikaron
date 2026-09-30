"""What a scan and a search count, where each number lands in `meta`, and the design table they
answer to.

The keys are read back out of `knowledge-index.md` rather than transcribed a second time here,
because the likelier drift is the design being revised while the code stays put — and a scan
writing a key nothing reports is invisible from either side on its own.
"""

import re
import time
from pathlib import Path
from typing import Final

import aiosqlite
import pytest

from tests.design_tables import table_with_columns
from tests.knowledge_fixtures import add_base, add_request, config_for, corpus_root, open_store
from zikaron.core.knowledge import counters as counter_module
from zikaron.core.knowledge import database, ddl, meta
from zikaron.core.knowledge.counters import (
    PRUNED_DIRECTORIES_KEY,
    SKIP_PREFIX,
    ScanCounters,
    SearchTally,
    SkipReason,
)
from zikaron.core.store.connection import open_connection

_DOCUMENT = "knowledge-index.md"
_HEADING = "### 3.2 Schema, per KB database"
_BACKTICKED = re.compile(r"`([^`]+)`")


def _keys_in_group(group: str) -> list[str]:
    """Every key the design's `meta` table lists under one group heading."""
    table = table_with_columns(_DOCUMENT, _HEADING, ("group", "keys"))
    rows = [row for row in table[1:] if row["group"] == group]
    if len(rows) != 1:
        pytest.fail(f"{len(rows)} rows for the {group!r} group in {_DOCUMENT} / {_HEADING}")
    return _BACKTICKED.findall(rows[0]["keys"])


class TestTheKeysMatchTheDesign:
    def test_the_skip_reasons_are_exactly_what_the_design_lists(self) -> None:
        """In the design's own order: the file reasons, then the directory count.

        Order is checked as well as membership because the report walks this tuple, and a
        reordering would silently change what a person reading a breakdown sees first."""
        assert list(meta.SKIP_REASON_KEYS) == _keys_in_group("skip reasons")

    def test_the_progress_counters_are_exactly_what_the_design_lists(self) -> None:
        assert list(meta.PROGRESS_KEYS) == _keys_in_group("scan progress")

    def test_the_search_counters_are_exactly_what_the_design_lists(self) -> None:
        assert list(meta.SEARCH_COUNTER_KEYS) == _keys_in_group("counters")

    def test_every_reason_names_its_own_key_and_the_directory_count_is_not_one(self) -> None:
        """Pruning is not a skip reason: it excludes directories, and the total the reasons
        decompose is a count of files."""
        assert [reason.meta_key for reason in SkipReason] == [
            key for key in meta.SKIP_REASON_KEYS if key != PRUNED_DIRECTORIES_KEY
        ]
        assert all(reason.meta_key.startswith(SKIP_PREFIX) for reason in SkipReason)

    def test_the_reported_name_is_the_key_without_its_prefix(self) -> None:
        """A report drops the prefix, which is a rule rather than a coincidence — so it is
        asserted where both halves are visible."""
        for reason in SkipReason:
            assert reason.meta_key.removeprefix(SKIP_PREFIX) == reason.value


class TestWhatTheCountersCount:
    def test_a_fresh_set_is_every_counter_at_zero(self) -> None:
        rows = ScanCounters().as_meta_rows()
        assert set(rows) == set(meta.PROGRESS_KEYS) | set(meta.SKIP_REASON_KEYS)
        assert set(rows.values()) == {"0"}

    def test_the_skipped_total_is_the_sum_of_the_reasons_and_excludes_pruning(self) -> None:
        counters = ScanCounters()
        counters.skip(SkipReason.BINARY)
        counters.skip(SkipReason.BINARY)
        counters.skip(SkipReason.SYMLINK)
        counters.pruned_directories = 7
        assert counters.files_skipped == 3
        rows = counters.as_meta_rows()
        assert rows["files_skipped"] == "3"
        assert rows[PRUNED_DIRECTORIES_KEY] == "7"

    def test_indexing_a_file_raises_both_the_count_and_the_byte_total(self) -> None:
        counters = ScanCounters()
        counters.index(120)
        counters.index(3)
        assert (counters.files_indexed, counters.bytes_indexed) == (2, 123)

    def test_every_reason_is_written_even_when_it_never_fired(self) -> None:
        """All of them on every flush, never only what changed: a reason left unwritten would
        report the previous scan's count beside this scan's neighbours."""
        counters = ScanCounters()
        counters.skip(SkipReason.DECODE_ERROR)
        rows = counters.as_meta_rows()
        assert rows[SkipReason.DECODE_ERROR.meta_key] == "1"
        assert rows[SkipReason.BINARY.meta_key] == "0"
        assert set(rows) == set(meta.PROGRESS_KEYS) | set(meta.SKIP_REASON_KEYS)


async def _open_corpus_db(tmp_path: Path) -> tuple[Path, aiosqlite.Connection]:
    """A registered knowledge base's own database, open for writing.

    Returns the path too, so a second connection can be opened against the same file — which is
    what it takes to hold the writer lock while the counter write asks for it.
    """
    async with open_store(tmp_path) as (store_dir, db):
        created = await add_base(
            store_dir, db, config_for(tmp_path), add_request(corpus_root(tmp_path))
        )
        connection, _inode = await open_connection(
            created.database_path, pragmas=ddl.PRAGMAS, existing_only=True
        )
        return created.database_path, connection


class TestWhatOneSearchContributes:
    def test_a_search_that_found_something_is_not_an_empty_one(self) -> None:
        increments = SearchTally(results=3, stale=1).as_increments()
        assert increments == {
            "searches": 1,
            "searches_empty": 0,
            "results_returned": 3,
            "results_stale": 1,
        }

    def test_a_search_that_found_nothing_raises_the_abstention_count(self) -> None:
        """The signal these counters exist for: how often a built corpus is asked and has
        nothing."""
        assert SearchTally(results=0, stale=0).as_increments()["searches_empty"] == 1

    def test_every_counter_is_written_even_at_zero(self) -> None:
        """One statement shape regardless of what the search found, so the write is the same
        transaction every time."""
        assert set(SearchTally(results=0, stale=0).as_increments()) == set(meta.SEARCH_COUNTER_KEYS)


class TestRecordingASearch:
    async def test_it_adds_to_what_is_already_there(self, tmp_path: Path) -> None:
        _db_path, connection = await _open_corpus_db(tmp_path)
        try:
            assert await counter_module.record_search(connection, SearchTally(results=2, stale=1))
            assert await counter_module.record_search(connection, SearchTally(results=0, stale=0))
            raw = await database.read_meta(connection)
        finally:
            await connection.close()

        assert raw["searches"] == "2"
        assert raw["searches_empty"] == "1"
        assert raw["results_returned"] == "2"
        assert raw["results_stale"] == "1"

    async def test_it_leaves_the_connection_waiting_for_the_lock_as_it_found_it(
        self, tmp_path: Path
    ) -> None:
        """The connection belongs to the caller, and every other statement on it expects to wait —
        a counter write that left the timeout at zero would make the next ordinary statement fail
        on contention that a search is supposed to ride out."""
        _db_path, connection = await _open_corpus_db(tmp_path)
        try:
            await counter_module.record_search(connection, SearchTally(results=1, stale=0))
            rows = await connection.execute_fetchall("PRAGMA busy_timeout")
        finally:
            await connection.close()
        ((timeout,),) = list(rows)
        assert timeout == ddl.BUSY_TIMEOUT_MS

    async def test_a_held_writer_lock_abandons_the_write_rather_than_waiting(
        self, tmp_path: Path
    ) -> None:
        """The whole reason the timeout is dropped to nothing: a build holds this lock for minutes
        at a time, and a search must not stop for it. The counts are lost, which is the stated
        trade.

        **The elapsed time is asserted, and without it this test proved only half its own name.**
        Whether the connection waits out `busy_timeout` or refuses at once, the call returns
        `False` and the counters stay where they were — so a version that waited the full five
        seconds passed every other assertion here. Found by mutation: leaving the timeout at its
        ordinary value changed the return value not at all, and only the clock.
        """
        db_path, connection = await _open_corpus_db(tmp_path)
        holder, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)
        try:
            await holder.execute("BEGIN IMMEDIATE")
            await holder.execute("INSERT INTO meta (key, value) VALUES ('held', '1')")

            started = time.perf_counter()
            assert not await counter_module.record_search(
                connection, SearchTally(results=4, stale=2)
            )
            elapsed = time.perf_counter() - started
            await holder.rollback()
            raw = await database.read_meta(connection)
        finally:
            await holder.close()
            await connection.close()
        assert raw["searches"] == "0", "an abandoned write leaves the counters where they were"
        # A fifth of the wait it must not have taken: far enough below `busy_timeout` that a loaded
        # machine cannot reach it, and far enough above an immediate refusal that only a genuine
        # wait crosses it.
        assert elapsed < ddl.BUSY_TIMEOUT_MS / 5_000, f"it waited {elapsed:.3f}s for the lock"

    async def test_the_timeout_is_restored_even_when_the_write_was_abandoned(
        self, tmp_path: Path
    ) -> None:
        db_path, connection = await _open_corpus_db(tmp_path)
        holder, _inode = await open_connection(db_path, pragmas=ddl.PRAGMAS, existing_only=True)
        try:
            await holder.execute("BEGIN IMMEDIATE")
            await holder.execute("INSERT INTO meta (key, value) VALUES ('held', '1')")
            await counter_module.record_search(connection, SearchTally(results=1, stale=0))
            await holder.rollback()
            rows = await connection.execute_fetchall("PRAGMA busy_timeout")
        finally:
            await holder.close()
            await connection.close()
        ((timeout,),) = list(rows)
        assert timeout == ddl.BUSY_TIMEOUT_MS

    async def test_a_failure_that_is_not_contention_is_not_swallowed(self, tmp_path: Path) -> None:
        """A knowledge base that refuses a four-row `UPDATE` for any other reason is one this
        process should stop claiming to serve, so the failure reaches a reader rather than being
        dropped along with the count."""
        _db_path, connection = await _open_corpus_db(tmp_path)
        try:
            await connection.execute("DROP TABLE meta")
            await connection.commit()
            with pytest.raises(aiosqlite.Error):
                await counter_module.record_search(connection, SearchTally(results=1, stale=0))
        finally:
            await connection.close()

    async def test_an_unreadable_counter_contributes_zero_rather_than_failing(
        self, tmp_path: Path
    ) -> None:
        """The same reading a report already gives such a value: a counter nothing can read as a
        number is worth nothing, and refusing over one would make a hand-edited row fatal."""
        _db_path, connection = await _open_corpus_db(tmp_path)
        try:
            await connection.execute(
                "UPDATE meta SET value = 'not a number' WHERE key = 'searches'"
            )
            await connection.commit()
            assert await counter_module.record_search(connection, SearchTally(results=0, stale=0))
            raw = await database.read_meta(connection)
        finally:
            await connection.close()
        assert raw["searches"] == "1"


#: Assembled from fragments so this file's own source is not a hit. Bounded to the neighbours of the
#: enumeration's size: smaller counts of *reasons* are ordinary English this tree already uses.
_NUMBER: Final = (
    r"\b(?:"
    + "|".join(("six", "seven", "eig" + "ht", "ni" + "ne", "ten", "eleven", "twelve"))
    + r"|[6-9]|1[0-2])\b"
)
_EMPHASIS: Final = r"[*_]*"
_SPELLED_COUNT: Final = re.compile(
    _NUMBER
    + r"\s+"
    + _EMPHASIS
    + r"(?:(?:file|skip)"
    + _EMPHASIS
    + r"\s+"
    + _EMPHASIS
    + r")?reas"
    + r"ons\b"
    + "|"
    + _NUMBER
    + r"-way\W+(?:\S+\s+){0,3}?\W*(?:skip"
    + r"ped|break"
    + r"down)",
    re.IGNORECASE,
)
_LINE_BREAK: Final = re.compile(r'"?\s*\n\s*(?:#:?|>)?\s*(?:[rfbRFB]{0,2}")?')
_REPO: Final = Path(__file__).resolve().parent.parent


def _spelled_counts(text: str) -> list[str]:
    """Every count of the reasons in `text`, with a wrapped line joined back into its sentence."""
    return [match.group(0) for match in _SPELLED_COUNT.finditer(_LINE_BREAK.sub(" ", text))]


class TestNoProseCountsTheReasons:
    """`SkipReason` is the enumeration, so a count written in prose is a second copy that goes
    stale silently on the next reason added. `coding-standards.md` §5."""

    def test_nothing_spells_out_how_many_there_are(self) -> None:
        sources = [
            *(_REPO / "zikaron").rglob("*.py"),
            *(_REPO / "tests").rglob("*.py"),
            _REPO / "design" / _DOCUMENT,
        ]
        found = {
            str(path.relative_to(_REPO)): hits
            for path in sources
            if (hits := _spelled_counts(path.read_text(encoding="utf-8")))
        }
        assert found == {}

    @pytest.mark.parametrize(
        "sentence",
        [
            "and `files_skipped` the eig" + "ht file reasons summed",
            "the sum of the eig" + "ht *file* reasons and",
            "files it refused for one of the eig" + "ht\nreasons.",
            "`files_seen` and the eig" + "ht skip\n    reasons count",
            "the ni" + "ne-way `skipped` breakdown",
            '"refused for one of the eig' + 'ht "\n        "file reasons."',
            '"refused for one of the eig' + 'ht "\n        f"file reasons {x}."',
            "and the " + "8 file reas" + "ons summed",
        ],
    )
    def test_the_guard_sees_each_phrasing_it_removed(self, sentence: str) -> None:
        assert _spelled_counts(sentence)

    def test_ordinary_small_counts_and_unrelated_compounds_stay_green(self) -> None:
        assert not _spelled_counts(
            "for two reasons, and a two-way guard; three reasons want; 3 reasons; 16 reasons"
        )
