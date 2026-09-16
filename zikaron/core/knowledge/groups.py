"""Searching every named knowledge base, and assembling one answer out of the results.

Three rules shape this, and each is a decision the design argues rather than a convenience:

- **Each corpus is queried on its own connection and merged here.** SQLite's attach limit is ten in
  any stock build, so a single-query path could not be relied on past nine corpora — and keeping
  both a joined path and a per-corpus one would be two implementations of one answer.
- **Group order is by best cosine, and nothing else crosses a corpus boundary.** BM25 scores are
  incomparable between corpora: measured on two 200-document corpora containing the same sentence,
  the one where a hundred documents matched scored its best hit at zero while the one with a single
  match scored -4.2. Pooling those would systematically bury the most on-topic documents in
  whichever corpus is most about the query. Cosine is a function of two vectors and has no such
  property, so it is used for the one cross-corpus decision the service makes and for nothing else.
- **Every named corpus appears in the answer.** Populated, empty, errored, unknown or with its
  results dropped to fit — but never silently absent, because "this corpus was searched and had
  nothing" is a real answer and indistinguishable from a corpus that was skipped.
"""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

import aiosqlite

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.errors import ZikaronError
from zikaron.core.indexing.encoder import Encoder
from zikaron.core.knowledge import arms, database, paths, registry, reporting, search
from zikaron.core.knowledge import state as corpus_state
from zikaron.core.knowledge.database import KnowledgeDatabase
from zikaron.core.knowledge.errors import InvalidNameError
from zikaron.core.knowledge.registry import KnowledgeBase
from zikaron.core.knowledge.state import KnowledgeState
from zikaron.core.retrieval.query import PreparedQuery

#: The most results one corpus may return, whatever a caller asks for. A caller above it is
#: clamped rather than refused: it wants as many as it can have, and answering nothing over a
#: number it does not care about would be the worse reading of the request.
LIMIT_PER_KB_CAP: Final = 20

#: The whole response's ceiling, under the delivery threshold measured for a tool result — and in
#: the same unit that threshold was measured in, which `response_bytes` explains and is the one
#: thing about this number that is easy to get wrong. Enforced by dropping whole groups' results,
#: never by cutting one short: a half-dropped group would misrepresent the one thing an empty group
#: is for, which is saying that a corpus was searched.
RESPONSE_MAX_BYTES: Final = 24_000

#: What a group reports when the name it was asked for is not registered. A per-group error rather
#: than a failed call, so naming one bad corpus among three still answers for the other two.
UNKNOWN_KNOWLEDGE_BASE: Final = "unknown_knowledge_base"

#: The ordering key for a group with nothing to order by. Every such group sorts after every group
#: that has a result, and among themselves by name, so one store and one query always produce the
#: same list.
_NO_KEY: Final = float("-inf")

#: The states whose corpus can be searched at all. Every other state answers as an empty group
#: rather than with results it cannot stand behind: `reindex_required`, on any of its causes, means
#: the vectors in the table are not the ones this corpus's recorded identity describes, are not a
#: completed build's, or are not there at all; `root_missing` means a result would point at a file
#: nobody can read; and `error` means the index itself could not be opened.
_SERVING: Final = frozenset({KnowledgeState.OK, KnowledgeState.INDEXING})


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """One search, exactly as its caller stated it.

    One type rather than a parameter list, because the caller is a tool boundary: the value that
    arrives has already been read out of a payload, and a parameter list would let a second caller
    accept a different set of things.

    `names` is free-form and is validated where the registry is read, not here. `None` means every
    registered corpus, which is what an agent that has not called `list` yet is asking for.

    `limit_per_kb` carries no default, deliberately: the default belongs to the surface a caller
    actually sees, and a second one here would be free to disagree with it.
    """

    text: str
    limit_per_kb: int
    names: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class KnownBase:
    """One corpus a caller could have meant, for a group that names one nobody registered."""

    name: str
    description: str

    def payload(self) -> dict[str, object]:
        return {"name": self.name, "description": self.description}


