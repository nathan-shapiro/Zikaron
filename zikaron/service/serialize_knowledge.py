"""The wire shapes the knowledge-base management methods answer in, one dataclass per object.

Separate from `serialize.py` for the reason the two subsystems are separate everywhere else: these
shapes are copied field-for-field from `knowledge-index.md` §8.5, where `serialize.py`'s come from
`architecture.md`'s tool-surface tables, and putting them in one module would invite a reader to
look for one document behind both.

**Field names are the response's, not the report's, and the two differ on purpose.** A skip
reason's `meta` key is `skipped_binary` and its reported name is `binary`; a corpus's stored globs
are `include_globs`/`exclude_globs` and the response calls them `include`/`exclude`. The mapping is
a rule rather than a coincidence, so it is applied in one place — here — rather than at whichever
call site happened to build a dict.

**`zikaron_knowledge_search` deliberately does *not* come through here.** Its response's size is
capped by measuring the encoded answer, so the object measured and the object sent have to be the
same one; building it twice is exactly how a measurement comes to describe something other than
what was delivered. Nothing here is under a cap, so every shape is built field by field, which is
what makes a renamed field a type error rather than a `KeyError` in front of a model.
"""

from dataclasses import dataclass

from zikaron.core.knowledge import reporting
from zikaron.core.knowledge.builds import PlannedBuild
from zikaron.service.serialize import RpcResult


def _lock_payload(report: reporting.LockReport) -> dict[str, object]:
    """One build lock's holder, as `status` reports it."""
    return {
        "pid": report.pid,
        "host": report.host,
        "started_at": report.started_at,
        "age_seconds": report.age_seconds,
        "live": report.live,
    }


def _summary_payload(summary: reporting.Summary) -> dict[str, object]:
    """The fields a caller needs in order to *choose* a corpus — what `list` returns."""
    return {
        "name": summary.name,
        "description": summary.description,
        "state": summary.state.value,
        "files_indexed": summary.files_indexed,
        "files_remaining": summary.files_remaining,
    }


def _details_payload(details: reporting.Details) -> dict[str, object]:
    """The diagnostic half of `status`: why a corpus is the way it is."""
    effective = details.git_mode_effective
    return {
        "root_path": details.root_path,
        "git_mode": details.git_mode.value,
        "git_mode_effective": None if effective is None else effective.value,
        "include": list(details.include_globs),
        "exclude": list(details.exclude_globs),
        "max_file_bytes": details.max_file_bytes,
        "chunks": details.chunks,
        "bytes_indexed": details.bytes_indexed,
        "files_seen": details.files_seen,
        "files_skipped": details.files_skipped,
        "skipped": dict(details.skipped),
        "searches": details.searches,
        "searches_empty": details.searches_empty,
        "results_returned": details.results_returned,
        "results_stale": details.results_stale,
        "last_scan_started_at": details.last_scan_started_at,
        "last_scan_completed_at": details.last_scan_completed_at,
        "lock": None if details.lock is None else _lock_payload(details.lock),
    }


@dataclass(frozen=True, slots=True)
class KnowledgeBaseJson:
    """One knowledge base's report: `list`'s fields, plus `status`'s when there are any.

    `detailed` decides which of the two calls this is, rather than the caller passing a
    pre-built dict, so "`list` is `status` projected down" stays a property of one function.
    A corpus with no readable database has no diagnostic half at all, and every one of those
    fields is then absent rather than zeroed — a zero no stored value backs is a confident
    answer to a question nothing could answer.
    """

    status: reporting.Status
    detailed: bool

    def as_json(self) -> dict[str, object]:
        payload = _summary_payload(self.status.summary)
        if self.detailed and self.status.details is not None:
            payload.update(_details_payload(self.status.details))
        return payload


