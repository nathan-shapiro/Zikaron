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
    #: The vector table is declared at a width the recorded identity does not name, so nothing
    #: carrying that identity can be inserted into it. A backstop rather than the ordinary route to
    #: this state — see `resolve`.
    width_mismatch: bool
    #: What a completed build left is not what is stored: `meta.last_scan_completed_at` is absent,
    #: because no build has ever completed or because one was dropped.
    never_built: bool
    #: A build is running — a lock held by somebody this machine cannot show has stopped.
    indexing: bool


def resolve(inputs: StateInputs) -> KnowledgeState:
    """The one state to report, decided in `PRECEDENCE` order.

    `reindex_required` has **four** causes and this is where they meet: no database file, no scan
    yet completed, an encoder mismatch, and a vector table left at a width the recorded identity
    does not name. All four answer a search the same way — the group carries this state and no
    results — which is why they share a state: it answers whether the corpus can be trusted, and
    none of the four can be. What differs between them is only what the emptiness means, and that
    is a matter for whoever reads the report rather than for anything here.

    **A rebuild interrupted and then seen through is caught by `never_built` alone, and nothing else
    could catch it.** The transaction that empties a corpus for a rebuild also records the model
    about to refill it, so afterwards `meta` names exactly what is stored; leave configuration
    naming that model and every comparison this module makes is quiet — the encoder agrees, the
    width agrees. What the same transaction clears is the completion instant, and that is the whole
    of what holds the knowledge base out of service until a scan finishes: it reports that what a
    completed build left is not what it holds, which is true of what is stored.

    **Where the operator reverts instead, `encoder_mismatch` fires as well**, since `meta` names the
    model the abandoned run was writing and configuration now names the older one. Both causes are
    true, the state is the same, and the repair differs: the mismatch is what makes the next scan
    drop and redo the corpus rather than resume it, which is correct, because the rows the dead run
    committed were made by the model being abandoned.

    **`width_mismatch` is therefore not the route to this state but a backstop against tampering.**
    The drop declares the vector table's width and records the identity naming that width in one
    transaction, so nothing this package does can separate them. What this input guards is a `meta`
    and a table separated by something else — a database file restored from a backup of another
    build, a hand-edited row — where the corpus would otherwise report `ok` and every later build
    would die inserting a vector of the recorded width into a table declared for another, one
    rejected insert per file in a process whose output nobody reads. **What repairs that case is a
    different test**, in `repair.rebuilt_identity`, which reads the same width to decide what the
    rebuilding scan declares the table at.

    `never_built` is a persisted fact rather than an emptiness test, and the difference is
    load-bearing in both directions. A first build that crashed after committing some files has
    rows, and reporting `ok` on the strength of having *some* rows would claim a currency nothing
    has evidence for; it is equally why the state is not inferred from a zero file count, since a
    corpus over a directory that genuinely holds no indexable file has completed a build and `ok` is
    the true answer there. And because the fact is *persisted*, the one transaction that destroys a
    built corpus can withdraw it — which is the only reason this input covers a rebuild at all.
    """
    if inputs.unreadable:
        return KnowledgeState.ERROR
    if inputs.root_missing:
        return KnowledgeState.ROOT_MISSING
    if (
        inputs.database_absent
        or inputs.never_built
        or inputs.encoder_mismatch
        or inputs.width_mismatch
    ):
        return KnowledgeState.REINDEX_REQUIRED
    if inputs.indexing:
        return KnowledgeState.INDEXING
    return KnowledgeState.OK


def inputs_for_open(
    opened: database.KnowledgeDatabase, raw: Mapping[str, str], config: EffectiveConfig
) -> StateInputs:
    """Every question only an *open* knowledge base can answer, gathered in one place.

    Every caller that has a knowledge base open needs exactly this, and the two that exist — a
    status report and a search — must not be able to answer the same question differently about one
    corpus. The two inputs left out are the ones this function's own precondition settles: the
    database is neither absent nor unreadable, since it is open.

    **`indexing` asks whether a build is *running*, not whether lock rows exist.** Those rows
    survive a build that was killed, deliberately, and reporting a corpus as mid-scan on the
    strength of them would say *a scan is in flight* for as long as nobody started another one.
    A build on another machine still counts, because nothing here can show it has stopped.

    **Unlike `encoder_mismatch`, `width_mismatch` compares the vector table against `meta` rather
    than against configuration**, so a configuration change can neither create nor clear it: it
    reports the state of the stored table rather than an opinion about it.
    """
    return StateInputs(
        unreadable=False,
        database_absent=False,
        root_missing=not Path(opened.meta.root_path).is_dir(),
        encoder_mismatch=not database.encoder_matches_config(opened.meta, config),
        width_mismatch=opened.vector_width != opened.meta.embed_dim,
        never_built=never_built(raw),
        indexing=lock.running_holder(raw, host=lock.this_host()) is not None,
    )


def never_built(raw: Mapping[str, str]) -> bool:
    """Whether what a completed build left is what this knowledge base now holds.

    Reads the absence of `last_scan_completed_at`, which is what that key exists to record — a
    knowledge base that has not been built has no completion instant, and seeding one at creation
    would make the state unrepresentable.

    **Absent covers two conditions, and the second is why the reading is about the stored corpus
    rather than about history.** No build has ever completed; or one did, and the transaction that
    dropped everything it produced withdrew the instant along with it. A corpus emptied by a rebuild
    that was then interrupted is, as far as anything readable goes, one that has never been built —
    and saying so is what stops it answering searches as though it had.
    """
    return meta.LAST_SCAN_COMPLETED_AT_KEY not in raw
