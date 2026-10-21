"""The search reminder: after a search of the project's files, one line naming the code knowledge
that documents what it searched.

`design/code-knowledge.md` §6 is normative, and `architecture.md` §"Degraded modes" for the order
this runs in: the agent's type, the paths the search covered, a listing of the store's knowledge
directory, a connect only to a service already serving, one `knowledge_remind`, and exit 0. It never
starts a service — a reminder is worth no wait — and the service decides whether one is due.

**Fail-open, as the guards are** (`design/guards.md` §6): nothing to remind of, no corpus, no
service and a malformed payload write nothing. A service that answers an error, or a failure once
connecting began, writes one `hook.log` line carrying `LOG_DETAIL` after its kind, so it is told
from a push's.
"""

import contextlib
import os
import time
from pathlib import Path
from typing import Final

from zikaron.core.errors import ZikaronError
from zikaron.core.knowledge.paths import orphan_candidates
from zikaron.harness import detect
from zikaron.harness.spec import HarnessSpec, SearchReminder
from zikaron.hook import connect, envelope, failure, rpc
from zikaron.service import paths

#: The agent types this path is silent for. Copies of the installer's names, which a test holds
#: equal, since importing the installer would put it on every search's path. The documenter takes
#: nothing from a code-knowledge base, and the orchestrator searches no source.
DOCUMENTER_AGENT_TYPE: Final = "zikaron-documenter"
ORCHESTRATOR_AGENT_TYPE: Final = "zikaron-code-orchestrator"
_SILENT_FOR: Final = frozenset({DOCUMENTER_AGENT_TYPE, ORCHESTRATOR_AGENT_TYPE})

#: The most paths one request names: `knowledge_remind`'s bound, a copy a test holds equal to the
#: service's, so a `bounds` refusal is unreachable from what this builds.
PATHS_AT_MOST: Final = 50

#: The whole exchange — connect, `health()`, the request — to a service already serving. A search
#: waits on it, so it is short.
DEADLINE_SECONDS: Final = 1.0

#: The word a reminder's `hook.log` line carries after its kind.
LOG_DETAIL: Final = "remind"


def run(payload: dict[str, object], *, scope_dir: Path, spec: HarnessSpec, pid: int) -> str | None:
    """The line to give the agent after this tool event, or `None` for none.

    Raises nothing it anticipates; `main` suppresses the rest, so the exit is 0 either way.
    """
    reminder = spec.search_reminder
    if reminder is None or payload.get("agent_type") in _SILENT_FOR:
        return None
    searched = _searched(payload, reminder, scope_dir=scope_dir)
    if not searched:
        return None
    store_dir = paths.store_dir(scope_dir)
    if not _holds_a_corpus(store_dir):
        return None
    label = detect.session_label(spec)
    if label is None:
        # A label the service minted for this one request would be a key of its own, due a
        # reminder every time.
        return None
    return _ask(
        store_dir,
        searched=searched[:PATHS_AT_MOST],
        agent_id=_agent_id(payload),
        client_envelope=envelope.build_envelope(session_id=label, pid=pid),
    )


def _searched(
    payload: dict[str, object], reminder: SearchReminder, *, scope_dir: Path
) -> tuple[str, ...]:
    """The absolute paths the search this payload reports covered; empty for no search."""
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return ()
    cwd = payload.get("cwd")
    base = cwd if isinstance(cwd, str) and Path(cwd).is_absolute() else str(scope_dir)
    if tool in reminder.files.tools:
        path = tool_input.get("path")
        written = path if isinstance(path, str) and path else "."
        return (os.path.normpath(Path(base) / Path(written).expanduser()),)
    if tool in reminder.shell.tools:
        command = tool_input.get("command")
        if not isinstance(command, str):
            return ()
        # The guard's parser is imported for a shell call alone, the one that needs it.
        from zikaron.hook import shell_search  # noqa: PLC0415

        return shell_search.searched_paths(command, cwd=base, top=str(scope_dir))
    return ()


def _holds_a_corpus(store_dir: Path) -> bool:
    """Whether the store has any knowledge base's database — a listing, not a store read."""
    try:
        return bool(orphan_candidates(store_dir))
    except OSError:
        return False


def _agent_id(payload: dict[str, object]) -> str | None:
    """The subagent's id, read only beside its type, so the main session's key never carries one."""
    agent_id = payload.get("agent_id")
    if isinstance(payload.get("agent_type"), str) and isinstance(agent_id, str):
        return agent_id
    return None


def _ask(
    store_dir: Path,
    *,
    searched: tuple[str, ...],
    agent_id: str | None,
    client_envelope: envelope.HookEnvelope,
) -> str | None:
    deadline = rpc.HookDeadline.after(DEADLINE_SECONDS, now=time.monotonic())
    hook_log_path = paths.hook_log_path(store_dir)
    try:
        connection = connect.connect_if_serving(
            connect.resolve_sock_path(store_dir), store_db_path=paths.store_db_path(store_dir)
        )
        if connection is None:
            return None
        with contextlib.closing(connection.sock) as sock:
            try:
                return rpc.remind_once(
                    sock,
                    paths=searched,
                    agent_id=agent_id,
                    envelope=client_envelope,
                    deadline=deadline,
                )
            except rpc.NotSentError:
                _record(hook_log_path, "deadline_exceeded")
            except TimeoutError:
                _record(hook_log_path, "unanswered")
    except (connect.HookTransportError, rpc.ServiceRejectionError, ZikaronError) as error:
        kind, code = failure.classify(error)
        _record(hook_log_path, kind, code=code)
    except Exception:
        # Any other failure, by the fixed word, so `hook.log` holds the closed vocabulary rather
        # than an exception's text.
        _record(hook_log_path, "transport")
    return None


def _record(hook_log_path: Path, kind: str, *, code: int | None = None) -> None:
    failure.record_failure(hook_log_path, kind, detail=LOG_DETAIL, code=code)
