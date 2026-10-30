#!/usr/bin/env python3
"""Throwaway kiro V3 hook probe, round 2: log what a hook receives, then answer by its label.

argv[1] is `<agent>-<role>`. Every call appends one JSON line to $PROBE_LOG. The role decides the
answer: `pre-shell` blocks on BLOCKME-SHORT / BLOCKME-LONG (exit 2, stderr); `post` answers on
stderr with a non-zero exit, one canary per tool kind; `pfc` prints a stdout canary; `pfs` a stderr
one with exit 1; `spawn` the old stdout canary; anything else only logs.
"""

import json
import os
import sys
import time

LOG = os.environ["PROBE_LOG"]
LONG_BODY = 5_000


def post_answer(raw: str, tool: str) -> tuple[str, int] | None:
    if "POSTERR1" in raw:
        return "The secret post-error-one word is UMBER-FINCH.", 1
    if "POSTERR2" in raw:
        return "The secret post-error-two word is VERMILION-KITE.", 2
    if tool in ("fs_write", "fs_append", "str_replace"):
        return "The secret re-read word is INDIGO-WREN.", 1
    if tool in ("grep_search", "file_search"):
        return "The secret grep word is TAUPE-GECKO.", 1
    if tool.startswith("mcp_"):
        return "The secret search word is OCHRE-STOAT.", 1
    return None


def main() -> int:
    label = sys.argv[1]
    role = label.split("-", 1)[1] if "-" in label else label
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        payload = {"_unparsed": raw[:4000]}
    tool = payload.get("tool_name", "") if isinstance(payload, dict) else ""
    record = {
        "at": time.strftime("%H:%M:%S"),
        "label": label,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "payload": payload,
        "KIRO_SESSION_ID": os.environ.get("KIRO_SESSION_ID"),
    }
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")

    if role == "spawn":
        sys.stdout.write("The secret spawn word is MAGENTA-OTTER.\n")
        return 0
    if role == "pre-shell":
        if "BLOCKME-SHORT" in raw:
            sys.stderr.write(
                "PROBE-BLOCK-SHORT: refused because the command holds the block word.\n"
            )
            return 2
        if "BLOCKME-LONG" in raw:
            body = "PRE-HEAD-ONYX " + "y" * (LONG_BODY - 28) + " PRE-TAIL-JADE"
            sys.stderr.write(body)
            return 2
        if "ACKME" in raw:
            sys.stdout.write("The secret pre-tool word is CERISE-MOLE.\n")
            return 0
        if "CRASHME" in raw:
            sys.stderr.write("The secret crash word is SLATE-HARE.\n")
            return 1
        return 0
    if role == "post":
        answer = post_answer(raw, tool)
        if answer is None:
            return 0
        text, code = answer
        sys.stderr.write(text + "\n")
        return code
    if role == "pfc":
        sys.stdout.write("The secret file-create word is PEWTER-IBIS.\n")
        return 0
    if role == "pfs":
        sys.stderr.write("The secret file-save word is RUSSET-NEWT.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
