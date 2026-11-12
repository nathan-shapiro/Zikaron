"""Pending markers: one empty file per agent whose latest instruction may not have been pushed yet.

`design/harness.md` §"Agent teams" is normative for who sets, claims and clears them, and
`architecture.md` §"Paths" for the directory. A marker is named for the session and, for an agent
inside it, the agent; the gate in front of the tool-call hook tests for a name beginning with its
own session's id, so a marker opens that session's gate and no other.

**Claiming is unlinking.** Every hook of a parallel tool batch is its own process, and `unlink`
succeeds for exactly one of them, so an instruction is pushed at most once however many calls race
for its marker.
"""

import contextlib
import os
import re
import stat
from pathlib import Path
from typing import Final

from zikaron.service import paths

#: An in-process agent's marker is cleared by its turn's `SubagentStop`, so one this old was set
#: for a turn that ended without it.
PENDING_TTL_SECONDS: Final = 1_800
#: A session's own marker may wait hours for a tmux teammate's next message, and opens no other
#: session's gate while it does; one this old was left by a session that ended without a tool call.
PENDING_SESSION_TTL_SECONDS: Final = 86_400

#: Between a session's id and an agent's in a marker's name. Neither id contains it.
_SEPARATOR: Final = "."
_SAFE: Final = re.compile(r"[A-Za-z0-9_-]+")


def name(session_id: object, agent_id: object) -> str | None:
    """The marker for this session's own agent, or for `agent_id` inside it; `None` for an id that
    could not safely name a file."""
    if not isinstance(session_id, str) or _SAFE.fullmatch(session_id) is None:
        return None
    if agent_id is None:
        return session_id
    if not isinstance(agent_id, str) or _SAFE.fullmatch(agent_id) is None:
        return None
    return f"{session_id}{_SEPARATOR}{agent_id}"


def mark(store_dir: Path, marker: str) -> None:
    """Set `marker`, refreshing its age if it is set already. Nothing where the store does not
    exist, since a project with no store has nothing to push, and nothing on a failure, since a
    marker missed is a push missed and pull remains."""
    if not store_dir.is_dir():
        return
    directory = paths.instruction_pending_dir(store_dir)
    with contextlib.suppress(OSError):
        with contextlib.suppress(FileExistsError):
            directory.mkdir(mode=0o700)
        if not stat.S_ISDIR(directory.lstat().st_mode):
            return
        target = directory / marker
        os.close(os.open(target, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600))
        os.utime(target, follow_symlinks=False)


def claim(store_dir: Path, marker: str) -> bool:
    """Remove `marker`, and say whether this call is the one that did."""
    try:
        (paths.instruction_pending_dir(store_dir) / marker).unlink()
    except OSError:
        return False
    return True


def sweep(store_dir: Path, *, now: float) -> None:
    """Delete every marker older than its kind's age limit, `now` being a `time.time()` reading."""
    try:
        entries = os.scandir(paths.instruction_pending_dir(store_dir))
    except OSError:
        return
    with entries:
        for entry in entries:
            limit = PENDING_TTL_SECONDS if _SEPARATOR in entry.name else PENDING_SESSION_TTL_SECONDS
            with contextlib.suppress(OSError):
                if now - entry.stat(follow_symlinks=False).st_mtime > limit:
                    Path(entry.path).unlink()
