"""What `state` a knowledge base is in, and the order in which the answers are decided.

`state` answers one question — *can I trust results from this corpus* — and `knowledge-index.md`
fixes both the vocabulary and the order they are decided in. That order is behaviour rather than an
implementation detail: two conditions genuinely hold at once during a rebuild, and which one is
reported decides whether a caller searches a corpus it should not.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.knowledge import database, lock, meta


class KnowledgeState(StrEnum):
    """Whether a corpus can be trusted, and if not, what kind of not.

    `ERROR` and `REINDEX_REQUIRED` are kept apart deliberately even though both mean *unusable*: a
    build repairs the second and does not obviously repair the first, so collapsing them would
    send an operator to run a refresh against a corrupt file forever.
    """

    OK = "ok"
    INDEXING = "indexing"
    REINDEX_REQUIRED = "reindex_required"
    ROOT_MISSING = "root_missing"
    ERROR = "error"


#: Top-down: the first condition that holds is the answer. A knowledge base being rebuilt from an
#: encoder mismatch reports `reindex_required` rather than `indexing`, because reporting progress
#: would invite a search that its corpus cannot honestly answer.
PRECEDENCE: tuple[KnowledgeState, ...] = (
    KnowledgeState.ERROR,
    KnowledgeState.ROOT_MISSING,
    KnowledgeState.REINDEX_REQUIRED,
    KnowledgeState.INDEXING,
    KnowledgeState.OK,
)


@dataclass(frozen=True, slots=True)
class StateInputs:
    """Everything `resolve` needs, gathered by whoever can actually observe it.

    Separated from `resolve` so the precedence is testable without a filesystem or a database:
    the ordering is the part that is easy to get subtly wrong, and it should not need a corpus to
    exercise.
    """

    #: The database file is present but could not be opened or parsed.
    unreadable: bool
    #: No database file at all — an empty knowledge base, not an error.
    database_absent: bool
    #: The indexed directory is gone.
    root_missing: bool
    #: The recorded encoder identity no longer agrees with configuration.
    encoder_mismatch: bool
    #: No scan has ever completed: `meta.last_scan_completed_at` is absent.
    never_built: bool
    #: An indexer holds the lock.
    indexing: bool


def resolve(inputs: StateInputs) -> KnowledgeState:
    """The one state to report, decided in `PRECEDENCE` order.

    `reindex_required` has **three** causes and this is where they meet: no database file, no
    scan yet completed, or an encoder mismatch. The first two serve as an empty corpus and the
    third refuses to serve at all, which is why they share a state — the state answers whether the
    corpus can be trusted, and none of the three can be.

    `never_built` is a persisted fact rather than an emptiness test, and the difference is
    load-bearing: a first build that crashed after committing some files has rows, and reporting
    `ok` on the strength of having *some* rows would claim a currency nothing has evidence for.
    It is equally why the state is not inferred from a zero file count — a corpus over a directory
    that genuinely holds no indexable file has completed a build, and `ok` is the true answer.
    """
    if inputs.unreadable:
        return KnowledgeState.ERROR
    if inputs.root_missing:
        return KnowledgeState.ROOT_MISSING
    if inputs.database_absent or inputs.never_built or inputs.encoder_mismatch:
        return KnowledgeState.REINDEX_REQUIRED
    if inputs.indexing:
        return KnowledgeState.INDEXING
    return KnowledgeState.OK


def inputs_for_open(
    current_meta: meta.KnowledgeMeta, raw: Mapping[str, str], config: EffectiveConfig
) -> StateInputs:
    """The four questions only an *open* knowledge base can answer, gathered in one place.

    Every caller that has a knowledge base open needs exactly this, and the two that exist — a
    status report and a search — must not be able to answer the same question differently about one
    corpus. The two inputs left out are the ones this function's own precondition settles: the
    database is neither absent nor unreadable, since it is open.
    """
    return StateInputs(
        unreadable=False,
        database_absent=False,
        root_missing=not Path(current_meta.root_path).is_dir(),
        encoder_mismatch=not database.encoder_matches_config(current_meta, config),
        never_built=never_built(raw),
        indexing=lock.is_held(raw),
    )


def never_built(raw: Mapping[str, str]) -> bool:
    """Whether no build has ever completed against this knowledge base.

    Reads the absence of `last_scan_completed_at`, which is exactly the fact that key exists to
    record — a knowledge base that has not been built has no completion instant, and seeding one
    at creation would make the state unrepresentable.
    """
    return meta.LAST_SCAN_COMPLETED_AT_KEY not in raw
