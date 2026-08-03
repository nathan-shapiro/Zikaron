"""The subagent-suppression check, and this client's `client` envelope.

`architecture.md` §"Subagent sessions — the push hook suppresses itself" is normative for
`is_subagent_session`; §"The request envelope" for `build_envelope`.

Reuses `zikaron.service.envelope.ClientEnvelope` for the envelope's *shape* — one dataclass, one
definition of what a `client` object carries, rather than a second copy of the same four fields —
and `zikaron.core.events.ClientKind` for the wire value `"hook"`. Neither pulls in anything beyond
the standard library (verified directly: importing either does not add `aiosqlite`, `fastembed`,
`sqlite_vec` or `fastmcp` to `sys.modules`), so reusing them here does not compromise this
package's own stdlib-only contract the way reusing `zikaron.service.lifecycle` would — that module
imports `zikaron.service.context`/`zikaron.service.server` for its unrelated `idle_self_stop`
function, and importing it at all pulls in the full model-loading stack regardless of which of its
functions a caller actually wants.
"""

import os

from zikaron.core.events import ClientKind
from zikaron.service.envelope import ClientEnvelope

#: The environment variable both `zikaron-hook` and `zikaron-mcp` read for the `harness` rung of
#: the two-rung session-label ladder (`architecture.md` §"Both clients resolve the same label").
_KIRO_SESSION_ID_VAR = "KIRO_SESSION_ID"

#: The reserved namespace a service-minted label always falls in. `architecture.md`'s client
#: contract: "a client that finds a `zk-`-prefixed value in `KIRO_SESSION_ID` must treat it as
#: absent" — mirrored here exactly as `zikaron.mcp.connection._harness_session_id` already
#: enforces it, so both clients honour the same rule rather than one trusting the environment
#: literally.
_MINTED_PREFIX = "zk-"


def harness_session_id() -> str | None:
    """`KIRO_SESSION_ID` from this process's own environment, or `None` if it is absent **or**
    intrudes on the service's reserved `zk-` namespace.

    `None` here means the bootstrap form: `build_envelope` sends `session_id: null` and the
    service mints one. Under kiro this practically never happens for the hook — `architecture.md`:
    "`zikaron-hook` never bootstraps under kiro: the id is in its payload and in its
    environment" — but the client-side contract holds regardless of harness.
    """
    value = os.environ.get(_KIRO_SESSION_ID_VAR)
    if value is not None and value.startswith(_MINTED_PREFIX):
        return None
    return value


def is_subagent_session(*, env_session_id: str | None, payload_session_id: object) -> bool:
    """Whether this invocation is running inside a subagent session, per
    `architecture.md`'s exact rule: "the hook reads `KIRO_SESSION_ID` from its environment and
    compares it to its payload's `session_id`. When they **differ**, this is a subagent session."

    A pure comparison, deliberately taking both values as already-extracted arguments rather than
    reading the environment or a payload dict itself — the caller (`push.py`, `spawn_warm.py`)
    owns *when* those reads happen (before any RPC, before any other action, per the same
    section's ordering), and this function only states the comparison, so it can be tested against
    every combination of present/absent/matching/differing without touching `os.environ` or
    constructing a payload.

    `payload_session_id` is typed `object` rather than `str | None`: the payload is untrusted JSON
    from kiro's own stdin delivery, and a value that is present but not a string (or not present at
    all) is treated as "no payload session id to differ from" — i.e. not a subagent session by this
    check alone — exactly as `architecture.md` states for the *other* absence case: "when
    `KIRO_SESSION_ID` is absent entirely, it proceeds normally." A malformed payload is a separate
    concern the caller's own JSON handling surfaces as an ordinary failure later, not a reason for
    this pure comparison to raise.

    **When `env_session_id` is `None`, this always returns `False`** — "when... `KIRO_SESSION_ID`
    is absent entirely, it proceeds normally" is unconditional on the payload's own value, so a
    missing environment variable never suppresses a top-level session merely because the payload
    happens to carry some session id.
    """
    if env_session_id is None:
        return False
    return payload_session_id != env_session_id


def build_envelope(*, session_id: str | None, pid: int) -> ClientEnvelope:
    """This request's `client` envelope: the resolved session label (or `None` for the bootstrap
    form), `kind="hook"`, this process's own pid, and no `op_id` — the service mints one per call
    when a client sends none (`zikaron.service.envelope.resolve`), and a single-request process has
    nothing of its own to correlate across calls the way a long-running MCP connection does.
    """
    return ClientEnvelope(session_id=session_id, kind=str(ClientKind.HOOK), pid=pid, op_id=None)
