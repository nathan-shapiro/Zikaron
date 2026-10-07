"""The re-read nudge: `design/edit-guards.md` §4.

After each successful edit of an authored file, a statement that it has not been re-read, with
the edited line ranges where the result carries them. It never blocks.

| Edit | Nudge |
|---|---|
| `Edit` of `/home/u/proj/a.md`, one hunk at new lines 12 to 18 | yes, `(lines 12-18)` |
| `Write` whose result `type` is `"update"`, or carries no `type` | yes |
| `Write` whose result `type` is `"create"` — a new file has no surroundings | no |
| `NotebookEdit` — its path is `notebook_path`, and it has no patch | yes, without lines |
| any edit of a scratch path (§3.3) | no |

>>> here = Location(cwd="/home/u/proj")
>>> patch = {"structuredPatch": [{"newStart": 12, "newLines": 7}]}
>>> reread_text("Edit", {"file_path": "/home/u/proj/a.md"}, patch, here)[:50]
'`/home/u/proj/a.md` was edited (lines `12-18`) and'
>>> reread_text("Write", {"file_path": "/home/u/proj/new.md"}, {"type": "create"}, here) is None
True
"""

from collections.abc import Mapping
from typing import Final, TypeGuard

from zikaron.guard.messages import reread_nudge
from zikaron.guard.scratch import Location

_NOTEBOOK_TOOL: Final = "NotebookEdit"
_WRITE_TOOL: Final = "Write"


def reread_text(
    tool: str, tool_input: Mapping[str, object], result: Mapping[str, object], location: Location
) -> str | None:
    """The nudge for one edit, or `None` when it gets none — including when it names no path."""
    path = tool_input.get("notebook_path" if tool == _NOTEBOOK_TOOL else "file_path")
    if not isinstance(path, str) or not path:
        return None
    if tool == _WRITE_TOOL and result.get("type") == "create":
        return None
    if location.is_scratch(path):
        return None
    return reread_nudge(path, edited_ranges(result.get("structuredPatch")))


def edited_ranges(patch: object) -> tuple[tuple[int, int], ...] | None:
    """Each hunk's new-side inclusive line range, or `None` for anything but a non-empty list of
    hunks each carrying integer `newStart` and `newLines` — omitted, never guessed.

    >>> edited_ranges([{"newStart": 3, "newLines": 1}, {"newStart": 40, "newLines": 0}])
    ((3, 3), (40, 40))
    >>> edited_ranges([{"newStart": 3}]) is None
    True
    """
    if not isinstance(patch, list) or not patch:
        return None
    ranges: list[tuple[int, int]] = []
    for hunk in patch:
        start = hunk.get("newStart") if isinstance(hunk, dict) else None
        lines = hunk.get("newLines") if isinstance(hunk, dict) else None
        if not _is_count(start) or not _is_count(lines):
            return None
        ranges.append((start, start + max(lines, 1) - 1))
    return tuple(ranges)


def _is_count(value: object) -> TypeGuard[int]:
    # `bool` is an `int` subclass, and `True` is no line number.
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
