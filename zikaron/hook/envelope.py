"""The session-divergence check, and this client's `client` envelope.

`architecture.md` §"Subagent sessions — the push hook suppresses itself" is normative for
`sessions_diverge`; §"The request envelope" for `build_envelope`.

**States the envelope's four fields locally rather than importing them, and the reason is
measured.** This module originally reused `zikaron.service.envelope.ClientEnvelope` and
`zikaron.core.events.ClientKind` on the argument that both are stdlib-only, so reuse cost nothing —
verified at the time, and wrong about the cost that matters. Stdlib-only is not the same as cheap:
measured on this machine, importing `zikaron.core.events` alone costs **28 ms** over a
socket/json/os/pathlib/subprocess floor and `zikaron.service.envelope` **34 ms** (it pulls in
`core.events`, `core.errors` and `dataclasses`, whose own `inspect` import is most of it), against
a whole-process hook budget of ~48 ms without them and ~68 ms with. This client runs **once per
user message**, so that is a per-turn tax on the exact critical path the design's argument for
keeping the hook thin is about — and `architecture.md` §Components quotes ~20 ms for this client, a
figure the reuse quietly tripled. `dataclasses` is avoided for the same reason `logging` is: a
`NamedTuple` gives the same frozen, typed, four-field value for no measurable import.

Two copies of a wire contract is exactly the drift this corpus keeps finding, so the copy is
**guarded rather than trusted**: `tests/test_hook_envelope.py` asserts this module's field names and
its `kind` literal against `ClientEnvelope`'s own fields and `ClientKind.HOOK.value`, which is the
same drift-guard shape `tests/design_tables.py` uses for the design's own tables. The test pays the
import
cost; the hook does not.
"""

from typing import NamedTuple

#: The wire value for this client's `client.kind`, i.e. `ClientKind.HOOK.value`. A literal here, an
#: enum there, and a test that they agree — see this module's docstring.
CLIENT_KIND = "hook"


class HookEnvelope(NamedTuple):
    """This client's `client` envelope: the four fields `architecture.md` §"The request envelope"
    states, in the shape `zikaron.service.envelope.ClientEnvelope` declares them.

    A `NamedTuple` rather than a frozen dataclass purely for import cost (module docstring); it is
    immutable and typed either way. `as_client_object()` is the one place the wire spelling of these
    fields is written, so `rpc.py` composes a request without restating them.
    """

    session_id: str | None
    kind: str
    pid: int
    op_id: str | None

    def as_client_object(self) -> dict[str, object]:
        """The `client` member of an outgoing request's `params`."""
        return {
            "session_id": self.session_id,
            "kind": self.kind,
            "pid": self.pid,
            "op_id": self.op_id,
        }


def sessions_diverge(*, env_session_id: str | None, payload_session_id: object) -> bool:
    """Whether the harness's session variable and this payload's `session_id` name two sessions,
    per `architecture.md` §"Subagent sessions — the push hook suppresses itself".

    Neither harness fires a spawn or prompt hook for a subagent session, so the two are equal in
    every hook either fires, and a divergence means the harness was misdetected: an inherited
    variable from an enclosing session. `tripwire.py` records that; the caller prints nothing.

    A pure comparison of values the caller has already read, so the caller owns *when* those reads
    happen — before any RPC — and every combination can be tested without touching `os.environ`.

    **When `env_session_id` is `None`, this is always `False`**: an absent variable is no evidence
    of another session, so it never suppresses a push. A payload value that is absent or not a
    string differs from any present variable, and suppresses: the payload is untrusted JSON, and a
    hook that cannot tell whose session it is in says nothing.
    """
    if env_session_id is None:
        return False
    return payload_session_id != env_session_id


def build_envelope(*, session_id: str | None, pid: int) -> HookEnvelope:
    """This request's `client` envelope: the resolved session label (or `None` for the bootstrap
    form), `kind="hook"`, this process's own pid, and no `op_id` — the service mints one per call
    when a client sends none (`zikaron.service.envelope.resolve`), and a single-request process has
    nothing of its own to correlate across calls the way a long-running MCP connection does.
    """
    return HookEnvelope(session_id=session_id, kind=CLIENT_KIND, pid=pid, op_id=None)
