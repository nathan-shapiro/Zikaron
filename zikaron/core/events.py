"""The event log's vocabulary: every kind, whether it names a memory, and its `detail` shape.

The event log is instrumentation, and untyped `detail` is what made an earlier generation of it
unusable: a signal computed over free-form JSON cannot be wrong in a detectable way. So each
kind declares the exact field names its `detail` carries, and — where the value is one of a
closed set rather than a number or an id — the exact set. A writer that invents or drops either
is a defect rather than a variation.

This vocabulary sits beside the error contract rather than inside any one layer because every
layer emits into the same log — records, indexing, retrieval and consolidation all write kinds
defined here, and putting the enum in whichever layer happened to need it first would make the
other three import across the domain to reach it. The layers consume these definitions; none of
them restates a value.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar, Final


class EventKind(StrEnum):
    """Every kind of row the event log holds."""

    SURFACE_CALL = "surface_call"
    SURFACE = "surface"
    SEARCH = "search"
    FETCH = "fetch"
    REMEMBER = "remember"
    AMEND = "amend"
    RETIRE = "retire"
    MERGE = "merge"
    PROMOTE = "promote"
    DISCARD = "discard"
    DEDUP_OFFERED = "dedup_offered"
    VERSION_CONFLICT = "version_conflict"
    NO_RECEIPT = "no_receipt"
    GROUP_SERVED = "group_served"
    CONSOLIDATE_RUN = "consolidate_run"


class Demotion(StrEnum):
    """Why a surfaced memory was ranked behind what it would otherwise have outranked."""

    SUPERSEDED = "superseded"
    RETIRED = "retired"


class MergeRole(StrEnum):
    """What one row was to a merge: the record that survived, or one folded into it."""

    TARGET = "target"
    ABSORBED = "absorbed"


class PromoteRole(StrEnum):
    """What one row was to a promotion.

    `FLIPPED` and `CREATED` are alternatives, not stages: a promotion either authors a new
    long-term record or lifts the single member it had in place, and the one physical row of an
    in-place promotion is both the thing promoted and the thing absorbed. Naming that case
    separately is what keeps one mutated row to one event.
    """

    CREATED = "created"
    FLIPPED = "flipped"
    ABSORBED = "absorbed"


class PromoteForm(StrEnum):
    """Whether a promotion authored a new record or lifted an existing one where it stood."""

    IN_PLACE = "in_place"
    NEW_ROW = "new_row"


class ServeRole(StrEnum):
    """What one delivered row was to a consolidation group's serve."""

    MEMBER = "member"
    CANDIDATE = "candidate"
    ANCHOR = "anchor"


class RunPhase(StrEnum):
    """The transition a consolidation run's event is recording."""

    PLANNED = "planned"
    COMPLETE = "complete"
    EXPIRED = "expired"
    ABANDONED = "abandoned"


class StopReason(StrEnum):
    """Why a retrieval arm stopped, which the depth it reached cannot say on its own.

    `DEPTH_REACHED` means a surplus was found beyond what the arm keeps, so the bound provably
    cut something. `INDEX_EXHAUSTED` means no surplus and the probe covered the index, so the
    depth reached is the true total. `PROBE_CAP_HIT` means no surplus and no coverage, so
    completeness is simply unknown — the one value that means a parameter wants tuning.
    """

    DEPTH_REACHED = "depth_reached"
    INDEX_EXHAUSTED = "index_exhausted"
    PROBE_CAP_HIT = "probe_cap_hit"


