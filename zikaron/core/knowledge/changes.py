"""What changed since the last build, decided before anything is written.

The authority is our own content hash — a hash of the bytes actually indexed, computed in process.
Git is consulted only as a way of *not reading* a file: where it can show that both its own
precomputed hash and its status agree with what was stored, the file is cleared without opening
it, which is roughly an order of magnitude cheaper than reading a tree of them.

**The read that answers "did this change" is also this scan's first sight of the file's bytes**,
so text detection runs on it here rather than waiting for the indexing read. A file that fails it
was indexed once and is not indexable now, so it stops being a candidate — and because the walk
phase is what discovered that, the walk phase is what deletes it.

Modification times are never consulted, at all: they are unreliable under checkout, under `touch`
and under clock skew, and a change detector that trusts one silently serves stale text.

**Comparison can be bypassed entirely**, for the caller whose reason to reindex is not that the
files moved — a chunk budget that changed, or content the index was handed through a filter that
has since changed under it. Every candidate is then changed by decree, and nothing else about the
scan differs.

**This is synchronous, and deliberately runs as one unit off the event loop.** It reads every
candidate git could not clear, and a thread hop per file would cost more in scheduling than the
reads themselves cost on a corpus of ordinary size.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from zikaron.core.knowledge import files, text, walk
from zikaron.core.knowledge.candidates import GitAnswers
from zikaron.core.knowledge.counters import ScanCounters, SkipReason
from zikaron.core.knowledge.meta import GitMode


@dataclass(slots=True)
class Comparison:
    """What comparing the walk against the index established.

    `changed` is what the index phase must do; `previously_indexed` says which of those already
    had a row, which is the difference between a deletion and a recorded skip when one of them
    turns out not to be text. `no_longer_admitted` is what stopped being part of the corpus during
    this comparison, which the caller folds into its deletions.
    """

    changed: list[str] = field(default_factory=list)
    previously_indexed: set[str] = field(default_factory=set)
    unchanged: list[files.IndexedFile] = field(default_factory=list)
    no_longer_admitted: set[str] = field(default_factory=set)
    blob_hash_refreshes: dict[str, str | None] = field(default_factory=dict)

    def keep(self, row: files.IndexedFile, listed: str | None, *, git_answered: bool) -> None:
        """Record a file as still in the index, and note a blob hash that has moved under it.

        The refresh matters more than it looks: a file committed *after* it was indexed keeps a
        null blob hash, and without writing the new one it is read and hashed on every scan for
        the rest of its life — which is every new file's ordinary lifecycle in a corpus that
        indexes untracked files too.

        **Nothing is refreshed when git was not consulted**, and the distinction is the whole
        reason this takes a flag. *Git says this file is untracked* and *git was never asked* both
        arrive here as an absent listing entry, and only the first is an observation. Treating the
        second as one would null every stored hash in the corpus on a scan that degraded — a
        container's dubious-ownership refusal, say — and charge the next healthy scan a full read
        of every file to build them again. Keeping the old value is safe in the other direction:
        a stale hash can only fail the equality test and route a file to be read, never clear one
        that changed.
        """
        self.unchanged.append(row)
        if git_answered and listed != row.git_blob_hash:
            self.blob_hash_refreshes[row.path] = listed

    def reindex(self, path: str, *, was_indexed: bool) -> None:
        """Record a file the index phase must read and write."""
        self.changed.append(path)
        if was_indexed:
            self.previously_indexed.add(path)


@dataclass(frozen=True, slots=True)
class Criteria:
    """What every candidate in one comparison is judged against.

    Held together so that the per-candidate step takes the comparison, the candidate, its row and
    *the scan* — rather than a parameter list long enough that one call site could pass a
    different size cap from the one the walk admitted files under.

    `bypass` treats every admitted candidate as changed, asking neither git nor the stored hash.
    What a caller wants when the thing that moved is not the files: a chunk budget that changed, or
    a file whose stored text was rewritten by a clean filter the index never saw.

    `git_answered` is derived once, here, for the same reason the rest is held together: both
    places that keep a file need it, and two independent derivations of one boolean are how one of
    them keeps a stale expression after the other moves.
    """

    answers: GitAnswers
    counters: ScanCounters
    max_file_bytes: int
    bypass: bool = False

    @property
    def git_answered(self) -> bool:
        """Whether git was consulted at all, which is not the same as its having found nothing."""
        return self.answers.effective is not GitMode.OFF


def compare(
    admitted: Sequence[walk.Candidate],
    indexed: Mapping[str, files.IndexedFile],
    criteria: Criteria,
) -> Comparison:
    """Sort the admitted candidates into changed, unchanged, and no longer indexable.

    A candidate with no indexed row is changed by definition — there is no stored hash to compare
    it against — so it is not read here at all, and the index phase is its first and only read.
    Every other candidate that git could not clear is read and hashed, unless the comparison is
    bypassed, in which case none of them is read here at all.

    Args:
        admitted: the candidates that survived every filter, in walk order.
        indexed: every existing row, keyed by path.
        criteria: what this scan judges its candidates against, including whether to skip the
            comparison entirely. Its counters are updated in place for each file that stops being
            indexable.
    """
    answers = criteria.answers
    comparison = Comparison()
    for candidate in admitted:
        row = indexed.get(candidate.path)
        if row is None or criteria.bypass:
            comparison.reindex(candidate.path, was_indexed=row is not None)
        elif files.unchanged_by_git(
            candidate.path, row, listed=answers.listed, reported_changed=answers.reported_changed
        ):
            comparison.keep(
                row,
                answers.listed.get(candidate.path),
                git_answered=criteria.git_answered,
            )
        else:
            _classify(comparison, candidate, row, criteria)
    return comparison


def _classify(
    comparison: Comparison,
    candidate: walk.Candidate,
    row: files.IndexedFile,
    criteria: Criteria,
) -> None:
    """Read one already-indexed candidate git could not clear, and decide what became of it."""
    raw = files.read_bounded(candidate.absolute, criteria.max_file_bytes)
    if raw is SkipReason.UNREADABLE:
        # Neither question this read answers can be answered, so the file is treated as changed
        # and the index phase's own read is left to decide — and to count — what became of it.
        # Counting it here as well would report one file twice in one scan.
        comparison.reindex(candidate.path, was_indexed=True)
        return
    if isinstance(raw, SkipReason):
        criteria.counters.skip(raw)
        comparison.no_longer_admitted.add(candidate.path)
        return
    detection = text.sniff(raw)
    if isinstance(detection, text.NotText):
        criteria.counters.skip(detection.reason)
        comparison.no_longer_admitted.add(candidate.path)
        return
    if files.content_hash(raw) == row.content_hash:
        comparison.keep(
            row,
            criteria.answers.listed.get(candidate.path),
            git_answered=criteria.git_answered,
        )
    else:
        comparison.reindex(candidate.path, was_indexed=True)
