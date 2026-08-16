"""The process entry point a harness's own hook configuration invokes.

A hook receives its event as JSON on **stdin** — `{hook_event_name, cwd, session_id}` always, plus
`prompt` for the prompt trigger and `agent_type` for the subagent trigger — and the same `command`
string is registered under every trigger it serves, dispatching here on `hook_event_name` from the
payload itself rather than on an argv flag.

Both harnesses would accept a per-trigger flag, so this is a choice rather than a constraint. One
identical command under every trigger keeps the installed entries uniform, and — the reason that
actually matters — the payload's own `hook_event_name` cannot disagree with the event that fired
it, while a flag copied into several config entries can be copied wrong exactly once and then
mis-dispatch every invocation of that trigger, silently.

**Trigger names are normalized before anything branches on them.** `zikaron.harness.spec` owns the
vocabulary; this module knows only the three events it resolves to. That is what keeps one
implementation serving both harnesses instead of two ladders of string comparisons drifting apart.

**Output channel is a property of the event, not a constant.** An earlier version of this module
wrote plain stdout unconditionally, which is correct for the spawn and prompt triggers and reaches
nobody at all for the subagent trigger — measured, not assumed. The seam answers which channel each
event uses and this module honours the answer.

**This process always exits 0, unconditionally.** `push.py`'s own module docstring states why: only
exit-0 stdout reaches the model, so a genuine failure is relayed through that channel rather than
through a non-zero exit or stderr, either of which would go unseen. `main()`'s own outermost
`contextlib.suppress(Exception)` is a *different*, narrower boundary again: it exists for whatever
none of the dispatched modules anticipated — a payload that is not even valid JSON, or a field a
harness's documented shape does not actually guarantee — and stays silent on stdout too, since at
that point this process may not even know which hook event it was invoked for, let alone have a
store-scoped failure to relay.
"""

import contextlib
import json
import os
import sys
from pathlib import Path

from zikaron.harness.spec import HookEvent, OutputChannel, channel_for, event_for
from zikaron.hook import push, spawn_warm, subagent_policy


def main() -> None:
    """Read one JSON payload from stdin, dispatch on `hook_event_name`, emit whatever the dispatched
    module returns (if anything) on that event's own channel, and exit 0 unconditionally.
    """
    with contextlib.suppress(Exception):
        _run()
    sys.exit(0)


def _run() -> None:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        return
    trigger = payload.get("hook_event_name")
    event = event_for(trigger)
    if event is None:
        # A trigger this hook is not registered for, or one a harness adds later. Not a failure of
        # anything this module owns: the process was invoked for a name it does not implement.
        return
    output = _dispatch(event, payload)
    if output is not None:
        _emit(event, output, trigger=str(trigger))


def _dispatch(event: HookEvent, payload: dict[str, object]) -> str | None:
    """Whatever this event's own module wants emitted, or `None` for nothing at all."""
    cwd = Path(str(payload.get("cwd", ".")))
    if event is HookEvent.SPAWN:
        return spawn_warm.run(cwd=cwd, payload_session_id=payload.get("session_id"))
    if event is HookEvent.PROMPT:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return None
        return push.run(
            cwd=cwd,
            payload_session_id=payload.get("session_id"),
            prompt=prompt,
            pid=os.getpid(),
        )
    return subagent_policy.run(cwd=cwd, agent_type=payload.get("agent_type"))


def _emit(event: HookEvent, output: str, *, trigger: str) -> None:
    """Write `output` on the channel this event actually reaches a model through.

    `sys.stdout.write`, not `print`, on the plain channel: `print` appends a trailing newline the
    dispatched modules never included in their returned text, and the empty-store case is specified
    as "prints nothing at all" — `print("")` would still emit a bare newline, which is not the same
    observable as nothing. Writing exactly the returned string is what makes a successful surface
    response reach the model byte-for-byte identical to what the service sent, and what makes the
    write-policy text land verbatim too.

    The structured channel echoes back the harness's own trigger name rather than reconstructing
    one. The name has already been validated — it resolved to a known event — and echoing what
    arrived is what keeps this correct if a harness ever serves one event under more than one
    spelling.
    """
    if channel_for(event) is OutputChannel.STDOUT:
        sys.stdout.write(output)
        return
    envelope = {"hookSpecificOutput": {"hookEventName": trigger, "additionalContext": output}}
    # `json.dumps` defaults, including `ensure_ascii`: escaping non-ASCII inflates the emitted text
    # against a budget the harness measures on what it receives, so it is worth knowing by how much
    # rather than assuming. Measured on the shipped policy: 13 non-ASCII characters, 65 characters
    # of escaping, 1.2% — immaterial against this channel's budget, so the default stands and the
    # decoded text is identical either way.
    sys.stdout.write(json.dumps(envelope))


if __name__ == "__main__":
    main()
