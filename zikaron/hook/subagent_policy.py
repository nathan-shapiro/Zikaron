"""`SubagentStart`'s policy half: deliver the write policy to a subagent. The instruction marker the
trigger also sets is `instruction_push.mark`'s, called from `main.py`.

`design/harness.md` §Subagents is normative. The spawn trigger fires once per session, so a subagent
would otherwise inherit Zikaron's tools having never seen the write policy at all. This path exists
to close that gap.

**Policy-only, stated because each omission is deliberate.** It does not spawn the warm helper — the
session's own spawn trigger already did, and a second spawn per subagent is pure cost against
nothing. It makes no RPC and opens no socket. It does not consult the session comparison the spawn
and prompt paths make: a subagent is identified here by the agent identity its own payload carries,
which is the exact mechanism the older, session-comparing rule existed to approximate, and the
relationship between a subagent payload's session id and the environment's is not something this
path needs to assume.

**The exclusion is exact, which is the whole reason this trigger is worth having.** The payload
names the agent, and the harness's record of it names its definition (`agents.known_as`), so the
policy goes to every subagent except the consolidator — whose policy is its own system prompt, and
which must not be handed the primary agent's write instructions on top of it.
"""

from pathlib import Path

from zikaron.harness import detect
from zikaron.hook import agents, write_policy
from zikaron.hook.agents import CONSOLIDATOR_AGENT_TYPE

__all__ = ["CONSOLIDATOR_AGENT_TYPE", "run"]


def run(*, scope_dir: Path, known_as: str | None) -> str | None:
    """Return the write-policy text to deliver to this subagent, or `None` for the consolidator.

    `known_as` is `agents.known_as`'s answer. Anything that is not exactly the consolidator — no
    name at all, an agent this build has never heard of — receives a policy, which is the safe
    direction to be wrong in: an agent that holds the memory write verbs and has not been told the
    write policy is the failure this path exists to prevent, while an agent that receives a policy
    it did not need has merely read a few thousand characters. The pushed-agent text goes to every
    agent the instruction push reaches, and the subagent text to the rest.

    Never raises, for the same reason every other hook path does not: the caller's contract is to
    exit 0 having printed something or nothing, and `resolved_policy_text` absorbs any failure
    beneath it and falls back to the shipped constant.
    """
    if known_as == CONSOLIDATOR_AGENT_TYPE:
        return None
    # Resolved through the seam rather than assumed to be the one harness that sends this trigger:
    # a path that hard-coded a harness here would be the forked code path the single-implementation
    # rule exists to prevent, however unreachable the other branch looks today.
    spec = detect.current_spec()
    pushed = spec.instruction_push is not None and known_as not in agents.NEVER_PUSHED
    return write_policy.resolved_policy_text(
        scope_dir,
        spec=spec,
        default=(
            write_policy.PUSHED_AGENT_WRITE_POLICY_PROMPT
            if pushed
            else write_policy.SUBAGENT_WRITE_POLICY_PROMPT
        ),
    )
