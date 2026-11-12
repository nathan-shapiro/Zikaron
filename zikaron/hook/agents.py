"""Which of Zikaron's own agents an agent is, by its definition rather than by what it is called.

`design/harness.md` §"Agent teams" is normative. A payload's `agent_type` is the agent's definition
for an ordinary subagent and a tmux teammate, but an in-process teammate's *name*, and any spawn
given a name becomes a teammate when agent teams are on. So an agent with an `agent_id` is named by
the record the harness keeps beside its transcript, and only an agent without one by `agent_type`.
"""

import json
from pathlib import Path
from typing import Final

from zikaron.harness.spec import InstructionPush

#: Copies of the installer's names, which a test holds equal, since importing the installer would
#: put it on every hook's path.
CONSOLIDATOR_AGENT_TYPE: Final = "zikaron-consolidator"
DOCUMENTER_AGENT_TYPE: Final = "zikaron-documenter"
ORCHESTRATOR_AGENT_TYPE: Final = "zikaron-code-orchestrator"

#: The agents an instruction push never reaches: the consolidator, since five headlines chosen over
#: the whole store would be the search D7 withholds from it; the documenter, whose documents must
#: derive from source; and the orchestrator, whose loop no memory changes.
NEVER_PUSHED: Final = frozenset(
    {CONSOLIDATOR_AGENT_TYPE, DOCUMENTER_AGENT_TYPE, ORCHESTRATOR_AGENT_TYPE}
)


def definition(
    instruction: InstructionPush,
    *,
    session_transcript: object,
    agent_id: object,
    agent_type: object,
) -> str | None:
    """The agent's definition, or `None` where it cannot be read.

    With an `agent_id`, the first of the record's definition keys holding a string; without one,
    `agent_type`. `None` for an `agent_id` whose record is missing, unreadable or names no
    definition, which a caller excluding agents must treat as excluded.
    """
    if not isinstance(agent_id, str):
        return agent_type if isinstance(agent_type, str) else None
    if not isinstance(session_transcript, str):
        return None
    record_path = instruction.agent_file(
        Path(session_transcript), agent_id, instruction.record_suffix
    )
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    for key in instruction.definition_keys:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def known_as(
    instruction: InstructionPush | None,
    *,
    session_transcript: object,
    agent_id: object,
    agent_type: object,
) -> str | None:
    """The agent's definition where its record names one, else its `agent_type`.

    For the paths that run before a spawn's record may exist — the start text, the policy, the
    reminder — and so fail toward giving text rather than toward a push.
    """
    if instruction is not None and isinstance(agent_id, str):
        named = definition(
            instruction,
            session_transcript=session_transcript,
            agent_id=agent_id,
            agent_type=agent_type,
        )
        if named is not None:
            return named
    return agent_type if isinstance(agent_type, str) else None
