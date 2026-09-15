"""What a scan counts, where each number lands in `meta`, and the design table it answers to.

The keys are read back out of `knowledge-index.md` rather than transcribed a second time here,
because the likelier drift is the design being revised while the code stays put — and a scan
writing a key nothing reports is invisible from either side on its own.
"""

import re

import pytest

from tests.design_tables import table_with_columns
from zikaron.core.knowledge import meta
from zikaron.core.knowledge.counters import (
    PRUNED_DIRECTORIES_KEY,
    SKIP_PREFIX,
    ScanCounters,
    SkipReason,
)

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
        """The nine, in the design's own order: the eight file reasons and the directory count.

        Order is checked as well as membership because the report walks this tuple, and a
        reordering would silently change what a person reading a breakdown sees first."""
        assert list(meta.SKIP_REASON_KEYS) == _keys_in_group("skip reasons")

    def test_the_progress_counters_are_exactly_what_the_design_lists(self) -> None:
        assert list(meta.PROGRESS_KEYS) == _keys_in_group("scan progress")

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
