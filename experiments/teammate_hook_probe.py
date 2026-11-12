"""Which Claude Code hooks fire for an agent-team teammate, with what payload, and what reaches it.

`setup DIR` writes a throwaway project: one logging hook registered on every event a teammate
push could ride, each returning a fresh nonce in `additionalContext`, and a haiku teammate
definition that only follows the lead's steps. Agent teams run interactively only, so an
operator drives the session from `DIR/PROBE.md`. `analyze DIR` then reads the hook log and every
transcript the payloads name, and reports per event: who fired it, its payload keys, whether the
payload and environment session ids agree, and where each nonce landed — in a
`hook_additional_context` attachment, the harness's record of what it injected, and in an
`api-request-blob` row, its record of what it sent to the model. Neither model is asked about
its context, and the injected text reads as an ordinary hook's: a prompt asking a model to list
what is in its context was refused as `reasoning_extraction` on 2026-11-09, and the transcripts
answer the question without it.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HOOK_SOURCE = r"""#!/usr/bin/env python3
import glob, json, os, secrets, sys, time

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook-log.jsonl")
CONTEXT_EVENTS = {"SessionStart", "UserPromptSubmit", "SubagentStart", "PreToolUse", "PostToolUse"}
SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "AUTH", "PASSWORD")
STATIC = "hookcheck-static"

raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except ValueError:
    payload = {"_unparsed": raw[:2000]}
event = payload.get("hook_event_name") or "?"
who = payload.get("agent_type") or "main"
static = sys.argv[1:] == ["static"]
if static:
    nonce = STATIC
elif event in CONTEXT_EVENTS:
    nonce = f"hookcheck-{event}-{who}-{secrets.token_hex(3)}"
else:
    nonce = None


def trim(value):
    text = json.dumps(value)
    return value if len(text) <= 4000 else text[:4000] + "...[trimmed]"


def last_user_text(path):
    lines, text = 0, None
    with open(path) as fh:
        for line in fh:
            lines += 1
            try:
                row = json.loads(line)
            except ValueError:
                continue
            content = (row.get("message") or {}).get("content")
            if row.get("type") == "user" and isinstance(content, str):
                text = content[:400]
    return {"path": path, "lines": lines, "last_user_text": text}


def snapshot():
    # What a push keyed on the incoming message could read at the moment this hook runs: the
    # payload names no message, so the candidates are the teammate's transcript and its inbox.
    snap = {"agent_transcripts": [], "inboxes": {}}
    tp, aid = payload.get("transcript_path"), payload.get("agent_id")
    if isinstance(tp, str) and isinstance(aid, str):
        sub = os.path.join(os.path.splitext(tp)[0], "subagents")
        for path in glob.glob(os.path.join(sub, "agent-*.jsonl")):
            if aid in os.path.basename(path):
                snap["agent_transcripts"].append(last_user_text(path))
    sid = str(payload.get("session_id") or "")
    for path in glob.glob(os.path.expanduser(f"~/.claude/teams/session-{sid[:8]}/inboxes/*.json")):
        try:
            with open(path) as fh:
                entries = json.load(fh)
        except (OSError, ValueError) as exc:
            snap["inboxes"][path] = repr(exc)
            continue
        last = entries[-1] if isinstance(entries, list) and entries else entries
        snap["inboxes"][path] = {
            "entries": len(entries) if isinstance(entries, list) else None,
            "last": json.dumps(last)[:600],
        }
    return snap


try:
    with open(f"/proc/{os.getppid()}/cmdline", "rb") as fh:
        parent_cmd = fh.read().replace(b"\0", b" ").decode(errors="replace")[:300]
except OSError:
    parent_cmd = None
