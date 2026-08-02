"""The value types' own refusals, and the ladder rungs a conforming caller cannot reach.

Every test here defends a **refusal**: a value that cannot be constructed, or a rung that answers
rather than proceeds. They are separated from the behaviour files because that is what they have in
common — for a defensive branch the assertion is "this is refused", never "this is what comes back",
since if returning something plausible were acceptable there the branch would not need to exist.
"""

from pathlib import Path

import pytest

from tests.consolidation_fixtures import consolidator
from zikaron.core.consolidation import planning, rowstate, serving, verbs
from zikaron.core.consolidation.context import ConsolidationSettings
from zikaron.core.consolidation.groups import Shard
from zikaron.core.consolidation.payload import (
    GroupConflict,
    MergeTarget,
    NamedRow,
    ServedGroup,
)
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.records.memory import Rewrite, Tier
from zikaron.core.retrieval.eligibility import Consumer

_RECORD = ("the proto toolchain is pinned", "the pinned version lives in requirements.txt")
_A = ("proto codegen fails on staging", "the compiler version drifts from requirements.txt")
_NEW = Rewrite(gist="proto drift, consolidated", content="one pin; the drift bites everywhere")


def _settings(**changed: float) -> ConsolidationSettings:
    values: dict[str, float] = {
        "anchor_cutoff": 0.65,
        "orphan_edge_cutoff": 0.65,
        "mutual_k": 5,
        "group_max": 12,
        "max_group_serves": 3,
        "run_lease_seconds": 1800,
    }
    values.update(changed)
    return ConsolidationSettings(
        anchor_cutoff=values["anchor_cutoff"],
        orphan_edge_cutoff=values["orphan_edge_cutoff"],
        mutual_k=int(values["mutual_k"]),
        group_max=int(values["group_max"]),
        max_group_serves=int(values["max_group_serves"]),
        run_lease_seconds=int(values["run_lease_seconds"]),
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("anchor_cutoff", 1.5),
        ("anchor_cutoff", -0.1),
        ("orphan_edge_cutoff", 1.5),
        ("mutual_k", 1),
        ("mutual_k", 51),
        ("group_max", 1),
        ("group_max", 65),
        ("max_group_serves", 0),
        ("max_group_serves", 17),
        ("run_lease_seconds", 59),
        ("run_lease_seconds", 86401),
    ],
)
def test_a_setting_outside_its_own_range_cannot_be_constructed(key: str, value: float) -> None:
    """Self-validating for the reason `EffectiveConfig` is: "the only caller checks first" is a fact
    about today's call sites rather than a property of the type. A cutoff outside `[0, 1]` silently
    turns a threshold into a pass-everything or a reject-everything, and a `max_group_serves` of 0
    would make every group deferrable before its first delivery."""
    with pytest.raises(ValueError, match=key.removesuffix("_seconds")):
        _settings(**{key: value})


def test_the_shipped_defaults_are_inside_their_own_ranges() -> None:
    """The other direction, so the parametrized refusals above cannot pass by refusing
    everything."""
    assert _settings().mutual_k == 5


@pytest.mark.parametrize(("index", "of"), [(1, 0), (0, 1), (2, 1), (-1, 3)])
def test_a_malformed_shard_cannot_be_constructed(index: int, of: int) -> None:
    """Held in the type as well as in the table's own `CHECK`s, because the planner computes these:
    a planner that can build an impossible shard can also build a set that violates invariant 19,
    and the type is where that becomes impossible rather than merely detected at the `INSERT`."""
    with pytest.raises(ValueError, match="shard"):
        Shard(index=index, of=of)


async def test_a_consumer_with_no_narrowing_filter_is_refused_rather_than_admitted(
    tmp_path: Path,
) -> None:
    """`surface` and `search` narrow nothing, so there is nothing to re-check — and a caller asking
    has confused "no filter" with "admits nothing". Refused, because the plausible answer here
    would be `True`, which would silently make every row a deliverable member."""
    async with consolidator(tmp_path) as c:
        with pytest.raises(KeyError, match="no narrowing filter"):
            await rowstate._satisfies(  # the refusal itself is the contract under test
                c.harness.store.connection, uuid="whatever", consumer=Consumer.SURFACE
            )


