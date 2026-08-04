"""`userPromptSubmit`: suppress, connect once, ask for the push block, print or relay a failure.

`architecture.md` §"Degraded modes" is normative for the whole sequence, and §"Subagent sessions"
for step 0. Every branch below reaches exactly one of three observable outcomes, and every one
exits 0: print `surface`'s text; print nothing (a suppressed subagent turn — not a failure); or
print a short, model-facing instruction asking the agent to relay the failure to the operator.
Every path, including an exception this module did not anticipate, reaches one of those three
rather than propagating: `run()` is the one function in this package that must never let an
exception escape uncaught, because a caller (`main.py`) treats a raised exception here identically
to any other unanticipated failure, with no carve-out for "unless something unexpected happened."

**On a failure, this always exits 0 and uses stdout, never stderr, to notify anyone at all —
because that is the one channel confirmed to reach the model on the harness this ships against**
(`architecture.md` §"Degraded modes" has the full measurement). `hook.log` still gets the exact,
verbatim, machine-readable record on every failure — the source of truth an operator can grep
directly — while the returned stdout text is a deliberately paraphrasable nudge pointing at that
log, never itself the record of what happened.
"""

import socket
import time
from pathlib import Path

from zikaron.core.errors import ZikaronError
from zikaron.hook import connect, envelope, failure, rpc
from zikaron.service import paths

#: `architecture.md`: "enforce an internal deadline of ~2 s, far under the `timeout_ms` the harness
#: enforces on the whole hook command" — 10 s on this harness, and stated explicitly in the shipped
#: hook entry rather than inherited (`architecture.md` §"The install contract").
#: Budgets the *whole* sequence below — connect, spawn-if-absent, health poll, the `surface`
#: request itself — not only the connect phase `connect.HEALTH_POLL_DEADLINE_SECONDS` bounds on
#: its own. Checked once, right before the one blocking sequence that can exceed it, rather than
#: interleaved through every step: the alternative (a fresh deadline check between each socket
#: call) would not materially tighten the bound, since `connect.connect_once` and
#: `rpc.surface_once` are each already individually bounded by socket timeouts, and a mid-sequence
#: abort would still need to close whatever socket was open — no cheaper than letting the one
#: attempt run to its own conclusion and discarding the result if it overran.
_DEADLINE_SECONDS = 2.0

#: `architecture.md` §"MCP tool surface": `surface`'s own documented default limit.
_SURFACE_LIMIT = 5


def run(*, cwd: Path, payload_session_id: object, prompt: str, pid: int) -> str | None:
    """Run the whole `userPromptSubmit` sequence and return what to print to stdout, or `None` if
    nothing should be printed — the caller (`main.py`) owns the actual `print`, so this function
    stays trivially testable without capturing real stdout.

    Every failure this function detects is handled by exactly one `_degrade` call before
    returning — there is no path that returns silently for a reason `hook.log` does not also
    record, and no path that returns silently for a reason the return value itself does not also
    carry as a model-facing relay instruction. That includes an exception this module did not
    anticipate: the degraded boundary below catches a genuine `Exception`, not a finite list of
    types, specifically so a defect in a dependency this function calls — or in this function's
    own future edits — degrades through the documented channel rather than escaping uncaught into
    `main.py`'s own outermost catch-all, which reports nothing on either channel.
    """
    started_at = time.monotonic()
    env_session_id = envelope.harness_session_id()
    if envelope.is_subagent_session(
        env_session_id=env_session_id, payload_session_id=payload_session_id
    ):
        # architecture.md §"Subagent sessions": "print nothing, stop... No RPC, no log line. This
        # is unrelated to the failure path below; it is not a failure at all."
        return None

    # `hook_log_path` is resolved *before* the degraded boundary, deliberately: it is the one
    # value `_degrade` itself needs to report *any* failure, including one raised by resolving
    # everything else below it — so it cannot itself be inside the boundary it feeds.
    store_dir = paths.store_dir(cwd)
    hook_log_path = paths.hook_log_path(store_dir)

    sock: socket.socket | None = None
    try:
        sock_path = connect.resolve_sock_path(store_dir)
        store_db_path = paths.store_db_path(store_dir)
        sock = connect.connect_once(
            sock_path,
            store_db_path=store_db_path,
            store_id=None,
            server_command=connect.default_server_command(sock_path, store_dir),
        )
        remaining = _DEADLINE_SECONDS - (time.monotonic() - started_at)
        if remaining <= 0:
            return _degrade(hook_log_path, "deadline_exceeded")
        sock.settimeout(remaining)
        client_envelope = envelope.build_envelope(session_id=env_session_id, pid=pid)
        return rpc.surface_once(sock, prompt=prompt, limit=_SURFACE_LIMIT, envelope=client_envelope)
    except (connect.HookTransportError, rpc.SurfaceRejectionError, ZikaronError) as error:
        kind, code = _classify_failure(error)
        return _degrade(hook_log_path, kind, code=code)
    except Exception:
        # Anything else — a send/recv failure, a malformed response, a timeout mid-request, or a
        # genuinely unanticipated defect in this function's own future edits. Never logs the
        # underlying exception's own message text: `_degrade`'s `kind` argument here is the fixed
        # word "transport", which is what keeps `hook.log` holding only the closed vocabulary
        # `architecture.md`'s error table names rather than arbitrary exception text that could
        # in principle echo something this process read (a path, a partial response body).
        return _degrade(hook_log_path, "transport")
    finally:
        if sock is not None:
            sock.close()


