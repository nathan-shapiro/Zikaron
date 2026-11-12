"""M43 done-when 3, first part: what the instruction gate costs a tool call with no marker pending.

Three arms, interleaved round-robin so each sees the same load: the gate's own shell line with no
marker pending; a bare `sh -c true`, the floor any hook entry pays to be spawned at all; and
`zikaron-hook` run ungated on the same payload, which finds no marker and exits — what every tool
call would cost without the gate. Each is a subprocess timed with `perf_counter` on both sides, as
`research/owed-measurements-2026-10-30.md` §5 timed the existing hooks. Results:
`research/teammate-hook-probe.md` §"The gate's cost per tool call".

    .venv/bin/python experiments/m43_gate_cost.py [rounds]
"""

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from zikaron.harness.spec import CLAUDE_CODE
from zikaron.install.entries import instruction_gate_command

REPO = Path(__file__).resolve().parents[1]
SESSION = "6ce78ba4-beb9-485f-b46d-fd39b8ed5073"


def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    hook = REPO / ".venv" / "bin" / "zikaron-hook"
    with tempfile.TemporaryDirectory() as scratch:
        project = Path(scratch) / "project"
        (project / ".zikaron" / "instruction-pending").mkdir(parents=True, mode=0o700)
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "CLAUDECODE": "1",
            "CLAUDE_PROJECT_DIR": str(project),
            "CLAUDE_CODE_SESSION_ID": SESSION,
        }
        payload = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": SESSION,
                "agent_id": "a1",
                "agent_type": "general-purpose",
                "cwd": str(project),
                "transcript_path": str(project / "t.jsonl"),
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
            }
        ).encode()
        arms = {
            "gate, no marker": ["/bin/sh", "-c", instruction_gate_command(hook, CLAUDE_CODE)],
            "sh -c true": ["/bin/sh", "-c", "true"],
            "zikaron-hook ungated": [str(hook)],
        }
        times: dict[str, list[float]] = {name: [] for name in arms}
        for _ in range(rounds):
            for name, argv in arms.items():
                started = time.perf_counter()
                subprocess.run(argv, input=payload, env=env, cwd=project, check=True)  # noqa: S603
                times[name].append((time.perf_counter() - started) * 1000)
        for name, samples in times.items():
            ordered = sorted(samples)
            p90 = ordered[int(0.9 * (len(ordered) - 1))]
            print(
                f"{name:<22} median {statistics.median(samples):7.2f} ms  "
                f"p90 {p90:7.2f}  max {max(samples):7.2f}  n={len(samples)}"
            )
        print(f"load average at end: {os.getloadavg()}")


if __name__ == "__main__":
    main()
