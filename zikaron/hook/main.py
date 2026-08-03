"""The process entry point kiro's own hook configuration invokes.

Confirmed against kiro's own hooks documentation: a hook receives its event as JSON on **stdin**
— `{"hook_event_name", "cwd", "session_id"}` always, plus `"prompt"` for `userPromptSubmit` — and
the same `command` string is free to be registered under either the `agentSpawn` or
`userPromptSubmit` trigger in an agent config, dispatching here on `hook_event_name` from the
payload itself rather than on an argv flag: kiro's hook fields (`command`/`matcher`/`timeout_ms`)
carry no per-trigger argument-injection mechanism, so the payload is the only place the trigger
name is actually available to branch on.

**This process always exits 0, unconditionally.** `push.py`'s own module docstring states why:
on this harness, only exit-0 stdout reaches the model, so a genuine failure is relayed through
that channel rather than through a non-zero exit or stderr, either of which would go unseen.
`main()`'s own outermost `contextlib.suppress(Exception)` is a *different*, narrower boundary
again: it exists for whatever neither `push.py` nor `spawn_warm.py` anticipated — a payload that
is not even valid JSON, or a field kiro's documented shape does not actually guarantee — and
stays silent on stdout too, since at that point this process may not even know which hook event
it was invoked for, let alone have a store-scoped failure to relay.
"""

import contextlib
import json
import os
import sys
from pathlib import Path

from zikaron.hook import push, spawn_warm

_AGENT_SPAWN = "agentSpawn"
_USER_PROMPT_SUBMIT = "userPromptSubmit"


def main() -> None:
    """Read one JSON payload from stdin, dispatch on `hook_event_name`, print whatever the
    dispatched module returns (if anything), and exit 0 unconditionally.
    """
    with contextlib.suppress(Exception):
        _run()
    sys.exit(0)


def _run() -> None:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        return
    event_name = payload.get("hook_event_name")
    cwd = Path(str(payload.get("cwd", ".")))
    pid = os.getpid()

    output: str | None
    if event_name == _AGENT_SPAWN:
        output = spawn_warm.run(cwd=cwd, payload_session_id=payload.get("session_id"))
    elif event_name == _USER_PROMPT_SUBMIT:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return
        output = push.run(
            cwd=cwd, payload_session_id=payload.get("session_id"), prompt=prompt, pid=pid
        )
    else:
        # An event this hook is not registered for, or a future trigger kiro adds. Nothing to do:
        # this process was invoked for a hook name it does not implement, which is not a failure
        # of anything this module owns.
        return

    if output is not None:
        # `sys.stdout.write`, not `print`: `print` appends a trailing `\n` this function's own
        # callers (`push.run`, `spawn_warm.run`) never included in their returned text, and
        # `architecture.md` states the empty-store case as "prints nothing at all" — `print("")`
        # would still emit a bare newline, which is not the same observable as nothing. Writing
        # exactly the returned string is what makes a successful `surface` response reach the
        # model byte-for-byte identical to what the service sent, and what makes the write-policy
        # constant `spawn_warm.run` returns land verbatim too.
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
