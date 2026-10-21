"""`knowledge_remind`: whether a search reached documented code, and the line that says so.

`design/code-knowledge.md` §6 is normative, and `architecture.md` §"Service RPC surface" names the
method. It has no tool, since an agent never asks for its own reminder: the hook calls it after a
search, and it is registered in `dispatch_knowledge.py`'s table beside the knowledge index's other
methods.

It reads the knowledge-base registry and nothing else of the store, and touches no encoder, so it
answers while the embedding model is still loading.
"""

import time
from dataclasses import dataclass

import aiosqlite

from zikaron.core.code_knowledge.reminder import corpora_reached, reminder_text
from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.knowledge import registry
from zikaron.core.store.pool import lease_deadline
from zikaron.service import paths
from zikaron.service.context import ServiceContext
from zikaron.service.envelope import ResolvedEnvelope
from zikaron.service.params import optional_str, require_path_list
from zikaron.service.serialize import RpcResult

#: The configuration key whose seconds an agent goes unreminded after a reminder.
INTERVAL_KEY = "knowledge_reminder_interval"


@dataclass(frozen=True, slots=True)
class RemindResult(RpcResult):
    """`knowledge_remind`'s success shape: `{text}` — the line, or `null` for no reminder."""

    text: str | None

    def as_json(self) -> dict[str, object]:
        return {"text": self.text}


async def knowledge_remind(
    db: aiosqlite.Connection,
    ctx: ServiceContext,
    envelope: ResolvedEnvelope,
    params: dict[str, object],
) -> RemindResult:
    """`knowledge_remind(paths, agent_id?, deadline_at_ms?) -> {text}`.

    The agent is the envelope's session label with `agent_id`, sent for a subagent. A search that
    reaches no documented module moves no time. **Past its caller's own deadline it records no
    reminder**, since the hook stops waiting there and a line nobody read must not hold back the
    next one; that check and the throttle's own run with no `await` between them, so two requests
    for one agent at once yield one line.

    Raises:
        ZikaronError: `BOUNDS` for a malformed `paths` or `agent_id`; `DEADLINE_PASSED` when the
            caller's own deadline passed before the answer was decided.
    """
    searched = require_path_list(params, "paths")
    agent_id = optional_str(params, "agent_id")
    corpora = [knowledge_base.name for knowledge_base in await registry.list_all(db)]
    project = str(paths.scope_of(ctx.store_directory))
    reached = corpora_reached(searched, project=project, corpora=corpora)
    if not reached:
        return RemindResult(text=None)
    deadline = lease_deadline(db)
    if deadline.set_by_caller and deadline.passed():
        raise ZikaronError(ErrorCode.DEADLINE_PASSED, verb="knowledge_remind")
    due = ctx.reminders.take(
        envelope.session_id,
        agent_id,
        now=time.monotonic(),
        interval=ctx.config.get_int(INTERVAL_KEY),
    )
    return RemindResult(text=reminder_text(reached) if due else None)
