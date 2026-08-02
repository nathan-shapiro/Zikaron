"""What one consolidation call holds constant: who owns the run, and the parameters D29 is tuned by.

Three value types, each self-validating at construction, because every one of them carries a fact a
later layer would otherwise have to keep re-deciding.

`RunOwner` is the **pair** `(session_id, pid)`, never the session alone. Since every client of one
kiro session shares a `session_id` *and* two consolidators of that session also share
`client_kind='consolidator'`, a session-only owner would make two concurrently launched
consolidators the same worker — which would silently defeat the one-worker guarantee `next_group`
establishes, and with it D29's claim that transitive merging emerges from processing groups
oldest-first against a store that updates as it goes.

`ConsolidationSettings` range-checks itself against `schema.md` §"Configuration keys" rather than
trusting that its one real caller resolved the config properly, for the reason `EffectiveConfig`
self-validates: "the only caller checks first" is a fact about today's call sites, not a property of
the type, and a cutoff outside `[0, 1]` silently turns a threshold into a pass-everything or a
reject-everything.
"""

from dataclasses import dataclass
from typing import Final, Self

from zikaron.core.config.resolution import EffectiveConfig
from zikaron.core.events import ClientKind
from zikaron.core.indexing.writes import IndexedCall, IndexingContext
from zikaron.core.records.memory import CallParams
from zikaron.core.retrieval.retrieve import RetrievalSettings

#: `schema.md` §"Configuration keys"' own ranges for the six `[consolidation]` keys. Transcribed
#: here as bounds this type refuses to be built outside, not as defaults — the defaults live in
#: `config.keys`, which is the one declaration of the table, and a second copy of them here would be
#: a second thing to keep in step.
_CUTOFF_MIN: Final = 0.0
_CUTOFF_MAX: Final = 1.0
_MUTUAL_K_MIN: Final = 2
_MUTUAL_K_MAX: Final = 50
_GROUP_MAX_MIN: Final = 2
_GROUP_MAX_MAX: Final = 64
_MAX_GROUP_SERVES_MIN: Final = 1
_MAX_GROUP_SERVES_MAX: Final = 16
_RUN_LEASE_MIN: Final = 60
_RUN_LEASE_MAX: Final = 86400


@dataclass(frozen=True, slots=True)
class RunOwner:
    """Who holds a consolidation run: the `(session_id, pid)` pair, both required.

    Compared by value, which is what makes "is the caller this run's owner" a single `==` rather
    than two comparisons one call site could get half right.

    Raises:
        ValueError: an empty `session_id`, or a `pid` below 1 — `architecture.md` rejects a missing
            envelope `pid` with `bounds` at the transport boundary, and this type is the reason a
            layer inward may then assume it has one.
    """

    session_id: str
    pid: int

    def __post_init__(self) -> None:
        if self.session_id == "":
            raise ValueError("a run owner's session_id cannot be empty")
        if self.pid < 1:
            raise ValueError(f"a run owner's pid must be >= 1, got {self.pid}")


@dataclass(frozen=True, slots=True)
class ConsolidationSettings:
    """The six `[consolidation]` config keys, resolved once for the life of a store handle.

    Bundled for the reason `RetrievalSettings` is: planning is a pure function of the store **plus
    these**, so two calls of one run reading them from different snapshots would make the run
    irreproducible, and `architecture.md` reads the effective config once at service startup
    precisely so that cannot happen.

    Raises:
        ValueError: any key outside the range `schema.md` §"Configuration keys" states for it.
    """

    anchor_cutoff: float
    orphan_edge_cutoff: float
    mutual_k: int
    group_max: int
    max_group_serves: int
    run_lease_seconds: int

    def __post_init__(self) -> None:
        self._require_cutoff("anchor_cutoff", self.anchor_cutoff)
        self._require_cutoff("orphan_edge_cutoff", self.orphan_edge_cutoff)
        self._require_range("mutual_k", self.mutual_k, _MUTUAL_K_MIN, _MUTUAL_K_MAX)
        self._require_range("group_max", self.group_max, _GROUP_MAX_MIN, _GROUP_MAX_MAX)
        self._require_range(
            "max_group_serves",
            self.max_group_serves,
            _MAX_GROUP_SERVES_MIN,
            _MAX_GROUP_SERVES_MAX,
        )
        self._require_range("run_lease", self.run_lease_seconds, _RUN_LEASE_MIN, _RUN_LEASE_MAX)

    @staticmethod
    def _require_cutoff(name: str, value: float) -> None:
        if not _CUTOFF_MIN <= value <= _CUTOFF_MAX:
            raise ValueError(f"{name}={value} outside [{_CUTOFF_MIN}, {_CUTOFF_MAX}]")

    @staticmethod
    def _require_range(name: str, value: int, low: int, high: int) -> None:
        if not low <= value <= high:
            raise ValueError(f"{name}={value} outside {low}-{high}")

    @classmethod
    def from_config(cls, config: EffectiveConfig) -> Self:
        """Read the six `[consolidation]` keys D29 is parameterized by."""
        return cls(
            anchor_cutoff=config.get_float("anchor_cutoff"),
            orphan_edge_cutoff=config.get_float("orphan_edge_cutoff"),
            mutual_k=config.get_int("mutual_k"),
            group_max=config.get_int("group_max"),
            max_group_serves=config.get_int("max_group_serves"),
            run_lease_seconds=config.get_int("run_lease"),
        )


@dataclass(frozen=True, slots=True)
class ConsolidationCall:
    """Everything one consolidator call needs: identity, ownership, parameters and the index.

    The same bundling `WriteCall` and `ReadCall` use, and for the same reasons — every entry point
    in this package needs at least three of the five, none changes partway through a call, and
    keeping them loose invites a call site that pairs one store's encoder with another's context.

    `pid` is separate from `ctx` rather than added to `CallParams` because it is not a fact every
    verb in the system needs: only a consolidation run has an owner, and `CallParams` is what every
    `event` row and every receipt in the store is written from.

    Raises:
        ValueError: `ctx.client_kind` is not `consolidator`. Checked here rather than assumed,
            because `read_receipt`'s key includes `client_kind` and this layer both mints and spends
            receipts: minted under `mcp`, a serve's receipts would license the **primary** agent to
            amend rows it never fetched, which is the exact hole that column was added to close.
            Also raised for an out-of-range setting or a malformed owner, by the two types above.
    """

    ctx: CallParams
    pid: int
    settings: ConsolidationSettings
    retrieval: RetrievalSettings
    index: IndexingContext

    def __post_init__(self) -> None:
        if self.ctx.client_kind != ClientKind.CONSOLIDATOR:
            raise ValueError(
                f"a consolidation call runs as client_kind={ClientKind.CONSOLIDATOR.value!r}, "
                f"not {self.ctx.client_kind!r}: receipts are scoped by client kind, so minting "
                f"this serve's under another kind would license a different client to write"
            )

    @property
    def owner(self) -> RunOwner:
        """This call's `(session_id, pid)` ownership pair."""
        return RunOwner(session_id=self.ctx.session_id, pid=self.pid)

    @property
    def indexed(self) -> IndexedCall:
        """This call as the indexed write path takes it, for the two verbs that author prose."""
        return IndexedCall(ctx=self.ctx, index=self.index)
