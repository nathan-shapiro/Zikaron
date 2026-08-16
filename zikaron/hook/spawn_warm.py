"""`agentSpawn`: print the write policy, spawn the detached warm helper, never fail.

`architecture.md` §"Warming" is normative: "the hook process prints the write policy — static
text, no RPC, so it can never fail — and spawns a detached warm helper, then exits." The split
matters, and the section says why: "the `agentSpawn` hook talks to the service" and "the
`agentSpawn` path makes no RPC" cannot both describe one process, so this module's own body makes
no socket call at all — it prints a constant string and asks the OS to start a *different*
process, `zikaron.hook.warm_helper`, which does the work that can fail.

§"Subagent sessions" applies here identically to `push.py`: "When they **differ**, this is a
subagent session and the hook **prints nothing and exits 0** — for `userPromptSubmit` *and*
`agentSpawn`."
"""

import contextlib
import subprocess
import sys
from pathlib import Path

from zikaron.harness import detect
from zikaron.hook import connect, envelope, tripwire, write_policy
from zikaron.service import paths


def run(*, cwd: Path, payload_session_id: object) -> str | None:
    """Return the write-policy text to print, or `None` in a subagent session — and, as a side
    effect on the non-subagent path, best-effort spawn the detached warm helper.

    Never raises: the only real action on the critical path is holding a string constant, and the
    spawn is deliberately best-effort — a `subprocess.Popen` failure here (a missing interpreter,
    an unreadable working directory) is caught and produces no output change at all, since
    `architecture.md` gives the warm helper no observable effect on this hook's own behaviour one
    way or the other. It exists purely to make the *next* `userPromptSubmit` warmer than it would
    otherwise be; failing to start it changes nothing about what `agentSpawn` itself prints.

    The one part that is not a bare constant is the operator's optional
    `.zikaron/write-policy.md` override (`write_policy.read_policy`), and it is read inside the same
    kind of whole-body guard as the spawn — so the never-fail property survives even a reader that
    raises for a reason its own six documented conditions did not anticipate: this function still
    returns the shipped text.
    """
    spec = detect.current_spec()
    env_session_id = detect.session_label(spec)
    if envelope.is_subagent_session(
        env_session_id=env_session_id, payload_session_id=payload_session_id
    ):
        tripwire.record_if_misdetected(spec=spec, cwd=cwd)
        return None
    _spawn_warm_helper_best_effort(cwd)
    return write_policy.resolved_policy_text(cwd, spec=spec)


def _spawn_warm_helper_best_effort(cwd: Path) -> None:
    """Best-effort, whole-operation: path derivation and the spawn itself are both allowed to
    fail with no effect on what `run()` returns. Wrapping only the `Popen` call itself in
    `contextlib.suppress(OSError)` would leave path derivation (`resolve_sock_path`'s own
    `Path.resolve()`, which can raise on a symlink loop) unguarded — a failure there would
    propagate straight past this function, past `run()` (which has no `try` of its own), and into
    `main.py`'s own outermost catch-all, which for `agentSpawn` would then suppress the
    **write-policy print itself**, not merely the warm-up this function exists to attempt.
    Catching a genuine `Exception` around the whole body, not a narrower list, is what keeps that
    guarantee true regardless of which step inside it fails.
    """
    with contextlib.suppress(Exception):
        store_dir = paths.store_dir(cwd)
        sock_path = connect.resolve_sock_path(store_dir)
        command = [
            sys.executable,
            "-m",
            "zikaron.hook.warm_helper",
            str(sock_path),
            str(store_dir),
        ]
        subprocess.Popen(  # noqa: S603 — a fixed argv this process itself constructed, not
            # built from request or payload data.
            command,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
