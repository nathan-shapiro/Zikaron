"""The planner's decision: from a module's sources and documents, what to write, remove and move.

`design/code-knowledge.md` §3.4 to §3.6 are normative. **Only a document that declares a link is
ever removed or moved**, and the module's README, whose path is the producer's by construction — so
a file written by hand without a link is reported and never touched.
"""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from zikaron.core.code_knowledge import readme as readme_text
from zikaron.core.code_knowledge.document import Defect, Document, front_matter
from zikaron.core.code_knowledge.layout import Layout, path_order
from zikaron.core.knowledge.links import SourceLink
from zikaron.core.knowledge.source_hash import Hashed, SourceState


class DocumentClass(StrEnum):
    """What one document is, by the first row of §3.4's table that applies."""

    FOREIGN = "foreign"
    ORPHANED = "orphaned"
    UNVERIFIED = "unverified"
    INVALID = "invalid"
    STALE = "stale"
    FRESH = "fresh"


class WorkKind(StrEnum):
    """Why a source's document is to be written."""

    MISSING = "missing"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class Survey:
    """Everything the planner judges.

    `sources` maps each module source to its hash, or to the state that answered where none could
    be had. `documents` maps every document under the module's documents directory but the README
    to its text, or to `None` where it could not be read as UTF-8 text — which is judged foreign,
    since nothing can be known of its link. `readme` is the README's text, `None` where it is
    absent or unreadable, and `readme_present` whether anything is at its path.
    """

    layout: Layout
    sources: Mapping[str, Hashed]
    documents: Mapping[str, str | None]
    readme: str | None = None
    readme_present: bool = False


@dataclass(frozen=True, slots=True)
class Verdict:
    """One document's class, with what was read from it and, for an invalid one, why."""

    document_class: DocumentClass
    document: Document | None = None
    defect: Defect | None = None


@dataclass(frozen=True, slots=True)
class WorkItem:
    """One document to write: at `document`, describing `source`, opening with `front_matter`."""

    kind: WorkKind
    source: str
    document: str
    front_matter: str
    defect: Defect | None = None


@dataclass(frozen=True, slots=True)
class DocumentedFile:
    """A source whose document is fresh, and that document's role line."""

    source: str
    role: str


@dataclass(frozen=True, slots=True)
class ReadmeItem:
    """The README to write, from the role lines in `files` and the documents under `documents`.

    `files` never reaches the planner's output: `--apply` writes it to a file of its own, and the
    item names that file, so the item stays small whatever the module's size."""

    document: str
    front_matter: str
    documents: str
    files: tuple[DocumentedFile, ...]


@dataclass(frozen=True, slots=True)
class Move:
    """An orphan that describes `source`'s bytes exactly, and the document path it moves to."""

    origin: str
    target: str
    source: str


@dataclass(frozen=True, slots=True)
class ForeignFile:
    """A document that declares no link, and the source whose document path it holds, if any."""

    document: str
    source: str | None


@dataclass(frozen=True, slots=True)
class UnverifiableSource:
    """A source with no hash, and the state that answered for it."""

    source: str
    state: SourceState


@dataclass(frozen=True, slots=True)
class Plan:
    """What one run lists, removes and moves. Every sequence is in path order.

    `removals` and `moves` are what `--apply` makes: every orphan that is not moved, every listed
    item's old document, and a listed README that is present.
    """

    work: tuple[WorkItem, ...]
    remaining: int
    readme: ReadmeItem | None
    removals: tuple[str, ...]
    moves: tuple[Move, ...]
    foreign: tuple[ForeignFile, ...]
    unplaceable: tuple[str, ...]
    unverifiable: tuple[UnverifiableSource, ...]

    def up_to_date(self, *, applied: bool) -> bool:
        """Whether every document the module needs is there and current (§3.5).

        Under `--apply` the removals and moves have been made by the time this is read; without
        it, any still to make hold it false.
        """
        settled = applied or not (self.removals or self.moves)
        return (
            settled
            and not self.work
            and not self.remaining
            and not self.unverifiable
            and self.readme is None
        )


def judge(survey: Survey, document: str) -> Verdict:
    """The class of the document at `document`, judged against the source its location derives."""
    text = survey.documents[document]
    parsed = None if text is None else Document.parse(text)
    if parsed is None or parsed.link is None:
        return Verdict(DocumentClass.FOREIGN, parsed)
    source = survey.layout.source_for(document)
    hashed = survey.sources.get(source)
    if hashed is None:
        return Verdict(DocumentClass.ORPHANED, parsed)
    if isinstance(hashed, SourceState):
        return Verdict(DocumentClass.UNVERIFIED, parsed)
    defect = parsed.defect(source)
    if defect is not None:
        return Verdict(DocumentClass.INVALID, parsed, defect)
    stale = isinstance(parsed.link, SourceLink) and parsed.link.blob != hashed
    return Verdict(DocumentClass.STALE if stale else DocumentClass.FRESH, parsed)