@dataclass(frozen=True, slots=True)
class Group:
    """One corpus's contribution to an answer.

    `state` and `files_remaining` are the same fields `status` reports, and carrying them here is
    what makes an empty group honest: *searched and found nothing*, *not built yet*, and *partial
    while a build finishes* are three different answers, and reporting only emptiness would collapse
    them into the one a reader is most likely to misread as evidence of absence.
    """

    knowledge_base: str
    description: str
    state: KnowledgeState
    files_remaining: int | None
    results: tuple[search.Result, ...]
    dropped: bool = False

    @property
    def order_key(self) -> float:
        """The best cosine in this group, or the key that sorts it after every populated one."""
        return max((result.score for result in self.results), default=_NO_KEY)

    def payload(self) -> dict[str, object]:
        """This group as the object a caller receives."""
        payload: dict[str, object] = {
            "knowledge_base": self.knowledge_base,
            "description": self.description,
            "state": self.state.value,
            "files_remaining": self.files_remaining,
            "results": [_result_payload(result) for result in self.results],
        }
        if self.dropped:
            payload["dropped"] = True
        return payload


@dataclass(frozen=True, slots=True)
class UnknownGroup:
    """A name in the request that no corpus is registered under.

    It has no state to report, since it names no corpus. **What it deliberately does not carry is
    the list of corpora that do exist**: that list is one property of the store rather than of this
    name, so it rides on the response once — see `SearchResponse.known_knowledge_bases`. Carrying it
    here instead multiplied the whole registry by the number of names a caller got wrong, which is
    bytes nothing could reduce, against a cap whose overflow is a silent truncation at the harness.
    """

    knowledge_base: str

    @property
    def order_key(self) -> float:
        return _NO_KEY

    def payload(self) -> dict[str, object]:
        return {"knowledge_base": self.knowledge_base, "error": UNKNOWN_KNOWLEDGE_BASE}


type AnyGroup = Group | UnknownGroup


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """Every named corpus's answer, in group order, and whether anything had to be left out.

    `known_knowledge_bases` is what a caller who named a corpus that does not exist actually needs:
    not "no", but "not that one — these". It is populated only when some name went unmatched, and it
    is carried once for the whole response rather than once per bad name, because it describes the
    store rather than any one of them.
    """

    groups: tuple[AnyGroup, ...]
    groups_dropped: bool
    known_knowledge_bases: tuple[KnownBase, ...] = ()

    def payload(self) -> dict[str, object]:
        return {
            "groups": [group.payload() for group in self.groups],
            "groups_dropped": self.groups_dropped,
            "known_knowledge_bases": [one.payload() for one in self.known_knowledge_bases],
        }


def _result_payload(result: search.Result) -> dict[str, object]:
    return {
        "path": result.path,
        "start_line": result.start_line,
        "end_line": result.end_line,
        "snippet": result.snippet,
        "truncated": result.truncated,
        "score": result.score,
        "stale": result.stale,
    }


def clamp_limit(limit: int) -> int:
    """`limit_per_kb` as it will actually be applied: at least one, at most the cap."""
    return max(1, min(limit, LIMIT_PER_KB_CAP))


def response_bytes(response: SearchResponse) -> int:
    """This response's payload size, in the unit the delivery threshold was measured in.

    Compact and without ASCII escaping, which is the shape the transport serializes in — measuring
    the indented form would test a document nobody receives. Slightly high rather than exact:
    `json.dumps` here keeps its default separators where the transport's own serializer drops them,
    and high is the direction a cap may err in.

    **Counted once, and the reason is a denomination rather than an oversight.** The transport
    delivers a tool result *twice* — a JSON text block and again as structured content — which
    invites the conclusion that a cap must charge for both. It must not, because the threshold this
    cap sits under was itself measured through that same duplicating transport and recorded in
    single-counted payload size: the probe that established it returned a plain string, and a
    string-returning tool is wrapped as structured content exactly as an object-returning one is.
    Charging twice here while the threshold stays denominated once would halve the deliverable
    answer for no gain. Both numbers are in the same unit; the duplication is already inside the
    measured figure.
    """
    return len(json.dumps(response.payload(), ensure_ascii=False).encode("utf-8"))


