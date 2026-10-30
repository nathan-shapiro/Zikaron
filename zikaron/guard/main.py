"""`zikaron-guard`: the process a harness runs for the guard hooks.

It reads one hook payload from stdin and dispatches on `hook_event_name`: the find-replace rule
and the self-match rule on `PreToolUse` (`design/guards.md` §3, §9), the re-read nudge on
`PostToolUse` (§4) where the harness has one. Which harness it serves is its command line's
(`arguments`). The trigger names, the tools each judges and how a deny is delivered are that
harness's `HarnessSpec.guards`, read rather than spelled again; the platform the self-match rule
reads is `sys.platform`, read here and passed down.

**Every failure is an allow, silently** (§6): malformed JSON, an unknown event, a missing field or
an exception inside a rule exits 0 with no output, and the tool call proceeds as if no guard were
installed. A guard that blocks on its own defect stops work for a reason that is not the agent's.

>>> payload = {"hook_event_name": "PreToolUse", "tool_name": "Monitor", "cwd": "/home/u/proj",
...            "tool_input": {"command": "sed -i 's/a/b/' f"}}
>>> output = respond(json.dumps(payload), tmpdir=None, platform="linux")
>>> json.loads(output.stdout)["hookSpecificOutput"]["permissionDecision"], output.exit_code
('deny', 0)
>>> from zikaron.harness.spec import KIRO
>>> kiro = respond(json.dumps({**payload, "tool_name": "execute_bash"}), tmpdir=None,
...                platform="linux", spec=KIRO)
>>> kiro.stdout, kiro.exit_code, kiro.stderr.startswith("Zikaron's find-replace guard refused")
('', 2, True)
>>> respond(json.dumps({**payload, "tool_name": "Grep"}), tmpdir=None, platform="linux") is None
True
"""

import contextlib
import json
import os
import sys
from collections.abc import Mapping
from typing import Final, NamedTuple

from zikaron.guard.arguments import spec_from_arguments
from zikaron.guard.decision import Acknowledge, Decision, Deny, decide
from zikaron.guard.messages import acknowledgement, deny_message
from zikaron.guard.nudge import reread_text
from zikaron.guard.scratch import Location
from zikaron.guard.script_file import Reader, read_script
from zikaron.harness.spec import CLAUDE_CODE, DenyChannel, GuardHook, HarnessSpec

#: The exit status by which a pre-tool hook blocks a call where a deny goes out on stderr.
_BLOCK: Final = 2


class HookOutput(NamedTuple):
    """What the hook writes, and the status it exits with."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


def main() -> None:
    """Read the payload, write whatever the dispatched rule returns, and exit with its status —
    0 for anything that is not a deny on stderr, a failure included."""
    status = 0
    with contextlib.suppress(Exception):
        output = respond(
            sys.stdin.read(),
            tmpdir=os.environ.get("TMPDIR"),
            platform=sys.platform,
            spec=spec_from_arguments(sys.argv[1:]),
            read=read_script,
            job_dir=os.environ.get("CLAUDE_JOB_DIR"),
        )
        if output is not None:
            sys.stdout.write(output.stdout)
            sys.stderr.write(output.stderr)
            status = output.exit_code
    sys.exit(status)


def respond(  # noqa: PLR0913 — `tmpdir` and `job_dir` are the hook's environment, read by `main`.
    raw: str,
    *,
    tmpdir: str | None,
    platform: str,
    spec: HarnessSpec = CLAUDE_CODE,
    read: Reader | None = None,
    job_dir: str | None = None,
) -> HookOutput | None:
    """The hook's output for one payload under `spec`'s harness on `platform`, a `sys.platform`
    value, or `None` for none. `tmpdir` and `job_dir` are the hook's own `TMPDIR` and
    `CLAUDE_JOB_DIR`, and `read` is row 6's file read, none by default: `main` is where the hook's
    I/O is done, and passes `read_script`.

    Raises whatever a malformed payload or a rule defect raises; `main` turns that into silence.
    """
    payload = json.loads(raw)
    guards = spec.guards
    if guards is None or not isinstance(payload, dict):
        return None
    location = _location(payload, tmpdir, job_dir)
    event = payload.get("hook_event_name")
    if event == guards.command.trigger:
        decision = _decision(payload, location, platform, tools=guards.command.tools, read=read)
        return _answer(payload, decision, spec=spec, deny=guards.deny)
    if guards.reread is not None and event == guards.reread.trigger:
        return _reread(payload, location, hook=guards.reread)
    return None


def _decision(
    payload: Mapping[str, object],
    location: Location | None,
    platform: str,
    *,
    tools: frozenset[str],
    read: Reader | None,
) -> Decision | None:
    """What the command hook decides of a call, or `None` where it judges none."""
    command = _field(payload, "tool_input").get("command")
    if payload.get("tool_name") not in tools or not isinstance(command, str) or location is None:
        return None
    return decide(command, location, platform=platform, read=read)


def _answer(
    payload: Mapping[str, object],
    decision: Decision | None,
    *,
    spec: HarnessSpec,
    deny: DenyChannel,
) -> HookOutput | None:
    """A decision as `deny` delivers it: on stderr only a deny, since nothing printed on exit 0
    reaches the model there."""
    if isinstance(decision, Deny):
        reason = deny_message(
            decision.match,
            invalid_marker=decision.invalid_marker,
            marker_in_content=decision.marker_in_content,
            spec=spec,
        )
        if deny is DenyChannel.STDERR:
            return HookOutput(stderr=reason, exit_code=_BLOCK)
        return _envelope(
            payload, {"permissionDecision": "deny", "permissionDecisionReason": reason}
        )
    if isinstance(decision, Acknowledge) and deny is DenyChannel.ENVELOPE:
        text = acknowledgement(decision.reason, decision.targets, spec=spec)
        return _envelope(payload, {"additionalContext": text})
    return None


def _reread(
    payload: Mapping[str, object], location: Location | None, *, hook: GuardHook
) -> HookOutput | None:
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or tool not in hook.tools or location is None:
        return None
    result = payload.get("tool_response")
    if not isinstance(result, dict):
        result = _field(payload, "tool_output")
    text = reread_text(tool, _field(payload, "tool_input"), result, location)
    return None if text is None else _envelope(payload, {"additionalContext": text})


def _location(
    payload: Mapping[str, object], tmpdir: str | None, job_dir: str | None
) -> Location | None:
    """Where the command ran, or `None` when the payload carries no usable `cwd`."""
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.startswith("/"):
        return None
    scratchpad = payload.get("scratchpad_dir")
    return Location(cwd, tmpdir, scratchpad if isinstance(scratchpad, str) else None, job_dir)


def _field(payload: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def _envelope(payload: Mapping[str, object], fields: Mapping[str, str]) -> HookOutput:
    """The `hookSpecificOutput` envelope, echoing the trigger name that arrived. A valid override
    carries no `permissionDecision`: it withdraws the deny and grants nothing (§3.4)."""
    event = payload["hook_event_name"]
    return HookOutput(stdout=json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}))