def _moves(
    survey: Survey, placeable: frozenset[str], verdicts: Mapping[str, Verdict]
) -> list[Move]:
    """Every orphan whose blob is the hash of exactly one source with nothing at its document
    path, where no other orphan matches that source too."""
    layout = survey.layout
    open_by_hash: dict[str, list[str]] = {}
    for source in placeable:
        hashed = survey.sources[source]
        if isinstance(hashed, SourceState) or layout.document_for(source) in survey.documents:
            continue
        open_by_hash.setdefault(hashed, []).append(source)
    matched: dict[str, str] = {}
    for origin, verdict in verdicts.items():
        parsed = verdict.document
        if verdict.document_class is not DocumentClass.ORPHANED or parsed is None:
            continue
        if isinstance(parsed.link, SourceLink) and parsed.movable:
            targets = open_by_hash.get(parsed.link.blob, [])
            if len(targets) == 1:
                matched[origin] = targets[0]
    claims = Counter(matched.values())
    return sorted(
        (
            Move(origin=origin, target=layout.document_for(source), source=source)
            for origin, source in matched.items()
            if claims[source] == 1
        ),
        key=lambda move: path_order(move.origin),
    )


def _item(survey: Survey, source: str, verdict: Verdict | None) -> WorkItem | None:
    """The work `source` needs, or `None` where its document is fresh or written by hand."""
    hashed = survey.sources[source]
    if isinstance(hashed, SourceState):
        return None
    document = survey.layout.document_for(source)
    if verdict is None:
        kind = WorkKind.MISSING
    elif verdict.document_class is DocumentClass.INVALID:
        kind = WorkKind.INVALID
    elif verdict.document_class is DocumentClass.STALE:
        kind = WorkKind.STALE
    else:
        return None
    defect = verdict.defect if verdict is not None else None
    return WorkItem(kind, source, document, front_matter(source, hashed), defect)


def _readme(
    survey: Survey,
    placeable: frozenset[str],
    verdicts: Mapping[str, Verdict],
    moves: list[Move],
) -> ReadmeItem | None:
    """The README item, or `None` where the README on disk is current. Called only once every
    source has a hash and no file work remains, so the digest is over hashed sources."""
    layout = survey.layout
    hashes = {
        source: hashed
        for source, hashed in survey.sources.items()
        if not isinstance(hashed, SourceState)
    }
    digest = readme_text.module_digest(hashes)
    if survey.readme is not None and readme_text.is_current(survey.readme, digest):
        return None
    moved = {move.source: verdicts[move.origin].document for move in moves}
    files: list[DocumentedFile] = []
    for source in sorted(placeable, key=path_order):
        verdict = verdicts.get(layout.document_for(source))
        parsed = moved.get(source)
        if parsed is None and verdict is not None and verdict.document_class is DocumentClass.FRESH:
            parsed = verdict.document
        if parsed is not None:
            files.append(DocumentedFile(source=source, role=parsed.role))
    return ReadmeItem(
        document=layout.readme,
        front_matter=readme_text.front_matter(digest),
        documents=layout.documents,
        files=tuple(files),
    )


def plan(survey: Survey, *, limit: int | None = None) -> Plan:
    """Judge every document, and list the work in path order, at most `limit` items of it."""
    layout = survey.layout
    placeable = frozenset(
        source for source in survey.sources if layout.document_for(source) != layout.readme
    )
    verdicts = {document: judge(survey, document) for document in survey.documents}
    moves = _moves(survey, placeable, verdicts)
    supplied = {move.source for move in moves}
    items = [
        item
        for source in sorted(placeable - supplied, key=path_order)
        if (item := _item(survey, source, verdicts.get(layout.document_for(source)))) is not None
    ]
    listed = items if limit is None else items[:limit]
    unverifiable = tuple(
        UnverifiableSource(source, hashed)
        for source, hashed in sorted(survey.sources.items(), key=lambda pair: path_order(pair[0]))
        if isinstance(hashed, SourceState)
    )
    moved = {move.origin for move in moves}
    removals = [
        document
        for document, verdict in verdicts.items()
        if verdict.document_class is DocumentClass.ORPHANED and document not in moved
    ]
    removals.extend(item.document for item in listed if item.kind is not WorkKind.MISSING)
    readme = None
    if not items and not unverifiable:
        readme = _readme(survey, placeable, verdicts, moves)
        if readme is not None and survey.readme_present:
            removals.append(layout.readme)
    foreign = tuple(
        ForeignFile(
            document=document,
            source=source if (source := layout.source_for(document)) in placeable else None,
        )
        for document in sorted(verdicts, key=path_order)
        if verdicts[document].document_class is DocumentClass.FOREIGN
    )
    return Plan(
        work=tuple(listed),
        remaining=len(items) - len(listed),
        readme=readme,
        removals=tuple(sorted(removals, key=path_order)),
        moves=tuple(moves),
        foreign=foreign,
        unplaceable=tuple(sorted(set(survey.sources) - placeable, key=path_order)),
        unverifiable=unverifiable,
    )
