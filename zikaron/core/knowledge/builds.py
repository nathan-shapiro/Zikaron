"""What must hold before a build is worth starting, and what stops one.

**A build is usually not run by the process that asked for one.** It is spawned detached, with its
output discarded and nowhere to report a refusal to, so every refusal decidable without reading a
file is decided here, in front of whoever asked. The build re-establishes each of them for itself,
because this and the build are not one transaction and the second is the one whose answer is acted
on — but by then there is nobody to tell.

**One classification, two callers, and they differ only in what they do with it.** A caller naming
one knowledge base wants the refusal *raised*, because with one corpus named there is nothing else
in the answer and a success carrying only a refusal is the shape this system refuses to produce. A
caller sweeping every knowledge base wants it *reported*, because failing the sweep for one
corpus's sake would deny the others a build they could have had. Deriving both from one function is
what keeps the two from disagreeing about, for instance, whether a corpus whose root has gone and
whose lock is held reports the missing root or the running build.

**The ordering is not this module's to choose.** It reads the state a corpus reports, so the answer
follows the same precedence every other reader sees: a database that will not open before a missing
root, a missing root before a running build.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.knowledge import registry, reporting, roots
from zikaron.core.knowledge.errors import (
    CorpusRootMissingError,
    DanglingKnowledgeBaseError,
    IndexerBusyError,
)
from zikaron.core.knowledge.registry import KnowledgeBase
from zikaron.core.knowledge.state import KnowledgeState


class BuildObstacle(StrEnum):
    """Why a build was not started for one knowledge base.

    A closed set of its own rather than a reading of `state`, because of one pair `state` cannot
    separate: a corpus that has never been built and a corpus whose database file is gone both
    report `reindex_required`, and the first starts a build while the second can never have one.
    Every member names the condition that stopped the build rather than restating the corpus's
    state.
    """

    #: A build that cannot be shown to be dead already holds this corpus's lock. Nothing was
    #: queued and nothing blocked: this is the idempotent case rather than a failure.
    ALREADY_INDEXING = "already_indexing"
    #: Registered, with no database file — so everything that said what to index is gone with it,
    #: and there is nothing for a walk to walk. Repaired by removing the name and adding it again,
    #: which loses nothing: a corpus in this state has never indexed anything.
    NO_DATABASE = "no_database"
    #: The indexed directory is gone. The index is kept as it is, ready for the root's return.
    ROOT_MISSING = "root_missing"
    #: The database is present and will not open. A build does not obviously repair it.
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class PlannedBuild:
    """One knowledge base's answer to *may a build start, and what is it now*.

    Carries the status as well as the verdict because the two answer different questions and a
    caller reporting this needs both: the verdict says what this call did, and the status says
    what the corpus is, which a verdict alone cannot supply — `started` says nothing about whether
    the corpus was empty, mid-rebuild or merely out of date.

    `refusal` is the exception a caller that must raise should raise. It is built here rather than
    at the raise site so that the reported obstacle and the raised message can never describe
    different conditions, and for `UNREADABLE` it is the driver's own exception rather than a
    message invented for it.
    """

    knowledge_base: KnowledgeBase
    status: reporting.Status
    obstacle: BuildObstacle | None
    refusal: Exception | None

    @property
    def may_start(self) -> bool:
        """Whether this corpus is ready for an indexer to be spawned against it."""
        return self.obstacle is None


def _stopped_by(
    registered: KnowledgeBase, observed: reporting.Observed
) -> tuple[BuildObstacle, Exception] | None:
    """What stops a build against this corpus and what a caller naming it would be raised, or
    `None` if nothing stops one.

    The obstacle and the exception are decided together, in one pass, so the reported condition
    and the raised message can never describe different things — and so that each branch builds
    its exception where the value it needs is in hand, rather than asserting it back later.

    The conditions are read off what the corpus already reports rather than re-derived, so two
    that hold at once resolve in the order every other reader sees. Two readings do that work.
    **Having no diagnostic half** is what separates the two conditions that share
    `reindex_required`: a database that is absent, and one that is merely unbuilt — the unbuilt one
    opens and has details to report. And among those with no details — the absent database and one
    that is present and will not open — **whether a failure was recorded** is what separates them.
    That second reading is the same question as the state, which `Observed` holds together as one
    fact, and it is asked this way round because the recorded failure is what a caller must be
    handed rather than something to look up afterwards.
    """
    details = observed.status.details
    if details is None:
        # Branching on the recorded failure rather than on the state, which `Observed` guarantees
        # are the same question: the driver's own exception is what a caller has to be given, so
        # asking for it directly leaves nothing to invent when it is absent. Nothing here could
        # say what went wrong better than the exception does, and nothing the caller can do fixes
        # it either way — so it stays a failure rather than becoming a refusal.
        failure = observed.unreadable_because
        if failure is not None:
            return BuildObstacle.UNREADABLE, failure
        return BuildObstacle.NO_DATABASE, DanglingKnowledgeBaseError(
            f"{registered.name!r} has no database, so nothing records what it indexes; "
            f"remove it and add it again"
        )
    if observed.status.summary.state is KnowledgeState.ROOT_MISSING:
        return BuildObstacle.ROOT_MISSING, CorpusRootMissingError(
            roots.missing_root_message(Path(details.root_path))
        )
    holder = observed.blocker
    if holder is not None:
        return BuildObstacle.ALREADY_INDEXING, IndexerBusyError(
            f"a build is already running against {registered.name!r} ({holder.describe()})",
            holder=holder,
        )
    return None


async def plan(
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
    *,
    names: Sequence[str] | None,
) -> tuple[PlannedBuild, ...]:
    """Classify a build for each named corpus, or for every registered one.

    Args:
        store_dir: the `.zikaron` directory this store lives in.
        db: an open connection to `memory.db`, which carries the registry.
        config: the effective configuration, used only to decide whether each corpus's recorded
            encoder identity still agrees with it. A disagreement is not an obstacle — it is what
            the build repairs.
        names: which corpora to plan for, or `None` for every registered one. A name that is
            registered under a different case is the same name.

    Returns:
        One entry per corpus, in the order named — or in registry order when none were.

    Raises:
        InvalidNameError: a name is empty or blank.
        UnknownKnowledgeBaseError: a name is registered under nothing. Raised rather than reported,
            because it is a fact about the request rather than about any corpus.
    """
    await registry.ensure(db)
    if names is None:
        wanted = list(await registry.list_all(db))
    else:
        wanted = [await registry.require(db, name) for name in names]
    planned: list[PlannedBuild] = []
    for registered in wanted:
        observed = await reporting.observe(store_dir, registered, config)
        stopped = _stopped_by(registered, observed)
        planned.append(
            PlannedBuild(
                knowledge_base=registered,
                status=observed.status,
                obstacle=None if stopped is None else stopped[0],
                refusal=None if stopped is None else stopped[1],
            )
        )
    return tuple(planned)


async def prepare(
    store_dir: Path, db: aiosqlite.Connection, config: EffectiveConfig, *, name: str
) -> KnowledgeBase:
    """Everything that must hold before a build of `name` is worth starting, raising if it does not.

    The single-corpus form: with one name given there is nothing else in the answer, so a refusal
    is the whole answer and is raised rather than reported.

    Raises:
        InvalidNameError: `name` is empty or blank.
        UnknownKnowledgeBaseError: nothing is registered under `name`.
        DanglingKnowledgeBaseError: the corpus is registered but its database is gone, and with it
            everything that said what to index.
        CorpusRootMissingError: the directory this corpus indexes is gone. The index is kept.
        IndexerBusyError: a build that cannot be shown to be dead already holds this corpus's lock.
        aiosqlite.Error | ZikaronError | OSError: the database is present and will not open. The
            driver's own failure, propagated rather than renamed, since nothing the caller can do
            fixes it.
    """
    (planned,) = await plan(store_dir, db, config, names=[name])
    if planned.refusal is not None:
        raise planned.refusal
    return planned.knowledge_base
