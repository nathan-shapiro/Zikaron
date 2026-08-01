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
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


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
