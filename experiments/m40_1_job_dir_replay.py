"""Replay the find-replace guard over every local command that names a background job's directory.

`design/build-plan.md` §M40-1, item 5 and done-when 2: every `Bash` command in every project's
Claude Code transcripts, subagents included, that names `CLAUDE_JOB_DIR` or a path under
`~/.claude/jobs/` spelled out from `/`, judged by `zikaron.guard.decision.decide` under its
recorded `cwd`, `$TMPDIR` unset — as a background job's hook sees it — and the job's directory as
`CLAUDE_JOB_DIR`, named by the session id's first eight characters, as Claude Code names it. The
transcripts of every checkout of this repository are left out, since they quote such commands in
discussion. A pair
of command and `cwd` counts once, and the counts grow with the transcripts, so a before and an
after are compared only when taken together. Prints the counts and the denies by
`m37_guard_replay.reading`'s class, whose `false: a Claude Code job's own tmp directory` is the
class this change must empty but for the stated false deny of a `cd` through the variable, which
`classify` names; `--dump PATH` writes every deny verbatim, with its class, to a local file — the
transcripts are this machine's and are not published.

`--no-job-dirs` judges with no job directory. The counts from before the change are that run's
with `PYTHONPATH` naming a checkout of the commit before it, whose rules ignore job directories.

Run: .venv/bin/python experiments/m40_1_job_dir_replay.py [--no-job-dirs] [--dump PATH]
"""

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path

from m37_guard_replay import bash_calls, reading, transcripts

from zikaron.guard.decision import Deny, decide
from zikaron.guard.scratch import Location

_JOBS = Path.home() / ".claude" / "jobs"
_JOB_TMP_SPELLED = re.compile(r"\$\{?CLAUDE_JOB_DIR\}?/tmp(?:/|$)")


def this_repositorys_keys() -> set[str]:
    """The transcript directory of every checkout of this repository, main and worktrees alike:
    each one's sessions quote such commands in discussion."""
    argv = ["git", "-C", str(Path(__file__).resolve().parent), "worktree", "list", "--porcelain"]
    # A fixed argv naming this file's own directory; `git` from `PATH`, as a developer runs it.
    listing = subprocess.run(argv, capture_output=True, text=True, check=True).stdout  # noqa: S603
    prefix = "worktree "
    return {
        transcripts(Path(line.removeprefix(prefix))).name
        for line in listing.splitlines()
        if line.startswith(prefix)
    }


def names_a_job_directory(command: str) -> bool:
    return "CLAUDE_JOB_DIR" in command or f"{_JOBS}/" in command


def classify(call: dict[str, str], deny: Deny) -> str:
    """`reading`'s class, except that a deny naming only paths spelled through the variable is a
    job's own tmp directory too: the rules read the spelling as a path under the `cwd`."""
    paths = deny.match.authored_paths
    if paths and all(_JOB_TMP_SPELLED.search(p) for p in paths):
        return "false: a Claude Code job's own tmp directory, spelled through the variable"
    return reading(call, deny)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-job-dirs", action="store_true")
    parser.add_argument("--dump", type=Path)
    args = parser.parse_args()
    base = Path.home() / ".claude" / "projects"
    excluded = this_repositorys_keys()
    seen: set[tuple[str, str]] = set()
    counts: collections.Counter[str] = collections.Counter()
    classes: collections.Counter[str] = collections.Counter()
    denies = []
    for root in sorted(p for p in base.iterdir() if p.is_dir() and p.name not in excluded):
        for call, written in bash_calls(root):
            key = (call["command"], call["cwd"])
            if not names_a_job_directory(call["command"]) or key in seen:
                continue
            seen.add(key)
            session = call["session"].split("/")[1][:8]
            if args.no_job_dirs:
                location = Location(call["cwd"])
            else:
                location = Location(call["cwd"], job_dir=str(_JOBS / session))
            counts["commands"] += 1
            # The find-replace rule alone, as `m37_guard_replay` judges it.
            decision = decide(call["command"], location, platform="", read=written.get)
            if isinstance(decision, Deny):
                counts["denied"] += 1
                label = classify(call, decision)
                classes[label] += 1
                denies.append({**call, "form": decision.match.form.name, "reading": label})
    print(json.dumps(counts, indent=1))
    for label, count in classes.most_common():
        print(f"{count:5}  {label}")
    if args.dump:
        args.dump.write_text(json.dumps(denies, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