def _fit_to_cap(
    groups: Sequence[AnyGroup], *, known: Sequence[KnownBase], max_bytes: int
) -> SearchResponse:
    """Shed what the answer can spare, in order, until the response fits.

    **Results go first**, lowest-ranked group first and whole rather than partially — a group that
    returned three of its five best fragments looks exactly like a corpus that had three, and the
    stub that replaces them keeps the corpus, its state and its progress in the answer.

    **The list of corpora that exist goes last, and the reason is which loss is announced.** Dropped
    results say so, in `groups_dropped`, so a caller knows to ask for fewer and can. Nothing reports
    a withheld listing: it is already empty whenever every name resolved, so its emptiness carries
    no information. Shedding the announced loss before the silent one is what keeps the unannounced
    one to the case where the response is degenerate anyway — every group already a stub.

    **The floor is presence**: once results and that list are gone, what remains is one short stub
    per corpus the caller named, and no further byte can be shed without removing a corpus from the
    answer. A response of nothing but stubs is therefore returned as it is, over the cap, and that
    is the deliberate choice — a caller told nothing about a corpus it asked about cannot tell that
    from a corpus that had nothing.
    """
    fitted = list(groups)
    carried = tuple(known)
    response = SearchResponse(
        groups=tuple(fitted), groups_dropped=False, known_knowledge_bases=carried
    )
    if response_bytes(response) <= max_bytes:
        return response
    dropped = False
    for index in range(len(fitted) - 1, -1, -1):
        group = fitted[index]
        if not isinstance(group, Group) or not group.results:
            continue
        fitted[index] = replace(group, results=(), dropped=True)
        dropped = True
        response = SearchResponse(
            groups=tuple(fitted), groups_dropped=True, known_knowledge_bases=carried
        )
        if response_bytes(response) <= max_bytes:
            return response
    # Every group is a stub and it still does not fit, so the listing goes too — stated here rather
    # than left to an omitted argument, because it is the last lever and a reader should see it.
    return SearchResponse(groups=tuple(fitted), groups_dropped=dropped, known_knowledge_bases=())


def _ordered(groups: Sequence[AnyGroup]) -> tuple[AnyGroup, ...]:
    """Groups by best cosine, then by name.

    **The order is approximate and is labelled as such where an agent reads it**: it is the best
    cross-corpus signal available, and it is not a claim that the first group holds the best answer.
    The name breaks ties so that two runs over one store agree.
    """
    return tuple(sorted(groups, key=lambda group: (-group.order_key, group.knowledge_base)))


async def _open_group(
    store_dir: Path,
    registered: KnowledgeBase,
    config: EffectiveConfig,
    *,
    query: PreparedQuery,
    settings: search.SearchSettings,
) -> Group:
    """One corpus's group: its state, its progress, and its results if it can serve any.

    Every failure to read a corpus is that corpus's own answer rather than the call's: a database
    that will not open reports `error` while its neighbours answer normally. The two are kept apart
    deliberately — an absent database is a corpus whose definition went with it, repaired by
    removing the name and adding it again, and a corrupt one is not obviously repaired at all.
    Neither is searchable; a caller reading only emptiness could not tell them apart.
    """
    db_path = paths.knowledge_db_path(store_dir, registered.id)
    if not db_path.is_file():
        return _barren(registered, KnowledgeState.REINDEX_REQUIRED)
    try:
        opened = await KnowledgeDatabase.open(store_dir, registered.id)
    except (aiosqlite.Error, ZikaronError, OSError):
        return _barren(registered, KnowledgeState.ERROR)
    try:
        async with opened:
            return await _serve(opened, registered, config, query=query, settings=settings)
    except (aiosqlite.Error, OSError):
        # The corpus opened and then could not be read — a file truncated under us, a vector table
        # that will not answer. Reported as this corpus's own state rather than as a failed call,
        # which is what keeps one bad database from taking every other corpus's answer with it.
        return _barren(registered, KnowledgeState.ERROR)


async def _serve(
    opened: KnowledgeDatabase,
    registered: KnowledgeBase,
    config: EffectiveConfig,
    *,
    query: PreparedQuery,
    settings: search.SearchSettings,
) -> Group:
    """Read one open corpus's state and search it if that state allows."""
    raw = await database.read_meta(opened.connection)
    state = corpus_state.resolve(corpus_state.inputs_for_open(opened, raw, config))
    remaining = await reporting.files_remaining(opened.connection, raw)
    results: tuple[search.Result, ...] = ()
    if state in _SERVING:
        results = await search.search_one(
            opened.connection, query=query, corpus=opened.meta, settings=settings
        )
    return Group(
        knowledge_base=registered.name,
        description=registered.description,
        state=state,
        files_remaining=remaining,
        results=results,
    )