async def test_a_write_verb_naming_a_pending_group_answers_not_in_group(tmp_path: Path) -> None:
    """The case rung 2's own list omitted. A `pending` group has never been delivered, so no
    version was handed out and no row of it is *actionable* — which is exactly what `not_in_group`
    means, and its stated recovery (call `next_group`) is exactly right.

    A conforming consolidator cannot reach this, since it learns a `group_id` only from a serve; the
    fixture therefore plans without serving and reads the id out of the table. Checked rather than
    argued away because the alternative argument is three steps long.
    """
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        await planning.plan_groups(c.harness.store.connection, call=c.call())
        group_id = (await c.groups())[0][0]
        with pytest.raises(ZikaronError) as raised:
            await verbs.discard(
                c.harness.store.connection,
                group_id=group_id,
                absorb=[NamedRow(uuid=member, expected_version=1)],
                reason="noise",
                call=c.call(op_id="d"),
            )
        assert raised.value.code is ErrorCode.NOT_IN_GROUP
        assert raised.value.data["uuids"] == [member]
        assert await c.member_rows(group_id) == [(member, 1, None, None)]


async def test_a_merge_target_that_stopped_being_targetable_is_refused(tmp_path: Path) -> None:
    """Rung 6 for the target: a merge never rewrites a historical row, because `superseded_by` is
    immutable once set, so a retired row given fresh prose would be neither the current record nor a
    faithful historical one.

    Reached the way the design says it is reached: retiring the target bumps its version, so the
    first call is a `version_conflict` carrying a fresh receipt, and the **retry** at the version
    the conflict reported arrives at rung 6 holding a row that is no longer targetable.
    """
    async with consolidator(tmp_path) as c:
        record = await c.write(
            gist=_RECORD[0], content=_RECORD[1], minute=1, degrees=0.0, tier=Tier.LONG_TERM
        )
        await c.write(gist=_A[0], content=_A[1], minute=2, degrees=10.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        assert served.anchor is not None
        await c.harness.retire(record)
        absorb = [
            NamedRow(
                uuid=served.journal_entries[0].uuid,
                expected_version=served.journal_entries[0].expected_version,
            )
        ]
        conflict = await verbs.merge(
            c.harness.store.connection,
            group_id=served.group_id,
            target=MergeTarget(
                row=NamedRow(uuid=record, expected_version=served.anchor.expected_version),
                rewrite=_NEW,
            ),
            absorb=absorb,
            call=c.call(op_id="m1"),
        )
        assert isinstance(conflict, GroupConflict)
        with pytest.raises(ZikaronError) as raised:
            await verbs.merge(
                c.harness.store.connection,
                group_id=served.group_id,
                target=MergeTarget(
                    row=NamedRow(uuid=record, expected_version=conflict.current[0].version),
                    rewrite=_NEW,
                ),
                absorb=absorb,
                call=c.call(op_id="m2"),
            )
        assert raised.value.code is ErrorCode.BAD_MERGE_TARGET
        assert raised.value.data["reason"] == "not_targetable"


async def test_a_promotion_returns_a_conflict_when_its_member_moved(tmp_path: Path) -> None:
    """`promote` shares the conflict shape with the other two verbs, and returns it before deciding
    which form to run — so a moved member cannot be flipped in place on the strength of prose that
    has since changed."""
    async with consolidator(tmp_path) as c:
        member = await c.write(gist=_A[0], content=_A[1], minute=1, degrees=0.0)
        served = await serving.next_group(c.harness.store.connection, call=c.call())
        assert isinstance(served, ServedGroup)
        await c.amend(member, gist=_A[0], content="a primary agent got here first")
        outcome = await verbs.promote(
            c.harness.store.connection,
            group_id=served.group_id,
            rewrite=Rewrite(gist=_A[0], content=_A[1]),
            absorb=[NamedRow(uuid=member, expected_version=1)],
            call=c.call(op_id="p"),
        )
        assert isinstance(outcome, GroupConflict)
        assert [one.uuid for one in outcome.current] == [member]
        assert await c.row(member) == ("journal", True, None, 2)
