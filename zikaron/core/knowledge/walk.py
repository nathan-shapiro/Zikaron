"""The filesystem walk: which files a corpus root offers, before git is asked anything about them.

**The walk is the sole authority on which files exist.** Filtering is deny-by-default at the
directory level and runs in a fixed order, because the order decides which reason a file's absence
is reported under and a report nobody can reproduce is worse than no report:

1. **Directory pruning**, at the directory node *before descending*. A named build or tool
   directory, or any directory whose name begins with a dot. The name `.git` is pruned whether it
   is a directory or a **file** — a linked worktree's and a submodule's are files holding a
   pointer, and directory pruning never sees those.
2. **Symlinks are not followed**, directory or file. A symlink is one refusal, whatever it points
   at: refusing to follow it is precisely declining to find out.
3. **`.gitignore`**, and 4. **globs**, and 5. **the size cap** — the first of which needs an answer
   from git, so all three are applied in one pass after the walk rather than inside it.
6. **A name-ending deny-list**, the walk-time half of text detection.

Steps 1, 2 and the `stat` for step 5 happen during the walk; steps 3 to 6 are applied by `admitted`
to what the walk found.

**What this module never does is read a file.** The whole-file UTF-8 decode that settles text
detection happens on the first read of a candidate's bytes in a scan, which is either the walk
phase's hashing read or the index phase's — running it here would read every byte of every
candidate on every scan and collapse the change-detection fast path into the read-everything path
it exists to beat.
"""

import fnmatch
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from zikaron.core.knowledge import text
from zikaron.core.knowledge.counters import ScanCounters, SkipReason

#: Directories never descended into. Several of these also begin with a dot and would be pruned by
#: that rule alone; they are named anyway, because the list says what it is *for* — version-control
#: metadata, dependency trees, build output and tool caches — and would survive the dot rule being
#: narrowed.
PRUNED_DIRECTORY_NAMES: Final = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "target",
        "dist",
        "build",
        ".next",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
    }
)

#: The one name pruned as a file as well as a directory. Every other dot-file is admitted.
_GIT_DIRECTORY_NAME: Final = ".git"


@dataclass(frozen=True, slots=True)
class WalkRules:
    """What one corpus's own configuration says about which files it wants.

    Held together rather than passed as three arguments because they are read together, in a fixed
    order, and a caller that supplied two of the three would silently index a different corpus.
    """

    include_globs: tuple[str, ...] = ()
    exclude_globs: tuple[str, ...] = ()
    max_file_bytes: int = 0


@dataclass(frozen=True, slots=True)
class Candidate:
    """One file the walk found, with what it cost nothing to learn while finding it.

    `path` is relative to the corpus root in POSIX form, and is the join key against everything
    else in the system: the `files` table, git's answers, and the globs. It is matched byte-exactly
    everywhere, so where a filesystem's casing differs from git's the two simply fail to meet and
    the file falls to the slower path — never to the wrong answer.
    """

    path: str
    absolute: Path
    size: int


def is_pruned_directory(name: str) -> bool:
    """Whether a directory of this name is one the walk refuses to descend into."""
    return name in PRUNED_DIRECTORY_NAMES or name.startswith(".")


