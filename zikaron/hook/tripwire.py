"""The one signal that this process misdetected its harness.

A process tree running under an enclosing session of a marked harness inherits that harness's
marker and its session variable. The root failure is **misdetection** — the wrong channel table and
the wrong injection budget follow from it, not only a stale session label — and link coverage
cannot see it: both clients read the environment by construction, so both read the same stale
value, they agree, and coverage reads as healthy while the inner session's work is attributed to
the outer, live one.

**Under both harnesses a hook's payload and environment carry one session id**, since neither fires
a spawn or prompt hook for a subagent session (`design/harness.md` §"Subagents"). So a divergence is
a misdetection wherever it is seen, and this records it wherever it is seen.

**On that divergence the hook prints nothing and makes no RPC**, which the callers own and this
module does not. Making no call is what delivers the reasoning, not merely printing nothing: a push
resolved under a stale label would be injected into — and counted against — a different, live
session's instrument stream, and the surfacing event is emitted by the service, so a call made but
not printed would corrupt the instrument anyway. A lost push is recoverable through pull, the arm
that depends on no hook at all.
"""

import contextlib
from pathlib import Path

from zikaron.hook import failure
from zikaron.service import paths

#: The one log kind this module writes. Named as its own fixed label so `hook.log`'s vocabulary
#: stays closed — every line in that file is a fixed kind and an optional wire error code, never
#: prompt or memory content.
SESSION_ENV_MISMATCH = "session_env_mismatch"


def record_misdetection(*, scope_dir: Path) -> None:
    """Write one `session_env_mismatch` line for the divergence the caller just observed.

    Called on the suppression path of a hook that has already decided to print nothing, so it must
    never raise: the caller's guarantee is that it exits quietly, and a tripwire that turned a
    silent suppression into a crash would cost more than the signal it buys. Best-effort as a
    whole rather than per-step, so a failure while deriving the log path is swallowed exactly like
    a failure while writing to it.
    """
    with contextlib.suppress(Exception):
        store_dir = paths.store_dir(scope_dir)
        failure.record_failure(paths.hook_log_path(store_dir), SESSION_ENV_MISMATCH)
