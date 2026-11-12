"""Push on an agent's first tool call after an instruction: a teammate's message, a subagent's task.

`design/harness.md` §"Agent teams" is normative, and `architecture.md` §"Degraded modes" for this
path's chain. No hook an agent fires as an instruction reaches it can carry a push, so the start
and idle hooks mark the agent pending and its next tool call claims the mark, reads the instruction
from its transcript and pushes the prompt hook's block for it.

**It never starts a service and never tells the agent of a failure.** A tool call waits on this,
and a push lost is recoverable by pull; the prompt path's notice asks the agent to tell the
operator, which an agent inside a session cannot. So every failure is one `hook.log` line carrying
`LOG_DETAIL`, told from the prompt path's — and since the marker is claimed before anything else, a
service absent or still loading writes one too, where the reminder's silence would leave the lost
push no trace.
"""

import contextlib
import time
from pathlib import Path
from typing import Final

from zikaron.core.errors import ZikaronError
from zikaron.harness import detect
from zikaron.harness.spec import HarnessSpec, HookEvent, InstructionPush
from zikaron.hook import (
    agents,
    connect,
    envelope,
    failure,
    instruction,
    instruction_markers,
    push,
    rpc,
    session_relay,
    tripwire,
)
from zikaron.service import paths

#: The word this path's `hook.log` lines carry after their kind.
LOG_DETAIL: Final = "instruction"

#: What `hook.log` records for an instruction the transcript does not hold in a shape measured.
INSTRUCTION_UNREAD: Final = "instruction_unread"

#: What `hook.log` records for a claimed marker with no service to push from.
NOT_SERVING: Final = "not_serving"

#: The whole exchange to a service already serving; a tool call waits on it.
DEADLINE_SECONDS: Final = 2.0

#: What the push tells the service it answers, so the service opens no turn for it.
OCCASION: Final = "instruction"

#: The `SessionStart` source of a session's first start, the one a tmux teammate's spawn is.
_FIRST_START: Final = "startup"


def mark(
    event: HookEvent, payload: dict[str, object], *, scope_dir: Path, spec: HarnessSpec
) -> None:
    """Set or clear this event's marker, where this harness has the path at all."""
    if spec.instruction_push is None:
        return
    agent_id = payload.get("agent_id")
    if event is HookEvent.SPAWN and payload.get("source") != _FIRST_START:
        return
    if event in (HookEvent.SPAWN, HookEvent.TEAMMATE_IDLE) and agent_id is not None:
        # An in-process teammate's idle carries its id, and its next message fires
        # `SubagentStart`, which marks it then.
        return
    if event in (HookEvent.SUBAGENT_START, HookEvent.SUBAGENT_STOP) and agent_id is None:
        # Without its id a subagent's event would name the session's own marker, a tmux
        # teammate's waiting message.
        return
    marker = instruction_markers.name(payload.get("session_id"), agent_id)
    if marker is None:
        return
    store_dir = paths.store_dir(scope_dir)
    if event is HookEvent.SPAWN:
        # A settings file from before the gate sets markers no tool call claims, so the sweep
        # cannot wait for one.
        instruction_markers.sweep(store_dir, now=time.time())
    if event is HookEvent.SUBAGENT_STOP:
        instruction_markers.claim(store_dir, marker)
    else:
        instruction_markers.mark(store_dir, marker)


def run(payload: dict[str, object], *, scope_dir: Path, spec: HarnessSpec, pid: int) -> str | None:
    """The block to give the agent before this tool call, or `None` for none. Raises nothing it
    anticipates; `main` suppresses the rest, so the exit is 0 either way."""
    push_spec = spec.instruction_push
    if push_spec is None:
        return None
    marker = instruction_markers.name(payload.get("session_id"), payload.get("agent_id"))
    if marker is None:
        return None
    store_dir = paths.store_dir(scope_dir)
    claimed = instruction_markers.claim(store_dir, marker)
    instruction_markers.sweep(store_dir, now=time.time())
    if not claimed:
        return None
    label = detect.session_label(spec, relay_dir=session_relay.relay_dir())
    if envelope.sessions_diverge(
        env_session_id=label, payload_session_id=payload.get("session_id")
    ):
        tripwire.record_misdetection(scope_dir=scope_dir)
        return None
    found = _instruction(payload, push_spec, hook_log_path=paths.hook_log_path(store_dir))
    if found is None:
        return None
    return _surface(
        store_dir,
        prompt=found,
        client_envelope=envelope.build_envelope(session_id=label, pid=pid),
        spec=spec,
    )


def _instruction(
    payload: dict[str, object], push_spec: InstructionPush, *, hook_log_path: Path
) -> str | None:
    """The claimed agent's instruction, or `None` where it is not pushed — never to an agent whose
    definition is excluded or, with an `agent_id`, cannot be read, since the consolidator is the
    one wrong answer D7 cannot absorb. A session's own agent with no type is decided by its
    transcript alone: a tmux teammate spawned with none is served, the main session is not."""
    agent_id = payload.get("agent_id")
    session_transcript = payload.get("transcript_path")
    named = agents.definition(
        push_spec,
        session_transcript=session_transcript,
        agent_id=agent_id,
        agent_type=payload.get("agent_type"),
    )
    if named is None and isinstance(agent_id, str):
        _record(hook_log_path, INSTRUCTION_UNREAD)
        return None
    if named in agents.NEVER_PUSHED or not isinstance(session_transcript, str):
        return None
    if isinstance(agent_id, str):
        transcript = push_spec.agent_file(
            Path(session_transcript), agent_id, push_spec.transcript_suffix
        )
    else:
        transcript = Path(session_transcript)
    found = instruction.latest(transcript, push_spec, main_shaped=not isinstance(agent_id, str))
    if isinstance(found, instruction.Unread):
        _record(hook_log_path, INSTRUCTION_UNREAD)
        return None
    return found


def _surface(
    store_dir: Path, *, prompt: str, client_envelope: envelope.HookEnvelope, spec: HarnessSpec
) -> str | None:
    deadline = rpc.HookDeadline.after(DEADLINE_SECONDS, now=time.monotonic())
    hook_log_path = paths.hook_log_path(store_dir)
    try:
        connection = connect.connect_if_serving(
            connect.resolve_sock_path(store_dir), store_db_path=paths.store_db_path(store_dir)
        )
        if connection is None:
            _record(hook_log_path, NOT_SERVING)
            return None
        with contextlib.closing(connection.sock) as sock:
            if not connection.health.model_loaded:
                _record(hook_log_path, push.STARTING)
                return None
            try:
                block = rpc.surface_once(
                    sock,
                    prompt=prompt,
                    limit=push.SURFACE_LIMIT,
                    envelope=client_envelope,
                    deadline=deadline,
                    occasion=OCCASION,
                )
            except rpc.NotSentError:
                _record(hook_log_path, "deadline_exceeded")
                return None
            except TimeoutError:
                _record(hook_log_path, "unanswered")
                return None
            if spec.exceeds_injection_budget(block):
                _record(hook_log_path, push.PUSH_OVERSIZE)
            # Nothing eligible renders as the empty string, which the structured channel would
            # still wrap as an envelope.
            return block or None
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
