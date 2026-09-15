"""The `files` table, and the two operations over a file's bytes that maintain it.

One row per indexed file; a bounded read that produces the bytes; and the hash taken over them.
The three belong together because the row is exactly what the read and the hash are for.

There is no separate checkpoint anywhere in this design. **This table *is* the progress record**:
a scan walks, compares hashes against these rows, and indexes whatever does not match, so a build
that died halfway leaves its committed files intact and resumes by doing the same thing again.

**The two hashes are different quantities and are never compared with each other.** `content_hash`
is a sha1 of the bytes actually indexed, computed in process, and it is the authority on *did what
we indexed change*. `git_blob_hash` is git's own precomputed hash of a header plus clean-filtered
content — it can never equal the first, and it is only ever compared against its own prior value,
as a way of skipping a read.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from zikaron.core.knowledge.counters import SkipReason

_COLUMNS = "path, size, content_hash, git_blob_hash, chunk_count, indexed_at"


@dataclass(frozen=True, slots=True)
class IndexedFile:
    """One file as the index records it.

    `path` is relative to the corpus root, in POSIX form, and is matched byte-exactly — which is
    what makes a case-insensitive filesystem cost a missed fast path rather than a wrong answer.

    `git_blob_hash` is `None` wherever git had nothing to say: outside a repository, for an
    untracked file, or for any scan that could not consult git at all. That is why the skip rule
    requires it to be **non-NULL** before it clears a file — comparing two absent values would
    otherwise read as agreement and skip an untracked file forever.
    """

    path: str
    size: int
    content_hash: str
    git_blob_hash: str | None
    chunk_count: int
    indexed_at: str


def read_bounded(path: Path, limit: int) -> bytes | SkipReason:
    """This file's bytes, or the reason they could not be taken.

    Bounded rather than read whole, and the bound is the corpus's own size cap. The size a walk
    checked was read before the file was opened, so a file may have grown since; one byte past the
    limit is enough to know, and refusing there is the same size rule arriving later rather than a
    new one. It is also what stops a file that grew without limit being read into memory whole.
    """
    try:
        with path.open("rb") as handle:
            raw = handle.read(limit + 1)
    except OSError:
        return SkipReason.UNREADABLE
    if len(raw) > limit:
        return SkipReason.OVER_SIZE_CAP
    return raw


def content_hash(raw: bytes) -> str:
    """The authority on whether a file's indexed bytes changed.

    Taken over the bytes exactly as read — before a byte-order mark is stripped and before
    decoding — so two files differing only by a mark are correctly different files. It is
    unaffected by git's clean filters for the same reason: it hashes what is on disk.
    """
    # Not a security decision: this value is compared against its own prior value to notice an
    # edit, never used to authenticate anything, and sha1 is what git's own object names cost.
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()


async def load_all(db: aiosqlite.Connection) -> dict[str, IndexedFile]:
    """Every indexed file, keyed by path.

    Read whole rather than queried per candidate: a scan compares its entire walk against its
    entire index, and one statement over a table of a few thousand rows costs less than the round
    trips of asking about each path in turn.
    """
    rows = await db.execute_fetchall(f"SELECT {_COLUMNS} FROM files")  # noqa: S608 — a source-level column list; no caller value is interpolated.
    found: dict[str, IndexedFile] = {}
    for path, size, hashed, blob, chunks, indexed_at in rows:
        found[str(path)] = IndexedFile(
            path=str(path),
            size=int(size),
            content_hash=str(hashed),
            git_blob_hash=None if blob is None else str(blob),
            chunk_count=int(chunks),
            indexed_at=str(indexed_at),
        )
    return found


async def record(db: aiosqlite.Connection, indexed: IndexedFile) -> None:
    """Write one file's row, replacing whatever was there.

    An upsert because both cases are ordinary and neither is worth asking about first: a file the
    corpus has never seen and a file whose content moved arrive down the same path, and the row
    that results is identical either way.
    """
    await db.execute(
        f"INSERT INTO files ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?) "  # noqa: S608 — a source-level column list; every value is bound.
        "ON CONFLICT(path) DO UPDATE SET "
        "size = excluded.size, content_hash = excluded.content_hash, "
        "git_blob_hash = excluded.git_blob_hash, chunk_count = excluded.chunk_count, "
        "indexed_at = excluded.indexed_at",
        (
            indexed.path,
            indexed.size,
            indexed.content_hash,
            indexed.git_blob_hash,
            indexed.chunk_count,
            indexed.indexed_at,
        ),
    )


async def record_git_blob_hash(
    db: aiosqlite.Connection, path: str, git_blob_hash: str | None
) -> None:
    """Store what git now calls this file, for a file whose content has not changed.

    Without this a file committed *after* it was indexed keeps a `NULL` blob hash and is therefore
    read and hashed on every scan for the rest of its life — which is every new file's ordinary
    lifecycle when a corpus indexes untracked files too. Nothing else about the row moves:
    `content_hash` is unchanged by definition, and `indexed_at` records when the content was
    indexed rather than when it was last looked at.
    """
    await db.execute("UPDATE files SET git_blob_hash = ? WHERE path = ?", (git_blob_hash, path))


async def forget(db: aiosqlite.Connection, path: str) -> None:
    """Remove one file from the index."""
    await db.execute("DELETE FROM files WHERE path = ?", (path,))


async def count(db: aiosqlite.Connection) -> int:
    """How many files the index holds."""
    rows = await db.execute_fetchall("SELECT count(*) FROM files")
    ((found,),) = list(rows)
    return int(found)


async def total_size(db: aiosqlite.Connection) -> int:
    """How many bytes of file the index holds, summed over its rows."""
    rows = await db.execute_fetchall("SELECT coalesce(sum(size), 0) FROM files")
    ((total,),) = list(rows)
    return int(total)


def unchanged_by_git(
    candidate_path: str,
    indexed: IndexedFile | None,
    *,
    listed: Mapping[str, str],
    reported_changed: frozenset[str],
) -> bool:
    """Whether git's answers alone are enough to skip reading this file.

    The rule, stated so it cannot admit NULL equalling NULL: a candidate is skipped as unchanged
    **only if** it has an indexed row, it appears in git's listing, its stored blob hash is
    non-NULL and equal to the listed one, and git's status does not report it. Every other
    candidate is read and hashed.

    The non-NULL requirement is the load-bearing half. An untracked file has no listing entry and
    no stored hash, so a comparison of two absent values would clear it as unchanged forever.

    **This fast path is correct only up to clean filters, and that is a real limit rather than a
    theoretical one.** Both of the values it reads describe *filtered* content, so a difference a
    filter erases — a line-ending normalisation, an `ident` expansion — is invisible here and the
    file is skipped without its content hash ever being consulted. A corpus configured to consult
    git not at all reads every file and is byte-exact.

    Args:
        candidate_path: the path as the walk spells it.
        indexed: this path's existing row, or `None` for a file the corpus has never indexed —
            which is changed by definition, since there is no stored hash to compare against.
        listed: git's tracked-file listing, path to blob hash. Empty where git was not consulted.
        reported_changed: the paths git's status reports, in either column.
    """
    if indexed is None or indexed.git_blob_hash is None:
        return False
    if candidate_path in reported_changed:
        return False
    return listed.get(candidate_path) == indexed.git_blob_hash
