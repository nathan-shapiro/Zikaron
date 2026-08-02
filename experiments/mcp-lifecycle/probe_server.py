#!/usr/bin/env python3
"""A throwaway MCP server whose only job is to record its own lifecycle.

The question it answers: when a kiro session's **primary** agent already has an MCP server running and
it then spawns a **subagent** whose config names that *same* server, does kiro start a second server
process or reuse the first?

Everything Zikaron's consolidation lease rests on depends on the answer. `(session_id, pid)` ownership
can only distinguish two workers if they are two processes; `read_receipt.client_kind` can only be a
per-process fact if each agent's config launches its own instance; and the takeover bridge — at most one
*successful* `plan_groups` per client process — only converts a human retry into a takeover if a retry
means a fresh process.

It appends one JSONL record per event to `$PROBE_LOG`, never truncating, so several server instances
writing concurrently still interleave rather than clobber. Each record carries the pid, the parent pid,
the full argv, the cwd, `KIRO_SESSION_ID`, every other `KIRO_*` variable, and — for a request — the
method and id. The one tool it exposes echoes the server's own pid back to the model, so the *agent's*
view and the *process's* view can be compared rather than assumed to agree.

Speaks the minimum of MCP over stdio: `initialize`, `tools/list`, `tools/call`, and it answers
`notifications/*` with nothing, since notifications take no reply.
"""

import json
import os
import sys
import time
from typing import Any

LOG = os.environ.get("PROBE_LOG", "/tmp/mcp_probe.jsonl")
LABEL = os.environ.get("PROBE_LABEL", "unlabelled")
PROTOCOL = "2024-11-05"


def record(event: str, **extra: Any) -> None:
    """Append one event. Opened per write and line-buffered, so a second instance cannot truncate it."""
    entry: dict[str, Any] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "monotonic": round(time.monotonic(), 6),
        "event": event,
        "label": LABEL,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "KIRO_SESSION_ID": os.environ.get("KIRO_SESSION_ID"),
        "kiro_env": {k: v for k, v in sorted(os.environ.items()) if k.startswith("KIRO_")},
        **extra,
    }
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


def send(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main() -> None:
    record("startup")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            record("unparseable", raw=line[:400])
            continue
        method = message.get("method")
        request_id = message.get("id")
        record("request", method=method, request_id=request_id)

        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": PROTOCOL,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "probe", "version": "0.0.0"},
                    },
                }
            )
        elif method == "tools/list":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "probe_ping",
                                "description": (
                                    "Return this MCP server process's own pid and session id. "
                                    "Call it once and report the exact text back."
                                ),
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "caller": {
                                            "type": "string",
                                            "description": "Who is calling: 'parent' or 'child-N'.",
                                        }
                                    },
                                    "required": ["caller"],
                                },
                            }
                        ]
                    },
                }
            )
        elif method == "tools/call":
            params = message.get("params") or {}
            caller = (params.get("arguments") or {}).get("caller", "unstated")
            record("tool_call", caller=caller, tool=params.get("name"))
            answer = (
                f"server_pid={os.getpid()} ppid={os.getppid()} "
                f"kiro_session_id={os.environ.get('KIRO_SESSION_ID')} caller={caller}"
            )
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": answer}], "isError": False},
                }
            )
        elif request_id is not None:
            send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    record("stdin_closed")


if __name__ == "__main__":
    main()