record = {
    "ts": time.time(),
    "event": event,
    "nonce": nonce,
    "pid": os.getpid(),
    "ppid": os.getppid(),
    "parent_cmd": parent_cmd,
    "env": {
        k: v
        for k, v in os.environ.items()
        if k.startswith("CLAUDE") and not any(m in k.upper() for m in SECRET_MARKERS)
    },
    "payload": {k: trim(v) for k, v in payload.items()},
    "handler": "static" if static else "nonce",
}
if event == "SubagentStart" and not static:
    try:
        record["snapshot"] = snapshot()
    except Exception as exc:
        record["snapshot"] = repr(exc)
with open(LOG, "a") as fh:
    fh.write(json.dumps(record) + "\n")
if nonce:
    marker = f"Project hook ran ({nonce})."
    context = {"hookEventName": event, "additionalContext": marker}
    sys.stdout.write(json.dumps({"hookSpecificOutput": context}))
"""

#: The fixed text the second `SubagentStart` handler returns; `HOOK_SOURCE` spells it too.
STATIC = "hookcheck-static"

#: Every event a per-message teammate push could ride, plus the lifecycle events that bracket one.
#: The tool events are limited to `Bash` so the lead's own messaging does not drown the log.
#: `SubagentStart` also gets a second handler returning the same text every time: the docs say a
#: re-run injects only when the context does not already hold that copy, so the fixed text
#: measures that deduplication while the nonce handler measures whether new text gets through.
EVENTS: dict[str, str | None] = {
    "SessionStart": None,
    "UserPromptSubmit": None,
    "SubagentStart": None,
    "SubagentStop": None,
    "PreToolUse": "Bash",
    "PostToolUse": "Bash",
    "TeammateIdle": None,
    "TaskCompleted": None,
    "Stop": None,
}

TEAMMATE_DEFINITION = """---
name: probe-mate
description: Test teammate for a hook-instrumentation check in a scratch project
model: haiku
tools: Bash, Read
---
You are a teammate in a scratch project used to test hook wiring. Do exactly the steps each
message gives you, reply to team-lead as the step says, and nothing more.
"""

#: How each backend's session is started. Each backend gets a directory of its own, so the two
#: runs' hook logs never mix and either can be analysed without the other.
LAUNCH = {
    "in-process": "    cd {dir}\n    claude --model sonnet --teammate-mode in-process",
    "tmux": "    tmux new -s probe\n    cd {dir}\n    claude --model sonnet --teammate-mode tmux",
}

#: One line, so it pastes as one prompt with no quote markers or hard wraps in it.
PASTE_PROMPT = (
    "Spawn one teammate named mate-1 of agent type probe-mate with this message: "
    "\"Run `echo one` with Bash, then send team-lead the message 'A done'. Then wait.\" "
    "When mate-1 replies, send it: "
    "\"Run `echo two` with Bash, then send team-lead 'B done'. Then wait.\" "
    "When it replies, send it: \"Send team-lead 'C done'.\" "
    "When it replies, ask it to shut down, and tell me once it has."
)

PROBE_STEPS = """# Teammate hook probe — {backend} teammates — operator steps

One interactive session in this directory. Make sure you are logged in first. Start it with:

{launch}

Paste this as the first prompt:

```text
{prompt}
```

Use a fresh session: the classifier judges the whole conversation, so a session that was refused
once stays refused.

