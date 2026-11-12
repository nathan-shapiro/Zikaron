"""M43 done-when 3, last part: a `TOOL_CALL`'s wall time with a marker pending, on the largest
transcript done-when 2's sessions left and on a short one, against a call the gate lets through for
another agent's marker and a call with no marker at all.

Run in one of done-when 2's scratch projects, whose store holds the seed; the prompt hook starts its
service first, and the arms wait until it serves. Each arm is the installed `PreToolUse` entry's
shell line through `subprocess.run`, timed with `perf_counter` on each side, the arms interleaved
round-robin so each sees the same load, as `experiments/m43_gate_cost.py` does. An agent's
transcript is a copy of the one given, or nothing, ending in the tail a response's first call reads;
each marked run sets its marker first and must print a block. Whichever marked arm runs first in a
round pays for the service's having been idle, so `short-first` swaps the two to show it; the reader
is then timed alone. Results: `research/teammate-hook-probe.md` §"Processes per tool call and turn".

    .venv/bin/python experiments/m43_tool_call_time.py PROJECT TRANSCRIPT ROUNDS [short-first]
"""

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from zikaron.harness.spec import CLAUDE_CODE
from zikaron.hook import connect, instruction, instruction_markers
from zikaron.install.entries import instruction_gate_command
from zikaron.service import paths

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / ".venv" / "bin" / "zikaron-hook"
OTHER = "other"
TAIL = [
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": '<teammate-message teammate_id="team-lead">\n'
            "Tell team-lead how the probe build should be run here.\n</teammate-message>",
        },
    },
    {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<system-reminder>x"}},
    {"type": "attachment", "attachment": {"type": "environment"}},
    {"type": "api-request"},
]


def _agent(session_transcript: Path, agent_id: str, prefix: bytes) -> None:
    push = CLAUDE_CODE.instruction_push
    assert push is not None
    transcript = push.agent_file(session_transcript, agent_id, push.transcript_suffix)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    tail = "".join(json.dumps(record) + "\n" for record in TAIL).encode()
    transcript.write_bytes(prefix + tail)
    record = push.agent_file(session_transcript, agent_id, push.record_suffix)
    record.write_text(json.dumps({"agentType": "general-purpose"}), encoding="utf-8")


def _wait_until_serving(store_dir: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connection = connect.connect_if_serving(
            connect.resolve_sock_path(store_dir), store_db_path=paths.store_db_path(store_dir)
        )
        if connection is not None:
            connection.sock.close()
            if connection.health.model_loaded:
                return
        time.sleep(0.5)
    message = "the service did not come up"
    raise SystemExit(message)


def main() -> None:
    project = Path(sys.argv[1]).expanduser().resolve()
    largest = Path(sys.argv[2]).expanduser().read_bytes()
    rounds = int(sys.argv[3])
    store_dir = paths.store_dir(project)
    session = str(uuid.uuid4())
    # The whole environment, as a harness gives a hook: the socket's path follows the runtime
    # directory, so a hook without `XDG_RUNTIME_DIR` looks for another service than this one polls.
    env = {
        **os.environ,
        "CLAUDECODE": "1",
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_CODE_SESSION_ID": session,
    }
    with tempfile.TemporaryDirectory() as scratch:
        session_transcript = Path(scratch) / f"{session}.jsonl"
        session_transcript.write_text("", encoding="utf-8")
        _agent(session_transcript, "large", largest)
        _agent(session_transcript, "short", b"")
        warm = {"hook_event_name": "UserPromptSubmit", "session_id": session, "cwd": str(project)}
        warm["prompt"] = "warm up"
        subprocess.run([str(HOOK)], input=json.dumps(warm).encode(), env=env, check=False)  # noqa: S603
        _wait_until_serving(store_dir, timeout=180)
        gate = ["/bin/sh", "-c", instruction_gate_command(HOOK, CLAUDE_CODE)]
        marked = {
            f"marker, {len(largest):,}-byte transcript": "large",
            "marker, 4-record transcript": "short",
        }
        if "short-first" in sys.argv:
            marked = dict(reversed(marked.items()))
        arms = {**marked, "another agent's marker pending": OTHER, "no marker": None}
        times: dict[str, list[float]] = {name: [] for name in arms}
        printed = dict.fromkeys(arms, 0)
        for _ in range(rounds):
            for name, agent_id in arms.items():
                payload = {
                    "hook_event_name": "PreToolUse",
                    "session_id": session,
                    "agent_id": "none" if agent_id in (None, OTHER) else agent_id,
                    "agent_type": "general-purpose",
                    "cwd": str(project),
                    "transcript_path": str(session_transcript),
                    "tool_name": "Bash",
                    "tool_input": {"command": "true"},
                }
                if agent_id is not None:
                    instruction_markers.mark(store_dir, f"{session}.{agent_id}")
                started = time.perf_counter()
                result = subprocess.run(  # noqa: S603
                    gate,
                    input=json.dumps(payload).encode(),
                    env=env,
                    capture_output=True,
                    check=True,
                )
                times[name].append((time.perf_counter() - started) * 1000)
                printed[name] += bool(result.stdout)
                if agent_id == OTHER:
                    instruction_markers.claim(store_dir, f"{session}.{OTHER}")
        for name, samples in times.items():
            ordered = sorted(samples)
            p90 = ordered[int(0.9 * (len(ordered) - 1))]
            print(
                f"{name:<34} median {statistics.median(samples):7.2f} ms  p90 {p90:7.2f}  "
                f"max {max(samples):7.2f}  n={len(samples)}  printed={printed[name]}"
            )
        push = CLAUDE_CODE.instruction_push
        assert push is not None
        for agent_id in ("large", "short"):
            transcript = push.agent_file(session_transcript, agent_id, push.transcript_suffix)
            samples = []
            for _ in range(300):
                started = time.perf_counter()
                instruction.latest(transcript, push, main_shaped=False)
                samples.append((time.perf_counter() - started) * 1000)
            print(f"the reader alone, {agent_id}: median {statistics.median(samples):.3f} ms")
        print(f"load average at end: {os.getloadavg()}")


if __name__ == "__main__":
    main()
