"""Replay the find-replace guard over this repository's own Claude Code transcripts.

`design/build-plan.md` §M37 done-when 2: every `Bash` `tool_input.command` the transcripts hold,
subagents included, judged by `zikaron.guard.decision.decide` under the call's recorded `cwd` and
this machine's `$TMPDIR`. Prints the counts and the would-be denies by class; `--dump PATH` writes
every would-be deny verbatim, with its class, to a local file — the transcripts are this machine's
and are not published.

Row 6's file read never touches this machine's disk, whose scratch files are long gone or belong
to later sessions: a scratch script is read as the session's latest `Write` of that path left it,
and as nothing otherwise. `--all-projects` replays every project under `~/.claude/projects/`
except the edit-guard live test's own arms.

Run: .venv/bin/python experiments/m37_guard_replay.py [--project DIR | --all-projects] [--dump PATH]
"""

import argparse
import collections
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

from zikaron.guard.decision import Deny, all_matches, decide
from zikaron.guard.heredoc import delimit
from zikaron.guard.scratch import Location

#: Write calls quoted inside a string literal, as a test of the guard itself writes them.
_GUARD_UNDER_TEST = re.compile(r"m37_guard|zikaron\.guard|edit-guards")
_JOB_TMP = re.compile(r"/\.claude/jobs/[^/]+/tmp(?:/|$)")


def transcripts(project: Path) -> Path:
    return Path.home() / ".claude" / "projects" / str(project.resolve()).replace("/", "-")


def bash_calls(root: Path) -> Iterator[tuple[dict[str, str], dict[str, str]]]:
    """Each Bash call, with what the transcript's `Write` calls had written by then, by path."""
    for path in sorted(root.rglob("*.jsonl")):
        written: dict[str, str] = {}
        for line in path.open(encoding="utf-8", errors="replace"):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = record.get("message")
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                tool_input = block.get("input") or {}
                if block.get("name") == "Write" and isinstance(tool_input.get("content"), str):
                    written[str(tool_input.get("file_path"))] = tool_input["content"]
                command = tool_input.get("command")
                if block.get("name") != "Bash" or not isinstance(command, str):
                    continue
                if isinstance(record.get("cwd"), str):
                    call = {
                        "command": command,
                        "cwd": record["cwd"],
                        "session": f"{root.name}/{str(path.relative_to(root)).split('/')[0]}",
                    }
                    yield call, written


def roots(project: Path, *, every: bool) -> list[Path]:
    if not every:
        return [transcripts(project)]
    base = Path.home() / ".claude" / "projects"
    return sorted(p for p in base.iterdir() if p.is_dir() and "-story" not in p.name)


def reading(call: dict[str, str], deny: Deny) -> str:
    """A deny's class, and so its reading: every class but `true` is a false deny."""
    paths = deny.match.authored_paths
    if _GUARD_UNDER_TEST.search(call["command"]) and not paths:
        return "false: a write call quoted in a string, testing the guard"
    if _GUARD_UNDER_TEST.search(call["command"]) and all("{" in p or "'" in p for p in paths):
        return "false: a write call quoted in a string, testing the guard"
    if paths and all(_JOB_TMP.search(p) for p in paths):
        return "false: a Claude Code job's own tmp directory"
    if paths and all(not p.startswith(call["cwd"].rstrip("/") + "/") for p in paths):
        return "true: an authored file outside the session's project"
    if not paths:
        return "true: a write whose target the rules cannot resolve (a loop or a parameter)"
    return "true: an authored file of the session's project"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--all-projects", action="store_true")
    parser.add_argument("--dump", type=Path)
    args = parser.parse_args()
    tmpdir = os.environ.get("TMPDIR")
    counts: collections.Counter[str] = collections.Counter()
    classes: collections.Counter[str] = collections.Counter()
    forms: collections.Counter[str] = collections.Counter()
    sessions: dict[str, set[str]] = collections.defaultdict(set)
    denies = []
    calls = (
        each for root in roots(args.project, every=args.all_projects) for each in bash_calls(root)
    )
    for call, written in calls:
        location = Location(call["cwd"], tmpdir)
        counts["commands"] += 1
        if all_matches(delimit(call["command"].split("\n")), location, read=written.get):
            counts["a form matched"] += 1
        decision = decide(call["command"], location, read=written.get)
        counts[type(decision).__name__] += 1
        if isinstance(decision, Deny):
            label = reading(call, decision)
            classes[label] += 1
            forms[decision.match.form.name] += 1
            sessions[label].add(call["session"])
            denies.append({**call, "form": decision.match.form.name, "reading": label})
    print(json.dumps(counts, indent=1))
    print(json.dumps(forms, indent=1))
    for label, count in classes.most_common():
        print(f"{count:5}  in {len(sessions[label]):3} sessions  {label}")
    if args.dump:
        args.dump.write_text(json.dumps(denies, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
