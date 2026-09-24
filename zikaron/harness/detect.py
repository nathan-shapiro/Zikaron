"""Which harness is running this process, and what its session label is.

The two questions a client asks before anything else. `design/harness.md` §"Detection,
session identity, and the nesting limit" is normative.
"""

import os
from typing import Final

from zikaron.harness.spec import SPECS, Harness, HarnessSpec

#: The namespace the service mints its own labels in. A client that finds a value in this namespace
#: in a harness's session variable must treat it as absent and send the bootstrap form, because the
#: prefix is how the service tells its own labels from a harness's — a distinction that is only
#: truthful if every client honours it rather than forwarding whatever the environment holds.
#: Applied to **whichever** harness's variable wins, so no harness can claim a minted label under
#: either name.
_MINTED_PREFIX = "zk-"


def _fallback_harness() -> Harness:
    """The harness detected by the *absence* of every marker.

    Derived from the table rather than named here, so the fallback cannot silently disagree with
    the spec that declares itself unmarked. Exactly one spec may be unmarked: none would make
    detection undefined when no marker is set, and two would make it ambiguous.
    """
    unmarked = [spec.harness for spec in SPECS.values() if spec.marker_variable is None]
    if len(unmarked) != 1:
        message = f"exactly one harness must be detected by absence of a marker, found {unmarked}"
        raise ValueError(message)
    return unmarked[0]


FALLBACK: Final = _fallback_harness()


def current_harness() -> Harness:
    """Which harness spawned this process, by marker variable and nothing cleverer.

    **A marker counts as present only when it is set to a non-empty value**, which is the same
    reading `session_label` gives an empty session variable: set-to-nothing is not set. An empty
    value is no evidence that this harness spawned anything, and detection is the one decision every
    other harness-varying value hangs off — a misdetection applies the wrong channel table and the
    wrong injection budget as well as the wrong session variable — so it takes the conservative
    reading.

    The asymmetry that does remain is narrower than emptiness: a *non-empty* session value is
    forwarded as the label it claims to be, checked only against the service's reserved namespace,
    while a marker is never read for more than its presence.

    When several markers are somehow set at once the first in declaration order wins. That cannot
    arise while only one harness is marked; it is stated so the outcome is deterministic rather
    than incidental.

    **A process tree running under an enclosing session of a marked harness inherits that marker
    and is misdetected.** The known remedy, should it ever bite, needs no new mechanism: the hook
    already holds its payload's own `session_id`, so it can select whichever harness's variable
    actually equals it and detect by agreement instead. Recorded here so it does not have to be
    rediscovered.
    """
    for spec in SPECS.values():
        if spec.marker_variable is not None and os.environ.get(spec.marker_variable):
            return spec.harness
    return FALLBACK


def current_spec() -> HarnessSpec:
    """The full table row for the harness running this process."""
    return SPECS[current_harness()]


def session_label(spec: HarnessSpec) -> str | None:
    """The `harness` rung of the two-rung session-label ladder: this harness's own session variable,
    or `None` when it is absent, **empty**, or intrudes on the service's reserved minted namespace.

    `None` means the bootstrap form — send `session_id: null` and adopt the label the service
    mints. Both clients resolve through here, so a hook and an MCP server in one session speak as
    one session under either harness, which is what keeps linked sessions, link coverage, the two
    cross-client signals and the per-session recall instrument computable.

    **An empty value is absence, matching the service's own definition of a label** rather than
    being forwarded for the service to reject. The two must agree, because a client-side consumer
    acts on this value before any request is made: the subagent-suppression check compares it to
    the payload's session id, so an exported-but-empty variable would differ from every real
    payload id and silently suppress every top-level push — no output, and under the harness that
    logs divergence, one tripwire line per turn for a store that is working perfectly.
    """
    value = os.environ.get(spec.session_variable)
    if not value or value.startswith(_MINTED_PREFIX):
        return None
    return value
