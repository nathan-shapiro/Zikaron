"""`SubagentStart`: deliver the write policy to a subagent, and nothing else.

`design/harness.md` §Subagents is normative. The spawn trigger fires once per session, so a subagent
would otherwise inherit the memory tools having never seen the write policy at all. This path exists
to close that gap and does nothing more.

**Policy-only, stated because each omission is deliberate.** It does not spawn the warm helper — the
session's own spawn trigger already did, and a second spawn per subagent is pure cost against
nothing. It makes no RPC and opens no socket. It does not consult the session comparison the spawn
and prompt paths make: a subagent is identified here by the agent identity its own payload carries,
which is the exact mechanism the older, session-comparing rule existed to approximate, and the
relationship between a subagent payload's session id and the environment's is not something this
path needs to assume.

**The exclusion is exact, which is the whole reason this trigger is worth having.** The other
harness suppresses *every* subagent because its payload carries no agent identity to discriminate
on. Here the payload names the agent type, so the policy goes to every subagent except the
consolidator — whose policy is its own system prompt, and which must not be handed the primary
agent's write instructions on top of it.
"""

from pathlib import Path

from zikaron.harness import detect
from zikaron.hook import write_policy

#: The agent type whose own system prompt already carries its instructions, and the one subagent
#: this path stays silent for.
#:
#: A guarded copy rather than an import: the canonical declaration lives with the installer that
#: writes the agent config, and importing that module would pull the whole installer onto a
#: critical path that is measured in milliseconds. A test asserts the two agree, which is the same
#: arrangement the request envelope's own copy uses — the test pays the import cost, the hook does
#: not.
CONSOLIDATOR_AGENT_TYPE = "zikaron-consolidator"


def run(*, scope_dir: Path, agent_type: object) -> str | None:
    """Return the write-policy text to deliver to this subagent, or `None` for the consolidator.

    `agent_type` is typed `object` because it arrives as untrusted JSON from the harness's own
    stdin delivery. Anything that is not exactly the consolidator's type — a missing field, a
    non-string, an agent type this build has never heard of — receives the policy, which is the
    safe direction to be wrong in: an agent that holds the memory tools and has not been told the
    write policy is the failure this path exists to prevent, while an agent that receives a policy
    it did not need has merely read a few thousand characters.

    Never raises, for the same reason every other hook path does not: the caller's contract is to
    exit 0 having printed something or nothing, and `resolved_policy_text` absorbs any failure
    beneath it and falls back to the shipped constant.
    """
    if agent_type == CONSOLIDATOR_AGENT_TYPE:
        return None
    # Resolved through the seam rather than assumed to be the one harness that sends this trigger:
    # a path that hard-coded a harness here would be the forked code path the single-implementation
    # rule exists to prevent, however unreachable the other branch looks today.
    return write_policy.resolved_policy_text(scope_dir, spec=detect.current_spec())
