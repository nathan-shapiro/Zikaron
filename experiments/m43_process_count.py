"""M43 done-when 3, middle part: the processes each new hook entry started in done-when 2's sessions,
against the tool calls and turns they made, replayed from each run's `hooks.jsonl`.

The kit's logging hook (`experiments/m43_live_run.py`) recorded every event the new entries run on.
Replayed in its order, a marker is set by a first-start `SessionStart`, an agent's `SubagentStart` and
an id-less `TeammateIdle`, claimed by its own agent's `PreToolUse` and cleared by its `SubagentStop`;
a gated entry's shell starts `zikaron-hook` where any marker of the event's session is pending, the
gate's own glob. So the `zikaron-hook` counts are what the gate does on the logged order — the logger
runs beside Zikaron's hook, not after it — and the TTL sweeps, which no run reached, are left out.
Results: `research/teammate-hook-probe.md` §"Processes per tool call and turn".

    .venv/bin/python experiments/m43_process_count.py DIR...
"""

import json
import sys
from pathlib import Path


def _replay(records: list[dict[str, object]]) -> dict[str, int]:
    markers: set[str] = set()
    counts = dict.fromkeys(
        (
            "tool calls",
            "PreToolUse zikaron-hook",
            "SubagentStop shells",
            "SubagentStop zikaron-hook",
            "TeammateIdle zikaron-hook",
            "agent turns",
        ),
        0,
    )
    for record in records:
        event, session, agent = record["event"], str(record["session_id"]), record["agent_id"]
        own = f"{session}.{agent}" if agent else session
        gate_opens = any(marker.startswith(session) for marker in markers)
        if event == "SessionStart" and record["source"] == "startup":
            markers.add(session)
        elif event == "SubagentStart" and agent:
            markers.add(own)
        elif event == "TeammateIdle":
            counts["TeammateIdle zikaron-hook"] += 1
            if not agent:
                markers.add(session)
                counts["agent turns"] += 1
        elif event == "PreToolUse":
            counts["tool calls"] += 1
            counts["PreToolUse zikaron-hook"] += gate_opens
            markers.discard(own)
        elif event == "SubagentStop":
            counts["SubagentStop shells"] += 1
            counts["SubagentStop zikaron-hook"] += gate_opens
            counts["agent turns"] += bool(agent)
            if agent:
                markers.discard(own)
    return counts


def main() -> None:
    for directory in sys.argv[1:]:
        log = Path(directory).expanduser() / "hooks.jsonl"
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        counts = _replay(records)
        print(Path(directory).name)
        for name, value in counts.items():
            print(f"  {name:<26} {value}")


if __name__ == "__main__":
    main()
