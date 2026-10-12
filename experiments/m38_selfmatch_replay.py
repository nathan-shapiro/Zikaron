"""Replay the self-match rule, shipped and prototype, over every Claude Code transcript here.

`design/build-plan.md` §M38 item 6: every `Bash` and `Monitor` `tool_input.command` the
transcripts hold, subagents included, judged in one pass by `zikaron.guard.selfmatch` on `linux`
and by the prototype the brief's counts came from (`experiments/m38_selfmatch_prototype.py`).
Each command is labelled by what its transcript recorded: `exit 143`/`exit 144` (the shell was
signalled) and the rest.

Prints the counts from that pass and every command on which the two disagree, with both
verdicts; `--dump PATH` writes every would-be deny, every signalled miss and every disagreement
verbatim to a local file — the transcripts are this machine's and are not published.

Run: .venv/bin/python experiments/m38_selfmatch_replay.py [--dump PATH] [--exclude-session ID]
"""

import argparse
import collections
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from m38_selfmatch_prototype import judge, quoted_substitution  # noqa: E402

from zikaron.guard.heredoc import delimit  # noqa: E402
from zikaron.guard.selfmatch import first_self_match  # noqa: E402

_ROOT = Path.home() / ".claude" / "projects"
_SIGNALLED = re.compile(r"Exit code (14[34])\b")
#: `tests/test_guard_claude_live.py`'s throwaway projects, whose commands are the guards' own tests.
_LIVE_TESTS = "zikaron-live-tests"


def _calls(exclude: str | None = None) -> Iterator[tuple[str, str, str]]:
    """Each Bash or Monitor command, its tool name and what its result recorded — leaving out the
    session `exclude` names, subagents included, and the live tests' projects, whose probes are
    deliberate self-matches."""
    uses: dict[str, tuple[str, str]] = {}
    results: dict[str, str] = {}
    for path in sorted(_ROOT.rglob("*.jsonl")):
        if exclude is not None and any(part.startswith(exclude) for part in path.parts):
            continue
        if any(_LIVE_TESTS in part for part in path.parts):
            continue
        for line in path.open(encoding="utf-8", errors="replace"):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in ("Bash", "Monitor"):
                    command = (block.get("input") or {}).get("command")
                    if isinstance(command, str):
                        uses[str(block.get("id"))] = (str(block.get("name")), command)
                elif block.get("type") == "tool_result":
                    content = block.get("content")
                    if isinstance(content, list):
                        content = " ".join(
                            str(part.get("text", "")) for part in content if isinstance(part, dict)
                        )
                    results[str(block.get("tool_use_id"))] = str(content)[:4000]
    for use_id, (tool, command) in uses.items():
        yield tool, command, results.get(use_id, "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path)
    parser.add_argument("--exclude-session", help="a session id whose transcripts are left out")
    args = parser.parse_args()
    counts: collections.Counter[str] = collections.Counter()
    dump: list[str] = []
    disagreements: list[str] = []
    for tool, command, result in _calls(args.exclude_session):
        counts[f"commands ({tool})"] += 1
        signalled = _SIGNALLED.search(result)
        status = f"exit {signalled.group(1)}" if signalled else "other"
        verdicts = judge(command)
        prototype = any(verdict.outcome == "deny" for verdict in verdicts)
        found = first_self_match(delimit(command.split("\n")), command, "linux")
        shipped = found is not None
        if quoted_substitution(command):
            counts[
                "commands with pgrep/pkill -f inside a double-quoted $(…)"
                + (", denied for another occurrence" if shipped else ", otherwise silent")
            ] += 1
        for verdict in verdicts:
            counts[f"prototype, per call: {verdict.call.name}: {verdict.outcome}"] += 1
        counts[f"shipped: commands {'denied' if shipped else 'silent'}, {status}"] += 1
        counts[f"prototype: commands {'denied' if prototype else 'silent'}, {status}"] += 1
        if shipped != prototype:
            counts["disagreements"] += 1
            line = f"shipped={'deny' if shipped else 'silent'}\tprototype={[v.outcome for v in verdicts]}\t{command!r}"
            disagreements.append(line)
            dump.append(f"DISAGREE\t{line}")
        if found is not None:
            dump.append(f"DENY\t{status}\t{tool}\t{found.excerpt!r}\t{command!r}")
        elif signalled and re.search(r"\bp(?:grep|kill)\b", command):
            dump.append(f"SILENT-SIGNALLED\t{status}\t{command!r}")
    for key in sorted(counts):
        print(f"{counts[key]:7d}  {key}")
    for line in disagreements:
        print(line)
    if args.dump is not None:
        args.dump.write_text("\n".join(dump) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