Then exit (`/exit`) and tell memory-researcher this run is done; it runs
`python experiments/teammate_hook_probe.py analyze {dir}`.
"""


def setup(target: Path, backend: str) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    hook = target / "probe_hook.py"
    hook.write_text(HOOK_SOURCE)
    command = f"python3 {hook}"
    hooks: dict[str, list[dict[str, object]]] = {}
    for event, matcher in EVENTS.items():
        handlers = [{"type": "command", "command": command}]
        if event == "SubagentStart":
            handlers.append({"type": "command", "command": f"{command} static"})
        group: dict[str, object] = {"hooks": handlers}
        if matcher is not None:
            group["matcher"] = matcher
        hooks[event] = [group]
    settings = {"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}, "hooks": hooks}
    (target / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    (target / ".claude" / "agents" / "probe-mate.md").write_text(TEAMMATE_DEFINITION)
    launch = LAUNCH[backend].format(dir=target)
    steps = PROBE_STEPS.format(dir=target, backend=backend, launch=launch, prompt=PASTE_PROMPT)
    (target / "PROBE.md").write_text(steps)
    print(f"wrote probe project to {target}; operator steps in {target / 'PROBE.md'}")


def _transcripts(paths: set[str]) -> list[Path]:
    found: set[Path] = set()
    for p in paths:
        main = Path(p)
        if main.exists():
            found.add(main)
        sub = main.with_suffix("") / "subagents"
        if sub.is_dir():
            found.update(sub.glob("*.jsonl"))
    return sorted(found)


Evidence = dict[str, list[str]]


def _evidence(transcripts: list[Path], nonces: set[str]) -> tuple[Evidence, Evidence]:
    """Map each nonce to the transcripts that attached it, and to those that sent it to the model.

    Each list has one entry per row carrying the nonce, so the fixed text's attachment list counts
    its injections; every other nonce is unique to one hook call. A request blob stores content
    once per hash, so a sent count is a floor, not a number of requests.
    """
    attached: Evidence = collections.defaultdict(list)
    sent: Evidence = collections.defaultdict(list)
    for path in transcripts:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("type") == "api-request-blob":
                text = json.dumps(row.get("message"))
                for nonce in nonces:
                    if nonce in text:
                        sent[nonce].append(path.name)
                continue
            attachment = row.get("attachment") or {}
            if attachment.get("type") != "hook_additional_context":
                continue
            text = " ".join(str(part) for part in attachment.get("content") or [])
            for nonce in nonces:
                if nonce in text:
                    attached[nonce].append(path.name)
    return attached, sent


def analyze(target: Path) -> None:
    log = target / "hook-log.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    transcripts = _transcripts(
        {str(r["payload"]["transcript_path"]) for r in records if "transcript_path" in r["payload"]}
    )
    attached, sent = _evidence(transcripts, {str(r["nonce"]) for r in records if r["nonce"]})
    print(f"{len(records)} hook calls; transcripts: {[t.name for t in transcripts]}\n")
    keys: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    static_calls: collections.Counter[str] = collections.Counter()
    for r in records:
        p = r["payload"]
        who = str(p.get("agent_type") or "main")
        if r.get("handler") == "static":
            static_calls[who] += 1
            continue
        keys[(r["event"], who)].update(p)
        env_sid = r["env"].get("CLAUDE_CODE_SESSION_ID")
        sid = p.get("session_id")
        nonce = r["nonce"]
        got = (",".join(attached.get(nonce, [])) or "NOWHERE") if nonce else "-"
        went = (",".join(sorted(set(sent.get(nonce, [])))) or "NOWHERE") if nonce else "-"
        print(
            f"{r['event']:<17} who={who:<10} agent_id={str(p.get('agent_id'))[:18]:<18} "
            f"sid={'env==payload' if env_sid == sid else f'DIVERGE env={env_sid} payload={sid}'} "
            f"pid={r['pid']} attached_in={got} sent_in={went}"
        )
        snap = r.get("snapshot")
        if isinstance(snap, dict):
            for t in snap["agent_transcripts"]:
                text = (t["last_user_text"] or "")[:160].replace("\n", " ")
                print(f"    agent transcript {t['lines']} lines, last user text: {text!r}")
            for path, inbox in snap["inboxes"].items():
                print(f"    inbox {Path(path).name}: {inbox}")
        elif snap is not None:
            print(f"    snapshot failed: {snap}")
    print(f"\nfixed-text SubagentStart calls per agent: {dict(static_calls)}")
    print(f"fixed-text attachments: {collections.Counter(attached.get(STATIC, []))}")
    print(f"fixed-text request blobs: {collections.Counter(sent.get(STATIC, []))}")
    print("\npayload keys per (event, who):")
    for (event, who), ks in sorted(keys.items()):
        print(f"  {event}/{who}: {sorted(ks)}")


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
