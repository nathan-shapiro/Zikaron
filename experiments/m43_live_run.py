"""M43 done-when 2: the instruction push in live Claude Code sessions, operator-driven.

`setup DIR --backend {in-process,tmux,default-mode}` makes a throwaway project with Zikaron
installed from **this checkout's** `.venv` — never one a real project runs — a store, agent teams
switched on, and a teammate and a helper definition, then writes the operator's steps to
`DIR/RUN.md`. No step asks a model to report its context: every finding is read from what the
harness and the store recorded, which `analyze DIR` does — the pushes each agent's transcript holds
and on which tool call, each pushed agent's fetches and replies, the `surface_call` rows by
`occasion`, `hook.log`, the markers left — and
from a logging hook of the kit's own beside Zikaron's, which records at hook time the payload
facts done-when 2 asks for: each event's agent identity and permission mode, whether the agent's
transcript existed and how its tail parsed, whether its record and the call's `tool_use` block were
already written, and when each `SubagentStart` fired.
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = REPO / ".venv" / "bin" / "python"
ZIKARON = REPO / ".venv" / "bin" / "zikaron"
BLOCK_HEADER = "<zikaron-memories>"
CONSOLIDATOR = "zikaron-consolidator"
CONSOLIDATOR_TOOL_PREFIX = "mcp__zikaron-consolidator__"
TOOL_TRIGGER = "PreToolUse"
REPORT_TOOLS = ("SendMessage", "SubagentHandback")

#: The kit's own hook: it prints nothing, and appends what the payload and the transcript held at
#: the moment it ran to `hooks.jsonl` beside it.
LOGGER = r"""#!/usr/bin/env python3
import json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
payload = json.loads(sys.stdin.read() or "{}")
agent_id = payload.get("agent_id")
session_transcript = payload.get("transcript_path") or ""
stem = os.path.splitext(session_transcript)[0]
transcript = (
    os.path.join(stem, "subagents", f"agent-{agent_id}.jsonl") if agent_id else session_transcript
)
last_type, tool_use_ids, rows, lines = None, [], [], []
exists = os.path.exists(transcript)
try:
    with open(transcript, encoding="utf-8") as handle:
        lines = [line for line in handle if line.strip()]
except OSError:
    pass
unparsed = []
for number, line in enumerate(lines):
    try:
        rows.append(json.loads(line))
    except ValueError:
        unparsed.append(number)
if rows:
    last_type = rows[-1].get("type")
