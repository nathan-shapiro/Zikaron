"""Whether a search reminder is followed by a search of the documents it named.

`design/build-plan.md` §M40-4 done-when 2: over one project's Claude Code transcripts, subagents
included, every search that reached a documented module — judged by the hook's own reading of the
call — is either reminded (the transcript holds the reminder's `hook_additional_context` for that
call) or left unreminded by the throttle. For each, whether a `zikaron_knowledge_search` whose scope
reaches one of the corpora that search reached follows within the next `--window` tool calls of the
same transcript. Prints both counts and both rates; there is no bar.

The corpora are read from the project's own registry, read-only. A search is classified as the hook
classifies it, so this counts what the hook saw rather than what a grep of the transcript suggests,
and the transcripts of the agents the hook never reminds, the documenter and the orchestrator, are
left out of both arms.

Run: .venv/bin/python experiments/m40_4_reminder_followon.py --project DIR [--window N]
"""

import argparse
import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from zikaron.core.code_knowledge.reminder import corpora_reached, module_of
from zikaron.harness.spec import CLAUDE_CODE
from zikaron.hook import reminder

#: How a reminder's line opens, so its attachment is told from any other hook's context. Only the
#: reminder's text opens this way, so a transcript written under an earlier wording still counts.
_LINE_OPENS = "Zikaron hook:"
_SEARCH_TOOL = "zikaron_knowledge_search"


@dataclass(frozen=True, slots=True)
class Call:
    """One tool call in a transcript, in order."""

    tool_use_id: str
    name: str
    tool_input: dict[str, object]
    cwd: str


def transcripts(project: Path) -> Path:
    return Path.home() / ".claude" / "projects" / str(project.resolve()).replace("/", "-")


def registered(project: Path) -> list[str]:
    database = project / ".zikaron" / "memory.db"
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        return [name for (name,) in connection.execute("SELECT name FROM knowledge_bases")]


def read(path: Path) -> tuple[list[Call], set[str]]:
    """A transcript's tool calls in order, and the ids of the calls a reminder followed."""
    calls: list[Call] = []
    reminded: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        attachment = entry.get("attachment") or {}
        if attachment.get("type") == "hook_additional_context" and any(
            str(text).startswith(_LINE_OPENS) for text in attachment.get("content") or ()
        ):
            reminded.add(str(attachment.get("toolUseID")))
        message = entry.get("message") or {}
        if entry.get("type") != "assistant" or not isinstance(message.get("content"), list):
            continue
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append(
                    Call(
                        tool_use_id=str(block.get("id")),
                        name=str(block.get("name")),
                        tool_input=block.get("input")
                        if isinstance(block.get("input"), dict)
                        else {},
                        cwd=str(entry.get("cwd") or ""),
                    )
                )
    return calls, reminded


def reached(call: Call, *, project: Path, corpora: list[str]) -> tuple[str, ...]:
    spec_reminder = CLAUDE_CODE.search_reminder
    if spec_reminder is None:
        return ()
    payload = {"tool_name": call.name, "tool_input": call.tool_input, "cwd": call.cwd}
    searched = reminder._searched(payload, spec_reminder, scope_dir=project)
    return corpora_reached(searched, project=str(project), corpora=corpora) if searched else ()


def searches_documents(call: Call, corpora: tuple[str, ...]) -> bool:
    if not call.name.endswith(_SEARCH_TOOL):
        return False
    scope = call.tool_input.get("knowledge_bases")
    if not isinstance(scope, list):
        return True
    return any(str(name).lower() in corpora for name in scope)


def never_reminded(path: Path) -> bool:
    """Whether the transcript is an agent the hook never reminds: the documenter, which searches
    the module it documents and its corpus by instruction, would fill the unreminded arm with
    searches no throttle left alone. Its type is in the `.meta.json` beside its transcript."""
    meta = path.with_suffix(".meta.json")
    try:
        agent_type = json.loads(meta.read_text(encoding="utf-8")).get("agentType")
    except (OSError, ValueError, AttributeError):
        return False
    return agent_type in (reminder.DOCUMENTER_AGENT_TYPE, reminder.ORCHESTRATOR_AGENT_TYPE)


def outcomes(project: Path, window: int) -> Iterator[tuple[bool, bool]]:
    """(reminded, followed) for every search that reached a documented module."""
    corpora = [name for name in registered(project) if module_of(name) is not None]
    for path in sorted(transcripts(project).rglob("*.jsonl")):
        if never_reminded(path):
            continue
        calls, reminded = read(path)
        for index, call in enumerate(calls):
            hit = reached(call, project=project, corpora=corpora)
            if not hit:
                continue
            following = calls[index + 1 : index + 1 + window]
            yield (
                call.tool_use_id in reminded,
                any(searches_documents(later, hit) for later in following),
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--window", type=int, default=5)
    arguments = parser.parse_args()
    counts = {(r, f): 0 for r in (True, False) for f in (True, False)}
    for outcome in outcomes(arguments.project.resolve(), arguments.window):
        counts[outcome] += 1
    for label, was in (("reminded", True), ("unreminded", False)):
        total = counts[(was, True)] + counts[(was, False)]
        rate = f"{counts[(was, True)] / total:.1%}" if total else "—"
        print(
            f"{label:<11} searches {total:>5}  followed within {arguments.window}: "
            f"{counts[(was, True)]:>5}  ({rate})"
        )


if __name__ == "__main__":
    main()