#: `architecture.md`'s error table names five wire codes a `surface` call can plausibly receive:
#: contention, the three store-level open failures, and an identity mismatch this module never
#: reaches through `SurfaceRejectionError` (it is caught earlier, inside `connect.connect_once`,
#: as a `HookTransportError`). Mapped to the log kind so `hook.log` names the same vocabulary
#: `architecture.md` §"Errors" already uses, rather than inventing a second one.
_REJECTION_KINDS: dict[int, str] = {
    -32020: "store_busy",
    -32022: "reindexing",
    -32023: "bad_config",
    -32024: "schema_incompatible",
}


def _classify_failure(error: Exception) -> tuple[str, int | None]:
    """Every exception `run()` catches, as the `(kind, code)` pair `_degrade` needs — one small
    dispatch rather than a `return _degrade(...)` per `except` clause, since the growing set of
    exception types this function must treat identically (a `SurfaceRejectionError`'s wire code,
    a `ZikaronError`'s own error code, a `StoreIdentityError`'s fixed `-32030`, or nothing more
    specific than "transport" for everything else) was pushing `run()` itself past a plain
    function's reasonable return-statement count — a lint signal worth heeding rather than
    suppressing, since the *reason* it fired is that `run()` was starting to do this module's
    classification work inline as well as its own control flow.

    A wire code the design's error table does not name (a programming error in the service, or a
    future addition neither side has been told about yet) still gets something identifiable
    rather than an uninformative default — `_REJECTION_KINDS.get(code, f"rejected_{code}")`.
    """
    if isinstance(error, connect.StoreIdentityError):
        # Checked before the plain `HookTransportError` base class it subclasses: an identity
        # mismatch is `architecture.md`'s own named code `-32030 store_identity`, not the generic
        # "transport" the base class's other cause (no server ever became reachable) collapses
        # to. Reachable through the unconditional store-*path* comparison `connect._verify_
        # identity` always runs — the hook has no persistent connection across invocations to
        # have learned a real `store_id` from the way a long-running client could, so its own
        # identity check stays path-only rather than reading the store file for one, which would
        # violate `architecture.md`'s own "never a reader of the store, under any failure."
        return "store_identity", -32030
    if isinstance(error, rpc.SurfaceRejectionError):
        return _REJECTION_KINDS.get(error.code, f"rejected_{error.code}"), error.code
    if isinstance(error, ZikaronError):
        # `connect.connect_once`'s own docstring: `security.ensure_runtime_dir`'s `ZikaronError`
        # on a hostile runtime directory "propagates as itself, since this single attempt has no
        # fallback path to degrade *through* a runtime directory it does not trust" — true about
        # *retrying*, but every failure kind must still reach `hook.log` and the model-facing
        # relay identically, **with its own numeric code**, not merely its name —
        # `architecture.md` names both wherever one exists, and omitting the code here would
        # leave `hook.log` naming, for example, `bad_config` with no accompanying `-32023`.
        return str(error.code.wire_name), int(error.code)
    # `connect.HookTransportError`'s own "no server became reachable" case, and anything else the
    # socket calls or JSON parsing can raise — a send/recv failure, a malformed response, a
    # timeout mid-request. `architecture.md` draws no distinction between these and a plain
    # transport failure.
    return "transport", None


def _degrade(hook_log_path: Path, kind: str, *, code: int | None = None) -> str:
    """Log the exact failure to `hook.log`, and return the model-facing relay instruction for it.

    The two channels carry different content on purpose: `hook.log`'s line names the machine
    vocabulary (`kind`, `code`) a future grep or an operator reading it directly can act on, while
    the returned instruction is prose aimed at a model that will paraphrase it — it names `kind`
    too, for a curious model to quote back, but its real job is pointing at `hook.log` as the
    place the exact detail lives, since the instruction itself is not the source of truth.
    """
    failure.record_failure(hook_log_path, kind, code=code)
    detail = f"{kind} ({code})" if code is not None else kind
    return (
        "The Zikaron memory hook failed to surface project memories for this turn "
        f"(reason: {detail}). Please let the operator know the memory hook failed, and that "
        "the exact error is recorded in .zikaron/hook.log if they want to look at it directly."
    )
