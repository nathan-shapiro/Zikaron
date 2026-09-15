"""What a scan counts, where each number is persisted, and what it means once the scan has stopped.

The counter vocabulary and the `meta` keys that hold it are defined together, here, rather than as
a list of names in the schema module and a matching list of reasons somewhere else. Those two would
be free to disagree, and the symptom would be a scan writing a count nothing reports — invisible,
because both halves would still look right on their own.

Two kinds of counter live here and the difference is deliberate. `files_seen` and the eight skip
reasons count **the scan's own work**: what the walk looked at, and what it refused. `files_indexed`
and `bytes_indexed` describe **the corpus the scan leaves behind** — every admitted file the scan
established is in the index raises them, whether it was reindexed or cleared as unchanged. The
alternative reading, *files this scan wrote*, makes a rescan that finds nothing changed report zero
files, and that number is what a caller is given in order to choose between corpora, so a healthy
corpus would advertise itself as empty.

The reading above is checkable rather than merely intended: on a scan that completes with nothing
left unreadable, `files_indexed` equals the row count of `files` and `bytes_indexed` equals the sum
of their sizes.

**One consequence of `files_seen`'s definition, since it otherwise reads as a defect.** The walk
evaluates every file it reaches; under `git_mode = tracked` the tracked-file intersection then
removes the untracked ones, which are therefore *seen* and outside the corpus without being
*skipped*. No skip reason describes them, and inventing one would put a value on a reported table
that the schema does not carry.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

#: What a skip-reason key is called in `meta`, and what a reported field name drops to get there.
SKIP_PREFIX: Final = "skipped_"

#: Directories the walk refused to descend. Counted apart from the skip reasons because it counts
#: directories, and the total those decompose is a count of files.
PRUNED_DIRECTORIES_KEY: Final = "pruned_directories"

FILES_SEEN_KEY: Final = "files_seen"
FILES_INDEXED_KEY: Final = "files_indexed"
FILES_SKIPPED_KEY: Final = "files_skipped"
BYTES_INDEXED_KEY: Final = "bytes_indexed"


class SkipReason(StrEnum):
    """Why one file is not in the corpus, from the closed set a report may name.

    The value is the name a report uses; `meta_key` is where the count is persisted. A closed set
    rather than free text, because these are reported by name and summed against a total — so a
    reason nobody declared would be a count that nothing adds up.
    """

    BINARY = "binary"
    DENIED_EXTENSION = "denied_extension"
    OVER_SIZE_CAP = "over_size_cap"
    EXCLUDED_BY_GLOB = "excluded_by_glob"
    GITIGNORED = "gitignored"
    DECODE_ERROR = "decode_error"
    SYMLINK = "symlink"
    UNREADABLE = "unreadable"

    @property
    def meta_key(self) -> str:
        """The `meta` key this reason's count is stored under."""
        return f"{SKIP_PREFIX}{self.value}"


#: The scan's own progress keys, in the order a report reads them.
PROGRESS_KEYS: Final[tuple[str, ...]] = (
    FILES_SEEN_KEY,
    FILES_INDEXED_KEY,
    FILES_SKIPPED_KEY,
    BYTES_INDEXED_KEY,
)

#: Every key the skip breakdown is reported from: the eight file reasons, then the directory count.
SKIP_REASON_KEYS: Final[tuple[str, ...]] = (
    *(reason.meta_key for reason in SkipReason),
    PRUNED_DIRECTORIES_KEY,
)


@dataclass(slots=True)
class ScanCounters:
    """One scan's counts, accumulated in memory and flushed to `meta` as the scan proceeds.

    Mutable, unlike most values in this package, because it is a running total by nature: a frozen
    counter would mean rebuilding the whole record per file, and the persisted rows are the durable
    copy in any case.

    Every count starts at zero for each scan rather than carrying over. A counter accumulating
    across scans could not answer *why is this file missing from the corpus* about the corpus in
    front of you, which is the only question the breakdown exists for.
    """

    files_seen: int = 0
    files_indexed: int = 0
    bytes_indexed: int = 0
    pruned_directories: int = 0
    skipped: dict[SkipReason, int] = field(default_factory=dict)

    @property
    def files_skipped(self) -> int:
        """The total the eight file reasons decompose. Pruned directories are not part of it."""
        return sum(self.skipped.values())

    def skip(self, reason: SkipReason) -> None:
        """Record one more file refused for `reason`."""
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def index(self, size_bytes: int) -> None:
        """Record one more file established in the index, of `size_bytes`."""
        self.files_indexed += 1
        self.bytes_indexed += size_bytes

    def as_meta_rows(self) -> Mapping[str, str]:
        """Every counter as the `meta` rows that persist it, including reasons that fired zero
        times.

        All of them on every flush, never only what changed: these rows are seeded at creation and
        read unconditionally, so a reason left unwritten would report the previous scan's count
        beside this scan's neighbours.
        """
        rows = {
            FILES_SEEN_KEY: str(self.files_seen),
            FILES_INDEXED_KEY: str(self.files_indexed),
            FILES_SKIPPED_KEY: str(self.files_skipped),
            BYTES_INDEXED_KEY: str(self.bytes_indexed),
            PRUNED_DIRECTORIES_KEY: str(self.pruned_directories),
        }
        rows.update({reason.meta_key: str(self.skipped.get(reason, 0)) for reason in SkipReason})
        return rows