def _barren(registered: KnowledgeBase, state: KnowledgeState) -> Group:
    """A group for a corpus that cannot be searched, carrying why rather than only emptiness."""
    return Group(
        knowledge_base=registered.name,
        description=registered.description,
        state=state,
        files_remaining=None,
        results=(),
    )


def _requested(
    registered: Sequence[KnowledgeBase], names: Sequence[str] | None
) -> tuple[tuple[KnowledgeBase, ...], tuple[str, ...]]:
    """Which corpora to search, and which requested names match none of them.

    A supplied name is lower-cased and then matched by plain string equality, which is the same
    normalisation the registry stores. Nothing else is normalised — no trimming, no whitespace
    collapsing — so a name differing by a space is a different name while one differing only by case
    is the same one. A name that could never be registered at all, being blank, is reported as
    unknown like any other miss rather than failing the call.

    **A corpus named twice is searched once and reported once**, and so is an unknown name. Both
    halves are deduplicated after normalisation, so `["DOCS", "docs"]` is one corpus rather than two
    identical groups — which would otherwise cost a second search, a second copy of the results, and
    twice the bytes against a response cap, for an answer the caller already has. Every name the
    caller supplied is still represented, which is what the request's own guarantee asks for.

    A name that has no normalized form at all — blank, so nothing could ever be registered under
    it — is carried as the caller wrote it, since there is nothing else to carry.
    """
    if names is None:
        return tuple(registered), ()
    by_name = {base.name: base for base in registered}
    found: dict[str, KnowledgeBase] = {}
    unknown: dict[str, None] = {}
    for name in names:
        try:
            normalized = registry.normalize_name(name)
        except InvalidNameError:
            unknown.setdefault(name, None)
            continue
        base = by_name.get(normalized)
        if base is None:
            # The normalized spelling, so that two namings of one absent corpus are one group —
            # `DCOS` and `dcos` could only ever have meant the same thing. It is also the spelling
            # a *found* group reports, since that is the registry's own.
            unknown.setdefault(normalized, None)
        else:
            found.setdefault(base.name, base)
    return tuple(found.values()), tuple(unknown)


async def search_all(
    store_dir: Path,
    db: aiosqlite.Connection,
    config: EffectiveConfig,
    request: SearchRequest,
    *,
    encoder: Encoder,
) -> SearchResponse:
    """Search every named corpus and assemble one answer.

    Args:
        store_dir: the `.zikaron` directory this store lives in.
        db: an open connection to `memory.db`, which carries the registry.
        config: the effective configuration, for the query prefix and the two output bounds.
        request: the query, which corpora to search, and how many results each may return.
        encoder: the artifact that embeds the query. Blocking, so it is used off the event loop.

    Returns:
        A response with one group per named corpus, ordered by best cosine, within the byte cap.
    """
    await registry.ensure(db)
    registered = await registry.list_all(db)
    wanted, unknown = _requested(registered, request.names)
    groups: list[AnyGroup] = [UnknownGroup(knowledge_base=name) for name in unknown]
    # Carried only when some name went unmatched: a caller whose names all resolved is being told
    # what it already knows, in bytes that count against the same cap as the answer.
    known = (
        tuple(KnownBase(name=base.name, description=base.description) for base in registered)
        if unknown
        else ()
    )
    if wanted:
        settings = search.SearchSettings(
            limit_per_kb=clamp_limit(request.limit_per_kb),
            max_chunks_per_file=config.get_int("knowledge_max_chunks_per_file"),
            snippet_max_chars=config.get_int("knowledge_snippet_max_chars"),
        )
        # Built once for every corpus, and off the event loop: it runs the model. A request naming
        # only corpora that do not exist never reaches here, so a typo costs no inference.
        query = await asyncio.to_thread(
            arms.unit_query,
            request.text,
            encoder=encoder,
            prefix=config.get_str("embed_prefix_query"),
            max_terms=config.get_int("fts_query_max_terms"),
        )
        for base in wanted:
            groups.append(
                await _open_group(store_dir, base, config, query=query.prepared, settings=settings)
            )
    return _fit_to_cap(_ordered(groups), known=known, max_bytes=RESPONSE_MAX_BYTES)