def _relative(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def _is_directory(entry: os.DirEntry[str]) -> bool:
    """Whether this entry is a directory in its own right, never through a symlink.

    A failed `stat` answers *no*, which routes the entry to the file path where it is refused and
    counted — the one place with a number to report it under.
    """
    try:
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def _is_symlink(entry: os.DirEntry[str]) -> bool:
    """Whether this entry is a symlink. A failed `stat` answers *no*, and the entry is then
    refused as unreadable a few lines later — which is the more accurate of the two words for an
    entry whose type could not be determined."""
    try:
        return entry.is_symlink()
    except OSError:
        return False


def _child_candidate(entry: os.DirEntry[str], relative_path: str) -> Candidate | None:
    """One directory entry as a candidate, or `None` if it is not a readable regular file."""
    try:
        if not entry.is_file(follow_symlinks=False):
            return None
        size = entry.stat(follow_symlinks=False).st_size
    except OSError:
        return None
    return Candidate(path=relative_path, absolute=Path(entry.path), size=size)


def entries(root: Path, counters: ScanCounters) -> Iterator[Candidate]:
    """Every file under `root` that the directory-level rules admit, depth-first and name-ordered.

    Ordered because the order is observable: it fixes which files a partially-completed scan has
    committed, and an unordered walk makes two runs over one tree incomparable.

    Counts as it goes, and the two it can only count here are the two nothing downstream will ever
    see: a symlink, which is refused whatever it points at, and an entry that could not be taken as
    a readable regular file — a device or a pipe, a file whose `stat` failed, or a **directory that
    could not be listed**. That last one is counted among the skipped files deliberately: the walk
    cannot know how many files it did not see, so it records the one refusal it can rather than
    letting the subtree vanish silently. Everything counted here is also counted as seen, so no
    skip is ever attributed to an entry the walk did not reach.

    Args:
        root: the corpus root, already resolved.
        counters: updated in place as the walk proceeds. Mutated rather than returned because the
            caller flushes it to the database periodically, which is the only evidence a scan is
            progressing before it has worked out what changed.
    """
    stack: list[tuple[Path, str]] = [(root, "")]
    while stack:
        directory, prefix = stack.pop()
        try:
            with os.scandir(directory) as scanning:
                found = sorted(scanning, key=lambda entry: entry.name)
        except OSError:
            counters.files_seen += 1
            counters.skip(SkipReason.UNREADABLE)
            continue
        descend: list[tuple[Path, str]] = []
        for entry in found:
            yield from _visit(entry, prefix, counters, descend)
        # Reversed, because the stack is popped from the end and the names were sorted ascending.
        stack.extend(reversed(descend))


def _visit(
    entry: os.DirEntry[str],
    prefix: str,
    counters: ScanCounters,
    descend: list[tuple[Path, str]],
) -> Iterator[Candidate]:
    """Classify one directory entry, counting it and queueing it for descent as appropriate."""
    if entry.name == _GIT_DIRECTORY_NAME:
        # Pruned whether it is a directory or the pointer file a linked worktree and a submodule
        # carry. Only the directory shape is counted: the counter it feeds is reported as a number
        # of directories, and a repository's own control file is not a corpus file whose absence
        # anyone would ask about.
        if _is_directory(entry):
            counters.pruned_directories += 1
        return
    if _is_directory(entry):
        if is_pruned_directory(entry.name):
            counters.pruned_directories += 1
        else:
            descend.append((Path(entry.path), _relative(prefix, entry.name)))
        return
    # Everything that is not a directory in its own right is evaluated as a file, symlinks to
    # directories included: not following one means never learning what it points at.
    counters.files_seen += 1
    if _is_symlink(entry):
        counters.skip(SkipReason.SYMLINK)
        return
    candidate = _child_candidate(entry, _relative(prefix, entry.name))
    if candidate is None:
        counters.skip(SkipReason.UNREADABLE)
        return
    yield candidate


def _matches_any(path: str, patterns: Sequence[str]) -> bool:
    """Whether the relative POSIX path matches any pattern, case-sensitively.

    `fnmatch`'s `*` crosses `/`, which is what makes `*.md` reach `docs/a.md` and `docs/*` mean
    the whole tree under `docs` rather than its direct children. Case-sensitive because this path
    is the same byte-exact string the index stores, so a pattern means one thing to the walk and
    to anyone reading the index back.

    The one surprise, since it is otherwise met as an empty corpus: **`**` carries no meaning of
    its own here**. It is two stars, so `docs/**/*.md` asks for a file two directories down and
    gets exactly that, where a reader used to git's globbing expects the whole tree. It fails
    closed rather than quietly wide, and `docs/*` is the pattern that means what they wanted.
    """
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def admitted(
    found: Sequence[Candidate],
    *,
    ignored: frozenset[str],
    rules: WalkRules,
    counters: ScanCounters,
) -> list[Candidate]:
    """The candidates that survive `.gitignore`, the globs, the size cap and the deny-list.

    Applied in that order, and the order is the reported answer rather than an optimisation: a
    file that is both ignored and over the cap is reported as ignored, and two implementations
    disagreeing about which would give two different accounts of one corpus.

    Args:
        found: what the walk yielded, in its order, which is preserved.
        ignored: the paths `.gitignore` excludes. Empty where git was not consulted, which is the
            same thing as applying no ignore rules.
        rules: this corpus's globs and size cap.
        counters: updated in place with one skip per refused file.
    """
    kept: list[Candidate] = []
    for candidate in found:
        reason = _refusal(candidate, ignored=ignored, rules=rules)
        if reason is None:
            kept.append(candidate)
        else:
            counters.skip(reason)
    return kept


def _refusal(
    candidate: Candidate, *, ignored: frozenset[str], rules: WalkRules
) -> SkipReason | None:
    if candidate.path in ignored:
        return SkipReason.GITIGNORED
    if _matches_any(candidate.path, rules.exclude_globs):
        return SkipReason.EXCLUDED_BY_GLOB
    if rules.include_globs and not _matches_any(candidate.path, rules.include_globs):
        return SkipReason.EXCLUDED_BY_GLOB
    if candidate.size > rules.max_file_bytes:
        return SkipReason.OVER_SIZE_CAP
    if text.extension_denied(candidate.absolute.name):
        return SkipReason.DENIED_EXTENSION
    return None