for row in rows[-6:]:
    content = (row.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_use_ids.append(block.get("id"))
record = {
    "ts": time.time(),
    "event": payload.get("hook_event_name"),
    "session_id": payload.get("session_id"),
    "agent_id": agent_id,
    "agent_type": payload.get("agent_type"),
    "permission_mode": payload.get("permission_mode"),
    "source": payload.get("source"),
    "tool_name": payload.get("tool_name"),
    "tool_use_id": payload.get("tool_use_id"),
    "meta_exists": bool(agent_id)
    and os.path.exists(os.path.join(stem, "subagents", f"agent-{agent_id}.meta.json")),
    "transcript_exists": exists,
    "transcript_last_type": last_type,
    "partial_tail": unparsed == [len(lines) - 1],
    "unparsed_lines": len(unparsed),
    "tool_use_written": payload.get("tool_use_id") in tool_use_ids,
}
with open(os.path.join(here, "hooks.jsonl"), "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\n")
"""

LOGGED_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "TeammateIdle",
    "PreToolUse",
)

MATE = """---
name: m43-mate
description: A teammate for the M43 live run in a scratch project
model: haiku
---
You are a teammate in a scratch project. Do what each message asks, reply to team-lead with
SendMessage as the message says, and nothing more.
"""

HELPER = """---
name: m43-helper
description: An ordinary subagent for the M43 live run in a scratch project
model: haiku
---
Do what you are asked in this scratch project and report back briefly.
"""

SEED = (
    "Record these three facts about this project with zikaron_memory_remember, one record each, "
    "each with a short headline: the probe build runs with `make probe-build` and never plain "
    "`make`, because plain make deletes the fixtures; the tests need the PROBE_TOKEN environment "
    "variable set to any value, or they skip silently; deploys go through `scripts/ship.sh`, "
    "which must be run from the repository root."
)

TEAM = (
    "Spawn two teammates together, of agent type m43-mate, named alpha and beta. Tell alpha: "
    '"Run `ls` with Bash, then tell team-lead in one line how the probe build should be run in '
    'this project. Then wait." Tell beta: "Run `pwd` with Bash, then tell team-lead in one line '
    'which environment variable the tests need. Then wait."'
)

#: Claude Code refuses a bare `sleep` before any hook fires, so the wait is Python's.
SLEEP = "Run `python3 -c 'import time; time.sleep(90)'` with Bash in the foreground, then tell team-lead 'slept'."

#: A lead told to send two messages sends them in one response, before the teammate's turn starts
#: (both in-process runs), so the mid-task message is its own prompt.
MID_TASK_NOTE = (
    "Paste this as soon as the lead's last turn ends, while the teammate is still in its"
    " 90-second sleep."
)

LATER = (
    f'When both have replied: send alpha "{SLEEP}" and send beta "Tell team-lead \'beta here\', '
    'without running anything." Then end your turn, without waiting for their replies.'
)

MID_TASK = (
    'Send alpha this message now, while it is still running: "Also tell team-lead how deploys '
    'are run here." Then wait for the replies from alpha and beta.'
)

HELPER_STEP = (
    "Spawn one subagent of type m43-helper, with no name, asking it to run `date` with Bash and "
    "report how deploys are run here. When it has reported, send that same subagent a second "
    "prompt, asking it to run `whoami` with Bash and report which environment variable the tests "
    "need."
)

CONSOLIDATE_AS_SHIPPED = "Run /zikaron-consolidate."

CONSOLIDATE_BY_NAME = (
    "Spawn the zikaron-consolidator subagent with the name consolidate-now, giving it this "
    "prompt: \"Consolidate this project's memory journal. Work through every group until "
    'zikaron_memory_next_group answers {\\"done\\": true}, then report what you did."'
)

SHUTDOWN = "Ask every teammate to shut down, and tell me once they have."

LAUNCH = {
    "in-process": "claude --model sonnet --teammate-mode in-process",
    "tmux": "claude --model sonnet --teammate-mode tmux",
    "default-mode": "claude --model sonnet --teammate-mode in-process --permission-mode default",
}

DEFAULT_MODE_TEAM = (
    'Spawn one teammate of agent type m43-mate named gamma. Tell gamma: "Run `touch made-by-gamma` '
    "with Bash, then tell team-lead in one line how the probe build should be run here. Then "
    f'wait." When gamma has replied, send it "{SLEEP}" Then end your turn, without waiting for its '
    "reply."
)

DEFAULT_MODE_MID_TASK = (
    'Send gamma this message now, while it is still running: "Also tell team-lead how deploys '
    'are run here." Then wait for its replies, and ask it to shut down.'
)


UNTYPED_TEAMMATE = (
    'Spawn one more teammate named delta, giving it no agent type, with this message: "Run `ls` '
    'with Bash, then tell team-lead in one line how deploys are run here. Then wait." When it has '
    "replied, ask it to shut down."
)


def _steps(backend: str) -> list[tuple[str, str]]:
    """Each step's prompt, beside a note for the operator or the empty string."""
    if backend == "default-mode":
        return [(SEED, ""), (DEFAULT_MODE_TEAM, ""), (DEFAULT_MODE_MID_TASK, MID_TASK_NOTE)]
    steps = [(SEED, ""), (TEAM, ""), (LATER, ""), (MID_TASK, MID_TASK_NOTE), (HELPER_STEP, "")]
    if backend == "in-process":
        steps.append((CONSOLIDATE_AS_SHIPPED, ""))
    if backend == "tmux":
        steps.append((UNTYPED_TEAMMATE, ""))
    steps += [(CONSOLIDATE_BY_NAME, ""), (SHUTDOWN, "")]
    return steps


def setup(target: Path, backend: str) -> None:
    if target.exists():
        message = f"{target} exists; each run gets a fresh directory"
        raise SystemExit(message)
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    subprocess.run([str(ZIKARON), "init", "--project", str(target)], check=True)
    subprocess.run(
        [
            str(PYTHON),
            "-m",
            "zikaron.install",
            "--project",
            str(target),
            "--harness",
            "claude-code",
            "--components",
            "memory",
        ],
        check=True,
    )
    agents = target / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / "m43-mate.md").write_text(MATE, encoding="utf-8")
    (agents / "m43-helper.md").write_text(HELPER, encoding="utf-8")
    logger = target / "m43_logger.py"
    logger.write_text(LOGGER, encoding="utf-8")
    group = {"hooks": [{"type": "command", "command": f"python3 '{logger}'", "timeout": 10}]}
    settings = {
        "env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"},
        "hooks": {event: [group] for event in LOGGED_EVENTS},
    }
    (target / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    lines = [
        f"# M43 live run — {backend}",
        "",
        "One fresh interactive session in this directory, logged in. Start it with:",
        "",
        f"    cd {target}",
        f"    {'tmux new -s m43' + chr(10) + '    ' if backend == 'tmux' else ''}{LAUNCH[backend]}",
        "",
        "Paste each prompt in turn, waiting for the lead to finish the one before. Approve any",
        "permission prompt that appears, and note which tool call asked.",
        "",
    ]
    for number, (step, note) in enumerate(_steps(backend), start=1):
        lines += [f"{number}. {note}".rstrip(), "", "```text", step, "```", ""]
    lines += [
        "Then `/exit`, and tell memory-researcher this run is done; it runs",
        f"`.venv/bin/python experiments/m43_live_run.py analyze {target}` in the checkout.",
        "",
    ]
    (target / "RUN.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {target}; the operator's steps are in {target / 'RUN.md'}")


def _transcripts(target: Path) -> list[Path]:
    mangled = str(target).replace("/", "-").replace(".", "-")
    root = Path.home() / ".claude" / "projects" / mangled
    return sorted(root.rglob("*.jsonl")) if root.is_dir() else []


def _pushes(path: Path) -> list[tuple[int, str]]:
    """Each instruction push a transcript records: its line, and the event that carried it."""
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        row = json.loads(line)
        attachment = row.get("attachment") or {}
        if attachment.get("type") != "hook_additional_context":
            continue
        text = " ".join(str(part) for part in attachment.get("content") or [])
        if BLOCK_HEADER in text:
            found.append((number, str(attachment.get("hookEvent"))))
    return found


def _tool_use_already_written(path: Path, line_number: int) -> bool | None:
    """Whether the assistant records just before a push's attachment hold a `tool_use` block."""
    rows = path.read_text(encoding="utf-8").splitlines()[: line_number - 1]
    for line in reversed(rows):
        row = json.loads(line)
        if row.get("type") == "assistant":
            content = (row.get("message") or {}).get("content") or []
            return any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        if row.get("type") == "user":
            return None
    return None


def _calls_the_consolidators_tools(path: Path) -> bool:
    """Whether a transcript's agent called the consolidation verbs — how a consolidator running as a
    session of its own, which has no record naming it, is told from the lead. By its `tool_use`
    blocks, since the skill's expansion and a quoted report name the verbs in the lead's too."""
    for line in path.read_text(encoding="utf-8").splitlines():
        content = (json.loads(line).get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and str(block.get("name", "")).startswith(CONSOLIDATOR_TOOL_PREFIX)
            ):
                return True
    return False


def _uptake(path: Path) -> tuple[int, list[str]]:
    """How many `zikaron_memory_fetch` calls a transcript's agent made, and what it reported back."""
    fetches, replies = 0, []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        content = (row.get("message") or {}).get("content")
        if row.get("type") != "assistant" or not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name, tool_input = str(block.get("name", "")), block.get("input") or {}
            fetches += name.endswith("zikaron_memory_fetch")
            if name in REPORT_TOOLS and isinstance(tool_input.get("message"), str):
                replies.append(tool_input["message"][:160])
    return fetches, replies


def _hook_facts(target: Path) -> None:
    """What the kit's logging hook saw: per event, the payload's identity and mode and, for each
    `PreToolUse`, whether the agent's record and the call's `tool_use` were already written."""
    log = target / "hooks.jsonl"
    if not log.exists():
        print("hooks.jsonl: (none)")
        return
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    start = records[0]["ts"] if records else 0.0
    print("hooks.jsonl, by time:")
    for r in records:
        print(
            f"  +{r['ts'] - start:7.1f}s {r['event']:<13} session={str(r['session_id'])[:8]} "
            f"agent_id={r['agent_id']} agent_type={r['agent_type']} mode={r['permission_mode']} "
            f"source={r['source']} tool={r['tool_name']} meta={r['meta_exists']} "
            f"transcript={r['transcript_exists']} last={r['transcript_last_type']} "
            f"partial_tail={r['partial_tail']} unparsed={r['unparsed_lines']} "
            f"tool_use_written={r['tool_use_written']}"
        )


def analyze(target: Path) -> None:
    store = target / ".zikaron"
    for path in _transcripts(target):
        meta = path.with_suffix("").with_suffix(".meta.json")
        definition = ""
        if meta.exists():
            record = json.loads(meta.read_text(encoding="utf-8"))
            definition = str(
                record.get("spawnedAgentType")
                or record.get("customAgentType")
                or record.get("agentType")
            )
        pushes = _pushes(path)
        marks = [_tool_use_already_written(path, number) for number, _ in pushes]
        consolidator = definition == CONSOLIDATOR or _calls_the_consolidators_tools(path)
        on_tool_calls = [n for n, event in pushes if event == TOOL_TRIGGER]
        flag = "  <-- CONSOLIDATOR PUSHED" if consolidator and on_tool_calls else ""
        print(f"{path.name:<60} {definition:<22} pushes={[(n, e) for n, e in pushes]}")
        print(f"{'':<60} tool_use before each, in file order: {marks}{flag}")
        if on_tool_calls:
            fetches, replies = _uptake(path)
            print(f"{'':<60} fetches: {fetches}")
            for reply in replies:
                print(f"{'':<60} reply: {reply!r}")
    _hook_facts(target)
    database = store / "memory.db"
    if database.exists():
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        rows = connection.execute(
            "SELECT json_extract(detail, '$.occasion'), count(*) FROM event "
            "WHERE kind = 'surface_call' GROUP BY 1"
        ).fetchall()
        connection.close()
        print(f"surface_call by occasion: {rows}")
    log = store / "hook.log"
    print("hook.log:")
    print(log.read_text(encoding="utf-8") if log.exists() else "  (none)")
    pending = store / "instruction-pending"
    print(f"markers left: {sorted(p.name for p in pending.iterdir()) if pending.exists() else []}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    setup_parser = sub.add_parser("setup")
    setup_parser.add_argument("dir", type=Path)
    setup_parser.add_argument("--backend", choices=sorted(LAUNCH), required=True)
    sub.add_parser("analyze").add_argument("dir", type=Path)
    args = parser.parse_args()
    target = args.dir.expanduser().resolve()
    if args.cmd == "setup":
        setup(target, args.backend)
    else:
        analyze(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
