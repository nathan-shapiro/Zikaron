"""The one signal that this process misdetected its harness.

A process tree running under an enclosing session of a marked harness inherits that harness's
marker and its session variable. The root failure is **misdetection** — the wrong channel table and
the wrong injection budget follow from it, not only a stale session label — and link coverage
cannot see it: both clients read the environment by construction, so both read the same stale
value, they agree, and coverage reads as healthy while the inner session's work is attributed to
the outer, live one.

**Why the scoping is load-bearing rather than tidy.** The naive rule — log whenever the payload's
session id differs from the environment's — is the *identical* predicate as
`envelope.is_subagent_session`. Under a harness that fires its ordinary hooks for subagent sessions,
that divergence is the routine, expected case, so an unscoped tripwire would fire on every subagent
turn: it would drown the signal and pollute a log whose whole value is a closed vocabulary of
failure kinds. So the tripwire fires only under a harness where payload and environment are
invariantly equal, and that property travels as a field on the harness spec rather than as an
identity test against a particular harness here.

**On that divergence the hook prints nothing and makes no RPC**, which the callers own and this
module does not. Making no call is what delivers the reasoning, not merely printing nothing: a push
resolved under a stale label would be injected into — and counted against — a different, live
session's instrument stream, and the surfacing event is emitted by the service, so a call made but
not printed would corrupt the instrument anyway. A lost push is recoverable through pull, the arm
that depends on no hook at all.
"""

import contextlib
from pathlib import Path

from zikaron.harness.spec import HarnessSpec
from zikaron.hook import failure
from zikaron.service import paths

#: The one log kind this module writes. Named as its own fixed label so `hook.log`'s vocabulary
#: stays closed — every line in that file is a fixed kind and an optional wire error code, never
#: prompt or memory content.
SESSION_ENV_MISMATCH = "session_env_mismatch"


def record_if_misdetected(*, spec: HarnessSpec, scope_dir: Path) -> None:
    """Write one `session_env_mismatch` line, if this harness is one where the divergence the
    caller just observed means a misdetection rather than a subagent.

    Called on the suppression path of a hook that has already decided to print nothing, so it must
    never raise: the caller's guarantee is that it exits quietly, and a tripwire that turned a
    silent suppression into a crash would cost more than the signal it buys. Best-effort as a
    whole rather than per-step, so a failure while deriving the log path is swallowed exactly like
    a failure while writing to it.
    """
    if spec.fires_hooks_for_subagent_sessions:
        return
    with contextlib.suppress(Exception):
        store_dir = paths.store_dir(scope_dir)
        failure.record_failure(paths.hook_log_path(store_dir), SESSION_ENV_MISMATCH)
