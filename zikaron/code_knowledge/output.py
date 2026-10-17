"""The one JSON object the planner prints (`design/code-knowledge.md` §3.5)."""

from pathlib import Path

from zikaron.code_knowledge.apply import Applied
from zikaron.code_knowledge.survey import ModuleSources
from zikaron.core.code_knowledge.plan import Move, Plan, ReadmeItem, WorkItem
from zikaron.core.knowledge.counters import PRUNED_DIRECTORIES_KEY, ScanCounters, SkipReason


def _item(item: WorkItem) -> dict[str, object]:
    rendered: dict[str, object] = {
        "kind": item.kind.value,
        "source": item.source,
        "document": item.document,
        "front_matter": item.front_matter,
    }
    if item.defect is not None:
        rendered["reason"] = item.defect.value
    return rendered


def _readme(readme: ReadmeItem | None, roles: str | None) -> dict[str, object] | None:
    if readme is None:
        return None
    return {
        "document": readme.document,
        "front_matter": readme.front_matter,
        "documents": readme.documents,
        "roles": roles,
    }


def _moves(moves: tuple[Move, ...]) -> list[dict[str, str]]:
    return [{"from": move.origin, "to": move.target} for move in moves]


def _skipped(counters: ScanCounters) -> dict[str, int]:
    """Every reason that refused at least one file, in the order the corpus scan reports them."""
    counts = {reason.value: counters.skipped.get(reason, 0) for reason in SkipReason}
    counts[PRUNED_DIRECTORIES_KEY] = counters.pruned_directories
    return {reason: count for reason, count in counts.items() if count}


def rendered(
    root: Path, sources: ModuleSources, plan: Plan, applied: Applied | None, roles: str | None
) -> dict[str, object]:
    """The planner's report on one run. Under `--apply` it names what was removed and moved, and
    `roles` the root-relative path of the role list it wrote; without it, what would be, and no
    role list, since none was written."""
    if applied is None:
        changes: dict[str, object] = {
            "would_remove": list(plan.removals),
            "would_move": _moves(plan.moves),
        }
    else:
        changes = {"removed": list(applied.removed), "moved": _moves(applied.moved)}
    # A move not made, because a file appeared at its target, leaves its orphan for the next run.
    settled = applied is not None and applied.moved == plan.moves
    return {
        "root": str(root),
        "git_mode_effective": sources.effective.value,
        "work": [_item(item) for item in plan.work],
        "readme": _readme(plan.readme, roles),
        **changes,
        "foreign": [
            {"document": foreign.document, "source": foreign.source} for foreign in plan.foreign
        ],
        "unplaceable": list(plan.unplaceable),
        "skipped": _skipped(sources.counters),
        "unverifiable": [
            {"source": source.source, "state": source.state.value} for source in plan.unverifiable
        ],
        "remaining": plan.remaining,
        "up_to_date": plan.up_to_date(applied=settled),
    }
