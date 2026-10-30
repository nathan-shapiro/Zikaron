"""What the `integration_kiro` tests share: one headless turn of a real `kiro-cli chat`, and the
records kiro keeps of it.

A launch's `~/.kiro/logs/<timestamp>/kiro.log` holds one JSON object a line, each carrying the
session's id as `rootConversationId`: an `acp.policy-eval.complete` line per tool call, naming the
tool, the effect and, where a rule decided it, the capability; and an `invoke_subagent.starting`
line per spawn, naming the agent, its model and its effort. The tool is named by kiro's log id,
which for the shell is `run_command` and for a spawn `invoke_sub_agent`, where the hook payload says
`execute_bash`; the file tools keep one name (`research/kiro-v3-probe.md` §59). A session's
transcript is `~/.kiro/sessions/<hash>/<session id>/messages.jsonl` (`research/kiro-v3-probe.md`
§31).
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Final, NamedTuple

from tests.harness_variables import HARNESS_VARIABLES
from zikaron.harness.spec import KIRO
from zikaron.install import harness

#: A cold turn pays for a kiro start, a service start, a subagent spawn and real model turns.
TURN_TIMEOUT: Final = 600.0

#: The release from which V3 is kiro's default engine, below which a launch asks for it.
_V3_DEFAULT_FROM: Final = (3, 0, 0)

_KIRO_HOME: Final = Path.home() / ".kiro"


class Turn(NamedTuple):
    """What one headless turn left behind."""

    stream: list[dict[str, object]]
    stderr: str
    returncode: int

    def of_type(self, kind: str) -> list[dict[str, object]]:
        return [event for event in self.stream if event.get("type") == kind]

    @property
    def session_id(self) -> object:
        (finished,) = self.of_type("runFinished")
        data = finished.get("data")
        return data.get("sessionId") if isinstance(data, dict) else None

    def diagnosis(self) -> str:
        return f"kiro-cli exited {self.returncode}; stderr: {self.stderr[-800:]!r}"


def require_kiro() -> None:
    """Fail — never skip — when the binary is absent (`test_install_harness.py::_require_kiro`)."""
    assert harness.binary_is_available(KIRO.harness_binary), (
        f"{KIRO.harness_binary!r} is not on PATH: either this machine has no kiro, in which case "
        "do not run `-m integration_kiro` here, or `HarnessSpec.harness_binary` names the wrong "
        "binary."
    )


def _without_harness_variables() -> dict[str, str]:
    """This process's environment less `HARNESS_VARIABLES`, the set `conftest` removes before each
    test. Removed here too because a fixture of wider scope runs before that removal, and a kiro
    started with Claude Code's variables reads its own hooks as nested and pushes nothing
    (`design/harness.md` §"The nesting limit")."""
    return {name: value for name, value in os.environ.items() if name not in HARNESS_VARIABLES}


def chat(project: Path, agent: str, prompt: str, *, model: str) -> Turn:
    """One headless V3 turn in `project`, started with no harness's variables. `--v3` is passed
    only where the binary is older than the release that makes V3 its default."""
    engine = ["--v3"] if harness.installed_version() < _V3_DEFAULT_FROM else []
    completed = subprocess.run(  # noqa: S603 — the argv is this module's own constants.
        [
            KIRO.harness_binary,
            "chat",
            *engine,
            "--no-interactive",
            "--require-mcp-startup",
            "--agent",
            agent,
            "--model",
            model,
            "--output-format",
            "stream-json",
            prompt,
        ],
        cwd=project,
        env=_without_harness_variables(),
        capture_output=True,
        text=True,
        timeout=TURN_TIMEOUT,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    stream = []
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            stream.append(event)
    return Turn(stream=stream, stderr=completed.stderr, returncode=completed.returncode)


def launch_log(session_id: object) -> list[dict[str, object]]:
    """The records of the launch whose session is `session_id`, from its own `kiro.log`."""
    marker = f'"rootConversationId":"{session_id}"'
    for log in sorted(_KIRO_HOME.glob("logs/*/kiro.log"), reverse=True):
        text = log.read_text(encoding="utf-8", errors="replace")
        if marker in text:
            return [
                record
                for record in _records(text)
                if record.get("rootConversationId") == session_id
            ]
    message = f"no kiro.log under {_KIRO_HOME / 'logs'} names session {session_id}"
    raise AssertionError(message)


def _records(text: str) -> list[dict[str, object]]:
    records = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def events(records: list[dict[str, object]], name: str) -> list[dict[str, object]]:
    """The JSON detail of every record whose message is `name`, such as
    `acp.policy-eval.complete` or `invoke_subagent.starting`."""
    found = []
    for record in records:
        message = record.get("message")
        if isinstance(message, str) and message.startswith(f"{name} "):
            detail = json.loads(message.removeprefix(f"{name} "))
            if isinstance(detail, dict):
                found.append(detail)
    return found


def session_messages(session_id: object) -> str:
    """The session's whole `messages.jsonl`, as text."""
    (transcript,) = _KIRO_HOME.glob(f"sessions/*/{session_id}/messages.jsonl")
    return transcript.read_text(encoding="utf-8", errors="replace")
