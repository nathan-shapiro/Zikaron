#!/usr/bin/env python3
"""Throwaway kiro V3 hook probe: log what a hook receives, print a canary the model can quote back.

argv[1] is the label the config gave this entry (spawn, prompt, pre, post). Each run appends one JSON
line to $PROBE_LOG with the parsed stdin, every KIRO_* variable, USER_PROMPT, pid and cwd.
"""

import json
import os
import sys
import time
import ancestry

LOG = os.environ.get("PROBE_LOG", "/tmp/kiro_v3_probe.jsonl")
CANARY = {
    "spawn": "The secret spawn word is MAGENTA-OTTER.",
    "prompt": "The secret prompt word is COBALT-HERON.",
    "post": "The secret post-tool word is SAFFRON-LYNX.",
}


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        payload = {"_unparsed": raw[:2000]}
    record = {
        "at": time.strftime("%H:%M:%S"),
        "label": label,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "cwd": os.getcwd(),
        "argv": sys.argv,
        "ancestry": ancestry.chain(),
        "payload": payload,
        "kiro_env": {k: v for k, v in sorted(os.environ.items()) if k.startswith("KIRO")},
        "USER_PROMPT": os.environ.get("USER_PROMPT"),
        "CLAUDECODE": os.environ.get("CLAUDECODE"),
    }
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    if label == "pre" and isinstance(payload, dict) and (payload.get("tool_input") or {}).get("seconds") == 7:
        sys.stderr.write("PROBE-BLOCK: the probe refused this call because it contains BLOCKME.\n")
        return 2
    if label in CANARY:
        sys.stdout.write(CANARY[label] + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