@dataclass(frozen=True, slots=True)
class DetailField:
    """One key of an event's `detail` object.

    `values` is the closed set the field's value is drawn from, empty when the value is a count,
    an id or a piece of prose. `nullable` records that null is one of the stated values, as
    against a field that is merely null on rows the value does not apply to — every field is
    always present, since a key that is absent and a key that is null are indistinguishable to a
    signal, and one of those two would mean "this writer predates this field".
    """

    name: str
    values: tuple[str, ...] = ()
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class EventSpec:
    """What one kind of event row looks like.

    `names_memory` says whether the row's `memory_uuid` column is populated: a per-memory kind
    always names one, and a per-call kind never does. `detail_fields` is the complete, ordered
    set of keys the `detail` JSON carries.
    """

    names_memory: bool
    detail_fields: tuple[DetailField, ...]

    def __post_init__(self) -> None:
        names = [field.name for field in self.detail_fields]
        if len(set(names)) != len(names):
            raise ValueError(f"detail declares a field twice: {names}")

    @property
    def field_names(self) -> tuple[str, ...]:
        """Every key of this kind's detail, in the order the contract states them."""
        return tuple(field.name for field in self.detail_fields)

    def validate(self, detail: Mapping[str, object]) -> None:
        """Check one `detail` against this kind's declared shape, before it is serialized.

        Enforced in production rather than only in tests, because `detail` reaches the log as a
        mapping and no type checker can see a renamed or misspelled key inside one. A signal
        computed over free-form JSON cannot be wrong in a *detectable* way, which is the whole
        reason these specs exist; a spec nothing checks at the boundary is the same problem one
        layer up.

        Three things are checked, and the first is the one a test cannot cover for every future
        writer: the key set and its **order**, so two implementations of one kind produce the same
        payload rather than merely equivalent ones. Then any field whose value the contract draws
        from a closed set, so a writer cannot invent a member. Enum members and their plain values
        are interchangeable here, since they serialize identically.

        Raises:
            ValueError: the keys are not exactly this kind's, in order, or a closed-set field holds
                a value outside its set.
        """
        if tuple(detail) != self.field_names:
            raise ValueError(
                f"detail keys {tuple(detail)} are not {self.field_names} in that order"
            )
        for field in self.detail_fields:
            value = detail[field.name]
            if not field.values or (value is None and field.nullable):
                continue
            if str(value) not in field.values:
                raise ValueError(f"{field.name}: {value!r} is not one of {list(field.values)}")


# The lexical arm cannot report `PROBE_CAP_HIT`: it is one limited statement over an ordered
# cursor, so returning fewer rows than it asked for is a proven end of cursor rather than an
# unknown. One vocabulary, two reachable subsets of it.
# The size fields describe authored prose, so a row that authored none carries them as null: on a
# merge that is every absorbed member, and on a promotion every row but the created or flipped one.
# An ordinary write always authors prose, so `remember` and `amend` use their own non-null fields.
_TOKEN_COUNT = DetailField("token_count", nullable=True)
_GIST_TOKENS = DetailField("gist_tokens", nullable=True)
_N_CHUNKS = DetailField("n_chunks", nullable=True)
_TRUNCATED = DetailField("truncated", nullable=True)

_DENSE_DEPTH = DetailField("dense_depth_reached", nullable=True)
_DENSE_STOP = DetailField("dense_stop_reason", values=tuple(StopReason), nullable=True)
_LEXICAL_DEPTH = DetailField("lexical_depth_reached", nullable=True)
_LEXICAL_STOP = DetailField(
    "lexical_stop_reason",
    values=(StopReason.DEPTH_REACHED, StopReason.INDEX_EXHAUSTED),
    nullable=True,
)

