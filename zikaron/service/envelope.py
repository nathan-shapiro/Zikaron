"""The resolution preamble: envelope shape, the two-rung label ladder, and `label_source`.

`architecture.md` §"Resolution is a preamble, not a step of the method" is normative. On every
request except `health()`, the service validates the envelope's shape, resolves a non-null
`session_id`, and normalizes the envelope to it — all *before* rung 1 of either validation ladder,
because rung 1 can itself emit `event` rows and every `event` row carries a non-null `session_id`.

**What this module does not do.** It does not read `KIRO_SESSION_ID` — that is the *client's* job
(`zikaron-mcp`/`zikaron-hook`, M10/M11), which reads its own environment and sends whatever it
finds as `client.session_id`. The service side of the two-rung ladder is simpler than the whole
ladder, precisely because the harness-agreement half of it is a client-side fact this module
never sees: given a conforming string, pass it through; given `null` or a malformed value, mint
`zk-<uuid4>`. `label_source` is then a pure function of the label alone, computed here and stored
nowhere, exactly as `architecture.md` requires.
"""

import uuid
from dataclasses import dataclass
from typing import Final

from zikaron.core.errors import ErrorCode, ZikaronError
from zikaron.core.events import ClientKind

#: `architecture.md`: "a string of ≤128 chars with no control characters, or explicit `null` for
#: the bootstrap form." Both halves of that sentence are enforced here.
_SESSION_ID_MAX_CHARS: Final = 128

#: The reserved namespace a service-minted label always falls in — load-bearing rather than
#: cosmetic, since it is how the service recognizes its own label coming back from a client and
#: therefore the entire mechanism `label_source` rests on.
_MINTED_PREFIX: Final = "zk-"

_KNOWN_CLIENT_KINDS: Final = frozenset(str(kind) for kind in ClientKind)


@dataclass(frozen=True, slots=True)
class ClientEnvelope:
    """One request's `client` object, exactly as the transport carried it — before resolution.

    `session_id` is `None` for the bootstrap form and a string for the resolved form; nothing
    later in this module's pipeline may treat a non-conforming string as equivalent to `None`, so
    the shape check below is what decides which of the two forms a request is in.
    """

    session_id: str | None
    kind: str
    pid: int
    op_id: str | None


@dataclass(frozen=True, slots=True)
class ResolvedEnvelope:
    """An envelope after the preamble: a session_id that is never null, and its derived source.

    Constructing one *is* having run the ladder — there is no way to hold a `ResolvedEnvelope`
    whose `session_id` is null or malformed, which is what lets every layer downstream of the
    preamble assume a well-formed label rather than re-checking it.
    """

    session_id: str
    kind: str
    pid: int
    op_id: str


#: The C0 control range plus DEL — the exact set `_has_control_characters` refuses in a
#: `session_id`, named rather than left as bare literals at the comparison site.
_CONTROL_RANGE_MAX = 0x1F
_DEL = 0x7F


def _has_control_characters(value: str) -> bool:
    return any(ord(char) <= _CONTROL_RANGE_MAX or ord(char) == _DEL for char in value)


def _conforms(session_id: str) -> bool:
    """Whether a non-null `session_id` satisfies the shape contract on its own terms.

    A string that fails this is treated exactly like `null` (§"the envelope is normalized"), never
    rejected outright — `architecture.md`: "a malformed label carries no information," so the
    service mints rather than raising `bounds` over a label whose only job is to be an audit
    string.
    """
    return 0 < len(session_id) <= _SESSION_ID_MAX_CHARS and not _has_control_characters(session_id)


def _reject_field(field: str, *, limit: object, actual: object) -> ZikaronError:
    return ZikaronError(ErrorCode.BOUNDS, field=field, limit=limit, actual=actual)


def parse_envelope(raw: object) -> ClientEnvelope:
    """The `client` object of a request's params, as a validated `ClientEnvelope`.

    This is rung 1 of the preamble — shape only, no store access and no label resolution yet.
    `pid` is checked here because `architecture.md` requires it "rejected `bounds`, never
    defaulted": half of the consolidation owner identity, so an absent or unparseable one must
    fail loudly rather than silently collapse ownership back to the session alone.

    Raises:
        ZikaronError: `BOUNDS` if `raw` is not an object; if `session_id` is present but neither a
            string nor `null`; if `kind` is missing or not one of the known client kinds; or if
            `pid` is missing, not an integer, or not a positive integer.
    """
    if not isinstance(raw, dict):
        raise _reject_field("client", limit="an object", actual=type(raw).__name__)

    session_id_raw = raw.get("session_id")
    if session_id_raw is not None and not isinstance(session_id_raw, str):
        raise _reject_field(
            "client.session_id", limit="a string or null", actual=type(session_id_raw).__name__
        )

    kind = raw.get("kind")
    if not isinstance(kind, str) or kind not in _KNOWN_CLIENT_KINDS:
        raise _reject_field("client.kind", limit=sorted(_KNOWN_CLIENT_KINDS), actual=kind)

    pid_raw = raw.get("pid")
    # `bool` is an `int` subclass, and a request sending `true` for `pid` must not silently
    # become pid 1 — the same exactness `ConfigKey.accepts` enforces for a configured value.
    if not isinstance(pid_raw, int) or isinstance(pid_raw, bool) or pid_raw < 1:
        raise _reject_field("client.pid", limit="a positive integer", actual=pid_raw)

    op_id_raw = raw.get("op_id")
    if op_id_raw is not None and not isinstance(op_id_raw, str):
        raise _reject_field(
            "client.op_id", limit="a string or absent", actual=type(op_id_raw).__name__
        )

    return ClientEnvelope(session_id=session_id_raw, kind=kind, pid=pid_raw, op_id=op_id_raw)


def resolve(envelope: ClientEnvelope) -> ResolvedEnvelope:
    """Rung 2 of the preamble: a non-null `session_id`, and `op_id` minted if the client sent none.

    Touches no table, per `architecture.md`: "resolution reads the client's own environment on the
    client side and, on the service side, either accepts the envelope's label or mints one." A
    `session_id` that is present but fails shape validation is treated identically to `None` — the
    service mints, because `architecture.md` states plainly that a malformed label carries no
    information worth rejecting the call over.
    """
    session_id = envelope.session_id
    resolved_session_id = (
        session_id if session_id is not None and _conforms(session_id) else _mint_session_id()
    )
    op_id = envelope.op_id if envelope.op_id is not None else _mint_op_id()
    return ResolvedEnvelope(
        session_id=resolved_session_id, kind=envelope.kind, pid=envelope.pid, op_id=op_id
    )


def _mint_session_id() -> str:
    return f"{_MINTED_PREFIX}{uuid.uuid4()}"


def _mint_op_id() -> str:
    return str(uuid.uuid4())


def label_source(session_id: str) -> str:
    """`"minted"` if `session_id` is in the service's reserved namespace, else `"harness"`.

    A pure function of the label alone, computed wherever wanted and stored nowhere —
    `architecture.md` §"`label_source` is derived, not stored": "there is exactly one source of
    truth and nothing to drift."
    """
    return "minted" if session_id.startswith(_MINTED_PREFIX) else "harness"
