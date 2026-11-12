"""An agent's latest instruction, read backward from the end of its transcript.

`design/harness.md` §"Agent teams" is normative. The harness hands the hook no instruction, so it is
read from the transcript the payload names: the last string-content `user` record and every such
record back to the `assistant` record, or the list-content `user` record, before them. The current
turn's own `assistant` records, one per content block, come after them and are passed over, as are
the records the harness flags as its own, except the one carrying a resumed subagent's prompt.

**What it cannot read as measured, it does not push.** A record after the instruction carrying a
tool result means the turn is past its first tool call, so this call is not the one the marker was
set for; one carrying text is an instruction of a shape never measured; and either would otherwise
push the instruction before it, silently and wrongly.
"""

import enum
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from zikaron.harness.spec import InstructionPush

#: A transcript grows for a whole session and the instruction is at its end, so it is read in
#: blocks from the end rather than whole.
_BLOCK_BYTES: Final = 65_536

_CLOSING: Final = "</teammate-message>"


class Unread(enum.Enum):
    """Why a transcript could not be read as measured — what `instruction_unread` stands for."""

    MISSING = "missing"
    MALFORMED = "malformed"
    TEXT_AFTER = "text_after"
    RESULT_AFTER = "result_after"
    UNWRAPPED = "unwrapped"


def latest(
    transcript: Path, push_spec: InstructionPush, *, main_shaped: bool
) -> str | Unread | None:
    """The instruction to push, the reason it cannot be read, or `None` for nothing to push.

    `main_shaped` is a session's own agent, served only where its transcript's first instruction is
    a message from another agent — a tmux teammate — and never a session's main agent, whose
    prompts the prompt hook serves. Raises nothing.
    """
    try:
        if main_shaped and not _opens_with_a_message(transcript, push_spec.message_opening):
            return None
        collected = _latest_records(transcript, push_spec)
    except OSError:
        return Unread.MISSING
    if isinstance(collected, Unread):
        return collected
    if not collected:
        return None
    return _text(reversed(collected), push_spec.message_opening)


def _latest_records(transcript: Path, push_spec: InstructionPush) -> list[str] | Unread:
    collected: list[str] = []
    for record in _records_backward(transcript):
        if record is None:
            return Unread.MALFORMED
        kind = record.get("type")
        if kind == "assistant":
            if collected:
                break
            continue
        if kind != "user":
            continue
        content = _user_content(record, push_spec)
        if content is None:
            continue
        if isinstance(content, Unread):
            return content
        if isinstance(content, str):
            collected.append(content)
            continue
        if collected:
            break
        blocks = {block.get("type") for block in content if isinstance(block, dict)}
        if "tool_result" in blocks:
            return Unread.RESULT_AFTER
        if "text" in blocks:
            return Unread.TEXT_AFTER
    return collected


def _opens_with_a_message(transcript: Path, message_opening: str) -> bool:
    """Whether the transcript's first instruction is a message from another agent."""
    with transcript.open("rb") as handle:
        for line in handle:
            record = _parse(line)
            if record is None or record.get("type") != "user" or _passed_over(record):
                continue
            content = _content(record)
            if isinstance(content, str):
                return content.startswith(message_opening)
    return False


def _records_backward(transcript: Path) -> Iterator[dict[str, object] | None]:
    """Each non-blank line from the last, parsed; `None` for one that is not a JSON object."""
    with transcript.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        tail = b""
        while position > 0:
            size = min(_BLOCK_BYTES, position)
            position -= size
            handle.seek(position)
            lines = (handle.read(size) + tail).split(b"\n")
            tail = lines[0]
            for line in reversed(lines[1:]):
                if line.strip():
                    yield _parse(line)
        if tail.strip():
            yield _parse(tail)


def _parse(line: bytes) -> dict[str, object] | None:
    try:
        record = json.loads(line)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _user_content(
    record: dict[str, object], push_spec: InstructionPush
) -> str | list[object] | Unread | None:
    """A `user` record's content, a resumed subagent's prompt as its body; `None` for a record
    passed over."""
    resumed = _resumed(record, push_spec)
    if resumed is not None:
        return resumed
    if _passed_over(record):
        return None
    return _content(record)


def _resumed(record: dict[str, object], push_spec: InstructionPush) -> str | Unread | None:
    """A resumed subagent's prompt, its body without the harness's two lines around it; `None`
    for any other record."""
    origin = record.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != push_spec.resume_origin:
        return None
    content = _content(record)
    if not isinstance(content, str) or not content.startswith(push_spec.resume_opening):
        return Unread.UNWRAPPED
    body = content.removeprefix(push_spec.resume_opening).strip()
    return body.removesuffix(push_spec.resume_closing).strip()


def _passed_over(record: dict[str, object]) -> bool:
    """A record the harness flags as its own — a command's caveat, a compaction's summary, a
    skill's expansion — which is no instruction."""
    return bool(record.get("isMeta")) or bool(record.get("isCompactSummary"))


def _content(record: dict[str, object]) -> str | list[object] | Unread:
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str | list):
        return content
    return Unread.MALFORMED


def _text(records: Iterator[str], message_opening: str) -> str | Unread | None:
    """The records as one instruction: each message reduced to its body, the shutdown and idle
    protocol's dropped, the rest joined by a blank line."""
    # The opening tag ends at the first `>` that ends its line: a model-written `summary` may hold
    # an arrow, and a body on the tag's own line is a shape never measured, so it reads as unread.
    wrapped = re.compile(
        re.escape(message_opening) + r"[^\n]*?>\n(.*?)" + re.escape(_CLOSING), re.S
    )
    parts: list[str] = []
    for record in records:
        if not record.startswith(message_opening):
            parts.append(record.strip())
            continue
        bodies = wrapped.findall(record)
        if not bodies:
            return Unread.UNWRAPPED
        parts.extend(body.strip() for body in bodies if not _is_protocol(body))
    text = "\n\n".join(part for part in parts if part)
    return text or None


def _is_protocol(body: str) -> bool:
    """Whether a message body is the team's own protocol rather than an instruction: its first line
    a JSON object carrying `type`, which a shutdown request follows with prose on how to answer."""
    first_line = body.strip().split("\n", 1)[0]
    try:
        parsed = json.loads(first_line)
    except ValueError:
        return False
    return isinstance(parsed, dict) and "type" in parsed