@dataclass(frozen=True, slots=True)
class OrphanJson:
    """A knowledge-base database no registry row points at.

    `name` is the file's own non-authoritative copy of what it was called, and is `null` when the
    file will not give one up — which is exactly when a reader needs telling the file is there
    rather than what it held.
    """

    orphan: reporting.Orphan

    def as_json(self) -> dict[str, object]:
        return {
            "path": str(self.orphan.path),
            "name": self.orphan.breadcrumb_name,
            "size_bytes": self.orphan.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeListResult(RpcResult):
    """`knowledge_list`'s shape: `{knowledge_bases}`, each projected down to the choosing fields."""

    reports: tuple[reporting.Status, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "knowledge_bases": [
                KnowledgeBaseJson(status=report, detailed=False).as_json()
                for report in self.reports
            ]
        }


@dataclass(frozen=True, slots=True)
class KnowledgeStatusResult(RpcResult):
    """`knowledge_status`'s shape: `{knowledge_bases, orphans}`, with the diagnostic half.

    `orphans` is empty when a single corpus was named, since an orphan belongs to no knowledge base
    and attaching one to a report about a named corpus would be attaching it arbitrarily. The key
    is present either way, so a caller reads its contents rather than testing for it.
    """

    reports: tuple[reporting.Status, ...]
    orphans: tuple[reporting.Orphan, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "knowledge_bases": [
                KnowledgeBaseJson(status=report, detailed=True).as_json() for report in self.reports
            ],
            "orphans": [OrphanJson(orphan=one).as_json() for one in self.orphans],
        }


def _build_entry(entry: PlannedBuild) -> dict[str, object]:
    """One corpus's line in a build result: what it is, and what this call did about it.

    `started` is read off the absence of an obstacle rather than from a record of which spawns
    happened, because a spawn that fails raises and takes the whole call with it: nothing reaches
    this function after a failed spawn. What that does *not* claim is that a sweep is atomic — the
    corpora ahead of the failure have live indexers against them, and they keep running. It claims
    only that no entry reporting `started` describes a corpus whose spawn was never made.
    """
    payload = KnowledgeBaseJson(status=entry.status, detailed=False).as_json()
    obstacle = entry.obstacle
    payload["outcome"] = "started" if obstacle is None else obstacle.value
    return payload


@dataclass(frozen=True, slots=True)
class KnowledgeBuildResult(RpcResult):
    """What `knowledge_add` and `knowledge_refresh` answer: each corpus's summary plus an `outcome`.

    One shape for both verbs and for both of `refresh`'s forms, so a caller parses one thing rather
    than three. Each entry is the **`list` projection** — name, description, state, files indexed,
    files remaining — in `status`'s own field names and vocabulary, which is what lets an agent
    read the result it already holds instead of learning a second one. The twenty diagnostic fields
    are deliberately not here: a verb that starts a build has no more of them to report than
    `list` does, and `add`'s own description points a caller at `zikaron_knowledge_status` for the
    detail.

    `git_modes` is `add`'s own creation-time probe and is absent for a refresh, which runs none. It
    sits beside the per-corpus entries rather than inside them, under its own names —
    `requested_git_mode` and `effective_git_mode` — because `status`'s per-corpus
    `git_mode_effective` answers a different question, *what the last completed build used*, and
    for a corpus created a moment ago that is `null` until one finishes. One name for two subjects
    across two calls is the seam this avoids.
    """

    planned: tuple[PlannedBuild, ...]
    git_modes: tuple[str, str] | None = None

    def as_json(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "knowledge_bases": [_build_entry(entry) for entry in self.planned]
        }
        if self.git_modes is not None:
            requested, effective = self.git_modes
            payload["requested_git_mode"] = requested
            payload["effective_git_mode"] = effective
        return payload


@dataclass(frozen=True, slots=True)
class KnowledgeRenameResult(RpcResult):
    """`knowledge_rename`'s shape: the renamed corpus under its new name, and nothing else.

    The same `{knowledge_bases: [...]}` envelope as the other management verbs, carrying one entry,
    rather than a bare object — so a caller that handles `add` and `refresh` handles this too. No
    `outcome`, because a rename starts no build.
    """

    status: reporting.Status

    def as_json(self) -> dict[str, object]:
        return {
            "knowledge_bases": [KnowledgeBaseJson(status=self.status, detailed=False).as_json()]
        }


@dataclass(frozen=True, slots=True)
class KnowledgeRemoveResult(RpcResult):
    """`knowledge_remove`'s shape: `{removed, knowledge_bases, files_unlinked}`.

    The status is a final snapshot taken before the row was deleted, since the corpus no longer
    exists to be polled. It carries the diagnostic half, because it is the last chance to see what
    was destroyed. `files_unlinked` reports what was actually on disk rather than what was
    attempted. A live database in WAL mode is three files, but reading a corpus's state opens and
    closes it and SQLite reclaims its own `-wal` and `-shm` on the last close — so one path is the
    ordinary answer whether or not the corpus was ever built, and the length says nothing about
    what it held.
    """

    status: reporting.Status
    files_unlinked: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "removed": True,
            "knowledge_bases": [KnowledgeBaseJson(status=self.status, detailed=True).as_json()],
            "files_unlinked": list(self.files_unlinked),
        }