EVENT_SPECS: Final[Mapping[EventKind, EventSpec]] = MappingProxyType(
    {
        EventKind.SURFACE_CALL: EventSpec(
            names_memory=False,
            detail_fields=(
                DetailField("prompt_chars"),
                DetailField("limit"),
                DetailField("fusion_depth"),
                _DENSE_DEPTH,
                _DENSE_STOP,
                _LEXICAL_DEPTH,
                _LEXICAL_STOP,
                DetailField("query_tokens"),
                DetailField("query_truncated"),
                DetailField("lexical_skipped"),
                DetailField("n_returned"),
                DetailField("n_demoted"),
            ),
        ),
        EventKind.SURFACE: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("rank"),
                DetailField("fused_score"),
                DetailField("demoted"),
                DetailField("demotion", values=tuple(Demotion), nullable=True),
            ),
        ),
        EventKind.SEARCH: EventSpec(
            names_memory=False,
            detail_fields=(
                DetailField("query_chars"),
                DetailField("limit"),
                DetailField("fusion_depth"),
                _DENSE_DEPTH,
                _DENSE_STOP,
                _LEXICAL_DEPTH,
                _LEXICAL_STOP,
                DetailField("query_tokens"),
                DetailField("query_truncated"),
                DetailField("lexical_skipped"),
                DetailField("include_retired"),
                DetailField("n_returned"),
                DetailField("uuids"),
            ),
        ),
        EventKind.FETCH: EventSpec(
            names_memory=True,
            detail_fields=(DetailField("version"), DetailField("found")),
        ),
        EventKind.REMEMBER: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("version"),
                DetailField("token_count"),
                DetailField("gist_tokens"),
                DetailField("n_chunks"),
                DetailField("truncated"),
            ),
        ),
        EventKind.AMEND: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("from_version"),
                DetailField("to_version"),
                DetailField("token_count"),
                DetailField("gist_tokens"),
                DetailField("n_chunks"),
                DetailField("truncated"),
            ),
        ),
        EventKind.RETIRE: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("from_version"),
                DetailField("to_version"),
                DetailField("superseded_by", nullable=True),
            ),
        ),
        EventKind.MERGE: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("group_id"),
                DetailField("run_id"),
                DetailField("role", values=tuple(MergeRole)),
                DetailField("from_version"),
                DetailField("to_version"),
                DetailField("n_absorbed"),
                _TOKEN_COUNT,
                _GIST_TOKENS,
                _N_CHUNKS,
                _TRUNCATED,
            ),
        ),
        EventKind.PROMOTE: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("group_id"),
                DetailField("run_id"),
                DetailField("role", values=tuple(PromoteRole)),
                DetailField("form", values=tuple(PromoteForm)),
                DetailField("from_version"),
                DetailField("to_version"),
                DetailField("n_absorbed"),
                _TOKEN_COUNT,
                _GIST_TOKENS,
                _N_CHUNKS,
                _TRUNCATED,
            ),
        ),
        EventKind.DISCARD: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("group_id"),
                DetailField("run_id"),
                DetailField("reason"),
                DetailField("from_version"),
                DetailField("to_version"),
                DetailField("n_absorbed"),
            ),
        ),
        EventKind.DEDUP_OFFERED: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("created_uuid"),
                DetailField("cosine"),
                DetailField("rank"),
            ),
        ),
        EventKind.VERSION_CONFLICT: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("verb"),
                DetailField("expected_version"),
                DetailField("actual_version"),
            ),
        ),
        EventKind.NO_RECEIPT: EventSpec(
            names_memory=True,
            detail_fields=(DetailField("verb"), DetailField("version_presented")),
        ),
        EventKind.GROUP_SERVED: EventSpec(
            names_memory=True,
            detail_fields=(
                DetailField("group_id"),
                DetailField("run_id"),
                DetailField("role", values=tuple(ServeRole)),
                DetailField("version_served"),
                DetailField("serve_count"),
            ),
        ),
        EventKind.CONSOLIDATE_RUN: EventSpec(
            names_memory=False,
            detail_fields=(
                DetailField("run_id"),
                DetailField("phase", values=tuple(RunPhase)),
                DetailField("n_groups"),
                DetailField("n_members"),
                DetailField("n_deferred"),
            ),
        ),
    }
)


# ---------------------------------------------------------------------------
# The typed detail values
# ---------------------------------------------------------------------------
#
# `coding-standards.md` §2: every payload the design specifies becomes a typed object, so a renamed
# or mistyped field fails at type-check time instead of surfacing as a wrong number in a signal.
# `EVENT_SPECS` above says what each kind's detail *is*; these say it in a form the type checker can
# hold a producer to, and each one carries its own `kind` so a producer cannot pair a payload with
# the wrong one — a mismatch that was representable while the kind travelled as a separate argument.
#
# Declaration order is the contract's order. `EventSpec.validate` compares the two, so a field added
# here in the wrong place fails rather than quietly reordering a payload.
#
# **Only the kinds something writes today are here.** The six consolidation kinds (`merge`,
# `promote`, `discard`, `dedup_offered`, `group_served`, `consolidate_run`) have no producer yet; a
# dataclass nothing constructs is dead code, and the milestone that writes those verbs adds its
# value type in the same change. It cannot forget: `log_event` takes an `EventDetail`, so there is
# no dict-shaped way in.


class EventDetail:
    """One event's `detail`, typed, and carrying the kind it belongs to.

    Subclasses are frozen dataclasses whose fields are exactly their kind's declared fields, in the
    declared order. This base is not itself a dataclass: it holds the one class-level fact (`kind`)
    and the one conversion every subclass needs, so a subclass declares nothing but its own payload.
    """

    kind: ClassVar[EventKind]

    def as_detail(self) -> dict[str, object]:
        """This payload as the mapping that will be serialized, in declaration order.

        Read off `dataclasses.fields`, so the order is the class's own and cannot drift from it. A
        field holding one of the shared groupings below is **spliced in place**, contributing its
        own fields rather than a nested object: the contract's detail is flat, and grouping the
        fields that belong together is what keeps the four arm-termination fields from being
        transcribed once per kind. `EventSpec.validate` compares the flattened order against the
        contract, so the splice is checked rather than assumed.

        Enum members are left as they are: they serialize identically to their values, and
        converting here would mean a second place that decides how a closed set reaches the log.
        """
        payload: dict[str, object] = {}
        for field in fields(self):  # type: ignore[arg-type]
            value = getattr(self, field.name)
            if is_dataclass(value) and not isinstance(value, type):
                payload.update({p.name: getattr(value, p.name) for p in fields(value)})
            else:
                payload[field.name] = value
        return payload


