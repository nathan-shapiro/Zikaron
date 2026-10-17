"""What `--apply` changes on disk: the removals and moves a plan implies, the directories its
listed documents need, and the role list a listed README is written from.

`design/code-knowledge.md` §3.4, §3.6 and §3.7 are normative. Nothing here writes into a document
but the two lines a move rewrites, and nothing is touched outside the plan's own paths and the role
list's.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from zikaron.core.code_knowledge import readme as readme_text
from zikaron.core.code_knowledge.document import relinked
from zikaron.core.code_knowledge.plan import Move, Plan
from zikaron.core.store import permissions

_BYTE_ORDER_MARK: Final = chr(0xFEFF).encode()


@dataclass(frozen=True, slots=True)
class Applied:
    """What was removed and moved."""

    removed: tuple[str, ...]
    moved: tuple[Move, ...]


def _move(root: Path, move: Move) -> bool:
    """Write the relinked document at its target and remove the original. A file that appeared at
    the target since the survey is never overwritten: the move is not made, and the orphan stays
    for the next run to judge."""
    origin = root / move.origin
    raw = origin.read_bytes()
    marked = raw.startswith(_BYTE_ORDER_MARK)
    text = relinked(raw.removeprefix(_BYTE_ORDER_MARK).decode("utf-8"), move.source)
    target = root / move.target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as handle:
            handle.write((_BYTE_ORDER_MARK if marked else b"") + text.encode("utf-8"))
    except FileExistsError:
        return False
    origin.unlink()
    return True


def apply(root: Path, plan: Plan, roles: Path, roles_base: Path) -> Applied:
    """Make `plan`'s moves and removals, and create every directory its listed items' documents
    and README need, so that a documenter with no shell can write them. A listed README's role
    list is written to `roles`, under `roles_base` in the store directory and at the store's own
    modes; while no README is listed it is removed, with every directory up to `roles_base` it
    leaves empty.

    Raises:
        OSError: a file could not be moved, removed or written, or a directory created.
        ValueError: a document to move stopped being UTF-8 since the survey read it.
    """
    moved = tuple(move for move in plan.moves if _move(root, move))
    for document in plan.removals:
        (root / document).unlink(missing_ok=True)
    listed = [item.document for item in plan.work]
    if plan.readme is not None:
        listed.append(plan.readme.document)
        lines = readme_text.roles((file.source, file.role) for file in plan.readme.files)
        with permissions.restrictive_umask():
            roles.parent.mkdir(parents=True, exist_ok=True)
            roles.write_text(lines, encoding="utf-8")
    else:
        _remove_role_list(roles, roles_base)
    for document in listed:
        (root / document).parent.mkdir(parents=True, exist_ok=True)
    return Applied(removed=plan.removals, moved=moved)


def _remove_role_list(roles: Path, roles_base: Path) -> None:
    roles.unlink(missing_ok=True)
    directory = roles.parent
    while directory == roles_base or directory.is_relative_to(roles_base):
        try:
            directory.rmdir()
        except OSError:  # not empty, or already gone: either way nothing above is ours to remove
            return
        directory = directory.parent
