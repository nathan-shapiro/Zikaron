"""Method dispatch for the knowledge index: search, and the six management verbs.

In its own module rather than in `dispatch.py` because it is a different subsystem rather than
more primary-agent verbs: it reads the knowledge-base registry and each corpus's own database, and
touches none of the memory store's tables beyond that registry.

**Search's result forwards `core`'s own payload instead of restating its shape.** Every other wire
shape in this service is a dataclass whose `as_json` builds the object field by field, which is
what keeps a renamed field a type error rather than a `KeyError`. Search cannot be: its byte cap is
enforced by measuring the encoded answer, so the object that is measured and the object that is
sent have to be the same one — and building it twice is exactly how the measurement comes to
describe something other than what was delivered. Nothing else here is under a cap, so the six
management verbs do build their shapes field by field, in `serialize_knowledge.py`.

**A knowledge-base refusal is translated to a wire code here, on the exception's type.** `core`
raises one class per refusal and gives none of them a numeric code, deliberately: those classes
describe a corpus rather than anything a client asked the memory service to do. This module is the
boundary where they become something a client can branch on, and it branches on the **type** so
that a message may be reworded without silently changing which code a caller sees. Left
untranslated they would reach `server.py`'s `except Exception:` fallback and arrive as *internal
error* — indistinguishable, to a model, from a bug in the service.

**A build is spawned, never run here.** The service is the process a user is waiting on; a build is
minutes of saturated CPU over a whole directory tree. `add` and `refresh` start a detached indexer
through the same function the command-line surface uses, so the two cannot come to disagree about
what a build is invoked as.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import builds, groups, lifecycle, registry, reporting, state
from zikaron.core.knowledge.errors import (
    DuplicateNameError,
    IndexerBusyError,
    InvalidNameError,
    InvalidRootError,
    InvalidSettingError,
    KnowledgeError,
    UnknownKnowledgeBaseError,
)
from zikaron.core.knowledge.meta import GitMode
from zikaron.knowledge.indexer import detach
from zikaron.service import paths
from zikaron.service.context import ServiceContext
from zikaron.service.envelope import ResolvedEnvelope
from zikaron.service.params import (
    Handler,
    optional_int,
    optional_str,
    optional_str_list,
    require_bool,
    require_int,
    require_str,
)
from zikaron.service.serialize import RpcResult
from zikaron.service.serialize_knowledge import (
    KnowledgeBuildResult,
    KnowledgeListResult,
    KnowledgeRemoveResult,
    KnowledgeRenameResult,
    KnowledgeStatusResult,
)

#: What `limit_per_kb` means when a caller does not say. Stated here as well as in the tool's own
#: signature because a direct RPC caller never passes through that signature.
DEFAULT_LIMIT_PER_KB = 5


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult(RpcResult):
    """`zikaron_knowledge_search`'s success shape: `{groups, groups_dropped,
    known_knowledge_bases}` — the last empty unless a name matched no corpus."""

    response: groups.SearchResponse

    def as_json(self) -> dict[str, object]:
        return self.response.payload()


def _reported_name(name: str) -> str:
    """A name as the registry would store it, for an error payload to name the corpus by.

    Normalized, because that is the spelling `list` reports and the one a caller has to supply to
    reach the same corpus again. A name with no normalized form at all is carried as it was
    written, since there is nothing else to carry — and that is exactly the case `bounds` is about,
    so the value is never the one a caller acts on.
    """
    try:
        return registry.normalize_name(name)
    except InvalidNameError:
        return name


def _as_bounds(error: KnowledgeError, *, supplied: Mapping[str, str]) -> ZikaronError | None:
    """The refusals that reject a **parameter value** rather than describing a corpus.

    A blank name, a root that is absent or is not a directory or is degenerate, and a size cap
    outside the range configuration declares. All three reuse `bounds`, whose `{field, limit,
    actual}` payload is exactly what a caller needs in order to call again, and the remedy for all
    three is a different value for the field named — which is why none earns a code of its own.

    `supplied` is the names this call was given, under the parameter names the caller used. A
    refused name is matched against it so the payload names the parameter to resend rather than
    always saying `name`: a rename takes two names and a status takes one called `knowledge_base`,
    and a caller told that `name` was blank when it sent a blank `new_name` would resend the
    value that was already accepted and get the identical refusal. Two values that are identical
    name the first, which is also the first validated, so the answer is the same either way.

    **A refused name that this call never sent is left untranslated**, which is the same rule this
    module applies to any refusal it has no code for. It cannot happen through the verbs — each
    one refuses only names it was handed — so reaching it means `core` refused something this
    layer does not know it asked for, and naming one of the parameters anyway would answer a
    defect with a refusal a caller would act on.
    """
    if isinstance(error, InvalidNameError):
        field = next((key for key, value in supplied.items() if value == error.value), None)
        if field is None:
            return None
        return ZikaronError(
            ErrorCode.BOUNDS,
            field=field,
            limit="a name with something in it",
            actual=error.value,
        )
    if isinstance(error, InvalidRootError):
        return ZikaronError(
            ErrorCode.BOUNDS,
            field="path",
            limit="an existing directory that is neither a filesystem root nor a home directory",
            actual=str(error.path),
        )
    if isinstance(error, InvalidSettingError):
        return ZikaronError(
            ErrorCode.BOUNDS,
            field=error.bounds.key,
            limit=error.bounds.expected,
            actual=error.bounds.value,
        )
    return None


def _translated(
    error: KnowledgeError, *, name: str, taken: str, supplied: Mapping[str, str]
) -> ZikaronError | None:
    """The wire error one knowledge-base refusal becomes, or `None` for one that has no code.

    Split on the line the design's own mapping table draws: `_as_bounds` holds the rejections of a
    supplied *value*, and this holds the three that are statements about a *corpus* — it does not
    exist, one by that name already does, or a build is holding it.

    **Every payload value comes from the exception's own field rather than from its message.** A
    `holder`, a `path` and a size cap are values a client reads, and filling one from `str(error)`
    would put a whole sentence there — after which the message could no longer be reworded, since
    it would have become the contract this translation exists to keep stable.

    **An unmapped class — or a mapped one refusing a value this call never sent — returns `None`
    and is propagated unchanged rather than given a nearby code.** The classes these verbs can
    actually raise are the six across both functions; anything else reaching here is a defect in
    this translation or in `core`, and so is a refusal about a name the caller did not supply.
    Answering either with a plausible-looking refusal would hide a defect behind an error a caller
    would act on.
    """
    bounded = _as_bounds(error, supplied=supplied)
    if bounded is not None:
        return bounded
    if isinstance(error, DuplicateNameError):
        return ZikaronError(ErrorCode.KNOWLEDGE_BASE_EXISTS, name=_reported_name(taken))
    if isinstance(error, UnknownKnowledgeBaseError):
        return ZikaronError(ErrorCode.KNOWLEDGE_BASE_UNKNOWN, name=_reported_name(name))
    if isinstance(error, IndexerBusyError):
        return ZikaronError(
            ErrorCode.KNOWLEDGE_BASE_BUSY,
            name=_reported_name(name),
            holder=error.holder.describe(),
        )
    return None


@contextmanager
def _refusals_as_wire_errors(
    *, supplied: Mapping[str, str], taken: str | None = None
) -> Iterator[None]:
    """Translate whatever `core` refuses inside this block into the wire error for it.

    A context manager rather than a wrapper per call site, because every one of these verbs needs
    the identical three lines and a hand-written copy of them is how one verb comes to answer a
    taken name differently from another.

    `supplied` is every name this call was given, keyed by the parameter the caller sent it under
    and in the order they are validated. The first is the corpus the call is about, which is what
    a refusal about a corpus names; the whole mapping is what lets a refusal about a *value* name
    the parameter to resend.

    `taken` is the name a duplicate would be about, which is the *new* one for a rename and the
    only one everywhere else — so the payload names the corpus that already exists rather than the
    one the caller was working from.
    """
    subject = next(iter(supplied.values()), "")
    try:
        yield
    except KnowledgeError as error:
        translated = _translated(
            error,
            name=subject,
            taken=subject if taken is None else taken,
            supplied=supplied,
        )
        if translated is None:
            raise
        raise translated from error


async def knowledge_search(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],
) -> KnowledgeSearchResult:
    """`knowledge_search(query, knowledge_bases?, limit_per_kb?)
    -> {groups, groups_dropped, known_knowledge_bases}`."""
    request = groups.SearchRequest(
        text=require_str(params, "query"),
        limit_per_kb=require_int(params, "limit_per_kb", default=DEFAULT_LIMIT_PER_KB),
        names=optional_str_list(params, "knowledge_bases"),
    )
    response = await groups.search_all(
        ctx.store_directory, db, ctx.config, request, encoder=ctx.encoder
    )
    return KnowledgeSearchResult(response=response)


async def knowledge_list(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],  # noqa: ARG001 — this method takes none; the table's shape passes one.
) -> KnowledgeListResult:
    """`knowledge_list() -> {knowledge_bases}` — every corpus, projected down to the choosing
    fields."""
    listing = await reporting.list_bases(ctx.store_directory, db, ctx.config)
    return KnowledgeListResult(reports=listing.knowledge_bases)


async def knowledge_status(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],
) -> KnowledgeStatusResult:
    """`knowledge_status(knowledge_base?) -> {knowledge_bases, orphans}`."""
    name = optional_str(params, "knowledge_base")
    with _refusals_as_wire_errors(supplied={"knowledge_base": name or ""}):
        listing = await reporting.status(ctx.store_directory, db, ctx.config, name=name)
    return KnowledgeStatusResult(reports=listing.knowledge_bases, orphans=listing.orphans)


def _git_mode(params: dict[str, object]) -> GitMode:
    """`git_mode` as the closed value it is, rejecting anything outside the three it may be."""
    supplied = optional_str(params, "git_mode")
    if supplied is None:
        return GitMode.TRACKED
    try:
        return GitMode(supplied)
    except ValueError as error:
        raise ZikaronError(
            ErrorCode.BOUNDS,
            field="git_mode",
            limit=" | ".join(mode.value for mode in GitMode),
            actual=supplied,
        ) from error


def _globs(params: dict[str, object], name: str) -> tuple[str, ...]:
    """One glob list, where absent and empty mean the same thing: no patterns of that kind."""
    return optional_str_list(params, name) or ()


def _corpus_root(ctx: ServiceContext, supplied: str) -> Path:
    """A supplied corpus root as an absolute path, resolving a relative one against the project.

    **The service's own working directory is not a place to resolve anything against.** It is
    inherited from whichever client happened to spawn the service — possibly a different session,
    possibly days earlier — and nothing an agent can see says what it is. A relative `path` left to
    resolve there would create a corpus over some unrelated directory, report `ok`, and answer
    searches from it: wrong, permanent, and silent, because the stored root is absolute and looks
    deliberate.

    The project root is the one directory the harness, the store and the agent already agree on,
    so that is what a relative path means here. An absolute one is left exactly as given, since
    indexing a tree outside the project is a legitimate use (`knowledge-index.md` §8.6).

    **A leading `~` is passed through untouched**, to be expanded further down where every other
    path this system accepts is expanded. It names the home directory rather than anything under
    the project, so joining it first would produce `<project>/~/notes` — a path that then expands
    to nothing, since expansion only applies to a `~` at the front.
    """
    root = Path(supplied)
    if root.is_absolute() or supplied.startswith("~"):
        return root
    return paths.scope_of(ctx.store_directory) / root


def _spawn(ctx: ServiceContext, planned: Sequence[builds.PlannedBuild], *, full: bool) -> None:
    """Start a detached indexer for every corpus nothing stops, and return without waiting."""
    project = paths.scope_of(ctx.store_directory)
    for entry in planned:
        if entry.may_start:
            detach.spawn(entry.knowledge_base.name, project=project, full=full)


async def knowledge_add(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],
) -> KnowledgeBuildResult:
    """`knowledge_add(name, path, description, include?, exclude?, git_mode?, max_file_bytes?)
    -> {knowledge_bases, requested_git_mode, effective_git_mode}`.

    Returns as soon as the corpus exists, with a build already running against it: a fresh corpus
    reports `reindex_required` until that build's completing transaction says otherwise, which is
    the truth rather than a placeholder.
    """
    request = lifecycle.AddRequest(
        name=require_str(params, "name"),
        root=_corpus_root(ctx, require_str(params, "path")),
        description=require_str(params, "description"),
        include_globs=_globs(params, "include"),
        exclude_globs=_globs(params, "exclude"),
        git_mode=_git_mode(params),
        max_file_bytes=optional_int(params, "max_file_bytes"),
    )
    with _refusals_as_wire_errors(supplied={"name": request.name}):
        created = await lifecycle.add(ctx.store_directory, db, ctx.config, request)
    planned = await builds.plan(
        ctx.store_directory, db, ctx.config, names=[created.knowledge_base.name]
    )
    _spawn(ctx, planned, full=False)
    return KnowledgeBuildResult(
        planned=planned,
        git_modes=(created.git_mode.value, created.git_mode_effective.value),
    )


async def knowledge_refresh(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],
) -> KnowledgeBuildResult:
    """`knowledge_refresh(name?, full?) -> {knowledge_bases}` — one `outcome` per corpus.

    An unknown name fails the call, because with one name given there is nothing else to answer
    for. Everything else a corpus can be stopped by is reported against that corpus, so one
    unbuildable knowledge base never denies the others a build they could have had.
    """
    name = optional_str(params, "name")
    # Both parameters are read before the store is touched, because a `bounds` refusal is decided
    # without consulting any stored state and must not depend on one. Read after the sweep, a
    # malformed `full` would be masked by an unknown name — so a caller correcting the name would
    # then meet a second refusal it could have been told about at once — and over a large store it
    # would be reported only after every corpus had been opened and observed for nothing.
    full = require_bool(params, "full", default=False)
    with _refusals_as_wire_errors(supplied={"name": name or ""}):
        planned = await builds.plan(
            ctx.store_directory, db, ctx.config, names=None if name is None else [name]
        )
    _spawn(ctx, planned, full=full)
    return KnowledgeBuildResult(planned=planned)


async def knowledge_rename(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],
) -> KnowledgeRenameResult:
    """`knowledge_rename(name, new_name) -> {knowledge_bases}` — a registry update, touching no
    file."""
    name = require_str(params, "name")
    new_name = require_str(params, "new_name")
    with _refusals_as_wire_errors(supplied={"name": name, "new_name": new_name}, taken=new_name):
        status = await lifecycle.rename(
            ctx.store_directory, db, ctx.config, name=name, new_name=new_name
        )
    return KnowledgeRenameResult(status=status)


async def knowledge_remove(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,  # noqa: ARG001 — every handler takes one; this method records no event.
    params: dict[str, object],
) -> KnowledgeRemoveResult:
    """`knowledge_remove(name, confirm) -> {removed, knowledge_bases, files_unlinked}`.

    Without `confirm` the call fails and its payload names what would be destroyed, which is the
    only preview an irreversible unlink has.
    """
    name = require_str(params, "name")
    if not require_bool(params, "confirm", default=False):
        raise await _what_would_be_destroyed(db, ctx, name)
    with _refusals_as_wire_errors(supplied={"name": name}):
        removed = await lifecycle.remove(ctx.store_directory, db, ctx.config, name=name)
    return KnowledgeRemoveResult(
        status=removed.status,
        files_unlinked=tuple(str(path) for path in removed.files_unlinked),
    )


async def _what_would_be_destroyed(
    db: aiosqlite.Connection, ctx: ServiceContext, name: str
) -> ZikaronError:
    """The refusal an unconfirmed `remove` is given, carrying the size of what it would destroy.

    Reported by reading the corpus rather than by naming the risk in prose, because *how much*
    is the whole of what a caller has to weigh — and an unknown name is answered as unknown here
    rather than as needing confirmation, so a typo is never met with a prompt to confirm it.

    **`chunks` is `null` where the corpus cannot be read, and never `0`.** A database that is
    present and will not open is exactly the case this preview must not guess at: the file may hold
    a fully built corpus and be refused for a permission or a schema reason, and `0` is then a
    confident number no stored value backs, on the one verb nothing undoes. `state` rides along for
    the same reason — it is what tells a caller that `files_indexed: 0` is a statement about
    availability rather than about content, which is the reading `list` and `status` already give
    a corpus in this condition.
    """
    with _refusals_as_wire_errors(supplied={"name": name}):
        listing = await reporting.status(ctx.store_directory, db, ctx.config, name=name)
    (found,) = listing.knowledge_bases
    return ZikaronError(
        ErrorCode.KNOWLEDGE_CONFIRM_REQUIRED,
        name=found.summary.name,
        state=found.summary.state.value,
        files_indexed=found.summary.files_indexed,
        chunks=_destroyable_chunks(found),
    )


def _destroyable_chunks(found: reporting.Status) -> int | None:
    """How many chunks a removal would destroy, or `None` where that cannot be established.

    The two states with no diagnostic half are not the same answer. An **absent** database holds
    nothing, and `0` is true of it. A **present** one that will not open holds an unknown amount,
    and the honest report is that nothing could be counted.
    """
    if found.details is not None:
        return found.details.chunks
    return None if found.summary.state is state.KnowledgeState.ERROR else 0


#: The knowledge methods this module handles, by wire name. `server.py` merges this table with the
#: primary and consolidator ones. Every one of them is a primary-agent method: a consolidator has
#: no use for a corpus of files, and D32's split is what keeps them out of that mode entirely.
KNOWLEDGE_METHODS: dict[str, Handler] = {
    "knowledge_search": knowledge_search,
    "knowledge_list": knowledge_list,
    "knowledge_status": knowledge_status,
    "knowledge_add": knowledge_add,
    "knowledge_remove": knowledge_remove,
    "knowledge_rename": knowledge_rename,
    "knowledge_refresh": knowledge_refresh,
}
