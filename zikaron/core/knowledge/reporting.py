"""What `list` and `status` report about a knowledge base, and how each field is derived.

`knowledge-index.md` is normative, and its central claim about these two calls is the one this
module exists to keep true: **`list` is `status` projected down**, never a parallel answer. So
there is one gathering step and two views of its result, rather than two queries that agree today.

Field names map to `meta` keys by dropping the `skipped_` prefix. That is stated as a rule so the
difference is deliberate rather than drift.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import aiosqlite

from zikaron.core.knowledge import meta, state
from zikaron.core.knowledge.registry import KnowledgeBase

_SKIP_PREFIX = "skipped_"


def _reported_skip_name(key: str) -> str:
    """The `status` field one skip-reason `meta` key is reported under."""
    return key.removeprefix(_SKIP_PREFIX)


@dataclass(frozen=True, slots=True)
class Summary:
    """The fields a caller needs in order to *choose* a corpus — what `list` returns.

    `files_remaining` is `None` both when no build is running and when one has started but has not
    yet worked out what changed. Those are deliberately one value rather than two: `0` would read
    as *nothing left to do* when the truth is *not yet counted*, and that is the reading that
    makes a caller stop waiting.
    """

    name: str
    description: str
    state: state.KnowledgeState
    files_indexed: int
    files_remaining: int | None


@dataclass(frozen=True, slots=True)
class Details:
    """The diagnostic half of `status`: why a corpus is the way it is.

    A separate type from `Summary` because it has a separate availability. Every field here is
    read out of the knowledge base's own database, so a knowledge base that has no readable
    database has none of them — which `Status.details` says by being `None` rather than by
    reporting zeros that no stored value backs.

    `git_mode_effective` is `None` until a build has recorded one. It is read from what the last
    build actually used rather than recomputed now, because the value that explains an indexed
    corpus is the one that shaped it, not whatever the environment happens to say today.
    """

    root_path: str
    git_mode: meta.GitMode
    git_mode_effective: meta.GitMode | None
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]
    max_file_bytes: int
    chunks: int
    bytes_indexed: int
    files_seen: int
    files_skipped: int
    skipped: Mapping[str, int]
    searches: int
    searches_empty: int
    results_returned: int
    results_stale: int
    last_scan_started_at: str | None
    last_scan_completed_at: str | None


@dataclass(frozen=True, slots=True)
class Status:
    """Everything `list` returns, plus the diagnostic half when there is one to report.

    Composition rather than one wide dataclass, so "`list` is `status` projected down" is a fact
    about the types rather than a convention two constructors have to keep.
    """

    summary: Summary
    details: Details | None


@dataclass(frozen=True, slots=True)
class Orphan:
    """A knowledge-base database with no registry row.

    The residue of an interrupted `remove`. Reported, never opened for search, and never deleted
    on its own — an unreferenced database may hold a corpus somebody wants back after a botched
    removal, and that is worth more than the disk it occupies.

    `breadcrumb_name` is read from the file's own non-authoritative name copy, which is what that
    copy exists for. It is `None` when the file cannot be read, which is exactly when a human
    needs to be told the file is there rather than what it was called.
    """

    path: Path
    breadcrumb_name: str | None
    size_bytes: int


def _counter(raw: Mapping[str, str], key: str) -> int:
    """One counter's value, treating anything unreadable as zero.

    Counters are seeded at creation, so a missing or malformed one means a database somebody
    edited by hand — and a diagnostic report is the wrong place to refuse over it. The identity
    keys, which decide whether a corpus can be served at all, are validated strictly instead.
    """
    try:
        return int(raw[key])
    except (KeyError, ValueError):
        return 0


def _git_mode_or_none(value: str | None) -> meta.GitMode | None:
    if value is None:
        return None
    try:
        return meta.GitMode(value)
    except ValueError:
        return None


async def _count(db: aiosqlite.Connection, table: str) -> int:
    # `table` is one of this module's own literals, never a caller's value, so there is nothing
    # here for a parameter to protect: SQLite does not accept a table name as one in any case.
    rows = await db.execute_fetchall(f"SELECT count(*) FROM {table}")  # noqa: S608
    ((count,),) = list(rows)
    return int(count)


async def files_remaining(db: aiosqlite.Connection, raw: Mapping[str, str]) -> int | None:
    """How many files a running build has left to dispose of, or `None` when that is not a number.

    The rule needs a persisted discriminator because the process answering this may not be the one
    building, and "walk finished, nothing changed" and "walk still running" are otherwise
    byte-identical states: an empty `pending` table either way, with nothing left in it to carry a
    timestamp. So the count is a number only when the lock is held **and** the walk phase's own
    completion instant is at least as recent as the build's start.
    """
    if not state.lock_is_held(raw):
        return None
    started = raw.get(meta.LAST_SCAN_STARTED_AT_KEY)
    walked = raw.get(meta.LAST_WALK_COMPLETED_AT_KEY)
    if started is None or walked is None or walked < started:
        return None
    return await _count(db, "pending")


async def gather(
    registered: KnowledgeBase,
    db: aiosqlite.Connection,
    current_meta: meta.KnowledgeMeta,
    raw: Mapping[str, str],
    *,
    corpus_state: state.KnowledgeState,
) -> Status:
    """Everything reportable about one open knowledge base.

    `name` and `description` come from the **registry**, never from the database's breadcrumb: the
    registry owns them, and a report preferring the copy would be authoritative about the wrong
    one of two values that are allowed to disagree.
    """
    return Status(
        summary=Summary(
            name=registered.name,
            description=registered.description,
            state=corpus_state,
            files_indexed=_counter(raw, "files_indexed"),
            files_remaining=await files_remaining(db, raw),
        ),
        details=Details(
            root_path=current_meta.root_path,
            git_mode=current_meta.git_mode,
            git_mode_effective=_git_mode_or_none(raw.get(meta.LAST_SCAN_GIT_MODE_EFFECTIVE_KEY)),
            include_globs=current_meta.include_globs,
            exclude_globs=current_meta.exclude_globs,
            max_file_bytes=current_meta.max_file_bytes,
            chunks=await _count(db, "chunks"),
            bytes_indexed=_counter(raw, "bytes_indexed"),
            files_seen=_counter(raw, "files_seen"),
            files_skipped=_counter(raw, "files_skipped"),
            skipped=MappingProxyType(
                {_reported_skip_name(key): _counter(raw, key) for key in meta.SKIP_REASON_KEYS}
            ),
            searches=_counter(raw, "searches"),
            searches_empty=_counter(raw, "searches_empty"),
            results_returned=_counter(raw, "results_returned"),
            results_stale=_counter(raw, "results_stale"),
            last_scan_started_at=raw.get(meta.LAST_SCAN_STARTED_AT_KEY),
            last_scan_completed_at=raw.get(meta.LAST_SCAN_COMPLETED_AT_KEY),
        ),
    )


def without_details(registered: KnowledgeBase, corpus_state: state.KnowledgeState) -> Status:
    """What to report for a knowledge base whose database is absent or could not be read.

    `files_indexed` is `0` because a corpus with no readable database has indexed nothing that can
    be served, which is a claim about availability rather than a guess at a stored number.
    Everything else the database would have supplied is absent rather than zeroed, so a caller is
    never handed a confident value that no stored one backs.
    """
    return Status(
        summary=Summary(
            name=registered.name,
            description=registered.description,
            state=corpus_state,
            files_indexed=0,
            files_remaining=None,
        ),
        details=None,
    )
