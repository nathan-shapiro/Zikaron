"""Transcript records shaped as Claude Code 2.1.311 wrote them in the agent-team probe runs and
M43's live runs, their content replaced by placeholders (`research/teammate-hook-probe.md`).

Only the keys `zikaron.hook.instruction` reads are kept, beside `uuid` and `isSidechain`, so a test
transcript is the measured shape and nothing the reader could come to depend on by accident.
"""

import json
from pathlib import Path

MESSAGE_OPENING = "<teammate-message"
RESUME_OPENING = "The coordinator sent a message while you were working:"
RESUME_CLOSING = "Address this before completing your current task."


def user(content: str | list[dict[str, object]], **flags: object) -> dict[str, object]:
    return {
        "type": "user",
        "isSidechain": True,
        "uuid": "u",
        "message": {"role": "user", "content": content},
        **flags,
    }


def assistant(*blocks: dict[str, object]) -> dict[str, object]:
    return {
        "type": "assistant",
        "isSidechain": True,
        "uuid": "a",
        "message": {"role": "assistant", "content": list(blocks)},
    }


def attachment() -> dict[str, object]:
    return {"type": "attachment", "attachment": {"type": "environment"}}


def thinking() -> dict[str, object]:
    return {"type": "thinking", "thinking": "placeholder", "signature": "s"}


def text(words: str = "placeholder") -> dict[str, object]:
    return {"type": "text", "text": words}


def tool_use() -> dict[str, object]:
    return {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "echo one"}}


def tool_result() -> dict[str, object]:
    return {"type": "tool_result", "tool_use_id": "t", "content": "one", "is_error": False}


def message(body: str, *, sender: str = "team-lead", summary: str | None = None) -> str:
    summary_attribute = f' summary="{summary}"' if summary is not None else ""
    return (
        f'{MESSAGE_OPENING} teammate_id="{sender}"{summary_attribute}>\n{body}\n</teammate-message>'
    )


def api_request(kind: str = "api-request") -> dict[str, object]:
    """One of the records the harness writes for a model request; the blob holds the request's
    text blocks."""
    record: dict[str, object] = {"type": kind, "uuid": "r"}
    if kind == "api-request-blob":
        record["message"] = {"content": [text("request text")]}
    return record


def at_first_call(instruction: str) -> list[dict[str, object]]:
    """A transcript as a response's first `PreToolUse` reads it: the instruction, the harness's own
    reminder and attachments, then the request records — the response itself not yet written."""
    return [
        user(instruction),
        user("<system-reminder>placeholder", isMeta=True),
        attachment(),
        api_request("api-request-shape"),
        api_request("api-request-blob"),
        api_request(),
    ]


def resumed(body: str, *, closing: bool = True) -> dict[str, object]:
    """A resumed subagent's next prompt, as the in-process live run recorded it."""
    ending = f"\n\n{RESUME_CLOSING}" if closing else ""
    return user(f"{RESUME_OPENING}\n{body}{ending}", isMeta=True, origin={"kind": "coordinator"})


def write(path: Path, records: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path
