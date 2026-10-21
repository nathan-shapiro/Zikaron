"""`userPromptSubmit`: suppress, connect once, ask for the push block, print or relay a failure.

`architecture.md` §"Degraded modes" is normative for the whole sequence, and §"Subagent sessions"
for step 0. Every branch below reaches exactly one of three observable outcomes, and every one
exits 0: print `surface`'s text; print nothing (a suppressed subagent turn — not a failure); or
print a short, model-facing notice — asking the agent to relay a failure to the operator, or, for
a service still starting, saying that memories resume once it has started.
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
from zikaron.harness import detect
from zikaron.hook import connect, envelope, failure, rpc, tripwire
from zikaron.hook.limits import HOOK_TIMEOUT_SECONDS
from zikaron.service import paths

#: The whole push — connect, `health()`, the `surface` request — to a service already running and
#: done starting. Short, because failing fast beats being correct and late while the user waits
#: (`architecture.md` §"Degraded modes").
_DEADLINE_SECONDS = 2.0

#: What a cold start's deadline leaves of the harness's kill. It pays for the connect's last
#: attempt running past the deadline, then this process's own start before `run` and its print
#: after: a miss has to reach `hook.log` and the relay, and a kill produces neither.
_OUTSIDE_RUN_SECONDS = 2.0

#: The whole push to a service that was starting when it began — absent, as on the first message
#: after an idle stop, or still loading its model soon after it opened its store — which waits for
#: the start as well as the answer.
_COLD_START_DEADLINE_SECONDS = HOOK_TIMEOUT_SECONDS - _OUTSIDE_RUN_SECONDS

#: How far ahead a `deadline_at_ms` may be: the service refuses one more than `ddl.BUSY_TIMEOUT_MS`
#: ahead as `bounds`, and the two ends read the realtime clock at different instants, so this sits
#: under that bound rather than on it. A literal, because this package is stdlib-only; a guard test
#: holds it under the service's.
_MAX_DEADLINE_AHEAD_SECONDS = 4.5

#: The three ways a push is late (`architecture.md` §"A push the agent never saw is never recorded
#: as shown"). To a push that found the service starting, each means the start is still running.
_LATENESS_KINDS = frozenset({"deadline_exceeded", "unanswered", "deadline_passed"})

#: What a push that found the service absent was still waiting on at its deadline, before it could
#: send anything: another client's start, through the lock, or its own, through the poll.
_START_WAITS = frozenset({"lock", "poll"})

#: What `hook.log` records for a push that ran out of time while the service was starting, kept
#: apart from every fault and followed by what it was waiting on — one of `_START_WAITS`, or the
#: lateness it would otherwise have been — so where a slow start spends its time stays readable.
_STARTING = "starting"

_STARTING_RELAY = (
    "The Zikaron memory service was still starting, so no project memories were surfaced for "
    "this message. This is expected when the service was not yet running, or had only just "
    "started, and needs no report; "
    "memories are surfaced again once it has started, usually from the next message."
)

#: `architecture.md` §"MCP tool surface": `surface`'s own documented default limit.
_SURFACE_LIMIT = 5


def run(*, scope_dir: Path, payload_session_id: object, prompt: str, pid: int) -> str | None:
    """Run the whole `userPromptSubmit` sequence and return what to print to stdout, or `None` if
    nothing should be printed — the caller (`main.py`) owns the actual `print`, so this function
    stays trivially testable without capturing real stdout.

    Every failure this function detects is handled by exactly one `_degrade` call before
    returning — there is no path that returns silently for a reason `hook.log` does not also
    record, and no path that returns silently for a reason the return value itself does not also
    carry as a model-facing notice. That includes an exception this module did not
    anticipate: the degraded boundary below catches a genuine `Exception`, not a finite list of
    types, specifically so a defect in a dependency this function calls — or in this function's
    own future edits — degrades through the documented channel rather than escaping uncaught into
    `main.py`'s own outermost catch-all, which reports nothing on either channel.
    """
    started_at = time.monotonic()
    spec = detect.current_spec()
    env_session_id = detect.session_label(spec)
    if envelope.is_subagent_session(
        env_session_id=env_session_id, payload_session_id=payload_session_id
    ):
        # Print nothing, make no RPC. Under a harness that fires this hook for subagent sessions
        # that is the whole story and not a failure at all. Under one where payload and
        # environment session ids are invariantly equal it instead means the harness was
        # misdetected — the single case `tripwire` records, and the only one that writes a line
        # here.
        tripwire.record_if_misdetected(spec=spec, scope_dir=scope_dir)
        return None

    # `hook_log_path` is resolved *before* the degraded boundary, deliberately: it is the one
    # value `_degrade` itself needs to report *any* failure, including one raised by resolving
    # everything else below it — so it cannot itself be inside the boundary it feeds.
    store_dir = paths.store_dir(scope_dir)
    hook_log_path = paths.hook_log_path(store_dir)

    sock: socket.socket | None = None
    cold_start = False
    try:
        sock_path = connect.resolve_sock_path(store_dir)
        connection = connect.connect_once(
            sock_path,
            store_db_path=paths.store_db_path(store_dir),
            store_id=None,
            server_command=connect.default_server_command(sock_path, store_dir),
            poll_deadline=started_at + _COLD_START_DEADLINE_SECONDS,
        )
        sock = connection.sock
        # A service that answered at once but is still loading its model, its store open for less
        # than a cold start is allowed, is as much a start as one this push had to spawn — the
        # session-start warm-up leaves exactly that behind.
        cold_start = connection.cold_start or connection.health.still_loading_within(
            _COLD_START_DEADLINE_SECONDS
        )
        budget = _COLD_START_DEADLINE_SECONDS if cold_start else _DEADLINE_SECONDS
        now = time.monotonic()
        remaining = min(budget - (now - started_at), _MAX_DEADLINE_AHEAD_SECONDS)
        client_envelope = envelope.build_envelope(session_id=env_session_id, pid=pid)
        try:
            return rpc.surface_once(
                sock,
                prompt=prompt,
                limit=_SURFACE_LIMIT,
                envelope=client_envelope,
                deadline=rpc.HookDeadline.after(remaining, now=now),
            )
        except rpc.NotSentError:
            # Connecting spent the budget, or the moment left of it ran out before the send.
            return _degrade(hook_log_path, "deadline_exceeded", cold_start=cold_start)
        except TimeoutError:
            # Sent, and not answered by the deadline: the service received this push. Scoped to
            # this call alone, because a timeout inside `connect_once` to a running service is a
            # listener that accepts and never answers `health` — a blocked event loop — which
            # stays `transport`.
            return _degrade(hook_log_path, "unanswered", cold_start=cold_start)
    except (connect.HookTransportError, rpc.ServiceRejectionError, ZikaronError) as error:
        kind, code = failure.classify(error)
        return _degrade(hook_log_path, kind, code=code, cold_start=cold_start)
    except Exception:
        # Anything else — a send/recv failure, a malformed response, a timeout before the send, or
        # a genuinely unanticipated defect in this function's own future edits. Never logs the
        # underlying exception's own message text: `_degrade`'s `kind` argument here is the fixed
        # word "transport", which is what keeps `hook.log` holding only the closed vocabulary
        # `architecture.md`'s error table names rather than arbitrary exception text that could
        # in principle echo something this process read (a path, a partial response body).
        return _degrade(hook_log_path, "transport")
    finally:
        if sock is not None:
            sock.close()


def _degrade(
    hook_log_path: Path, kind: str, *, code: int | None = None, cold_start: bool = False
) -> str:
    """Log the exact failure to `hook.log`, and return what the model is told about it.

    A push that found the service starting and ran out of time — `kind` is one of `_START_WAITS`,
    or one of the lateness kinds with `cold_start` set — is logged as `starting`, followed by
    `kind`, and told only that memories resume once it has started. That is not an alarm, and it
    need not be, because how long one start can be called one is bounded: a spawned process that
    fails ends the poll, a service still loading after the cold-start deadline is no longer
    starting, and a holder that has shown no sign of life for too long is reported (`connect.py`).

    Every other failure keeps its own kind and code, and asks the model to tell the operator. The
    two channels differ on purpose: `hook.log`'s line is the machine vocabulary a grep can act on,
    while the instruction is prose a model will paraphrase, so its job is to point at `hook.log`.
    """
    if kind in _START_WAITS or (cold_start and kind in _LATENESS_KINDS):
        failure.record_failure(hook_log_path, _STARTING, detail=kind, code=code)
        return _STARTING_RELAY
    failure.record_failure(hook_log_path, kind, code=code)
    detail = f"{kind} ({code})" if code is not None else kind
    return (
        "The Zikaron memory hook failed to surface project memories for this turn "
        f"(reason: {detail}). Please let the operator know the memory hook failed, and that "
        "the exact error is recorded in .zikaron/hook.log if they want to look at it directly."
    )