@dataclass(frozen=True, slots=True)
class ArmTermination:
    """Both arms' depth-and-reason pairs, which `search` and `surface_call` report identically.

    One value rather than four loose fields on each of the two kinds, so the pair that
    `schema.md` invariant 20 constrains travels as a unit and one kind cannot come to mean something
    the other does not. Null in both fields of an arm is the skipped case, and only the lexical arm
    can be skipped.
    """

    dense_depth_reached: int | None
    dense_stop_reason: StopReason | None
    lexical_depth_reached: int | None
    lexical_stop_reason: StopReason | None


@dataclass(frozen=True, slots=True)
class QueryShape:
    """What one external query cost and whether it survived the model's input budget intact.

    Shared by `search` and `surface_call` for the same reason as `ArmTermination`: the three fields
    are one fact about one query, and `query_truncated` is only interpretable beside the count it
    applies to.
    """

    query_tokens: int
    query_truncated: bool
    lexical_skipped: bool


@dataclass(frozen=True, slots=True)
class SurfaceCallDetail(EventDetail):
    """`surface_call` — exactly one per push, including when nothing was returned."""

    kind: ClassVar[EventKind] = EventKind.SURFACE_CALL

    prompt_chars: int
    limit: int
    fusion_depth: int
    arms: ArmTermination
    query: QueryShape
    n_returned: int
    n_demoted: int


@dataclass(frozen=True, slots=True)
class SurfaceDetail(EventDetail):
    """`surface` — one per memory the push returned, sharing its call's `op_id`."""

    kind: ClassVar[EventKind] = EventKind.SURFACE

    rank: int
    fused_score: float
    demoted: bool
    demotion: Demotion | None


@dataclass(frozen=True, slots=True)
class SearchDetail(EventDetail):
    """`search` — one per pull call, carrying the uuids it returned."""

    kind: ClassVar[EventKind] = EventKind.SEARCH

    query_chars: int
    limit: int
    fusion_depth: int
    arms: ArmTermination
    query: QueryShape
    include_retired: bool
    n_returned: int
    uuids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Refuse a count that disagrees with the list it counts.

        The contract states both, so both are written — but two ways to say how many rows came back
        is one way for them to disagree, and a signal dividing by `n_returned` while joining on
        `uuids` would then be dividing by a number describing a different set.
        """
        if self.n_returned != len(self.uuids):
            raise ValueError(
                f"n_returned={self.n_returned} but {len(self.uuids)} uuids were listed"
            )


@dataclass(frozen=True, slots=True)
class FetchDetail(EventDetail):
    """`fetch` — one per distinct uuid requested, found or not."""

    kind: ClassVar[EventKind] = EventKind.FETCH

    version: int | None
    found: bool


@dataclass(frozen=True, slots=True)
class RememberDetail(EventDetail):
    """`remember` — one per call, with the chunking preflight's own numbers."""

    kind: ClassVar[EventKind] = EventKind.REMEMBER

    version: int
    token_count: int
    gist_tokens: int
    n_chunks: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class AmendDetail(EventDetail):
    """`amend` — one per call, reporting both versions and the preflight's numbers."""

    kind: ClassVar[EventKind] = EventKind.AMEND

    from_version: int
    to_version: int
    token_count: int
    gist_tokens: int
    n_chunks: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class RetireDetail(EventDetail):
    """`retire` — one per call. `superseded_by` null is retired-outright, not a missing value."""

    kind: ClassVar[EventKind] = EventKind.RETIRE

    from_version: int
    to_version: int
    superseded_by: str | None


@dataclass(frozen=True, slots=True)
class VersionConflictDetail(EventDetail):
    """`version_conflict` — one per contested uuid in a rejected call."""

    kind: ClassVar[EventKind] = EventKind.VERSION_CONFLICT

    verb: str
    expected_version: int
    actual_version: int


@dataclass(frozen=True, slots=True)
class NoReceiptDetail(EventDetail):
    """`no_receipt` — one per uuid lacking a receipt in a rejected call."""

    kind: ClassVar[EventKind] = EventKind.NO_RECEIPT

    verb: str
    version_presented: int
