"""`zikaron-guard`: the process Claude Code runs for both guard hooks.

It reads one hook payload from stdin and dispatches on `hook_event_name`: the find-replace rule
and the self-match rule on `PreToolUse` (`design/guards.md` §3, §9), the re-read nudge on
`PostToolUse` (§4). The trigger names and the tools each judges are `HarnessSpec.guards`, read
rather than spelled again; the platform the self-match rule reads is `sys.platform`, read here
and passed down.

**Every failure is an allow, silently** (§6): malformed JSON, an unknown event, a missing field or
an exception inside a rule exits 0 with no output, and the tool call proceeds as if no guard were
installed. A guard that blocks on its own defect stops work for a reason that is not the agent's.

>>> payload = {"hook_event_name": "PreToolUse", "tool_name": "Monitor", "cwd": "/home/u/proj",
...            "tool_input": {"command": "sed -i 's/a/b/' f"}}
>>> json.loads(respond(json.dumps(payload), tmpdir=None, platform="linux"))["hookSpecificOutput"][
...     "permissionDecision"]
'deny'
>>> respond(json.dumps({**payload, "tool_name": "Grep"}), tmpdir=None, platform="linux") is None
True
"""

import contextlib
import json
import os
import sys
from collections.abc import Mapping

from zikaron.guard.decision import Acknowledge, Deny, decide
from zikaron.guard.messages import acknowledgement, deny_message
from zikaron.guard.nudge import reread_text
from zikaron.guard.scratch import Location
from zikaron.guard.script_file import Reader, read_script
from zikaron.harness.spec import CLAUDE_CODE, Guards


def main() -> None:
    """Read the payload, write whatever the dispatched rule returns, and exit 0 unconditionally."""
    with contextlib.suppress(Exception):
        output = respond(
            sys.stdin.read(),
            tmpdir=os.environ.get("TMPDIR"),
            platform=sys.platform,
            read=read_script,
            job_dir=os.environ.get("CLAUDE_JOB_DIR"),
        )
        if output is not None:
            sys.stdout.write(output)
    sys.exit(0)


def respond(  # noqa: PLR0913 — `tmpdir` and `job_dir` are the hook's environment, read by `main`.
    raw: str,
    *,
    tmpdir: str | None,
    platform: str,
    guards: Guards | None = CLAUDE_CODE.guards,
    read: Reader | None = None,
    job_dir: str | None = None,
) -> str | None:
    """The hook's stdout for one payload on `platform`, a `sys.platform` value, or `None` for no
    output. `tmpdir` and `job_dir` are the hook's own `TMPDIR` and `CLAUDE_JOB_DIR`, and `read` is
    row 6's file read, none by default: `main` is where the hook's I/O is done, and passes
    `read_script`.

    Raises whatever a malformed payload or a rule defect raises; `main` turns that into silence.
    """
    payload = json.loads(raw)
    if guards is None or not isinstance(payload, dict):
        return None
    location = _location(payload, tmpdir, job_dir)
    event = payload.get("hook_event_name")
    if event == guards.command.trigger:
        return _command(payload, location, platform, tools=guards.command.tools, read=read)
    if event == guards.reread.trigger:
        return _reread(payload, location, tools=guards.reread.tools)
    return None


def _command(
    payload: Mapping[str, object],
    location: Location | None,
    platform: str,
    *,
    tools: frozenset[str],
    read: Reader | None,
) -> str | None:
    command = _field(payload, "tool_input").get("command")
    if payload.get("tool_name") not in tools or not isinstance(command, str) or location is None:
        return None
    decision = decide(command, location, platform=platform, read=read)
    if isinstance(decision, Deny):
        reason = deny_message(
            decision.match,
            invalid_marker=decision.invalid_marker,
            marker_in_content=decision.marker_in_content,
        )
        return _hook_output(
            payload, {"permissionDecision": "deny", "permissionDecisionReason": reason}
        )
    if isinstance(decision, Acknowledge):
        text = acknowledgement(decision.reason, decision.targets)
        return _hook_output(payload, {"additionalContext": text})
    return None


def _reread(
    payload: Mapping[str, object], location: Location | None, *, tools: frozenset[str]
) -> str | None:
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or tool not in tools or location is None:
        return None
    result = payload.get("tool_response")
    if not isinstance(result, dict):
        result = _field(payload, "tool_output")
    text = reread_text(tool, _field(payload, "tool_input"), result, location)
    return None if text is None else _hook_output(payload, {"additionalContext": text})


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


def _hook_output(payload: Mapping[str, object], fields: Mapping[str, str]) -> str:
    """The `hookSpecificOutput` envelope, echoing the trigger name that arrived. A valid override
    carries no `permissionDecision`: it withdraws the deny and grants nothing (§3.4)."""
    event = payload["hook_event_name"]
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}})
