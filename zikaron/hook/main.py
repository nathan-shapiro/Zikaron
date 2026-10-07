"""The process entry point a harness's own hook configuration invokes.

A hook receives its event as JSON on **stdin** — `{hook_event_name, cwd, session_id}` always, plus
`prompt` for the prompt trigger and `agent_type` for the subagent trigger — and it dispatches on
`hook_event_name` from the payload itself rather than on an argv flag.

Both harnesses would accept a per-trigger flag, so this is a choice rather than a constraint: the
payload's own `hook_event_name` cannot disagree with the event that fired it, while a flag copied
into several config entries can be copied wrong exactly once and then mis-dispatch every invocation
of that trigger, silently. The one argument a command carries, `--components` on the two start
triggers, selects what is said rather than which event is served, and reads as the memory hook
whenever it does not read cleanly.

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

from zikaron.guard.start_text import GUARD_START_TEXT
from zikaron.harness import detect
from zikaron.harness.spec import HookEvent, OutputChannel, channel_for, event_for
from zikaron.hook import push, spawn_warm, subagent_policy
from zikaron.hook.components import Components


def main() -> None:
    """Read one JSON payload from stdin, dispatch on `hook_event_name`, emit whatever the dispatched
    module returns (if anything) on that event's own channel, and exit 0 unconditionally.

    `--components guards|both` on the command line selects what the start triggers emit
    (`design/edit-guards.md` §5); without it this is exactly the memory hook.
    """
    with contextlib.suppress(Exception):
        _run(Components.from_arguments(sys.argv[1:]))
    sys.exit(0)


def _run(components: Components = Components.MEMORY) -> None:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        return
    trigger = payload.get("hook_event_name")
    event = event_for(trigger)
    if event is None:
        # A trigger this hook is not registered for, or one a harness adds later. Not a failure of
        # anything this module owns: the process was invoked for a name it does not implement.
        return
    output = _dispatch(event, payload, components)
    if output is not None:
        _emit(event, output, trigger=str(trigger))


def _dispatch(event: HookEvent, payload: dict[str, object], components: Components) -> str | None:
    """Whatever this event's own module wants emitted, or `None` for nothing at all.

    A start trigger emits the write policy for the memory store and the guard start text for the
    guards, in that order; a guards-only start makes no service connection at all.
    """
    if event is HookEvent.PROMPT:
        return _push(payload) if components.memory else None
    parts = [_start_policy(event, payload) if components.memory else None]
    if components.guards and not _is_consolidator(event, payload):
        parts.append(GUARD_START_TEXT)
    text = "\n\n".join(part for part in parts if part is not None)
    return text or None


def _scope_dir(payload: dict[str, object]) -> Path:
    # **Not the payload's `cwd` directly** — that is the value this harness reports *live*, and
    # under Claude Code it follows the agent's own `cd`, so keying a store on it put stores under
    # log directories and Scala source trees while `zikaron-mcp` stayed on the real one. The seam
    # decides; both clients ask it the same question. See `HarnessSpec.store_scope_dir`.
    return detect.current_spec().store_scope_dir(Path(str(payload.get("cwd", "."))))


def _push(payload: dict[str, object]) -> str | None:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return None
    return push.run(
        scope_dir=_scope_dir(payload),
        payload_session_id=payload.get("session_id"),
        prompt=prompt,
        pid=os.getpid(),
    )


def _start_policy(event: HookEvent, payload: dict[str, object]) -> str | None:
    if event is HookEvent.SPAWN:
        return spawn_warm.run(
            scope_dir=_scope_dir(payload), payload_session_id=payload.get("session_id")
        )
    return subagent_policy.run(scope_dir=_scope_dir(payload), agent_type=payload.get("agent_type"))


def _is_consolidator(event: HookEvent, payload: dict[str, object]) -> bool:
    """The consolidator's system prompt is its whole instruction, so it is given no start text."""
    return event is HookEvent.SUBAGENT_START and subagent_policy.is_consolidator(
        payload.get("agent_type")
    )


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
