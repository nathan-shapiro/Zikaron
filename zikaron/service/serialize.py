"""Typed RPC response shapes: one frozen dataclass per wire object `architecture.md` specifies.

`coding-standards.md` §2: "every payload the design specifies becomes a typed object... a renamed
field then fails at type-check time instead of surfacing as a `KeyError` in production." The
service boundary is exactly such a payload — every shape here is copied field-for-field from a
table in `architecture.md`'s tool-surface or consolidator-tool-surface sections — so each gets its
own dataclass rather than a hand-built `dict[str, object]` at each dispatch call site. A field
renamed on one side of a nested structure and not the other, or a nested object serialized flat
where the contract states a flat one nested, now fails `mypy --strict` at the call site that built
it wrong, rather than only at the one wire test that happened to exercise that exact shape.

**`RpcResult` is the one seam every handler's return value passes through.** `as_json()` is where
a typed value finally becomes the JSON value (`object` — a dict for most shapes, a bare list for
`SearchResult`) that `rpc.encode_result`/`encode_error` frame — one conversion, in one place, per
type, so the *dispatch* layer never touches a bare dict or list at all.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

from zikaron.core.consolidation.groups import Shard
from zikaron.core.consolidation.payload import GroupRecord
from zikaron.core.errors import RowState
from zikaron.core.records.memory import ConflictRecord, FetchedMemory, Tier
from zikaron.core.retrieval.reads import SearchHit
from zikaron.core.write.dedup import NearDuplicate


class RpcResult(ABC):
    """One RPC method's successful result, as the exact wire shape `architecture.md` specifies.

    `as_json()` returns `object`, not `dict[str, object]`: most of `architecture.md`'s
    tool-surface tables give a method a bare object (`{uuid, version, ...}`), but
    `zikaron_search` is documented as returning a bare **list** — `[{uuid, gist, ...}, ...]`
    directly, no wrapping key — and forcing that shape through a `dict`-typed return would either
    misrepresent it or require inventing a key the design never states. `SearchResult` is
    therefore the one subclass whose `as_json()` returns a `list`, not a `dict`.
    """

    @abstractmethod
    def as_json(self) -> object:
        """This result, as the JSON value `rpc.encode_result` frames."""


# ---------------------------------------------------------------------------
# Shared record shapes — `CONFLICT_RECORD`, `fetch`'s per-record shape, `search`'s per-row shape
# ---------------------------------------------------------------------------


class _HasResolvedStateFields(Protocol):
    """The nine fields `CONFLICT_RECORD` states, which `ConflictRecord` and `FetchedMemory` both
    carry — structurally, since the two are separate dataclasses with different field *order*
    (`FetchedMemory` interleaves `active` between `version` and `state`; `ConflictRecord` has no
    `active` at all), so one cannot stand in for the other positionally. Taking the whole record
    as one parameter, typed by this protocol, is what keeps `_resolved_state_fields` a
    five-argument function rather than a nine-keyword one for a single logical value.
    """

    @property
    def uuid(self) -> str: ...
    @property
    def gist(self) -> str: ...
    @property
    def content(self) -> str: ...
    @property
    def version(self) -> int: ...
    @property
    def tier(self) -> Tier: ...
    @property
    def state(self) -> RowState: ...
    @property
    def superseded_by(self) -> str | None: ...
    @property
    def superseded_by_latest(self) -> str | None: ...
    @property
    def superseded_by_latest_state(self) -> RowState | None: ...


def _resolved_state_fields(record: _HasResolvedStateFields) -> dict[str, object]:
    """The nine fields `CONFLICT_RECORD` states, shared by `ConflictRecordJson` and
    `FetchedMemoryJson` rather than duplicated between them — a schema change here is one edit,
    not two dataclasses that happen to agree today.
    """
    return {
        "uuid": record.uuid,
        "gist": record.gist,
        "content": record.content,
        "version": record.version,
        "tier": str(record.tier),
        "state": str(record.state),
        "superseded_by": record.superseded_by,
        "superseded_by_latest": record.superseded_by_latest,
        "superseded_by_latest_state": (
            None
            if record.superseded_by_latest_state is None
            else str(record.superseded_by_latest_state)
        ),
    }


@dataclass(frozen=True, slots=True)
class ConflictRecordJson:
    """`architecture.md`'s `CONFLICT_RECORD`, exactly: `fetch`'s record minus `active` and the
    timestamps. Not an `RpcResult` on its own — it nests inside `AmendResult`/`RetireResult`/the
    consolidator conflict shapes, never travels as a whole response by itself."""

    record: ConflictRecord

    def as_json(self) -> dict[str, object]:
        return _resolved_state_fields(self.record)


@dataclass(frozen=True, slots=True)
class FetchedMemoryJson:
    """`zikaron_fetch`'s per-record shape: `CONFLICT_RECORD`'s fields plus `active` and both
    timestamps."""

    record: FetchedMemory

    def as_json(self) -> dict[str, object]:
        payload = _resolved_state_fields(self.record)
        payload["active"] = self.record.active
        payload["created_at"] = self.record.created_at
        payload["updated_at"] = self.record.updated_at
        return payload


@dataclass(frozen=True, slots=True)
class SearchHitJson:
    """`zikaron_search`'s per-row shape, exactly the seven fields the tool surface states."""

    hit: SearchHit

    def as_json(self) -> dict[str, object]:
        hit = self.hit
        return {
            "uuid": hit.uuid,
            "gist": hit.gist,
            "tier": str(hit.tier),
            "state": str(hit.state),
            "created_at": hit.created_at,
            "updated_at": hit.updated_at,
            "superseded_by": hit.superseded_by,
        }


@dataclass(frozen=True, slots=True)
class NearDuplicateJson:
    """One `near_duplicates` entry: `{uuid, gist, cosine, rank}`, exactly as `zikaron_remember`
    states it."""

    candidate: NearDuplicate

    def as_json(self) -> dict[str, object]:
        candidate = self.candidate
        return {
            "uuid": candidate.uuid,
            "gist": candidate.gist,
            "cosine": candidate.cosine,
            "rank": candidate.rank,
        }


@dataclass(frozen=True, slots=True)
class GroupRecordJson:
    """One `{uuid, expected_version, gist, content, created_at}` row — a group member, an
    anchor, or (with `rank` spliced in) a candidate."""

    record: GroupRecord

    def as_json(self) -> dict[str, object]:
        record = self.record
        return {
            "uuid": record.uuid,
            "expected_version": record.expected_version,
            "gist": record.gist,
            "content": record.content,
            "created_at": record.created_at,
        }


@dataclass(frozen=True, slots=True)
class RankedRecordJson:
    """One `candidates` entry: `GroupRecordJson`'s five fields **flattened** with `rank` spliced
    in, per `architecture.md`'s `[{uuid, expected_version, gist, content, created_at, rank}]` —
    never `{record: {...}, rank}`, which is a different, undocumented shape."""

    record: GroupRecord
    rank: int

    def as_json(self) -> dict[str, object]:
        return {**GroupRecordJson(self.record).as_json(), "rank": self.rank}


@dataclass(frozen=True, slots=True)
class ShardJson:
    """`{index, of}`, exactly as `zikaron_next_group`'s `shard` field states it."""

    shard: Shard

    def as_json(self) -> dict[str, object]:
        return {"index": self.shard.index, "of": self.shard.of}
