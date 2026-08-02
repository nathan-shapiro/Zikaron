"""The one retrieval-eligibility predicate, and the complete table of per-consumer filters.

`schema.md` §"Retrieval eligibility" defines three row states and which of them a read may see;
§"Consumer filters" then states, in one table, the single filter each read path is allowed to add
on top. The contract is unusually strict about that second half — *"a filter that is not in this
table does not exist"* — because divergence between read paths is how a memory ends up eligible
for the agent's `search` and invisible to the hook that injects. That is not a hypothetical: this
table has already had to correct a draft in which two consumers were handed rows they could not
legally act on.

So this module is the only place in `core` that writes `active`, `tier` or `superseded_by` into a
retrieval `WHERE` clause. A consumer names itself and gets a clause; it cannot pass one. The three
narrowing filters are each the *legality* condition of the action the rows are being retrieved for
— dedup offers an `amend`, consolidation may `merge`, orphan adjacency makes group members — which
is why retrieval for reading narrows nothing at all.

`fetch` is deliberately absent from `Consumer`: `schema.md`'s table lists it to say it is **not a
predicate path** — a uuid is a handle and resolving it must work in any state — so giving it a
member here would invent the very filter the design says it does not have.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

#: The alias every statement in this package gives the `memory` table. The filter fragments below
#: are written against it, so an arm that renamed its join would silently stop being filtered.
MEMORY_ALIAS: Final = "m"

#: `schema.md`'s `ELIGIBLE(include_retired = 0)`: live rows and superseded rows, which is what makes
#: D25's "demotes rather than hides" true at all. Outright-retired rows — `active = 0` with no
#: replacement — are the only state excluded, and `include_retired` is what widens to them.
_BASE_PREDICATE: Final = f"({MEMORY_ALIAS}.active = 1 OR {MEMORY_ALIAS}.superseded_by IS NOT NULL)"

#: `ELIGIBLE(include_retired = 1)`: all rows. Written as a true conjunct rather than as an absent
#: one so that "the base predicate" is always present in the clause a reader of the SQL sees, and
#: so the widened form is visibly a widening rather than a missing `WHERE`.
_WIDENED_PREDICATE: Final = "1 = 1"


class Consumer(StrEnum):
    """The five read paths, exactly as `schema.md` §"Consumer filters" enumerates them.

    Closed on purpose: the filter is chosen by *which consumer this is*, never passed in, so a
    sixth read path cannot appear without a row being added to the design table first.
    """

    SURFACE = "surface"
    SEARCH = "search"
    DEDUP = "dedup"
    CONSOLIDATION = "consolidation"
    ORPHAN = "orphan"


@dataclass(frozen=True, slots=True)
class ConsumerFilter:
    """One consumer's single permitted narrowing of the base predicate.

    `predicate` is the SQL the design states for it, or `None` where the design states none.
    `excludes_self` is the other half of two of those rows — "and exclude the row just created",
    "and exclude the querying row itself" — which is a bound uuid rather than a static predicate
    and so cannot live in the same string.

    `include_retired_allowed` is not a filter but the same kind of fact about the read path, and it
    belongs here for the same reason: `schema.md` gives `include_retired` to `search` alone, so
    every other consumer having it available would be a second, undocumented way to widen the base.
    """

    predicate: str | None
    excludes_self: bool = False
    include_retired_allowed: bool = False


#: The design table, transcribed once. A test parses `schema.md` and asserts this matches it.
CONSUMER_FILTERS: Final[Mapping[Consumer, ConsumerFilter]] = MappingProxyType(
    {
        # D25: superseded rows must be able to reach the injected five.
        Consumer.SURFACE: ConsumerFilter(predicate=None),
        # Deliberate archaeology is the agent's call, and it widens the base rather than narrowing.
        Consumer.SEARCH: ConsumerFilter(predicate=None, include_retired_allowed=True),
        # The offered resolution is `amend`, which rejects `active = 0`.
        Consumer.DEDUP: ConsumerFilter(predicate=f"{MEMORY_ALIAS}.active = 1", excludes_self=True),
        # Every long-term row shown is one `merge` may be asked to rewrite.
        Consumer.CONSOLIDATION: ConsumerFilter(
            predicate=f"{MEMORY_ALIAS}.tier = 'long_term' AND {MEMORY_ALIAS}.active = 1"
        ),
        # Exactly the definition of an unconsolidated journal row, i.e. of a group member.
        Consumer.ORPHAN: ConsumerFilter(
            predicate=f"{MEMORY_ALIAS}.tier = 'journal' AND {MEMORY_ALIAS}.active = 1",
            excludes_self=True,
        ),
    }
)


def narrowing(consumer: Consumer) -> str | None:
    """The single filter this consumer adds on top of the base predicate, as SQL over
    `MEMORY_ALIAS`.

    Exposed because two paths outside retrieval have to answer "does this one row still satisfy that
    filter": a consolidation serve re-validates the members it is about to deliver, and the
    consolidator ladder's rung 6 re-checks state on rows it has already authorized. Both use this
    string in a `WHERE` of their own rather than re-expressing the condition in Python, and that is
    a structural choice rather than a stylistic one — a hand-written `row.tier is Tier.JOURNAL and
    row.active` is a **second statement** of a rule the design says has exactly one home, and it
    would keep passing while this table moved underneath it.

    Returns:
        The consumer's clause, or `None` where the design states no narrowing — for `surface` and
        `search`, where every eligible row is admitted and there is nothing to re-check.
    """
    return CONSUMER_FILTERS[consumer].predicate


@dataclass(frozen=True, slots=True)
class Scope:
    """Which rows one read may see: a consumer, and the two facts the design lets it vary.

    Self-validating, because both of those facts are constrained by the consumer and a violation
    is a silent widening rather than a visible error. A consumer that may not set `include_retired`
    would otherwise reach outright-retired rows with no row in the design table permitting it, and
    an `exclude_uuid` supplied where the table states no exclusion — or omitted where it states one
    — changes the candidate set on a path whose whole purpose is that every consumer agrees.

    Raises:
        ValueError: `include_retired` on a consumer the design does not give it to, or an
            `exclude_uuid` that disagrees with the consumer's `excludes_self`.
    """

    consumer: Consumer
    include_retired: bool = False
    exclude_uuid: str | None = None

    def __post_init__(self) -> None:
        rule = CONSUMER_FILTERS[self.consumer]
        if self.include_retired and not rule.include_retired_allowed:
            raise ValueError(f"{self.consumer} may not set include_retired")
        if rule.excludes_self != (self.exclude_uuid is not None):
            raise ValueError(
                f"{self.consumer} excludes_self={rule.excludes_self}, "
                f"exclude_uuid={self.exclude_uuid!r}"
            )

    def where(self) -> tuple[str, tuple[str, ...]]:
        """This scope as a `WHERE` fragment over `MEMORY_ALIAS`, plus its bound parameters.

        The fragment is built from source-level constants only; the one request-time value an
        eligibility clause can carry — the excluded uuid — is a bound parameter, never text.

        Returns:
            `(clause, params)`, the clause always non-empty so a caller can concatenate it without
            deciding whether a `WHERE` is needed at all.
        """
        conjuncts = [_WIDENED_PREDICATE if self.include_retired else _BASE_PREDICATE]
        rule = CONSUMER_FILTERS[self.consumer]
        if rule.predicate is not None:
            conjuncts.append(rule.predicate)
        params: tuple[str, ...] = ()
        if self.exclude_uuid is not None:
            conjuncts.append(f"{MEMORY_ALIAS}.uuid <> ?")
            params = (self.exclude_uuid,)
        return " AND ".join(conjuncts), params
